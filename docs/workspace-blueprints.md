# Agentium Workspace Blueprints

Workspace Blueprints are the portable contract for recreating an Agentium
workspace structure from a real reference workspace such as Andritz.

## Purpose

A blueprint exports structure and configuration:

- workspace mode and settings;
- capabilities referenced by the workspace;
- systems, flows, execution profile and model defaults;
- non-ephemeral contexts;
- knowledge collection metadata;
- RAG and evaluation presets;
- IAM role flags and capability overrides.

It deliberately does not export:

- users, members, Keycloak identities or personal roles;
- Secure Deposit links, passwords or staged files;
- raw documents, object-store payloads or Qdrant vectors;
- run history, audit logs or operational evidence.

## API

| Route | Purpose |
|---|---|
| `GET /api/v1/blueprints/workspace/current` | Export the current workspace blueprint. |
| `POST /api/v1/blueprints/workspace/validate` | Dry-run an import into the current workspace. No writes. |
| `POST /api/v1/blueprints/workspace/apply` | Apply the blueprint additively. Dry-run remains available through `dry_run=true`. |

All routes require workspace admin/owner privileges and use the current
workspace resolved from `X-Workspace-Slug`.

## Import Semantics

Imports are additive and keyed by stable names/slugs:

- capabilities are reused by slug when visible to the target workspace;
- contexts are reused by name;
- systems are reused by name, otherwise created as `draft`;
- knowledge collections are recreated as metadata-only rows;
- presets are recreated after capability/system references are resolved;
- IAM config is patched, but members are never imported.

The default UI path is `/governance/blueprints`. Operators should run a dry-run
before applying a pasted blueprint, then review created/reused/skipped counts.

## Andritz Reference

The Andritz workspace can now act as a reference implementation without becoming
a hardcoded tenant:

- Expert Knowledge Capture remains a System Workbench.
- Secure Deposit/SFTP remains a Connector and External Intake surface.
- Staging and proposals remain review queues.
- Knowledge collections are exported as collection contracts, not as raw files
  or vector data.
