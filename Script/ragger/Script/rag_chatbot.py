import os
import io
import numpy as np
from os.path import join
import streamlit as st
import rag_functions
import toml
import time
import json
import numpy as np
import pandas as pd
from xlsxwriter import Workbook


# from rag_metrics import (fluency,
#                           coherence,
#                           relevance,
#                           latency,
#                           factuality,
#                           consistency,
#                           HHEM,
#                           Advance_HHEM,
#                           )
# st.set_page_config(layout = "wide")
#---
st.title("Customized RAG Agent")

help_ = { # help suggestions...
        'HuggingFace': "You can get theHuggingFace token from settings of your Huggingface account",
        'LLM_Model': 'An instruction LLM model well (distilled or not) necessary to provide the right anwser'+'\n'
            'toward the particular context',
        'Instruction_Embedding': 'An instruction LLM Embedding well suited to provide the right anwser'+'\n'+
            'toward the particular context',
        'Vector_store': 'A lsit vector embedding created using the instruction embedding',
        'Temperature': 'Apply a larger temperature when sampling for challenging tokens, allowing LLMs to explore'+'\n'+
        'diverse choices. A smaller temperature for confident tokens avoiding the influence '+'\n'+'of tail randomness noises',
        'Max_characer': 'The maximum number of characters to generated. This can be similar to the maximum token'+'\n'+
                        ' size of the embedding space. The default is set to 500.'
                        }

#data_path = '/workspace/Ragger/ragger/Data' # for the cluster
data_path = '/Users/kennethezukwoke/Documents/Datategy/Kenneth/ragger/Data'
img_path = '/Users/kennethezukwoke/Documents/Datategy/Kenneth/ragger/image'

instruction_embedding = list(np.load(join(data_path, 'hkuNLP.npy'), allow_pickle = True)) + ["sentence-transformers/all-mpnet-base-v2"]
instruction_embedding.sort(key = lambda x: x.upper()[0])

#%% import streamlit as st

def theme():
    st.sidebar.title('Settings')
    CONFIG_PATH = "/Users/kennethezukwoke/.streamlit/config.toml"
    # Load the current theme from the config file
    def load_current_theme():
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as configfile:
                config = toml.load(configfile)
                return config['theme']['backgroundColor'] == 'black'
        return
    
    # Update the config.toml file based on the selected theme
    def update_config(theme):
        config = {
            "theme.light": {
                "primaryColor": "blue",
                "backgroundColor": "white",
                "secondaryBackgroundColor": "lightgrey",
                "textColor": "black"
            },
            "theme.dark": {
                "primaryColor": "yellow",
                "backgroundColor": "black",
                "secondaryBackgroundColor": "grey",
                "textColor": "white"
            }
        }
    
        if theme == 'dark':
            config["theme.dark"]["primaryColor"] = config["theme.dark"]["primaryColor"]
            config["theme.dark"]["backgroundColor"] = config["theme.dark"]["backgroundColor"]
            config["theme.dark"]["secondaryBackgroundColor"] = config["theme.dark"]["secondaryBackgroundColor"]
            config["theme.dark"]["textColor"] = config["theme.dark"]["textColor"]
        else:
            config["theme.light"]["primaryColor"] = config["theme.light"]["primaryColor"]
            config["theme.light"]["backgroundColor"] = config["theme.light"]["backgroundColor"]
            config["theme.light"]["secondaryBackgroundColor"] = config["theme.light"]["secondaryBackgroundColor"]
            config["theme.light"]["textColor"] = config["theme.light"]["textColor"]
    
        with open(CONFIG_PATH, 'w') as configfile:
            toml.dump(config, configfile)
    # Sidebar for theme toggle
    # st.sidebar.title("Settings")
    theme = st.sidebar.toggle("Switch theme",)
    # st.divider()
    # switch 
    if theme:
        update_config('light')
    else:
        update_config('dark')
    

#%% Document embedding...

#--Different columns for Embedding/Chat app
def document_embed():
    with st.expander('Document Embedding'):
        st.title("Document Embedding")
        st.markdown("This page is used to upload the documents as the custom knowledge for the chatbot.")
        # instructio_embedding = ["hkunlp/instructor-xl", "sentence-transformers/all-mpnet-base-v2"]
        #--
        with st.form("document_input"):
            document = st.file_uploader("Knowledge Documents", type = ['pdf', 'txt'], help = ".pdf or .txt file")
    
            row_ae = st.columns([2, 1, 1])
            with row_ae[0]:
                instruct_embeddings = st.selectbox(
                    "Model Name of the Instruct Embeddings", instruction_embedding
                )
            
            with row_ae[1]:
                chunk_size = st.number_input(
                    "Chunk Size", value = 200, min_value = 0, step = 1,
                )
            
            with row_ae[2]:
                chunk_overlap = st.number_input(
                    "Chunk Overlap", value = 10, min_value = 0, step = 1,
                    help = "higher that chunk size"
                )
            
            row_be = st.columns(2)
            with row_be[0]:
                # List the existing vector stores
                vector_store_list = os.listdir("vector store/")
                vector_store_list = ["<New>"] + vector_store_list
                
                existing_vector_store = st.selectbox(
                    "Vector Store to Merge the Knowledge", vector_store_list,
                    help = "Which vector store to add the new documents. Choose <New> to create a new vector store."
                )
    
            with row_be[1]:
                # List the existing vector stores     
                new_vs_name = st.text_input(
                    "New Vector Store Name", value = "new_vector_store_name",
                    help = "If choose <New> in the dropdown / multiselect box, name the new vector store. Otherwise, fill in the existing vector store to merge."
                )
    
            save_button = st.form_submit_button("Save vector store")
    
        if save_button:
            # Read the uploaded file
            if document == None:
                return st.error("No document uploaded...")
            if document.name.endswith('.pdf'):
                document = rag_functions.read_pdf(document)
            elif document.name.endswith('.txt'):
                document = rag_functions.read_txt(document)
            else:
                st.error('Unknown document format..' + '\n' + \
                         'Check if the uploaded file is .pdf or .txt"')
    
            # Split document
            split = rag_functions.split_doc(document, chunk_size, chunk_overlap)
    
            # Check whether to create new vector store
            create_new_vs = None
            if existing_vector_store == "<New>" and new_vs_name != "":
                create_new_vs = True
            elif existing_vector_store != "<New>" and new_vs_name != "":
                create_new_vs = False
            else:
                st.error("Check the 'Vector Store to Merge the Knowledge' and 'New Vector Store Name'")
            
            # Embeddings and storing
            rag_functions.embedding_storing(
                instruct_embeddings, split, create_new_vs, existing_vector_store, new_vs_name
            )
       
        
#%% App main functions...chatbot

# #-- tabs
# tab_a, tab_b, tab_c = st.tabs(["Customized chatbot",
#                                "Document Embedding",
#                                "Document previewer"])
# #-- 
# tabs = {'tabA': tab_a, 'tabB': tab_b, 'tabC': tab_c,}
embd_name = "sentence-transformers/all-mpnet-base-v2"
#-- llm_name = "MBZUAI/LaMini-Flan-T5-248M"
llm_name = 'MBZUAI/LaMini-GPT-774M'

#-- Toggle sidebar...
# theme()

# Setting the LLM
st.title("RAG Agent")
#--load document embedding
document_embed()
with st.expander("LLM Settings"):
    st.title('LLM Settings')
    st.markdown("This page is used to have a chat with the uploaded documents")
    with st.form("setting"):
        row_a = st.columns(3)
        with row_a[0]:
            token = st.text_input("Hugging Face Token", type = "password", value = "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",
                                  help = help_['HuggingFace'])

        with row_a[1]:
            llm_model = st.text_input("LLM model", value = llm_name,
                                      help = help_['LLM_Model'])

        with row_a[2]:
            instruct_embeddings = st.selectbox("Instruct Embeddings", instruction_embedding,
                                                help = help_['Instruction_Embedding'])

        row_b = st.columns(3)
        with row_b[0]:
            vector_store_list = os.listdir("vector store/")
            vector_store_list = [vect for vect in os.listdir("vector store/") if not vect.startswith('.')]
            vector_store_list.sort(key = lambda x: x.upper()[0])
            default_choice = (
                                vector_store_list.index(vector_store_list[0])
                            )
            existing_vector_store = st.selectbox("Vector Store", vector_store_list, default_choice,
                                                 help = help_['Vector_store'])
        
        with row_b[1]:
            temperature = st.number_input("Temperature", value = 0.9, step = 0.1,
                                          help = help_['Temperature'])

        with row_b[2]:
            max_length = st.number_input("Maximum character length", value = 500, step = 1,
                                         help = help_['Max_characer'])
        #--
        create_chatbot = st.form_submit_button("Create chatbot")

# Prepare the LLM model
if "conversation" not in st.session_state:
    st.session_state.conversation = None

if token:
    st.session_state.conversation = rag_functions.prepare_rag_llm(
                                        token, llm_model,
                                        instruct_embeddings,
                                        existing_vector_store,
                                        temperature,
                                        max_length
                                    )
    
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

#-- Define sidebar
# st.sidebar.header('', divider='rainbow')
st.sidebar.image(join(img_path, 'Dtgy.png'), width = 78, use_column_width = False)

#-- init mettrics
fl, la, co, re, hhem, adv_hhem = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
# Ask a question
if question := st.chat_input("Ask a question"):
    # Append user question to history
    st.session_state.history.append({"role": "user", "content": question})
    # Add user question
    with st.chat_message("user"):
        st.markdown(question)

    # Answer the question
    answer, doc_source, metrics_ = rag_functions.generate_answer(question, token)
    with st.chat_message("assistant"):
        st.write(answer)
    # Append assistant answer to history
    st.session_state.history.append({"role": "assistant", "content": answer})
    #--
    fl, la, co, re = metrics_['fluency'],\
                        metrics_['latency'],\
                            metrics_['coherence'],\
                                metrics_['relevance']
    st.session_state.source.append({"question": question, "answer": answer, "document": doc_source})

#-- Eval metrics w/ Latency
st.sidebar.title('Metrics')
st.sidebar.text(f"Fluency: {fl:.2f}")
st.sidebar.text(f'Coherence: {co:.2f}')
st.sidebar.text(f'Relevance: {re:.2f}')
st.sidebar.text(f'Latency: {la:.2f}-secs')
#-- Hallucination metrics
st.sidebar.text(f'HHEM: {hhem}')
st.sidebar.text(f'Adv-HHEM: {adv_hhem}')


#%% >Stop session while running to retrieve results...

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
    st.button("run", on_click = Running)
with col2:
    st.button("Stop", on_click = stopRunning)

with st.expander("Source documents"):
    st.write(st.session_state.source)

#-- convert conversation to downloadable formats...
json_string = json.dumps(st.session_state.source)

def convert_json_to_df(json_file):
    source_dict = {k:v for (k,v) in zip(range(len(json_file)), json_file)}
    dataframe = pd.DataFrame.from_dict(source_dict, orient = 'index').T
    return dataframe

data_frame = convert_json_to_df(json_string)

@st.cache_data
def convert_df(data_frame):
    #-- convert json --> pd.DataFrame
    return data_frame.to_csv().encode('utf-8')

# csv = convert_df(data_frame)
def xlxs(data):
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine="xlsxwriter")
    data.to_excel(writer, index = False,
                  sheet_name = "sheet1")
    writer.close()
    data_bytes = output.getvalue()
    return data_bytes

data_bytes = xlxs(data_frame)

st.sidebar.markdown("""<hr style="height:2px;border:none;color:#333;background-color:white;" /> """, unsafe_allow_html = True)
st.sidebar.title('Download chat')
#
st.sidebar.download_button(
                label = "json",
                file_name = "data.json",
                mime = "application/json",
                data = json_string,
            )

st.sidebar.download_button(
                label = "csv",
                file_name = "data.csv",
                # mime = "text/csv",
                data = convert_df(data_frame),
            )


st.sidebar.download_button(label = "xlsx",
    data = data_bytes,
    file_name = "data.xlsx")

#%%

# download_path = '/Users/kennethezukwoke/Downloads'
# with open(join(download_path, 'data.json'), 'rb') as filename:
#     docs = json.load(filename)
    
    
#%%

# #-- Preview metrics
# def metric(metrics):
#     fl, la, co, re = metrics['fluency'],\
#                         metrics['latency'],\
#                             metrics['coherence'],\
#                                 metrics['relevance']
#     st.sidebar.title('Metrics')
#     st.sidebar.text(f'Fluency: {fl:.2f}')
#     st.sidebar.text(f'Coherence: {co:.2f}')
#     st.sidebar.text(f'Relevance: {re:.2f}')
#     st.sidebar.text(f'Latency: {la:.2f} secs')

# # #-- Metrics
# metric(metrics_)
# def docPrevier(tabs, ):
#     pass

#%%


# if __name__ == "__main__":
#     #-- tabs
#     tab_a, tab_b, tab_c = st.tabs(["Customized chatbot",
#                                    "Document Embedding",
#                                    "Document previewer"])
#     #-- 
#     tabs = {'tabA': tab_a, 'tabB': tab_b, 'tabc': tab_c,}
#     embd_name = "sentence-transformers/all-mpnet-base-v2"
#     #-- llm_name = "MBZUAI/LaMini-Flan-T5-248M"
#     llm_name = 'MBZUAI/LaMini-GPT-774M'
#     #--Chatbot
#     customizedChatter(tabs, embd_name, llm_name)
#     #--load document embedding
#     document_embed(tabs)
#     #-- Toggle sidebar...
#     theme()
    
    