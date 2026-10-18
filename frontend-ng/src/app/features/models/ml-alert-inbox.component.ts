import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { WorkspaceService } from '@app/core/workspace.service';
import { EndpointsService } from './endpoints.service';
import { MLAlert } from './endpoints.vm';

@Component({
  selector: 'app-ml-alert-inbox', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, NavLinkDirective],
  template: `
    @if (enabled()) {
      <section class="ck-surface rounded p-4 my-4" data-testid="ml-alert-inbox">
        <h2><a class="underline" [navLink]="{ leaf: 'model-endpoints' }">{{ i18n.t('models.endpoints.alerts') }} ({{ total() }})</a></h2>
        @if (failed()) { <p role="status">{{ i18n.t('models.endpoints.error') }}</p> }
        @for (item of items(); track item.id) {
          <p class="mt-2"><a [navLink]="{ leaf: 'model-doc', ref: item.model_id }">{{ label(item.event) }}</a> · {{ item.state }} · {{ item.created_at | date:'short' }}</p>
        }
      </section>
    }
  `,
})
export class MLAlertInboxComponent implements OnInit {
  readonly i18n = inject(I18nService); private readonly api = inject(EndpointsService);
  readonly enabled = signal(false); readonly failed = signal(false);
  readonly total = signal(0); readonly items = signal<MLAlert[]>([]);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  private destroyed = false;
  constructor() {
    const unregister = this.workspace.registerContextReset(() => {
      this.enabled.set(false); this.failed.set(false); this.items.set([]); this.total.set(0);
      queueMicrotask(() => { if (!this.destroyed) void this.ngOnInit(); });
    });
    this.destroyRef.onDestroy(() => { this.destroyed = true; unregister(); });
  }
  async ngOnInit(): Promise<void> {
    const scope = this.workspace.captureRequestScope();
    const current = () => !this.destroyed && this.workspace.isRequestScopeCurrent(scope);
    try {
      const features = await this.api.features(); if (!current()) return;
      this.enabled.set(features.enabled);
      if (!this.enabled()) return;
      const result = await this.api.alerts('workspace', '');
      if (!current()) return;
      this.total.set(result.total); this.items.set(result.items.filter(item => !item.acknowledged_at).slice(0, 5));
    } catch { if (current()) this.failed.set(true); }
  }
  label(event: string): string {
    return this.i18n.t(event === 'monitor_transition' ? 'models.endpoints.transition' : event === 'monitor_failed' ? 'models.endpoints.monitor_failed' : event === 'key_expiring' ? 'models.endpoints.key_expiring' : event === 'fairness_gap' ? 'models.endpoints.fairness_gap' : 'models.endpoints.quota');
  }
}
