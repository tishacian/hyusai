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

