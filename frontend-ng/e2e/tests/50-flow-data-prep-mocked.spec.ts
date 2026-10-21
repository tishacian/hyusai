import {readFileSync} from 'node:fs';
import { expect, test, type Page, type Route, type Locator } from '@playwright/test';
test.use({serviceWorkers:'block',video:'off',ignoreHTTPSErrors:false});
const workspace={id:'prep-qa',slug:'prep-qa',name:'Preparation QA',role:'owner',role_template:'workspace_owner',settings:{features:{dataops_enabled:true}},effective_features:{dataops_enabled:true},mode:'builder'};
const systemId='data-prep-qa',hash='d'.repeat(64);
const columns=[{name:'id',dtype:'BIGINT',kind:'integer'},{name:'name',dtype:'VARCHAR',kind:'string'},{name:'amount',dtype:'DOUBLE',kind:'float'}];
const datasets=[{id:'customers-v3',name:'Customers',slug:'customers',version:3,schema:columns},{id:'segments-v2',name:'Segments',slug:'segments',version:2,schema:[columns[0],{name:'segment',dtype:'VARCHAR',kind:'string'}]}].map(row=>({...row,status:'ready',source:'upload',row_count:10000,column_count:row.schema.length,parent_ids:[],created_at:'2026-10-13T10:00:00Z'}));
function upstreamTestGraph(){
 const task=(id:string,label:string,x:number,y:number,skill:string,params:unknown)=>({id,kind:'task',type:'skill',label,position:{x,y},config:{skill_slug:skill,params},inputs:[{name:'in',schema:'object'}],outputs:[{name:'out',schema:'object'}]});
 return {version:3,runtime_mode:'dag_overlay',nodes:[
  task('sav.features','Source SQL',40,80,'sql_transform_v1',{sql:'SELECT * FROM input',sources:[{view:'input',dataset_id:'customers-v3'}],output_name:'Source test'}),
  task('sav.prepare','Préparation SAV',430,80,'data_prep_v1',{spec:{version:1,operation:'prepare',params:{steps:[
   {id:'columns',kind:'select_columns',enabled:true,params:{columns:['id','name','amount']}},
   {id:'amount_twice',kind:'formula',enabled:true,params:{output:'amount_twice',expression:'amount * 2'}},
   {id:'amount_positive',kind:'formula',enabled:true,params:{output:'amount_positive',expression:'amount > 0'}},
   {id:'order',kind:'sort',enabled:true,params:{keys:[{column:'id',direction:'asc'}]}},
  ]}},outputs:[{port:'out',name:'Prepared source'}],sources:[],placement:'local'}),
  task('user.draft','Préparation utilisateur inachevée',430,390,'data_prep_v1',{spec:{version:1,operation:'prepare',params:{steps:[]}},outputs:[{port:'out',name:'User draft'}],sources:[],placement:'local'}),
 ],edges:[{id:'source-to-prep',from:'sav.features',from_port:'out',to:'sav.prepare',to_port:'in',kind:'data'}]};
}
async function setup(page:Page,locale:'fr'|'en',options:{upstreamNodeTest?:boolean;compiledSql?:string}={}){
 let graph:any={version:3,runtime_mode:'dag_overlay',nodes:[{id:'sql-train',kind:'task',type:'skill',label:'SQL train',position:{x:700,y:70},config:{skill_slug:'sql_transform_v1',params:{sql:'SELECT * FROM input',sources:[],output_name:'Train SQL'}},inputs:[{name:'in',schema:'object'}],outputs:[{name:'out',schema:'object'}]},{id:'sql-test',kind:'task',type:'skill',label:'SQL test',position:{x:700,y:330},config:{skill_slug:'sql_transform_v1',params:{sql:'SELECT * FROM input',sources:[],output_name:'Test SQL'}},inputs:[{name:'in',schema:'object'}],outputs:[{name:'out',schema:'object'}]}],edges:[]};
 if(options.upstreamNodeTest)graph=upstreamTestGraph();
 const published=structuredClone(graph);let revision=1;const writes:Array<{path:string;body:any}>=[];
 let nodeRun:any=null;
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
  if(path===`/systems/${systemId}/validate-flow`)return json(route,{valid:!options.upstreamNodeTest,issues:options.upstreamNodeTest?[{level:'error',code:'FLOW_NODE_UNREACHABLE',message:'Unconnected user draft node',node_id:'user.draft'}]:[],runtime_mode:'dag_overlay',flow_sha256:hash});
  if(path===`/systems/${systemId}/flow-workbench/node-runs`){
   const body=request.postDataJSON(),execution={node_id:body.node_id,execution_surface:'node_preview',source_flow_sha256:hash,flow_sha256:'e'.repeat(64),runtime_mode:'dag_overlay'};
   nodeRun={id:'source-preview-run',system_id:systemId,status:'pending',...execution,input_ref:{...body.input_ref,execution},output_ref:{},checkpoints:[]};return json(route,nodeRun,201);
  }
  if(path==='/runs/source-preview-run')return json(route,{...nodeRun,status:'completed',output_ref:{dataset_id:'source-test-dataset',row_count:23,column_count:3}});
  if(path==='/skills')return json(route,{skills:[{id:'prep-skill',slug:'data_prep_v1',name:'Data preparation',version:'1',type:'workflow',category:'Data',runtime_status:'bound',description:'Prepare datasets',input_schema:{type:'object',properties:{}},output_schema:{type:'object',properties:{out:{type:'object'}}},visibility:{visible:true,reason:'visible',capabilities:[]}}]});
  if(path==='/connectors')return json(route,{can_configure:true,connectors:[]});if(path==='/documents/collections')return json(route,{collections:[]});if(path==='/ml-models')return json(route,{models:[]});
  if(path==='/datasets')return json(route,{datasets:options.upstreamNodeTest?[...datasets,{...datasets[0],id:'source-test-dataset',name:'Source test',version:9,row_count:23,source:'postgresql',run_id:'published-run-123',node_id:'source.reader',system_id:systemId}]:datasets,feature:{enabled:true,upload_max_bytes:1<<26}});
  if(path==='/dataops/catalog')return json(route,JSON.parse(readFileSync('e2e/fixtures/dataops-catalog.json','utf8')));
  if(path==='/dataops/validate-expression')return json(route,{valid:true,dtype:'DOUBLE',sql:request.postDataJSON().expression});
  if(path==='/dataops/preview'){const body=request.postDataJSON();return json(route,{rows:[{id:1,name:'Alice',amount:12,amount_twice:24}],schema:[...columns,{name:'amount_twice',dtype:'DOUBLE',kind:'float'}],stats:{},sample:true,sample_info:{rows:10000,of_rows:2000000,version:{in:'sample-v3'}},step_schemas:(body.spec.params.steps??[]).map((step:any,index:number)=>({id:step.id,index,enabled:step.enabled,schema:columns,schema_diff:{added:step.kind==='formula'?['amount_twice']:[],removed:[],changed:[]}})),warnings:[],counters:{inputs:{in:10000},outputs:{out:9250}},duration_ms:14});}
  if(path==='/dataops/compile')return json(route,{sql:options.compiledSql??'SELECT * FROM "in"',sql_export:'SELECT * FROM input',sql_export_allowed:true,fingerprint:hash,schema:columns,columns:columns.map(col=>col.name),ports:['in']});
  return json(route,{});
 });
 return {writes,graph:()=>graph,node:(operation:string)=>graph.nodes.find((node:any)=>node.config?.params?.spec?.operation===operation)};
}
async function add(page:Page,operation:string){await page.locator('.ck-flow-palette__search-input').fill('data_prep');await page.getByTestId('palette-data_prep_v1#'+operation).click();await page.getByTestId('open-prep-workshop').click();const workshop=page.locator('app-flow-data-prep-workshop');await expect(workshop).toBeVisible();return workshop;}
async function connect(page:Page,api:Awaited<ReturnType<typeof setup>>,sourceId:string,sourcePort:string,targetId:string,targetPort:string){
 const from=page.locator(`[data-f-output-id="${sourceId}::out::${sourcePort}"]`),to=page.locator(`[data-f-input-id="${targetId}::in::${targetPort}"]`);
 const previous=await page.locator('f-connection').count();
 await expect(page.locator('.ck-flow-toolbar__state')).toHaveClass(/is-saved/);
 await page.getByRole('button',{name:/^(Ajuster à la vue|Fit to view)$/}).click();
 // Fit and the autosave receipt can move the canvas. Resolve the target at
 // the end of the real drag instead of dropping at its earlier coordinates.
 await from.hover();
 const start=await from.boundingBox();expect(start).toBeTruthy();
 const point={x:start!.x+start!.width/2,y:start!.y+start!.height/2};
 await page.mouse.move(point.x,point.y);
 expect(await from.evaluate((element,point)=>element.contains(document.elementFromPoint(point.x,point.y)),point)).toBe(true);
 await page.mouse.down();
 // Foblex starts its connection gesture on the first move, then resolves the
 // destination on a following move. Keep the pointer down through both.
 await page.mouse.move(start!.x+start!.width/2+12,start!.y+start!.height/2,{steps:3});
 await to.hover();
 await to.hover();
 await page.mouse.up();
 await expect(page.locator('.flow-builder__handle-backdrop')).toHaveCount(0);
 await expect(page.locator('f-connection')).toHaveCount(previous+1);
 await expect.poll(()=>api.graph().edges.some((edge:any)=>edge.from===sourceId&&edge.from_port===sourcePort&&edge.to===targetId&&edge.to_port===targetPort)).toBe(true);
 await expect(page.locator('.ck-flow-toolbar__state')).toHaveClass(/is-saved/);
}
test.describe('Data preparation workshops — isolated mocked QA',()=>{
 test.beforeEach(async({},info)=>{test.skip(process.env['E2E_CHROME_V2_MOCKED']!=='1'||!['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),'Local mocked QA only.');});
 for(const locale of ['fr','en'] as const)test(`${locale}: compiled SQL fills an opaque scrollable dialog above table headers`,async({page},info)=>{
  await page.setViewportSize({width:1440,height:1000});
  const sql=['-- '+Array(80).fill('wide SQL expression').join(' '),...Array.from({length:80},(_,i)=>`SELECT ${i} AS step FROM "in"${i<79?' UNION ALL':';'}`)].join('\n');
  const api=await setup(page,locale,{upstreamNodeTest:true,compiledSql:sql}),original=structuredClone(api.graph());
  await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
  await expect(page.locator('app-flow-node')).toHaveCount(3);
  await page.locator('app-flow-node').filter({hasText:'Préparation SAV'}).click();
  await page.getByTestId('open-prep-workshop').click();
  const workshop=page.locator('app-flow-data-prep-workshop');
  await workshop.getByTestId('prep-preview-input-in').selectOption('source-test-dataset');
  await workshop.getByTestId('prep-preview').click();
  await expect(workshop.locator('ck-data-table')).toContainText('Alice');
  await workshop.getByTestId('prep-sql').click();
  const dialog=workshop.getByTestId('prep-sql-result'),close=dialog.getByRole('button',{name:locale==='fr'?'Fermer':'Close',exact:true});
  await expect(dialog).toHaveAttribute('role','dialog');
  await expect(dialog.getByRole('heading',{name:locale==='fr'?'SQL compilé':'Compiled SQL',exact:true})).toBeVisible();
  await expect(dialog.locator('.cm-content')).toHaveAttribute('contenteditable','false');
  const boxes=await dialog.evaluate(el=>{
   const box=(target:Element)=>{const b=target.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};};
   return {dialog:box(el),editor:box(el.querySelector('ck-code-editor')!),close:box(el.querySelector('button')!)};
  });
  expect(boxes.editor.height).toBeGreaterThan(500);
  expect(boxes.editor.height/boxes.dialog.height).toBeGreaterThan(.8);
  expect(boxes.close.x).toBeGreaterThan(boxes.dialog.x+boxes.dialog.width-120);
  expect(boxes.close.y).toBeLessThan(boxes.dialog.y+70);
  const tableHeader=workshop.locator('ck-data-table th').nth(1);
  const covered=await tableHeader.evaluate(el=>{
   const b=el.getBoundingClientRect();
   return !!document.elementFromPoint(b.x+b.width/2,b.y+b.height/2)?.closest('[data-testid="prep-sql-result"]');
  });
  expect(covered,'table header must not paint or receive pointer events above the dialog').toBe(true);
  const scroller=dialog.locator('.cm-scroller');
  await expect.poll(()=>scroller.evaluate(el=>el.scrollHeight>el.clientHeight&&el.scrollWidth>el.clientWidth)).toBe(true);
  await scroller.evaluate(el=>{el.scrollTop=250;el.scrollLeft=250;});
  expect(await scroller.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
  expect(await scroller.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  await scroller.evaluate(el=>{el.scrollTop=0;el.scrollLeft=0;});
  await workshop.screenshot({path:info.outputPath(`compiled-sql-${locale}.png`)});
  await close.focus();await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(workshop).toBeVisible();
  await expect(workshop.getByTestId('prep-sql')).toBeFocused();
  await workshop.getByTestId('close-prep-workshop').click();
  await page.waitForTimeout(1500);
  expect(api.graph()).toEqual(original);
  expect(api.writes.filter(write=>/\/flow-draft$|\/publish$|\/node-runs$|\/executions$/.test(write.path))).toHaveLength(0);
 });
 for(const locale of ['fr','en'] as const)test(`${locale}: preview an existing Run dataset without changing the Flow or its pins`,async({page},info)=>{
  await page.setViewportSize({width:1440,height:1000});
  const api=await setup(page,locale,{upstreamNodeTest:true}),original=structuredClone(api.graph());
  await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
  await expect(page.locator('app-flow-node')).toHaveCount(3);
  await page.locator('app-flow-node').filter({hasText:'Préparation SAV'}).click();
  await page.getByTestId('open-prep-workshop').click();
  const workshop=page.locator('app-flow-data-prep-workshop'),select=workshop.getByTestId('prep-preview-input-in');
  await expect(workshop.getByTestId('prep-preview')).toBeDisabled();
  await expect(workshop.getByTestId('prep-sql')).toBeDisabled();
  await expect(workshop.getByTestId('prep-preview-sources')).toHaveAttribute('open','');
  await select.selectOption('source-test-dataset');
  await expect(workshop.getByTestId('prep-preview-provenance')).toContainText('Source test · v9');
  await expect(workshop.getByTestId('prep-preview-provenance').getByRole('link')).toHaveAttribute('href',/\/runs\/published-run-123/);
  await expect(workshop.getByTestId('prep-input-in')).toHaveValue('');
  await expect(workshop.getByTestId('prep-convert-sql')).toBeDisabled();
  await workshop.getByTestId('prep-preview').click();
  await expect(workshop.locator('ck-data-table')).toContainText('Alice');
  expect(api.writes.find(write=>write.path==='/dataops/preview')!.body.inputs).toEqual({in:{dataset_id:'source-test-dataset'}});
  await workshop.getByTestId('prep-sql').click();
  await expect(workshop.getByTestId('prep-sql-result')).toBeVisible();
  expect(api.writes.find(write=>write.path==='/dataops/compile')!.body.inputs).toEqual({in:{dataset_id:'source-test-dataset'}});
  await workshop.getByTestId('prep-sql-result').getByRole('button',{name:locale==='fr'?'Fermer':'Close',exact:true}).click();
  await workshop.screenshot({path:info.outputPath(`temporary-preview-${locale}.png`)});
  // A changed sample source invalidates rows and SQL immediately. A response
  // from the former source must not repopulate the new selection.
  await select.selectOption('customers-v3');
  await expect(workshop.locator('ck-data-table')).toHaveCount(0);
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let observed!:()=>void;
  const received=new Promise<void>(resolve=>{observed=resolve;});
  await page.route('**/api/v1/dataops/preview',async route=>{
   observed();await gate;
   await route.fulfill({contentType:'application/json',body:JSON.stringify({rows:[{name:'stale row'}],schema:columns,sample:true})});
  });
  await workshop.getByTestId('prep-preview').click();await received;
  await select.selectOption('segments-v2');release();
  await expect(workshop.getByTestId('prep-preview')).toBeEnabled();
  await expect(workshop.locator('ck-data-table')).toHaveCount(0);
  await select.selectOption('');
  await expect(workshop.getByTestId('prep-preview')).toBeDisabled();
  await workshop.getByTestId('close-prep-workshop').click();
  await page.getByTestId('open-prep-workshop').click();
  await expect(select).toHaveValue('');
  await expect(workshop.getByTestId('prep-input-in')).toHaveValue('');
  await workshop.getByTestId('close-prep-workshop').click();
  await page.waitForTimeout(1500);
  expect(api.graph()).toEqual(original);
  expect(api.writes.filter(write=>/\/flow-draft$|\/publish$|\/node-runs$|\/executions$/.test(write.path))).toHaveLength(0);
 });
 for(const locale of ['fr','en'] as const)test(`${locale}: isolated source test feeds the visual workshop without pinning or saving the user draft`,async({page},info)=>{
  await page.setViewportSize({width:1600,height:1100});
  const api=await setup(page,locale,{upstreamNodeTest:true}),original=structuredClone(api.graph());
  await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
  await expect(page.locator('app-flow-node')).toHaveCount(3);
  await page.getByRole('button',{name:locale==='fr'?'Exploiter':'Operate',exact:true}).click();
  await page.getByRole('button',{name:locale==='fr'?"Basculer l'atelier d'essai local":'Toggle local Flow workbench'}).click();
  const workbench=page.locator('app-flow-workbench-panel');
  await workbench.getByRole('tab',{name:locale==='fr'?'Nœud':'Node',exact:true}).click();
  await page.locator('app-flow-node').filter({hasText:'Source SQL'}).click();
  await workbench.getByRole('textbox',{name:locale==='fr'?'Entrée manuelle (JSON)':'Manual input_ref (JSON)'}).fill('{}');
  await workbench.getByRole('checkbox').check();
  await workbench.getByRole('button',{name:locale==='fr'?'Exécuter le nœud sélectionné':'Run selected node'}).click();
  await expect(workbench.locator('.ck-workbench__result[data-status="completed"]')).toContainText('source-test-dataset');
  const execution=api.writes.find(write=>write.path.endsWith('/flow-workbench/node-runs'))!.body;
  expect(execution.node_id).toBe('sav.features');expect(execution.expected_flow_sha256).toBe(hash);
  expect(execution.acknowledge_real_side_effects).toBe(true);
  expect(execution.flow_definition.nodes.find((node:any)=>node.id==='user.draft')).toEqual(original.nodes.find((node:any)=>node.id==='user.draft'));
  await workbench.getByRole('button',{name:locale==='fr'?'Fermer l’atelier local':'Close local workbench'}).click();
  await page.locator('app-flow-node').filter({hasText:'Préparation SAV'}).click();
  await page.getByTestId('open-prep-workshop').click();
  const workshop=page.locator('app-flow-data-prep-workshop');
  await expect(workshop.getByTestId('prep-input-in')).toHaveValue('');
  await expect(workshop.locator('.dp-workshop-inputs')).toContainText(locale==='fr'?'Sortie du dernier test':'Last test output');
  await expect(workshop.locator('.dp-step')).toHaveCount(4);
  await workshop.getByTestId('prep-preview').click();
  await expect(workshop.locator('ck-data-table')).toContainText('Alice');
  const preview=api.writes.find(write=>write.path==='/dataops/preview')!.body;
  expect(preview.inputs).toEqual({in:{dataset_id:'source-test-dataset'}});
  expect(preview.spec.params.steps).toHaveLength(4);
  await expect(workshop.getByTestId('prep-input-in')).toHaveValue('');
  await workshop.screenshot({path:info.outputPath(`upstream-node-test-${locale}.png`)});
  await workshop.getByTestId('close-prep-workshop').click();
  await expect(page.locator('app-flow-node').filter({hasText:'Préparation utilisateur inachevée'})).toBeVisible();
  // Observe beyond the 1.2 s autosave debounce after both panels have closed.
  await page.waitForTimeout(1500);
  // Opening, previewing and closing only consume ephemeral evidence; the edge,
  // unpinned input, four steps and unfinished user node remain byte-for-byte.
  expect(api.graph()).toEqual(original);
  expect(api.writes.filter(write=>/\/flow-draft$|\/publish$/.test(write.path))).toHaveLength(0);
  expect(api.writes.filter(write=>write.path.endsWith('/flow-workbench/node-runs'))).toHaveLength(1);
  if(locale==='fr'){
   // A separate, deliberate local edit invalidates the evidence. Keep the
   // workbench hold open so this assertion never saves the changed draft.
   const operate=page.getByRole('button',{name:'Exploiter',exact:true});
   if(await operate.getAttribute('aria-expanded')!=='true')await operate.click();
   await page.getByRole('button',{name:"Basculer l'atelier d'essai local"}).click();
   await page.getByTestId('open-prep-workshop').click();
   await expect(workshop.locator('.dp-workshop-inputs')).toContainText('Sortie du dernier test');
   await workshop.getByTestId('prep-preview').click();
   await expect(workshop.locator('ck-data-table')).toContainText('Alice');
   const count=api.writes.filter(write=>write.path==='/dataops/preview').length;
   await workshop.locator('.dp-step-name').first().click();
   await workshop.getByTestId('prep-step-comment').fill('Modification volontaire après le test');
   await expect(workshop.locator('ck-data-table')).toHaveCount(0);
   await expect(workshop.locator('.dp-workshop-inputs')).toContainText('Entrée du Flow indisponible');
   await expect(workshop.getByTestId('prep-preview')).toBeDisabled();
   expect(api.writes.filter(write=>write.path==='/dataops/preview')).toHaveLength(count);
   expect(api.writes.filter(write=>/\/flow-draft$|\/publish$/.test(write.path))).toHaveLength(0);
  }
 });
 for(const locale of ['fr','en'] as const)test(`${locale}: author five stable steps, preview, join pins and persist split edges`,async({page},info)=>{
  test.setTimeout(120000);await page.setViewportSize({width:1600,height:1000});const api=await setup(page,locale);await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();await expect(page.locator('app-flow-node')).toHaveCount(2);
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
  // Reload separated, unconnected fixture nodes so each real pointer gesture
  // creates an edge, independently of palette insertion's automatic wiring.
  api.graph().nodes.forEach((node:any)=>{const operation=node.config?.params?.spec?.operation;if(operation==='prepare')node.position={x:20,y:30};if(operation==='join')node.position={x:280,y:30};if(operation==='split')node.position={x:280,y:350};});
  api.graph().edges=[];
  await page.reload();await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();await expect(page.locator('app-flow-node')).toHaveCount(5);await connect(page,api,api.node('join').id,'out',api.node('split').id,'in');await connect(page,api,api.node('split').id,'train','sql-train','in');await connect(page,api,api.node('split').id,'test','sql-test','in');
  await expect.poll(()=>api.graph().edges.map((edge:any)=>[edge.from_port,edge.to_port])).toEqual(expect.arrayContaining([['out','in'],['train','in'],['test','in']]));expect(api.graph().edges.map((edge:any)=>[edge.from_port,edge.to_port])).toEqual(expect.arrayContaining([['out','in'],['train','in'],['test','in']]));
  expect(api.node('split').outputs.map((port:any)=>port.name)).toEqual(['train','test']);expect(api.node('prepare').config.params.spec.params.steps.map((step:any)=>step.id)).toEqual(steps.map((step:any)=>step.id));
  expect(api.writes.filter(write=>/\/runs$|\/publish$|\/executions$/.test(write.path))).toHaveLength(0);await page.screenshot({path:info.outputPath(`data-prep-${locale}.png`),fullPage:true});
 });
});
