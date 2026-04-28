import asyncio
import logging
import pickle
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from connections.database.system_prompts import SystemPrompts
from connections.qdrant import qdrant_client
from connections.storage import fs
from src.globalvariables import EMBEDDING_NAME
from src.metrics import Evaluatrix
from src.system_prompts import (
    ALL_SYSTEM_PROMPT_TEMPLATES,
    DEFAULT_SYSTEM_PROMPT_LANG,
    SystemPromptLangs,
    SystemPromptTypes,
)
from src.utils import add_leading_space_if_needed, format_llm_response

if torch.cuda.is_available():
    from vllm import SamplingParams

warnings.simplefilter(action="ignore", category=FutureWarning)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@lru_cache(maxsize=None)
class CustomLLMChain:
    def __init__(
        self,
        model_name,
        vector_store_name,
        embedding_model_name=EMBEDDING_NAME,
        instruction_lang: SystemPromptLangs = DEFAULT_SYSTEM_PROMPT_LANG,
    ):
        """Custom LLMChain

        Parameters
        ----------
            model_name (str) : model name.
            vector_store_name (str) : vector store name.
            embedding_model_name (str), optional : embedding model name. The default is "sentence-transformers/all-mpnet-base-v2".
            instruction_lang : SystemPromptLangs, optional
                Language of the LLM instruction, by default DEFAULT_SYSTEM_PROMPT_LANG

        Raises
        ------
            ValueError : if model and tokenizer failed to load

        Returns
        -------
        None.

        """
        self.model_name = model_name
        self.vector_store_name = vector_store_name
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        # Local generation model not needed — generation is handled by the OpenAI API.
        self.model = None

        self.instruction_lang = instruction_lang
        self.embedding_model_name = EMBEDDING_NAME
        self.embedding_model = SentenceTransformer(
            self.embedding_model_name, device=self.device.type
        )
        # Use the embedding model's tokenizer for token counting (context assembly, etc.).
        # Same source as TextChunker — the only local tokenizer available.
        self.tokenizer = self.embedding_model.tokenizer

        # -- loading index
        self.load_index()

        # -- CoT Template
        self.template = ALL_SYSTEM_PROMPT_TEMPLATES[self.instruction_lang][
            SystemPromptTypes.NAIVE
        ]
        self.assistant_role = SystemPrompts.get_by_language(
            self.instruction_lang
        ).llm_role_definition
        self.assistant_role = add_leading_space_if_needed(self.assistant_role)

    def load_index(self):
        self.qdrant_client = qdrant_client
        self.qdrant_collection_name = self.vector_store_name
        logging.info("Qdrant client initialized successfully.")

        # -- load BM25 path from Qdrant point payload
        results, _ = self.qdrant_client.scroll(
            collection_name=self.qdrant_collection_name,
            limit=1,
            with_payload=True,
        )
        if not results:
            raise ValueError(
                f"Qdrant collection '{self.qdrant_collection_name}' is empty."
            )
        bm25_path = results[0].payload["bm25_path"]
        self.bm25_retriever = fs.loader(bm25_path, pickle.load)

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
                mmr_scores = list(executor.map(compute_mmr_score, candidate_indices))

            # -- Select the document with the highest MMR score
            best_index = candidate_indices[np.argmax(mmr_scores)]
            selected_indices.append(best_index)
            candidate_indices.remove(best_index)

        return [all_texts[i] for i in selected_indices]

    def reciprocal_rank_fusion(
        self, bm25_ranks, dense_ranks, k=60, weight_bm25=0.4, weight_dense=0.6
    ):
        """
        Compute Reciprocal Rank Fusion (RRF) scores for the combined results.

        Parameters:
        ----------
            bm25_ranks : dict
                Document rankings from BM25. Keys are document indices, values are their ranks.
            dense_ranks : dict
                Document rankings from dense retrieval. Keys are document indices, values are their ranks.
            k : int
                The constant k used in the RRF formula.
            weight_bm25 : float
                The weight for the BM25 ranking scores.
            weight_dense : float
                The weight for the dense ranking scores.

        Returns:
        --------
            dict : Combined RRF scores for each document.
        """
        combined_scores = {}

        # -- RRF for BM25 results
        for doc_id, rank in bm25_ranks.items():
            if doc_id not in combined_scores:
                combined_scores[doc_id] = 0
            combined_scores[doc_id] += weight_bm25 / (k + rank)

        # -- RRF for dense results
        for doc_id, rank in dense_ranks.items():
            if doc_id not in combined_scores:
                combined_scores[doc_id] = 0
            combined_scores[doc_id] += weight_dense / (k + rank)

        return combined_scores

    def rank_documents(self, scores):
        """
        Rank documents based on their fusion scores.

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
        """
        Get the number of available devices (GPUs or CPU cores).
        """
        if self.device == "cuda":
            return torch.cuda.device_count()
        else:
            return torch.get_num_threads()

    def device_transfer(self, chunk, device):
        """
        Transfer a chunk of the tensor to the specified device -- CPU/GPU
        """
        return chunk.to(device, non_blocking=True)

    def parallel_chunk_transfer(self, tensor, device):
        """
        Transfer the tensor to the device in chunks using ThreadPoolExecutor,
        distributing across available devices (GPUs or CPU cores).

        Parameters:
            - tensor: The tensor to transfer.
            - device: The target device (e.g., "cuda" or "cpu").

        Returns:
            - The tensor on the target device, reassembled from the chunks.
        """
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)

        # Determine the number of available devices
        num_devices = self.available_device_count(device)
        num_chunks = max(1, num_devices)

        # Chunk the tensor based on the number of devices
        chunk_size = tensor.size(1) // num_chunks
        chunks = []

        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size
            if i == num_chunks - 1:
                end_idx = tensor.size(1)
            chunks.append(tensor[:, start_idx:end_idx])

        # Transfer chunks in parallel
        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            futures = [
                executor.submit(self.device_transfer, chunk, device) for chunk in chunks
            ]
            device_chunks = [future.result() for future in as_completed(futures)]

        return torch.cat(device_chunks, dim=1)

    def _calculate_frequency_penalty(self, input_length: int) -> float:
        """Calculate appropriate frequency penalty based on input length.

        Parameters:
            input_length (int): Length of input tokens

        Returns:
            float: Calculated frequency penalty
        """
        SHORT_CONTEXT = 512
        MEDIUM_CONTEXT = 1024

        # -- corresponding penalties
        SHORT_PENALTY = 0.01
        MEDIUM_PENALTY = 0.05
        LONG_PENALTY = 0.25

        if input_length <= SHORT_CONTEXT:
            return SHORT_PENALTY
        elif input_length <= MEDIUM_CONTEXT:
            return MEDIUM_PENALTY
        else:  # ignore LONG_CONTEXT here
            return LONG_PENALTY

    async def generate_text(
        self, prompt, temperature=1e-12, max_length=None, top_p=0.95, top_k=10
    ):
        """
        Generate text from the model with chunked input transfer using ThreadPoolExecutor.

        Parameters:
            prompt: The input prompt for the model.
            temperature: The temperature for text generation.
            max_length: The maximum length of the generated text.

        Returns:
            - The generated text.
        """
        max_new_tokens = (
            self.tokenizer.max_len_single_sentence if max_length is None else max_length
        )
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",  # NOTE:  No need to truncate or pad input during generation.
        )

        # -- transfer the input_ids to the device
        self.parallel_chunk_transfer(inputs["input_ids"], self.device.type)
        """
        check if model.generate returns empty strings..otherwise, return empty text.
        Sometimes, the model returns empty strings
        """
        # -- choose whether to use mixed precision based on the device
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
                ],
            )
            outputs = self.model.generate([prompt], sampling_params)
            return outputs[0].outputs[0].text.strip()
        else:
            input_length = inputs["input_ids"].shape[1]
            freq_penalty = self._calculate_frequency_penalty(input_length)
            formatted_prompt = f"""### Instruction: {prompt}"""
            try:
                output = await asyncio.to_thread(
                    self.model.create_completion,
                    prompt=formatted_prompt,
                    max_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    presence_penalty=1.0,
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

    async def custom_llm_chain(self, context, question):
        """Custom LLM chain

        Parameters:
            context (str): context
            question (str): input question

        Returns:
            str: LLM generated text
        """
        prompt_format = self.template.format(
            assistant_role=self.assistant_role, context=context, question=question
        )
        generated_text = await self.generate_text(prompt_format)
        return generated_text

    def chunk_document(self, document, num_chunks=3):
        """Split the document into sub-chunks."""
        words = document.split()
        chunk_size = max(1, len(words) // num_chunks)
        return [
            " ".join(words[i : i + chunk_size])
            for i in range(0, len(words), chunk_size)
        ]

    async def search_similar_texts_async(self, chunk, k=5, lambda_param=0.5):
        """Asynchronous version of search_similar_texts for a single chunk.

        Args:
            chunk (list): list of chunked text
            k (int, optional): number of context to return. Defaults to 5.
            lambda_param (float, optional): unused parameter kept for compatibility. Defaults to 0.5.

        Returns:
            list: list of searched contexts using only vector search
        """
        try:
            chunk_embedding = await self.create_embeddings_async([chunk])
            results = await asyncio.to_thread(
                self.qdrant_client.query_points,
                collection_name=self.qdrant_collection_name,
                query=chunk_embedding[0].tolist(),
                limit=k,
            )
            return [point.payload.get("text", "") for point in results.points]
        except Exception as e:
            logging.error(f"🚩 Error in vector search: {str(e)}")
            return []

    async def create_embeddings_async(self, texts):
        """
        Asynchronous version of create_embeddings.
        Creates embeddings using pre-loaded SentenceTransformer or tokenizer based on availability.

        Parameters:
            text (str): input text

        Returns
            prompt (text) embedding
        """
        try:
            if torch.cuda.is_available():
                # Use pre-loaded sentence transformer model
                with torch.no_grad():
                    embeddings = self.embedding_model.encode(
                        texts,  # use [texts] if texts does not work
                        convert_to_tensor=True,
                        show_progress_bar=False,
                        device=self.device.type,  # Ensure it uses the correct device
                    )
                    embeddings = embeddings.cpu().numpy()
            else:
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

            return embeddings

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            return np.array([])

    async def parallel_search(self, document, k=5):
        """Parallel search

        Parameters:
            document (str): input document
            k (int, optional): size of context to return. Defaults to 5.

        Returns:
            str: Merged unique context
        """
        chunks = self.chunk_document(document, k)
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self.search_similar_texts_async(chunk, k))
                for chunk in chunks
            ]
        results = [task.result() for task in tasks]
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

    async def invoke_async(self, question):
        """Use the parallelized search_similar_texts method.

        Parameters:
            question (str): input question

        Returns:
            tuple (str, str, dict): answer, conbined context, evaluation metrics
        """
        relevant_contexts = await self.search_similar_texts_async(question, k=5)
        combined_context = "\n\n".join(relevant_contexts)
        result_text = await self.custom_llm_chain(combined_context, question)
        answer = self._format_llm_response(result_text, self.instruction_lang)
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

    async def retrieve_context_async(self, question: str) -> dict:
        """Retrieval only — mirrors invoke_async but returns before generate_text.

        Used by the ``retrieve_rag_context`` Celery task so FastAPI can stream
        the LLM completion via SSE instead of waiting for local generation.

        Parameters
        ----------
        question : str
            User question

        Returns
        -------
        dict
            {"combined_context": str, "system_prompt": str, "contexts": list[str]}
        """
        relevant_contexts = await self.search_similar_texts_async(question, k=5)
        combined_context = "\n\n".join(relevant_contexts)
        return {
            "combined_context": combined_context,
            "system_prompt": self.assistant_role,
            "contexts": relevant_contexts,
        }

    def ainvoke(self, question):
        """Use the enhanced asynchronous invoke method.

        Parameters:
            question (str): input question

        Returns:
            tuple: result of invoke_async
        """
        return self.run_async_in_thread(self.invoke_async(question))

    @staticmethod
    def _format_llm_response(
        response: str, language: SystemPromptLangs = DEFAULT_SYSTEM_PROMPT_LANG
    ) -> str:
        """Format LLM response while preserving tables and structured data.
        Only removes template artifacts and prompt phrases.

        Parameters
        ----------
        response : str
            Raw response from the LLM
        language : SystemPromptLangs, optional
            Language of the reasoning instructions to remove,
            by default DEFAULT_SYSTEM_PROMPT_LANG

        Returns
        -------
        str
            Cleaned response with preserved formatting
        """
        return format_llm_response(response, language)
