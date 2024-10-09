import os
import sys
import torch
import pickle
import sqlite3
from io import BytesIO
import xlsxwriter
import logging
import numpy as np
import pandas as pd
import streamlit as st
from pathlib import Path
from tempfile import NamedTemporaryFile
from global_variables import (
    DATA_PATH,
    IMG_PATH,
    VECTOR_STORE_PATH,
    PipelineTypes,
    Reranker,
    HELP,
    TEMPLATE,
    LLM_NAMES,
    EMBEDDING_NAME,
    SUPPLEMENT,
    Models,
    ChunkingMethod,
    IndexType,
)
from LoaderModelTokenizer import (
    tokenizer,
    model,
)
import json
from datetime import datetime
from Embedding import EmbeddingVectors
from Chunker import TextChunker
from CustomChain import CustomLLMChain
from DocLoader import LOADER_MAPPING, loadSingleDocument, ThreadMultiDocLoader

# --
conn = sqlite3.connect("chat_history.db", check_same_thread=False)
c = conn.cursor()
c.execute(
    """CREATE TABLE IF NOT EXISTS chats
             (id INTEGER PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, chat_data TEXT)"""
)
conn.commit()

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="RAGGER", page_icon="🦙", layout="wide")

st.markdown(
    """
<style>
.metrics-container {
    background-color: transparent;
    padding: 5px;
    margin-top: 5px;
    text-align: right;
}
.metric {
    display: inline-block;
    margin-left: 15px;
    font-size: 12px;
}
.metric-name {
    color: #888;
}
.metric-value {
    font-weight: bold;
    margin-left: 3px;
}
.red {
    color: #ff4b4b;
}
.green {
    color: #00c853;
}
n: 0 !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# -- style metrics
def display_metrics(metrics):
    metrics_html = "<div class='metrics-container'>"
    for key, value in metrics.items():
        if key in ["hhem", "Advance_HHEM"]:
            color = "red" if value > 0.5 else "green"
        else:
            color = "green" if value >= 0.5 else "red"
        metrics_html += f"<span class='metric'><span class='metric-name'>{key}:</span><span class='metric-value {color}'>{value:.2f}</span></span>"
    metrics_html += "</div>"
    st.markdown(metrics_html, unsafe_allow_html=True)


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
def save_chat_to_db(chat_history):
    chat_json = json.dumps(chat_history)
    current_time = datetime.now().isoformat()
    c.execute(
        "INSERT INTO chats (chat_data, timestamp) VALUES (?, ?)",
        (chat_json, current_time),
    )
    conn.commit()


def delete_chat_from_db(chat_id):
    c.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()


# -- delete chat
def delete_chat(chat_id):
    delete_chat_from_db(chat_id)
    if st.session_state.current_chat_id == chat_id:
        st.session_state.current_chat_id = None
        st.session_state.chat_history = []
    st.experimental_rerun()


# Function to load chat history from database
def load_chat_from_db(chat_id):
    c.execute("SELECT chat_data FROM chats WHERE id = ?", (chat_id,))
    result = c.fetchone()
    if result:
        return json.loads(result[0])
    return []


# --get all chat history
def get_all_chats():
    try:
        c.execute("SELECT id, timestamp FROM chats ORDER BY timestamp DESC")
        return c.fetchall()
    except sqlite3.OperationalError:
        # If timestamp column doesn't exist, alter the table to add it
        c.execute("ALTER TABLE chats ADD COLUMN timestamp TEXT")
        conn.commit()

        # Update all existing rows with the current timestamp
        current_time = datetime.now().isoformat()
        c.execute(
            "UPDATE chats SET timestamp = ? WHERE timestamp IS NULL",
            (current_time,),
        )
        conn.commit()

        # Fetch the updated results
        c.execute("SELECT id, timestamp FROM chats ORDER BY timestamp DESC")
        return c.fetchall()


# -- side bar
# st.sidebar.title("Chat Options")


# -- Loader tokenizer and model
@st.cache_resource
def load_model_and_tokenizer():
    return tokenizer, model


tokenizer, model = load_model_and_tokenizer()

st.session_state.model = model
st.session_state.tokenizer = tokenizer


# -- Pipeline/Embedding...
PIPELINE_RAG = list(map(str, PipelineTypes))
Models = list(map(str, Models))
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
    # --
    with st.form("document_input"):
        uploaded_files = st.file_uploader(
            "Knowledge Documents",
            accept_multiple_files=True,
            type=ACCEPTABLE_DOC_TYPES,
            help="Acceptable document formats includes: "
            + " ".join(ACCEPTABLE_DOC_TYPES[:5])
            + " et al.",
        )
        # --
        SINGLE_FILE = 1
        NUMBER_OF_FILES = len(uploaded_files)
        # --
        row_ae = st.columns([2, 1, 1])
        with row_ae[0]:
            model_name = st.selectbox(
                "Models",
                Models,
            )

        with row_ae[1]:
            chunking_method = st.selectbox(
                "Chunking method",
                ChunkingMethod,
            )

        with row_ae[2]:
            index_type = st.selectbox(
                "Index Type",
                IndexType,
            )

        row_be = st.columns(2)
        with row_be[0]:
            # List the existing vector stores
            vector_store_list = ["<New>"] + os.listdir(VECTOR_STORE_PATH)
            vector_store_list = [
                file
                for file in vector_store_list
                if not file.startswith((".", "BM25"))
            ]
            existing_vector_store = st.selectbox(
                "Vector Store to Merge the Knowledge",
                vector_store_list,
                help="Which vector store to add the new documents. Choose <New> to create a new vector store.",
            )

        with row_be[1]:
            # List the existing vector stores
            new_vs_name = st.text_input(
                "New Vector Store Name",
                value="New_vector_store_name",
                help=HELP["new_vector_store"],
            )

        row_buttons = st.columns(6)
        with row_buttons[0]:
            save_button = st.form_submit_button("Create new vector DB")
        with row_buttons[1]:
            custom_chain_button = st.form_submit_button(
                "Initialize context-chain"
            )
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
                if NUMBER_OF_FILES == SINGLE_FILE:
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
            chunker = TextChunker(tokenizer, model)
            chunks = chunker.chunker(documents, method=chunking_method)

            embedding_vector = EmbeddingVectors(
                tokenizer,
                model,
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

        if custom_chain_button:
            chain = CustomLLMChain(
                st.session_state.tokenizer,
                st.session_state.model,
                model_name,
                existing_vector_store,
                index_type=index_type,
            )
            st.session_state.chain = chain

# New Chat
if st.sidebar.button("New Chat"):
    if st.session_state.chat_history:
        save_chat_to_db(st.session_state.chat_history)
    st.session_state.chat_history = []
    st.session_state.current_chat_id = None
    st.experimental_rerun()

st.sidebar.markdown("Recents")
historical_chats = get_all_chats()
for chat_id, timestamp in historical_chats:
    chat_label = f"Chat {chat_id}"
    if timestamp:
        chat_label += f" - {timestamp}"

    col1, col2 = st.sidebar.columns([15, 1])

    with col1:
        if st.button(chat_label, key=f"chat_{chat_id}"):
            st.session_state.chat_history = load_chat_from_db(chat_id)
            st.session_state.current_chat_id = chat_id
            st.experimental_rerun()

    with col2:
        if st.button("×", key=f"delete_{chat_id}"):
            delete_chat(chat_id)
            st.experimental_rerun()

# Add a button to clear all chat history
if st.sidebar.button("Clear All Chat History"):
    c.execute("DELETE FROM chats")
    conn.commit()
    st.session_state.chat_history.clear()
    st.session_state.current_chat_id = None
    st.experimental_rerun()

if st.session_state.chat_history:
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if "metrics" in msg:
                display_metrics(msg["metrics"])
else:
    st.info("No chat history. Start a new conversation!")


col1, col2 = st.columns([3, 1])  # Create two columns
# -- main
if prompt := st.chat_input("Type your message here..."):
    # Display and store user's question
    st.chat_message("human").write(prompt)
    st.session_state.chat_history.append({"role": "human", "content": prompt})

    with st.spinner("Executing chain-of-thoughts"):
        # Use CustomLLMChain.ainvoke to get the response
        response, context, metrics = st.session_state.chain.ainvoke(prompt)

        # Display and store AI's response with metrics
        with st.chat_message("ai"):
            st.write(response)
            display_metrics(metrics)

        st.session_state.chat_history.append(
            {"role": "ai", "content": response, "metrics": metrics}
        )

    # Save the updated chat history if we're continuing an existing chat
    if st.session_state.current_chat_id:
        c.execute(
            "UPDATE chats SET chat_data = ? WHERE id = ?",
            (
                json.dumps(st.session_state.chat_history),
                st.session_state.current_chat_id,
            ),
        )
        conn.commit()

data = []
for i in range(0, len(st.session_state.chat_history), 2):
    if i + 1 < len(st.session_state.chat_history):
        question = st.session_state.chat_history[i]["content"]
        answer = st.session_state.chat_history[i + 1]["content"]
        metrics = st.session_state.chat_history[i + 1].get("metrics", {})
        data.append({"Question": question, "Answer": answer, **metrics})


df = pd.DataFrame(data)

# Download buttons in sidebar
st.sidebar.markdown("## Download Chat History")

col1, col2, col3 = st.sidebar.columns(3)

if not df.empty:
    # CSV download
    csv = df.to_csv(index=False)
    col1.download_button(
        label="CSV",
        data=csv,
        file_name="chat_history.csv",
        mime="text/csv",
    )

    # Excel download
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

    # JSON download
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
    st.experimental_rerun()
