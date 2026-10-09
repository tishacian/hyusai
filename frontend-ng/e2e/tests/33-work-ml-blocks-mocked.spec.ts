import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'qa-work-models', slug: 'qa-work-models', name: 'Product QA', role: 'owner', role_template: 'workspace_owner', settings: { features: { experience_v1: true } } };
const contract = { schema_version:1, task:'classification', model_id:'qa-sla-model',model_version:2,target:'late',positive_label:'1',label:'SLA risk',unit:'probability',value_column:'prediction',score_column:'probability',max_age_seconds:3600,bands:[{key:'low',label:'Standard',min:0},{key:'high',label:'Priority review',min:.6}],order:'descending' };
function document() { return {pages:[{id:'forecast',title:'Charge et capacité',components:[
  {type:'header',id:'intro',props:{title:'Anticiper la charge',subtitle:'Historique observé, prévision et preuve du modèle.'}},
  {type:'action_button',id:'forecast-action',props:{label:'Calculer la prévision',bindingKey:'operations.forecast',input:{}}},
  {type:'prediction',id:'risk',props:{title:'Priorité du dossier',predictionContract:contract,dataBinding:{source:'run-output',componentId:'forecast-action',nodeId:'sav.context',selector:'model_advice'}}},
  {type:'chart',id:'forecast-chart',props:{title:'Charge par jour',caption:'Observations et prévision à 14 jours',kind:'timeseries',datasetSource:{source:'run-output',componentId:'forecast-action',selector:'dataset_id'},mapping:{time:'ds',actual:'actual',value:'forecast',lower:'lower',upper:'upper',series:'channel'},unit:'dossiers'}},
]},{id:'history',title:'Historique',components:[{type:'callout',id:'help',props:{body:'Les décisions restent liées à leur exécution.'}}]}]}; }
const rows = Array.from({length:28},(_,i)=> { const date=new Date('2026-10-01T00:00:00Z');date.setUTCDate(date.getUTCDate()+i);const y=Math.round(42+20*Math.sin(i/3)+i*2);return {ds:date.toISOString(),channel:'Web',actual:i<14?y:null,forecast:i>=14?y:null,lower:i>=14?y-12:null,upper:i>=14?y+14:null}; });
async function setup(page:Page, theme='dark',locale='fr',state:'ready'|'denied'|'empty'|'stale'|'partial'='ready') {
  let saved=document();const writes:any[]=[];const datasetRequests:string[]=[];
  const experience={id:'qa-experience',slug:'operations',name:'Opérations SAV',description:'Décider avec les données et les preuves',pattern:'dashboard',languages:['fr','en'],theme:{mode:theme},access_policy:{roles:[],groups:[]},created_by:'qa-user',updated_at:'2026-10-09T00:00:00Z'};
  const binding={binding_key:'operations.forecast',system_id:'qa-system',published_flow_version_id:'qa-version',ingress_id:'source.forecast',confirmation_policy:'none',on_unavailable:'unavailable'};
  await page.route('**/*',route=>['localhost','127.0.0.1'].includes(new URL(route.request().url()).hostname)?route.fallback():route.abort());
  await page.addInitScript(({theme,locale,slug})=>{localStorage.setItem('agentium_token','Bearer isolated-work-models-qa');localStorage.setItem('agentium_theme',theme);localStorage.setItem('agentium_locale',locale);localStorage.setItem('agentium_workspace_slug',slug);},{theme,locale,slug:workspace.slug});
  const json=(route:Route,body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  await page.route('**/api/v1/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname.replace(/^\/api\/v1/,'');
    if(path==='/auth/validate')return json(route,{valid:true,user_id:'qa-user',email:'qa@example.test',role:'admin'});
    if(path==='/auth/me')return json(route,{id:'qa-user',email:'qa@example.test',role:'admin',is_active:true,workspaces:[workspace]});
    if(path==='/auth/workspaces')return json(route,[workspace]);
    if(path==='/auth/workspaces/'+workspace.slug)return json(route,workspace);
    if(path==='/work/operations')return json(route,{experience,channel:'live',release:{id:'qa-release',release_number:2,pages:saved,renderer_version:'certified-components-0.2.0',bindings_snapshot:[binding],theme:{mode:theme},languages:['fr','en']}});
    if(path.endsWith('/bindings/operations.forecast/resolve'))return json(route,{status:'ok',binding});
    if(path.endsWith('/bindings/operations.forecast/runs')){writes.push(req.postDataJSON());return json(route,{id:'qa-forecast-run',status:'pending'},201);}
    if(path==='/runs/qa-forecast-run')return json(route,{id:'qa-forecast-run',system_id:'qa-system',status:'completed',completed_at:new Date().toISOString(),output_ref:{dataset_id:'qa-result-dataset',advice:{served:{model_id:'qa-sla-model',version:state==='stale'?1:2},target:'late',positive_label:'1',captured_at:new Date().toISOString(),predictions:[{prediction:'1',probability:.82}]}},skill_invocations:[{id:'qa-context',run_id:'qa-forecast-run',status:'completed',trace:{node_id:'sav.context'},output_ref:{model_advice:{served:{model_id:'qa-sla-model',version:state==='stale'?1:2},target:'late',positive_label:'1',captured_at:new Date().toISOString(),predictions:[{prediction:'1',probability:.82}]}}}]});
    if(path.startsWith('/work/operations/datasets/')){datasetRequests.push(url.search);return json(route,state==='denied'?{detail:{code:'WORK_DATASET_NOT_FOUND'}}:{rows:state==='empty'?[]:rows,columns:['ds','actual','forecast','lower','upper','channel'],total_rows:state==='empty'?0:state==='partial'?40:28,returned_rows:state==='empty'?0:28,truncated:state==='partial',provenance:{dataset_id:'qa-result-dataset',dataset_version:3,dataset_name:'Charge SAV',run_id:'qa-forecast-run',model:{model_id:'qa-forecast-model',name:'Prévision de charge',version:2}},freshness:{dataset_created_at:new Date().toISOString()}},state==='denied'?404:200);}
    if(path==='/experiences/qa-experience')return json(route,{...experience,draft:{pages:saved,binding_keys:['operations.forecast'],revision:1,content_sha256:'a'.repeat(64)},deployments:[]});
    if(path==='/experiences/qa-experience/draft'&&req.method()==='PUT'){const body=req.postDataJSON();writes.push(body);saved=body.pages;return json(route,{...body,revision:2,content_sha256:'b'.repeat(64)});}
    if(path==='/experiences/qa-experience/ready-check')return json(route,{ready:true,blockers:[],warnings:[],bindings:[binding]});
    if(path==='/experiences/qa-experience/releases')return json(route,{releases:[]});
    if(path==='/experiences/qa-experience/draft/revisions')return json(route,{revisions:[]});
    if(path==='/experiences')return json(route,{experiences:[experience]});
    if(path==='/system-bindings')return json(route,{bindings:[binding]});
    if(path==='/system-bindings/drift')return json(route,{bindings:[]});
    if(path==='/systems')return json(route,[]);
    if(path==='/systems/qa-system/ingresses')return json(route,{system_id:'qa-system',published_flow_version_id:'qa-version',ingresses:[{ingress_id:'source.forecast',kind:'manual',input_schema:{type:'object',properties:{}}}],output_schema:{type:'object'}});
    if(path==='/work/operations/validations')return json(route,{runs:[]});
    return json(route,{});
  });
  return {writes,datasetRequests,saved:()=>saved};
}

test.describe('Generic Work prediction and time series — local product QA',()=>{
 test.beforeEach(async({},info)=>{test.skip(process.env['E2E_CHROME_V2_MOCKED']!=='1'||!['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),'Local mocked QA only');});
 for(const [theme,locale,width] of [['dark','fr',1440],['light','en',1440],['light','fr',390]] as const){
  test(`${theme}/${locale}/${width}: run output, forecast band, provenance and keyboard`,async({page})=>{
   await page.setViewportSize({width,height:1000});const fixture=await setup(page,theme,locale);
   await page.goto('/work/operations/forecast');
   const action=page.getByRole('button',{name:'Calculer la prévision',exact:true});await expect(action).toBeVisible();
   await expect(page.locator('xp-timeseries canvas')).toHaveCount(0);
   await action.focus();await page.keyboard.press('Enter');
   await expect(page.locator('xp-prediction-card')).toContainText('82');
   await expect(page.locator('xp-prediction-card')).toContainText('Priority review');
   await expect(page.locator('xp-timeseries canvas')).toBeVisible();
   await expect(page.locator('xp-timeseries')).toContainText('28 / 28');
   await expect(page.locator('xp-timeseries a').filter({hasText:'Charge SAV'})).toHaveAttribute('href',/\/data\/qa-result-dataset/);
   await expect(page.locator('xp-timeseries a').filter({hasText:'Prévision de charge'})).toHaveAttribute('href',/\/models\/qa-forecast-model/);
   expect(fixture.datasetRequests).toEqual(['?run_id=qa-forecast-run']);
   expect(fixture.writes[0]).toMatchObject({page_id:'forecast',component_id:'forecast-action',payload:{}});
   const summary=page.locator('xp-timeseries summary');await summary.focus();await page.keyboard.press('Enter');
   await expect(page.locator('xp-timeseries tbody tr')).toHaveCount(28);
   await page.keyboard.press('Enter');
   const violations=(await new AxeBuilder({page}).include('app-experience-runtime-host').analyze()).violations;
   expect(violations).toEqual([]);
   const overflow=await page.evaluate(()=>({ok:document.documentElement.scrollWidth<=innerWidth, offenders:[...document.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).slice(0,12)}));
   expect(overflow.ok,JSON.stringify(overflow.offenders)).toBe(true);
   expect((await action.boundingBox())!.height).toBeLessThanOrEqual(44);
   expect((await action.boundingBox())!.width).toBeLessThanOrEqual(260);
   await page.screenshot({path:`/workspace/scratch/work-blocks-2026-10-09/work-${theme}-${locale}-${width}.png`,fullPage:true});
   await page.getByRole('link',{name:'Historique',exact:true}).click();await expect(page.getByText('Les décisions restent liées à leur exécution.')).toBeVisible();
  });
 }
 for(const state of ['denied','empty','stale','partial'] as const){
  test(`${state}: unavailable data is never replaced by a preview or another model`,async({page})=>{
   await setup(page,'dark','fr',state);await page.goto('/work/operations/forecast');await page.getByRole('button',{name:'Calculer la prévision',exact:true}).click();
   if(state==='denied'){await expect(page.locator('xp-timeseries [role=alert]')).toBeVisible();await expect(page.locator('xp-timeseries canvas')).toHaveCount(0);await page.locator('xp-timeseries button').click();await expect(page.locator('xp-timeseries [role=alert]')).toBeVisible();}
   if(state==='empty'){await expect(page.locator('xp-timeseries')).toContainText('Aucune série disponible');await expect(page.locator('xp-timeseries canvas')).toHaveCount(0);}
   if(state==='partial'){await expect(page.locator('xp-timeseries')).toContainText('Vue partielle');await expect(page.locator('xp-timeseries')).toContainText('28 / 40');await expect(page.locator('xp-timeseries canvas')).toBeVisible();}
   if(state==='stale'){await expect(page.locator('xp-prediction-card')).toContainText('Aucune prédiction récente');await expect(page.locator('.prediction__value')).toHaveCount(0);}
   await page.screenshot({path:`/workspace/scratch/work-blocks-2026-10-09/work-${state}.png`,fullPage:true});
  });
 }
 test('Studio exposes typed controls and persists mappings and prediction semantics',async({page})=>{
   const fixture=await setup(page);await page.setViewportSize({width:1600,height:1100});await page.goto('/create/apps/qa-experience');
   await expect(page.locator('.xp-ed')).toBeVisible();
   await page.locator('.xp-tree').getByRole('button',{name:'Graphique',exact:true}).click();
   await expect(page.locator('xp-timeseries-editor')).toBeVisible();
   await expect(page.getByRole('combobox',{name:'Composant source',exact:true})).toHaveValue('forecast-action');
   await expect(page.getByLabel('Titre',{exact:true})).toHaveValue('Charge par jour');
   await page.getByLabel('Unité',{exact:true}).fill('tickets');
   await page.getByLabel('Colonne date',{exact:true}).fill('event_date');
   await expect.poll(()=>fixture.saved().pages[0].components.find((c:any)=>c.id==='forecast-chart')!.props.mapping?.time).toBe('event_date');
   await page.locator('.xp-tree').getByRole('button',{name:'Prédiction',exact:true}).click();
   await expect(page.locator('xp-prediction-contract-editor')).toBeVisible();
   await page.getByLabel('Version épinglée',{exact:true}).fill('3');
   await expect.poll(()=>fixture.saved().pages[0].components.find((c:any)=>c.id==='risk')!.props.predictionContract?.model_version).toBe(3);
   await page.screenshot({path:'/workspace/scratch/work-blocks-2026-10-09/studio-prediction.png',fullPage:true});
   await page.reload();await page.locator('.xp-tree').getByRole('button',{name:'Graphique',exact:true}).click();await expect(page.getByLabel('Colonne date',{exact:true})).toHaveValue('event_date');await expect(page.getByLabel('Unité',{exact:true})).toHaveValue('tickets');
   await page.screenshot({path:'/workspace/scratch/work-blocks-2026-10-09/studio-chart.png',fullPage:true});
 });
});
