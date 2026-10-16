import { ChangeDetectionStrategy, Component, OnDestroy, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivityApiService } from '../observability/activities/activity-api.service';
import { RunViewComponent } from './run-view.component';
import { RunExecutionViewComponent } from './run-execution-view.component';
/** Query switch preserves every existing investigation/builder parameter; it never mounts the draft builder. */
@Component({selector:'app-run-page',standalone:true,imports:[RouterLink,RunViewComponent,RunExecutionViewComponent],changeDetection:ChangeDetectionStrategy.OnPush,
 template:`@if(enabled() || flow()) { <nav class="run-views" [attr.aria-label]="i18n.t('runs.detail.facets_aria')"><a [routerLink]="[]" [queryParams]="{view:null,nodeId:null,activityId:null,attemptId:null,offset:null}" queryParamsHandling="merge" [attr.aria-current]="!flow() ? 'page' : null">{{ i18n.t('observability.flow.detail') }}</a><a [routerLink]="[]" [queryParams]="{view:'flow'}" queryParamsHandling="merge" [attr.aria-current]="flow() ? 'page' : null">{{ i18n.t('observability.flow.open') }}</a></nav> } @if(flow()) {<app-run-execution-view />} @else {<app-run-view />}`,
 styles:`.run-views{display:flex;flex-wrap:wrap;gap:16px;padding:16px 24px;color:var(--ck-fg-2);font-size:13px}.run-views a[aria-current=page]{color:var(--ck-signal-cool);text-decoration:underline}`})
export class RunPageComponent implements OnDestroy {
 readonly i18n=inject(I18nService);private readonly route=inject(ActivatedRoute);private readonly api=inject(ActivityApiService);private readonly workspace=inject(WorkspaceService);private readonly auth=inject(AuthStore);
 readonly flow=signal(false);readonly enabled=signal(false);private readonly subscription:Subscription;private resets:Array<()=>void>=[];private generation=0;private destroyed=false;
 constructor(){this.subscription=this.route.queryParamMap.subscribe(params=>this.flow.set(params.get('view')==='flow'));this.resets.push(this.workspace.registerContextReset(()=>{this.generation++;this.enabled.set(false);queueMicrotask(()=>void this.discover());}));this.resets.push(this.auth.registerContextReset(()=>{this.generation++;this.enabled.set(false);}));void this.discover();}
 private async discover(){const generation=++this.generation;try{const features=await this.api.features();if(!this.destroyed&&generation===this.generation)this.enabled.set(!!features.execution_view_enabled);}catch{if(generation===this.generation)this.enabled.set(false);}}
 ngOnDestroy(){this.destroyed=true;this.generation++;this.subscription.unsubscribe();this.resets.forEach(reset=>reset());}
}
