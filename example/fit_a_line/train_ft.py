#   Copyright (c) 2018 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import math
import pickle
import glob
import os
import sys
import paddle.v2 as paddle
import paddle.v2.dataset.common as common
from paddle.reader.creator import cloud_reader

embsize = 32
hiddensize = 256
N = 5

# NOTE: You need to generate and split dataset then put it under your cloud storage.
#       then you can use different size of embedding.

TRAIN_FILES_PATH = "/data/recordio/imikolov-train-*"

TRAINER_ID = int(os.getenv("PADDLE_INIT_TRAINER_ID", "-1"))
TRAINER_COUNT = int(os.getenv("PADDLE_INIT_NUM_GRADIENT_SERVERS", "-1"))

etcd_ip = os.getenv("ETCD_IP")
etcd_endpoint = "http://" + etcd_ip + ":" + "2379"
trainer_id = int(os.getenv("PADDLE_INIT_TRAINER_ID", "-1"))


def wordemb(inlayer):
    wordemb = paddle.layer.table_projection(
        input=inlayer,
        size=embsize,
        param_attr=paddle.attr.Param(
            name="_proj",
            initial_std=0.001,
            learning_rate=1,
            l2_rate=0, ))
    return wordemb


def main():
    paddle.init(use_gpu=False, trainer_count=1)
    word_dict = paddle.dataset.imikolov.build_dict()
    dict_size = len(word_dict)
    firstword = paddle.layer.data(
        name="firstw", type=paddle.data_type.integer_value(dict_size))
    secondword = paddle.layer.data(
        name="secondw", type=paddle.data_type.integer_value(dict_size))
    thirdword = paddle.layer.data(
        name="thirdw", type=paddle.data_type.integer_value(dict_size))
    fourthword = paddle.layer.data(
        name="fourthw", type=paddle.data_type.integer_value(dict_size))
    nextword = paddle.layer.data(
        name="fifthw", type=paddle.data_type.integer_value(dict_size))

    Efirst = wordemb(firstword)
    Esecond = wordemb(secondword)
    Ethird = wordemb(thirdword)
    Efourth = wordemb(fourthword)

    contextemb = paddle.layer.concat(input=[Efirst, Esecond, Ethird, Efourth])
    hidden1 = paddle.layer.fc(input=contextemb,
                              size=hiddensize,
                              act=paddle.activation.Sigmoid(),
                              layer_attr=paddle.attr.Extra(drop_rate=0.5),
                              bias_attr=paddle.attr.Param(learning_rate=2),
                              param_attr=paddle.attr.Param(
                                  initial_std=1. / math.sqrt(embsize * 8),
                                  learning_rate=1))
    predictword = paddle.layer.fc(input=hidden1,
                                  size=dict_size,
                                  bias_attr=paddle.attr.Param(learning_rate=2),
                                  act=paddle.activation.Softmax())

    def event_handler(event):
        if isinstance(event, paddle.event.EndIteration):
            if event.batch_id % 100 == 0:
                result = trainer.test(
                    paddle.batch(
                        # NOTE: if you're going to use cluster test files,
                        #       prepare them on the storage first
                        paddle.dataset.imikolov.test(word_dict, N),
                        32))
                print "Pass %d, Batch %d, Cost %f, %s, Testing metrics %s" % (
                    event.pass_id, event.batch_id, event.cost, event.metrics,
                    result.metrics)

    cost = paddle.layer.classification_cost(input=predictword, label=nextword)
    parameters = paddle.parameters.create(cost)
    adam_optimizer = paddle.optimizer.Adam(
        learning_rate=3e-3,
        regularization=paddle.optimizer.L2Regularization(8e-4))
    trainer = paddle.trainer.SGD(cost,
                                 parameters,
                                 adam_optimizer,
                                 is_local=False,
                                 pserver_spec=etcd_endpoint,
                                 use_etcd=True)
    trainer.train(
        paddle.batch(cloud_reader([TRAIN_FILES_PATH], etcd_endpoint), 32),
        num_passes=30,
        event_handler=event_handler)


if __name__ == '__main__':
    main()