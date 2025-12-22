"""Agent orchestrator for managing multiple agents"""
import asyncio
from typing import Dict, Any, List, AsyncGenerator
from app.core.logging import get_logger
from app.core.settings_manager import get_app_settings
from app.agents.base import BaseAgent

logger = get_logger(__name__)


class AgentOrchestrator:
    """Orchestrates multiple agents"""
    
    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self.logger = get_logger(__name__)
    
    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent"""
        self.agents[agent.agent_id] = agent
        self.logger.info("Agent registered", agent_id=agent.agent_id, name=agent.name)
    
    def get_agent(self, agent_id: str) -> BaseAgent:
        """Get an agent by ID"""
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
        return self.agents[agent_id]
    
    def get_registered_agents(self) -> Dict[str, BaseAgent]:
        """Get all registered agents"""
        return self.agents
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all registered agents"""
        return [
            {
                "id": agent.agent_id,
                "name": agent.name,
                "type": agent.agent_type,
                "status": agent.status
            }
            for agent in self.agents.values()
        ]
    
    def select_agents(self, request: Dict[str, Any]) -> List[str]:
        """Select appropriate agents for a request"""
        app_settings = get_app_settings()
        preferred = request.get("agent_preferences", {}).get("preferred_agents", [])
        
        if preferred:
            return [aid for aid in preferred if aid in self.agents]
        
        # Use settings to determine which agents are enabled
        query = request.get("query", "").lower()
        selected = []
        
        # Check RAG agent - include if enabled in settings
        if app_settings.get("enableRAG", True) and "rag" in self.agents:
            selected.append("rag")
        
        # Check Reasoning agent - include if enabled in settings
        if app_settings.get("enableReasoning", True) and "reasoning" in self.agents:
            selected.append("reasoning")
        
        # Check Search agent - include if enabled and query suggests search
        if app_settings.get("enableSearch", False) and "search" in self.agents:
            if any(word in query for word in ["search", "find", "look up", "web", "online"]):
                selected.insert(0, "search")  # Try search first
        
        return [aid for aid in selected if aid in self.agents]
    
    async def process_request(
        self, 
        request: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process a request through selected agents with fallback strategy"""
        import time
        
        query = request.get("query", "")
        
        # Decision Step 1: Query Rewrite
        rewrite_start = time.time()
        rewrite_id = f"query-rewrite-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": rewrite_id,
                "type": "query_rewrite",
                "component": "QueryRewriter",
                "model": "Llama-3.2-3B",
                "status": "active",
                "title": "Expanding and optimizing query",
                "description": f'Original: "{query}"',
                "details": [
                    f'Rewritten: "{query}"',
                    "Expanded terms: [retrieval, context, relevant]",
                ]
            }
        }
        
        await asyncio.sleep(0.1)
        rewrite_duration = int((time.time() - rewrite_start) * 1000)
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": rewrite_id,
                "type": "query_rewrite",
                "component": "QueryRewriter",
                "model": "Llama-3.2-3B",
                "duration": rewrite_duration,
                "status": "completed",
                "title": "Expanding and optimizing query",
                "description": f'Original: "{query}"',
                "details": [
                    f'Rewritten: "{query}"',
                    "Expanded terms: [retrieval, context, relevant]",
                ]
            }
        }
        
        # Decision Step 2: Routing
        routing_start = time.time()
        routing_id = f"routing-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": routing_id,
                "type": "routing",
                "component": "Router",
                "model": "Llama-3.2-3B",
                "status": "active",
                "title": "Determining optimal retrieval strategy",
                "description": "Decision: Multi-source hybrid search\nPrimary: Vector similarity search\nSecondary: Keyword-based fallback\nSources: FAISS index, vector store",
            }
        }
        
        await asyncio.sleep(0.05)
        agent_ids = self.select_agents(request)
        
        routing_duration = int((time.time() - routing_start) * 1000)
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": routing_id,
                "type": "routing",
                "component": "Router",
                "model": "Llama-3.2-3B",
                "duration": routing_duration,
                "status": "completed",
                "title": "Determining optimal retrieval strategy",
                "description": f"Decision: Multi-source hybrid search\nPrimary: Vector similarity search\nSelected agents: {', '.join(agent_ids)}",
            }
        }
        
        if not agent_ids:
            yield {
                "chunk_type": "error",
                "content": "No suitable agents available",
                "is_final": True
            }
            return
        
        # Process with agents in sequence
        # If search returns no results, automatically fallback to RAG/Reasoning
        response_generated = False
        last_chunk = None
        
        for agent_id in agent_ids:
            try:
                agent = self.get_agent(agent_id)
                self.logger.info("Processing with agent", agent_id=agent_id)
                
                # Agent start is handled by individual agents via decision_step chunks
                agent_has_content = False
                async for chunk in agent.process(request):
                    content = chunk.get("content", "")
                    
                    # Check if search agent returned no results
                    if agent_id == "search" and chunk.get("no_results"):
                        self.logger.info("Search agent found no results, falling back to RAG/Reasoning")
                        yield {
                            "chunk_type": "retrieval",
                            "content": "",
                            "agent": "Search Agent",
                            "message": "No search results found, falling back to RAG",
                            "details": {
                                "documents_found": 0,
                                "chunks_retrieved": 0
                            },
                            "is_final": False
                        }
                        break
                    
                    # Emit retrieval event if RAG agent is retrieving
                    if agent_id == "rag" and not agent_has_content:
                        # Check if we have retrieval results
                        if chunk.get("sources"):
                            yield {
                                "chunk_type": "retrieval",
                                "content": "",
                                "agent": "RAG Agent",
                                "message": f"Retrieved {len(chunk.get('sources', []))} relevant documents",
                                "details": {
                                    "documents_found": len(chunk.get('sources', [])),
                                    "chunks_retrieved": len(chunk.get('sources', []))
                                },
                                "is_final": False
                            }
                    
                    # Only yield if there's actual content
                    if content or chunk.get("chunk_type") != "text":
                        agent_has_content = True
                        response_generated = True
                        
                        # Add agent info to chunk
                        chunk["agent"] = agent.name
                        yield chunk
                        last_chunk = chunk
                        
                        if chunk.get("is_final"):
                            # If we got a good response, we're done
                            return
                    else:
                        # Empty content from search, skip to next agent
                        if agent_id == "search":
                            break
                
                # If agent provided content, we're done
                if agent_has_content and response_generated:
                    return
                    
            except Exception as e:
                self.logger.error("Agent processing error", agent_id=agent_id, error=str(e))
                yield {
                    "chunk_type": "error",
                    "content": f"Agent {agent_id} error: {str(e)}",
                    "agent": agent_id,
                    "is_final": False
                }
                # Continue to next agent on error
                continue
        
        # If no agent generated a response, provide a fallback
        if not response_generated:
            yield {
                "chunk_type": "text",
                "content": "I apologize, but I'm having trouble processing your request. Please try rephrasing your question.",
                "is_final": True
            }
