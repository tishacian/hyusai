import {test} from 'node:test';
import assert from 'node:assert/strict';
import {recordedTimeline,scoreValue} from './observability-chart.vm';
test('unknown and invalid metrics never become a zero or perfect score',()=>{for(const value of [null,undefined,NaN,Infinity,-1,101,'75'])assert.equal(scoreValue(value),null);assert.equal(scoreValue(0),0);assert.equal(scoreValue(100),100);});
test('timeline preserves parallel execution and does not add durations serially',()=>{const timeline=recordedTimeline([{id:'a',started_at:'2026-09-15T10:00:00Z',completed_at:'2026-09-15T10:00:04Z'},{id:'b',started_at:'2026-09-15T10:00:01Z',completed_at:'2026-09-15T10:00:03Z'}]);assert.equal(timeline.duration,4000);assert.equal(timeline.rows[1].left,25);assert.equal(timeline.rows[1].width,50);});
test('missing and reversed timestamps are not fabricated into intervals',()=>{assert.deepEqual(recordedTimeline([{latency_ms:50},{started_at:'bad',completed_at:'2026-09-15T10:00:00Z'},{started_at:'2026-09-15T10:00:05Z',completed_at:'2026-09-15T10:00:00Z'}]).rows,[]);});
