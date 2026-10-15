#!/usr/bin/env python3
"""Read Compose/Docker JSON without exposing its environment or credentials."""

from __future__ import annotations

import argparse
import json
import re
import sys

FLAGS = (
    "ACTIVITY_OBSERVABILITY_ENABLED",
    "EXECUTION_CONTROL_ENABLED",
    "EXECUTION_DURABLE_DISPATCH_ENABLED",
    "EXECUTION_TEMPORAL_ENABLED",
)
SERVICES = ("agentium-worker-control", "agentium-scheduler-control")
APP = "app.workers.execution_control:app"
COMMANDS = {
    SERVICES[0]: [
        "python",
        "-m",
        "celery",
        "-A",
        APP,
        "worker",
        "-Q",
        "control",
        "-c",
        "1",
        "--pool",
        "solo",
        "--without-gossip",
        "--without-mingle",
        "--loglevel",
        "info",
    ],
    SERVICES[1]: [
        "python",
        "-m",
        "celery",
        "-A",
        APP,
        "beat",
        "--max-interval",
        "1",
        "--schedule",
        "/tmp/control-celerybeat-schedule",
        "--pidfile",
        "/tmp/control-beat.pid",
        "--loglevel",
        "info",
    ],
}


def flags(environment: dict) -> tuple[bool, ...]:
    if not isinstance(environment, dict):
        raise TypeError("Service environment is unavailable")
    enabled = []
    for key in FLAGS:
        value = str(environment.get(key, "false")).lower()
        if value not in {
            "true",
            "1",
            "yes",
            "y",
            "on",
            "t",
            "false",
            "0",
            "no",
            "n",
            "off",
            "f",
        }:
            raise ValueError("An execution flag is invalid")
        enabled.append(value in {"true", "1", "yes", "y", "on", "t"})
    return tuple(enabled)


def required(document: dict) -> bool:
    return any(flags(document["services"]["agentium-backend"]["environment"]))


def aligned(document: dict) -> bool:
    services = document["services"]
    expected = flags(services["agentium-backend"]["environment"])
    for name in SERVICES:
        if flags(services[name]["environment"]) != expected:
            raise ValueError("Control and backend execution flags differ")
    return True


def worker_destination(document: list, *, image: str, revision: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or not re.fullmatch(
        r"[0-9a-f]{40}", revision
    ):
        raise ValueError("Expected release image or revision is invalid")
    containers = {row["Name"].removeprefix("/"): row for row in document}
    if len(document) != 2 or set(containers) != set(SERVICES):
        raise ValueError("Both control containers are required")
    for name, row in containers.items():
        state, config = row["State"], row["Config"]
        if (
            state.get("Running") is not True
            or state.get("Restarting")
            or state.get("Paused")
        ):
            raise ValueError("A control container is not running")
        if (
            row["Image"] != image
            or config.get("Labels", {}).get("org.opencontainers.image.revision")
            != revision
        ):
            raise ValueError("Control does not run the verified release revision")
        if config.get("Cmd") != COMMANDS[name]:
            raise ValueError("A control process has an unexpected command")
        environment = dict(
            item.split("=", 1) for item in config.get("Env", []) if "=" in item
        )
        expected = {
            "CELERY_APP": APP,
            "CELERY_CONTROL_QUEUE": "control",
            "CELERY_QUEUES": "control",
            "CELERY_CONCURRENCY": "1",
            "CELERY_BEAT": "0",
            "AGENTIUM_DISABLE_DOTENV": "1",
        }
        if any(environment.get(key) != value for key, value in expected.items()):
            raise ValueError("Control process isolation is invalid")
    hostname = containers[SERVICES[0]]["Config"]["Hostname"]
    if not isinstance(hostname, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,64}", hostname
    ):
        raise ValueError("Control worker hostname is invalid")
    return "celery@" + hostname


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("required")
    commands.add_parser("aligned")
    runtime = commands.add_parser("runtime")
    runtime.add_argument("--image", required=True)
    runtime.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        content = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024:
            raise ValueError("Input too large")
        document = json.loads(content)
        if args.command == "runtime":
            result = worker_destination(
                document, image=args.image, revision=args.revision
            )
        else:
            check = required if args.command == "required" else aligned
            result = str(int(check(document)))
    except (ValueError, TypeError, KeyError, AttributeError):
        # Compose and inspect contain secrets. Never print their content or a
        # parser exception, even when the input is malformed.
        print("Execution control configuration/runtime check failed", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
