import concurrent.futures,json,sys,time,uuid,urllib.request,os
from pathlib import Path
sys.path.insert(0,'/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
os.umask(0o077)
c=Client('https://agentium.papai.ai/api/v1','/root/.attestation-username','/root/.attestation-password')
sha='7532d4491a239d0e2285303cb12447ceac7419c2'
assert c.call('/build-info')['revision']==sha
phase=sys.argv[1]
path=Path('/tmp/agentium-7532-'+phase+'.json')
assert not path.exists(), 'Use a new phase for an intentional repeat'
state={'sha':sha,'phase':phase,'keys':[str(uuid.uuid4()) for _ in range(2)],'status':'dispatching'}
def save():path.write_text(json.dumps(state,indent=2))
def invoke(key):
 r=urllib.request.Request(c.base+'/work/operational-analysis/bindings/showcase.operational.analyze/runs',data=json.dumps({'payload':{},'page_id':'analysis','component_id':'analyze'}).encode(),headers={'Content-Type':'application/json','X-Workspace-Slug':'agentium-showcase','Authorization':'Bearer '+c.token,'Idempotency-Key':key})
 with urllib.request.urlopen(r,timeout=90) as response:return json.load(response)
save()
start=time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 receipts=list(pool.map(invoke,state['keys']))
 state['receipts']=receipts;state['status']='running';save()
 print(json.dumps({'phase':phase,'run_ids':[x['id'] for x in receipts]}),flush=True)
 runs=list(pool.map(lambda r:c.poll('/runs/'+r['id'],seconds=240),receipts))
state['runs']=runs;state['seconds']=round(time.monotonic()-start,3);save()
expected={'orders':4,'planned_minutes':120,'actual_minutes':155,'overrun_minutes':35,'late_orders':3,'largest_overrun_order':'NF-04','largest_overrun_minutes':25}
for key,r in zip(state['keys'],runs):
 assert r['status']=='completed',(r['id'],r['status'],r.get('error'))
 assert r['output_ref']['stats']==expected
 assert r['output_ref']['numerical_reference_passed'] is True
 assert r['output_ref']['human_validated'] is False
 assert r['outcome']['decision'] is None
 assert r['outcome']['confidence'] is None
 inv=r.get('invocations',[])
 assert len([i for i in inv if i['skill_slug']=='python_recipe_v1' and i['status']=='completed'])==2
 assert len([i for i in inv if i['skill_slug']=='llm_rag_answer_v1' and i['status']=='completed'])==1
 replay=invoke(key)
 assert replay['id']==r['id'] and replay['idempotent_replay'] is True
assert max(r['started_at'] for r in runs)<min(r['completed_at'] for r in runs),'Runs did not overlap'
state['status']='passed';save()
print(json.dumps({'phase':phase,'status':'passed','seconds':state['seconds']}),flush=True)
