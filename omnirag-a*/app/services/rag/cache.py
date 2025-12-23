"""Caching layer for RAG operations"""
from typing import Optional, Dict, List
import hashlib
import json
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


class RAGCache:
    """Simple in-memory cache for RAG operations"""
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 1000):
        """
        Initialize cache
        
        Args:
            ttl_seconds: Time to live for cache entries (default: 1 hour)
            max_size: Maximum number of cache entries (default: 1000)
        """
        self.cache: Dict[str, Dict] = {}
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self.access_times: Dict[str, datetime] = {}
    
    def _generate_key(self, query: str, top_k: int, filters: Optional[Dict] = None, use_hybrid: bool = False) -> str:
        """Generate cache key from query parameters"""
        key_data = {
            "query": query,
            "top_k": top_k,
            "filters": filters or {},
            "use_hybrid": use_hybrid,
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()
    
    def get(self, query: str, top_k: int, filters: Optional[Dict] = None, use_hybrid: bool = False) -> Optional[List[Dict]]:
        """Get cached search results"""
        key = self._generate_key(query, top_k, filters, use_hybrid)
        
        if key not in self.cache:
            return None
        
        entry = self.cache[key]
        
        # Check if expired
        if datetime.now() > entry["expires_at"]:
            del self.cache[key]
            if key in self.access_times:
                del self.access_times[key]
            return None
        
        # Update access time
        self.access_times[key] = datetime.now()
        
        logger.debug(f"Cache hit for query: {query[:50]}")
        return entry["results"]
    
    def set(self, query: str, top_k: int, results: List[Dict], filters: Optional[Dict] = None, use_hybrid: bool = False):
        """Cache search results"""
        key = self._generate_key(query, top_k, filters, use_hybrid)
        
        # Evict oldest if cache is full
        if len(self.cache) >= self.max_size and key not in self.cache:
            self._evict_oldest()
        
        expires_at = datetime.now() + timedelta(seconds=self.ttl_seconds)
        
        self.cache[key] = {
            "results": results,
            "expires_at": expires_at,
            "created_at": datetime.now(),
        }
        
        self.access_times[key] = datetime.now()
        logger.debug(f"Cached results for query: {query[:50]}")
    
    def _evict_oldest(self):
        """Evict least recently used entry"""
        if not self.access_times:
            # Fallback: remove first entry
            if self.cache:
                first_key = next(iter(self.cache))
                del self.cache[first_key]
            return
        
        # Find least recently used
        oldest_key = min(self.access_times.items(), key=lambda x: x[1])[0]
        
        if oldest_key in self.cache:
            del self.cache[oldest_key]
        if oldest_key in self.access_times:
            del self.access_times[oldest_key]
    
    def clear(self):
        """Clear all cache entries"""
        self.cache.clear()
        self.access_times.clear()
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        now = datetime.now()
        expired_count = sum(1 for entry in self.cache.values() if now > entry["expires_at"])
        
        return {
            "total_entries": len(self.cache),
            "max_size": self.max_size,
            "expired_entries": expired_count,
            "ttl_seconds": self.ttl_seconds,
        }


# Global cache instance
_global_cache: Optional[RAGCache] = None


def get_cache() -> RAGCache:
    """Get global cache instance"""
    global _global_cache
    if _global_cache is None:
        _global_cache = RAGCache()
    return _global_cache

