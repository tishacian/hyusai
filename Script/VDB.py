import File_preprocessing as fp
from langchain.vectorstores import Chroma


def VDB(filepath,embeddings):
    chunk_texts=fp.file_processing(filepath)
    vector_store = Chroma.from_documents(chunk_texts, embeddings)
    return vector_store
