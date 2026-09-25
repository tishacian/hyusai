import {ChangeDetectionStrategy,Component,computed,inject,input} from '@angular/core';
import {Router} from '@angular/router';
import {observabilityText,observabilityNumber} from '../observability/observability-labels';
import {I18nService} from '@app/core/i18n.service';
import {ZoomContextService} from '@app/core/zoom-context.service';
import type {Run} from '@app/core/canonical-api.service';
import {NavLinkDirective} from '@app/shared/cockpit';
import {recordedTimeline} from '../observability/observability-chart.vm';
import {arrivalProvenanceState} from './arrival-provenance';
import {longestTimelineRowIndex} from './run-trace.vm';

@Component({
  selector:'app-run-waterfall',
  standalone:true,
  imports:[NavLinkDirective],
  changeDetection:ChangeDetectionStrategy.OnPush,
  template:`<section class="waterfall" data-testid="run-waterfall"><header><h3>{{i18n.t('observability.charts.timeline')}}</h3><span>{{i18n.t('observability.charts.recorded_timing')}}</span></header>
 @if(timeline().rows.length){<div class="ruler"><span>0 s</span><span>{{seconds(timeline().duration)}} s</span></div>
  @for(row of timeline().rows;track row.inv.id || $index; let idx = $index){<div class="row" [class.longest]="highlightLongest() && idx === longestIndex()"><div class="name">@if(row.inv.id && fromTraceId()){<button type="button" class="skill-link" (click)="openFromTrace(row.inv.id!)">{{row.inv.skill_slug || row.inv.skill_id || row.inv.id}}</button>}@else if(row.inv.id){<a [navLink]="{type:'skill_invocation',ref:row.inv.id}">{{row.inv.skill_slug || row.inv.skill_id || row.inv.id}}</a>}@else {<span>{{row.inv.skill_slug || row.inv.skill_id}}</span>}</div><div class="track"><div class="bar" [class.failed]="row.inv.status==='failed'" [class.longest]="highlightLongest() && idx === longestIndex()" [style.left.%]="row.left" [style.width.%]="row.width" [title]="status(row.inv.status)"></div></div><div class="duration">{{seconds(row.duration)}} s</div></div>}
 } @else {<p>{{i18n.t('observability.charts.no_timing')}}</p>}
 </section>`,
  styles:[`.waterfall{padding:24px 0;color:var(--ck-fg-1)}header{display:flex;justify-content:space-between;gap:20px;align-items:baseline;margin-bottom:20px}h3{font-size:18px;font-weight:600}header span{font-size:12px;color:var(--ck-fg-3)}.ruler{display:flex;justify-content:space-between;margin:0 88px 12px 210px;font-size:12px;color:var(--ck-fg-3)}.row{display:grid;grid-template-columns:190px minmax(100px,1fr) 68px;gap:20px;align-items:center;min-height:42px}.name{font-size:13px;overflow-wrap:anywhere}.track{height:24px;position:relative;background:var(--ck-bg-inset);border-radius:3px}.bar{height:24px;position:absolute;min-width:2px;background:var(--ck-signal-cool);border-radius:3px}.bar.failed{background:var(--ck-signal-neg)}.bar.longest:not(.failed){background:var(--ck-copper)}.row.longest .name{color:var(--ck-copper)}.duration{text-align:right;font-variant-numeric:tabular-nums;font-size:13px}a,.skill-link{color:var(--ck-signal-cool);background:none;border:0;padding:0;font:inherit;cursor:pointer;text-decoration:underline;text-underline-offset:2px}@media(max-width:650px){.row{grid-template-columns:105px minmax(80px,1fr) 48px;gap:10px}.ruler{margin-left:115px;margin-right:58px}header{display:block}}`]
})
export class RunWaterfallComponent{
  seconds(ms:number):string{return observabilityNumber(ms/1000,this.i18n.locale(),2);}
  status(value:unknown):string{return observabilityText(this.i18n,'status',value);}
  readonly run=input.required<Run>();
  /** Mark the longest span in copper (Trace page). */
  readonly highlightLongest=input(false);
  /** When set, skill opens carry « Depuis la trace {id} » provenance. */
  readonly fromTraceId=input<string | null>(null);
  readonly i18n=inject(I18nService);
  private readonly router=inject(Router);
  private readonly navigation=inject(ZoomContextService);
  readonly timeline=computed(()=>recordedTimeline(this.run().skill_invocations || []));
  readonly longestIndex=computed(()=>longestTimelineRowIndex(this.timeline().rows));

  openFromTrace(invocationId: string): void {
    const runId = this.fromTraceId() || this.run().id;
    void this.router.navigateByUrl(
      this.navigation.objectUrl('skill_invocation', invocationId, { runId }),
      {
        state: arrivalProvenanceState({
          kind: 'trace',
          traceId: runId,
          backUrl: `/runs/${encodeURIComponent(runId)}?facet=trace`,
        }),
      },
    );
  }
}
