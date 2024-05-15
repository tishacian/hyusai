#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri May 10 18:08:11 2024

@author: kennethezukwoke
"""
from langchain.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
from langchain.llms import HuggingFacePipeline
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import Embeddings as emb
import VDB as vdb
#--
import streamlit as st
import LLM_pipline as llm
import tempfile

from langchain.document_loaders import PyPDFLoader

def file_processing(file):
    # Load data from PDF
    loader=PyPDFLoader(file)
    documents = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=20)
    chunk_texts = text_splitter.split_documents(documents)

    return chunk_texts

def VDB(filepath, embeddings):
    chunk_texts = file_processing(filepath)
    vector_store = Chroma.from_documents(chunk_texts, embeddings)
    return vector_store


def llm_pipeline(file_path):
    model = AutoModelForSeq2SeqLM.from_pretrained(file_path)
    tokenizer = AutoTokenizer.from_pretrained(file_path)
    llm = pipeline(
                    "text2text-generation",
                    model=model, 
                    tokenizer=tokenizer, 
                    max_length=128
                )

    llm_model = HuggingFacePipeline(pipeline=llm)

    return llm_model

def llm_reply(input,filepath,embd_name,llm_name):

    embedd = emb.Embeddings(embd_name)
    #print('embed')
    llm_model = llm_pipeline(llm_name)
    #print('llm_model')
    Vec = vdb.VDB(filepath,embedd)
    #print('vec')
    prompt_template = """Use the following pieces of information to answer the user's question.
    If you don't know the answer, just say that you don't know, don't try to make up an answer.

    Context: {context}
    Question: {question}

    Only return the helpful answer below and nothing else.
    Helpful answer:
    """
    prompt = PromptTemplate(template=prompt_template, input_variables=['context', 'question'])
    retriever = Vec.as_retriever(search_kwargs={"k":1}) 

    query = input
    chain_type_kwargs = {"prompt": prompt}
    qa = RetrievalQA.from_chain_type(llm=llm_model, chain_type="stuff", 
                                        retriever=retriever, return_source_documents=False,
                                        chain_type_kwargs=chain_type_kwargs, verbose=True)
    reply = qa(query)
    return reply


#%%




st.set_page_config(layout='wide',page_title='Questions Answering APP')

def main(embd_name,llm_name):
    st.title('PDF Question Answer Web-App')
    #-- 
    uploaded_file=st.file_uploader("Upload your PDF File Here",type=['pdf'])

    if uploaded_file is not None:
        question = st.text_input("Enter your question:")
        if st.button("Show Q and A"):
            filepath =uploaded_file.name
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(uploaded_file.read())
                filepath = tmp_file.name
            answer = llm.llm_reply(question,filepath,embd_name,llm_name)
            #answer = ans_chain.run(question)
            st.text(">>> Response >>>")
            st.text(answer['result'])


if __name__ == '__main__':
    embd_name = "sentence-transformers/all-mpnet-base-v2"
    llm_name = "MBZUAI/LaMini-Flan-T5-248M"
    
    main(embd_name,llm_name)
    
    