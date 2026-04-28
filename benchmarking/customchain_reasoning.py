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

if torch.cuda.is_available():
    from vllm import SamplingParams

warnings.simplefilter(action="ignore", category=FutureWarning)

import logging
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cache import LRUCache
from src.chunker import BM25Retriever
from src.contextcompressor import ContextualCompressionRetriever, ContextualConfig
from src.conversationmemorybuffer import ConversationMemoryBuffer
from src.embedding import EmbeddingModelLoader
from src.ensembleretriever import EnsembleConfig, EnsembleRetriever, FusionMethod
from src.flashreranker import FlashReranker, RerankerConfig
from src.globalvariables import (
    EMBEDDING_NAME,
    LARGE_MODELS,
    MAX_MODEL_LEN,
    IndexType,
    ReasoningType,
)
from src.metrics import Evaluatrix
from src.reasoningmetrics import ReasoningMetrics
from src.system_prompts.types import SystemPromptTypes
from src.trivial_check import is_trivial_question
from src.utils import (
    add_leading_space_if_needed,
    format_llm_response,
    get_max_model_len,
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
    logging.warning(
        "Importing system prompts from src.system_prompts failed. Using fallback definitions."
    )
    from enum import StrEnum

    class SystemPromptLangs(StrEnum):
        EN = "EN"
        FR = "FR"

    DEFAULT_SYSTEM_PROMPT_LANG = SystemPromptLangs.EN

    ALL_DEFAULT_SYSTEM_PROMPT_ROLE = {
        SystemPromptLangs.EN: " You are an expert AI assistant with advanced reasoning capabilities, specialized in analyzing complex questions and providing comprehensive, accurate responses. Your expertise spans multiple domains including factual analysis, comparative reasoning, causal relationships, and hypothetical scenarios. You excel at breaking down complex problems, identifying key patterns, and synthesizing information to deliver clear, well-structured answers that directly address the user's needs.",
        SystemPromptLangs.FR: "Vous êtes un assistant IA utile qui fournit des réponses précises et concises basées sur le contexte donné.",
    }

    # Import SystemPromptTypes for fallback
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
        """Custom LLMChain with reasoning capabilities

        Parameters
        ----------
        tokenizer : tokenizer
            tokenizer.
        model : llm model
            llm model.
        model_name : str
            model name.
        vector_store_name : str
            vector store name.
        embedding_model_name : str, optional
            Embedding name. The default is "sentence-transformers/all-mpnet-base-v2".
        index_type : str, optional
            Index type. The default is IndexType.FAISS.
        cache_size : int, optional
            Size of token to cache. The default is 1000.
        dynamic_k : bool, optional
            k-computation type. The default is True.
        instruction_lang : SystemPromptLangs, optional
            Language of the LLM instruction, by default DEFAULT_SYSTEM_PROMPT_LANG
        """
        start_time = time.time()
        self.tokenizer = tokenizer
        self.model = model
        self.model_name = model_name
        self.vector_store_name = vector_store_name
        self.context_cache = LRUCache(cache_size)
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
                f"🚩 Failed to load model or tokenizer. \nModel: {None if not self.model else self.model} and "
                + f"\nTokenizer: {None if not self.tokenizer else self.tokenizer} cannot be None"
            )

        self.index_type = index_type
        self.instruction_lang = instruction_lang
        self.max_model_len = get_max_model_len(self.model_name, MAX_MODEL_LEN)
        self.embedding_model_name = embedding_model_name
        self.conversation_memory = ConversationMemoryBuffer(max_turns=2)

        # Initialize embedding model
        try:
            load_embedding_start = time.time()
            self.embedding_model = EmbeddingModelLoader.load_embedding_model(
                self.index_type, self.embedding_model_name
            )
            load_embedding_time = time.time() - load_embedding_start
            logging.info(
                f"Successfully loaded embedding model (cached): {self.embedding_model_name} in {load_embedding_time:.4f} seconds"
            )
        except Exception as e:
            logging.error(f"🚩 Error loading cached embedding model: {e}")
            raise

        # -- initialize components
        self._initialize_retrievers()
        self._initialize_reranker()
        self._initialize_contextual_retriever()

        # -- CoT template
        self.templates = ALL_SYSTEM_PROMPT_TEMPLATES[self.instruction_lang]
        self.assistant_role = ALL_DEFAULT_SYSTEM_PROMPT_ROLE[self.instruction_lang]
        self.assistant_role = add_leading_space_if_needed(self.assistant_role)

        init_time = time.time() - start_time
        logging.info(
            f"CustomLLMChain initialization completed in {init_time:.4f} seconds"
        )

    @measure_time_sync
    def _initialize_retrievers(self):
        """Initialize retriever

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

            # -- initialize ensemble retriever
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

    @measure_time_sync
    def _initialize_reranker(self):
        """Initialize FlashReranker

        Returns:
            None
        """
        try:
            self.reranker = FlashReranker(RerankerConfig())
        except Exception as e:
            logging.error(f"Error initializing reranker: {e}")
            raise

    @measure_time_sync
    def _initialize_contextual_retriever(self):
        """Initialize ContextualCompressionRetriever

        Returns:
            None
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

    @measure_time
    async def analyze_query_complexity(self, question):
        """Analyze query complexity to determine optimal retrieval parameters

        Parameters:
            question: str

        Returns:
            tuple: k, compression_ratio
        """
        has_multiple_questions = len(re.findall(r"\?", question)) > 1
        word_count = len(question.split())

        if has_multiple_questions or word_count > 20:
            return 7, 0.6
        elif word_count > 10:
            return 5, 0.5
        else:
            return 3, 0.4

    @measure_time
    async def context_filtering(self, contexts, question):
        """context filtering with relevance scoring and diversity analysis

        Parameters:
            contexts: list
            question: str

        Returns:
            list: Filtered contexts
        """
        try:
            if not contexts:
                return []

            question_embedding = await self.create_embeddings_async([question])
            context_embeddings = await self.create_embeddings_async(contexts)
            if question_embedding.size == 0 or context_embeddings.size == 0:
                return contexts

            if len(question_embedding.shape) == 1:
                question_embedding = question_embedding.reshape(1, -1)
            if len(context_embeddings.shape) == 1:
                context_embeddings = context_embeddings.reshape(1, -1)

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

            final_scores = 0.7 * relevance_scores + 0.3 * diversity_scores
            top_indices = np.argsort(final_scores)[::-1]
            return [contexts[i] for i in top_indices]
        except Exception as e:
            logging.error(f"Error in context filtering: {e}")
            return contexts

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
        input_tokens = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_input_length,
        )
        input_length = input_tokens["input_ids"].shape[1]
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
                return ""
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
                return ""

    def _calculate_frequency_penalty(self, input_length: int) -> float:
        """Calculate appropriate frequency penalty based on input length.

        Parameters:
            input_length: int

        Returns:
            float: Frequency penalty
        """
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
        """Calculate token allocation based on context ratio.

        Parameters:
            input_len: int
            max_input_length: int

        Returns:
            int: Dynamic tokens
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
        """custom_llm_chain with reasoning capabilities

        Parameters:
            context: str
            question: str
            is_trivial: bool

        Returns:
            str: Generated text
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

                reasoning_type, _ = self.reasoning_metrics.bayesian_reasoning_detection(
                    question
                )
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

            return generated_text

        except Exception as e:
            logging.error(f"Error in custom_llm_chain: {str(e)}")
            fallback_reasoning_type = ReasoningType.ANALYTICAL
            template = self.templates[fallback_reasoning_type]
            prompt_format = template.format(
                assistant_role=self.assistant_role, context=context, question=question
            )
            return await self.generate_text(prompt_format)

    @measure_time
    async def search_similar_texts_async(self, chunk, k=5, lambda_param=0.5):
        """Search with reasoning scores

        Parameters:
            chunk: str
            k: int
            lambda_param: float

        Returns:
            list: Contexts
            list: Scores
        """
        if not hasattr(self, "reasoning_metrics"):
            self.reasoning_metrics = ReasoningMetrics(
                self.embedding_model, self.instruction_lang
            )

        cache_key = f"{chunk[:100]}_{k}"
        if cache_key in self.context_cache:
            return self.context_cache[cache_key]

        reasoning_start = time.time()
        reasoning_task = asyncio.create_task(self.detect_reasoning_type(chunk))
        contexts_task = asyncio.create_task(
            self.contextual_retriever.retrieve_and_compress(chunk, k)
        )
        reasoning_result, contexts_result = await asyncio.gather(
            reasoning_task, contexts_task
        )
        reasoning_type, confidence = reasoning_result
        contexts, scores = contexts_result
        reasoning_time = time.time() - reasoning_start
        logging.info(
            f"Reasoning and contexts retrieval took {reasoning_time:.4f} seconds"
        )

        if not contexts:
            return []

        score_start = time.time()

        async def process_context(ctx):
            reasoning_score = (
                await self.reasoning_metrics.compute_reasoning_score_async(
                    chunk, ctx, reasoning_type
                )
            )
            combined_score = 0.7 * reasoning_score + 0.3 * confidence
            return (ctx, combined_score)

        context_score_tasks = [process_context(ctx) for ctx in contexts]
        context_scores = await asyncio.gather(*context_score_tasks)
        ranked_contexts = sorted(context_scores, key=lambda x: x[1], reverse=True)
        filtered_contexts = [ctx for ctx, _ in ranked_contexts[:k]]
        score_time = time.time() - score_start
        logging.info(f"Context scoring and ranking took {score_time:.4f} seconds")

        self.context_cache[cache_key] = filtered_contexts
        return filtered_contexts

    @measure_time
    async def detect_reasoning_type(self, question: str):
        """Reasoning detection with confidence score

        Parameters:
            question: str

        Returns:
            tuple: Reasoning type, Confidence score
        """
        if not hasattr(self, "reasoning_metrics"):
            self.reasoning_metrics = ReasoningMetrics(
                self.embedding_model, self.instruction_lang
            )

        return await self.reasoning_metrics.bayesian_reasoning_detection_async(question)

    @measure_time
    async def create_embeddings_async(self, texts):
        """Asynchronous version of create_embeddings.

        Parameters:
            texts: list

        Returns:
            np.array: Embeddings
        """
        try:
            if torch.cuda.is_available():
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
                    embeddings = np.array(self.embedding_model.embed_documents(texts))
                elif self.index_type in [IndexType.FAISS, IndexType.WEAVIATE]:
                    try:
                        embeddings = self.embedding_model.encode(
                            texts,
                            convert_to_tensor=True,
                            show_progress_bar=False,
                            device=self.device.type,
                        )
                        embeddings = embeddings.to(dtype=torch.float32).cpu().numpy()
                    except IndexError as e:
                        logging.error(
                            f"🚩 Index out of range error: {e}. Check input text length."
                        )
                        return np.array([])
                else:
                    logging.error(f"🚩 Unsupported embedding type: {self.index_type}")
                    return np.array([])

            return embeddings

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            return np.array([])

    @measure_time
    async def parallel_search(self, document, k=5):
        """Parallel search with improved concurrency

        Parameters:
            document: str
            k: int

        Returns:
            list: Results
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
        """Split the document into sub-chunks.

        Parameters:
            document: str
            num_chunks: int

        Returns:
            list: Chunks
        """
        words = document.split()
        chunk_size = max(1, len(words) // num_chunks)
        return [
            " ".join(words[i : i + chunk_size])
            for i in range(0, len(words), chunk_size)
        ]

    def merge_results(self, results, k):
        """Merge top-k results from parallel searches.

        Parameters:
            results: list
            k: int

        Returns:
            list: Merged results
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
        """Parallelized version of search_similar_texts.

        Parameters:
            question: str
            k: int

        Returns:
            list: Results
        """
        return await self.parallel_search(question, k)

    def run_async_in_thread(self, coro):
        """Run an async coroutine in a separate thread.

        Parameters:
            coro: async coroutine

        Returns:
            Future: Result
        """

        def wrapper():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        with ThreadPoolExecutor() as executor:
            future = executor.submit(wrapper)
            return future.result()

    @measure_time
    async def invoke_async(self, question: str):
        """Invoke conversation memory buffer with reasoning

        Parameters:
            question: str

        Returns:
            tuple: answer, combined_context, eval_metrics
        """
        overall_start = time.time()

        try:
            # -- Trivial question bypass
            if is_trivial_question(question, self.instruction_lang):
                self.conversation_memory.add_message("user", question)
                conversation_context = (
                    self.conversation_memory.get_context_with_reasoning(
                        SystemPromptTypes.TRIVIAL
                    )
                )
                combined_context = conversation_context or ""
                result_text = await self.custom_llm_chain(
                    combined_context,
                    question,
                    is_trivial=True,
                )
                answer = self._format_llm_response(result_text)
                self.conversation_memory.add_message("assistant", answer)
                return answer, combined_context, {}

            # -- non-trivial path
            memory_start = time.time()
            self.conversation_memory.add_message("user", question)
            memory_time = time.time() - memory_start
            logging.info(f"Memory update took {memory_time:.4f} seconds")

            # -- run reasoning detection
            reasoning_start = time.time()
            reasoning_task = self.detect_reasoning_type(question)
            conversation_context = self.conversation_memory.get_context_with_reasoning(
                ReasoningType.ANALYTICAL
            )
            reasoning_type, _ = await reasoning_task
            if conversation_context:
                conversation_context = (
                    self.conversation_memory.get_context_with_reasoning(reasoning_type)
                )
            reasoning_time = time.time() - reasoning_start
            logging.info(
                f"Reasoning detection and context preparation took {reasoning_time:.4f} seconds"
            )
            query_with_context = (
                question + " " + conversation_context
                if conversation_context
                else question
            )

            # -- analyze query complexity and optimize retrieval
            complexity_start = time.time()
            base_k, lambda_param = await self.analyze_query_complexity(
                query_with_context
            )
            query_characteristics = (
                self.ensemble_retriever._analyze_query_characteristics(question)
            )
            self.optimize_ensemble_for_query_type(query_characteristics)
            complexity_time = time.time() - complexity_start
            logging.info(f"Query analysis took {complexity_time:.4f} seconds")

            k = base_k * 10 if self.is_large_model else base_k
            logging.info(
                f"Query parameters - k: {k}, lambda: {lambda_param}, large_model: {self.is_large_model}"
            )

            # -- first search pass
            search1_start = time.time()
            initial_contexts = await self.search_similar_texts_async(
                question, k, lambda_param
            )
            search1_time = time.time() - search1_start
            logging.info(f"Initial search took {search1_time:.4f} seconds")

            if not initial_contexts:
                no_context_response = (
                    "No relevant context found to answer the question."
                )
                self.conversation_memory.add_message("assistant", no_context_response)
                return no_context_response, "", {}

            # -- filter context considering conversation history
            filter_start = time.time()
            filtered_contexts = await self.context_filtering(
                initial_contexts,
                query_with_context,
            )
            filter_time = time.time() - filter_start
            logging.info(f"Context filtering took {filter_time:.4f} seconds")

            # -- second search pass
            search2_start = time.time()
            document = ". ".join(filtered_contexts[:k])
            retrieval_k = 15 if self.is_large_model else 12
            relevant_contexts = await self.search_similar_texts(document, k=retrieval_k)
            search2_time = time.time() - search2_start
            logging.info(f"Secondary search took {search2_time:.4f} seconds")

            # -- build context
            context_build_start = time.time()
            combined_context = ""
            if conversation_context:
                combined_context = f"Previous Conversation:\n{conversation_context}\n\n"

            contexts_added = 0
            max_contexts = len(relevant_contexts)

            for i, context in enumerate(relevant_contexts):
                if not combined_context:
                    combined_context = f"Context 1:\n{context}"
                    contexts_added += 1
                    continue

                if self.is_large_model and contexts_added < 5:
                    combined_context += f"\n\nContext {i + 1}:\n{context}"
                    contexts_added += 1
                    continue

                can_add = await self.check_context_length(combined_context, context)
                if not can_add:
                    logging.info(
                        f"Stopped at {contexts_added} contexts due to length limit"
                    )
                    break

                combined_context += f"\n\nContext {i + 1}:\n{context}"
                contexts_added += 1

            if self.is_large_model:
                logging.info(
                    f"Large model context: {contexts_added}/{max_contexts} contexts added"
                )
            context_build_time = time.time() - context_build_start
            logging.info(f"Context building took {context_build_time:.4f} seconds")

            # Generate response
            generation_start = time.time()
            result_text = await self.custom_llm_chain(
                combined_context, question, is_trivial=False
            )
            answer = self._format_llm_response(result_text, self.instruction_lang)
            self.conversation_memory.add_message("assistant", answer)
            generation_time = time.time() - generation_start
            logging.info(
                f"Response generation and formatting took {generation_time:.4f} seconds"
            )

            # Evaluation metrics
            eval_start = time.time()
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
            eval_time = time.time() - eval_start
            logging.info(f"Metrics evaluation took {eval_time:.4f} seconds")

            # Log overall performance
            overall_time = time.time() - overall_start
            logging.info(
                f"Total invoke_async execution took {overall_time:.4f} seconds"
            )

            return answer, combined_context, eval_metrics

        except Exception as e:
            error_msg = f"Error in invoke_async: {str(e)}"
            logging.error(error_msg)
            self.conversation_memory.add_message(
                "assistant",
                "I apologize, but I encountered an error processing your request.",
            )
            return error_msg, "", {}

    @measure_time_sync
    def ainvoke(self, question):
        """asynchronous invoke

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
        """Format LLM response while preserving tables and structured data.

        Parameters:
            response: str
            language: SystemPromptLangs

        Returns:
            str: Formatted response
        """
        return format_llm_response(response, language)

    def set_ensemble_fusion_method(self, method: FusionMethod):
        """Switch ensemble fusion method dynamically

        Parameters:
            method: FusionMethod
        """
        if hasattr(self, "ensemble_retriever"):
            self.ensemble_retriever.set_fusion_method(method)
            logging.info(f"Ensemble fusion method changed to: {method.value}")
        else:
            logging.error("Ensemble retriever not initialized")

    def optimize_ensemble_for_query_type(self, query_characteristics):
        """Optimize ensemble method based on query characteristics

        Parameters:
            query_characteristics: dict
        """
        if (
            query_characteristics.get("has_proper_nouns", 0) > 0.5
            or query_characteristics.get("technical_ratio", 0) > 0.3
        ):
            self.set_ensemble_fusion_method(FusionMethod.QUERY_ADAPTIVE)
        elif (
            query_characteristics.get("word_count", 0) > 15
            and query_characteristics.get("has_wh_words", 0) > 0
        ):
            self.set_ensemble_fusion_method(FusionMethod.HARMONIC_MEAN)
        elif query_characteristics.get("has_boolean", 0) > 0:
            self.set_ensemble_fusion_method(FusionMethod.COMBMNZ)
        else:
            self.set_ensemble_fusion_method(FusionMethod.SCORE_ADAPTIVE)

    @measure_time
    async def check_context_length(
        self, current_context: str, new_context: str
    ) -> bool:
        """Check if adding new context would exceed model's maximum length

        Parameters:
            current_context: str
            new_context: str

        Returns:
            bool: True if adding new context would exceed model's maximum length
        """
        safety_buffer = int(self.max_model_len * 0.05) if self.is_large_model else 500
        estimated_combined_length = len(current_context + new_context) * 0.25
        if self.is_large_model and estimated_combined_length < (
            self.max_model_len * 0.7
        ):
            return True

        combined = f"{current_context}\n\nContext {len(current_context.split('Context')) + 1}:\n{new_context}"

        if len(combined) > 100000 and self.is_large_model:
            chunk_size = 50000
            chunks = [
                combined[i : i + chunk_size]
                for i in range(0, len(combined), chunk_size)
            ]

            async def tokenize_chunk(chunk):
                return await asyncio.to_thread(
                    lambda: self.tokenizer(
                        chunk, return_tensors="pt", truncation=False
                    )["input_ids"].shape[1]
                )

            token_counts = await asyncio.gather(
                *[tokenize_chunk(chunk) for chunk in chunks]
            )
            total_tokens = sum(token_counts)
            return total_tokens <= (self.max_model_len - safety_buffer)
        else:
            token_count = await asyncio.to_thread(
                lambda: self.tokenizer(combined, return_tensors="pt", truncation=False)[
                    "input_ids"
                ].shape[1]
            )
            return token_count <= (self.max_model_len - safety_buffer)
