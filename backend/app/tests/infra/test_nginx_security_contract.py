import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

NGINX_CONFIGS = (
    "deploy/nginx/agentium.conf",
    "deploy/nginx/agentium-container-backend.conf",
    "deploy/nginx/agentium-container-frontend.conf",
    "docker/nginx/agentium-frontend.conf",
)

KEYCLOAK_EDGE_CONFIGS = (
    "deploy/nginx/agentium.conf",
    "deploy/nginx/agentium-container-backend.conf",
    "deploy/nginx/agentium-container-frontend.conf",
)

DOTFILE_LOCATION_PATTERN = (
    r"^(?!/\.well-known/acme-challenge/)(?:.*/)?\."
)
DOTFILE_GUARD = (
    f"location ~ {DOTFILE_LOCATION_PATTERN} {{\n"
    "        return 404;\n"
    "    }"
)
SPA_FALLBACK = "\n    location / {\n"


@pytest.mark.parametrize("config_path", NGINX_CONFIGS)
def test_dotfile_guard_precedes_spa_fallback(config_path: str) -> None:
    config = (REPO_ROOT / config_path).read_text()

    guard_index = config.index(DOTFILE_GUARD)
    fallback_index = config.index(SPA_FALLBACK)

    assert guard_index < fallback_index


@pytest.mark.parametrize(
    "uri",
    (
        "/.env",
        "/.git/config",
        "/assets/.secret",
        "/nested/.well-known/acme-challenge/token",
    ),
)
def test_dotfile_guard_rejects_hidden_segments(uri: str) -> None:
    assert re.search(DOTFILE_LOCATION_PATTERN, uri)


def test_dotfile_guard_preserves_root_acme_challenge_namespace() -> None:
    assert not re.search(
        DOTFILE_LOCATION_PATTERN,
        "/.well-known/acme-challenge/certbot-token",
    )


@pytest.mark.parametrize("config_path", KEYCLOAK_EDGE_CONFIGS)
def test_keycloak_prefix_keeps_oidc_discovery_outside_spa_guard(
    config_path: str,
) -> None:
    config = (REPO_ROOT / config_path).read_text()

    # The OIDC URI itself contains a hidden segment and would match the SPA
    # guard. Nginx's ^~ prefix semantics stop regex evaluation for /kc/ first.
    assert re.search(
        DOTFILE_LOCATION_PATTERN,
        "/kc/realms/papai-org/.well-known/openid-configuration",
    )
    assert "location ^~ /kc/ {" in config


@pytest.mark.parametrize("config_path", KEYCLOAK_EDGE_CONFIGS)
def test_keycloak_proxy_forwards_complete_external_origin(config_path: str) -> None:
    config = (REPO_ROOT / config_path).read_text()
    keycloak_start = config.index("location ^~ /kc/ {")
    keycloak_end = config.index("\n    }", keycloak_start)
    keycloak_location = config[keycloak_start:keycloak_end]

    assert "proxy_set_header Host $host;" in keycloak_location
    assert 'proxy_set_header Forwarded "";' in keycloak_location
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in keycloak_location
    assert "proxy_set_header X-Forwarded-Host $host;" in keycloak_location
    assert "proxy_set_header X-Forwarded-Port $server_port;" in keycloak_location
    assert 'proxy_set_header X-Forwarded-Prefix "";' in keycloak_location
    assert 'proxy_set_header X-Forwarded-Server "";' in keycloak_location
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in keycloak_location
    assert "$proxy_add_x_forwarded_for" not in keycloak_location


def test_keycloak_runtime_declares_xforwarded_proxy_contract() -> None:
    keycloak_env = (
        REPO_ROOT / "docker/env/keycloak.agentium.env.example"
    ).read_text()

    assert "KC_PROXY_HEADERS=xforwarded" in keycloak_env
    assert "KC_HOSTNAME=https://agentium.papai.ai/kc" in keycloak_env
    assert "KC_HTTP_RELATIVE_PATH=/kc" in keycloak_env
