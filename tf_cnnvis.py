# imports
import os
import time

import numpy as np

from six.moves import range
from six import string_types

import tensorflow as tf
from tensorflow.python.framework import ops
from tensorflow.python.ops import gen_nn_ops

from skimage.restoration import denoise_tv_bregman

from utils import *
from utils import config


is_Registered = False 

dict_layer = {'r' : "relu", 'p' : 'maxpool', 'c' : 'conv2d'}
units = None

configProto = tf.ConfigProto(allow_soft_placement = True)

# register custom gradients
def _register_custom_gradients():
    """
    Register Custom Gradients.
    """
    global is_Registered

    if not is_Registered:
        # register LRN gradients
        @ops.RegisterGradient("Customlrn")
        def _CustomlrnGrad(op, grad):
            return grad

        # register Relu gradients
        @ops.RegisterGradient("GuidedRelu")
        def _GuidedReluGrad(op, grad):
            return tf.where(0. < grad, gen_nn_ops._relu_grad(grad, op.outputs[0]), tf.zeros_like(grad))

        is_Registered = True



def _save_model(graph_or_sess):
    
    if isinstance(graph_or_sess, tf.Graph):
        ops = graph_or_sess.get_operations()
        for op in ops:
            if 'variable' in op.type.lower():
                raise ValueError('Please input a frozen graph (no variables). Or pass in the session object.')

        with graph_or_sess.as_default():
            sess = tf.Session(config=configProto)

            fake_var = tf.Variable([0.0], name="fake_var")
            sess.run(tf.global_variables_initializer())
    else:
        sess=graph_or_sess

    PATH = os.path.join("model", "tmp-model")
    make_dir(path = os.path.dirname(PATH))
    saver = tf.train.Saver()
    #i should deal with the case in which sess is closed.
    saver.save(sess, PATH)

    if isinstance(graph_or_sess, tf.Graph):
        sess.close()

    return PATH + ".meta"


# All visualization of convolution happens here
def _get_visualization(sess_graph_path, value_feed_dict, input_tensor, layers, path_logdir, path_outdir, method = None):

    is_success = True

    
    if isinstance(sess_graph_path, tf.Graph):
        PATH = _save_model(sess_graph_path)
    elif isinstance(sess_graph_path, tf.Session):
        PATH = _save_model(sess_graph_path)
    elif isinstance(sess_graph_path, string_types):
        PATH = sess_graph_path
    elif sess_graph_path is None:
        
        if isinstance(tf.get_default_session(), tf.Session):
            PATH = _save_model(tf.get_default_session())
        else:
            PATH = _save_model(tf.get_default_graph())
    else:
        print("sess_graph_path must be an instance of tf.Session, tf. Graph, string or None.")
        is_success = False
        return is_success

    is_gradient_overwrite = method == "deconv"
    if is_gradient_overwrite:
        _register_custom_gradients() 

    # a new default Graph g and Session s which are loaded and used only in these nested with statements
    with tf.Graph().as_default() as g:
        with tf.Session(graph=g).as_default() as s:
            if is_gradient_overwrite:
                with g.gradient_override_map({'Relu': 'GuidedRelu', 'LRN': 'Customlrn'}): 
                    
                    s = _graph_import_function(PATH,s)
            else:
                s = _graph_import_function(PATH,s)

            if not isinstance(layers, list):
                layers =[layers]

            for layer in layers:
                if layer != None and layer.lower() not in dict_layer.keys():
                    is_success = _visualization_by_layer_name(g, value_feed_dict, input_tensor, layer, method, path_logdir, path_outdir)
                elif layer != None and layer.lower() in dict_layer.keys():
                    layer_type = dict_layer[layer.lower()]
                    is_success = _visualization_by_layer_type(g, value_feed_dict, input_tensor, layer_type, method, path_logdir, path_outdir)
                else:
                    print("Skipping %s . %s is not valid layer name or layer type" % (layer, layer))

    return is_success


def _graph_import_function(PATH, sess):
    new_saver = tf.train.import_meta_graph(PATH)
    new_saver.restore(sess, tf.train.latest_checkpoint(os.path.dirname(PATH)))
    return sess

def _visualization_by_layer_type(graph, value_feed_dict, input_tensor, layer_type, method, path_logdir, path_outdir):
    """
    
    param layer_type:
        Type of the layer. Supported layer types :
        'r' : Reconstruction from all the relu layers
        'p' : Reconstruction from all the pooling layers
        'c' : Reconstruction from all the convolutional layers
    type layer_type: String (Default = 'r')

    
    """
    is_success = True

    layers = []
   
    for i in graph.get_operations():
        if layer_type.lower() == i.type.lower():
            layers.append(i.name)

    for layer in layers:
        is_success = _visualization_by_layer_name(graph, value_feed_dict, input_tensor, layer, method, path_logdir, path_outdir)
    return is_success

def _visualization_by_layer_name(graph, value_feed_dict, input_tensor, layer_name, method, path_logdir, path_outdir):
    """
    Generate and store filter visualization from the layer which has the name layer_name


    :param input_tensor:
        Where to reconstruct
    :type input_tensor: tf.tensor object (Default = None)

    :param layer_name:
        Name of the layer to visualize
    :type layer_name: String

    :param path_logdir:
        <path-to-log-dir> to make log file for TensorBoard visualization


    :return:
        True if successful. False otherwise.
    :rtype: boolean
    """
    start = -time.time()
    is_success = True

    sess = tf.get_default_session()
    if not(graph is sess.graph):
        print('Error, the graph input is not the graph of the current session!!')
    
    parsed_tensors = parse_tensors_dict(graph, layer_name, value_feed_dict)
    if parsed_tensors == None:
        return is_success

    op_tensor, x, X_in, feed_dict = parsed_tensors

    is_deep_dream = True
    
    with graph.as_default():
       
        X = X_in
        if input_tensor != None:
            X = get_tensor(graph = graph, name = input_tensor.name)
       

        results = None
        if method == "act":
            # compute activations
            results = _activation(graph, sess, op_tensor, feed_dict)
        elif method == "deconv":
            # deconvolution
            results = _deconvolution(graph, sess, op_tensor, X, feed_dict)

   



    start += time.time()
    print("Reconstruction Completed for %s layer. Time taken = %f s" % (layer_name, start))

    return is_success


# computing visualizations
def _activation(graph, sess, op_tensor, feed_dict):
    with graph.as_default() as g:
        with sess.as_default() as sess:
            act = sess.run(op_tensor, feed_dict = feed_dict)
    return act
def _deconvolution(graph, sess, op_tensor, X, feed_dict):
    out = []
    with graph.as_default() as g:
        # get shape of tensor
        tensor_shape = op_tensor.get_shape().as_list()

        with sess.as_default() as sess:
            
            # creating gradient ops
            featuremap = [tf.placeholder(tf.int32) for i in range(config["N"])]
            reconstruct = [tf.gradients(tf.transpose(tf.transpose(op_tensor)[featuremap[i]]), X)[0] for i in range(config["N"])]

            
            for i in range(0, tensor_shape[-1], config["N"]):
                c = 0
                for j in range(config["N"]):
                    if (i + j) < tensor_shape[-1]:
                        feed_dict[featuremap[j]] = i + j
                        c += 1
                if c > 0:
                    out.extend(sess.run(reconstruct[:c], feed_dict = feed_dict))
    return out


# main api methods
def activation_visualization(sess_graph_path, value_feed_dict, input_tensor = None,  layers = 'r', path_logdir = './Log', path_outdir = "./Output"):
    is_success = _get_visualization(sess_graph_path, value_feed_dict, input_tensor = input_tensor, layers = layers, method = "act",
        path_logdir = path_logdir, path_outdir = path_outdir)
    return is_success
def deconv_visualization(sess_graph_path, value_feed_dict, input_tensor = None,  layers = 'r', path_logdir = './Log', path_outdir = "./Output"):
    is_success = _get_visualization(sess_graph_path, value_feed_dict, input_tensor = input_tensor, layers = layers, method = "deconv",
        path_logdir = path_logdir, path_outdir = path_outdir)
    return is_success


