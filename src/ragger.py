import os
import torch
from tempfile import NamedTemporaryFile
import streamlit as st
import sqlite3
from io import BytesIO
import json
import base64
import time
from typing import Iterator
from datetime import datetime
import pandas as pd
from globalvariables import (
    IMG_PATH,
    REPO_PATH,
    VECTOR_STORE_PATH,
    PipelineType,
    HELP,
    ChunkingMethod,
    IndexType,
    GPU_MODEL_SET,
    CPU_MODEL_SET,
    DEFAULT_GPU_MODEL,
    DEFAULT_CPU_MODEL,
)
from metrics import DUMMY_METRICS
from modeltokenizer import load_model_and_tokenizer
from PIL import Image
from embedding import EmbeddingVectors
from chunker import TextChunker
from customchain import CustomLLMChain as HAHCustomLLMChain
from customchain_naive import CustomLLMChain as NaiveCustomLLMChain
from docloader import LOADER_MAPPING, loadSingleDocument, ThreadMultiDocLoader
from ragger_css import HEADER_METRICS, BUTTONS, THINKING_SPINNER


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
        DEFAULT_GPU_MODEL if torch.cuda.is_available() else DEFAULT_CPU_MODEL
    )


HUMAN_AVATAR_PATH = os.path.join(IMG_PATH, "aitubo.jpg")
AI_AVATAR_PATH = os.path.join(IMG_PATH, "datategy_logo.png")


def load_avatar(image_path):
    return Image.open(image_path).resize((32, 32))


def image_to_base64(image):
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


# -- avatars
HUMAN_AVATAR = load_avatar(HUMAN_AVATAR_PATH)
AI_AVATAR = load_avatar(AI_AVATAR_PATH)

# -- avatars to base64
HUMAN_AVATAR_B64 = image_to_base64(HUMAN_AVATAR)
AI_AVATAR_B64 = image_to_base64(AI_AVATAR)


# -- initialize database
def init_db():
    conn = sqlite3.connect("chat_history.db", check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chats'"
    )
    if c.fetchone() is None:
        c.execute(
            """
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                chat_data TEXT,
                model_name TEXT,
                chunking_method TEXT,
                index_type TEXT,
                vector_store TEXT,
                pipeline_type TEXT
            )
        """
        )
    else:
        columns_to_add = [
            ("model_name", "TEXT"),
            ("chunking_method", "TEXT"),
            ("index_type", "TEXT"),
            ("vector_store", "TEXT"),
            ("pipeline_type", "TEXT"),
        ]
        for column_name, column_type in columns_to_add:
            c.execute("PRAGMA table_info(chats)")
            existing_columns = [column[1] for column in c.fetchall()]
            if column_name not in existing_columns:
                c.execute(
                    f"ALTER TABLE chats ADD COLUMN {column_name} {column_type}"
                )

    conn.commit()
    return conn, c


conn, c = init_db()
st.set_page_config(page_title="RAGGER", page_icon="🦙", layout="wide")
st.markdown(HEADER_METRICS, unsafe_allow_html=True)
st.markdown(BUTTONS, unsafe_allow_html=True)
st.markdown(THINKING_SPINNER, unsafe_allow_html=True)
st.markdown(
    f"""
<div class="app-header">
    <img src="data:image/png;base64,{AI_AVATAR_B64}" alt="AI Avatar"/>
    <h1>RAGGER</h1>
</div>
""",
    unsafe_allow_html=True,
)
# st.markdown(
#    PADDINGS,
#    unsafe_allow_html=True,
# )


# -- metrics style
def display_metrics(metrics):
    metrics_html = "<div class='metrics-container'>"
    try:
        for key, value in metrics.items():
            if key in ["hhem", "Advance_HHEM"]:
                color = "red" if value > 0.5 else "green"
            else:
                color = "green" if value >= 0.5 else "red"
            metrics_html += f"<span class='metric'><span class='metric-name'>{key}:</span><span class='metric-value {color}'>{value:.2f}</span></span>"
        metrics_html += "</div>"
        st.markdown(metrics_html, unsafe_allow_html=True)
    except (IndexError, AttributeError, IOError, ValueError, TypeError):
        pass


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


# Function to save chat history to database
def save_chat_to_db(
    chat_history,
    model_name,
    chunking_method,
    index_type,
    vector_store,
    pipeline_type,
):
    chat_data = []
    for msg in chat_history:
        msg_copy = msg.copy()
        if "avatar" in msg_copy and isinstance(msg_copy["avatar"], str):
            msg_copy["avatar"] = msg_copy["avatar"].split(",")[-1]
        chat_data.append(msg_copy)

    chat_json = json.dumps(chat_data)
    current_time = datetime.now().isoformat()

    c.execute(
        """
        INSERT INTO chats 
        (chat_data, timestamp, model_name, chunking_method, index_type, vector_store, pipeline_type) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_json,
            current_time,
            model_name,
            chunking_method,
            index_type,
            vector_store,
            pipeline_type,
        ),
    )
    conn.commit()


# -- update the load_chat_from_db function
def load_chat_from_db(chat_id):
    c.execute(
        """
        SELECT chat_data, model_name, chunking_method, index_type, vector_store, pipeline_type 
        FROM chats WHERE id = ?
    """,
        (chat_id,),
    )
    result = c.fetchone()
    if result:
        chat_history = json.loads(result[0])
        for msg in chat_history:
            if "avatar" in msg and msg["avatar"]:
                if not msg["avatar"].startswith("data:image/png;base64,"):
                    msg["avatar"] = f"data:image/png;base64,{msg['avatar']}"
        return (
            chat_history,
            result[1],
            result[2],
            result[3],
            result[4],
            result[5],
        )
    return [], None, None, None, None, None


# -- delete chat
def delete_chat(chat_id):
    c.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    if st.session_state.current_chat_id == chat_id:
        st.session_state.current_chat_id = None
        st.session_state.chat_history = []
    st.experimental_rerun()


# --get all chat history
def get_all_chats():
    try:
        c.execute("SELECT id, timestamp FROM chats ORDER BY timestamp DESC")
        return c.fetchall()
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE chats ADD COLUMN timestamp TEXT")
        conn.commit()
        current_time = datetime.now().isoformat()
        c.execute(
            "UPDATE chats SET timestamp = ? WHERE timestamp IS NULL",
            (current_time,),
        )
        conn.commit()

        # -- fetch updated results
        c.execute("SELECT id, timestamp FROM chats ORDER BY timestamp DESC")
        return c.fetchall()


# -- Loader tokenizer and model
@st.cache_resource
def cache_model_and_tokenizer(model_name, abs_path):
    return load_model_and_tokenizer(model_name, abs_path)


# -- Pipeline/Embedding...
PIPELINE_TYPES = list(map(str, PipelineType))
Models = device_available_models()
ChunkingMethod = list(map(str, ChunkingMethod))
IndexType = list(map(str, IndexType))

LOADER_MAPPING = LOADER_MAPPING
ACCEPTABLE_DOC_TYPES = tuple(LOADER_MAPPING.keys())

# %% Document embedding

with st.expander("Document Embedding"):
    st.title("Document Embedding")
    st.markdown(
        "This page is used to upload the documents as the custom knowledge for the chatbot."
    )
    with st.form("document_input"):
        uploaded_files = st.file_uploader(
            "Knowledge Documents",
            accept_multiple_files=True,
            type=ACCEPTABLE_DOC_TYPES,
            help="Acceptable document formats includes: "
            + " ".join(ACCEPTABLE_DOC_TYPES[:5])
            + " et al.",
        )

        NUMBER_OF_FILES = len(uploaded_files)
        current_model = st.session_state.get(
            "model_name", device_available_models()
        )
        # Validate current model against available models
        if current_model not in Models:
            current_model = device_default_model()

        model_name = current_model
        # Initialize/Update model and tokenizer when model changes
        if model_name != st.session_state.get("model_name"):
            st.session_state.model_name = model_name
            model, tokenizer = cache_model_and_tokenizer(model_name, REPO_PATH)
            if model and tokenizer:
                st.session_state.model = model
                st.session_state.tokenizer = tokenizer
                st.success(f"Successfully loaded model: {model_name}")
            else:
                st.error(f"Failed to load model: {model_name}")
        # -- Initialize chunker, index and pipeline
        chunking_method = ChunkingMethod[0]
        st.session_state.chunking_method = chunking_method
        index_type = IndexType[0]
        st.session_state.index_type = index_type
        pipeline_type = PIPELINE_TYPES[0]
        st.session_state.pipeline_type = pipeline_type

        row_be = st.columns(2)
        with row_be[0]:
            new_vs_name = st.text_input(
                "New Vector Store Name",
                value=st.session_state.get(
                    "new_vs_name", "New_vector_store_name"
                ),
                help=HELP["new_vector_store"],
            )
        with row_be[1]:
            vector_store_list = ["<New>"] + os.listdir(VECTOR_STORE_PATH)
            vector_store_list = [
                file
                for file in vector_store_list
                if not file.startswith((".", "BM25"))
            ]
            current_vector_store = st.session_state.get(
                "vector_store", "<New>"
            )
            if current_vector_store not in vector_store_list:
                current_vector_store = "<New>"

            existing_vector_store = st.selectbox(
                "Vector Store to Merge the Knowledge",
                vector_store_list,
                index=vector_store_list.index(
                    current_vector_store
                ),  # This will now be safe
                help="Which vector store to add the new documents. Choose <New> to create a new vector store.",
            )
        # --
        row_buttons = st.columns(2)
        with row_buttons[0]:
            save_button = st.form_submit_button("Create new vector DB")
        with row_buttons[1]:
            custom_chain_button = st.form_submit_button("Initialize RAGGER")
        # --
        if save_button:
            # Check whether to create new vector store --> Checking params
            create_new_vs = None
            if existing_vector_store == "<New>" and new_vs_name != "":
                # -- Create new embedding..
                create_new_vs = True
            elif existing_vector_store != "<New>" and new_vs_name != "":
                # -- Use existing embedding..
                create_new_vs = False
            else:
                st.error(
                    "Check the 'Vector Store to Merge the Knowledge' and 'New Vector Store Name'"
                )
            # -- check for uploaded document
            if not uploaded_files:
                st.error("No document uploaded...")
            else:
                if NUMBER_OF_FILES == 1:
                    # -- load temporary folder first before loading document..
                    _, extension = os.path.splitext(uploaded_files[0].name)
                    with NamedTemporaryFile(
                        delete=False, suffix=extension
                    ) as temp_file:
                        temp_file.write(uploaded_files[0].getbuffer())
                        documents = loadSingleDocument(temp_file.name)
                else:
                    # -- Save the location of all the temporary files first..
                    temp_files = []
                    for uploaded_file in uploaded_files:
                        _, extension = os.path.splitext(uploaded_file.name)
                        with NamedTemporaryFile(
                            delete=False, suffix=extension
                        ) as temp_file:
                            temp_file.write(uploaded_file.getbuffer())
                            temp_files.append(temp_file.name)
                    # -- Threaded loading of collected documents
                    documents = ThreadMultiDocLoader(temp_files)
            chunker = TextChunker(
                st.session_state.tokenizer, st.session_state.model
            )
            chunks = chunker.chunker(documents, method=chunking_method)

            embedding_vector = EmbeddingVectors(
                st.session_state.tokenizer,
                st.session_state.model,
                create_new_vs,
                existing_vector_store,
                new_vs_name,
                embedding_model_name="sentence-transformers/all-mpnet-base-v2",
                embedding_type=index_type,
            )
            st.session_state.embedding_index = (
                embedding_vector.create_and_save_index(chunks)
            )
            st.success("PDF processed and embedding index created!")
            st.session_state.model_name = model_name
            st.session_state.chunking_method = chunking_method
            st.session_state.index_type = index_type
            st.session_state.vector_store = (
                existing_vector_store
                if existing_vector_store != "<New>"
                else new_vs_name
            )
            st.session_state.new_vs_name = new_vs_name
            st.rerun()
        if custom_chain_button:
            RaggerChain = (
                HAHCustomLLMChain
                if pipeline_type == PipelineType.HAH
                else NaiveCustomLLMChain
            )

            chain = RaggerChain(
                st.session_state.tokenizer,
                st.session_state.model,
                model_name,
                existing_vector_store,
                index_type=index_type,
            )
            st.session_state.chain = chain
            st.session_state.pipeline_type = pipeline_type

if "model_name" not in st.session_state:
    st.session_state.model_name = Models[0]
if "chunking_method" not in st.session_state:
    st.session_state.chunking_name = ChunkingMethod[0]
if "index_type" not in st.session_state:
    st.session_state.index_type = IndexType[0]
if "vector_store" not in st.session_state:
    st.session_state.vector_store = "<New>"
if "pipeline_type" not in st.session_state:
    st.session_state.pipeline_type = PipelineType.HAH

# -- New chat
if st.sidebar.button("New Chat"):
    if st.session_state.chat_history:
        save_chat_to_db(
            st.session_state.chat_history,
            st.session_state.get("model_name", ""),
            st.session_state.get("chunking_method", ""),
            st.session_state.get("index_type", ""),
            st.session_state.get("vector_store", ""),
            st.session_state.get("pipeline_type", ""),
        )
    st.session_state.chat_history = []
    st.session_state.current_chat_id = None
    st.rerun()


# -- Recently saved chats...
# -- Recently saved chats...
st.sidebar.markdown("Recents")
historical_chats = get_all_chats()
for chat_id, timestamp in historical_chats:
    chat_label = f"Chat {chat_id}"
    if timestamp:
        chat_label += f" - {timestamp}"

    col1, col2 = st.sidebar.columns([15, 1])

    with col1:
        if st.button(chat_label, key=f"chat_{chat_id}"):
            (
                chat_history,
                model_name,
                chunking_method,
                index_type,
                vector_store,
                pipeline_type,
            ) = load_chat_from_db(chat_id)

            # Set session state variables
            st.session_state.chat_history = chat_history
            st.session_state.current_chat_id = chat_id
            st.session_state.model_name = model_name
            st.session_state.chunking_method = chunking_method
            st.session_state.index_type = index_type
            st.session_state.vector_store = vector_store
            st.session_state.pipeline_type = pipeline_type or PipelineType.HAH

            # Choose the appropriate chain class based on pipeline type
            RaggerChain = (
                HAHCustomLLMChain
                if st.session_state.pipeline_type == PipelineType.HAH
                else NaiveCustomLLMChain
            )

            # -- reinit chain
            chain = RaggerChain(
                st.session_state.tokenizer,
                st.session_state.model,
                model_name,
                vector_store,
                index_type=index_type,
            )
            st.session_state.chain = chain
            st.rerun()
    # --
    with col2:
        if st.button("×", key=f"delete_{chat_id}"):
            delete_chat(chat_id)
            st.rerun()

# -- Clear all chat history + from DB..
if st.sidebar.button("Clear All Chat History"):
    c.execute("DELETE FROM chats")
    conn.commit()
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
if prompt := st.chat_input("Message RAGGER..."):
    response, context, metrics = None, None, None
    st.chat_message("human", avatar=HUMAN_AVATAR).write(prompt)
    st.session_state.chat_history.append(
        {"role": "human", "content": prompt, "avatar": HUMAN_AVATAR_B64}
    )

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
                response, context, metrics = st.session_state.chain.ainvoke(
                    prompt
                )
            except (
                IndexError,
                AttributeError,
                IOError,
                ValueError,
                TypeError,
            ):
                st.error(
                    "Ensure a vector database is selected to initialize before chatting"
                )
                response = "No available context is provided to answer this question. Please ensure to intialize the right vector DB"
                context = ""

        # -- streamer
        try:
            for partial_response in stream_text(response):
                message_placeholder.markdown(partial_response + "▌")
        except (IndexError, AttributeError, IOError, ValueError, TypeError):
            st.error(
                "Something went wrong...Check to see if the vector DB is selected not <New>"
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

    # -- Save or update chat history in database
    if st.session_state.current_chat_id:
        c.execute(
            """
            UPDATE chats 
            SET chat_data = ?, model_name = ?, chunking_method = ?, index_type = ?, vector_store = ?, pipeline_type = ?
            WHERE id = ?
            """,
            (
                json.dumps(st.session_state.chat_history),
                st.session_state.get("model_name", ""),
                st.session_state.get("chunking_method", ""),
                st.session_state.get("index_type", ""),
                st.session_state.get("vector_store", ""),
                st.session_state.get("pipeline_type", ""),
                st.session_state.current_chat_id,
            ),
        )
    else:
        save_chat_to_db(
            st.session_state.chat_history,
            st.session_state.get("model_name", ""),
            st.session_state.get("chunking_method", ""),
            st.session_state.get("index_type", ""),
            st.session_state.get("vector_store", ""),
            st.session_state.get("pipeline_type", ""),
        )
        st.session_state.current_chat_id = c.lastrowid

    conn.commit()


data = []
for i in range(0, len(st.session_state.chat_history), 2):
    if i + 1 < len(st.session_state.chat_history):
        question = st.session_state.chat_history[i]["content"]
        answer = st.session_state.chat_history[i + 1]["content"]
        metrics = st.session_state.chat_history[i + 1].get("metrics", {})
        if metrics is None:
            metrics = DUMMY_METRICS
        data.append({"Question": question, "Answer": answer, **metrics})


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
