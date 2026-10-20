"""Pure C0 evidence contract; no storage, endpoint, driver or certified profile.

The caller must authenticate the producer and verify the referenced evidence
files before supplying bundles. A SHA256 detects mutation, not authorship.
Unit-test bundles are not certification evidence and are never registered.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[\w.+:/@-]+$")]


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


OPERATIONS = (
    "read",
    "read_partitioned",
    "read_incremental",
    "write_append",
    "write_overwrite",
    "write_upsert",
    "create_table",
    "export_files",
    "watch",
)
BASE_SUITES = frozenset(
    {
        "contract",
        "connection",
        "introspection",
        "security",
        "revocation",
        "resilience",
        "lineage",
    }
)


class Capabilities(FrozenContract):
    read: StrictBool = False
    read_partitioned: StrictBool = False
    read_incremental: StrictBool = False
    consistency: Literal["snapshot", "per_partition", "none"] = "none"
    write_append: StrictBool = False
    write_overwrite: StrictBool = False
    write_upsert: StrictBool = False
    create_table: StrictBool = False
    write_outcome_check: Literal[
        "marker_table", "job_id", "idempotency_key", "conditional_put", "snapshot_summary", "none"
    ] = "none"
    export_files: StrictBool = False
    watch: StrictBool = False

    @model_validator(mode="after")
    def coherent(self):
        if not self.read and (
            self.read_partitioned
            or self.read_incremental
            or self.watch
            or self.consistency != "none"
        ):
            raise ValueError("CONNECTOR_READ_CAPABILITY_REQUIRED")
        writes = self.write_append or self.write_overwrite or self.write_upsert
        if self.create_table and not writes:
            raise ValueError("CONNECTOR_WRITE_CAPABILITY_REQUIRED")
        if self.write_outcome_check != "none" and not (writes or self.export_files):
            raise ValueError("CONNECTOR_WRITE_CAPABILITY_REQUIRED")
        return self

    @property
    def sha256(self) -> str:
        return _digest(self.model_dump(mode="json"))


def required_suites(capabilities: Capabilities) -> frozenset[str]:
    """Unavailable operations require a refusal test, never a silent skip."""
    suites = set(BASE_SUITES)
    for operation in OPERATIONS:
        suites.add(operation if getattr(capabilities, operation) else f"unsupported:{operation}")
    if capabilities.read:
        suites.add(f"consistency:{capabilities.consistency}")
    if any(
        getattr(capabilities, op)
        for op in ("write_append", "write_overwrite", "write_upsert", "export_files")
    ):
        suites.update({"write_dry_run", "write_read_only_refusal", "write_unknown_outcome"})
        suites.add(f"outcome:{capabilities.write_outcome_check}")
    return frozenset(suites)


class DriverVersion(FrozenContract):
    package: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    version: Annotated[str, Field(pattern=r"^[0-9][A-Za-z0-9.+!-]*$")]


class ComponentIdentity(FrozenContract):
    profile_key: Identifier
    profile_version: Identifier
    profile_sha256: Digest
    capabilities: Capabilities
    drivers: tuple[DriverVersion, ...] = Field(min_length=1, max_length=100)
    runner_image_sha256: Digest
    kit_version: Identifier
    kit_sha256: Digest
    server_version: Identifier

    @model_validator(mode="after")
    def unique_drivers(self):
        if len({driver.package for driver in self.drivers}) != len(self.drivers):
            raise ValueError("CONNECTOR_DUPLICATE_DRIVER")
        return self

    @property
    def sha256(self) -> str:
        values = self.model_dump(mode="json")
        values["drivers"] = sorted(values["drivers"], key=lambda driver: driver["package"])
        return _digest(values)


class SuiteResult(FrozenContract):
    suite: Identifier
    status: Literal["passed", "failed", "skipped"]
    evidence_sha256: Digest


class EvidencePayload(FrozenContract):
    schema_version: Literal[1] = 1
    kind: Literal["suite", "canary"]
    identity: ComponentIdentity
    source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    environment: Literal["container", "test_account", "deployed"]
    environment_id: Identifier
    # Demo fallback or an emulator cannot be promoted to a deployed canary.
    source: Literal["real", "emulator", "demo"]
    completed_at: datetime
    results: tuple[SuiteResult, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def coherent(self):
        if self.completed_at.utcoffset() is None:
            raise ValueError("CONNECTOR_EVIDENCE_TIMEZONE_REQUIRED")
        if len({result.suite for result in self.results}) != len(self.results):
            raise ValueError("CONNECTOR_DUPLICATE_SUITE")
        expected = (
            required_suites(self.identity.capabilities)
            if self.kind == "suite"
            else {"canary", "revocation"}
        )
        if {result.suite for result in self.results} != expected:
            raise ValueError("CONNECTOR_EVIDENCE_SUITES_MISMATCH")
        return self


def evidence_digest(payload: EvidencePayload) -> str:
    return _digest(payload.model_dump(mode="json"))


class EvidenceBundle(FrozenContract):
    payload: EvidencePayload
    sha256: Digest

    @model_validator(mode="after")
    def intact(self):
        if self.sha256 != evidence_digest(self.payload):
            raise ValueError("CONNECTOR_EVIDENCE_DIGEST_MISMATCH")
        return self


class CertificationDecision(FrozenContract):
    level: Literal["unverified", "needs_requalification", "verified", "certified", "third_party"]
    reason: Identifier
    evidence_sha256: tuple[Digest, ...] = ()


def certification_level(
    identity: ComponentIdentity,
    bundles: tuple[EvidenceBundle, ...],
    *,
    now: datetime,
    deployed_environment_id: str,
    origin: Literal["native", "third_party"] = "native",
    max_age_days: int = 30,
) -> CertificationDecision:
    """Evaluate *trusted* bundles against the current components and deployment.

    A later failure wins over an older success. Conflicting same-time reports
    fail closed. API connection badges evaluate trusted proof bundles against
    the exact identity observed by the isolated runner.
    """
    if now.utcoffset() is None or type(max_age_days) is not int or max_age_days <= 0:
        raise ValueError("CONNECTOR_CERTIFICATION_POLICY_INVALID")
    if origin not in {"native", "third_party"}:
        raise ValueError("CONNECTOR_CERTIFICATION_ORIGIN_INVALID")
    if origin == "third_party":
        return CertificationDecision(level="third_party", reason="THIRD_PARTY")
    relevant = [b for b in bundles if b.payload.identity.profile_key == identity.profile_key]
    matching = [b for b in relevant if b.payload.identity.sha256 == identity.sha256]
    suites = [b for b in matching if b.payload.kind == "suite"]
    if not suites:
        changed = any(b.payload.identity.sha256 != identity.sha256 for b in relevant)
        return CertificationDecision(
            level="needs_requalification" if changed else "unverified",
            reason="COMPONENTS_CHANGED" if changed else "NO_CURRENT_SUITE",
        )

    def latest_success(candidates):
        if not candidates:
            return None
        newest = max(b.payload.completed_at for b in candidates)
        latest = [b for b in candidates if b.payload.completed_at == newest]
        if len({b.sha256 for b in latest}) != 1:
            return None
        result = latest[0]
        payload = result.payload
        if payload.completed_at > now or payload.source == "demo":
            return None
        if any(row.status != "passed" for row in payload.results):
            return None
        # Showcase's synthetic fallback and containers do not qualify SAP HANA.
        if identity.profile_key == "sap_hana" and (
            payload.environment == "container" or payload.source != "real"
        ):
            return None
        return result

    suite = latest_success(suites)
    if suite is None:
        return CertificationDecision(level="unverified", reason="SUITE_NOT_PASSED")
    canary = latest_success(
        [
            b
            for b in matching
            if b.payload.kind == "canary" and b.payload.environment_id == deployed_environment_id
        ]
    )
    if canary is not None and (
        canary.payload.environment == "deployed"
        and canary.payload.source == "real"
        and now - canary.payload.completed_at < timedelta(days=max_age_days)
    ):
        return CertificationDecision(
            level="certified",
            reason="CURRENT_CANARY_AND_REVOCATION",
            evidence_sha256=(suite.sha256, canary.sha256),
        )
    return CertificationDecision(
        level="verified",
        reason="CURRENT_SUITE_ONLY",
        evidence_sha256=(suite.sha256,),
    )
