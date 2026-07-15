#!/usr/bin/env python3
"""Generate and verify Agentium's repository compliance contract.

The manifest contains expected, inspectable proofs. It never contains a
hand-written delivery state: the repository state is derived from those
proofs on every run. Runner results and deployment attestations are accepted
as separate, SHA-bound evidence and never upgrade the static repository state.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config/agentium/product-compliance.v1.json"
REQUIRED_FAMILIES: dict[str, tuple[str, ...]] = {
    "frontend": ("implementation", "frontend", "tests"),
    "backend": ("implementation", "tests"),
    "api": ("implementation", "api", "tests"),
    "full_stack": ("implementation", "api", "frontend", "tests"),
    "migration": ("implementation", "tests"),
    "governance": ("implementation", "tests"),
}
PROOF_FAMILIES = ("implementation", "api", "frontend", "tests")
RUNNERS = frozenset({"pytest", "node", "playwright"})
FORMAL_SHIPPED_RE = re.compile(r"\bshipped\b", re.IGNORECASE)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CLAIM_ID_RE = re.compile(r"^LOT[0-5]-[A-Z0-9][A-Z0-9-]*$")


class ComplianceError(ValueError):
    """Raised when the compliance contract cannot be evaluated safely."""


@dataclass(frozen=True)
class ProofResult:
    family: str
    label: str
    path: str
    passed: bool
    missing_literals: tuple[str, ...]


@dataclass(frozen=True)
class ClaimResult:
    claim: dict[str, Any]
    required_families: tuple[str, ...]
    required_runners: tuple[str, ...]
    proofs: tuple[ProofResult, ...]
    computed_state: str

    @property
    def static_verified(self) -> bool:
        return self.computed_state == "static_verified"


@dataclass(frozen=True, order=True)
class WorkspaceSlugBranch:
    path: str
    expression: str


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ComplianceError(f"JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ComplianceError(f"Invalid JSON in {path}: {exc}") from exc


def _forbidden_state_keys(value: Any, trail: str = "$") -> list[str]:
    """Return manifest locations containing a manually authored state key."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_trail = f"{trail}.{key}"
            if str(key).lower() == "status":
                found.append(child_trail)
            found.extend(_forbidden_state_keys(child, child_trail))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_state_keys(child, f"{trail}[{index}]"))
    return found


def _repo_path(root: Path, raw: Any, *, field: str, must_exist: bool = True) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ComplianceError(f"{field} must be a non-empty repository-relative path")
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ComplianceError(f"{field} escapes the repository: {raw}") from exc
    if must_exist and not candidate.is_file():
        raise ComplianceError(f"Referenced file does not exist ({field}): {raw}")
    return candidate


def _expect_string_list(value: Any, *, field: str, non_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (non_empty and not value):
        qualifier = "non-empty " if non_empty else ""
        raise ComplianceError(f"{field} must be a {qualifier}list of strings")
    if any(not isinstance(item, str) or not item for item in value):
        raise ComplianceError(f"{field} must contain only non-empty strings")
    return value


def _normalized_expression(value: str) -> str:
    return " ".join(value.split())


def _python_workspace_slug_access(node: ast.AST) -> bool:
    """Return whether *node* contains a Workspace identity slug access.

    Other domain objects also have slugs (Capability, Skill, map rows, ...), so
    a bare ``.slug`` check would turn their legitimate dispatch into tenant
    debt.  Workspace variables/classes are deliberately recognised by name;
    direct ``slug`` aliases remain covered only for versioned identity literals.
    """

    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute) or child.attr.lower() != "slug":
            continue
        owner = ast.unparse(child.value).lower()
        owner_tokens = set(re.findall(r"[a-z_][a-z0-9_]*", owner))
        if any(
            token == "ws"
            or token.startswith("ws_")
            or re.search(r"(?:^|_)workspace(?:$|_)", token)
            for token in owner_tokens
        ):
            return True
    return False


def _python_workspace_slug_branches(
    path: Path,
    relative_path: str,
    identity_literals: set[str],
) -> list[WorkspaceSlugBranch]:
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=relative_path)
    except SyntaxError as exc:
        raise ComplianceError(
            f"Cannot scan workspace slug branches in {relative_path}: {exc}"
        ) from exc

    constants: dict[str, str] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            constants[target.id] = value.value

    branches: list[WorkspaceSlugBranch] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        names: set[str] = set()
        literal_values: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
            elif isinstance(child, ast.Attribute):
                names.add(child.attr)
            elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                literal_values.add(child.value)
        literal_values.update(constants[name] for name in names if name in constants)
        static_constant_reference = any(
            name == name.upper() and name.endswith("_WORKSPACE_SLUG") for name in names
        )
        known_alias_branch = any(
            name.lower() in {"slug", "workspace_slug"} for name in names
        ) and bool(identity_literals.intersection(literal_values))
        has_static_identity = (
            bool({value for value in literal_values if value.strip()})
            or static_constant_reference
        )
        if not (
            (_python_workspace_slug_access(node) and has_static_identity)
            or known_alias_branch
        ):
            continue
        expression = ast.get_source_segment(text, node)
        if not expression:
            raise ComplianceError(
                f"Cannot recover branch expression in {relative_path}:{node.lineno}"
            )
        branches.append(
            WorkspaceSlugBranch(
                path=relative_path,
                expression=_normalized_expression(expression),
            )
        )
    return branches


def _typescript_workspace_slug_branches(
    path: Path,
    relative_path: str,
    identity_literals: set[str],
) -> list[WorkspaceSlugBranch]:
    text = path.read_text(encoding="utf-8")
    constants = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"(?:const|readonly)\s+([A-Z][A-Z0-9_]*)[^=]*=\s*['\"]([^'\"]+)['\"]",
            text,
        )
    }
    workspace_slug_accessor = re.compile(
        r"(?:[A-Za-z_$][\w$]*(?:\?\.|\.))*" r"(?:workspace|ws)(?:\?\.|\.)slug",
        re.IGNORECASE,
    )
    literal_comparison = re.compile(
        r"(?:"
        + workspace_slug_accessor.pattern
        + r")\s*(?:===|!==|==|!=)\s*(['\"])([^'\"]+)\1"
        r"|(['\"])([^'\"]+)\3\s*(?:===|!==|==|!=)\s*(?:"
        + workspace_slug_accessor.pattern
        + r")",
        re.IGNORECASE,
    )
    explicit_alias_comparison = re.compile(
        r"\b(?:workspaceSlug|workspace_slug|workspace)\b\s*"
        r"(?:===|!==|==|!=)\s*(['\"])([^'\"]+)\1"
        r"|(['\"])([^'\"]+)\3\s*(?:===|!==|==|!=)\s*"
        r"\b(?:workspaceSlug|workspace_slug|workspace)\b",
    )
    branches: list[WorkspaceSlugBranch] = []
    for line in text.splitlines():
        expression = line.strip()
        if not expression or not re.search(
            r"===|!==|(?<![=!])==(?!=)|(?<![=!])!=(?!=)", expression
        ):
            continue
        literal_values = set(re.findall(r"['\"]([^'\"]+)['\"]", expression))
        literal_values.update(
            value
            for name, value in constants.items()
            if re.search(rf"\b{re.escape(name)}\b", expression)
        )
        static_workspace_constant = bool(
            workspace_slug_accessor.search(expression)
            and re.search(r"\b[A-Z][A-Z0-9_]*_WORKSPACE_SLUG\b", expression)
        )
        known_plain_slug_alias = bool(
            re.search(
                r"\bslug\b\s*(?:===|!==|==|!=)|(?:===|!==|==|!=)\s*\bslug\b", expression
            )
            and identity_literals.intersection(literal_values)
        )
        if (
            literal_comparison.search(expression)
            or explicit_alias_comparison.search(expression)
            or static_workspace_constant
            or known_plain_slug_alias
        ):
            branches.append(
                WorkspaceSlugBranch(
                    path=relative_path,
                    expression=_normalized_expression(expression),
                )
            )
    return branches


def discover_workspace_slug_branches(
    inventory: dict[str, Any],
    root: Path = REPO_ROOT,
) -> Counter[WorkspaceSlugBranch]:
    identity_literals = set(inventory["identity_literals"])
    excluded_prefixes = tuple(
        f"{value.rstrip('/')}" for value in inventory["exclude_paths"]
    )
    excluded_suffixes = tuple(inventory["exclude_suffixes"])
    discovered: Counter[WorkspaceSlugBranch] = Counter()
    for raw_root in inventory["scan_roots"]:
        scan_root = (root / raw_root).resolve()
        for path in sorted(scan_root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".ts"}:
                continue
            relative_path = path.relative_to(root.resolve()).as_posix()
            if relative_path.endswith(excluded_suffixes) or any(
                relative_path == prefix or relative_path.startswith(prefix + "/")
                for prefix in excluded_prefixes
            ):
                continue
            if path.suffix == ".py":
                discovered.update(
                    _python_workspace_slug_branches(
                        path, relative_path, identity_literals
                    )
                )
            else:
                discovered.update(
                    _typescript_workspace_slug_branches(
                        path, relative_path, identity_literals
                    )
                )
    return discovered


def validate_workspace_slug_branch_inventory(
    inventory: Any,
    root: Path = REPO_ROOT,
) -> dict[str, Any]:
    if not isinstance(inventory, dict):
        raise ComplianceError("workspace_slug_branch_inventory must be an object")
    expected_keys = {
        "schema_version",
        "identity_literals",
        "scan_roots",
        "exclude_paths",
        "exclude_suffixes",
        "entries",
    }
    unknown = sorted(set(inventory) - expected_keys)
    missing = sorted(expected_keys - set(inventory))
    if unknown or missing:
        details = []
        if unknown:
            details.append("unknown keys: " + ", ".join(unknown))
        if missing:
            details.append("missing keys: " + ", ".join(missing))
        raise ComplianceError("workspace_slug_branch_inventory " + "; ".join(details))
    if inventory["schema_version"] != 1:
        raise ComplianceError(
            "workspace_slug_branch_inventory.schema_version must be 1"
        )
    _expect_string_list(
        inventory["identity_literals"],
        field="workspace_slug_branch_inventory.identity_literals",
    )
    _expect_string_list(
        inventory["scan_roots"], field="workspace_slug_branch_inventory.scan_roots"
    )
    _expect_string_list(
        inventory["exclude_paths"],
        field="workspace_slug_branch_inventory.exclude_paths",
        non_empty=False,
    )
    _expect_string_list(
        inventory["exclude_suffixes"],
        field="workspace_slug_branch_inventory.exclude_suffixes",
        non_empty=False,
    )
    for index, raw_root in enumerate(inventory["scan_roots"]):
        scan_root = (root / raw_root).resolve()
        try:
            scan_root.relative_to(root.resolve())
        except ValueError as exc:
            raise ComplianceError(
                f"workspace_slug_branch_inventory.scan_roots[{index}] escapes the repository"
            ) from exc
        if not scan_root.is_dir():
            raise ComplianceError(
                f"workspace slug scan root does not exist: {raw_root}"
            )

    entries = inventory["entries"]
    if not isinstance(entries, list):
        raise ComplianceError("workspace_slug_branch_inventory.entries must be a list")
    declared: Counter[WorkspaceSlugBranch] = Counter()
    categories = {
        "provisioning_identity",
        "runtime_legacy",
        "resolver_contract",
        "ui_compatibility",
    }
    entry_keys = {"path", "expression", "occurrences", "category", "reason"}
    for index, entry in enumerate(entries):
        prefix = f"workspace_slug_branch_inventory.entries[{index}]"
        if not isinstance(entry, dict) or set(entry) != entry_keys:
            raise ComplianceError(
                f"{prefix} must contain exactly {', '.join(sorted(entry_keys))}"
            )
        _repo_path(root, entry["path"], field=f"{prefix}.path")
        if not isinstance(entry["expression"], str) or not entry["expression"].strip():
            raise ComplianceError(f"{prefix}.expression must be a non-empty string")
        if (
            not isinstance(entry["occurrences"], int)
            or isinstance(entry["occurrences"], bool)
            or entry["occurrences"] < 1
        ):
            raise ComplianceError(f"{prefix}.occurrences must be a positive integer")
        if entry["category"] not in categories:
            raise ComplianceError(
                f"{prefix}.category must be one of {', '.join(sorted(categories))}"
            )
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            raise ComplianceError(f"{prefix}.reason must be a non-empty string")
        branch = WorkspaceSlugBranch(
            path=entry["path"],
            expression=_normalized_expression(entry["expression"]),
        )
        if branch in declared:
            raise ComplianceError(
                f"Duplicate workspace slug branch inventory entry: {branch}"
            )
        declared[branch] = entry["occurrences"]

    discovered = discover_workspace_slug_branches(inventory, root)
    mismatches = sorted(set(discovered) | set(declared))
    mismatches = [item for item in mismatches if discovered[item] != declared[item]]
    if mismatches:
        lines = []
        lines.append("Workspace slug branch inventory drift:")
        lines.extend(
            "  "
            f"{item.path} :: {item.expression} "
            f"(discovered={discovered[item]}, declared={declared[item]})"
            for item in mismatches
        )
        raise ComplianceError("\n".join(lines))
    return inventory


def validate_manifest(manifest: Any, root: Path = REPO_ROOT) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ComplianceError("Manifest root must be an object")
    forbidden = _forbidden_state_keys(manifest)
    if forbidden:
        raise ComplianceError(
            "Computed state cannot be authored in the manifest; forbidden key(s): "
            + ", ".join(forbidden)
        )
    if manifest.get("schema_version") != 1:
        raise ComplianceError("Manifest schema_version must be 1")
    root_keys = {
        "schema_version",
        "title",
        "generated",
        "governed_docs",
        "workspace_slug_branch_inventory",
        "claims",
    }
    unknown_root_keys = sorted(set(manifest) - root_keys)
    if unknown_root_keys:
        raise ComplianceError(
            "Manifest root has unknown keys: " + ", ".join(unknown_root_keys)
        )
    if not isinstance(manifest.get("title"), str) or not manifest["title"].strip():
        raise ComplianceError("title must be a non-empty string")

    generated = manifest.get("generated")
    if not isinstance(generated, dict):
        raise ComplianceError("generated must be an object")
    generated_keys = {
        "matrix_path",
        "mental_model_path",
        "mental_model_begin",
        "mental_model_end",
    }
    unknown_generated_keys = sorted(set(generated) - generated_keys)
    if unknown_generated_keys:
        raise ComplianceError(
            "generated has unknown keys: " + ", ".join(unknown_generated_keys)
        )
    missing_generated_keys = sorted(generated_keys - set(generated))
    if missing_generated_keys:
        raise ComplianceError(
            "generated is missing keys: " + ", ".join(missing_generated_keys)
        )
    _repo_path(
        root,
        generated.get("matrix_path"),
        field="generated.matrix_path",
        must_exist=False,
    )
    _repo_path(
        root,
        generated.get("mental_model_path"),
        field="generated.mental_model_path",
    )
    for marker_key in ("mental_model_begin", "mental_model_end"):
        marker = generated.get(marker_key)
        if (
            not isinstance(marker, str)
            or not marker.startswith("<!-- ")
            or not marker.endswith(" -->")
        ):
            raise ComplianceError(
                f"generated.{marker_key} must be an HTML comment marker"
            )
    if generated["mental_model_begin"] == generated["mental_model_end"]:
        raise ComplianceError("Generated block markers must be distinct")

    governed_docs = _expect_string_list(
        manifest.get("governed_docs"), field="governed_docs"
    )
    for index, raw in enumerate(governed_docs):
        _repo_path(root, raw, field=f"governed_docs[{index}]")
    validate_workspace_slug_branch_inventory(
        manifest.get("workspace_slug_branch_inventory"), root
    )

    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ComplianceError("claims must be a non-empty list")
    seen_ids: set[str] = set()
    seen_lots: set[int] = set()
    for claim_index, claim in enumerate(claims):
        prefix = f"claims[{claim_index}]"
        if not isinstance(claim, dict):
            raise ComplianceError(f"{prefix} must be an object")
        claim_keys = {
            "id",
            "lot",
            "title",
            "kind",
            "description",
            "mental_model_sections",
            "proofs",
        }
        unknown_claim_keys = sorted(set(claim) - claim_keys)
        if unknown_claim_keys:
            raise ComplianceError(
                f"{prefix} has unknown keys: {', '.join(unknown_claim_keys)}"
            )
        missing_claim_keys = sorted(claim_keys - set(claim))
        if missing_claim_keys:
            raise ComplianceError(
                f"{prefix} is missing keys: {', '.join(missing_claim_keys)}"
            )
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
            raise ComplianceError(f"{prefix}.id must match {CLAIM_ID_RE.pattern}")
        if claim_id in seen_ids:
            raise ComplianceError(f"Duplicate claim id: {claim_id}")
        seen_ids.add(claim_id)
        lot = claim.get("lot")
        if not isinstance(lot, int) or isinstance(lot, bool) or not 0 <= lot <= 5:
            raise ComplianceError(f"{prefix}.lot must be an integer from 0 through 5")
        if not claim_id.startswith(f"LOT{lot}-"):
            raise ComplianceError(f"{prefix}.id must agree with lot {lot}")
        seen_lots.add(lot)
        for field in ("title", "description"):
            if not isinstance(claim.get(field), str) or not claim[field].strip():
                raise ComplianceError(f"{prefix}.{field} must be a non-empty string")
        kind = claim.get("kind")
        if kind not in REQUIRED_FAMILIES:
            raise ComplianceError(
                f"{prefix}.kind must be one of {', '.join(sorted(REQUIRED_FAMILIES))}"
            )
        _expect_string_list(
            claim.get("mental_model_sections"),
            field=f"{prefix}.mental_model_sections",
        )
        proofs = claim.get("proofs")
        if not isinstance(proofs, dict):
            raise ComplianceError(f"{prefix}.proofs must be an object")
        unknown_families = sorted(set(proofs) - set(PROOF_FAMILIES))
        if unknown_families:
            raise ComplianceError(
                f"{prefix}.proofs contains unknown families: {', '.join(unknown_families)}"
            )
        for family in REQUIRED_FAMILIES[kind]:
            if family not in proofs:
                raise ComplianceError(
                    f"{prefix}.proofs.{family} is required for kind {kind}"
                )
        for family, family_proofs in proofs.items():
            if not isinstance(family_proofs, list) or not family_proofs:
                raise ComplianceError(
                    f"{prefix}.proofs.{family} must be a non-empty list"
                )
            for proof_index, proof in enumerate(family_proofs):
                proof_prefix = f"{prefix}.proofs.{family}[{proof_index}]"
                if not isinstance(proof, dict):
                    raise ComplianceError(f"{proof_prefix} must be an object")
                allowed_proof_keys = {"label", "path", "contains"}
                if family == "tests":
                    allowed_proof_keys.add("runner")
                unknown_keys = sorted(set(proof) - allowed_proof_keys)
                if unknown_keys:
                    raise ComplianceError(
                        f"{proof_prefix} has unknown keys: {', '.join(unknown_keys)}"
                    )
                if (
                    not isinstance(proof.get("label"), str)
                    or not proof["label"].strip()
                ):
                    raise ComplianceError(
                        f"{proof_prefix}.label must be a non-empty string"
                    )
                _repo_path(root, proof.get("path"), field=f"{proof_prefix}.path")
                _expect_string_list(
                    proof.get("contains"), field=f"{proof_prefix}.contains"
                )
                if family == "tests" and proof.get("runner") not in RUNNERS:
                    raise ComplianceError(
                        f"{proof_prefix}.runner must be one of {', '.join(sorted(RUNNERS))}"
                    )
    if seen_lots != set(range(6)):
        missing = ", ".join(str(lot) for lot in sorted(set(range(6)) - seen_lots))
        raise ComplianceError(
            f"Manifest must represent Lots 0 through 5; missing: {missing}"
        )
    return manifest


def evaluate_claims(
    manifest: dict[str, Any], root: Path = REPO_ROOT
) -> list[ClaimResult]:
    text_cache: dict[str, str] = {}
    results: list[ClaimResult] = []
    for claim in manifest["claims"]:
        proof_results: list[ProofResult] = []
        for family in PROOF_FAMILIES:
            for proof in claim["proofs"].get(family, []):
                raw_path = proof["path"]
                if raw_path not in text_cache:
                    text_cache[raw_path] = _repo_path(
                        root, raw_path, field=f"claim {claim['id']} proof"
                    ).read_text(encoding="utf-8")
                missing = tuple(
                    literal
                    for literal in proof["contains"]
                    if literal not in text_cache[raw_path]
                )
                proof_results.append(
                    ProofResult(
                        family=family,
                        label=proof["label"],
                        path=raw_path,
                        passed=not missing,
                        missing_literals=missing,
                    )
                )
        required = REQUIRED_FAMILIES[claim["kind"]]
        families_pass = {
            family: all(
                proof.passed for proof in proof_results if proof.family == family
            )
            for family in required
        }
        if all(families_pass.values()):
            computed_state = "static_verified"
        elif any(proof.passed for proof in proof_results):
            computed_state = "partial"
        else:
            computed_state = "planned"
        results.append(
            ClaimResult(
                claim=claim,
                required_families=required,
                required_runners=tuple(
                    sorted(
                        {proof["runner"] for proof in claim["proofs"].get("tests", [])}
                    )
                ),
                proofs=tuple(proof_results),
                computed_state=computed_state,
            )
        )
    return results


def _badge(computed_state: str) -> str:
    return {
        "static_verified": "🟠 Static verified",
        "partial": "🟡 Partial",
        "planned": "🔵 Planned",
    }[computed_state]


def _family_cell(result: ClaimResult, family: str) -> str:
    proofs = [proof for proof in result.proofs if proof.family == family]
    if not proofs:
        return "—"
    passed = sum(proof.passed for proof in proofs)
    icon = "✅" if passed == len(proofs) else "❌"
    requirement = "required" if family in result.required_families else "supporting"
    return f"{icon} {passed}/{len(proofs)} {requirement}"


def render_matrix(manifest: dict[str, Any], results: list[ClaimResult]) -> str:
    manifest_path = "config/agentium/product-compliance.v1.json"
    lines = [
        "# Agentium compliance matrix",
        "",
        "<!-- GENERATED FILE: run `python3 scripts/agentium_compliance.py`; DO NOT EDIT. -->",
        "",
        f"Source contract: [`{manifest_path}`](../{manifest_path}). The repository state below is computed from inspectable files and literals; it is never authored in the manifest.",
        "",
        "`🟠 Static verified` means every repository proof family required by the claim kind passes, including a declared test contract. It does not attest that those tests ran. Local JSON evidence is recorded but cannot promote a claim to a formal delivery state.",
        "",
        "| Lot | Claim | Kind | Implementation | API | Frontend | Tests | Required runners | Computed repository state |",
        "|---:|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        claim = result.claim
        title = claim["title"].replace("|", "\\|")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(claim["lot"]),
                    f"`{claim['id']}` — {title}",
                    f"`{claim['kind']}`",
                    _family_cell(result, "implementation"),
                    _family_cell(result, "api"),
                    _family_cell(result, "frontend"),
                    _family_cell(result, "tests"),
                    ", ".join(f"`{runner}`" for runner in result.required_runners),
                    _badge(result.computed_state),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Evidence detail",
            "",
        ]
    )
    for result in results:
        claim = result.claim
        sections = ", ".join(
            f"§{section}" for section in claim["mental_model_sections"]
        )
        lines.extend(
            [
                f"### `{claim['id']}` — {claim['title']}",
                "",
                f"{claim['description']} Mental model: {sections}.",
                "",
            ]
        )
        for family in PROOF_FAMILIES:
            for proof in [item for item in result.proofs if item.family == family]:
                outcome = "PASS" if proof.passed else "FAIL"
                detail = ""
                if proof.missing_literals:
                    missing = ", ".join(
                        f"`{value}`" for value in proof.missing_literals
                    )
                    detail = f"; missing literal(s): {missing}"
                lines.append(
                    f"- **{family} / {outcome}** — [{proof.label}](../{proof.path}){detail}"
                )
        lines.append("")

    inventory = manifest["workspace_slug_branch_inventory"]
    occurrence_total = sum(entry["occurrences"] for entry in inventory["entries"])
    scan_roots = ", ".join(f"`{path}`" for path in inventory["scan_roots"])
    excluded_paths = (
        ", ".join(f"`{path}`" for path in inventory["exclude_paths"]) or "none"
    )
    excluded_suffixes = (
        ", ".join(f"`*{suffix}`" for suffix in inventory["exclude_suffixes"]) or "none"
    )
    lines.extend(
        [
            "## Residual workspace-slug branch debt",
            "",
            f"Inventory schema v{inventory['schema_version']} declares **{occurrence_total} occurrence(s)** across **{len(inventory['entries'])} expression(s)**. Any new, removed, duplicated or edited branch fails `--check` until this versioned debt list is reviewed explicitly.",
            "",
            f"Runtime scan roots: {scan_roots}. Excluded paths: {excluded_paths}. Excluded suffixes: {excluded_suffixes}.",
            "",
            "Alembic migrations and repository utilities under `backend/scripts` are outside these runtime scan roots; migration 058's one-shot legacy inference is covered by its own implementation and test proofs. Runtime seed/bootstrap code under `backend/app` remains scanned.",
            "",
            "| Path | Expression | Occurrences | Category | Reason |",
            "|---|---|---:|---|---|",
        ]
    )
    for entry in inventory["entries"]:
        expression = entry["expression"].replace("|", "\\|").replace("`", "\\`")
        reason = entry["reason"].replace("|", "\\|")
        lines.append(
            f"| [`{entry['path']}`](../{entry['path']}) | `{expression}` | "
            f"{entry['occurrences']} | `{entry['category']}` | {reason} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Runner and deployment attestations",
            "",
            "Repository proofs, runner results, and deployment evidence are deliberately independent. External JSON is treated as untrusted evidence until an authenticated CI collector derives it:",
            "",
            "- `python3 scripts/agentium_compliance.py --check` verifies the committed manifest and generated documentation.",
            "- `--runner-attestation <json> --sha <40-hex-sha>` records claimed runner evidence for an exact commit; it never sets `runner_verified` or `shipped`.",
            "- `--deployment-attestation <json> --sha <40-hex-sha>` records a claimed environment; it never sets `deployed`.",
            "- The requested SHA must equal Git `HEAD`, `CI_COMMIT_SHA` when present, and a completely clean checkout; evidence for another or dirty ref is rejected.",
            "- `--report-json <path|->` emits the combined machine-readable view. Neither external evidence type mutates this matrix.",
            "",
            "Formal promotion is intentionally disabled until a trusted CI collector derives proof coverage from immutable job identities and artifacts. A decorative mechanism therefore cannot self-declare `Shipped` or `Deployed` through a hand-written JSON file, branch name, manifest field, or documentation badge.",
            "",
        ]
    )
    return "\n".join(lines)


def render_mental_block(manifest: dict[str, Any], results: list[ClaimResult]) -> str:
    begin = manifest["generated"]["mental_model_begin"]
    end = manifest["generated"]["mental_model_end"]
    lines = [
        begin,
        "## Computed Agentium compliance state",
        "",
        "_This block is generated from `config/agentium/product-compliance.v1.json`. Run `python3 scripts/agentium_compliance.py`; manual formal delivery badges are rejected outside generated zones._",
        "",
        "| Lot | Contract claim | Repository state |",
        "|---:|---|---|",
    ]
    for result in results:
        claim = result.claim
        lines.append(
            f"| {claim['lot']} | `{claim['id']}` — {claim['title'].replace('|', '\\|')} | {_badge(result.computed_state)} |"
        )
    lines.extend(
        [
            "",
            "These are static repository states. External runner/deployment JSON is recorded as untrusted evidence and cannot promote a formal delivery state; see [`docs/agentium-compliance-matrix.md`](agentium-compliance-matrix.md).",
            end,
        ]
    )
    return "\n".join(lines)


def replace_generated_block(document: str, begin: str, end: str, block: str) -> str:
    begin_count = document.count(begin)
    end_count = document.count(end)
    if begin_count != 1 or end_count != 1:
        raise ComplianceError(
            "Mental-model generated markers must each appear exactly once "
            f"(begin={begin_count}, end={end_count})"
        )
    before, remainder = document.split(begin, 1)
    _old, after = remainder.split(end, 1)
    return before + block + after


def lint_manual_shipped_claims(
    manifest: dict[str, Any], root: Path = REPO_ROOT
) -> list[str]:
    generated = manifest["generated"]
    violations: list[str] = []
    for raw_path in manifest["governed_docs"]:
        text = _repo_path(root, raw_path, field="governed_docs entry").read_text(
            encoding="utf-8"
        )
        if raw_path == generated["mental_model_path"]:
            begin = generated["mental_model_begin"]
            end = generated["mental_model_end"]
            if text.count(begin) == 1 and text.count(end) == 1:
                before, remainder = text.split(begin, 1)
                _generated, after = remainder.split(end, 1)
                text = before + ("\n" * _generated.count("\n")) + after
        for match in FORMAL_SHIPPED_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(
                f"{raw_path}:{line}: manual `{match.group(0)}` declaration"
            )
    return violations


def _current_git_sha(root: Path = REPO_ROOT) -> str | None:
    """Return the checked-out commit; CI metadata is never an authority for it."""

    try:
        value = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .lower()
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return value if FULL_SHA_RE.fullmatch(value) else None


def validate_requested_sha(value: str | None, root: Path = REPO_ROOT) -> str | None:
    if value is None:
        return None
    sha = value.lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise ComplianceError(
            "--sha must be exactly 40 lowercase hexadecimal characters"
        )
    current_sha = _current_git_sha(root)
    if current_sha is None or sha != current_sha:
        raise ComplianceError(
            "Requested SHA must match the current checkout HEAD "
            f"({current_sha or 'unavailable'})"
        )
    ci_sha = os.environ.get("CI_COMMIT_SHA", "").strip()
    if ci_sha:
        if not FULL_SHA_RE.fullmatch(ci_sha):
            raise ComplianceError(
                "CI_COMMIT_SHA must be exactly 40 lowercase hexadecimal characters"
            )
        if ci_sha != current_sha:
            raise ComplianceError(
                f"CI_COMMIT_SHA must match the current checkout HEAD ({current_sha})"
            )
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ComplianceError("Unable to verify the checkout worktree") from exc
    if dirty:
        raise ComplianceError(
            "A SHA-bound report requires a completely clean checkout; "
            "uncommitted or untracked proof content is forbidden"
        )
    return sha


def validate_sha_bound_repository_content(
    manifest: dict[str, Any],
    manifest_path: Path,
    root: Path = REPO_ROOT,
) -> None:
    """Require every input used by a SHA-bound report to exist in that commit."""

    resolved_root = root.resolve()
    try:
        relative_manifest = (
            manifest_path.resolve().relative_to(resolved_root).as_posix()
        )
    except ValueError as exc:
        raise ComplianceError(
            "A SHA-bound manifest must live inside the checkout"
        ) from exc

    paths = {
        relative_manifest,
        *manifest["governed_docs"],
        manifest["generated"]["matrix_path"],
        manifest["generated"]["mental_model_path"],
    }
    for claim in manifest["claims"]:
        for family in PROOF_FAMILIES:
            paths.update(proof["path"] for proof in claim["proofs"].get(family, []))

    inventory = manifest["workspace_slug_branch_inventory"]
    excluded_prefixes = tuple(value.rstrip("/") for value in inventory["exclude_paths"])
    excluded_suffixes = tuple(inventory["exclude_suffixes"])
    for raw_root in inventory["scan_roots"]:
        scan_root = (resolved_root / raw_root).resolve()
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts"}:
                continue
            relative_path = path.relative_to(resolved_root).as_posix()
            if relative_path.endswith(excluded_suffixes) or any(
                relative_path == prefix or relative_path.startswith(prefix + "/")
                for prefix in excluded_prefixes
            ):
                continue
            paths.add(relative_path)

    ordered_paths = sorted(paths)
    try:
        tracked = set(
            subprocess.run(
                ["git", "ls-files", "--", *ordered_paths],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ComplianceError("Unable to verify SHA-bound proof paths") from exc
    missing = [path for path in ordered_paths if path not in tracked]
    if missing:
        preview = ", ".join(missing[:5])
        suffix = " …" if len(missing) > 5 else ""
        raise ComplianceError(
            "SHA-bound report inputs must be tracked at HEAD: " + preview + suffix
        )


def _load_attestations(
    paths: list[Path],
    *,
    expected_kind: str,
    expected_sha: str | None,
    claim_ids: set[str],
) -> list[dict[str, Any]]:
    if paths and expected_sha is None:
        raise ComplianceError("--sha is required when attestations are supplied")
    attestations: list[dict[str, Any]] = []
    expected_result = "passed" if expected_kind == "runner" else "deployed"
    for path in paths:
        evidence = _load_json(path)
        if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
            raise ComplianceError(f"{path}: attestation schema_version must be 1")
        if evidence.get("kind") != expected_kind:
            raise ComplianceError(f"{path}: kind must be {expected_kind!r}")
        commit_sha = evidence.get("commit_sha")
        if not isinstance(commit_sha, str) or not FULL_SHA_RE.fullmatch(commit_sha):
            raise ComplianceError(
                f"{path}: commit_sha must be 40 lowercase hex characters"
            )
        if commit_sha != expected_sha:
            raise ComplianceError(
                f"{path}: commit_sha {commit_sha} does not match requested SHA {expected_sha}"
            )
        if expected_kind == "runner":
            if (
                not isinstance(evidence.get("runner"), str)
                or not evidence["runner"].strip()
            ):
                raise ComplianceError(f"{path}: runner must be a non-empty string")
            if evidence["runner"] not in RUNNERS:
                raise ComplianceError(
                    f"{path}: runner must be one of {', '.join(sorted(RUNNERS))}"
                )
        else:
            if (
                not isinstance(evidence.get("environment"), str)
                or not evidence["environment"].strip()
            ):
                raise ComplianceError(f"{path}: environment must be a non-empty string")
        claims = evidence.get("claims")
        if not isinstance(claims, dict) or not claims:
            raise ComplianceError(f"{path}: claims must be a non-empty object")
        unknown = sorted(set(claims) - claim_ids)
        if unknown:
            raise ComplianceError(f"{path}: unknown claim ids: {', '.join(unknown)}")
        invalid = sorted(
            key for key, value in claims.items() if value != expected_result
        )
        if invalid:
            raise ComplianceError(
                f"{path}: claim values must be {expected_result!r}: {', '.join(invalid)}"
            )
        attestations.append(evidence)
    return attestations


def build_report(
    results: list[ClaimResult],
    *,
    commit_sha: str | None,
    runner_attestations: list[dict[str, Any]],
    deployment_attestations: list[dict[str, Any]],
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    for result in results:
        claim_id = result.claim["id"]
        runner_names = sorted(
            evidence["runner"]
            for evidence in runner_attestations
            if evidence["claims"].get(claim_id) == "passed"
        )
        environments = sorted(
            evidence["environment"]
            for evidence in deployment_attestations
            if evidence["claims"].get(claim_id) == "deployed"
        )
        runner_evidence_complete = result.static_verified and set(
            result.required_runners
        ).issubset(runner_names)
        claims.append(
            {
                "id": claim_id,
                "computed_state": result.computed_state,
                "static_proofs": {
                    family: {
                        "passed": sum(
                            proof.passed
                            for proof in result.proofs
                            if proof.family == family
                        ),
                        "total": sum(
                            1 for proof in result.proofs if proof.family == family
                        ),
                        "required": family in result.required_families,
                    }
                    for family in PROOF_FAMILIES
                },
                "required_runners": list(result.required_runners),
                "runner_evidence_complete": runner_evidence_complete,
                "runner_verified": False,
                "runner_attestations": runner_names,
                "deployment_evidence_environments": environments,
                "attestation_trust": "untrusted_external",
                "shipped": False,
                "deployed": False,
                "deployment_environments": [],
            }
        )
    return {
        "schema_version": 1,
        "commit_sha": commit_sha,
        "formal_promotion": "disabled_without_authenticated_ci_collector",
        "claims": claims,
    }


def _write_if_changed(path: Path, content: str) -> bool:
    normalized = content.rstrip() + "\n"
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == normalized:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8")
    return True


def _check_exact(path: Path, expected: str) -> str | None:
    normalized = expected.rstrip() + "\n"
    if not path.is_file():
        return f"generated file missing: {path.relative_to(REPO_ROOT)}"
    if path.read_text(encoding="utf-8") != normalized:
        return f"generated file drift: {path.relative_to(REPO_ROOT)}"
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--sha", help="exact 40-character lowercase commit SHA for attestations"
    )
    parser.add_argument("--runner-attestation", type=Path, action="append", default=[])
    parser.add_argument(
        "--deployment-attestation", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--report-json",
        help="write combined evidence JSON to a path, or '-' for stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log_stream = sys.stderr if args.report_json == "-" else sys.stdout
    try:
        manifest = validate_manifest(_load_json(args.manifest), REPO_ROOT)
        results = evaluate_claims(manifest, REPO_ROOT)
        generated = manifest["generated"]
        matrix_path = _repo_path(
            REPO_ROOT,
            generated["matrix_path"],
            field="generated.matrix_path",
            must_exist=False,
        )
        mental_path = _repo_path(
            REPO_ROOT,
            generated["mental_model_path"],
            field="generated.mental_model_path",
        )
        matrix = render_matrix(manifest, results)
        mental_document = mental_path.read_text(encoding="utf-8")
        mental_block = render_mental_block(manifest, results)
        expected_mental = replace_generated_block(
            mental_document,
            generated["mental_model_begin"],
            generated["mental_model_end"],
            mental_block,
        )

        violations = lint_manual_shipped_claims(manifest, REPO_ROOT)
        if violations:
            raise ComplianceError(
                "Manual Shipped declarations are forbidden outside generated zones:\n"
                + "\n".join(f"  - {violation}" for violation in violations)
            )

        failures: list[str] = []
        if args.check:
            for failure in (
                _check_exact(matrix_path, matrix),
                _check_exact(mental_path, expected_mental),
            ):
                if failure:
                    failures.append(failure)
        else:
            changed = [
                path.relative_to(REPO_ROOT).as_posix()
                for path, content in (
                    (matrix_path, matrix),
                    (mental_path, expected_mental),
                )
                if _write_if_changed(path, content)
            ]
            if changed:
                print("Updated: " + ", ".join(changed), file=log_stream)
            else:
                print("Compliance documentation already up to date", file=log_stream)

        if failures:
            raise ComplianceError("\n".join(failures))

        sha = validate_requested_sha(args.sha, REPO_ROOT)
        if sha is not None:
            validate_sha_bound_repository_content(manifest, args.manifest, REPO_ROOT)
        claim_ids = {result.claim["id"] for result in results}
        runner_attestations = _load_attestations(
            args.runner_attestation,
            expected_kind="runner",
            expected_sha=sha,
            claim_ids=claim_ids,
        )
        deployment_attestations = _load_attestations(
            args.deployment_attestation,
            expected_kind="deployment",
            expected_sha=sha,
            claim_ids=claim_ids,
        )
        if args.report_json:
            report = build_report(
                results,
                commit_sha=sha,
                runner_attestations=runner_attestations,
                deployment_attestations=deployment_attestations,
            )
            payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
            if args.report_json == "-":
                sys.stdout.write(payload)
            else:
                output_path = Path(args.report_json)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(payload, encoding="utf-8")

        if args.check:
            verified = sum(result.static_verified for result in results)
            print(
                "Agentium compliance check passed "
                f"({verified}/{len(results)} claims static verified; runner attestations separate)",
                file=log_stream,
            )
        return 0
    except ComplianceError as exc:
        print(f"Agentium compliance check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
