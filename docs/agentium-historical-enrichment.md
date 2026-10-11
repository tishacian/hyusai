# Historical features in an existing Flow

The `sql_transform_v1` node accepts a graph-owned `params.enrichment` contract.
It compiles deterministic historical aggregates onto the existing in-memory
DuckDB engine, then registers the result as an ordinary versioned dataset in
ObjectStore/MinIO. There is no new runtime, feature store or learned transform.

```json
{
  "enrichment": {
    "version": 1,
    "operation": "historical_aggregates",
    "base": {"dataset_id": "orders-dataset-id", "version": 1},
    "history": {"dataset_id": "payments-dataset-id", "version": 2},
    "base_row_id": "order_id",
    "history_row_id": "event_id",
    "base_key": "customer_id",
    "history_key": "customer_id",
    "decision_time": "ordered_at",
    "available_time": "available_at",
    "base_features": ["basket_amount"],
    "target_columns": ["late"],
    "unavailable_columns": ["delivered_at", "future_status"],
    "aggregates": [
      {"operation": "count", "output": "prior_events"},
      {"operation": "mean", "column": "amount", "output": "prior_amount"}
    ],
    "max_unmatched_fraction": 0.1,
    "max_base_rows": 50000,
    "max_history_rows": 100000,
    "max_input_bytes": 64000000,
    "timeout_s": 30
  },
  "output_name": "Orders with historical payment features"
}
```

The same contract can be previewed through
`POST /api/v1/datasets/enrichment-preview` with
`{"enrichment": {...}, "row_limit": 50}`. A preview validates the complete
result and creates no dataset. Execution follows normal Flow publication and
Run/SkillInvocation accounting; trigger payloads cannot replace this configuration.

In the Flow workshop, switch a SQL node to **Historical aggregates / Agrégats
historiques**, then edit its JSON contract. The source panel lists dataset IDs
and versions; the editor preserves them through save/reload. The preview uses
the historical operation even if the node still retains an earlier SQL draft.
Malformed historical JSON is refused, never replaced by that SQL. After a
successful preview, **Pin source fingerprints / Épingler les empreintes** saves
the qualified contract in the draft Flow; changing the contract invalidates
that action until another preview succeeds. Publish the revision normally.

## Temporal and lineage contract

- An event contributes only when its **availability timestamp is strictly earlier
  than the decision timestamp**. Use the date the data became available, which
  may differ from its business occurrence date. Naive dates/timestamps mean UTC;
  timezone offsets are normalized by DuckDB. Equal timestamps are excluded.
- Input row identities must be unique. Entity keys must be non-null, non-empty,
  and have the same string/integer type on both sides. Repeated events at the
  same entity/timestamp are aggregated together before the ASOF join, so no
  row multiplication or arbitrary tie selection occurs.
- `count` counts events; `sum`, `mean`, `min`, `max` accept numeric columns and
  ignore null values. No history yields zero events and null numeric features.
  The operation uses all available history; sliding windows are not supported.
- Only declared base features, base identity/key/decision time and available
  target columns are retained. Targets and declared unavailable columns cannot
  contribute aggregates or join keys. Correct declaration of semantic targets
  and availability remains a required part of problem framing; the operation
  cannot infer an undisclosed target proxy from a column name.
  Configure downstream training with the returned `enrichment.feature_columns`
  list: identities and decision timestamps are retained for lineage, not
  implicitly recommended as predictive features.
- Lineage records both exact dataset identities/versions and Parquet SHA-256,
  the complete typed contract and its digest, row identities, entity/time
  selection rule, unmatched fraction, added columns and elapsed computation.
  These resolve every output row to its contributing source rows without a
  potentially quadratic list of edges. They do not establish independent test
  partitions across different derived datasets.
- Preview returns the qualified `enrichment.contract` with source SHA-256 pins.
  Save this contract in the published Flow for exact replay; changed content
  under an unchanged dataset identity is then refused. A newer slug version is
  never selected implicitly. Inference is performed by running this same
  preparation before the ordinary scoring node, not by the estimator silently
  fetching a different history table.

## Bounds and qualification

Each input's materialization is streamed under its byte cap. Actual input counts
are checked in addition to catalog metadata. Output cardinality must equal the
base cardinality and remain within the platform transform cap. DuckDB retains
its existing 1 GB memory limit and two-thread limit; a timer interrupts SQL work.
Temporary files and the connection are cleaned after success or failure.
The time budget does not claim to measure total service latency or process RSS.

`backend/app/tests/services/test_tabular_enrichment.py` exercises real Parquet,
DuckDB, dataset registration, the API and the Flow wrapper, including hostile
payloads, workspace isolation, changed references, future data, invalid keys,
size bounds and deadlines. It also includes a **synthetic technical fixture**:
400 distinct customers, a deliberately planted historical signal, future
distractors, a fixed 300/100 split and the same depth-two tree before/after.
Its acceptance thresholds are fixed in the test before execution. Passing this
fixture demonstrates the implemented mechanism; business value and production
resource measurements remain unmeasured until authorized representative data
and deployment resources are available.
