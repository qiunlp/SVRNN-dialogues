from __future__ import print_function

import random
import os
import time
import argparse
import sys
import inspect

import pickle as pkl
import torch
from torch import nn, optim
import numpy as np
from beeprint import pp

from models.linear_vrnn import LinearVRNN
from data_apis.data_utils import SWDADataLoader
from data_apis.SWDADialogCorpus import SWDADialogCorpus
from torch.utils.tensorboard import SummaryWriter
from utils.loss import print_loss
import params


def get_dataset(device):
    with open(params.api_dir, "rb") as fh:
        api = pkl.load(fh, encoding='latin1')
    dial_corpus = api.get_dialog_corpus()

    train_dial, labeled_dial, test_dial = dial_corpus.get(
        "train"), dial_corpus.get("labeled"), dial_corpus.get("test")

    # convert to numeric input outputs
    train_loader = SWDADataLoader("Train",
                                  train_dial,
                                  params.max_utt_len,
                                  params.max_dialog_len,
                                  device=device)
    valid_loader = test_loader = SWDADataLoader("Test",
                                                test_dial,
                                                params.max_utt_len,
                                                params.max_dialog_len,
                                                device=device)
    return train_loader, valid_loader, test_loader, np.array(api.word2vec)


def train(model, train_loader, optimizer, writer):
    elbo_t = []
    rc_loss = []
    kl_loss = []
    bow_loss = []
    local_t = 0
    start_time = time.time()
    loss_names = ["elbo_t", "rc_loss", "kl_loss", "bow_loss"]
    model.train()

    while True:
        optimizer.zero_grad()
        batch = train_loader.next_batch()
        if batch is None:
            break
        local_t += 1
        loss = model(*batch)
        # use .data to free the loss Variable
        elbo_t.append(loss[0].data)
        rc_loss.append(loss[1].data)
        kl_loss.append(loss[2].data)
        bow_loss.append(loss[3].data)
        writer.add_scalars(
            'Loss/train', {
                'elbo_t': loss[0].data,
                'rc_loss': loss[1].data,
                'kl_loss': loss[2].data,
                'bow_loss': loss[3].data
            }, local_t)
        loss[0].backward(
        )  # loss[0] = elbo_t = rc_loss + weight_kl * kl_loss + weight_bow * bow_loss
        optimizer.step()

        if local_t % (train_loader.num_batch // 10) == 0:
            print_loss("%.2f" %
                       (train_loader.ptr / float(train_loader.num_batch)),
                       loss_names, [elbo_t, rc_loss, kl_loss, bow_loss],
                       postfix='')
    # finish epoch!
    epoch_time = time.time() - start_time
    print_loss("Epoch Done", loss_names, [elbo_t, rc_loss, kl_loss, bow_loss],
               "step time %.4f" % (epoch_time / train_loader.num_batch))


def valid(model, valid_loader, writer):
    elbo_t = []
    model.eval()
    local_t = 0
    while True:
        batch = valid_loader.next_batch()
        if batch is None:
            break
        local_t += 1
        loss = model(*batch)
        elbo_t.append(loss[0].data)
        writer.add_scalar('Loss/train/elbo_t', loss[0].data, local_t)

    print_loss("Valid", ["elbo_t"], [elbo_t], "")
    return torch.mean(torch.stack(elbo_t))


def decode(model, data_loader):
    results = []
    model.eval()
    while True:
        batch = data_loader.next_batch()
        if batch is None:
            break
        result = model(*batch, training=False)
        results.append(result)
    return results


def main(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--decode',
                        dest='forward_only',
                        action='store_true',
                        help='Decoding mode')
    parser.add_argument('--train',
                        dest='forward_only',
                        action='store_false',
                        help='Training mode')
    parser.set_defaults(forward_only=False)

    parser.add_argument('--resume',
                        dest='resume',
                        action='store_true',
                        help='Resume training from checkpoint')
    parser.add_argument('--no_resume',
                        dest='resume',
                        action='store_false',
                        help='Training from scratch')
    parser.set_defaults(resume=False)

    parser.add_argument(
        '--ckpt_dir',
        default='',
        type=str,
        help='The directory to load the checkpoint, e.g. run1585003537')
    parser.add_argument(
        '--ckpt_name',
        default='',
        type=str,
        help='Name of the saved model checkpoint, e.g. vrnn_60.pt')

    parser.add_argument('--save_model',
                        dest='save_model',
                        action='store_true',
                        help='Saving checkpoints')
    parser.add_argument('--no_save_model',
                        dest='save_model',
                        action='store_false',
                        help='Not saving checkpoints')
    parser.set_defaults(save_model=True)

    args = parser.parse_args(args)
    print(args)
    pp(params)

    # set random seeds
    seed = params.seed
    random.seed(seed)
    np.random.seed(seed + 1)
    torch.manual_seed(seed + 2)

    print("Available GPUs: %d" % torch.cuda.device_count())
    sys.stdout.flush()
    use_cuda = params.use_cuda and torch.cuda.is_available()
    if use_cuda:
        assert params.gpu_idx < torch.cuda.device_count(
        ), "params.gpu_idx must be one of the available GPUs"
        device = torch.device("cuda:" + str(params.gpu_idx))
        torch.cuda.set_device(device)
        print("Using GPU: %d" % torch.cuda.current_device())
        sys.stdout.flush()
    else:
        device = torch.device("cpu")
        print("Using CPU for training, you poor kid :)")

    train_loader, valid_loader, test_loader, word2vec = get_dataset(device)

    if args.forward_only or args.resume:
        log_dir = os.path.join(params.log_dir, "linear_vrnn", args.ckpt_dir)
        checkpoint_path = os.path.join(log_dir, args.ckpt_name)
    else:
        ckpt_dir = "run" + str(int(time.time()))
        log_dir = os.path.join(params.log_dir, "linear_vrnn", ckpt_dir)
    os.makedirs(log_dir, exist_ok=True)
    print("Writing logs to %s" % log_dir)
    writer = SummaryWriter(log_dir=log_dir)

    model = LinearVRNN().to(device)
    if params.op == "adam":
        optimizer = optim.Adam(model.parameters(),
                               lr=params.init_lr,
                               weight_decay=params.lr_decay)
    elif params.op == "rmsprop":
        optimizer = optim.RMSprop(model.parameters(),
                                  lr=params.init_lr,
                                  weight_decay=params.lr_decay)
    else:
        optimizer = optim.SGD(model.parameters(),
                              lr=params.init_lr,
                              weight_decay=params.lr_decay)

    if word2vec is not None and not args.forward_only:
        print("Load word2vec")
        sys.stdout.flush()
        model.embedding.from_pretrained(torch.from_numpy(word2vec),
                                        freeze=False)

    # # write config to a file for logging
    # if not args.forward_only:
    #     with open(os.path.join(log_dir, "run.log"), "w") as f:
    #         f.write(pp(params, output=False))
    variables = dir(params)
    param_vars = []
    for var in variables:
        if not var.startswith("_"):
            param_vars.append(var)
    params_dict = {
        var: getattr(params, var)
        for var in param_vars if getattr(params, var) != None
    }
    writer.add_hparams(params_dict, {"NA": 0})

    writer.add_text('Hyperparameters', pp(params, output=False))

    last_epoch = 0
    if args.resume:
        print("Resuming training from %s" % checkpoint_path)
        sys.stdout.flush()
        state = torch.load(checkpoint_path)
        model.load_state_dict(state['state_dict'])
        optimizer.load_state_dict(state['optimizer'])
        last_epoch = state['epoch']

    # Train and evaluate
    patience = params.max_epoch
    dev_loss_threshold = np.inf
    best_dev_loss = np.inf
    if not args.forward_only:
        start = time.time()
        for epoch in range(last_epoch + 1, params.max_epoch + 1):
            print(">> Epoch %d" % (epoch))
            sys.stdout.flush()
            for param_group in optimizer.param_groups:
                print("Learning rate %f" % param_group['lr'])
                sys.stdout.flush()

            if train_loader.num_batch is None or train_loader.ptr >= train_loader.num_batch:
                train_loader.epoch_init(params.batch_size, shuffle=True)
            train(model, train_loader, optimizer, writer)

            print("Best valid loss before this validation: %f" % best_dev_loss)
            sys.stdout.flush()
            valid_loader.epoch_init(params.batch_size, shuffle=False)
            valid_loss = valid(model, valid_loader, writer)
            if valid_loss < best_dev_loss:
                print("Get a smaller valid loss, update the best valid loss")
                sys.stdout.flush()
                best_dev_loss = valid_loss
                # increase patience when valid_loss is small enough
                if valid_loss <= dev_loss_threshold * params.improve_threshold:
                    patience = max(patience, epoch * params.patient_increase)
                    dev_loss_threshold = valid_loss

                # still save the best train model
                if args.save_model:
                    print("Saving the model")
                    sys.stdout.flush()
                    state = {
                        'epoch': epoch,
                        'state_dict': model.state_dict(),
                        'optimizer': optimizer.state_dict(),
                    }
                    ckpt_name = "vrnn_" + str(epoch) + ".pt"
                    torch.save(state, os.path.join(log_dir, ckpt_name))
            if params.early_stop and patience <= epoch:
                print("Early stop due to run out of patience!!")
                sys.stdout.flush()
                break
        print("Total training time: %.2f" % float(time.time() - start) / 60.00)
        return ckpt_dir, ckpt_name
    # Inference only
    else:
        state = torch.load(checkpoint_path)
        print("Load model from %s" % checkpoint_path)
        sys.stdout.flush()
        model.load_state_dict(state['state_dict'])
        if not params.use_test_batch:
            train_loader.epoch_init(params.batch_size, shuffle=False)
            results = decode(model, train_loader)
        else:
            test_loader.epoch_init(params.batch_size, shuffle=False)
            results = decode(
                model, test_loader
            )  # [num_batches(8), 4, batch_size(16), max_dialog_len(10), n_state(10)]
        with open(os.path.join(log_dir, "result.pkl"), "wb") as fh:
            pkl.dump(results, fh)


if __name__ == "__main__":
    main(sys.argv[1:])
