# Invocation audit without 360 perspectives — 17 September 2026

Observed on runtime `4771f15b`: the timeline operation shortcut opened a disabled
perspective although the parent Run already retained readable invocation evidence.
See the [original browser evidence](../release-4771f15b-2026-09-17/README.md).

The existing invocation URL now shows the selected invocation from the canonical
Run response when `skill_invocation_360_projection_v1` is false. That response
already filters unreadable invocations and redacts held I/O. The gated invocation
and perspective endpoints remain unchanged and are not requested in this mode.
The Run's operation lists use the same working link in both Run layouts.

The audit retains the exact input, output, metrics and trace supplied by the server.
It does not reconstruct missing evidence, relaunch a Run or assert human validation.
Route/workspace changes and flag revocation clear stale evidence. An unavailable
invocation presents a retry and the existing link back to its Run.

Local qualification:

- 1,496 frontend tests passed, including exact invocation selection, unavailable
  evidence, stale Run response, retry and 360 activation/revocation.
- 16 existing backend authorization/aggregate/perspective tests passed.
- i18n, navigation links, UI chrome and production build passed.
- The existing observability canary now clicks an operation, reloads its audit,
  and returns to the same Run when the fixture contains a timeline operation.

Runtime build, live canaries and manual browser verification: pending at this commit.
No migration, flag change, shared Skill modification or NAWA theme change.
