"""Capture only public builder identity, limits and cgroup counters."""
import argparse,json,os,subprocess,time
from pathlib import Path
ROOT=Path('/workspace/dataops-image-qualification')
CONTAINER='buildx_buildkit_agentium-dataops-review0'
ENV=dict(os.environ)
for key in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):
 ENV.pop(key,None)
DOCKER=['docker','--host=unix:///var/run/docker.sock']
def output(*args):
 return subprocess.check_output(DOCKER+list(args),env=ENV,text=True).strip()
def main():
 p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('--initialize',action='store_true');a=p.parse_args()
 metrics={}
 for key in ('memory.max','memory.swap.max','memory.current','memory.peak','memory.events','cpu.max','cpu.stat'):
  metrics[key]=output('exec',CONTAINER,'cat','/sys/fs/cgroup/'+key)
 record={'stage':a.stage,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cgroup':metrics}
 with (ROOT/'builder-metrics.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
 if a.initialize:
  raw=json.loads(output('inspect','--format','{{json .HostConfig}}',CONTAINER))
  proof={'container':CONTAINER,'host_config_limits':{key:raw.get(key) for key in ('Memory','MemorySwap','NanoCpus','CpuPeriod','CpuQuota','CgroupnsMode','CgroupParent')},'effective_cgroup_before_build':metrics,'worker':output('exec',CONTAINER,'buildctl','debug','workers','--verbose'),'daemon_version':output('version','--format','{{.Server.Version}}'),'counter_scope':'Existing dedicated builder lifetime. Compare before/after events; memory.peak also includes the archived diagnostic build.'}
  (ROOT/'builder-environment.json').write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps(record))
if __name__=='__main__':main()
