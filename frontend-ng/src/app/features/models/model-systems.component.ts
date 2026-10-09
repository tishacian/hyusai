import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal, untracked } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import type { SystemAgent } from '../systems/systems.store';

/** Published lineage references are navigation evidence, not exclusive ownership. */
@Component({
  selector: 'ck-model-systems', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush, imports: [NavLinkDirective],
  template: `
    <section data-testid="model-systems">
      <h4>{{ i18n.t('models.systems.title') }}</h4>
      <p>{{ i18n.t('models.systems.hint') }}</p>
      @if (loading()) { <p role="status">{{ i18n.t('models.systems.loading') }}</p> }
      @else if (failed()) {
        <p role="status">{{ i18n.t('models.systems.unavailable') }}</p>
        <button type="button" class="ck-btn ck-btn--sm ck-btn-quiet" (click)="reload()">{{ i18n.t('common.retry') }}</button>
      } @else {
        @if (!systems().length) { <p>{{ i18n.t('models.systems.empty') }}</p> }
        @for (system of systems(); track system.id) {
          <div class="consumer">
            <a [navLink]="{leaf:'system-flow', ref:system.id}" data-testid="model-consumer-flow">{{ system.name }}</a>
            <span>
              @for (reference of system.model_references; track $index) {
                <span class="reference">{{ reference.node_id }} · {{ reference.binding === 'champion' ? i18n.t('models.systems.champion') : i18n.t('models.systems.pinned', {version: reference.pinned_version ?? '—'}) }}</span>
              }
            </span>
          </div>
        }
        @if (hasMore()) { <p>{{ i18n.t('models.systems.more') }}</p> }
      }
    </section>
  `,
  styles: [`
    section{margin-top:16px}h4{font-size:13px;margin:0 0 8px}p,.reference{font-size:12px;color:var(--ck-fg-3);line-height:1.5}
    .consumer{display:flex;gap:16px;align-items:baseline;justify-content:space-between;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid var(--ck-stroke-1)}
    .reference{display:block}a{font-size:12px;color:var(--ck-signal-cool)}
  `],
})
export class ModelSystemsComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  readonly modelId = input.required<string>();
  readonly systems = signal<SystemAgent[]>([]);
  readonly loading = signal(false);
  readonly failed = signal(false);
  readonly hasMore = signal(false);
  private generation = 0;

  constructor() {
    effect(() => {
      this.modelId(); this.workspace.current()?.id;
      untracked(() => { void this.reload(); });
    });
    this.destroy.onDestroy(() => { this.generation++; });
  }

  async reload(): Promise<void> {
    const id = this.modelId(), generation = ++this.generation;
    const scope = this.workspace.captureRequestScope();
    const current = () => generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
    this.systems.set([]); this.loading.set(true); this.failed.set(false); this.hasMore.set(false);
    try {
      const response = await firstValueFrom(this.api.get<{systems: SystemAgent[]; has_more?: boolean}>(
        '/systems', {uses_model_id: id}, {workspaceSlug: scope.workspaceSlug},
      ));
      if (!current()) return;
      this.systems.set(response.systems); this.hasMore.set(response.has_more === true);
    } catch {
      if (current()) this.failed.set(true);
    } finally {
      if (current()) this.loading.set(false);
    }
  }
}
