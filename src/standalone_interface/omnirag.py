import json
import logging
import time
import uuid
from datetime import datetime as _dt
from io import BytesIO
from typing import Iterator
from uuid import UUID

import httpx
import pandas as pd
import streamlit as st
from pydantic import ValidationError
from streamlit.runtime.uploaded_file_manager import UploadedFile

from configurations import FrontendConfig
from connections.models.flow_operations.create_vector_store.components.chunking_params import (
    FixedChunkingParams,
    HierarchicalChunkingParams,
    RecursiveCharacterChunkingParams,
    SemanticChunkingParams,
    SentenceBoundaryChunkingParams,
    TokenBasedChunkingParams,
)
from connections.models.flow_operations.create_vector_store.components.embedding_params import (
    EmbeddingConfig,
)
from connections.models.flow_operations.create_vector_store.payload import (
    IndexCollectionPayload,
)
from connections.models.flow_operations.ingest_documents import (
    IngestDocumentsPayload,
)
from connections.models.flow_operations.ingest_documents.response import (
    IngestDocumentsResponse,
)
from src.standalone_interface.api_client import STREAM_TIMEOUT, get_client
from src.standalone_interface.assets import (
    AI_AVATAR,
    AI_AVATAR_B64,
    HUMAN_AVATAR,
    HUMAN_AVATAR_B64,
    omnirag_header,
)
from src.standalone_interface.components.auth import auth_component
from src.standalone_interface.style import apply_omnirag_style
from src.standalone_interface.utils import humanize_datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_frontend = FrontendConfig.get()
_API_URL: str = _frontend.api.url
_FORCED_VDB: str = _frontend.ui.forced_collection
_HIDE_RAG_PARAMS: bool = _frontend.ui.hide_rag_params
_PAGE_TITLE: str = _frontend.ui.page_title
_PAGE_ICON: str = _frontend.ui.page_icon

# ---------------------------------------------------------------------------
# UI constants — hardcoded, no server-side imports needed
# ---------------------------------------------------------------------------
AVAILABLE_MODELS = ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]
DEFAULT_MODEL = "gpt-4o"
PIPELINE_TYPES = ["Contextual (recommended)", "Hybrid", "Basic"]
DEFAULT_PIPELINE = "Contextual (recommended)"
_PIPELINE_TO_STRATEGY = {
    "Contextual (recommended)": "HAHCOMPOSITE",
    "Hybrid": "HAH",
    "Basic": "NAIVE",
}
CHUNKING_METHODS = [
    "recursive_character",
    "fixed",
    "semantic",
    "sentences",
    "paragraphs",
]
_CHUNKING_DISPLAY = {
    "recursive_character": "Auto-split (recommended)",
    "fixed": "Fixed size",
    "semantic": "By meaning",
    "sentences": "By sentences",
    "paragraphs": "By paragraphs",
}
DEFAULT_CHUNKING = "recursive_character"
SYSTEM_PROMPT_LANGS = ["EN", "FR"]
DEFAULT_LANG = "EN"
ACCEPTED_EXTENSIONS = ["pdf", "txt", "csv", "docx", "md", "html"]
DUMMY_METRICS = {
    "fluency": 0.0,
    "coherence": 0.0,
    "relevance": 0.0,
    "factuality": 0.0,
    "correctness": 0.0,
    "hhem": 0.0,
    "Advance_HHEM": 0.0,
    "latency": 0.0,
}

logger = logging.getLogger(__name__)

_CHUNKING_PARAM_BUILDERS = {
    "recursive_character": lambda: RecursiveCharacterChunkingParams(
        method="recursive_character"
    ),
    "fixed": lambda: FixedChunkingParams(method="fixed"),
    "semantic": lambda: SemanticChunkingParams(method="semantic"),
    "sentences": lambda: SentenceBoundaryChunkingParams(method="sentence_boundary"),
    "paragraphs": lambda: HierarchicalChunkingParams(method="hierarchical"),
    "token_based": lambda: TokenBasedChunkingParams(method="token_based"),
}
_KB_STATUS_EMOJI = {"ingesting": "⏳", "embedding": "🔄", "error": "✗", "created": "⏳"}


def _build_index_payload(collection_uuid: str, chunking_method: str) -> dict:
    builder = _CHUNKING_PARAM_BUILDERS.get(
        chunking_method, _CHUNKING_PARAM_BUILDERS["recursive_character"]
    )
    payload = IndexCollectionPayload(
        collection_uuid=collection_uuid,
        chunking=builder(),
        embedding=EmbeddingConfig(),
    )
    return payload.model_dump(mode="json")


def save_button_action(
    new_vs_name: str,
    uploaded_files: list[UploadedFile],
    chunking_method: str,
    existing_vector_store: UUID | None,
    model_name: str,
):
    if new_vs_name == "":
        st.error("Please enter a name for the new knowledge base.")
        st.stop()
    if not uploaded_files:
        st.error("Please upload at least one file before proceeding.")
        st.stop()
    # upload files via the files API
    input_bucket_uuid = uuid.uuid4()
    bucket_path = f"buckets/{input_bucket_uuid}"
    files = [
        ("files", (f.name, f.getvalue(), f.type or "application/octet-stream"))
        for f in uploaded_files
    ]
    try:
        with get_client() as client:
            resp = client.post(f"/files/{bucket_path}", files=files)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"File upload failed: {e}")
        st.error("Failed to upload files. Please try again.")
        st.stop()
    # send to ingestion endpoint
    ingest_docs_payload = IngestDocumentsPayload(
        input_documents_bucket=input_bucket_uuid,
        collection_name=new_vs_name,
        created_by=st.session_state.get("username", "guest"),
    )
    try:
        with get_client() as client:
            response = client.post(
                "/flow_operations/ingest_documents",
                json=ingest_docs_payload.model_dump(mode="json"),
            )
            response.raise_for_status()
        ingest_docs_validated_response = IngestDocumentsResponse(**response.json())
    except httpx.HTTPError as e:
        logger.error(
            f"Document ingestion request failed: {e}. "
            f"Payload: {ingest_docs_payload.model_dump(mode='json')}",
            exc_info=True,
        )
        st.error(
            "Failed to send document ingestion request. "
            "Please check your connection or service status."
        )
        st.stop()
    except ValidationError as e:
        logger.error(
            f"Document ingestion service returned an unexpected response: {e}. "
            f"Response content: {response.text}",
            exc_info=True,
        )
        st.error(
            "Document ingestion service returned invalid data. Please contact support."
        )
        st.stop()
    st.session_state.pending_ingest_task_id = str(
        ingest_docs_validated_response.task_id
    )
    st.session_state.pending_collection_uuid = str(
        ingest_docs_validated_response.knowledge_base_uuid
    )
    st.session_state.pending_chunking_method = chunking_method
    st.rerun()


def omnirag_page():
    # default values
    pipeline_type = DEFAULT_PIPELINE
    chunking_method = DEFAULT_CHUNKING
    model_name = DEFAULT_MODEL
    instruction_lang = DEFAULT_LANG

    # -- metrics style
    def display_metrics(metrics):
        metrics_html = "<div class='metrics-container'>"
        try:
            for key, value in metrics.items():
                latency_keys = ["latency", "time", "duration", "response_time"]
                is_latency_metric = any(
                    latency_key in key.lower() for latency_key in latency_keys
                )

                if is_latency_metric:
                    color = "white"
                    formatted_value = f"{value:.2f}s"
                else:
                    if key in ["hhem", "Advance_HHEM"]:
                        color = "red" if value > 0.5 else "green"
                    else:
                        color = "green" if value >= 0.5 else "red"
                    formatted_value = f"{value:.2f}"

                metrics_html += (
                    f"<span class='metric'>"
                    f"<span class='metric-name'>{key}:</span>"
                    f"<span class='metric-value {color}'>{formatted_value}</span>"
                    f"</span>"
                )
            metrics_html += "</div>"
            st.markdown(metrics_html, unsafe_allow_html=True)
        except (IndexError, AttributeError, IOError, ValueError, TypeError):
            pass

    # Initialize session state variables
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "current_chat_id" not in st.session_state:
        st.session_state.current_chat_id = None
    if "display_history" not in st.session_state:
        st.session_state.display_history = False
    if "chunking_method" not in st.session_state:
        st.session_state.chunking_method = None
    if "model_name" not in st.session_state:
        st.session_state.model_name = DEFAULT_MODEL
    if "expand_doc_embedding" not in st.session_state:
        st.session_state.expand_doc_embedding = True
    if "instruction_lang" not in st.session_state:
        st.session_state.instruction_lang = None
    if "pending_ingest_task_id" not in st.session_state:
        st.session_state.pending_ingest_task_id = None
    if "pending_embed_task_id" not in st.session_state:
        st.session_state.pending_embed_task_id = None
    if "pending_collection_uuid" not in st.session_state:
        st.session_state.pending_collection_uuid = None
    if "pending_chunking_method" not in st.session_state:
        st.session_state.pending_chunking_method = None

    # -- Poll pending KB creation tasks
    _pending_ingest = st.session_state.get("pending_ingest_task_id")
    _pending_embed = st.session_state.get("pending_embed_task_id")
    _pending_uuid = st.session_state.get("pending_collection_uuid")

    if _pending_ingest or _pending_embed:
        _active_task = _pending_embed or _pending_ingest
        _is_embedding = bool(_pending_embed)
        try:
            with get_client() as client:
                _task_resp = client.get(f"/tasks/{_active_task}")
                _task_resp.raise_for_status()
            _task_status = _task_resp.json().get("status")
        except httpx.HTTPError:
            _task_status = "waiting"

        if _task_status == "error":
            st.session_state.pending_ingest_task_id = None
            st.session_state.pending_embed_task_id = None
            st.session_state.pending_collection_uuid = None
            st.session_state.pending_chunking_method = None

        elif _task_status == "available" and not _is_embedding:
            _method = st.session_state.get("pending_chunking_method", DEFAULT_CHUNKING)
            try:
                with get_client() as client:
                    _embed_resp = client.post(
                        "/flow_operations/create_vector_store",
                        json=_build_index_payload(_pending_uuid, _method),
                    )
                    _embed_resp.raise_for_status()
                st.session_state.pending_ingest_task_id = None
                st.session_state.pending_embed_task_id = _embed_resp.json()["task_id"]
            except httpx.HTTPError as e:
                logger.error(f"Failed to start embedding: {e}", exc_info=True)
                st.session_state.pending_ingest_task_id = None
                st.session_state.pending_embed_task_id = None
                st.session_state.pending_collection_uuid = None
                st.session_state.pending_chunking_method = None
            time.sleep(2)
            st.rerun()

        elif _task_status == "available" and _is_embedding:
            st.session_state.pending_embed_task_id = None
            st.session_state.pending_collection_uuid = None
            st.session_state.pending_chunking_method = None
            st.rerun()

        else:
            time.sleep(3)
            st.rerun()

    # -- Pipeline/Embedding...
    Models = AVAILABLE_MODELS
    chunking_methods = CHUNKING_METHODS
    ACCEPTABLE_DOC_TYPES = tuple(ACCEPTED_EXTENSIONS)

    # %% Reactive settings — always visible, take effect on change
    if _FORCED_VDB == "None":
        try:
            with get_client() as client:
                _kbs_resp = client.get("/collections/")
                _kbs_resp.raise_for_status()
            _all_kbs = _kbs_resp.json()
        except httpx.HTTPError:
            _all_kbs = []
        _ready_kbs = [kb for kb in _all_kbs if kb["status"] == "ready"]
        _active_kbs = [kb for kb in _all_kbs if kb["status"] != "ready"]
        _labels = {
            kb[
                "uuid"
            ]: f"{kb['name']} ({humanize_datetime(_dt.fromisoformat(kb['created_at']))})"
            for kb in _ready_kbs
        }
        _labels = {None: "<New>"} | _labels
        _uuids = list(_labels.keys())
        _current_coll = st.session_state.get("vector_store", None)
        if _current_coll not in _labels:
            _current_coll = None

        if not _HIDE_RAG_PARAMS:
            _cfg_cols = st.columns([2, 2, 1, 1])
        else:
            _cfg_cols = [st.container()]

        with _cfg_cols[0]:
            existing_vector_store = st.selectbox(
                "Active collection",
                options=_uuids,
                index=_uuids.index(_current_coll),
                format_func=lambda u: _labels[u],
                help="The collection your questions will be answered from.",
            )
            st.session_state.vector_store = existing_vector_store
            for _kb in _active_kbs:
                _emoji = _KB_STATUS_EMOJI.get(_kb["status"], "⏳")
                st.caption(f"{_emoji} **{_kb['name']}** — {_kb['status']}")

        if not _HIDE_RAG_PARAMS:
            with _cfg_cols[1]:
                pipeline_type = st.selectbox(
                    "Search strategy",
                    PIPELINE_TYPES,
                    index=(
                        PIPELINE_TYPES.index(
                            st.session_state.get("pipeline_type", DEFAULT_PIPELINE)
                        )
                        if st.session_state.get("pipeline_type") in PIPELINE_TYPES
                        else 0
                    ),
                    help="How documents are retrieved to answer your question",
                )
                st.session_state.pipeline_type = pipeline_type

            with _cfg_cols[2]:
                instruction_lang = st.selectbox(
                    "Response language",
                    SYSTEM_PROMPT_LANGS,
                    index=(
                        SYSTEM_PROMPT_LANGS.index(
                            st.session_state.get("instruction_lang", DEFAULT_LANG)
                        )
                        if st.session_state.get("instruction_lang")
                        in SYSTEM_PROMPT_LANGS
                        else 0
                    ),
                    help="Language used for the AI reasoning instructions.",
                )
                st.session_state.instruction_lang = instruction_lang

            with _cfg_cols[3]:
                _cur_model = st.session_state.get("model_name", DEFAULT_MODEL)
                if _cur_model not in Models:
                    _cur_model = DEFAULT_MODEL
                model_name = st.selectbox(
                    "Model", Models, index=Models.index(_cur_model)
                )
                st.session_state.model_name = model_name
        else:
            if "pipeline_type" not in st.session_state:
                st.session_state.pipeline_type = DEFAULT_PIPELINE
            if "instruction_lang" not in st.session_state:
                st.session_state.instruction_lang = DEFAULT_LANG
            if "model_name" not in st.session_state:
                st.session_state.model_name = DEFAULT_MODEL

        # Expander — only for uploading documents and creating collections
        with st.expander("Add documents to a collection"):
            with st.form("document_input"):
                uploaded_files = st.file_uploader(
                    "Upload documents",
                    accept_multiple_files=True,
                    type=ACCEPTABLE_DOC_TYPES,
                    help="Accepted formats: " + ", ".join(ACCEPTABLE_DOC_TYPES) + ".",
                )
                _form_cols = st.columns([2, 1])
                with _form_cols[0]:
                    new_vs_name = st.text_input(
                        "New collection name",
                        value=st.session_state.get("new_vs_name", ""),
                        help="Name for the new collection. Ignored when adding documents to an existing one.",
                    )
                with _form_cols[1]:
                    chunking_method = st.selectbox(
                        "Text splitting",
                        chunking_methods,
                        index=(
                            chunking_methods.index(
                                st.session_state.get(
                                    "chunking_method", chunking_methods[0]
                                )
                            )
                            if st.session_state.get("chunking_method")
                            in chunking_methods
                            else 0
                        ),
                        format_func=lambda m: _CHUNKING_DISPLAY.get(m, m),
                    )
                if st.form_submit_button("Create collection"):
                    save_button_action(
                        new_vs_name=new_vs_name,
                        uploaded_files=uploaded_files,
                        chunking_method=chunking_method,
                        existing_vector_store=st.session_state.get("vector_store"),
                        model_name=st.session_state.get("model_name", DEFAULT_MODEL),
                    )
            _pi = st.session_state.get("pending_ingest_task_id")
            _pe = st.session_state.get("pending_embed_task_id")
            if _pi or _pe:
                if _pi:
                    st.info("⏳ **Step 1/2:** Ingesting documents…")
                    st.caption(
                        "⬜ Step 2/2: Embedding — waiting for ingestion to finish"
                    )
                else:
                    st.success("✅ **Step 1/2:** Documents ingested")
                    st.info("🔄 **Step 2/2:** Embedding…")
    else:
        # forced_vdb mode: collection is fixed by server config
        if "vector_store" not in st.session_state:
            st.session_state.vector_store = _FORCED_VDB
        if "pipeline_type" not in st.session_state:
            st.session_state.pipeline_type = DEFAULT_PIPELINE
        if "instruction_lang" not in st.session_state:
            st.session_state.instruction_lang = DEFAULT_LANG
        if "model_name" not in st.session_state:
            st.session_state.model_name = DEFAULT_MODEL

    if "vector_store" not in st.session_state:
        st.session_state.vector_store = "<New>"
    if "pipeline_type" not in st.session_state:
        st.session_state.pipeline_type = DEFAULT_PIPELINE
    if "instruction_lang" not in st.session_state:
        st.session_state.instruction_lang = DEFAULT_LANG

    # -- New chat
    if st.sidebar.button("New Chat"):
        st.session_state.chat_history = []
        st.session_state.current_chat_id = None
        st.rerun()

    # -- Recently saved chats...
    username = st.session_state.get("username", "")
    st.sidebar.markdown("Recents")
    try:
        with get_client() as client:
            chats_resp = client.get("/db/chats", params={"username": username})
            chats_resp.raise_for_status()
        historical_chats = chats_resp.json()
    except httpx.HTTPError:
        historical_chats = []
    total_chats = len(historical_chats)
    for chat_number, chat_item in enumerate(historical_chats, start=1):
        chat_id = chat_item["chat_id"]
        timestamp = chat_item.get("timestamp")
        chat_desc_number = total_chats - chat_number + 1
        chat_label = f"Chat {chat_desc_number}"
        if timestamp:
            try:
                ts = _dt.fromisoformat(timestamp)
                chat_label += f" - {humanize_datetime(ts)}"
            except (ValueError, TypeError):
                pass

        col1, col2 = st.sidebar.columns([15, 1])

        with col1:
            if st.button(chat_label, key=f"chat_{chat_desc_number}"):
                try:
                    with get_client() as client:
                        detail_resp = client.get(f"/db/chats/{chat_id}")
                        detail_resp.raise_for_status()
                    detail = detail_resp.json()
                    st.session_state.chat_history = detail.get("chat_history", [])
                    st.session_state.current_chat_id = chat_id
                    st.session_state.model_name = (
                        detail.get("model_name") or DEFAULT_MODEL
                    )
                    st.session_state.chunking_method = detail.get("chunking_method")
                    st.session_state.vector_store = detail.get("vector_store")
                    st.session_state.pipeline_type = (
                        detail.get("pipeline_type") or DEFAULT_PIPELINE
                    )
                    st.session_state.instruction_lang = (
                        detail.get("instruction_lang") or DEFAULT_LANG
                    )
                except httpx.HTTPError as e:
                    st.error(f"Failed to load chat: {e}")
                st.rerun()
        # --
        with col2:
            if st.button("×", key=f"delete_{chat_id}"):
                try:
                    with get_client() as client:
                        client.delete(f"/db/chats/{chat_id}")
                except httpx.HTTPError:
                    pass
                if st.session_state.current_chat_id == chat_id:
                    st.session_state.current_chat_id = None
                    st.session_state.chat_history = []
                st.rerun()

    # -- Clear all chat history + from DB..
    if st.sidebar.button("Clear All Chat History"):
        try:
            with get_client() as client:
                client.delete("/db/chats", params={"username": username})
        except httpx.HTTPError:
            pass
        st.session_state.chat_history.clear()
        st.session_state.current_chat_id = None
        st.rerun()

    # -- view chat history...
    if st.session_state.chat_history:
        for msg in st.session_state.chat_history:
            avatar = msg.get("avatar")
            if (
                avatar
                and isinstance(avatar, str)
                and avatar.startswith("data:image/png;base64,")
            ):
                avatar = avatar
            elif msg["role"] == "human":
                avatar = HUMAN_AVATAR
            else:
                avatar = AI_AVATAR

            with st.chat_message(msg["role"], avatar=avatar):
                st.write(msg["content"])
                if "metrics" in msg:
                    display_metrics(msg["metrics"])
    else:
        st.info("No chat history. Start a new conversation!")

    col1, col2 = st.columns([3, 1])  # Create two columns

    def stream_text(text: str) -> Iterator[str]:
        """Stream with fast typing effect while preserving formatting

        Parameters:
            text (str): Text to stream

        Yields:
            str: Streamed text with preserved formatting
        """
        lines = text.split("\n")
        full_text = ""

        for i, line in enumerate(lines):
            if not line:
                full_text += "\n"
                yield full_text
                time.sleep(0.02)
                continue

            words = line.split(" ")
            chunk_size = 3

            for j in range(0, len(words), chunk_size):
                chunk = " ".join(words[j : j + chunk_size])
                full_text += chunk
                if j + chunk_size < len(words):
                    full_text += " "
                yield full_text
                time.sleep(0.01)
            # --
            if i < len(lines) - 1:
                full_text += "\n"
                yield full_text
                time.sleep(0.01)

    # -- prompting...
    if prompt := st.chat_input("Ask a question..."):
        response = None
        metrics = dict(DUMMY_METRICS)
        st.chat_message("human", avatar=HUMAN_AVATAR).write(prompt)
        st.session_state.chat_history.append(
            {"role": "human", "content": prompt, "avatar": HUMAN_AVATAR_B64}
        )

        vector_store = st.session_state.get("vector_store")
        if not vector_store or vector_store == "<New>":
            st.error("Please select a collection and connect to it before chatting.")
            st.stop()

        query_payload = {
            "collection_uuid": str(vector_store),
            "user_prompt": prompt,
            "chat_history_id": st.session_state.get("current_chat_id"),
            "retrieval": {
                "strategy": _PIPELINE_TO_STRATEGY.get(
                    st.session_state.get("pipeline_type", DEFAULT_PIPELINE),
                    "HAHCOMPOSITE",
                ),
            },
            "generation": {
                "model_name": st.session_state.get("model_name", DEFAULT_MODEL),
                "system_prompt_language": st.session_state.get(
                    "instruction_lang", DEFAULT_LANG
                ),
            },
        }

        with st.chat_message("ai", avatar=AI_AVATAR):
            message_placeholder = st.empty()
            message_placeholder.markdown(
                '<div class="thinking-animation"></div>', unsafe_allow_html=True
            )

            full_text = ""
            start_time = time.time()
            try:
                with get_client(timeout=STREAM_TIMEOUT) as client:
                    with client.stream(
                        "POST", "/query/stream", json=query_payload
                    ) as r:
                        r.raise_for_status()
                        for line in r.iter_lines():
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if not data_str:
                                    continue
                                try:
                                    data = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue
                                if "content" in data:
                                    full_text += data["content"]
                                    message_placeholder.markdown(full_text + "▌")
                                elif "chat_id" in data:
                                    st.session_state.current_chat_id = data["chat_id"]
                                    response = full_text
                                elif "message" in data:
                                    st.error(f"Something went wrong: {data['message']}")
            except httpx.HTTPError:
                st.error(
                    "Could not reach the server. Make sure a collection is selected and connected."
                )
                response = "No answer available. Please select a collection and connect to it first."
                full_text = response

            metrics["latency"] = time.time() - start_time
            message_placeholder.markdown(full_text or response or "")
            display_metrics(metrics)

        response = full_text or response or ""
        # -- Update local chat history
        st.session_state.chat_history.append(
            {
                "role": "ai",
                "content": response,
                "metrics": metrics,
                "avatar": AI_AVATAR_B64,
            }
        )

    data = []
    chat_history = st.session_state.chat_history
    i = 0
    while i < len(chat_history):
        if chat_history[i]["role"] == "human":
            question = chat_history[i]["content"]
            if i + 1 < len(chat_history) and chat_history[i + 1]["role"] == "ai":
                answer = chat_history[i + 1]["content"]
                metrics = chat_history[i + 1].get("metrics") or DUMMY_METRICS
                data.append({"Question": question, "Answer": answer, **metrics})
                i += 2
            else:
                data.append({"Question": question})
                i += 1
        else:
            i += 1

    df = pd.DataFrame(data)

    # Download buttons in sidebar
    st.sidebar.markdown("## Download Chat History")
    col1, col2, col3 = st.sidebar.columns(3)

    if not df.empty:
        # -- CSV download
        csv = df.to_csv(index=False)
        col1.download_button(
            label="CSV",
            data=csv,
            file_name="chat_history.csv",
            mime="text/csv",
        )

        # -- Excel download
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        excel_data = buffer.getvalue()
        col2.download_button(
            label="XLSX",
            data=excel_data,
            file_name="chat_history.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # -- JSON download
        json_str = df.to_json(orient="records")
        col3.download_button(
            label="JSON",
            data=json_str,
            file_name="chat_history.json",
            mime="application/json",
        )

    # Add a button to clear chat history
    if st.button("Clear Chat History"):
        st.session_state.chat_history.clear()
        st.rerun()


if __name__ == "__main__":
    st.set_page_config(
        page_title=_PAGE_TITLE,
        page_icon=_PAGE_ICON,
        layout="wide",
    )
    apply_omnirag_style()
    omnirag_header()
    auth_component()
    if st.session_state.get("authentication_status"):
        omnirag_page()
