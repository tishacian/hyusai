import os,sys,tempfile,time,json,pathlib,contextlib
out=pathlib.Path('/workspace/dataops-hana-fallback-review-2026-10-14');out.mkdir(exist_ok=True)
os.environ['TMPDIR']=str(out)
for k in ('DATABASE_URL','ML_REGISTRY_URI','_PYTEST_OMNIRAG_DEFAULT_DATABASE_URL','_PYTEST_OMNIRAG_DEFAULT_ML_REGISTRY_URI'):
 os.environ.pop(k,None)
os.environ['CELERY_BROKER_URL']='memory://'
os.environ['CELERY_RESULT_BACKEND']='cache+memory://'
os.environ['SECRETS_BACKEND']='legacy'
blocked=[]
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','socket.sendto'):
  blocked.append(event)
  raise RuntimeError('External network disabled for HANA unit qualification')
sys.addaudithook(guard)
import pytest
start=time.monotonic()
with (out/'hana-48.log').open('w') as log, contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
 code=pytest.main(['app/tests/services/test_hana_security.py','app/tests/services/test_hana_preview.py','app/tests/api/test_hana_rpa_admin_api.py','-q','-p','no:cacheprovider','--basetemp',str(out/'pytest-tmp')])
result={'exit_code':int(code),'seconds':round(time.monotonic()-start,3),'python':sys.version.split()[0],'network_blocked_events':blocked,'log':str(out/'hana-48.log')}
(out/'hana-48-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result));print('\n'.join((out/'hana-48.log').read_text().splitlines()[-5:]));sys.exit(code)
