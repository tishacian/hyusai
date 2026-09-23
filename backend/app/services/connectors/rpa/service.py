"""RPA Bridge connector: encrypted workspace config + generic REST job dispatch.

Config lives under ``workspace.settings["connectors"]["rpa_bridge"]``. The
auth token is encrypted at rest with a Fernet master key
(``RPA_CONNECTOR_FERNET_KEY``), using the same envelope pattern as the SAP
HANA connector. When no key is configured (dev), the token is stored in a
plaintext envelope. ``RPA_CONNECTOR_AUTH_TOKEN`` can supply a demo token
when none is stored on the workspace.

Generic orchestrator contract (no UiPath SDK):
  POST {base_url}/jobs          → start job
  GET  {base_url}/jobs/{id}     → status / result
  GET  {base_url}/health        → optional liveness (used by /test)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Mapping, Optional
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "RPA_CONNECTOR_FERNET_KEY"
ENV_FALLBACK_TOKEN = "RPA_CONNECTOR_AUTH_TOKEN"
CONNECTOR_KEY = "rpa_bridge"
FEATURE_FLAG = "rpa_bridge"
ENVELOPE_VERSION = 1

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_POLL_INTERVAL_S = 0.5
DEFAULT_POLL_TIMEOUT_S = 30.0
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "completed", "error"})


class EncryptionNotConfigured(RuntimeError):
    """Fernet master key missing or invalid."""


def is_workspace_enabled(workspace: "Workspace") -> bool:
    from app.services.workspace_features import feature_enabled

    return feature_enabled(workspace, FEATURE_FLAG)


def _connectors(workspace: "Workspace") -> dict[str, Any]:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    raw = settings.get("connectors")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _fernet_from_env():
    raw = os.environ.get(ENV_MASTER_KEY)
    if not raw:
        return None
    try:
        key = raw.encode("ascii")
        if len(base64.urlsafe_b64decode(key)) != 32:
            raise ValueError("expected 32 bytes after base64 decode")
    except Exception as exc:
        raise EncryptionNotConfigured(
            f"{ENV_MASTER_KEY} is not a valid urlsafe base64 Fernet key: {exc}"
        ) from exc
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    raw_master = base64.urlsafe_b64decode(key)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"rpa_connector:v1",
        info=b"rpa_bridge",
    ).derive(raw_master)
    return Fernet(base64.urlsafe_b64encode(derived))


def _encrypt_secret(plaintext: str) -> str:
    payload = plaintext.encode("utf-8")
    fernet = _fernet_from_env()
    if fernet is None:
        logger.warning(
            "%s not set; persisting RPA connector auth token in PLAINTEXT. "
            "Set %s to a urlsafe-base64 Fernet key before going to production.",
            ENV_MASTER_KEY,
            ENV_MASTER_KEY,
        )
        envelope = {
            "v": ENVELOPE_VERSION,
            "plaintext": base64.b64encode(payload).decode("ascii"),
        }
        return json.dumps(envelope)
    envelope = {
        "v": ENVELOPE_VERSION,
        "ciphertext": fernet.encrypt(payload).decode("ascii"),
    }
    return json.dumps(envelope)


def _decrypt_secret(blob: str) -> str:
    if not blob:
        return ""
    try:
        envelope = json.loads(blob)
    except Exception:
        return blob
    if not isinstance(envelope, dict) or "v" not in envelope:
        return blob
    if "plaintext" in envelope:
        return base64.b64decode(envelope["plaintext"]).decode("utf-8")
    if "ciphertext" in envelope:
        fernet = _fernet_from_env()
        if fernet is None:
            raise EncryptionNotConfigured(
                f"{ENV_MASTER_KEY} required to decrypt but is not set."
            )
        return fernet.decrypt(envelope["ciphertext"].encode("ascii")).decode("utf-8")
    raise ValueError(f"Unknown auth token envelope keys={sorted(envelope)}")


def _normalize_job_mapping(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        logical = str(key or "").strip()
        external = str(value or "").strip()
        if logical and external:
            out[logical] = external
    return out


def get_config(workspace: "Workspace", *, include_secrets: bool = False) -> dict[str, Any]:
    """Return the workspace RPA Bridge connector config.

    By default the auth token is masked (``auth_token_set`` bool only). Pass
    ``include_secrets=True`` for runtime dispatch (test/jobs/skill).
    """
    stored = _connectors(workspace).get(CONNECTOR_KEY)
    stored = dict(stored) if isinstance(stored, Mapping) else {}
    token_blob = str(stored.get("auth_token_encrypted") or "")
    token_set = bool(token_blob) or bool(os.environ.get(ENV_FALLBACK_TOKEN))
    base_url = str(stored.get("base_url") or "").rstrip("/")
    job_mapping = _normalize_job_mapping(stored.get("job_mapping"))
    callback_webhook_url = str(stored.get("callback_webhook_url") or "").strip() or None
    config: dict[str, Any] = {
        "base_url": base_url,
        "auth_token_set": token_set,
        "job_mapping": job_mapping,
        "callback_webhook_url": callback_webhook_url,
        "configured": bool(base_url and token_set),
    }
    if include_secrets:
        token = ""
        if token_blob:
            token = _decrypt_secret(token_blob)
        if not token:
            token = os.environ.get(ENV_FALLBACK_TOKEN) or ""
        config["auth_token"] = token
    return config


def set_config(db: DBSession, workspace: "Workspace", payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist connector settings. Auth token is write-only (omit to keep current)."""
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("base_url is required")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError("base_url must start with http:// or https://")

    job_mapping = _normalize_job_mapping(payload.get("job_mapping"))
    callback_raw = payload.get("callback_webhook_url")
    callback_webhook_url = (
        str(callback_raw).strip() if callback_raw is not None else None
    )
    if callback_webhook_url == "":
        callback_webhook_url = None

    settings = dict(workspace.settings or {})
    connectors = dict(settings.get("connectors") or {})
    current = dict(connectors.get(CONNECTOR_KEY) or {})
    stored: dict[str, Any] = {
        "base_url": base_url,
        "job_mapping": job_mapping,
    }
    if callback_webhook_url is not None:
        stored["callback_webhook_url"] = callback_webhook_url
    elif current.get("callback_webhook_url") and "callback_webhook_url" not in payload:
        stored["callback_webhook_url"] = current["callback_webhook_url"]

    auth_token = payload.get("auth_token")
    if auth_token is not None and str(auth_token) != "":
        stored["auth_token_encrypted"] = _encrypt_secret(str(auth_token))
    elif current.get("auth_token_encrypted"):
        stored["auth_token_encrypted"] = current["auth_token_encrypted"]

    connectors[CONNECTOR_KEY] = stored
    settings["connectors"] = connectors
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return get_config(workspace)


def _auth_headers(config: Mapping[str, Any]) -> dict[str, str]:
    token = str(config.get("auth_token") or "").strip()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _jobs_url(base_url: str, job_id: Optional[str] = None) -> str:
    root = base_url.rstrip("/") + "/"
    path = "jobs" if not job_id else f"jobs/{job_id}"
    return urljoin(root, path)


def resolve_job_key(config: Mapping[str, Any], job_key: str) -> str:
    """Map a logical job key through ``job_mapping`` when present."""
    key = str(job_key or "").strip()
    if not key:
        raise ValueError("job_key is required")
    mapping = _normalize_job_mapping(config.get("job_mapping"))
    return mapping.get(key, key)


def test_connection(config: Mapping[str, Any]) -> dict[str, Any]:
    """Hit ``GET {base}/health`` (preferred) or fall back to ``GET {base}/jobs``."""
    base_url = str(config.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ValueError("RPA Bridge connector is not fully configured (base_url)")
    headers = _auth_headers(config)
    started = time.perf_counter()
    with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
        health_url = urljoin(base_url.rstrip("/") + "/", "health")
        response = client.get(health_url, headers=headers)
        if response.status_code == 404:
            response = client.get(_jobs_url(base_url), headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(
                f"RPA orchestrator returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:200]}
    return {
        "ok": True,
        "status_code": response.status_code,
        "body": body,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def start_job(
    config: Mapping[str, Any],
    *,
    job_key: str,
    input_payload: Optional[Mapping[str, Any]] = None,
    callback_url: Optional[str] = None,
) -> dict[str, Any]:
    """POST ``{base}/jobs`` and return the orchestrator response."""
    base_url = str(config.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ValueError("RPA Bridge connector is not fully configured (base_url)")
    external_key = resolve_job_key(config, job_key)
    body: dict[str, Any] = {
        "job_key": external_key,
        "input": dict(input_payload) if isinstance(input_payload, Mapping) else {},
    }
    cb = (callback_url or config.get("callback_webhook_url") or "").strip()
    if cb:
        body["callback_url"] = cb

    started = time.perf_counter()
    with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
        response = client.post(
            _jobs_url(base_url),
            headers=_auth_headers(config),
            json=body,
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"RPA start_job failed HTTP {response.status_code}: {response.text[:300]}"
        )
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError("RPA start_job returned non-JSON body") from exc
    if not isinstance(data, dict):
        raise RuntimeError("RPA start_job returned unexpected payload")
    job_id = str(data.get("id") or data.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError("RPA start_job response missing id/job_id")
    return {
        "job_id": job_id,
        "job_key": external_key,
        "status": str(data.get("status") or "queued"),
        "result": data.get("result"),
        "raw": data,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def get_job(config: Mapping[str, Any], job_id: str) -> dict[str, Any]:
    """GET ``{base}/jobs/{id}``."""
    base_url = str(config.get("base_url") or "").rstrip("/")
    jid = str(job_id or "").strip()
    if not base_url:
        raise ValueError("RPA Bridge connector is not fully configured (base_url)")
    if not jid:
        raise ValueError("job_id is required")
    started = time.perf_counter()
    with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
        response = client.get(
            _jobs_url(base_url, jid),
            headers=_auth_headers(config),
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"RPA get_job failed HTTP {response.status_code}: {response.text[:300]}"
        )
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError("RPA get_job returned non-JSON body") from exc
    if not isinstance(data, dict):
        raise RuntimeError("RPA get_job returned unexpected payload")
    return {
        "job_id": str(data.get("id") or data.get("job_id") or jid),
        "status": str(data.get("status") or "unknown"),
        "result": data.get("result"),
        "error": data.get("error"),
        "raw": data,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def dispatch_and_poll(
    config: Mapping[str, Any],
    *,
    job_key: str,
    input_payload: Optional[Mapping[str, Any]] = None,
    callback_url: Optional[str] = None,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> dict[str, Any]:
    """Start a job and poll until a terminal status or timeout (bounded sync)."""
    try:
        timeout = max(0.1, float(timeout_s))
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_s must be a number") from exc
    try:
        interval = max(0.05, float(poll_interval_s))
    except (TypeError, ValueError) as exc:
        raise ValueError("poll_interval_s must be a number") from exc

    started = time.perf_counter()
    started_job = start_job(
        config,
        job_key=job_key,
        input_payload=input_payload,
        callback_url=callback_url,
    )
    job_id = started_job["job_id"]
    status = str(started_job.get("status") or "queued")
    result = started_job.get("result")
    error = None
    polls = 0

    if status.lower() not in TERMINAL_STATUSES:
        deadline = started + timeout
        while time.perf_counter() < deadline:
            time.sleep(interval)
            polls += 1
            current = get_job(config, job_id)
            status = str(current.get("status") or "unknown")
            result = current.get("result")
            error = current.get("error")
            if status.lower() in TERMINAL_STATUSES:
                break
        else:
            raise TimeoutError(
                f"RPA job {job_id} did not finish within {timeout:.1f}s "
                f"(last status={status})"
            )

    return {
        "job_id": job_id,
        "job_key": started_job.get("job_key") or resolve_job_key(config, job_key),
        "status": status,
        "result": result,
        "error": error,
        "polls": polls,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "timed_out": False,
    }
