"""Bind accepted proofs to an observed runner, driver and source identity.

Only the isolated runner observes package/server versions. API processes compare
that observation to their deployed image and the current profile/kit contracts;
missing or stale identity can never produce a positive certification badge.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from importlib import metadata

from pydantic import ValidationError

from app.core.config import settings
from app.services.connectors.certification import (
    CertificationDecision,
    ComponentIdentity,
    certification_level,
)
from app.services.connectors.profiles import get_profile


def kit_identity():
    from app.services.connectors.kit_identity import kit_identity as current

    return current()


def observe(profile_key, output):
    if (
        output.get("source") != "real"
        or output.get("connected") is not True
        or output.get("version_kind", "server") != "server"
    ):
        return None
    image = settings.connector_runner_image_sha256.removeprefix("sha256:")
    server = output.get("server_version")
    if (
        not re.fullmatch(r"[a-f0-9]{64}", image)
        or not isinstance(server, str)
        or not server
        or len(server) > 4096
    ):
        return None
    # Free-form server banners are bound without lossy normalization or leakage.
    server_key = (
        server
        if re.fullmatch(r"[\w.+:/@-]{1,160}", server)
        else "sha256:" + hashlib.sha256(server.encode()).hexdigest()
    )
    profile = get_profile(profile_key)
    try:
        drivers = []
        for package in profile.packages:
            try:
                version = metadata.version(package)
            except metadata.PackageNotFoundError:
                if package != "psycopg2":
                    raise
                package, version = "psycopg2-binary", metadata.version("psycopg2-binary")
            drivers.append({"package": re.sub(r"[-_.]+", "-", package.lower()), "version": version})
        kit = kit_identity()
        identity = ComponentIdentity(
            profile_key=profile.key,
            profile_version=str(profile.version),
            profile_sha256=profile.digest,
            capabilities=profile.capabilities,
            drivers=drivers,
            runner_image_sha256=image,
            kit_version=kit["version"],
            kit_sha256=kit["sha256"],
            server_version=server_key,
        )
    except (
        metadata.PackageNotFoundError,
        ValidationError,
        FileNotFoundError,
        ImportError,
        KeyError,
        ValueError,
    ):
        return None
    return identity.model_dump(mode="json")


def record_test(db, run, output):
    from app.models.connector_connection import ConnectorConnection

    connection = (
        db.query(ConnectorConnection)
        .filter_by(id=run.connection_id, workspace_id=run.workspace_id)
        .populate_existing()
        .one_or_none()
    )
    if (
        connection is None
        or connection.disabled_at
        or connection.revision != run.connection_revision
    ):
        return
    observation = output.get("runtime_identity")
    try:
        identity = ComponentIdentity.model_validate(observation) if observation else None
        if identity and (
            identity.profile_key != connection.profile_key
            or identity.profile_version != str(connection.profile_version)
        ):
            identity = None
    except ValidationError:
        identity = None
    connection.last_test = {
        "run_id": run.id,
        "connection_revision": run.connection_revision,
        "observed_at": datetime.now(UTC).isoformat(),
        "source": output.get("source"),
        "connected": output.get("connected") is True,
        "identity": identity.model_dump(mode="json") if identity else None,
    }
    db.flush()


def connection_decision(db, connection, *, now=None):
    from app.services.connectors.evidence_store import trusted_bundles

    profile = get_profile(connection.profile_key)
    if profile.family in {"mcp", "openapi"}:
        return CertificationDecision(level="third_party", reason="THIRD_PARTY")
    now = now or datetime.now(UTC)
    observation = connection.last_test or {}
    try:
        evidence = trusted_bundles(db, profile.key) if db is not None else ()
    except ValidationError:
        return CertificationDecision(level="needs_requalification", reason="EVIDENCE_INVALID")

    def missing(reason):
        return CertificationDecision(
            level="needs_requalification" if evidence else "unverified", reason=reason
        )

    image = settings.connector_runner_image_sha256.removeprefix("sha256:")
    environment = settings.connector_environment_id
    if not re.fullmatch(r"[a-f0-9]{64}", image) or not environment:
        return missing("DEPLOYED_IDENTITY_REQUIRED")
    try:
        identity = ComponentIdentity.model_validate(observation.get("identity"))
        observed_at = datetime.fromisoformat(observation["observed_at"])
        kit = kit_identity()
    except (ValidationError, ValueError, KeyError, TypeError, FileNotFoundError, ImportError):
        return missing("RUNNER_OBSERVATION_REQUIRED")
    if (
        observation.get("connection_revision") != connection.revision
        or observation.get("source") != "real"
        or observation.get("connected") is not True
    ):
        return missing("CONNECTION_OBSERVATION_CHANGED")
    if (
        observed_at.utcoffset() is None
        or observed_at > now
        or now - observed_at >= timedelta(days=30)
    ):
        return missing("RUNNER_OBSERVATION_EXPIRED")
    if (
        identity.profile_sha256 != profile.digest
        or identity.runner_image_sha256 != image
        or identity.kit_sha256 != kit["sha256"]
        or identity.kit_version != kit["version"]
    ):
        return missing("COMPONENTS_CHANGED")
    return certification_level(identity, evidence, now=now, deployed_environment_id=environment)
