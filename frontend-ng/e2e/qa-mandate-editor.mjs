/** Real compiled editor, synthetic API fixtures; no production execution claimed. */
import assert from 'node:assert/strict';
import {chromium, expect} from '@playwright/test';
import {mkdirSync, writeFileSync} from 'node:fs';
const base = process.env.BASE ?? 'http://localhost:4200';
const out = process.env.OUT ?? '../docs/reports/mandate-experience/editor-qa';
mkdirSync(out, {recursive:true});
const workspace = {id:'ws-qa',slug:'showcase',name:'Showcase',role:'admin',role_template:'workspace_admin',mode:'builder',is_active:true,settings:{features:{adoption_experience_v1:true,flow_publication_v1:true}}};
const user = {id:'qa-user',username:'qa',email:'qa@example.test',role:'admin',roles:['admin','owner'],is_active:true,workspaces:[workspace]};
const system = {id:'northforge',workspace_id:workspace.id,name:'NorthForge · Préparation d’intervention',status:'active',settings:{},flow_definition:{nodes:[],edges:[]}};
const spec = {version:2,enforcement_mode:'enforce',inbound:{collection_allowlist:['northforge-manuals','northforge-history'],reject_cross_project_sources:true},outbound:{expert_review_required:true,gate_if_confidence_below:.75},capabilities:{allowed_skills:['document_retrieval','intervention_analysis'],allowed_models:['gpt-4.1'],allowed_actions:['system.engine.run'],allowed_delegations:[]},provenance:{require_citations:true},valves:{max_cost_per_decision:.2,max_latency_ms:60000,token_budget:12000,hard_abort:true}};
const checks = valid => ({valid,checks:['mandate_schema','workspace_resources','flow_contract','provider_availability','runtime_tests'].map(code=>({code,status:valid&&!['runtime_tests','provider_availability'].includes(code)?'passed':'not_run'}))});
const initial = () => ({system_id:system.id,permissions:{can_edit:true},draft:{revision:4,flow_sha256:'flow-qa',spec:structuredClone(spec),base_published_version_id:'published-3',snapshot_sha256:'a'.repeat(64),policy_binding:'frozen'},published:{version_id:'published-3',version_number:3,spec:structuredClone(spec),policy_revision:'policy-3',snapshot_sha256:'a'.repeat(64),policy_binding:'frozen'},options:{collections:[{id:'northforge-manuals',label:'NorthForge · Notices NF-04'},{id:'northforge-history',label:'Historique des interventions'}],skills:[{id:'document_retrieval',label:'Recherche documentaire'},{id:'intervention_analysis',label:'Analyse des interventions'}],models:[{id:'gpt-4.1',label:'GPT-4.1'}],delegations:[]},validation:checks(false)});
const browser=await chromium.launch(process.env.E2E_CHROMIUM_EXECUTABLE?{executablePath:process.env.E2E_CHROMIUM_EXECUTABLE}:{});
const report=[];
try {
 for(const theme of ['light','dark']) for(const locale of ['fr','en']) {
  console.log(`Checking ${theme}/${locale}`);
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(({theme,locale})=>{localStorage.setItem('agentium_token','Bearer qa-local');localStorage.setItem('agentium_workspace_slug','showcase');localStorage.setItem('agentium_theme',theme);localStorage.setItem('agentium_locale',locale);},{theme,locale});
  const page=await context.newPage();const errors=[];let state=initial();let conflict=false;let writes=0;let published=0;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const req=route.request(),path=new URL(req.url()).pathname;let body={items:[],results:[],total:0};let status=200;
   if(/\/auth\/me|\/users\/me|\/me$/.test(path))body=user;
   else if(/\/workspaces\/?$/.test(path))body=[workspace];
   else if(/\/workspaces\/[^/]+\/?$/.test(path))body=workspace;
   else if(path.endsWith('/systems/northforge/mandate/draft/validate')){const value=req.postDataJSON();assert.equal(value.expected_revision,state.draft.revision);assert.equal(value.expected_snapshot_sha256,state.draft.snapshot_sha256);body=checks(true);}
   else if(path.endsWith('/systems/northforge/mandate/draft')){
    if(req.method()==='PUT'){
     writes++;const value=req.postDataJSON();assert.equal(value.expected_revision,state.draft.revision);assert.equal(value.expected_snapshot_sha256,state.draft.snapshot_sha256);
     if(conflict){status=409;body={detail:{code:'MANDATE_DRAFT_REVISION_MISMATCH'}};}
     else {state={...state,draft:{...state.draft,revision:state.draft.revision+1,spec:value.spec,snapshot_sha256:'b'.repeat(64)},validation:checks(false)};body=state;}
    }else body=state;
   }
   else if(path.endsWith('/systems/northforge/mandate'))body={system_id:system.id,system_name:system.name,configuration:{state:'explicit',mode:'enforce',version:2,spec,configured_facets:['inbound','outbound','capabilities','provenance','valves']},permissions:{can_edit:false},recent_runs:[],recent_runs_limit:8,limitations:[]};
   else if(path.endsWith('/systems/northforge/flow-state'))body={system_id:system.id,status:'active',draft:{revision:state.draft.revision,flow_sha256:'flow-qa',flow_definition:system.flow_definition},published:{version_id:'published-3',version_number:3,flow_sha256:'flow-qa',flow_definition:system.flow_definition}};
   else if(path.endsWith('/systems/northforge/flow/publish')){published++;throw new Error('Editor must never publish implicitly');}
   else if(path.endsWith('/systems/northforge'))body=system;
   else if(path.endsWith('/systems'))body=[system];
   else if(path.includes('/evaluation/latest'))body={evaluation:null};
   else if(path.endsWith('/documents/collections'))body={collections:[]};
   else if(/\/(skills|capabilities|collections|sessions|presets|help|apps|templates|models|contexts|connectors|runs)\/?$/.test(path))body=[];
   await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  const editor=page.locator('app-mandate-editor');
  const capture=async name=>{
   const text=await editor.innerText();assert.ok(!/mandate(?:_system)?\.[a-z_]+/.test(text),`Missing translation in ${name}`);
   const viewport=page.viewportSize();
   const bounds=await editor.evaluate(el=>({left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,height:el.getBoundingClientRect().height,viewport:innerWidth,scroll:el.scrollWidth,width:el.clientWidth}));
   assert.ok(bounds.left>=0&&bounds.right<=bounds.viewport+2&&bounds.scroll<=bounds.width+2,`Overflow ${JSON.stringify(bounds)}`);
   await page.setViewportSize({width:viewport.width,height:Math.ceil(bounds.height)+950});
   await page.locator('main').evaluateAll(els=>els.forEach(el=>el.scrollTo(0,0)));
   await editor.screenshot({path:`${out}/${name}-${theme}-${locale}.png`});
   await page.setViewportSize(viewport);
   report.push({name,theme,locale,url:page.url(),fixture:true,viewport,errors:[...errors]});
  };
  await page.goto(`${base}/systems/northforge?lens=build&facet=context`,{waitUntil:'domcontentloaded'});
  try { await editor.locator('#mandate-mode').waitFor({timeout:25000}); } catch(error) { console.log('UI state:', await page.locator('body').innerText(), errors); throw error; }
  await expect(editor.locator('#mandate-mode')).toHaveValue('enforce');
  await capture('editor-initial');
  const save=editor.getByRole('button',{name:locale==='fr'?'Enregistrer le mandat dans le draft':'Save mandate to draft',exact:true});
  const review=editor.locator('.reviewed input');
  await expect(save).toBeDisabled();
  await editor.locator('input[name=cost]').fill('0.12');
  await editor.locator('input[name=review_threshold]').fill('85');
  await expect(save).toBeDisabled();
  assert.ok((await editor.locator('.diff-list').innerText()).includes(locale==='fr'?'0,12':'0.12'));
  await review.check();await expect(save).toBeEnabled();
  await capture('editor-diff');
  await save.click();await editor.locator('.editor-saved').waitFor();
  assert.equal(writes,1);assert.equal(published,0);assert.equal(state.published.spec.valves.max_cost_per_decision,.2);assert.equal(state.draft.spec.valves.max_cost_per_decision,.12);
  await editor.getByRole('button',{name:locale==='fr'?'Valider le draft enregistré':'Validate saved draft',exact:true}).click();
  const publication=editor.getByRole('link',{name:locale==='fr'?'Relire et publier dans le Flow':'Review and publish in the Flow',exact:true});
  await publication.waitFor();assert.match(await publication.getAttribute('href'),/northforge/);
  await capture('editor-validated');
  await page.setViewportSize({width:390,height:844});await capture('editor-narrow');await page.setViewportSize({width:1440,height:1000});
  conflict=true;await editor.locator('input[name=cost]').fill('0.15');await review.check();await save.click();
  await editor.locator('.editor-error').waitFor();await expect(save).toBeDisabled();assert.equal(published,0);
  await capture('editor-conflict');
  assert.deepEqual(errors,[]);await context.close();
 }
 writeFileSync(`${out}/report.json`,JSON.stringify({generated_at:new Date().toISOString(),kind:'compiled UI + synthetic API fixtures',states:report.length,checks:report},null,2));
 console.log(`PASS ${report.length} editor states; reviewed save, CAS, validation, explicit publication handoff, conflict, FR/EN, light/dark, narrow.`);
}finally{await browser.close();}
