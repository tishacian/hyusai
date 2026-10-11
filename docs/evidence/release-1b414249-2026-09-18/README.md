# Release 1b414249 — compact advanced chat controls

Published `demo/agentic` revision:
`1b4142496f70d88ba34b56147be2a09baa872488`

## Change

The advanced chat header now starts compact:

- model, source, retrieval, reasoning, voice and action controls are hidden;
- one 36 px row keeps the active model name and a settings control;
- an active voice loop is still marked with `voice`;
- clicking the compact row expands the complete controls;
- clicking the collapse arrow restores the compact row;
- the preference is persisted locally.

## Local gates

- i18n: passed
- UI chrome: passed
- Frontend unit tests: 1,561 passed
- Frontend production build: passed

## Deployment

- Previous live revision: `c6119850dd100ca5f26f13a1af51619ed554ce53`
- Rollback tag: `c6119850dd10`
- Storage check: passed
- Migration: none
- Workspace flag and NAWA theme: unchanged
- Public revision verified: `1b4142496f70d88ba34b56147be2a09baa872488`
- Frontend HTTP: `200`
- Backend exception matches in inspected startup window: `0`

Images built on `omnirag-demo` at `1b4142496f70`:

- backend `sha256:bfebdc6a76d1e43c65f6094edef06f4cee1cddc5bb1035bb10392b1ef7e76637`
- worker `sha256:a00d11c16ecbc631094cf7dedb2213204d083d250c7eedca912ad281341d7b6c`
- frontend `sha256:baeb651afa46158aa4617e3539904e44ca98c0072a7e61fa5c70cefc3f089944`

Carakai iteration canaries: **10 passed, 2 intentional local-contract skips,
0 failed**. Machine-readable results are under [canaries](./canaries/).
