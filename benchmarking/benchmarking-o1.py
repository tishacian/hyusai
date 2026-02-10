import os
import threading
from dataclasses import dataclass
from time import sleep, time
from typing import Dict, List, Optional, Tuple

import datasets
import GPUtil
import nltk
import numpy as np
import pandas as pd
import psutil
import torch
from codecarbon import EmissionsTracker
from customchain_hah_o1 import (
    CustomLLMChain,
)
from rouge import Rouge
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm

from chunker import TextChunker
from embedding import EmbeddingVectors
from globalvariables import REPO_PATH, ChunkingMethod, Models
from modeltokenizer import load_model_and_tokenizer

pipeline = "HAH_o1"
evaluation_dir = "evaluation_results-o1"


@dataclass
class ComputeCosts:
    """Constants for compute costs in euros"""

    CPU_COST_PER_HOUR: float = 0.05  # €/hour for CPU compute
    GPU_COST_PER_HOUR: float = 0.95  # €/hour for GPU compute
    MEMORY_COST_PER_GB_HOUR: float = 0.01  # €/GB-hour for memory
    POWER_COST_PER_KWH: float = 0.15  # €/kWh for electricity


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
    def __init__(self, sampling_interval: float = 0.1, country_code: str = "FR"):
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
                energy_kwh = (total_power * self.sampling_interval) / (1000 * 3600)
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
            self._monitor_thread.join(timeout=2.0)  # 2 seconds for thread to finish

        emissions = 0.0
        if self.emissions_tracker:
            try:
                emissions = self.emissions_tracker.stop()
            except Exception as e:
                print(f"Warning: Could not get emissions from tracker: {e}")

        # -- Calculate metrics
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

        # -- Add GPU metrics if available
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
                    "gpu_power_avg": np.mean([m.power_usage for m in self.gpu_metrics]),
                }
            )

        return metrics_summary


class ResourceCostCalculator:
    def __init__(self, sampling_interval: float = 0.1):
        """Initialize cost calculator

        Args:
            sampling_interval: Time interval between resource measurements in seconds
        """
        self.sampling_interval = sampling_interval
        self.costs = ComputeCosts()

    def calculate_costs(self, resource_metrics: Dict) -> Dict[str, float]:
        """Calculate costs from resource metrics

        Args:
            resource_metrics: Dictionary containing resource usage metrics

        Returns:
            Dictionary with calculated costs in euros
        """
        hours = self.sampling_interval / 3600  # sampling per hour
        cpu_cost = (
            resource_metrics.get("cpu_percent_avg", 0)
            / 100
            * self.costs.CPU_COST_PER_HOUR
            * hours
        )  # compute cost
        gpu_cost = 0
        if "gpu_utilization_avg" in resource_metrics:
            gpu_cost = (
                resource_metrics["gpu_utilization_avg"]
                / 100
                * self.costs.GPU_COST_PER_HOUR
                * hours
            )

        # -  compute costs
        memory_gb = (
            resource_metrics.get("memory_percent_avg", 0)
            / 100
            * resource_metrics.get("total_memory_gb", 16)
        )
        memory_cost = memory_gb * self.costs.MEMORY_COST_PER_GB_HOUR * hours
        total_energy_kwh = resource_metrics.get("total_energy_consumed", 0)
        power_cost = total_energy_kwh * self.costs.POWER_COST_PER_KWH
        total_cost = cpu_cost + gpu_cost + memory_cost + power_cost

        return {
            "compute_cost_cpu": cpu_cost,
            "compute_cost_gpu": gpu_cost,
            "memory_cost": memory_cost,
            "power_cost": power_cost,
            "total_cost": total_cost,
        }

    def calculate_cost_per_query(self, total_cost: float, num_queries: int) -> float:
        """Calculate cost per query

        Args:
            total_cost: Total cost in euros
            num_queries: Number of queries processed

        Returns:
            Cost per query in euros
        """
        return total_cost / max(num_queries, 1)


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
                    np.subtract(np.power(2, r), 1) / np.log2(np.arange(2, r.size + 2))
                )
            return 0.0

        # -- compute relevance score...
        relevance_scores = []
        for doc in retrieved_docs:
            max_score = 0
            doc_embedding = embeddings_model.encode(doc, show_progress_bar=False)

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
        idcg = dcg_at_k(sorted(relevance_scores, reverse=True), len(retrieved_docs))

        return dcg / idcg if idcg > 0 else 0.0

    def compute_rouge_scores(self, hypothesis: str, reference: str) -> Dict[str, float]:
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
            rouge_scores = self.compute_rouge_scores(generated_answer, ground_truth)
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
    def __init__(self, country_code: str = "FR"):
        """Initialize model and monitoring based on available hardware

        Args:
            country_code: ISO country code for CO2 emissions calculation
        """
        self.country_code = country_code
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
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
            country_code=self.country_code,
        )
        # -- cost evaluator
        self.cost_calculator = ResourceCostCalculator(sampling_interval=0.1)

    def load_datasets(self) -> Dict[str, datasets.Dataset]:
        """Load question answering datasets for evaluation.

        Returns:
            Dict[str, datasets.Dataset]: Dictionary of loaded datasets
        """
        dataset_dict = {}

        # Load HotpotQA dataset
        try:
            print("Loading HotpotQA dataset...")
            hotpotqa_dataset = datasets.load_dataset(
                "hotpot_qa",
                "distractor",
                split="validation",
                trust_remote_code=True,
            )
            if hotpotqa_dataset is not None:
                dataset_dict["hotpotqa"] = hotpotqa_dataset.select_columns(
                    ["question", "answer", "supporting_facts"]
                )
                print("Successfully loaded HotpotQA dataset")
        except Exception as e:
            print(f"Error loading HotpotQA dataset: {e}")

        # Load SQUAD-Shifts dataset
        try:
            print("Loading SQUAD-Shifts dataset...")
            squad_dataset = datasets.load_dataset(
                "squadshifts", "new_wiki", split="test"
            )
            if squad_dataset is not None:
                dataset_dict["squadshifts"] = squad_dataset.select_columns(
                    ["question", "answers", "context"]
                )
                print("Successfully loaded SQUAD-Shifts dataset")
        except Exception as e:
            print(f"Error loading SQUAD-Shifts dataset: {e}")

        # Load CommonsenseQA dataset
        try:
            print("Loading CommonsenseQA dataset...")
            commonsenseqa_dataset = datasets.load_dataset(
                "commonsense_qa", split="validation"
            )
            if commonsenseqa_dataset is not None:
                dataset_dict["commonsenseqa"] = commonsenseqa_dataset.select_columns(
                    ["question", "choices", "answerKey"]
                )
                print("Successfully loaded CommonsenseQA dataset")
        except Exception as e:
            print(f"Error loading CommonsenseQA dataset: {e}")

        if not dataset_dict:
            raise ValueError("No datasets could be loaded successfully")

        print(
            f"Successfully loaded {len(dataset_dict)} datasets: {list(dataset_dict.keys())}"
        )
        return dataset_dict

    def extract_qa_pair(
        self, example_idx: int, dataset: datasets.Dataset, dataset_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract question-answer pairs from different dataset formats.

        Args:
            example_idx (int): Index of the example to extract
            dataset (datasets.Dataset): The dataset to extract from
            dataset_name (str): Name of the dataset type

        Returns:
            Tuple[Optional[str], Optional[str]]: Question and answer pair, or None if extraction fails
        """
        try:
            example = dataset[example_idx]

            if dataset_name == "hotpotqa":
                question = str(example["question"])
                answer = str(example["answer"])
                supporting_facts = example.get("supporting_facts", [])
                if supporting_facts:
                    supporting_text = " Supporting facts: " + " ".join(
                        [f"{fact[0]}: {fact[1]}" for fact in supporting_facts]
                    )
                    answer = f"{answer}{supporting_text}"
                return question, answer

            elif dataset_name == "squadshifts":
                question = str(example["question"])
                answer_text = (
                    example["answers"]["text"][0] if example["answers"]["text"] else ""
                )
                context = example.get("context", "")
                if context:
                    context_preview = (
                        context[:500] + "..." if len(context) > 500 else context
                    )
                    answer = f"{answer_text} Context: {context_preview}"
                else:
                    answer = answer_text
                return question, answer

            elif dataset_name == "commonsenseqa":
                question = str(example["question"])
                choices = example["choices"]
                answer_key = example["answerKey"]

                # Find the correct answer from choices
                answer_text = ""
                for choice in choices["text"]:
                    if choices["label"][choices["text"].index(choice)] == answer_key:
                        answer_text = choice
                        break

                # Include all choices in the answer for context
                choice_context = " Choices: " + ", ".join(
                    [
                        f"({label}) {text}"
                        for label, text in zip(choices["label"], choices["text"])
                    ]
                )
                answer = f"{answer_text}{choice_context}"
                return question, answer

        except Exception as e:
            print(f"Error extracting QA pair from {dataset_name}: {e}")
            print(f"Example structure: {example}")
            return None, None

        return None, None

    def evaluate_dataset(
        self, dataset: datasets.Dataset, dataset_name: str
    ) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        batch_size = 100
        evaluation_data = []
        self.resource_monitor.start_monitoring()

        # Initialize all metric lists
        metrics = {
            "ndcg": [],
            "rouge1": [],
            "rouge2": [],
            "rougeL": [],
            "latency": [],
            "hhem": [],
            "rouge": [],
            "Advance_HHEM": [],
        }

        try:
            # Process QA pairs
            qa_pairs = []
            for idx in range(min(batch_size, len(dataset))):
                question, answer = self.extract_qa_pair(idx, dataset, dataset_name)
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
                    chunker.chunker(text, method=ChunkingMethod.RECURSIVE_CHARACTER)
                )

            vector_store = embedding_vectors.create_and_save_index(chunks)

            chain = CustomLLMChain(
                self.tokenizer,
                self.model,
                self.model_name,
                f"faiss_evaluation_store_{dataset_name}",
                index_type="faiss",
            )

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

                extra_metrics = self.compute_metricx.evaluate_rag(
                    retrieved_docs=(
                        context.split("\n") if isinstance(context, str) else context
                    ),
                    generated_answer=response,
                    relevant_docs=[reference],
                    ground_truth=reference,
                    embeddings_model=embedding_vectors.embedding_model,
                )

                for k, v in extra_metrics.items():
                    if k in metrics:
                        metrics[k].append(v)

                # -- update the eval scores
                for k, v in eval_metrics.items():
                    if k in metrics:
                        metrics[k].append(float(v))
                    else:
                        metrics[k] = [float(v)] * len(next(iter(metrics.values())))

                # Add latency
                metrics["latency"].append(time() - start_time)

                # Calculate current averages for progress bar
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

            # Calculate costs
            cost_metrics = self.cost_calculator.calculate_costs(resource_metrics)
            cost_per_query = self.cost_calculator.calculate_cost_per_query(
                cost_metrics["total_cost"], len(evaluation_data)
            )

            # Add cost metrics to resource metrics
            resource_metrics.update(
                {
                    "cost_metrics": cost_metrics,
                    "cost_per_query": cost_per_query,
                }
            )

        # Ensure all metric lists have the same length before saving
        max_len = max(len(v) for v in metrics.values())
        for k in metrics:
            if len(metrics[k]) < max_len:
                metrics[k].extend([0.0] * (max_len - len(metrics[k])))

        # Save detailed evaluation data
        self._save_detailed_results(
            metrics,
            resource_metrics,
            dataset_name,
        )

        # Compute average metrics
        avg_metrics = {k: np.mean(v) for k, v in metrics.items() if k != "latency"}
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
        output_dir = os.path.join(f"{evaluation_dir}", dataset_name)
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
        costs_per_method = {}
        # --
        output_base_dir = f"{evaluation_dir}"
        os.makedirs(output_base_dir, exist_ok=True)
        summary_data = []
        # --
        for dataset_name, dataset in datasets_dict.items():
            print(f"\n{'*' * 50}")
            print(f"Evaluating {dataset_name}...")
            print(f"{'*' * 50}")
            metrics, latency, res_metrics = evaluator.evaluate_dataset(
                dataset, dataset_name
            )
            all_metrics[dataset_name] = metrics
            latencies[dataset_name] = latency
            resource_metrics[dataset_name] = res_metrics
            costs_per_method[dataset_name] = res_metrics["cost_metrics"]

            summary_data.append(
                {
                    "dataset": dataset_name,
                    "latency": latency,
                    **metrics,
                    **{f"resource_{k}": v for k, v in res_metrics.items()},
                    **{f"cost_{k}": v for k, v in res_metrics["cost_metrics"].items()},
                }
            )

        summary_df = pd.DataFrame(summary_data)
        summary_path = os.path.join(
            output_base_dir, f"{pipeline}_evaluation_summary.csv"
        )
        summary_df.to_csv(summary_path, index=False)

        print("\nCost Summary (in euros):")
        for dataset, costs in costs_per_method.items():
            print(f"\n{dataset}:")
            print(f"  Total cost: €{costs['total_cost']:.4f}")
            print(
                f"  Cost per query: €{resource_metrics[dataset]['cost_per_query']:.4f}"
            )

        print(f"\nResults saved to: {summary_path}")

    except Exception as e:
        print(f"Error in main execution: {e}")
        raise


if __name__ == "__main__":
    main()
