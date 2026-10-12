# Agentium

Agentium is Datategy's governed agentic platform: workspaces, knowledge bases and
RAG, flows and automations, applications, human review and the evidence trail that
goes with them. It is deployed on the demo VM by `scripts/agentium-vm-deploy.sh`.

The repository started as OmniRAG, a standalone RAG R&D app. That code (the
Streamlit app, `src/`, `benchmarking/`, `configurations/` and its Docker stack) is
no longer part of the tree; it stays readable at the tag `archive/omnirag-rd`.

## Getting the code

Clone over SSH ([Atlassian guide](https://support.atlassian.com/bitbucket-cloud/docs/configure-ssh-and-two-step-verification/)):

```
git clone git@bitbucket.org:datategy-root/omnirag.git
```

Then follow [CONTRIBUTING.md](CONTRIBUTING.md) and the
[contributor guide](docs/agentium-contributor-guide.md).

## Repository map

| Path | Content |
|---|---|
| `backend/` | FastAPI app (`app/api`, `app/services`, `app/workers`), Alembic migrations, tests (`app/tests`), data scripts (`scripts/`), Keycloak realm and theme |
| `frontend-ng/` | Angular app, its unit specs and Playwright e2e (`e2e/`) |
| `livekit-agent/` | LiveKit voice agent |
| `docker/` | `Dockerfile.agentium-*` images, their `.dockerignore`, Compose files for the VM and the OpenBao config |
| `deploy/` | nginx confs for the host and the containers, Keycloak redeploy scripts |
| `scripts/` | release, VM deployment, compliance and QA scripts |
| `ops/` | infrastructure as code: Terraform, Ansible, Helm chart |
| `config/` | versioned product contracts (compliance, Release A evidence authorities, application manifests, ML pilots) |
| `docs/` | architecture, runbooks, ADRs (`docs/adr/`), compliance matrix; historical docs under `docs/archive/` |
| `run_celery.sh`, `start.sh` | worker entry point of the Python images, local demo launcher |

Two bridges from the OmniRAG era are still wired and move under `backend/` in the
next lot: `src/metadata_extraction/` (document metadata extraction) and
`sample_data/` (demo documents). The vanilla SPA `frontend/` (served under
`/legacy/`) is retired in the same lot. See
[ADR 0004](docs/adr/0004-reorganisation-monorepo.md).

## Who do I talk to?

- RAG engine: [Kenneth](mailto:kenneth.ezukwoke@datategy.net)
- LLM as a Service: [Ahmed](mailto:ahmed.benmessaoud@datategy.net)
- Docker services, API: [Enzo](mailto:enzo.damion@datategy.net)
