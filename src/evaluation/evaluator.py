import glob
import logging
import itertools
import os
import pickle

import numpy as np
import pandas as pd
import time
from sklearn.metrics import classification_report, matthews_corrcoef,\
    accuracy_score, precision_recall_fscore_support

from .plotter import Plotter
from .config import init_logging
from ..preparation import prepare_data
from ..pipeline import run_pipeline
from ..algorithms import Algorithm
from ..utils import create_deep_dict


class Evaluator:
    def __init__(self, name: str, datasets: list, get_predictors: callable, output_dir: {str}=None,
                 create_log_file: bool=True, store: bool=False,
                 n_train_samples: int=60000, n_test_samples: int=6000, downsample: bool=True):
        """
        :param datasets: list of datasets
        :param predictors: callable that returns list of predictors
        """
        self.name = name
        self.datasets = datasets
        self.dataset_names = [str(x) for x in self.datasets]
        assert np.unique(self.dataset_names).size == len(self.dataset_names),\
            'Some datasets have the same name!'
        self.get_predictors = get_predictors
        # Create instances to read out name and repr (incl. seed)
        temp_predictors = self.get_predictors(1)
        self.predictor_names = [repr(x) if isinstance(x, Algorithm) else x.__class__.__name__
                                for x in temp_predictors]
        self.pred_to_algo = dict((repr(p), p.name) for p in temp_predictors)
        assert np.unique(self.predictor_names).size == len(self.predictor_names),\
            'Some predictors have the same name!'
        # Algorithm names may not be unique since they do not contain a seed
        self.output_dir = output_dir or 'reports'
        if create_log_file:
            init_logging(os.path.join(self.output_dir, 'logs'))
        self.logger = logging.getLogger(__name__)
        self.metrics = None
        self.predictions = None
        # Temporary results if the pipeline breaks
        self._metrics = None
        self._predictions = None
        self.plotter = Plotter(self.output_dir, f'figures/exp-{name}')
        self.store = store
        self.downsample = downsample
        self.n_train_samples = n_train_samples
        self.n_test_samples = n_test_samples
        self._temp_pipelines = create_deep_dict(self.dataset_names, self.predictor_names)

    def __call__(self):
        multiindex = pd.MultiIndex.from_product([self.dataset_names, self.predictor_names],
                                                names=['datasets', 'predictors'])
        # metrics = create_deep_dict(self.dataset_names, self.predictor_names)
        self._metrics = pd.DataFrame(0, index=['prec', 'rec', 'f1', 'acc', 'mcc'],
                                     columns=multiindex)
        self._metrics.sort_index(axis=1, inplace=True)
        # Might be required if datasets have different sizes
        # predictions = create_deep_dict(self.dataset_names, self.predictor_names)
        self._predictions = pd.DataFrame(0, index=range(self.n_test_samples), columns=multiindex)
        for ds in self.datasets:
            self.logger.info(f"{'-'*10} Prepare dataset {'-'*10}")
            data = prepare_data(ds, self.n_train_samples, self.n_test_samples,
                                downsample=self.downsample)
            n_features = len(data[0].columns.levels[1])
            predictors = self.get_predictors(n_features)
            for predictor, predictor_name in zip(predictors, self.predictor_names):
                self._execute_predictor(ds, predictor, predictor_name, data)
        self.predictions = self._predictions
        self.metrics = self.get_metrics_conclusion()
        if self.store:
            self.export_results()
            self.metrics.to_csv(os.path.join(self.output_dir, f'custom/{self.name}.csv'))
            self.plot_histories()
        return self.metrics

    def _execute_predictor(self, ds, predictor, predictor_name, data):
        self.logger.info(f"{'-'*10} {predictor_name} | {ds} {'-'*10}")
        pipeline, y_pred = run_pipeline(predictor, data)
        time.sleep(1)  # TODO: Why did I do this?
        y_pred = y_pred.clip(-1, 1)
        ev = self.measure_pipeline_run_results(data[3], y_pred)
        if len(y_pred) != self.n_test_samples:
            self.logger.warn(
                f'Not enough self._predictions are available. Check the data distribution!')
        self._predictions.loc[:len(y_pred)-1, (str(ds), predictor_name)] = y_pred
        assert all(self._metrics.index == list(ev.keys()))
        self._metrics.loc[:, (str(ds), predictor_name)] = ev.values()
        self._temp_pipelines[str(ds)][predictor_name] = pipeline, y_pred

    def measure_pipeline_run_results(self, y_true, y_pred):
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        prec, rec, f1, _ = precision_recall_fscore_support(y_true, y_pred, average='weighted')
        acc = accuracy_score(y_true, y_pred)
        mcc = matthews_corrcoef(y_true, y_pred)
        target_names = np.array(['Down', 'Still', 'Up'])[np.unique(y_true).astype(int) + 1]
        self.logger.debug(
            f'\n{classification_report(y_true, y_pred, target_names=target_names)}\n\nMCC='
            f'{mcc:.5f}, Accuracy={acc:.5f}, Precision={prec:.5f}, Recall={rec:.5f}, F1={f1:.5f}')
        return {
            'prec': round(prec, 5),
            'rec': round(rec, 5),
            'f1': round(f1, 5),
            'acc': round(acc, 5),
            'mcc': round(mcc, 5)
        }

    # Merge runs with same algorithms but different seeds (represented by mean and std)
    def get_metrics_conclusion(self):
        metrics = self._metrics
        predictors = pd.DataFrame(list(metrics.columns), columns=['l1', 'l2'])
        predictors['algo'] = [self.pred_to_algo[p] for _, (_, p) in predictors.iterrows()]
        merged_metrics = []
        for (ds, algo), matches in predictors.groupby(['l1', 'algo']):
            regarding_metrics = metrics[[(ds, x) for x in matches.l2]]
            if regarding_metrics.shape[1] == 1:
                merged_metrics.append((f'{ds} {algo}', *regarding_metrics.iloc[:, 0]))
            else:
                means = regarding_metrics.mean(axis=1).round(5)
                stds = regarding_metrics.std(axis=1).round(5)
                merged_metrics.append(
                    (f'{ds} {algo}', *[f'{m} +- {s}' for m, s in zip(means, stds)]))
        merged_metrics = pd.DataFrame(merged_metrics, columns=['predictor', *metrics.index])
        merged_metrics.index = merged_metrics.predictor
        merged_metrics = merged_metrics.T.iloc[1:]
        return merged_metrics

    def get_predictor(self, ds_i, predictor_i):
        ds_name = self.dataset_names[ds_i] if isinstance(ds_i, int) else ds_i
        pred_name = self.predictor_names[predictor_i] if \
            isinstance(predictor_i, int) else predictor_i
        return self._temp_pipelines[ds_name][pred_name][0].steps[-1][1]

    # ----- Plotting --------------------------------------------------------- #

    def plot_histories(self, store=True):
        for ds, pred in itertools.product(self.dataset_names, self.predictor_names):
            predictor = self.get_predictor(ds, pred)
            if hasattr(predictor, 'history') and predictor.history is not None:
                self.plotter.plot_history(predictor.history, f'{pred} on {ds}', store=store)

    # ----- Utils ------------------------------------------------------------ #

    def get_model_summary(self, ds_i, predictor_i):
        return self.get_predictor(ds_i, predictor_i).model.summary()

    def get_models_input(self, ds_i, predictor_i):
        ds = self.datasets[ds_i]
        ds_name = self.dataset_names[ds_i]
        pred_name = self.predictor_names[predictor_i]
        data = prepare_data(ds, self.n_train_samples, self.n_test_samples)
        X_train = data[0]
        pipeline = self._temp_pipelines[ds_name][pred_name][0]
        X_train = pipeline.steps[0][1].transform(X_train)
        X_train = pipeline.steps[1][1].transform(X_train)
        X_train = pipeline.steps[2][1].transform(X_train)
        return X_train

    def get_mcc_metric(self, metrics=None):
        metrics = metrics or self.metrics
        mcc_flatten = metrics.loc['mcc'].reset_index()
        mcc = mcc_flatten.pivot(*mcc_flatten.columns)  # index, column, value
        return mcc

    def export_results(self):
        output_dir = os.path.join(self.output_dir, 'evaluators')
        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime('%Y-%m-%d-%H%M%S')
        path = os.path.join(output_dir, f'{self.name}-{timestamp}.pkl')
        self.logger.info(f'Store evaluator results at {os.path.abspath(path)}')
        save_dict = {
            'name': self.name,
            'dataset_names': self.dataset_names,
            'predictor_names': self.predictor_names,
            # 'pred_to_algo': self.pred_to_algo,
            'output_dir': self.output_dir,
            '_metrics': self._metrics,
            'predictions': self.predictions,
            'downsample': self.downsample,
            'n_train_samples': self.n_train_samples,
            'n_test_samples': self.n_test_samples,
        }
        with open(path, 'wb') as f:
            pickle.dump(save_dict, f)
        return path

    # Import metrics & predictions if this evaluator uses the same datasets and predictors
    # If you want to import old evaluators (before 22.01.2019) you need to adapt the code:
    # The save_dict will only contain dataset_names, predictor_name, metrics and output_dir
    def import_results(self):
        output_dir = os.path.join(self.output_dir, 'evaluators')
        path_regex = os.path.join(output_dir, f'{self.name}-20*.pkl')  # Wildcard should only match dates
        matches = glob.glob(path_regex)
        path = matches[-1]
        if len(matches) == 0:
            self.logger.error('No evaluator with this name was found in the output directory.')
            return
        elif len(matches) > 1:
            self.logger.info(f'Found {len(matches)} possible matches. Selecting the latest one.')
        self.logger.info(f'Read evaluator results at {os.path.abspath(path)}')
        with open(path, 'rb') as f:
            save_dict = pickle.load(f)

        assert np.array_equal(save_dict['dataset_names'], self.dataset_names), \
            'Datasets do not match'
        assert np.array_equal(save_dict['predictor_names'], self.predictor_names), \
            'Predictors do not match'
        # assert save_dict['output_dir'] == self.output_dir, 'Output directory does not match'
        self._metrics = save_dict['_metrics']
        self.metrics = self.get_metrics_conclusion()
        self.predictions = save_dict['predictions']
        self.downsample = save_dict['downsample']
        self.n_train_samples = save_dict['n_train_samples']
        self.n_test_samples = save_dict['n_test_samples']
        # self.name = name
        return self
