"""Use existing protected-runner identity; never print credentials."""
import argparse, fcntl, json, sys, time, uuid
from pathlib import Path
sys.path.insert(0, '/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
parser = argparse.ArgumentParser()
parser.add_argument('--retry', action='store_true')
args = parser.parse_args()
report = Path('/tmp/ingest-recovery-37056391.json')
lock = report.with_suffix('.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
sha = '37056391d6cc315c72495f973fb6fe0e2072ed68'
seed = json.loads(Path('/tmp/ingest-3705-seed.json').read_text())
state = json.loads(report.read_text()) if report.exists() else {'sha': sha, 'seed': seed}
assert state['sha'] == sha and state['seed']['job']['id'] == seed['job']['id']
def save():
    tmp = report.with_suffix('.tmp'); tmp.write_text(json.dumps(state, indent=2)); tmp.replace(report)
client = Client('https://agentium.papai.ai/api/v1', '/root/.attestation-username', '/root/.attestation-password')
assert client.call('/build-info')['revision'] == sha
path = '/documents/jobs/' + seed['job']['id']
job = client.call(path)
assert job['workspace_id'] == 'e2ed9e40-5fa6-4e32-8948-3e1220134fd3'
assert job['collection_id'] == seed['collection_id']
if args.retry:
    if 'request' not in state:
        assert job['status'] == 'failed', job['status']
        assert job['kind'] == 'document_ingest_index'
        assert job['result']['source_failure'] == {'code':'original_source_missing','filename':'synthetic-recovery-checkpoint.txt'}
        state['before'] = job
        state['request'] = {'request_id':str(uuid.uuid4()), 'observed_updated_at':job['updated_at']}
        save()
    state['receipt'] = client.call(path+'/retry', state['request'])
    save()
assert 'receipt' in state, 'No retry receipt. Use the retained request, never replace this job.'
deadline=time.monotonic()+180
while True:
    state['after'] = client.call(path); save()
    if state['after']['status'] not in {'queued','running'}: break
    if time.monotonic()>deadline:
        print(json.dumps({'status':'still_active','job_id':job['id'],'report':str(report)})); raise SystemExit(2)
    time.sleep(3)
after = state['after']
assert after['status'] == 'completed', after['error']
assert len(after['result']['retry_history']) == 1
assert 'source_failure' not in after['result']
assert after['result']['retry_history'][0]['result']['source_failure'] == state['before']['result']['source_failure']
assert after['result']['retry_history'][0]['error'] == state['before']['error']
assert after['celery_task_id'] != state['before']['celery_task_id']
assert not str(after['celery_task_id']).startswith('eager:')
state['inventory'] = client.call('/documents/collections/'+seed['collection_id']+'/inventory')
assert state['inventory']['chunk_count'] > 0
state['retrieval'] = client.call('/documents/search', {'query':'R2-DIAG-3705 ingestion recovery checkpoint', 'top_k':3,
                              'collection_name':seed['collection_slug']})
assert any('R2-DIAG-3705' in r.get('content','') for r in state['retrieval'].get('results',[]))
state['replay'] = client.call(path+'/retry',state['request'])
assert state['replay']['id']==after['id'] and state['replay']['celery_task_id']==after['celery_task_id']
assert len(state['replay']['result']['retry_history'])==1
state['status']='verified'; save()
print(json.dumps({'status':'verified','collection':seed['collection_slug'],'job_id':after['id'],'chunks':state['inventory']['chunk_count']}))
