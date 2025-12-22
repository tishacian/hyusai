"""Reasoning agent implementation"""
from typing import Dict, Any, AsyncGenerator
from app.agents.base import BaseAgent
from app.services.models import ModelService
from app.core.config import settings
from app.core.settings_manager import get_app_settings

class ReasoningAgent(BaseAgent):
    """Agent for chain-of-thought reasoning"""
    
    def __init__(self):
        super().__init__(
            agent_id="reasoning",
            name="Reasoning Agent",
            agent_type="reasoning"
        )
        self.model_service = ModelService()
        self.initialized = False
    
    async def initialize(self) -> None:
        """Initialize the reasoning agent"""
        if not self.initialized:
            await self.model_service.ollama_client.health_check()
            self.status = "active"
            self.initialized = True
    
    async def process(
        self, 
        request: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process request with reasoning"""
        query = request.get("query", "")
        app_settings = get_app_settings()
        model_name = request.get("agent_preferences", {}).get(
            "model_preferences", {}
        ).get("model", app_settings.get("defaultModel", settings.ollama_default_model))
        
        # Step 1: Analyze query
        reasoning_steps = []
        reasoning_steps.append({
            "step_number": 1,
            "type": "observation",
            "content": f"Analyzing query: {query}",
        })
        
        yield {
            "chunk_type": "reasoning",
            "reasoning_trace": {"steps": reasoning_steps},
            "is_final": False
        }
        
        # Step 2: Generate reasoning prompt
        reasoning_prompt = f"""You are a reasoning assistant. Think step by step about the following question and format your response using Markdown.

Question: {query}

Provide your reasoning process step by step, then give your final answer. Format your response using Markdown:
- Use ## for main sections
- Use ### for reasoning steps
- Use **bold** for key conclusions
- Use - for bullet points
- Use numbered lists for sequential reasoning
- Use code blocks for any code or technical details
- Use > for important insights or conclusions"""
        
        # Step 3: Stream response
        sequence = 0
        full_content = ""
        
        try:
            async for chunk in self.model_service.ollama_client.stream(
                model=model_name,
                prompt=reasoning_prompt
            ):
                sequence += 1
                content = chunk.get("content", "")
                full_content += content
                
                yield {
                    "chunk_type": "text",
                    "content": content,
                    "delta": content,
                    "reasoning_trace": {"steps": reasoning_steps},
                    "sequence": sequence,
                    "is_final": chunk.get("done", False)
                }
                
                if chunk.get("done"):
                    break
        except Exception as e:
            yield {
                "chunk_type": "error",
                "content": f"Error during reasoning: {str(e)}",
                "is_final": True
            }
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        self.status = "inactive"
        self.initialized = False
