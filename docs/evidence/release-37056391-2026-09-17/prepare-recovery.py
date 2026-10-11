"""Dedicated synthetic source failure/recovery; never touches an existing corpus."""
import argparse, json
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.services.knowledge_collections import create_collection, create_worker_job, original_key, serialize_job
from app.services.object_store import get_object_store
from app.services.worker_dispatch import dispatch_worker_job

parser = argparse.ArgumentParser()
parser.add_argument('--prepare', action='store_true')
parser.add_argument('--restore', action='store_true')
args = parser.parse_args()
slug = 'qa-ingest-retry-37056391'
filename = 'synthetic-recovery-checkpoint.txt'
content = b'Agentium synthetic ingestion recovery checkpoint R2-DIAG-3705. Retained source restored after an intentional missing-original failure. This is a technical qualification document, not client knowledge or an operational instruction.'
with SessionLocal() as db:
    ws = db.query(Workspace).filter(Workspace.slug == 'agentium-showcase').one()
    col = db.query(KnowledgeCollection).filter_by(workspace_id=ws.id, slug=slug).first()
    if not col:
        if not args.prepare:
            print(json.dumps({'status':'not_prepared'})); raise SystemExit(0)
        col = create_collection(db, workspace=ws, name='QA ingestion recovery 37056391', slug=slug,
                               description='Synthetic technical qualification only. Intentionally missing original, then explicit source recovery.')
        col.document_names = [filename]
        job = create_worker_job(db, workspace_id=ws.id, collection_id=col.id)
        job.result = {'stage':'dispatch_pending', 'qualification':'37056391-retained-source-recovery'}
        db.commit()
        dispatch_worker_job(db, job, allow_inline_fallback=False)
        db.commit()
    jobs = db.query(WorkerJob).filter_by(collection_id=col.id).all()
    assert len(jobs) == 1, 'Unexpected jobs: inspect; never replace qualification evidence'
    job = jobs[0]
    assert col.document_names == [filename]
    if args.restore:
        assert job.status == 'failed', 'Restore only after the observed failure'
        store = get_object_store()
        key = original_key(col, filename)
        if store.exists(key):
            assert store.read_bytes(key) == content
        else:
            store.write_bytes(key, content)
    print(json.dumps({'collection_id':col.id, 'collection_slug':col.slug, 'source_restored':args.restore,
                      'job':serialize_job(job)}, default=str))
