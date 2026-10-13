# Provisioning the Agentium data/ML plane on `omnirag-demo`

What has to exist on the VM before datasets, transforms and models work, and —
the part that saves the most time — what deliberately does **not** have to exist.

Applies from Alembic revision `096_tabular_data_plane` / `097_ml_training_plane`
onward. As of 25/08/2026 the VM is still at `095_python_recipes`, so nothing
here has been applied there yet.

## There is an MLflow database, and no MLflow server

Those two halves are both load-bearing, and confusing them is the mistake this
section exists to prevent.

**The database.** MLflow's Model Registry requires a **SQL backend store**. A
bare `mlruns/` file store does not support it — `create_registered_model` raises
against one — so "registry without a server" means "client writing straight to
SQL". `backend/app/services/ml_registry.py` derives that store from
`DATABASE_URL` by swapping the database name to `mlflow`, which is why the
provisioning step is one `CREATE DATABASE` on the instance already running and
not a second credential. The service creates it on first use if the role is
allowed to; pre-creating it is still preferable, because then the deploy fails
loudly rather than the first fit logging a warning and carrying on.

**No server.** Nothing runs `mlflow server`. There is no port, no container, no
supervised process — the Python client opens a connection, writes a run and a
model version, and closes it. What the database buys is a registry a *stranger*
can read: point a stock MLflow at the same store and it resolves
`models:/<workspace>.<slug>@champion`, follows the version's `source` to MinIO
and loads the pipeline knowing nothing about Agentium. That is the "no lock-in"
claim, and it is checkable in one command instead of asserted:

```bash
# read-only inspection of the registry this deployment writes
mlflow server --backend-store-uri postgresql://agentium:…@agentium-pg:5432/mlflow
```

**Two records, one fact each.** `ml_models` stays the operational row — status
machine, API keys, what the UI lists and paginates. The registry holds the
portable record — run, version, `source`, alias. They are joined by
`ml_models.mlflow_run_id`. Promotion writes both: `set_champion` flips the row's
`is_champion` and moves the registry's `champion` alias, so an operator who
promotes in our UI and then resolves `@champion` from a foreign client gets the
version they chose.

**`challenger` is derived, not chosen.** It names the best *ready* version that
is not serving — by score, with the higher version breaking a tie — so a foreign
client can A/B the incumbent against its contender knowing only two alias names.
Deliberately not "the newest version": a retrain is frequently worse, which is
the whole reason promotion is a human decision. `sync_challenger` re-derives it
after every fit, every promotion and every delete, and **clears** it when a
lineage is down to one version or the contender's row is gone — an alias
resolving to a version nobody can audit any more is worse than an absent one,
because it fails silently. Expect `@challenger` to be absent on a
single-version lineage; that is correct, not a provisioning fault.

**Artifacts are not logged through MLflow.** The bytes go to the object store
through the same `ObjectStore` facade as everything else, and the model version
is created with an explicit `source` pointing at that location
(`s3://agentium-artifacts/workspaces/<ws>/ml/models/<id>/model`). So there is one
copy of the bytes, one storage contract and one backup routine — and
`MLFLOW_S3_ENDPOINT_URL` is **not** needed by our writer. A *foreign* MLflow
client resolving that `source` does need it, along with S3 credentials; that is
the reader's configuration, not ours.

**The evaluation is an artifact too.** A fit keeps skore's own report state next
to the model, at `…/ml/models/<id>/report/state.joblib`, and the run carries its
location as the tag `agentium.skore_report_state`. `metrics_json` is a *reading*
of the evaluation flattened for one card; the state is the evaluation, split rows
and cached predictions included, so a metric nobody asked for at fit time can
still be computed on the rows the card reports on:

```python
import joblib
from skore import EstimatorReport
report = EstimatorReport.from_dict(joblib.load("state.joblib"))
report.metrics.summarize().frame()
```

It sits beside the model directory rather than inside it because serving
downloads that directory on every cold load and has no use for a training split.
Above `ML_TRAIN_REPORT_STATE_LIMIT_MB` (64 by default) it is dropped rather than
stored, so its absence on a large fit is by design and not a failure.

**The training subprocess is deliberately cut off from all of this.**
`tabular_ml.py` pins the harness's `MLFLOW_TRACKING_URI` to a throwaway
directory inside the run's scratch. The child serializes a model directory and
nothing else; the registry write happens in the worker process afterwards,
through an explicit client. A resource-capped subprocess should not be holding a
database connection.

Consequences for provisioning:

- **Do** ensure a `mlflow` database exists on `agentium-pg`, owned by the
  `agentium` role. No new role, no new credential.
- **Do not** set `MLFLOW_TRACKING_URI` in the compose environment. The client is
  configured in code; an ambient value would only confuse the subprocess pinning
  described above. `ML_REGISTRY_URI` exists for the case where the registry must
  live somewhere other than beside the application database.
- `ML_REGISTRY_ENABLED=false` turns the mirror off. Training, serving and
  promotion all keep working — only the portable record stops being written.

## What does have to exist

**1. The migrations.** `096_tabular_data_plane` then `097_ml_training_plane`,
applied by the ordinary `agentium-vm-deploy.sh migrate` path. They chain from
`095_python_recipes`, which is the VM's current head. MLflow migrates its own
schema inside the `mlflow` database on first connection; that is not an Alembic
revision and does not appear in our history.

**2. The object-store prefixes.** None to create by hand. The backend writes to
`workspaces/<workspace>/tabular/datasets/<id>/…` and
`workspaces/<workspace>/ml/models/<id>/{model,report}/…` inside the existing
`agentium-artifacts` bucket, and MinIO creates prefixes on write. The bucket and
its credentials are already configured (`OBJECT_STORE_BACKEND=s3`,
`OBJECT_STORE_S3_BUCKET=agentium-artifacts`,
`OBJECT_STORE_S3_ENDPOINT_URL=http://agentium-minio:9000`).

**3. The recipe venv root.** `/srv/agentium-data/recipe_envs` must exist on the
protected data device. `agentium-vm-deploy.sh storage-check` already asserts it
alongside `object_store`, so a wrong bind fails the gate before `migrate` or
`up` rather than at the first Polars node.

**4. Two settings, or two nodes report a refusal.** The Polars and dbt transform
nodes execute author-written Python in a managed venv, and the plane gates that:

| Setting | Value | Without it |
|---|---|---|
| `RECIPE_EXECUTION_ENABLED` | `true` | the node fails with `POLARS_EXECUTION_DISABLED` |
| `WORKER_EAGER_MODE` | `true` **only** where no Celery worker runs | the ingest/transform task is queued and never picked up |

On the VM `agentium-worker-cpu` runs, so `WORKER_EAGER_MODE` stays off — eager
mode is for a bare backend (local, or a seed run). `RECIPE_EXECUTION_ENABLED`
must be on for the demo's Polars and dbt beats to execute.

**5. Disk for the venvs.** The first dbt node builds a `dbt-duckdb` venv of
about 345 MB, cached by dependency fingerprint under `recipe_envs`. The first
run of that node pays roughly 13 s; later runs pay nothing. Budget the space and
warm it before a demo rather than during one.

## Backups: the dump is now three parts

A Postgres-only dump of `agentium` stops being restorable the moment `096` is
applied, because `tabular_datasets.storage_key` and `ml_models.model_uri` point
outside the database. `scripts/agentium-data-plane-dump.sh` takes all three
parts into one window — the `agentium` database, the `mlflow` database, and the
object-store prefixes they reference — and then checks that every artifact the
registry names is present in it. See
[§5b of the release process](../agentium-release-process.md#5b-once-the-dataml-plane-is-deployed-that-dump-is-no-longer-a-backup).

Suspend writers, schedulers, workers and purges for the complete backup window.
The two SQL dumps, the reference export and the object mirror do not share a
distributed snapshot. The script does not stop these services itself. Without
this operational boundary, successful byte checks cannot establish that the
dump and objects describe the same instant.

From A1/Delta onward, the mirror takes the complete prefix of every workspace
referenced by datasets, models, retained BRDs or governed assets. A1 evidence
can live outside `tabular/`, `ml/` and `brd/`; workspaces with no such references
remain excluded. The existing 8 GiB staging ceiling still applies. Larger
workspaces require a deliberately provisioned backup path, not a bypass of the
ceiling or a partial mirror presented as complete.

The window now retains `reference-registry.jsonl`, its checksum, and
`governed-verification.json`. The offline verifier compares every A1 SQL envelope
with its canonical manifest and content digest, then streams all declared
objects to verify their sizes and SHA-256 hashes. Parent references must match
their workspace, ID, kind, version and digest; pinned native references must
retain their identity. Delta verification uses the registered log hash and exact
part inventory, including every part's hash. Same-size corruption, extra commits,
missing parents, traversal and symlinks fail the check and block `.ready`.
Stored dataset samples are checked too. Legacy Parquet rows without a recorded
hash are explicitly counted in `legacy_datasets_without_recorded_hash`; the
validator cannot invent a pre-existing byte identity for them.

Before restoration, verify the retained dump and registry checksums and run the
object checks from the backup window. `$BACKUP_WINDOW` is the actual completed
window, not a new export from the current application database:

```bash
(cd "$BACKUP_WINDOW" && sha256sum -c reference-registry.jsonl.sha256)
(cd "$BACKUP_WINDOW/objects" && sha256sum -c ../objects.sha256)
python3 scripts/agentium_validate_delta_backup.py \
  --objects-root "$BACKUP_WINDOW/objects" \
  --registry "$BACKUP_WINDOW/reference-registry.jsonl"
```

Restore both dumps with `pg_restore`, then mirror the window's `objects/` back
under the bucket root. The object keys are already relative to that root. Keep
the application stopped until an independent copy of the restored bucket has
passed the same checksum and registry commands, substituting that copy as
`--objects-root`. Re-export A1 and native registry rows from the restored SQL
database in the JSONL shape used by the dump script and verify that export too;
this catches restoration of the wrong SQL window. Do not treat validation of
the original backup alone as validation of a completed restore.

The checker needs only Python's standard library and no network. It limits its
registry to 256 MiB and each row to 4 MiB; exceeding these limits fails explicitly.
Its legacy positional invocation checks Delta structure and part sizes only;
use the `--registry` form for recorded cryptographic identities. Local tests
cover actual Delta parts, an application A1/SQLite/ObjectStore restore and
same-size corruption. Docker/PG transport doubles additionally exercise the
shell `.ready` gate. These tests do not establish `pg_restore`, S3 IAM, bucket
versioning, a production RPO/RTO or recovery from an actual lost VM; those remain
part of an isolated operational restore rehearsal.

Losing the `mlflow` half alone is survivable and worth knowing: the models keep
training, serving and promoting from `ml_models`, and what is gone is the
portable record — runs, versions, aliases. It does not rebuild itself for models
already trained, so it is dumped rather than treated as a cache.

Recipe venvs under `recipe_envs` are **not** backed up and should not be: they
are rebuilt from their dependency fingerprints, and a stale venv restored over a
new interpreter is worse than an absent one.

## A benign schema divergence to expect

Migration `070_workspace_app_entitlement_registry` was edited in this slice. Its
`app_key` check constraint used `NOT LIKE '% %'`; SQLAlchemy carries that string
through `create_all` as a parameter-style template, which made fresh-Postgres
schema creation fail. It now spells the same rule as
`app_key = replace(app_key, ' ', '')`.

`070` is already applied on the VM, so Alembic will not revisit it: the live
constraint keeps the `!~~ '% %'` form while the migration file and the model now
say `replace(...)`. The two are behaviourally identical — and the sibling regex
`^[a-z0-9][a-z0-9.-]{0,79}$` already excludes spaces regardless — so there is
nothing to repair. Recorded here so that a future schema diff against a
freshly-provisioned database reads as expected rather than as drift.
