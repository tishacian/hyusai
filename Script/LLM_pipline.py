from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
from langchain.llms import HuggingFacePipeline
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import Embeddings as emb
import VDB as vdb

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

    embedd=emb.Embeddings(embd_name)
    #print('embed')
    llm_model=llm_pipeline(llm_name)
    #print('llm_model')
    Vec=vdb.VDB(filepath,embedd)
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