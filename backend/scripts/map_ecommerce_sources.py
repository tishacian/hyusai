"""Emit reviewed SQL receipts mapping real, ready, SHA-matched source identities.

Reads the Agentium DB only. Output targets the separate synthetic business DB.
No credentials, caller SQL or arbitrary table/column identifiers are accepted.
"""
import argparse
import json
import sys
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.workspace import Workspace


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def mapping(db, workspace, documents, collections):
    sources = db.query(KnowledgeCollectionSource, KnowledgeCollection).join(KnowledgeCollection,
        KnowledgeCollection.id == KnowledgeCollectionSource.collection_id).filter(
        KnowledgeCollectionSource.workspace_id == workspace.id, KnowledgeCollection.workspace_id == workspace.id,
        KnowledgeCollection.slug.in_(collections), KnowledgeCollectionSource.status == "ready").all()
    statements = ["-- Actual Document Center source identities, scoped to " + workspace.slug, "BEGIN;"]
    for document in documents:
        if document.get("current") is False: continue
        matches = [s for s, c in sources if s.filename == document["filename"]
                   and (s.source_metadata or {}).get("content_sha256") == document["sha256"]
                   and (s.source_metadata or {}).get("document_id")]
        if len(matches) != 1: raise ValueError("SOURCE_RECEIPT_NOT_UNIQUE: " + document["filename"])
        source = matches[0]
        reference, sha, filename, source_id = [literal(v) for v in (document["reference"], document["sha256"], document["filename"], source.id)]
        statements.append(f"UPDATE showcase_ecommerce.document_refs SET knowledge_source_id={source_id} WHERE document_key={reference} AND sha256={sha} AND source_filename={filename} AND (knowledge_source_id IS NULL OR knowledge_source_id={source_id});")
        statements.append(f"DO $receipt$ BEGIN IF NOT EXISTS (SELECT 1 FROM showcase_ecommerce.document_refs WHERE document_key={reference} AND sha256={sha} AND source_filename={filename} AND knowledge_source_id={source_id}) THEN RAISE EXCEPTION 'Source mapping conflict'; END IF; END $receipt$;")
    return "\n".join(statements + ["COMMIT;", ""])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--collections", nargs="+", required=True)
    parser.add_argument("--payload-stdin", action="store_true", required=True)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    documents = payload["manifest"]["documents"] + payload["benchmark_manifest"]["documents"]
    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).one()
        print(mapping(db, workspace, documents, args.collections), end="")


if __name__ == "__main__": main()
