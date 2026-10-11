from configurations.config import Config
from src.init_utils import build_multilang_stopwords, download_nltk_data

if __name__ == "__main__":
    download_nltk_data(download_dir=Config.get().ressources.nltk_data, quiet=True)
    build_multilang_stopwords(target_dir=Config.get().ressources.custom)
    print("NLTK data and multilingual stopwords have been downloaded and set up.")
