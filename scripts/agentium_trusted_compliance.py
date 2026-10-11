#!/usr/bin/env python3
"""Derive formal Agentium evidence states inside an authenticated GitLab job.

Ordinary JSON remains untrusted input.  Formal promotion is only possible when
this collector verifies a GitLab-issued OIDC ID token, a protected ref, the
exact commit/job/pipeline identity, and SHA-bound runner/deployment/behaviour
artifacts produced by that same job.  The output is an immutable CI artifact;
it never edits the repository compliance matrix or mental model.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DER_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
FORMAL_STATES = (
    "declared",
    "static_verified",
    "runner_verified",
    "deployed_verified",
    "behavior_verified",
    "user_validated",
)


class TrustedComplianceError(ValueError):
    """Raised when CI identity or an evidence artifact is not trustworthy."""


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise TrustedComplianceError("invalid base64url data in OIDC token") from exc


def _json_object(raw: bytes, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustedComplianceError(f"{field} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TrustedComplianceError(f"{field} must be a JSON object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _json_object(path.read_bytes(), field=str(path))
    except FileNotFoundError as exc:
        raise TrustedComplianceError(f"evidence file does not exist: {path}") from exc


def _fetch_json(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise TrustedComplianceError("OIDC metadata and keys must use absolute HTTPS URLs")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "agentium-trusted-collector/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            payload = response.read(262_145)
            if response.status != 200 or len(payload) > 262_144:
                raise TrustedComplianceError("OIDC endpoint returned an invalid response")
    except OSError as exc:
        raise TrustedComplianceError("cannot retrieve GitLab OIDC metadata") from exc
    return _json_object(payload, field="OIDC endpoint")


def _same_origin(left: str, right: str) -> bool:
    a = urllib.parse.urlparse(left)
    b = urllib.parse.urlparse(right)
    return (
        a.scheme.lower(),
        a.hostname,
        a.port or (443 if a.scheme.lower() == "https" else None),
    ) == (
        b.scheme.lower(),
        b.hostname,
        b.port or (443 if b.scheme.lower() == "https" else None),
    )


def _verify_rs256(signing_input: bytes, signature: bytes, jwk: Mapping[str, Any]) -> None:
    if jwk.get("kty") != "RSA" or jwk.get("alg") not in {None, "RS256"}:
        raise TrustedComplianceError("GitLab OIDC signing key must be RSA/RS256")
    try:
        modulus = int.from_bytes(_b64url_decode(str(jwk["n"])), "big")
        exponent = int.from_bytes(_b64url_decode(str(jwk["e"])), "big")
    except (KeyError, ValueError) as exc:
        raise TrustedComplianceError("GitLab OIDC RSA key is incomplete") from exc
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        raise TrustedComplianceError("OIDC signature has an invalid length")
    encoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(width, "big")
    digest_info = DER_SHA256_PREFIX + hashlib.sha256(signing_input).digest()
    padding_length = width - len(digest_info) - 3
    expected = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    if padding_length < 8 or not hmac.compare_digest(encoded, expected):
        raise TrustedComplianceError("GitLab OIDC signature verification failed")


def verify_gitlab_oidc(
    token: str,
    *,
    server_url: str,
    audience: str,
    now: int | None = None,
    fetch_json=_fetch_json,
) -> dict[str, Any]:
    """Verify GitLab's signature and return bound job claims."""

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise TrustedComplianceError("GitLab OIDC token must be a signed JWT")
    header = _json_object(_b64url_decode(parts[0]), field="OIDC header")
    claims = _json_object(_b64url_decode(parts[1]), field="OIDC claims")
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise TrustedComplianceError("GitLab OIDC token must use a keyed RS256 signature")

    expected_issuer = server_url.rstrip("/")
    if claims.get("iss") != expected_issuer:
        raise TrustedComplianceError("OIDC issuer does not match CI_SERVER_URL")
    audiences = claims.get("aud")
    audience_set = {audiences} if isinstance(audiences, str) else set(audiences or [])
    if audience not in audience_set:
        raise TrustedComplianceError("OIDC audience does not authorize this collector")

    current = int(time.time()) if now is None else now
    try:
        expires = int(claims["exp"])
        not_before = int(claims.get("nbf", claims.get("iat", 0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise TrustedComplianceError("OIDC token time claims are invalid") from exc
    if current >= expires or current + 60 < not_before:
        raise TrustedComplianceError("OIDC token is expired or not active")

    discovery_url = expected_issuer + "/.well-known/openid-configuration"
    discovery = fetch_json(discovery_url)
    if discovery.get("issuer") != expected_issuer:
        raise TrustedComplianceError("OIDC discovery issuer mismatch")
    jwks_uri = discovery.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not _same_origin(expected_issuer, jwks_uri):
        raise TrustedComplianceError("OIDC JWKS URI must stay on the GitLab origin")
    jwks = fetch_json(jwks_uri)
    keys = jwks.get("keys")
    key = next(
        (
            item
            for item in keys or []
            if isinstance(item, Mapping) and item.get("kid") == header["kid"]
        ),
        None,
    )
    if key is None:
        raise TrustedComplianceError("OIDC signing key was not found")
    _verify_rs256(
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        _b64url_decode(parts[2]),
        key,
    )
    return claims


def bound_ci_identity(claims: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, str]:
    """Bind signed token claims to the current protected GitLab process."""

    required_env = (
        "CI_SERVER_URL",
        "CI_PROJECT_ID",
        "CI_PIPELINE_ID",
        "CI_JOB_ID",
        "CI_COMMIT_SHA",
        "CI_COMMIT_REF_NAME",
    )
    missing = [key for key in required_env if not env.get(key, "").strip()]
    if missing:
        raise TrustedComplianceError("missing GitLab job metadata: " + ", ".join(missing))
    sha = env["CI_COMMIT_SHA"].lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise TrustedComplianceError("CI_COMMIT_SHA must be a full lowercase SHA")
    if env.get("CI_COMMIT_REF_PROTECTED", "").lower() != "true":
        raise TrustedComplianceError("formal evidence requires a protected GitLab ref")

    expected = {
        "project_id": env["CI_PROJECT_ID"],
        "pipeline_id": env["CI_PIPELINE_ID"],
        "job_id": env["CI_JOB_ID"],
        "sha": sha,
        "ref": env["CI_COMMIT_REF_NAME"],
    }
    for key, value in expected.items():
        if str(claims.get(key, "")) != value:
            raise TrustedComplianceError(f"signed OIDC {key} does not match the running job")
    if str(claims.get("ref_protected", "")).lower() != "true":
        raise TrustedComplianceError("signed OIDC token does not identify a protected ref")
    return {
        "issuer": str(claims["iss"]),
        "project_id": expected["project_id"],
        "pipeline_id": expected["pipeline_id"],
        "job_id": expected["job_id"],
        "commit_sha": sha,
        "ref": expected["ref"],
        "ref_protected": "true",
    }


def _artifact_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_evidence(
    evidence: Mapping[str, Any],
    *,
    path: Path,
    kind: str,
    sha: str,
    identity: Mapping[str, str],
) -> dict[str, Any]:
    if evidence.get("schema_version") != 1 or evidence.get("kind") != kind:
        raise TrustedComplianceError(f"{path}: expected schema v1 {kind!r} evidence")
    if evidence.get("commit_sha") != sha or evidence.get("outcome") != "passed":
        raise TrustedComplianceError(f"{path}: evidence is not a passed result for {sha}")
    ci = evidence.get("ci")
    if not isinstance(ci, Mapping):
        raise TrustedComplianceError(f"{path}: CI identity is missing")
    for key in ("project_id", "pipeline_id", "job_id", "commit_sha", "ref"):
        if str(ci.get(key, "")) != identity[key]:
            raise TrustedComplianceError(f"{path}: CI identity mismatch for {key}")
    if str(ci.get("ref_protected", "")).lower() != "true":
        raise TrustedComplianceError(f"{path}: evidence was not produced on a protected ref")
    claims = evidence.get("claims")
    if not isinstance(claims, dict) or not claims:
        raise TrustedComplianceError(f"{path}: claims must be a non-empty object")
    expected_result = "deployed" if kind == "deployment" else "passed"
    if any(value != expected_result for value in claims.values()):
        raise TrustedComplianceError(f"{path}: invalid claim result for {kind}")
    checks = evidence.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        raise TrustedComplianceError(f"{path}: check results are missing")
    for name, value in checks.items():
        passed = value.get("passed") if isinstance(value, Mapping) else value
        if passed is not True:
            raise TrustedComplianceError(f"{path}: check {name!r} did not pass")
    return dict(evidence)


def validate_user_validation_evidence(
    evidence: Mapping[str, Any],
    *,
    path: Path,
    sha: str,
    identity: Mapping[str, str],
) -> dict[str, Any]:
    """Validate the minimum five-profile, four-question product gate.

    Human validation cannot be inferred from browser checks.  The structured
    study result must itself be collected by the authenticated protected job,
    and the thresholds are re-evaluated here instead of trusting a free-form
    ``passed`` label.
    """

    validated = validate_evidence(
        evidence,
        path=path,
        kind="user_validation",
        sha=sha,
        identity=identity,
    )
    study = validated.get("study")
    if not isinstance(study, Mapping):
        raise TrustedComplianceError(f"{path}: user validation study is missing")
    profiles = study.get("profiles")
    required_profiles = {
        "builder",
        "operator",
        "decision_owner",
        "governor",
        "transverse",
    }
    if not isinstance(profiles, list) or required_profiles - {
        str(value) for value in profiles
    }:
        raise TrustedComplianceError(
            f"{path}: user validation must cover the five required profiles"
        )
    try:
        participant_count = int(study.get("participant_count", 0))
        confidence_mean = float(study.get("confidence_mean", 0))
        critical_confusions = int(
            study.get("critical_identity_or_lens_confusions", -1)
        )
    except (TypeError, ValueError) as exc:
        raise TrustedComplianceError(
            f"{path}: user validation aggregate values are invalid"
        ) from exc
    successes = study.get("successes_per_question")
    if (
        participant_count < 5
        or confidence_mean < 4.0
        or critical_confusions != 0
        or not isinstance(successes, Mapping)
        or len(successes) != 4
    ):
        raise TrustedComplianceError(f"{path}: user validation thresholds were not met")
    try:
        success_counts = [int(value) for value in successes.values()]
    except (TypeError, ValueError) as exc:
        raise TrustedComplianceError(
            f"{path}: successes_per_question contains an invalid value"
        ) from exc
    if any(value < 4 for value in success_counts):
        raise TrustedComplianceError(
            f"{path}: every validation question requires at least four successes"
        )
    return validated


def derive_formal_report(
    *,
    static_report: Mapping[str, Any],
    sha: str,
    identity: Mapping[str, str],
    runners: Sequence[Mapping[str, Any]],
    deployments: Sequence[Mapping[str, Any]],
    behaviors: Sequence[Mapping[str, Any]],
    artifact_hashes: Mapping[str, str],
    user_validations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Apply the one-way state machine to authenticated evidence only."""

    if static_report.get("commit_sha") != sha:
        raise TrustedComplianceError("static compliance report is for another SHA")
    rows = static_report.get("claims")
    if not isinstance(rows, list):
        raise TrustedComplianceError("static compliance report has no claims")

    output: list[dict[str, Any]] = []
    for row in rows:
        claim_id = row.get("id")
        if not isinstance(claim_id, str):
            raise TrustedComplianceError("static compliance claim id is invalid")
        static = row.get("computed_state") == "static_verified"
        required_runners = set(row.get("required_runners") or [])
        seen_runners = {
            str(item.get("runner"))
            for item in runners
            if item.get("claims", {}).get(claim_id) == "passed"
        }
        runner_verified = static and required_runners.issubset(seen_runners)
        deployed = runner_verified and any(
            item.get("claims", {}).get(claim_id) == "deployed" for item in deployments
        )
        behavior = deployed and any(
            item.get("claims", {}).get(claim_id) == "passed" for item in behaviors
        )
        user_validated = behavior and any(
            item.get("claims", {}).get(claim_id) == "passed"
            for item in user_validations
        )
        state = (
            "user_validated"
            if user_validated
            else "behavior_verified"
            if behavior
            else "deployed_verified"
            if deployed
            else "runner_verified"
            if runner_verified
            else "static_verified"
            if static
            else "declared"
        )
        output.append(
            {
                "id": claim_id,
                "state": state,
                "required_runners": sorted(required_runners),
                "verified_runners": sorted(seen_runners),
                "deployment_environments": sorted(
                    {
                        str(item.get("environment"))
                        for item in deployments
                        if item.get("claims", {}).get(claim_id) == "deployed"
                    }
                ),
                "behavior_jobs": sorted(
                    {
                        str(item.get("ci", {}).get("job_id"))
                        for item in behaviors
                        if item.get("claims", {}).get(claim_id) == "passed"
                    }
                ),
                "user_validation_jobs": sorted(
                    {
                        str(item.get("ci", {}).get("job_id"))
                        for item in user_validations
                        if item.get("claims", {}).get(claim_id) == "passed"
                    }
                ),
            }
        )
    return {
        "schema_version": 1,
        "commit_sha": sha,
        "formal_promotion": "authenticated_gitlab_oidc",
        "state_model": list(FORMAL_STATES),
        "trust": {
            **dict(identity),
            "artifact_sha256": dict(sorted(artifact_hashes.items())),
        },
        "claims": output,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-report", type=Path, required=True)
    parser.add_argument("--runner-attestation", type=Path, action="append", default=[])
    parser.add_argument("--deployment-attestation", type=Path, action="append", default=[])
    parser.add_argument("--behavior-attestation", type=Path, action="append", default=[])
    parser.add_argument("--user-attestation", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oidc-token-env", default="AGENTIUM_ATTESTATION_ID_TOKEN")
    parser.add_argument("--audience", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        server_url = os.environ.get("CI_SERVER_URL", "").rstrip("/")
        audience = args.audience or server_url
        token = os.environ.get(args.oidc_token_env, "")
        if not token:
            raise TrustedComplianceError(
                f"signed GitLab ID token is missing from {args.oidc_token_env}"
            )
        signed_claims = verify_gitlab_oidc(
            token,
            server_url=server_url,
            audience=audience,
        )
        identity = bound_ci_identity(signed_claims, os.environ)
        sha = identity["commit_sha"]

        paths = [
            args.static_report,
            *args.runner_attestation,
            *args.deployment_attestation,
            *args.behavior_attestation,
            *args.user_attestation,
        ]
        hashes = {str(path): _artifact_digest(path) for path in paths}
        runners = [
            validate_evidence(
                _load_json(path), path=path, kind="runner", sha=sha, identity=identity
            )
            for path in args.runner_attestation
        ]
        deployments = [
            validate_evidence(
                _load_json(path), path=path, kind="deployment", sha=sha, identity=identity
            )
            for path in args.deployment_attestation
        ]
        behaviors = [
            validate_evidence(
                _load_json(path), path=path, kind="behavior", sha=sha, identity=identity
            )
            for path in args.behavior_attestation
        ]
        user_validations = [
            validate_user_validation_evidence(
                _load_json(path), path=path, sha=sha, identity=identity
            )
            for path in args.user_attestation
        ]
        report = derive_formal_report(
            static_report=_load_json(args.static_report),
            sha=sha,
            identity=identity,
            runners=runners,
            deployments=deployments,
            behaviors=behaviors,
            artifact_hashes=hashes,
            user_validations=user_validations,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        behavior_count = sum(
            item["state"] in {"behavior_verified", "user_validated"}
            for item in report["claims"]
        )
        user_count = sum(
            item["state"] == "user_validated" for item in report["claims"]
        )
        print(
            f"Trusted compliance report written for {sha[:12]} "
            f"({behavior_count} behavior-verified claim(s), "
            f"{user_count} user-validated claim(s))"
        )
        return 0
    except TrustedComplianceError as exc:
        print(f"Trusted compliance collection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
