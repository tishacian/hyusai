import io
import os
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rag_functions
import streamlit as st
import toml
from global_variables import DATA_PATH, IMG_PATH, VECTOR_STORE_PATH
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferWindowMemory
from langchain.retrievers import BM25Retriever
from rag_metrics import (
    Evaluatrix,
    embedding_model,
    model_evaluator,
    nli_model,
    qa_model,
    tokenizer,
)

# ---

st.title("Customized RAG Agent")

help_ = {  # help suggestions...
    "HuggingFace": "You can get theHuggingFace token from settings of your Huggingface account",
    "LLM_Model": "An instruction LLM model well (distilled or not) necessary to provide the right anwser"
    + "\n"
    "toward the particular context",
    "Instruction_Embedding": "An instruction LLM Embedding well suited to provide the right anwser"
    + "\n"
    + "toward the particular context",
    "Vector_store": "A lsit vector embedding created using the instruction embedding",
    "Temperature": "Apply a larger temperature when sampling for challenging tokens, allowing LLMs to explore"
    + "\n"
    + "diverse choices. A smaller temperature for confident tokens avoiding the influence "
    + "\n"
    + "of tail randomness noises",
    "Max_characer": "The maximum number of characters to generated. This can be similar to the maximum token"
    + "\n"
    + " size of the embedding space. The default is set to 500.",
    "vector_type": "Slect desired vector types",
    "pipeline": "Select the desired pipeline. Default is without Chain of Thought (COT)",
    "template": "Select a template style of choice. Default is a simple template.",
    "reranker": "Reranker algorithm selects between two different response types. The first is Reciprocal Rank Fusion,"
    + "\n"
    + "The other is the Flash reranker, which uses a Cross-Encoder for reranking.",
}


# Add supplmentary embedding models..
supplement = [
    "Alibaba-NLP/gte-large-en-v1.5",
    "sentence-transformers/all-mpnet-base-v2",
    "mixedbread-ai/mxbai-embed-large-v1",
    "WhereIsAI/UAE-Large-V1",
    "avsolatorio/GIST-large-Embedding-v0",
    "w601sxs/b1ade-embed",
    "Labib11/MUG-B-1.6",
    "WhereIsAI/UAE-Large-V1",
]

instruction_embedding = (
    list(np.load(DATA_PATH / "hkuNLP.npy", allow_pickle=True)) + supplement
)
# instruction_embedding.sort(key = lambda x: x.upper()[0])

embd_name = "sentence-transformers/all-mpnet-base-v2"
llm_name = [
    "MBZUAI/LaMini-GPT-774M",
    "MBZUAI/LaMini-GPT-1.5B",
    "MBZUAI/LaMini-Neo-125M",
    "MBZUAI/LaMini-Neo-1.3B",
    "MBZUAI/LaMini-Cerebras-590M",
    "MBZUAI/LaMini-Cerebras-1.3B",
    "MBZUAI/LaMini-Flan-T5-783M",
]
vector_types = ["FAISS", "Chroma", "Weaviate", "PGVector"]
pipeline_rag = ["Default", "COT", "AsynCOT"]
templates = ["Default", "Custom"]


# %% import streamlit as st


def theme():
    st.sidebar.title("Settings")
    CONFIG_PATH = Path("/Users/kennethezukwoke/.streamlit/config.toml")

    # Load the current theme from the config file
    def load_current_theme():
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as configfile:
                config = toml.load(configfile)
                return config["theme"]["backgroundColor"] == "black"
        return

    # Update the config.toml file based on the selected theme
    def update_config(theme):
        config = {
            "theme.light": {
                "primaryColor": "blue",
                "backgroundColor": "white",
                "secondaryBackgroundColor": "lightgrey",
                "textColor": "black",
            },
            "theme.dark": {
                "primaryColor": "yellow",
                "backgroundColor": "black",
                "secondaryBackgroundColor": "grey",
                "textColor": "white",
            },
        }

        if theme == "dark":
            config["theme.dark"]["primaryColor"] = config["theme.dark"]["primaryColor"]
            config["theme.dark"]["backgroundColor"] = config["theme.dark"][
                "backgroundColor"
            ]
            config["theme.dark"]["secondaryBackgroundColor"] = config["theme.dark"][
                "secondaryBackgroundColor"
            ]
            config["theme.dark"]["textColor"] = config["theme.dark"]["textColor"]
        else:
            config["theme.light"]["primaryColor"] = config["theme.light"][
                "primaryColor"
            ]
            config["theme.light"]["backgroundColor"] = config["theme.light"][
                "backgroundColor"
            ]
            config["theme.light"]["secondaryBackgroundColor"] = config["theme.light"][
                "secondaryBackgroundColor"
            ]
            config["theme.light"]["textColor"] = config["theme.light"]["textColor"]

        with open(CONFIG_PATH, "w") as configfile:
            toml.dump(config, configfile)

    # Sidebar for theme toggle
    # st.sidebar.title("Settings")
    theme = st.sidebar.toggle(
        "Switch theme",
    )
    # st.divider()
    # switch
    if theme:
        update_config("light")
    else:
        update_config("dark")


# %% Document embedding...

# --Different columns for Embedding/Chat app
bm25_retriever = 0
with st.expander("Document Embedding"):
    st.title("Document Embedding")
    st.markdown(
        "This page is used to upload the documents as the custom knowledge for the chatbot."
    )
    # instructio_embedding = ["hkunlp/instructor-xl", "sentence-transformers/all-mpnet-base-v2"]
    # --
    with st.form("document_input"):
        document = st.file_uploader(
            "Knowledge Documents", type=["pdf", "txt"], help=".pdf or .txt file"
        )

        row_ae = st.columns([2, 1, 1])
        with row_ae[0]:
            instruct_embeddings = st.selectbox(
                "Model Name of the Instruct Embeddings", instruction_embedding
            )

        with row_ae[1]:
            chunk_size = st.number_input(
                "Chunk Size",
                value=200,
                min_value=0,
                step=1,
            )

        with row_ae[2]:
            chunk_overlap = st.number_input(
                "Chunk Overlap",
                value=10,
                min_value=0,
                step=1,
                help="higher that chunk size",
            )

        row_be = st.columns(2)
        with row_be[0]:
            # List the existing vector stores
            # vector_store_list = list(VECTOR_STORE_PATH.iterdir())
            vector_store_list = ["<New>"] + os.listdir(VECTOR_STORE_PATH)
            vector_store_list = [
                file for file in vector_store_list if not file.startswith(".")
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
                value="new_vector_store_name",
                help="If choose <New> in the dropdown / multiselect box, name the new vector store. Otherwise, fill in the existing vector store to merge.",
            )

        # --
        row_ce = st.columns(3)

        with row_ce[2]:
            default_pipeline = pipeline_rag.index(
                pipeline_rag[1]
            )  # set defaullt pipeline
            pipeline_a = st.selectbox(
                "Pipeline", pipeline_rag, default_pipeline, help=help_["pipeline"]
            )

        save_button = st.form_submit_button("Save vector store")

        if pipeline_a.lower() == "default":
            if save_button:
                # Read the uploaded file
                if document == None:
                    st.error("No document uploaded...")
                if document.name.endswith(".pdf"):
                    document = rag_functions.read_pdf(document)
                elif document.name.endswith(".txt"):
                    document = rag_functions.read_txt(document)
                else:
                    st.error(
                        "Unknown document format.."
                        + "\n"
                        + 'Check if the uploaded file is .pdf or .txt"'
                    )

                # Split document
                split = rag_functions.split_doc(document, chunk_size, chunk_overlap)

                # Check whether to create new vector store
                create_new_vs = None
                if existing_vector_store == "<New>" and new_vs_name != "":
                    create_new_vs = True
                elif existing_vector_store != "<New>" and new_vs_name != "":
                    create_new_vs = False
                else:
                    st.error(
                        "Check the 'Vector Store to Merge the Knowledge' and 'New Vector Store Name'"
                    )

                # Embeddings and storing
                rag_functions.embedding_storing(
                    instruct_embeddings,
                    split,
                    create_new_vs,
                    existing_vector_store,
                    new_vs_name,
                )
        elif pipeline_a.lower() == "cot":
            if save_button:
                # Read the uploaded file
                if document == None:
                    st.error("No document uploaded...")
                if document.name.endswith(".pdf"):
                    document = rag_functions.read_pdf(document)
                    # Split document
                    chunks = rag_functions.split_doc(
                        document, chunk_size, chunk_overlap
                    )
                    bm25_retriever = BM25Retriever.from_documents(chunks)
                    st.success("The BM25 PDF Retriever is created")
                elif document.name.endswith(".txt"):
                    document = rag_functions.read_txt(document)
                    # Split document
                    chunks = rag_functions.split_doc(
                        document, chunk_size, chunk_overlap
                    )
                    bm25_retriever = BM25Retriever.from_documents(chunks)
                    st.success("The BM25 Text Retriever is created")
                else:
                    st.error(
                        "Unknown document format.."
                        + "\n"
                        + 'Check if the uploaded file is .pdf or .txt"'
                    )
            else:
                # Read the uploaded file
                if document == None:
                    st.error("No document uploaded...")
                elif document.name.endswith(".pdf"):
                    document = rag_functions.read_pdf(document)
                    # Split document
                    chunks = rag_functions.split_doc(
                        document, chunk_size, chunk_overlap
                    )
                    bm25_retriever = BM25Retriever.from_documents(chunks)
                    st.success("The BM25 PDF Retriever is created")
                elif document.name.endswith(".txt"):
                    document = rag_functions.read_txt(document)
                    # Split document
                    chunks = rag_functions.split_doc(
                        document, chunk_size, chunk_overlap
                    )
                    bm25_retriever = BM25Retriever.from_documents(chunks)
                    st.success("The BM25 Text Retriever is created")
                else:
                    st.error(
                        "Unknown document format.."
                        + "\n"
                        + 'Check if the uploaded file is .pdf or .txt"'
                    )

# %% Metrics and reranking

st.sidebar.image(str(IMG_PATH / "Dtgy.png"), width=78, use_column_width=False)
reranker = st.sidebar.selectbox(
    "Reranker", ["RRF", "FlashReranker"], help=help_["reranker"]
)

# %% App main functions...chatbot

# theme()

# Setting the LLM
# --load document embedding
with st.expander("LLM Settings"):
    st.title("LLM Settings")
    st.markdown("This page is used to have a chat with the uploaded documents")
    with st.form("setting"):
        row_a = st.columns(3)
        with row_a[0]:
            token = st.text_input(
                "Hugging Face Token",
                type="password",
                value="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",
                help=help_["HuggingFace"],
            )

        with row_a[1]:
            llm_model = st.selectbox("LLM model", llm_name, help=help_["LLM_Model"])

        with row_a[2]:
            instruct_embeddings = st.selectbox(
                "Instruct Embeddings",
                instruction_embedding,
                help=help_["Instruction_Embedding"],
            )

        row_b = st.columns(3)
        with row_b[0]:
            vector_store_list = os.listdir(VECTOR_STORE_PATH)
            vector_store_list = [
                file for file in vector_store_list if not file.startswith(".")
            ]
            vector_store_list.sort(key=lambda x: str(x).upper()[0])
            default_choice = vector_store_list.index(vector_store_list[0])
            existing_vector_store = st.selectbox(
                "Vector Store",
                vector_store_list,
                default_choice,
                help=help_["Vector_store"],
            )

        with row_b[1]:
            temperature = st.number_input(
                "Temperature", value=0.1, step=0.1, help=help_["Temperature"]
            )

        with row_b[2]:
            max_length = st.number_input(
                "Maximum character length",
                value=500,
                step=1,
                help=help_["Max_characer"],
            )
        # --
        row_c = st.columns(3)
        with row_c[0]:
            vector_type = st.selectbox(
                "Vector type", vector_types, help=help_["vector_type"]
            )

        with row_c[1]:
            default_pipeline_cbot = pipeline_rag.index(
                pipeline_rag[1]
            )  # set defaullt pipeline
            pipeline_ = st.selectbox("Pipeline", pipeline_rag, default_pipeline_cbot, help=help_["pipeline"])

        with row_c[2]:
            template_opt = st.selectbox(
                "Template format", templates, help=help_["template"]
            )

        create_chatbot = st.form_submit_button("Create chatbot")
        if token:
            retriever_base, llm = rag_functions.prepare_rag_llm(
                token,
                llm_model,
                instruct_embeddings,
                existing_vector_store,
                temperature,
                max_length,
                vector_type,
            )

with st.expander("Template"):
    st.title("Template format")
    template_input = st.text_area(
        "",
        "You are a professional question-answering AI assistant. You should provide a helpful response to the user question"
        + "\n"
        "In your response, PLEASE ALWAYS:" + "\n"
        "(0) Be a detail-oriented reader: read the question and context and understand both before answering"
        + "\n"
        "(1) Start your answer with a friendly tone, and reiterate the question so the user is sure you understood it"
        + "\n"
        "(2) If the context enables you to answer the question, write a detailed, helpful, and easily understandable answer with sources referenced inline."
        + "\n"
        "IF NOT: you can't find the answer, respond with an explanation, starting with: I couldn't find the information in the laws or cedes provided"
        + "\n"
        "(3) Below the answer, please list out all the referenced sources (i.e. legal paragraphs backing up your claims)"
        + "\n"
        "(4) Now you have your answer, that's amazing - review your answer to make sure it answers the question, is helpful and professional and formatted to be easily readable."
        + "\n"
        "Think step by step." + "\n"
        "Answer the following question using the context provided." + "\n"
        "Question: {question}" + "\n"
        "Context: {context}",
        help=help_["template"],
    )

# Prepare the LLM model
if "conversation" not in st.session_state:
    st.session_state.conversation = None


if pipeline_.lower() == "default":
    # -- Store in conversaional memory
    memory = ConversationBufferWindowMemory(
        k=2,
        memory_key="chat_history",
        output_key="answer",
        return_messages=True,
    )
    # -- Create the chatbot
    qa_conversation = ConversationalRetrievalChain.from_llm(
        llm=llm,
        chain_type="stuff",
        retriever=retriever_base.as_retriever(),
        return_source_documents=True,
        memory=memory,
        # combine_docs_chain_kwargs = {"prompt": custom_prompt},
    )
    # -- session state and generate response
    st.session_state.conversation = qa_conversation


# Chat history
if "history" not in st.session_state:
    st.session_state.history = []

# Source documents
if "source" not in st.session_state:
    st.session_state.source = []


# Display chats
for message in st.session_state.history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# -- init mettrics
fl, la, co, re, hhem, adv_hhem = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
fac, cons, hall = 0.0, 0.0, 0.0

# Ask a question
if question := st.chat_input("Ask a question"):
    # Append user question to history
    st.session_state.history.append({"role": "user", "content": question})
    # Add user question
    with st.chat_message("user"):
        st.markdown(question)

    # Answer the question
    if pipeline_.lower() == "default":
        start_time = time.time()
        answer, doc_source = rag_functions.generate_answer(question, token)
        metrics_ = Evaluatrix(
            answer,
            tokenizer,
            model_evaluator,
            embedding_model,
            nli_model,
            qa_model,
            doc_source,
            question,
            start_time,
        )
    elif pipeline_.lower() == "cot":
        retriever_base = retriever_base.as_retriever(search_kwargs={"k": 2})
        if reranker.lower() == "rrf":
            start_time = time.time()
            answer, doc_source = rag_functions.llm_reply(
                question,
                bm25_retriever,
                llm,
                retriever_base,
                template_opt,
                template_input,
            )
            metrics_ = Evaluatrix(
                answer,
                tokenizer,
                model_evaluator,
                embedding_model,
                nli_model,
                qa_model,
                doc_source,
                question,
                start_time,
            )
        elif reranker.lower() == "flashreranker":
            start_time = time.time()
            answer, doc_source = rag_functions.emsembleFlashreranker(
                question,
                bm25_retriever,
                llm,
                retriever_base,
                template_opt,
                template_input,
            )
            metrics_ = Evaluatrix(
                answer,
                tokenizer,
                model_evaluator,
                embedding_model,
                nli_model,
                qa_model,
                doc_source,
                question,
                start_time,
            )
    else:
        ValueError(
            f'Unknown pipeline type {pipeline_}\n\
                   Please check that pipeline is of types in the list: ["Default", "CoT", "AsynCoT"]'
        )
    # -- Write assistant message
    with st.chat_message("assistant"):
        st.write(answer)
    # Append assistant answer to history
    st.session_state.history.append({"role": "assistant", "content": answer})
    # --
    fl, la, co, re, fac, cons, hall = (
        metrics_["fluency"],
        metrics_["latency"],
        metrics_["coherence"],
        metrics_["relevance"],
        metrics_["factuality"],
        metrics_["consistency"],
        metrics_["hhem"],
    )
    st.session_state.source.append(
        {"question": question, "answer": answer, "document": doc_source}
    )

# -- Eval metrics w/ Latency
st.sidebar.title("$Metrics$")
st.sidebar.markdown("Metrics I")
st.sidebar.markdown(
    f"Fluency: :green[{fl:.2f}]" if fl >= 0.50 else f"Fluency: :red[{fl:.2f}]"
)
st.sidebar.markdown(
    f"Coherence: :green[{co:.2f}]" if co >= 0.50 else f"Coherence: :red[{co:.2f}]"
)
st.sidebar.markdown(
    f"Relevance: :green[{re:.2f}]" if re >= 0.50 else f"Relevance: :red[{re:.2f}]"
)
st.sidebar.markdown(f"Latency: :grey[{la:.2f}] secs")

# -- Hallucination metrics
st.sidebar.markdown("Metrics II")
st.sidebar.markdown(
    f"Factuality: :green[{fac:.2f}]" if fac >= 0.50 else f"Factuality: :red[{fac:.2f}]"
)
st.sidebar.markdown(
    f"Consistency: :green[{cons:.2f}]"
    if cons >= 0.50
    else f"Consistency: :red[{cons:.2f}]"
)
st.sidebar.markdown(
    f"Hallucination: :green[{hall:.2f}]"
    if hall <= 0.50
    else f"Hallucination: :red[{hall:.2f}]"
)
# st.sidebar.text(f'Adv-HHEM: {adv_hhem}')


# %% >Stop session while running to retrieve results...

if "app_stopped" not in st.session_state:
    st.session_state["app_stopped"] = False
elif st.session_state["app_stopped"]:
    st.session_state["app_stopped"] = False


def Running():
    with st.spinner("running"):
        time.sleep(60)


def stopRunning():
    st.session_state["app_stopped"] = True


if st.session_state["app_stopped"]:
    st.stop()

col1, col2 = st.columns(2)
with col1:
    st.button("run", on_click=Running)
with col2:
    st.button("Stop", on_click=stopRunning)

with st.expander("Source documents"):
    st.write(st.session_state.source)

# -- convert conversation to downloadable formats...
json_string = json.dumps(st.session_state.source)


def convert_json_to_df(json_file):
    source_dict = {k: v for (k, v) in zip(range(len(json_file)), json_file)}
    dataframe = pd.DataFrame.from_dict(source_dict, orient="index").T
    return dataframe


data_frame = convert_json_to_df(json_string)


@st.cache_data
def convert_df(data_frame):
    # -- convert json --> pd.DataFrame
    return data_frame.to_csv().encode("utf-8")


# csv = convert_df(data_frame)
def xlxs(data):
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine="xlsxwriter")
    data.to_excel(writer, index=False, sheet_name="sheet1")
    writer.close()
    data_bytes = output.getvalue()
    return data_bytes


data_bytes = xlxs(data_frame)

st.sidebar.markdown(
    """<hr style="height:2px;border:none;color:#333;background-color:white;" /> """,
    unsafe_allow_html=True,
)
st.sidebar.title("Download chat")
#
st.sidebar.download_button(
    label="json",
    file_name="data.json",
    mime="application/json",
    data=json_string,
)

st.sidebar.download_button(
    label="csv",
    file_name="data.csv",
    # mime = "text/csv",
    data=convert_df(data_frame),
)


st.sidebar.download_button(label="xlsx", data=data_bytes, file_name="data.xlsx")
