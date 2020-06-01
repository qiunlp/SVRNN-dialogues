"""Global parameters.
"""
max_epoch = 60  # max number of epoch of training
use_cuda = False
gpu_idx = 7
seed = 233
max_vocab_cnt = 500
word2vec_path = None  # The path to word2vec. Can be None.
log_dir = "log"  # Experiment results directory.
use_glove = False
glove_path = "/home/liang/Workspace/Corpus/glove.840B.300d.txt"
use_test_batch = False  # Use test dataset for structure interpretion

# Weather, Restaurant, Simdial
data_dir = "data/simdial/weather-CleanSpec-2000.pkl"  # Raw data directory. options: {bus, movie, restaurant, weather}
api_dir = "data/cambridge_data/api_cambridge.pkl"  # "data/api_simdial_weather.pkl"
rev_vocab_dir = "data/cambridge_data/rev_vocab.pkl"  # "data/weather_rev_vocab.pkl"

# Ubuntu Dialog Corpus
data_pre = "/home/liang/Workspace/Corpus/#ubuntu-2004/"
data_path = data_pre + "train-sample/train-*.json"
eval_data_path = data_pre + "dev-sample/dev-*.json"
test_data_path = data_pre + "test-sample/test-*.json"
vocab_path = data_pre + "vocab"
mode = "train"  # train, eval, decode

# tree_vae config
max_enc_steps = 50
max_dec_steps = 50
print_after = 10
n_training_steps = 100
eval_num = 100  # number of samples to evaluate

# linear_vae config
n_state = 10  # Number of states.with open(FLAGS.result_path, "w") as fh:
temperature = 0.5  # temperature for gumbel softmax

# Network general
cell_type = "lstm"  # gru or lstm
encoding_cell_size = 400  # size of the rnn
state_cell_size = n_state
embed_size = 300  # word embedding size
max_utt_len = 40  # max number of words in an utterance
max_dialog_len = 13  # max number of turns in a dialog
num_layer = 1  # number of context RNN layers
use_struct_attention = True
attention_type = "concat"  #dot, general, concat

# Optimization parameters
op = "adam"  # adam, rmsprop, sgd
grad_clip = 5.0  # gradient abs max cut
init_w = 0.08  # uniform random from [-init_w, init_w]
batch_size = 40  # mini-batch size
init_lr = 0.001  # initial learning rate
lr_decay = 0.6
dropout = 0.2  # drop out rate
improve_threshold = 0.996  # for early stopping
patient_increase = 2.0  # for early stopping
early_stop = True
grad_noise = 0.0  # inject gradient noise?

with_BOW = True
kl_loss_weight = 1  # weight of the kl_loss
bow_loss_weight = 0.5  # weight of the bow_loss
with_label_loss = False  # semi-supervised or not
with_BPR = True
with_direct_transition = False  # direct prior transition prob
with_word_weights = False

if with_word_weights:
    with open(rev_vocab_dir, "r") as fh:
        rev_vocab = pkl.load(fh)

    slot_value_id_list = []
    for k, v in rev_vocab.items():
        # print(type(k))
        if ("slot_" in k) or ("value_" in k):
            #print(k)
            slot_value_id_list.append(v)

    multiply_factor = 3
    one_weight = 1.0 / (len(rev_vocab) +
                        (multiply_factor - 1) * len(slot_value_id_list))
    word_weights = [one_weight] * len(rev_vocab)
    for i in slot_value_id_list:
        word_weights[i] = multiply_factor * word_weights[i]

    sum_word_weights = np.sum(word_weights)
    # print(sum_word_weights)
    # print(type(sum_word_weights))
    assert (sum_word_weights == float(1.0))
    word_weights = list(len(rev_vocab) * np.array(word_weights))

else:
    word_weights = None
