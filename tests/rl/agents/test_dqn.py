from __future__ import division
from __future__ import absolute_import

import pytest
import numpy as np
from numpy.testing import assert_allclose

from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import Input, Dense, Flatten, Concatenate

from rl.agents.dqn import NAFLayer, DQNAgent, NAFAgent
from rl.memory import SequentialMemory
from rl.processors import MultiInputProcessor

from ..util import MultiInputTestEnv


def test_single_dqn_input():
    model = Sequential()
    model.add(Flatten(input_shape=(2, 3)))
    model.add(Dense(2))

    memory = SequentialMemory(limit=10, window_length=2)
    for double_dqn in (True, False):
        agent = DQNAgent(model, memory=memory, nb_actions=2, nb_steps_warmup=5, batch_size=4,
                         enable_double_dqn=double_dqn)
        agent.compile('sgd')
        agent.fit(MultiInputTestEnv((3,)), nb_steps=10)


def test_multi_dqn_input():
    input1 = Input(shape=(2, 3))
    input2 = Input(shape=(2, 4))
    x = Concatenate()([input1, input2])
    x = Flatten()(x)
    x = Dense(2)(x)
    model = Model(inputs=[input1, input2], outputs=x)

    memory = SequentialMemory(limit=10, window_length=2)
    processor = MultiInputProcessor(nb_inputs=2)
    for double_dqn in (True, False):
        agent = DQNAgent(model, memory=memory, nb_actions=2, nb_steps_warmup=5, batch_size=4,
                         processor=processor, enable_double_dqn=double_dqn)
        agent.compile('sgd')
        agent.fit(MultiInputTestEnv([(3,), (4,)]), nb_steps=10)


def test_single_continuous_dqn_input():
    nb_actions = 2

    V_model = Sequential()
    V_model.add(Flatten(input_shape=(2, 3)))
    V_model.add(Dense(1))

    mu_model = Sequential()
    mu_model.add(Flatten(input_shape=(2, 3)))
    mu_model.add(Dense(nb_actions))

    L_input = Input(shape=(2, 3))
    L_input_action = Input(shape=(nb_actions,))
    x = Concatenate()([Flatten()(L_input), L_input_action])
    x = Dense(((nb_actions * nb_actions + nb_actions) // 2))(x)
    L_model = Model(inputs=[L_input_action, L_input], outputs=x)

    memory = SequentialMemory(limit=10, window_length=2)
    agent = NAFAgent(nb_actions=nb_actions, V_model=V_model, L_model=L_model, mu_model=mu_model,
                     memory=memory, nb_steps_warmup=5, batch_size=4)
    agent.compile('sgd')
    agent.fit(MultiInputTestEnv((3,)), nb_steps=10)


def test_multi_continuous_dqn_input():
    nb_actions = 2

    V_input1 = Input(shape=(2, 3))
    V_input2 = Input(shape=(2, 4))
    x = Concatenate()([V_input1, V_input2])
    x = Flatten()(x)
    x = Dense(1)(x)
    V_model = Model(inputs=[V_input1, V_input2], outputs=x)

    mu_input1 = Input(shape=(2, 3))
    mu_input2 = Input(shape=(2, 4))
    x = Concatenate()([mu_input1, mu_input2])
    x = Flatten()(x)
    x = Dense(nb_actions)(x)
    mu_model = Model(inputs=[mu_input1, mu_input2], outputs=x)

    L_input1 = Input(shape=(2, 3))
    L_input2 = Input(shape=(2, 4))
    L_input_action = Input(shape=(nb_actions,))
    x = Concatenate()([L_input1, L_input2])
    x = Concatenate()([Flatten()(x), L_input_action])
    x = Dense(((nb_actions * nb_actions + nb_actions) // 2))(x)
    L_model = Model(inputs=[L_input_action, L_input1, L_input2], outputs=x)

    memory = SequentialMemory(limit=10, window_length=2)
    processor = MultiInputProcessor(nb_inputs=2)
    agent = NAFAgent(nb_actions=nb_actions, V_model=V_model, L_model=L_model, mu_model=mu_model,
                     memory=memory, nb_steps_warmup=5, batch_size=4, processor=processor)
    agent.compile('sgd')
    agent.fit(MultiInputTestEnv([(3,), (4,)]), nb_steps=10)


def test_naf_layer_full():
    batch_size = 2
    for nb_actions in (1, 3):
        # Construct single model with NAF as the only layer, hence it is fully deterministic
        # since no weights are used, which would be randomly initialized.
        L_flat_input = Input(shape=((nb_actions * nb_actions + nb_actions) // 2,))
        mu_input = Input(shape=(nb_actions,))
        action_input = Input(shape=(nb_actions,))
        x = NAFLayer(nb_actions, mode='full')([L_flat_input, mu_input, action_input])
        model = Model(inputs=[L_flat_input, mu_input, action_input], outputs=x)
        model.compile(loss='mse', optimizer='sgd')
        
        # Create random test data.
        L_flat = np.random.random((batch_size, (nb_actions * nb_actions + nb_actions) // 2)).astype('float32')
        mu = np.random.random((batch_size, nb_actions)).astype('float32')
        action = np.random.random((batch_size, nb_actions)).astype('float32')

        # Perform reference computations in numpy since these are much easier to verify.
        L = np.zeros((batch_size, nb_actions, nb_actions)).astype('float32')
        LT = np.copy(L)
        for l, l_T, l_flat in zip(L, LT, L_flat):
            l[np.tril_indices(nb_actions)] = l_flat
            l[np.diag_indices(nb_actions)] = np.exp(l[np.diag_indices(nb_actions)])
            l_T[:, :] = l.T
        P = np.array([np.dot(l, l_T) for l, l_T in zip(L, LT)]).astype('float32')
        A_ref = np.array([np.dot(np.dot(a - m, p), a - m) for a, m, p in zip(action, mu, P)]).astype('float32')
        A_ref *= -.5

        # Finally, compute the output of the net, which should be identical to the previously
        # computed reference.
        A_net = model.predict([L_flat, mu, action]).flatten()
        assert_allclose(A_net, A_ref, rtol=1e-5)


def test_naf_layer_diag():
    batch_size = 2
    for nb_actions in (1, 3):
        # Construct single model with NAF as the only layer, hence it is fully deterministic
        # since no weights are used, which would be randomly initialized.
        L_flat_input = Input(shape=(nb_actions,))
        mu_input = Input(shape=(nb_actions,))
        action_input = Input(shape=(nb_actions,))
        x = NAFLayer(nb_actions, mode='diag')([L_flat_input, mu_input, action_input])
        model = Model(inputs=[L_flat_input, mu_input, action_input], outputs=x)
        model.compile(loss='mse', optimizer='sgd')
        
        # Create random test data.
        L_flat = np.random.random((batch_size, nb_actions)).astype('float32')
        mu = np.random.random((batch_size, nb_actions)).astype('float32')
        action = np.random.random((batch_size, nb_actions)).astype('float32')

        # Perform reference computations in numpy since these are much easier to verify.
        P = np.zeros((batch_size, nb_actions, nb_actions)).astype('float32')
        for p, l_flat in zip(P, L_flat):
            p[np.diag_indices(nb_actions)] = l_flat
        print(P, L_flat)
        A_ref = np.array([np.dot(np.dot(a - m, p), a - m) for a, m, p in zip(action, mu, P)]).astype('float32')
        A_ref *= -.5

        # Finally, compute the output of the net, which should be identical to the previously
        # computed reference.
        A_net = model.predict([L_flat, mu, action]).flatten()
        assert_allclose(A_net, A_ref, rtol=1e-5)


if __name__ == '__main__':
    pytest.main([__file__])
