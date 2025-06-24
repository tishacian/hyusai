import asyncio
import logging
import os
import pickle
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import faiss
import numpy as np
import torch
import weaviate
from langchain_community.vectorstores import Chroma
from sentence_transformers import SentenceTransformer
from torch import autocast

from src.chunker import BM25Retriever, cache_chunker_embedding_chain
from src.globalvariables import VECTOR_STORE_PATH, IndexType
from src.metrics import Evaluatrix
from src.reasoning_instructions import DEFAULT_INSTRUCTION_LANG, InstructionLangs
from src.utils import format_llm_response

if torch.cuda.is_available():
    from vllm import SamplingParams

warnings.simplefilter(action="ignore", category=FutureWarning)
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


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
    ):
        """Custom LLMChain

        Parameters
        ----------
            tokenizer (tokenizer) : tokenizer
            model (model) : llm model
            embedding_model_name (str), optional : embedding model name. The default is "sentence-transformers/all-mpnet-base-v2".
            index_type (str), optional : index type. The default is "faiss".

        Raises
        ------
            ValueError : if model and tokenizer is None

        Returns
        -------
        None.

        """
        self.tokenizer = tokenizer
        self.model = model
        self.model_name = model_name
        self.vector_store_name = vector_store_name
        self.device = torch.device(
            "cuda:0"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )

        if self.model is None or self.tokenizer is None:
            raise ValueError(
                f"🚩 Failed to load model or tokenizer. \nModel: {None if not self.model else self.model} and "
                + f"\nTokenizer: {None if not self.tokenizer else self.tokenizer} cannot be None"
            )

        self.index_type = index_type
        self.embedding_model_name = embedding_model_name
        # --initialize embedding model
        try:
            if self.index_type == IndexType.FAISS:
                self.embedding_model_name = "all-MiniLM-L6-v2"
                self.embedding_model = SentenceTransformer(
                    self.embedding_model_name, device=self.device.type
                )
            elif self.index_type == IndexType.CHROMA:
                self.embedding_model_name = "sentence-transformers/all-mpnet-base-v2"
                self.embedding_model = SentenceTransformer(
                    self.embedding_model_name, device=self.device.type
                )
            elif self.index_type == IndexType.WEAVIATE:
                self.embedding_model = weaviate.Client("http://localhost:8080")
                self.class_name = "Document"
                if not self.embedding_model.schema.contains(self.class_name):
                    self.embedding_model.schema.create_class(
                        {
                            "class": self.class_name,
                            "vectorizer": "none",
                        }
                    )
            else:
                raise ValueError(
                    "🚩 Unsupported embedding type. Choose 'faiss', 'chroma', or 'weaviate'."
                )
        except Exception as e:
            logging.error(f"🚩 Error initializing embedding model: {e}")
            raise

        # -- loading index
        self.load_index()

        # -- CoT Template
        self.template = """[INST] You are an AI assistant specialized in providing precise and detailed information. Focus on important information that directly addresses the main topic or question.
                            Include relevant details that provide context or support your points.
                            Ensure the information is engaging by highlighting unique accuracy, precision, completeness, conciseness, clarity, relevance,
                            objectivity, and emotional resonance.

                            Your task is to answer the following question based on the given context:
                            {context}

                            Question: {question}

                            Answer: [/INST]"""

    def load_index(self):
        # -- load BM25 retriever first
        vector_store_path = VECTOR_STORE_PATH / self.vector_store_name
        self.bm25_retriever = BM25Retriever.load_bm25(
            vector_store_path / "bm25_retriever.pkl"
        )
        if self.index_type == IndexType.FAISS:
            if os.path.exists(
                str(vector_store_path / "faiss.index")
            ) and os.path.exists(str(vector_store_path / "faiss.pkl")):
                self.index = faiss.read_index(str(vector_store_path / "faiss.index"))
                with open(str(vector_store_path / "faiss.pkl"), "rb") as f:
                    self.texts = pickle.load(f)
                logging.info("FAISS index and texts loaded successfully.")
            else:
                raise FileNotFoundError(
                    "🚩 FAISS index or texts file not found. Please create an index first."
                )
        elif self.index_type == IndexType.CHROMA:
            self.vectorstore = Chroma(
                persist_directory=str(vector_store_path),
                embedding_function=self.embedding_model,
            )
            logging.info("Chroma index loaded successfully.")
        elif self.index_type == IndexType.WEAVIATE:
            self.weaviate_client = weaviate.Client("http://localhost:8080")
            self.class_name = "Document"
            if not self.weaviate_client.schema.contains(self.class_name):
                raise ValueError(
                    "🚩 Weaviate index not found. Please create an index first."
                )
            logging.info("Weaviate index loaded successfully.")
        else:
            raise ValueError(
                "Unsupported index type. Choose 'faiss', 'chroma', or 'weaviate'."
            )

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
        self, bm25_ranks, faiss_ranks, k=60, weight_bm25=0.4, weight_faiss=0.6
    ):
        """
        Compute Reciprocal Rank Fusion (RRF) scores for the combined results.

        Parameters:
        ----------
            bm25_ranks : dict
                Document rankings from BM25. Keys are document indices, values are their ranks.
            faiss_ranks : dict
                Document rankings from FAISS. Keys are document indices, values are their ranks.
            k : int
                The constant k used in the RRF formula.
            weight_bm25 : float
                The weight for the BM25 ranking scores.
            weight_faiss : float
                The weight for the FAISS ranking scores.

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

        # -- RRF for FAISS results
        for doc_id, rank in faiss_ranks.items():
            if doc_id not in combined_scores:
                combined_scores[doc_id] = 0
            combined_scores[doc_id] += weight_faiss / (k + rank)

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
        """
        Transfer the tensor to the device in chunks using ThreadPoolExecutor,
        distributing across available devices (GPUs or CPU cores).

        Parameters:
            - tensor: The tensor to transfer.
            - device: The target device (e.g., "cuda:0" or "cpu").

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
        inputs_on_device = self.parallel_chunk_transfer(
            inputs["input_ids"], self.device.type
        )
        """
        check if model.generate returns empty strings..otherwise, return empty text.
        Sometimes, the model returns empty strings
        """
        # -- choose whether to use mixed precision based on the device
        use_mixed_precision = True if self.device.type == "cuda:0" else False
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
            with (
                autocast(device_type=self.device.type)
                if use_mixed_precision
                else torch.no_grad()
            ):
                try:
                    outputs = self.model.generate(
                        inputs_on_device,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                        num_return_sequences=1,
                        do_sample=True,
                        top_p=top_p,
                        top_k=top_k,
                        repetition_penalty=1.0,
                        pad_token_id=self.tokenizer.pad_token_id,
                    )
                    text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                except (IndexError, ValueError, RuntimeError, KeyError) as e:
                    logging.error(
                        f"🚩 An error occurred during text generation: {str(e)}"
                    )
                    text = ""

            return text

    async def custom_llm_chain(self, context, question):
        """Custom LLM chain

        Parameters:
            context (str): context
            question (str): input question

        Returns:
            str: LLM generated text
        """
        prompt_format = self.template.format(context=context, question=question)
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
            lambda_param (float, optional): search hyper-parameter. Defaults to 0.5.

        Returns:
            list: list of searched contexts
        """
        # -- BM25 search
        bm25_scores = self.bm25_retriever.get_scores(chunk)
        bm25_ranked_indices = np.argsort(bm25_scores)[::-1]
        bm25_ranks = {doc_id: rank for rank, doc_id in enumerate(bm25_ranked_indices)}

        # -- vector search
        if self.index_type == IndexType.FAISS:
            chunk_embedding = await self.create_embeddings_async([chunk])
            faiss.normalize_L2(chunk_embedding)
            _, faiss_indices = self.index.search(chunk_embedding, k)
            dense_ranks = {
                str(doc_id): rank for rank, doc_id in enumerate(faiss_indices[0])
            }
        elif self.index_type in [IndexType.CHROMA, IndexType.WEAVIATE]:
            chunk_embedding = await self.create_embeddings_async([chunk])
            dense_results = await self.vector_search_async(chunk_embedding, k)
            dense_ranks = {
                str(doc_id): rank for rank, doc_id in enumerate(dense_results)
            }

        # -- combine BM25 and dense retrieval results
        combined_rrf_scores = self.reciprocal_rank_fusion(bm25_ranks, dense_ranks, k=k)
        ranked_docs = self.rank_documents(combined_rrf_scores)
        # --
        if isinstance(self.bm25_retriever.documents, list):
            ranked_docs = [
                int(doc_id)
                for doc_id in ranked_docs[:k]
                if isinstance(doc_id, (int, np.integer))
            ]
        elif isinstance(self.bm25_retriever.documents, dict):
            ranked_docs = [doc_id for doc_id in ranked_docs[:k]]

        return [self.bm25_retriever.documents[doc_id] for doc_id in ranked_docs[:k]]

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
                # Handle different index types
                if self.index_type == IndexType.CHROMA:
                    embeddings = np.array(self.embedding_model.embed_documents(texts))
                elif self.index_type in [IndexType.FAISS, IndexType.WEAVIATE]:
                    try:
                        embeddings = self.embedding_model.encode(
                            texts,
                            convert_to_tensor=True,
                            show_progress_bar=False,
                            device=self.device.type,  # Ensure it uses the correct device
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

    async def vector_search_async(self, embedding, k):
        """Asynchronous vector search for Chroma and Weaviate.

        Args:
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
                self.weaviate_client.query.get(self.class_name, ["page_content"])
                .with_near_vector({"vector": embedding.tolist()})
                .with_limit(k)
                .do
            )
            return [
                result["page_content"]
                for result in results["data"]["Get"][self.class_name]
            ]

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
        answer = self._format_llm_response(result_text)
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
        response: str, language: InstructionLangs = DEFAULT_INSTRUCTION_LANG
    ) -> str:
        """Format LLM response while preserving tables and structured data.
        Only removes template artifacts and prompt phrases.

        Parameters
        ----------
        response : str
            Raw response from the LLM
        language : InstructionLangs, optional
            Language of the reasoning instructions to remove,
            by default DEFAULT_INSTRUCTION_LANG

        Returns
        -------
        str
            Cleaned response with preserved formatting
        """
        return format_llm_response(response, language)
