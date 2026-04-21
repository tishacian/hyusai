"""Chat/completion endpoints"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.core.auth import get_current_workspace
from app.core.logging import get_logger
from app.core.validation import QueryValidator, ResponseValidator
from app.core.errors import ValidationError
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.user import Message
from app.models.workspace import Workspace
from app.api.v1.endpoints.agents import get_orchestrator
from datetime import datetime
import uuid

logger = get_logger(__name__)
router = APIRouter()
query_validator = QueryValidator()
response_validator = ResponseValidator()


class ChatRequest(BaseModel):
    """Chat completion request"""
    query: str
    session_id: Optional[str] = None
    agent_preferences: Optional[Dict[str, Any]] = None
    stream: bool = True
    include_reasoning: bool = True
    include_sources: bool = True
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.3
    top_k: Optional[int] = None
    similarity_threshold: Optional[float] = None
    system_prompt: Optional[str] = None
    # RAG mode: auto | naive | hybrid | hah | chah — see docs/rag-rd-papai-mapping.md
    rag_pipeline_mode: Optional[str] = None
    # Per-query retrieval override (alias of rag_pipeline_mode used by the
    # cockpit chip selector — takes precedence over workspace settings).
    rag_mode_override: Optional[str] = None
    # Reasoning template (factual | analytical | comparative | causal |
    # hypothetical | trivial | auto). When unset or "auto" the orchestrator
    # runs the mode_selector heuristic.
    prompt_type: Optional[str] = None


@router.post("/completion")
async def chat_completion(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    """Non-streaming chat completion (scoped to current workspace)."""
    try:
        # Validate query
        try:
            validated_query = query_validator.validate(request.query)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        orchestrator = get_orchestrator()
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        # Load resolved preset config for defaults (workspace-scoped).
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        
        request_dict = request.model_dump()
        request_dict["query"] = validated_query
        request_dict["workspace_slug"] = workspace.slug
        request_dict["workspace_id"] = workspace.id

        # If the cockpit sent a per-query override, promote it onto the
        # legacy pipeline-mode key so downstream code picks it up without
        # changing its signature.
        if request.rag_mode_override:
            request_dict["rag_pipeline_mode"] = request.rag_mode_override

        # Apply settings defaults if not provided
        if not request_dict.get("agent_preferences"):
            request_dict["agent_preferences"] = {}
        if not request_dict["agent_preferences"].get("preferred_agents"):
            request_dict["agent_preferences"]["preferred_agents"] = app_settings.get("preferredAgents", [])
        if not request_dict["agent_preferences"].get("model_preferences"):
            request_dict["agent_preferences"]["model_preferences"] = {}
        if not request_dict["agent_preferences"]["model_preferences"].get("model"):
            request_dict["agent_preferences"]["model_preferences"]["model"] = app_settings.get("defaultModel", "deepseek-r1:14b")
        if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
            request_dict["agent_preferences"]["model_preferences"]["provider"] = app_settings.get("defaultProvider", "ollama")
        
        # Apply default temperature and max_tokens from settings
        if request.max_tokens is None:
            request_dict["max_tokens"] = app_settings.get("maxTokens", 2000)
        if request.temperature is None:
            request_dict["temperature"] = app_settings.get("temperature", 0.7)
        chunks = []
        decision_steps = []  # Collect decision pipeline steps
        import time
        pipeline_start_time = None
        pipeline_end_time = None
        
        async for chunk in orchestrator.process_request(request_dict):
            chunks.append(chunk)
            
            # Collect decision pipeline steps
            if chunk.get("chunk_type") == "decision_step" and chunk.get("decision_step"):
                decision_step = chunk.get("decision_step")
                existing_index = next(
                    (i for i, ds in enumerate(decision_steps) if ds.get("id") == decision_step.get("id")),
                    None
                )
                if existing_index is not None:
                    decision_steps[existing_index] = decision_step
                else:
                    decision_steps.append(decision_step)
                
                if pipeline_start_time is None:
                    pipeline_start_time = time.time()
            
            if chunk.get("is_final"):
                break
        
        # Calculate pipeline total time
        if pipeline_start_time:
            pipeline_end_time = time.time()
            pipeline_total_time = int((pipeline_end_time - pipeline_start_time) * 1000)
        else:
            pipeline_total_time = None
        
        # Combine chunks
        content = "".join([c.get("content", "") for c in chunks if c.get("chunk_type") == "text"])
        
        # Validate response
        try:
            response_validator.validate(content)
        except ValidationError as e:
            logger.warning("Response validation warning", error=str(e))
            # Don't fail, just log warning
        
        # Save messages to database if session_id provided
        if request.session_id:
            # Save user message
            user_message = Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="user",
                content=request.query,
                meta_data={}
            )
            db.add(user_message)
            
            # Build meta_data with decision steps
            meta_data = {
                "reasoning_trace": chunks[0].get("reasoning_trace") if chunks else None,
                "sources": chunks[0].get("sources") if chunks else None
            }
            
            # Add decision steps if any were collected
            if decision_steps:
                meta_data["decision_steps"] = decision_steps
                if pipeline_total_time is not None:
                    meta_data["decision_pipeline_total_time"] = pipeline_total_time
            
            # Save assistant message
            assistant_message = Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=content,
                meta_data=meta_data
            )
            db.add(assistant_message)
            db.commit()
        
        return {
            "id": chunks[0].get("id") if chunks else None,
            "content": content,
            "reasoning_trace": chunks[0].get("reasoning_trace") if chunks else None,
            "sources": chunks[0].get("sources") if chunks else None,
            "status": "completed"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat completion error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    """Streaming chat completion (scoped to current workspace)."""
    from fastapi.responses import StreamingResponse
    import json

    async def generate():
        try:
            orchestrator = get_orchestrator()
            if not orchestrator:
                yield f"data: {json.dumps({'chunk_type': 'error', 'content': 'Orchestrator not initialized', 'is_final': True})}\n\n"
                return

            app_settings = get_resolved_settings(workspace_id=workspace.id)

            request_dict = request.model_dump()
            request_dict["workspace_slug"] = workspace.slug
            request_dict["workspace_id"] = workspace.id
            if request.rag_mode_override:
                request_dict["rag_pipeline_mode"] = request.rag_mode_override
            
            # Apply settings defaults if not provided
            if not request_dict.get("agent_preferences"):
                request_dict["agent_preferences"] = {}
            if not request_dict["agent_preferences"].get("preferred_agents"):
                request_dict["agent_preferences"]["preferred_agents"] = app_settings.get("preferredAgents", [])
            if not request_dict["agent_preferences"].get("model_preferences"):
                request_dict["agent_preferences"]["model_preferences"] = {}
            if not request_dict["agent_preferences"]["model_preferences"].get("model"):
                request_dict["agent_preferences"]["model_preferences"]["model"] = app_settings.get("defaultModel", "deepseek-r1:14b")
            if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
                request_dict["agent_preferences"]["model_preferences"]["provider"] = app_settings.get("defaultProvider", "ollama")
            
            full_content = []
            all_chunks = []
            reasoning_trace = None
            sources = None
            decision_steps = []  # Collect all decision pipeline steps
            pipeline_start_time = None
            pipeline_end_time = None
            
            # Load conversation history for context (long-term memory)
            conversation_history = []
            if request.session_id:
                # Get previous messages from this session for context
                previous_messages = db.query(Message).filter(
                    Message.session_id == request.session_id
                ).order_by(Message.timestamp.asc()).all()
                
                # Build conversation history (last 20 messages for context)
                for msg in previous_messages[-20:]:
                    conversation_history.append({
                        "role": msg.role,
                        "content": msg.content
                    })
                
                # Save user message
                user_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="user",
                    content=request.query,
                    meta_data={}
                )
                db.add(user_message)
                
                # Update session last_activity
                from app.models.user import Session as SessionModel
                session = db.query(SessionModel).filter(SessionModel.id == request.session_id).first()
                if session:
                    session.last_activity = datetime.utcnow()
                
                db.commit()
            
            # Add conversation history to request for context
            if conversation_history:
                if not request_dict.get("context"):
                    request_dict["context"] = {}
                request_dict["context"]["conversation_history"] = conversation_history
                request_dict["context"]["memory_type"] = "long_term"  # Default to long-term memory
            
            # Add RAG settings if provided
            if request.top_k is not None:
                request_dict["top_k"] = request.top_k
            if request.similarity_threshold is not None:
                request_dict["similarity_threshold"] = request.similarity_threshold
            
            async for chunk in orchestrator.process_request(request_dict):
                all_chunks.append(chunk)
                if chunk.get("chunk_type") == "text":
                    full_content.append(chunk.get("content", ""))
                
                # Collect metadata from chunks as we go
                if chunk.get("reasoning_trace"):
                    reasoning_trace = chunk.get("reasoning_trace")
                if chunk.get("sources"):
                    sources = chunk.get("sources")
                
                # Collect decision pipeline steps
                if chunk.get("chunk_type") == "decision_step" and chunk.get("decision_step"):
                    decision_step = chunk.get("decision_step")
                    # Check if this step already exists (update) or is new (add)
                    existing_index = next(
                        (i for i, ds in enumerate(decision_steps) if ds.get("id") == decision_step.get("id")),
                        None
                    )
                    if existing_index is not None:
                        # Update existing step
                        decision_steps[existing_index] = decision_step
                    else:
                        # Add new step
                        decision_steps.append(decision_step)
                    
                    # Track pipeline timing
                    if pipeline_start_time is None:
                        import time
                        pipeline_start_time = time.time()
                
                yield f"data: {json.dumps(chunk)}\n\n"
            
            # Calculate total pipeline time
            if pipeline_start_time:
                import time
                pipeline_end_time = time.time()
                pipeline_total_time = int((pipeline_end_time - pipeline_start_time) * 1000)
            else:
                pipeline_total_time = None
            
            # Save assistant message after streaming completes
            if request.session_id and full_content:
                # Build meta_data with decision steps
                meta_data = {
                    "reasoning_trace": reasoning_trace,
                    "sources": sources
                }
                
                # Add decision steps if any were collected
                if decision_steps:
                    meta_data["decision_steps"] = decision_steps
                    if pipeline_total_time is not None:
                        meta_data["decision_pipeline_total_time"] = pipeline_total_time
                
                assistant_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="assistant",
                    content="".join(full_content),
                    meta_data=meta_data
                )
                db.add(assistant_message)
                
                # Update session last_activity
                from app.models.user import Session as SessionModel
                session = db.query(SessionModel).filter(SessionModel.id == request.session_id).first()
                if session:
                    session.last_activity = datetime.utcnow()
                
                db.commit()
            
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Streaming error", error=str(e))
            yield f"data: {json.dumps({'chunk_type': 'error', 'content': str(e), 'is_final': True})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

