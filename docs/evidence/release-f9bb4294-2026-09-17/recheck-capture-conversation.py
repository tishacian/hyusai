"""One new synthetic conversation on the retained published Capture, never republishes."""
import fcntl,json,sys,time
from pathlib import Path
sys.path.insert(0,'/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
sha='f9bb429438119e2d9a2a5e90aa28fae51807a964'
p=Path('/tmp/capture-f9bb-conversation.json')
lock=p.with_suffix('.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
s=json.loads(p.read_text()) if p.exists() else {'sha':sha,'kind':'synthetic technical API qualification; no human or voice acceptance'}
assert s['sha']==sha

def save():
 t=p.with_suffix('.tmp'); t.write_text(json.dumps(s,indent=2,ensure_ascii=False)); t.replace(p)

c=Client('https://agentium.papai.ai/api/v1','/root/.attestation-username','/root/.attestation-password')
assert c.call('/build-info')['revision']==sha
prior=json.loads(Path('/tmp/capture-fd92-qualification.json').read_text())
ctx=prior['conversation_context']['id']; doc=prior['publication']['document_id']; slug=prior['collection']
s['reference']={'failed_run_id':prior['conversation']['run_id'],'context_id':ctx,'document_id':doc,'collection':slug,'proposal_id':prior['proposal']['id']}
s['context']=c.call('/contexts/'+ctx)
assert s['context']['environment_state']['collection']==slug
s['preview']=c.call(prior['publication']['export_urls']['preview_url'].removeprefix('/api/v1'))
assert '6 bar' in s['preview'].get('content','')
save()
if 'answer' not in s:
 assert 'intent' not in s, 'Uncertain request: inspect server state instead of repeating'
 s['intent']={'at':time.time(),'query':'Quelle est la pression nominale retenue dans la fiche R2CAP4771 ? Cite le passage qui la justifie.','context_mode':'replace'}; save()
 s['answer']=c.call('/chat/completion',{'query':s['intent']['query'],'context_id':ctx,'context_mode':'replace','response_language':'fr','max_tokens':600}); save()
a=s['answer']
if a.get('run_id'):
 s['run']=c.call('/runs/'+a['run_id']); save()
s['checks']={'corrected_value':'6 bar' in a.get('content',''),'has_run':bool(a.get('run_id')),'has_source':doc in json.dumps(a.get('sources') or []),'selected_collection_searched':slug in (a.get('retrieval_scope') or {}).get('collections',[])}; save()
print(json.dumps({'run_id':a.get('run_id'),'checks':s['checks'],'content':a.get('content'),'sources':a.get('sources'),'collections':(a.get('retrieval_scope') or {}).get('collections')},ensure_ascii=False))
assert all(s['checks'].values()),s['checks']
