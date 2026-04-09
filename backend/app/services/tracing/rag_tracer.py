"""RAG execution tracing"""
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import uuid


class TraceStepType(Enum):
    """Types of trace steps"""
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_PARSE = "document_parse"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    QUERY_EMBEDDING = "query_embedding"
    VECTOR_SEARCH = "vector_search"
    RERANKING = "reranking"
    CONTEXT_CONSTRUCTION = "context_construction"
    GENERATION = "generation"


@dataclass
class TraceStep:
    """Single trace step"""
    id: str
    step_type: TraceStepType
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    status: str = "active"  # active, completed, error
    metadata: Dict = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def complete(self, metadata: Optional[Dict] = None):
        """Mark step as completed"""
        self.end_time = datetime.now()
        if self.start_time:
            delta = self.end_time - self.start_time
            self.duration_ms = delta.total_seconds() * 1000
        self.status = "completed"
        if metadata:
            self.metadata.update(metadata)
    
    def mark_error(self, error_message: str, metadata: Optional[Dict] = None):
        """Mark step as error"""
        self.end_time = datetime.now()
        if self.start_time:
            delta = self.end_time - self.start_time
            self.duration_ms = delta.total_seconds() * 1000
        self.status = "error"
        self.error = error_message
        if metadata:
            self.metadata.update(metadata)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        result = asdict(self)
        result['step_type'] = self.step_type.value
        result['start_time'] = self.start_time.isoformat()
        if self.end_time:
            result['end_time'] = self.end_time.isoformat()
        return result


@dataclass
class RAGTrace:
    """Complete RAG execution trace"""
    id: str
    operation_type: str  # "ingest", "search", "query"
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    steps: List[TraceStep] = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.steps is None:
            self.steps = []
        if self.metadata is None:
            self.metadata = {}
    
    def add_step(self, step: TraceStep):
        """Add a step to the trace"""
        self.steps.append(step)
    
    def complete(self, metadata: Optional[Dict] = None):
        """Mark trace as completed"""
        self.end_time = datetime.now()
        if self.start_time:
            delta = self.end_time - self.start_time
            self.duration_ms = delta.total_seconds() * 1000
        if metadata:
            self.metadata.update(metadata)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        result = {
            'id': self.id,
            'operation_type': self.operation_type,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_ms': self.duration_ms,
            'steps': [step.to_dict() for step in self.steps],
            'metadata': self.metadata,
        }
        return result


class RAGTracer:
    """Tracer for RAG operations"""
    
    def __init__(self):
        self.traces: Dict[str, RAGTrace] = {}
    
    def start_trace(self, operation_type: str, metadata: Optional[Dict] = None) -> RAGTrace:
        """Start a new trace"""
        trace_id = str(uuid.uuid4())
        trace = RAGTrace(
            id=trace_id,
            operation_type=operation_type,
            start_time=datetime.now(),
            metadata=metadata or {},
        )
        self.traces[trace_id] = trace
        return trace
    
    def get_trace(self, trace_id: str) -> Optional[RAGTrace]:
        """Get trace by ID"""
        return self.traces.get(trace_id)
    
    def add_step(
        self,
        trace_id: str,
        step_type: TraceStepType,
        metadata: Optional[Dict] = None
    ) -> TraceStep:
        """Add a step to a trace"""
        trace = self.traces.get(trace_id)
        if not trace:
            raise ValueError(f"Trace {trace_id} not found")
        
        step = TraceStep(
            id=str(uuid.uuid4()),
            step_type=step_type,
            start_time=datetime.now(),
            metadata=metadata or {},
        )
        trace.add_step(step)
        return step
    
    def get_all_traces(self) -> List[Dict]:
        """Get all traces as dictionaries"""
        return [trace.to_dict() for trace in self.traces.values()]


# Global tracer instance
_global_tracer = RAGTracer()


def get_tracer() -> RAGTracer:
    """Get global tracer instance"""
    return _global_tracer

