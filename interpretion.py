import argparse
from collections import Counter
import os
import sys

import pickle as pkl
import numpy as np
import torch
import networkx as nx
from beeprint import pp
import matplotlib.pyplot as plt
from torch.utils.tensorboard import SummaryWriter

import params
from models.linear_vrnn import LinearVRNN
from data_apis.SWDADialogCorpus import SWDADialogCorpus
from utils.draw_struct import draw_networkx_nodes_ellipses


def softmax(x):
    """Compute softmax values for each sets of scores in x."""
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum(axis=0)  # only difference


def id_to_sent(id_to_vocab, ids):
    sent = []
    for id in ids:
        if id:
            if id_to_vocab[id] != '<s>' and id_to_vocab[id] != '</s>':
                sent.append(id_to_vocab[id])
        else:
            break
    return " ".join(sent)


def id_to_probs(probs, ids, id_to_vocab, SOFTMAX=False):
    if SOFTMAX:
        probs = softmax(probs)
    else:
        pass

    product = 1
    for id in ids:
        if id_to_vocab[id] == '</s>':
            break
        elif id_to_vocab[id] == '<s>':
            pass
        elif id:
            product *= probs[id]
        else:
            print("")
            raise Exception("id is empty!")
    return product


def id_to_log_probs(probs, ids, id_to_vocab, SOFTMAX=False):
    if SOFTMAX:
        probs = softmax(probs)
    else:
        pass

    sum = 0
    for id in ids:
        if id_to_vocab[id] == '</s>':
            break
        elif id_to_vocab[id] == '<s>':
            pass
        elif id:
            sum += np.log(probs[id])
        else:
            print("")
            raise Exception("id is empty!")
    return sum


def get_state_sents(state,
                    converted_sents,
                    converted_labels,
                    last_n=3,
                    sys_side=1):
    state_sents = []
    for i in range(len(converted_sents)):
        for j, label in enumerate(converted_labels[i]):
            if label == state:
                if converted_sents[i][j][sys_side]:
                    last_n_sents = [
                        converted_sents[i][j - i_last_n][sys_side]
                        for i_last_n in range(last_n) if (j - i_last_n) >= 0
                    ]
                    last_n_sents = last_n_sents[::-1]
                    last_n_sents = "\n ".join(last_n_sents)

                    state_sents.append(last_n_sents)
    return state_sents


def main(args):
    parser = argparse.ArgumentParser()

    parser.add_argument('--ckpt_dir',
                        type=str,
                        help='Directory of the saved checkpoint')
    parser.add_argument('--ckpt_name',
                        type=str,
                        help='Name of the saved model checkpoint')

    parser.add_argument('--with_start', default=False, type=bool)
    args = parser.parse_args(args)

    with open(params.api_dir, "rb") as fh:
        api2 = pkl.load(fh, encoding='latin1')

    with open(
            os.path.join(params.log_dir, "linear_vrnn", args.ckpt_dir,
                         "result.pkl"), "rb") as fh:
        results = pkl.load(fh)

    state = torch.load(
        os.path.join(params.log_dir, "linear_vrnn", args.ckpt_dir,
                     args.ckpt_name))
    writer = SummaryWriter(
        log_dir=os.path.join(params.log_dir, "linear_vrnn", args.ckpt_dir))
    # pp(state['state_dict'])

    converted_labels = []
    converted_sents = []
    conv_probs = []
    for batch_i in range(len(results)):
        usr_sents = results[batch_i][0]
        sys_sents = results[batch_i][1]
        probs = results[batch_i][2]
        trans_probs = results[batch_i][3]
        bow_logits1 = results[batch_i][4]
        bow_logits2 = results[batch_i][5]
        for i in range(params.batch_size):
            this_dialog_labels = []
            this_dialog_sents = []
            prev_label = -1
            this_conv_prob = 1
            for turn_j in range(params.max_dialog_len):
                if not usr_sents[i, turn_j, 0]:
                    break
                label = probs[i, turn_j].argmax()
                usr_tokens = id_to_sent(api2.id_to_vocab, usr_sents[i, turn_j])
                sys_tokens = id_to_sent(api2.id_to_vocab, sys_sents[i, turn_j])
                usr_prob = id_to_log_probs(bow_logits1[i, turn_j],
                                           usr_sents[i, turn_j],
                                           api2.id_to_vocab,
                                           SOFTMAX=True)
                sys_prob = id_to_log_probs(bow_logits2[i, turn_j],
                                           sys_sents[i, turn_j],
                                           api2.id_to_vocab,
                                           SOFTMAX=True)

                this_dialog_labels += [label]
                this_dialog_sents += [[usr_tokens, sys_tokens]]
                this_turn_prob = usr_prob + sys_prob
                this_conv_prob += this_turn_prob
            # print(this_dialog_sents)
            # print(this_dialog_labels)
            conv_probs.append(this_conv_prob)
            converted_labels.append(this_dialog_labels)
            converted_sents.append(this_dialog_sents)

    sents_by_state = []
    for i in range(params.n_state):
        sents_by_state.append(
            get_state_sents(i,
                            converted_sents,
                            converted_labels,
                            sys_side=0,
                            last_n=1))
    sents_by_state_sys = []
    for i in range(params.n_state):
        sents_by_state_sys.append(
            get_state_sents(i,
                            converted_sents,
                            converted_labels,
                            sys_side=1,
                            last_n=1))

    # TODO: n_state become 11
    if args.with_start:
        sents_by_state = [['START']] + sents_by_state
        sents_by_state_sys = [['START']] + sents_by_state_sys

    transition_count = np.zeros((params.n_state, params.n_state))

    for labels in converted_labels:
        for i in range(len(labels) - 1):
            transition_count[labels[i], labels[i + 1]] += 1

    transition_prob = np.zeros((params.n_state, params.n_state))
    for i in range(params.n_state):
        if transition_count[i].sum() != 0:
            transition_prob[i] = transition_count[i] / transition_count[i].sum(
            )

    # direct transition only, for direct transition, the transition probs are from the fetch_results from the model
    if params.with_direct_transition:
        label_i_list = np.eye(params.n_state, params.n_state)
        label_i_list = np.vstack([[1] * params.n_state, label_i_list])

        w0 = state['state_dict']['vae_cell.transit_mlp._linear.0.weight'].cpu(
        ).detach().numpy()
        b0 = state['state_dict']['vae_cell.transit_mlp._linear.0.bias'].cpu(
        ).detach().numpy()
        w1 = state['state_dict']['vae_cell.transit_mlp._linear.1.weight'].cpu(
        ).detach().numpy()
        b1 = state['state_dict']['vae_cell.transit_mlp._linear.1.bias'].cpu(
        ).detach().numpy()
        w2 = state['state_dict']['vae_cell.transit_fc.weight'].cpu().detach(
        ).numpy()
        b2 = state['state_dict']['vae_cell.transit_fc.bias'].cpu().detach(
        ).numpy()

        prob_list = []
        for i in range(params.n_state + 1):
            tmp_prob = np.matmul(
                w2,
                np.matmul(w1,
                          np.matmul(w0, label_i_list[i]) + b0) + b1) + b2
            prob_list.append(softmax(tmp_prob))

        transition_prob = prob_list

    # print("transition probability:")
    # print(transition_prob)
    # print("\n")

    #  draw the interpretion with networkx and matplotlib
    G = nx.DiGraph()
    node_labels = {}
    stop_words = [
        '[', ']', '.', '?', ',', 'the', 'i', 'you', 'a', 'is', 'and', 'please',
        'that', 'what', 'for', 'to', 'there', 'restaurant'
    ]
    for i in range(params.n_state):
        print("Most common words in state %d" % i)
        # print(Counter(sents_by_state[i]).most_common(5))
        words_by_state = []
        for sent in sents_by_state[i]:
            words = sent.split(" ")
            words = [w for w in words if w not in stop_words]
            words_by_state.extend(words)
        print(Counter(words_by_state).most_common(10))
        G.add_node(i)
        node_labels[i] = Counter(sents_by_state[i]).most_common(1)[0][0]
    edge_labels = {}
    for i in range(params.n_state):
        for j in range(params.n_state):
            if transition_prob[i, j] > 0.13:
                G.add_edge(i, j)
                edge_labels[(i, j)] = "%.2f" % transition_prob[i, j]

    pos = nx.spring_layout(G)
    node_width = [5 * len(node_labels[node]) for node in G.nodes()]
    draw_networkx_nodes_ellipses(G,
                                 pos=pos,
                                 node_width=node_width,
                                 node_height=10,
                                 node_color='w',
                                 edge_color='k',
                                 alpha=1.0)

    nx.draw_networkx_labels(G, pos=pos, labels=node_labels, font_size=7)
    nx.draw_networkx_edges(G, pos=pos, arrows=True)
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7)
    plt.axis('off')
    fig = plt.gcf()
    fig.set_size_inches(8, 8)
    # plt.show()
    writer.add_figure('structure', fig)
    writer.close()


if __name__ == "__main__":
    main(sys.argv[1:])
