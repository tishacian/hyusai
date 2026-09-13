# Agentium

Agentium is a workspace for asking grounded questions, adding trusted knowledge,
building task-focused AI Systems, and reviewing their Runs. It is designed to
be useful on first launch without requiring users to understand providers,
retrieval pipelines, Skills, policies, or orchestration graphs.

The historical OmniRAG engine remains part of Agentium's retrieval layer. The
active product surfaces are the FastAPI backend in `backend/` and the Angular
application in `frontend-ng/`; the root `frontend/`, `src/`, and `main.py`
belong to the retired pre-Agentium interface.

## Product story

The supported first-use path is intentionally short:

1. Open **Ask**.
2. If needed, connect and verify one model in **Settings**.
3. Add a document in **Knowledge**.
4. Ask a question, inspect its cited source, and retry safely if generation fails.
5. Move to **Build** only when the question-and-answer loop works and you need a reusable System. Review execution evidence in **Runs**.

Normal workspace navigation contains four destinations: **Ask**,
**Knowledge**, **Build**, and **Runs**. Advanced authoring and diagnostics stay
available through contextual actions and Settings.

## Local development

Prerequisites: Python 3.12, Node.js 22 or newer, and the dependency credentials
required by this private repository. Keep provider keys in `backend/.env`; do
not commit them.

Start the backend from the repository root:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements/celery.txt -r requirements/cpu.txt -r requirements/test.txt
cd backend
uvicorn app.main:app --reload
```

In a second terminal, start the frontend:

```bash
cd frontend-ng
npm ci
npm run start
```

Open [http://localhost:4200](http://localhost:4200). The Angular development
server proxies `/api/v1` to the backend at `127.0.0.1:8000`.

For the containerized infrastructure profile and its storage safety rules, see
[`docker/README.md`](docker/README.md). Production and VM deployment are
separate, explicit operations documented in
[`docs/agentium-release-process.md`](docs/agentium-release-process.md).

## Verification

Frontend gates, from `frontend-ng/`:

```bash
npm run check:i18n
npm run check:nav-links
npm run check:ui-chrome
npm run test:unit
npm run build:prod
```

Backend tests, from `backend/`:

```bash
pytest app/tests/...
```

The live first-use release gate is
`frontend-ng/e2e/tests/00-first-use-golden-path.spec.ts`. Run it only against an
isolated clean workspace with a real test provider:

```bash
cd frontend-ng
E2E_GOLDEN_PATH=1 \
E2E_GOLDEN_PROVIDER=ollama \
E2E_GOLDEN_MODEL=your-installed-model \
E2E_USERNAME=your-test-user \
E2E_PASSWORD=your-test-password \
E2E_WORKSPACE_SLUG=your-isolated-workspace \
E2E_BASE_URL=http://localhost:4200 \
npx playwright test e2e/tests/00-first-use-golden-path.spec.ts --project=chromium
```

For a cloud provider, also set `E2E_GOLDEN_API_KEY`; Azure-compatible setups
can set `E2E_GOLDEN_ENDPOINT` and `E2E_GOLDEN_DEPLOYMENT`. The test principal
must already belong to the isolated workspace. The test validates
the model before saving, uploads a synthetic document, opens a cited source,
forces one retryable transport failure, retries, runs in English and French,
and enforces `E2E_GOLDEN_MAX_FIRST_ANSWER_MS` (45 seconds by default).

## Repository map

```
Agentium/
├── backend/       FastAPI APIs, services, migrations, and backend tests
├── frontend-ng/   Angular product UI, unit contracts, and Playwright journeys
├── docker/        Agentium images and Compose profiles
├── scripts/       Quality, release, and operations tooling
├── docs/          Product, architecture, and operator documentation
└── src/           Historical OmniRAG interface; do not extend
```

Start with the
[`Agentium contributor guide`](docs/agentium-contributor-guide.md), then read
the [`product reference`](docs/agentium-reference.md) and
[`mental model`](docs/mental-model.md).
