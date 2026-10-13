import {readFileSync} from 'node:fs';
import { expect, test, type Page, type Route, type Locator } from '@playwright/test';
test.use({serviceWorkers:'block',video:'off',ignoreHTTPSErrors:false});
const workspace={id:'prep-qa',slug:'prep-qa',name:'Preparation QA',role:'owner',role_template:'workspace_owner',settings:{features:{dataops_enabled:true}},effective_features:{dataops_enabled:true},mode:'builder'};
const systemId='data-prep-qa',hash='d'.repeat(64);
const columns=[{name:'id',dtype:'BIGINT',kind:'integer'},{name:'name',dtype:'VARCHAR',kind:'string'},{name:'amount',dtype:'DOUBLE',kind:'float'}];
const datasets=[{id:'customers-v3',name:'Customers',slug:'customers',version:3,schema:columns},{id:'segments-v2',name:'Segments',slug:'segments',version:2,schema:[columns[0],{name:'segment',dtype:'VARCHAR',kind:'string'}]}].map(row=>({...row,status:'ready',source:'upload',row_count:10000,column_count:row.schema.length,parent_ids:[],created_at:'2026-10-13T10:00:00Z'}));
async function setup(page:Page,locale:'fr'|'en'){
 let graph:any={version:3,runtime_mode:'dag_overlay',nodes:[{id:'sql-train',kind:'task',type:'skill',label:'SQL train',position:{x:700,y:70},config:{skill_slug:'sql_transform_v1',params:{sql:'SELECT * FROM input',sources:[],output_name:'Train SQL'}},inputs:[{name:'in',schema:'object'}],outputs:[{name:'out',schema:'object'}]},{id:'sql-test',kind:'task',type:'skill',label:'SQL test',position:{x:700,y:330},config:{skill_slug:'sql_transform_v1',params:{sql:'SELECT * FROM input',sources:[],output_name:'Test SQL'}},inputs:[{name:'in',schema:'object'}],outputs:[{name:'out',schema:'object'}]}],edges:[]};
 const published=structuredClone(graph);let revision=1;const writes:Array<{path:string;body:any}>=[];
 const json=(route:Route,body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
 const system=()=>({id:systemId,workspace_id:workspace.id,name:'Prepare customers',status:'active',flow_definition:published,flow_sha256:hash});
 const state=()=>({system_id:systemId,status:'active',draft:{revision,base_published_version_id:'prep-v1',flow_sha256:hash,flow_definition:graph},published:{version_id:'prep-v1',version_number:1,flow_sha256:hash,flow_definition:published,execution_contract_ready:true}});
 await page.route('**/*',route=>['localhost','127.0.0.1'].includes(new URL(route.request().url()).hostname)?route.fallback():route.abort());
 await page.addInitScript(({slug,locale})=>{localStorage.setItem('agentium_token','Bearer isolated-prep-qa');localStorage.setItem('agentium_workspace_slug',slug);localStorage.setItem('agentium_locale',locale);localStorage.setItem('agentium_theme',locale==='fr'?'dark':'light');},{slug:workspace.slug,locale});
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname.replace(/^\/api\/v1/,'');
  if(path==='/auth/validate')return json(route,{valid:true,user_id:'qa-human',role:'admin'});
  if(path==='/auth/me')return json(route,{id:'qa-human',role:'admin',is_active:true,workspaces:[workspace]});
  if(path==='/auth/workspaces')return json(route,[workspace]);if(path===`/auth/workspaces/${workspace.slug}`)return json(route,workspace);
  if(request.method()!=='GET')writes.push({path,body:request.postDataJSON()});
  if(path==='/systems')return json(route,{systems:[system()]});if(path===`/systems/${systemId}`)return json(route,system());
  if(path===`/systems/${systemId}/flow-state`)return json(route,state());
  if(path===`/systems/${systemId}/flow-draft`&&request.method()==='PUT'){graph=request.postDataJSON().flow_definition;revision++;return json(route,{...state().draft,system_id:systemId,no_op:false});}
  if(path===`/systems/${systemId}/validate-flow`)return json(route,{valid:true,issues:[],runtime_mode:'dag_overlay',flow_sha256:hash});
  if(path==='/skills')return json(route,{skills:[{id:'prep-skill',slug:'data_prep_v1',name:'Data preparation',version:'1',type:'workflow',category:'Data',runtime_status:'bound',description:'Prepare datasets',input_schema:{type:'object',properties:{}},output_schema:{type:'object',properties:{out:{type:'object'}}},visibility:{visible:true,reason:'visible',capabilities:[]}}]});
  if(path==='/connectors')return json(route,{can_configure:true,connectors:[]});if(path==='/documents/collections')return json(route,{collections:[]});if(path==='/ml-models')return json(route,{models:[]});
  if(path==='/datasets')return json(route,{datasets,feature:{enabled:true,upload_max_bytes:1<<26}});
  if(path==='/dataops/catalog')return json(route,JSON.parse(readFileSync('e2e/fixtures/dataops-catalog.json','utf8')));
  if(path==='/dataops/validate-expression')return json(route,{valid:true,dtype:'DOUBLE',sql:request.postDataJSON().expression});
  if(path==='/dataops/preview'){const body=request.postDataJSON();return json(route,{rows:[{id:1,name:'Alice',amount:12,amount_twice:24}],schema:[...columns,{name:'amount_twice',dtype:'DOUBLE',kind:'float'}],stats:{},sample:true,sample_info:{rows:10000,of_rows:2000000,version:{in:'sample-v3'}},step_schemas:(body.spec.params.steps??[]).map((step:any,index:number)=>({id:step.id,index,enabled:step.enabled,schema:columns,schema_diff:{added:step.kind==='formula'?['amount_twice']:[],removed:[],changed:[]}})),warnings:[],counters:{inputs:{in:10000},outputs:{out:9250}},duration_ms:14});}
  if(path==='/dataops/compile')return json(route,{sql:'SELECT * FROM "in"',sql_export:'SELECT * FROM input',sql_export_allowed:true,fingerprint:hash,schema:columns,columns:columns.map(col=>col.name),ports:['in']});
  return json(route,{});
 });
 return {writes,graph:()=>graph,node:(operation:string)=>graph.nodes.find((node:any)=>node.config?.params?.spec?.operation===operation)};
}
async function add(page:Page,operation:string){await page.locator('.ck-flow-palette__search-input').fill('data_prep');await page.getByTestId('palette-data_prep_v1#'+operation).click();await page.getByTestId('open-prep-workshop').click();const workshop=page.locator('app-flow-data-prep-workshop');await expect(workshop).toBeVisible();return workshop;}
async function connect(page:Page,sourceId:string,sourcePort:string,targetId:string,targetPort:string){
 const from=page.locator(`[data-f-output-id="${sourceId}::out::${sourcePort}"]`),to=page.locator(`[data-f-input-id="${targetId}::in::${targetPort}"]`);
 await page.getByRole('button',{name:/^(Ajuster à la vue|Fit to view)$/}).click();await from.hover();const a=await from.boundingBox(),b=await to.boundingBox();expect(a).toBeTruthy();expect(b).toBeTruthy();await page.mouse.move(a!.x+a!.width/2,a!.y+a!.height/2);await page.mouse.down();await page.mouse.move(b!.x+b!.width/2,b!.y+b!.height/2,{steps:16});await page.mouse.up();
}
test.describe('Data preparation workshops — isolated mocked QA',()=>{
 test.beforeEach(async({},info)=>{test.skip(process.env['E2E_CHROME_V2_MOCKED']!=='1'||!['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),'Local mocked QA only.');});
 for(const locale of ['fr','en'] as const)test(`${locale}: author five stable steps, preview, join pins and persist split edges`,async({page},info)=>{
  test.setTimeout(120000);await page.setViewportSize({width:1600,height:1000});const api=await setup(page,locale);await page.goto(`/systems/${systemId}/flow?lens=build`);await expect(page.locator('app-flow-node')).toHaveCount(2);
  let workshop=await add(page,'prepare');await workshop.getByTestId('prep-input-in').selectOption('customers-v3');
  await workshop.getByTestId('prep-add-select_columns').click();
  await workshop.getByTestId('prep-add-text_transform').click();let params=workshop.locator('.dp-workshop-right app-prep-params');await params.locator('select[multiple]').first().selectOption('name');await params.locator('select').last().selectOption('trim');
  await workshop.getByTestId('prep-add-formula').click();params=workshop.locator('.dp-workshop-right app-prep-params');await params.locator('input.dp-input').first().fill('amount_twice');await params.locator('.cm-content').fill('"amount" * 2');
  await workshop.getByTestId('prep-add-filter_expression').click();await workshop.locator('.dp-workshop-right .cm-content').fill('"amount" > 0');
  await workshop.getByTestId('prep-add-sort').click();await workshop.locator('.dp-workshop-right select[multiple]').selectOption('amount');await workshop.getByTestId('prep-step-comment').fill(locale==='fr'?'Tri du résultat':'Sort result');
  await workshop.getByTestId('prep-step-enabled').uncheck();await expect.poll(()=>api.node('prepare')?.config.params.spec.params.steps.at(-1)?.enabled).toBe(false);await workshop.getByTestId('prep-step-enabled').check();
  await workshop.getByTestId('prep-preview').click();await expect(workshop.getByTestId('prep-sample-notice')).toContainText('10000');await expect(workshop.locator('ck-data-table')).toContainText('Alice');
  await expect.poll(()=>api.node('prepare')?.config.params.spec.params.steps.length).toBe(5);const steps=api.node('prepare').config.params.spec.params.steps;expect(new Set(steps.map((step:any)=>step.id)).size).toBe(5);expect(steps.every((step:any)=>/^[0-9a-f-]{36}$/.test(step.id))).toBe(true);
  const preview=api.writes.find(write=>write.path==='/dataops/preview')!.body;expect(preview.step_id).toBe(steps.at(-1).id);expect(preview.inputs).toEqual({in:{dataset_id:'customers-v3'}});expect(preview.outputs).toEqual([{port:'out',name:'prepare'}]);expect(preview.spec.params.steps[2].kind).toBe('formula');expect(preview.spec.params.steps[2].params.expression).toBe('"amount" * 2');
  await workshop.getByTestId('prep-undo').click();await workshop.getByTestId('prep-redo').click();await workshop.getByTestId('close-prep-workshop').click();
  workshop=await add(page,'join');await workshop.getByTestId('prep-input-left').selectOption('customers-v3');await workshop.getByTestId('prep-input-right').selectOption('segments-v2');await workshop.getByTestId('prep-match-keys').click();await workshop.getByTestId('close-prep-workshop').click();
  await expect.poll(()=>api.node('join')?.config.params.sources.length).toBe(2);expect(api.node('join').config.params.spec.params.on).toEqual([{left:'id',right:'id',op:'eq'}]);expect(api.node('join').inputs.map((port:any)=>port.name)).toEqual(['left','right']);
  workshop=await add(page,'split');await workshop.getByTestId('prep-output-name-0').fill('Training customers');await workshop.getByTestId('prep-output-name-1').fill('Test customers');await workshop.getByTestId('close-prep-workshop').click();await expect.poll(()=>api.node('split')?.config.params.outputs[1].name).toBe('Test customers');
  // The saved nodes are reloaded at separated positions, so real pointer wiring is deterministic.
  api.graph().nodes.forEach((node:any)=>{const operation=node.config?.params?.spec?.operation;if(operation==='prepare')node.position={x:20,y:30};if(operation==='join')node.position={x:280,y:30};if(operation==='split')node.position={x:280,y:350};});
  await page.reload();await expect(page.locator('app-flow-node')).toHaveCount(5);await connect(page,api.node('join').id,'out',api.node('split').id,'in');await connect(page,api.node('split').id,'train','sql-train','in');await connect(page,api.node('split').id,'test','sql-test','in');
  await expect.poll(()=>api.graph().edges.map((edge:any)=>[edge.from_port,edge.to_port])).toEqual(expect.arrayContaining([['out','in'],['train','in'],['test','in']]));expect(api.graph().edges.map((edge:any)=>[edge.from_port,edge.to_port])).toEqual(expect.arrayContaining([['out','in'],['train','in'],['test','in']]));
  expect(api.node('split').outputs.map((port:any)=>port.name)).toEqual(['train','test']);expect(api.node('prepare').config.params.spec.params.steps.map((step:any)=>step.id)).toEqual(steps.map((step:any)=>step.id));
  expect(api.writes.filter(write=>/\/runs$|\/publish$|\/executions$/.test(write.path))).toHaveLength(0);await page.screenshot({path:info.outputPath(`data-prep-${locale}.png`),fullPage:true});
 });
});
