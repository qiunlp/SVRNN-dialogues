# TSAN-Dialogues

All configuration is in `params.py`. You should change `use_cuda=True` if you want to use GPU.

## Install Requirements

```bash
make install
```

## Dataset

### SimDial

Simulated dialogs in JSON are generated with code [here](https://github.com/snakeztc/SimDial).
Generate samepls and interpretion by running

```bash
cd data/simdial/
python read_simdial.py
```

### Ubuntu Chat Corpus

First download the Ubuntu Chat Corpus from [here](https://daviduthus.org/UCC/).
Then generate samples from the corpus by running

```bash
make dataset data_path=path/to/your/ubuntu/corpus
```


If you want to use GloVe, download it [here](https://nlp.stanford.edu/projects/glove/).

## Train  

```bash
python train_linear_vrnn.py
```

or

```bash
python train_tree_vrnn.py
```

## Decode

```bash
python train_linear_vrnn.py --decode --ckpt_dir run1585003537 --ckpt_name vrnn_5.pt
```

or

```bash
python train_tree_vrnn.py --decode --ckpt_dir run1585003537 --ckpt_name vrnn_5.pt
```

## Interpret

```bash
python interpretion.py --ckpt_dir run1585003537 --ckpt_name vrnn_5.pt
```

## Run all of them

```bash
python train_interpret.py
```

and to view the result

```bash
tensorboard --logdir /log/ckpt_dir/
```

## Model Architecture

![Image 1](imgs/dialog_attn_2.PNG)
