import os
import re
import nltk
import threading
import GPUtil
import torch
import psutil
import pynvml
from typing import Dict, List, Tuple, Optional, defaultdict
import datasets
import numpy as np
from time import time, sleep
from tqdm import tqdm
import pandas as pd
from modeltokenizer import load_model_and_tokenizer
from globalvariables import Models, REPO_PATH, ChunkingMethod
from customchain_naive import (
    CustomLLMChain,
)  # change this for different pipeline [1]
from embedding import EmbeddingVectors
from chunker import TextChunker
from sklearn.metrics.pairwise import cosine_similarity
from rouge import Rouge
from dataclasses import dataclass
from codecarbon import EmissionsTracker


pipeline = "Naive"


@dataclass
class GPUMetrics:
    gpu_utilization: float
    gpu_memory_used: float
    gpu_memory_total: float
    power_usage: float  # in watts
    timestamp: float


@dataclass
class CPUMetrics:
    cpu_percent: float
    memory_percent: float
    power_usage: float  # in watts
    timestamp: float


@dataclass
class EmissionMetrics:
    energy_consumed: float  # in kWh
    co2_emissions: float  # in kg
    timestamp: float


class ResourceMonitor:
    def __init__(
        self, sampling_interval: float = 0.1, country_code: str = "FR"
    ):
        """Initialize the resource monitor"""
        self.sampling_interval = sampling_interval
        self.country_code = country_code
        self.is_monitoring = False
        self.gpu_metrics: List[GPUMetrics] = []
        self.cpu_metrics: List[CPUMetrics] = []
        self.emission_metrics: List[EmissionMetrics] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self.cpu = psutil.cpu_times_percent()
        self.cpu_power_start = self._get_cpu_power()

        try:
            self.emissions_tracker = EmissionsTracker(
                project_name="rag_evaluation",
                output_dir="emission_logs",
                log_level="warning",
                measure_power_secs=self.sampling_interval,
                save_to_file=False,
            )
        except Exception as e:
            print(f"Warning: Could not initialize emissions tracker: {e}")
            self.emissions_tracker = None

        self.carbon_intensity = self._get_carbon_intensity(country_code)

    def _get_cpu_power(self) -> float:
        """Get CPU power consumption estimate"""
        try:
            freq = psutil.cpu_freq()
            if freq is None:
                return 65.0  # default TDP for a typical CPU

            base_power = 65.0
            freq_ratio = freq.current / freq.max if freq.max > 0 else 1.0
            cpu_percent = psutil.cpu_percent() / 100.0

            return base_power * freq_ratio * cpu_percent
        except Exception as e:
            print(f"Warning: Could not get CPU power: {e}")
            return 65.0

    def _get_gpu_power(self) -> float:
        """Get GPU power consumption"""
        try:
            if torch.cuda.is_available():
                gpu = GPUtil.getGPUs()[0]
                if hasattr(gpu, "powerUsage") and gpu.powerUsage is not None:
                    return float(gpu.powerUsage)
                else:
                    return float(gpu.load * 250)
            return 0.0
        except Exception as e:
            print(f"Warning: Could not get GPU power: {e}")
            return 0.0

    def _get_carbon_intensity(self, country_code: str) -> float:
        """Get carbon intensity for a given country"""
        carbon_intensities = {
            "US": 385,
            "CN": 555,
            "IN": 725,
            "GB": 225,
            "DE": 350,
            "FR": 70,
            "JP": 460,
        }
        return carbon_intensities.get(country_code, 475)

    def _collect_metrics(self):
        """Collect metrics continuously"""
        start_time = time()
        cumulative_energy = 0.0

        while self.is_monitoring:
            try:
                current_time = time()
                duration = current_time - start_time

                # Get CPU metrics
                cpu_percent = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                cpu_power = self._get_cpu_power()

                self.cpu_metrics.append(
                    CPUMetrics(
                        cpu_percent=cpu_percent,
                        memory_percent=memory.percent,
                        power_usage=cpu_power,
                        timestamp=current_time,
                    )
                )

                # Get GPU metrics if available
                gpu_power = 0.0
                if torch.cuda.is_available():
                    gpu = GPUtil.getGPUs()[0]
                    gpu_power = self._get_gpu_power()

                    self.gpu_metrics.append(
                        GPUMetrics(
                            gpu_utilization=gpu.load * 100,
                            gpu_memory_used=gpu.memoryUsed,
                            gpu_memory_total=gpu.memoryTotal,
                            power_usage=gpu_power,
                            timestamp=current_time,
                        )
                    )

                # Calculate energy and emissions
                total_power = cpu_power + gpu_power
                energy_kwh = (total_power * self.sampling_interval) / (
                    1000 * 3600
                )
                cumulative_energy += energy_kwh
                emissions_kg = (energy_kwh * self.carbon_intensity) / 1000

                self.emission_metrics.append(
                    EmissionMetrics(
                        energy_consumed=energy_kwh,
                        co2_emissions=emissions_kg,
                        timestamp=current_time,
                    )
                )

                sleep(self.sampling_interval)

            except Exception as e:
                print(f"Error collecting metrics: {e}")
                sleep(self.sampling_interval)

    def start_monitoring(self):
        """Start collecting metrics"""
        self.is_monitoring = True
        self.gpu_metrics = []
        self.cpu_metrics = []
        self.emission_metrics = []
        if self.emissions_tracker:
            try:
                self.emissions_tracker.start()
            except Exception as e:
                print(f"Warning: Could not start emissions tracker: {e}")

        self._monitor_thread = threading.Thread(target=self._collect_metrics)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()

    def stop_monitoring(self) -> Dict[str, float]:
        """Stop collecting metrics and return summary"""
        self.is_monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(
                timeout=2.0
            )  # 2 seconds for thread to finish

        emissions = 0.0
        if self.emissions_tracker:
            try:
                emissions = self.emissions_tracker.stop()
            except Exception as e:
                print(f"Warning: Could not get emissions from tracker: {e}")

        # Calculate metrics
        metrics_summary = {
            "cpu_percent_avg": (
                np.mean([m.cpu_percent for m in self.cpu_metrics])
                if self.cpu_metrics
                else 0.0
            ),
            "memory_percent_avg": (
                np.mean([m.memory_percent for m in self.cpu_metrics])
                if self.cpu_metrics
                else 0.0
            ),
            "cpu_power_avg": (
                np.mean([m.power_usage for m in self.cpu_metrics])
                if self.cpu_metrics
                else 0.0
            ),
            "total_energy_consumed": (
                sum(m.energy_consumed for m in self.emission_metrics)
                if self.emission_metrics
                else 0.0
            ),
            "total_co2_emissions": (
                sum(m.co2_emissions for m in self.emission_metrics)
                if self.emission_metrics
                else 0.0
            ),
            "carbon_intensity": self.carbon_intensity,
            "emissions_tracked": emissions,
        }

        # Add GPU metrics if available
        if self.gpu_metrics:
            metrics_summary.update(
                {
                    "gpu_utilization_avg": np.mean(
                        [m.gpu_utilization for m in self.gpu_metrics]
                    ),
                    "gpu_memory_used_avg": np.mean(
                        [m.gpu_memory_used for m in self.gpu_metrics]
                    ),
                    "gpu_memory_used_max": max(
                        m.gpu_memory_used for m in self.gpu_metrics
                    ),
                    "gpu_memory_total": self.gpu_metrics[0].gpu_memory_total,
                    "gpu_power_avg": np.mean(
                        [m.power_usage for m in self.gpu_metrics]
                    ),
                }
            )

        return metrics_summary


class ExtraMetrics:
    def __init__(self):
        """Initialize RAG evaluation metrics calculator"""
        self.rouge = Rouge()
        try:
            nltk.download("punkt", quiet=True)
        except Exception as e:
            print(f"Error initializing NLTK: {e}")

    def compute_ndcg(
        self,
        retrieved_docs: List[str],
        relevant_docs: List[str],
        embeddings_model,
        k: int = None,
    ) -> float:
        """Compute Normalized Discounted Cumulative Gain"""
        if not retrieved_docs or not relevant_docs:
            return 0.0

        if k is not None:
            retrieved_docs = retrieved_docs[:k]

        def dcg_at_k(r, k):
            r = np.asfarray(r)[:k]
            if r.size:
                return np.sum(
                    np.subtract(np.power(2, r), 1)
                    / np.log2(np.arange(2, r.size + 2))
                )
            return 0.0

        # Calculate relevance scores
        relevance_scores = []
        for doc in retrieved_docs:
            max_score = 0
            doc_embedding = embeddings_model.encode(
                doc, show_progress_bar=False
            )

            for rel_doc in relevant_docs:
                rel_embedding = embeddings_model.encode(
                    rel_doc, show_progress_bar=False
                )
                similarity = float(
                    cosine_similarity(
                        doc_embedding.reshape(1, -1),
                        rel_embedding.reshape(1, -1),
                    )[0][0]
                )
                max_score = max(max_score, similarity)

            relevance_scores.append(max_score)

        dcg = dcg_at_k(relevance_scores, len(retrieved_docs))
        idcg = dcg_at_k(
            sorted(relevance_scores, reverse=True), len(retrieved_docs)
        )

        return dcg / idcg if idcg > 0 else 0.0

    def compute_rouge_scores(
        self, hypothesis: str, reference: str
    ) -> Dict[str, float]:
        """Compute ROUGE scores"""
        if not hypothesis or not reference:
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

        try:
            hypothesis = str(hypothesis).strip()
            reference = str(reference).strip()

            if not hypothesis or not reference:
                return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

            if len(hypothesis.split()) == 1 or len(reference.split()) == 1:
                exact_match = float(hypothesis.lower() == reference.lower())
                return {
                    "rouge1": exact_match,
                    "rouge2": 0.0,
                    "rougeL": exact_match,
                }

            scores = self.rouge.get_scores(hypothesis, reference)[0]
            return {
                "rouge1": float(scores["rouge-1"]["f"]),
                "rouge2": float(scores["rouge-2"]["f"]),
                "rougeL": float(scores["rouge-l"]["f"]),
            }

        except Exception as e:
            print(f"Error computing ROUGE scores: {e}")
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

    def evaluate_rag(
        self,
        retrieved_docs: List[str],
        generated_answer: str,
        relevant_docs: List[str],
        ground_truth: str,
        embeddings_model,
        k: int = 12,
    ) -> Dict[str, float]:
        """Comprehensive RAG evaluation with all metrics"""
        try:
            metrics = {}
            metrics["ndcg"] = self.compute_ndcg(
                retrieved_docs, relevant_docs, embeddings_model, k
            )
            rouge_scores = self.compute_rouge_scores(
                generated_answer, ground_truth
            )
            metrics.update(rouge_scores)
            return metrics

        except Exception as e:
            print(f"Error in evaluate_rag: {e}")
            return {
                "ndcg": 0.0,
                "rouge1": 0.0,
                "rouge2": 0.0,
                "rougeL": 0.0,
            }


class HAHRAGEvaluator:
    def __init__(self, country_code: str = "US"):
        """Initialize model and monitoring based on available hardware

        Args:
            country_code: ISO country code for CO2 emissions calculation
        """
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.model_name = (
            Models.LLAMA3 if torch.cuda.is_available() else Models.LAMINIGPT
        )
        self.model, self.tokenizer = load_model_and_tokenizer(
            self.model_name, REPO_PATH
        )
        if self.model is None or self.tokenizer is None:
            raise ValueError("Failed to load model or tokenizer")

        self.compute_metricx = ExtraMetrics()
        self.resource_monitor = ResourceMonitor(
            sampling_interval=0.1,
        )

    def load_datasets(self) -> Dict[str, datasets.Dataset]:
        dataset_dict = {}
        nq_dataset = datasets.load_dataset(
            "natural_questions", split="validation"
        )
        if nq_dataset is not None:
            dataset_dict["nq"] = nq_dataset

        triviaqa_dataset = datasets.load_dataset(
            "trivia_qa", "unfiltered", split="validation"
        )
        if triviaqa_dataset is not None:
            dataset_dict["triviaqa"] = triviaqa_dataset.select_columns(
                ["question", "answer"]
            )

        hotpotqa_dataset = datasets.load_dataset(
            "hotpot_qa",
            "distractor",
            split="validation",
            trust_remote_code=True,
        )
        if hotpotqa_dataset is not None:
            dataset_dict["hotpotqa"] = hotpotqa_dataset.select_columns(
                ["question", "answer"]
            )

        narrativeqa_dataset = datasets.load_dataset(
            "narrativeqa", split="validation"
        )
        if narrativeqa_dataset is not None:
            dataset_dict["narrativeqa"] = narrativeqa_dataset.select_columns(
                ["question", "answers"]
            )

        return dataset_dict

    def extract_qa_pair(
        self, example_idx: int, dataset: datasets.Dataset, dataset_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        try:
            example = dataset[example_idx]

            if dataset_name == "nq":
                question = example["question"]["text"]
                annotations = example["annotations"]
                answer = None

                for annotation_idx in range(len(annotations["short_answers"])):
                    short_answers = annotations["short_answers"][
                        annotation_idx
                    ]
                    if (
                        short_answers
                        and "text" in short_answers
                        and short_answers["text"]
                    ):
                        answer = short_answers["text"][0]
                        break

                if question and answer:
                    return str(question), str(answer)
                return None, None

            elif dataset_name == "triviaqa":
                if isinstance(example["answer"], dict):
                    return str(example["question"]), str(
                        example["answer"]["value"]
                    )
                return str(example["question"]), str(example["answer"])

            elif dataset_name == "hotpotqa":
                return str(example["question"]), str(example["answer"])

            elif dataset_name == "narrativeqa":
                question = (
                    example["question"]["text"]
                    if isinstance(example["question"], dict)
                    else example["question"]
                )
                if isinstance(example["answers"], list) and example["answers"]:
                    answer = example["answers"][0]["text"]
                else:
                    answer = example["answers"][0]["text"]
                return str(question), str(answer)

        except Exception as e:
            print(f"Error extracting QA pair from {dataset_name}: {e}")
            print(f"Example causing error: {example}")
            return None, None

        return None, None

    def evaluate_dataset(
        self, dataset: datasets.Dataset, dataset_name: str
    ) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        batch_size = 100
        evaluation_data = []
        self.resource_monitor.start_monitoring()

        try:
            # Process QA pairs
            qa_pairs = []
            for idx in range(min(batch_size, len(dataset))):
                question, answer = self.extract_qa_pair(
                    idx, dataset, dataset_name
                )
                if question and answer:
                    qa_pairs.append((question, answer))

            combined_texts = [f"{q} {a}" for q, a in qa_pairs]
            chunker = TextChunker(self.tokenizer, self.model)
            embedding_vectors = EmbeddingVectors(
                self.tokenizer,
                self.model,
                create_new_vs=True,
                existing_vector_store="",
                new_vs_name=f"evaluation_store_{dataset_name}",
                embedding_type="faiss",
            )

            chunks = []
            for text in combined_texts:
                chunks.extend(
                    chunker.chunker(
                        text, method=ChunkingMethod.RECURSIVE_CHARACTER
                    )
                )

            vector_store = embedding_vectors.create_and_save_index(chunks)

            chain = CustomLLMChain(
                self.tokenizer,
                self.model,
                self.model_name,
                f"faiss_evaluation_store_{dataset_name}",
                index_type="faiss",
            )

            metrics = defaultdict(list)
            progress_bar = tqdm(qa_pairs, desc="Evaluating QA pairs")
            for question, reference in progress_bar:
                start_time = time()
                response, context, eval_metrics = chain.ainvoke(question)

                evaluation_data.append(
                    {
                        "question": question,
                        "response": response,
                        "context": context,
                        "reference": reference,
                    }
                )

                # -- extra metrics
                extra_metrics = self.compute_metricx.evaluate_rag(
                    retrieved_docs=context,
                    generated_answer=response,
                    relevant_docs=[reference],
                    ground_truth=reference,
                    embeddings_model=embedding_vectors.embedding_model,
                )

                metrics.update(extra_metrics)
                for k, v in eval_metrics.items():
                    metrics[k].append(v)
                metrics["latency"].append(time() - start_time)

                avg_metrics = {
                    k: np.mean(v) for k, v in metrics.items() if k != "latency"
                }
                progress_bar.set_postfix(
                    rouge1=f"{avg_metrics.get('rouge1', 0):.3f}",
                    ndcg=f"{avg_metrics.get('ndcg', 0):.3f}",
                )

        finally:
            # Stop resource monitoring and get summary
            print("\nCollecting resource usage metrics...")
            resource_metrics = self.resource_monitor.stop_monitoring()

        # Save detailed evaluation data
        self._save_detailed_results(
            metrics,
            resource_metrics,
            dataset_name,
        )

        # --compute average metrics
        avg_metrics = {
            k: np.mean(v) for k, v in metrics.items() if k != "latency"
        }
        avg_latency = np.mean(metrics["latency"])

        return avg_metrics, avg_latency, resource_metrics

    def _save_detailed_results(
        self,
        metrics: Dict[str, List],
        resource_metrics: Dict[str, float],
        dataset_name: str,
    ):
        """Save detailed evaluation results to files

        Args:
            metrics: Dictionary of metric lists
            resource_metrics: Dictionary of resource usage metrics
            dataset_name: Name of the dataset being evaluated
        """
        output_dir = os.path.join("evaluation_results", dataset_name)
        os.makedirs(output_dir, exist_ok=True)
        metrics_df = pd.DataFrame(metrics)
        metrics_df.to_csv(
            os.path.join(output_dir, f"{pipeline}_metrics_over_time.csv"),
            index=False,
        )
        resource_df = pd.DataFrame([resource_metrics])
        resource_df.to_csv(
            os.path.join(output_dir, f"{pipeline}_resource_metrics.csv"),
            index=False,
        )


def main():
    try:
        country_code = os.getenv("COUNTRY_CODE", "FR")
        evaluator = HAHRAGEvaluator(country_code=country_code)
        datasets_dict = evaluator.load_datasets()

        all_metrics = {}
        latencies = {}
        resource_metrics = {}
        output_base_dir = "evaluation_results"
        os.makedirs(output_base_dir, exist_ok=True)
        summary_data = []
        # --
        for dataset_name, dataset in datasets_dict.items():
            print(f"\n{'*'*50}")
            print(f"Evaluating {dataset_name}...")
            print(f"{'*'*50}")
            metrics, latency, res_metrics = evaluator.evaluate_dataset(
                dataset, dataset_name
            )
            all_metrics[dataset_name] = metrics
            latencies[dataset_name] = latency
            resource_metrics[dataset_name] = res_metrics

            summary_data.append(
                {
                    "latency": latency,
                    **metrics,
                    **{f"resource_{k}": v for k, v in res_metrics.items()},
                }
            )

        summary_df = pd.DataFrame(summary_data)
        summary_path = os.path.join(
            output_base_dir, f"{pipeline}_evaluation_summary.csv"
        )
        summary_df.to_csv(summary_path, index=False)

        print("\nEvaluation completed. Results saved to:")
        print(f"- Summary CSV: {summary_path}")

    except Exception as e:
        print(f"Error in main execution: {e}")
        raise


if __name__ == "__main__":
    main()
