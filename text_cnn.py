#!/usr/bin/python3.6
# -*- coding: utf-8 -*-


import tensorflow as tf
import numpy as np

class ModelConfig(object):
    """
    textcnn model
    """

    def __init__(self, embedding_dim=128, filter_sizes="3,4,5", num_filters=128, dropout_rate=0.5,
                 l2_reg_lambda=0.0, max_seq_length=128, vocab_size=8192, label_size=64):
        self.embedding_dim = embedding_dim
        # "3,4,5" => list(3,4,5)
        self.filter_sizes = list(map(lambda x: int(x), filter_sizes.split(",")))
        self.num_filters = num_filters
        self.dropout_rate = dropout_rate
        self.l2_reg_lambda = l2_reg_lambda
        self.max_seq_length = max_seq_length
        self.vocab_size = vocab_size
        self.label_size = label_size

    def to_string(self):
        lines = [
            "embedding_dim = {:d}".format(self.embedding_dim),
            "filter_sizes = {}".format(self.filter_sizes),
            "num_filters = {:d}".format(self.num_filters),
            "dropout_rate = {:g}".format(self.dropout_rate),
            "l2_reg_lambda = {:g}".format(self.l2_reg_lambda),
            "max_seq_length = {:d}".format(self.max_seq_length),
            "vocab_size = {:d}".format(self.vocab_size),
            "label_size = {:d}".format(self.label_size)
        ]
        return "\n".join(lines)


class TextCNNModel(object):
    def __init__(self,
                 config,
                 is_training):
        self._config = config
        tf.logging.info("\n ******TextCNN MODEL CONFIG*******")
        tf.logging.info(self._config.to_string())

        tf.logging.info("\n ******Shape of MODEL VARS********")
        self.input_x = tf.placeholder(tf.int32, [None, self._config.max_seq_length], name="input_x") # (batch_size,max_seq_length)
        self.input_y = tf.placeholder(tf.float32, [None, self._config.label_size], name="input_y") # (batch_size,2)
        tf.logging.info("num_class {}".format(str(self.input_y.shape)))
        tf.logging.info("is_trainging :{}".format(str(is_training)))
        l2_loss = tf.constant(0.0)

        # embedding layer
        with tf.name_scope("embedding"):
            self.W = tf.Variable(tf.random_uniform([self._config.vocab_size, self._config.embedding_dim], -1.0, 1.0),
                                 name="W")  # (vocab_size,embedding_dim)
            self.char_emb = tf.nn.embedding_lookup(self.W, self.input_x)  #  (batch_size,max_seq_length,embedding_dim)
            self.char_emb_expanded = tf.expand_dims(self.char_emb, -1)  #  (batch_size,max_seq_length,embedding_dim,1)
            tf.logging.info("Shape of embedding_chars:{}".format(str(self.char_emb_expanded.shape)))

        # convolution + pooling layer
        pooled_outputs = []
        for i, filter_size in enumerate(self._config.filter_sizes):   #filter_sizes=[2,3,5]
            with tf.variable_scope("conv-maxpool-%s" % filter_size):
                # convolution layer
                filter_width = self._config.embedding_dim # 卷积核的宽
                input_channel_num = 1
                output_channel_num = self._config.num_filters
                filter_shape = [filter_size, filter_width, input_channel_num, output_channel_num]

                n = filter_size * filter_width * input_channel_num
                kernal = tf.get_variable(name="kernal",
                                         shape=filter_shape,
                                         dtype=tf.float32,
                                         initializer=tf.random_normal_initializer(stddev=np.sqrt(2.0 / n)))
                bias = tf.get_variable(name="bias",
                                       shape=[output_channel_num],
                                       dtype=tf.float32,
                                       initializer=tf.zeros_initializer)
                # apply convolution process
                # conv shape: [batch_size, max_seq_len - filter_size + 1, 1, output_channel_num]
                conv = tf.nn.conv2d(
                    input=self.char_emb_expanded,
                    filter=kernal,
                    strides=[1, 1, 1, 1],
                    padding="VALID",
                    name="cov")
                tf.logging.info("Shape of Conv:{0}=={1}".format(i, str(conv.shape)))

                # apply non-linerity
                h = tf.nn.relu(tf.nn.bias_add(conv, bias), name="relu")
                tf.logging.info("Shape of h:{}".format(str(h)))

                # Maxpooling over the outputs
                pooled = tf.nn.max_pool(
                    value=h,
                    ksize=[1, self._config.max_seq_length - filter_size + 1, 1, 1],  # 需计算cnn输出的大小
                    strides=[1, 1, 1, 1],
                    padding="VALID",
                    name="pool"
                )
                tf.logging.info("Shape of pooled:{0}=={1}".format(i, str(pooled.shape)))
                pooled_outputs.append(pooled)
                # tf.logging.info("Shape of pooled_outputs:{}".format(str(np.array(pooled_outputs).shape)))

        # concatenate all filter's output
        total_filter_num = self._config.num_filters * len(self._config.filter_sizes)
        all_features = tf.reshape(tf.concat(pooled_outputs, axis=-1), [-1, total_filter_num]) #[batch_size, total_filter_num]
        tf.logging.info("Shape of all_features:{}".format(str(all_features.shape)))

        # apply dropout during training
        if is_training:
            all_features = tf.nn.dropout(all_features, rate=self._config.dropout_rate)

        with tf.name_scope("output"):
            output_dense_layer = tf.layers.Dense(self._config.label_size, use_bias=True, name="output_layer")
            logits = output_dense_layer(all_features)
            tf.logging.info("Shape of logits:{}".format(str(logits.shape)))
            self.predictions = tf.nn.softmax(logits, name="predictions")
            tf.logging.info("Shape of predictions:{}".format(str(self.predictions.shape)))
            W = tf.get_variable(
                name="W",
                shape=[total_filter_num, self._config.label_size],
                initializer=tf.contrib.layers.xavier_initializer())
            b = tf.Variable(tf.constant(0.1, shape=[self._config.label_size]), name="b")
            l2_loss += tf.nn.l2_loss(W) #L2惩罚项
            l2_loss += tf.nn.l2_loss(b) #L2惩罚项
            self.scores = tf.nn.xw_plus_b(all_features, W, b, name="scores") #Computes matmul(x, weights) + biases. [batch_size,2]
            self.predictions = tf.argmax(self.scores, 1, name="predictions") #第二维度 返回最大的那个数值所在的下标

        # compute loss
        with tf.name_scope("loss"):
            losses = tf.nn.softmax_cross_entropy_with_logits(logits=self.scores, labels=self.input_y)
            self.loss = tf.reduce_mean(losses) + self._config.l2_reg_lambda * l2_loss  #L2惩罚项

        #compute accuracy meric
        with tf.name_scope("accuracy"):
            self.accuracy = self._accuracy_op(self.predictions, self.input_y)

        # Accuracy
        with tf.name_scope("accuracy"):
            correct_predictions = tf.equal(self.predictions, tf.argmax(self.input_y, 1))
            self.accuracy = tf.reduce_mean(tf.cast(correct_predictions, "float"), name="accuracy")

    def _accuracy_op(self, predictions, labels):
        return tf.metrics.accuracy(labels=tf.argmax(self.input_y, axis=-1),
                                   predictions=tf.argmax(predictions,axis=-1))
