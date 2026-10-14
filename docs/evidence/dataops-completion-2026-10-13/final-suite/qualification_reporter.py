"""Persist worker results immediately so an interrupted lab retains diagnostics."""
import json
import os
from pathlib import Path


def pytest_runtest_logreport(report):
    if report.when != "call" and not report.failed and not report.skipped:
        return
    value = {"nodeid": report.nodeid, "when": report.when,
             "outcome": report.outcome, "duration": report.duration}
    if report.failed:
        value["longrepr"] = report.longreprtext
    # Every process has its own file: xdist workers and the coordinator cannot
    # interleave writes. The coordinator's log is authoritative when present.
    worker = os.environ.get("PYTEST_XDIST_WORKER", "coordinator")
    target = Path(os.environ["QUALIFICATION_REPORT_PREFIX"] + "." + worker + ".jsonl")
    with target.open("a") as stream:
        stream.write(json.dumps(value) + "\n")
        if report.failed:
            stream.flush()
            os.fsync(stream.fileno())


def pytest_sessionfinish(session, exitstatus):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "coordinator")
    target = Path(os.environ["QUALIFICATION_REPORT_PREFIX"] + "." + worker + ".finished.json")
    target.write_text(json.dumps({"exit_code": int(exitstatus),
                                  "collected": session.testscollected,
                                  "failed": session.testsfailed}) + "\n")
