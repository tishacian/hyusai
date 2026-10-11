#!/usr/bin/env python3
"""Demo mock RPA orchestrator implementing the generic REST job contract.

Contract:
  GET  /health
  POST /jobs              body: {job_key, input?, callback_url?}
  GET  /jobs/{id}

Usage (from repo root or backend/):
  uvicorn scripts.mock_rpa_orchestrator:app --host 127.0.0.1 --port 8099

Optional auth: set MOCK_RPA_AUTH_TOKEN; when set, requests must send
Authorization: Bearer <token>.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Mock RPA Orchestrator", version="1.0.0")

AUTH_TOKEN = (os.environ.get("MOCK_RPA_AUTH_TOKEN") or "").strip()
JOB_DELAY_S = float(os.environ.get("MOCK_RPA_JOB_DELAY_S") or "0.3")

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


class StartJobBody(BaseModel):
    job_key: str = Field(..., min_length=1)
    input: Optional[dict[str, Any]] = None
    callback_url: Optional[str] = None


def _require_auth(authorization: Optional[str]) -> None:
    if not AUTH_TOKEN:
        return
    expected = f"Bearer {AUTH_TOKEN}"
    if (authorization or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _complete_job(job_id: str) -> None:
    time.sleep(max(0.0, JOB_DELAY_S))
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        payload = job.get("input") or {}
        job["status"] = "succeeded"
        job["result"] = {
            "message": f"Mock RPA completed job_key={job.get('job_key')}",
            "echo": payload,
            "completed_at": time.time(),
        }
        job["updated_at"] = time.time()


@app.get("/health")
def health(authorization: Optional[str] = Header(default=None)):
    _require_auth(authorization)
    return {"ok": True, "service": "mock_rpa_orchestrator"}


@app.get("/jobs")
def list_jobs(authorization: Optional[str] = Header(default=None)):
    _require_auth(authorization)
    with _lock:
        return {"jobs": list(_jobs.values()), "count": len(_jobs)}


@app.post("/jobs")
def start_job(
    body: StartJobBody,
    authorization: Optional[str] = Header(default=None),
):
    _require_auth(authorization)
    job_id = str(uuid.uuid4())
    now = time.time()
    record = {
        "id": job_id,
        "job_key": body.job_key,
        "status": "running",
        "input": body.input or {},
        "callback_url": body.callback_url,
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        _jobs[job_id] = record
    threading.Thread(target=_complete_job, args=(job_id,), daemon=True).start()
    return {
        "id": job_id,
        "job_key": body.job_key,
        "status": "running",
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: Optional[str] = Header(default=None)):
    _require_auth(authorization)
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Unknown job_id={job_id}")
    return job


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("MOCK_RPA_HOST", "127.0.0.1")
    port = int(os.environ.get("MOCK_RPA_PORT", "8099"))
    uvicorn.run(
        "scripts.mock_rpa_orchestrator:app",
        host=host,
        port=port,
        reload=False,
    )
