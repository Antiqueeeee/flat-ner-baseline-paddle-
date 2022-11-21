import warnings
warnings.filterwarnings("ignore")
import paddle

from tqdm import tqdm
from seqeval.metrics import accuracy_score,recall_score,f1_score
import argparse
import prettytable as pt
import utils
import numpy as np
import data_loader

import models
import os
class Trainer(object):
    def __init__(self, model):
        self.model = model
        criterion = {
            "ce": paddle.nn.CrossEntropyLoss(),
        }
        self.criterion = criterion[config.loss_type]
        self.optimizer = paddle.optimizer.AdamW(parameters=self.model.parameters(), learning_rate=config.bert_learning_rate,
                                                weight_decay=config.weight_decay)
    def train(self, epoch, data_loader):
        self.model.train()
        loss_list = list()
        origin_labels = list()
        pred_labels = list()
        # 拿batch数据
        for i, data_batch in tqdm(enumerate(data_loader)):
            data_batch = [data for data in data_batch]
            bert_inputs, bert_labels, sent_length = data_batch
            # 输入模型
            outputs = self.model(bert_inputs)
            # 计算损失函数
            valid_index = bert_inputs.not_equal(paddle.to_tensor(0, dtype="int64"))
            valid_index = paddle.reshape(valid_index, shape=[-1])
            loss = self.criterion(
                paddle.reshape(outputs, shape=(-1, config.label_num))[valid_index],
                paddle.reshape(bert_labels,shape=[-1])[valid_index]
            )
            # 梯度下降反向传播
            loss.backward()
            self.optimizer.step()
            self.optimizer.clear_grad()
            loss_list.append(loss.cpu().item())

            # 保存输出
            for origin_label, pred_label, bert_input in zip(bert_labels, outputs, bert_inputs):
                _valid_index = bert_input.not_equal(paddle.to_tensor(0,dtype="int64"))
                origin_label = origin_label[_valid_index].cpu().numpy()
                pred_label = paddle.argmax(pred_label, -1)[_valid_index].cpu().numpy()
                origin_label = [config.vocab.id_to_label(i) for i in origin_label]
                pred_label = [config.vocab.id_to_label(i) for i in pred_label]
                origin_labels.append(origin_label)
                pred_labels.append(pred_label)

        # 输出Loss
        table = pt.PrettyTable(["Train {}".format(epoch),"Loss"])
        table.add_row(["Metrics", "{:.4f}".format(np.mean(loss_list))])
        logger.info("\n{}".format(table))

    def eval(self, epoch, data_loader):
        self.model.eval()
        origin_labels = list()
        pred_labels = list()
        with paddle.no_grad():
            for i, data_batch in tqdm(enumerate(data_loader)):
                data_batch = [data for data in data_batch]
                bert_inputs, bert_labels, sent_length = data_batch
                outputs = self.model(bert_inputs)
                for origin_label, pred_label, bert_input in zip(bert_labels, outputs, bert_inputs):
                    _valid_index = bert_input.not_equal(paddle.to_tensor(0,dtype="int64")).astype("int64")
                    origin_label = origin_label[_valid_index].cpu().numpy()
                    pred_label = paddle.argmax(pred_label, -1)[_valid_index].cpu().numpy()
                    origin_label = [config.vocab.id_to_label(i) for i in origin_label]
                    pred_label = [config.vocab.id_to_label(i) for i in pred_label]
                    origin_labels.append(origin_label)
                    pred_labels.append(pred_label)
        p = accuracy_score(origin_labels, pred_labels)
        r = recall_score(origin_labels, pred_labels)
        f1 = f1_score(origin_labels, pred_labels)
        table = pt.PrettyTable(["Dev {}".format(epoch), "F1", "Precision", "Recall"])
        table.add_row(["Metrics"] + ["{:3.4f}".format(x) for x in [f1, p, r]])
        logger.info("\n{}".format(table))
        return f1
    def save(self):
        paddle.save(
            self.model.state_dict(), os.path.join(config.save_path,config.dataset,self.model.model_name + ".pt")
        )

    def load(self, path=None):
        if path:
            self.model.set_state_dict(paddle.load(path))

        else:
            self.model.set_state_dict(paddle.load(
                os.path.join(config.save_path, config.dataset, self.model.model_name + ".pt")
            ))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default='./config/chinese_news.json')
    parser.add_argument('--save_path', type=str, default='./outputs')
    parser.add_argument('--bert_name', type=str, default=r"bert-base-chinese")
    parser.add_argument('--device', type=str, default="gpu")
    args = parser.parse_args(args=[])

    config = utils.Config(args)
    logger = utils.get_logger(config.dataset)
    logger.info(config)
    config.logger = logger
    paddle.device.set_device(config.device)
    datasets, ori_data = data_loader.load_data_bert(config)

    train_batch_sampler,dev_batch_sample = (paddle.io.BatchSampler(
        dataset
        ,batch_size=config.batch_size
        ,shuffle=i==0
    ) for i,dataset in enumerate(datasets))

    train_loader,dev_loader = (paddle.io.DataLoader(dataset=dataset
                                                    ,batch_sampler=[train_batch_sampler,dev_batch_sample][i]
                                                    ,collate_fn=data_loader.collate_fn
                                                    ) for i,dataset in enumerate(datasets))


    updates_total = len(datasets[0]) // config.batch_size * config.epochs
    logger.info("Building Model")
    model = models.bertCNN(config)
    trainer = Trainer(model)

    best_f1 = 0
    best_test_f1 = 0
    # 训练config.epochs次
    for i in range(config.epochs):
        logger.info("Epoch: {}".format(i))
        # 训练模型
        trainer.train(i, train_loader)
    #     # 训练结束验证训练效果
        f1 = trainer.eval(i, dev_loader)
        if f1 > best_test_f1:
            best_f1 = f1
            trainer.save()
    model = trainer.load()
    trainer.eval("Final",dev_loader)
    logger.info("Best DEV F1: {:3.4f}".format(best_f1))