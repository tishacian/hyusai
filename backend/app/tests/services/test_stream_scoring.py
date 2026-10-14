"""Cardinality, bounded batches and truthful inference evidence."""
import pyarrow as pa
import pytest

from app.services.dataops.scoring import score_batches


def test_stream_scoring_preserves_every_row_with_bounded_evidence():
    batches=(pa.record_batch({"id":list(range(i,i+1000)),"value":[float(j) for j in range(1000)]}) for i in range(0,100000,1000))
    def predict(batch):
        return [{"prediction":"yes" if value>500 else "no","confidence":0.9,"score":value/1000} for value in batch.column("value").to_pylist()]
    generated,evidence=score_batches(batches,predict_batch=predict,task="classification",positive_label="yes")
    count=0
    for batch in generated:
        count+=batch.num_rows
        assert batch.num_rows==1000 and batch.schema.names[-1]=="score_yes"
    assert count==evidence["scored_rows"]==evidence["input_rows"]==100000
    assert len(evidence["sample_answers"])==len(evidence["sample_inputs"])==64
    assert sum(evidence["classes"].values())==count


def test_incomplete_answers_and_cancel_never_become_complete():
    batch=pa.record_batch({"id":[1,2]})
    generator,_=score_batches([batch],predict_batch=lambda _:[],task="regression")
    with pytest.raises(ValueError,match="CARDINALITY"):
        list(generator)
    generator,_=score_batches([batch],predict_batch=lambda _:[],task="regression",should_cancel=lambda:True)
    with pytest.raises(ValueError,match="CANCELLED"):
        list(generator)


def test_scoring_limit_and_nonfinite_are_fail_closed():
    batch=pa.record_batch({"id":[1,2]})
    generator,_=score_batches([batch],predict_batch=lambda b:[{"prediction":1.0}]*2,task="regression",max_rows=1)
    with pytest.raises(ValueError,match="TOO_MANY"):
        list(generator)
    generator,_=score_batches([batch],predict_batch=lambda b:[{"prediction":float("inf")}]*2,task="regression")
    with pytest.raises(ValueError,match="NONFINITE"):
        list(generator)
