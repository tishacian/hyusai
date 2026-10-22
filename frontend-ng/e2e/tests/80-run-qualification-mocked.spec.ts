import {expect,test,type Page,type Route} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({serviceWorkers:'block',video:'off'});
const workspace={id:'quality-workspace',slug:'quality-workspace',name:'Quality QA',role:'owner',role_template:'workspace_owner',settings:{features:{}},effective_features:{}};
const question={key:'policy',question:'Is the decision supported by the evidence?',type:'boolean',choices:[],required:true,requires_evidence:true};
const proof='Delivery evidence';
const typed={schema_version:2,evaluation_id:'check-passed',rubric_id:'claims-review',rubric_version:'1',status:'completed',quality_status:'passed',disposition:'review',confidence:null,questions:[question],answers:{policy:{status:'answered',value:true,reason:null,explanation:'The retained evidence supports the decision.',evidence:[{evidence_id:'source-1',quote:proof,start:0,end:proof.length}],confidence:null}},coverage:{questions_total:1,questions_answered:1,evidence_total:1,evidence_examined:1}};
const passed={id:'check-passed',evaluation_id:'check-passed',run_id:'quality-run',source:'evaluate_v2',created_at:'2026-10-22T12:00:00Z',execution_status:'completed',quality_status:'passed',producer_invocation_id:'judge-call',rubric:{id:'claims-review',version:'1'},evidence_availability:'available',typed_evaluation:typed,evidence_sources:[{evidence_id:'source-1',sha256:'a'.repeat(64),text:proof,asset_ref:{version:4,digest:'a'.repeat(64)},invocation_id:'source-call'}],review:{count:0}};
const failed={...passed,id:'check-failed',evaluation_id:'check-failed',created_at:'2026-10-22T11:00:00Z',execution_status:'failed',quality_status:'unassessed',typed_evaluation:{...typed,evaluation_id:'check-failed',status:'failed',quality_status:'unassessed',reason:'JUDGE_RESPONSE_INVALID',response_diagnostic:{category:'evidence_quote',question_index:0},answers:{policy:{status:'invalid',value:null,reason:'JUDGE_RESPONSE_INVALID',explanation:'',evidence:[],confidence:null}}}};
const totals={evaluations:2,distinct_runs:1,technical_failures:1,completed:1,partial:0,assessed:1,passed:1,failed:0,unassessed:1,pass_rate:1,questions_total:2,questions_answered:1};
const campaignSide={run_id:'qa-run',status:'cancelled',termination:'human_gate',quality_status:'unassessed',verdict:'passed',output_ref:{answer:'Ask a reviewer to examine the proposal.'},duration_ms:350,execution_cost:null,assertions:[],controls:[{invocation_id:'qa-judge',evaluation_id:'qa-evaluation',execution_status:'failed',quality_status:'unassessed'}]};
const campaign={id:'campaign-1',status:'completed',method:'assertions_v2',snapshot:{comparability:'limited',limitations:[]},results:[{case_id:'case-1',result_key:'case-1:0',repetition_index:0,change:'unchanged',baseline:{...campaignSide,run_id:'qa-reference'},candidate:{...campaignSide,run_id:'qa-candidate',controls:[{...campaignSide.controls[0],evaluation_id:'qa-candidate-evaluation'}]}}]};

async function setup(page:Page,locale:'fr'|'en'='fr'){
 const writes:Array<{path:string;body:any}>=[],reads:string[]=[];let revoked=false;let annotated=false;
 await page.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.fallback():route.abort());
 await page.addInitScript(({locale,slug})=>{localStorage.setItem('agentium_token','Bearer isolated-quality');localStorage.setItem('agentium_workspace_slug',slug);localStorage.setItem('agentium_locale',locale);localStorage.setItem('agentium_theme','dark');},{locale,slug:workspace.slug});
 const json=(route:Route,body:unknown)=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 await page.route('**/api/v1/**',route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace(/^\/api\/v1/,'');if(request.method()==='GET')reads.push(path);const body=request.method()==='GET'?null:request.postDataJSON();if(request.method()!=='GET')writes.push({path,body});
  if(path==='/auth/validate')return json(route,{valid:true,user_id:'reviewer-1',role:'admin'});
  if(path==='/auth/me')return json(route,{id:'reviewer-1',role:'admin',is_active:true,workspaces:[workspace]});
  if(path==='/auth/workspaces')return json(route,[workspace]);if(path==='/auth/workspaces/'+workspace.slug)return json(route,workspace);
  if(path==='/systems')return json(route,[{id:'quality-system',name:'Claims application',status:'active'}]);
  if(path==='/systems/quality-system/flow-state')return json(route,{draft:{revision:38}});
  if(path==='/runs')return json(route,[{id:'reference-run',system_id:'quality-system',status:'completed',started_at:'2026-10-22T10:00:00Z'}]);
  if(path==='/evaluation/summary'||path==='/evaluation/by-run/quality-run/summary')return json(route,{schema_version:1,run_id:'quality-run',records:[passed,failed],totals});
  if(path.startsWith('/evaluation/records/')){const row=path.endsWith('check-failed')?failed:passed;return json(route,revoked?{...row,typed_evaluation:null,evidence_sources:[],evidence_availability:'unavailable'}:row);}
  if(path==='/evaluation/history')return json(route,{evaluations:[]});if(path==='/evaluation/latest')return json(route,{evaluation:null});if(path==='/evaluation/dimensions')return json(route,{dimensions:{}});
  if(path==='/evaluation/trend'||path==='/evaluation/component-health')return json(route,null);
  if(path==='/evaluation/review-queue')return json(route,{items:[],count:0});
  if(path==='/evaluation/suites')return json(route,request.method()==='GET'?[]:{id:'suite-1',name:body.name,revision:1,cases:body.cases});
  if(path==='/evaluation/campaigns/preflight')return json(route,{eligible:true,preflight_sha256:'b'.repeat(64),planned_runs:2,comparability:'limited',limitations:[],issues:[]});
  if(path==='/evaluation/campaigns')return json(route,request.method()==='GET'?[]:campaign);
  if(path==='/evaluation/campaigns/campaign-1')return json(route,campaign);
  if(path==='/documents/collections')return json(route,{items:[]});
  if(path==='/typed-calibration/corpora')return json(route,{items:[{id:'corpus-1',logical_key:'Claims reference',rubric_id:'claims-review',rubric_version:'1',unit_count:4}],total:1});
  if(path==='/typed-calibration/corpora/corpus-1/review-units')return json(route,{items:[{key:'fresh-1',document_family:'family-A',partition:'test'}],total:1});
  if(path==='/typed-calibration/corpora/corpus-1/review-units/fresh-1')return json(route,{unit_key:'fresh-1',partition:'test',questions:[question],evidence:[{id:'source-1',kind:'text',text:proof,sha256:'a'.repeat(64)}],own_annotation:annotated?{id:'annotation-1'}:null,annotation_count:annotated?1:0,can_annotate:!annotated,adjudication_required:false,can_adjudicate:false});
  if(path==='/typed-calibration/corpora/corpus-1/annotations'){annotated=true;return json(route,{asset_ref:{id:'annotation-1'},reviewer_user_id:'reviewer-1'});}
  return json(route,{});
 });
 return {writes,reads,revoke:()=>{revoked=true;}};
}

test.describe('Run quality and qualification — isolated product UI',()=>{
 test.beforeEach(async({},info)=>{test.skip(process.env['E2E_CHROME_V2_MOCKED']!=='1'||!['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),'Local mocked QA only.');});
 for(const locale of ['fr','en'] as const)test(`${locale}: quality preserves attempts, exact evidence and revoked access`,async({page},info)=>{
  const api=await setup(page,locale);await page.setViewportSize({width:locale==='fr'?1440:390,height:900});await page.goto('/observability?facet=quality&systemId=quality-system');
  const panel=page.getByTestId('evaluation-records');await expect(panel).toContainText('1 / 2');await expect(panel.locator('.quality-record')).toHaveCount(2);
  await panel.locator('.quality-select').first().click();await expect(panel.getByTestId('typed-judge-result')).toBeVisible();await panel.getByTestId('typed-judge-result').locator('details').filter({has:page.locator('blockquote')}).first().locator(':scope > summary').click();
  await expect(panel.locator('blockquote > p').first()).toBeVisible();await expect(panel.locator('a[href*="source-call"]')).toHaveAttribute('href',/quality-run.*source-call/);await expect(panel.locator('.quality-links a').first()).toHaveAttribute('href',/quality-run.*evaluationId=check-passed/);
  expect(api.writes.filter(row=>row.path.startsWith('/evaluation/'))).toEqual([]);
  expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);expect((await new AxeBuilder({page}).include('app-evaluation-records').analyze()).violations).toEqual([]);
  await panel.screenshot({path:info.outputPath('quality-'+locale+'.png')});api.revoke();await panel.getByRole('button',{name:locale==='fr'?'Actualiser':'Refresh',exact:true}).click();await expect(panel.getByTestId('typed-judge-result')).toHaveCount(0);await expect(panel).toContainText(locale==='fr'?'ne sont plus accessibles':'no longer accessible');
 });
 test('a business user creates a reviewed suite and must recheck before comparison',async({page})=>{
  const api=await setup(page);await page.goto('/observability?facet=quality&qualityView=tests&systemId=quality-system');const panel=page.locator('app-run-comparison');
  await panel.getByText('Créer un jeu de cas',{exact:true}).click();await panel.getByLabel('Nom du jeu de cas',{exact:true}).fill('Claims regression');await panel.getByLabel('Valeur',{exact:true}).fill('RC-5001');await panel.getByLabel('Réponse attendue',{exact:true}).fill('Request proof before reimbursement.');
  await expect(panel.getByRole('button',{name:'Enregistrer le jeu relu',exact:true})).toBeDisabled();await panel.getByLabel('J’ai relu ce cas et ses références',{exact:true}).check();await panel.getByRole('button',{name:'Enregistrer le jeu relu',exact:true}).click();
  await expect.poll(()=>api.writes.filter(row=>row.path==='/evaluation/suites').length).toBe(1);const suite=api.writes.find(row=>row.path==='/evaluation/suites')!.body;expect(suite.schema_version).toBe(2);expect(suite.cases[0].input_ref.question).toBe('RC-5001');expect(suite.reviewed).toBe(true);
  await panel.getByRole('combobox',{name:'Exécution de référence',exact:true}).selectOption('reference-run');await expect(panel.getByRole('button',{name:'Lancer la comparaison',exact:true})).toBeDisabled();await panel.getByRole('button',{name:'Vérifier le parcours',exact:true}).click();await expect(panel.getByRole('button',{name:'Lancer la comparaison',exact:true})).toBeEnabled();
  await panel.getByRole('combobox',{name:'Répétitions par version',exact:true}).selectOption({label:'2'});await expect(panel.getByRole('button',{name:'Lancer la comparaison',exact:true})).toBeDisabled();await panel.getByRole('button',{name:'Vérifier le parcours',exact:true}).click();await panel.getByRole('button',{name:'Lancer la comparaison',exact:true}).click();await expect.poll(()=>api.writes.filter(row=>row.path==='/evaluation/campaigns').length).toBe(1);expect(api.writes.find(row=>row.path==='/evaluation/campaigns')!.body.preflight_sha256).toBe('b'.repeat(64));await expect(panel).toContainText('Ask a reviewer to examine the proposal.');await expect(panel).toContainText('aucune action métier n’a été approuvée.');await expect(panel).toContainText('Non évalué');expect(api.writes.some(row=>row.path.endsWith('/raget'))).toBe(false);await expect(panel.locator('a[href*="qa-candidate-evaluation"]')).toHaveAttribute('href',/qa-candidate.*evaluationId=qa-candidate-evaluation/);
  await expect(panel.locator('a[href*="evaluationId=qa-evaluation"]')).toHaveCount(1); await expect(panel.locator('a[href*="evaluationId=qa-evaluation"]').first()).toHaveAttribute('href',/\/runs\/qa-reference\?.*facet=quality.*evaluationId=qa-evaluation/);
 });
 for(const locale of ['fr','en'] as const)test(`${locale}: a targeted retry preserves the initial comparison and checks a lost response idempotently`,async({page},info)=>{
  await setup(page,locale);await page.setViewportSize({width:locale==='fr'?1440:390,height:1000});
  const initial={...structuredClone(campaign),retry_pending:false};
  const original=initial.results[0].candidate;
  Object.assign(original,{status:'failed',termination:'failed',verdict:'unevaluated',quality_status:'unassessed',output_ref:{answer:'Initial measurement remains unavailable.'},can_retry:true,retry_source_run_id:'qa-candidate',attempts:[]});
  Object.assign(initial.results[0].baseline,{can_retry:false,retry_blocked_reason:'not_failed_terminal'});
  let current:any=initial;let pendingReads=0;const requests:any[]=[];
  await page.route('**/api/v1/evaluation/campaigns/campaign-1**',async route=>{
   if(route.request().method()==='POST'){
    requests.push(route.request().postDataJSON());
    if(requests.length===1){
     current={...current,retry_pending:true,results:[{...current.results[0],candidate:{...current.results[0].candidate,can_retry:false,retry_source_run_id:'retry-run',attempts:[{...campaignSide,id:'attempt-1',attempt_index:1,initial_run_id:'qa-candidate',source_run_id:'qa-candidate',run_id:'retry-run',job_id:'retry-job',created_at:'2026-10-22T15:00:00Z',actor_user_id:'reviewer-1',status:'pending',termination:null,verdict:'unevaluated',quality_status:'unassessed',output_ref:null,controls:[]}]}}]};
     return route.fulfill({status:504,contentType:'application/json',body:'{}'});
    }
    expect(requests[1]).toEqual(requests[0]);
   }else if(current.retry_pending){
    pendingReads++;
    if(pendingReads>=3){current=structuredClone(current);current.retry_pending=false;Object.assign(current.results[0].candidate.attempts[0],{status:'completed',verdict:'passed',quality_status:'passed',output_ref:{answer:'Retry evidence is now available.'},controls:[{invocation_id:'retry-judge',evaluation_id:'retry-evaluation',execution_status:'completed',quality_status:'passed'}]});}
   }
   return route.fulfill({contentType:'application/json',body:JSON.stringify(current)});
  });
  await page.goto('/observability?facet=quality&qualityView=tests&systemId=quality-system&campaign=campaign-1');const panel=page.locator('app-run-comparison');
  const action=panel.getByRole('button',{name:locale==='fr'?'Relancer cet essai':'Retry this trial',exact:true});await expect(action).toHaveCount(1);await action.click();
  await expect(panel).toContainText(locale==='fr'?'La réponse n’est pas arrivée':'The response did not arrive');await panel.getByRole('button',{name:locale==='fr'?'Vérifier ou renvoyer':'Check or resend',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(2);expect(requests[0]).toMatchObject({result_key:'case-1:0',side:'candidate',source_run_id:'qa-candidate'});expect(requests[0].request_key).toBeTruthy();expect(requests[1].request_key).toBe(requests[0].request_key);
  const attempt=panel.locator('[data-attempt-id="attempt-1"]');await expect(attempt).toHaveCount(1);await expect(attempt).toContainText('Retry evidence is now available.',{timeout:15000});
  await expect(panel).toContainText('Initial measurement remains unavailable.');await expect(panel).toContainText(locale==='fr'?'Les résultats et les totaux de la comparaison initiale restent inchangés.':'The initial comparison results and totals remain unchanged.');
  await expect(panel.locator('.columns > div').last()).toContainText(locale==='fr'?'Non évalué':'Not assessed');
  await expect(attempt.locator('a[href*="evaluationId=retry-evaluation"]')).toHaveAttribute('href',/retry-run.*facet=quality.*evaluationId=retry-evaluation/);
  await expect(panel.locator('a[href*="evaluationId=qa-candidate-evaluation"]')).toHaveAttribute('href',/qa-candidate.*evaluationId=qa-candidate-evaluation/);
  await expect(action).toHaveCount(0);expect(pendingReads).toBeGreaterThanOrEqual(3);expect(current.results[0].candidate.run_id).toBe('qa-candidate');expect(current.results[0].candidate.status).toBe('failed');
  expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);expect((await new AxeBuilder({page}).include('app-run-comparison').analyze()).violations).toEqual([]);await panel.locator('.columns').last().screenshot({path:info.outputPath('campaign-retry-'+locale+'.png')});
 });
 test('human annotation uses blind evidence and cannot be submitted twice',async({page})=>{
  const api=await setup(page);await page.goto('/observability?facet=quality&qualityView=review&systemId=quality-system&corpusId=corpus-1&unitKey=fresh-1');const panel=page.getByTestId('calibration-review');await expect(panel).toContainText(proof);await expect(panel).not.toContainText('The retained evidence supports the decision.');
  await panel.getByLabel(question.question,{exact:true}).selectOption({label:'Non'});await panel.getByLabel('Justification de votre appréciation',{exact:true}).fill('The source does not establish the requested policy exception.');await panel.getByRole('button',{name:'Enregistrer mon annotation',exact:true}).click();await expect(panel).toContainText('Votre annotation est enregistrée');await expect(panel.getByRole('button',{name:'Enregistrer mon annotation',exact:true})).toHaveCount(0);
  expect(api.reads).not.toContain('/typed-calibration/corpora/corpus-1');expect(api.reads.some(path=>path.includes('/evaluation/records/'))).toBe(false);const requests=api.writes.filter(row=>row.path.endsWith('/annotations'));expect(requests).toHaveLength(1);expect(requests[0].body.values).toEqual({policy:false});expect(requests[0].body.adjudication).toBe(false);expect(api.writes.some(row=>row.path.endsWith('/qualify'))).toBe(false);
 });
});
