# Agentium ingress and Keycloak proxy contract

This document records the Lot 0 security contract for the public Agentium
ingress. It applies to `agentium.papai.ai` and to the frontend container when
it is reached directly from the host.

## Authoritative configuration

- `deploy/nginx/agentium-container-frontend.conf` is the current VM edge
  configuration once both application tiers run in Docker.
- `deploy/nginx/agentium-container-backend.conf` is the intermediate Docker
  backend cutover configuration.
- `deploy/nginx/agentium.conf` is the systemd/static-frontend configuration.
- `docker/nginx/agentium-frontend.conf` is baked into the frontend image.
- `docker/env/keycloak.agentium.env.example` defines the matching Keycloak
  hostname, `/kc` relative path, and `xforwarded` parsing contract.

The four Nginx variants deliberately carry the same hidden-path guard so that
changing deployment topology cannot reintroduce the SPA fallback exposure.

## SPA hidden-path invariant

Any URI that reaches the SPA surface and contains a hidden path segment must
return `404` before the Angular fallback is evaluated. Examples include:

- `/.env`
- `/.git/config`
- `/assets/.secret`

Without this guard, Nginx returns `index.html` with `200`, which does not leak
the requested file but incorrectly signals that common secret-discovery probes
succeeded.

Explicit service prefixes retain their own behavior. In particular,
`location ^~ /kc/` wins before regex evaluation, so Keycloak's legitimate
`/kc/realms/.../.well-known/openid-configuration` endpoint remains reachable.

The single SPA exception is the root `/.well-known/acme-challenge/` namespace.
The VM renewal profile uses the Certbot Nginx authenticator and installer. The
installed plugin injects an exact
`location = /.well-known/acme-challenge/<token>` directive into both matching
HTTP and HTTPS virtual hosts while the challenge runs; exact locations take
precedence over regex locations. The explicit exception supplies a second
safety margin, while nested lookalikes such as
`/assets/.well-known/acme-challenge/` remain blocked.

## Keycloak forwarded-header invariant

Keycloak is configured with `KC_PROXY_HEADERS=xforwarded`, so the public edge
must overwrite every origin-defining header that Keycloak consumes. The `/kc/`
location therefore:

- sets `X-Forwarded-For` from `$remote_addr` rather than appending an
  untrusted client value;
- sets `X-Forwarded-Host`, `X-Forwarded-Port`, and `X-Forwarded-Proto` from the
  accepted TLS request;
- removes incoming `Forwarded`, `X-Forwarded-Prefix`, and
  `X-Forwarded-Server` values.

This follows the Keycloak reverse-proxy guidance to set and overwrite the
selected proxy-header family. See
[Configuring a reverse proxy](https://www.keycloak.org/server/reverseproxy).

The runtime warning `Non-secure context detected; cookies are not secured`
does not, by itself, prove that the public proxy lost the HTTPS scheme. The
current deployment has both `KC_PROXY_HEADERS=xforwarded` and
`X-Forwarded-Proto $scheme`, and public authorization responses set `Secure`
cookies. The backend intentionally uses
`KEYCLOAK_URL_INTERNAL=http://agentium-kc:8080/kc` for server-to-server token
calls; warning timestamps observed during the Lot 0 audit correlate with
`POST /api/v1/auth/login` and no public `/kc/` request. Those internal calls do
not depend on browser cookies. They should not be made to impersonate an HTTPS
proxy request merely to silence a warning.

## Validation and rollout

The repository contract is covered by:

```bash
cd backend
.venv/bin/pytest app/tests/infra/test_nginx_security_contract.py -q
```

Do not install this file with a standalone `cp`/`reload` sequence. Use the
SHA-bound, no-clobber transaction in section 2 of
`docs/ops/navigation-lot-0-rollout.md`. It verifies the checkout SHA and exact
installed bytes, stores the original edge outside `sites-enabled`, runs
`nginx -t`, restores and reloads automatically on any failure, and retains an
`nginx -T` proof. A second file under `sites-enabled` would itself become an
active, conflicting virtual host.

Rebuild and recreate `agentium-frontend` as part of the next normal frontend
deployment so that the same guard is present inside the image. The edge reload
is sufficient to close the public exposure; no Keycloak restart is required.

Post-deployment checks:

```bash
for uri in /.env /.git/config /assets/.secret; do
  curl -sS -o /dev/null -w "$uri %{http_code}\n" \
    "https://agentium.papai.ai$uri"
done
curl -sS -o /dev/null -w '/systems %{http_code}\n' \
  https://agentium.papai.ai/systems
```

The hidden paths must return `404`, while `/systems` must remain `200`.
