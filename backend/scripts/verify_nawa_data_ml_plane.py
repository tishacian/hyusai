"""Re-verify, against a seeded database, every figure the Nawa runbook quotes.

The runbook says its numbers are measured rather than illustrative. That claim is
only worth making if it can be re-checked in one command after a re-seed, which is
what this does: it reads the seeded plane and prints the figures next to the
values the runbook commits to, marking each line ``ok`` or ``DRIFT``.

Three of the checks are about portability rather than arithmetic, and they are the
ones worth watching. A *stock* MLflow client — pointed only at the registry URI,
knowing nothing about Agentium — has to resolve the ``champion`` alias, load the
pipeline off the object store and read back the metric the model card shows; and a
stock skore has to reopen the stored report state and find the same score on the
same rows. If those three pass, "your models are not locked in here" is a fact
rather than a slide.

Usage (with the demo already seeded by ``seed_nawa_data_demo``):
    cd backend && python -m scripts.verify_nawa_data_ml_plane
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app.db.base import SessionLocal  # noqa: E402
from app.models.tabular import MLModel, TabularDataset  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import ml_comparison, ml_registry  # noqa: E402
from app.services.object_store import get_object_store  # noqa: E402
from app.services.tabular_datasets import read_frame  # noqa: E402
from app.services.tabular_ml import runner_up  # noqa: E402

# Every number the runbook prints, keyed by the line it appears on. Kept here
# rather than in the prose so a drift is a failed check and not a reader noticing.
EXPECTED = {
    "raw rows": 8412,
    "raw region spellings": 28,
    "raw plan spellings": 6,
    "raw arpu null": 310,
    "raw arpu sentinel -1": 170,
    "raw suspended lines": 677,
    "raw duplicate msisdn": 412,
    "raw nps null": 1383,
    "clean rows": 6903,
    "clean columns": 22,
    "clean nps null": 1144,
    "feature columns": 31,
    "scored columns": 34,
    "network rows": 24192,
    "network cell-hours at 100% prb": 0,
    "watchlist rows": 72,
    "watchlist critique": 9,
    "watchlist surveillé": 8,
    "watchlist sain": 55,
    "flagged subscribers": 999,
    "v1 roc_auc": 0.835206,
    "v2 roc_auc": 0.859632,
    "v3 roc_auc": 0.855853,
    "test rows": 1726,
}
FAILURES: list[str] = []


def check(label: str, actual, *, expected=None, tolerance: float = 0.0) -> None:
    want = EXPECTED.get(label) if expected is None else expected
    if want is None:
        print(f"  {label}: {actual}")
        return
    if isinstance(want, float):
        agrees = abs(float(actual) - want) <= (tolerance or 1e-6)
    else:
        agrees = actual == want
    print(f"  {label}: {actual} (runbook says {want}) {'ok' if agrees else 'DRIFT'}")
    if not agrees:
        FAILURES.append(f"{label}: {actual} != {want}")


def frame(db, slug: str, version: int | None = None):
    query = db.query(TabularDataset).filter(TabularDataset.slug == slug)
    if version is not None:
        query = query.filter(TabularDataset.version == version)
    rows = query.order_by(TabularDataset.version).all()
    if not rows:
        raise SystemExit(f"dataset {slug} is not seeded — run seed_nawa_data_demo first")
    return read_frame(rows[-1]).to_pandas()


def main() -> int:  # noqa: C901 - a linear checklist, read top down
    db = SessionLocal()
    workspace = db.query(Workspace).filter(Workspace.slug == "nawa").first()
    if workspace is None:
        raise SystemExit("no `nawa` workspace — run seed_nawa_data_demo first")
    print(f"workspace: nawa {workspace.id}")

    print("\n[1] the export arrives dirty")
    raw = frame(db, "base-clients-export-brut")
    check("raw rows", len(raw))
    check("raw region spellings", int(raw["region"].nunique()))
    check("raw plan spellings", int(raw["plan"].nunique()))
    check("raw arpu null", int(raw["arpu_mad"].isna().sum()))
    check("raw arpu sentinel -1", int((raw["arpu_mad"] == -1).sum()))
    check("raw suspended lines", int((raw["line_status"] == "suspended").sum()))
    check("raw duplicate msisdn", int(raw["msisdn"].duplicated().sum()))
    check("raw nps null", int(raw["nps"].isna().sum()))

    print("\n[2] the SQL that cleans it")
    clean = frame(db, "base-clients-nettoyee", 1)
    check("clean rows", len(clean))
    check("clean columns", len(clean.columns))
    check("clean nps null", int(clean["nps"].isna().sum()))
    check("clean churn rate %", round(100 * float(clean["churn"].mean()), 4), expected=22.1643)

    print("\n[3] the Polars features, and the score")
    check("feature columns", len(frame(db, "base-clients-features").columns))
    scored = frame(db, "base-clients-scoree")
    check("scored columns", len(scored.columns))
    check("flagged subscribers", int((scored["prediction"].astype(str) == "1").sum()))
    decile = scored.nlargest(len(scored) // 10, "score_1")
    base = float(scored["churn"].mean())
    check("top decile churn %", round(100 * float(decile["churn"].mean()), 1), expected=77.2)
    check("top decile lift", round(float(decile["churn"].mean()) / base, 2), expected=3.49)

    print("\n[4] three versions, and what the registry says about them")
    models = {m.version: m for m in db.query(MLModel).order_by(MLModel.version).all()}
    for version in (1, 2, 3):
        check(f"v{version} roc_auc", models[version].metrics_json["primary"]["value"])
    check("champion row", [v for v, m in models.items() if m.is_champion], expected=[1])
    name = models[1].mlflow_model_name
    check("registry alias champion", ml_registry.alias_version(model_name=name), expected="1")
    # The contender is the best loser, not the newest fit: v2 scores above v3.
    check(
        "registry alias challenger",
        ml_registry.alias_version(model_name=name, alias="challenger"),
        expected="2",
    )
    check("runner_up picks", runner_up(db, models[1]).version, expected=2)
    for version, model in models.items():
        found = ml_registry.version_of_run(
            model_name=name, run_id=model.mlflow_run_id or ""
        )
        check(f"v{version} registered as", found, expected=str(version))

    print("\n[5] a stock MLflow client, told only the registry URI")
    import mlflow.pyfunc
    from mlflow.tracking import MlflowClient

    uri = ml_registry.registry_uri()
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    champion = client.get_model_version_by_alias(name, "champion")
    check("resolved version", str(champion.version), expected="1")
    check("source is the object store", champion.source.endswith(models[1].model_uri), expected=True)
    loaded = mlflow.pyfunc.load_model(champion.source)
    check("signature columns", len(loaded.metadata.get_input_schema().inputs), expected=20)
    run = client.get_run(champion.run_id)
    check("run metric roc_auc", round(run.data.metrics["roc_auc"], 6), expected=0.835206)
    # Both halves of the story, from outside: an A/B between the incumbent and
    # its contender needs no knowledge of our tables, only the two aliases.
    contender = client.get_model_version_by_alias(name, "challenger")
    check("challenger resolves to", str(contender.version), expected="2")
    check(
        "the two aliases are different bytes",
        contender.source != champion.source,
        expected=True,
    )
    check(
        "challenger run metric roc_auc",
        round(client.get_run(contender.run_id).data.metrics["roc_auc"], 6),
        expected=0.859632,
    )

    print("\n[6] a stock skore, told only the tag that run carries")
    import io

    import joblib
    from skore import EstimatorReport

    state_uri = run.data.tags.get("agentium.skore_report_state") or ""
    check("run names the report state", bool(state_uri), expected=True)
    stored = (models[1].metrics_json.get("report") or {}).get("key")
    # Through the store facade rather than a filesystem path, so this reads the
    # same on the MinIO posture as on a local one.
    blob = get_object_store().read_bytes(stored)
    report = EstimatorReport.from_dict(joblib.load(io.BytesIO(blob)))
    table = report.metrics.summarize().frame()
    check("test rows", len(report.y_test))
    check("reopened roc_auc", round(float(table.loc["roc_auc"]), 6), expected=0.835206)
    # The point of keeping the state: a metric the fit never flattened, on the
    # rows the card reports on.
    check("recomputed precision", round(float(table.loc["precision"]), 4), expected=0.7049)

    print("\n[7] the two versions on one split, by skore")
    joint = ml_comparison.compare(db, left=models[1], right=models[2])
    check("compared rows", joint["split"]["rows"], expected=1726)
    check("no caveat needed", joint["warnings"], expected=[])
    rows = {row["key"]: row for row in joint["metrics"]}
    for version in (1, 2):
        check(
            f"v{version} column reproduces its card",
            round(rows["roc_auc"][models[version].id], 6),
            expected=models[version].metrics_json["primary"]["value"],
        )
    check(
        "v2 wins every metric",
        all(
            rows[key][models[2].id] > rows[key][models[1].id]
            for key in ("roc_auc", "accuracy", "precision", "recall")
        )
        and all(
            rows[key][models[2].id] < rows[key][models[1].id]
            for key in ("log_loss", "brier_score")
        ),
        expected=True,
    )
    across = ml_comparison.compare(db, left=models[2], right=models[3])
    check(
        "v2 vs v3 says the datasets differ",
        [entry["code"] for entry in across["warnings"]],
        expected=["TRAINED_ON_ANOTHER_DATASET"],
    )

    print("\n[8] the radio watchlist")
    watch = frame(db, "cellules-a-risque-7-jours")
    check("watchlist rows", len(watch))
    bands = watch["risk_band"].value_counts().to_dict()
    for band in ("critique", "surveillé", "sain"):
        check(f"watchlist {band}", int(bands.get(band, 0)))
    network = frame(db, "kpi-cellules-radio")
    check("network rows", len(network))
    check(
        "network cell-hours at 100% prb",
        int((network["prb_utilization_pct"] >= 100.0).sum()),
    )
    movers = watch.nlargest(4, "prb_pct_delta")["prb_pct_delta"].round(2).tolist()
    check("the three real movers, then a cliff", movers, expected=[27.8, 27.56, 21.32, 2.42])

    print()
    if FAILURES:
        print(f"DRIFT — {len(FAILURES)} figure(s) no longer match the runbook:")
        for line in FAILURES:
            print(f"  - {line}")
        return 1
    print("every figure in the runbook still measures true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
