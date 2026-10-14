#!/usr/bin/env python3
"""Read existing Docker images; never build, pull, load, prune or deploy.

Run on the VM with Python 3, passing each release tag via --tag. JSON on stdout
contains selected metadata only, never container/image environments or history
commands. Missing images remain missing; no alternative size is substituted.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


BUDGETS = {"backend": 1400, "worker": 1760, "frontend": 40,
           "ml-ts": 1240, "livekit-agent": 110}
EXPECTED_SCRIPT_SHA256 = "1abd2f02b780fff2190099833bffc7a631c34aad2b397018112a2b9e25aa1366"
DEFAULT_SCRIPT = "/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-image-budget.sh"
DOCKER_SOCKET = "unix:///var/run/docker.sock"


def local_docker_env():
    env = os.environ.copy()
    for key in ("DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(key, None)
    env["DOCKER_HOST"] = DOCKER_SOCKET
    return env


def run(argv, env=None):
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=60, env=env if env is not None else local_docker_env(),
                                check=False)
        return {"exit_code": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Do not serialize the exception: it can contain partial command output.
        return {"exit_code": None, "stdout": "", "stderr": type(exc).__name__}


def inspect_image(reference):
    # Project inside Docker, rather than dumping Config.Env or all labels.
    template = ('{"id":{{json .Id}},"repo_tags":{{json .RepoTags}},'
                '"repo_digests":{{json .RepoDigests}},"created":{{json .Created}},'
                '"size_bytes":{{json .Size}},"os":{{json .Os}},'
                '"architecture":{{json .Architecture}},'
                '"descriptor":{{json (index . "Descriptor")}},'
                '"diff_ids":{{json .RootFS.Layers}},'
                '"revision":{{if .Config.Labels}}{{json (index .Config.Labels '
                '"org.opencontainers.image.revision")}}{{else}}null{{end}}}')
    result = run(["docker", "image", "inspect", "--format", template, reference])
    if result["exit_code"] != 0:
        return {"reference": reference, "available": False, "error": result}
    data = json.loads(result["stdout"])
    if isinstance(data.get("descriptor"), dict):
        # Containerd image IDs may name an index/manifest, not the image config.
        data["descriptor"] = {key: data["descriptor"].get(key)
                              for key in ("mediaType", "digest", "size")}
    data.update(reference=reference, available=True,
                size_mib_floor=data["size_bytes"] // 1048576)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", action="append", required=True,
                        help="Existing release tag; repeat for reference and candidate")
    parser.add_argument("--budget-script", type=Path, default=Path(DEFAULT_SCRIPT))
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", t) for t in args.tag):
        parser.error("invalid Docker release tag")
    report = {"schema_version": 1,
              "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "read-only metadata for existing images, no deployment qualification",
              "budgets_mib": BUDGETS, "docker_endpoint": DOCKER_SOCKET,
              "releases": []}
    info_template = ('{"server_version":{{json .ServerVersion}},'
                     '"driver":{{json .Driver}},"driver_status":{{json .DriverStatus}},'
                     '"os_type":{{json .OSType}},"architecture":{{json .Architecture}}}')
    info = run(["docker", "info", "--format", info_template])
    report["docker"] = json.loads(info["stdout"]) if info["exit_code"] == 0 else info
    try:
        script_hash = hashlib.sha256(args.budget_script.read_bytes()).hexdigest()
    except OSError:
        script_hash = None
    script_ok = script_hash == EXPECTED_SCRIPT_SHA256
    report["budget_script"] = {"path": str(args.budget_script), "sha256": script_hash,
                               "expected_sha256": EXPECTED_SCRIPT_SHA256,
                               "matches_reviewed_script": script_ok}
    env = local_docker_env()
    for name, budget in BUDGETS.items():
        env["AGENTIUM_IMAGE_BUDGET_MB_" + name.upper().replace("-", "_")] = str(budget)
    env["AGENTIUM_IMAGE_REQUIRE_LIVEKIT_AGENT"] = "1"
    passed = info["exit_code"] == 0 and script_ok
    for tag in dict.fromkeys(args.tag):
        images = [inspect_image("agentium-" + name + ":" + tag) for name in BUDGETS]
        budget_result = (run(["bash", str(args.budget_script), tag], env=env)
                         if script_ok else {"exit_code": None, "stdout": "",
                                            "stderr": "reviewed budget script missing or changed"})
        report["releases"].append({"tag": tag, "images": images,
                                   "all_listed_images_measured": all(i["available"] for i in images),
                                   "budget_check": budget_result})
        passed = passed and budget_result["exit_code"] == 0
    report["all_requested_budget_checks_passed"] = bool(passed)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
