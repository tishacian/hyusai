"""Seed the knowledge base with sample procurement documents.

Run once at startup (or manually) to populate the FAISS index.
Idempotent: checks if documents are already present before ingesting.
"""
import asyncio
from pathlib import Path
from app.core.logging import get_logger

logger = get_logger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample_data"


async def seed_knowledge_base():
    try:
        from app.services.rag.document_service import DocumentService
    except ImportError as e:
        logger.warning("DocumentService not available, skipping seed", error=str(e))
        return

    doc_service = DocumentService(collection_name="documents", vector_db_type="faiss")

    try:
        count = await doc_service.get_document_count()
        if count > 0:
            logger.info("Knowledge base already seeded", vectors=count)
            return
    except Exception:
        pass

    md_files = sorted(SAMPLE_DIR.glob("*.md"))
    if not md_files:
        logger.warning("No sample documents found", path=str(SAMPLE_DIR))
        return

    logger.info("Seeding knowledge base", files=len(md_files))
    for fp in md_files:
        try:
            result = await doc_service.ingest_document(str(fp))
            logger.info("Ingested", file=fp.name, chunks=result.get("chunks_processed", 0))
        except Exception as e:
            logger.warning("Failed to ingest", file=fp.name, error=str(e))

    logger.info("Knowledge base seeded successfully")


def run_seed():
    asyncio.run(seed_knowledge_base())


if __name__ == "__main__":
    from app.core.logging import setup_logging
    setup_logging("INFO")
    run_seed()
