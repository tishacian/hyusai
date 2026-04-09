"""Agent orchestrator for managing multiple agents"""
import asyncio
import time
from typing import Dict, Any, List, AsyncGenerator
from app.core.logging import get_logger
from app.core.settings_manager import get_app_settings
from app.agents.base import BaseAgent

logger = get_logger(__name__)

REWRITE_SYSTEM = """You are a query rewriting assistant for a RAG retrieval system.
Given a user query, output ONLY a rewritten version that is clearer, more specific,
and better suited for semantic search against a knowledge base.
Do not explain anything. Output only the rewritten query."""


class AgentOrchestrator:
    """Orchestrates multiple agents"""

    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self._rewrite_llm = None
        self.logger = get_logger(__name__)

    def _get_rewrite_llm(self):
        if self._rewrite_llm is None:
            from app.core.config import settings
            from app.llm.llm import LLM
            self._rewrite_llm = LLM(provider=settings.default_provider, api_key=settings.openai_api_key)
        return self._rewrite_llm

    async def _rewrite_query(self, query: str) -> str:
        """Rewrite a query using GPT-4o-mini for better retrieval."""
        try:
            llm = self._get_rewrite_llm()
            result = ""
            async for chunk in llm.stream_complete(
                prompt=query,
                model="gpt-4o-mini",
                system_prompt=REWRITE_SYSTEM,
                temperature=0.0,
                max_tokens=200,
            ):
                result += chunk
            rewritten = result.strip().strip('"')
            if len(rewritten) > 10:
                return rewritten
            return query
        except Exception as e:
            self.logger.warning("Query rewriting failed, using original", error=str(e))
            return query
    
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

        query = request.get("query", "").lower()
        selected = []

        # Domain-specific agents first (procurement, etc.)
        for aid, agent in self.agents.items():
            if agent.agent_type not in ("rag", "reasoning", "search"):
                selected.append(aid)

        # Check RAG agent - include if enabled in settings
        if app_settings.get("enableRAG", True) and "rag" in self.agents:
            selected.append("rag")

        # Check Reasoning agent - include if enabled in settings
        if app_settings.get("enableReasoning", True) and "reasoning" in self.agents:
            selected.append("reasoning")

        # Check Search agent - include if enabled and query suggests search
        if app_settings.get("enableSearch", False) and "search" in self.agents:
            if any(word in query for word in ["search", "find", "look up", "web", "online"]):
                selected.insert(0, "search")

        # Deduplicate while preserving order
        seen = set()
        return [aid for aid in selected if aid in self.agents and not (aid in seen or seen.add(aid))]
    
    async def process_request(
        self,
        request: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process a request through selected agents with fallback strategy"""

        query = request.get("query", "")
        model_name = (
            request.get("agent_preferences", {})
            .get("model_preferences", {})
            .get("model", "gpt-4o")
        )

        # Decision Step 1: Real Query Rewrite via GPT-4o-mini
        rewrite_start = time.time()
        rewrite_id = f"query-rewrite-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": rewrite_id,
                "type": "query_rewrite",
                "component": "QueryRewriter",
                "model": "gpt-4o-mini",
                "status": "active",
                "title": "Expanding and optimizing query",
                "description": f'Original: "{query[:120]}"',
            }
        }

        rewritten_query = await self._rewrite_query(query)
        request["rewritten_query"] = rewritten_query

        rewrite_duration = int((time.time() - rewrite_start) * 1000)
        changed = rewritten_query != query
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": rewrite_id,
                "type": "query_rewrite",
                "component": "QueryRewriter",
                "model": "gpt-4o-mini",
                "duration": rewrite_duration,
                "status": "completed",
                "title": "Query optimized" if changed else "Query kept as-is",
                "description": f'Original: "{query[:120]}"',
                "details": [
                    f'Rewritten: "{rewritten_query[:120]}"',
                ] if changed else [
                    "Query is already well-formed for retrieval",
                ],
            }
        }

        # Decision Step 2: Routing
        routing_start = time.time()
        routing_id = f"routing-{id(query)}"

        app_settings = get_app_settings()
        hybrid = app_settings.get("ragUseHybridSearch", True)
        strategy = "Hybrid (vector + BM25)" if hybrid else "Vector similarity"

        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": routing_id,
                "type": "routing",
                "component": "Router",
                "model": model_name,
                "status": "active",
                "title": "Determining optimal retrieval strategy",
                "description": f"Strategy: {strategy}\nSources: FAISS index ({app_settings.get('ragCollectionName', 'documents')})\nTop-K: {app_settings.get('ragTopK', 5)}",
            }
        }

        agent_ids = self.select_agents(request)

        routing_duration = int((time.time() - routing_start) * 1000)
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": routing_id,
                "type": "routing",
                "component": "Router",
                "model": model_name,
                "duration": routing_duration,
                "status": "completed",
                "title": "Retrieval strategy determined",
                "description": f"Strategy: {strategy}\nSelected agents: {', '.join(agent_ids)}",
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
