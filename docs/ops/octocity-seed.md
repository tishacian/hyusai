# Octocity workspace seed contract

`ensure_octocity_mission_room_workspace` is idempotent and never removes an
existing workspace membership.

Owner auto-provisioning is opt-in through the backend environment:

```bash
OCTOCITY_OWNER_EMAILS='<operator-email>[,<second-operator-email>]'
```

Each value must identify an existing Agentium account. When the variable is
empty or absent, the seed logs that owner auto-provisioning was skipped and
leaves all existing memberships unchanged. No personal account is encoded in
the repository.

The seed owns four active OCTAVE Systems (`Mission Room`, `Territorial Map`,
`Open Intelligence`, `Decision Desk`) and the `octocity-operating-map` France
fixture. Upgrades are non-destructive: operator-created map rows, extra
settings and existing identifiers are retained; only fixture-owned fields are
reconciled. Sentinel remains on its own map and defaults.

For rollout and rollback, do not invoke the seed as an isolated ad-hoc step.
Use `docs/ops/navigation-lot-0-rollout.md`, which snapshots the seed-owned
System IDs before/after execution. The rollback CLI requires every requested
ID to exist and belong to the Octocity seed. It accepts either a wholly active
set (which it pauses) or a wholly paused set (idempotent retry); a missing,
foreign or mixed-state set fails the whole operation without a partial
mutation.
