import {ChangeDetectionStrategy,Component,computed,inject,input} from '@angular/core';
import {observabilityText,observabilityNumber} from '../observability/observability-labels';
import {I18nService} from '@app/core/i18n.service';
import type {Run,SkillInvocation} from '@app/core/canonical-api.service';
import {NavLinkDirective} from '@app/shared/cockpit';
import { recordedTimeline } from '../observability/observability-chart.vm';
@Component({selector:'app-run-waterfall',standalone:true,imports:[NavLinkDirective],changeDetection:ChangeDetectionStrategy.OnPush,
 template:`<section class="waterfall"><header><h3>{{i18n.t('observability.charts.timeline')}}</h3><span>{{i18n.t('observability.charts.recorded_timing')}}</span></header>
 @if(timeline().rows.length){<div class="ruler"><span>0 s</span><span>{{seconds(timeline().duration)}} s</span></div>
  @for(row of timeline().rows;track row.inv.id || $index){<div class="row"><div class="name">@if(row.inv.id){<a [navLink]="{type:'skill_invocation',ref:row.inv.id}">{{row.inv.skill_slug || row.inv.skill_id || row.inv.id}}</a>}@else {<span>{{row.inv.skill_slug || row.inv.skill_id}}</span>}</div><div class="track"><div class="bar" [class.failed]="row.inv.status==='failed'" [style.left.%]="row.left" [style.width.%]="row.width" [title]="status(row.inv.status)"></div></div><div class="duration">{{seconds(row.duration)}} s</div></div>}
 } @else {<p>{{i18n.t('observability.charts.no_timing')}}</p>}
 </section>`,
 styles:[`.waterfall{padding:24px 0;color:var(--ck-fg-1)}header{display:flex;justify-content:space-between;gap:20px;align-items:baseline;margin-bottom:20px}h3{font-size:18px;font-weight:600}header span{font-size:12px;color:var(--ck-fg-3)}.ruler{display:flex;justify-content:space-between;margin:0 88px 12px 210px;font-size:12px;color:var(--ck-fg-3)}.row{display:grid;grid-template-columns:190px minmax(100px,1fr) 68px;gap:20px;align-items:center;min-height:42px}.name{font-size:13px;overflow-wrap:anywhere}.track{height:24px;position:relative;background:var(--ck-bg-inset);border-radius:3px}.bar{height:24px;position:absolute;min-width:2px;background:var(--ck-signal-cool);border-radius:3px}.bar.failed{background:var(--ck-signal-neg)}.duration{text-align:right;font-variant-numeric:tabular-nums;font-size:13px}a{color:var(--ck-signal-cool)}@media(max-width:650px){.row{grid-template-columns:105px minmax(80px,1fr) 48px;gap:10px}.ruler{margin-left:115px;margin-right:58px}header{display:block}}`]
})
export class RunWaterfallComponent{seconds(ms:number):string{return observabilityNumber(ms/1000,this.i18n.locale(),2);}status(value:unknown):string{return observabilityText(this.i18n,'status',value);}readonly run=input.required<Run>();readonly i18n=inject(I18nService);readonly timeline=computed(()=>recordedTimeline(this.run().skill_invocations || []));}
