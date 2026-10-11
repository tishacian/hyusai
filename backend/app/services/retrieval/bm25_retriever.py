"""BM25 sparse retrieval"""
from typing import List, Dict
import re
import numpy as np
from collections import Counter
import math


class BM25Retriever:
    """BM25 sparse retrieval implementation"""
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Initialize BM25 retriever
        
        Args:
            k1: Term frequency saturation parameter
            b: Length normalization parameter
        """
        self.k1 = k1
        self.b = b
        self.documents: List[str] = []
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}
        self.avg_doc_len: float = 0.0
        self._fitted = False
    
    def fit(self, documents: List[str], document_ids: List[str] = None, document_metadatas: List[Dict] = None):
        """
        Fit BM25 on a collection of documents
        
        Args:
            documents: List of document texts
            document_ids: Optional list of document IDs (for compatibility with ensemble retriever)
            document_metadatas: Optional list of document metadatas (for compatibility with ensemble retriever)
        """
        self.documents = documents
        self.document_ids = document_ids or [f"doc_{i}" for i in range(len(documents))]
        self.document_metadatas = document_metadatas or [{}] * len(documents)
        self.doc_freqs = []
        doc_lens = []
        
        # Tokenize and count term frequencies for each document
        for doc in documents:
            tokens = self._tokenize(doc)
            doc_freq = Counter(tokens)
            self.doc_freqs.append(doc_freq)
            doc_lens.append(len(tokens))
        
        # Calculate average document length
        self.avg_doc_len = sum(doc_lens) / len(doc_lens) if doc_lens else 0.0
        
        # Calculate IDF (Inverse Document Frequency)
        doc_count = len(documents)
        term_doc_count = Counter()
        
        for doc_freq in self.doc_freqs:
            for term in doc_freq.keys():
                term_doc_count[term] += 1
        
        # Calculate IDF for each term
        for term, df in term_doc_count.items():
            # IDF = log((N - df + 0.5) / (df + 0.5))
            self.idf[term] = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)
        
        self._fitted = True
    
    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        Search documents using BM25
        
        Args:
            query: Search query
            top_k: Number of top results to return
            
        Returns:
            List of results with scores, sorted by relevance
        """
        if not self._fitted:
            raise ValueError("BM25 retriever must be fitted before searching")
        
        query_tokens = self._tokenize(query)
        scores = []
        
        for i, (doc, doc_freq) in enumerate(zip(self.documents, self.doc_freqs)):
            score = 0.0
            doc_len = sum(doc_freq.values())
            
            for term in query_tokens:
                if term in doc_freq:
                    # BM25 score calculation
                    tf = doc_freq[term]
                    idf = self.idf.get(term, 0.0)
                    
                    # BM25 formula
                    numerator = idf * tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_len))
                    
                    score += numerator / denominator
            
            scores.append({
                "index": i,
                "score": score,
                "content": doc,
            })
        
        # Sort by score descending
        scores.sort(key=lambda x: x["score"], reverse=True)
        
        # Return top_k results
        return scores[:top_k]
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into terms"""
        # Simple tokenization: lowercase, split on non-alphanumeric
        text = text.lower()
        tokens = re.findall(r'\b\w+\b', text)
        return tokens
    
    def get_document(self, index: int) -> str:
        """Get document by index"""
        if 0 <= index < len(self.documents):
            return self.documents[index]
        raise IndexError(f"Document index {index} out of range")
    
    def get_scores(self, query: str) -> np.ndarray:
        """
        Get BM25 scores for a query (returns numpy array for compatibility with ensemble retriever)
        
        Args:
            query: Search query
            
        Returns:
            numpy array of scores for all documents
        """
        if not self._fitted:
            raise ValueError("BM25 retriever must be fitted before getting scores")
        
        query_tokens = self._tokenize(query)
        scores = []
        
        for doc_freq in self.doc_freqs:
            score = 0.0
            doc_len = sum(doc_freq.values())
            
            for term in query_tokens:
                if term in doc_freq:
                    tf = doc_freq[term]
                    idf = self.idf.get(term, 0.0)
                    numerator = idf * tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_len))
                    score += numerator / denominator
            
            scores.append(score)
        
        return np.array(scores)

