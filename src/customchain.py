import asyncio
import os
import pickle
import re

# --
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import faiss
import numpy as np
import torch
import weaviate
from langchain_community.vectorstores import Chroma

if torch.cuda.is_available():
    from vllm import SamplingParams

warnings.simplefilter(action="ignore", category=FutureWarning)

# --
import logging
import sys
from typing import Tuple

from cache import LRUCache
from chunker import BM25Retriever, cache_chunker_embedding_chain
from contextcompressor import ContextualCompressionRetriever, ContextualConfig
from conversationmemorybuffer import ConversationMemoryBuffer
from embedding import EmbeddingModelLoader
from ensembleretriever import EnsembleConfig, EnsembleRetriever
from flashreranker import FlashReranker, RerankerConfig
from globalvariables import (
    LARGE_MODELS,
    TEMPLATES,
    VECTOR_STORE_PATH,
    IndexType,
    ReasoningType,
    MAX_MODEL_LEN,
)

# -- Model evaluation
from metrics import Evaluatrix
from reasoningmetrics import ReasoningMetrics
from utils import get_max_model_len

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# %% Custom LLMChain


@lru_cache(maxsize=None)
@cache_chunker_embedding_chain
class CustomLLMChain:
    def __init__(
        self,
        tokenizer,
        model,
        model_name,
        vector_store_name,
        embedding_model_name="sentence-transformers/all-mpnet-base-v2",
        index_type=IndexType.FAISS,
        cache_size=1000,
        dynamic_k=True,
    ):
        """Custom LLMChain


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

        Raises
        ------
        ValueError
            DESCRIPTION.

        Returns
        -------
        None.

        """
        self.tokenizer = tokenizer
        self.model = model
        self.model_name = model_name
        self.vector_store_name = vector_store_name
        self.context_cache = LRUCache(cache_size)
        self.dynamic_k = dynamic_k
        self.is_large_model = self.model_name in LARGE_MODELS
        self.device = torch.device(
            "cuda:0"
            if torch.cuda.is_available()
            else "cpu" if torch.backends.mps.is_available() else "cpu"
        )
        self.max_input_ratio = 0.8 if self.is_large_model else 0.75
        if self.model is None or self.tokenizer is None:
            raise ValueError(
                f"🚩 Failed to load model or tokenizer. \nModel: {None if not self.model else self.model} and "
                + f"\nTokenizer: {None if not self.tokenizer else self.tokenizer} cannot be None"
            )

        self.index_type = index_type
        self.max_model_len = get_max_model_len(self.model_name, MAX_MODEL_LEN)
        self.embedding_model_name = embedding_model_name
        self.conversation_memory = ConversationMemoryBuffer(max_turns=2)
        # --initialize embedding model
        try:
            self.embedding_model = EmbeddingModelLoader.load_embedding_model(
                self.index_type, self.embedding_model_name
            )
            logging.info(
                f"Successfully loaded embedding model (cached): {self.embedding_model_name}"
            )
        except Exception as e:
            logging.error(f"🚩 Error loading cached embedding model: {e}")
            raise

        # --
        self._initialize_retrievers()
        self._initialize_reranker()
        self._initialize_contextual_retriever()

        # -- CoT template
        self.templates = TEMPLATES

    def _initialize_retrievers(self):
        """Initialize retriever

        Raises
        ------
        FileNotFoundError
            File error.
        ValueError
            Value error.

        Returns
        -------
        None.

        """
        try:
            vector_store_path = VECTOR_STORE_PATH / self.vector_store_name
            self.bm25_retriever = BM25Retriever.load_bm25(
                vector_store_path / "bm25_retriever.pkl"
            )
            self.texts = []
            # --
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

            # -- intialize ensemble retriever
            self.ensemble_retriever = EnsembleRetriever(
                bm25_retriever=self.bm25_retriever,
                dense_retriever=self.dense_retriever,
                embedding_model=self.embedding_model,  # Pass embedding model
                texts=self.texts,  # Pass texts
                config=EnsembleConfig(k=10),
            )

        except Exception as e:
            logging.error(f"Error initializing retrievers: {e}")
            raise

    def _initialize_reranker(self):
        """Initialize FlashReranker

        Returns
        -------
        None.
        """
        try:
            self.reranker = FlashReranker(
                RerankerConfig(batch_size=32, threshold=0.5)
            )
        except Exception as e:
            logging.error(f"Error initializing reranker: {e}")
            raise

    def _initialize_contextual_retriever(self):
        """Initialize ContextualCompressionRetriever

        Returns
        -------
        None.

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

    async def analyze_query_complexity(self, question):
        """Analyze query complexity to determine optimal retrieval parameters

        Returns:
            tuple: (k_value, lambda_param) based on query complexity
        """
        has_multiple_questions = len(re.findall(r"\?", question)) > 1
        word_count = len(question.split())

        # -- complexity
        if has_multiple_questions or word_count > 20:
            return 7, 0.6
        elif word_count > 10:
            return 5, 0.5
        else:
            return 3, 0.4

    async def context_filtering(self, contexts, question):
        """Enhanced context filtering with relevance scoring

        Parameters:
            contexts (list): Retrieved contexts
            question (str): Original question

        Returns:
            list: Filtered and reranked contexts
        """
        try:
            if not contexts:
                return []
            # --
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
            # --
            final_scores = 0.7 * relevance_scores + 0.3 * diversity_scores
            top_indices = np.argsort(final_scores)[::-1]
            return [contexts[i] for i in top_indices]
        except Exception as e:
            logging.error(f"Error in context filtering: {e}")
            return contexts

    def compute_mmr(
        self,
        all_texts,
        all_embeddings,
        query_embedding,
        k=100,
        lambda_param=0.5,
    ):
        """Maximal Marginal Relevance (MMR)
        -----------------------------------
            Maximal Marginal Relevance (MMR): This approach balances relevance (how similar a document
            is to the query) and diversity (how different the document is from those already selected).
            This helps in selecting a set of documents that are both relevant and diverse.


        Parameters
        ----------
        all_texts (str): text.
        all_embeddings (embeddings): text embeddings.
        query_embedding (embedding): query embedding.
        k : int, optional
            top-k context to return. The default is 100.
        lambda_param : float, optional
            query complexity. The default is 0.5.

        Returns (str): searched documents
        """
        query_similarity = np.dot(all_embeddings, query_embedding.T)
        selected_indices = []
        candidate_indices = list(range(len(all_texts)))

        # --
        def compute_mmr_score(i):
            relevance = query_similarity[i]
            diversity = (
                max(
                    [
                        np.dot(all_embeddings[i], all_embeddings[j].T)
                        for j in selected_indices
                    ]
                )
                if selected_indices
                else 0
            )
            return lambda_param * relevance - (1 - lambda_param) * diversity

        # --
        for _ in range(k):
            if not candidate_indices:
                break

            with ThreadPoolExecutor() as executor:
                mmr_scores = list(
                    executor.map(compute_mmr_score, candidate_indices)
                )

            # -- Select the document with the highest MMR score
            best_index = candidate_indices[np.argmax(mmr_scores)]
            selected_indices.append(best_index)
            candidate_indices.remove(best_index)

        return [all_texts[i] for i in selected_indices]

    def rank_documents(self, scores):
        """Rank documents based on their fusion scores.

        Parameters:
        ----------
        scores : dict
            Document scores from Reciprocal Rank Fusion.

        Returns:
        --------
        List of ranked document indices.
        """
        return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    def available_device_count(self, device):
        """Get the number of available devices (GPUs or CPU cores)."""
        if self.device == "cuda:0":
            return torch.cuda.device_count()
        else:
            return torch.get_num_threads()

    def device_transfer(self, chunk, device):
        """
        Transfer a chunk of the tensor to the specified device -- CPU/GPU
        """
        return chunk.to(device, non_blocking=True)

    def parallel_chunk_transfer(self, tensor, device):
        """Transfer the tensor to the device in chunks using ThreadPoolExecutor,
            distributing across available devices (GPUs or CPU cores).

        Parameters:
            tensor (tensor): The tensor to transfer.
            device (str): The target device (e.g., "cuda:0" or "cpu").

        Returns:
            The tensor on the target device, reassembled from the chunks.
        """
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)

        # -- number of available devices
        num_devices = self.available_device_count(device)
        num_chunks = max(1, num_devices)

        # -- chunk tensor based on the number of devices
        chunk_size = tensor.size(1) // num_chunks
        chunks = []

        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size
            if i == num_chunks - 1:
                end_idx = tensor.size(1)
            chunks.append(tensor[:, start_idx:end_idx])

        # -- Transfer chunks in parallel
        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            futures = [
                executor.submit(self.device_transfer, chunk, device)
                for chunk in chunks
            ]
            device_chunks = [
                future.result() for future in as_completed(futures)
            ]

        return torch.cat(device_chunks, dim=1)

    def _format_llm_response(self, text):
        """Format LLM response while preserving tables and structured data.
            Only removes template artifacts and prompt phrases.

        Parameters:
            text (str): Raw response from the LLM

        Returns:
            str: Cleaned text with preserved formatting
        """
        try:
            text = re.sub(
                r"\[INST\].*?\[/INST\]", "", text, flags=re.DOTALL
            ).strip()
            text = re.sub(
                r"Analysis Steps:.*?Context:", "", text, flags=re.DOTALL
            ).strip()
            text = re.sub(
                r"Context:.*?Question:", "", text, flags=re.DOTALL
            ).strip()

            # -- remove standard prompt phrases
            phrases_to_remove = [
                r"Provide .*? based on the context:",
                r"Explain .*? based on the context:",
                r"Explore .*? based on the context:",
                r"Compare .*? based on the context:",
            ]
            for phrase in phrases_to_remove:
                text = re.sub(phrase, "", text, flags=re.IGNORECASE).strip()

            return text

        except Exception as e:
            logging.error(
                f"🚩 An error occurred during text formatting: {str(e)}"
            )
            return "No sufficient context to respond to the question."

    def _calculate_frequency_penalty(self, input_length: int) -> float:
        """Calculate appropriate frequency penalty based on input length.

        Parameters:
            input_length (int): Length of input tokens

        Returns:
            float: Calculated frequency penalty
        """
        SHORT_CONTEXT = 512
        MEDIUM_CONTEXT = 1024
        LONG_CONTEXT = 2048

        # -- corresponding penalties
        SHORT_PENALTY = 0.01
        MEDIUM_PENALTY = 0.05
        LONG_PENALTY = 0.10

        if input_length <= SHORT_CONTEXT:
            return SHORT_PENALTY
        elif input_length <= MEDIUM_CONTEXT:
            return MEDIUM_PENALTY
        else:  # ignore LONG_CONTEXT here
            return LONG_PENALTY

    def _compute_dynamic_tokens(
        self, input_len: int, max_input_length: int
    ) -> int:
        """
        Calculate token allocation based on context ratio.

        Parameters
        ----------
            input_len (int): Length of the input context in tokens
            max_input_length (int): Maximum allowed input length

        Returns
        -------
            int: Dynamically calculated token allocation based on context ratio thresholds
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

    async def generate_text(
        self, prompt, temperature=1e-12, max_length=None, top_p=0.95, top_k=50
    ):
        """Optimized text generation focusing on prefill efficiency with dynamic token allocation

        Parameters
        ----------
        prompt (str): input prompt.
        temperature (float): optional
            text control for deterministic or non-deterministics generartion. The default is 1e-12.
        max_length : int, optional
            max length. The default is None.
        top_p : float, optional
            top-p. The default is 0.95.
        top_k : int, optional
            top-k. The default is 50.
        Returns (str): text
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
        max_new_tokens = (
            default_new_tokens if max_length is None else max_length
        )
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
                    response = (
                        output.get("choices", [{}])[0].get("text", "").strip()
                    )
                else:
                    response = output.choices[0].text.strip()
                return response
            except Exception as e:
                logging.error(f"CPU generation error: {e}")
                return ""

    async def custom_llm_chain(self, context, question):
        """custom_llm_chain with reasoning capabilities

        Parameters
        ----------
        context (str): final context.
        question (str): input question/query.

        Returns (str): generated final text.

        """
        try:
            reasoning_type, _ = (
                self.reasoning_metrics.bayesian_reasoning_detection(question)
            )
            template = self.templates[reasoning_type]
            prompt_format = template.format(context=context, question=question)
            generated_text = await self.generate_text(prompt_format)
            return generated_text

        except Exception as e:
            logging.error(f"Error in custom_llm_chain: {str(e)}")
            template = self.templates[ReasoningType.ANALYTICAL]
            prompt_format = template.format(context=context, question=question)
            return await self.generate_text(prompt_format)

    def chunk_document(self, document, num_chunks=3):
        """Split the document into sub-chunks.

        Parameters
        ----------
        document (str): input document
        num_chunks : int, optional
            chunk size. The default is 3.

        Returns
        -------
        list
            sub-chunked documents.
        """
        words = document.split()
        chunk_size = max(1, len(words) // num_chunks)
        return [
            " ".join(words[i : i + chunk_size])
            for i in range(0, len(words), chunk_size)
        ]

    async def search_similar_texts_async(self, chunk, k=5, lambda_param=0.5):
        """Search w/ reasoning scores (optimized)

        Parameters
        ----------
        chunk : str
            chunked document.
        k : int, optional
            context size. The default is 5.
        lambda_param : float, optional
            context confidence score . The default is 0.5.

        Returns
        -------
        List
            filtered context.
        """
        if not hasattr(self, "reasoning_metrics"):
            self.reasoning_metrics = ReasoningMetrics(self.embedding_model)

        cache_key = f"{chunk[:100]}_{k}"
        if cache_key in self.context_cache:
            return self.context_cache[cache_key]

        reasoning_task = asyncio.create_task(self.detect_reasoning_type(chunk))
        contexts_task = asyncio.create_task(
            self.contextual_retriever.retrieve_and_compress(chunk, k)
        )
        reasoning_result, contexts_result = await asyncio.gather(
            reasoning_task, contexts_task
        )
        reasoning_type, confidence = reasoning_result
        contexts, scores = contexts_result
        if not contexts:
            return []

        async def process_context(ctx):
            reasoning_score = (
                await self.reasoning_metrics.compute_reasoning_score_async(
                    chunk, ctx, reasoning_type
                )
            )
            combined_score = 0.7 * reasoning_score + 0.3 * confidence
            return (ctx, combined_score)

        # -- t/p/c
        context_score_tasks = [process_context(ctx) for ctx in contexts]
        context_scores = await asyncio.gather(*context_score_tasks)
        ranked_contexts = sorted(
            context_scores, key=lambda x: x[1], reverse=True
        )
        filtered_contexts = [ctx for ctx, _ in ranked_contexts[:k]]
        self.context_cache[cache_key] = filtered_contexts
        return filtered_contexts

    async def detect_reasoning_type(
        self, question: str
    ) -> Tuple[ReasoningType, float]:
        """Reasoning detection with confidence score (optimized)

        Parameters
        ----------
        question (str): input question

        Returns
        -------
        Tuple[ReasoningType, float]: Bayesian reasoning classification with score.
        """
        if not hasattr(self, "reasoning_metrics"):
            self.reasoning_metrics = ReasoningMetrics(self.embedding_model)

        return await self.reasoning_metrics.bayesian_reasoning_detection_async(
            question
        )

    async def create_embeddings_async(self, texts):
        """Asynchronous version of create_embeddings.
            Creates embeddings using pre-loaded SentenceTransformer or tokenizer based on availability.

        Parameters:
            text (str): input text

        Returns
            prompt (text) embedding
        """
        try:
            if torch.cuda.is_available():
                with torch.no_grad():
                    embeddings = self.embedding_model.encode(
                        texts,
                        convert_to_tensor=True,
                        show_progress_bar=False,
                        device=self.device.type,  # Ensure it uses the correct device
                    )
                    embeddings = embeddings.cpu().numpy()
            else:
                if self.index_type == IndexType.CHROMA:
                    embeddings = np.array(
                        self.embedding_model.embed_documents(texts)
                    )
                elif self.index_type in [IndexType.FAISS, IndexType.WEAVIATE]:
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
                        logging.error(
                            f"🚩 Index out of range error: {e}. Check input text length."
                        )
                        return np.array([])
                else:
                    logging.error(
                        f"🚩 Unsupported embedding type: {self.index_type}"
                    )
                    return np.array([])

            return embeddings

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            return np.array([])

    async def vector_search_async(self, embedding, k):
        """Asynchronous vector search for Chroma and Weaviate.

        Parameters:
            embedding (np): embedding model
            k (int): number of context to return after search

        Returns:
            list: list of context generated from vector (index) search
        """
        if self.index_type == IndexType.CHROMA:
            results = await asyncio.to_thread(
                self.vectorstore.similarity_search_by_vector,
                embedding.tolist(),
                k,
            )
            return [result.page_content for result in results]
        elif self.index_type == IndexType.WEAVIATE:
            results = await asyncio.to_thread(
                self.weaviate_client.query.get(
                    self.class_name, ["page_content"]
                )
                .with_near_vector({"vector": embedding.tolist()})
                .with_limit(k)
                .do
            )
            return [
                result["page_content"]
                for result in results["data"]["Get"][self.class_name]
            ]

    async def parallel_search(self, document, k=5):
        """Optimized parallel search with improved concurrency

        Parameters:
            document (str): input document
            k (int, optional): size of context to return. Defaults to 5.

        Returns:
            str: Merged unique context
        """
        chunks = self.chunk_document(document, k)

        async def safe_search(chunk):
            try:
                return await self.search_similar_texts_async(chunk, k)
            except Exception as e:
                logging.error(f"Error searching for chunk: {e}")
                return []

        results = await asyncio.gather(
            *[safe_search(chunk) for chunk in chunks]
        )
        return self.merge_results(results, k)

    def merge_results(self, results, k):
        """Merge top-k results from parallel searches.

        Parameter:
            results (lis): list of input context to filter
            k (int): top-k context to return after merging

        Returns:
            list: merged top-k context
        """
        all_docs = []
        for result in results:
            all_docs.extend(result)

        # -- remove duplicates while preserving order
        seen = set()
        merged = []
        for doc in all_docs:
            if doc not in seen:
                seen.add(doc)
                merged.append(doc)

        return merged[:k]  # return top-k unique elements

    async def search_similar_texts(self, question, k=5):
        """Parallelized version of search_similar_texts.

        Parameters:
            question (str): Prompt or input question
            k (int, optional): top-k input context to return. Defaults to 5.

        Returns:
            str : Merged unique top-k context
        """
        return await self.parallel_search(question, k)

    def run_async_in_thread(self, coro):
        """Run an async coroutine in a separate thread.

        Parameters:
            coro (coroutine): Coroutines to assemble
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

    async def check_context_length(
        self, current_context: str, new_context: str
    ) -> bool:
        """Check if adding new context would exceed model's maximum length

        Parameters:
            current_context (str): Existing combined context
            new_context (str): New context to potentially add

        Returns:
            bool: True if adding new context stays within limits, False otherwise
        """
        safety_buffer = (
            int(self.max_model_len * 0.05) if self.is_large_model else 500
        )
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

            #  --
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
                lambda: self.tokenizer(
                    combined, return_tensors="pt", truncation=False
                )["input_ids"].shape[1]
            )
            return token_count <= (self.max_model_len - safety_buffer)

    async def invoke_async(self, question: str):
        """Invoke conversation memory buffer w/ reasoning (optimized for large context models)

        Parameters:
            question (str): The current user question

        Returns:
            Tuple[str, str, Dict]: Answer, context, and evaluation metrics

        !IMPORTANT
        ----------
            ~> k (int): This value is key to search and retrieval. The higher the value the better
            ~> retrieval_k (int): Given the k-retrievals (k-questions), HAH consumes these contexts to search again for loss information or re-retrieves similar context and reranks.
                                    Note the use of keyword ```re-retrieve```, lost context relevant to the question.

        NOTE: In the case of bad response. Simply find an optimal k/retrieval trade-off.
        """
        try:
            self.conversation_memory.add_message("user", question)
            reasoning_task = self.detect_reasoning_type(question)
            conversation_context = (
                self.conversation_memory.get_context_with_reasoning(
                    ReasoningType.ANALYTICAL
                )
            )
            reasoning_type, _ = await reasoning_task
            if conversation_context:
                conversation_context = (
                    self.conversation_memory.get_context_with_reasoning(
                        reasoning_type
                    )
                )
            query_with_context = (
                question + " " + conversation_context
                if conversation_context
                else question
            )
            base_k, lambda_param = await self.analyze_query_complexity(
                query_with_context
            )
            k = base_k * 10 if self.is_large_model else base_k  # ~ !IMPORTANT
            logging.info(
                f"Query parameters - k: {k}, lambda: {lambda_param}, large_model: {self.is_large_model}"
            )
            initial_contexts = await self.search_similar_texts_async(
                question, k, lambda_param
            )

            if not initial_contexts:
                no_context_response = (
                    "No relevant context found to answer the question."
                )
                self.conversation_memory.add_message(
                    "assistant", no_context_response
                )
                return no_context_response, "", {}

            # -- filter context considering conversation history
            filtering_task = self.context_filtering(
                initial_contexts,
                query_with_context,
            )
            filtered_contexts = await filtering_task
            document = ". ".join(filtered_contexts[:k])
            retrieval_k = 15 if self.is_large_model else 12  # ~ !IMPORTANT
            relevant_contexts = await self.search_similar_texts(
                document, k=retrieval_k
            )

            combined_context = ""
            if conversation_context:
                combined_context = (
                    f"Previous Conversation:\n{conversation_context}\n\n"
                )

            contexts_added = 0
            max_contexts = len(relevant_contexts)
            # --
            for i, context in enumerate(relevant_contexts):
                if not combined_context:
                    combined_context = f"Context 1:\n{context}"
                    contexts_added += 1
                    continue

                if self.is_large_model and contexts_added < 5:
                    combined_context += f"\n\nContext {i + 1}:\n{context}"
                    contexts_added += 1
                    continue

                can_add = await self.check_context_length(
                    combined_context, context
                )
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

            # Generate response
            result_text = await self.custom_llm_chain(
                combined_context, question
            )
            answer = self._format_llm_response(result_text)
            self.conversation_memory.add_message("assistant", answer)

            # -- Evaluation metrics gather...
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

            return answer, combined_context, eval_metrics

        except Exception as e:
            error_msg = f"Error in invoke_async: {str(e)}"
            logging.error(error_msg)
            self.conversation_memory.add_message(
                "assistant",
                "I apologize, but I encountered an error processing your request.",
            )
            return error_msg, "", {}

    def ainvoke(self, question):
        """asynchronous invoke

        Parameters:
            question (str): input question

        Returns:
            tuple: result of invoke_async
        """
        return self.run_async_in_thread(self.invoke_async(question))
