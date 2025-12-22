"""Monitoring and metrics collection"""
from typing import Dict, Any, Optional
from datetime import datetime
from collections import defaultdict
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
        self.logger = get_logger(__name__)
    
    def record_latency(self, endpoint: str, latency_ms: float):
        """Record endpoint latency"""
        key = f"latency:{endpoint}"
        self.metrics[key]["count"] += 1
        self.metrics[key]["total"] += latency_ms
        self.metrics[key]["min"] = min(self.metrics[key]["min"], latency_ms)
        self.metrics[key]["max"] = max(self.metrics[key]["max"], latency_ms)
        self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()
    
    def record_request(self, endpoint: str, status_code: int):
        """Record request"""
        key = f"requests:{endpoint}:{status_code}"
        self.metrics[key]["count"] += 1
        self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()
    
    def record_error(self, error_type: str):
        """Record error"""
        key = f"errors:{error_type}"
        self.metrics[key]["count"] += 1
        self.metrics[key]["last_updated"] = datetime.utcnow().isoformat()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics"""
        formatted_metrics = {}
        
        for key, value in self.metrics.items():
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
        
        return formatted_metrics
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        total_requests = sum(
            v["count"] for k, v in self.metrics.items()
            if k.startswith("requests:")
        )
        
        total_errors = sum(
            v["count"] for k, v in self.metrics.items()
            if k.startswith("errors:")
        )
        
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_percent": round(error_rate, 2),
            "metrics_count": len(self.metrics)
        }


# Global metrics collector instance
metrics_collector = MetricsCollector()

