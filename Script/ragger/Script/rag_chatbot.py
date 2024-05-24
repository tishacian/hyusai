import streamlit as st
import os
import rag_functions
import toml
from rag_metrics import (fluency,
                          coherence,
                          relevance,
                          latency,
                          factuality,
                          consistency,
                          HHEM,
                          Advance_HHEM,
                          )
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
                        ' size of the embedding space. The default is set to 512.'
                        }

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

def metric():
    st.sidebar.title('Metrics')
    st.sidebar.text('Fluency')
    st.sidebar.text('Coherence')
    st.sidebar.text('Relevance')
    st.sidebar.text('Latency')
    

#%% Document embedding...

#--Different columns for Embedding/Chat app
def document_embed():
    with st.expander('Document Embedding'):
        st.title("Document Embedding")
        st.markdown("This page is used to upload the documents as the custom knowledge for the chatbot.")
        instructio_embedding = ["hkunlp/instructor-xl", "sentence-transformers/all-mpnet-base-v2"]
        #--
        with st.form("document_input"):
            document = st.file_uploader("Knowledge Documents", type = ['pdf', 'txt'], help = ".pdf or .txt file")
    
            row_ae = st.columns([2, 1, 1])
            with row_ae[0]:
                instruct_embeddings = st.selectbox(
                    "Model Name of the Instruct Embeddings", instructio_embedding
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
theme()


# Setting the LLM
st.title("RAG Agent")
#--load document embedding
document_embed()
with st.expander("LLM Settings"):
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
            instruct_embeddings = st.text_input("Instruct Embeddings", value = embd_name,
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

# Ask a question
if question := st.chat_input("Ask a question"):
    # Append user question to history
    st.session_state.history.append({"role": "user", "content": question})
    # Add user question
    with st.chat_message("user"):
        st.markdown(question)

    # Answer the question
    answer, doc_source = rag_functions.generate_answer(question, token)
    with st.chat_message("assistant"):
        st.write(answer)
    # Append assistant answer to history
    st.session_state.history.append({"role": "assistant", "content": answer})

    # Append the document sources
    st.session_state.source.append({"question": question, "answer": answer, "document": doc_source})


# Source documents
with st.expander("Source documents"):
    st.write(st.session_state.source)
        
# def compute_scores(question, answer):
#     fluency = fluency(answer)
#     latency = latency(start_time, end_time)
#     coherence = coherence(answer)
#     relevance = relevance(question, answer)
    
#-- Metrics
metric()
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
    
    