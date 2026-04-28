import logging
import time
import uuid
from io import BytesIO
from typing import Iterator

import pandas as pd
import streamlit as st
import torch

from configurations import FrontendConfig
from connections.database.chats import Chats
from connections.database.users import Users
from connections.qdrant import qdrant_client
from connections.storage import fs
from src.chunker import TextChunker
from src.customchain import CustomLLMChain as HAHCustomLLMChain
from src.customchain_naive import CustomLLMChain as NaiveCustomLLMChain
from src.customchainmixedhah import CustomLLMChain as CHAHCustomLLMChain
from src.docloader import LOADER_MAPPING, ThreadMultiDocLoader
from src.embedding import EmbeddingVectors
from src.globalvariables import (
    CPU_MODEL_SET,
    DEFAULT_CPU_MODEL,
    EMBEDDING_NAME,
    GPU_MODEL_SET,
    REPO_PATH,
    ChunkingMethod,
    PipelineType,
)
from src.metrics import DUMMY_METRICS
from src.modeltokenizer import load_model_and_tokenizer
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
from src.system_prompts import DEFAULT_SYSTEM_PROMPT_LANG, SYSTEM_PROMPT_LANGS_LIST


# -- device available model
def device_available_models():
    """List of available models based on device."""
    if torch.cuda.is_available():
        return list(GPU_MODEL_SET)
    return list(CPU_MODEL_SET)


# -- device default model
def device_default_model():
    """Default model based on device."""
    return (
        FrontendConfig.get().ui.default_gpu_model
        if torch.cuda.is_available()
        else DEFAULT_CPU_MODEL
    )


def omnirag_page():
    # default values
    pipeline_type = PipelineType.HAHCOMPOSITE
    chunking_method = ChunkingMethod.RECURSIVE_CHARACTER
    model_name = device_default_model()
    instruction_lang = DEFAULT_SYSTEM_PROMPT_LANG

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

    # -- Loader tokenizer and model
    @st.cache_resource
    def cache_model_and_tokenizer(model_name, abs_path):
        return load_model_and_tokenizer(model_name, abs_path)

    def init_cached_model(
        model_name: str, repo_path: str, force_update: bool = False
    ) -> bool:
        """
        Initialize a model and tokenizer or update them if the model has changed.

        Parameters:
            model_name: Name of the model to load
            repo_path: Repository path for the model
            force_update: If True, reload the model even if it's already loaded

        Returns:
            bool: True if initialization/update was successful, False otherwise
        """
        if (
            "model" not in st.session_state
            or "tokenizer" not in st.session_state
            or st.session_state.get("model_name") != model_name
            or force_update
        ):
            model, tokenizer = cache_model_and_tokenizer(model_name, repo_path)

            if model and tokenizer:
                st.session_state.model = model
                st.session_state.tokenizer = tokenizer
                st.session_state.model_name = model_name
                return True
            else:
                st.error(
                    f"Failed to load model: {model_name}"
                )  # --> only return in case of failure to load model
                return False

        return True

    # Initialize session state variables
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "current_chat_id" not in st.session_state:
        st.session_state.current_chat_id = None
    if "embedding_index" not in st.session_state:
        st.session_state.embedding_index = None
    if "display_history" not in st.session_state:
        st.session_state.display_history = False
    if "chain" not in st.session_state:
        st.session_state.chain = None
    if "chunking_method" not in st.session_state:
        st.session_state.chunking_method = None
    if "model_name" not in st.session_state or "tokenizer" not in st.session_state:
        st.session_state.model_name = device_default_model()
        init_cached_model(st.session_state.model_name, REPO_PATH)
    if "expand_doc_embedding" not in st.session_state:
        st.session_state.expand_doc_embedding = True
    if "instruction_lang" not in st.session_state:
        st.session_state.instruction_lang = None

    # -- Pipeline/Embedding...
    PIPELINE_TYPES = list(map(str, PipelineType))
    _PIPELINE_DISPLAY = {
        "C-HAH RAG": "Contextual (recommended)",
        "HAH RAG": "Hybrid",
        "Naive RAG": "Basic",
    }
    Models = device_available_models()
    chunking_methods = list(map(str, ChunkingMethod))
    _CHUNKING_DISPLAY = {
        "recursive_character": "Auto-split (recommended)",
        "fixed": "Fixed size",
        "semantic": "By meaning",
        "sentences": "By sentences",
        "paragraphs": "By paragraphs",
    }

    ACCEPTABLE_DOC_TYPES = tuple(LOADER_MAPPING.keys())

    # %% Document embedding
    if FrontendConfig.get().ui.forced_collection == "None":
        with st.expander("Set up your knowledge base"):
            with st.form("document_input"):
                uploaded_files = st.file_uploader(
                    "Upload Documents",
                    accept_multiple_files=True,
                    type=ACCEPTABLE_DOC_TYPES,
                    help="Acceptable document formats includes: "
                    + " ".join(ACCEPTABLE_DOC_TYPES[:5])
                    + " et al.",
                )

                len(uploaded_files)
                if not FrontendConfig.get().ui.hide_rag_params:
                    row_ae = st.columns([2, 1])
                    with row_ae[0]:
                        current_model = st.session_state.get(
                            "model_name", device_available_models()
                        )

                        # Validate current model against available models
                        if current_model not in Models:
                            current_model = device_default_model()

                        model_name = st.selectbox(
                            "Models",
                            Models,
                            index=(
                                Models.index(
                                    st.session_state.get("model_name", current_model)
                                )
                                if st.session_state.get("model_name") in Models
                                else 0
                            ),
                        )
                        # Update model and tokenizer when model changes
                        if model_name != st.session_state.get("model_name"):
                            st.session_state.model_name = model_name
                            model, tokenizer = cache_model_and_tokenizer(
                                model_name, REPO_PATH
                            )
                            if model and tokenizer:
                                st.session_state.model = model
                                st.session_state.tokenizer = tokenizer
                                st.success(f"Successfully loaded model: {model_name}")
                            else:
                                st.error(f"Failed to load model: {model_name}")

                    with row_ae[1]:
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

                existing_collections = [
                    c.name for c in qdrant_client.get_collections().collections
                ]
                row_be = st.columns(4)
                with row_be[0]:
                    new_collection_name = st.text_input(
                        "Collection name",
                        value=st.session_state.get("new_vs_name", ""),
                        help="Name of the collection to create or update.",
                    )

                with row_be[1]:
                    source_options = ["(none)"] + existing_collections
                    source_collection_choice = st.selectbox(
                        "Copy from existing collection (optional)",
                        source_options,
                        index=0,
                        help=(
                            "Leave as '(none)' to create a new collection from scratch. "
                            "Select an existing collection to copy its documents into the new one, "
                            "or to add new documents to it (when the name above matches)."
                        ),
                    )

                if not FrontendConfig.get().ui.hide_rag_params:
                    with row_be[2]:
                        pipeline_type = st.selectbox(
                            "Search strategy",
                            PIPELINE_TYPES,
                            index=PIPELINE_TYPES.index(
                                st.session_state.get(
                                    "pipeline_type", PipelineType.HAHCOMPOSITE
                                )
                            ),
                            format_func=lambda p: _PIPELINE_DISPLAY.get(p, p),
                            help="How documents are retrieved to answer your question",
                        )
                    with row_be[3]:
                        instruction_lang = st.selectbox(
                            "Response language",
                            SYSTEM_PROMPT_LANGS_LIST,
                            help="Language used for the AI reasoning instructions.",
                        )
                # --
                row_buttons = st.columns(6)
                with row_buttons[0]:
                    save_button = st.form_submit_button("Create collection")
                with row_buttons[1]:
                    custom_chain_button = st.form_submit_button("Connect to collection")
                # --
                if save_button:
                    target_collection = new_collection_name.strip()
                    if not target_collection:
                        st.error("Enter a name for the collection.")
                        st.stop()

                    source_collection = (
                        None
                        if source_collection_choice == "(none)"
                        else source_collection_choice
                    )

                    # Guard: if the target already exists it can only be updated by
                    # selecting it as its own source (name must match).
                    if (
                        target_collection in existing_collections
                        and source_collection != target_collection
                    ):
                        if source_collection is None:
                            st.error(
                                f"Collection **{target_collection}** already exists. "
                                "To update it, select it as the source collection."
                            )
                        else:
                            st.error(
                                f"Collection **{target_collection}** already exists and "
                                f"does not match the selected source **{source_collection}**. "
                                f"To update it, select **{target_collection}** as the source collection."
                            )
                        st.stop()

                    # -- check for uploaded document
                    if not uploaded_files:
                        st.error("No document uploaded...")
                        st.stop()

                    # Updating an existing collection: reuse its kb_uuid so new files
                    # are co-located with the existing ones in storage.
                    if (
                        source_collection == target_collection
                        and target_collection in existing_collections
                    ):
                        try:
                            first, _ = qdrant_client.scroll(
                                collection_name=target_collection,
                                limit=1,
                                with_payload=True,
                                with_vectors=False,
                            )
                            if first and "bm25_path" in first[0].payload:
                                knowledge_base_uuid = (
                                    first[0].payload["bm25_path"].split("/")[1]
                                )
                            else:
                                knowledge_base_uuid = str(uuid.uuid4())
                        except Exception:
                            knowledge_base_uuid = str(uuid.uuid4())
                    else:
                        knowledge_base_uuid = str(uuid.uuid4())
                        # Seeding from an existing collection: copy its storage files so
                        # the new collection owns a full copy of the original documents.
                        if source_collection:
                            try:
                                first, _ = qdrant_client.scroll(
                                    collection_name=source_collection,
                                    limit=1,
                                    with_payload=True,
                                    with_vectors=False,
                                )
                                if first and "bm25_path" in first[0].payload:
                                    source_kb_uuid = (
                                        first[0].payload["bm25_path"].split("/")[1]
                                    )
                                    source_kb_path = fs.joinpath(
                                        "knowledge-bases", source_kb_uuid
                                    )
                                    dest_kb_path = fs.joinpath(
                                        "knowledge-bases", knowledge_base_uuid
                                    )
                                    fs.filesystem.copy(
                                        source_kb_path, dest_kb_path, recursive=True
                                    )
                            except Exception as e:
                                logging.warning(
                                    f"Could not copy storage files from '{source_collection}': {e}. "
                                    "Proceeding with new documents only."
                                )

                    uploaded_folder = fs.joinpath(
                        "knowledge-bases", str(knowledge_base_uuid), "uploaded"
                    )
                    new_file_paths = []
                    for uploaded_file in uploaded_files:
                        path = fs.joinpath(uploaded_folder, uploaded_file.name)
                        fs.write_to_file(path, uploaded_file)
                        new_file_paths.append(path)
                    ingested_folder = fs.joinpath(
                        "knowledge-bases", str(knowledge_base_uuid), "ingested"
                    )
                    documents = ThreadMultiDocLoader(
                        new_file_paths, target_dir=ingested_folder
                    )
                    text_chunker = TextChunker(
                        st.session_state.tokenizer, st.session_state.model
                    )
                    chunks = text_chunker.chunker(documents, method=chunking_method)

                    if not chunks or len(chunks) == 0:
                        st.error(
                            "Could not extract text from this document. It may be empty or in an unsupported format."
                        )
                        st.stop()

                    embedding_vector = EmbeddingVectors(
                        st.session_state.tokenizer,
                        st.session_state.model,
                        target_collection,
                        knowledge_base_uuid,
                        source_collection=source_collection,
                        embedding_model_name=EMBEDDING_NAME,
                    )
                    st.session_state.embedding_index = (
                        embedding_vector.create_and_save_index(chunks)
                    )
                    st.success("Collection is ready! Documents have been indexed.")
                    st.session_state.model_name = model_name
                    st.session_state.chunking_method = chunking_method
                    st.session_state.vector_store = target_collection
                    st.session_state.new_vs_name = new_collection_name
                    st.rerun()
                if custom_chain_button:
                    RaggerChain = (
                        CHAHCustomLLMChain
                        if pipeline_type == PipelineType.HAHCOMPOSITE
                        else (
                            HAHCustomLLMChain
                            if pipeline_type == PipelineType.HAH
                            else NaiveCustomLLMChain
                        )
                    )

                    chain_collection = (
                        st.session_state.get("vector_store") or new_collection_name
                    )
                    chain = RaggerChain(
                        model_name,
                        chain_collection,
                        instruction_lang=instruction_lang,
                    )
                    st.session_state.chain = chain
                    st.session_state.pipeline_type = pipeline_type
                    st.session_state.instruction_lang = instruction_lang
    else:
        RaggerChain = (
            CHAHCustomLLMChain
            if pipeline_type == PipelineType.HAHCOMPOSITE
            else (
                HAHCustomLLMChain
                if pipeline_type == PipelineType.HAH
                else NaiveCustomLLMChain
            )
        )

        chain = RaggerChain(
            model_name,
            FrontendConfig.get().ui.forced_collection,
            instruction_lang=instruction_lang,
        )
        st.session_state.chain = chain
        st.session_state.pipeline_type = pipeline_type
        st.session_state.instruction_lang = instruction_lang

    if "model_name" not in st.session_state:
        st.session_state.model_name = device_default_model()
    if "chunking_method" not in st.session_state:
        st.session_state.chunking_name = chunking_methods[0]
    if "vector_store" not in st.session_state:
        st.session_state.vector_store = "<New>"
    if "pipeline_type" not in st.session_state:
        st.session_state.pipeline_type = PipelineType.HAHCOMPOSITE
    if "instruction_lang" not in st.session_state:
        st.session_state.instruction_lang = DEFAULT_SYSTEM_PROMPT_LANG

    # -- New chat
    if st.sidebar.button("New Chat"):
        if hasattr(st.session_state.chain, "conversation_memory"):
            st.session_state.chain.conversation_memory.clear()
        st.session_state.chat_history = []
        st.session_state.current_chat_id = None
        st.rerun()

    # -- Recently saved chats...
    st.sidebar.markdown("Recents")
    user_id = Users.get_by_email(st.session_state.get("username")).id
    historical_chats = Chats.get_all_user_chats(user_id)
    total_chats = len(historical_chats)
    for chat_number, (chat_id, timestamp) in enumerate(historical_chats, start=1):
        chat_desc_number = total_chats - chat_number + 1
        chat_label = f"Chat {chat_desc_number}"
        if timestamp:
            chat_label += f" - {humanize_datetime(timestamp)}"

        col1, col2 = st.sidebar.columns([15, 1])

        with col1:
            if st.button(chat_label, key=f"chat_{chat_desc_number}"):
                (
                    chat_history,
                    model_name,
                    chunking_method,
                    _,
                    vector_store,
                    pipeline_type,
                    instruction_lang,
                ) = Chats.get_chat(chat_id)

                # Set session state variables
                st.session_state.chat_history = chat_history
                st.session_state.current_chat_id = chat_id
                st.session_state.model_name = model_name
                st.session_state.chunking_method = chunking_method
                st.session_state.vector_store = vector_store
                st.session_state.pipeline_type = pipeline_type or PipelineType.HAH
                st.session_state.instruction_lang = instruction_lang

                # -- select appropriate chain class based on pipeline type
                RaggerChain = (
                    CHAHCustomLLMChain
                    if st.session_state.pipeline_type == PipelineType.HAHCOMPOSITE
                    else (
                        HAHCustomLLMChain
                        if st.session_state.pipeline_type == PipelineType.HAH
                        else NaiveCustomLLMChain
                    )
                )

                # -- reinit chain
                chain = RaggerChain(
                    model_name,
                    vector_store,
                    instruction_lang=instruction_lang,
                )
                st.session_state.chain = chain
                st.rerun()
        # --
        with col2:
            if st.button("×", key=f"delete_{chat_id}"):
                Chats.delete_chat(chat_id)
                if st.session_state.current_chat_id == chat_id:
                    st.session_state.current_chat_id = None
                    st.session_state.chat_history = []
                st.rerun()

    # -- Clear all chat history + from DB..
    if st.sidebar.button("Clear All Chat History"):
        user_id = Users.get_by_email(st.session_state.get("username")).id
        Chats.delete_all_user_chats(user_id)
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
        response, context, metrics = None, None, None
        st.chat_message("human", avatar=HUMAN_AVATAR).write(prompt)
        st.session_state.chat_history.append(
            {"role": "human", "content": prompt, "avatar": HUMAN_AVATAR_B64}
        )
        if st.session_state.current_chat_id:
            Chats.update_chat(
                st.session_state.current_chat_id,
                st.session_state.chat_history,
                st.session_state.get("model_name", ""),
                st.session_state.get("chunking_method", ""),
                "",
                st.session_state.get("vector_store", ""),
                st.session_state.get("pipeline_type", ""),
                st.session_state.get("instruction_lang", ""),
            )
        else:
            user_id = Users.get_by_email(st.session_state.get("username")).id
            chat_id = Chats.post_chat(
                user_id,
                st.session_state.chat_history,
                st.session_state.get("model_name", ""),
                st.session_state.get("chunking_method", ""),
                "",
                st.session_state.get("vector_store", ""),
                st.session_state.get("pipeline_type", ""),
                st.session_state.get("instruction_lang", ""),
            )
            st.session_state.current_chat_id = chat_id

        with st.chat_message("ai", avatar=AI_AVATAR):
            message_placeholder = st.empty()

            for _ in range(6):
                message_placeholder.markdown(
                    '<div class="thinking-animation"></div>',
                    unsafe_allow_html=True,
                )
                time.sleep(1)

            with st.spinner(""):
                try:
                    start_time = time.time()
                    response, context, metrics = st.session_state.chain.ainvoke(prompt)
                    end_time = time.time()
                    metrics["latency"] = end_time - start_time
                except (
                    IndexError,
                    AttributeError,
                    IOError,
                    ValueError,
                    TypeError,
                ):
                    st.error(
                        "Please select a collection and connect to it before chatting."
                    )
                    response = "No answer available. Please select a collection and connect to it first."

            # -- streamer
            try:
                for partial_response in stream_text(response):
                    message_placeholder.markdown(partial_response + "▌")
            except (IndexError, AttributeError, IOError, ValueError, TypeError):
                st.error(
                    "Something went wrong. Make sure a collection is selected (not '<New>')."
                )
            message_placeholder.markdown(response)
            display_metrics(metrics)

        # -- Update chat history
        st.session_state.chat_history.append(
            {
                "role": "ai",
                "content": response,
                "metrics": metrics,
                "avatar": AI_AVATAR_B64,
            }
        )

        Chats.update_chat(
            st.session_state.current_chat_id,
            st.session_state.chat_history,
            st.session_state.get("model_name", ""),
            st.session_state.get("chunking_method", ""),
            "",
            st.session_state.get("vector_store", ""),
            st.session_state.get("pipeline_type", ""),
            st.session_state.get("instruction_lang", ""),
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
        if hasattr(st.session_state.chain, "conversation_memory"):
            st.session_state.chain.conversation_memory.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        st.rerun()


if __name__ == "__main__":
    st.set_page_config(
        page_title=FrontendConfig.get().ui.page_title,
        page_icon=FrontendConfig.get().ui.page_icon,
        layout="wide",
    )
    apply_omnirag_style()
    omnirag_header()
    auth_component()
    if st.session_state.get("authentication_status"):
        omnirag_page()
