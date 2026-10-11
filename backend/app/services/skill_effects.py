"""Effects shared by AgentLoop visibility and verified executor binding.

These data-plane writes require an explicit Flow node. An authored registry
alias must not inject graph-owned blocks after the DAG stripped caller inputs.
Prediction aliases remain supported: they do not train or materialize datasets.
"""

EXPLICIT_DATA_WRITE_SKILLS = frozenset(
    {
        "ml_train_sklearn_v1",
        "ml_retrain_model_v1",
        "ml_monitor_model_v1",
        "ml_batch_score_v1",
        "llm_label_dataset_v1",
        "hf_dataset_import_v1",
        "sql_transform_v1",
        "polars_transform_v1",
        "dbt_transform_v1",
        "python_recipe_v1",
    }
)
