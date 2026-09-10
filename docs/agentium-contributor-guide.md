# Agentium contributor guide — newcomer onboarding

> Scope: day-to-day development on the `demo/agentic` branch of the `omnirag`
> repo. Releasing to the demo VM is a separate, explicit step — see
> [`agentium-release-process.md`](./agentium-release-process.md).
>
> The root `CONTRIBUTING.md` describes the historical papAI process (PRs to
> `develop`). Agentium work happens on `demo/agentic`; this guide takes
> precedence for it.

---

## 1. What you are working on

Agentium is an agentic work platform: a FastAPI backend, an Angular 20
frontend, Celery workers, and an infrastructure stack (PostgreSQL, Qdrant,
MinIO, Keycloak, RabbitMQ, LiveKit) deployed as Docker containers on the demo
VM `omnirag-demo`, served at `https://agentium.papai.ai`.

Two product layers matter for orientation:

- **Systems** — the intelligence layer: Flows, Runs, bindings, governance.
  Authors build and publish Systems.
- **Experience** — the application layer on top: end-users consume published
  Systems through business applications (`/work`), authors compose them in
  the Cockpit (`/create`). A **Studio** is the human surface of one such
  application's agent (the NAWA Agent Studio on `/work/pr-to-po`).

Read [`mental-model.md`](./mental-model.md) first. Then
[`agentium-reference.md`](./agentium-reference.md) — identity, lexicon,
surfaces and the Experience platform in one document.

The opt-in adoption experience, synthetic exercise and acceptance protocol are
documented in [agentium-adoption-roadmap.md](./agentium-adoption-roadmap.md).
Conversation is a first-class interface for using and controlling published
Systems; the graphical and conversational surfaces share execution and
authorization contracts.

## 2. The branch

`demo/agentic` is both the integration branch and the deployed branch. It is
the place of record. Rules:

- Start from an up-to-date branch: `git checkout demo/agentic && git pull
  --ff-only origin demo/agentic`. For isolated work, branch off
  (`feat/<topic>`, or a Cloud-agent `cursor/<topic>` branch) and merge back
  with `--ff-only`. After the land, keep working **on** `demo/agentic` —
  the topic branch is not a second integration line.
- Conventional commits, message explains the **why**:
  `feat(experience): …`, `fix(rag): …`, `docs(ops): …`.
- Never force-push. Never rewrite pushed history.
- Commit, push, and deploy only on explicit request/approval — the repo policy
  treats each of these as a separate GO
  ([`dev-deploy-policy.md`](./dev-deploy-policy.md)). Landing on
  `origin/demo/agentic` is **not** a VM switch; that is the
  [release process](./agentium-release-process.md).
- Never `rsync`/`scp` code to the VM. Code reaches the VM through git only.

## 3. Repo map

| Path | Status | Content |
|---|---|---|
| `backend/` | active | FastAPI app (`app/api/v1/endpoints`, `app/services`), Alembic migrations (`backend/alembic/versions`), tests (`backend/app/tests`) |
| `frontend-ng/` | active | Angular 20 app (standalone components + signals), its guards (`scripts/*.mjs`), unit runner, Playwright e2e (`e2e/tests`) |
| `docker/` | active | Dockerfiles (`Dockerfile.agentium-{backend,worker,frontend}`) and compose files for the VM |
| `scripts/` | active | Deployment and operations scripts (`agentium-vm-deploy.sh`, `run-iteration-canaries.sh`, orchestrator) |
| `docs/` | active | Architecture, runbooks, lot plans. Docs are part of the deliverable: ship them with the code they describe |
| `deploy/` | active | systemd units, Keycloak redeploy scripts |
| `frontend/`, `src/`, `main.py`, `archive/` | historical | Pre-Agentium OmniRAG surfaces. Do not build on them |

## 4. Local setup

Prerequisites: Docker Desktop, Python 3.12, Node ≥ 22.

**Backend**

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements/celery.txt -r requirements/cpu.txt -r requirements/test.txt
cd backend && uvicorn app.main:app --reload        # http://localhost:8000
```

`backend/.env` holds your local config. It is gitignored — keep it that way.
No secret ever enters the repo.

**Frontend**

```bash
cd frontend-ng
npm ci
npm run start        # http://localhost:4200, proxies /api/v1 to localhost:8000
```

**Hooks**: `pre-commit run --all-files` (config at repo root).

## 5. Quality gates — must be green before any commit

Frontend (from `frontend-ng/`):

```bash
npm run check:i18n       # i18n keys, FR/EN parity, lexicon, hardcoded-string hunt
npm run check:nav-links  # fail-closed: no raw Cockpit links outside the allowlist
npm run check:ui-chrome  # UI chrome rules (docs/agentium-ui-chrome.md)
npm run test:unit        # co-located *.spec.ts via node:test (no Karma)
npm run build:prod       # the type gate — ng lint is NOT configured; the prod build is
```

Backend (from `backend/`):

```bash
pytest app/tests/...     # target the tests for your area; full run before large slices
```

Playwright e2e (`npm run test:e2e`) targets the live VM and needs credentials;
it is the release gate, not a local development gate. The iteration canaries
(specs `11`, `12`, `16`, `17` under `e2e/tests/`) run from the protected runner
host at release time.

## 6. Conventions that are enforced, not suggested

**Every user-facing string goes through i18n.** Dictionaries live in
`frontend-ng/src/app/core/i18n/*.dict.ts`, French and English both, keyed by
domain (`experience.dict.ts`, `chrome.dict.ts`, …). `check:i18n` fails on
missing keys, unused keys, FR/EN drift, hardcoded UI text, and lexicon
violations — the lexicon (`src/app/core/i18n.lexicon.ts`) bans internal jargon
(e.g. "unbound") from user-facing copy. Write the FR entry and its EN mirror
in the same commit.

**UI chrome is governed.** Spacing, buttons, panels, and shell patterns follow
[`agentium-ui-chrome.md`](./agentium-ui-chrome.md), enforced by
`check:ui-chrome`. Don't invent one-off chrome.

**Angular style.** Standalone components, signals, `ChangeDetectionStrategy`
where present. Pure logic goes in plain TS modules with a co-located
`*.spec.ts` so the dependency-light unit runner (`scripts/run-unit.mjs`) can
execute it.

**Backend errors carry a contract.** Business rejections return a
`{code, message}` detail object with an explicit status code (see the
`ExperienceError` pattern in `backend/app/services/experience/`). Bare
FastAPI/Pydantic 422s are reserved for payload-shape rejections — the frontend
relies on this distinction to detect stale-bundle/API skew.

**Migrations.** One file per change in `backend/alembic/versions/`, numbered
`NNN_snake_case.py`, next free number. Migrations must be safe on live data:
fail closed on invalid rows rather than guessing. Anything touching a
migration changes the release procedure (pre-migration dump — see the release
note).

**No debug residue.** Remove temporary instrumentation before the delivery
commit. A dirty `git status` is not a parking lot: finish or stash.

## 7. Definition of done

- Gates in §5 green, prod build clean.
- FR + EN i18n entries shipped together.
- Tests updated alongside behavior (unit specs frontend, pytest backend).
- Docs updated when you change architecture, process, or an operator surface.
- No secrets, no debug instrumentation, clean working tree.
- Deployment is **not** part of done — it is a separate explicit step, per the
  [release process](./agentium-release-process.md).

## 8. Access checklist

- Bitbucket: `datategy-root/omnirag`, push rights on `demo/agentic`.
- SSH alias `omnirag-demo` with sudo (VM access — needed for releases only).
  Host `217.182.104.99` = `agentium.papai.ai`, user `ubuntu`. A Cloud Agent
  environment must carry that private key (or have its pubkey in the VM
  `authorized_keys`). Port 22 reachable + `Permission denied (publickey)`
  means the iteration loop stops at release-process §3 — do not rsync around
  it.
- A demo account on `https://agentium.papai.ai` for manual QA.

## 9. Reading list, in order

1. [`mental-model.md`](./mental-model.md) — what the product is.
2. [`agentium-reference.md`](./agentium-reference.md) — the lexicon, where things live in the UI, the Experience layer architecture.
3. [`agentium-ui-chrome.md`](./agentium-ui-chrome.md) — the visual rules the guard enforces.
4. [`agentium-realignment-plan.md`](./agentium-realignment-plan.md) — the drift matrix and target decisions the reference implements.
5. [`dev-deploy-policy.md`](./dev-deploy-policy.md) — the git/deploy policy and its anti-patterns.
6. [`agentium-release-process.md`](./agentium-release-process.md) — how a commit reaches the VM.
7. [`ops/agentium-safe-vm-deployment.md`](./ops/agentium-safe-vm-deployment.md) — the full operator runbook (milestones, incidents, storage protections).
8. [`agent-loop-openclaw-dev-plan.md`](./agent-loop-openclaw-dev-plan.md) — AgentLoop contract (deterministic envelope, non-deterministic interior). Lands on `demo/agentic`; deploy remains the release process.
