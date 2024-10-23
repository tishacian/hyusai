import os
from tempfile import NamedTemporaryFile
import streamlit as st
import sqlite3
from io import BytesIO
import json
import base64
from datetime import datetime
import pandas as pd
from global_variables import (
    IMG_PATH,
    VECTOR_STORE_PATH,
    PipelineTypes,
    HELP,
    Models,
    ChunkingMethod,
    IndexType,
)
from LoaderModelTokenizer import (
    tokenizer,
    model,
)
from PIL import Image
from Embedding import EmbeddingVectors
from Chunker import TextChunker
from CustomChain import CustomLLMChain
from DocLoader import LOADER_MAPPING, loadSingleDocument, ThreadMultiDocLoader


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

    # -- check if the table exists
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
                vector_store TEXT
            )
        """
        )
    else:
        columns_to_add = [
            ("model_name", "TEXT"),
            ("chunking_method", "TEXT"),
            ("index_type", "TEXT"),
            ("vector_store", "TEXT"),
        ]
        for column_name, column_type in columns_to_add:
            c.execute(f"PRAGMA table_info(chats)")
            existing_columns = [column[1] for column in c.fetchall()]
            if column_name not in existing_columns:
                c.execute(
                    f"ALTER TABLE chats ADD COLUMN {column_name} {column_type}"
                )

    conn.commit()
    return conn, c


conn, c = init_db()

st.set_page_config(page_title="RAGGER", page_icon="🦙", layout="wide")

st.markdown(
    """
<style>
.app-header {
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: #f0f2f6;
    padding: 10px;
    border-radius: 10px;
    margin-bottom: 20px;
}
.app-header img {
    margin-right: 10px;
    border-radius: 50%;
    width: 50px;
    height: 50px;
}
.app-header h1 {
    color: #262730;
    font-size: 2.5rem;
    margin: 0;
}
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

st.markdown(
    """
<style>
.stButton > button {
    border: none !important;
    text-align: center !important;
    font-size: 14px !important;
    padding: 5px 10px !important;
    width: 100% !important;
    background-color: transparent !important;
    color: white !important;
    transition: background-color 0.3s ease !important;
}

.stButton > button:hover {
    background-color: #f0f0f0 !important;
    color: #262730 !important;
}

/* Chat history buttons */
button[key^="chat_"] {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    width: 100% !important;
    margin-bottom: 5px !important;
    transition: background-color 0.3s ease !important;
}

button[key^="chat_"]:hover {
    background-color: #f0f0f0 !important;
}

/* Delete button */
button[key^="delete_"] {
    background-color: transparent !important;
    color: #ff4b4b !important;
    padding: 0 !important;
    font-size: 18px !important;
    width: auto !important;
    float: right !important;
    transition: background-color 0.3s ease !important;
}

button[key^="delete_"]:hover {
    background-color: #f0f0f0 !important;
}

/* Highlight for chat hover */
button[key^="chat_"]:focus {
    background-color: #e6f3ff !important;
}

/* Download styler */
.stDownloadButton > button {
    border: none !important;
    text-align: center !important;
    font-size: 12px !important;
    padding: 5px !important;
    width: 100% !important;
    margin-bottom: 5px !important;
    transition: background-color 0.3s ease !important;
}

.stDownloadButton > button:hover {
    background-color: #f0f0f0 !important;
}

/* Auto-hide sidebar */
[data-testid="stSidebar"] {
    position: fixed !important;
    left: -350px;
    top: -50px;
    height: 100vh;
    width: 300px;
    transition: left 0.3s ease-in-out;
    z-index: 100; /* Ensure sidebar is above other elements */
}

/* Sidebar hover effect for expansion */
[data-testid="stSidebar"]:hover {
    left: 0 !important;
}

/* Adjust main content when sidebar is hidden or shown */
.main .block-container {
    padding-left: 20px;
    transition: padding-left 0.3s ease-in-out;
}

[data-testid="stSidebar"]:hover + .main .block-container {
    padding-left: 320px;
}
</style>

<script>
// Using localStorage to persist the sidebar state (expanded/collapsed) across page reloads
document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.querySelector('[data-testid="stSidebar"]');
    const mainContainer = document.querySelector('.main .block-container');
    
    // Check if the sidebar state is saved in localStorage
    const isSidebarExpanded = localStorage.getItem('sidebarExpanded');

    if (isSidebarExpanded === 'true') {
        sidebar.style.left = '0';
        mainContainer.style.paddingLeft = '320px';
    } else {
        sidebar.style.left = '-240px';
        mainContainer.style.paddingLeft = '20px';
    }

    // -- hover event listener to expand the sidebar
    sidebar.addEventListener('mouseenter', function () {
        sidebar.style.left = '0';
        mainContainer.style.paddingLeft = '320px';
        localStorage.setItem('sidebarExpanded', 'true');  // Save expanded state
    });

    // -- event listener to collapse the sidebar on mouse leave
    sidebar.addEventListener('mouseleave', function () {
        sidebar.style.left = '-240px';
        mainContainer.style.paddingLeft = '20px';
        localStorage.setItem('sidebarExpanded', 'false');  // Save collapsed state
    });
});
</script>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    f"""
<div class="app-header">
    <img src="data:image/png;base64,{AI_AVATAR_B64}" alt="AI Avatar"/>
    <h1>RAGGER</h1>
</div>
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
def save_chat_to_db(
    chat_history, model_name, chunking_method, index_type, vector_store
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
        (chat_data, timestamp, model_name, chunking_method, index_type, vector_store) 
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            chat_json,
            current_time,
            model_name,
            chunking_method,
            index_type,
            vector_store,
        ),
    )
    conn.commit()


# Update the load_chat_from_db function
def load_chat_from_db(chat_id):
    c.execute(
        """
        SELECT chat_data, model_name, chunking_method, index_type, vector_store 
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
        return chat_history, result[1], result[2], result[3], result[4]
    return [], None, None, None, None


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

        row_ae = st.columns([2, 1, 1])
        with row_ae[0]:
            model_name = st.selectbox(
                "Models",
                Models,
                index=(
                    Models.index(st.session_state.get("model_name", Models[0]))
                    if st.session_state.get("model_name") in Models
                    else 0
                ),
            )

        with row_ae[1]:
            chunking_method = st.selectbox(
                "Chunking method",
                ChunkingMethod,
                index=(
                    ChunkingMethod.index(
                        st.session_state.get(
                            "chunking_method", ChunkingMethod[0]
                        )
                    )
                    if st.session_state.get("chunking_method")
                    in ChunkingMethod
                    else 0
                ),
            )

        with row_ae[2]:
            index_type = st.selectbox(
                "Index Type",
                IndexType,
                index=(
                    IndexType.index(
                        st.session_state.get("index_type", IndexType[0])
                    )
                    if st.session_state.get("index_type") in IndexType
                    else 0
                ),
            )

        row_be = st.columns(2)
        with row_be[0]:
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

        with row_be[1]:
            new_vs_name = st.text_input(
                "New Vector Store Name",
                value=st.session_state.get(
                    "new_vs_name", "New_vector_store_name"
                ),
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
            chain = CustomLLMChain(
                st.session_state.tokenizer,
                st.session_state.model,
                model_name,
                existing_vector_store,
                index_type=index_type,
            )
            st.session_state.chain = chain

if "model_name" not in st.session_state:
    st.session_state.model_name = Models[0]
if "chunking_method" not in st.session_state:
    st.session_state.chunking_name = ChunkingMethod[0]
if "index_type" not in st.session_state:
    st.session_state.index_type = IndexType[0]
if "vector_store" not in st.session_state:
    st.session_state.vector_store = "<New>"

# -- New chat
if st.sidebar.button("New Chat"):
    if st.session_state.chat_history:
        save_chat_to_db(
            st.session_state.chat_history,
            st.session_state.get("model_name", ""),
            st.session_state.get("chunking_method", ""),
            st.session_state.get("index_type", ""),
            st.session_state.get("vector_store", ""),
        )
    st.session_state.chat_history = []
    st.session_state.current_chat_id = None
    # -- erase old chat history
    if "chain" in st.session_state:
        st.session_state.chain = CustomLLMChain(
            st.session_state.tokenizer,
            st.session_state.model,
            st.session_state.get("model_name", ""),
            st.session_state.get("vector_store", ""),
            index_type=st.session_state.get("index_type", ""),
        )
    st.rerun()


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
            ) = load_chat_from_db(chat_id)
            st.session_state.chat_history = chat_history
            st.session_state.current_chat_id = chat_id
            st.session_state.model_name = model_name
            st.session_state.chunking_method = chunking_method
            st.session_state.index_type = index_type
            st.session_state.vector_store = vector_store

            # Reinitialize the chain with the loaded information
            chain = CustomLLMChain(
                st.session_state.tokenizer,
                st.session_state.model,
                model_name,
                vector_store,
                index_type=index_type,
            )
            st.session_state.chain = chain

            st.rerun()

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
# -- main
response_placeholder = st.empty()
progress_bar = st.progress(0)
if prompt := st.chat_input("Message RAGGER..."):
    response, context, metrics = None, None, None
    # Display and store user's question
    progress_bar.progress(0)
    response_placeholder.empty()
    st.chat_message("human", avatar=HUMAN_AVATAR).write(prompt)
    st.session_state.chat_history.append(
        {"role": "human", "content": prompt, "avatar": HUMAN_AVATAR_B64}
    )

    progress_bar.progress(10)
    progress_bar.progress(50)
    response_placeholder.markdown("Thinking...")
    response, context, metrics = st.session_state.chain.ainvoke(prompt)
    progress_bar.progress(80)
    # Display ragger response
    with st.chat_message("ai", avatar=AI_AVATAR):
        st.write(response)
        display_metrics(metrics)

    st.session_state.chat_history.append(
        {
            "role": "ai",
            "content": response,
            "metrics": metrics,
            "avatar": AI_AVATAR_B64,
        }
    )

    # Save or update chat history
    if st.session_state.current_chat_id:
        # Update existing chat
        c.execute(
            """
            UPDATE chats 
            SET chat_data = ?, model_name = ?, chunking_method = ?, index_type = ?, vector_store = ? 
            WHERE id = ?
            """,
            (
                json.dumps(st.session_state.chat_history),
                st.session_state.get("model_name", ""),
                st.session_state.get("chunking_method", ""),
                st.session_state.get("index_type", ""),
                st.session_state.get("vector_store", ""),
                st.session_state.current_chat_id,
            ),
        )
    else:
        # Create new chat
        save_chat_to_db(
            st.session_state.chat_history,
            st.session_state.get("model_name", ""),
            st.session_state.get("chunking_method", ""),
            st.session_state.get("index_type", ""),
            st.session_state.get("vector_store", ""),
        )
        st.session_state.current_chat_id = c.lastrowid

    conn.commit()
    progress_bar.progress(100)
    progress_bar.empty()
    response_placeholder.empty()


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
    st.rerun()
