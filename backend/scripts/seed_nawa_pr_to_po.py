"""Seed the NAWA PR→PO witness: MCP servers, System, 4h schedule, HITL binding.

The published graph includes ``task.format_dossier`` — a ``python_recipe_v1``
node with ``requirements_text=tabulate>=0.9.0``. That is the training surface
for the managed-env workshop (Environment → Prepare → Test). Isolated Test
does not call SAP. A live Start-a-cycle reads advertised tools; write nodes compose and stay sealed.

Idempotent. Does not delete on re-seed. Does not talk to live SAP unless
the workspace has OAuth (``MCP_OAUTH_CLIENT_SECRET`` or the CONNECTORS form)
and the operator runs a test / skill.

Server attachment (live, default for nawa):
  * four Hikma S/4 MCP HTTP servers sharing one OAuth client-credentials
  * ``sap`` = Purchase Requisition (``s4-pr-mcp``), ``hikma`` = Purchase Order
    (``s4-po-mcp``) — hostnames and ``tools/list`` win if a note swaps them
  * ``sap_gr`` = Good Receipt, ``sap_inbox`` = Approval
  * client secret from ``MCP_OAUTH_CLIENT_SECRET`` (never stored in this file)

Override:
  * ``MCP_<SERVER_ID>_URL`` wins per server
  * ``MCP_OAUTH_TOKEN_URL`` / ``MCP_OAUTH_CLIENT_ID`` / ``MCP_OAUTH_SCOPE``
  * ``MCP_FIXTURE=1`` points ``sap`` and ``hikma`` at the local fixture
    (bearer, no OAuth). The two extra servers stay live unless overridden.

Usage:
    cd backend
    MCP_OAUTH_CLIENT_SECRET=... python -m scripts.seed_nawa_pr_to_po
    MCP_FIXTURE=1 python -m scripts.seed_nawa_pr_to_po
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

import app.models  # noqa: F401
from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.run_schedule import RunSchedule
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.mcp.flow import PR_TO_PO_SKILL_SLUGS, pr_to_po_flow
from app.services.seed_catalog_safety import owned_capability_for_seed
from app.services.skills_registry import seed_skills_and_capabilities
from app.services.systems import flow_publication
from app.services.run_engine import scheduler as run_scheduler

DEFAULT_WORKSPACE_SLUG = "nawa"
SEED_ACTOR = "nawa-pr-to-po-seed"
SYSTEM_NAME = "PR to PO"
CAPABILITY_SLUG = "nawa_pr_to_po"
BINDING_KEY = "procurement.pr_to_po.run"
EXPERIENCE_SLUG = "pr-to-po"
EXPERIENCE_NAME = "PR to PO"
EXPERIENCE_DESCRIPTION = (
    "Purchasing factory on live Hikma. The desk stays /work/pr-to-po."
)
EXPERIENCE_THEME: dict[str, Any] = {
    "live_href": "/work/pr-to-po",
    "origin": "existing",
}
EXPERIENCE_ACCESS_POLICY: dict[str, Any] = {
    "role_templates": [
        "workspace_viewer",
        "workspace_contributor",
        "workspace_reviewer",
        "workspace_admin",
        "workspace_owner",
    ]
}
FACTORY_I18N: dict[str, dict[str, str]] = {
    "en": {
        "home.title": "PR to PO",
        "home.subtitle": "The live surface is the purchasing factory.",
        "home.body": (
            "Open the factory on /work/pr-to-po. This inventory entry does not "
            "replace that desk."
        ),
        "home.action": "Start a cycle",
    },
    "fr": {
        "home.title": "PR vers PO",
        "home.subtitle": "La surface live est l’usine d’achat.",
        "home.body": (
            "Ouvrez l’usine sur /work/pr-to-po. Cette entrée d’inventaire ne "
            "remplace pas ce bureau."
        ),
        "home.action": "Lancer un cycle",
    },
}
CRON_EXPR = "0 */4 * * *"
DEFAULT_FIXTURE_URL = "http://127.0.0.1:8765"
NAWA_OAUTH_TOKEN_URL = "https://pihqa.authentication.eu10.hana.ondemand.com/oauth/token"
NAWA_OAUTH_CLIENT_ID = "sb-hikmah-s4-mcp!t37634"
NAWA_LIVE_SERVERS: tuple[tuple[str, str, str], ...] = (
    (
        "sap",
        "Purchase Requisition",
        "https://hikmah-s4-pr-mcp.cfapps.eu10.hana.ondemand.com/mcp",
    ),
    (
        "hikma",
        "Purchase Order",
        "https://hikmah-s4-po-mcp.cfapps.eu10.hana.ondemand.com/mcp",
    ),
    (
        "sap_gr",
        "Good Receipt",
        "https://hikmah-s4-goods-receipt-mcp.cfapps.eu10.hana.ondemand.com/mcp",
    ),
    (
        "sap_inbox",
        "Approval",
        "https://hikmah-s4-inbox-mcp.cfapps.eu10.hana.ondemand.com/mcp",
    ),
)
# The BAPI pair rides a *separate* OAuth client on eu20 (Integration Suite,
# 1 h token) — a token from the OData client does not authenticate here, so
# these rows carry their own oauth_* fields instead of auth_mode "inherit".
# Secret from MCP_BAPI_OAUTH_CLIENT_SECRET (or MCP_BAPI_PO_OAUTH_CLIENT_SECRET
# per server); never stored in this file.
NAWA_BAPI_OAUTH_TOKEN_URL = (
    "https://pihisdev-suite.authentication.eu20.hana.ondemand.com/oauth/token"
)
NAWA_BAPI_OAUTH_CLIENT_ID = (
    "sb-926f0aa8-7e67-4165-baca-4382c14e51de!b171326|it-rt-pihisdev-suite!b150645"
)
NAWA_BAPI_SERVERS: tuple[tuple[str, str, str], ...] = (
    (
        "bapi_po",
        "PO Posting (BAPI)",
        "https://pihisdev-suite-c2a4a4f295de49fe8e1e1bd4c17b1cdc.a.integration.cloud.sap/bapi_po",
    ),
    (
        "bapi_pr",
        "PR BAPIs",
        "https://pihisdev-suite-c2a4a4f295de49fe8e1e1bd4c17b1cdc.a.integration.cloud.sap/bapi_pr",
    ),
)


def _workspace(db: DBSession, slug: str) -> Workspace:
    row = db.query(Workspace).filter(Workspace.slug == slug).first()
    if row is None:
        raise SystemExit(
            f"workspace {slug!r} not found. Create it (or run the NAWA demo seed) first."
        )
    return row


def ensure_mcp_flag(db: DBSession, workspace: Workspace) -> None:
    settings = dict(workspace.settings or {})
    features = dict(settings.get("features") or {})
    catalog = dict(settings.get("catalog") or {})
    enabled = list(catalog.get("enabled_skills") or [])
    features["mcp_connector"] = True
    features["experience_v1"] = True
    features["flow_workbench_v1"] = True
    # Live SAP writes stay sealed unless the operator says so explicitly at
    # seed time. Absent env leaves the stored value untouched (default off).
    unseal = (os.environ.get("SAP_WRITE_UNSEALED") or "").strip().lower()
    if unseal in {"1", "true", "yes", "on"}:
        features["sap_write_unsealed"] = True
    elif unseal in {"0", "false", "no", "off"}:
        features["sap_write_unsealed"] = False
    for slug in PR_TO_PO_SKILL_SLUGS:
        if slug not in enabled:
            enabled.append(slug)
    catalog["enabled_skills"] = enabled
    settings["features"] = features
    settings["catalog"] = catalog
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)


def _server_url(server_id: str, fixture: bool, live_default: str = "") -> str:
    explicit = (os.environ.get(f"MCP_{server_id.upper()}_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if fixture and server_id in {"sap", "hikma"}:
        return f"{DEFAULT_FIXTURE_URL.rstrip('/')}/{server_id}"
    if fixture:
        return ""
    return str(live_default or "").strip().rstrip("/")


def _shared_oauth_payload() -> dict[str, Any]:
    token_url = (os.environ.get("MCP_OAUTH_TOKEN_URL") or NAWA_OAUTH_TOKEN_URL).strip()
    client_id = (os.environ.get("MCP_OAUTH_CLIENT_ID") or NAWA_OAUTH_CLIENT_ID).strip()
    scope = (os.environ.get("MCP_OAUTH_SCOPE") or "").strip()
    payload: dict[str, Any] = {
        "oauth_token_url": token_url,
        "oauth_client_id": client_id,
        "oauth_scope": scope,
    }
    secret = (os.environ.get("MCP_OAUTH_CLIENT_SECRET") or "").strip()
    if secret:
        payload["oauth_client_secret"] = secret
    return payload


def ensure_mcp_servers(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    fixture = os.environ.get("MCP_FIXTURE", "").strip() in {"1", "true", "yes"}
    current = {
        str(item.get("id") or ""): item
        for item in mcp_service.get_servers(workspace).get("servers") or []
    }
    rows = []
    for server_id, label, live_url in NAWA_LIVE_SERVERS:
        use_fixture = fixture and server_id in {"sap", "hikma"}
        url = _server_url(server_id, fixture, live_url)
        if not url:
            url = str((current.get(server_id) or {}).get("url") or "")
        token = (os.environ.get(f"MCP_{server_id.upper()}_TOKEN") or "").strip()
        payload: dict[str, Any] = {
            "id": server_id,
            "label": label,
            "transport": "http_sse" if use_fixture else "streamable_http",
            "auth_mode": "bearer" if use_fixture else "inherit",
            "url": url,
            "enabled": True,
        }
        if token:
            payload["token"] = token
        rows.append(payload)
    bapi_secret = (
        os.environ.get("MCP_BAPI_OAUTH_CLIENT_SECRET") or ""
    ).strip()
    for server_id, label, live_url in NAWA_BAPI_SERVERS:
        url = _server_url(server_id, fixture=False, live_default=live_url)
        if not url:
            url = str((current.get(server_id) or {}).get("url") or "")
        payload = {
            "id": server_id,
            "label": label,
            "transport": "streamable_http",
            "auth_mode": "oauth_client_credentials",
            "url": url,
            "enabled": True,
            "oauth_token_url": (
                os.environ.get("MCP_BAPI_OAUTH_TOKEN_URL") or NAWA_BAPI_OAUTH_TOKEN_URL
            ).strip(),
            "oauth_client_id": (
                os.environ.get("MCP_BAPI_OAUTH_CLIENT_ID") or NAWA_BAPI_OAUTH_CLIENT_ID
            ).strip(),
        }
        per_server_secret = (
            os.environ.get(f"MCP_{server_id.upper()}_OAUTH_CLIENT_SECRET") or ""
        ).strip()
        secret = per_server_secret or bapi_secret
        if secret:
            payload["oauth_client_secret"] = secret
        rows.append(payload)
    return mcp_service.replace_servers(
        db,
        workspace,
        {"servers": rows, "shared_auth": _shared_oauth_payload()},
    )


def _skill_ids(db: DBSession, slugs: tuple[str, ...]) -> list[str]:
    rows = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    by_slug = {row.slug: row.id for row in rows}
    missing = [slug for slug in slugs if slug not in by_slug]
    if missing:
        raise RuntimeError(f"Skills not seeded: {missing}. Run seed_skills_and_capabilities first.")
    return [by_slug[slug] for slug in slugs]


def ensure_capability(db: DBSession, workspace: Workspace) -> Capability:
    skill_ids = _skill_ids(db, PR_TO_PO_SKILL_SLUGS)
    payload = {
        "workspace_id": workspace.id,
        "name": "PR to PO",
        "description": (
            "NAWA procurement witness: seven MCP tools plus justification "
            "summary and a deterministic supplier vote."
        ),
        "tier": "client",
        "input_unit": "approved_pr",
        "output_unit": "purchase_order",
        "skill_ids": skill_ids,
        "pricing": {"unit": "per_run", "unit_price": 0.0, "currency": "USD"},
        "value_per_outcome": 0.0,
        "confidence_threshold": 0.0,
        "sla": {},
        "roi_model": {"seed": SEED_ACTOR, "value_driver": "procurement"},
        "is_seeded": "N",
    }
    existing = owned_capability_for_seed(db, workspace=workspace, slug=CAPABILITY_SLUG)
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing
    row = Capability(id=str(uuid4()), slug=CAPABILITY_SLUG, **payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    print(f"capability ready: {row.slug}")
    return row


def ensure_system(db: DBSession, workspace: Workspace, capability: Capability) -> System:
    flow = pr_to_po_flow()
    payload = {
        "objective": (
            "List approved PRs over MCP, reject over-budget ones without a human, "
            "and pause in NAWA before creating a PO."
        ),
        "capability_id": capability.id,
        "skill_ids": list(capability.skill_ids or []),
        "flow_definition": flow,
        "settings": {
            "nawa_pr_to_po": True,
            "surface": "work",
            "system_type": "pr_to_po",
            "brand": "Nawa",
            "work_route": "/work/pr-to-po",
            "binding_key": BINDING_KEY,
        },
        "execution_mode": "human_augmented",
        "execution_profile": {"nawa_pr_to_po": True},
        "coordination_pattern": "graph",
        "status": "active",
        "created_by": SEED_ACTOR,
        "default_prompt_type": "factual",
        "default_model": "gpt-4o-mini",
        "retrieval_mode_default": "hybrid",
    }
    system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == SYSTEM_NAME)
        .first()
    )
    if system:
        for key, value in payload.items():
            if key == "flow_definition":
                continue
            setattr(system, key, value)
        flow_publication.reconcile_system_flow(
            db,
            system=system,
            workspace=workspace,
            flow_definition=flow,
            actor=SEED_ACTOR,
            publish_if_owned=True,
            ownership_prefix=SEED_ACTOR,
            message="PR to PO — seed reconciliation",
        )
        system.updated_at = datetime.utcnow()
    else:
        system = System(id=str(uuid4()), workspace_id=workspace.id, name=SYSTEM_NAME, **payload)
        db.add(system)
        db.flush()
        flow_publication.initialize_new_system_publication_if_enabled(
            db, system=system, workspace=workspace, actor=SEED_ACTOR
        )
        if not flow_publication.flow_publication_enabled(workspace):
            system.flow_definition = flow
    db.commit()
    db.refresh(system)
    print(f"system ready: {system.name} id={system.id}")
    return system


def ensure_schedule(db: DBSession, workspace: Workspace, system: System) -> RunSchedule:
    row = (
        db.query(RunSchedule)
        .filter(
            RunSchedule.workspace_id == workspace.id,
            RunSchedule.system_id == system.id,
            RunSchedule.cron_expr == CRON_EXPR,
        )
        .first()
    )
    next_fire = run_scheduler.validate_cron_expr(CRON_EXPR, "UTC")
    if row:
        row.enabled = True
        row.name = "PR to PO every 4 hours"
        row.next_fire_at = next_fire
        row.updated_at = datetime.utcnow()
    else:
        row = RunSchedule(
            id=str(uuid4()),
            workspace_id=workspace.id,
            system_id=system.id,
            name="PR to PO every 4 hours",
            cron_expr=CRON_EXPR,
            timezone="UTC",
            input_payload={},
            enabled=True,
            next_fire_at=next_fire,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    print(f"schedule ready: {row.cron_expr} next={row.next_fire_at}")
    return row


def ensure_binding(db: DBSession, workspace: Workspace, system: System) -> Any:
    from app.services.experience import bindings as binding_service

    version_id = system.published_flow_version_id
    if not version_id:
        print("binding skipped: system has no published flow version")
        return None
    try:
        row = binding_service.get_binding(
            db, workspace_id=workspace.id, binding_key=BINDING_KEY
        )
    except binding_service.BindingError:
        row = binding_service.create_binding(
            db,
            workspace=workspace,
            actor=SEED_ACTOR,
            binding_key=BINDING_KEY,
            system_id=system.id,
            published_flow_version_id=version_id,
            ingress_id="src",
            confirmation_policy="direct-safe",
            on_unavailable="unavailable",
        )
    else:
        if row.published_flow_version_id != version_id:
            row = binding_service.retarget_binding(
                db,
                workspace=workspace,
                binding_key=BINDING_KEY,
                actor=SEED_ACTOR,
            )
    db.commit()
    print(f"binding ready: {BINDING_KEY}")
    return row


def _copy(key: str, english: str) -> dict[str, Any]:
    return {"$i18n": key, "fallback": english}


def factory_document(binding_key: str | None = BINDING_KEY) -> dict[str, Any]:
    """Inventory pointer. The live desk stays the hardcoded /work/pr-to-po route."""
    components: list[dict[str, Any]] = [
        {
            "type": "header",
            "id": "factory-head",
            "props": {
                "title": _copy("home.title", FACTORY_I18N["en"]["home.title"]),
                "subtitle": _copy("home.subtitle", FACTORY_I18N["en"]["home.subtitle"]),
            },
        },
        {
            "type": "callout",
            "id": "factory-live",
            "props": {
                "body": _copy("home.body", FACTORY_I18N["en"]["home.body"]),
                "href": "/work/pr-to-po",
            },
        },
    ]
    keys: list[str] = []
    if binding_key:
        keys.append(binding_key)
        components.append(
            {
                "type": "action_button",
                "id": "factory-cycle",
                "props": {
                    "label": _copy("home.action", FACTORY_I18N["en"]["home.action"]),
                    "bindingKey": binding_key,
                    "input": {},
                    "afterSuccess": "stay",
                },
            }
        )
    return {"i18n": FACTORY_I18N, "pages": [{"id": "home", "title": _copy("home.title", FACTORY_I18N["en"]["home.title"]), "components": components}]}


def _factory_release(db: DBSession, workspace: Workspace, experience: Any) -> Any:
    from app.models.experience import ExperienceRelease
    from app.services.experience import lifecycle

    check = lifecycle.ready_check(db, workspace=workspace, experience_id=experience.id)
    if check["blockers"]:
        raise SystemExit(
            f"{EXPERIENCE_SLUG}: the draft is not releasable — {check['blockers']}"
        )
    _row, draft, _deployments = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    access = dict(experience.access_policy or {})
    for candidate in (
        db.query(ExperienceRelease)
        .filter(
            ExperienceRelease.experience_id == experience.id,
            ExperienceRelease.workspace_id == workspace.id,
        )
        .order_by(ExperienceRelease.release_number.desc())
        .all()
    ):
        if (
            candidate.content_sha256 == draft.content_sha256
            and (candidate.bindings_snapshot or []) == check["bindings"]
            and dict(candidate.access_snapshot or {}) == access
        ):
            return candidate
    return lifecycle.create_release(
        db,
        workspace=workspace,
        experience_id=experience.id,
        notes="PR to PO factory: inventory pointer to /work/pr-to-po.",
        expected_draft_revision=int(draft.revision),
        expected_content_sha256=draft.content_sha256,
        expected_experience_updated_at=experience.updated_at,
        expected_bindings_sha256=check["bindings_sha256"],
        actor=SEED_ACTOR,
    )


def ensure_experience(db: DBSession, workspace: Workspace, binding_key: str | None) -> Any:
    """Publish PR to PO as a business application that launches the factory desk."""
    from app.models.experience import Experience, ExperienceDeployment
    from app.services.experience import lifecycle

    document = factory_document(binding_key)
    keys = lifecycle.referenced_binding_keys(document)
    experience = (
        db.query(Experience)
        .filter(
            Experience.workspace_id == workspace.id,
            Experience.slug == EXPERIENCE_SLUG,
        )
        .one_or_none()
    )
    if experience is None:
        experience, _draft = lifecycle.create_experience(
            db,
            workspace=workspace,
            actor=SEED_ACTOR,
            name=EXPERIENCE_NAME,
            slug=EXPERIENCE_SLUG,
            pattern="assistant",
            languages=["en", "fr"],
            theme=EXPERIENCE_THEME,
            access_policy=EXPERIENCE_ACCESS_POLICY,
            description=EXPERIENCE_DESCRIPTION,
        )
        db.commit()
        db.refresh(experience)
    else:
        experience = lifecycle.update_experience(
            db,
            workspace_id=workspace.id,
            experience_id=experience.id,
            name=EXPERIENCE_NAME,
            pattern="assistant",
            languages=["en", "fr"],
            theme=EXPERIENCE_THEME,
            access_policy=EXPERIENCE_ACCESS_POLICY,
            description=EXPERIENCE_DESCRIPTION,
            set_description=True,
            actor=SEED_ACTOR,
        )
        db.commit()
        db.refresh(experience)

    _row, draft, _deployments = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    lifecycle.save_draft(
        db,
        workspace_id=workspace.id,
        experience_id=experience.id,
        pages=document,
        binding_keys=keys,
        expected_revision=int(draft.revision),
        actor=SEED_ACTOR,
    )
    db.commit()
    db.refresh(experience)

    release = _factory_release(db, workspace, experience)
    db.commit()

    deployment = (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == experience.id,
            ExperienceDeployment.channel == "live",
        )
        .one_or_none()
    )
    if deployment is None or deployment.release_id != release.id:
        deployment = lifecycle.deploy(
            db,
            workspace=workspace,
            experience_id=experience.id,
            channel="live",
            release_id=release.id,
            expected_current_release_id=(
                deployment.release_id if deployment is not None else None
            ),
            expected_deployment_updated_at=(
                deployment.updated_at if deployment is not None else None
            ),
            audience=None,
            actor=SEED_ACTOR,
        )
        db.commit()
    db.refresh(deployment)
    print(
        f"experience live: /work/{experience.slug} → {EXPERIENCE_THEME['live_href']} "
        f"r{release.release_number}"
    )
    return experience


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-slug", default=DEFAULT_WORKSPACE_SLUG)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed_skills_and_capabilities(db)
        workspace = _workspace(db, args.workspace_slug)
        ensure_mcp_flag(db, workspace)
        servers = ensure_mcp_servers(db, workspace)
        capability = ensure_capability(db, workspace)
        system = ensure_system(db, workspace, capability)
        ensure_schedule(db, workspace, system)
        binding = ensure_binding(db, workspace, system)
        ensure_experience(db, workspace, BINDING_KEY if binding is not None else None)
        print("MCP servers:", servers)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
