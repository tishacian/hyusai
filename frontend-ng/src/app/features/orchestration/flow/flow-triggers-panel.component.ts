/**
 * `<app-flow-triggers-panel>` — cron schedules + webhook hooks for a System.
 *
 * Surfaced in the Flow Builder inspector when a trigger source node is selected.
 * Talks to `/systems/{id}/schedules` and `/systems/{id}/hooks`.
 */
import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';

interface RunSchedule {
  id: string;
  name: string;
  cron_expr: string;
  timezone: string;
  enabled: boolean;
  next_fire_at?: string | null;
  last_run_id?: string | null;
}

interface WebhookHook {
  id: string;
  name: string;
  event_type: string;
  enabled: boolean;
  path?: string;
  secret?: string;
}

type LoadState = 'loading' | 'loaded' | 'error';

@Component({
  selector: 'app-flow-triggers-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, GlyphComponent],
  styleUrl: './flow-trigger-controls.component.scss',
  template: `
    <section class="ck-trig">
      <span class="ck-trig__label">{{ i18n.t('flow.triggers.schedules') }}</span>

      @if (schedLoad() === 'loading') {
        <p class="ck-trig__muted">{{ i18n.t('flow.triggers.schedules.loading') }}</p>
      } @else if (schedLoad() === 'error') {
        <p class="ck-trig__muted">
          {{ i18n.t('flow.triggers.schedules.error') }}
          <button type="button" class="ck-trig__linkbtn" (click)="reloadSchedules()">
            {{ i18n.t('flow.triggers.retry') }}
          </button>
        </p>
      } @else {
        <ul class="ck-trig__list">
          @for (s of schedules(); track s.id) {
            <li class="ck-trig__row">
              <div class="ck-trig__row-main">
                <strong>{{ s.name }}</strong>
                <code>{{ s.cron_expr }}</code>
                <span class="ck-trig__pill" [attr.data-on]="s.enabled">
                  {{ s.enabled ? i18n.t('flow.triggers.on') : i18n.t('flow.triggers.off') }}
                </span>
              </div>
              <button
                type="button"
                class="ck-trig__btn"
                [disabled]="busy()"
                (click)="toggleSchedule(s)"
              >
                {{
                  s.enabled ? i18n.t('flow.triggers.disable') : i18n.t('flow.triggers.enable')
                }}
              </button>
            </li>
          } @empty {
            <li class="ck-trig__muted">{{ i18n.t('flow.triggers.schedules.empty') }}</li>
          }
        </ul>

        <div class="ck-trig__form">
          <input
            class="ck-trig__input"
            type="text"
            [attr.placeholder]="i18n.t('flow.triggers.schedules.name')"
            [(ngModel)]="newSchedName"
          />
          <input
            class="ck-trig__input"
            type="text"
            [attr.placeholder]="i18n.t('flow.triggers.schedules.cron')"
            [(ngModel)]="newSchedCron"
          />
          <button
            type="button"
            class="ck-trig__btn"
            [disabled]="busy() || !newSchedCron.trim()"
            (click)="createSchedule()"
          >
            <ck-glyph name="bolt" [size]="12" color="currentColor" />
            {{ i18n.t('flow.triggers.schedules.create') }}
          </button>
        </div>
      }

      <span class="ck-trig__label">{{ i18n.t('flow.triggers.webhooks') }}</span>

      @if (hookLoad() === 'loading') {
        <p class="ck-trig__muted">{{ i18n.t('flow.triggers.webhooks.loading') }}</p>
      } @else if (hookLoad() === 'error') {
        <p class="ck-trig__muted">
          {{ i18n.t('flow.triggers.webhooks.error') }}
          <button type="button" class="ck-trig__linkbtn" (click)="reloadHooks()">
            {{ i18n.t('flow.triggers.retry') }}
          </button>
        </p>
      } @else {
        <ul class="ck-trig__list">
          @for (h of hooks(); track h.id) {
            <li class="ck-trig__row">
              <div class="ck-trig__row-main">
                <strong>{{ h.name }}</strong>
                <code>{{ h.path || ('/api/v1/hooks/' + h.id) }}</code>
                <span class="ck-trig__pill" [attr.data-on]="h.enabled">
                  {{ h.enabled ? i18n.t('flow.triggers.on') : i18n.t('flow.triggers.off') }}
                </span>
              </div>
              <button
                type="button"
                class="ck-trig__btn"
                [disabled]="busy()"
                (click)="toggleHook(h)"
              >
                {{
                  h.enabled ? i18n.t('flow.triggers.disable') : i18n.t('flow.triggers.enable')
                }}
              </button>
            </li>
          } @empty {
            <li class="ck-trig__muted">{{ i18n.t('flow.triggers.webhooks.empty') }}</li>
          }
        </ul>

        @if (lastSecret(); as secret) {
          <p class="ck-trig__secret" role="status">
            {{ i18n.t('flow.triggers.webhooks.secret') }}
            <code>{{ secret }}</code>
          </p>
        }

        <div class="ck-trig__form">
          <input
            class="ck-trig__input"
            type="text"
            [attr.placeholder]="i18n.t('flow.triggers.webhooks.name')"
            [(ngModel)]="newHookName"
          />
          <button
            type="button"
            class="ck-trig__btn"
            [disabled]="busy()"
            (click)="createHook()"
          >
            <ck-glyph name="bolt" [size]="12" color="currentColor" />
            {{ i18n.t('flow.triggers.webhooks.create') }}
          </button>
        </div>
      }
    </section>
  `,
})
export class FlowTriggersPanelComponent {
  private readonly api = inject(ApiService);
  private readonly toastr = inject(ToastrService);
  readonly i18n = inject(I18nService);

  readonly systemId = input.required<string>();

  readonly schedules = signal<RunSchedule[]>([]);
  readonly hooks = signal<WebhookHook[]>([]);
  readonly schedLoad = signal<LoadState>('loading');
  readonly hookLoad = signal<LoadState>('loading');
  readonly busy = signal(false);
  readonly lastSecret = signal<string | null>(null);

  newSchedName = 'Hourly';
  newSchedCron = '0 * * * *';
  newHookName = 'Inbound';

  constructor() {
    effect(() => {
      const id = this.systemId();
      if (id) {
        this.fetchSchedules(id);
        this.fetchHooks(id);
      }
    });
  }

  reloadSchedules(): void {
    const id = this.systemId();
    if (id) this.fetchSchedules(id);
  }

  reloadHooks(): void {
    const id = this.systemId();
    if (id) this.fetchHooks(id);
  }

  private fetchSchedules(id: string): void {
    this.schedLoad.set('loading');
    this.api.get<{ schedules: RunSchedule[] }>(`/systems/${id}/schedules`).subscribe({
      next: (res) => {
        this.schedules.set(res.schedules ?? []);
        this.schedLoad.set('loaded');
      },
      error: () => this.schedLoad.set('error'),
    });
  }

  private fetchHooks(id: string): void {
    this.hookLoad.set('loading');
    this.api.get<{ hooks: WebhookHook[] }>(`/systems/${id}/hooks`).subscribe({
      next: (res) => {
        this.hooks.set(res.hooks ?? []);
        this.hookLoad.set('loaded');
      },
      error: () => this.hookLoad.set('error'),
    });
  }

  createSchedule(): void {
    const id = this.systemId();
    const cron = this.newSchedCron.trim();
    if (!id || !cron || this.busy()) return;
    this.busy.set(true);
    this.api
      .post<RunSchedule>(`/systems/${id}/schedules`, {
        name: this.newSchedName.trim() || 'Schedule',
        cron_expr: cron,
        timezone: 'UTC',
        enabled: true,
        input_payload: {},
      })
      .subscribe({
        next: (row) => {
          this.schedules.update((list) => [row, ...list]);
          this.busy.set(false);
          this.toastr.success(
            this.i18n.t('flow.triggers.schedules.created'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
        error: () => {
          this.busy.set(false);
          this.toastr.error(
            this.i18n.t('flow.triggers.schedules.create_failed'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
      });
  }

  toggleSchedule(s: RunSchedule): void {
    const id = this.systemId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api
      .patch<RunSchedule>(`/systems/${id}/schedules/${s.id}`, { enabled: !s.enabled })
      .subscribe({
        next: (row) => {
          this.schedules.update((list) => list.map((x) => (x.id === row.id ? row : x)));
          this.busy.set(false);
        },
        error: () => {
          this.busy.set(false);
          this.toastr.error(
            this.i18n.t('flow.triggers.schedules.update_failed'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
      });
  }

  createHook(): void {
    const id = this.systemId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api
      .post<WebhookHook>(`/systems/${id}/hooks`, {
        name: this.newHookName.trim() || 'Webhook',
        event_type: 'webhook.received',
        enabled: true,
      })
      .subscribe({
        next: (row) => {
          this.hooks.update((list) => [row, ...list]);
          this.lastSecret.set(row.secret ?? null);
          this.busy.set(false);
          this.toastr.success(
            this.i18n.t('flow.triggers.webhooks.created'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
        error: () => {
          this.busy.set(false);
          this.toastr.error(
            this.i18n.t('flow.triggers.webhooks.create_failed'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
      });
  }

  toggleHook(h: WebhookHook): void {
    const id = this.systemId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api
      .patch<WebhookHook>(`/systems/${id}/hooks/${h.id}`, { enabled: !h.enabled })
      .subscribe({
        next: (row) => {
          this.hooks.update((list) => list.map((x) => (x.id === row.id ? row : x)));
          this.busy.set(false);
        },
        error: () => {
          this.busy.set(false);
          this.toastr.error(
            this.i18n.t('flow.triggers.webhooks.update_failed'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
      });
  }
}
