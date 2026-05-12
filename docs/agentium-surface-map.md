# Agentium Surface Map

This document is the human-readable companion to the runtime catalog exposed at
`GET /api/v1/catalog/endpoints`.

## Mental Model Objects

| Object | Meaning | Primary UI |
|---|---|---|
| `Workspace` | Tenant boundary, membership, mode, data isolation | `/workspace`, workspace picker |
| `Capability` | Business capability blueprint | `/capabilities` |
| `System` | Configured executable agentic system | `/systems`, `/systems/:id` |
| `Workbench` | Task-focused operating surface for a system or capability | `/systems/:id/capture`, `/knowledge/capture`, `/chat` |
| `Run` | Execution evidence and runtime ledger | `/runs`, `/observability`, `/tasks` |
| `Knowledge` | Collections, context and vectorized evidence | `/knowledge`, `/steering/contexts` |
| `Review Queue` | Human validation before policy or knowledge changes | `/steering/review-queue`, `/hypervisor` |
| `Connector` | External intake or integration surface | `/resources`, `/connectors/*` |
| `Governance` | Access, audit, presets and platform control | `/governance/*`, `/presets` |

## Canonical Andritz Mapping

| Andritz need | Agentium object | UI route | API prefix | Status |
|---|---|---|---|---|
| Expert interview planning and capture | `Workbench` | `/systems/:id/capture`, `/knowledge/capture` | `/api/v1/knowledge-capture` | `canonical` |
| Secure external file intake | `Connector` | `/connectors/sftp`, `/deposit/:accessId` | `/api/v1/sftp`, `/api/v1/deposit-links` | `canonical` / `public-external` |
| Workspace access and reviewer roles | `Governance` | `/governance/access`, `/workspace/:slug/access` | `/api/v1/iam` | `canonical` |
| Files waiting for validation | `Review Queue` | `/connectors/sftp` staging queue | `/api/v1/sftp/deposits` | `canonical` |
| Knowledge base collections and ingestion | `Knowledge` | `/knowledge` | `/api/v1/documents` | `canonical` |
| Execution traceability | `Run` | `/runs/:id` | `/api/v1/runs` | `canonical` |
| Recreate the workspace pattern elsewhere | `Workspace` | `/governance/blueprints` | `/api/v1/blueprints` | `canonical` |

## Canonical SENTINEL-CI Mapping

| Government mission-room need | Agentium object | UI route | API prefix | Status |
|---|---|---|---|---|
| Ministerial cockpit and daily briefing | `Workbench` | `/hypervisor/mission-room` | `/api/v1/mission-room` | `canonical` |
| Open intelligence and RSS weak signals | `Run` | `/hypervisor/mission-room`, `/intelligence` | `/api/v1/mission-room`, `/api/v1/intelligence` | `canonical` |
| Strategic project pilotage | `System` / `Workbench` | `/hypervisor/mission-room`, `/systems` | `/api/v1/mission-room`, `/api/v1/systems` | `canonical` |
| Territorial action map | `Workbench` | `/hypervisor/mission-room` | `/api/v1/mission-room/map` | `canonical` |
| Draft cabinet instructions | `Review Queue` | `/hypervisor/mission-room` | `/api/v1/mission-room/actions/draft` | `canonical` |
| Recreate the demo workspace elsewhere | `Workspace` | `/governance/blueprints` | `/api/v1/blueprints` | `canonical` |

SENTINEL-CI is deliberately a workspace pattern, not a hardcoded client
fork: the demo behavior is carried by workspace `mode=demo`, workspace
settings, seeded Capabilities/Skills, System `flow_definition.variant`, and
the Mission Room API surface.

## API Stability States

| Status | Rule |
|---|---|
| `canonical` | Preferred contract for new frontend and external integration work. |
| `compatibility` | Still active, but should not be used by new surfaces. Must point to a canonical successor. |
| `deprecated` | Backward-compatible alias with deprecation headers and a sunset target. |
| `public-external` | Intentionally unauthenticated by Agentium JWT, protected by its own scoped token or password flow. |
| `internal` | Operational/system endpoint; not a product surface. |

## Current Compatibility Ledger

| Legacy surface | Successor | Notes |
|---|---|---|
| `/api/v1/agents` | `/api/v1/systems` | Legacy alias for system inventory. Emits `X-Deprecated`, `Sunset`, `Link`. |
| `/api/v1/traces` | `/api/v1/runs` | Legacy trace access. Emits `X-Deprecated`, `Sunset`, `Link`. |
| `/api/v1/settings` | `/api/v1/presets` | Compatibility proxy over workspace-default presets. Emits compatibility/deprecation headers. |
| `/api/v1/documents/list` | `/api/v1/documents/collections` + collection document routes | Retained for older document views. |
| `/api/v1/documents/collections/{collection_name}` delete by name | `/api/v1/documents/collections/{collection_id}` | Retained while collection-ledger migration completes. |

## Navigation Contract

The frontend source of truth is `frontend-ng/src/app/core/navigation.catalog.ts`.
Each UI surface declares:

- lens: `Hypervisor`, `Build`, `Operate`, `Steer`, or `Govern`;
- object: one of the mental model objects above;
- scope: `workspace`, `capability`, `system`, `run`, `admin`, or `public`;
- primary API prefix;
- stability status and audience.

The backend source of truth is `backend/app/services/surface_catalog.py`.
FastAPI OpenAPI paths are enriched from prefix-level metadata and exposed via
`/api/v1/catalog/endpoints`.

## Workspace Blueprints

`/governance/blueprints` and `/api/v1/blueprints/*` provide the first portable
workspace-level contract. It exports structure and configuration only: Systems,
Capabilities, Contexts, IAM flags, presets and Knowledge collection metadata.
Members, credentials, Secure Deposit files, raw documents, vectors, runs and
audit logs are excluded. See `docs/workspace-blueprints.md`.

## Alignment Rule

No new Agentium route should ship unless it is represented in both:

1. the backend surface catalog, and
2. the frontend navigation catalog when it has a UI route.

This keeps Andritz-specific work generalizable: the workspace may be the first
real-world target, but every shipped surface must map back to an Agentium object.
