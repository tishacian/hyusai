"""Error recovery mechanisms"""
import asyncio
from typing import Dict, Any, Optional, Callable, Awaitable
from app.core.errors import BaseAppError, ErrorCategory
from app.core.logging import get_logger

logger = get_logger(__name__)


class RecoveryResult:
    """Result of recovery attempt"""
    
    def __init__(self, success: bool, result: Any = None, action: str = "unknown"):
        self.success = success
        self.result = result
        self.action = action


class RecoveryManager:
    """Manages error recovery strategies"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.max_retries = 3
        self.backoff_seconds = [1, 2, 4]
    
    def is_recoverable(self, error: Exception) -> bool:
        """Check if error is recoverable"""
        if isinstance(error, BaseAppError):
            return error.recoverable
        
        # Check error category
        error_type = type(error).__name__
        recoverable_types = [
            "TimeoutError",
            "ConnectionError",
            "NetworkError",
            "ModelUnavailableError"
        ]
        return any(rt in error_type for rt in recoverable_types)
    
    async def attempt_recovery(
        self,
        error: Exception,
        context: Dict[str, Any],
        operation: Optional[Callable[[], Awaitable[Any]]] = None
    ) -> RecoveryResult:
        """Attempt to recover from error"""
        if not self.is_recoverable(error):
            return RecoveryResult(success=False, action="fail")
        
        recovery_strategies = [
            self._retry_with_backoff,
            self._fallback_to_alternative_model,
            self._fallback_to_cached_response,
        ]
        
        for strategy in recovery_strategies:
            try:
                result = await strategy(error, context, operation)
                if result.success:
                    return result
            except Exception as e:
                self.logger.warning("Recovery strategy failed", strategy=strategy.__name__, error=str(e))
                continue
        
        return RecoveryResult(success=False, action="fail")
    
    async def _retry_with_backoff(
        self,
        error: Exception,
        context: Dict[str, Any],
        operation: Optional[Callable[[], Awaitable[Any]]]
    ) -> RecoveryResult:
        """Retry operation with exponential backoff"""
        if not operation:
            return RecoveryResult(success=False)
        
        for attempt in range(self.max_retries):
            try:
                await asyncio.sleep(self.backoff_seconds[attempt])
                result = await operation()
                self.logger.info("Retry successful", attempt=attempt + 1)
                return RecoveryResult(success=True, result=result, action="retry")
            except Exception as e:
                self.logger.warning("Retry failed", attempt=attempt + 1, error=str(e))
                if attempt == self.max_retries - 1:
                    return RecoveryResult(success=False)
        
        return RecoveryResult(success=False)
    
    async def _fallback_to_alternative_model(
        self,
        error: Exception,
        context: Dict[str, Any],
        operation: Optional[Callable[[], Awaitable[Any]]]
    ) -> RecoveryResult:
        """Fallback to alternative model"""
        # This would be implemented by the model router
        # For now, return failure
        return RecoveryResult(success=False)
    
    async def _fallback_to_cached_response(
        self,
        error: Exception,
        context: Dict[str, Any],
        operation: Optional[Callable[[], Awaitable[Any]]]
    ) -> RecoveryResult:
        """Fallback to cached response"""
        # This would check cache for previous response
        # For now, return failure
        return RecoveryResult(success=False)

