"""High-cardinality text stays inside the sklearn pipeline and needs no torch."""
from __future__ import annotations

import pandas as pd
import polars as pl
import pytest

from app.services.tabular_datasets import profile_frame
from app.tests.services.test_ml_training import _run_harness


def tickets(rows=240):
    return pd.DataFrame({
        'message': [
            (f'I cannot login to my account, please unlock my password for ticket {index} today.'
             if index % 2 else f'My payment was charged twice, please refund this invoice for ticket {index} today.')
            for index in range(rows)
        ],
        'category': ['access' if index % 2 else 'billing' for index in range(rows)],
    })


def test_text_profile_measures_characters_on_full_column():
    frame = pl.DataFrame({'words': ['éclair', '漢字', None], 'number': [1, 2, 3]})
    profile = profile_frame(frame)
    assert profile['stats']['words']['mean_length'] == 4
    assert 'mean_length' not in profile['stats']['number']
    assert profile_frame(pl.DataFrame({'empty': pl.Series([None], dtype=pl.String)}))['stats']['empty']['mean_length'] is None


@pytest.mark.parametrize('encoder,seed', [('auto', 42), ('string', 42), ('minhash', 42), ('string', 0)])
def test_ticket_classifier_saves_the_selected_encoder_and_serves_unseen_text(tmp_path, encoder, seed):
    data = tickets()
    data_path = tmp_path / 'tickets.parquet'
    data.to_parquet(data_path)
    manifest = {
        'data_path': str(data_path), 'model_dir': str(tmp_path / 'model'),
        'task': 'classification', 'algo': 'linear', 'target': 'category',
        'features': ['message'], 'spec': {'text_encoder': encoder},
        'estimator': 'sklearn.linear_model.LogisticRegression',
        'params': {'C': 10, 'max_iter': 500, 'random_state': seed},
        'random_state': seed, 'min_rows': 40, 'cv': 0, 'importance_rows': 60,
    }
    code, summary, stderr = _run_harness(tmp_path / 'run', manifest)
    assert code == 0, stderr
    assert summary['metrics']['primary']['value'] >= .9
    import mlflow.sklearn
    model = mlflow.sklearn.load_model(manifest['model_dir'])
    chosen = model.named_steps['tablevectorizer'].high_cardinality
    assert type(chosen).__name__ == ('MinHashEncoder' if encoder == 'minhash' else 'StringEncoder')
    if encoder == 'string':
        assert chosen.random_state == seed
    if encoder == 'auto':
        assert chosen.random_state is None
    prediction = model.predict(pd.DataFrame({'message': ['Please refund my invoice, the payment was charged twice on ticket 99999 today.']}))
    assert prediction.tolist() == ['billing']
    assert all(not item.startswith(('torch.', 'transformers.')) for item in summary['trusted_types'])


@pytest.mark.parametrize('kind,distinct,length,expected', [
    ('string', 41, 20, True), ('string', 40, 30, False), ('string', 41, 19.9, False),
    ('integer', 100, 30, False), ('string', 100, None, False),
])
def test_text_role_and_identifier_warning_share_one_threshold(kind, distinct, length, expected):
    from app.services.tabular_ml import is_text_column
    assert is_text_column(kind, {'distinct': distinct, 'mean_length': length}) is expected
