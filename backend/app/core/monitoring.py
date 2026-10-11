"""Monitoring and metrics collection."""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Deque, Dict, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

_UUID_RE = re.compile(
    r"(?<=/)[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)
_LONG_TOKEN_RE = re.compile(r"(?<=/)[A-Za-z0-9_-]{18,}(?=/|$)")
_INT_RE = re.compile(r"(?<=/)\d+(?=/|$)")


def normalize_endpoint(path: str) -> str:
    """Reduce high-cardinality URL paths to stable metric keys."""
    if not path:
        return "/"
    normalized = path.split("?", 1)[0].rstrip("/") or "/"
    normalized = _UUID_RE.sub("{uuid}", normalized)
    normalized = _LONG_TOKEN_RE.sub(
        lambda match: "{id}" if any(ch.isdigit() for ch in match.group(0)) else match.group(0),
        normalized,
    )
    normalized = _INT_RE.sub("{int}", normalized)
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class MetricsCollector:
    """Collects lightweight in-process runtime metrics.

    This intentionally stays dependency-free and memory-bounded: it is useful
    during incidents where DB/Qdrant may be slow, and it must never become part
    of the problem.
    """
    
    def __init__(self):
        self.metrics: Dict[str, Any] = defaultdict(lambda: {
            "count": 0,
            "total": 0.0,
            "min": float('inf'),
            "max": float('-inf'),
            "last_updated": None
        })
        self.pending: Dict[str, int] = defaultdict(int)
        self.pending_requests: Dict[str, Dict[str, Any]] = {}
        self.active_streams: Dict[str, Dict[str, Any]] = {}
        self.latency_samples: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=200))
        self.recent_slow_requests: Deque[Dict[str, Any]] = deque(maxlen=80)
        self.total_pending = 0
        self.event_loop_lag_ms = 0.0
        self.event_loop_lag_max_ms = 0.0
        self._lock = RLock()
        self.logger = get_logger(__name__)

    def start_request(self, endpoint: str, *, request_id: Optional[str] = None, method: Optional[str] = None) -> str:
        """Track an in-flight request."""
        endpoint = normalize_endpoint(endpoint)
        request_id = request_id or str(uuid.uuid4())
        now = time.monotonic()
        with self._lock:
            self.pending[endpoint] += 1
            self.total_pending += 1
            self.pending_requests[request_id] = {
                "endpoint": endpoint,
                "method": method or "",
                "started_monotonic": now,
                "started_at": _utc_now_iso(),
            }
        return request_id

    def finish_request(self, endpoint: str, *, request_id: Optional[str] = None):
        """Release an in-flight request counter."""
        endpoint = normalize_endpoint(endpoint)
        with self._lock:
            if request_id:
                record = self.pending_requests.pop(request_id, None)
                if record:
                    endpoint = record.get("endpoint") or endpoint
            if self.pending.get(endpoint, 0) > 0:
                self.pending[endpoint] -= 1
            if self.total_pending > 0:
                self.total_pending -= 1

    def start_stream(
        self,
        endpoint: str,
        *,
        stream_type: str = "sse",
        stream_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Track a long-lived stream beyond the HTTP response object."""
        endpoint = normalize_endpoint(endpoint)
        stream_id = stream_id or str(uuid.uuid4())
        with self._lock:
            self.active_streams[stream_id] = {
                "endpoint": endpoint,
                "stream_type": stream_type,
                "metadata": dict(metadata or {}),
                "started_monotonic": time.monotonic(),
                "started_at": _utc_now_iso(),
            }
        return stream_id

    def finish_stream(self, stream_id: str, *, status: str = "completed"):
        """Release a long-lived stream and record its total duration."""
        with self._lock:
            record = self.active_streams.pop(stream_id, None)
        if not record:
            return
        duration_ms = (time.monotonic() - float(record.get("started_monotonic") or time.monotonic())) * 1000
        endpoint = f"{record.get('endpoint') or 'stream'}#{record.get('stream_type') or 'stream'}"
        self.record_latency(endpoint, duration_ms)
        with self._lock:
            key = f"streams:{status}:{endpoint}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = _utc_now_iso()
    
    def record_latency(self, endpoint: str, latency_ms: float):
        """Record endpoint latency"""
        endpoint = normalize_endpoint(endpoint)
        with self._lock:
            key = f"latency:{endpoint}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["total"] += latency_ms
            self.metrics[key]["min"] = min(self.metrics[key]["min"], latency_ms)
            self.metrics[key]["max"] = max(self.metrics[key]["max"], latency_ms)
            self.metrics[key]["last_updated"] = _utc_now_iso()
            self.latency_samples[endpoint].append(float(latency_ms))
    
    def record_request(self, endpoint: str, status_code: int):
        """Record request"""
        endpoint = normalize_endpoint(endpoint)
        with self._lock:
            key = f"requests:{endpoint}:{status_code}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = _utc_now_iso()
    
    def record_error(self, error_type: str):
        """Record error"""
        with self._lock:
            key = f"errors:{error_type}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = _utc_now_iso()

    def record_timeout(self, endpoint: str, timeout_type: str = "request"):
        """Record a controlled timeout."""
        endpoint = normalize_endpoint(endpoint)
        with self._lock:
            key = f"timeouts:{timeout_type}:{endpoint}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = _utc_now_iso()

    def record_slow_request(
        self,
        *,
        method: str,
        endpoint: str,
        status_code: int,
        duration_ms: float,
        request_id: Optional[str] = None,
    ):
        """Keep a bounded recent slow-request ledger for incident triage."""
        with self._lock:
            self.recent_slow_requests.appendleft(
                {
                    "method": method,
                    "endpoint": normalize_endpoint(endpoint),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "request_id": request_id,
                    "at": _utc_now_iso(),
                }
            )

    def record_event_loop_lag(self, lag_ms: float):
        """Record current and maximum observed event-loop lag for this worker."""
        with self._lock:
            self.event_loop_lag_ms = round(max(0.0, lag_ms), 2)
            self.event_loop_lag_max_ms = round(max(self.event_loop_lag_max_ms, lag_ms), 2)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics"""
        formatted_metrics = {}

        with self._lock:
            metrics_snapshot = dict(self.metrics)
            pending_snapshot = dict(self.pending)
            total_pending = self.total_pending
            event_loop_lag_ms = self.event_loop_lag_ms
            event_loop_lag_max_ms = self.event_loop_lag_max_ms

        for key, value in metrics_snapshot.items():
            if "latency" in key:
                avg = value["total"] / value["count"] if value["count"] > 0 else 0
                formatted_metrics[key] = {
                    "count": value["count"],
                    "avg_ms": round(avg, 2),
                    "min_ms": value["min"] if value["min"] != float('inf') else 0,
                    "max_ms": value["max"] if value["max"] != float('-inf') else 0,
                    "last_updated": value["last_updated"]
                }
            else:
                formatted_metrics[key] = {
                    "count": value["count"],
                    "last_updated": value["last_updated"]
                }
        formatted_metrics["runtime:pending_requests"] = {
            "total": total_pending,
            "by_endpoint": pending_snapshot,
        }
        formatted_metrics["runtime:event_loop_lag"] = {
            "current_ms": event_loop_lag_ms,
            "max_ms": event_loop_lag_max_ms,
        }
        return formatted_metrics

    def get_endpoint_summary(self) -> Dict[str, Any]:
        """Return endpoint-centric request, latency, timeout and pending stats."""
        with self._lock:
            metrics_snapshot = dict(self.metrics)
            samples_snapshot = {key: list(values) for key, values in self.latency_samples.items()}
            pending_snapshot = dict(self.pending)

        endpoints = set(samples_snapshot) | set(pending_snapshot)
        request_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
        timeout_counts: Dict[str, int] = defaultdict(int)
        for key, value in metrics_snapshot.items():
            if key.startswith("requests:"):
                rest = key[len("requests:") :]
                try:
                    endpoint, status = rest.rsplit(":", 1)
                except ValueError:
                    continue
                endpoints.add(endpoint)
                request_counts[endpoint][status] = int(value.get("count") or 0)
            elif key.startswith("timeouts:"):
                rest = key[len("timeouts:") :]
                try:
                    _timeout_type, endpoint = rest.split(":", 1)
                except ValueError:
                    continue
                endpoints.add(endpoint)
                timeout_counts[endpoint] += int(value.get("count") or 0)

        summary: Dict[str, Any] = {}
        for endpoint in sorted(endpoints):
            samples = sorted(samples_snapshot.get(endpoint) or [])
            count = len(samples)
            p50 = samples[int((count - 1) * 0.50)] if count else 0.0
            p95 = samples[int((count - 1) * 0.95)] if count else 0.0
            summary[endpoint] = {
                "latency": {
                    "samples": count,
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "max_ms": round(samples[-1], 2) if samples else 0.0,
                },
                "requests": request_counts.get(endpoint, {}),
                "timeouts": timeout_counts.get(endpoint, 0),
                "pending": pending_snapshot.get(endpoint, 0),
            }
        return summary

    def get_runtime_snapshot(
        self,
        *,
        include_details: bool = False,
        stuck_after_ms: float = 30_000.0,
    ) -> Dict[str, Any]:
        """Return process runtime state without touching external systems."""
        now = time.monotonic()
        with self._lock:
            pending_records = {
                request_id: dict(record)
                for request_id, record in self.pending_requests.items()
            }
            stream_records = {
                stream_id: dict(record)
                for stream_id, record in self.active_streams.items()
            }
            pending_snapshot = dict(self.pending)
            total_pending = self.total_pending
            event_loop_lag_ms = self.event_loop_lag_ms
            event_loop_lag_max_ms = self.event_loop_lag_max_ms
            slow_requests = list(self.recent_slow_requests)

        def _age(record: Dict[str, Any]) -> float:
            return max(0.0, (now - float(record.get("started_monotonic") or now)) * 1000)

        active_requests = [
            {
                "request_id": request_id,
                "method": record.get("method") or "",
                "endpoint": record.get("endpoint") or "",
                "age_ms": round(_age(record), 2),
                "started_at": record.get("started_at"),
            }
            for request_id, record in pending_records.items()
        ]
        active_streams = [
            {
                "stream_id": stream_id,
                "endpoint": record.get("endpoint") or "",
                "stream_type": record.get("stream_type") or "stream",
                "age_ms": round(_age(record), 2),
                "started_at": record.get("started_at"),
                "metadata": record.get("metadata") or {},
            }
            for stream_id, record in stream_records.items()
        ]
        active_requests.sort(key=lambda item: item["age_ms"], reverse=True)
        active_streams.sort(key=lambda item: item["age_ms"], reverse=True)
        stuck_requests = [item for item in active_requests if item["age_ms"] >= stuck_after_ms]
        stuck_streams = [item for item in active_streams if item["age_ms"] >= stuck_after_ms]

        snapshot: Dict[str, Any] = {
            "pending_requests": {
                "total": total_pending,
                "by_endpoint": pending_snapshot,
                "stuck": len(stuck_requests),
                "stuck_after_ms": int(stuck_after_ms),
            },
            "active_streams": {
                "total": len(active_streams),
                "stuck": len(stuck_streams),
                "stuck_after_ms": int(stuck_after_ms),
            },
            "event_loop_lag": {
                "current_ms": event_loop_lag_ms,
                "max_ms": event_loop_lag_max_ms,
            },
            "recent_slow_requests": slow_requests[:20],
        }
        if include_details:
            snapshot["pending_requests"]["active"] = active_requests[:50]
            snapshot["active_streams"]["active"] = active_streams[:50]
        return snapshot

    def get_runtime_health(
        self,
        *,
        event_loop_lag_degraded_ms: float = 500.0,
        stuck_after_ms: float = 30_000.0,
    ) -> Dict[str, Any]:
        """Compact readiness-friendly runtime health."""
        snapshot = self.get_runtime_snapshot(include_details=False, stuck_after_ms=stuck_after_ms)
        current_lag = float((snapshot.get("event_loop_lag") or {}).get("current_ms") or 0)
        stuck_requests = int((snapshot.get("pending_requests") or {}).get("stuck") or 0)
        stuck_streams = int((snapshot.get("active_streams") or {}).get("stuck") or 0)
        degraded_reasons = []
        if current_lag >= event_loop_lag_degraded_ms:
            degraded_reasons.append("event_loop_lag")
        if stuck_requests:
            degraded_reasons.append("stuck_requests")
        if stuck_streams:
            degraded_reasons.append("stuck_streams")
        return {
            "status": "degraded" if degraded_reasons else "ok",
            "reasons": degraded_reasons,
            "pending_requests": snapshot["pending_requests"]["total"],
            "active_streams": snapshot["active_streams"]["total"],
            "event_loop_lag_ms": current_lag,
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        with self._lock:
            metrics_snapshot = dict(self.metrics)
            pending_snapshot = dict(self.pending)
            total_pending = self.total_pending
            event_loop_lag_ms = self.event_loop_lag_ms
            event_loop_lag_max_ms = self.event_loop_lag_max_ms

        total_requests = sum(
            v["count"] for k, v in metrics_snapshot.items()
            if k.startswith("requests:")
        )
        
        total_errors = sum(
            v["count"] for k, v in metrics_snapshot.items()
            if k.startswith("errors:")
        )
        
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_percent": round(error_rate, 2),
            "metrics_count": len(metrics_snapshot),
            "pending_requests": {
                "total": total_pending,
                "by_endpoint": pending_snapshot,
            },
            "event_loop_lag": {
                "current_ms": event_loop_lag_ms,
                "max_ms": event_loop_lag_max_ms,
            },
            "active_streams": self.get_runtime_snapshot().get("active_streams", {}),
        }


# Global metrics collector instance
metrics_collector = MetricsCollector()
