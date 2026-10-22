import {expect, test, type Page, type Route} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({serviceWorkers:'block',video:'off'});
const workspace = {id:'typed-engine-qa',slug:'typed-engine-qa',name:'Typed engine QA',role:'owner',role_template:'workspace_owner',mode:'builder',settings:{features:{flow_publication_v1:true}},effective_features:{flow_publication_v1:true}};
const rubric = {rubric_id:'priority',rubric_version:'3',questions:[{key:'priority',question:'Is the request urgent?',type:'boolean',choices:[],required:true,requires_evidence:true,acceptable_values:[true]}],budget:{max_calls:1,max_tokens:10000,max_cost_usd:1,max_output_tokens:2048,timeout_s:45,max_prompt_bytes:32000},tariff:{provider:'openai',model:'gpt-5',input_per_million:1.25,output_per_million:10,currency:'USD',reference:'existing-price'}};
async function fixture(page:Page,locale:'fr'|'en') {
  const writes:string[]=[];
  const drafts:Array<Record<string,any>>=[];
  const graph={version:3,runtime_mode:'dag_overlay',nodes:[
    {id:'source',type:'source',kind:'source',label:'Request',position:{x:20,y:40},config:{},outputs:[{name:'out',schema:'object'}]},
    {id:'judge',type:'skill',kind:'task',label:'Quality gate',position:{x:330,y:40},config:{skill_slug:'evaluate_v2',typed_evaluation:structuredClone(rubric)},inputs:[{name:'in',schema:'object'}],outputs:[{name:'out',schema:'object'}]},
  ],edges:[{from:'source',from_port:'out',to:'judge',to_port:'in',kind:'data'}]};
  const system={id:'typed-engine-system',workspace_id:workspace.id,name:'Typed engine system',status:'active',flow_definition:graph,flow_sha256:'a'.repeat(64)};
  await page.route('**/*',route=>['localhost','127.0.0.1'].includes(new URL(route.request().url()).hostname)?route.fallback():route.abort());
  await page.addInitScript(({locale,slug})=>{localStorage.setItem('agentium_token','Bearer local-typed-engine');localStorage.setItem('agentium_workspace_slug',slug);localStorage.setItem('agentium_locale',locale);localStorage.setItem('agentium_theme',locale==='fr'?'dark':'light');},{locale,slug:workspace.slug});
  const json=(route:Route,body:unknown)=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  await page.route('**/api/v1/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace(/^\/api\/v1/,'');
    if(req.method()!=='GET')writes.push(path);
    if(path==='/auth/validate')return json(route,{valid:true,user_id:'qa-builder',role:'admin'});
    if(path==='/auth/me')return json(route,{id:'qa-builder',role:'admin',is_active:true,workspaces:[workspace]});
    if(path==='/auth/workspaces')return json(route,[workspace]);
    if(path==='/auth/workspaces/'+workspace.slug)return json(route,workspace);
    if(path==='/systems')return json(route,{systems:[system]});
    if(path==='/systems/'+system.id)return json(route,system);
    if(path==='/systems/'+system.id+'/flow-state')return json(route,{system_id:system.id,status:'active',draft:{revision:3,base_published_version_id:'flow-v10',flow_sha256:system.flow_sha256,flow_definition:graph},published:{version_id:'flow-v10',version_number:10,flow_sha256:system.flow_sha256,flow_definition:graph,execution_contract_ready:true}});
    if(path==='/systems/'+system.id+'/flow-draft'&&req.method()==='PUT') { const body=req.postDataJSON(); drafts.push(body); return json(route,{system_id:system.id,revision:4,base_published_version_id:'flow-v10',flow_sha256:'b'.repeat(64),flow_definition:body.flow_definition,updated_at:'2026-10-22T15:00:00Z'}); }
    if(path.endsWith('/validate-flow'))return json(route,{valid:true,issues:[],runtime_mode:'dag_overlay',flow_sha256:system.flow_sha256});
    if(path==='/skills')return json(route,{skills:[{id:'evaluate_v2',slug:'evaluate_v2',name:'Typed Evaluation',version:'2',type:'evaluation',category:'Analysis',runtime_status:'bound',input_schema:{type:'object',properties:{}},output_schema:{type:'object',properties:{}},visibility:{visible:true,reason:'visible',capabilities:[]}}]});
    if(path==='/models')return json(route,{models:[{provider:'openai',model:'gpt-5',configured:true,runtime_available:true,status:'active',discovered:true,compatibility:'text_generation'},{provider:'typesafe',model:'jev-latest',configured:true,runtime_available:false,typed_decisions_available:true,status:'active',discovered:true,compatibility:'typed_decisions'}]});
    if(path==='/runs')return json(route,{runs:[]});
    if(path==='/connectors')return json(route,{connectors:[],can_configure:true});
    if(path==='/documents/collections')return json(route,{collections:[]});
    return json(route,{});
  });
  return {writes,drafts};
}
for(const locale of ['fr','en'] as const) {
  test(`Flow engine selection preserves required evidence and invalidates the previous tariff (${locale})`,async({page},info)=>{
    const api=await fixture(page,locale);
    await page.setViewportSize({width:1440,height:1000});
    await page.goto('/systems/typed-engine-system/flow?lens=build');
    const node = page.locator('app-flow-node').filter({hasText:'Quality gate'});
    await expect(node).toBeVisible();
    const edit = page.getByRole('button',{name:/Edit draft|Modifier le brouillon/});
    if (await edit.isVisible()) await edit.click();
    await node.click();
    const editor=page.locator('app-typed-judge-editor');
    await expect(editor).toBeVisible();
    const engine=editor.getByRole('combobox',{name:locale==='fr'?'Moteur d’évaluation':'Evaluation engine',exact:true});
    await expect(engine).toHaveValue('openai:gpt-5');
    await engine.selectOption('typesafe:jev-latest');
    await expect(engine).toHaveValue('typesafe:jev-latest');
    await expect(editor.getByRole('checkbox',{name:locale==='fr'?'Preuve obligatoire':'Evidence required',exact:true})).toBeChecked();
    await expect(editor.getByRole('textbox',{name:locale==='fr'?'Référence du tarif':'Tariff reference',exact:true})).toHaveValue('');
    await expect(editor).toContainText(locale==='fr'?'Jev ne produit pas les citations exigées':'Jev cannot produce the citations');
    await expect(editor).toContainText(locale==='fr'?'Les plafonds monétaires prennent en charge Jev 1.13.0':'Monetary limits support Jev 1.13.0');
    await expect(editor).toContainText(locale==='fr'?'Les alias et les plafonds de tokens restent bloqués':'Aliases and token limits remain blocked');
    await expect(editor.getByRole('spinbutton',{name:locale==='fr'?'Réserve locale de tokens de sortie':'Local output token reservation',exact:true})).toHaveValue('2048');
    await expect(editor).toContainText(locale==='fr'?'l’API Jev ne garantit pas de plafond':'the Jev API does not guarantee an output token cap');
    await editor.getByRole('textbox',{name:locale==='fr'?'Référence du tarif':'Tariff reference',exact:true}).fill('reviewed-alias-price');
    await editor.locator('summary').filter({hasText:locale==='fr'?'Réglages avancés':'Advanced settings'}).click();
    const explicit=editor.getByRole('textbox',{name:locale==='fr'?'Identifiant exact du modèle · typesafe':'Exact model identifier · typesafe',exact:true});
    await expect(explicit).toHaveValue('jev-latest');
    await explicit.fill('jev invalid');
    const apply=editor.getByRole('button',{name:locale==='fr'?'Utiliser cet identifiant':'Use this identifier',exact:true});
    await apply.click();
    await expect(engine).toHaveValue('typesafe:jev-latest');
    await expect(editor.getByRole('alert')).toContainText(locale==='fr'?'sans espace':'without spaces');
    await explicit.fill('jev-1.13.0');
    await apply.click();
    await expect(engine).toHaveValue('typesafe:jev-1.13.0');
    await expect(engine.locator('option:checked')).toContainText(locale==='fr'?'disponibilité à vérifier':'availability unverified');
    await expect(editor).toContainText(locale==='fr'?'Le budget local de tokens doit couvrir 65 536':'The local token budget must cover 65,536');
    await expect(editor.getByRole('textbox',{name:locale==='fr'?'Référence du tarif':'Tariff reference',exact:true})).toHaveValue('');
    await expect(editor.getByRole('checkbox',{name:locale==='fr'?'Preuve obligatoire':'Evidence required',exact:true})).toBeChecked();
    expect((await new AxeBuilder({page}).include('app-typed-judge-editor').analyze()).violations).toEqual([]);
    await engine.scrollIntoViewIfNeeded();
    await page.screenshot({path:info.outputPath('jev-engine-'+locale+'.png')});
    await expect.poll(()=>api.drafts.at(-1)?.flow_definition.nodes.find((entry:any)=>entry.id==='judge').config.typed_evaluation.tariff.model).toBe('jev-1.13.0');
    const savedJudge=api.drafts.at(-1)!.flow_definition.nodes.find((entry:any)=>entry.id==='judge').config.typed_evaluation;
    expect(savedJudge.tariff).toMatchObject({provider:'typesafe',model:'jev-1.13.0',reference:'',input_per_million:0,output_per_million:0});
    expect(savedJudge.questions).toEqual(rubric.questions);
    expect(api.writes.filter(path=>!path.endsWith('/validate-flow')&&!path.endsWith('/flow-draft')&&!['/audit','/auth/validate'].includes(path)&&!path.includes('/navigation'))).toEqual([]);
  });
}
