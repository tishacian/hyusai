import os
from typing import Dict, List, Optional, Tuple

import datasets
import torch

from src.globalvariables import Models


class EvaluatorDataDownload:
    def __init__(self):
        """Initialize model based on available hardware"""
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = (
            Models.LLAMA3 if torch.cuda.is_available() else Models.LAMINIGPT
        )

    def load_datasets(self) -> Dict[str, datasets.Dataset]:
        dataset_dict = {}
        nq_dataset = datasets.load_dataset("natural_questions", split="validation")
        if nq_dataset is not None:
            dataset_dict["nq"] = nq_dataset
            print(f"Loaded NQ dataset with {len(nq_dataset)} examples")

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
    ) -> List[Tuple[Dict[str, float], float]]:
        """Evaluate HAH-RAG on a single dataset"""
        batch_size = 100
        qa_pairs = []

        print(f"\nProcessing {dataset_name} dataset:")
        print(f"Dataset size: {len(dataset)}")

        # Process examples
        for idx in range(min(batch_size, len(dataset))):
            input_text, reference = self.extract_qa_pair(idx, dataset, dataset_name)
            if input_text and reference:
                qa_pairs.append((input_text, reference))
                print(
                    f"Extracted QA pair {idx} Q: {input_text[:100]}... A: {reference[:100]}..."
                )

        print(f"\nFound {len(qa_pairs)} valid QA pairs in {dataset_name}")
        return qa_pairs


def main():
    evaluator = EvaluatorDataDownload()
    datasets_dict = evaluator.load_datasets()
    output_base_dir = "evaluation_results"
    os.makedirs(output_base_dir, exist_ok=True)

    for dataset_name, dataset in datasets_dict.items():
        print(f"Evaluating {dataset_name}...")
        evaluator.evaluate_dataset(dataset, dataset_name)


if __name__ == "__main__":
    main()
