import assert from 'node:assert/strict';
import { test } from 'node:test';
import { projectTimeseries, timeseriesMapping } from './timeseries';

test('observations and forecasts align by timestamp with honest gaps and uncertainty', () => {
  const result = projectTimeseries([
    {ds:'2026-10-02',forecast:12,lower:9,upper:14},
    {ds:'2026-10-01',actual:8}, {ds:'2026-10-02',actual:11},
    {ds:'2026-10-03',forecast:'13'},
  ], {});
  assert.equal(result.groups.length, 1);
  assert.deepEqual(result.groups[0].series.actual, [8,11,null]);
  assert.deepEqual(result.groups[0].series.pred, [null,12,13]);
  assert.deepEqual(result.groups[0].series.lower, [null,9,null]);
  assert.equal(result.duplicate,0);
});
test('invalid numbers, dates, reversed and one-sided intervals never draw manufactured zeroes', () => {
  const result=projectTimeseries([{ds:'garbage',forecast:1},{ds:'2026-10-01',forecast:true},{ds:'2026-10-01',forecast:'   '},{ds:'2026-10-02',forecast:4,lower:8,upper:3},{ds:'2026-10-03',forecast:4,lower:2}],{});
  assert.equal(result.invalid,3); assert.equal(result.invalidIntervals,2);
  assert.deepEqual(result.groups[0].series.lower,[null,null]);
});
test('column mappings support multiple independent series without flattening duplicate timestamps', () => {
  const result=projectTimeseries([{day:'2026-10-01',team:'A',qty:8},{day:'2026-10-01',team:'B',qty:9},{day:'2026-10-01',team:'A',qty:10}],{time:'day',value:'qty',series:'team'});
  assert.equal(result.groups.length,2); assert.equal(result.duplicate,1);
  assert.equal(result.groups[0].series.pred[0],8);
});
test('large result and group counts are bounded explicitly',()=>{
  const result=projectTimeseries(Array.from({length:1200},(_,i)=>({ds:'2026-10-01',forecast:i,series:String(i)})),{series:'series'});
  assert.equal(result.groups.length,12);assert.equal(result.omitted,1188);
  assert.equal(timeseriesMapping(null).time,'ds');
});
