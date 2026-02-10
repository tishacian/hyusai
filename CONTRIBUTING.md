# Contributing

## Accessing Internal Packages

To set up access to our internal Python packages hosted on GitLab, follow the steps below.

---

### 1. Create a Personal Access Token

1. Go to your GitLab **[Personal Access Tokens page](https://gitlab.com/-/user_settings/personal_access_tokens)**.
2. Click **"Create new token"**.
3. Set the **scope** to `api` — this is the only required permission.
4. Give your token a descriptive name, for example: `package-registry-access-token`

5. Save the generated token securely (you’ll need it in the next step).

---

### 2. Configure pip

To allow `pip` to authenticate with GitLab’s package registry, update (or create) your pip configuration file.

Depending on your system:
- **Linux/macOS:** `~/.config/pip/pip.conf`
- **Windows:** `%APPDATA%\pip\pip.ini`

Add the following lines, replacing `<your-token-name>` and `<token>` with your actual values:

```ini
[global]
trusted-host = gitlab.com
index-url = https://<your-token-name>:<token>@gitlab.com/api/v4/groups/118007886/-/packages/pypi/simple
```

---

### 3. Verify Access

You can now install internal packages directly with:

```
pip install <package-name>
```

## Running Unit Tests Locally

Unit tests are executed using pytest. Before running them, you must install the required dependency sets.

### 1. Install Required Dependencies

From the project root, inside your local .venv install the following requirements files:
```
pip install -r requirements/celery.txt -r requirements/cpu.txt -r requirements/test.txt
```

### 2. Run the Full Test Suite

```
pytest
```

### 3. Advanced pytest Usage

For more advanced use cases (running specific tests, markers, fixtures, parallel execution, debugging, etc.), refer to the official pytest documentation:
https://docs.pytest.org/en/stable/how-to/usage.html
