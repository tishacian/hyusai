"""A customer can be a fixture or an adapter, never a dependency of the engine.

This is the ratchet behind docs/adr/0003-generalisation-frontieres.md. It
counts customer identifiers in executable code and data only: comments and
docstrings carry the reasons and the lessons learnt from those customers, and
must stay free to name them.

Every file that still carries identifiers is listed in
``tenant_neutral_baseline.json`` with its count and its kind:

- ``adapter``: code a customer family, pack or manifest selects on purpose.
- ``family``: the canonical family names themselves.
- ``fixture``: a customer's content or rule inside a generic module. Goes to 0.
- ``demo``: scripted demo content living among services. Moves to seeds.
- ``client-app``: a customer application or skin inside the product shell.
- ``tooling``: command-line examples.

The counts must match exactly. A file that gains identifiers fails; a file
that loses some also fails until its entry is lowered, so a cleanup cannot be
undone quietly by the next change.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BACKEND_APP = REPO / "backend" / "app"
FRONTEND_APP = REPO / "frontend-ng" / "src" / "app"
BASELINE = Path(__file__).with_name("tenant_neutral_baseline.json")

IDENTIFIERS = re.compile(r"(?<![a-z])(nawa|andritz|pih)(?![a-z])|spark-?0?89", re.IGNORECASE)
WEB_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->|(?<![:\w])//[^\n]*", re.DOTALL)
KINDS = {"adapter", "family", "fixture", "demo", "client-app", "tooling"}


def _docstring_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    return lines


def _python_count(text: str) -> int:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return len(IDENTIFIERS.findall(text))
    docstring_lines = _docstring_lines(tree)
    count = 0
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.start[0] in docstring_lines:
            continue
        count += len(IDENTIFIERS.findall(token.string))
    return count


def _web_count(text: str) -> int:
    return len(IDENTIFIERS.findall(WEB_COMMENTS.sub("", text)))


def scan() -> dict[str, int]:
    """Identifier counts per repository-relative path, product code only."""

    found: dict[str, int] = {}
    for path in BACKEND_APP.rglob("*.py"):
        if "tests" in path.relative_to(BACKEND_APP).parts:
            continue
        count = _python_count(path.read_text(encoding="utf-8", errors="ignore"))
        if count:
            found[str(path.relative_to(REPO))] = count
    for path in FRONTEND_APP.rglob("*"):
        if path.suffix not in {".ts", ".html", ".scss"} or path.name.endswith(".spec.ts"):
            continue
        count = _web_count(path.read_text(encoding="utf-8", errors="ignore"))
        if count:
            found[str(path.relative_to(REPO))] = count
    return found


def _baseline() -> dict[str, dict]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["files"]


def test_every_baseline_entry_has_a_known_kind():
    unknown = {path: entry.get("kind") for path, entry in _baseline().items() if entry.get("kind") not in KINDS}
    assert not unknown, unknown


def test_customer_identifiers_only_where_the_baseline_says():
    baseline = _baseline()
    current = scan()
    problems = []
    for path, count in sorted(current.items()):
        entry = baseline.get(path)
        if entry is None:
            problems.append(
                f"{path} now names a customer {count} time(s). Customer content belongs in a"
                " declared adapter, a seed or a test fixture; if this file is one, add it to"
                " tenant_neutral_baseline.json with its kind."
            )
        elif count > entry["count"]:
            problems.append(f"{path} gained customer identifiers: {entry['count']} -> {count}.")
        elif count < entry["count"]:
            problems.append(
                f"{path} lost customer identifiers ({entry['count']} -> {count}). Lower its"
                " baseline entry so the gain is kept."
            )
    for path in sorted(set(baseline) - set(current)):
        problems.append(f"{path} no longer names any customer: remove its baseline entry.")
    assert not problems, "\n".join(problems)


def test_no_setting_lists_workspace_slugs():
    """A per-customer switch is a workspace setting, never a deployment list."""

    from app.core.config import Settings

    lists = sorted(name for name in Settings.model_fields if name.endswith("_workspace_slugs"))
    assert not lists, lists


def test_no_gate_falls_back_to_a_slug_list():
    offenders = []
    for path in BACKEND_APP.rglob("*.py"):
        if path == Path(__file__):
            continue
        if "csv_fallback" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, offenders


def test_no_branch_on_a_customer_slug():
    """Runtime code selects on the stamped family, never on a mutable slug."""

    slug_branch = re.compile(
        r"slug[^\n=]{0,30}(==|!=|\bin\b|startswith)\s*[(\[{]?\s*[\"'](nawa|andritz|pih)"
        r"|[\"'](nawa|andritz|pih)[a-z_-]*[\"']\s*(==|!=|\bin\b)\s*[\w.]*slug",
        re.IGNORECASE,
    )
    offenders = []
    for path in BACKEND_APP.rglob("*.py"):
        if "tests" in path.relative_to(BACKEND_APP).parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        docstrings = _docstring_lines(ast.parse(text))
        for number, line in enumerate(text.splitlines(), 1):
            if number in docstrings or line.lstrip().startswith("#"):
                continue
            if slug_branch.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{number}")
    assert not offenders, offenders
