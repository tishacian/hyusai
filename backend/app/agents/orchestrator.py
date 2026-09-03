"""Agent orchestrator for managing multiple agents"""
import asyncio
import re
import time
from typing import Dict, Any, List, AsyncGenerator
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.agents.base import BaseAgent

logger = get_logger(__name__)

REWRITE_SYSTEM = """You are a query rewriting assistant for a RAG retrieval system.
Given a user query, output ONLY a rewritten version that is clearer, more specific,
and better suited for semantic search against a knowledge base.
Preserve every domain term, product/project reference, acronym, number, and quoted phrase exactly.
Do not correct spelling when the token could be a business, technical, or product term.
Do not explain anything. Output only the rewritten query."""

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_.-]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "au",
    "aux",
    "avec",
    "can",
    "ce",
    "ces",
    "comment",
    "de",
    "des",
    "do",
    "does",
    "du",
    "en",
    "est",
    "et",
    "for",
    "from",
    "il",
    "in",
    "is",
    "la",
    "le",
    "les",
    "me",
    "mon",
    "nous",
    "numero",
    "numéro",
    "of",
    "on",
    "ou",
    "peux",
    "pour",
    "que",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "qui",
    "retrouver",
    "sur",
    "the",
    "to",
    "tu",
    "un",
    "une",
    "vous",
    "what",
    "which",
}


def _normalise_token(value: str) -> str:
    return str(value or "").lower().replace("’", "'")


def _query_terms_to_preserve(query: str) -> set[str]:
    terms: set[str] = set()
    for raw in _TOKEN_RE.findall(query or ""):
        raw = raw.strip()
        pieces = (raw,) if any(char.isdigit() for char in raw) else re.split(r"[-_]", raw)
        for piece in pieces:
            token = _normalise_token(piece.strip())
            if not token or token in _STOPWORDS:
                continue
            if any(char.isdigit() for char in token) or len(token) >= 4:
                terms.add(token)
    return terms


def _rewrite_preserves_query_terms(original: str, rewritten: str) -> bool:
    original_terms = _query_terms_to_preserve(original)
    if not original_terms:
        return True
    rewritten_terms = {_normalise_token(token) for token in _TOKEN_RE.findall(rewritten or "")}
    return original_terms.issubset(rewritten_terms)


class AgentOrchestrator:
    """Orchestrates multiple agents"""

    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self._rewrite_llm = None
        self.logger = get_logger(__name__)

    _REWRITE_DEFAULT_MODEL = "gpt-4o-mini"

    def _get_rewrite_llm(self, provider: str | None = None):
        from app.core.config import settings
        from app.llm.llm import LLM

        wanted = str(provider or "").strip().lower()
        if not wanted or wanted == str(settings.default_provider or "").lower():
            if self._rewrite_llm is None:
                self._rewrite_llm = LLM(provider=settings.default_provider, api_key=settings.openai_api_key)
            return self._rewrite_llm
        cache = getattr(self, "_rewrite_llm_by_provider", None)
        if cache is None:
            cache = {}
            self._rewrite_llm_by_provider = cache
        if wanted not in cache:
            try:
                cache[wanted] = LLM(
                    provider=wanted,
                    api_key=settings.openai_api_key if wanted in {"openai", "azure"} else None,
                )
            except ValueError:
                return self._get_rewrite_llm(None)
        return cache[wanted]

    def _rewrite_model(self, request: dict[str, Any] | None) -> tuple[str, str | None]:
        """Query rewriting is the platform's cheapest LLM step: tier ``fast``.

        Only a configured fast tier moves it off the historical gpt-4o-mini.
        """
        snapshot = (request or {}).get("model_routing") if isinstance(request, dict) else None
        if not isinstance(snapshot, dict) or not snapshot.get("tiers"):
            return self._REWRITE_DEFAULT_MODEL, None
        try:
            from app.services.model_plane.routing_policy import resolve_model

            choice = resolve_model(snapshot=snapshot, tier_hint="fast")
        except Exception:  # noqa: BLE001 — rewriting must never fail on routing
            return self._REWRITE_DEFAULT_MODEL, None
        if choice.source != "tier":
            return self._REWRITE_DEFAULT_MODEL, None
        return choice.model, choice.provider

    @staticmethod
    def _model_routing_step(
        model_prefs: Dict[str, Any], request: Dict[str, Any] | None
    ) -> Dict[str, Any] | None:
        """Visible ``routing`` step for the classic path (deterministic tier)."""
        source = str(model_prefs.get("source") or "")
        tier = model_prefs.get("tier")
        if not source or not tier:
            return None
        provider = str(model_prefs.get("provider") or "?")
        model = str(model_prefs.get("model") or "?")
        description = {
            "tier": "Niveau choisi dans la table des tiers du workspace",
            "explicit": "Modèle demandé explicitement",
            "preset": "Modèle par défaut du préréglage RAG",
        }.get(source, "Politique de routage modèle")
        return {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": f"model-routing-{id(request) if request is not None else 0}",
                "type": "routing",
                "component": "ModelRouting",
                "model": model,
                "status": "completed",
                "title": f"Modèle {tier} → {provider}:{model}",
                "description": description,
                "metrics": {
                    "model_tier": tier,
                    "provider": provider,
                    "model": model,
                    "source": source,
                },
            },
        }

    async def _rewrite_query(self, query: str, request: dict[str, Any] | None = None) -> str:
        """Rewrite a query with the fast tier (gpt-4o-mini by default) for better retrieval."""
        try:
            rewrite_model, rewrite_provider = self._rewrite_model(request)
            llm = self._get_rewrite_llm(rewrite_provider)
            result = ""
            async for chunk in llm.stream_complete(
                prompt=query,
                model=rewrite_model,
                system_prompt=REWRITE_SYSTEM,
                temperature=0.0,
                max_tokens=200,
            ):
                result += chunk
            rewritten = result.strip().strip('"')
            if len(rewritten) > 10:
                if not _rewrite_preserves_query_terms(query, rewritten):
                    self.logger.info(
                        "Query rewrite rejected because it changed protected user terms",
                        original=query,
                        rewritten=rewritten,
                    )
                    return query
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
        app_settings = get_resolved_settings(
            workspace_id=request.get("workspace_id"),
            capability_id=request.get("capability_id"),
            system_id=request.get("system_id"),
        )
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
        model_prefs = request.get("agent_preferences", {}).get("model_preferences", {})
        model_prefs = model_prefs if isinstance(model_prefs, dict) else {}
        model_name = model_prefs.get("model", "gpt-4o")

        # Decision Step 0: the model routing decision the chat seed already
        # made (tier -> provider:model), shown only when a policy took part.
        routing_step = self._model_routing_step(model_prefs, request)
        if routing_step is not None:
            yield routing_step

        # Decision Step 1: Real Query Rewrite via GPT-4o-mini
        rewrite_start = time.time()
        rewrite_id = f"query-rewrite-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": rewrite_id,
                "type": "query_rewrite",
                "component": "QueryRewriter",
                "model": self._rewrite_model(request)[0],
                "status": "active",
                "title": "Expanding and optimizing query",
                "description": f'Original: "{query[:120]}"',
            }
        }

        rewritten_query = await self._rewrite_query(query, request)
        request["rewritten_query"] = rewritten_query

        rewrite_duration = int((time.time() - rewrite_start) * 1000)
        changed = rewritten_query != query
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": rewrite_id,
                "type": "query_rewrite",
                "component": "QueryRewriter",
                "model": self._rewrite_model(request)[0],
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

        app_settings = get_resolved_settings(
            workspace_id=request.get("workspace_id"),
            capability_id=request.get("capability_id"),
            system_id=request.get("system_id"),
        )
        requested_hybrid = app_settings.get("ragUseHybridSearch", True)
        requested_strategy = "hybrid-capable" if requested_hybrid else "dense-preferred"
        strategy = f"Corpus planner ({requested_strategy} preset)"

        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": routing_id,
                "type": "routing",
                "component": "Router",
                "model": model_name,
                "status": "active",
                "title": "Determining optimal retrieval strategy",
                "description": (
                    f"Strategy: {strategy}\n"
                    f"Sources: Vector store ({app_settings.get('ragCollectionName', 'documents')})\n"
                    f"Top-K: {app_settings.get('ragTopK', 5)}"
                ),
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
                rag_retrieval_reported = False
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
                    
                    if agent_id == "rag" and chunk.get("chunk_type") == "retrieval":
                        rag_retrieval_reported = True

                    # Emit legacy retrieval event if the agent did not already
                    # emit the structured retrieval lifecycle.
                    if agent_id == "rag" and not agent_has_content:
                        # Check if we have retrieval results
                        if chunk.get("sources") and not rag_retrieval_reported:
                            yield {
                                "chunk_type": "retrieval",
                                "phase": "completed",
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
