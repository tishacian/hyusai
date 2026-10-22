import { ChangeDetectionStrategy, Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivityApiService } from '../observability/activities/activity-api.service';
import { RunViewComponent } from './run-view.component';
import { RunExecutionViewComponent } from './run-execution-view.component';
import { runSection, runSectionLabels } from './run-sections';
/** Query switch preserves every existing investigation/builder parameter; it never mounts the draft builder. */
@Component({selector:'app-run-page',standalone:true,imports:[RouterLink,RunViewComponent,RunExecutionViewComponent],changeDetection:ChangeDetectionStrategy.OnPush,
 template:`
   <nav class="run-views" [attr.aria-label]="i18n.t('runs.detail.facets_aria')" data-testid="run-sections">
     <a [routerLink]="[]" [queryParams]="{view:null,facet:null,nodeId:null,activityId:null,attemptId:null,offset:null}" queryParamsHandling="merge" [attr.aria-current]="section()==='result' ? 'page' : null">{{ labels().result }}</a>
     <a [routerLink]="[]" [queryParams]="{view:enabled() ? 'flow' : null,facet:enabled() ? null : 'trace'}" queryParamsHandling="merge" [attr.aria-current]="section()==='execution' ? 'page' : null">{{ labels().execution }}</a>
     <a [routerLink]="[]" [queryParams]="{view:null,facet:'quality'}" queryParamsHandling="merge" [attr.aria-current]="section()==='quality' ? 'page' : null">{{ labels().quality }}</a>
     <a [routerLink]="[]" [queryParams]="{view:null,facet:'usage'}" queryParamsHandling="merge" [attr.aria-current]="section()==='usage' ? 'page' : null">{{ labels().usage }}</a>
   </nav>
   @if(section()==='execution' && (enabled() || flow())) {
     <nav class="run-execution-views" [attr.aria-label]="labels().execution">
       <a [routerLink]="[]" [queryParams]="{view:'flow',facet:null}" queryParamsHandling="merge" [attr.aria-current]="flow() ? 'page' : null">{{ labels().flow }}</a>
       <a [routerLink]="[]" [queryParams]="{view:null,facet:'trace'}" queryParamsHandling="merge" [attr.aria-current]="!flow() ? 'page' : null">{{ labels().timeline }}</a>
     </nav>
   }
   @if(flow()) {<app-run-execution-view />} @else {<app-run-view />}`,
 styles:`:host{display:block;min-width:0}.run-views,.run-execution-views{display:flex;flex-wrap:wrap;align-items:center;gap:4px;padding:12px clamp(12px,3vw,32px);color:var(--ck-fg-2);font-size:13px}.run-views{border-bottom:1px solid var(--ck-stroke-2)}.run-views a,.run-execution-views a{padding:8px 12px;border-radius:4px;text-decoration:none}.run-views a[aria-current=page]{color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);box-shadow:inset 0 -2px var(--ck-signal-cool)}.run-execution-views{padding-block:8px;font-size:12px}.run-execution-views a[aria-current=page]{color:var(--ck-signal-cool);text-decoration:underline;text-underline-offset:5px}.run-views a:hover,.run-execution-views a:hover{background:var(--ck-bg-panel)}a:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:2px}@media(max-width:480px){.run-views{gap:0}.run-views a{padding:8px;font-size:12px}}`})
export class RunPageComponent implements OnDestroy {
 readonly i18n=inject(I18nService);private readonly route=inject(ActivatedRoute);private readonly api=inject(ActivityApiService);private readonly workspace=inject(WorkspaceService);private readonly auth=inject(AuthStore);
 readonly flow=signal(false);readonly facet=signal<string|null>(null);readonly enabled=signal(false);readonly section=computed(()=>runSection(this.flow() ? 'flow' : null,this.facet()));readonly labels=computed(()=>runSectionLabels(this.i18n.locale()));private readonly subscription:Subscription;private resets:Array<()=>void>=[];private generation=0;private destroyed=false;
 constructor(){this.subscription=this.route.queryParamMap.subscribe(params=>{this.flow.set(params.get('view')==='flow');this.facet.set(params.get('facet'));});this.resets.push(this.workspace.registerContextReset(()=>{this.generation++;this.enabled.set(false);queueMicrotask(()=>void this.discover());}));this.resets.push(this.auth.registerContextReset(()=>{this.generation++;this.enabled.set(false);}));void this.discover();}
 private async discover(){const generation=++this.generation;try{const features=await this.api.features();if(!this.destroyed&&generation===this.generation)this.enabled.set(!!features.execution_view_enabled);}catch{if(generation===this.generation)this.enabled.set(false);}}
 ngOnDestroy(){this.destroyed=true;this.generation++;this.subscription.unsubscribe();this.resets.forEach(reset=>reset());}
}
