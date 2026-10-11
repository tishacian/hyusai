# Release 701cecc2 — chat drag performance

Published `demo/agentic` revision:
`701cecc2e587139bd290b5166c8d3f658ea75b2e`

## Change

Panel dragging no longer runs Angular change detection on every pointer move:

- pointer move handlers run outside Angular Zone;
- one width update is coalesced per animation frame;
- panel children stop receiving hover/pointer events during drag;
- the persisted width is committed once on pointer release.

## Local gates

- `check:i18n`: passed
- `check:ui-chrome`: passed
- frontend unit tests: 1,558 passed
- frontend production build: passed

## Deployment

- Previous live revision: `428e596e2e8965840655c1047c09d3ab07bd1876`
- Rollback tag: `428e596e2e89`
- Storage check: passed
- Migration: none
- Workspace flag and NAWA theme: unchanged
- Public revision: `701cecc2e587139bd290b5166c8d3f658ea75b2e`, verified
- Frontend HTTP: `200`
- Backend exception matches in inspected startup window: `0`

Images built on `omnirag-demo` at `701cecc2e587`:

- backend `sha256:9b66249a197b171753f5ca0dc1366b3d56f53d57d732f2b18a992a5fbf8bb6ae`
- worker `sha256:f6c1a76ddca0730bed0dcb8cba2df0b6e49a897f4df18a921d1b0918050599d9`
- frontend `sha256:59655289a94d416df0e9a654ca1f7c921eee9c0c9578b09c5b889c148c3ea382`

Carakai iteration canaries: **10 passed, 2 intentional local-contract skips,
0 failed**. Machine-readable results are under [canaries](./canaries/).
