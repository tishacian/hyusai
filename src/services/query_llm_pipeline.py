from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.models.flow_operations import QueryLLMPipelinePayload
from src.customchain import CustomLLMChain as HAHCustomLLMChain
from src.customchain_naive import CustomLLMChain as NaiveCustomLLMChain
from src.customchainmixedhah import CustomLLMChain as CHAHCustomLLMChain
from src.modeltokenizer import load_model_and_tokenizer


class QueryLLMPipelineService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: QueryLLMPipelinePayload) -> TaskResponse:
        if payload.retrieval_strategy == "HAH":
            RaggerChain = HAHCustomLLMChain
        elif payload.retrieval_strategy == "HAHCOMPOSITE":
            RaggerChain = CHAHCustomLLMChain
        elif payload.retrieval_strategy == "NAIVE":
            RaggerChain = NaiveCustomLLMChain
        else:
            raise ValueError(
                f"Unsupported retrieval strategy: {payload.retrieval_strategy}"
            )
        model, tokenizer = load_model_and_tokenizer(payload.llm_full_name)
        chain = RaggerChain(
            tokenizer,
            model,
            payload.llm_full_name,
            payload.knowledge_base_uuid,
            index_type="faiss",
            instruction_lang=payload.system_prompt_language,
        )
        response, context, metrics = chain.ainvoke(payload.prompt)
        return {"status": "success"}
