import os
from time import time
from typing import Dict, List, Optional, Tuple, defaultdict

import datasets
import numpy as np
import pandas as pd
import torch
from computationcost import ResourceCost
from extrametrics import ExtraMetrics
from resourcemonitor import ResourceMonitor
from tqdm import tqdm

from customchain_naive import (
    CustomLLMChain,
)  # change this for different pipeline [1]
from src.chunker import TextChunker
from src.embedding import EmbeddingVectors
from src.globalvariables import REPO_PATH, ChunkingMethod, Models
from src.modeltokenizer import load_model_and_tokenizer

pipeline = "Naive"


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
        self.cost_calculator = ResourceCost(sampling_interval=0.1)

    def load_datasets(self) -> Dict[str, datasets.Dataset]:
        dataset_dict = {}
        nq_dataset = datasets.load_dataset("natural_questions", split="validation")
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

        narrativeqa_dataset = datasets.load_dataset("narrativeqa", split="validation")
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
                    short_answers = annotations["short_answers"][annotation_idx]
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
                    return str(example["question"]), str(example["answer"]["value"])
                return str(example["question"]), str(example["answer"])

            elif dataset_name == "hotpotqa":
                return str(example["question"]), str(example["answer"])

            elif dataset_name == "narrativeqa":
                question = (
                    example["question"]["text"]
                    if isinstance(example["question"], dict)
                    else example["question"]
                )
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
            # -- Stop resource monitoring and get summary
            print("\nCollecting resource usage metrics...")
            resource_metrics = self.resource_monitor.stop_monitoring()

            # -- Calculate costs
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

        # Save detailed evaluation data
        self._save_detailed_results(
            metrics,
            resource_metrics,
            dataset_name,
        )

        # --compute average metrics
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
        costs_per_method = {}
        # --
        output_base_dir = "evaluation_results"
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
        # --
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
