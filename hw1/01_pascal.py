from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# Imports
import sys
import numpy as np
import tensorflow as tf
import argparse
import os.path as osp
import scipy.misc as sci
from PIL import Image
from functools import partial
import matplotlib.pyplot as plt

from eval import compute_map
# import model

tf.logging.set_verbosity(tf.logging.INFO)

CLASS_NAMES = [
    'aeroplane',
    'bicycle',
    'bird',
    'boat',
    'bottle',
    'bus',
    'car',
    'cat',
    'chair',
    'cow',
    'diningtable',
    'dog',
    'horse',
    'motorbike',
    'person',
    'pottedplant',
    'sheep',
    'sofa',
    'train',
    'tvmonitor',
]


def cnn_model_fn(features, labels, mode, num_classes=20):
    # Build model
    input_layer = tf.reshape(features["x"], [-1, 256, 256, 3])

    # Convolutional Layer #1
    conv1 = tf.layers.conv2d(
        inputs=input_layer,
        filters=32,
        kernel_size=[5, 5],
        padding="same",
        activation=tf.nn.relu)

    # Pooling Layer #1
    pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)

    # Convolutional Layer #2 and Pooling Layer #2
    conv2 = tf.layers.conv2d(
        inputs=pool1,
        filters=64,
        kernel_size=[5, 5],
        padding="same",
        activation=tf.nn.relu)
    pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)

    # Dense Layer
    print(pool2.shape)
    pool2_flat = tf.reshape(pool2, [-1, 64 * 64 * 64])
    dense = tf.layers.dense(inputs=pool2_flat, units=1024,
                            activation=tf.nn.relu)
    dropout = tf.layers.dropout(
        inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)

    # Logits Layer
    logits = tf.layers.dense(inputs=dropout, units=20)

    predictions = {
        # Generate predictions (for PREDICT and EVAL mode)
        "classes": tf.argmax(input=logits, axis=1),
        # Add `softmax_tensor` to the graph. It is used for PREDICT and by the
        # `logging_hook`.
        "probabilities": tf.nn.sigmoid(logits, name="sigmoid_tensor")
    }

    if mode == tf.estimator.ModeKeys.PREDICT:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

    # Calculate Loss (for both TRAIN and EVAL modes)
    loss = tf.identity(tf.losses.sigmoid_cross_entropy(
        multi_class_labels=labels, logits=logits), name='loss')

    # Configure the Training Op (for TRAIN mode)
    if mode == tf.estimator.ModeKeys.TRAIN:
        optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.001)
        train_op = optimizer.minimize(
            loss=loss,
            global_step=tf.train.get_global_step())
        return tf.estimator.EstimatorSpec(
            mode=mode, loss=loss, train_op=train_op)

    # Add evaluation metrics (for EVAL mode)
    eval_metric_ops = {
        "accuracy": tf.metrics.accuracy(
            labels=labels, predictions=predictions["classes"])} 
    return tf.estimator.EstimatorSpec(
        mode=mode, loss=loss, eval_metric_ops=eval_metric_ops)


def load_pascal(data_dir, split='train'):
    """
    Function to read images from PASCAL data folder.
    Args:
        data_dir (str): Path to the VOC2007 directory.
        split (str): train/val/trainval split to use.
    Returns:
        images (np.ndarray): Return a np.float32 array of
            shape (N, H, W, 3), where H, W are 224px each,
            and each image is in RGB format.
        labels (np.ndarray): An array of shape (N, 20) of
            type np.int32, with 0s and 1s; 1s for classes that
            are active in that image.
    """
    # Wrote this function
    img_dir = data_dir + 'JPEGImages/'
    label_dir = data_dir + 'ImageSets/Main/'

    # read images
    label_path = label_dir + 'aeroplane_' + split + '.txt'
    file = open(label_path, 'r')
    lines = file.readlines()
    img_num = len(lines)
    first_flag = True

    for line in lines:
        line = line.split(' ')[0]
        img_name = img_dir + line + '.jpg'
        img = sci.imread(img_name)
        img = sci.imresize(img, (256, 256, 3))
        img = np.expand_dims(img, axis=0)
        if first_flag == True:
            img_list = img
            first_flag = False
        else:
            img_list = np.concatenate((img_list, img), axis=0)        
    file.close()
    print("finish loading images")
    print(img_list.shape)

    # read labels
    label_list = np.zeros((img_num, 20))
    weight_list = np.zeros((img_num, 20))
    cls_pos = 0
    for class_name in CLASS_NAMES:
        img_pos = 0
        label_path = label_dir + class_name + '_' + split + '.txt'
        # load images
        file = open(label_path, 'r')
        lines = file.readlines()
        for line in lines:
            label = line.split()[1]
            label = int(label)
            if label == 1:
                label_list[img_pos, cls_pos] = 1
                weight_list[img_pos, cls_pos] = 1
            elif label == 0:
                label_list[img_pos, cls_pos] = 1
            else:
                weight_list[img_pos, cls_pos] = 1
            img_pos += 1
        cls_pos += 1
        file.close()
    print("finish loading label")

    img_list = img_list.astype(np.float32)
    label_list = label_list.astype(np.int32)
    weight_list = weight_list.astype(np.int32)
    return img_list, label_list, weight_list
    

def parse_args():
    parser = argparse.ArgumentParser(
        description='Train a classifier in tensorflow!')
    parser.add_argument(
        'data_dir', type=str, default='data/VOC2007',
        help='Path to PASCAL data storage')
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    args = parser.parse_args()
    return args


def _get_el(arr, i):
    try:
        return arr[i]
    except IndexError:
        return arr


def main():
    args = parse_args()
    # Load training and eval data
    train_data, train_labels, train_weights = load_pascal(
        args.data_dir, split='trainval')
    eval_data, eval_labels, eval_weights = load_pascal(
        args.data_dir, split='trainval')

    pascal_classifier = tf.estimator.Estimator(
        model_fn=partial(cnn_model_fn,
                         num_classes=train_labels.shape[1]),
        model_dir="pascal_model_scratch")
    tensors_to_log = {"loss": "loss"}
    logging_hook = tf.train.LoggingTensorHook(
        tensors=tensors_to_log, every_n_iter=10)
    # Train the model
    train_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": train_data, "w": train_weights},
        y=train_labels,
        batch_size=10,
        num_epochs=None,
        shuffle=True)
    # Evaluate the model and print results
    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data, "w": eval_weights},
        y=eval_labels,
        num_epochs=1,
        shuffle=False)

    max_step = 1000
    stride = 10
    
    # sess = tf.Session()  
    # writer = tf.summary.FileWriter("pascal_model_scratch/", sess.graph)
    # holder = tf.placeholder(tf.float32, name="holder") 

    map_list = []
    step_list = []
    for step in xrange(1, max_step, stride):
        pascal_classifier.train(
            input_fn=train_input_fn,
            steps=stride,
            hooks=[logging_hook])
        print("evaluate")
        # eval_results = pascal_classifier.evaluate(input_fn=eval_input_fn)

        pred = list(pascal_classifier.predict(input_fn=eval_input_fn))
        pred = np.stack([p['probabilities'] for p in pred])
        rand_AP = compute_map(
            eval_labels, np.random.random(eval_labels.shape),
            eval_weights, average=None)
        print('Random AP: {} mAP'.format(np.mean(rand_AP)))
        gt_AP = compute_map(
            eval_labels, eval_labels, eval_weights, average=None)
        print('GT AP: {} mAP'.format(np.mean(gt_AP)))
        AP = compute_map(eval_labels, pred, eval_weights, average=None)
        print('Obtained {} mAP'.format(np.mean(AP)))
        print('per class:')
        for cid, cname in enumerate(CLASS_NAMES):
            print('{}: {}'.format(cname, _get_el(AP, cid)))

        # tf.summary.scalar("mAP", holder)
        # merged = tf.summary.merge_all()
        # result = sess.run(merged, feed_dict={holder:np.mean(AP)})
        # writer.add_summary(result, step) 
        map_list.append(np.mean(AP))
        step_list.append(step)

    fig = plt.figure()
    plt.plot(step_list, map_list)
    plt.title("mAP")
    fig.savefig("mAP_plot.jpg")


if __name__ == "__main__":
    main()