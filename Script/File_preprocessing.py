from langchain.text_splitter import RecursiveCharacterTextSplitter


from langchain.document_loaders import PyPDFLoader

def file_processing(file):
    # Load data from PDF
    loader=PyPDFLoader(file)
    documents = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=20)
    chunk_texts = text_splitter.split_documents(documents)

    return chunk_texts