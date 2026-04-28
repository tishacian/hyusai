import asyncio

from connections.celery.app import app
from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.models.flow_operations import IngestDocumentsPayload
from connections.models.flow_operations.create_vector_store.payload import (
    IndexCollectionPayload,
)
from connections.models.flow_operations.query_llm_pipeline.payload import QueryPayload


@app.task(name="ingest_documents", bind=True)
def ingest_documents(self: CustomTask, payload: dict, kb_uuid: str) -> TaskResponse:
    from src.services.ingest_documents import IngestDocumentsService

    validated_payload = IngestDocumentsPayload.model_validate(payload)
    IngestDocumentsService(celery_task=self).call(validated_payload, kb_uuid)
    return {"status": "success"}


@app.task(name="create_vector_store", bind=True)
def create_vector_store(self: CustomTask, payload: dict) -> TaskResponse:
    from src.services.create_vector_store import CreateVectorStoreService

    validated_payload = IndexCollectionPayload.model_validate(payload)
    CreateVectorStoreService(celery_task=self).call(validated_payload)
    return {"status": "success"}


@app.task(name="query_llm_pipeline", bind=True)
def query_llm_pipeline(self: CustomTask, payload: dict) -> TaskResponse:
    from src.services.query_llm_pipeline import RAGOrchestrationService

    validated_payload = QueryPayload.model_validate(payload)
    return RAGOrchestrationService().call(validated_payload)


@app.task(name="retrieve_rag_context", bind=True)
def retrieve_rag_context(self: CustomTask, payload: dict) -> dict:
    """Pre-LLM retrieval using the appropriate CustomChain.

    Runs the full retrieval pipeline (encoding, vector search, BM25, context assembly)
    without calling generate_text. Returns data needed for the FastAPI SSE endpoint to
    stream the OpenAI completion.

    Returns
    -------
    dict
        {"combined_context": str, "system_prompt": str, "contexts": list[str]}
    """
    from src.customchain import CustomLLMChain as HAHCustomLLMChain
    from src.customchain_naive import CustomLLMChain as NaiveCustomLLMChain
    from src.customchainmixedhah import CustomLLMChain as CHAHCustomLLMChain
    from src.globalvariables import PipelineType

    validated = QueryPayload.model_validate(payload)
    _strategy_map = {
        "HAHCOMPOSITE": PipelineType.HAHCOMPOSITE,
        "HAH": PipelineType.HAH,
        "NAIVE": PipelineType.NAIVE,
    }
    pipeline_type = _strategy_map[validated.retrieval.strategy]

    chain_class = {
        PipelineType.HAHCOMPOSITE: CHAHCustomLLMChain,
        PipelineType.HAH: HAHCustomLLMChain,
        PipelineType.NAIVE: NaiveCustomLLMChain,
    }[pipeline_type]

    chain = chain_class(
        validated.generation.model_name,
        str(validated.collection_uuid),
        instruction_lang=validated.generation.system_prompt_language,
    )
    return asyncio.run(chain.retrieve_context_async(validated.user_prompt))
