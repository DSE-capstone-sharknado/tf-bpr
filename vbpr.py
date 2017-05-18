

import tensorflow as tf
import os
import cPickle as pickle
import numpy
import random
import time
import numpy as np

from utils import load_data, load_image_features, load_data_simple



def generate_test(user_ratings):
    '''
    for each user, random select one rating into test set
    '''
    user_test = dict()
    for u, i_list in user_ratings.items():
        user_test[u] = random.sample(user_ratings[u], 1)[0]
    return user_test
    
def uniform_sample_batch(train_ratings, test_ratings, item_count, image_features, sample_count=400, batch_size=512):
    for i in xrange(sample_count):
        t = []
        iv = []
        jv = []
        for b in xrange(batch_size):
            u = random.sample(train_ratings.keys(), 1)[0] #random user
            
            i = random.sample(train_ratings[u], 1)[0]
            while i == test_ratings[u]: #make sure i is not in the test set
                i = random.sample(train_ratings[u], 1)[0]
                
            j = random.randint(0, item_count)
            while j in train_ratings[u]:
                j = random.randint(0, item_count)
                
            #sometimes there will not be an image for given item i or j
            try: 
              image_features[i]
              image_features[j]
            except KeyError:
              continue  #if so, skip this item
              
            t.append([u, i, j])
            iv.append(image_features[i])
            jv.append(image_features[j])
        yield numpy.asarray(t), numpy.vstack(tuple(iv)), numpy.vstack(tuple(jv))

def test_batch_generator_by_user(train_ratings, test_ratings, item_count, image_features, sample_size=3000):
    # using leave one cv
    for u in random.sample(test_ratings.keys(), sample_size): #uniform random sampling w/o replacement
        t = []
        ilist = []
        jlist = []
        
        i = test_ratings[u]
        #check if we have an image for i, sometimes we dont...
        if i not in image_features:
          continue
        
        for j in range(item_count):
            if j != test_ratings[u] and not (j in train_ratings[u]):
                # find negative item not in train or test set

                #sometimes there will not be an image for given product
                try: 
                  image_features[i]
                  image_features[j]
                except KeyError:
                  continue  #if image not found, skip item
                
                t.append([u, i, j])
                ilist.append(image_features[i])
                jlist.append(image_features[j])
                
        yield numpy.asarray(t), numpy.vstack(tuple(ilist)), numpy.vstack(tuple(jlist))
        
def vbpr(user_count, item_count, hidden_dim=20, hidden_img_dim=128, 
         learning_rate = 0.001,
         l2_regulization = 0.01, 
         bias_regulization=1.0):
    """
    user_count: total number of users
    item_count: total number of items
    hidden_dim: hidden feature size of MF
    hidden_img_dim: [4096, hidden_img_dim]
    """
    u = tf.placeholder(tf.int32, [None])
    i = tf.placeholder(tf.int32, [None])
    j = tf.placeholder(tf.int32, [None])
    iv = tf.placeholder(tf.float32, [None, 4096])
    jv = tf.placeholder(tf.float32, [None, 4096])
    
    user_emb_w = tf.get_variable("user_emb_w", [user_count+1, hidden_dim], 
                                initializer=tf.random_normal_initializer(0, 0.1))
    user_img_w = tf.get_variable("user_img_w", [user_count+1, hidden_img_dim],
                                initializer=tf.random_normal_initializer(0, 0.1))
    item_emb_w = tf.get_variable("item_emb_w", [item_count+1, hidden_dim], 
                                initializer=tf.random_normal_initializer(0, 0.1))
    item_b = tf.get_variable("item_b", [item_count+1, 1], 
                                initializer=tf.constant_initializer(0.0))
    visual_bias = tf.get_variable("visual_bias", [1, 4096], initializer=tf.constant_initializer(0.0))
    
    u_emb = tf.nn.embedding_lookup(user_emb_w, u)
    u_img = tf.nn.embedding_lookup(user_img_w, u)
    
    i_emb = tf.nn.embedding_lookup(item_emb_w, i)
    i_b = tf.nn.embedding_lookup(item_b, i)
    j_emb = tf.nn.embedding_lookup(item_emb_w, j)
    j_b = tf.nn.embedding_lookup(item_b, j)
    
    img_emb_w = tf.get_variable("image_embedding_weights", [4096, hidden_img_dim], 
                               initializer=tf.random_normal_initializer(0, 0.1))


    # MF predict: u_i > u_j
    theta_i = tf.matmul(iv, img_emb_w) # (f_i * E), eq. 3
    theta_j = tf.matmul(jv, img_emb_w) # (f_j * E), eq. 3
    xui = i_b + tf.reduce_sum(tf.multiply(u_emb, i_emb), 1, keep_dims=True) + tf.reduce_sum(tf.multiply(u_img, theta_i), 1, keep_dims=True) + tf.reduce_sum(tf.multiply(visual_bias, iv), 1, keep_dims=True)
    xuj = j_b + tf.reduce_sum(tf.multiply(u_emb, j_emb), 1, keep_dims=True) + tf.reduce_sum(tf.multiply(u_img, theta_j), 1, keep_dims=True) + tf.reduce_sum(tf.multiply(visual_bias, jv), 1, keep_dims=True)
    xuij = xui - xuj
    #

    # auc score is used in test/cv
    # reduce_mean is reasonable BECAUSE
    # all test (i, j) pairs of one user is in ONE batch
    auc = tf.reduce_mean(tf.to_float(xuij > 0))

    l2_norm = tf.add_n([
            l2_regulization * tf.reduce_sum(tf.multiply(u_emb, u_emb)), 
            l2_regulization * tf.reduce_sum(tf.multiply(u_img, u_img)),
            l2_regulization * tf.reduce_sum(tf.multiply(i_emb, i_emb)),
            l2_regulization * tf.reduce_sum(tf.multiply(j_emb, j_emb)),
            l2_regulization * tf.reduce_sum(tf.multiply(img_emb_w, img_emb_w)),
            bias_regulization * tf.reduce_sum(tf.multiply(i_b, i_b)),
            bias_regulization * tf.reduce_sum(tf.multiply(j_b, j_b)),
            bias_regulization * tf.reduce_sum(tf.multiply(visual_bias,visual_bias))
        ])

    loss = l2_norm - tf.reduce_mean(tf.log(tf.sigmoid(xuij)))
    train_op = tf.train.GradientDescentOptimizer(learning_rate).minimize(loss)
    print "Hyper-parameters: K=%d, K2=%d, lr=%f, l2r=%f, br=%f"%(hidden_dim, hidden_img_dim, learning_rate, l2_regulization, bias_regulization)
    return u, i, j, iv, jv, loss, auc, train_op
    


# data_path = os.path.join('data/amzn/', 'review_Women.csv')
# user_count, item_count, users, items, train_ratings = load_data(data_path)
simple_path = os.path.join('data', 'amzn', 'reviews_Women_5.txt')
users, items, reviews_count, train_ratings = load_data_simple(simple_path, min_items=5)
user_count = len(users)
item_count = len(items)
print user_count,item_count,reviews_count

#items: asin -> iid

  
images_path = "data/amzn/image_features_Women.b"
image_features = load_image_features(images_path, items)    
    
print "extracted image feature count: ",len(image_features)

test_ratings = generate_test(train_ratings)

sample_count = 400
batch_size = 512
epochs =21 # ideally we should not hard code this. GD should terminate when loss converges
K=20
K2=128
lr=0.01
lam=0.01
lam2=0.01  

with tf.Graph().as_default(), tf.Session() as session:
    with tf.variable_scope('vbpr'):
        u, i, j, iv, jv, loss, auc, train_op = vbpr(user_count, item_count, hidden_dim=K, hidden_img_dim=K2, learning_rate =lr, l2_regulization =lam, bias_regulization=lam2)
    
    session.run(tf.global_variables_initializer())
    
    epoch_durations = []
    for epoch in range(1, epochs):
        print "epoch ", epoch
        epoch_start_time = time.time()
        _loss_train = 0.0
        for d, _iv, _jv in uniform_sample_batch(train_ratings, test_ratings, item_count, image_features, sample_count=sample_count, batch_size=batch_size ):
            _loss, _ = session.run([loss, train_op], feed_dict={ u:d[:,0], i:d[:,1], j:d[:,2], iv:_iv, jv:_jv})
            _loss_train += _loss
        print "train_loss:", _loss_train/sample_count
        
        epoch_end_time = time.time()
        epoch_duration = epoch_end_time - epoch_start_time
        epoch_durations.append(epoch_duration)
        print "epoch time: ",epoch_duration,", avg: ",np.mean(epoch_durations)
        
        if epoch % 20 != 0:
            continue
        
        auc_values=[]
        loss_values=[]
        user_count=0
        dur_sum=0
        _test_user_count = len(test_ratings)
        for d, fi, fj in test_batch_generator_by_user(train_ratings, test_ratings, item_count, image_features):
            s = time.time()    
            _loss, _auc = session.run([loss, auc], feed_dict={u:d[:,0], i:d[:,1], j:d[:,2], iv:fi, jv:fj})
            loss_values.append(_loss)
            auc_values.append(_auc)
            user_count+=1
            e=time.time()
            dur=e-s
            dur_sum+=dur
            print "user ",user_count," auc:",_auc,", loss:",_loss,", avg loss:",np.mean(loss_values),", avg auc:",np.mean(auc_values)
        print "test_loss: ", np.mean(loss_values), " auc: ", np.mean(auc_values)
        print ""
        

# nohup time python -u vbpr2.py > vbpr2-test001.log 2>&1 &