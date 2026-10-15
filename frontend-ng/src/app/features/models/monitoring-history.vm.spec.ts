import assert from 'node:assert/strict';
import { test } from 'node:test';
import { monitoringDomain, monitoringSeries } from './monitoring-history.vm';
import { retrainingDataPolicy } from './retraining-evidence.vm';

test('historical metrics preserve chronology, gaps, zero and task units',()=>{
  const rows:any[]=[
    {id:'3',created_at:'2026-10-15T03:00:00',score_drift:{value:.3},concept_drift:{metrics:[{metric:'mae',value:4}]},data_drift:{features:[{name:'x',value:.2,test:{p_value_adjusted:0}}]}},
    {id:'1',created_at:'2026-10-15T01:00:00',score_drift:{value:0},concept_drift:{metrics:[{metric:'mae',value:2}]}},
    {id:'2',created_at:'2026-10-15T02:00:00',score_drift:{value:null},concept_drift:{rolling_auc:null}},
  ];
  const series=monitoringSeries(rows);
  assert.deepEqual(series.find(x=>x.key==='score')?.points,[{x:1,y:0},{x:3,y:.3}]);
  assert.deepEqual(series.find(x=>x.key==='concept:mae')?.points,[{x:1,y:2},{x:3,y:4}]);
  assert.deepEqual(series.find(x=>x.key==='p:x')?.points,[{x:3,y:0}]);
  assert.equal(series.some(x=>x.key==='concept:roc_auc'),false);
  assert.equal(series[0].dates[0],rows[1].created_at);
  assert.deepEqual(monitoringDomain([{x:2,y:4}]),{minX:1,maxX:2,minY:0,maxY:4});
});

test('retraining source policy validates caps and preserves an empty window as null',()=>{
  assert.deepEqual(retrainingDataPolicy('original_plus_feedback','25',''),{mode:'original_plus_feedback',max_feedback_fraction:.25,feedback_window_days:null});
  assert.equal(retrainingDataPolicy('feedback_only','100','30')?.feedback_window_days,30);
  for(const cap of ['','0','-1','101','NaN']) assert.equal(retrainingDataPolicy('original_plus_feedback',cap,''),null);
  for(const days of ['0','1.5','3651','NaN']) assert.equal(retrainingDataPolicy('feedback_only','25',days),null);
  assert.equal(retrainingDataPolicy('forged','25',''),null);
});
