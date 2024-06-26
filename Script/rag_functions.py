import streamlit as st
import torch
from flashrank import Ranker
from global_variables import VECTOR_STORE_PATH
from langchain import HuggingFaceHub
from langchain.document_loaders import PyPDFLoader
from langchain.embeddings import HuggingFaceInstructEmbeddings
from langchain.prompts import PromptTemplate

# --
from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS, Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableParallel, RunnablePassthrough
from pypdf import PdfReader
from transformers import AutoTokenizer

device = "cuda" if torch.cuda.is_available() else "cpu"


# %%


def read_pdf(file):
    document = ""
    reader = PdfReader(file)
    for page in reader.pages:
        document += page.extract_text()
    # --
    return document


def read_txt(file):
    document = str(file.getvalue())
    document = document.replace("\\n", " \\n ").replace("\\r", " \\r ")

    return document


# -- Using RecursiveCharacterTextSplitter from langchain...
def split_doc(document, chunk_size, chunk_overlap):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    split = splitter.split_text(document)
    split = splitter.create_documents(split)

    return split


# --- Embedding storing...
def embedding_storing(
    model_name,
    split,
    create_new_vs,
    existing_vector_store,
    new_vs_name,
    vectorization_type: str = "",
):
    """
    Embedding stroe

    Parameters
    ----------
    model_name (str): Model name
    split (<Document>): Document chunks
    create_new_vs (str): flag to create new vector store
    existing_vector_store (str): Flag to skip creating VD if existing
    new_vs_name (str): New vector store
    vectorization_type (str): vectorization type

    Raises
    ------
    ValueError (Eror): Error if no vector store.

    Returns
    -------
    None.

    """
    if create_new_vs is not None:
        # Load embeddings instructor
        instructor_embeddings = HuggingFaceInstructEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            # trust_remote_code = True,
        )

        if create_new_vs == True:
            # Save db
            if vectorization_type.lower() == "chroma":
                retriever_base = Chroma.from_documents(
                    split,
                    instructor_embeddings,
                    persist_directory=str(VECTOR_STORE_PATH / f"Chr_{new_vs_name}"),
                )
                st.write("Chroma DB already saved")
            elif vectorization_type.lower() == "faiss":
                retriever_base = FAISS.from_documents(
                    split, embedding=instructor_embeddings
                )
                retriever_base.save_local(
                    str(VECTOR_STORE_PATH / f"FAIS_{new_vs_name}")
                )
                st.write("Created and saved FAISS DB")
        else:
            # Load existing db
            if vectorization_type.lower() == "chroma":
                ld_retriever_base = Chroma(
                    persist_directory=str(
                        VECTOR_STORE_PATH / f"Chr_{existing_vector_store}"
                    ),
                    embedding_function=instructor_embeddings,
                )
                # Merge two DBs and save
                ld_retriever_base.merge_from(retriever_base)
                ld_retriever_base.save_local(
                    str(VECTOR_STORE_PATH / f"Chr_{existing_vector_store}")
                )
            elif vectorization_type.lower() == "faiss":
                ld_retriever_base = FAISS.load_local(
                    str(VECTOR_STORE_PATH / new_vs_name),
                    instructor_embeddings,
                    allow_dangerous_deserialization=True,
                )
                # Merge two DBs and save
                ld_retriever_base.merge_from(retriever_base)
                ld_retriever_base.save_local(
                    str(VECTOR_STORE_PATH / f"FAIS_{existing_vector_store}")
                )

        st.success("The document has been saved.")


# - File processing...
def file_processing(file, embed_name):
    # -- Load PDF
    loader = PyPDFLoader(file)
    documents = loader.load()
    tok = AutoTokenizer.from_pretrained(embed_name)
    text_splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
        tok,
        chunk_size=tok.model_max_length,
        chunk_overlap=int(tok.model_max_length / 10),
    )
    chunk_texts = text_splitter.split_documents(documents)
    return chunk_texts


# -- LLM reply module...
def llm_reply(
    question, bm25_retriever, llm_model, retriever, template_opt, template_input
):
    """
    Using Emsemble retriever w/ RunnablePassthrough/RunnableParrel
    ------------------------------------
    The EnsembleRetriever in LangChain is a retrieval algorithm that combines the results of multiple
    retrievers and reranks them using the Reciprocal Rank Fusion algorithm.

    It is used to improve the performance of retrieval by leveraging the strengths of different algorithms.
    You may need to use the EnsembleRetriever when you want to achieve better retrieval performance
    than any single algorithm can provide. It is particularly useful when combining a sparse
    retriever (e.g., BM25) with a dense retriever (e.g., embedding similarity) because their
    strengths are complementary.

    The sparse retriever is good at finding relevant documents based on keywords, while the dense retriever (e.g FAISS)
    is good at finding relevant documents based on semantic similarity (Hybrid search =  keyword search + Semantic search).

    Parameters
    ----------
    token (str): HuggingFace token

        Add to environment using
        >> import os
        >> os.environ['HUGGINGFACEHUB_API_TOKEN']

    bm25_retriever (BM25 retriever class): BM25 retriever class
    llm_model (llm_model class): LLM model class
    retriever (Dense retriever class): Dense retriever class
    template_opt (str): template options
    template_input (str): Custom template input

    Returns
    ------
    answer (str): answer
    doc_source (list): Ranked document source
    metric (dict): eveluation metrics

    """
    # --
    bm25_retriever.k = 2
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever], weights=[0.5, 0.5]
    )
    # docs = [ensemble_retriever.invoke(question)] # for query in queries] # apply asynchronoys retrival here...

    format_docs = lambda x: "\n\n".join(doc.page_content for doc in x)

    # Define template
    if template_opt.lower() == "default":
        template = """Use the following pieces of context to answer the question at the end.
                                If you don't know the answer, just say that you don't know, don't try to make up an answer.
                                
                                {context}
                                
                                Question: {question}
                            """

    elif template_opt.lower() == "custom":
        if not template_input:
            template = """Use the following pieces of context to answer the question at the end.
                                    If you don't know the answer, just say that you don't know, don't try to make up an answer.
                                    
                                    {context}
                                    
                                    Question: {question}
                                """
        else:
            template = f"""
                                    {template_input}
                                """
    # Create the prompt template
    prompt = PromptTemplate.from_template(template=template)

    # Define the runnable chain from docs
    rag_chain_from_docs = (
        RunnablePassthrough.assign(
            context=lambda x: {"context": format_docs(x["context"])}
        )
        | prompt  # prompt
        | llm_model  # LLM Model
        | StrOutputParser()  # Output parser
    )

    """
    ----
    Define the parallel chain --> Runs N-questions in parallel from the Emsemble retriever
    These documenst are then ranked and returns as document response. The top-k response is returned and the index zero
    is the most favoured response of the LLM.
    """
    rag_chain_with_source = RunnableParallel(
        {"context": ensemble_retriever, "question": RunnablePassthrough()}
    ).assign(answer=rag_chain_from_docs)
    # --
    ans_datategy = rag_chain_with_source.invoke(question)

    # -- Document source
    doc_source = [
        doc.page_content for doc in ans_datategy["context"]
    ]  # returns the source documents...
    answer = doc_source[0]
    return answer, doc_source


# -- LLM reply module...
def emsembleFlashreranker(
    question, bm25_retriever, llm_model, retriever, template_opt, template_input
):
    """
    Using Emsemble retriever w/ Flash Reranker
    ------------------------------------
    The EnsembleRetriever algorithm combines the results of multiple retrievers and reranks them
    using the Reciprocal ```Reciprocal Rank Fusion algorithm``` (RRF). However, instead of using the RFA Algorithm,
    we opt for the FlashReranking algorithm.


    FlashReranker is a zero-shot cross-encoder reranking algorithm.
        - Ultra-lite and fast. No Torch or Transformers needed.
        - Rerank speed is a function of # of tokens in passages, query + model depth (layers).

        Model card
        ----------
        ->[1] ms-marco-TinyBERT-L-2-v2 (default) Model card
        ->[2] ms-marco-MiniLM-L-12-v2 Model card
        ->[3] rank-T5-flan (Best non cross-encoder reranker) Model card
        ->[4] ms-marco-MultiBERT-L-12 (Multi-lingual, supports 100+ languages)
        ->[5] ce-esci-MiniLM-L12-v2 FT on Amazon ESCI dataset (This is interesting because most models are FT on MSFT MARCO Bing queries) Model card
        ->[6] rank_zephyr_7b_v1_full (4-bit-quantised GGUF) Model card (Offers very competitive performance, with large context window and relatively faster for a 4GB model).
                Important note: Our current integration of rank_zephyr supports a max of 20 passages in one pass. The sliding window logic support is yet to be added.

        source: https://github.com/PrithivirajDamodaran/FlashRank?tab=readme-ov-file

    References
    ----------
    Orginal paper, Reciprocal Rank Fusion Algorithm: https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
    Flash Reranker: https://github.com/PrithivirajDamodaran/FlashRank

    Parameters
    ----------
    token (str): HuggingFace token

        Add to environment using
        >> import os
        >> os.environ['HUGGINGFACEHUB_API_TOKEN'] = 'api-key'

    bm25_retriever (BM25 retriever class): BM25 retriever class
    llm_model (llm_model class): LLM model class
    retriever (Dense retriever class): Dense retriever class
    template_opt (str): template options
    template_input (str): Custom template input

    Returns
    ------
    answer (str): answer
    doc_source (list): Ranked document source
    metric (dict): eveluation metrics

    """
    # --
    bm25_retriever.k = 2
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever], weights=[0.4, 0.6]
    )

    model_name = "ms-marco-MultiBERT-L-12"  # example Cross-Encoder model
    flashrank_client = Ranker(model_name=model_name)

    compressor = FlashrankRerank(client=flashrank_client, top_n=3, model=model_name)
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor, base_retriever=ensemble_retriever
    )
    compressed_docs = compression_retriever.invoke(question)
    # -- Document source
    doc_source = [
        doc.page_content for doc in compressed_docs
    ]  # returns the source documents...
    # To use later (document_relevance) as context relevance --> Depending on the reranking model used ```model_name```...
    document_relevance = [doc.metadata["relevance_score"] for doc in compressed_docs]
    answer = doc_source[0]
    # --
    return answer, doc_source


# --- Base retriever store...
def vectorizer(embeddings, vector_store_list, vectorization_type: str = ""):
    vector_store_list_path = VECTOR_STORE_PATH / vector_store_list
    # --- initialize vector DB
    if vectorization_type.lower() == "chroma":
        if vector_store_list_path.exists():
            retriever_base = Chroma(
                persist_directory=str(vector_store_list_path),
                embedding_function=embeddings,
            )
            st.success("Chroma vector DB loaded...")
        else:
            st.error("Chroma vector DB [NOT] loaded...")
    # --
    if vectorization_type.lower() == "faiss":
        if vector_store_list_path.exists():
            retriever_base = FAISS.load_local(
                str(vector_store_list_path),
                embeddings,
                allow_dangerous_deserialization=True,
            )
            st.success("FAISS vector DB loaded...")
        else:
            st.error("FAISS vector DB [NOT] loaded...")

    else:
        st.write(f"Unknown vector database {vectorization_type}")

    return retriever_base


# --- Use similar prepare RAG-LLM
def prepare_rag_llm(
    token,
    llm_model,
    instruct_embeddings,
    vector_store_list,
    temperature,
    max_length,
    vect_type,
):
    """
    Prepare the LLM Embedding and Model

    Parameters
    ----------
    token (str): HuggingFace token

        Add to environment using
        >> import os
        >> os.environ['HUGGINGFACEHUB_API_TOKEN']

    llm_model (str): LLM model name
    instruct_embeddings (str) Embedding name
        DESCRIPTION.
    vector_store_list (str): vector store
    temperature (sr): Temperature
    max_length (str): Maximum token size
    vect_type (str): vector type (e.g FAISS or Chroma)

    Returns
    -------
    retriever_base (retriever_class): rettriver base class
    llm (LLM class): Main LLm class
    """
    # -- Load embeddings instructor
    instructor_embeddings = HuggingFaceInstructEmbeddings(
        model_name=instruct_embeddings,
        model_kwargs={"device": device},
        # trust_remote_code = True,
    )

    # -- Load db
    retriever_base = vectorizer(
        instructor_embeddings, vector_store_list, vectorization_type=vect_type
    )

    # -- Load LLM
    llm = HuggingFaceHub(
        repo_id=llm_model,
        model_kwargs={"temperature": temperature, "max_length": max_length},
        huggingfacehub_api_token=token,
    )

    return retriever_base, llm


# -- Generating answers
def generate_answer(question, token):
    """
    Stuff chain response model

    Parameters
    ------------
    question (str): input question
    token (str): HuggingFace token

        Add to environment using
        >> import os
        >> os.environ['HUGGINGFACEHUB_API_TOKEN']

    Returns
    ------
    answer (str): answer
    doc_source (list): Ranked document source
    metric (dict): eveluation metrics
    """
    # -- answer
    answer = "An error has occured"
    # -- timer..
    if token == "":
        answer = "Insert the Hugging Face token"
        doc_source = ["no source"]
    else:
        response = st.session_state.conversation({"question": question})
        answer = response.get("answer").split("Helpful Answer:")[-1].strip()
        explanation = response.get("source_documents", [])
        doc_source = [d.page_content for d in explanation]
    # --
    return answer, doc_source


# %%
