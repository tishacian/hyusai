"""
Utility for keyword extraction.
"""

import re
from sklearn.feature_extraction.text import TfidfVectorizer
import nltk
from nltk.corpus import stopwords


def clean_text_for_tfidf(text: str) -> str:
    """Basic text cleaning for TF-IDF."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'\d+', '', text)  # Remove numbers
    text = re.sub(r'\s+', ' ', text) # Normalize whitespace
    # Remove punctuation but keep intra-word hyphens/apostrophes for phrases
    text = re.sub(r'(?<!\w)[^\w\s\'\-]+(?<!\w)|(?<=\w)[^\w\s\'\-]+(?=\w)', '', text)
    text = text.strip()
    return text

def get_stopwords(language: str = 'french') -> list[str]:
    """
    Get stopwords for the specified language.

    Args:
        language: Language code (default: 'french')

    Returns:
        List of stopwords for the specified language
    """
    # Ensure stopwords are downloaded
    if not nltk.data.find(f'corpora/stopwords', raise_on_error=False):
        nltk.download('stopwords', quiet=True)

    # Get stopwords for the specified language
    if language in stopwords.fileids():
        return list(stopwords.words(language))
    else:
        print(f"Stopwords for language '{language}' not available. Using empty stopwords list.")
        return []

def extract_keywords_tfidf(text: str, max_keywords: int = 10, language: str = 'french') -> list[str] | None:
    """
    Extract keywords from text using TF-IDF.

    Args:
        text: The input text.
        max_keywords: The maximum number of keywords to return.
        language: Language of the text for stopwords (default: 'french')

    Returns:
        A list of keywords, or None if text is empty.
    """
    if not text or not text.strip():
        return None

    cleaned_text = clean_text_for_tfidf(text)
    if not cleaned_text:
        return None

    # Get stopwords for the specified language
    stop_words = get_stopwords(language)

    vectorizer = TfidfVectorizer(
        stop_words=stop_words,
        max_features=max_keywords,
        ngram_range=(1, 2) # Consider unigrams and bigrams
    )

    vectorizer.fit_transform([cleaned_text])

    feature_names = vectorizer.get_feature_names_out()

    return list(feature_names)