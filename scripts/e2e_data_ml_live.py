#!/usr/bin/env python3
"""Drive the data/ML plane over HTTP against a deployed Agentium, end to end.

This is the release gate for the slice: it walks the same path a demo walks —
upload a CSV, watch the ingest steps, run SQL over the result, plan and fit a
model, mint a key, call ``/predict`` with nothing but that key — and asserts on
the answers rather than on the absence of a 500. It talks to the public URL
through nginx, so it exercises what a browser and a cURL exercise: routing,
auth, the worker plane behind the queue, MinIO, and the registry.

Three of its assertions are the ones worth having:

* **The ingest narrates.** ``status_detail`` has to change while the row is
  ``ingesting``; a dataset that only ever says "pending" then "ready" would pass
  a status check and fail the demo, because that field is what the page renders
  instead of a mute spinner.
* **A key is a key to one model.** The minted key must score its own model and
  must be refused by any other route on the API. A key that can also list
  datasets is not a scoped credential, it is a session.
* **The fit is reproducible.** Training the same rows with the same knobs twice
  must land on the same metric, or "v2 beats v1" means nothing on stage.

Everything it creates is namespaced with a run stamp and removed at the end
unless ``--keep`` is passed, so it can run against a demo VM without leaving
rows on the pages the demo shows.

Usage:
    python scripts/e2e_data_ml_live.py \
        --base-url https://agentium.papai.ai \
        --workspace nawa \
        --email user@example.com --password-file /path/to/secret \
        --expect-sha <40-hex>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from typing import Any

STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


class Failure(RuntimeError):
    """A check that did not hold. Carries no response body: those are logged."""


def log(line: str) -> None:
    print(line, flush=True)


def check(condition: Any, message: str) -> None:
    if not condition:
        raise Failure(message)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Api:
    """A tiny JSON/multipart client. No dependency, so it runs anywhere."""

    def __init__(self, base_url: str, *, insecure: bool = False) -> None:
        self.base = base_url.rstrip("/")
        self.token: str | None = None
        self.workspace: str | None = None
        self._opener = urllib.request.build_opener()
        if insecure:
            import ssl

            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=context)
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        multipart: tuple[str, str, bytes] | None = None,
        api_key: str | None = None,
        authenticated: bool = True,
        expect: int | tuple[int, ...] = 200,
    ) -> Any:
        url = f"{self.base}{path}"
        data: bytes | None = None
        headers: dict[str, str] = {"Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        if multipart is not None:
            field, filename, payload = multipart
            boundary = f"----agentium{STAMP}"
            body = io.BytesIO()
            body.write(f"--{boundary}\r\n".encode())
            body.write(
                f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{filename}"\r\n'.encode()
            )
            body.write(b"Content-Type: text/csv\r\n\r\n")
            body.write(payload)
            body.write(f"\r\n--{boundary}--\r\n".encode())
            data = body.getvalue()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        if api_key:
            headers["X-API-Key"] = api_key
        elif authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.workspace and not api_key:
            headers["X-Workspace-Slug"] = self.workspace

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        expected = (expect,) if isinstance(expect, int) else expect
        try:
            with self._opener.open(request, timeout=180) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            parsed = json.loads(raw.decode() or "null")
        except ValueError:
            parsed = raw.decode(errors="replace")
        if status not in expected:
            raise Failure(
                f"{method} {path} -> {status} (wanted {expected}): "
                f"{json.dumps(parsed)[:600]}"
            )
        return parsed


# ---------------------------------------------------------------------------
# The fixture: a subscriber export with the kind of dirt a real one has
# ---------------------------------------------------------------------------

REGIONS = ["Casablanca", "Rabat", "Tanger", "Marrakech", "Fès"]
PLANS = ["prepaid", "postpaid", "hybrid"]


def subscriber_csv(rows: int, *, seed: int) -> bytes:
    """A churn export whose label is learnable but not separable.

    The signal is deliberately weak-but-real (tenure, complaints, data use), so
    a fit lands in the 0.75-0.95 band: a 1.0 would mean the fixture leaks the
    label and the metric assertion would prove nothing.
    """

    rng = random.Random(seed)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["msisdn", "region", "plan", "tenure_months", "arpu", "complaints", "data_gb", "churn"]
    )
    for index in range(rows):
        tenure = rng.randint(1, 72)
        complaints = rng.choice([0, 0, 0, 1, 1, 2, 3])
        data_gb = round(rng.uniform(0.2, 40.0), 2)
        arpu = round(rng.uniform(35.0, 260.0), 2)
        risk = (
            0.55
            - 0.006 * tenure
            + 0.11 * complaints
            - 0.004 * data_gb
            + rng.gauss(0, 0.16)
        )
        writer.writerow(
            [
                f"2126{700000 + index:07d}",
                rng.choice(REGIONS),
                rng.choice(PLANS),
                tenure,
                arpu,
                complaints,
                data_gb,
                1 if risk > 0.35 else 0,
            ]
        )
    return buffer.getvalue().encode()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


# The vocabularies the two planes narrate through, in the order they are
# written. Kept here rather than imported: this driver talks HTTP to a deployed
# host and must not need the application package to be importable.
INGEST_STEPS = ("queued", "reading", "profiling", "writing")
TRAIN_STEPS = ("queued", "reading", "fitting", "scoring", "validating", "saving")


def step_of(detail: str) -> str:
    """The step code in a ``status_detail``, which may carry a row count.

    Ingest writes ``profiling:8412`` so the page can say "Profiling — 8 412
    rows" without a second request; the step is the part before the colon.
    """

    return detail.split(":", 1)[0].strip()


def check_narration(observed: list[str], vocabulary: tuple[str, ...], what: str) -> None:
    """That the field a page renders instead of a spinner was actually written.

    Counting distinct steps is the obvious check and the wrong one: on a small
    file the whole ingest is faster than one poll, so a correct plane looks mute
    and the run fails for being quick. What can be asserted without a race is
    that every value came from the declared vocabulary, that the sequence never
    walks backwards through it, and that at least one value is real work rather
    than ``queued`` — a row that only ever said "queued" then "ready" is exactly
    the mute spinner this is here to catch.
    """

    steps = [step_of(detail) for detail in observed]
    unknown = [step for step in steps if step not in vocabulary]
    check(not unknown, f"{what} narrated steps outside its vocabulary: {unknown}")
    positions = [vocabulary.index(step) for step in steps]
    check(
        positions == sorted(positions),
        f"{what} narrated its steps out of order: {observed}",
    )
    check(
        any(step != vocabulary[0] for step in steps),
        f"{what} never narrated any work, only {observed or '[]'}",
    )


def wait_for_dataset(api: Api, dataset_id: str, *, timeout: float = 240.0) -> dict:
    """Poll a dataset to ready, collecting the steps it narrated on the way.

    Polled without a pause: the steps are the point, and an ingest of a few
    thousand rows finishes inside a one-second sleep.
    """

    deadline = time.time() + timeout
    details: list[str] = []
    while time.time() < deadline:
        body = api.request("GET", f"/api/v1/datasets/{dataset_id}")
        dataset = body["dataset"]
        detail = (dataset.get("status_detail") or "").strip()
        if detail and (not details or details[-1] != detail):
            details.append(detail)
        status = dataset.get("status")
        if status == "ready":
            return {"dataset": dataset, "details": details}
        if status == "failed":
            raise Failure(f"ingest failed: {dataset.get('error')}")
    raise Failure(f"dataset {dataset_id} never became ready (saw {details})")


def wait_for_model(api: Api, model_id: str, *, timeout: float = 600.0) -> dict:
    deadline = time.time() + timeout
    details: list[str] = []
    while time.time() < deadline:
        body = api.request("GET", f"/api/v1/ml-models/{model_id}")
        model = body["model"]
        detail = (model.get("status_detail") or "").strip()
        if detail and (not details or details[-1] != detail):
            details.append(detail)
        status = model.get("status")
        if status == "ready":
            return {"model": model, "details": details}
        if status in {"failed", "cancelled"}:
            raise Failure(f"training {status}: {model.get('error')}")
        time.sleep(0.25)
    raise Failure(f"model {model_id} never became ready (saw {details})")


def primary_score(model: dict, key: str = "roc_auc") -> float:
    for score in ((model.get("metrics") or {}).get("scores") or []):
        if score.get("key") == key:
            return float(score.get("value"))
    raise Failure(f"model has no {key} in its metrics: {json.dumps(model)[:400]}")


def run(args: argparse.Namespace) -> int:
    api = Api(args.base_url, insecure=args.insecure)
    created: dict[str, list[str]] = {"datasets": [], "models": []}
    report: dict[str, Any] = {"base_url": args.base_url, "stamp": STAMP, "steps": {}}

    # ── 0. what is live ───────────────────────────────────────────────────
    info = api.request("GET", "/api/v1/build-info", authenticated=False)
    log(f"build-info: {info.get('revision')} verified={info.get('revision_verified')}")
    if args.expect_sha:
        check(
            info.get("revision") == args.expect_sha,
            f"live revision {info.get('revision')} != expected {args.expect_sha}",
        )
        check(info.get("revision_verified") is True, "revision is not verified")
    report["steps"]["build_info"] = info

    # ── 1. session ────────────────────────────────────────────────────────
    password = args.password
    if args.password_file:
        password = open(args.password_file).read().strip()
    check(password, "a password is required (--password or --password-file)")
    tokens = api.request(
        "POST",
        "/api/v1/auth/login",
        json_body={"email": args.email, "password": password, "remember_me": False},
        authenticated=False,
    )
    check("token" in tokens, f"login did not return a token: {json.dumps(tokens)[:200]}")
    api.token = tokens["token"]
    api.workspace = args.workspace
    memberships = api.request("GET", "/api/v1/auth/workspaces")
    slugs = [
        entry.get("slug")
        for entry in (
            memberships
            if isinstance(memberships, list)
            else memberships.get("workspaces", [])
        )
    ]
    check(args.workspace in slugs, f"{args.workspace} not among {slugs}")
    log(f"session: {args.email} on {args.workspace} ({len(slugs)} workspaces)")

    # ── 2. upload → ingest narrates → profile ─────────────────────────────
    payload = subscriber_csv(args.rows, seed=args.seed)
    name = f"E2E churn export {STAMP}"
    upload = api.request(
        "POST",
        "/api/v1/datasets/upload",
        multipart=("file", f"e2e-churn-{STAMP}.csv", payload),
    )
    dataset_id = upload["dataset"]["id"]
    created["datasets"].append(dataset_id)
    log(f"upload: dataset {dataset_id} queued={upload.get('queued')}")
    check(upload.get("queued") is True, "the ingest was not queued to the worker plane")

    settled = wait_for_dataset(api, dataset_id)
    dataset = settled["dataset"]
    check(
        int(dataset["row_count"]) == args.rows,
        f"ingest kept {dataset['row_count']} of {args.rows} rows",
    )
    check(len(dataset["schema"]) == 8, f"schema has {len(dataset['schema'])} columns, want 8")
    check(
        len(settled["details"]) >= 2,
        f"the ingest never narrated more than one step: {settled['details']}",
    )
    stats = dataset.get("stats") or {}
    arpu = stats.get("arpu") or {}
    check(arpu.get("histogram"), "no histogram on a numeric column — the header spark is empty")
    check((stats.get("region") or {}).get("top_values"), "no top values on a categorical column")
    log(
        f"ingest: {dataset['row_count']} rows, {len(dataset['schema'])} columns, "
        f"steps={settled['details']}"
    )
    report["steps"]["ingest"] = {
        "dataset_id": dataset_id,
        "rows": dataset["row_count"],
        "status_detail_seen": settled["details"],
        "histogram_bins": len(arpu.get("histogram") or []),
    }

    # ── 3. SQL over it, in duckdb, with a timing to show ──────────────────
    preview = api.request(
        "POST",
        "/api/v1/datasets/sql-preview",
        json_body={
            "sql": (
                "SELECT region, plan, count(*) AS lines, "
                "round(avg(arpu), 2) AS arpu_moyen "
                "FROM subscribers WHERE arpu > 0 GROUP BY 1, 2 ORDER BY lines DESC"
            ),
            "sources": [{"view": "subscribers", "dataset_id": dataset_id}],
            "row_limit": 50,
        },
    )
    result = preview["preview"]
    check(result["row_count"] >= 5, f"the aggregate returned {result['row_count']} rows")
    check(result["duration_ms"] >= 0, "no timing on the preview — the badge would be empty")
    catalog = {source["view"]: source for source in preview["sources"]}
    check("subscribers" in catalog, "the editor would autocomplete against nothing")
    check(
        len(catalog["subscribers"]["columns"]) == 8,
        "the autocompletion catalog lost columns",
    )
    log(
        f"sql: {result['row_count']} groups in {result['duration_ms']} ms, "
        f"catalog {len(catalog['subscribers']['columns'])} columns"
    )
    report["steps"]["sql"] = {
        "rows": result["row_count"],
        "duration_ms": result["duration_ms"],
    }

    # A guard, not a formality: the node must refuse anything but a read.
    refused = api.request(
        "POST",
        "/api/v1/datasets/sql-preview",
        json_body={
            "sql": "DROP TABLE subscribers",
            "sources": [{"view": "subscribers", "dataset_id": dataset_id}],
        },
        expect=(400, 409, 422),
    )
    log(f"sql guard: DROP refused ({json.dumps(refused)[:120]})")

    # ── 4. plan, then fit ─────────────────────────────────────────────────
    plan = api.request(
        "POST",
        "/api/v1/ml-models/plan",
        json_body={"dataset_id": dataset_id, "target": "churn"},
    )
    check(plan["plan"] is not None, f"the planner refused: {plan.get('refusal')}")
    check(plan["plan"]["task"] == "classification", "churn was not read as a classification")
    columns = {row["name"]: row for row in plan["columns"]}
    check(
        (columns["arpu"].get("profile") or {}).get("histogram"),
        "the picker would draw no sparkline: the plan carries no profile",
    )
    log(
        f"plan: {plan['plan']['task']} on {plan['plan']['target']}, "
        f"{len(plan['plan']['features'])} features, algo {plan['plan']['algo']}"
    )

    first = api.request(
        "POST",
        "/api/v1/ml-models",
        json_body={
            "dataset_id": dataset_id,
            "task": "classification",
            "target": "churn",
            "features": [
                "region",
                "plan",
                "tenure_months",
                "arpu",
                "complaints",
                "data_gb",
            ],
            "algo": "hist_gradient_boosting",
            "name": f"E2E churn {STAMP}",
        },
    )
    model_id = first["model"]["id"]
    created["models"].append(model_id)
    fitted = wait_for_model(api, model_id)
    model = fitted["model"]
    auc = primary_score(model)
    check(0.6 <= auc <= 0.999, f"roc_auc {auc} is outside the believable band")
    check(
        len(fitted["details"]) >= 2,
        f"training never narrated more than one step: {fitted['details']}",
    )
    curves = (model.get("metrics") or {}).get("curves") or {}
    check(curves.get("roc"), "no ROC curve in the metrics — the card would be empty")
    check(
        (model.get("metrics") or {}).get("confusion"),
        "no confusion matrix in the metrics",
    )
    check(
        (model.get("metrics") or {}).get("importances"),
        "no permutation importances in the metrics",
    )
    detail = api.request("GET", f"/api/v1/ml-models/{model_id}")
    serving = detail["serving"]
    check(serving["callable"] is True, "the fitted model is not callable")
    check(serving["fields"], "no input contract — the Playground would render nothing")
    log(
        f"train: v{model['version']} roc_auc {auc:.6f}, steps={fitted['details']}, "
        f"contract {len(serving['fields'])} fields, endpoint {serving['endpoint']}"
    )
    report["steps"]["train"] = {
        "model_id": model_id,
        "version": model["version"],
        "roc_auc": auc,
        "status_detail_seen": fitted["details"],
        "contract_fields": len(serving["fields"]),
    }

    # ── 5. the same rows, the same knobs, the same number ─────────────────
    if args.reproduce:
        again = api.request(
            "POST",
            "/api/v1/ml-models",
            json_body={
                "dataset_id": dataset_id,
                "task": "classification",
                "target": "churn",
                "features": [
                    "region",
                    "plan",
                    "tenure_months",
                    "arpu",
                    "complaints",
                    "data_gb",
                ],
                "algo": "hist_gradient_boosting",
                "name": f"E2E churn {STAMP}",
            },
        )
        second_id = again["model"]["id"]
        created["models"].append(second_id)
        second = wait_for_model(api, second_id)["model"]
        second_auc = primary_score(second)
        check(
            abs(second_auc - auc) < 1e-9,
            f"the same fit landed on {second_auc} then {auc} — not reproducible",
        )
        log(f"reproduce: v{second['version']} roc_auc {second_auc:.6f} (identical)")
        report["steps"]["reproduce"] = {"roc_auc": second_auc, "version": second["version"]}

        comparison = api.request(
            "GET", f"/api/v1/ml-models/{second_id}/comparison?against={model_id}"
        )
        rows = comparison.get("metrics") or []
        check(rows, f"no comparison table: {json.dumps(comparison)[:300]}")
        check(
            comparison["split"]["rows"] > 0,
            "the comparison scored both versions on zero rows",
        )
        log(
            f"comparison: {len(rows)} metric rows over one split of "
            f"{comparison['split']['rows']} rows"
        )
        report["steps"]["comparison"] = {
            "metric_rows": len(rows),
            "split_rows": comparison["split"]["rows"],
        }

    # ── 6. a key, and the one thing it may do ─────────────────────────────
    minted = api.request(
        "POST",
        f"/api/v1/ml-models/{model_id}/keys",
        json_body={"name": f"e2e-{STAMP}"},
    )
    secret = minted.get("secret") or (minted.get("key") or {}).get("secret")
    check(secret, f"the mint did not return a secret once: {json.dumps(minted)[:200]}")
    key_id = (minted.get("key") or {}).get("id") or minted.get("id")

    example = model.get("input_example") or []
    if isinstance(example, dict):
        example = [example]
    records = example or [
        {
            "region": "Casablanca",
            "plan": "prepaid",
            "tenure_months": 3,
            "arpu": 60.0,
            "complaints": 3,
            "data_gb": 1.2,
        }
    ]
    scored = api.request(
        "POST",
        f"/api/v1/ml-models/{model_id}/predict",
        json_body={"inputs": records},
        api_key=secret,
    )
    predictions = scored.get("predictions") or []
    check(predictions, f"no prediction came back: {json.dumps(scored)[:300]}")
    probability = predictions[0].get("score", predictions[0].get("confidence"))
    check(
        probability is not None and 0.0 <= float(probability) <= 1.0,
        f"probability {probability} is not a probability",
    )
    check(
        scored["served"]["version"] >= 1,
        "the answer does not say which version served it",
    )
    log(
        f"predict (X-API-Key only): {len(predictions)} row(s) in "
        f"{scored['duration_ms']} ms, first={predictions[0].get('prediction')} "
        f"p={probability}, served v{scored['served']['version']}, "
        f"cached={scored['cached']}"
    )

    # The scope, checked rather than asserted: the key is not a session.
    api.request("GET", "/api/v1/datasets", api_key=secret, expect=(401, 403))
    api.request("GET", f"/api/v1/ml-models/{model_id}", api_key=secret, expect=(401, 403))
    log("scope: the same key is refused by /datasets and by the model detail route")
    report["steps"]["predict"] = {
        "rows": len(predictions),
        "probability": probability,
        "key_scope_refusals": ["/datasets", "/ml-models/{id}"],
    }

    if key_id:
        api.request(
            "DELETE",
            f"/api/v1/ml-models/{model_id}/keys/{key_id}",
            expect=(200, 204),
        )
        api.request(
            "POST",
            f"/api/v1/ml-models/{model_id}/predict",
            json_body={"inputs": records},
            api_key=secret,
            expect=(401, 403),
        )
        log("revoke: the revoked key stops answering immediately")
        report["steps"]["predict"]["revoked"] = True

    # ── 7. leave the pages as they were ───────────────────────────────────
    if not args.keep:
        for model_id_ in created["models"]:
            api.request(
                "DELETE", f"/api/v1/ml-models/{model_id_}", expect=(200, 204, 404, 409)
            )
        for dataset_id_ in created["datasets"]:
            api.request(
                "DELETE", f"/api/v1/datasets/{dataset_id_}", expect=(200, 204, 404, 409)
            )
        log(
            f"cleanup: {len(created['models'])} model(s) and "
            f"{len(created['datasets'])} dataset(s) soft-deleted"
        )
    else:
        log(f"kept: models={created['models']} datasets={created['datasets']}")

    report["created"] = created
    report["result"] = "passed"
    if args.report:
        with open(args.report, "w") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        log(f"report: {args.report}")
    log("E2E PASSED")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "https://agentium.papai.ai"))
    parser.add_argument("--workspace", default="nawa")
    parser.add_argument("--email", default=os.environ.get("E2E_USERNAME", ""))
    parser.add_argument("--password", default=os.environ.get("E2E_PASSWORD", ""))
    parser.add_argument("--password-file", default=None)
    parser.add_argument("--expect-sha", default=None)
    parser.add_argument("--rows", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--report", default=None)
    parser.add_argument(
        "--reproduce",
        action="store_true",
        help="fit the same request twice and require the same metric",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the created dataset and models behind (default: soft delete)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="skip TLS verification (for driving https://localhost with a Host header)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except Failure as exc:
        print(f"E2E FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
