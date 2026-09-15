import { ChangeDetectionStrategy, Component, Input, OnChanges, OnDestroy, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import type { ModelResolution } from '@app/core/model-catalog';
import { WorkspaceService } from '@app/core/workspace.service';
import type { I18nKey } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { ModelExecutionComponent } from '@app/shared/cockpit/model-execution.component';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';

/** Read the same binding on a Skill and on a Flow node, without copying it into node inputs. */
@Component({
  selector: 'app-skill-execution',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ModelExecutionComponent, NavLinkDirective],
  template: `
    @if (binding(); as binding) {
      @if (!summaryOnly) {
      <dl class="space-y-3 text-sm m-0">
        <div>
          <dt style="color:var(--ck-fg-3);">{{ i18n.t('skills.runtime.label') }}</dt>
          <dd class="m-0 mt-1" style="color:var(--ck-fg-1);">{{ label('runtime', binding.kind) }}</dd>
        </div>
        @for (param of params(); track param.key) {
          <div>
            <dt style="color:var(--ck-fg-3);">{{ label('param', param.key) }}</dt>
            <dd class="m-0 mt-1">
              <pre class="text-xs whitespace-pre-wrap break-words m-0" style="color:var(--ck-fg-1); overflow-wrap:anywhere;">{{ param.value }}</pre>
            </dd>
          </div>
        }
      </dl>
      }
      @if (binding.kind === 'prompt_template') {
        @if (showResolution) {
          <div class="mt-3 rounded p-3" style="background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft)">
            @if (loading()) { <p class="text-xs m-0" role="status">{{ i18n.t('common.loading') }}</p> }
            @if (resolution(); as effective) { <app-model-execution [resolution]="effective" /> }
            @if (failed()) { <p class="text-xs m-0" role="status">{{ i18n.t('skills.models.resolve_error') }}</p> }
          </div>
        }
        <p class="text-xs mt-3" style="color:var(--ck-fg-3);">{{ i18n.t('skills.execution.model_hint') }}</p>
        <a [navLink]="{ surface: 'resources', facet: 'providers', lens: 'govern' }" target="_blank" rel="noopener" class="text-xs underline">
          {{ i18n.t('skills.models.open_portal') }}
        </a>
      }
    } @else {
      <p class="text-sm m-0" style="color:var(--ck-fg-3);">{{ i18n.t('skills.execution.unavailable') }}</p>
    }
  `,
})
export class SkillExecutionComponent implements OnChanges, OnDestroy {
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  @Input() set executor(value: Skill['executor']) { this.binding.set(value ?? null); }
  @Input() systemId?: string;
  @Input() showResolution = true;
  @Input() summaryOnly = false;
  readonly binding = signal<Skill['executor']>(null);
  readonly resolution = signal<ModelResolution | null>(null);
  readonly failed = signal(false);
  readonly loading = signal(false);
  private request = 0;
  private subscription: Subscription | null = null;
  private readonly unregisterReset = this.workspace.registerContextReset(() => {
    this.request += 1;
    this.subscription?.unsubscribe();
    this.resolution.set(null);
    this.failed.set(false);
    this.loading.set(false);
  });
  readonly params = computed(() => Object.entries(this.binding()?.params ?? {}).map(([key, value]) => ({
    key,
    value: key === 'provider' && value === 'azure' ? this.i18n.t('skills.models.legacy_azure')
      : typeof value === 'string' ? value : JSON.stringify(value, null, 2),
  })));

  ngOnChanges(): void {
    this.subscription?.unsubscribe();
    const request = ++this.request;
    this.resolution.set(null);
    this.failed.set(false);
    this.loading.set(false);
    const binding = this.binding();
    if (!this.showResolution || binding?.kind !== 'prompt_template') return;
    const provider = binding.params?.['provider'];
    const model = binding.params?.['model'];
    if (typeof provider !== 'string' || !provider) return;
    const scope = this.workspace.captureRequestScope();
    this.loading.set(true);
    this.subscription = this.api.resolveModel(provider, typeof model === 'string' ? model : undefined, this.systemId).subscribe({
      next: (resolution) => {
        if (request !== this.request || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.resolution.set(resolution);
        this.loading.set(false);
      },
      error: () => {
        if (request !== this.request || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  ngOnDestroy(): void { this.request += 1; this.subscription?.unsubscribe(); this.unregisterReset(); }

  label(group: 'runtime' | 'param', value: string): string {
    const key = `skills.${group}.${value}` as I18nKey;
    const label = this.i18n.t(key);
    return label === key ? value : label;
  }
}
