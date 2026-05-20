"""Monitoring and metrics collection"""
from typing import Dict, Any, Optional
from datetime import datetime
from collections import defaultdict
from threading import RLock
from app.core.logging import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """Collects application metrics"""
    
    def __init__(self):
        self.metrics: Dict[str, Any] = defaultdict(lambda: {
            "count": 0,
            "total": 0.0,
            "min": float('inf'),
            "max": float('-inf'),
            "last_updated": None
        })
        self.pending: Dict[str, int] = defaultdict(int)
        self.total_pending = 0
        self.event_loop_lag_ms = 0.0
        self.event_loop_lag_max_ms = 0.0
        self._lock = RLock()
        self.logger = get_logger(__name__)

    def start_request(self, endpoint: str):
        """Track an in-flight request."""
        with self._lock:
            self.pending[endpoint] += 1
            self.total_pending += 1

    def finish_request(self, endpoint: str):
        """Release an in-flight request counter."""
        with self._lock:
            if self.pending.get(endpoint, 0) > 0:
                self.pending[endpoint] -= 1
            if self.total_pending > 0:
                self.total_pending -= 1
    
    def record_latency(self, endpoint: str, latency_ms: float):
        """Record endpoint latency"""
        with self._lock:
            key = f"latency:{endpoint}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["total"] += latency_ms
            self.metrics[key]["min"] = min(self.metrics[key]["min"], latency_ms)
            self.metrics[key]["max"] = max(self.metrics[key]["max"], latency_ms)
            self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()
    
    def record_request(self, endpoint: str, status_code: int):
        """Record request"""
        with self._lock:
            key = f"requests:{endpoint}:{status_code}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()
    
    def record_error(self, error_type: str):
        """Record error"""
        with self._lock:
            key = f"errors:{error_type}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()

    def record_timeout(self, endpoint: str, timeout_type: str = "request"):
        """Record a controlled timeout."""
        with self._lock:
            key = f"timeouts:{timeout_type}:{endpoint}"
            self.metrics[key]["count"] += 1
            self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()

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
        }


# Global metrics collector instance
metrics_collector = MetricsCollector()
