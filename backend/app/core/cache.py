"""Caching layer for responses and embeddings"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import hashlib
import json
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheEntry:
    """Cache entry"""
    
    def __init__(self, key: str, value: Any, ttl_seconds: int = 3600):
        self.key = key
        self.value = value
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)
        self.access_count = 0
        self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        """Check if entry is expired"""
        return datetime.utcnow() > self.expires_at
    
    def access(self):
        """Record access"""
        self.access_count += 1
        self.last_accessed = datetime.utcnow()


class SimpleCache:
    """Simple in-memory cache (for production, use Redis)"""
    
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.logger = get_logger(__name__)
    
    def _generate_key(self, *args, **kwargs) -> str:
        """Generate cache key from arguments"""
        key_data = {
            "args": args,
            "kwargs": kwargs
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        entry = self.cache.get(key)
        
        if not entry:
            return None
        
        if entry.is_expired():
            del self.cache[key]
            return None
        
        entry.access()
        return entry.value
    
    def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        """Set value in cache"""
        # Evict expired entries
        self._evict_expired()
        
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
        
        self.cache[key] = CacheEntry(key, value, ttl_seconds)
    
    def delete(self, key: str):
        """Delete from cache"""
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """Clear all cache"""
        self.cache.clear()
    
    def _evict_expired(self):
        """Remove expired entries"""
        expired_keys = [
            key for key, entry in self.cache.items()
            if entry.is_expired()
        ]
        for key in expired_keys:
            del self.cache[key]
    
    def _evict_oldest(self):
        """Evict least recently used entry"""
        if not self.cache:
            return
        
        oldest_key = min(
            self.cache.keys(),
            key=lambda k: self.cache[k].last_accessed
        )
        del self.cache[oldest_key]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        self._evict_expired()
        
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "usage_percent": round((len(self.cache) / self.max_size) * 100, 2)
        }


# Global cache instance
cache = SimpleCache()

