"""Agentium API surface catalog.

The catalog keeps the public FastAPI surface tied to Agentium's product
mental model.  It is intentionally prefix-based: OpenAPI remains the source
of truth for concrete methods and paths, while this module provides the
business metadata required by docs, UI, and compatibility checks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


SurfaceStatus = Literal[
    "canonical",
    "compatibility",
    "internal",
    "public-external",
    "deprecated",
]

SurfaceAudience = Literal["workspace-user", "admin", "external", "system"]


@dataclass(frozen=True)
class SurfaceMetadata:
    prefix: str
    domain: str
    mental_object: str
    status: SurfaceStatus
    audience: SurfaceAudience
    owner: str
    ui_routes: tuple[str, ...] = ()
    successor_prefix: str | None = None
    notes: str = ""


CATALOG_VERSION = "2026-05-12"


SURFACE_METADATA: tuple[SurfaceMetadata, ...] = (
    SurfaceMetadata(
        "/api/v1/catalog",
        "Governance",
        "Governance",
        "canonical",
        "admin",
        "Platform",
        ("/governance/surface-map",),
        notes="Machine-readable catalog of API routes and UI surfaces.",
    ),
    SurfaceMetadata(
        "/api/v1/blueprints",
        "Governance",
        "Workspace",
        "canonical",
        "admin",
        "Platform",
        ("/governance/blueprints",),
        notes="Export/import workspace structure and configuration without members, secrets or raw data.",
    ),
    SurfaceMetadata(
        "/api/v1/mission-room",
        "Hypervisor",
        "Workbench",
        "canonical",
        "workspace-user",
        "Government Mission Room",
        ("/hypervisor/mission-room", "/hypervisor/mission-room/:view"),
        notes="Immersive workspace app: briefing, open intelligence, projects, map and advisory actions.",
    ),
    SurfaceMetadata(
        "/api/v1/auth",
        "Identity",
        "Workspace",
        "canonical",
        "workspace-user",
        "Platform",
        ("/auth", "/workspace", "/account"),
    ),
    SurfaceMetadata(
        "/api/v1/iam",
        "Governance",
        "Governance",
        "canonical",
        "admin",
        "Platform",
        ("/governance/access", "/workspace/:slug/access"),
    ),
    SurfaceMetadata(
        "/api/v1/systems",
        "Build",
        "System",
        "canonical",
        "workspace-user",
        "Agentium Core",
        ("/systems", "/systems/:id", "/systems/:id/capture"),
    ),
    SurfaceMetadata(
        "/api/v1/capabilities",
        "Build",
        "Capability",
        "canonical",
        "workspace-user",
        "Agentium Core",
        ("/capabilities", "/capabilities/:id"),
    ),
    SurfaceMetadata(
        "/api/v1/skills",
        "Build",
        "Skill",
        "canonical",
        "workspace-user",
        "Agentium Core",
        ("/skills", "/skills/:slug"),
    ),
    SurfaceMetadata(
        "/api/v1/knowledge-capture",
        "Build",
        "Workbench",
        "canonical",
        "workspace-user",
        "Knowledge Capture",
        ("/knowledge/capture", "/systems/:id/capture"),
        notes="Expert Knowledge Capture workbench; system-scoped or capability-level entry.",
    ),
    SurfaceMetadata(
        "/api/v1/documents",
        "Knowledge",
        "Knowledge",
        "canonical",
        "workspace-user",
        "Knowledge",
        ("/knowledge", "/knowledge/:id"),
        notes="Includes canonical collection ledger plus compatibility document routes.",
    ),
    SurfaceMetadata(
        "/api/v1/knowledge",
        "Knowledge",
        "Knowledge",
        "canonical",
        "workspace-user",
        "Knowledge",
        ("/knowledge", "/chat", "/hypervisor/mission-room"),
        notes="Workspace Knowledge Scopes: named multi-collection retrieval surfaces for assistants.",
    ),
    SurfaceMetadata(
        "/api/v1/runs",
        "Operate",
        "Run",
        "canonical",
        "workspace-user",
        "Runtime",
        ("/runs", "/runs/:id"),
    ),
    SurfaceMetadata(
        "/api/v1/voice",
        "Operate",
        "Workbench",
        "canonical",
        "workspace-user",
        "Runtime",
        ("/chat", "/knowledge/capture", "/systems/:id/capture"),
    ),
    SurfaceMetadata(
        "/api/v1/tasks",
        "Operate",
        "Run",
        "canonical",
        "workspace-user",
        "Runtime",
        ("/tasks",),
    ),
    SurfaceMetadata(
        "/api/v1/intelligence",
        "Operate",
        "Run",
        "canonical",
        "workspace-user",
        "Runtime",
        ("/intelligence",),
    ),
    SurfaceMetadata(
        "/api/v1/metrics",
        "Operate",
        "Run",
        "canonical",
        "workspace-user",
        "Runtime",
    ),
    SurfaceMetadata(
        "/api/v1/telemetry",
        "Operate",
        "Run",
        "canonical",
        "workspace-user",
        "Runtime",
        ("/observability",),
    ),
    SurfaceMetadata(
        "/api/v1/health",
        "Operate",
        "Run",
        "internal",
        "system",
        "Platform",
    ),
    SurfaceMetadata(
        "/api/v1/models",
        "Build",
        "System",
        "canonical",
        "workspace-user",
        "Platform",
        ("/systems/new", "/settings/legacy"),
    ),
    SurfaceMetadata(
        "/api/v1/chat",
        "Operate",
        "Workbench",
        "canonical",
        "workspace-user",
        "Runtime",
        ("/chat",),
    ),
    SurfaceMetadata(
        "/api/v1/sessions",
        "Operate",
        "Run",
        "compatibility",
        "workspace-user",
        "Runtime",
        ("/chat",),
        notes="Chat/session compatibility surface; canonical evidence lives under Runs.",
    ),
    SurfaceMetadata(
        "/api/v1/impact",
        "Hypervisor",
        "Review Queue",
        "canonical",
        "workspace-user",
        "Business Control",
        ("/hypervisor",),
    ),
    SurfaceMetadata(
        "/api/v1/hypervisor",
        "Hypervisor",
        "Review Queue",
        "canonical",
        "workspace-user",
        "Business Control",
        ("/hypervisor",),
    ),
    SurfaceMetadata(
        "/api/v1/control-plane",
        "Steer",
        "Governance",
        "canonical",
        "admin",
        "Business Control",
        ("/steering",),
    ),
    SurfaceMetadata(
        "/api/v1/contexts",
        "Steer",
        "Knowledge",
        "canonical",
        "workspace-user",
        "Knowledge",
        ("/steering/contexts", "/steering/contexts/:id"),
    ),
    SurfaceMetadata(
        "/api/v1/reasoning",
        "Build",
        "System",
        "canonical",
        "workspace-user",
        "Agentium Core",
        ("/systems/new", "/presets"),
    ),
    SurfaceMetadata(
        "/api/v1/evaluation",
        "Governance",
        "Review Queue",
        "canonical",
        "workspace-user",
        "Quality",
        ("/governance/canonical-answers", "/steering/review-queue"),
    ),
    SurfaceMetadata(
        "/api/v1/audit",
        "Governance",
        "Governance",
        "canonical",
        "admin",
        "Platform",
        ("/governance/audit",),
    ),
    SurfaceMetadata(
        "/api/v1/help-content",
        "Governance",
        "Governance",
        "canonical",
        "workspace-user",
        "Product",
    ),
    SurfaceMetadata(
        "/api/v1/presets",
        "Governance",
        "Governance",
        "canonical",
        "admin",
        "Knowledge",
        ("/presets",),
    ),
    SurfaceMetadata(
        "/api/v1/sharepoint",
        "Governance",
        "Connector",
        "canonical",
        "admin",
        "Connectors",
        ("/connectors/sharepoint", "/resources"),
    ),
    SurfaceMetadata(
        "/api/v1/sftp",
        "Governance",
        "Connector",
        "canonical",
        "workspace-user",
        "Connectors",
        ("/connectors", "/connectors/sftp", "/resources"),
        notes="Secure Deposit management and workspace staging queue.",
    ),
    SurfaceMetadata(
        "/api/v1/deposit-links",
        "External Intake",
        "Connector",
        "public-external",
        "external",
        "Connectors",
        ("/deposit/:accessId",),
        notes="Password-protected external deposit portal; no Agentium session required.",
    ),
    SurfaceMetadata(
        "/api/v1/agents",
        "Build",
        "System",
        "deprecated",
        "workspace-user",
        "Agentium Core",
        successor_prefix="/api/v1/systems",
        notes="Legacy alias retained for compatibility.",
    ),
    SurfaceMetadata(
        "/api/v1/traces",
        "Operate",
        "Run",
        "deprecated",
        "workspace-user",
        "Runtime",
        successor_prefix="/api/v1/runs",
        notes="Legacy trace surface; Runs are canonical.",
    ),
    SurfaceMetadata(
        "/api/v1/settings",
        "Governance",
        "Governance",
        "compatibility",
        "admin",
        "Knowledge",
        ("/settings/legacy",),
        successor_prefix="/api/v1/presets",
        notes="Compatibility proxy over workspace-default Presets.",
    ),
)


def surface_metadata() -> list[dict[str, Any]]:
    return [asdict(item) for item in SURFACE_METADATA]


def match_surface(path: str) -> SurfaceMetadata:
    ordered = sorted(SURFACE_METADATA, key=lambda item: len(item.prefix), reverse=True)
    for item in ordered:
        if path == item.prefix or path.startswith(item.prefix + "/"):
            return item
    # Deliberately explicit instead of failing: the catalog endpoint must
    # keep working if a route is added before metadata is filled in. Tests
    # guard against shipping uncataloged surfaces.
    segment = "/" + "/".join(path.strip("/").split("/")[:3])
    return SurfaceMetadata(
        segment,
        "Uncataloged",
        "Governance",
        "internal",
        "system",
        "Platform",
        notes="Missing surface metadata; add this prefix to SURFACE_METADATA.",
    )


def build_endpoint_catalog(openapi_schema: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path, operations in sorted(openapi_schema.get("paths", {}).items()):
        surface = match_surface(path)
        for method, operation in sorted(operations.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            entries.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId"),
                    "summary": operation.get("summary") or operation.get("description") or "",
                    "tags": operation.get("tags", []),
                    "domain": surface.domain,
                    "mental_object": surface.mental_object,
                    "status": surface.status,
                    "audience": surface.audience,
                    "owner": surface.owner,
                    "ui_routes": list(surface.ui_routes),
                    "successor_prefix": surface.successor_prefix,
                    "notes": surface.notes,
                }
            )
    return {
        "version": CATALOG_VERSION,
        "status_values": [
            "canonical",
            "compatibility",
            "internal",
            "public-external",
            "deprecated",
        ],
        "entries": entries,
        "uncataloged": [
            entry
            for entry in entries
            if entry["domain"] == "Uncataloged"
        ],
    }
