"""Frozen multilingual embeddings followed by an ordinary tabular estimator."""

from dataclasses import replace

from app.services.ml.families.base import SpecField
from app.services.ml.families.tabular import TABULAR

TABULAR_DEEP = replace(
    TABULAR,
    key="tabular_deep",
    runtime="ml-deep",
    serving="remote",
    queue_setting="celery_ml_deep_queue",
    serve_queue_setting="celery_ml_deep_serve_queue",
    required_modules=(*TABULAR.required_modules, "torch", "sentence_transformers"),
    spec_fields=(
        SpecField("artifact_id", "artifact"),
        SpecField("text_encoder", "enum", default="embedding", choices=("embedding",)),
        SpecField(
            "embedding_columns",
            "columns",
            required=True,
            max_items=1,
            column_kinds=("text", "categorical", "string"),
        ),
        SpecField("embedding_components", "int", default=30, minimum=2, maximum=128),
        *(field for field in TABULAR.spec_fields if field.key != "text_encoder"),
    ),
)
