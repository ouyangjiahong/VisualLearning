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

BATCH_SIZE = 10
IMAGE_SIZE = 256
IMAGE_CROP_SIZE = 224
MODEL_PATH = "pascal_model_vgg16"
max_step = 40000
stride = 400
display = 400


def cnn_model_fn(features, labels, mode, num_classes=20):
    # Build model
    if mode == tf.estimator.ModeKeys.TRAIN:
        input_layer = tf.reshape(features["x"], [-1, IMAGE_SIZE, IMAGE_SIZE, 3])
    else:
        input_layer = tf.reshape(features["x"], [-1, IMAGE_CROP_SIZE, IMAGE_CROP_SIZE, 3])

    def data_augmentation(inputs):
        for i in xrange(BATCH_SIZE):
            output = tf.image.random_flip_left_right(inputs[i])
            # output = tf.image.random_contrast(output, 0.95, 1.05)
            # output += tf.random_normal([IMAGE_SIZE, IMAGE_SIZE, 3], 0, 0.1)
            output = tf.random_crop(output, [IMAGE_CROP_SIZE, IMAGE_CROP_SIZE, 3])
            output = tf.expand_dims(output, 0)
            if i == 0:
                outputs = output
            else:
                outputs = tf.concat([outputs, output], 0)
        return outputs

    # def center_crop(inputs, size):
    #     print(size)
    #     ratio = IMAGE_CROP_SIZE / float(IMAGE_SIZE)
    #     for i in xrange(size):
    #         output = tf.image.central_crop(inputs[i], ratio)
    #         output = tf.expand_dims(output, 0)
    #         if i == 0:
    #             outputs = output
    #         else:
    #             outputs = tf.concat([outputs, output], 0)
    #     return outputs

    #data augmentation
    if mode == tf.estimator.ModeKeys.TRAIN:
        input_layer = data_augmentation(input_layer)
    # else:
    #     input_layer = center_crop(input_layer, test_num)

    def vgg_conv(input, num_filters):
        output = tf.layers.conv2d(
            inputs=input,
            filters=num_filters,
            kernel_size=[3, 3],
            strides=[1, 1],
            padding="same",
            activation=tf.nn.relu)
            # kernel_initializer=tf.random_normal_initializer(0, 0.01),
            # bias_initializer=tf.zeros_initializer())
        return output

    def vgg_maxpool(input):
        output = tf.layers.max_pooling2d(inputs=input, pool_size=[2, 2], strides=2)
        return output

    def vgg_dense(input, num_out, std):
        output = tf.layers.dense(
            inputs=input, units=num_out,
            activation=tf.nn.relu)
            # kernel_initializer=tf.random_normal_initializer(0, std),
            # bias_initializer=tf.zeros_initializer())
        return output

    def vgg_dropout(input):
        output = tf.layers.dropout(
            inputs=input, rate=0.5, training=mode == tf.estimator.ModeKeys.TRAIN)
        return output

    # conv block 1
    conv1_1 = vgg_conv(input_layer, 64)
    conv1_2 = vgg_conv(conv1_1, 64)
    pool1 = vgg_maxpool(conv1_2)

    # conv block 2
    conv2_1 = vgg_conv(pool1, 128)
    conv2_2 = vgg_conv(conv2_1, 128)
    pool2 = vgg_maxpool(conv2_2)

    # conv block 3
    conv3_1 = vgg_conv(pool2, 256)
    conv3_2 = vgg_conv(conv3_1, 256)
    conv3_3 = vgg_conv(conv3_2, 256)
    pool3 = vgg_maxpool(conv3_3)

    # conv block 4
    conv4_1 = vgg_conv(pool3, 512)
    conv4_2 = vgg_conv(conv4_1, 512)
    conv4_3 = vgg_conv(conv4_2, 512)
    pool4 = vgg_maxpool(conv4_3)

    # conv block 5
    conv5_1 = vgg_conv(pool4, 512)
    conv5_2 = vgg_conv(conv5_1, 512)
    conv5_3 = vgg_conv(conv5_2, 512)
    pool5 = vgg_maxpool(conv5_3)

    # dense
    pool5_flat = tf.reshape(pool5, [-1, 512 * 7 * 7])
    dense1 = vgg_dense(pool5_flat, 4096, 0.005)
    dropout1 = vgg_dropout(dense1)

    dense2 = vgg_dense(dropout1, 4096, 0.005)
    dropout2 = vgg_dropout(dense2)

    # Logits Layer
    logits = vgg_dense(dropout2, 20, 0.01)

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
        lr = tf.train.exponential_decay(0.001, tf.train.get_global_step(), 10000, 0.5)
        optimizer = tf.train.MomentumOptimizer(learning_rate=lr, momentum=0.9)

        grads_and_vars = optimizer.compute_gradients(loss)

        tf.summary.scalar("learning rate", lr)
        tf.summary.image("input image", input_layer[:3,:,:,:])
        for g, v in grads_and_vars:
            if g is not None:
                tf.summary.histogram("{}/grad_histogram".format(v.name), g)
        
        # summary_hook = tf.train.SummarySaverHook(display, summary_op=tf.summary.merge_all())

        train_op = optimizer.minimize(
            loss=loss,
            global_step=tf.train.get_global_step())
        return tf.estimator.EstimatorSpec(
            mode=mode, loss=loss, train_op=train_op)
        # return tf.estimator.EstimatorSpec(
        #     mode=mode, loss=loss, train_op=train_op, training_hooks=[summary_hook])

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
    label_path = label_dir + split + '.txt'
    file = open(label_path, 'r')
    lines = file.readlines()
    file.close()
    img_num = len(lines)
    first_flag = True
    margin = (IMAGE_SIZE - IMAGE_CROP_SIZE) // 2

    mean_value = [123, 116, 103]
    mean_r = np.tile(np.array(mean_value[0]), (IMAGE_SIZE, IMAGE_SIZE))
    mean_g = np.tile(np.array(mean_value[1]), (IMAGE_SIZE, IMAGE_SIZE))
    mean_b = np.tile(np.array(mean_value[2]), (IMAGE_SIZE, IMAGE_SIZE))
    mean = np.stack((mean_r, mean_g, mean_b), axis=2)
    print(mean.shape)

    if split != 'test':
        img_list = np.zeros((len(lines), IMAGE_SIZE, IMAGE_SIZE, 3))
    else:
        img_list = np.zeros((len(lines), IMAGE_CROP_SIZE, IMAGE_CROP_SIZE, 3))

    count = 0
    for line in lines:
        line = line[:6]
        img_name = img_dir + line + '.jpg'
        img = sci.imread(img_name)
        img = sci.imresize(img, (IMAGE_SIZE, IMAGE_SIZE, 3))
        img = np.subtract(img, mean)

        if split == 'test':
            img = img[margin:IMAGE_CROP_SIZE+margin, margin:IMAGE_CROP_SIZE+margin, :]
        img_list[count, :, :, :] = img
        count += 1
        if count % 1000 == 1:
            print(count)


    print("finish loading images")
    img_list = img_list.astype(np.float32)
    img_list /= 255.0
    img_list -= 0.5
    img_list *= 2       

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
        file.close()
        for line in lines:
            label = line.split()[1]
            label = int(label)
            if label == 1:
                label_list[img_pos, cls_pos] = 1
                weight_list[img_pos, cls_pos] = 1
            # elif label == 0:
            #     label_list[img_pos, cls_pos] = 1
            else:
                weight_list[img_pos, cls_pos] = 1
            img_pos += 1
        cls_pos += 1

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
        args.data_dir, split='test')

    pascal_classifier = tf.estimator.Estimator(
        model_fn=partial(cnn_model_fn,
        num_classes=train_labels.shape[1]),
        model_dir=MODEL_PATH)

    tensors_to_log = {"loss": "loss"}
    logging_hook = tf.train.LoggingTensorHook(
        tensors=tensors_to_log, every_n_iter=100)

    # Train the model
    train_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": train_data, "w": train_weights},
        y=train_labels,
        batch_size=BATCH_SIZE,
        num_epochs=None,
        shuffle=True)
    # Evaluate the model and print results
    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data, "w": eval_weights},
        y=eval_labels,
        num_epochs=1,
        shuffle=False)
    

    map_list = []
    step_list = []
    for step in xrange(0, max_step, stride):
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

        map_list.append(np.mean(AP))
        step_list.append(step)
        if step % 10000 == 0:
            fig = plt.figure()
            plt.plot(step_list, map_list)
            plt.title("mAP")
            fig.savefig("task3_mAP_plot.jpg")

    fig = plt.figure()
    plt.plot(step_list, map_list)
    plt.title("mAP")
    fig.savefig("task3_mAP_plot.jpg")


if __name__ == "__main__":
    main()
