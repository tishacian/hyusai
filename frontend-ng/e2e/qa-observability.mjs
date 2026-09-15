/** Local visual/interaction checks with synthetic API fixtures, not live evaluation evidence. */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
const base=process.env.BASE || 'http://127.0.0.1:4205';
const out=process.env.OUT || '../docs/ui/observability/screenshots';mkdirSync(out,{recursive:true});
const workspace={id:'ws-qa',slug:'showcase',name:'Showcase',role:'admin',role_template:'workspace_admin',mode:'builder',is_active:true,settings:{features:{adoption_experience_v1:true}}};
const user={id:'qa-user',username:'qa',email:'qa@example.test',role:'admin',roles:['admin','owner'],is_active:true,first_name:'QA',last_name:'Local',workspaces:[workspace]};
const evaluations=Array.from({length:20},(_,i)=>({id:'eval-'+i,run_id:'run-'+i,system_id:'northforge',created_at:new Date(Date.UTC(2026,8,15,8,i)).toISOString(),status:i===8?'failed':'completed',composite_score:i===8?null:i===9?42:83+i%12,scores:i===8?{}:{grounding:i===9?26:80+i%15,accuracy:i===9?52:86+i%9,completeness:89+i%10}})).reverse();
const run={id:'run-9',system_id:'northforge',status:'completed',started_at:'2026-09-15T08:00:00Z',completed_at:'2026-09-15T08:00:04Z',input_ref:{question:'Quelle est la pression nominale ?'},output_ref:{answer:'La pression nominale est de 8 bar.'},skill_invocations:[{id:'retrieve-1',skill_slug:'document_retrieval',status:'completed',started_at:'2026-09-15T08:00:00Z',completed_at:'2026-09-15T08:00:01Z'},{id:'answer-1',skill_slug:'northforge_summary',status:'completed',started_at:'2026-09-15T08:00:01Z',completed_at:'2026-09-15T08:00:04Z'}],checkpoints:[]};
const evaluation={evaluation_id:'eval-9',status:'completed',composite_score:42,claim_audit:{claims:[{claim:'8 bar',text:'8 bar',verdict:'contradicted',excerpt_ids:['1'],response_span:{start:27,end:32}}]},metadata:{method:'native_llm_judge',response_examined:'La pression nominale est de 8 bar.',excerpts:[{id:'1',text:'Pression nominale : 6 bar.',document_ref:'NorthForge — Fiche technique.pdf',page:2,invocation_id:'retrieve-1'}]}};
function response(path){
 if(/\/auth\/me|\/users\/me|\/me$/.test(path))return user;
 if(/\/workspaces\/?$/.test(path))return [workspace];
 if(/\/workspaces\/[^/]+\/?$/.test(path))return workspace;
 if(path.endsWith('/evaluation/history'))return {evaluations,total:20};
 if(path.endsWith('/evaluation/latest'))return {evaluation:evaluations[0]};
 if(path.endsWith('/evaluation/trend'))return {since:'7d',group_by:'day',thresholds:null,totals:{runs_evaluated:20,breaches:1,breach_rate:1/19,threshold_coverage:19,incomplete:1},series:[{bucket:'2026-09-15',count:20,avg_composite:86,observed_composite_count:19,observed_hallucination_count:0,avg_hallucination:null,breaches:1}]};
 if(path.endsWith('/evaluation/dimensions'))return {dimensions:{grounding:'Grounding',accuracy:'Accuracy',completeness:'Completeness'}};
 if(path.includes('/evaluation/component-health'))return {since:'7d',thresholds:null,totals:{evaluations:20,breaches:1},components:[],taxonomy:{components:{},question_types:{},question_type_components:{}}};
 if(path.endsWith('/evaluation/corrections'))return {corrections:[]};
 if(path.includes('/evaluation/by-run/'))return evaluation;
 if(path.endsWith('/runs/run-9'))return run;
 if(path.endsWith('/systems/northforge'))return {id:'northforge',name:'NorthForge',status:'active'};
 if(path.endsWith('/systems'))return [{id:'northforge',name:'NorthForge'}];
 if(/\/(skills|capabilities|runs|collections|sessions|presets|help)\/?$/.test(path))return [];
 return {items:[],results:[],total:0,count:0};
}
const browser=await chromium.launch();const report=[];
try{for(const theme of ['light','dark'])for(const locale of ['fr','en']){
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addInitScript(({theme,locale})=>{localStorage.setItem('agentium_token','Bearer qa-local-token');localStorage.setItem('agentium_workspace_slug','showcase');localStorage.setItem('agentium_theme',theme);localStorage.setItem('agentium_locale',locale);},{theme,locale});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response(new URL(route.request().url()).pathname))}));
 for(const [name,path,selector]of [['quality','/observability/quality','app-quality-evidence-charts'],['investigation','/runs/run-9','app-run-investigation']]){
  await page.goto(base+path,{waitUntil:'domcontentloaded'});await page.locator(selector).waitFor({timeout:20000});await page.waitForTimeout(300);
  if(name==='quality'){await page.locator('app-quality-evidence-charts .cell').first().click();if(!await page.locator('app-quality-evidence-charts .selection a').getAttribute('href'))throw Error('Missing Run link');}
  else {await page.locator('.claim').first().click();if(!await page.locator('.excerpt').textContent().then(t=>t.includes('6 bar')))throw Error('Source not linked');}
  if(name==='quality')await page.screenshot({path:`${out}/quality-overview-${theme}-${locale}.png`});
  await page.locator(selector).screenshot({path:`${out}/${name}-${theme}-${locale}.png`});
  report.push({name,theme,locale,url:page.url(),errors:[...errors],fixture:true});
 }
 await page.setViewportSize({width:390,height:844});await page.locator('app-run-investigation').screenshot({path:`${out}/investigation-mobile-${theme}-${locale}.png`});
 await context.close();
}}finally{await browser.close();writeFileSync(`${out}/visual-report.json`,JSON.stringify(report,null,2));}
if(report.some(r=>r.errors.length))throw Error(JSON.stringify(report));
console.log(`${report.length} desktop states + 4 narrow states passed (synthetic API fixtures).`);
