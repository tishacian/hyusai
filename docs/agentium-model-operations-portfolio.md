# Model operations in the Systems portfolio

Model Center owns the configuration of scheduled monitoring and retraining. A
monitoring System belongs to one model version, while the model lineage may be
referenced by several business Systems. Those references are navigation evidence,
not an exclusive business owner or a financial allocation.

## Product behavior

- The Systems grid opens on **Business**, with visible **Model operations** and
  **All** filters and their counts. Each operation retains its Flow, run statistics
  and a compact **View model** action.
- Model Center → Monitoring shows the managed monitoring Flow and the business
  Flows explicitly referencing the model lineage. Each node identifies whether
  it follows the champion or pins a version; references to other versions in the
  lineage remain visible.
- The read model includes native `ml_predict_v1`, `ml_batch_score_v1` and
  `ml_forecast_v1` nodes with explicit model parameters. Runtime-selected models,
  agent tool choices, custom published Skill executors and editable drafts are
  not inferred. This is not a replacement for invocation evidence in Runs.
- The immutable published version is read when a publication pointer exists.
  Legacy Systems without one use their executable Flow; unpublished legacy
  drafts are excluded. Retired Systems remain available through the existing
  explicit `include_retired` option.

## API and compatibility

`GET /systems` still returns both business and model-operation Systems by
default. Serialization adds `category` (`business` or `model_operations`) and
`model_operation` (`null` or `{kind: "model_monitoring", model_id: "…"}`).

Optional collection filters:

```text
GET /systems?category=model_operations
GET /systems?category=business
GET /systems?uses_model_id=<model-version-id>
```

`uses_model_id` is workspace-scoped and returns a lineage's explicit consumers,
with `model_references`, `reference_scope: "published_model_lineage"`, and
`has_more`. Matching occurs before the limit (default 100, maximum 500 for this
query). Collection permissions are enforced before resolving a model. Missing
and foreign-workspace models both return 404.

Existing `settings.ml_monitoring_model_id` markers identify prior monitoring
Systems without a migration. New schedules also record typed `model_operation`
metadata. Generic System writes preserve those fields when omitted and reject
creating, changing or removing their values. Model Center's monitoring policy
remains the authority for enabling/disabling schedules.

## Impact and activation

No Run, invocation, receipt, System or cost is deleted or moved. Category filters
change the Systems grid only; no implicit filter is added to Impact. A view
scoped to a business System does not automatically include its shared model's
technical operations. Workspace-level views retain both; any narrower scope
must be chosen explicitly. No shared cost is assigned or multiplied across
consumer Systems.

Deploy backend and frontend together. Existing monitoring Systems are recognized
immediately. Configure monitoring via Model Center if required, then open
Systems → Model operations → View model and verify its published consumers.
Creating a consumer relation only requires publishing the native prediction or
forecast node with its model selection; no extra ownership configuration is
needed.

## Verification

- Backend API tests cover legacy classification, unchanged default scope,
  multiple consumers, pinned versus champion references, publication authority,
  tenant isolation, filter-before-limit and protected operation metadata.
- Existing scheduled monitoring/retraining service tests preserve canonical
  human approval and separate challenger creation.
- Frontend tests cover category partitions, current-workspace queries, errors
  distinct from an empty result and stale response suppression.
