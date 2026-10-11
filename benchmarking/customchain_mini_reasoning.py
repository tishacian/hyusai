import asyncio
import os
import pickle
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
import faiss
import numpy as np
import torch
import weaviate
from langchain_community.vectorstores import Chroma

from src.system_prompts.types import SystemPromptTypes

if torch.cuda.is_available():
    from vllm import SamplingParams

warnings.simplefilter(action="ignore", category=FutureWarning)

import logging
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cache import TieredCache
from src.chunker import BM25Retriever
from src.contextcompressor import ContextualCompressionRetriever, ContextualConfig
from src.conversationmemorybuffer import ConversationMemoryBuffer
from src.embedding import EmbeddingModelLoader
from src.ensembleretriever import EnsembleConfig, EnsembleRetriever, FusionMethod
from src.flashreranker import FlashReranker, RerankerConfig
from src.globalvariables import (
    DATA_PATH,
    EMBEDDING_NAME,
    LARGE_MODELS,
    MAX_MODEL_LEN,
    VECTOR_STORE_PATH,
    IndexType,
    ReasoningType,
)
from src.metrics import Evaluatrix
from src.reasoningmetrics import ReasoningMetrics
from src.retrievalplan import QueryAnalysis, RetrievalContext, RetrievalPlan
from src.trivial_check import is_trivial_question
from src.utils import (
    add_leading_space_if_needed,
    format_llm_response,
    get_max_model_len,
    load_stopwords,
    measure_time,
    measure_time_sync,
)

try:
    from src.system_prompts import (
        ALL_DEFAULT_SYSTEM_PROMPT_ROLE,
        ALL_SYSTEM_PROMPT_TEMPLATES,
        DEFAULT_SYSTEM_PROMPT_LANG,
        SystemPromptLangs,
    )
except ImportError:
    from enum import StrEnum

    class SystemPromptLangs(StrEnum):
        EN = "EN"
        FR = "FR"

    DEFAULT_SYSTEM_PROMPT_LANG = SystemPromptLangs.EN

    ALL_DEFAULT_SYSTEM_PROMPT_ROLE = {
        SystemPromptLangs.EN: " You are an expert AI assistant with advanced reasoning capabilities, specialized in analyzing complex questions and providing comprehensive, accurate responses. Your expertise spans multiple domains including factual analysis, comparative reasoning, causal relationships, and hypothetical scenarios. You excel at breaking down complex problems, identifying key patterns, and synthesizing information to deliver clear, well-structured answers that directly address the user's needs.",
        SystemPromptLangs.FR: "Vous êtes un assistant IA utile qui fournit des réponses précises et concises basées sur le contexte donné.",
    }

    from src.system_prompts.types import SystemPromptTypes

    ALL_SYSTEM_PROMPT_TEMPLATES = {
        SystemPromptLangs.EN: {
            SystemPromptTypes.FACTUAL: """[INST] You are an AI assistant specialized in providing precise and factual information.{assistant_role}
                                                Analysis Steps:
                                                1. Identify key facts from context
                                                2. Extract relevant information
                                                3. Verify factual consistency
                                                4. Present information clearly and concisely
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Provide a clear factual response based on the context: [/INST]""",
            SystemPromptTypes.ANALYTICAL: """[INST] You are an AI assistant specialized in detailed analysis.{assistant_role}
                                                Analysis Steps:
                                                1. Identify the core goal and constraints
                                                2. Break down key requirements and parameters
                                                3. Research factual information relevant to the query
                                                4. Verify accuracy of names, locations, and specific details
                                                5. Examine relationships between facts and context provided
                                                6. Synthesize insights relevant to user's situation
                                                7. Draw conclusions based on verified evidence
                                                                                               
                                                Context: {context}
                                                                                               
                                                Question: {question}
                                                                                               
                                                Provide a thorough analysis that combines factual accuracy with analytical insights based on the context: [/INST]""",
            SystemPromptTypes.COMPARATIVE: """[INST] You are an AI assistant specialized in comparative analysis.{assistant_role}
                                                Analysis Steps:
                                                1. Identify elements for comparison
                                                2. Examine similarities and differences
                                                3. Evaluate relative strengths/weaknesses
                                                4. Draw balanced conclusions
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Compare and contrast based on the context: [/INST]""",
            SystemPromptTypes.CAUSAL: """[INST] You are an AI assistant specialized in causal analysis.{assistant_role}
                                                Analysis Steps:
                                                1. Identify cause-effect relationships
                                                2. Examine contributing factors
                                                3. Analyze implications and consequences
                                                4. Establish causal chains
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Explain the causal relationships based on the context: [/INST]""",
            SystemPromptTypes.HYPOTHETICAL: """[INST] You are an AI assistant specialized in hypothetical reasoning.{assistant_role}
                                                Analysis Steps:
                                                1. Consider given conditions
                                                2. Analyze potential scenarios
                                                3. Evaluate implications
                                                4. Draw reasoned conclusions
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Explore this scenario based on the context: [/INST]""",
            SystemPromptTypes.NAIVE: """[INST] You are an AI assistant specialized in providing precise and detailed information.{assistant_role}
                                                Focus on important information that directly addresses the main topic or question.
                                                Include relevant details that provide context or support your points.
                                                Ensure the information is engaging by highlighting unique accuracy, precision, completeness, conciseness, clarity, relevance, objectivity, and emotional resonance.

                                                Your task is to answer the following question based on the given context:
                                                {context}

                                                Question: {question}

                                                Answer: [/INST]""",
            SystemPromptTypes.TRIVIAL: """[INST] You are a friendly conversational assistant.{assistant_role} If there is any previous conversation below, keep it in mind. Otherwise just answer the user's short message naturally (greeting, thanks, farewell, etc.). Do NOT provide additional information beyond what is appropriate for the user's message.

{context}

User: {question}
Assistant: [/INST]""",
        },
        SystemPromptLangs.FR: {
            "default": "Répondez à la question suivante basée sur le contexte: {question}"
        },
    }

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class CustomLLMChain:
    def __init__(
        self,
        tokenizer,
        model,
        model_name,
        vector_store_name,
        embedding_model_name=EMBEDDING_NAME,
        index_type=IndexType.FAISS,
        cache_size=1000,
        dynamic_k=True,
        instruction_lang: SystemPromptLangs = DEFAULT_SYSTEM_PROMPT_LANG,
    ):
        """Initialize CustomLLMChain with retrieval capabilities

        Parameters:
            tokenizer: Tokenizer
            model: Model
            model_name: str
            vector_store_name: str
        """
        start_time = time.time()

        self.tokenizer = tokenizer
        self.model = model
        self.model_name = model_name
        self.vector_store_name = vector_store_name
        self.dynamic_k = dynamic_k
        self.is_large_model = self.model_name in LARGE_MODELS
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        self.max_input_ratio = 0.8 if self.is_large_model else 0.75

        if self.model is None or self.tokenizer is None:
            raise ValueError(
                f"Failed to load model or tokenizer. Model: {self.model}, Tokenizer: {self.tokenizer}"
            )

        self.index_type = index_type
        self.instruction_lang = instruction_lang
        self.stopwords = load_stopwords(DATA_PATH)
        self.max_model_len = get_max_model_len(self.model_name, MAX_MODEL_LEN)
        self.embedding_model_name = embedding_model_name

        self.tiered_cache = TieredCache(l1_size=cache_size, l2_size=cache_size * 10)
        self.context_cache = self.tiered_cache.l1_cache

        self.conversation_memory = ConversationMemoryBuffer(max_turns=3)

        self.embedding_semaphore = asyncio.Semaphore(5)
        self.retrieval_semaphore = asyncio.Semaphore(3)

        try:
            load_embedding_start = time.time()
            self.embedding_model = EmbeddingModelLoader.load_embedding_model(
                self.index_type, self.embedding_model_name
            )
            load_embedding_time = time.time() - load_embedding_start
            logging.info(
                f"Successfully loaded embedding model: {self.embedding_model_name} in {load_embedding_time:.4f} seconds"
            )
        except Exception as e:
            logging.error(f"Error loading embedding model: {e}")
            raise

        self.reasoning_metrics = ReasoningMetrics(
            self.embedding_model, self.instruction_lang
        )

        self._initialize_retrievers()
        self._initialize_reranker()
        self._initialize_contextual_retriever()

        self.templates = ALL_SYSTEM_PROMPT_TEMPLATES[self.instruction_lang]
        self.assistant_role = ALL_DEFAULT_SYSTEM_PROMPT_ROLE[self.instruction_lang]
        self.assistant_role = add_leading_space_if_needed(self.assistant_role)
        self.executor = ThreadPoolExecutor(max_workers=os.cpu_count())

        self.perf_stats = {
            "total_calls": 0,
            "avg_response_time": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

        init_time = time.time() - start_time
        logging.info(
            f"mini-CustomLLMChain initialization completed in {init_time:.4f} seconds"
        )

    @measure_time_sync
    def _initialize_retrievers(self):
        """Initialize retriever components

        Returns:
            None
        """
        try:
            vector_store_path = VECTOR_STORE_PATH / self.vector_store_name
            self.bm25_retriever = BM25Retriever.load_bm25(
                vector_store_path / "bm25_retriever.pkl"
            )
            self.texts = []

            if self.index_type == IndexType.FAISS:
                if os.path.exists(
                    str(vector_store_path / "faiss.index")
                ) and os.path.exists(str(vector_store_path / "faiss.pkl")):
                    self.dense_retriever = faiss.read_index(
                        str(vector_store_path / "faiss.index")
                    )
                    with open(str(vector_store_path / "faiss.pkl"), "rb") as f:
                        self.texts = pickle.load(f)
                    logging.info("FAISS index and texts loaded successfully.")
                else:
                    raise FileNotFoundError(
                        "FAISS index or texts file not found. Please create an index first."
                    )
            elif self.index_type == IndexType.CHROMA:
                self.dense_retriever = Chroma(
                    persist_directory=str(vector_store_path),
                    embedding_function=self.embedding_model,
                )
                logging.info("Chroma index loaded successfully.")
            elif self.index_type == IndexType.WEAVIATE:
                self.dense_retriever = weaviate.Client("http://localhost:8080")
                self.class_name = "Document"
                if not self.dense_retriever.schema.contains(self.class_name):
                    raise ValueError(
                        "Weaviate index not found. Please create an index first."
                    )
                logging.info("Weaviate index loaded successfully.")
            else:
                raise ValueError(
                    "Unsupported index type. Choose 'faiss', 'chroma', or 'weaviate'."
                )

            self.ensemble_retriever = EnsembleRetriever(
                bm25_retriever=self.bm25_retriever,
                dense_retriever=self.dense_retriever,
                embedding_model=self.embedding_model,
                texts=self.texts,
                config=EnsembleConfig(),
            )

        except Exception as e:
            logging.error(f"Error initializing retrievers: {e}")
            raise

    def _initialize_reranker(self):
        """Initialize FlashReranker component

        Returns:
            FlashReranker: Flash reranker
        """
        try:
            self.reranker = FlashReranker(RerankerConfig())
        except Exception as e:
            logging.error(f"Error initializing reranker: {e}")
            raise

    def _initialize_contextual_retriever(self):
        """Initialize ContextualCompressionRetriever component

        Returns:
            ContextualCompressionRetriever: Contextual compression retriever
        """
        try:
            self.contextual_retriever = ContextualCompressionRetriever(
                base_retriever=self.ensemble_retriever,
                reranker=self.reranker,
                config=ContextualConfig(k=5, compression_ratio=0.7),
            )
        except Exception as e:
            logging.error(f"Error initializing contextual retriever: {e}")
            raise

    async def analyze_query(self, question: str) -> QueryAnalysis:
        """Comprehensive query analysis to determine optimal retrieval parameters"""
        has_multiple_questions = len(re.findall(r"\?", question)) > 1
        word_count = len(question.split())

        if has_multiple_questions or word_count > 20:
            k_value, lambda_param = 7, 0.6
            complexity = 0.8
        elif word_count > 10:
            k_value, lambda_param = 5, 0.5
            complexity = 0.5
        else:
            k_value, lambda_param = 3, 0.4
            complexity = 0.3

        query_characteristics = self.ensemble_retriever._analyze_query_characteristics(
            question
        )

        reasoning_type, reasoning_confidence = await self.detect_reasoning_type(
            question
        )

        question_embedding = await self.create_embeddings_async([question])
        if question_embedding.size > 0 and len(question_embedding.shape) == 1:
            question_embedding = question_embedding.reshape(1, -1)

        analysis = QueryAnalysis(
            complexity=complexity,
            k_value=k_value,
            lambda_param=lambda_param,
            has_multiple_questions=has_multiple_questions,
            word_count=word_count,
            query_characteristics=query_characteristics,
            reasoning_type=reasoning_type,
            reasoning_confidence=reasoning_confidence,
            embedding=question_embedding,
        )

        return analysis

    async def detect_reasoning_type(self, question: str):
        """Reasoning detection with confidence score

        Parameters:
            question: str

        Returns:
            tuple: Reasoning type, Confidence score
        """
        cache_key = f"reasoning_{question[:50]}"
        cached_result = self.tiered_cache.get(cache_key)
        if cached_result:
            return cached_result

        try:
            result = await self.reasoning_metrics.bayesian_reasoning_detection_async(
                question
            )

            if isinstance(result, tuple) and len(result) == 2:
                reasoning_type, confidence = result
                if isinstance(reasoning_type, str):
                    try:
                        reasoning_type = ReasoningType(reasoning_type)
                    except KeyError:
                        reasoning_type = ReasoningType.ANALYTICAL
            elif isinstance(result, ReasoningType):
                reasoning_type, confidence = result, 0.8
            elif isinstance(result, str):
                try:
                    reasoning_type = ReasoningType(result)
                    confidence = 0.8
                except KeyError:
                    reasoning_type = ReasoningType.ANALYTICAL
                    confidence = 0.6
            else:
                reasoning_type = ReasoningType.ANALYTICAL
                confidence = 0.6

            valid_types = {
                ReasoningType.FACTUAL,
                ReasoningType.ANALYTICAL,
                ReasoningType.COMPARATIVE,
                ReasoningType.CAUSAL,
                ReasoningType.HYPOTHETICAL,
            }

            if reasoning_type not in valid_types:
                reasoning_type = ReasoningType.ANALYTICAL

            result_tuple = (reasoning_type, confidence)
            self.tiered_cache.set(cache_key, result_tuple)
            return result_tuple

        except Exception as e:
            logging.error(f"Error in reasoning detection: {e}")
            return (ReasoningType.ANALYTICAL, 0.6)

    async def create_embeddings_async(self, texts):
        """Asynchronous version of create_embeddings with caching and batching

        Parameters:
            texts: list

        Returns:
            np.array: Embeddings
        """
        if not texts:
            return np.array([])

        async with self.embedding_semaphore:
            if len(texts) == 1:
                text_key = texts[0][:100]
                cached_embedding = self.tiered_cache.get_embedding(text_key)
                if cached_embedding is not None:
                    self.perf_stats["cache_hits"] += 1
                    return cached_embedding
                self.perf_stats["cache_misses"] += 1

            try:
                if torch.cuda.is_available():
                    batch_size = 32
                    if len(texts) > batch_size:
                        all_embeddings = []
                        for i in range(0, len(texts), batch_size):
                            batch_texts = texts[i : i + batch_size]
                            with torch.no_grad():
                                batch_embeddings = self.embedding_model.encode(
                                    batch_texts,
                                    convert_to_tensor=True,
                                    show_progress_bar=False,
                                    device=self.device.type,
                                )
                                all_embeddings.append(batch_embeddings.cpu().numpy())
                        embeddings = np.vstack(all_embeddings)
                    else:
                        with torch.no_grad():
                            embeddings = self.embedding_model.encode(
                                texts,
                                convert_to_tensor=True,
                                show_progress_bar=False,
                                device=self.device.type,
                            )
                            embeddings = embeddings.cpu().numpy()
                else:
                    if self.index_type == IndexType.CHROMA:
                        embeddings = np.array(
                            self.embedding_model.embed_documents(texts)
                        )
                    elif self.index_type in [
                        IndexType.FAISS,
                        IndexType.WEAVIATE,
                    ]:
                        try:
                            embeddings = self.embedding_model.encode(
                                texts,
                                convert_to_tensor=True,
                                show_progress_bar=False,
                                device=self.device.type,
                            )
                            embeddings = (
                                embeddings.to(dtype=torch.float32).cpu().numpy()
                            )
                        except IndexError as e:
                            logging.error(f"Index out of range error: {e}")
                            return np.array([])
                    else:
                        logging.error(f"Unsupported embedding type: {self.index_type}")
                        return np.array([])

                if len(texts) == 1:
                    self.tiered_cache.set_embedding(text_key, embeddings)

                return embeddings

            except Exception as e:
                logging.error(f"Error creating embeddings: {e}")
                return np.array([])

    @measure_time
    async def parallel_composite_retrieval(
        self,
        question: str,
        k: int = 5,
        lambda_param: float = 0.5,
        use_query_expansion: bool = False,
        use_bm25_retriever: bool = False,
    ):
        """Mixed retrieval strategies in parallel

        Parameters:
            question: str
            k: int
            lambda_param: float
            use_query_expansion: bool
            use_bm25_retriever: bool

        Returns:
            list: Contexts
        """
        async with self.retrieval_semaphore:
            query_embedding = await self.create_embeddings_async([question])
            if query_embedding.size > 0 and len(query_embedding.shape) == 1:
                query_embedding = query_embedding.reshape(1, -1)

            expanded_queries = await self.expand_query(
                question, use_expansion=use_query_expansion
            )

            all_contexts = []
            retrieval_tasks = []

            retrieval_tasks.append(
                self.contextual_retriever.retrieve_and_compress(question, k)
            )

            if len(expanded_queries) > 1:
                for expanded_q in expanded_queries[1:]:
                    retrieval_tasks.append(
                        self.contextual_retriever.retrieve_and_compress(
                            expanded_q, max(3, k // 2)
                        )
                    )

            if use_bm25_retriever:
                retrieval_tasks.append(self.bm25_retrieve(question, k=k))

            results = await asyncio.gather(*retrieval_tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.error(f"Retrieval error in strategy {i}: {result}")
                    continue

                if i == 0 or (i < len(expanded_queries) and i > 0):
                    if isinstance(result, tuple) and len(result) == 2:
                        contexts, scores = result
                        is_expanded = i > 0

                        for j, (ctx, score) in enumerate(zip(contexts, scores)):
                            query_expansion_wt = 0.9 if is_expanded else 1.0
                            retrieval_ctx = RetrievalContext(
                                text=ctx,
                                score=score * query_expansion_wt,
                                relevance_score=score * (0.9 if is_expanded else 1.0),
                                metadata={
                                    "source": (
                                        "expanded" if is_expanded else "contextual"
                                    ),
                                    "rank": j,
                                },
                            )
                            all_contexts.append(retrieval_ctx)

            if not all_contexts:
                return []

            unique_texts = []
            text_to_idx = {}
            for i, ctx in enumerate(all_contexts):
                if ctx.text not in text_to_idx:
                    text_to_idx[ctx.text] = len(unique_texts)
                    unique_texts.append(ctx.text)

            if unique_texts:
                context_embeddings = await self.create_embeddings_async(unique_texts)

                for ctx in all_contexts:
                    idx = text_to_idx[ctx.text]
                    if len(context_embeddings.shape) == 1:
                        ctx.embedding = context_embeddings.reshape(1, -1)
                    else:
                        ctx.embedding = context_embeddings[idx].reshape(1, -1)

            # -- compute diversity scores
            if len(context_embeddings.shape) == 1:
                context_embeddings = context_embeddings.reshape(1, -1)
            diversity_matrix = np.dot(context_embeddings, context_embeddings.T)
            np.fill_diagonal(diversity_matrix, 0)
            for i, ctx in enumerate(unique_texts):
                idx = text_to_idx[ctx]
                row_sum = np.sum(diversity_matrix[idx])
                row_count = max(1, len(unique_texts) - 1)
                diversity_score = 1 - (row_sum / row_count)

                for context in all_contexts:
                    if context.text == ctx:
                        context.diversity_score = float(diversity_score)

            # -- compute reasoning scores
            if hasattr(self, "reasoning_metrics"):
                reasoning_type, _ = await self.detect_reasoning_type(question)

                async def compute_reasoning_score(ctx):
                    try:
                        score = (
                            await self.reasoning_metrics.compute_reasoning_score_async(
                                question, ctx.text, reasoning_type
                            )
                        )
                        return ctx, score
                    except Exception as e:
                        logging.error(f"Error computing reasoning score: {e}")
                        return ctx, 0.5

                reasoning_tasks = [compute_reasoning_score(ctx) for ctx in all_contexts]
                reasoning_results = await asyncio.gather(*reasoning_tasks)

                for ctx, score in reasoning_results:
                    for c in all_contexts:
                        if c.text == ctx.text:
                            c.reasoning_score = score

            # -- compute final scores
            for ctx in all_contexts:
                ctx.score = (
                    lambda_param * ctx.relevance_score
                    + (1 - lambda_param) * ctx.diversity_score
                    + 0.2 * ctx.reasoning_score
                )

            # Deduplicate and sort
            seen_texts = {}
            for ctx in all_contexts:
                if ctx.text not in seen_texts or ctx.score > seen_texts[ctx.text].score:
                    seen_texts[ctx.text] = ctx

            unique_contexts = list(seen_texts.values())
            unique_contexts.sort(key=lambda x: x.score, reverse=True)
            return unique_contexts[:k]

    async def expand_query(self, question: str, use_expansion: bool = False):
        """Expand query with related terms to improve retrieval

        Parameters:
            question: str
            use_expansion: bool

        Returns:
            list: Expanded queries
        """
        if not use_expansion:
            return [question]

        words = question.lower().split()
        key_terms = [w for w in words if w not in self.stopwords and len(w) > 3]

        expanded_queries = [question]

        if len(key_terms) >= 2:
            for i in range(len(key_terms)):
                for j in range(i + 1, len(key_terms)):
                    expanded_queries.append(f"{key_terms[i]} {key_terms[j]}")

        for term in key_terms:
            if term not in expanded_queries and len(term) > 4:
                expanded_queries.append(term)

        return expanded_queries[:3]

    async def bm25_retrieve(self, query, k=5):
        """Retrieve from BM25 using the same approach as EnsembleRetriever

        Parameters:
            query: str
            k: int

        Returns:
            list: Passages
        """
        try:
            scores = await asyncio.to_thread(self.bm25_retriever.get_scores, query)
            top_k_indices = np.argsort(scores)[-k:][::-1]
            if hasattr(self.bm25_retriever, "documents"):
                passages = [self.bm25_retriever.documents[idx] for idx in top_k_indices]
            else:
                passages = [
                    self.texts[idx] for idx in top_k_indices if idx < len(self.texts)
                ]

            return passages

        except Exception as e:
            logging.error(f"Error in BM25 retrieval: {e}")
            try:
                (
                    bm25_passages,
                    bm25_scores,
                    _,
                ) = await self.ensemble_retriever._get_bm25_scores(query, k)
                return bm25_passages
            except Exception as e2:
                logging.error(f"Fallback BM25 retrieval also failed: {e2}")
                return []

    @measure_time
    async def search_similar_texts_async(self, chunk, k=5, lambda_param=0.5):
        """Search with reasoning scores

        Parameters:
            chunk: str
            k: int
            lambda_param: float
        """
        cache_key = f"{chunk[:100]}_{k}"
        if cache_key in self.context_cache:
            return self.context_cache[cache_key]

        contexts = await self.parallel_composite_retrieval(
            chunk,
            k=k,
            lambda_param=lambda_param,
            use_query_expansion=lambda_param > 0.6,
        )

        result = [ctx.text for ctx in contexts]
        self.context_cache[cache_key] = result
        return result

    @measure_time
    async def parallel_search(self, document, k=5):
        """Parallel search with improved concurrency

        Parameters:
            document: str
            k: int
        """
        chunks = self.chunk_document(document, k)

        async def safe_search(chunk):
            try:
                return await self.search_similar_texts_async(chunk, k)
            except Exception as e:
                logging.error(f"Error searching for chunk: {e}")
                return []

        results = await asyncio.gather(*[safe_search(chunk) for chunk in chunks])
        return self.merge_results(results, k)

    def chunk_document(self, document, num_chunks=3):
        """Split the document into sub-chunks for parallel processing

        Parameters:
            document: str
            num_chunks: int
        """
        words = document.split()
        chunk_size = max(1, len(words) // num_chunks)
        return [
            " ".join(words[i : i + chunk_size])
            for i in range(0, len(words), chunk_size)
        ]

    def merge_results(self, results, k):
        """Merge top-k results from parallel searches with deduplication

        Parameters:
            results: list
            k: int
        """
        all_docs = []
        for result in results:
            all_docs.extend(result)

        seen = set()
        merged = []
        for doc in all_docs:
            if doc not in seen:
                seen.add(doc)
                merged.append(doc)

        return merged[:k]

    @measure_time
    async def search_similar_texts(self, question, k=5):
        """Parallelized version of search_similar_texts

        Parameters:
            question: str
            k: int

        Returns:
            list: Similar texts
        """
        return await self.parallel_search(question, k)

    def run_async_in_thread(self, coro):
        """Run an async coroutine in a separate thread with proper cleanup

        Parameters:
            coro: async coroutine
        """

        def wrapper():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()

                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )

                loop.close()

        with ThreadPoolExecutor() as executor:
            future = executor.submit(wrapper)
            return future.result()

    @measure_time
    async def generate_text(
        self, prompt, temperature=1e-12, max_length=None, top_p=0.95, top_k=50
    ):
        """Text generation focusing on prefill efficiency with dynamic token allocation

        Parameters:
            prompt: str
            temperature: float
            max_length: int
            top_p: float
            top_k: int
        """
        is_large_model = getattr(self, "is_large_model", False)
        max_input_length = int(self.max_model_len * self.max_input_ratio)

        cache_key = f"token_count_{prompt[:50]}"
        cached_length = self.tiered_cache.get(cache_key, cache_level=1)

        if cached_length:
            input_length = cached_length
        else:
            input_tokens = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=max_input_length,
            )
            input_length = input_tokens["input_ids"].shape[1]
            self.tiered_cache.set(cache_key, input_length, cache_level=1)

        default_new_tokens = self._compute_dynamic_tokens(
            input_length, self.max_model_len
        )
        max_new_tokens = default_new_tokens if max_length is None else max_length
        freq_penalty = self._calculate_frequency_penalty(input_length)

        if torch.cuda.is_available():
            sampling_params = SamplingParams(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_tokens=max_new_tokens,
                stop=[
                    "[INST]",
                    "[/INST]",
                    "<INST>",
                    "</INST>",
                    "<|assistant|>",
                    "</s>",
                    "[END]",
                ],
                frequency_penalty=freq_penalty,
                presence_penalty=0.1,
                repetition_penalty=1.15 if not is_large_model else 1.05,
            )
            try:
                with torch.inference_mode():
                    outputs = await asyncio.to_thread(
                        self.model.generate,
                        [prompt],
                        sampling_params,
                    )
                    generated_text = outputs[0].outputs[0].text.strip()
                    return generated_text
            except Exception as e:
                logging.error(f"Error in GPU generation: {e}")
                return (
                    "I apologize, but I encountered an error processing your request."
                )
        else:
            formatted_prompt = f"""### Instruction: {prompt}"""
            try:
                output = await asyncio.to_thread(
                    self.model.create_completion,
                    prompt=formatted_prompt,
                    max_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    presence_penalty=0.1,
                    frequency_penalty=freq_penalty,
                    stop=["###"],
                    stream=False,
                )
                if isinstance(output, dict):
                    response = output.get("choices", [{}])[0].get("text", "").strip()
                else:
                    response = output.choices[0].text.strip()
                return response
            except Exception as e:
                logging.error(f"CPU generation error: {e}")
                return "I apologize, but I encountered an error generating a response."

    def _calculate_frequency_penalty(self, input_length: int) -> float:
        """Calculate appropriate frequency penalty based on input length"""
        SHORT_CONTEXT = 512
        MEDIUM_CONTEXT = 1024

        SHORT_PENALTY = 0.01
        MEDIUM_PENALTY = 0.05
        LONG_PENALTY = 0.10

        if input_length <= SHORT_CONTEXT:
            return SHORT_PENALTY
        elif input_length <= MEDIUM_CONTEXT:
            return MEDIUM_PENALTY
        else:
            return LONG_PENALTY

    def _compute_dynamic_tokens(self, input_len: int, max_input_length: int) -> int:
        """
        Compute dynamic token allocation based on context ratio

        Parameters:
            input_len: int
            max_input_length: int

        Returns:
            int: Dynamic token allocation
        """
        context_ratio = input_len / max_input_length

        if 0 <= context_ratio < 0.4:
            return 8 * 1024
        elif 0.4 <= context_ratio < 0.55:
            return 7 * 1024
        elif 0.55 <= context_ratio < 0.625:
            return 6 * 1024
        elif 0.625 <= context_ratio < 0.7:
            return 5 * 1024
        elif 0.7 <= context_ratio < 0.78:
            return 4 * 1024
        elif 0.78 <= context_ratio < 0.86:
            return 3 * 1024
        elif 0.86 <= context_ratio < 0.94:
            return 2.5 * 1024
        elif 0.94 <= context_ratio <= 1.0:
            return 2 * 1024
        else:
            return 2 * 1024

    @measure_time
    async def custom_llm_chain(self, context, question, is_trivial: bool = False):
        """
        Custom LLM chain with reasoning capabilities and fallback mechanisms

        Parameters:
            context: str
            question: str
            is_trivial: bool
        """
        try:
            if is_trivial:
                reasoning_type = SystemPromptTypes.TRIVIAL
            else:
                reasoning_detect_start = time.time()
                if not hasattr(self, "reasoning_metrics"):
                    self.reasoning_metrics = ReasoningMetrics(
                        self.embedding_model, self.instruction_lang
                    )

                reasoning_type, confidence = await self.detect_reasoning_type(question)
                reasoning_time = time.time() - reasoning_detect_start
                logging.info(f"Reasoning detection took {reasoning_time:.4f} seconds")

            template = self.templates[reasoning_type]
            prompt_format = template.format(
                assistant_role=self.assistant_role, context=context, question=question
            )

            generate_start = time.time()
            generated_text = await self.generate_text(prompt_format)
            generate_time = time.time() - generate_start
            logging.info(f"Text generation took {generate_time:.4f} seconds")

            if (
                not generated_text or len(generated_text.split()) < 10
            ) and not is_trivial:
                raise ValueError(
                    "Primary generation failed or produced short response."
                )

            return generated_text

        except Exception as e:
            logging.error(f"Error in custom_llm_chain: {str(e)}")
            try:
                fallback_reasoning_type = ReasoningType.ANALYTICAL
                template = self.templates[fallback_reasoning_type]
                prompt_format = template.format(
                    assistant_role=self.assistant_role,
                    context=context,
                    question=question,
                )
                return await self.generate_text(prompt_format)
            except Exception:
                return (
                    "I apologize, but I encountered an error processing your request."
                )

    @measure_time
    async def invoke_async(self, question: str):
        """Invoke conversation memory buffer with hyper-parallel retrieval and adaptive context assembly

        Parameters:
            question: str

        Returns:
            tuple: answer, combined_context, eval_metrics
        """
        overall_start = time.time()

        try:
            # Trivial question bypass
            if is_trivial_question(question, self.instruction_lang):
                await asyncio.to_thread(
                    self.conversation_memory.add_message, "user", question
                )

                conversation_context = await asyncio.to_thread(
                    self.conversation_memory.get_context_with_reasoning,
                    SystemPromptTypes.TRIVIAL,
                )

                combined_context = conversation_context or ""

                generation_start = time.time()
                result_text = await self.custom_llm_chain(
                    combined_context, question, is_trivial=True
                )
                answer = self._format_llm_response(result_text)

                await asyncio.to_thread(
                    self.conversation_memory.add_message, "assistant", answer
                )

                generation_time = time.time() - generation_start
                logging.info(
                    f"[Trivial-Bypass] Response generation took {generation_time:.4f} seconds"
                )

                overall_time = time.time() - overall_start
                logging.info(
                    f"[Trivial-Bypass] Total invoke_async execution took {overall_time:.4f} seconds"
                )

                return answer, combined_context, {}

            memory_task = asyncio.create_task(
                asyncio.to_thread(
                    self.conversation_memory.add_message, "user", question
                )
            )

            query_analysis_task = asyncio.create_task(self.analyze_query(question))

            await memory_task
            query_analysis = await query_analysis_task

            conversation_context_task = asyncio.create_task(
                asyncio.to_thread(
                    self.conversation_memory.get_context_with_reasoning,
                    query_analysis.reasoning_type,
                )
            )

            retrieval_plan = RetrievalPlan.from_query_analysis(
                query_analysis, self.is_large_model
            )

            self.set_ensemble_fusion_method(retrieval_plan.fusion_method)

            conversation_context = await conversation_context_task

            query_with_context = (
                question + " " + conversation_context
                if conversation_context
                else question
            )

            retrieval_start = time.time()

            initial_contexts = await self.parallel_composite_retrieval(
                question,
                k=retrieval_plan.primary_k,
                lambda_param=query_analysis.lambda_param,
                use_query_expansion=retrieval_plan.use_query_expansion,
            )

            if not initial_contexts:
                no_context_response = (
                    "No relevant context found to answer the question."
                )
                self.conversation_memory.add_message("assistant", no_context_response)
                return no_context_response, "", {}

            filtered_contexts = initial_contexts
            if conversation_context:
                filtered_contexts = await self.context_filtering(
                    [
                        ctx.text
                        for ctx in initial_contexts[: min(50, len(initial_contexts))]
                    ],
                    query_with_context,
                )
                filtered_contexts = [
                    ctx for ctx in initial_contexts if ctx.text in filtered_contexts
                ]

            document = ". ".join(
                [
                    ctx.text
                    for ctx in filtered_contexts[: min(10, len(filtered_contexts))]
                ]
            )

            secondary_contexts_task = asyncio.create_task(
                self.parallel_composite_retrieval(
                    document,
                    k=retrieval_plan.secondary_k,
                    lambda_param=query_analysis.lambda_param,
                )
            )

            secondary_contexts = await secondary_contexts_task

            all_contexts = []
            seen_texts = set()

            for ctx in initial_contexts:
                if ctx.text not in seen_texts:
                    seen_texts.add(ctx.text)
                    all_contexts.append(ctx)

            for ctx in secondary_contexts:
                if ctx.text not in seen_texts:
                    seen_texts.add(ctx.text)
                    all_contexts.append(ctx)

            retrieval_time = time.time() - retrieval_start
            logging.info(f"Total retrieval took {retrieval_time:.4f} seconds")

            context_build_start = time.time()
            combined_context = await self.assemble_context(
                all_contexts, conversation_context, query_analysis
            )
            context_build_time = time.time() - context_build_start
            logging.info(f"Context assembly took {context_build_time:.4f} seconds")

            generation_start = time.time()
            result_text = await self.custom_llm_chain(
                combined_context, question, is_trivial=False
            )
            answer = self._format_llm_response(result_text, self.instruction_lang)

            await asyncio.to_thread(
                self.conversation_memory.add_message, "assistant", answer
            )
            generation_time = time.time() - generation_start
            logging.info(f"Response generation took {generation_time:.4f} seconds")

            eval_start = time.time()
            try:
                eval_metrics = await Evaluatrix(
                    answer,
                    combined_context,
                    self.tokenizer,
                    self.model,
                    self.embedding_model,
                    question,
                    method="ngram",
                    n_gram=3,
                )

                if eval_metrics is None:
                    eval_metrics = {}
                elif not isinstance(eval_metrics, dict):
                    eval_metrics = {"evaluation_error": str(eval_metrics)}

            except Exception as e:
                logging.error(f"Error in metrics evaluation: {e}")
                eval_metrics = {"error": str(e)}
            eval_time = time.time() - eval_start
            logging.info(f"Metrics evaluation took {eval_time:.4f} seconds")

            overall_time = time.time() - overall_start
            self.perf_stats["total_calls"] += 1
            self.perf_stats["avg_response_time"] = (
                self.perf_stats["avg_response_time"]
                * (self.perf_stats["total_calls"] - 1)
                + overall_time
            ) / self.perf_stats["total_calls"]
            logging.info(
                f"Total invoke_async execution took {overall_time:.4f} seconds"
            )

            return answer, combined_context, eval_metrics

        except Exception as e:
            error_msg = f"Error in invoke_async: {str(e)}"
            logging.error(error_msg)

            try:
                self.conversation_memory.add_message(
                    "assistant",
                    "I apologize, but I encountered an error processing your request.",
                )
            except Exception:
                pass

            return error_msg, "", {}

    @measure_time_sync
    def ainvoke(self, question):
        """
        Synchronous wrapper for invoke_async

        Parameters:
            question: str

        Returns:
            tuple: answer, combined_context, eval_metrics
        """
        return self.run_async_in_thread(self.invoke_async(question))

    @staticmethod
    def _format_llm_response(
        response: str, language: SystemPromptLangs = DEFAULT_SYSTEM_PROMPT_LANG
    ) -> str:
        """
        Format LLM response while preserving tables and structured data.

        Parameters:
            response: str
            language: SystemPromptLangs

        Returns:
            str: Formatted LLM response
        """
        return format_llm_response(response, language)

    def set_ensemble_fusion_method(self, method: FusionMethod):
        """
        Switch ensemble fusion method dynamically

        Parameters:
            method: FusionMethod
        """
        if hasattr(self, "ensemble_retriever"):
            self.ensemble_retriever.set_fusion_method(method)
            logging.info(f"Ensemble fusion method changed to: {method.value}")
        else:
            logging.error("Ensemble retriever not initialized")

    async def context_filtering(self, contexts, question):
        """Enhanced context filtering with relevance scoring and diversity analysis

        Parameters:
            contexts: list
            question: str

        Returns:
            list: Filtered contexts
        """
        try:
            if not contexts:
                return []

            retrieval_contexts = []
            for i, ctx in enumerate(contexts):
                retrieval_contexts.append(
                    RetrievalContext(text=ctx, score=1.0, metadata={"rank": i})
                )

            question_embedding = await self.create_embeddings_async([question])
            if question_embedding.size > 0:
                if len(question_embedding.shape) == 1:
                    question_embedding = question_embedding.reshape(1, -1)

            context_embeddings = await self.create_embeddings_async(contexts)

            if context_embeddings.size > 0 and question_embedding.size > 0:
                relevance_scores = np.dot(
                    context_embeddings, question_embedding.T
                ).squeeze()
                diversity_matrix = np.dot(context_embeddings, context_embeddings.T)
                np.fill_diagonal(diversity_matrix, 0)
                diversity_scores = 1 - (
                    np.sum(diversity_matrix, axis=1) / max(1, len(contexts) - 1)
                )

                if len(relevance_scores.shape) == 0:
                    relevance_scores = np.array([float(relevance_scores)])
                if len(diversity_scores.shape) == 0:
                    diversity_scores = np.array([float(diversity_scores)])

                for i, ctx in enumerate(retrieval_contexts):
                    ctx.relevance_score = float(relevance_scores[i])
                    ctx.diversity_score = float(diversity_scores[i])
                    ctx.score = 0.7 * ctx.relevance_score + 0.3 * ctx.diversity_score

            retrieval_contexts.sort(key=lambda x: x.score, reverse=True)
            return [ctx.text for ctx in retrieval_contexts]

        except Exception as e:
            logging.error(f"Error in context filtering: {e}")
            return contexts

    @measure_time
    async def assemble_context(
        self, contexts, conversation_context, query_analysis=None
    ):
        """
        Context assembly with similarity grouping

        Parameters:
            contexts: list
            conversation_context: str
            query_analysis: QueryAnalysis

        Returns:
            str: Combined context
        """
        combined_context = ""
        if conversation_context:
            combined_context = f"Previous Conversation:\n{conversation_context}\n\n"

        safety_buffer = int(self.max_model_len * 0.05) if self.is_large_model else 500
        max_token_limit = self.max_model_len - safety_buffer
        lambda_i = 0.01
        if contexts and not isinstance(contexts[0], RetrievalContext):
            retrieval_contexts = [
                RetrievalContext(text=ctx, score=1.0 - (i * lambda_i))
                for i, ctx in enumerate(contexts)
            ]
        else:
            retrieval_contexts = contexts

        sorted_contexts = sorted(
            retrieval_contexts, key=lambda x: x.score, reverse=True
        )

        # Similarity grouping logic would go here
        grouped_contexts = sorted_contexts

        for ctx in grouped_contexts:
            if not hasattr(ctx, "token_count") or ctx.token_count == 0:
                cache_key = f"tokens_{hash(ctx.text) % 10000000}"
                cached_count = self.tiered_cache.get(cache_key)
                if cached_count:
                    ctx.token_count = cached_count
                else:
                    if len(ctx.text) < 1000:
                        tokens = self.tokenizer(ctx.text, return_tensors="pt")[
                            "input_ids"
                        ]
                        ctx.token_count = tokens.shape[1]
                    else:
                        ctx.token_count = int(len(ctx.text.split()) * 1.3)
                    self.tiered_cache.set(cache_key, ctx.token_count)

        current_token_count = 0
        if combined_context:
            current_token_count = int(len(combined_context.split()) * 1.3)

        contexts_added = 0

        for i, ctx in enumerate(grouped_contexts):
            if current_token_count + ctx.token_count > max_token_limit:
                logging.info(
                    f"Stopping context assembly at {contexts_added} contexts due to token limit"
                )
                break

            if not combined_context:
                combined_context = f"Context 1:\n{ctx.text}"
            else:
                combined_context += f"\n\nContext {contexts_added + 1}:\n{ctx.text}"

            current_token_count += ctx.token_count
            contexts_added += 1

            max_contexts = 15 if self.is_large_model else 7
            if contexts_added >= max_contexts:
                break

        logging.info(f"Assembled context with {contexts_added} contexts")
        return combined_context
