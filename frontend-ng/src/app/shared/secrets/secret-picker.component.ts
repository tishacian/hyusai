import { Component, DestroyRef, OnInit, inject, input, model, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { catchError, forkJoin, map, of } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  SecretKind,
  SecretListQuery,
  SecretMeta,
  SecretScope,
  SecretsApi,
  isValidSecretName,
  secretErrorCode,
} from './secrets.api';

/** Lists the picker offers: its own scope, plus the workspace scope when asked and bound to a system. */
export function pickerQueries(
  scope: SecretScope,
  systemId: string | null,
  includeWorkspace: boolean,
): SecretListQuery[] {
  const own: SecretListQuery = scope === 'system' && systemId ? { scope, system_id: systemId } : { scope };
  return includeWorkspace && scope === 'system' && systemId ? [{ scope: 'workspace' }, own] : [own];
}

/**
 * Bind a form field to a registry secret: either type a value (stored as a new
 * secret) or pick an existing one. The bound model is a `secret://` reference,
 * never the value; the typed value is cleared as soon as it is sent.
 */
@Component({
  selector: 'app-secret-picker',
  standalone: true,
  imports: [FormsModule, IconComponent],
  template: `
    <div class="space-y-2" data-testid="secret-picker">
      <div class="inline-flex rounded border border-white/10 text-xs" role="radiogroup">
        <button
          type="button"
          role="radio"
          [attr.aria-checked]="mode() === 'new'"
          (click)="mode.set('new')"
          class="px-2.5 py-1 transition"
          [class.bg-white/10]="mode() === 'new'"
        >{{ i18n.t('resources.secrets.picker.mode_new') }}</button>
        <button
          type="button"
          role="radio"
          [attr.aria-checked]="mode() === 'existing'"
          (click)="mode.set('existing')"
          class="px-2.5 py-1 transition"
          [class.bg-white/10]="mode() === 'existing'"
        >{{ i18n.t('resources.secrets.picker.mode_existing') }}</button>
      </div>

      @if (mode() === 'existing') {
        <select
          class="w-full rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
          [attr.aria-label]="i18n.t('resources.secrets.picker.existing_label')"
          [ngModel]="ref()"
          (ngModelChange)="ref.set($event || null)"
        >
          <option [ngValue]="null">{{ i18n.t('resources.secrets.picker.none') }}</option>
          @for (secret of secrets(); track secret.id) {
            <option [ngValue]="secret.ref">{{ secret.name }} · {{ scopeLabel(secret.scope) }} · v{{ secret.current_version }}</option>
          }
        </select>
        @if (!loading() && secrets().length === 0) {
          <p class="text-xs text-gray-500">{{ i18n.t('resources.secrets.picker.empty') }}</p>
        }
      } @else {
        <div class="grid gap-2 sm:grid-cols-2">
          <input
            type="text"
            class="rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
            [placeholder]="i18n.t('resources.secrets.field.name')"
            [attr.aria-label]="i18n.t('resources.secrets.field.name')"
            [ngModel]="name()"
            (ngModelChange)="name.set($event)"
          />
          <input
            type="password"
            autocomplete="new-password"
            class="rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
            [placeholder]="i18n.t('resources.secrets.field.value')"
            [attr.aria-label]="i18n.t('resources.secrets.field.value')"
            [ngModel]="value()"
            (ngModelChange)="value.set($event)"
          />
        </div>
        <button
          type="button"
          (click)="createSecret()"
          [disabled]="saving() || !canCreate()"
          class="inline-flex items-center gap-1.5 rounded border border-cyan-400/30 px-3 py-1 text-xs text-cyan-300 disabled:opacity-40"
        >
          <app-icon name="key-round" [size]="12" />
          {{ i18n.t('resources.secrets.picker.create') }}
        </button>
      }

      @if (ref(); as current) {
        <p class="text-xs text-gray-500 font-mono">{{ current }}</p>
      }
      @if (error(); as code) {
        <p class="text-xs text-red-400" role="alert">{{ errorLabel(code) }}</p>
      }
    </div>
  `,
})
export class SecretPickerComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly api = inject(SecretsApi);
  private readonly destroyRef = inject(DestroyRef);

  readonly ref = model<string | null>(null);
  readonly scope = input<SecretScope>('workspace');
  readonly systemId = input<string | null>(null);
  /** With `scope="system"`, also offer the workspace secrets. */
  readonly includeWorkspace = input(false);
  readonly kind = input<SecretKind>('generic');
  readonly suggestedName = input<string>('');
  readonly workspaceSlug = input<string | null>(null);

  readonly mode = signal<'new' | 'existing'>('existing');
  readonly secrets = signal<SecretMeta[]>([]);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly name = signal('');
  readonly value = signal('');

  ngOnInit(): void {
    this.name.set(this.suggestedName());
    this.load();
  }

  load(): void {
    this.loading.set(true);
    const options = { workspaceSlug: this.workspaceSlug() };
    const queries = pickerQueries(this.scope(), this.systemId(), this.includeWorkspace());
    forkJoin(
      queries.map((query) =>
        this.api.list(query, options).pipe(
          map((res) => ({ secrets: res.secrets, error: null as string | null })),
          catchError((err) => of({ secrets: [] as SecretMeta[], error: secretErrorCode(err) ?? 'UNKNOWN' })),
        ),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.loading.set(false);
        const secrets = results.flatMap((res) => res.secrets);
        this.secrets.set(secrets);
        if (results.every((res) => res.error)) {
          this.error.set(results[0].error);
          return;
        }
        if (!this.ref() && secrets.length === 0) this.mode.set('new');
      });
  }

  scopeLabel(scope: SecretScope): string {
    return this.i18n.t(`resources.secrets.scope.${scope}`);
  }

  canCreate(): boolean {
    return isValidSecretName(this.name().trim()) && this.value().length > 0;
  }

  createSecret(): void {
    if (!this.canCreate() || this.saving()) return;
    const value = this.value();
    this.value.set('');
    this.saving.set(true);
    this.error.set(null);
    const systemId = this.systemId();
    this.api
      .create(
        {
          name: this.name().trim(),
          value,
          kind: this.kind(),
          scope: this.scope(),
          ...(systemId ? { system_id: systemId } : {}),
        },
        { workspaceSlug: this.workspaceSlug() },
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (secret) => {
          this.saving.set(false);
          this.secrets.update((list) => [...list, secret].sort((a, b) => a.name.localeCompare(b.name)));
          this.ref.set(secret.ref);
          this.mode.set('existing');
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(secretErrorCode(err) ?? 'UNKNOWN');
        },
      });
  }

  errorLabel(code: string): string {
    const key = `resources.secrets.error.${code.toLowerCase()}`;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('resources.secrets.error.unknown') : label;
  }
}
