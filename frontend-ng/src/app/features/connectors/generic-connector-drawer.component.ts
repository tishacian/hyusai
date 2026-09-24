import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Injector,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  afterNextRender,
  inject,
  signal,
} from '@angular/core';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { ConnectorDef, ConnectorField } from '@app/features/resources/resources.catalog';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { IconComponent } from '@app/shared/ui/icon.component';

/** One `GET /connectors` row: plain values, and only whether each secret is set. */
export interface GenericConnectorConfig {
  id: string;
  values: Record<string, string>;
  secrets_set: Record<string, boolean>;
  configured: boolean;
  testable: boolean;
}

export interface GenericConnectorList {
  connectors: GenericConnectorConfig[];
  can_configure: boolean;
}

export type ConnectorTestStatus =
  | 'connected'
  | 'auth_failed'
  | 'unreachable'
  | 'not_configured'
  | 'unsupported'
  | 'error';

export interface ConnectorTestResult {
  id: string;
  status: ConnectorTestStatus;
  detail: string | null;
  checked_at: string;
}

export function genericConnectorMap(list: GenericConnectorList | null): Record<string, GenericConnectorConfig> {
  return Object.fromEntries((list?.connectors ?? []).map((row) => [row.id, row]));
}

const TEST_TONE: Record<ConnectorTestStatus, string> = {
  connected: 'bg-emerald-500/10 text-emerald-100 ring-emerald-400/25',
  auth_failed: 'bg-red-500/10 text-red-100 ring-red-400/25',
  error: 'bg-red-500/10 text-red-100 ring-red-400/25',
  unreachable: 'bg-amber-500/10 text-amber-100 ring-amber-400/25',
  not_configured: 'bg-amber-500/10 text-amber-100 ring-amber-400/25',
  unsupported: 'bg-white/5 text-gray-200 ring-white/10',
};

/**
 * Setup drawer of the catalog connectors that have no page of their own.
 * Values live on the server (`/connectors`). A stored secret is never read
 * back: the drawer only knows whether it is set, and offers to replace it.
 */
@Component({
  selector: 'app-generic-connector-drawer',
  standalone: true,
  imports: [CommonModule, DrawerComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-drawer
      [open]="open"
      [title]="connector?.name ?? i18n.t('connectors.drawer.setup_fallback_title')"
      [subtitle]="connector?.version ?? ''"
      [icon]="connector?.icon ?? 'plug'"
      [width]="width"
      (close)="close.emit()"
    >
      @if (connector; as c) {
        <div class="space-y-5">
          <p class="text-xs text-gray-400 leading-relaxed">{{ catalogDescription(c) }}</p>

          @if (c.status === 'coming-soon') {
            <div class="rounded-md p-3 flex items-start gap-2 ring-1 bg-amber-500/5 ring-amber-500/20">
              <app-icon name="clock" [size]="14" class="mt-0.5 shrink-0 text-amber-400" />
              <div class="text-[11px] leading-relaxed text-amber-200/90">
                <p>{{ i18n.t('connectors.drawer.planned') }}</p>
                @if (c.fields.length) {
                  <p class="mt-2 font-semibold">{{ i18n.t('connectors.drawer.expected_fields') }}</p>
                  <ul class="mt-1 list-disc pl-4">
                    @for (field of c.fields; track field.key) {
                      <li>{{ field.label }}</li>
                    }
                  </ul>
                }
              </div>
            </div>
          } @else if (!c.fields.length) {
            <p class="text-[11px] text-gray-400 leading-relaxed">{{ i18n.t('connectors.drawer.nothing_to_set') }}</p>
          } @else if (!config) {
            <p class="text-[11px] text-amber-200/90 leading-relaxed">{{ i18n.t('connectors.drawer.unavailable') }}</p>
          } @else {
            <div class="rounded-md p-3 flex items-start gap-2 ring-1 bg-cyan-500/5 ring-cyan-500/20">
              <app-icon name="shield-check" [size]="14" class="mt-0.5 shrink-0 text-cyan-300" />
              <p class="text-[11px] leading-relaxed text-cyan-200/90">{{ i18n.t('connectors.drawer.server') }}</p>
            </div>
            @if (!canConfigure) {
              <p class="text-[11px] text-amber-200/90 leading-relaxed">{{ i18n.t('connectors.drawer.admin_only') }}</p>
            }

            <form (submit)="save($event)" class="space-y-4">
              @for (field of c.fields; track field.key) {
                <div>
                  <label
                    [attr.for]="showsInput(field) ? inputId(field) : null"
                    class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5"
                  >
                    {{ field.label }}
                    @if (field.required && !secretSet(field)) {
                      <span class="text-red-400">*</span>
                    }
                  </label>
                  @if (!showsInput(field)) {
                    <div class="flex items-center justify-between gap-3 rounded bg-black/30 border border-white/10 px-3 py-2">
                      <span class="inline-flex items-center gap-1.5 text-[12px] text-emerald-300">
                        <app-icon name="lock" [size]="12" /> {{ i18n.t('connectors.secret.set') }}
                      </span>
                      <button
                        type="button"
                        [id]="replaceId(field)"
                        (click)="replace(field)"
                        [disabled]="!canConfigure"
                        [attr.aria-label]="i18n.t('connectors.secret.replace_label', { field: field.label })"
                        class="text-[12px] font-medium text-cyan-300 hover:text-cyan-200 transition disabled:opacity-50"
                      >
                        {{ i18n.t('connectors.secret.replace') }}
                      </button>
                    </div>
                  } @else if (isSecret(field)) {
                    <input
                      [id]="inputId(field)"
                      type="password"
                      autocomplete="new-password"
                      [value]="secrets[field.key] || ''"
                      (input)="onSecretInput(field.key, $event)"
                      [placeholder]="field.placeholder ?? ''"
                      [required]="!!field.required && !secretSet(field)"
                      [disabled]="!canConfigure"
                      class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm disabled:opacity-50"
                    />
                    <div class="mt-1 flex items-start justify-between gap-3 text-[11px] text-gray-500">
                      <span>{{ i18n.t('connectors.secret.write_only') }}</span>
                      @if (secretSet(field)) {
                        <button
                          type="button"
                          (click)="keep(field)"
                          class="shrink-0 font-medium text-gray-300 hover:text-white transition"
                        >
                          {{ i18n.t('connectors.secret.keep') }}
                        </button>
                      }
                    </div>
                  } @else {
                    <input
                      [id]="inputId(field)"
                      [type]="field.type"
                      [value]="values[field.key] || ''"
                      (input)="onValueInput(field.key, $event)"
                      [placeholder]="field.placeholder ?? ''"
                      [required]="!!field.required"
                      [disabled]="!canConfigure"
                      class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm disabled:opacity-50"
                    />
                  }
                </div>
              }

              <div class="flex flex-wrap items-center gap-2 pt-2">
                <button
                  type="submit"
                  [disabled]="!canConfigure || saving()"
                  class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 text-white text-sm font-medium transition disabled:opacity-50"
                >
                  <app-icon name="save" [size]="14" />
                  {{ saving() ? i18n.t('connectors.action.saving') : i18n.t('common.save') }}
                </button>
                <button
                  type="button"
                  (click)="test()"
                  [disabled]="!canTest()"
                  [attr.aria-describedby]="testHint() ? testHintId(c) : null"
                  class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition disabled:opacity-50"
                >
                  <app-icon name="zap" [size]="14" [class.animate-pulse]="testing()" />
                  {{ testLabel() }}
                </button>
                <button
                  type="button"
                  (click)="clear()"
                  [disabled]="!canConfigure || !config.configured || saving()"
                  class="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded text-red-300 hover:bg-red-500/10 text-sm transition disabled:opacity-50"
                >
                  <app-icon name="trash-2" [size]="14" />
                  {{ confirmingClear() ? i18n.t('connectors.action.clear_confirm') : i18n.t('connectors.action.clear') }}
                </button>
              </div>
              @if (testHint(); as hint) {
                <p [id]="testHintId(c)" class="text-[11px] text-gray-400 leading-relaxed">{{ hint }}</p>
              }
            </form>

            <div role="status" aria-live="polite">
              @if (testResult(); as result) {
                <div class="rounded-md p-3 ring-1" [ngClass]="testTone(result)">
                  <p class="text-sm font-medium">{{ testStatusLabel(result) }}</p>
                  <p class="mt-0.5 text-[11px] opacity-80">
                    {{ i18n.t('connectors.test.checked_at', { time: checkedAt(result) }) }}
                    @if (result.detail) {
                      · <span class="font-mono">{{ result.detail }}</span>
                    }
                  </p>
                </div>
              } @else if (testFailed()) {
                <p class="rounded-md p-3 text-sm ring-1 bg-red-500/10 text-red-100 ring-red-400/25">
                  {{ i18n.t('connectors.test.failed') }}
                </p>
              }
            </div>
          }
        </div>
      }
    </app-drawer>
  `,
})
export class GenericConnectorDrawerComponent implements OnChanges {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  private readonly injector = inject(Injector);
  readonly i18n = inject(I18nService);

  @Input() open = false;
  @Input() connector: ConnectorDef | null = null;
  @Input() config: GenericConnectorConfig | null = null;
  @Input() canConfigure = false;
  @Input() width = 460;
  @Output() readonly close = new EventEmitter<void>();
  @Output() readonly changed = new EventEmitter<GenericConnectorConfig>();

  /** Plain fields, prefilled from the server. */
  values: Record<string, string> = {};
  /** Secrets typed in this drawer, sent once on save and then dropped. */
  secrets: Record<string, string> = {};
  readonly replacing = signal<ReadonlySet<string>>(new Set());
  readonly saving = signal(false);
  readonly testing = signal(false);
  readonly testResult = signal<ConnectorTestResult | null>(null);
  readonly testFailed = signal(false);
  readonly confirmingClear = signal(false);

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['connector'] || changes['config'] || changes['open']) this.reset();
  }

  reset(): void {
    this.values = { ...(this.config?.values ?? {}) };
    this.secrets = {};
    this.replacing.set(new Set());
    this.testResult.set(null);
    this.testFailed.set(false);
    this.confirmingClear.set(false);
  }

  /** Static catalog entries are translated at render time by stable id, with a
   * fallback to the raw description. */
  catalogDescription(connector: ConnectorDef): string {
    const key = `resources.catalog.${connector.id}.description`;
    const label = this.i18n.t(key);
    return label === key ? connector.description : label;
  }

  isSecret(field: ConnectorField): boolean {
    return field.type === 'password' || field.key in (this.config?.secrets_set ?? {});
  }

  secretSet(field: ConnectorField): boolean {
    return this.config?.secrets_set?.[field.key] === true;
  }

  showsInput(field: ConnectorField): boolean {
    return !this.isSecret(field) || !this.secretSet(field) || this.replacing().has(field.key);
  }

  inputId(field: ConnectorField): string {
    return `connector-${this.connector?.id}-${field.key}`;
  }

  replaceId(field: ConnectorField): string {
    return `${this.inputId(field)}-replace`;
  }

  testHintId(connector: ConnectorDef): string {
    return `connector-${connector.id}-test-hint`;
  }

  onValueInput(key: string, event: Event): void {
    this.values = { ...this.values, [key]: (event.target as HTMLInputElement).value };
  }

  onSecretInput(key: string, event: Event): void {
    this.secrets = { ...this.secrets, [key]: (event.target as HTMLInputElement).value };
  }

  replace(field: ConnectorField): void {
    this.replacing.update((keys) => new Set(keys).add(field.key));
    afterNextRender(() => document.getElementById(this.inputId(field))?.focus(), {
      injector: this.injector,
    });
  }

  keep(field: ConnectorField): void {
    const secrets = { ...this.secrets };
    delete secrets[field.key];
    this.secrets = secrets;
    this.replacing.update((keys) => {
      const next = new Set(keys);
      next.delete(field.key);
      return next;
    });
    afterNextRender(() => document.getElementById(this.replaceId(field))?.focus(), {
      injector: this.injector,
    });
  }

  /** The test runs on the saved setup, so unsaved edits would be misleading. */
  isDirty(): boolean {
    return (this.connector?.fields ?? []).some((field) =>
      this.isSecret(field)
        ? !!this.secrets[field.key]?.trim()
        : (this.values[field.key] ?? '').trim() !== (this.config?.values[field.key] ?? ''),
    );
  }

  canTest(): boolean {
    return (
      this.canConfigure &&
      this.config?.testable === true &&
      !this.isDirty() &&
      !this.testing() &&
      !this.saving()
    );
  }

  testLabel(): string {
    if (this.config && !this.config.testable) return this.i18n.t('connectors.test.unavailable');
    return this.testing() ? this.i18n.t('connectors.action.testing') : this.i18n.t('connectors.action.test');
  }

  testHint(): string | null {
    if (!this.config) return null;
    if (!this.config.testable) return this.i18n.t('connectors.test.unavailable_hint');
    return this.isDirty() ? this.i18n.t('connectors.test.save_first') : null;
  }

  testTone(result: ConnectorTestResult): string {
    return TEST_TONE[result.status] ?? TEST_TONE.error;
  }

  testStatusLabel(result: ConnectorTestResult): string {
    const key = `connectors.test.status.${result.status}`;
    const label = this.i18n.t(key);
    return label === key ? result.status : label;
  }

  checkedAt(result: ConnectorTestResult): string {
    const date = new Date(result.checked_at);
    if (Number.isNaN(date.getTime())) return result.checked_at;
    return new Intl.DateTimeFormat(this.i18n.locale(), { timeStyle: 'medium' }).format(date);
  }

  save(event?: Event): void {
    event?.preventDefault();
    const connector = this.connector;
    if (!connector || !this.config || !this.canConfigure || this.saving()) return;
    const values: Record<string, string> = {};
    for (const field of connector.fields) {
      if (!this.isSecret(field)) values[field.key] = (this.values[field.key] ?? '').trim();
      else if (this.secrets[field.key]?.trim()) values[field.key] = this.secrets[field.key];
    }
    const scope = this.workspace.captureRequestScope();
    this.saving.set(true);
    this.confirmingClear.set(false);
    this.api
      .put<GenericConnectorConfig>(`/connectors/${connector.id}`, { values }, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (config) => {
          this.saving.set(false);
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.secrets = {};
          this.replacing.set(new Set());
          this.changed.emit(config);
          this.toast.success(
            this.i18n.t('connectors.toast.setup_saved', { name: connector.name }),
            this.i18n.t('connectors.toast.title'),
          );
        },
        error: () => {
          this.saving.set(false);
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.toast.error(
            this.i18n.t('connectors.toast.save_failed', { name: connector.name }),
            this.i18n.t('connectors.toast.title'),
          );
        },
      });
  }

  test(): void {
    const connector = this.connector;
    if (!connector || !this.canTest()) return;
    const scope = this.workspace.captureRequestScope();
    this.testing.set(true);
    this.testResult.set(null);
    this.testFailed.set(false);
    this.confirmingClear.set(false);
    this.api
      .post<ConnectorTestResult>(`/connectors/${connector.id}/test`, {}, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (result) => {
          this.testing.set(false);
          if (this.workspace.isRequestScopeCurrent(scope)) this.testResult.set(result);
        },
        error: () => {
          this.testing.set(false);
          if (this.workspace.isRequestScopeCurrent(scope)) this.testFailed.set(true);
        },
      });
  }

  /** Two clicks: the setup is shared by the workspace and its secrets cannot be read back. */
  clear(): void {
    const connector = this.connector;
    if (!connector || !this.config?.configured || !this.canConfigure) return;
    if (!this.confirmingClear()) {
      this.confirmingClear.set(true);
      return;
    }
    this.confirmingClear.set(false);
    const scope = this.workspace.captureRequestScope();
    this.api
      .delete<GenericConnectorConfig>(`/connectors/${connector.id}`, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (config) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.changed.emit(config);
          this.toast.info(
            this.i18n.t('connectors.toast.setup_cleared', { name: connector.name }),
            this.i18n.t('connectors.toast.title'),
          );
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.toast.error(
            this.i18n.t('connectors.toast.clear_failed', { name: connector.name }),
            this.i18n.t('connectors.toast.title'),
          );
        },
      });
  }
}
