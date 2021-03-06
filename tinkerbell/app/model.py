import numpy as np
import pickle
import sys
import logging as log
import keras.models as kem
import keras.layers as kel
import keras.callbacks as kec
import sklearn.preprocessing as skprep
import collections as coll


def makes_deep_copy(fct):
    def ret_fct(*args, **kwargs):
        print('Think about this deep copy of a potentially large buffer in \'{}()\''.format(fct.__name__))
        return fct(*args, **kwargs)
    ret_fct.f = fct.__name__
    ret_fct.__doc__ = fct.__doc__
    ret_fct.__dict__.update(fct.__dict__)
    return ret_fct


class Features:
    def __init__(self, production, stage):        
        assert len(production) == len(stage), "Feature vectors must have same number of samples."
        self.production = np.copy(production)
        self.stage = np.copy(stage)
        self.eval_gradients()

    def eval_gradients(self):
        self.stage_delta = np.diff(self.stage)

    def matrix(self):
        # here we must account for that we lost the bottom row
        # when taking the delta from the production stage
        # this is coupled with matrix() in Targets in a sense
        # through the diff in the targets (we predict gradients)
        return np.transpose(np.array([self.production[:-1], self.stage_delta]))


class Targets:
    def __init__(self, production, time=None):
        """
        If time=None, assumes equidistant.
        """
        self.production = np.copy(production)        
        if time is not None:
            self.time = np.copy(time)
        else:
            self.time = np.arange(float(len(production)))
        self.eval_gradients()

    def eval_gradients(self):
        self.dp_dt = np.diff(self.production) / np.diff(self.time)        

    def matrix(self):
        return self.dp_dt.reshape(-1, 1)


class Normalizer:
    def __init__(self):
        self.features = skprep.MinMaxScaler(feature_range=(-1, 1))
        self.targets = skprep.MinMaxScaler(feature_range=(-1, 1))

    def normalize_features(self, features):
        return self.features.transform(features.matrix())

    def denormalize_features(self, feature_matrix):
        return self.features.inverse_transform(feature_matrix)

    def normalize_targets(self, targets):
        return self.targets.transform(targets.matrix())

    def denormalize_targets(self, target_matrix):
        return self.targets.inverse_transform(target_matrix)

    @staticmethod
    @makes_deep_copy    
    def fit(features, targets):
        normalizer = Normalizer()
        normalizer.features.fit(features.matrix())
        normalizer.targets.fit(targets.matrix())
        return normalizer

    def save(self, fname):
        pickle.dump(self, open(fname, "wb"))

    @staticmethod
    def load(fname):
        return pickle.load(open(fname, "rb"))


class ProgressBar:
    def __init__(self, num_iterations):
        self.fill = '█'
        self.length = 50
        self.decimals = 1
        self.num_iterations = num_iterations

    def __enter__(self):
        self.update()
        return self

    def __exit__(self, *args):
        print()

    def update(self, iteration=0, history=None):
        iteration = iteration + 1
        fraction = ("{0:." + str(self.decimals) + "f}").format(100.0*iteration/self.num_iterations)
        num_filled = int(self.length * iteration // self.num_iterations)
        bar = self.fill * num_filled + '-' * (self.length - num_filled)
        loss = 0.0
        if history:
            try:
                loss = history.history['loss'][-1]
            except:
                loss = history.history['loss']
        print('\rTraining |%s| %s%% complete, loss = %f.' % (bar, fraction, loss), end='\r')


def train(model, X, y, num_epochs, batch_size):
    with ProgressBar(num_epochs) as progress_bar:
        for i in range(num_epochs):
            history = model.fit(X, y, epochs=1, batch_size=batch_size, shuffle=False, verbose=0)
            model.reset_states()
            progress_bar.update(i, history)


@makes_deep_copy
def lstm(feature_matrix, target_matrix, batch_size, num_epochs, num_neurons):
    log.info('LSTM model with {0:d} neurons'.format(num_neurons))
    X, y = feature_matrix, target_matrix[:, 0]
    X = X.reshape(X.shape[0], 1, X.shape[1])
    model = kem.Sequential()
    model.add(kel.LSTM(num_neurons, batch_input_shape=(batch_size, X.shape[1], X.shape[2]), stateful=True))
    model.add(kel.Dense(1))
    model.compile(loss='mean_squared_error', optimizer='adam')
    train(model, X, y, num_epochs, batch_size)
    return model


NormalizerSeq = coll.namedtuple("NormalizerSeq", "time stage production")
NormalizerGrad = coll.namedtuple("NormalizerGrad", "dp_dt_src dp_dt_trg stage_delta")


@makes_deep_copy
def lstmseq(time, production, stage, num_epochs=1000):
    log.info('LSTM sequence model.')

    num_sequences = 1
    num_features = 2 # time and stage delta
    num_targets = 1
    num_timesteps = len(time)

    # sinc this is delta between [i] and [i-1], we loose the first row
    # and assume there is no stage change there, which wouldnt matter anyways
    # so for [0, 0, 1, 1] we produce a delta mapping of 
    #        [0, 0, 1, 0]
    stage_delta = np.zeros_like(stage)
    stage_delta[1:] = np.diff(stage)

    normalizer_stage_delta = skprep.MinMaxScaler(feature_range=(-1, 1))
    normalizer_production = skprep.MinMaxScaler(feature_range=(-1, 1))
    normalizer_time = skprep.MinMaxScaler(feature_range=(-1, 1))

    stage_delta_normalized = normalizer_stage_delta.fit_transform(stage_delta.reshape(-1, 1))
    production_normalized = normalizer_production.fit_transform(production.reshape(-1, 1))
    time_normalized = normalizer_time.fit_transform(time.reshape(-1, 1))
    
    X = np.zeros((num_sequences, num_timesteps, num_features))
    y = np.zeros((num_sequences, num_timesteps, num_targets))

    X[0, :, 0] = time_normalized[:, 0] # first feature is time
    X[0, :, 1] = stage_delta_normalized[:, 0] # second feature is state change
    y[0, :, 0] = production_normalized[:, 0] # only target is production
    
    log.info(X)
    log.info(y)
    
    # expected input data shape: (batch_size, timesteps, data_dim) 
    model = kem.Sequential()
    model.add(kel.LSTM(num_timesteps, input_shape=(num_timesteps, num_features), return_sequences=True))
    model.add(kel.TimeDistributed(kel.Dense(1)))
    model.compile(loss='mean_squared_error', optimizer='adam')
    
    model.summary()
    model.fit(X, y, batch_size=1, epochs=num_epochs)
    return model, NormalizerSeq(normalizer_time, normalizer_stage_delta, normalizer_production)


def predictseq(x, stage, normlizerseq, model):
    assert len(x) == len(stage)
    
    time = np.array(x)
    stage_delta = np.zeros_like(stage)
    stage_delta[1:] = np.diff(stage)
    num_timesteps = len(stage)
    num_features = 2

    stage_delta_normalized = normlizerseq.stage.transform(stage_delta.reshape(-1, 1))
    time_normalized = normlizerseq.time.transform(time.reshape(-1, 1))

    X = np.zeros((1, num_timesteps, num_features))
    X[0, :, 0] = time_normalized[:, 0] # first feature is time
    X[0, :, 1] = stage_delta_normalized[:, 0] # second feature is state change

    yhat_normalized = model.predict(X)
    yhat = normlizerseq.production.inverse_transform(yhat_normalized[0])
    return x, yhat[:, 0]


def predict(y_0, stage, normalizer, model, time=None):
    yhat = [y_0]
    for i in range(1, len(stage)-1): 
        # input is first value, last discarded internally due to grad calc
        yprevious = yhat[-1]
        yinput = [yprevious, 0.0]
        stageinput = stage[i-1:i+1] # contains stage[i-1] and stage[i]
        features = Features(yinput, stageinput)
        features_normalized = normalizer.normalize_features(features)
        features_normalized_timeframe = features_normalized.reshape(features_normalized.shape[0], 
          1, features_normalized.shape[1])
        targets_normalized = model.predict(features_normalized_timeframe, batch_size=1)
        targets = normalizer.denormalize_targets(targets_normalized)
        dy_dt = targets[0, 0] 
        if time is None:
            time_delta = 1.0
        else:
            time_delta = time[i]-time[i-1]
        y_delta = time_delta * dy_dt
        yhat += [yprevious+y_delta]
    return np.array(yhat)


def load(fname):
    return kem.load_model(fname)


def save(model, fname):
    return model.save(fname)


@makes_deep_copy
def lstmseqwin(production, stage, num_epochs=1000, num_timesteps=3, num_units=3,
               offset_forecast=1):
    log.info('LSTM sequence model with window.')
    RNN_t = kel.LSTM
    #RNN_t = kel.SimpleRNN
    num_time = len(production)
    num_sequences = num_time - num_timesteps - offset_forecast
    num_features = 2 # production and stage delta
    
    num_targets = 1
    log.info(num_timesteps)
    
    normalizer_stage = skprep.MinMaxScaler(feature_range=(-1, 1))
    normalizer_production = skprep.MinMaxScaler(feature_range=(0, 1))

    stage_normalized = normalizer_stage.fit_transform(stage.reshape(-1, 1))
    production_normalized = normalizer_production.fit_transform(production.reshape(-1, 1))
    
    X = np.zeros((num_sequences, num_timesteps, num_features))
    y = np.zeros((num_sequences, num_timesteps, num_targets))

    for isequence in range(num_sequences):
        for itimestep in range(num_timesteps):
            ifeature = 0
            X[isequence, itimestep, ifeature] = production_normalized[isequence+itimestep, 0]
            ifeature = 1
            X[isequence, itimestep, ifeature] = stage_normalized[isequence+itimestep+offset_forecast, 0]
            itarget = 0
            y[isequence, itimestep, itarget] = production_normalized[isequence+itimestep+offset_forecast, 0]
        log.info('<sequence', isequence)            
        log.info(X[isequence])
        log.info(y[isequence])
        log.info('sequence', isequence, '>')
    
    # expected input data shape: (batch_size, timesteps, data_dim) 
    batch_size = 1
    model = kem.Sequential()
    model.add(RNN_t(num_units, batch_input_shape=(batch_size, num_timesteps, num_features), 
      return_sequences=True, stateful=True))
    #model.add(RNN_t(1, return_sequences=True, stateful=True))
    #model.add(kel.Dropout(0.33))
    model.add(kel.TimeDistributed(kel.Dense(num_targets, activation='linear')))
    model.compile(loss='mean_squared_error', optimizer='adam')

    reset_state = kec.LambdaCallback(on_epoch_end=lambda *_ : model.reset_states())
    
    model.summary()
    model.fit(X, y, epochs=num_epochs, batch_size=batch_size, shuffle=False,
      callbacks=[reset_state])
    
    return model, NormalizerSeq(None, normalizer_stage, normalizer_production)


def predictseqwin(y_init, stage, normalizer, model, offset_forecast):
    model.reset_states()
    yhat = list(y_init)
    num_timesteps = len(y_init)
    num_y = len(stage)
    num_features = 2 # production and stage delta
    X = np.zeros((1, num_timesteps, num_features))
    for itime in range(num_timesteps, num_y-1):
        stage_window = np.array(stage[itime-num_timesteps+1:itime+1])
        production_window = np.array(yhat[itime-num_timesteps:itime])
        stage_window_normalized = normalizer.stage.transform(stage_window.reshape(-1, 1))
        production_window_normalized = normalizer.production.transform(production_window.reshape(-1, 1))
        X[0, :, 0] = production_window_normalized[:,0]
        X[0, :, 1] = stage_window_normalized[:,0]
        y = model.predict(X, batch_size=1)
        production_predicted = normalizer.production.inverse_transform(y[0])
        yhat += [production_predicted[-offset_forecast, 0]] # always next value
    return np.array(yhat)
    

@makes_deep_copy
def lstmseqwingrad(production, time, stage, num_epochs=1000, num_timesteps=3, num_units=3,
  offset_forecast=1):
    log.info('LSTM gradient sequence model with window.')
    RNN_t = kel.LSTM
    #RNN_t = kel.SimpleRNN
    num_features = 2 # dp_dt and stage delta
    num_targets = 1

    dp_dt = np.diff(production) / np.diff(time)
    stage_delta = np.diff(stage)

    num_time = len(dp_dt)
    assert num_time == len(stage_delta)

    normalizer_stage_delta = skprep.MinMaxScaler(feature_range=(-1, 1))
    normalizer_dp_dt_src = skprep.MinMaxScaler(feature_range=(-1, 1))
    normalizer_dp_dt_trg = skprep.MinMaxScaler(feature_range=(-1, 1))

    stage_delta_normalized = normalizer_stage_delta.fit_transform(stage_delta.reshape(-1, 1))
    dp_dt_src_normalized = normalizer_dp_dt_src.fit_transform(dp_dt.reshape(-1, 1))    
    dp_dt_trg_normalized = normalizer_dp_dt_trg.fit_transform(dp_dt.reshape(-1, 1))    

    num_sequences = num_time - num_timesteps - offset_forecast + 1
    
    X = np.zeros((num_sequences, num_timesteps, num_features))
    y = np.zeros((num_sequences, num_timesteps, num_targets))

    iflat = 0
    for isequence in range(num_sequences):
        for itimestep in range(num_timesteps):
            ifeature = 0
            X[isequence, itimestep, ifeature] = dp_dt_src_normalized[iflat+itimestep, 0]
            ifeature = 1
            X[isequence, itimestep, ifeature] = stage_delta_normalized[iflat+itimestep+offset_forecast, 0]
            itarget = 0
            y[isequence, itimestep, itarget] = dp_dt_trg_normalized[iflat+itimestep+offset_forecast, 0]
        iflat += 1
    idxprint = 5
    #print(dp_dt_src_normalized[:idxprint*2,0])
    print(X[:idxprint,:,:])
    #print(y[:idxprint,:,:])

    #print(X)
    #print(y)
    
    #np.savetxt('y.txt', y)
    #sys.exit()
    # expected input data shape: (batch_size, timesteps, data_dim) 
    batch_size = 1
    model = kem.Sequential()
    model.add(RNN_t(num_units, batch_input_shape=(batch_size, num_timesteps, num_features), 
      stateful=True, return_sequences=True))
    #model.add(kel.Dropout(0.2))
    model.add(kel.TimeDistributed(kel.Dense(1, activation='tanh')))
    #model.add(kel.Dense(num_timesteps))
    model.compile(loss='mean_squared_error', optimizer='adam')

    reset_state = kec.LambdaCallback(on_epoch_end=lambda *_ : model.reset_states())
    
    model.summary()
    model.fit(X, y, epochs=num_epochs, batch_size=batch_size, shuffle=False,
      callbacks=[reset_state])
    
    return model, NormalizerGrad(normalizer_dp_dt_src, normalizer_dp_dt_trg, normalizer_stage_delta)


def predictseqwingrad(y_init, time, stage, normalizer, model, offset_forecast):
    model.reset_states()
    yhat = list(y_init)
    num_features = 2
    num_timesteps = len(y_init) - 1
    num_time = len(time) - num_timesteps - offset_forecast
    X = np.zeros((1, num_timesteps, num_features))
    for itime in range(num_timesteps + 1, num_time):
        stage_window = np.array(stage[itime-num_timesteps:itime+1])        
        production_window = np.array(yhat[itime-num_timesteps-1:itime])
        time_window = np.array(time[itime-num_timesteps-1:itime])
        dp_dt_src = np.diff(production_window) / np.diff(time_window)
        stage_delta = np.diff(stage_window)        
        stage_delta_normalized = normalizer.stage_delta.transform(stage_delta.reshape(-1, 1))
        dp_dt_src_normalized = normalizer.dp_dt_src.transform(dp_dt_src.reshape(-1, 1))
        X[0, :, 0] = dp_dt_src_normalized[:, 0]
        X[0, :, 1] = stage_delta_normalized[:, 0]
        #print(X)
        #input('...')
        y = model.predict(X)
        dp_dt_predicted = normalizer.dp_dt_trg.inverse_transform(y[0])
        dp_dt_predicted = dp_dt_predicted[-offset_forecast, 0]
        time_delta = time[itime] - time[itime-1]
        pprev = yhat[-1]
        yhat += [pprev + time_delta*dp_dt_predicted] #  value at yhat[itime]
    return np.array(yhat)
