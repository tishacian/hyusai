"""Task execution engine for autonomous agent missions"""
import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import AsyncGenerator

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PLAN_PROMPT = """You are a task planner for an AI orchestration platform.
Given a mission description, decompose it into 3-7 concrete executable steps.
Each step should have: a short title, a description of what to do, and a type
(one of: rag_query, analysis, synthesis, search, document_scan, aggregation).

Return ONLY valid JSON array, no markdown:
[{"title": "...", "description": "...", "type": "..."}]

Mission: {mission}"""

STEP_PROMPT = """You are executing step {step_num} of {total_steps} in an autonomous mission.

Mission: {mission}
Step: {step_title}
Step description: {step_description}

Previous steps results:
{previous_results}

Execute this step thoroughly. Provide a detailed, actionable result.
If this is a synthesis/aggregation step, compile all previous findings into a structured report."""


class TaskEngine:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from app.llm.llm import LLM
            self._llm = LLM(provider=settings.default_provider, api_key=settings.openai_api_key)
        return self._llm

    async def plan_mission(self, description: str) -> list[dict]:
        llm = self._get_llm()
        prompt = PLAN_PROMPT.format(mission=description)
        result = await llm.complete(prompt=prompt, model="gpt-4o-mini", temperature=0.3, max_tokens=1000)
        try:
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            steps = json.loads(text)
            if isinstance(steps, list):
                return steps
        except Exception as e:
            logger.error(f"Failed to parse plan: {e}")
        return [
            {"title": "Analyze request", "description": "Understand the mission scope", "type": "analysis"},
            {"title": "Research", "description": "Gather relevant information", "type": "rag_query"},
            {"title": "Synthesize", "description": "Compile findings into a report", "type": "synthesis"},
        ]

    async def execute_task(self, task_id: str, description: str, agent_id: str = None) -> AsyncGenerator[dict, None]:
        start_time = time.time()

        yield {"type": "task_status", "task_id": task_id, "status": "planning", "progress": 0}

        steps = await self.plan_mission(description)
        step_records = []
        for i, s in enumerate(steps):
            step_records.append({
                "id": str(uuid.uuid4())[:8],
                "num": i + 1,
                "title": s.get("title", f"Step {i+1}"),
                "description": s.get("description", ""),
                "step_type": s.get("type", "analysis"),
                "status": "pending",
                "result": None,
                "duration_ms": None,
            })

        yield {
            "type": "task_plan",
            "task_id": task_id,
            "status": "running",
            "steps": step_records,
            "progress": 5,
        }

        llm = self._get_llm()
        previous_results = ""

        for i, step in enumerate(step_records):
            step_start = time.time()
            step["status"] = "running"

            yield {
                "type": "task_step",
                "task_id": task_id,
                "step": step,
                "progress": int(5 + (i / len(step_records)) * 85),
            }

            prompt = STEP_PROMPT.format(
                step_num=i + 1,
                total_steps=len(step_records),
                mission=description,
                step_title=step["title"],
                step_description=step["description"],
                previous_results=previous_results or "(first step)",
            )

            try:
                result = await llm.complete(
                    prompt=prompt,
                    model="gpt-4o-mini" if step["step_type"] != "synthesis" else "gpt-4o",
                    temperature=0.4,
                    max_tokens=2000,
                )
                step["result"] = result
                step["status"] = "completed"
            except Exception as e:
                logger.error(f"Step {i+1} failed: {e}")
                step["result"] = f"Error: {str(e)}"
                step["status"] = "failed"

            step["duration_ms"] = round((time.time() - step_start) * 1000)
            previous_results += f"\n\n### Step {i+1}: {step['title']}\n{step.get('result', '')}"

            yield {
                "type": "task_step_complete",
                "task_id": task_id,
                "step": step,
                "progress": int(5 + ((i + 1) / len(step_records)) * 85),
            }

        total_ms = round((time.time() - start_time) * 1000)

        final_report = step_records[-1].get("result", "") if step_records else ""
        artifacts = {
            "report": final_report,
            "steps_summary": [{"title": s["title"], "status": s["status"]} for s in step_records],
            "total_steps": len(step_records),
            "completed_steps": sum(1 for s in step_records if s["status"] == "completed"),
        }

        yield {
            "type": "task_complete",
            "task_id": task_id,
            "status": "completed",
            "steps": step_records,
            "artifacts": artifacts,
            "progress": 100,
            "total_duration_ms": total_ms,
        }


_engine = None

def get_task_engine() -> TaskEngine:
    global _engine
    if _engine is None:
        _engine = TaskEngine()
    return _engine
