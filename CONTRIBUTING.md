# Contributing

## Contribution guidelines

The following are some guidelines on how new code should be written. Following these rules when submitting new code makes the review easier so new code can be integrated in less time.

### While you are coding

- We follow the [PEP8](https://peps.python.org/pep-0008/) standard. Read it thoroughly.
- Use the [numpy docstring standard](https://numpydoc.readthedocs.io/en/latest/format.html#docstring-standard) in all your docstrings.
- Prefix your branch so that its content is clear. Read the [confluence page](https://datategy.atlassian.net/wiki/spaces/PAPAI/pages/294913/Git+Flow+Updates#Branch-naming-convention) on branch naming convention.
- Use the [conventional commit standard](https://www.conventionalcommits.org/en/v1.0.0/) in all your commits.
- Install and use the pre-commit hooks: `pip install pre-commit && pre-commit install`.
- Don't use LLM coding assistant that uses your data for training.

### After you finished developing

- Create a Pull Request from your branch to `develop`.
- Give a clear title to your PR. You can use the same prefix as for your branch.

The full workflow (repository map, local setup, tests, deployment) is in the
[contributor guide](docs/agentium-contributor-guide.md).

## Accessing Internal Packages

To set up access to our internal Python packages hosted on GitLab, follow the steps below.

---

### 1. Configure pip

To allow `pip` to authenticate with Datategy’s private package registry, update (or create) your pip configuration file.

Depending on your system:
- **Linux/macOS:** `~/.config/pip/pip.conf`
- **Windows:** `%APPDATA%\pip\pip.ini`

Add the following lines, replacing `<pip-index-url>` with the actual value:

```ini
[global]
trusted-host = gitlab.com
index-url = <pip-index-url>
```

---

### 2. Verify Access

You can now install internal packages directly with:

```
pip install <package-name>
```

## Development Setup

The backend runs on Python 3.12, the frontend on Node 22 or later.

```
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -c constraints-demo-app.txt
pip install pytest pytest-asyncio pytest-xdist
```

```
cd frontend-ng
npm ci
```

`backend/.env` holds your local configuration. It is gitignored; no secret ever
enters the repository.

## Running Tests Locally

From `backend/`:

```
pytest app/tests/infra -q      # contracts of the images, the VM chain and the repository
pytest -n 8 app/tests          # the full backend suite
```

From the repository root:

```
python scripts/agentium_compliance.py --check
```

From `frontend-ng/`, when you touch the frontend:

```
npx ng test
```

For more advanced use cases (running specific tests, markers, fixtures, parallel execution, debugging, etc.), refer to the official pytest documentation:
https://docs.pytest.org/en/stable/how-to/usage.html

## Where a script goes

Three folders, one role each ([ADR 0004](docs/adr/0004-reorganisation-monorepo.md), D6):

- `backend/scripts/`: data work run against the application (seeds, backfills,
  audits, benchmarks), started with `python scripts/<name>.py` from `backend/`.
- `scripts/`: release and VM operations (`agentium-*.sh`, `agentium_*.py`,
  deployment, compliance, QA gates), run from the repository root.
- `backend/app/cli/`: entry points that ship in the image, run with
  `python -m app.cli.<name>`.

A command that already exists in `app/cli` is not duplicated in either scripts
folder.
