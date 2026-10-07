"""Search has one translation, a real baseline, train-only folds and a hard clock."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pandas as pd
import pytest
from sklearn.datasets import make_regression

from app.core.config import settings
from app.models.tabular import MLModel
from app.resources.ml_knob_translation import translate
from app.resources.ml_train_harness import _tune
from app.services import tabular_ml
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_training import (  # noqa: F401
    dataset, enabled, store, workspace, churn_parquet, _manifest_for, _run_harness,
)


def _config(**overrides):
    config = {
        'algo': 'linear', 'task': 'regression', 'estimator': 'sklearn.linear_model.Ridge',
        'random_state': 42, 'tuning': {
            'trials': 8, 'budget_s': 10, 'metric': 'r2', 'direction': 'max', 'folds': 3,
            'start': {'alpha': 1.0, 'max_iter': 500},
            'space': [{'key': 'alpha', 'kind': 'float', 'low': .001, 'high': 20, 'log': True}],
            'forest_leaves': 2048,
        },
    }
    config.update(overrides)
    return config


def _data(rows=150):
    x, y = make_regression(n_samples=rows, n_features=4, noise=8, random_state=42)
    return pd.DataFrame(x, columns=list('abcd')), pd.Series(y)


def test_translation_agrees_for_random_catalog_knobs(monkeypatch):
    rng = random.Random(42)
    monkeypatch.setattr(settings, 'ml_train_random_state', 71)
    for algo in tabular_ml.ALGOS:
        for task in algo.estimators:
            for _ in range(20):
                raw = {k.key: rng.uniform(k.minimum, k.maximum) for k in algo.knobs}
                knobs = algo.resolve(raw)
                assert tabular_ml.estimator_params(algo, task, knobs) == translate(
                    algo.key, task, knobs, random_state=71, forest_leaves=2048)
    assert translate('linear', 'classification', {'alpha': 2}, random_state=1, forest_leaves=2048)['C'] == .5
    assert translate('random_forest', 'regression', {'max_depth': None}, random_state=1, forest_leaves=2048)['max_leaf_nodes'] == 2048


def test_search_is_seeded_and_best_includes_exact_form_baseline():
    config = _config()
    params, first = _tune(config, *_data())
    _, second = _tune(config, *_data())
    assert first['start']['knobs'] == config['tuning']['start']
    assert first['best']['score'] >= first['start']['score']
    assert first['best'] == second['best']
    assert [r['score'] for r in first['trials']] == [r['score'] for r in second['trials']]
    assert first['elapsed_s'] <= 11
    assert len(first['trials']) == 8
    assert params['alpha'] == first['best']['knobs']['alpha']
    assert len(json.dumps(first)) < 20_000
    assert all('knobs' not in trial for trial in first['trials'])


def test_automatic_depth_is_exact_in_baseline_and_finite_in_search():
    config = _config(algo='random_forest', estimator='sklearn.ensemble.RandomForestRegressor')
    config['tuning'].update(trials=3, budget_s=20, start={'max_depth': None, 'n_estimators': 50, 'min_samples_leaf': 1},
                           space=[{'key': 'max_depth', 'kind': 'int', 'low': 1, 'high': 8}])
    _, summary = _tune(config, *_data())
    assert summary['start']['knobs']['max_depth'] is None
    assert summary['start']['score'] is not None
    assert summary['trials_run'] == 3
    assert summary['best']['score'] >= summary['start']['score']


def test_deadline_kills_an_unfinished_fit_and_preserves_form_settings():
    config = _config(algo='random_forest', estimator='sklearn.ensemble.RandomForestRegressor')
    config['tuning'].update(budget_s=4, start={'max_depth': None, 'n_estimators': 600, 'min_samples_leaf': 1}, space=[])
    started = time.monotonic()
    _, summary = _tune(config, *_data(15000))
    assert time.monotonic() - started < 4.8
    assert summary['elapsed_s'] <= 4.4
    assert summary['stopped_by'] == 'budget'
    assert summary['warning'] == 'ML_TUNING_BASELINE_UNAVAILABLE'
    assert summary['best']['knobs'] == config['tuning']['start']
    assert summary['start']['score'] is None


def test_search_child_receives_only_train_rows_not_original_dataset(monkeypatch):
    import joblib
    original = joblib.dump
    observed = []
    def capture(value, path):
        observed.append(value)
        return original(value, path)
    monkeypatch.setattr(joblib, 'dump', capture)
    config = _config(data_path='/must/not/read/test.parquet', forbidden_test='sentinel')
    config['tuning']['budget_s'] = .001
    x, y = _data()
    _tune(config, x, y)
    child, rows, target = observed[0]
    assert 'data_path' not in child and 'forbidden_test' not in child
    assert rows is x and target is y


def test_tuning_budget_cannot_consume_final_fit_time(dataset, enabled, monkeypatch):
    monkeypatch.setattr(settings, 'ml_train_timeout_s', 100)
    with pytest.raises(TabularError) as caught:
        tabular_ml.validate_training(dataset, task='classification', target='churn',
                                    spec={'tuning': 'budget', 'tuning_budget_s': 61})
    assert caught.value.code == 'ML_SPEC_INVALID'
    assert caught.value.details['field'] == 'tuning_budget_s'
    spec = tabular_ml.validate_training(dataset, task='classification', target='churn',
                                       spec={'tuning': 'budget', 'tuning_budget_s': 60})
    config = tabular_ml.tuning_configuration(spec)
    assert config['metric'] == 'roc_auc' and config['direction'] == 'max'
    assert config['start'] == spec.knobs


def test_summary_records_the_knobs_the_final_estimator_used():
    model = MLModel(algo='linear', task='classification', params_json={'knobs': {'alpha': 1, 'max_iter': 500}})
    tabular_ml._apply_summary(model, {'metrics': {'tuning': {'best': {'knobs': {'alpha': 2, 'max_iter': 200}}}}})
    assert model.params_json['knobs'] == {'alpha': 2, 'max_iter': 200}
    assert model.params_json['estimator_params']['C'] == .5
    assert model.params_json['tuned'] is True


def test_real_harness_scores_and_saves_the_selected_model(churn_parquet, tmp_path):
    config = _config(algo='linear', task='classification', estimator='sklearn.linear_model.LogisticRegression')
    config['tuning'].update(metric='roc_auc', budget_s=15, trials=5)
    manifest = _manifest_for(churn_parquet, tmp_path, **config)
    code, summary, stderr = _run_harness(tmp_path / 'run', manifest)
    assert code == 0, stderr
    tuning = summary['metrics']['tuning']
    assert tuning['best']['score'] >= tuning['start']['score']
    assert summary['metrics']['rows']['test'] == 100
    assert any(score['key'] == 'roc_auc' for score in summary['metrics']['scores'])
    import mlflow.sklearn
    model = mlflow.sklearn.load_model(manifest['model_dir'])
    assert model.steps[-1][1].C == round(1 / tuning['best']['knobs']['alpha'], 6)
    progress = Path(manifest['progress_path']).read_text()
    assert progress.index('tuning:') < progress.index('fitting:')


def test_tuning_manifest_uses_knob_space_and_keeps_the_automatic_baseline(dataset, enabled, db_session, tmp_path):
    spec = tabular_ml.validate_training(dataset, task='classification', target='churn', algo='random_forest',
                                       spec={'tuning': 'budget', 'tuning_trials': 5, 'tuning_budget_s': 30})
    model = tabular_ml.create_model(db_session, workspace_id=dataset.workspace_id, spec=spec)
    path = tabular_ml._write_manifest(tmp_path, model, Path('train.parquet'))
    tuning = json.loads(path.read_text())['tuning']
    assert tuning['start']['max_depth'] is None
    depth = next(field for field in tuning['space'] if field['key'] == 'max_depth')
    assert depth['low'] == 1 and depth['high'] == 40
    assert tuning['metric'] == 'roc_auc'
    assert tuning['folds'] == 3


def test_pruning_reports_folds_and_failed_trials_do_not_discard_baseline(tmp_path, monkeypatch):
    import optuna
    from app.resources.ml_tuning_harness import search
    config = _config()
    monkeypatch.setattr(optuna.pruners, 'MedianPruner', lambda **_: optuna.pruners.ThresholdPruner(lower=2))
    output = tmp_path / 'pruned.json'
    search(config, *_data(), output)
    summary = json.loads(output.read_text())
    assert summary['trials_pruned'] == config['tuning']['trials'] - 1
    assert summary['best']['trial'] == 0
    assert summary['best']['score'] == summary['start']['score']

    config = _config(algo='knn', estimator='sklearn.neighbors.KNeighborsRegressor')
    config['tuning'].update(start={'n_neighbors': 1}, space=[{'key': 'n_neighbors', 'kind': 'int', 'low': 80, 'high': 100}])
    # Baseline may be outside the sampled range: enqueue still preserves it.
    search(config, *_data(30), output)
    summary = json.loads(output.read_text())
    assert summary['trials_failed'] > 0
    assert summary['best']['knobs'] == {'n_neighbors': 1}
    assert summary['best']['score'] == summary['start']['score']
