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

**Artifacts are not logged through MLflow.** The bytes go to the object store
through the same `ObjectStore` facade as everything else, and the model version
is created with an explicit `source` pointing at that location
(`s3://agentium-artifacts/workspaces/<ws>/ml/models/<id>/model`). So there is one
copy of the bytes, one storage contract and one backup routine — and
`MLFLOW_S3_ENDPOINT_URL` is **not** needed by our writer. A *foreign* MLflow
client resolving that `source` does need it, along with S3 credentials; that is
the reader's configuration, not ours.

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
`workspaces/<workspace>/ml/models/<id>/model/…` inside the existing
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

To restore: `pg_restore` both dumps, then `mc mirror` the window's `objects/`
back under the bucket root. The keys in `objects.sha256` are already relative to
that root, so they go back exactly where both registries expect them.

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
