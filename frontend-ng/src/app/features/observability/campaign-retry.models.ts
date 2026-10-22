import type { RunAssertionResult } from '@app/core/canonical-api.service';

export type CampaignSide = 'baseline' | 'candidate';
export interface CaseResult {
 run_id:string; status:string; termination?:string; quality_status?:string;
 controls?:Array<{invocation_id:string;evaluation_id:string;execution_status:string;quality_status:string}>;
 verdict:string; output_ref:unknown; duration_ms:number|null; execution_cost:number|null;
 assertions:RunAssertionResult[]; trajectory_assertions?:RunAssertionResult[];
 can_retry?:boolean; retry_blocked_reason?:string|null; retry_source_run_id?:string;
 attempts?:CampaignAttempt[];
}
export interface CampaignAttempt extends CaseResult {
 id:string; attempt_index:number; initial_run_id:string; source_run_id:string;
 job_id:string; created_at:string; actor_user_id:string; reason?:string|null;
}
export interface CampaignResult {case_id:string;change:string;result_key?:string;repetition_index?:number;baseline:CaseResult;candidate:CaseResult;}
export interface Campaign {
 id:string;status:string;method:string;created_at?:string;retry_pending?:boolean;
 snapshot:{comparability:string;limitations:unknown[]};results:CampaignResult[];
}
export interface CampaignRetryBody {result_key:string;side:CampaignSide;source_run_id:string;request_key:string;}

/** Retries are additional evidence. Never project them over the initial comparison. */
export function campaignPollingActive(campaign:Campaign):boolean {
 return ['queued','running'].includes(campaign.status) || campaign.retry_pending === true ||
  campaign.results.some(row=>[row.baseline,row.candidate].some(side=>side.attempts?.some(attempt=>['created','queued','pending','running','hitl_pending'].includes(attempt.status))));
}

export function retryTarget(campaignId:string,resultKey:string,side:CampaignSide):string {
 return JSON.stringify([campaignId,resultKey,side]);
}

/** A transport failure does not prove the write was rejected. Keep its identity. */
export class CampaignRetryRequests {
 private readonly pending=new Map<string,{body:CampaignRetryBody;active:boolean}>();
 begin(target:string,body:Omit<CampaignRetryBody,'request_key'>,newKey:()=>string):CampaignRetryBody|null {
  const previous=this.pending.get(target);
  if(previous?.active)return null;
  // A still-unknown request must be checked before another source can be retried.
  const request=previous?.body || {...body,request_key:newKey()};
  this.pending.set(target,{body:request,active:true});
  return request;
 }
 settle(target:string,unknown:boolean):void {
  const request=this.pending.get(target);
  if(unknown&&request)request.active=false;else this.pending.delete(target);
 }
 clear():void {this.pending.clear();}
}

export function campaignResponseCurrent(context:string,currentContext:string,id:string,currentId:string,responseId=id):boolean {
 return context===currentContext&&id===currentId&&responseId===id;
}
