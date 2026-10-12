import {test} from 'node:test';
import assert from 'node:assert/strict';
import {benchMetric,ratioPercent,shortSha,type PublicBenchRun} from './public-bench.vm';
import {OBSERVABILITY_EN,OBSERVABILITY_FR} from '../../core/i18n/observability.dict';

const run=(id:string,status:string,recall:number|null):PublicBenchRun=>({id,status,k:10,case_count:200,error_count:0,recall_at_k:recall,supporting_fact_rate:recall});

test('unmeasured ratios never render as zero',()=>{for(const value of [null,undefined,NaN,-0.1,1.2,'0.5'])assert.equal(ratioPercent(value),null);assert.equal(ratioPercent(0),0);assert.equal(ratioPercent(0.8234),82.3);});
test('delta compares the two latest completed runs and skips failed ones',()=>{const metric=benchMetric([run('c','failed',null),run('b','completed',0.8),run('a','completed',0.75)],'recall_at_k');assert.deepEqual(metric,{value:80,delta:5});});
test('a single run has no delta and no runs no value',()=>{assert.deepEqual(benchMetric([run('a','completed',0.5)],'recall_at_k'),{value:50,delta:null});assert.deepEqual(benchMetric([],'supporting_fact_rate'),{value:null,delta:null});});
test('only git shas are shortened',()=>{assert.equal(shortSha('0123456789abcdef0123456789abcdef01234567'),'0123456789ab');assert.equal(shortSha('development'),'—');assert.equal(shortSha(null),'—');});
test('public bench labels exist in both languages',()=>{const keys=Object.keys(OBSERVABILITY_FR).filter(k=>k.startsWith('observability.bench.'));assert.ok(keys.length>=8);for(const key of keys)assert.ok((OBSERVABILITY_EN as Record<string,string>)[key]);});
