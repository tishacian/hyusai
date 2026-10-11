import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  SECRET_KINDS,
  SecretConsumerMeta,
  SecretKind,
  SecretMeta,
  SecretScope,
  SecretsApi,
  isValidSecretName,
  secretErrorCode,
} from '@app/shared/secrets/secrets.api';

/** Workspace settings → Secrets: list, create, rotate, history, consumers. Values are write-only. */
@Component({
  selector: 'app-workspace-secrets',
  standalone: true,
  imports: [FormsModule, DatePipe, IconComponent],
  template: `
    <div class="space-y-6">
      <section class="ck-surface rounded-md p-6 space-y-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-white">{{ i18n.t('resources.secrets.title') }}</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">{{ i18n.t('resources.secrets.description') }}</p>
          </div>
          @if (canManagePlatform()) {
            <div class="inline-flex rounded border border-white/10 text-xs" role="radiogroup">
              @for (s of scopes; track s) {
                <button
                  type="button"
                  role="radio"
                  [attr.aria-checked]="scope() === s"
                  (click)="setScope(s)"
                  class="px-2.5 py-1"
                  [class.bg-white/10]="scope() === s"
                >{{ i18n.t('resources.secrets.scope.' + s) }}</button>
              }
            </div>
          }
        </div>

        @if (error(); as code) {
          <p class="text-sm text-red-400" role="alert">{{ errorLabel(code) }}</p>
        }

        @if (loading()) {
          <p class="text-sm text-gray-500">{{ i18n.t('resources.secrets.loading') }}</p>
        } @else if (secrets().length === 0) {
          <p class="text-sm text-gray-500">{{ i18n.t('resources.secrets.empty') }}</p>
        } @else {
          <table class="w-full text-sm">
            <thead class="text-xs text-gray-500 text-left">
              <tr>
                <th class="py-1.5">{{ i18n.t('resources.secrets.field.name') }}</th>
                <th>{{ i18n.t('resources.secrets.field.kind') }}</th>
                <th>{{ i18n.t('resources.secrets.column.version') }}</th>
                <th>{{ i18n.t('resources.secrets.column.status') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              @for (secret of secrets(); track secret.id) {
                <tr class="border-t border-white/5">
                  <td class="py-2">
                    <button type="button" class="text-white hover:underline" (click)="select(secret)">{{ secret.name }}</button>
                    <div class="text-xs text-gray-500 font-mono">{{ secret.ref }}</div>
                  </td>
                  <td>{{ i18n.t('resources.secrets.kind.' + secret.kind) }}</td>
                  <td>v{{ secret.current_version }}</td>
                  <td>{{ statusLabel(secret) }}</td>
                  <td class="text-right">
                    @if (!secret.disabled_at) {
                      <button type="button" class="text-xs text-cyan-300 mr-2" (click)="startRotate(secret)">
                        <app-icon name="rotate-cw" [size]="12" /> {{ i18n.t('resources.secrets.action.rotate') }}
                      </button>
                      <button type="button" class="text-xs text-amber-400" (click)="disable(secret)">
                        <app-icon name="lock" [size]="12" /> {{ i18n.t('resources.secrets.action.disable') }}
                      </button>
                    }
                  </td>
                </tr>
                @if (rotating() === secret.id) {
                  <tr>
                    <td colspan="5" class="pb-3">
                      <div class="flex gap-2">
                        <input
                          type="password"
                          autocomplete="new-password"
                          class="flex-1 rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
                          [attr.aria-label]="i18n.t('resources.secrets.field.new_value')"
                          [placeholder]="i18n.t('resources.secrets.field.new_value')"
                          [ngModel]="rotateValue()"
                          (ngModelChange)="rotateValue.set($event)"
                        />
                        <button type="button" class="text-xs text-cyan-300" [disabled]="!rotateValue() || busy()" (click)="rotate(secret)">
                          {{ i18n.t('resources.secrets.action.rotate') }}
                        </button>
                        <button type="button" class="text-xs text-gray-400" (click)="cancelRotate()">
                          {{ i18n.t('resources.secrets.action.cancel') }}
                        </button>
                      </div>
                    </td>
                  </tr>
                }
              }
            </tbody>
          </table>
        }
        <label class="inline-flex items-center gap-2 text-xs text-gray-400">
          <input type="checkbox" [ngModel]="includeDisabled()" (ngModelChange)="includeDisabled.set($event); load()" />
          {{ i18n.t('resources.secrets.include_disabled') }}
        </label>
      </section>

      <section class="ck-surface rounded-md p-6 space-y-3">
        <h3 class="text-sm font-semibold text-white">{{ i18n.t('resources.secrets.create.title') }}</h3>
        <div class="grid gap-2 sm:grid-cols-3">
          <input
            type="text"
            class="rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
            [attr.aria-label]="i18n.t('resources.secrets.field.name')"
            [placeholder]="i18n.t('resources.secrets.field.name')"
            [ngModel]="newName()"
            (ngModelChange)="newName.set($event)"
          />
          <select
            class="rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
            [attr.aria-label]="i18n.t('resources.secrets.field.kind')"
            [ngModel]="newKind()"
            (ngModelChange)="newKind.set($event)"
          >
            @for (k of kinds; track k) {
              <option [ngValue]="k">{{ i18n.t('resources.secrets.kind.' + k) }}</option>
            }
          </select>
          <input
            type="password"
            autocomplete="new-password"
            class="rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
            [attr.aria-label]="i18n.t('resources.secrets.field.value')"
            [placeholder]="i18n.t('resources.secrets.field.value')"
            [ngModel]="newValue()"
            (ngModelChange)="newValue.set($event)"
          />
        </div>
        <input
          type="text"
          class="w-full rounded border border-white/10 bg-transparent px-2 py-1.5 text-sm"
          [attr.aria-label]="i18n.t('resources.secrets.field.description')"
          [placeholder]="i18n.t('resources.secrets.field.description')"
          [ngModel]="newDescription()"
          (ngModelChange)="newDescription.set($event)"
        />
        @if (newName() && !nameValid()) {
          <p class="text-xs text-amber-400">{{ i18n.t('resources.secrets.name_hint') }}</p>
        }
        <button
          type="button"
          (click)="create()"
          [disabled]="busy() || !canCreate()"
          class="inline-flex items-center gap-1.5 px-4 py-2 border border-cyan-400/30 text-cyan-300 rounded text-sm disabled:opacity-40"
        >
          <app-icon name="plus" [size]="14" /> {{ i18n.t('resources.secrets.action.create') }}
        </button>
      </section>

      @if (selected(); as secret) {
        <section class="ck-surface rounded-md p-6 space-y-4" data-testid="secret-detail">
          <h3 class="text-sm font-semibold text-white">{{ secret.name }}</h3>
          @if (secret.description) {
            <p class="text-sm text-gray-400">{{ secret.description }}</p>
          }
          <div>
            <h4 class="text-xs uppercase text-gray-500 mb-1.5">
              <app-icon name="history" [size]="12" /> {{ i18n.t('resources.secrets.versions') }}
            </h4>
            <ul class="text-sm space-y-1">
              @for (v of secret.versions; track v.version) {
                <li class="flex items-center gap-3">
                  <span class="font-mono">v{{ v.version }}</span>
                  <span class="text-gray-500">{{ v.created_at | date: 'short' }}</span>
                  @if (v.destroyed_at) {
                    <span class="text-xs text-red-400">{{ i18n.t('resources.secrets.status.destroyed') }}</span>
                  } @else if (v.version !== secret.current_version) {
                    <button type="button" class="text-xs text-red-400" (click)="destroy(secret, v.version)">
                      {{ i18n.t('resources.secrets.action.destroy_version') }}
                    </button>
                  }
                </li>
              }
            </ul>
          </div>
          <div>
            <h4 class="text-xs uppercase text-gray-500 mb-1.5">{{ i18n.t('resources.secrets.consumers') }}</h4>
            @if (consumers().length === 0) {
              <p class="text-sm text-gray-500">{{ i18n.t('resources.secrets.consumers_empty') }}</p>
            } @else {
              <ul class="text-sm space-y-1">
                @for (c of consumers(); track $index) {
                  <li>
                    <span class="font-mono">{{ c.kind }}:{{ c.id }}</span>
                    @if (c.node_id) { <span class="text-gray-500"> · {{ c.node_id }}</span> }
                    <span class="text-gray-500"> · {{ i18n.t('resources.secrets.consumer_count', { count: c.count }) }}</span>
                  </li>
                }
              </ul>
            }
          </div>
          <div class="border-t border-white/5 pt-3">
            @if (confirmDestroy() === secret.id) {
              <p class="text-xs text-red-400 mb-2">{{ i18n.t('resources.secrets.destroy_confirm') }}</p>
              <button type="button" class="text-xs text-red-400 mr-3" (click)="destroy(secret)">
                <app-icon name="trash-2" [size]="12" /> {{ i18n.t('resources.secrets.action.destroy') }}
              </button>
              <button type="button" class="text-xs text-gray-400" (click)="confirmDestroy.set(null)">
                {{ i18n.t('resources.secrets.action.cancel') }}
              </button>
            } @else {
              <button type="button" class="text-xs text-red-400" (click)="confirmDestroy.set(secret.id)">
                <app-icon name="trash-2" [size]="12" /> {{ i18n.t('resources.secrets.action.destroy') }}
              </button>
            }
          </div>
        </section>
      }
    </div>
  `,
})
export class WorkspaceSecretsComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly api = inject(SecretsApi);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly kinds = SECRET_KINDS;
  readonly scopes: readonly SecretScope[] = ['workspace', 'platform'];

  readonly slug = signal<string | null>(null);
  readonly scope = signal<SecretScope>('workspace');
  readonly includeDisabled = signal(false);
  readonly canManagePlatform = signal(false);
  readonly secrets = signal<SecretMeta[]>([]);
  readonly loading = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  readonly newName = signal('');
  readonly newKind = signal<SecretKind>('api_key');
  readonly newValue = signal('');
  readonly newDescription = signal('');

  readonly rotating = signal<string | null>(null);
  readonly rotateValue = signal('');
  readonly selected = signal<SecretMeta | null>(null);
  readonly consumers = signal<SecretConsumerMeta[]>([]);
  readonly confirmDestroy = signal<string | null>(null);

  ngOnInit(): void {
    (this.route.parent ?? this.route).paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        this.slug.set(params.get('slug'));
        this.selected.set(null);
        this.load();
      });
  }

  private get options() {
    return { workspaceSlug: this.slug() };
  }

  setScope(scope: SecretScope): void {
    this.scope.set(scope);
    this.selected.set(null);
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api
      .list({ scope: this.scope(), include_disabled: this.includeDisabled() }, this.options)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.secrets.set(res.secrets);
          this.canManagePlatform.set(res.can_manage_platform);
          this.loading.set(false);
          this.error.set(null);
        },
        error: (err) => this.fail(err),
      });
  }

  nameValid(): boolean {
    return isValidSecretName(this.newName().trim());
  }

  canCreate(): boolean {
    return this.nameValid() && this.newValue().length > 0;
  }

  create(): void {
    if (!this.canCreate() || this.busy()) return;
    const value = this.newValue();
    this.newValue.set('');
    const description = this.newDescription().trim();
    this.run(
      this.api.create(
        {
          name: this.newName().trim(),
          value,
          kind: this.newKind(),
          scope: this.scope(),
          ...(description ? { description } : {}),
        },
        this.options,
      ),
      () => {
        this.newName.set('');
        this.newDescription.set('');
      },
    );
  }

  startRotate(secret: SecretMeta): void {
    this.rotating.set(secret.id);
    this.rotateValue.set('');
  }

  cancelRotate(): void {
    this.rotating.set(null);
    this.rotateValue.set('');
  }

  rotate(secret: SecretMeta): void {
    const value = this.rotateValue();
    if (!value || this.busy()) return;
    this.rotateValue.set('');
    this.rotating.set(null);
    this.run(this.api.rotate(secret.id, value, this.options));
  }

  disable(secret: SecretMeta): void {
    this.run(this.api.disable(secret.id, this.options));
  }

  destroy(secret: SecretMeta, version?: number): void {
    this.confirmDestroy.set(null);
    this.run(this.api.destroy(secret.id, version, this.options));
  }

  select(secret: SecretMeta): void {
    this.selected.set(secret);
    this.consumers.set([]);
    this.api
      .consumers(secret.id, this.options)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (res) => this.consumers.set(res.consumers), error: (err) => this.fail(err) });
  }

  statusLabel(secret: SecretMeta): string {
    if (secret.disabled_at) return this.i18n.t('resources.secrets.status.disabled');
    if (!secret.value_set) return this.i18n.t('resources.secrets.status.destroyed');
    if (secret.expires_at && new Date(secret.expires_at).getTime() <= Date.now()) {
      return this.i18n.t('resources.secrets.status.expired');
    }
    return this.i18n.t('resources.secrets.status.active');
  }

  errorLabel(code: string): string {
    const key = `resources.secrets.error.${code.toLowerCase()}`;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('resources.secrets.error.unknown') : label;
  }

  private run(request: ReturnType<SecretsApi['create']>, after?: () => void): void {
    this.busy.set(true);
    this.error.set(null);
    request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (secret) => {
        this.busy.set(false);
        after?.();
        if (this.selected()?.id === secret.id) this.selected.set(secret);
        this.load();
      },
      error: (err) => this.fail(err),
    });
  }

  private fail(err: unknown): void {
    this.busy.set(false);
    this.loading.set(false);
    this.error.set(secretErrorCode(err) ?? 'UNKNOWN');
  }
}
