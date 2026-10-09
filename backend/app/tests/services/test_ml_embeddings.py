"""Frozen embeddings, ordinary tasks and inference isolated from the API."""
import hashlib
import json
import os
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.tabular import MLModel, MLPrediction
from app.models.workspace import Workspace
from app.services import tabular_ml, tabular_predict
from app.services.ml import deep_serving, runtime
from app.services.ml.artifacts import verify_bundle
from app.services.tabular_datasets import TabularError


@pytest.fixture
def enabled(monkeypatch):
    for key in ('ml_train_enabled', 'tabular_data_enabled', 'ml_predict_enabled'):
        monkeypatch.setattr(settings, key, True)
    monkeypatch.setattr(settings, 'worker_eager_mode', False)
    monkeypatch.setattr(settings, 'ml_runtime', 'worker')
    monkeypatch.setattr(tabular_ml, 'family_availability', lambda *a, **kw: (True, None))
    monkeypatch.setattr(runtime, 'model_availability', lambda *a, **kw: (True, None))


@pytest.fixture
def dataset():
    return SimpleNamespace(id=uuid4().hex, name='Tickets', status='ready', row_count=100, lineage_json={}, produced_by=None,
                           schema_json=[{'name': 'text', 'kind': 'text'}, {'name': 'amount', 'kind': 'numeric'}, {'name': 'label', 'kind': 'categorical'}],
                           stats_json={'text': {'distinct': 100}, 'amount': {'distinct': 100}, 'label': {'distinct': 2}})


def validate(dataset, **kw):
    body = dict(target='label', task='classification', features=['text', 'amount'], algo='linear', knobs={}, test_size=.25,
                cross_validation=0, name='Tickets', spec={'text_encoder': 'embedding', 'embedding_columns': ['text']})
    return tabular_ml.validate_training(dataset, **{**body, **kw})


def test_embedding_keeps_task_but_selects_deep_runtime(enabled, dataset):
    selected = validate(dataset)
    assert selected.family == 'tabular_deep' and selected.task == 'classification'
    assert selected.spec['embedding_components'] == 30
    assert validate(dataset, spec={'text_encoder': 'auto'}).family == 'tabular'


@pytest.mark.parametrize('change', [{'embedding_columns': []}, {'embedding_columns': ['label']}, {'embedding_columns': ['amount']},
    {'embedding_columns': ['missing']}, {'embedding_components': 0}, {'tuning': 'budget'}, {'explain': 'pack'}, {'calibration': 'sigmoid'}, {'threshold': 'f1'}])
def test_invalid_or_unbounded_options_are_refused(enabled, dataset, change):
    with pytest.raises(TabularError):
        validate(dataset, spec={'text_encoder': 'embedding', 'embedding_columns': ['text'], **change})


def test_columns_must_be_features_and_additional_fits_are_refused(enabled, dataset):
    for overrides in ({'features': ['amount']}, {'cross_validation': 3}):
        with pytest.raises(TabularError):
            validate(dataset, **overrides)


def test_asset_absent_hides_capability_and_refuses_submission(enabled, dataset, monkeypatch):
    monkeypatch.setattr(runtime, 'model_availability', lambda *a, **kw: (False, 'model_missing'))
    with pytest.raises(TabularError) as error:
        validate(dataset)
    assert error.value.code == 'ML_DEEP_MODEL_MISSING'
    family = next(f for f in tabular_ml.catalog_payload()['families'] if f['key'] == 'tabular_deep')
    assert not family['available'] and family['reason'] == 'model_missing'


def test_bundle_rejects_changed_and_unlisted_files(tmp_path):
    (tmp_path/'MLmodel').write_text('flavor')
    (tmp_path/'model.pkl').write_bytes(b'weights')
    artifact = {'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}}
    verify_bundle(tmp_path, artifact)
    (tmp_path/'model.pkl').write_bytes(b'changed')
    with pytest.raises(TabularError) as error:
        verify_bundle(tmp_path, artifact)
    assert error.value.code == 'ML_ARTIFACT_TAMPERED'
    (tmp_path/'model.pkl').write_bytes(b'weights')
    (tmp_path/'extra.py').write_text('untrusted')
    with pytest.raises(TabularError):
        verify_bundle(tmp_path, artifact)


def test_model_cannot_load_in_api_runtime(enabled):
    model = SimpleNamespace(status='ready', family='tabular_deep', task='classification')
    with pytest.raises(TabularError) as error:
        tabular_predict.load_pipeline_traced(model)
    assert error.value.code == 'ML_RUNTIME_MISSING'


@pytest.fixture
def model(db_session):
    space = Workspace(id=uuid4().hex, name='Embedding tests', slug=uuid4().hex, settings={})
    db_session.add(space)
    db_session.flush()
    row = MLModel(id=uuid4().hex, workspace_id=space.id, name='Tickets', slug=uuid4().hex, version=1, task='classification',
                  family='tabular_deep', algo='linear', target='label', features=['text'], status='ready', is_champion=True,
                  classes_json=['billing', 'network'], signature_json={'inputs': [{'name': 'text', 'type': 'string', 'kind': 'text'}]},
                  params_json={}, metrics_json={}, dataset_slug='tickets', row_count=100, test_size=.25, cross_validation=0)
    db_session.add(row)
    db_session.commit()
    return row


def test_rpc_pins_version_and_api_journals_once(enabled, db_session, model, monkeypatch):
    calls = []
    def remote(db, served, rows, **kwargs):
        calls.append((served.id, rows))
        return {'predictions': [{'prediction': 'network', 'confidence': .9, 'score': .9}], 'classes': ['billing', 'network'],
                'positive_label': 'network', 'duration_ms': 12, 'load_ms': 0, 'cached': True}
    monkeypatch.setattr(deep_serving, 'request_rows', remote)
    monkeypatch.setattr(tabular_predict, 'load_pipeline_traced', lambda *a: pytest.fail('API loaded weights'))
    result = tabular_predict.predict_rows(db_session, model, [{'text': 'réseau coupé'}], version=1)
    assert calls == [(model.id, [{'text': 'réseau coupé'}])]
    assert result['prediction_id']
    assert db_session.query(MLPrediction).filter_by(model_id=model.id).count() == 1


def test_rpc_timeout_uses_deep_queue_and_forgets_result(enabled, db_session, model, monkeypatch):
    from app.workers.celery_app import celery_app
    from celery.exceptions import TimeoutError
    monkeypatch.setattr(runtime, 'serving_availability', lambda *a: (True, None))
    sent = {}
    class Pending:
        def get(self, **kw):
            assert kw['propagate'] is False
            raise TimeoutError()
        def forget(self):
            sent['forgotten'] = True
    def send(name, **kwargs):
        sent.update(name=name, **kwargs)
        return Pending()
    monkeypatch.setattr(celery_app, 'send_task', send)
    with pytest.raises(TabularError) as error:
        deep_serving.request_rows(db_session, model, [{'text': 'hi'}])
    assert error.value.code == 'ML_PREDICT_TIMEOUT'
    assert sent['queue'] == settings.celery_ml_deep_serve_queue and sent['args'][0] == model.id and sent['forgotten']


def test_worker_rejects_wrong_runtime(enabled):
    assert deep_serving.answer_for('missing', [{'text': 'hi'}])['error']['code'] == 'ML_RUNTIME_MISSING'


@pytest.mark.parametrize('task', ['classification', 'regression'])
def test_real_export_loads_offline_after_source_disappears(tmp_path, task):
    model_dir = os.environ.get('ML_DEEP_TEST_EMBEDDING_DIR')
    if not model_dir:
        pytest.skip('Provision the multilingual encoder to exercise the deep runtime')
    import numpy as np
    import pandas as pd
    import mlflow.pyfunc
    from app.resources import ml_train_harness
    source = tmp_path/'source'
    source.symlink_to(model_dir, target_is_directory=True)
    rows = pd.DataFrame([{'text': ('network connection lost' if i % 2 else 'paiement facture')+f' ticket {i}',
                          'amount': float(i % 7), 'label': str(i % 2) if task == 'classification' else float(i % 7 + (i % 2) * 10)} for i in range(64)])
    rows.to_parquet(tmp_path/'data.parquet')
    manifest = {'family': 'tabular_deep', 'task': task, 'algo': 'linear', 'target': 'label', 'features': ['text', 'amount'],
                'estimator': 'sklearn.linear_model.LogisticRegression' if task == 'classification' else 'sklearn.linear_model.Ridge',
                'params': {'max_iter': 100, 'random_state': 42}, 'random_state': 42, 'data_path': str(tmp_path/'data.parquet'),
                'model_dir': str(tmp_path/'model'), 'test_size': .25, 'min_rows': 40, 'importance_rows': 10, 'curve_points': 10,
                'report_state_limit_mb': 0, 'spec': {'text_encoder': 'embedding', 'embedding_columns': ['text'], 'embedding_components': 5,
                '_embedding_path': str(source)}, 'foundation': {'model_id': 'multilingual-minilm', 'revision': 'fixed'}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    result = subprocess.run([os.sys.executable, ml_train_harness.__file__, str(tmp_path/'manifest.json'), str(tmp_path/'result.json')],
                env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'},
                capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr[-3000:]
    summary = json.loads((tmp_path/'result.json').read_text())
    assert summary['metrics']['embedding']['frozen'] is True
    assert summary['artifact']['serialization'] == 'cloudpickle'
    verify_bundle(tmp_path/'model', summary['artifact'])
    source.unlink()
    restored = mlflow.pyfunc.load_model(str(tmp_path/'model'))
    before = restored.predict(rows[['text', 'amount']].head(4))
    again = mlflow.pyfunc.load_model(str(tmp_path/'model')).predict(rows[['text', 'amount']].head(4))
    np.testing.assert_array_equal(before, again)
    vectorizer = restored._model_impl.sklearn_model.named_steps['tablevectorizer']
    encoder = vectorizer.transformers_['text']
    assert encoder.store_weights_in_pickle
    assert encoder.pca_.n_samples_ == 48


def test_embedding_worker_lifecycle_uses_frozen_asset_and_serves_predictions(tmp_path, db_session, enabled, monkeypatch):
    source = os.environ.get('ML_DEEP_TEST_EMBEDDING_DIR')
    if not source:
        pytest.skip('Provision the multilingual encoder to exercise the supervised worker')
    import polars as pl
    from pathlib import Path
    from app.services.ml import local_models
    from app.services.tabular_datasets import register_frame
    folder = Path(source)
    files = {str(path.relative_to(folder)): local_models.file_hash(path) for path in folder.rglob('*') if path.is_file()}
    local = local_models.LocalModel(path=folder, model_id='multilingual-minilm', revision='e8f8c211226b894fcb81acc59f3b34ba3efd5f42',
                                   kind='embedding', fingerprint=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
                                   upstream_id='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', files=files)
    monkeypatch.setattr(local_models, 'resolve_model', lambda *a, **kw: local)
    monkeypatch.setattr(runtime, 'model_descriptors', lambda *a, **kw: {'multilingual-minilm': local.public()})
    monkeypatch.setattr(settings, 'ml_runtime', 'ml-deep')
    monkeypatch.setattr(settings, 'object_store_backend', 'local')
    monkeypatch.setattr(settings, 'object_store_base_path', str(tmp_path/'store'))
    monkeypatch.setattr(settings, 'ml_train_timeout_s', 180)
    space = Workspace(id=uuid4().hex, name='Real embeddings', slug=uuid4().hex, settings={})
    db_session.add(space)
    db_session.flush()
    dataset = register_frame(db_session, workspace_id=space.id, name='Tickets', source='generated', produced_by='test',
        frame=pl.DataFrame([{'text': ('réseau perdu' if i % 2 else 'paiement facture')+f' numéro {i}', 'amount': float(i % 5), 'label': str(i % 2)} for i in range(64)]))
    selected = validate(dataset, spec={'text_encoder': 'embedding', 'embedding_columns': ['text'], 'embedding_components': 5})
    row = tabular_ml.create_model(db_session, workspace_id=space.id, spec=selected)
    db_session.commit()
    assert row.params_json['foundation']['fingerprint'] == local.fingerprint
    result = tabular_ml.run_training(row.id)
    db_session.refresh(row)
    assert result['status'] == 'ready', row.error
    assert row.runtime_json['runtime'] == 'ml-deep' and row.metrics_json['artifact']['files']
    answer = tabular_predict.predict_rows(db_session, row, [{'text': 'réseau perdu', 'amount': 1.0}], version=row.version)
    assert answer['rows'] == 1 and answer['predictions'][0]['prediction'] in {'0', '1'}
    tabular_predict.reset_cache()
