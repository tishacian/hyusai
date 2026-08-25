# Provisioning the Agentium data/ML plane on `omnirag-demo`

What has to exist on the VM before datasets, transforms and models work, and —
the part that saves the most time — what deliberately does **not** have to exist.

Applies from Alembic revision `096_tabular_data_plane` / `097_ml_training_plane`
onward. As of 25/08/2026 the VM is still at `095_python_recipes`, so nothing
here has been applied there yet.

## There is no MLflow database, and no MLflow server

The plan for this slice said "create the `mlflow` database". Do not. Nothing
would connect to it.

MLflow is used here as an **artifact format**, not as a service. A fit writes a
standard MLflow model directory — `MLmodel`, `model.skops`, `conda.yaml`,
`python_env.yaml`, `requirements.txt`, `input_example.json` — and that directory
is uploaded to the object store under
`workspaces/<workspace>/ml/models/<model>/model`. The registry is the
`ml_models` table: version, algorithm, metrics, signature, lineage, champion
flag, predict counters. A tracking server would hold a second, weaker copy of
facts that table already holds authoritatively, and would add a stateful service
to the demo VM for no capability.

The code says so in two places, and both are worth checking before anyone
reopens the question:

- `backend/app/core/config.py` carries `mlflow_tracking_uri`,
  `mlflow_artifact_root` and `mlflow_experiment_name`, all defaulting to empty
  and **read by nothing**. They are a placeholder for a later phase.
- `backend/app/services/tabular_ml.py` sets `MLFLOW_TRACKING_URI` in the training
  subprocess's environment to a throwaway directory inside that run's scratch
  space. That is deliberate: it stops the MLflow client from discovering an
  ambient tracking URI and trying to log to it. A tracking server configured at
  the VM level therefore could not be reached by a fit even if one existed —
  the per-run value overrides it.

Consequences for provisioning:

- **Do not** create a `mlflow` database or role on `agentium-pg`. The only
  application database stays `agentium`.
- **Do not** set `MLFLOW_TRACKING_URI` in the compose environment. It is unset
  today (`docker exec agentium-backend printenv | grep MLFLOW` returns nothing),
  which is correct.
- If a tracking server is ever genuinely wanted — for cross-workspace experiment
  comparison, say — it is a new slice: a database, a service, a bucket policy,
  and a decision about which of the two registries wins. It is not a
  provisioning step for this one.

## What does have to exist

**1. The migrations.** `096_tabular_data_plane` then `097_ml_training_plane`,
applied by the ordinary `agentium-vm-deploy.sh migrate` path. They chain from
`095_python_recipes`, which is the VM's current head.

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

## Backups: the dump is now two halves

A Postgres-only dump stops being restorable the moment `096` is applied, because
`tabular_datasets.storage_key` and `ml_models.model_uri` point outside the
database. `scripts/agentium-data-plane-dump.sh` takes both halves into one
window and then checks that every artifact the registry names is present in it —
see [§5b of the release process](../agentium-release-process.md#5b-once-the-dataml-plane-is-deployed-that-dump-is-no-longer-a-backup).

To restore: `pg_restore` the dump, then `mc mirror` the window's `objects/` back
under the bucket root. The keys in `objects.sha256` are already relative to that
root, so they go back exactly where the registry expects them.

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
