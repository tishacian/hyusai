"""Input validation and sanitization"""
import re
from typing import Dict, Any, Optional
from app.core.errors import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class QueryValidator:
    """Validates user queries"""
    
    MAX_QUERY_LENGTH = 10000
    MIN_QUERY_LENGTH = 1
    FORBIDDEN_PATTERNS = [
        r'<script.*?>.*?</script>',  # XSS attempts
        r'javascript:',  # JavaScript injection
        r'on\w+\s*=',  # Event handlers
    ]
    
    def validate(self, query: str) -> str:
        """Validate and sanitize query"""
        if not isinstance(query, str):
            raise ValidationError("Query must be a string")
        
        # Length validation
        if len(query) < self.MIN_QUERY_LENGTH:
            raise ValidationError("Query too short")
        
        if len(query) > self.MAX_QUERY_LENGTH:
            raise ValidationError(f"Query too long (max {self.MAX_QUERY_LENGTH} characters)")
        
        # Pattern validation
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                raise ValidationError("Query contains forbidden patterns")
        
        # Encoding validation
        try:
            query.encode('utf-8')
        except UnicodeEncodeError:
            raise ValidationError("Invalid character encoding")
        
        # Basic sanitization (remove null bytes)
        sanitized = query.replace('\x00', '')
        
        return sanitized.strip()


class ResponseValidator:
    """Validates model responses"""
    
    MAX_RESPONSE_LENGTH = 100000
    MAX_TOKENS = 50000
    
    def validate(self, response: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Validate response"""
        if not isinstance(response, str):
            raise ValidationError("Response must be a string")
        
        # Length validation
        if len(response) > self.MAX_RESPONSE_LENGTH:
            raise ValidationError(f"Response too long (max {self.MAX_RESPONSE_LENGTH} characters)")
        
        # Token count validation
        if metadata:
            token_count = metadata.get("tokens", 0)
            if token_count > self.MAX_TOKENS:
                raise ValidationError(f"Response exceeds token limit (max {self.MAX_TOKENS})")
        
        # Basic quality checks
        if self._is_gibberish(response):
            logger.warning("Response appears to be gibberish")
            # Don't raise error, just log warning
        
        return True
    
    def _is_gibberish(self, text: str) -> bool:
        """Simple heuristic to detect gibberish"""
        if not text:
            return True
        
        # Check character diversity
        unique_chars = len(set(text.lower()))
        total_chars = len(text)
        if total_chars > 0:
            diversity = unique_chars / total_chars
            return diversity < 0.1  # Too repetitive
        
        return False

