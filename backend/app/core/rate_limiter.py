"""Rate limiting implementation"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter (for production, use Redis)"""
    
    def __init__(self):
        self.requests: Dict[str, List[datetime]] = {}
        self.limits: Dict[str, Dict[str, int]] = {
            "/api/v1/chat/completion": {"requests": 100, "window": 3600},
            "/api/v1/chat/stream": {"requests": 100, "window": 3600},
            "/api/v1/documents": {"requests": 50, "window": 3600},
        }
        self.logger = get_logger(__name__)
    
    def check_rate_limit(
        self, 
        user_id: str, 
        endpoint: str
    ) -> tuple[bool, dict[str, any]]:
        """Check if request is within rate limit"""
        key = f"{user_id}:{endpoint}"
        limit_config = self.limits.get(endpoint, {"requests": 10, "window": 60})
        
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=limit_config["window"])
        
        # Get requests in current window
        if key not in self.requests:
            self.requests[key] = []
        
        # Remove old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if req_time > window_start
        ]
        
        current_count = len(self.requests[key])
        limit = limit_config["requests"]
        
        if current_count >= limit:
            reset_time = (self.requests[key][0] + timedelta(seconds=limit_config["window"])).timestamp()
            return False, {
                "limit": limit,
                "remaining": 0,
                "reset": int(reset_time),
                "retry_after": int((reset_time - now.timestamp()))
            }
        
        # Add current request
        self.requests[key].append(now)
        
        remaining = limit - current_count - 1
        reset_time = (now + timedelta(seconds=limit_config["window"])).timestamp()
        
        return True, {
            "limit": limit,
            "remaining": remaining,
            "reset": int(reset_time)
        }

