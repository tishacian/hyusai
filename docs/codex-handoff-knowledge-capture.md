# Codex Handoff — Agentium Knowledge Capture

## Current State

- Local branch: `demo/agentic`
- Last deployed VM commit: `6318615f1a27824843154be7f7cd15ccba2306b5`
- VM host: `ubuntu@agentium.papai.ai`
- VM repo: `/home/ubuntu/omnirag`
- Backend service: `agentium-backend`
- Frontend static root: `/var/www/agentium`
- Primary capture route: `/systems/demo/capture`
- Legacy capture route: `/knowledge/capture`

## Useful Docs

- `docs/vm-deploy-chat-runbook.md`
- `docs/expert-knowledge-capture.md`
- `docs/operator-deploy-vague-d.md`
- `deploy/agentium-backend.service`
- `deploy/nginx/agentium.conf`
- `docs/ops/secrets.md`

## Recent Product Direction

Expert Knowledge Capture should be treated as a dedicated Agentium System UI, not as a generic Knowledge screen.

The current goal is a more user-friendly capture cockpit inspired by the mockups:

- guided wizard: Sessions -> Preparation -> Plan -> Capture -> Proposal
- system-scoped route and layout under Agentium chrome
- conversation-first voice capture
- visible trace focused on business events, not technical STT/retrieval noise
- proposal review as structured facts / evidence / open questions, not raw transcript first

## Recent Frontend Work

Main file:

- `frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts`

Related API file:

- `frontend-ng/src/app/core/api.service.ts`

Implemented:

- System UI route at `/systems/:id/capture`.
- Wizard-style navigation and screen organization.
- Preparation screen inspired by mockups:
  - session title
  - objective
  - domain selection
  - knowledge context
  - expert profile
  - maximum duration
- Plan mode step:
  - `AI proposes a plan`
  - `I provide the plan`
  - `No plan - free conversation`
- Capture cockpit with conversation-only mode.
- Conversation-only primary action uses `Start session` semantics.
- Conversation-only mic handling was fixed:
  - pre-arms microphone during the user click
  - reuses the stream after TTS
  - avoids the session stopping after only reading the first question
- Visible ledger now calls events with `business_only=true`.
- UI label for deferred empty proposal:
  - `More expert detail needed before proposal`

## Recent Backend Work

Main files:

- `backend/app/api/v1/endpoints/knowledge_capture.py`
- `backend/app/services/knowledge_capture.py`
- `backend/app/tests/services/test_knowledge_capture.py`

Implemented:

- `GET /api/v1/knowledge-capture/sessions/{session_id}/events` supports `business_only=true`.
- `create_update_proposal` is idempotent for the latest `pending_review` proposal of a session.
- Conversation-only no longer depends strictly on UI-provided `last_proposal_id`; backend resolves the latest active proposal for the session.
- Empty proposal requests are deferred instead of producing empty proposals.
- Proposal generation event metadata now includes:
  - `operation`: `created` or `updated`
  - `fact_count`
- Business event filter includes:
  - `capture_plan_created`
  - `capture_session_started`
  - `expert_turn_finalized`
  - `transcript_amended`
  - `conversation_intent_detected`
  - `proposal_generated`
  - `proposal_reviewed`
  - `ai_speech_interrupted`

## Verification Commands

Frontend:

```bash
cd frontend-ng
PATH=/Users/thibaudishacian/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npx tsc -p tsconfig.app.json --noEmit
PATH=/Users/thibaudishacian/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npx ngc -p tsconfig.app.json --noEmit
```

Backend:

```bash
cd backend
PYTHONPATH=. .venv/bin/pytest app/tests/services/test_knowledge_capture.py
```

Last observed backend result:

```text
7 passed
```

## VM Deploy Runbook

```bash
ssh ubuntu@agentium.papai.ai
cd /home/ubuntu/omnirag
git pull --ff-only origin demo/agentic

cd backend
../venv/bin/alembic upgrade head

cd ../frontend-ng
npm run build:prod

sudo rsync -a --delete /home/ubuntu/omnirag/frontend-ng/dist/agentium/browser/ /var/www/agentium/
sudo systemctl restart agentium-backend

systemctl is-active agentium-backend
curl -fsS http://127.0.0.1:8000/health
```

Expected health:

```json
{"status":"healthy","app":"AI Orchestration Platform","version":"1.0.0-demo"}
```

OpenAPI smoke:

```bash
curl -fsS http://127.0.0.1:8000/openapi.json | python3 -c 'import json,sys; d=json.load(sys.stdin); paths=d.get("paths",{}); print("conversation-step", any("conversation-step" in p for p in paths)); print("retrieval-prefetch", any("retrieval-prefetch" in p for p in paths)); params=paths.get("/api/v1/knowledge-capture/sessions/{session_id}/events",{}).get("get",{}).get("parameters",[]); print("business_only", any(p.get("name")=="business_only" for p in params))'
```

Expected:

```text
conversation-step True
retrieval-prefetch True
business_only True
```

Frontend smoke:

```bash
curl -fsSI https://agentium.papai.ai/systems/demo/capture | head -20
grep -R "business_only" -n /var/www/agentium/*.js /var/www/agentium/*.mjs 2>/dev/null | head -5
```

## VM Notes

- Current VM untracked file observed after deploy: `uvicorn.log`.
- It was already present and should be ignored unless explicitly investigating backend logs.
- Last deploy completed successfully on commit `6318615f1a27824843154be7f7cd15ccba2306b5`.

## Next Useful Work

- Continue improving the capture cockpit toward the mockup:
  - clearer left interview plan rail
  - more conversational transcript center
  - quality panel on the right
  - proposal as fact-level review with accept/reject/edit controls
- Consider using `business_only=true` everywhere the visible trace is shown, while keeping full event polling available for debug/ops views.
- Validate conversation-only manually on VM:
  - start session
  - hear first question
  - answer by voice
  - request proposal
  - confirm proposal
  - accept proposal

