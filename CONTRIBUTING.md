# Contributing

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

To set up your local development environment with all necessary tools for code quality and testing, follow these steps.

Run the dependencies installation script `install.sh`:
```
bash ./install.sh
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
