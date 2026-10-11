# Agentium Workspace Blueprints

Workspace Blueprint v2 is the portable contract for recreating both the
structure **and the configured experience** of an Agentium workspace. It can
therefore reproduce an Andritz business shell or a Sentinel/Octocity Mission
Room without turning a tenant slug into application logic.

## Portable contract

A v2 export contains:

- the canonical workspace mode;
- the positive-allowlisted experience contract: family/profile, feature flags,
  navigation, shell, assistant profiles, knowledge scopes, action packs and
  Mission Room extension configuration;
- application-access intent, but never per-member grants;
- capabilities and their Skill slugs;
- Systems, flows, execution mode/profile, source status and model defaults;
- non-ephemeral Contexts;
- Knowledge collection metadata;
- RAG and evaluation presets;
- IAM role flags and capability overrides.

The export does **not** serialize `workspace.settings` wholesale. Every nested
configuration is copied through a positive allowlist and credential-shaped
keys are removed recursively. Indirect descriptors such as
`{"name":"OPENAI_API_KEY","value":"…"}`, URL userinfo/query credentials and
Bearer values are removed as a unit, while ordinary business fields such as
`secretariat_label` or `passwordless_enabled` remain portable. This prevents an
SMTP password, provider token, runtime action state or migration marker from
becoming portable by accident.

The following data always remains outside a Blueprint:

- users, memberships, Keycloak identities and personal roles;
- per-member application grants;
- Secure Deposit links, passwords and staged files;
- raw documents, object-store payloads and vectors;
- run history, audit logs and operational evidence.

The `data_policy` section in every export records these exclusions explicitly.

## API

| Route | Purpose |
|---|---|
| `GET /api/v1/blueprints/workspace/current` | Export the current workspace as schema v2. |
| `POST /api/v1/blueprints/workspace/validate` | Compute an immutable dry-run for the current target workspace. No writes. |
| `POST /api/v1/blueprints/workspace/apply` | Apply the exact previously validated plan. |

All routes require workspace admin/owner privileges. The target is always the
workspace resolved from `X-Workspace-Slug`; neither the source slug nor the
source workspace ID can redirect an import.

A mutation of either supported schema requires the 64-character `plan_token`
returned by a dry-run.
The token binds the Blueprint digest, target workspace, target experience,
relevant object keys, memberships/grants and every operator choice. Apply locks
the target, reloads the caller's admin authority, then recomputes this state;
any permission loss is denied and any target drift returns a conflict requiring
a fresh dry-run.

Example request options:

```json
{
  "blueprint": { "kind": "agentium.workspace.blueprint", "schema_version": 2 },
  "dry_run": true,
  "experience_policy": "merge_missing",
  "entitlement_policy": "preserve_target",
  "activate_systems": false
}
```

The governance UI at `/governance/blueprints` binds Apply to the exact JSON,
workspace slug and selected policies that produced the latest dry-run. Editing
the JSON, switching workspace or changing an option invalidates that plan.

## Experience policies

`experience_policy` is mandatory in intent even though the safe default is
`preserve_target`:

- `preserve_target` reports every portable difference and writes none of it;
- `merge_missing` fills missing portable leaves and blocks on a different
  existing value or incompatible parent;
- `replace_portable` makes the complete positive-allowlisted projection match
  the source: it overwrites changed leaves and removes portable leaves absent
  from the source, while retaining non-portable and unknown target settings.

For object lists (assistant profiles, knowledge scopes, Mission Room navigation
and document profiles), `replace_portable` refuses the plan if replacing a
target item would erase private nested fields. It reports a conflict instead of
silently leaking or deleting the private state.

Source workspace name and slug are descriptive only. The target identity is
never overwritten.

Systems are created as `draft` by default. `activate_systems=true` restores a
canonical source status only as part of the dry-run-bound plan.

## Application entitlements

Application enforcement cannot be copied implicitly. The Blueprint carries
only:

```json
{
  "app_access": {
    "enforcement_requested": true,
    "required_apps": ["chat", "client360-pdr", "knowledge-capture"],
    "member_grants": "excluded"
  }
}
```

With `entitlement_policy=preserve_target`, the target grants and feature flag
remain unchanged. With
`entitlement_policy=grant_all_existing_members`, Apply creates every missing
required grant, verifies complete coverage, and only then enables
`app_entitlements_v1` in the same transaction. A partial backfill aborts the
whole import.

## Object import semantics

Object import remains additive and keyed by stable names/slugs:

- capabilities are reused by slug when visible to the target workspace;
- Contexts are reused by name;
- Systems are reused by name, otherwise created as `draft` unless explicit
  activation was validated;
- Knowledge collections are recreated as metadata-only rows;
- presets are recreated after Capability/System references are resolved;
- IAM configuration is patched, but members are never imported.

Canonical workspace modes, System statuses, execution modes, application keys
and action-pack IDs are validated before any writes.

## Schema v1 compatibility

Existing schema v1 files remain importable for their historical structural
content. Their `workspace.mode` and raw `workspace.settings` fields are
intentionally ignored and listed in `experience.legacy_ignored`; v1 can never
silently gain v2 experience semantics or bypass the dry-run token.

## Reference workspaces

Andritz can act as a reference implementation without becoming a hardcoded
tenant:

- Research (`/chat`), Client360 PDR (`/client360`) and Knowledge Capture
  (`/knowledge/capture`) remain the three business applications;
- Expert Knowledge Capture remains a System Workbench;
- Secure Deposit/SFTP remains a Connector and External Intake surface;
- staging and proposals remain review queues;
- Knowledge collections remain contracts, not exported content.

Sentinel and Octocity carry Mission Room as the same extension contract with
separate profiles, brands and canonical action packs. The extension also owns
strictly allowlisted dependencies for calendar, action planner, document and
visual intelligence, feature flags and the two institutional connector
descriptors. Private connectors, sessions and credentials remain target-local.
Blueprint validation rejects crossed Sentinel/Octocity packs, actions and
presentation terms before planning an apply.
