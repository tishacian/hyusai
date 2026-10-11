"""Repro harness for the Andritz chat quality bugs (memory / sources / robustness).

Runs the real orchestrator + OmniRAGAgent against a workspace, bypassing HTTP
auth, so we can replay the demo turns (incl. multi-turn follow-ups) and capture
the assistant text, the emitted sources, and any error chunk.

Usage (inside agentium-backend container):
    python -m scripts.repro_chat_memory --workspace andritz --turns turns.json
or with inline turns:
    python -m scripts.repro_chat_memory --workspace andritz \
        --turn "Quels documents de convoyeur sont indexes pour ARA200 ?" \
        --turn "detaille"
"""
import argparse
import asyncio
import json
import sys

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.agents.orchestrator import AgentOrchestrator
from app.agents.procurement_agent import OmniRAGAgent
from app.services.chat_grounding import resolve_grounding_policy


def _load_workspace(slug: str) -> Workspace:
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.slug == slug).first()
        if not ws:
            raise SystemExit(f"workspace slug not found: {slug}")
        db.expunge(ws)
        return ws
    finally:
        db.close()


async def _run_turn(orchestrator, workspace, query, history, model):
    grounding_policy = resolve_grounding_policy(
        query=query, workspace=workspace, assistant_profile=None,
        requested_mode=None, context_id=None,
    )
    request_dict = {
        "query": query,
        "workspace_slug": workspace.slug,
        "workspace_id": workspace.id,
        "stream": True,
        "include_sources": True,
        "temperature": 0.3,
        "max_tokens": 2000,
        "grounding_policy": grounding_policy,
        "grounding_mode": grounding_policy["mode"],
        "agent_preferences": {"model_preferences": {"model": model, "provider": "openai"}},
    }
    if history:
        request_dict["context"] = {
            "conversation_history": history,
            "memory_type": "long_term",
        }

    text_parts = []
    sources = None
    error = None
    retrieval_phase = None
    chunks_retrieved = None
    try:
        async for chunk in orchestrator.process_request(request_dict):
            ct = chunk.get("chunk_type")
            # Mirror the frontend/chat endpoint: sources can ride along ANY
            # chunk type; a non-empty list is the latest authoritative set.
            if chunk.get("sources"):
                sources = chunk.get("sources")
            if ct == "text":
                text_parts.append(chunk.get("content", ""))
            elif ct == "error":
                error = chunk.get("content")
            elif ct == "retrieval":
                retrieval_phase = chunk.get("phase")
                det = chunk.get("details") or {}
                if det.get("chunks_retrieved") is not None:
                    chunks_retrieved = det.get("chunks_retrieved")
            if chunk.get("is_final"):
                break
    except Exception as exc:  # noqa: BLE001
        import traceback
        error = f"EXCEPTION: {exc}\n{traceback.format_exc()}"

    return {
        "query": query,
        "grounding_mode": grounding_policy["mode"],
        "text": "".join(text_parts),
        "sources_count": len(sources) if sources else 0,
        "sources_titles": [s.get("title") for s in (sources or [])],
        "retrieval_phase": retrieval_phase,
        "chunks_retrieved": chunks_retrieved,
        "error": error,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="andritz")
    ap.add_argument("--turn", action="append", default=[])
    ap.add_argument("--turns", help="path to JSON list of strings")
    ap.add_argument("--model", default="gpt-5")
    args = ap.parse_args()

    turns = list(args.turn)
    if args.turns:
        with open(args.turns) as fh:
            turns.extend(json.load(fh))
    if not turns:
        raise SystemExit("no turns provided")

    workspace = _load_workspace(args.workspace)
    orchestrator = AgentOrchestrator()
    agent = OmniRAGAgent()
    await agent.initialize()
    orchestrator.register_agent(agent)

    history: list[dict] = []
    for query in turns:
        result = await _run_turn(orchestrator, workspace, query, history, args.model)
        print("=" * 80)
        print(f"USER: {query}")
        print(f"  grounding_mode={result['grounding_mode']} "
              f"retrieval_phase={result['retrieval_phase']} "
              f"chunks={result['chunks_retrieved']} "
              f"SOURCES={result['sources_count']} {result['sources_titles']}")
        if result["error"]:
            print(f"  ERROR: {result['error']}")
        print(f"ASSISTANT ({len(result['text'])} chars): {result['text']}")
        sys.stdout.flush()
        # Append to history like the chat endpoint persists turns.
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": result["text"]})


if __name__ == "__main__":
    asyncio.run(main())
