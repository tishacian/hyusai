import type { SkillInvocation } from '@app/core/canonical-api.service';
export function recordedTimeline(invocations:SkillInvocation[]){
 const timed=invocations.flatMap(inv=>{const start=Date.parse(inv.started_at || '');const end=Date.parse(inv.completed_at || inv.ended_at || '');return Number.isFinite(start)&&Number.isFinite(end)&&end>=start?[{inv,start,end}]:[];});
 if(!timed.length)return {rows:[],duration:0};
 const origin=Math.min(...timed.map(i=>i.start));const duration=Math.max(...timed.map(i=>i.end))-origin;
 return {duration,rows:timed.map(i=>({...i,left:duration?(i.start-origin)/duration*100:0,width:duration?(i.end-i.start)/duration*100:0,duration:i.end-i.start}))};
}
export function scoreValue(value:unknown):number|null {return typeof value==='number' && Number.isFinite(value) && value>=0 && value<=100 ? value : null;}
