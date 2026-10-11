#!/usr/bin/env python3
"""Five real Showcase Work executions, with resumable idempotency keys.

Run on carakai. Records synthetic outputs only, never credentials. This is a
technical check of arithmetic, dispatch and provenance, not human validation.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from observability_live import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from scripts.showcase_operational_analysis import EXPECTED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    client = Client("https://agentium.papai.ai/api/v1", "/root/.attestation-username", "/root/.attestation-password")
    build = client.call("/build-info")
    assert build.get("revision_verified") and build["revision"] == args.sha, "Unexpected deployed SHA"
    state = json.loads(args.state.read_text()) if args.state.exists() else {"sha": args.sha, "attempts": []}
    assert state["sha"] == args.sha, "Never mix candidates in one qualification report"

    def save():
        args.state.write_text(json.dumps(state, indent=2))

    def invoke(key):
        request = urllib.request.Request(client.base + "/work/operational-analysis/bindings/showcase.operational.analyze/runs",
            data=json.dumps({"payload": {}, "page_id": "analysis", "component_id": "analyze"}).encode(),
            headers={"Content-Type": "application/json", "X-Workspace-Slug": "agentium-showcase",
                     "Authorization": "Bearer " + client.token, "Idempotency-Key": key})
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)

    app = client.call("/work/operational-analysis")
    state["experience_id"] = app["experience"]["id"]
    for index in range(5):
        if len(state["attempts"]) <= index:
            state["attempts"].append({"key": str(uuid.uuid4())})
            save()  # Preserve the key before dispatch, including uncertain network responses.
        attempt = state["attempts"][index]
        if attempt.get("passed"):
            continue
        started = time.monotonic()
        receipt = invoke(attempt["key"])
        attempt["receipt"] = receipt
        save()
        run = client.poll("/runs/" + receipt["id"], seconds=900)
        attempt["run"] = run
        attempt["seconds"] = round(time.monotonic() - started, 3)
        save()
        assert run["status"] == "completed", f"Run {receipt['id']} ended {run['status']}: {run.get('error')}"
        output = run["output_ref"]
        assert output.get("stats") == EXPECTED, "Numerical reference mismatch"
        assert output.get("numerical_reference_passed") is True
        assert output.get("human_validated") is False
        assert isinstance(output.get("answer"), str) and output["answer"].strip()
        assert run["flow_evidence"]["flow_version_id"], "Missing immutable Flow version"
        invocations = run.get("invocations", [])
        assert sum(i["skill_slug"] == "python_recipe_v1" and i["status"] == "completed" for i in invocations) == 2
        assert any(i["skill_slug"] == "llm_rag_answer_v1" and i["status"] == "completed" for i in invocations)
        replay = invoke(attempt["key"])
        assert replay["id"] == receipt["id"] and replay["idempotent_replay"] is True
        attempt["passed"] = True
        save()
        print(json.dumps({"iteration": index + 1, "run_id": receipt["id"], "seconds": attempt["seconds"], "passed": True}), flush=True)
    state["status"] = "five_passed"
    save()


if __name__ == "__main__":
    main()
