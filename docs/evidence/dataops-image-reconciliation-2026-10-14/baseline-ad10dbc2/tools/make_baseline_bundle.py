"""Create a small auditable comparison bundle; never copy OCI layers or secrets."""
import gzip,hashlib,json,re,shutil,subprocess
from pathlib import Path
SOURCE=Path(__file__).resolve().parent
OUT=Path('/workspace/dataops-image-evidence-baseline-ad10dbc2')
REPO=Path('/workspace/omnirag')
QUALIFIED=Path('/workspace/dataops-image-evidence-final-bd724044')
REPORTS=['backend-comparison.json','backend.measurement.json','backend.build.json','source-comparison.json','source-inputs.diff','historical.attribution.json','qualified.attribution.json','packed-descriptor-sizes.json','docker-inspect-comparison-method.json','scoring-fixtures-cleanup.json','builder-environment.json','builder-metrics.jsonl','final-state.json']
TOOLS=['build.py','prepare_build.py','measure_oci.py','compare_oci.py','capture_builder.py','make_baseline_bundle.py']
def copy(source,destination):
 raw=source.read_bytes()
 assert len(raw)<=8*1024**2
 assert not re.search(rb'-{5}BEGIN (?:[A-Z ]+ )?PRIVATE KEY-{5}',raw)
 assert not re.search(rb'https?://[^/\s:@]+:[^/\s@]+@',raw)
 destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
def main():
 OUT.mkdir(mode=0o700,exist_ok=False)
 for name in REPORTS:copy(SOURCE/name,OUT/name)
 for name in TOOLS:copy(SOURCE/name,OUT/'tools'/name)
 for name in ('Dockerfile.backend','Dockerfile.backend.dockerignore'):copy(SOURCE/name,OUT/'qualification-dockerfiles'/name)
 for name in ('backend','worker'):
  copy(QUALIFIED/'reports'/f'{name}.measurement.json',OUT/f'qualified-{name}.measurement.json')
  for kind in ('index','manifest','config'):copy(QUALIFIED/'oci-metadata'/f'{name}.{kind}.json',OUT/'oci-metadata'/'qualified'/f'{name}.{kind}.json')
 for kind in ('index','manifest','config'):copy(SOURCE/'oci-metadata'/f'backend.{kind}.json',OUT/'oci-metadata'/'historical'/f'backend.{kind}.json')
 copy(SOURCE/'moby-containerd-image-inspect.go',OUT/'method-reference'/'moby-v28.4.0-containerd-image-inspect.go')
 comparison=json.loads((SOURCE/'source-comparison.json').read_text())
 for row in comparison['files']:
  for label,revision in [('historical',comparison['historical_revision']),('qualified',comparison['qualified_revision'])]:
   raw=subprocess.check_output(['git','show',revision+':'+row['path']],cwd=REPO)
   assert hashlib.sha256(raw).hexdigest()==row[label]['sha256']
   p=OUT/'source-inputs'/label/row['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 for name in ('backend.log','builder-bootstrap.log','compare_oci.log'):
  raw=(SOURCE/name).read_bytes();assert len(raw)<=8*1024**2 and not re.search(rb'-{5}BEGIN (?:[A-Z ]+ )?PRIVATE KEY-{5}',raw);assert not re.search(rb'https?://[^/\s:@]+:[^/\s@]+@',raw)
  p=OUT/'logs'/(name+'.gz');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(gzip.compress(raw,mtime=0))
 files={}
 for p in sorted(OUT.rglob('*')):
  if p.is_file():
   raw=p.read_bytes();files[str(p.relative_to(OUT))]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 index={'classification':'Fresh rebuild of historical source compared with verified qualified OCI images, not an observed deployment.','historical_revision':comparison['historical_revision'],'qualified_revision':comparison['qualified_revision'],'source_inputs_and_generated_dockerfiles_compared':True,'files':files,'excludes':['OCI archives/layer binaries','Credentials/CA bundles','Terraform state','Whole checkout'],'reproduction':['Use source at the recorded historical revision in a clean checkout, the exact pinned base and build options from backend.build.json.','Dedicated BuildKit fuse-overlayfs at4GiB/no-swap/2CPU, unchanged4GiB disk reserve, session proxy and CA via secret mounts.','External build.py retains the original Dockerfile; its baseline report explicitly does not claim a historical test suite or deployment.','measure_oci.py streams and verifies compressed hashes/diff_ids, separates archive/tar/payload sizes. compare_oci.py attributes actual dependencies, OS versions and copied files.','Use docker-inspect-comparison-method.json for store-specific actual-inspect comparison; no VM store was observed by this task.'],'limits':['All budgets remain unchanged. Graphdriver and containerd size accounting differ; VM identity/store is needed for an operational budget verdict.','Base digest is exact but apt repository versions drifted in two libcurl packages, as recorded.','A large historical rebuild is not evidence that the deployed historical image was large, or that OCI measurement is wrong.']}
 (OUT/'bundle-index.json').write_text(json.dumps(index,indent=2)+'\n')
 for name,proof in files.items():assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==proof['sha256']
 print(json.dumps({'bundle':str(OUT),'files':len(files)+1,'bytes':sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file()),'index_sha256':hashlib.sha256((OUT/'bundle-index.json').read_bytes()).hexdigest()}))
if __name__=='__main__':main()
