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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from src.modeltokenizer import load_model_and_tokenizer
except ImportError as e:
    logger.error(f"Failed to import load_model_and_tokenizer: {e}")
    logger.info("This might be due to vLLM compatibility issues. Please check your CUDA setup.")
    raise
from src.globalvariables import Models, CPUModels, REPO_PATH, ChunkingMethod
from src.embedding import EmbeddingVectors
from src.chunker import TextChunker

from resourcemonitor import ResourceMonitor
from extrametrics import ExtraMetrics
from computationcost import ResourceCost
from dataset_manager import DatasetManager
from model_manager import get_model_manager

# Pipeline configuration for O1 reasoning chains
# Pipeline will be set dynamically in main() based on command line arguments


def get_custom_chain_class(pipeline_type: str):
    """Get the appropriate CustomLLMChain class based on pipeline type."""
    if pipeline_type.lower() == "reasoning":
        from customchain_reasoning import CustomLLMChain
        return CustomLLMChain
    elif pipeline_type.lower() == "mini-reasoning":
        from customchain_mini_reasoning import CustomLLMChain
        return CustomLLMChain
    else:
        raise ValueError(f"Unknown pipeline type: {pipeline_type}. Supported types: Reasoning, Mini-Reasoning")

# CustomLLMChain will be set dynamically in main() after parsing command line arguments


class O1RAGEvaluator:
    def __init__(self, country_code: str = "FR", model_name: str = None, pipeline: str = "Reasoning"):
        """Initialize model and monitoring based on available hardware for O1 reasoning chains

        Args:
            country_code: ISO country code for CO2 emissions calculation
            model_name: Specific model to use (overrides default selection)
            pipeline: Pipeline type (Reasoning or Mini-Reasoning)
        """
        self.country_code = country_code
        self.pipeline = pipeline
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        
        # Use provided model or default based on hardware
        if model_name:
            self.model_name = model_name
        else:
            self.model_name = (
                Models.LLAMA3_8B if torch.cuda.is_available() else CPUModels.LLAMA32_3B_INSTRUCT
            )
        
        # Use model manager to load/reuse model
        model_manager = get_model_manager()
        self.model, self.tokenizer = model_manager.load_model(self.model_name, self.country_code)
        if self.model is None or self.tokenizer is None:
            raise ValueError("Failed to load model or tokenizer")

        self.compute_metricx = ExtraMetrics()
        self.resource_monitor = ResourceMonitor(
            sampling_interval=1.0,  # Reduce frequency to avoid warnings
            country_code=self.country_code,
        )
        self.resource_monitor_stopped = False  # Flag to track if monitor has been stopped
        # -- cost evaluator
        self.cost_calculator = ResourceCost(sampling_interval=0.1)
        
        # Initialize dataset manager
        self.dataset_manager = DatasetManager()

    def reset_resource_monitor(self):
        """Reset the resource monitor for a new evaluation."""
        try:
            # Stop monitoring if it's running
            if not self.resource_monitor_stopped and hasattr(self.resource_monitor, 'stop_monitoring'):
                self.resource_monitor.stop_monitoring()
        except Exception as e:
            logger.warning(f"Error stopping resource monitor during reset: {e}")
        
        # Reset the flag
        self.resource_monitor_stopped = False
        
        # Create a new resource monitor instance
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
        """Evaluate a single dataset with comprehensive metrics for O1 reasoning chains."""
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
            # -- process QA pairs
            qa_pairs = []
            for idx in range(min(batch_size, len(dataset))):
                question, answer = self.extract_qa_pair(idx, dataset, dataset_name)
                if question and answer:
                    qa_pairs.append((question, answer))

            if not qa_pairs:
                logger.warning(f"No valid QA pairs found for {dataset_name}")
                return {}, 0.0, {}
            
            logger.info(f"Processing {len(qa_pairs)} QA pairs for {dataset_name}")

            # -- create chunks from combined texts
            combined_texts = [f"{q} {a}" for q, a in qa_pairs]
            chunker = TextChunker(self.tokenizer, self.model)
            
            chunks = []
            for text in combined_texts:
                chunks.extend(
                    chunker.chunker(text, method=ChunkingMethod.RECURSIVE_CHARACTER)
                )

            # -- create embedding vectors and vector store
            embedding_vectors = EmbeddingVectors(
                self.tokenizer,
                self.model,
                create_new_vs=True,
                existing_vector_store="",
                new_vs_name=f"evaluation_store_o1_{dataset_name}",
                embedding_type="faiss",
                embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
            )

            # -- create and save the index
            vector_store = embedding_vectors.create_and_save_index(chunks)

            # -- create the chain with the new vector store
            # Get the appropriate CustomLLMChain class dynamically
            CustomLLMChain = get_custom_chain_class(self.pipeline)
            chain = CustomLLMChain(
                self.tokenizer,
                self.model,
                self.model_name,
                f"faiss_evaluation_store_o1_{dataset_name}",
                index_type="faiss",
                embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
            )

            # Initialize metrics dictionary with all expected metrics
            # This ensures all metrics are saved even if not computed
            metrics = defaultdict(list)
            # Pre-initialize all expected metric lists to ensure they're in the output
            expected_metrics = [
                "ndcg", "rouge1", "rouge2", "rougeL",
                "fluency", "coherence", "relevance",
                "factuality", "correctness", "hhem", "Advance_HHEM"
            ]
            for metric in expected_metrics:
                metrics[metric] = []  # Initialize empty list
            
            progress_bar = tqdm(qa_pairs, desc=f"Evaluating QA pairs with {self.pipeline}")
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
                try:
                    extra_metrics = self.compute_metricx.evaluate_rag(
                        retrieved_docs=context,
                        generated_answer=response,
                        relevant_docs=[reference],
                        ground_truth=reference,
                        embeddings_model=embedding_vectors.embedding_model,
                    )
                    # Ensure all expected metrics are present
                    expected_metrics = [
                        "ndcg", "rouge1", "rouge2", "rougeL",
                        "fluency", "coherence", "relevance",
                        "factuality", "correctness", "hhem", "Advance_HHEM"
                    ]
                    for metric in expected_metrics:
                        if metric not in extra_metrics:
                            extra_metrics[metric] = 0.0
                except Exception as e:
                    logger.warning(f"Error calculating extra metrics: {e}")
                    # Provide default values for all expected metrics
                    extra_metrics = {
                        "ndcg": 0.0,
                        "rouge1": 0.0,
                        "rouge2": 0.0,
                        "rougeL": 0.0,
                        "fluency": 0.0,
                        "coherence": 0.0,
                        "relevance": 0.0,
                        "factuality": 0.0,
                        "correctness": 0.0,
                        "hhem": 0.0,
                        "Advance_HHEM": 0.0,
                    }

                # -- append extra metrics values to the lists (same as regular benchmarking)
                for k, v in extra_metrics.items():
                    metrics[k].append(v)
                for k, v in eval_metrics.items():
                    metrics[k].append(v)
                metrics["latency"].append(time() - start_time)
                
                # -- O1-specific reasoning steps
                o1_reasoning_steps = self._calculate_o1_reasoning_steps(question, response, context)
                metrics["o1_reasoning_steps"].append(o1_reasoning_steps)

                avg_metrics = {
                    k: np.mean(v) for k, v in metrics.items() if k not in ["latency", "o1_reasoning_steps"]
                }
                progress_bar.set_postfix(
                    rouge1=f"{avg_metrics.get('rouge1', 0):.3f}",
                    ndcg=f"{avg_metrics.get('ndcg', 0):.3f}",
                    o1_steps=f"{np.mean(metrics['o1_reasoning_steps']):.1f}",
                )

        finally:
            # -- Stop resource monitoring and get summary
            logger.info("\nCollecting resource usage metrics...")
            try:
                if not self.resource_monitor_stopped and hasattr(self.resource_monitor, 'stop_monitoring') and self.resource_monitor is not None:
                    resource_metrics = self.resource_monitor.stop_monitoring()
                    self.resource_monitor_stopped = True
                else:
                    logger.warning("Resource monitor not properly initialized or already stopped")
                    resource_metrics = {
                        "cpu_usage": 0.0,
                        "memory_usage": 0.0,
                        "gpu_usage": 0.0,
                        "power_consumption": 0.0,
                        "co2_emissions": 0.0
                    }
            except Exception as e:
                logger.warning(f"Error stopping resource monitoring: {e}")
                resource_metrics = {
                    "cpu_usage": 0.0,
                    "memory_usage": 0.0,
                    "gpu_usage": 0.0,
                    "power_consumption": 0.0,
                    "co2_emissions": 0.0
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
                    "total_cost": 0.0
                }
                cost_per_query = 0.0

            resource_metrics.update(
                {
                    "cost_metrics": cost_metrics,
                    "cost_per_query": cost_per_query,
                }
            )

        # -- save detailed evaluation data
        self._save_detailed_results(
            metrics,
            resource_metrics,
            dataset_name,
        )

        # --compute average metrics
        avg_metrics = {k: np.mean(v) for k, v in metrics.items() if k not in ["latency", "o1_reasoning_steps"]}
        avg_latency = np.mean(metrics["latency"])
        avg_o1_steps = np.mean(metrics["o1_reasoning_steps"])

        return avg_metrics, avg_latency, resource_metrics

    def _calculate_o1_reasoning_steps(self, question: str, response: str, context: str) -> int:
        """Calculate O1 reasoning steps based on question complexity and response length."""
        question_words = len(question.split())
        response_words = len(response.split())
        context_words = len(context.split())
        
        # -- more complex questions and longer responses indicate more reasoning steps
        base_steps = 2
        complexity_factor = min(question_words / 10, 3)  # Cap at 3
        response_factor = min(response_words / 50, 2)    # Cap at 2
        context_factor = min(context_words / 100, 1)     # Cap at 1
        
        total_steps = base_steps + complexity_factor + response_factor + context_factor
        return int(total_steps)

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
        logger.info(f"Metrics lengths: {[(k, len(v)) for k, v in metrics.items()]}")
        
        # Ensure all expected metrics are present (even if empty)
        expected_metrics = [
            "ndcg", "rouge1", "rouge2", "rougeL",
            "fluency", "coherence", "relevance",
            "factuality", "correctness", "hhem", "Advance_HHEM",
            "latency", "o1_reasoning_steps"
        ]
        for metric in expected_metrics:
            if metric not in metrics or not isinstance(metrics[metric], list):
                metrics[metric] = []
        
        # -- ensure all arrays have the same length
        if metrics:
            has_data = any(
                isinstance(v, list) and len(v) > 0 for v in metrics.values()
            )
            if has_data:
                max_length = max(
                    len(v) for v in metrics.values() if isinstance(v, list)
                )
            else:
                max_length = 0
            if max_length > 0:
                for k, v in metrics.items():
                    if isinstance(v, list) and len(v) != max_length:
                        logger.warning(f"Padding {k} from {len(v)} to {max_length}")
                        if k in [
                            "fluency", "coherence", "relevance",
                            "factuality", "correctness", "hhem", "Advance_HHEM"
                        ]:
                            padding_value = 0.0  # These are typically 0-1 scores
                        elif k in ["ndcg", "rouge1", "rouge2", "rougeL"]:
                            padding_value = 0.0
                        elif k == "latency":
                            padding_value = 0.0
                        elif k == "o1_reasoning_steps":
                            padding_value = 1
                        else:
                            padding_value = 0.0

                        metrics[k] = v + [padding_value] * (max_length - len(v))
        
        # Create DataFrame ensuring all expected columns are included
        # Order columns to match expected format (same as Naive/Hybrid/HAH)
        column_order = [
            "ndcg", "rouge1", "rouge2", "rougeL",
            "fluency", "coherence", "relevance", "factuality",
            "correctness", "hhem", "Advance_HHEM", "latency",
            "o1_reasoning_steps"
        ]
        # Filter to only include columns that exist in metrics
        available_columns = [
            col for col in column_order if col in metrics
        ]
        # Add any other columns that might exist
        other_columns = [
            col for col in metrics.keys() if col not in available_columns
        ]
        final_columns = available_columns + other_columns

        metrics_df = pd.DataFrame({k: metrics[k] for k in final_columns})
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
    """Main O1 benchmarking function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Benchmark RAG pipelines with O1 reasoning chains")
    parser.add_argument(
        "--pipeline", 
        type=str, 
        default="Reasoning", 
        choices=["Reasoning", "Mini-Reasoning"],
        help="Pipeline type to benchmark (default: Reasoning)"
    )
    parser.add_argument(
        "--country-code", 
        type=str, 
        default="FR",
        help="Country code for CO2 emissions calculation (default: FR)"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Specific model to use (overrides default model selection)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="evaluation_results",
        help="Output directory for results (default: evaluation_results)"
    )
    
    args = parser.parse_args()
    
    # Update global pipeline variable
    global pipeline
    pipeline = args.pipeline
    
    # Re-import the appropriate CustomLLMChain class
    global CustomLLMChain
    CustomLLMChain = get_custom_chain_class(pipeline)
    
    logger.info(f"Using O1 pipeline: {pipeline}")
    
    try:
        country_code = args.country_code
        model_name = args.model
        output_base_dir = args.output_dir
        
        evaluator = O1RAGEvaluator(country_code=country_code, model_name=model_name, pipeline=pipeline)
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
            logger.info(f"Evaluating {dataset_name} with {pipeline}...")
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
                    "pipeline": pipeline,
                    "latency": latency,
                    **metrics,
                    **{f"resource_{k}": v for k, v in res_metrics.items() if k != "cost_metrics"},
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