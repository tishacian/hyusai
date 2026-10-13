import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { DATAOPS_FR, DATAOPS_EN } from '@app/core/i18n/dataops.dict';
import { PREP_STEP_GROUPS } from './flow-data-prep.vm';
const source=(file:string)=>readFileSync('src/app/'+file,'utf8');
test('the workshop exposes the shared table, named pins, stable step actions and sample scope',()=>{
 const body=source('features/orchestration/flow/flow-data-prep-workshop.component.ts');for(const contract of ['ck-data-table','cdkDropList','track step.id','maxlength="500"','prep-step-enabled','prep-preview','sample_info','schema_diff','PrepHistory','PREP_WRITE_DEBOUNCE'])assert.ok(body.includes(contract),contract);
 assert.ok(source('features/orchestration/flow/flow-dataops-inspector.component.ts').includes("surfaceFeatureEnabled('data-preparation')"));
 assert.ok(source('features/data/prep-formula.component.ts').includes('<ck-code-editor language="sql"'));
});
test('every displayed catalogue step and workshop group has FR and EN copy',()=>{
 for(const [group,steps]of Object.entries(PREP_STEP_GROUPS)){for(const key of ['dataops.group.'+group,...steps.map(step=>'dataops.step.'+step)]){assert.ok((DATAOPS_FR as Record<string,string>)[key],key);assert.ok((DATAOPS_EN as Record<string,string>)[key],key);}}
 assert.notEqual(DATAOPS_FR['dataops.operation.join'],'Join');assert.equal(DATAOPS_EN['dataops.operation.join'],'Join tables');
});

test('the real catalogue fixture has translated normative labels and field descriptors',()=>{
 const catalog=JSON.parse(readFileSync('e2e/fixtures/dataops-catalog.json','utf8'));
 const source=readFileSync('src/app/core/i18n/flow.dict.ts','utf8');
 for(const definition of catalog.step_definitions){assert.ok(Object.values(PREP_STEP_GROUPS).flat().includes(definition.kind),definition.kind);for(const key of [definition.label_key,...definition.fields.map((field:any)=>field.label_key)])assert.equal(source.split(JSON.stringify(key)+':').length-1,2,key);}
 for(const fn of catalog.functions)assert.equal(source.split(JSON.stringify(fn.label_key)+':').length-1,2,fn.label_key);
});
