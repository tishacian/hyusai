"""Preflight an isolated Jev preview; dispatch one case only with --execute."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import httpx
from prepare import (
    MODEL,
    SYSTEM_ID,
    TRANSPORT,
    WORKSPACE_ID,
    WORKSPACE_SLUG,
    build,
    flow_identity,
    sha,
)

ORIGIN = "https://agentium.papai.ai"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def check_preflight(
    *, plan, live_flow, workspace, readiness, budgets, providers, tariffs
):
    require(workspace.get("id") == WORKSPACE_ID, "SHOWCASE_WORKSPACE_REQUIRED")
    features = workspace.get("settings", {}).get("features", {})
    require(features.get("flow_workbench_v1") is True, "FLOW_WORKBENCH_DISABLED")
    require(
        features.get("flow_publication_v1") is not False, "FLOW_PUBLICATION_DISABLED"
    )
    require(
        flow_identity(live_flow) == plan["preserve"], "LUMA_FLOW_CHANGED_REPREPARE_PLAN"
    )
    require(readiness.get("ready") is True, "USAGE_ROLLOUT_UNVERIFIED")
    require(
        TRANSPORT in readiness.get("qualified_transports", []),
        "USAGE_TRANSPORT_UNQUALIFIED",
    )
    require(budgets.get("can_manage") is True, "USAGE_BUDGET_MANAGEMENT_REQUIRED")
    active = [row for row in budgets["items"] if row.get("enabled")]
    workspace_caps = [row for row in active if row.get("scope") == "workspace"]
    require(len(workspace_caps) == 1, "ACTIVE_SHOWCASE_BUDGET_REQUIRED")
    require(
        Decimal(workspace_caps[0]["currency_limits"].get("EUR", "0"))
        == Decimal("2000"),
        "SHOWCASE_BUDGET_CHANGED",
    )
    for row in active:
        if row.get("scope") == "system" and row.get("system_id") != SYSTEM_ID:
            continue
        require(row.get("max_tokens") is None, "TYPESAFE_TOKEN_BUDGET_UNQUALIFIED")
        require("EUR" in row.get("currency_limits", {}), "USAGE_CURRENCY_NOT_BUDGETED")
        require(not row.get("reconciliation_required"), "USAGE_RECONCILIATION_REQUIRED")
        for amount in row["current_period"]["amounts"]:
            if amount.get("limit") is not None:
                require(
                    Decimal(amount.get("consumed", "0"))
                    + Decimal(amount.get("reserved", "0"))
                    < Decimal(amount["limit"]),
                    "USAGE_BUDGET_EXHAUSTED",
                )
    provider = next(
        (row for row in providers["providers"] if row.get("key") == "typesafe"), {}
    )
    require(
        provider.get("configured") is True and provider.get("status") == "active",
        "TYPESAFE_CONNECTION_NOT_ACTIVE",
    )
    # The provider documents pinned versions as accepted even when discovery
    # lists only rolling aliases. Account permission is still enforced on send.
    require(
        provider.get("typed_decisions_available") is True,
        "TYPESAFE_DECISIONS_UNAVAILABLE",
    )
    prices = [
        row
        for row in tariffs["items"]
        if row.get("provider") == "typesafe" and row.get("model") == MODEL
    ]
    require(bool(prices), "TYPESAFE_EUR_TARIFF_REQUIRED")
    price = max(prices, key=lambda row: row["revision"])
    require(price.get("currency") == "EUR", "TYPESAFE_LATEST_TARIFF_NOT_EUR")
    rates = price["rates"]
    require(
        Decimal(rates["input_per_million"]) > 0
        and Decimal(rates["output_per_million"]) == 0,
        "TYPESAFE_TARIFF_CONTRACT_MISMATCH",
    )
    input_rate = max(
        Decimal(rates[key])
        for key in (
            "input_per_million",
            "cached_input_per_million",
            "cache_write_per_million",
        )
        if rates.get(key) is not None
    )
    reserve_eur = (Decimal(65536) * input_rate / Decimal(1000000)).quantize(
        Decimal("0.000000000001"), rounding=ROUND_CEILING
    )
    for row in active:
        if row.get("scope") == "system" and row.get("system_id") != SYSTEM_ID:
            continue
        for amount in row["current_period"]["amounts"]:
            if amount.get("currency") == "EUR" and amount.get("limit") is not None:
                require(
                    Decimal(amount.get("consumed", "0"))
                    + Decimal(amount.get("reserved", "0"))
                    + reserve_eur
                    <= Decimal(amount["limit"]),
                    "USAGE_BUDGET_INSUFFICIENT",
                )
    return {
        "revision": readiness["revision"],
        "tariff_id": price["id"],
        "tariff_revision": price["revision"],
        "budget_revision": workspace_caps[0]["revision"],
        "conservative_reservation_eur": str(reserve_eur),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--case", choices=["RC-1042", "RC-1043", "RC-1044", "RC-5007"], required=True
    )
    parser.add_argument(
        "--execute", action="store_true", help="Create one paid node-preview Run."
    )
    parser.add_argument(
        "--record", type=Path, help="New local receipt path; mandatory for execution."
    )
    args = parser.parse_args()
    require(not args.execute or args.record is not None, "NEW_RECEIPT_PATH_REQUIRED")
    require(
        args.record is None or not args.record.exists(),
        "RECEIPT_ALREADY_EXISTS_NO_RETRY",
    )
    plan = json.loads(args.plan.read_text())
    require(plan.get("format") == "luma-jev-node-preview-v1", "PLAN_FORMAT_INVALID")
    bearer = os.environ.get("AGENTIUM_BEARER_TOKEN") or getpass.getpass(
        "Jeton Agentium (non affiché) : "
    )
    require(bool(bearer.strip()), "AGENTIUM_TOKEN_REQUIRED")
    authorization = bearer if bearer.startswith("Bearer ") else "Bearer " + bearer
    with httpx.Client(
        base_url=ORIGIN,
        timeout=45,
        follow_redirects=False,
        headers={
            "Authorization": authorization,
            "X-Workspace-Slug": WORKSPACE_SLUG,
        },
    ) as client:
        bearer = authorization = None

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        live = get(f"/api/v1/systems/{SYSTEM_ID}/flow-state")
        # Rebuild from checked-in fixtures and live state, preventing an edited
        # plan from introducing another skill, system, effect or evidence text.
        require(sha(build(live)) == sha(plan), "PLAN_CHANGED_OR_STALE")
        budgets = get("/api/v1/observability/usage/budgets")
        checks = check_preflight(
            plan=plan,
            live_flow=live,
            workspace=get(f"/api/v1/auth/workspaces/{WORKSPACE_SLUG}"),
            readiness=get("/api/v1/observability/usage/readiness"),
            budgets=budgets,
            providers=get("/api/v1/models/providers"),
            tariffs=get("/api/v1/observability/usage/tariffs"),
        )
        case = next(row for row in plan["cases"] if row["case_id"] == args.case)
        request = case["request"]
        receipt = {
            "case_id": args.case,
            "preflight": checks,
            "executed": False,
            "request_sha256": sha(request),
            "preserve": plan["preserve"],
        }
        if not args.execute:
            print(
                json.dumps(
                    {**receipt, "result": "preflight_passed; no inference dispatched"},
                    indent=2,
                )
            )
            return
        args.record.parent.mkdir(parents=True, exist_ok=True)
        # No idempotency key exists on node-runs: reserve the local receipt
        # before POST, do not retry ambiguous timeouts or overwrite receipts.
        with args.record.open("x") as stream:
            json.dump({**receipt, "dispatch_state": "starting"}, stream, indent=2)
        response = client.post(request["path"], json=request["body"])
        response.raise_for_status()
        run = response.json()
        require(
            run.get("system_id") == SYSTEM_ID
            and run.get("execution_surface") == "node_preview",
            "UNEXPECTED_RUN_SCOPE",
        )
        receipt.update(
            executed=True,
            dispatch_state="queued",
            run_id=run["id"],
            run_status=run["status"],
            run_url=f"{ORIGIN}/runs/{run['id']}",
        )
        args.record.write_text(json.dumps(receipt, indent=2) + "\n")
        after = get(f"/api/v1/systems/{SYSTEM_ID}/flow-state")
        require(
            flow_identity(after) == plan["preserve"], "LUMA_FLOW_CHANGED_DURING_PREVIEW"
        )
        after_budgets = get("/api/v1/observability/usage/budgets")

        def stable(rows):
            return [
                {key: value for key, value in row.items() if key != "current_period"}
                for row in rows
            ]

        require(
            stable(budgets["items"]) == stable(after_budgets["items"]),
            "BUDGET_POLICY_CHANGED",
        )
        receipt.update(flow_preserved=True, budget_policy_preserved=True)
        args.record.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(
            json.dumps(
                {
                    "error": "HTTP_REQUEST_REFUSED",
                    "status": exc.response.status_code,
                    "path": exc.request.url.path,
                    "automatic_retry": False,
                }
            )
        )
        raise SystemExit(1) from None
    except httpx.HTTPError:
        print(
            json.dumps({"error": "HTTP_OUTCOME_UNCONFIRMED", "automatic_retry": False})
        )
        raise SystemExit(1) from None
    except (ValueError, KeyError, StopIteration) as exc:
        print(json.dumps({"error": str(exc), "automatic_retry": False}))
        raise SystemExit(1) from None
