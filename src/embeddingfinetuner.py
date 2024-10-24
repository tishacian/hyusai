import torch
import numpy as np
from torch import nn
from torch.utils.data import Dataset, DataLoader
from sentence_transformers import SentenceTransformer
from typing import List, Tuple, Optional, Union
import logging
from tqdm import tqdm


class EmbeddingFineTuner:
    """
    Class for fine-tuning embedding models for RAG applications.
    Supports contrastive learning and custom loss functions.
    """

    def __init__(
        self,
        base_model_name: str = "sentence-transformers/all-mpnet-base-v2",
        device: Optional[str] = None,
        learning_rate: float = 2e-5,
        batch_size: int = 32,
        num_epochs: int = 5,
        margin: float = 0.5,
        temperature: float = 0.07,
    ):
        """
        Initialize the fine-tuning setup.

        Args:
            base_model_name (str): Name of the base SentenceTransformer model
            device (str): Device to use ('cuda' or 'cpu')
            learning_rate (float): Learning rate for optimization
            batch_size (int): Batch size for training
            num_epochs (int): Number of training epochs
            margin (float): Margin for triplet loss
            temperature (float): Temperature for contrastive loss
        """
        self.device = device or (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.model = SentenceTransformer(base_model_name).to(self.device)
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.num_epochs = num_epochs
        self.margin = margin
        self.temperature = temperature

        # Configure logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    class RAGDataset(Dataset):
        """Custom dataset for RAG training pairs"""

        def __init__(
            self,
            queries: List[str],
            positive_docs: List[str],
            negative_docs: List[str],
        ):
            self.queries = queries
            self.positive_docs = positive_docs
            self.negative_docs = negative_docs

        def __len__(self):
            return len(self.queries)

        def __getitem__(self, idx):
            return {
                "query": self.queries[idx],
                "positive": self.positive_docs[idx],
                "negative": self.negative_docs[idx],
            }

    def triplet_loss(
        self,
        query_embeddings: torch.Tensor,
        positive_embeddings: torch.Tensor,
        negative_embeddings: torch.Tensor,
    ) -> torch.Tensor:
        """
        Compute triplet loss for the embeddings.

        Args:
            query_embeddings: Query text embeddings
            positive_embeddings: Positive document embeddings
            negative_embeddings: Negative document embeddings

        Returns:
            torch.Tensor: Computed loss
        """
        positive_distances = torch.norm(
            query_embeddings - positive_embeddings, dim=1
        )
        negative_distances = torch.norm(
            query_embeddings - negative_embeddings, dim=1
        )
        losses = torch.relu(
            positive_distances - negative_distances + self.margin
        )
        return losses.mean()

    def contrastive_loss(
        self,
        query_embeddings: torch.Tensor,
        positive_embeddings: torch.Tensor,
        negative_embeddings: torch.Tensor,
    ) -> torch.Tensor:
        """
        Compute contrastive loss for the embeddings.

        Args:
            query_embeddings: Query text embeddings
            positive_embeddings: Positive document embeddings
            negative_embeddings: Negative document embeddings

        Returns:
            torch.Tensor: Computed loss
        """
        # Normalize embeddings
        query_embeddings = nn.functional.normalize(query_embeddings, dim=1)
        positive_embeddings = nn.functional.normalize(
            positive_embeddings, dim=1
        )
        negative_embeddings = nn.functional.normalize(
            negative_embeddings, dim=1
        )

        # Compute similarities
        positive_similarities = torch.sum(
            query_embeddings * positive_embeddings, dim=1
        )
        negative_similarities = torch.sum(
            query_embeddings * negative_embeddings, dim=1
        )

        # Compute loss
        positive_loss = -torch.log(
            torch.exp(positive_similarities / self.temperature)
        )
        negative_loss = torch.log(
            1 + torch.exp(negative_similarities / self.temperature)
        )

        return (positive_loss + negative_loss).mean()

    def prepare_data(
        self,
        queries: List[str],
        positive_docs: List[str],
        negative_docs: List[str],
    ) -> DataLoader:
        """
        Prepare data for training.

        Args:
            queries: List of query texts
            positive_docs: List of relevant documents
            negative_docs: List of irrelevant documents

        Returns:
            DataLoader: PyTorch DataLoader for training
        """
        dataset = self.RAGDataset(queries, positive_docs, negative_docs)
        return DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

    def train(
        self,
        train_data: Tuple[List[str], List[str], List[str]],
        validation_data: Optional[
            Tuple[List[str], List[str], List[str]]
        ] = None,
        loss_type: str = "contrastive",
    ) -> dict:
        """
        Train the embedding model.

        Args:
            train_data: Tuple of (queries, positive_docs, negative_docs)
            validation_data: Optional validation data tuple
            loss_type: Type of loss function ('contrastive' or 'triplet')

        Returns:
            dict: Training history
        """
        train_loader = self.prepare_data(*train_data)
        if validation_data:
            val_loader = self.prepare_data(*validation_data)

        optimizer = torch.optim.AdamW(
            self.model.parameters(), lr=self.learning_rate
        )
        loss_fn = (
            self.contrastive_loss
            if loss_type == "contrastive"
            else self.triplet_loss
        )

        history = {"train_loss": [], "val_loss": []}

        for epoch in range(self.num_epochs):
            # Training
            self.model.train()
            total_loss = 0
            train_progress = tqdm(
                train_loader, desc=f"Epoch {epoch + 1}/{self.num_epochs}"
            )

            for batch in train_progress:
                optimizer.zero_grad()

                # Get embeddings with gradients
                query_embeddings = self.model.encode(
                    batch["query"],
                    convert_to_tensor=True,
                    show_progress_bar=False,
                    device=self.device,
                    convert_to_numpy=False,  # Keep as torch tensor
                    requires_grad=True,  # Enable gradients
                )

                positive_embeddings = self.model.encode(
                    batch["positive"],
                    convert_to_tensor=True,
                    show_progress_bar=False,
                    device=self.device,
                    convert_to_numpy=False,  # Keep as torch tensor
                    requires_grad=True,  # Enable gradients
                )

                negative_embeddings = self.model.encode(
                    batch["negative"],
                    convert_to_tensor=True,
                    show_progress_bar=False,
                    device=self.device,
                    convert_to_numpy=False,  # Keep as torch tensor
                    requires_grad=True,  # Enable gradients
                )

                # Ensure tensors are on the correct device and have gradients
                query_embeddings = query_embeddings.to(
                    self.device
                ).requires_grad_(True)
                positive_embeddings = positive_embeddings.to(
                    self.device
                ).requires_grad_(True)
                negative_embeddings = negative_embeddings.to(
                    self.device
                ).requires_grad_(True)

                # Compute loss
                loss = loss_fn(
                    query_embeddings, positive_embeddings, negative_embeddings
                )
                loss.backward()
                optimizer.step()

                total_loss += loss.item()
                train_progress.set_postfix({"loss": loss.item()})

            avg_train_loss = total_loss / len(train_loader)
            history["train_loss"].append(avg_train_loss)

            # Validation
            if validation_data:
                self.model.eval()
                total_val_loss = 0

                with torch.no_grad():
                    for batch in val_loader:
                        query_embeddings = self.model.encode(
                            batch["query"],
                            convert_to_tensor=True,
                            show_progress_bar=False,
                            device=self.device,
                            convert_to_numpy=False,
                        )

                        positive_embeddings = self.model.encode(
                            batch["positive"],
                            convert_to_tensor=True,
                            show_progress_bar=False,
                            device=self.device,
                            convert_to_numpy=False,
                        )

                        negative_embeddings = self.model.encode(
                            batch["negative"],
                            convert_to_tensor=True,
                            show_progress_bar=False,
                            device=self.device,
                            convert_to_numpy=False,
                        )

                        loss = loss_fn(
                            query_embeddings,
                            positive_embeddings,
                            negative_embeddings,
                        )
                        total_val_loss += loss.item()

                avg_val_loss = total_val_loss / len(val_loader)
                history["val_loss"].append(avg_val_loss)

                self.logger.info(
                    f"Epoch {epoch + 1}: Train Loss = {avg_train_loss:.4f}, "
                    f"Val Loss = {avg_val_loss:.4f}"
                )
            else:
                self.logger.info(
                    f"Epoch {epoch + 1}: Train Loss = {avg_train_loss:.4f}"
                )

        return history

    def save_model(self, path: str):
        """Save the fine-tuned model"""
        self.model.save(path)
        self.logger.info(f"Model saved to {path}")

    def encode(
        self, texts: Union[str, List[str]], **kwargs
    ) -> Union[np.ndarray, torch.Tensor]:
        """
        Encode texts using the fine-tuned model.

        Args:
            texts: Text or list of texts to encode
            **kwargs: Additional encoding parameters

        Returns:
            Union[np.ndarray, torch.Tensor]: Text embeddings
        """
        try:
            kwargs.setdefault("convert_to_tensor", True)
            kwargs.setdefault("device", self.device)
            kwargs.setdefault("show_progress_bar", False)
            embeddings = self.model.encode(texts, **kwargs)
            if kwargs.get("convert_to_tensor", True):
                return embeddings  # Return as torch.Tensor
            else:
                return embeddings.cpu().numpy()

        except Exception as e:
            self.logger.error(f"Error in encoding: {str(e)}")
            # Return empty tensor or array based on convert_to_tensor
            if kwargs.get("convert_to_tensor", True):
                return torch.empty(0, device=self.device)
            return np.array([])


# %%

# Example usage:
queries = ["What is RAG?", "How does embedding work?"]
positive_docs = [
    "RAG is a retrieval-augmented generation...",
    "Embeddings are vector representations...",
]
negative_docs = [
    "The weather is sunny today.",
    "Python is a programming language.",
]

# Initialize fine-tuner
fine_tuner = EmbeddingFineTuner(
    base_model_name="sentence-transformers/all-mpnet-base-v2",
    learning_rate=2e-5,
    batch_size=32,
    num_epochs=5,
)

# Train the model
training_history = fine_tuner.train(
    train_data=(queries, positive_docs, negative_docs), loss_type="contrastive"
)

# Save the fine-tuned model
fine_tuner.save_model("fine_tuned_embeddings")

# Use the fine-tuned model for encoding
embeddings = fine_tuner.encode(["New query text"])
