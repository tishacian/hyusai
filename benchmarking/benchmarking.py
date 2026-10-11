import os
import sys
import torch
import argparse
from typing import Dict, List, Tuple, Optional, defaultdict
import datasets
import numpy as np
from time import time
from tqdm import tqdm
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# os.environ['CUDA_VISIBLE_DEVICES'] = '1'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.modeltokenizer import load_model_and_tokenizer
except ImportError as e:
    logger.error(f"Failed to import load_model_and_tokenizer: {e}")
    logger.info(
        "This might be due to vLLM compatibility issues. Please check your CUDA setup."
    )
    raise
from src.globalvariables import Models, CPUModels, ChunkingMethod
from src.embedding import EmbeddingVectors
from src.chunker import TextChunker

from resourcemonitor import ResourceMonitor
from extrametrics import ExtraMetrics
from computationcost import ResourceCost
from dataset_manager import DatasetManager
from model_manager import get_model_manager


def get_custom_chain_class(pipeline_type: str):
    """Get the appropriate CustomLLMChain class based on pipeline type."""
    if pipeline_type.lower() == "naive":
        from customchain_naive import CustomLLMChain

        return CustomLLMChain
    elif pipeline_type.lower() == "hybrid":
        from customchain_hybrid import CustomLLMChain

        return CustomLLMChain
    elif pipeline_type.lower() == "hah":
        from customchain_hah import CustomLLMChain

        return CustomLLMChain
    else:
        raise ValueError(
            f"Unknown pipeline type: {pipeline_type}. Supported types: Naive, Hybrid, HAH"
        )


class HAHRAGEvaluator:
    def __init__(self, country_code: str = "FR", model_name: str = None):
        """Initialize model and monitoring based on available hardware

        Args:
            country_code: ISO country code for CO2 emissions calculation
            model_name: Specific model to use (overrides default selection)
        """
        self.country_code = country_code
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # --use provided model or default based on hardware
        if model_name:
            self.model_name = model_name
        else:
            self.model_name = (
                Models.LLAMA3_8B
                if torch.cuda.is_available()
                else CPUModels.LLAMA32_3B_INSTRUCT
            )

        # -- model manager to load/reuse model
        model_manager = get_model_manager()
        self.model, self.tokenizer = model_manager.load_model(
            self.model_name, self.country_code
        )
        if self.model is None or self.tokenizer is None:
            raise ValueError("Failed to load model or tokenizer")

        self.compute_metricx = ExtraMetrics()
        self.resource_monitor = ResourceMonitor(
            sampling_interval=1.0,  # Reduce frequency to avoid warnings
            country_code=self.country_code,
        )
        self.resource_monitor_stopped = False
        # -- cost evaluator
        self.cost_calculator = ResourceCost(sampling_interval=0.1)

        # -- initialize dataset manager
        self.dataset_manager = DatasetManager()

    def reset_resource_monitor(self):
        """Reset the resource monitor for a new evaluation."""
        try:
            if not self.resource_monitor_stopped and hasattr(
                self.resource_monitor, "stop_monitoring"
            ):
                self.resource_monitor.stop_monitoring()
        except Exception as e:
            logger.warning(f"Error stopping resource monitor during reset: {e}")

        self.resource_monitor_stopped = False

        self.resource_monitor = ResourceMonitor(
            sampling_interval=1.0,
            country_code=self.country_code,
        )

    def load_datasets(self) -> Dict[str, datasets.Dataset]:
        """Load all datasets using the dataset manager."""
        return self.dataset_manager.load_all_datasets()

    def extract_qa_pair(
        self, example_idx: int, dataset: datasets.Dataset, dataset_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract question-answer pair from dataset sample."""
        try:
            example = dataset[example_idx]

            if dataset_name == "squad":
                question = example["question"]
                answers = example.get("answers", {})
                answer = ""

                if answers and "text" in answers and answers["text"]:
                    answer = answers["text"][0]

                if question and answer:
                    return str(question), str(answer)
                return None, None

            elif dataset_name == "commonsense_qa":
                question = example["question"]
                choices = example.get("choices", {})
                answer_key = example.get("answerKey", "")

                # Get the correct answer text
                answer = ""
                if choices and "text" in choices and answer_key:
                    choice_texts = choices["text"]
                    choice_keys = choices.get("label", [])
                    if answer_key in choice_keys:
                        answer_idx = choice_keys.index(answer_key)
                        if answer_idx < len(choice_texts):
                            answer = choice_texts[answer_idx]

                if question and answer:
                    return str(question), str(answer)
                return None, None

            elif dataset_name == "hotpot_qa":
                question = example["question"]
                answer = example["answer"]
                supporting_facts = example.get("supporting_facts", [])

                # Add supporting facts to answer for context
                if supporting_facts:
                    supporting_text = " Supporting facts: " + " ".join(
                        [f"{fact[0]}: {fact[1]}" for fact in supporting_facts]
                    )
                    answer = f"{answer}{supporting_text}"

                if question and answer:
                    return str(question), str(answer)
                return None, None

            elif dataset_name == "2wikimultihop":
                question = example["question"]
                answer = example["answer"]
                supporting_facts = example.get("supporting_facts", [])

                # Add supporting facts to answer for context
                if supporting_facts:
                    supporting_text = " Supporting facts: " + " ".join(
                        [f"{fact[0]}: {fact[1]}" for fact in supporting_facts]
                    )
                    answer = f"{answer}{supporting_text}"

                if question and answer:
                    return str(question), str(answer)
                return None, None

            elif dataset_name == "ambig_qa":
                question = example["question"]
                answers = example.get("answers", [])

                # Take the first answer if multiple exist
                if answers and len(answers) > 0:
                    answer = str(answers[0])
                else:
                    answer = "No answer provided"

                if question and answer:
                    return str(question), str(answer)
                return None, None

            elif dataset_name == "strategy_qa":
                question = example["question"]
                answer = example["answer"]
                facts = example.get("facts", [])

                # Add facts to answer for context
                if facts:
                    facts_text = " Facts: " + " ".join(facts)
                    answer = f"{answer}{facts_text}"

                if question and answer:
                    return str(question), str(answer)
                return None, None

        except Exception as e:
            logger.error(f"Error extracting QA pair from {dataset_name}: {e}")
            logger.error(f"Example causing error: {example}")
            return None, None

        return None, None

    def evaluate_dataset(
        self, dataset: datasets.Dataset, dataset_name: str
    ) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """Evaluate a single dataset with comprehensive metrics."""
        # Reset resource monitor for this evaluation
        self.reset_resource_monitor()

        # Use the same batch_size as the dataset's sample_size
        dataset_info = self.dataset_manager.get_dataset_info(dataset_name)
        batch_size = dataset_info.get("sample_size", 1000) if dataset_info else 1000
        logger.info(f"Using batch_size: {batch_size} for dataset: {dataset_name}")
        evaluation_data = []
        try:
            self.resource_monitor.start_monitoring()
        except Exception as e:
            logger.warning(f"Error starting resource monitoring: {e}")

        try:
            # Process QA pairs
            qa_pairs = []
            for idx in range(min(batch_size, len(dataset))):
                question, answer = self.extract_qa_pair(idx, dataset, dataset_name)
                if question and answer:
                    qa_pairs.append((question, answer))

            if not qa_pairs:
                logger.warning(f"No valid QA pairs found for {dataset_name}")
                return {}, 0.0, {}

            logger.info(f"Processing {len(qa_pairs)} QA pairs for {dataset_name}")

            # Create chunks from combined texts
            combined_texts = [f"{q} {a}" for q, a in qa_pairs]
            chunker = TextChunker(self.tokenizer, self.model)

            chunks = []
            for text in combined_texts:
                chunks.extend(
                    chunker.chunker(text, method=ChunkingMethod.RECURSIVE_CHARACTER)
                )

            # Create embedding vectors and vector store
            embedding_vectors = EmbeddingVectors(
                self.tokenizer,
                self.model,
                create_new_vs=True,
                existing_vector_store="",
                new_vs_name=f"evaluation_store_{dataset_name}",
                embedding_type="faiss",
                embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
            )

            # Create and save the index
            embedding_vectors.create_and_save_index(chunks)

            # Create the chain with the new vector store
            chain = CustomLLMChain(
                self.tokenizer,
                self.model,
                self.model_name,
                f"faiss_evaluation_store_{dataset_name}",
                index_type="faiss",
                embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
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
            logger.info("\nCollecting resource usage metrics...")
            try:
                if (
                    not self.resource_monitor_stopped
                    and hasattr(self.resource_monitor, "stop_monitoring")
                    and self.resource_monitor is not None
                ):
                    resource_metrics = self.resource_monitor.stop_monitoring()
                    self.resource_monitor_stopped = True
                else:
                    logger.warning(
                        "Resource monitor not properly initialized or already stopped"
                    )
                    resource_metrics = {
                        "cpu_usage": 0.0,
                        "memory_usage": 0.0,
                        "gpu_usage": 0.0,
                        "power_consumption": 0.0,
                        "co2_emissions": 0.0,
                    }
            except Exception as e:
                logger.warning(f"Error stopping resource monitoring: {e}")
                # Provide default resource metrics if monitoring fails
                resource_metrics = {
                    "cpu_usage": 0.0,
                    "memory_usage": 0.0,
                    "gpu_usage": 0.0,
                    "power_consumption": 0.0,
                    "co2_emissions": 0.0,
                }

            # -- Calculate costs
            try:
                cost_metrics = self.cost_calculator.calculate_costs(resource_metrics)
                cost_per_query = self.cost_calculator.calculate_cost_per_query(
                    cost_metrics["total_cost"], len(evaluation_data)
                )
            except Exception as e:
                logger.warning(f"Error calculating costs: {e}")
                cost_metrics = {
                    "compute_cost_cpu": 0.0,
                    "compute_cost_gpu": 0.0,
                    "memory_cost": 0.0,
                    "power_cost": 0.0,
                    "total_cost": 0.0,
                }
                cost_per_query = 0.0

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
    """Main benchmarking function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Benchmark RAG pipelines")
    parser.add_argument(
        "--pipeline",
        type=str,
        default="Naive",
        choices=["Naive", "Hybrid", "HAH"],
        help="Pipeline type to benchmark (default: Naive)",
    )
    parser.add_argument(
        "--country-code",
        type=str,
        default="FR",
        help="Country code for CO2 emissions calculation (default: FR)",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Specific model to use (overrides default model selection)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="evaluation_results",
        help="Output directory for results (default: evaluation_results)",
    )

    args = parser.parse_args()

    global pipeline
    pipeline = args.pipeline

    global CustomLLMChain
    CustomLLMChain = get_custom_chain_class(pipeline)

    logger.info(f"Using pipeline: {pipeline}")

    try:
        country_code = args.country_code
        model_name = args.model
        output_base_dir = args.output_dir

        evaluator = HAHRAGEvaluator(country_code=country_code, model_name=model_name)
        datasets_dict = evaluator.load_datasets()

        all_metrics = {}
        latencies = {}
        resource_metrics = {}
        costs_per_method = {}
        # --
        os.makedirs(output_base_dir, exist_ok=True)
        summary_data = []
        # --
        for dataset_name, dataset in datasets_dict.items():
            logger.info(f"\n{'*' * 50}")
            logger.info(f"Evaluating {dataset_name}...")
            logger.info(f"{'*' * 50}")
            metrics, latency, res_metrics = evaluator.evaluate_dataset(
                dataset, dataset_name
            )
            all_metrics[dataset_name] = metrics
            latencies[dataset_name] = latency
            resource_metrics[dataset_name] = res_metrics
            costs_per_method[dataset_name] = res_metrics["cost_metrics"]

            # Extract cost metrics into separate columns
            cost_metrics = res_metrics["cost_metrics"]

            summary_data.append(
                {
                    "dataset": dataset_name,
                    "latency": latency,
                    **metrics,
                    **{
                        f"resource_{k}": v
                        for k, v in res_metrics.items()
                        if k != "cost_metrics"
                    },
                    # Separate cost columns
                    "compute_cost_cpu": cost_metrics["compute_cost_cpu"],
                    "compute_cost_gpu": cost_metrics["compute_cost_gpu"],
                    "memory_cost": cost_metrics["memory_cost"],
                    "power_cost": cost_metrics["power_cost"],
                    "total_cost": cost_metrics["total_cost"],
                }
            )
        # --
        summary_df = pd.DataFrame(summary_data)
        summary_path = os.path.join(
            output_base_dir, f"{pipeline}_evaluation_summary.csv"
        )
        summary_df.to_csv(summary_path, index=False)

        logger.info("\nCost Summary (in euros):")
        for dataset, costs in costs_per_method.items():
            logger.info(f"\n{dataset}:")
            logger.info(f"  Total cost: €{costs['total_cost']:.4f}")
            logger.info(
                f"  Cost per query: €{resource_metrics[dataset]['cost_per_query']:.4f}"
            )

        logger.info(f"\nResults saved to: {summary_path}")

    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        raise


if __name__ == "__main__":
    main()
