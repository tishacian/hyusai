from langchain_community.embeddings import HuggingFaceBgeEmbeddings

def Embeddings(embd_name):
    embd= HuggingFaceBgeEmbeddings(
        model_name=embd_name,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': False}
    )
    return embd