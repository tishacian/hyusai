import assert from 'node:assert/strict';
import { test } from 'node:test';
import { executionGraphLayout, executionInterval, executionTimeline, type ExecutionItem } from './run-execution.models';
import { navigationRunFlowUrl } from '@app/core/navigation.catalog';
test('parallel branches have independent positions and cycles terminate without mutating a graph',()=>{
 const nodes=['fork','left','right','join'].map(id=>({id,kind:'skill',label:id})); const edges=[['fork','left'],['fork','right'],['left','join'],['right','join']].map(([source,target],i)=>({id:String(i),source,target,kind:'data',label:null}));
 const before=JSON.stringify({nodes,edges});const layout=executionGraphLayout(nodes,edges); assert.equal(layout[1].position.x,layout[2].position.x);assert.notEqual(layout[1].position.y,layout[2].position.y); assert.equal(JSON.stringify({nodes,edges}),before);
 assert.equal(executionGraphLayout(nodes,[...edges,{id:'loop',source:'join',target:'fork',kind:'control',label:null}]).length,4);
});
test('missing and inverted dates remain unavailable and parallel durations do not add',()=>{
 const start='2026-10-16T10:00:00Z',end='2026-10-16T10:00:10Z';const item={started_at:start,finished_at:end} as ExecutionItem;
 assert.deepEqual(executionInterval(item,start,end),{left:0,width:100});assert.deepEqual(executionInterval(item,start,end),{left:0,width:100});
 assert.equal(executionInterval({...item,finished_at:null},start,end),null);assert.equal(executionInterval({...item,finished_at:'2026-10-16T09:00:00Z'},start,end),null);
});
test('historical navigation never selects the draft builder and preserves explicit identity',()=>{
 const url=new URL(navigationRunFlowUrl('run-A',{nodeId:'n:1',activityId:'a:2',attemptId:'try3'}),'http://fixture');assert.equal(url.pathname,'/runs/run-A');assert.equal(url.searchParams.get('view'),'flow');assert.equal(url.searchParams.get('nodeId'),'n:1');assert.equal(url.searchParams.get('activityId'),'a:2');assert.equal(url.searchParams.get('attemptId'),'try3');
});

test('shared human review is shown once while failed and successful attempts retain their intervals',()=>{
 const human={id:'review-1',phase:'human',started_at:'2026-10-16T10:00:00Z',finished_at:'2026-10-16T10:01:00Z',coverage:'exact'};
 const items=['failed','succeeded'].map((status,i)=>({id:'attempt'+i,status,started_at:'2026-10-16T10:01:00Z',finished_at:'2026-10-16T10:01:01Z',coverage:'exact',passage_intervals:[human]}) as ExecutionItem);
 const timeline=executionTimeline(items);assert.equal(timeline.length,3);assert.equal(timeline.filter(entry=>entry.phase.phase==='human').length,1);assert.deepEqual(timeline.filter(entry=>entry.phase.phase==='execution').map(entry=>entry.item.status),['failed','succeeded']);
});
