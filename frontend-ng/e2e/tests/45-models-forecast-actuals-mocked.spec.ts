import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {expect,test,type Page} from '@playwright/test';
test.use({serviceWorkers:'block',video:'off',viewport:{width:1440,height:1000}});
const catalog=JSON.parse(readFileSync(resolve(process.cwd(),'e2e/fixtures/ml-forecast.json'),'utf8')).catalog;
const workspace={id:'actuals-qa',slug:'actuals-qa',name:'Forecast QA',role:'owner',role_template:'workspace_owner',settings:{},mode:'builder'};
const model={id:'forecast-v1',name:'Network load',slug:'network-load',version:1,task:'forecasting',family:'forecasting',algo:'linear',target:'load',features:[],status:'ready',is_champion:true,metrics:{scores:[]},params:{knobs:{}},spec:{time_column:'date',horizon:24,shape:'single'},signature:{inputs:[]}};
const dataset={id:'observed-dataset',name:'Observed network load',slug:'observed-load',version:2,status:'ready',schema:[],parent_ids:[]};
const metric={count:24,mae:4,rmse:5,smape:12,interval_count:24,coverage:.5,nominal_coverage:.8,mean_interval_width:2,anomalies:12};
async function setup(page:Page,locale:string,readOnly=false,forbidden=false){
 let associated=false;const posts:unknown[]=[];
 const report=()=>({badge:associated?'alert':null,window:{predictions:1,labeled:0,limit:400},data_drift:{status:'unknown',features:[]},score_drift:{status:'unknown'},concept_drift:{status:'unknown'},forecast_actuals:{status:associated?'alert':'unconfigured',can_configure:!readOnly,dataset:associated?{...dataset,sha256:'a'.repeat(64),follow_latest:true}:null,overall:metric,by_series:[{series:'load',...metric}],by_horizon:[{horizon:1,...metric}],anomalies:[{series:'load',timestamp:'2026-10-08T12:00:00+00:00',horizon:1,actual:13,pred:10,lower_bound:9,upper_bound:11,prediction_id:'prediction-1'}],window:{calls:1,retained_points:24,matched:24,excluded_late:2,excluded_future:3,duplicates:1,limit_calls:400,limit_points:25600,truncated:true},policy:{selection:'earliest_issued_per_series_timestamp_horizon'}}});
 await page.route('**/*',route=>['localhost','127.0.0.1'].includes(new URL(route.request().url()).hostname)?route.fallback():route.abort());
 await page.addInitScript(({locale,slug})=>{localStorage.setItem('agentium_token','Bearer actuals-qa');localStorage.setItem('agentium_workspace_slug',slug);localStorage.setItem('agentium_locale',locale);localStorage.setItem('agentium_theme',locale==='fr'?'dark':'light');},{locale,slug:workspace.slug});
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname.replace(/^\/api\/v1/,'');
  const json=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(path==='/auth/validate')return json({valid:true,user_id:'qa',role:'admin'});
  if(path==='/auth/me')return json({id:'qa',role:'admin',is_active:true,workspaces:[workspace]});
  if(path==='/auth/workspaces')return json([workspace]);
  if(path===`/auth/workspaces/${workspace.slug}`)return json(workspace);
  if(path==='/ml-models/catalog')return json({catalog});
  if(path==='/ml-models')return json({models:[model],catalog});
  if(path===`/ml-models/${model.id}`)return json({model,dataset:null,versions:[model],catalog,serving:{enabled:true,callable:true,fields:[],keys:[]}});
  if(path===`/ml-models/${model.id}/monitoring`)return json({monitoring:report()});
  if(path===`/ml-models/${model.id}/monitoring/actuals`){posts.push(req.postDataJSON());if(forbidden)return json({detail:{code:'ML_FORECAST_ACTUALS_FORBIDDEN'}},403);associated=true;return json({monitoring:report()});}
  if(path==='/datasets')return json({datasets:[dataset],feature:{enabled:true}});
  return json({});
 });return{posts};
}
test.beforeEach(async({},info)=>{test.skip(process.env['E2E_CHROME_V2_MOCKED']!=='1'||!['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),'Local mocked QA only.');});
for(const locale of ['fr','en'])test(`${locale}: associate actuals and inspect observed errors and coverage`,async({page},info)=>{
 const api=await setup(page,locale);await page.goto(`/models/${model.id}?facet=monitor`);
 const panel=page.getByTestId('forecast-actuals');await expect(panel).toBeVisible();
 await panel.getByTestId('actuals-load-datasets').click();await panel.getByTestId('actuals-dataset').selectOption(dataset.id);
 await panel.getByTestId('actuals-follow').check();await panel.getByTestId('actuals-save').click();
 await expect.poll(()=>api.posts).toEqual([{dataset_id:dataset.id,follow_latest:true}]);
 await expect(panel.getByTestId('actuals-status')).toContainText(locale==='fr'?'nettement inférieure':'substantially below');
 await expect(panel.locator('[data-metric="coverage"]')).toContainText('50');await expect(panel.locator('[data-metric="mae"]')).toHaveText('4');
 await expect(panel.getByTestId('actuals-series')).toContainText('load');await expect(panel.getByTestId('actuals-horizons')).toContainText('+1');await expect(panel.getByTestId('actuals-anomalies')).toContainText('13');
 await expect(panel).toContainText(locale==='fr'?'ne couvrent pas tout':'do not cover');await expect(page.getByTestId('monitor-panel')).toHaveCount(0);
 await panel.screenshot({path:info.outputPath(`actuals-${locale}.png`)});
});
test('read-only users see actuals without mutation controls',async({page})=>{const api=await setup(page,'en',true);await page.goto(`/models/${model.id}?facet=monitor`);await expect(page.getByTestId('forecast-actuals')).toBeVisible();await expect(page.getByTestId('actuals-save')).toHaveCount(0);expect(api.posts).toHaveLength(0);});
test('forbidden association keeps current evidence and disables editing',async({page})=>{const api=await setup(page,'en',false,true);await page.goto(`/models/${model.id}?facet=monitor`);await page.getByTestId('actuals-load-datasets').click();await page.getByTestId('actuals-dataset').selectOption(dataset.id);await page.getByTestId('actuals-save').click();await expect(page.getByTestId('forecast-actuals').getByRole('alert')).toContainText('cannot change');await expect(page.getByTestId('actuals-status')).toContainText('Associate a dataset');await expect(page.getByTestId('actuals-save')).toHaveCount(0);expect(api.posts).toHaveLength(1);});
