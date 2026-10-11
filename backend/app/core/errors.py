"""Custom error classes and error handling"""
from typing import Optional, Dict, Any
from enum import Enum


class ErrorCategory(Enum):
    """Error categories"""
    VALIDATION = "validation"
    MODEL_UNAVAILABLE = "model_unavailable"
    TIMEOUT = "timeout"
    NETWORK = "network"
    AGENT_ERROR = "agent_error"
    DATABASE_ERROR = "database_error"
    VECTOR_STORE_ERROR = "vector_store_error"
    UNKNOWN = "unknown"


class BaseAppError(Exception):
    """Base application error"""
    
    def __init__(
        self, 
        message: str, 
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False
    ):
        self.message = message
        self.category = category
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)


class ValidationError(BaseAppError):
    """Validation error"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message, 
            category=ErrorCategory.VALIDATION,
            details=details,
            recoverable=False
        )


class ModelUnavailableError(BaseAppError):
    """Model unavailable error"""
    
    def __init__(self, message: str, provider: str, details: Optional[Dict[str, Any]] = None):
        merged_details = details.copy() if details else {}
        merged_details["provider"] = provider
        super().__init__(
            message,
            category=ErrorCategory.MODEL_UNAVAILABLE,
            details=merged_details,
            recoverable=True
        )


class AgentError(BaseAppError):
    """Agent execution error"""
    
    def __init__(self, message: str, agent_id: str, details: Optional[Dict[str, Any]] = None):
        merged_details = details.copy() if details else {}
        merged_details["agent_id"] = agent_id
        super().__init__(
            message,
            category=ErrorCategory.AGENT_ERROR,
            details=merged_details,
            recoverable=True
        )


class TimeoutError(BaseAppError):
    """Timeout error"""
    
    def __init__(self, message: str, timeout_seconds: float, details: Optional[Dict[str, Any]] = None):
        merged_details = details.copy() if details else {}
        merged_details["timeout_seconds"] = timeout_seconds
        super().__init__(
            message,
            category=ErrorCategory.TIMEOUT,
            details=merged_details,
            recoverable=True
        )


class NetworkError(BaseAppError):
    """Network error"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            category=ErrorCategory.NETWORK,
            details=details,
            recoverable=True
        )


class DatabaseError(BaseAppError):
    """Database error"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            category=ErrorCategory.DATABASE_ERROR,
            details=details,
            recoverable=True
        )


class VectorStoreError(BaseAppError):
    """Vector store error"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            category=ErrorCategory.VECTOR_STORE_ERROR,
            details=details,
            recoverable=True
        )

