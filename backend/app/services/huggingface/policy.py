"""Effective license policy and revision-bound evidence, independent of artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.services.huggingface.connection import get_platform_config
from app.services.huggingface.errors import HFError

ALLOWED = {"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "cc-by-4.0", "cc0-1.0"}
REVIEW = {"gemma", "openrail", "openrail++", "creativeml-openrail-m", "cc-by-sa-4.0", "other"}
CLASSES = {"allowed": 0, "acceptance_required": 1, "blocked": 2}
WORKSPACE_POLICY_KEY = "huggingface_policy"
POLICY_VERSION = "hf-license-v1"


def classify(license_tag: str | None) -> str:
    tag = str(license_tag or "unknown").strip().lower()
    if tag in ALLOWED:
        return "allowed"
    if tag in REVIEW or tag == "llama3" or tag.startswith("llama3."):
        return "acceptance_required"
    # Unknown custom identifiers are never assumed permissive.
    return "blocked"


def license_digest(metadata: dict, license_text: str = "") -> str:
    evidence = {"license": str(metadata.get("license") or "unknown").lower(), "text": license_text}
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _overrides(policy) -> dict:
    return dict(policy.get("overrides") or {}) if isinstance(policy, dict) else {}


def effective_policy(db, workspace) -> tuple[dict, str]:
    platform = get_platform_config(db)
    platform_overrides = _overrides(platform.policy if platform else {})
    workspace_overrides = _overrides(
        (getattr(workspace, "settings", None) or {}).get(WORKSPACE_POLICY_KEY)
    )
    effective = {}
    for tag in set(platform_overrides) | set(workspace_overrides):
        levels = [
            classify(tag),
            platform_overrides.get(tag, "allowed"),
            workspace_overrides.get(tag, "allowed"),
        ]
        effective[tag] = max(levels, key=lambda value: CLASSES.get(value, 2))
    version = hashlib.sha256(
        json.dumps({"version": POLICY_VERSION, "overrides": effective}, sort_keys=True).encode()
    ).hexdigest()
    return effective, version


def _scope(workspace, metadata: dict, digest: str) -> dict:
    from app.services.huggingface.client import SHA, validate_repo
    from app.services.huggingface.connection import normalize_endpoint

    validate_repo(metadata.get("kind"), metadata.get("repo_id"))
    if not SHA.fullmatch(str(metadata.get("revision", ""))):
        raise HFError("HF_REVISION_INVALID", "License evidence requires an immutable commit.")
    if workspace is None or not getattr(workspace, "id", None):
        raise HFError(
            "HF_WORKSPACE_REQUIRED", "A workspace is required for license authorization.", 403
        )
    return {
        "workspace_id": workspace.id,
        "hub_endpoint": normalize_endpoint(metadata.get("hub_endpoint")),
        "kind": metadata["kind"],
        "repo_id": metadata["repo_id"],
        "revision": metadata["revision"],
        "license_digest": digest,
    }


def assess(db, workspace, metadata: dict, license_text: str = "") -> dict:
    from app.models.huggingface import HFLicenseAcceptance, HFLicenseException

    tag = str(metadata.get("license") or "unknown").strip().lower()
    overrides, version = effective_policy(db, workspace)
    classification = max((classify(tag), overrides.get(tag, "allowed")), key=CLASSES.__getitem__)
    digest = license_digest(metadata, license_text)
    scope = _scope(workspace, metadata, digest)
    accepted = (
        db.query(HFLicenseAcceptance).filter_by(**scope, policy_version=version).first()
        if db
        else None
    )
    exception = None
    if classification == "blocked" and db:
        now = datetime.now(timezone.utc)
        for row in db.query(HFLicenseException).filter_by(**scope, policy_version=version).all():
            expiry = row.expires_at
            if (
                expiry is None
                or (expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry) > now
            ):
                exception = row
                break
        if exception:
            # A platform exception cannot weaken an explicit workspace denial.
            workspace_rule = _overrides((workspace.settings or {}).get(WORKSPACE_POLICY_KEY)).get(
                tag
            )
            if workspace_rule != "blocked":
                classification = "acceptance_required"
            else:
                exception = None
    return {
        "license": tag,
        "license_class": classification,
        "license_digest": digest,
        "policy_version": version,
        "accepted": bool(accepted),
        "accepted_by": accepted.accepted_by if accepted else None,
        "accepted_at": accepted.accepted_at.isoformat() if accepted else None,
        "exception_id": exception.id if exception else None,
    }


def _audit(db, workspace_id, action, actor, details):
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        workspace_id=workspace_id,
        event_type="hf.license." + action,
        actor=actor,
        details=details,
        db=db,
    )


def require_acceptance(
    db, workspace, metadata: dict, license_text: str = "", *, actor: str = "system"
) -> dict:
    decision = assess(db, workspace, metadata, license_text)
    if decision["license_class"] == "blocked":
        _audit(
            db,
            workspace.id,
            "refused",
            actor,
            {**decision, "repo_id": metadata["repo_id"], "revision": metadata["revision"]},
        )
        raise HFError(
            "HF_LICENSE_BLOCKED",
            "This license is blocked by the effective workspace policy.",
            403,
            decision,
        )
    if decision["license_class"] == "acceptance_required" and not decision["accepted"]:
        _audit(
            db,
            workspace.id,
            "refused",
            actor,
            {**decision, "repo_id": metadata["repo_id"], "revision": metadata["revision"]},
        )
        raise HFError(
            "HF_LICENSE_ACCEPTANCE_REQUIRED",
            "A workspace administrator must accept this revision's license first.",
            403,
            decision,
        )
    return decision


def accept_license(db, workspace, metadata: dict, license_text: str, *, actor: str) -> dict:
    from app.models.huggingface import HFLicenseAcceptance

    if not license_text.strip():
        raise HFError(
            "HF_LICENSE_TEXT_REQUIRED",
            "The complete license text must be available before acceptance.",
            422,
        )
    decision = assess(db, workspace, metadata, license_text)
    if decision["license_class"] == "blocked":
        raise HFError(
            "HF_LICENSE_BLOCKED",
            "A platform exception is required before accepting this license.",
            403,
            decision,
        )
    if not decision["accepted"]:
        scope = _scope(workspace, metadata, decision["license_digest"])
        db.add(
            HFLicenseAcceptance(
                **scope,
                policy_version=decision["policy_version"],
                accepted_by=actor,
                license_text=license_text,
            )
        )
        _audit(
            db,
            workspace.id,
            "accepted",
            actor,
            {**scope, "policy_version": decision["policy_version"]},
        )
        db.commit()
    return assess(db, workspace, metadata, license_text)


def grant_exception(
    db, workspace, metadata: dict, license_text: str, *, actor: str, reason: str, expires_at=None
) -> dict:
    from app.models.huggingface import HFLicenseException

    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise HFError(
            "HF_EXCEPTION_REASON_REQUIRED",
            "A specific reason of at most 2000 characters is required.",
        )
    if expires_at:
        expiry = (
            expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        )
        if expiry <= datetime.now(timezone.utc):
            raise HFError(
                "HF_EXCEPTION_EXPIRED", "The license exception expiry must be in the future."
            )
    decision = assess(db, workspace, metadata, license_text)
    scope = _scope(workspace, metadata, decision["license_digest"])
    entry = HFLicenseException(
        **scope,
        policy_version=decision["policy_version"],
        reason=reason.strip(),
        license_text=license_text,
        created_by=actor,
        expires_at=expires_at,
    )
    db.add(entry)
    _audit(
        db,
        workspace.id,
        "exception",
        actor,
        {**scope, "reason": reason.strip(), "policy_version": decision["policy_version"]},
    )
    db.commit()
    return assess(db, workspace, metadata, license_text)


def _validate_overrides(overrides: dict, base: dict) -> dict:
    if not isinstance(overrides, dict) or len(overrides) > 200:
        raise HFError(
            "HF_POLICY_INVALID", "License overrides must be a mapping of at most 200 licenses."
        )
    result = {}
    for tag, classification in overrides.items():
        if (
            not isinstance(tag, str)
            or len(tag) > 100
            or not isinstance(classification, str)
            or classification not in CLASSES
        ):
            raise HFError("HF_POLICY_INVALID", "Unknown license class or invalid license tag.")
        tag = tag.strip().lower()
        minimum = max((classify(tag), base.get(tag, "allowed")), key=CLASSES.__getitem__)
        if CLASSES[classification] < CLASSES[minimum]:
            raise HFError(
                "HF_POLICY_WEAKENING",
                "License policy overrides may only tighten the existing policy.",
                403,
            )
        result[tag] = classification
    return result


def set_workspace_policy(db, workspace, overrides: dict, *, actor: str) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    platform = get_platform_config(db)
    checked = _validate_overrides(overrides, _overrides(platform.policy if platform else {}))
    workspace.settings = {
        **(workspace.settings or {}),
        WORKSPACE_POLICY_KEY: {"overrides": checked},
    }
    flag_modified(workspace, "settings")
    db.add(workspace)
    _audit(db, workspace.id, "policy_updated", actor, {"scope": "workspace", "overrides": checked})
    db.commit()
    effective, version = effective_policy(db, workspace)
    return {"overrides": checked, "effective_overrides": effective, "policy_version": version}


def set_platform_policy(db, policy: dict, *, actor: str) -> dict:
    from app.models.huggingface import HFPlatformConfig

    if set(policy) - {"overrides"}:
        raise HFError("HF_POLICY_INVALID", "Unknown platform policy fields.")
    checked = _validate_overrides(policy.get("overrides", {}), {})
    config = get_platform_config(db)
    if config is None:
        config = HFPlatformConfig(id="default", connection={}, limits={})
        db.add(config)
    config.policy = {"overrides": checked}
    _audit(db, None, "policy_updated", actor, {"scope": "platform", "overrides": checked})
    db.commit()
    return config.policy
