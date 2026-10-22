export type FieldKind = 'string'|'number'|'boolean'|'null'|'json';
export interface TestInputField {key:string;type:FieldKind;value:string;}
export interface TestAssertionDraft {id:string;path:string;operator:'equals'|'contains'|'not_contains'|'exists'|'invocation_succeeded';type:FieldKind;value:string;}
export interface TrajectoryDraft {id:string;operator:'tool_required'|'tool_forbidden'|'before'|'max_calls'|'human_gate'|'no_business_effects';skill_slug?:string;before_skill?:string;after_skill?:string;limit?:number;severity:'critical'|'normal';}
export interface TestCaseDraft {id:string;question:string;reference_answer:string;reference_context:string;answer_path:string;answer_format:'text'|'json';output_path:string;fields:TestInputField[];trajectory_assertions:TrajectoryDraft[];assertions:TestAssertionDraft[];reviewed:boolean;expected_termination:'completed'|'human_gate'|'either';output_skill:string;output_node:string;tags:string[];family:string;critical:boolean;reference_run_id?:string;}
export function newTestCase(index:number):TestCaseDraft{return {id:`case-${index}`,question:'',reference_answer:'',reference_context:'',answer_path:'',answer_format:'text',output_path:'',fields:[{key:'question',type:'string',value:''}],assertions:[],trajectory_assertions:[],reviewed:false,expected_termination:'completed',output_skill:'',output_node:'',tags:[],family:'',critical:false};}
const reserved=new Set(['__proto__','prototype','constructor']);
export function fieldValue(field:Pick<TestInputField,'type'|'value'>):unknown{
 if(field.type==='number'){if(!field.value.trim()||!Number.isFinite(Number(field.value)))throw new Error('invalid_number');return Number(field.value);}
 if(field.type==='boolean'){if(!['true','false'].includes(field.value))throw new Error('invalid_boolean');return field.value==='true';}
 if(field.type==='null')return null;
 if(field.type==='json')return JSON.parse(field.value);
 return field.value;
}
function path(value:string):string[]{const segments=value.startsWith('[')?JSON.parse(value):value?value.split('.'):[];if(!Array.isArray(segments)||segments.length>12||segments.some(key=>typeof key!=='string'||!key.trim()||key!==key.trim()||reserved.has(key)))throw new Error('invalid_path');return segments;}
function editablePath(value:unknown):string{if(!Array.isArray(value))return '';if(value.some(key=>typeof key!=='string'))throw new Error('invalid_path');return value.some(key=>key.includes('.')||key.startsWith('['))?JSON.stringify(value):value.join('.');}
export function serializeTestCases(cases:readonly TestCaseDraft[]):Record<string,unknown>[] {
 if(!cases.length||cases.length>20||new Set(cases.map(row=>row.id.trim())).size!==cases.length)throw new Error('invalid_cases');
 return cases.map(row=>{
  if(!row.reviewed||!row.id.trim()||row.id.length>100||new Set(row.fields.map(field=>field.key)).size!==row.fields.length)throw new Error('unreviewed_case');
  const input_ref:Record<string,unknown>={};
  for(const field of row.fields){if(!field.key.trim()||field.key!==field.key.trim()||reserved.has(field.key))throw new Error('invalid_field');input_ref[field.key]=fieldValue(field);}
  const assertions=row.assertions.map((check,index)=>{const value=check.operator==='exists'?undefined:fieldValue(check);if(['contains','not_contains','invocation_succeeded'].includes(check.operator)&&(typeof value!=='string'||!value.trim()))throw new Error('invalid_assertion');return {id:check.id||`check-${index+1}`,path:check.operator==='invocation_succeeded'?[]:path(check.path),operator:check.operator,...(check.operator==='exists'?{}:{value})};});
  if(new Set(assertions.map(check=>check.id)).size!==assertions.length)throw new Error('duplicate_assertion');
  if(row.trajectory_assertions.length>30||new Set(row.trajectory_assertions.map(check=>check.id)).size!==row.trajectory_assertions.length)throw new Error('invalid_trajectory');
  const trajectory_assertions=row.trajectory_assertions.map(check=>{
   if(!check.id.trim()||!['tool_required','tool_forbidden','before','max_calls','human_gate','no_business_effects'].includes(check.operator))throw new Error('invalid_trajectory');
   if(['tool_required','tool_forbidden'].includes(check.operator)&&!check.skill_slug?.trim())throw new Error('missing_tool');
   if(check.operator==='before'&&(!check.before_skill?.trim()||!check.after_skill?.trim()))throw new Error('missing_order');
   if(check.operator==='max_calls'&&(!Number.isInteger(check.limit)||check.limit!<0||check.limit!>500))throw new Error('invalid_limit');
   return {id:check.id,operator:check.operator,severity:check.severity,...(['tool_required','tool_forbidden','max_calls'].includes(check.operator)&&check.skill_slug?{skill_slug:check.skill_slug.trim()}:{}),...(check.operator==='before'?{before_skill:check.before_skill?.trim(),after_skill:check.after_skill?.trim()}:{}),...(check.operator==='max_calls'?{limit:check.limit}:{})};
  });
  return {id:row.id.trim(),input_ref,assertions,question:row.question||undefined,reference_answer:row.reference_answer||undefined,reference_context:row.reference_context||undefined,answer_path:path(row.answer_path),answer_format:row.answer_format,expected_termination:row.expected_termination,case_family:row.family||undefined,severity:row.critical?'critical':'normal',tags:[...row.tags],trajectory_assertions,...(row.output_skill?{output_selector:{skill_slug:row.output_skill.trim(),...(row.output_node?{node_id:row.output_node}:{}),path:path(row.output_path)}}:{}),...(row.reference_run_id?{reference_run_id:row.reference_run_id}:{})};
 });
}
/** Import preserves structured input values; imported or generated cases always need a fresh review. */
export function editTestCase(value:unknown,index:number):TestCaseDraft {
 if(!value||typeof value!=='object')throw new Error('invalid_case');const row=value as Record<string,unknown>;const result=newTestCase(index);const inputs=row['input_ref'];
 if(!inputs||typeof inputs!=='object'||Array.isArray(inputs))throw new Error('invalid_input');
 result.id=typeof row['id']==='string'?row['id']:result.id;
 for(const key of ['question','reference_answer','reference_context'] as const)result[key]=typeof row[key]==='string'?row[key]:'';
 result.answer_path=editablePath(row['answer_path']);result.answer_format=row['answer_format']==='json'?'json':'text';
 result.fields=Object.entries(inputs).map(([key,value])=>({key,type:value===null?'null':typeof value==='number'?'number':typeof value==='boolean'?'boolean':typeof value==='string'?'string':'json',value:typeof value==='string'?value:JSON.stringify(value)}));
 result.expected_termination=['human_gate','either'].includes(String(row['expected_termination']))?row['expected_termination'] as 'human_gate'|'either':'completed';result.critical=row['severity']==='critical';result.family=typeof row['case_family']==='string'?row['case_family']:'';
 const output=row['output_selector'] as {skill_slug?:string;node_id?:string;path?:string[]}|undefined;result.output_skill=output?.skill_slug||'';result.output_node=output?.node_id||'';result.tags=Array.isArray(row['tags'])?row['tags'].filter((value):value is string=>typeof value==='string'):[];result.output_path=editablePath(output?.path);
 if(Array.isArray(row['trajectory_assertions']))result.trajectory_assertions=row['trajectory_assertions'].map(check=>({...check as TrajectoryDraft}));
 if(typeof row['reference_run_id']==='string')result.reference_run_id=row['reference_run_id'];
 if(Array.isArray(row['assertions']))result.assertions=row['assertions'].map((raw,index)=>{const check=raw as Record<string,unknown>;if(!['equals','contains','not_contains','exists','invocation_succeeded'].includes(String(check['operator'])))throw new Error('unsupported_assertion');const value=check['value'];return {id:typeof check['id']==='string'?check['id']:`check-${index+1}`,path:editablePath(check['path']),operator:check['operator'] as TestAssertionDraft['operator'],type:typeof value==='number'?'number':typeof value==='boolean'?'boolean':value===null?'null':typeof value==='object'?'json':'string',value:typeof value==='string'?value:value===undefined?'':JSON.stringify(value)};});
 return result;
}
/** Answers are data, not HTML. Structured outputs are reduced to readable scalar fields. */
export function readableOutput(value:unknown):string {
 if(typeof value==='string')return value.slice(0,16000);if(value==null)return '';if(typeof value!=='object')return String(value);
 const row=value as Record<string,unknown>;for(const key of ['answer','summary','response','text','proposal'])if(typeof row[key]==='string')return String(row[key]).slice(0,16000);
 return Object.entries(row).filter(([,entry])=>entry!=null&&typeof entry!=='object').slice(0,20).map(([key,entry])=>`${key.replace(/_/g,' ')}: ${entry}`).join('\n').slice(0,16000);
}
