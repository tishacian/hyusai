# Translation Suite runner contract

**Status:** contract, 23 October 2026. The Agentium side (catalog
`translation_suite.*` in `backend/app/services/remote_runners/catalogs/`) is
implemented; the machine side is the `ts.runner` entry point of the
translation pipeline repository, qualified on a GPU runner on 23 October 2026.

## How a command runs

Agentium's external runner connects over SSH, creates a job directory
`<work_root>/jobs/<job_id>`, uploads the job's inputs under `inputs/`, and
starts, in its own session:

```
env PYTHONPATH=<translation.repo> <translation.python> -m ts.runner <subcommand> \
  --repo <translation.repo> --base-dir <translation.base_dir> --lot <lot> [options]
```

with the job directory as working directory, `stdout.log` / `stderr.log`
captured and the exit code recorded. The three paths are runner labels set by
an administrator; `translation.base_dir` must not be a tree another
orchestrator writes to on the same machine.

Every subcommand must:

1. Exit `0` on success and non-zero on failure. A gate that refuses is a
   success of the command with a negative verdict in `result.json`, not a
   failure, so the flow can route on it.
2. Write `result.json` (a JSON object, at most 1 MB) in the job directory.
3. Write each declared artifact in the job directory (missing artifacts are
   reported as absent, not fatal).
4. Stop every process it started when it receives `SIGTERM`. The runner
   signals the job's process group; a child started with its own session
   (for instance `start_new_session=True`) must be stopped by the entry point
   itself, otherwise cancellation does not reach it. After a grace period the
   group receives `SIGKILL`.
5. Keep the lot working tree in `<base_dir>/<lot>/` between subcommands, and
   never write outside `<base_dir>` and the job directory.

## Subcommands

| Subcommand | Options | Reads | `result.json` | Artifacts |
| --- | --- | --- | --- | --- |
| `prepare` | `--archive inputs/<name>.zip` (default: the one .zip under `inputs/`), `--source-lang`, `--pivot-lang`, `--target` (repeatable) | the staged source pack | `{job_id, languages: [..], topics: n, pivot_mode}` | `job.json` |
| `translate` | `--max-parallel n` | the prepared lot | `{languages: {<tag>: {accept, needs_review, reject_technical, failed}}, complete: bool}` | `outcomes.json` (one entry per topic and language) |
| `review-export` | none | reports of the lot | `{items: n, groups: [..]}` | `review.jsonl`, `quality_gate.json` |
| `audit` | none | the lot | `{verdict: "pass" \| "fail", layers: {<layer>: "pass" \| "fail" \| "info"}}` | `audit.json` |
| `reinject` | `--decisions inputs/decisions.jsonl` | reviewers' decisions | `{applied: n, skipped: n, requalified_topics: n}` | `reinject_report.json` |
| `package` | `--producer-commit <sha>` (optional) | the lot | `{verdict: "pass" \| "blocked", blockers: [..]}` | `package.zip`, `release_certificate.json` |

`package` only returns `pass` when the release certificate is `ACCEPTED`:
the certificate requires the full locale set (39), the cleanroom quality
report and the resolved-view receipts of the archive. Otherwise the built
archive stays on the machine, `result.json` lists the certificate blockers
(`certificate:<code>`) and no `package.zip` is returned. `audit` and the
archive audit inside `package` fail when no file was checked.

`translate` runs the scheduler in the foreground: the job ends when the lot is
translated, never by polling a marker file. Completion is read from the topic
outcomes, not from cost files.

## `review.jsonl`: one line per segment to review

```json
{
  "item_ref": "<stable id, e.g. the element uuid>",
  "group": "<target language tag>",
  "tier": "P0",
  "weight": 12,
  "subject": {
    "source": "text without markup",
    "candidate": "proposed translation",
    "direction": "ltr",
    "context": {"before": ["..."], "after": ["..."]},
    "references": [{"source": "...", "target": "...", "score": 0.93, "label": "file"}],
    "findings": [{"category": "WT", "severity": "major", "text": "...", "fixed": false}],
    "protected_spans": ["@@REF-12@@"]
  }
}
```

`weight` is the word count of the source. `tier` is one of `P0` to `P4`.
Agentium opens one review set per `group` with the J2450 taxonomy (seven
categories, minor and major) and the tier policy configured in the flow.

## `inputs/decisions.jsonl`: what `reinject` receives

One line per decided segment, as returned by `review_set_read_v1`:
`{item_ref, tier, decision: "approve" | "correct" | "reject", value,
annotations: [{category, severity}], comment, subject}`. Only `correct` lines
change the lot; `reject` lines are reported for a new translation.
