import sys

import torch
import torch.nn as nn
import torch.nn.functional as F

from .sequential import MLP
sys.path.append("..")
from utils.sample import gumbel_softmax
from models.attention_module import Attn
import params


class TreeVAECell(nn.Module):
    def __init__(self, state_is_tuple=True):
        super(TreeVAECell, self).__init__()

        self._state_is_tuple = state_is_tuple
        # temperature of gumbel_softmax
        self.tau = nn.Parameter(torch.tensor([5.0]))

        self.enc_mlp = MLP(params.sen_hidden_dim + params.state_cell_size,
                           [400, 200],
                           dropout_rate=params.dropout)
        self.enc_fc = nn.Linear(200, params.n_state)
        self.dec_mlp = MLP(params.n_state, [200, 200],
                           dropout_rate=params.dropout)

        self.dec_rnn = nn.LSTM(params.embed_size,
                               200 + params.n_state,
                               1,
                               batch_first=True)
        self.dec_fc = nn.Linear(200 + params.n_state, params.max_vocab_cnt)

        self.bow_fc = nn.Linear(params.state_cell_size + 200, 400)
        self.bow_project = nn.Linear(400, params.max_vocab_cnt)

        if params.with_direct_transition:
            self.transit_mlp = MLP(params.n_state, [100, 100],
                                   dropout_rate=params.dropout)
        else:
            self.transit_mlp = MLP(params.state_cell_size, [100, 100],
                                   dropout_rate=params.dropout)
        self.transit_fc = nn.Linear(100, params.n_state)

        if params.cell_type == "gru":
            self.state_rnn = nn.GRUCell(params.sen_hidden_dim + 200,
                                        params.state_cell_size)
        else:
            self.state_rnn = nn.LSTMCell(params.sen_hidden_dim + 200,
                                         params.state_cell_size)
        if params.dropout not in (None, 0):
            self.dropout = nn.Dropout(params.dropout)

        # attention
        if params.use_sentence_attention:
            self.attn = Attn(params.attention_type, params.sen_hidden_dim)

    def encode(self, inputs, h_prev):
        enc_inputs = torch.cat([h_prev, inputs],
                               1)  # [batch, sen_hidden_dim + state_cell_size]
        net1 = self.enc_mlp(enc_inputs)
        logits_z = self.enc_fc(net1)
        q_z = F.softmax(logits_z, dim=1)
        log_q_z = F.log_softmax(logits_z, dim=1)

        return logits_z, q_z, log_q_z

    def context_encode(self, inputs, h_prev, prev_embeddings):
        '''
        :param inputs: sentence encoding for current dialogue index(utt) [batch, encoding_cell_size * 2]
        :param h_prev: previous h state from LSTM [batch, state_cell_size]
        :param prev_embeddings: previous sentence embeddings [batch, current_utt_index - 1, encoding_cell_size * 2]
        :return: hidden_state from vae [batch x n_state]
        '''
        attn_weights = self.attn(inputs, prev_embeddings)
        context = attn_weights.bmm(prev_embeddings).squeeze(1)
        enc_inputs = torch.cat([h_prev, context],
                               1)  # [batch, sen_hidden_dim + state_cell_size]

        net1 = self.enc_mlp(enc_inputs)
        logits_z = self.enc_fc(net1)
        q_z = F.softmax(logits_z, dim=1)
        log_q_z = F.log_softmax(logits_z, dim=1)

        return logits_z, q_z, log_q_z

    def decode(self,
               z_samples,
               h_prev,
               dec_input_embedding,
               z_samples_context=None):
        net2 = self.dec_mlp(z_samples)  # [batch, 200]
        # decoder for user utterance
        dec_input = torch.unsqueeze(
            torch.cat([h_prev, net2], dim=1),
            dim=0)  # [num_layer(1), batch, state_cell_size + 200]

        # decoder from context
        if params.use_sentence_attention:
            net2_context = self.dec_mlp(z_samples_context)  # [batch, 200]
            dec_input_context = torch.unsqueeze(
                torch.cat([h_prev, net2_context], dim=1),
                dim=0)  # [num_layer(1), batch, state_cell_size + 200]
        else:
            dec_input_context = dec_input

        dec_outs, final_state = self.dec_rnn(dec_input_embedding,
                                             (dec_input, dec_input_context))

        if params.dropout not in (None, 0):
            dec_outs = self.dropout(dec_outs)
        dec_outs = self.dec_fc(dec_outs)

        # for computing BOW loss
        bow_logits = None
        if params.with_BOW:
            bow_fc = self.bow_fc(torch.squeeze(dec_input, dim=0))
            bow_fc = torch.tanh(bow_fc)
            if params.dropout not in (None, 0):
                bow_fc = self.dropout(bow_fc)
            bow_logits = self.bow_project(bow_fc)  # [batch_size, vocab_size]

        return dec_outs, bow_logits

    def forward(self, inputs, state, prev_z_t=None, prev_embeddings=None):
        if params.with_direct_transition:
            assert prev_z_t is not None
        if self._state_is_tuple:
            (h_prev, _) = state
        else:
            h_prev = state
        # encode
        logits_z, q_z, log_q_z = self.encode(inputs, h_prev)

        # sample
        z_samples, logits_z_samples = gumbel_softmax(
            logits_z, self.tau, hard=False)  # [batch, n_state]

        #encode from context
        if params.use_sentence_attention:
            logits_z_context, q_z_context, log_q_z_context = self.context_encode(
                inputs, h_prev, prev_embeddings)

            #sample from context
            z_samples_context, logits_z_samples_context = gumbel_softmax(
                logits_z_context, self.tau, hard=False)  # [batch, n_state]
        else:
            z_samples_context = None

        net2 = self.dec_mlp(z_samples)  # [batch, 200]

        if params.with_direct_transition:
            net3 = self.transit_mlp(prev_z_t)
            p_z = self.transit_fc(net3)
            p_z = F.softmax(p_z, dim=1)
            log_p_z = torch.log(p_z + 1e-20)

        else:
            net3 = self.transit_mlp(h_prev)
            p_z = self.transit_fc(net3)
            p_z = F.softmax(p_z, dim=1)
            log_p_z = torch.log(p_z + 1e-20)

        recur_input = torch.cat([net2, inputs],
                                dim=1)  # [batch, sen_hidden_dim + 200]
        next_state = self.state_rnn(recur_input, state)

        return z_samples, z_samples_context, next_state, p_z, q_z, log_p_z, log_q_z
