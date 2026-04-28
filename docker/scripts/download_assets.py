from configurations import WorkerConfig
from src.init_utils import build_multilang_stopwords, download_nltk_data

if __name__ == "__main__":
    resources = WorkerConfig.get().resources
    download_nltk_data(download_dir=resources.nltk, quiet=True)
    build_multilang_stopwords(target_dir=resources.custom)
    print("NLTK data and multilingual stopwords have been downloaded and set up.")
