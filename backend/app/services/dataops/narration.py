"""Narration gateway adapter: durable checkpoints, exact source scope and no fallback.

Only the configured gateway is contacted. Output bytes arrive inline and are
hashed into the tenant ObjectStore; gateway URLs and object keys are never read.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import ipaddress
import re
import socket
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.models.run import Run
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.schemas.narration import NarrationGatewayResult, NarrationSourceUnit, NarrationSpec
from app.schemas.service_contract import AssetRef
from app.services.governed_assets import (
    GovernanceError,
    asset_ref,
    canonical_bytes,
    content_digest,
    native_authorizer,
    record_qualification,
    register_asset,
    resolve_asset_ref,
)
from app.services.object_store import get_object_store
from app.services.service_promises import require_member

KIND = "narration_v1"
MAX_RESPONSE_BYTES = 8 * 1024**2


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


class NarrationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _host(value):
    value = value.lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if (
            not value
            or len(value) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in value.split(".")
            )
        ):
            raise NarrationError("NARRATION_ENDPOINT_INVALID") from None
        return value


class Gateway:
    """Pin a reviewed DNS address while retaining the verified TLS hostname."""

    def __init__(self):
        endpoint = str(settings.narration_endpoint or "").strip()
        if not endpoint:
            raise NarrationError("NARRATION_ENDPOINT_UNCONFIGURED")
        try:
            parsed = urlsplit(endpoint)
            self.host = _host(parsed.hostname or "")
            self.port = parsed.port or 443
            allowed = {
                _host(x.strip()) for x in settings.narration_allowed_hosts.split(",") if x.strip()
            }
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or self.host not in allowed
                or ".." in parsed.path.split("/")
                or "%" in parsed.path
                or "\\" in endpoint
            ):
                raise NarrationError("NARRATION_DESTINATION_DENIED")
            addresses = list(
                dict.fromkeys(
                    ipaddress.ip_address(row[4][0])
                    for row in socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
                )
            )
            if not addresses:
                raise NarrationError("NARRATION_DNS_FAILED")
            for address in addresses:
                ip = getattr(address, "ipv4_mapped", None) or address
                if (
                    ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_reserved
                    or ip.is_unspecified
                    or not ip.is_global
                    and str(ip) not in allowed
                ):
                    raise NarrationError("NARRATION_DESTINATION_DENIED")
            address = str(addresses[0])
            self.authority = self.host if self.port == 443 else f"{self.host}:{self.port}"
            authority = f"[{address}]" if ":" in address else address
            self.base = urlunsplit(
                ("https", f"{authority}:{self.port}", parsed.path.rstrip("/"), "", "")
            )
            self.identity = content_digest({"endpoint": endpoint, "host": self.host})
        except NarrationError:
            raise
        except (OSError, ValueError):
            raise NarrationError("NARRATION_DNS_FAILED") from None
        self.client = httpx.Client(verify=True, follow_redirects=False, trust_env=False)

    def close(self):
        self.client.close()

    def request(self, method, path, *, body=None, idempotency_key=None, timeout=30):
        headers = {"Host": self.authority, "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with self.client.stream(
                method,
                self.base + path,
                json=body,
                headers=headers,
                extensions={"sni_hostname": self.host},
                timeout=max(0.1, min(timeout, 30)),
            ) as response:
                if response.is_redirect:
                    raise NarrationError("NARRATION_REDIRECT_DENIED")
                if method == "DELETE" and response.status_code in {200, 202, 204, 404, 405}:
                    return {}
                if not 200 <= response.status_code < 300:
                    raise NarrationError("NARRATION_GATEWAY_REJECTED")
                data = bytearray()
                for block in response.iter_bytes(chunk_size=65536):
                    if len(data) + len(block) > MAX_RESPONSE_BYTES:
                        raise NarrationError("NARRATION_RESPONSE_TOO_LARGE")
                    data.extend(block)
            return NarrationGatewayResult.model_validate_json(bytes(data))
        except NarrationError:
            raise
        except (ValueError, ValidationError):
            raise NarrationError("NARRATION_RESPONSE_INVALID") from None
        except Exception:
            raise NarrationError("NARRATION_NETWORK_UNAVAILABLE") from None


def _authorize(db, ctx, reference):
    workspace = db.get(Workspace, ctx.get("workspace_id"), populate_existing=True)
    run = db.get(Run, ctx.get("run_id"), populate_existing=True) if ctx.get("run_id") else None
    if workspace is None or not workspace.is_active:
        raise NarrationError("NARRATION_WORKSPACE_DENIED")
    if run is None or run.workspace_id != workspace.id:
        raise NarrationError("NARRATION_RUN_REQUIRED")
    if run.status in {"failed", "cancelled"}:
        raise NarrationError("NARRATION_CANCELLED")
    user_id = ctx.get("user_id") or run.initiated_by_user_id
    user = require_member(db, workspace.id, user_id) if user_id else None
    if user:
        from app.services.run_access import readable_runs

        if not readable_runs(db, runs=[run], workspace=workspace, user=user):
            raise NarrationError("NARRATION_RUN_DENIED")
    source = resolve_asset_ref(
        db,
        workspace.id,
        reference,
        authorize=native_authorizer(db, workspace, user) if user else None,
    )
    if (
        user is None
        and source.run_id != run.id
        and (run.input_ref or {}).get("asset_ref") != asset_ref(source)
    ):
        # Scheduled identities can only use the immutable ingress source, or an
        # asset already produced by this same Run.
        raise NarrationError("NARRATION_SOURCE_DENIED")
    return workspace, run, source


def _units(source, budgets):
    raw = source.manifest_json.get("units")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 1000:
        raise NarrationError("NARRATION_SOURCE_UNITS_REQUIRED")
    try:
        units = [NarrationSourceUnit.model_validate(value) for value in raw]
    except ValidationError:
        raise NarrationError("NARRATION_SOURCE_UNITS_INVALID") from None
    objects = {obj["key"]: obj for obj in source.manifest_json.get("objects", [])}
    if len({unit.id for unit in units}) != len(units):
        raise NarrationError("NARRATION_SOURCE_UNITS_INVALID")
    for unit in units:
        declared = objects.get(unit.object_key)
        if declared is None or unit.sha256 != declared["sha256"]:
            raise NarrationError("NARRATION_SOURCE_UNIT_UNBOUND")
    if sum(unit.kind == "page" for unit in units) > min(
        budgets.max_pages, settings.narration_max_pages
    ) or sum(unit.kind == "image" for unit in units) > min(
        budgets.max_images, settings.narration_max_images
    ):
        raise NarrationError("NARRATION_UNIT_BUDGET_EXHAUSTED")
    return units


def _coverage(units, state):
    known = state["units"]

    def count(kind):
        selected = [unit.id for unit in units if kind is None or unit.kind == kind]
        processed = sum(known.get(key, {}).get("status") == "completed" for key in selected)
        failed = sum(known.get(key, {}).get("status") == "failed" for key in selected)
        return {
            "expected": len(selected),
            "processed": processed,
            "failed": failed,
            "missing": len(selected) - processed - failed,
        }

    return {**count(None), "pages": count("page"), "images": count("image")}


def _save(db, job, state, *, status=None, error=None, ctx=None):
    if ctx is not None:
        from app.services.window_budget import guard_checkpoint

        guard_checkpoint(db, ctx)
    job.result = copy.deepcopy(state)
    job.updated_at = _now()
    if status:
        job.status = status
        job.stage = status
        if status == "running" and job.started_at is None:
            job.started_at = job.updated_at
        if status in {"completed", "failed", "cancelled"}:
            job.completed_at = job.updated_at
    job.error = error
    db.commit()


def _charge(db, job, state, budgets, ctx):
    if state["requests"] >= budgets.max_requests:
        raise NarrationError("NARRATION_REQUEST_BUDGET_EXHAUSTED")
    state["requests"] += 1
    _save(db, job, state, ctx=ctx)


def _record_units(db, job, state, result, units, budgets, ctx):
    expected = {unit.id for unit in units}
    for unit in result.units:
        if unit.id not in expected:
            raise NarrationError("NARRATION_UNKNOWN_UNIT")
        if unit.status == "failed":
            checkpoint = {"status": "failed"}
        else:
            try:
                content = base64.b64decode(unit.content_base64, validate=True)
            except (ValueError, TypeError):
                raise NarrationError("NARRATION_CONTENT_INVALID") from None
            if not content or hashlib.sha256(content).hexdigest() != unit.sha256:
                raise NarrationError("NARRATION_CONTENT_DIGEST_MISMATCH")
            if len(content) > budgets.max_unit_bytes:
                raise NarrationError("NARRATION_UNIT_BYTES_EXHAUSTED")
            key = f"workspaces/{job.workspace_id}/narration/{job.id}/{unit.sha256}"
            checkpoint = {
                "status": "completed",
                "key": key,
                "sha256": unit.sha256,
                "size_bytes": len(content),
                "mime_type": unit.mime_type,
            }
        previous = state["units"].get(unit.id)
        if previous is not None:
            if previous != checkpoint:
                raise NarrationError("NARRATION_CHECKPOINT_CONFLICT")
            continue
        if unit.status == "completed":
            if state["output_bytes"] + len(content) > budgets.max_output_bytes:
                raise NarrationError("NARRATION_OUTPUT_BUDGET_EXHAUSTED")
            store = get_object_store()
            try:
                store.write_once(key, content)
            except Exception:
                if not store.exists(key) or store.read_bytes(key) != content:
                    raise NarrationError("NARRATION_OBJECT_WRITE_FAILED") from None
            state["output_bytes"] += len(content)
        state["units"][unit.id] = checkpoint
        # A page is acknowledged only after its actual bytes are stored; crashes
        # replay the same page and cannot double-charge its byte budget.
        state["coverage"] = _coverage(units, state)
        job.progress = min(99, int(100 * state["coverage"]["processed"] / len(units)))
        _save(db, job, state, ctx=ctx)


def _finish(db, job, state, result, source, units, run, ctx):
    from app.services.window_budget import guard_checkpoint

    guard_checkpoint(db, ctx)
    coverage = _coverage(units, state)
    if coverage["processed"] != coverage["expected"] or coverage["failed"] or result.next_cursor:
        raise NarrationError("NARRATION_COVERAGE_INCOMPLETE")
    objects = {
        value["key"]: {key: value[key] for key in ("key", "sha256", "size_bytes")}
        for value in state["units"].values()
    }
    evidence = [
        {
            "id": key,
            "kind": "image" if value["mime_type"].startswith("image/") else "text",
            "sha256": value["sha256"],
            "locator": {"object_key": value["key"]},
            **(
                {"mime_type": value["mime_type"]} if value["mime_type"].startswith("image/") else {}
            ),
        }
        for key, value in state["units"].items()
        if value["mime_type"].startswith(("text/", "image/"))
    ]
    output = {
        "technical_status": "completed",
        "coverage": coverage,
        "engine_revision": result.engine_revision,
        "job_id": job.id,
        "cost": state["cost"],
        "tokens": state["tokens"],
        "tokens_coverage": state["tokens_coverage"],
        "confidence": None,
        "disposition": "review",
    }
    derived = register_asset(
        db,
        job.workspace_id,
        "document_set",
        f"narration:{source.logical_key}"[:200],
        {
            **{
                key: source.manifest_json[key]
                for key in ("document_family", "source", "language", "task")
                if key in source.manifest_json
            },
            "objects": list(objects.values()),
            "output": output,
            "evidence": evidence,
            "source_ref": asset_ref(source),
            "units": state["units"],
            "producer": {"run_id": run.id, "engine_revision": result.engine_revision},
        },
        parents=[asset_ref(source)],
        run_id=run.id,
    )
    state["output"] = {**output, "asset_ref": asset_ref(derived)}
    job.progress = 100
    _save(db, job, state, status="completed", ctx=ctx)
    return state["output"]


def _cached_output(db, job, state, run, ctx):
    from app.services import window_budget

    old = resolve_asset_ref(
        db,
        job.workspace_id,
        state["output"]["asset_ref"],
        authorize=native_authorizer(
            db,
            db.get(Workspace, job.workspace_id),
            require_member(db, job.workspace_id, ctx.get("user_id") or run.initiated_by_user_id),
        ),
    )
    if old.run_id == run.id:
        window_budget.assert_active(ctx)
        return state["output"]
    # Reuse immutable bytes, but attach a new candidate to this producing Run.
    zero = window_budget.reserve(
        ctx,
        stage="narration",
        key="reuse:" + job.id + ":" + run.id,
        cost=0.0,
        tokens=0,
        seconds=0.0,
        replayable=True,
    )
    window_budget.settle(zero, cost=0.0, tokens=0, seconds=0.0)
    window_budget.guard_checkpoint(db, ctx)
    output = {
        **{k: v for k, v in state["output"].items() if k != "asset_ref"},
        "reused_from": {"run_id": old.run_id, "job_id": job.id, "asset_ref": asset_ref(old)},
        "original_measurement": {
            k: state["output"].get(k) for k in ("cost", "tokens", "tokens_coverage")
        },
        "cost": {
            "amount": 0.0,
            "currency": "USD",
            "measurement_coverage": "complete",
            "measurement_source": "idempotency_cache",
            "reserved_amount": 0.0,
        },
        "tokens": 0,
        "tokens_coverage": "complete",
        "confidence": None,
        "disposition": "review",
    }
    derived = register_asset(
        db,
        job.workspace_id,
        "document_set",
        old.logical_key,
        {
            **old.manifest_json,
            "output": output,
            "producer": {
                **old.manifest_json.get("producer", {}),
                "run_id": run.id,
                "reused_from_run_id": old.run_id,
                "reused_from_job_id": job.id,
            },
        },
        parents=[asset_ref(old)],
        run_id=run.id,
    )
    record_qualification(
        db,
        job.workspace_id,
        asset_ref(derived),
        status="review_required",
        policy={"authority": "narration_cached_candidate"},
        evidence={
            "producer_run_id": run.id,
            "source_ref": asset_ref(old),
            "no_new_gateway_execution": True,
        },
    )
    db.commit()
    return {**output, "asset_ref": asset_ref(derived)}


def _execute(spec, reference, node_id, ctx, cancelled):
    from app.db.base import SessionLocal
    from app.services import window_budget
    from app.services.llm_dataset_labeling import LabelingError, _workspace_lock
    from app.services.service_engine import window_for_run

    gateway = Gateway()
    try:
        with SessionLocal() as db:
            workspace, run, source = _authorize(db, ctx, reference)
            budgets = spec.budgets.model_copy(deep=True)
            budgets.timeout_s = min(budgets.timeout_s, settings.narration_timeout_s)
            window = window_for_run(db, run.id, workspace.id)
            budget = window_budget.limits(ctx, "narration")
            if budget:
                budgets.max_cost_usd = min(budgets.max_cost_usd, budget["max_cost"])
                budgets.max_tokens = min(budgets.max_tokens, budget["max_tokens"])
                budgets.timeout_s = min(
                    budgets.timeout_s,
                    budget["max_seconds"],
                )
            if budgets.timeout_s <= 0 or budgets.max_cost_usd <= 0 or budgets.max_tokens <= 0:
                raise NarrationError("NARRATION_BUDGET_EXHAUSTED")
            units = _units(source, budgets)
            request_hash = content_digest(
                {
                    "source_ref": reference,
                    "spec": spec.model_dump(mode="json"),
                    "budgets": budgets.model_dump(),
                    "gateway": gateway.identity,
                }
            )
            job_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"agentium:narration:{workspace.id}:{window.id if window else run.id}:{node_id}",
                )
            )
            with _workspace_lock(db.get_bind(), "narration:" + job_id):
                job = db.get(WorkspaceJob, job_id, populate_existing=True)
                if job:
                    if job.input_ref.get("request_sha256") != request_hash:
                        raise NarrationError("NARRATION_REQUEST_CHANGED")
                    state = copy.deepcopy(job.result)
                    if job.status == "completed":
                        return _cached_output(db, job, state, run, ctx)
                    if job.status in {"failed", "cancelled"}:
                        raise NarrationError(job.error or "NARRATION_JOB_CLOSED")
                else:
                    job = WorkspaceJob(
                        id=job_id,
                        workspace_id=workspace.id,
                        run_id=run.id,
                        system_id=run.system_id,
                        kind=KIND,
                        title="Document narration",
                        status="queued",
                        stage="queued",
                        created_by_user_id=ctx.get("user_id") or run.initiated_by_user_id,
                        input_ref={
                            "source_ref": reference,
                            "engine_revision": spec.engine_revision,
                            "node_id": node_id,
                            "request_sha256": request_hash,
                            "budgets": budgets.model_dump(),
                        },
                        progress=0,
                    )
                    state = {
                        "remote_job_id": None,
                        "cursor": None,
                        "requests": 0,
                        "output_bytes": 0,
                        "units": {},
                        "deadline_at": min(
                            _now() + timedelta(seconds=budgets.timeout_s),
                            window.deadline_at if window else datetime.max,
                        ).isoformat(),
                        "cost": {
                            "amount": None,
                            "currency": "USD",
                            "measurement_coverage": "unavailable",
                            "reserved_amount": budgets.max_cost_usd,
                        },
                        "tokens": None,
                        "tokens_coverage": "unavailable",
                    }
                    state["coverage"] = _coverage(units, state)
                    db.add(job)
                    _save(db, job, state, status="queued", ctx=ctx)
                service_reservation = None
                try:
                    while True:
                        db.refresh(job)
                        if cancelled.is_set() or job.status == "cancelled":
                            raise NarrationError("NARRATION_CANCELLED")
                        _, run, source = _authorize(db, ctx, reference)
                        window_budget.assert_active(ctx)
                        remaining = (
                            datetime.fromisoformat(state["deadline_at"]) - _now()
                        ).total_seconds()
                        if remaining <= 0:
                            raise NarrationError("NARRATION_TIMEOUT")
                        _charge(db, job, state, budgets, ctx)
                        if service_reservation is None:
                            service_reservation = window_budget.reserve(
                                ctx,
                                stage="narration",
                                key=job.id,
                                cost=budgets.max_cost_usd,
                                tokens=budgets.max_tokens,
                                seconds=budgets.timeout_s,
                                replayable=True,
                            )
                            if "budget_started_at" not in state:
                                state["budget_started_at"] = _now().isoformat()
                                _save(db, job, state, ctx=ctx)
                        if state["remote_job_id"] is None:
                            result = gateway.request(
                                "POST",
                                "/jobs",
                                idempotency_key=job.id,
                                timeout=remaining,
                                body={
                                    "protocol_version": 1,
                                    "source_ref": reference,
                                    "units": [unit.model_dump(exclude_none=True) for unit in units],
                                    "engine_revision": spec.engine_revision,
                                    "options": spec.options,
                                    "budgets": budgets.model_dump(),
                                },
                            )
                        else:
                            path = "/jobs/" + state["remote_job_id"]
                            if state["cursor"]:
                                path += "?cursor=" + quote(state["cursor"], safe="")
                            result = gateway.request("GET", path, timeout=remaining)
                        if (
                            result.engine_revision != spec.engine_revision
                            or result.source_digest != source.digest
                            or state["remote_job_id"] not in {None, result.job_id}
                        ):
                            raise NarrationError("NARRATION_RESPONSE_IDENTITY_CHANGED")
                        state["remote_job_id"] = result.job_id
                        if result.cost_usd is not None:
                            previous = state["cost"]["amount"]
                            if previous is not None and result.cost_usd < previous:
                                raise NarrationError("NARRATION_USAGE_CHANGED")
                            state["cost"]["amount"] = result.cost_usd
                            state["cost"]["measurement_coverage"] = "partial"
                        if result.tokens is not None:
                            if state["tokens"] is not None and result.tokens < state["tokens"]:
                                raise NarrationError("NARRATION_USAGE_CHANGED")
                            state["tokens"] = result.tokens
                            state["tokens_coverage"] = "partial"
                        terminal = result.status in {"completed", "failed", "cancelled"}
                        settlement = window_budget.settle(
                            service_reservation,
                            cost=result.cost_usd,
                            tokens=result.tokens,
                            seconds=max(
                                0.0,
                                (
                                    _now() - datetime.fromisoformat(state["budget_started_at"])
                                ).total_seconds(),
                            )
                            if terminal
                            else None,
                            final=terminal,
                        )
                        if settlement and settlement["over_budget"]:
                            raise NarrationError("SERVICE_BUDGET_EXHAUSTED")
                        if settlement and settlement.get("measurement_conflict"):
                            raise NarrationError("SERVICE_BUDGET_MEASUREMENT_CHANGED")
                        _save(
                            db,
                            job,
                            state,
                            status=result.status
                            if result.status in {"queued", "running"}
                            else None,
                            ctx=ctx,
                        )
                        if _now() >= datetime.fromisoformat(state["deadline_at"]):
                            raise NarrationError("NARRATION_TIMEOUT")
                        if (
                            (
                                state["cost"]["amount"] is not None
                                and state["cost"]["amount"] > budgets.max_cost_usd
                            )
                            or state["tokens"] is not None
                            and state["tokens"] > budgets.max_tokens
                        ):
                            raise NarrationError("NARRATION_BUDGET_EXHAUSTED")
                        _record_units(db, job, state, result, units, budgets, ctx)
                        state["cursor"] = result.next_cursor
                        _save(db, job, state, ctx=ctx)
                        if result.status == "completed":
                            if result.cost_usd is not None:
                                state["cost"]["measurement_coverage"] = "complete"
                            if result.tokens is not None:
                                state["tokens_coverage"] = "complete"
                            _, run, source = _authorize(db, ctx, reference)
                            if _now() >= datetime.fromisoformat(state["deadline_at"]):
                                raise NarrationError("NARRATION_TIMEOUT")
                            return _finish(db, job, state, result, source, units, run, ctx)
                        if result.status in {"failed", "cancelled"}:
                            raise NarrationError(
                                "NARRATION_CANCELLED"
                                if result.status == "cancelled"
                                else "NARRATION_PROVIDER_FAILED"
                            )
                        if not result.next_cursor:
                            cancelled.wait(min(budgets.poll_interval_s, max(0, remaining)))
                except (NarrationError, GovernanceError) as exc:
                    db.rollback()
                    code = exc.code
                    if code == "SERVICE_STALE_LEASE":
                        # A stale worker must not cancel the new attempt's shared
                        # gateway job or overwrite its resumable checkpoints.
                        raise NarrationError(code) from None
                    # Transport failures are resumable with the same remote
                    # idempotency key and cursor; invalid outputs fail closed.
                    if code == "NARRATION_NETWORK_UNAVAILABLE":
                        _save(db, job, state, error=code, ctx=ctx)
                        raise
                    if state.get("remote_job_id") and state["requests"] < budgets.max_requests:
                        try:
                            _charge(db, job, state, budgets, ctx)
                            gateway.request("DELETE", "/jobs/" + state["remote_job_id"], timeout=2)
                        except (NarrationError, GovernanceError):
                            pass
                    _save(
                        db,
                        job,
                        state,
                        status="cancelled" if code == "NARRATION_CANCELLED" else "failed",
                        error=code,
                        ctx=ctx,
                    )
                    raise NarrationError(code) from None
    except LabelingError:
        raise NarrationError("NARRATION_BUSY") from None
    finally:
        gateway.close()


async def run_narration(payload, ctx=None):
    """Graph-owned narration settings; the actual Run supplies tenant authority."""
    try:
        envelope = payload["_narration"]
        if set(envelope) != {"narration", "node_id"}:
            raise ValueError
        spec = NarrationSpec.model_validate(envelope["narration"])
        node_id = envelope["node_id"]
        if not isinstance(node_id, str) or not 1 <= len(node_id) <= 160:
            raise ValueError
        supplied = payload.get("asset_ref")
        reference = AssetRef.model_validate(supplied or spec.source_ref).model_dump(mode="json")
        if spec.source_ref is not None and spec.source_ref.model_dump(mode="json") != reference:
            raise NarrationError("NARRATION_SOURCE_MISMATCH")
        if len(canonical_bytes(spec.options)) > 16384:
            raise ValueError
        if not ctx or not ctx.get("workspace_id") or not ctx.get("run_id"):
            raise NarrationError("NARRATION_RUN_REQUIRED")
    except NarrationError:
        raise
    except (ValueError, TypeError, KeyError, ValidationError):
        raise NarrationError("NARRATION_INPUT_INVALID") from None
    cancelled = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(_execute, spec, reference, node_id, ctx, cancelled)
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        try:
            await asyncio.shield(task)
        except Exception:
            pass
        raise
