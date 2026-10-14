"""Attribute two verified OCI backends without extraction or package execution."""
import collections,gzip,hashlib,json,tarfile,time
from email.parser import Parser
from pathlib import Path
WORK=Path(__file__).resolve().parent
QUALIFIED=WORK.parent
PREFIX='usr/local/lib/python3.12/site-packages/'
ROLES=['base_debian','base_ca','base_python','base_links','require_pip_index','os_ocr_office','app_requirements','app_dependencies','rag_manifest','rag_model_bytes','hf_requirements','hf_dependencies','os_impress','system_user','workdir','copy_context','permissions','backend_workdir']

def scalar_package(name):
 if not name.startswith(PREFIX):return None
 relative=name[len(PREFIX):];head=relative.split('/',1)[0]
 for package in ('sqlglot','deltalake'):
  if head==package or head==package+'.libs' or (head.startswith(package+'-') and head.endswith('.dist-info')):return package
 if relative.startswith('arro3/core/') or (head.startswith('arro3_core-') and head.endswith('.dist-info')):return 'arro3-core'
 return None

def analyze(directory,label):
 measured=json.loads((directory/'backend.measurement.json').read_text())['images'][0]
 assert len(measured['layers'])==len(ROLES)
 inventory={};installed={};packages={};os_versions={};layer_details=[];dataops=collections.Counter()
 with tarfile.open(directory/'backend.oci.tar','r:') as archive:
  for index in (5,7,11,12,15):
   descriptor=measured['layers'][index];blob=archive.extractfile('blobs/sha256/'+descriptor['digest'].split(':',1)[1]);tops=collections.Counter();sources=collections.Counter();payload=0;terraform=0
   with gzip.GzipFile(fileobj=blob) as decoded,tarfile.open(fileobj=decoded,mode='r|') as layer:
    while (entry:=layer.next()) is not None:
     name=entry.name.removeprefix('./');payload+=entry.size
     if '/.terraform/' in '/'+name:terraform+=entry.size
     if name.startswith(PREFIX):
      top=name[len(PREFIX):].split('/',1)[0];tops[top]+=entry.size
     p=scalar_package(name)
     if p:dataops[p]+=entry.size
     if entry.isfile() and name.startswith(PREFIX) and name.endswith('.dist-info/METADATA'):
      assert entry.size<=2*1024**2
      raw=layer.extractfile(entry).read();m=Parser().parsestr(raw.decode('utf-8',errors='replace'));package=(m.get('Name') or name).lower().replace('_','-');installed[package]=m.get('Version')
     if entry.isfile() and name=='var/lib/dpkg/status':
      assert entry.size<=8*1024**2
      raw=layer.extractfile(entry).read().decode('utf-8',errors='replace')
      for paragraph in raw.split('\n\n'):
       m=Parser().parsestr(paragraph)
       if m.get('Package'):os_versions[m['Package']]=m.get('Version')
     if index==15 and name.startswith('app/'):
      relative=name[4:];sources[relative.split('/',1)[0]]+=entry.size
      if entry.isfile():
       digest=hashlib.sha256();stream=layer.extractfile(entry)
       while chunk:=stream.read(1024**2):digest.update(chunk)
       inventory[relative]={'bytes':entry.size,'sha256':digest.hexdigest()}
     layer.members.clear()
   blob.close();assert payload==descriptor['tar_entry_payload_bytes']
   layer_details.append({'index':index,'role':ROLES[index],'bytes':payload,'terraform_cache_bytes':terraform,'site_package_top_entries':dict(tops),'context_top_directories':dict(sources)})
 layers=[{'index':i,'role':ROLES[i],**row} for i,row in enumerate(measured['layers'])]
 result={'label':label,'revision':measured['revision'],'measurement':{k:v for k,v in measured.items() if k!='layers'},'layers':layers,'layer_details':layer_details,'installed_distribution_versions':installed,'installed_os_package_versions':os_versions,'copy_files':inventory,'dataops_three_distributions_bytes':dict(dataops),'scope':'Actual layer bytes; package METADATA and OS status read as data. No packages or copied files executed.'}
 (WORK/f'{label}.attribution.json').write_text(json.dumps(result,indent=2)+'\n')
 return result

def changes(a,b):
 return {k:{'historical':a.get(k),'qualified':b.get(k)} for k in sorted(a.keys()|b.keys()) if a.get(k)!=b.get(k)}

def main():
 started=time.monotonic();old=analyze(WORK,'historical');new=analyze(QUALIFIED,'qualified');deltas=[]
 for left,right in zip(old['layers'],new['layers'],strict=True):
  deltas.append({'role':left['role'],'historical_bytes':left['tar_entry_payload_bytes'],'qualified_bytes':right['tar_entry_payload_bytes'],'delta_bytes':right['tar_entry_payload_bytes']-left['tar_entry_payload_bytes'],'same_diff_id':left['diff_id']==right['diff_id']})
 report={'historical_revision':old['revision'],'qualified_revision':new['revision'],'historical_size_bytes':old['measurement']['docker_graphdriver_comparable_size_bytes'],'qualified_size_bytes':new['measurement']['docker_graphdriver_comparable_size_bytes'],'delta_bytes':new['measurement']['docker_graphdriver_comparable_size_bytes']-old['measurement']['docker_graphdriver_comparable_size_bytes'],'layer_deltas':deltas,'distribution_version_changes':changes(old['installed_distribution_versions'],new['installed_distribution_versions']),'os_package_version_changes':changes(old['installed_os_package_versions'],new['installed_os_package_versions']),'dataops_three_distributions_bytes':{'historical':old['dataops_three_distributions_bytes'],'qualified':new['dataops_three_distributions_bytes']},'context_changed_files':changes(old['copy_files'],new['copy_files']),'seconds':round(time.monotonic()-started,3),'limits':['Historical source rebuilt now, not the deployed historical image.','Both OCI payload sums use the same Moby classic-graphdriver algorithm; no full application docker inspect was performed.','Base is pinned, but repository timestamps/OS indexes and build-generated files can differ. Actual package versions and context bytes are compared explicitly.']}
 assert sum(x['delta_bytes'] for x in deltas)==report['delta_bytes']
 (WORK/'backend-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ('context_changed_files','layer_deltas')}))
if __name__=='__main__':main()
