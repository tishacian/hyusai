"""Seed the knowledge base with sample procurement documents.

Run once at startup (or manually) to populate the FAISS index.
Idempotent: checks if documents are already present before ingesting.
"""

import asyncio
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample_data"
OPEX_PDF = Path(__file__).resolve().parent.parent.parent / "OPEX.pdf"


async def seed_knowledge_base():
    """No pre-loading — knowledge base is populated via document upload in the UI."""
    logger.info("Knowledge base seeding disabled: documents are uploaded by the user")


def run_seed():
    asyncio.run(seed_knowledge_base())


if __name__ == "__main__":
    from app.core.logging import setup_logging

    setup_logging("INFO")
    run_seed()
