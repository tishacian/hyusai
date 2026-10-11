"""Bounded live API qualification. Credentials are read from stdin, never written.

Input JSON: {"base_url":"https://agentium.papai.ai/api/v1", "token":"...",
"workspace":"agentium-showcase", "system_id":"..."}. Run `--help` for phases.
Generation writes proposals only. Compare requires an explicitly reviewed SuiteBody
JSON file (including answer_path for the actual System output); it never approves
model-generated references. No System, shared Skill or published version is edited.
"""
from __future__ import annotations
import argparse
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

NORTHFORGE = "5c0f10fa-c7ff-499a-bd99-6efda2a98fb1"
TERMINAL = {"completed", "failed", "cancelled"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["inspect", "generate", "compare", "report"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--reviewed-suite", type=Path)
    parser.add_argument("--baseline-run")
    parser.add_argument("--draft-revision", type=int)
    parser.add_argument("--timeout", type=int, default=600, choices=range(30, 1201), metavar="30..1200")
    args = parser.parse_args()
    import sys
    config = json.load(sys.stdin)
    base = config["base_url"].rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
        raise SystemExit("HTTPS or an explicitly local forwarded endpoint is required")
    if config["workspace"] != "agentium-showcase":
        raise SystemExit("This qualification is restricted to Showcase")
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    scope = {"base_url": base, "workspace": config["workspace"], "system_id": config["system_id"]}
    if state.get("scope", scope) != scope:
        raise SystemExit("State belongs to another target")
    state["scope"] = scope

    def save():
        args.state.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
            json.dump(state, handle, indent=2)

    def api(path, body=None):
        request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + config["token"], "X-Workspace-Slug": config["workspace"],
                     "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            # Do not print arbitrary vendor/server payloads or credentials.
            raise SystemExit(f"API {request.get_method()} {path}: HTTP {exc.code}; inspect the authorized UI") from None
        except (URLError, TimeoutError):
            raise SystemExit("Network result uncertain. Reuse this state file; do not generate a new request key.") from None

    def key(name):
        state.setdefault(name + "_request_key", str(uuid.uuid4()))
        save()
        return state[name + "_request_key"]

    def poll(path, field):
        deadline = time.monotonic() + args.timeout
        while True:
            result = api(path)
            state[field] = result
            save()
            if result.get("status") in TERMINAL:
                print(json.dumps({"phase": field, "id": result.get("id"), "status": result["status"]}))
                if result["status"] != "completed":
                    raise SystemExit("Qualification did not complete; details are in the restricted state file")
                return result
            if time.monotonic() >= deadline:
                raise SystemExit("Polling deadline reached; persisted job remains resumable with this state file")
            time.sleep(3)

    if args.phase == "inspect":
        state["system"] = api("/systems/" + config["system_id"])
        state["manifest"] = api("/systems/" + config["system_id"] + "/flow-manifest")
        collections = api("/documents/collections")
        state["collection"] = next((row for row in collections.get("items", []) if row["id"] == NORTHFORGE), None)
        if not state["collection"]:
            raise SystemExit("Authorized NorthForge collection not found")
        save()
        print(json.dumps({"status": "inspected", "system_id": config["system_id"], "collection_id": NORTHFORGE}))
    elif args.phase == "generate":
        body = {"system_id": config["system_id"], "collection_ids": [NORTHFORGE], "num_questions": 3,
                "language": "en", "max_calls": 24, "max_tokens": 60000, "request_key": key("generation")}
        job = api("/evaluation/generations", body)
        state["generation_id"] = job["id"]
        save()
        poll("/evaluation/generations/" + job["id"], "generation")
        print("Generated cases remain proposals. Review question, reference passage, input mapping and answer_path before compare.")
    elif args.phase == "compare":
        if not args.reviewed_suite or not args.baseline_run or not args.draft_revision:
            raise SystemExit("compare requires --reviewed-suite, --baseline-run and --draft-revision")
        body = json.loads(args.reviewed_suite.read_text())
        if body.get("reviewed") is not True or body.get("system_id") != config["system_id"] or body.get("collection_ids") != [NORTHFORGE]:
            raise SystemExit("Reviewed suite must explicitly target this System and NorthForge only")
        if len(body.get("cases", [])) > 3:
            raise SystemExit("Live qualification is bounded to three reviewed cases")
        body["generation_job_id"] = state["generation_id"]
        if "suite" not in state:
            # Suite creation is revisioned but not idempotent. On an uncertain response
            # inspect /evaluation/suites and recover the revision before retrying.
            if state.get("suite_post_started"):
                raise SystemExit("Suite POST was uncertain. Recover its ID from the UI into state.suite before retrying")
            state["suite_post_started"] = True
            save()
            state["suite"] = api("/evaluation/suites", body)
            save()
        campaign = api("/evaluation/campaigns", {"suite_id": state["suite"]["id"], "baseline_run_id": args.baseline_run,
            "expected_draft_revision": args.draft_revision, "request_key": key("comparison")})
        state["campaign_id"] = campaign["id"]
        save()
        poll("/evaluation/campaigns/" + campaign["id"], "campaign")
    else:
        job = api("/evaluation/campaigns/" + state["campaign_id"] + "/raget", {"request_key": key("raget")})
        state["raget_id"] = job["id"]
        save()
        poll("/evaluation/generations/" + job["id"], "raget")


if __name__ == "__main__":
    main()
