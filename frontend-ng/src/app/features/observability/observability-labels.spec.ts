import {test} from 'node:test';
import assert from 'node:assert/strict';
import {OBSERVABILITY_FR, OBSERVABILITY_EN} from '../../core/i18n/observability.dict';
import {observabilityText, observabilityNumber} from './observability-labels';
import {formatSkillCost} from '../skills/skill-cost';
const translator = (dictionary: Record<string,string>) => ({t:(key:string)=>dictionary[key] ?? key});
test('pending, failure and unknown platform codes stay readable in both languages',()=>{
 for(const dictionary of [OBSERVABILITY_FR,OBSERVABILITY_EN]) {
  const i18n=translator(dictionary);
  for(const [category,code] of [['status','pending'],['status','failed'],['stage','generation_unavailable'],['verdict','contradicted'],['method','server_assertions'],['change','pending']]) {
   const label=observabilityText(i18n,category,code);
   assert.equal(label,dictionary[`observability.codes.${category}.${code}`]);
   assert.ok(!label.startsWith('observability.'));
  }
  for(const category of ['status','stage','reason','method','verdict','dimension','change','comparability','limitation']) {
   assert.equal(observabilityText(i18n,category,'future_server_code'),dictionary[`observability.codes.${category}.unknown`]);
  }
 }
 assert.notEqual(observabilityText(translator(OBSERVABILITY_FR),'status','pending'),observabilityText(translator(OBSERVABILITY_EN),'status','pending'));
});
test('legacy server errors and limitations resolve without displaying English as French primary copy',()=>{
 const fr=translator(OBSERVABILITY_FR);
 assert.equal(observabilityText(fr,'reason','Draft changed; review it again'),OBSERVABILITY_FR['observability.codes.reason.draft_changed']);
 assert.equal(observabilityText(fr,'limitation','Corpus changed or became unavailable during the campaign.'),OBSERVABILITY_FR['observability.codes.limitation.corpus_changed']);
 assert.equal(observabilityText(fr,'reason',{detail:'unexpected'}),OBSERVABILITY_FR['observability.codes.reason.unknown']);
});
test('localized decimal and cost displays preserve missing, zero and positive tiny amounts',()=>{
 assert.equal(observabilityNumber(1.25,'fr',2),'1,25');
 assert.equal(observabilityNumber(1.25,'en',2),'1.25');
 assert.equal(observabilityNumber(null,'fr'),'—');
 assert.equal(observabilityNumber(NaN,'fr'),'—');
 assert.equal(observabilityNumber(0,'fr'),'0');
 assert.ok(formatSkillCost(1.25,'EUR','fr').includes('1,25'));
 assert.ok(formatSkillCost(0.00001,'EUR','fr').startsWith('< 0,0001'));
 assert.equal(formatSkillCost(null,'EUR','fr'),'—');
 assert.equal(formatSkillCost(1.25),'$1.25');
});
