"""Synthetic API qualification; no voice claim and no human acceptance claim.

Every mutation has a retained intent. Never repeat an uncertain request: inspect
its server state first. The technical-publication phase is limited to this new
synthetic session, never an existing customer proposal or R1 human gate.
"""
import argparse, fcntl, json, sys, time, urllib.parse
from pathlib import Path
sys.path.insert(0, '/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
p=argparse.ArgumentParser(); p.add_argument('phase', choices=['prepare','technical-publication','conversation']); args=p.parse_args()
sha='447997ee62c280988cd072b32386245173874f3c'; marker='R2INV4479'; slug='qa-capture-inventory-4479'
report=Path('/tmp/capture-4479-qualification.json')
lock=report.with_suffix('.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
state=json.loads(report.read_text()) if report.exists() else {'sha':sha,'kind':'synthetic technical API test, not a human review or voice test','marker':marker,'collection':slug}
assert state['sha']==sha

def save():
 tmp=report.with_suffix('.tmp'); tmp.write_text(json.dumps(state,indent=2,ensure_ascii=False)); tmp.replace(report)

client=Client('https://agentium.papai.ai/api/v1','/root/.attestation-username','/root/.attestation-password')
assert client.call('/build-info')['revision']==sha

def once(key,path,body,method=None):
 if key in state: return state[key]
 assert key+'_intent' not in state, 'Uncertain prior '+key+': inspect its retained server state; do not repeat'
 state[key+'_intent']={'path':path,'method':method or 'POST','time':time.time()}; save()
 state[key]=client.call(path,body,method); save(); return state[key]

if args.phase=='prepare':
 created=once('collection_created','/documents/collections',{'name':'Synthetic Capture inventory QA 4479','slug':slug,'description':'Isolated synthetic technical qualification; not customer knowledge.'})
 assert created['collection_name']==slug
 context=once('conversation_context','/contexts',{'name':'Synthetic Capture inventory QA 4479','environment_state':{'collection':slug},'ephemeral':True,'ttl_hours':24})
 if 'inventory_before' not in state:
  state['inventory_before']=client.call('/documents/collections/'+slug+'/inventory'); save()
 assert state['inventory_before']['source_count']==0 and state['inventory_before']['chunk_count']==0
 before=once('conversation_before','/chat/completion',{'query':'Quelle est la pression nominale retenue dans la fiche '+marker+' ? Cite le passage qui la justifie.','context_id':context['id'],'context_mode':'replace','response_language':'fr','max_tokens':600})
 state['before_run']=client.call('/runs/'+before['run_id']); save()
 session=once('session','/knowledge-capture/plans',{'title':'QA Capture continuity '+marker,
  'objective':'Recette technique synthétique du passage Capture vers une connaissance publiée. Ne pas utiliser comme consigne réelle.',
  'expert_profile':'Compte de recette technique, pas un participant humain',
  'duration_minutes':0,'plan_mode':'free_conversation'})
 sid=session['id']; base='/knowledge-capture/sessions/'+sid
 once('start',base+'/start',{})
 original='Recette synthétique '+marker+'. La pression nominale indiquée dans ce compte rendu est de 8 bar. Cette donnée fictive sert uniquement à tester la correction avant publication.'
 corrected='Recette synthétique '+marker+'. Correction : la pression nominale est de 6 bar. Cette donnée fictive sert uniquement à tester la correction avant publication. Aucune intervention réelle n’est autorisée.'
 once('turn',base+'/turns',{'speaker':'expert','text':original,'input_modality':'text','client_turn_id':marker+'-turn-1'})
 events=client.call(base+'/events'); state['events_before_amendment']=events; save()
 target=next(e for e in events['events'] if e.get('event_type')=='expert_turn_finalized' and marker in str(e))
 once('amendment',base+'/events/'+target['id']+'/amend',{'text_amended':corrected,'reason':'Technical synthetic correction; not a voice test'},'PATCH')
 proposal=once('proposal',base+'/proposal',{})
 state['events_after_amendment']=client.call(base+'/events'); save()
 content=(proposal.get('proposal') or {}).get('report_markdown') or ((proposal.get('proposal') or {}).get('recommended_ingestion') or {}).get('content','')
 state['checks']={'unrelated_context_absent':session.get('context_id') is None,'inventory_absent':'Inventaire Knowledge collection' not in content and 'chunks indexés' not in content,'corrected_value_in_report':'6 bar' in content,'old_value_absent_from_report':'8 bar' not in content,'synthetic_marker_in_report':marker in content,'review_status':proposal['status']}; save()
 assert all(state['checks'][k] for k in ['corrected_value_in_report','old_value_absent_from_report','synthetic_marker_in_report','unrelated_context_absent','inventory_absent']),state['checks']
 print(json.dumps({'phase':'prepared','session_id':sid,'proposal_id':proposal['id'],'checks':state['checks']}))
else:
 assert state.get('proposal') and all(state['checks'][k] for k in ['corrected_value_in_report','old_value_absent_from_report','synthetic_marker_in_report','unrelated_context_absent','inventory_absent'])
 pid=state['proposal']['id']; base='/knowledge-capture/proposals/'+pid
 reviewed=once('technical_review',base+'/review',{'status':'accepted','review_notes':'AUTOMATED TECHNICAL QA of an isolated synthetic fixture. Not a human user acceptance or operational approval.'},'PATCH')
 assert reviewed['status']=='accepted'
 result=once('publication',base+'/publish',{'category':'technique','destination_scope':slug,'final_title':'QA Capture '+marker,'include_unresolved_questions':False})
 assert result['status']=='success' and result['collection']==slug and result['document_id']
 state['restored']=client.call('/knowledge-capture/proposals?'+urllib.parse.urlencode({'session_id':state['session']['id']})); save()
 stored=next(x for x in state['restored']['proposals'] if x['id']==pid)
 assert stored['status']=='published'
 url=stored['proposal']['publication']['export_urls']['preview_url']; assert url.startswith('/api/v1/documents/')
 state['preview']=client.call(url.removeprefix('/api/v1')); save()
 state['search']=client.call('/documents/search',{'query':marker+' pression nominale','collection_name':slug,'top_k':3}); save()
 assert any(marker in x.get('content','') and '6 bar' in x.get('content','') for x in state['search']['results'])
 state['inventory_after']=client.call('/documents/collections/'+slug+'/inventory'); save()
 inventory=state['inventory_after']; sources=inventory['sources']
 assert inventory['status']=='ready' and inventory['source_count']==1
 assert inventory['chunk_count']==result['chunks_processed'] and result['chunks_processed']>0
 source=next(x for x in sources if x['metadata'].get('document_id')==result['document_id'])
 import hashlib
 assert source['status']=='ready' and source['metadata']['proposal_id']==pid
 assert source['metadata']['content_sha256']==hashlib.sha256(state['preview']['content'].encode('utf-8')).hexdigest()
 state['status']='publication_and_retrieval_verified'; save()
 print(json.dumps({'status':state['status'],'session_id':state['session']['id'],'proposal_id':pid,'document_id':result['document_id'],'collection':slug,'human_acceptance':'NOT RUN','voice':'NOT RUN'}))

if args.phase=='conversation':
 context=once('conversation_context','/contexts',{'name':'QA Capture '+marker,'environment_state':{'collection':slug},'business_constraints':{'source':'capture_publication_technical_qa','proposal_id':state['proposal']['id']},'ephemeral':True,'ttl_hours':24})
 answer=once('conversation','/chat/completion',{'query':'Quelle est la pression nominale retenue dans la fiche '+marker+' ? Cite le passage qui la justifie.','context_id':context['id'],'context_mode':'replace','response_language':'fr','max_tokens':600})
 state['conversation_checks']={'corrected_value':'6 bar' in answer.get('content',''),'has_run':bool(answer.get('run_id')),'has_source':state['publication']['document_id'] in json.dumps(answer.get('sources') or [])}; save()
 assert all(state['conversation_checks'].values()),state['conversation_checks']
 state['conversation_run']=client.call('/runs/'+answer['run_id']); save()
 print(json.dumps({'status':'fresh_conversation_verified','run_id':answer['run_id'],'checks':state['conversation_checks']}))
