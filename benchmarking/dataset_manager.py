import logging
from pathlib import Path
from typing import Dict, List, Optional
import datasets
import psutil


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatasetManager:
    """Manages dataset loading for benchmarking.

    Parameters:
        cache_dir: Directory to store cached datasets
        min_free_space_gb: Minimum free space required (in GB)
    """
    
    def __init__(self, cache_dir: str = "./dataset_cache", min_free_space_gb: float = 2.0):
        """
        Initialize the dataset manager.

        Parameters:
            cache_dir: Directory to store cached datasets
            min_free_space_gb: Minimum free space required (in GB)
        """
        self.cache_dir = Path(cache_dir)
        self.min_free_space_gb = min_free_space_gb
        self.cache_dir.mkdir(exist_ok=True)
        emission_logs_dir = Path("emission_logs")
        emission_logs_dir.mkdir(exist_ok=True)
        self.dataset_configs = {
            "squad": {
                "name": "squad",
                "config": None,
                "split": "validation",
                "columns": ["question", "answers", "context"],
                "description": "SQuAD 2.0 - Single-hop reading comprehension (baseline)",
                "reasoning_type": "single_hop",
                "sample_size": 2000,  # 19% of full dataset (10,570)
                "full_size": 10570
            },
            "commonsense_qa": {
                "name": "commonsense_qa",
                "config": None,
                "split": "validation",
                "columns": ["question", "choices", "answerKey"],
                "description": "CommonsenseQA - Commonsense reasoning with multiple choice",
                "reasoning_type": "commonsense",
                "sample_size": 1000,  # 82% of full dataset (1,221)
                "full_size": 1221
            },
            "hotpot_qa": {
                "name": "hotpot_qa",
                "config": "distractor",
                "split": "validation",
                "columns": ["question", "answer", "supporting_facts"],
                "description": "HotpotQA - Multi-hop reasoning requiring 2+ facts",
                "reasoning_type": "multi_hop",
                "sample_size": 1500,  # 28% of full dataset (5,447)
                "full_size": 5447
            },
            "2wikimultihop": {
                "name": "framolfese/2WikiMultihopQA",
                "config": None,
                "split": "validation",
                "columns": ["question", "answer", "supporting_facts"],
                "description": "2WikiMultiHopQA - Wikipedia-based multi-hop reasoning",
                "reasoning_type": "multi_hop",
                "sample_size": 2500,  # 20% of full dataset (12,576)  
                "full_size": 12576  
            },
            "ambig_qa": {
                "name": "ambig_qa",
                "config": None,
                "split": "validation",
                "columns": ["id", "question", "annotations", "viewed_doc_titles", "used_queries", "nq_answer", "nq_doc_title"],
                "description": "AmbigQA - Ambiguous questions requiring clarification",
                "reasoning_type": "ambiguous",
                "sample_size": 1000,  # 50% of full dataset (2,002)
                "full_size": 2002
            },
            # "strategy_qa": { # disabled for now, error with dataset
            #     "name": "allenai/strategy-qa",
            #     "config": None,
            #     "split": "test",
            #     "columns": ["question", "answer", "facts"],
            #     "description": "StrategyQA - Complex multi-step reasoning",
            #     "reasoning_type": "strategic",
            #     "sample_size": 1000,  
            #     "full_size": 2290  
            # }
        }
    
    def check_disk_space(self) -> bool:
        """Check if there's enough disk space.

        Returns:
            bool: True if there's enough disk space
        """
        disk_usage = psutil.disk_usage(self.cache_dir)
        free_gb = disk_usage.free / (1024**3)
        
        logger.info("Disk space: %.2f GB free (minimum required: %.1f GB)", 
                   free_gb, self.min_free_space_gb)
        
        if free_gb < self.min_free_space_gb:
            logger.warning("Insufficient disk space: %.2f GB < %.1f GB", 
                          free_gb, self.min_free_space_gb)
            return False
        return True
    
    def load_dataset(self, dataset_name: str, sample_size: int = None) -> Optional[datasets.Dataset]:
        """
        Load a dataset with optional sampling.
        
        Parameters:
            dataset_name: Name of the dataset to load
            sample_size: Number of samples to load (None uses config default, 0 for all)
            
        Returns:
            Loaded dataset or None if failed
        """
        if not self.check_disk_space():
            return None
        
        if dataset_name not in self.dataset_configs:
            logger.error("Unknown dataset: %s", dataset_name)
            return None
        
        config = self.dataset_configs[dataset_name]
        
        try:
            dataset = datasets.load_dataset(
                config["name"],
                config["config"],
                split=config["split"]
            )
            
            # Sample if requested
            if sample_size:
                if len(dataset) > sample_size:
                    dataset = dataset.shuffle(seed=42).select(range(sample_size))
            
            print(f" Successfully loaded {dataset_name}: {len(dataset)} examples")
            print(f"  Columns: {dataset.column_names}")
            print(f"  First example keys: {list(dataset[0].keys())}")
            return dataset
            
        except Exception as e:
            print(f" Failed to load {dataset_name}: {str(e)}")
            return None
    
    def cleanup_cache(self):
        """Clean up the cache directory.

        Returns:
            None
        """
        try:
            import shutil
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                logger.info("Cache directory cleaned up: %s", self.cache_dir)
        except Exception as e:
            logger.error("Error cleaning up cache: %s", str(e))
    
    def get_available_datasets(self) -> List[str]:
        """Get list of available dataset names.

        Returns:
            List[str]: List of available dataset names
        """
        return list(self.dataset_configs.keys())
    
    def load_all_datasets(self, use_full_datasets: bool = False) -> Dict[str, datasets.Dataset]:
        """
        Load all configured datasets using their default sample sizes or full datasets.
        
        Parameters:
            use_full_datasets: If True, loads complete datasets (sample_size=0)
        
        Returns:
            Dictionary mapping dataset names to loaded datasets
        """
        dataset_dict = {}
        
        for dataset_name in self.dataset_configs.keys():
            logger.info(f"Loading dataset: {dataset_name}")
            
            if use_full_datasets:
                dataset = self.load_dataset(dataset_name, sample_size=0)
                logger.info(f"Loading complete {dataset_name} dataset")
            else:
                dataset = self.load_dataset(dataset_name)
            
            if dataset is not None:
                dataset_dict[dataset_name] = dataset
                coverage = (len(dataset) / self.dataset_configs[dataset_name]["full_size"]) * 100
                logger.info(f"Successfully loaded {dataset_name} with {len(dataset)} examples ({coverage:.1f}% coverage)")
            else:
                logger.warning(f"Failed to load dataset: {dataset_name}")
        
        return dataset_dict
    
    def get_dataset_info(self, dataset_name: str) -> Optional[Dict]:
        """Get information about a dataset.
        
        Parameters:
            dataset_name: Name of the dataset to get information about
        Returns:
            Dictionary containing dataset information
        """
        return self.dataset_configs.get(dataset_name)
