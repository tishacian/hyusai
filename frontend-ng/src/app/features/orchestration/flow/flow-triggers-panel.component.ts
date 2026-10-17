/**
 * `<app-flow-triggers-panel>` — cron schedules + webhook hooks for a System.
 *
 * Surfaced in the Flow Builder inspector when a trigger source node is selected.
 * Talks to `/systems/{id}/schedules` and `/systems/{id}/hooks`.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ToastrService } from 'ngx-toastr';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { scheduleInstant, schedulePayload, validScheduleTimezone } from './flow-triggers.vm';

interface RunSchedule {
  id: string;
  name: string;
  cron_expr: string;
  timezone: string;
  enabled: boolean;
  next_fire_at?: string | null;
  last_run_id?: string | null;
  input_payload?: Record<string, unknown>;
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
  imports: [FormsModule, GlyphComponent, NavLinkDirective],
  styleUrl: './flow-trigger-controls.component.scss',
  template: `
    <section class="ck-trig">
      @if (kind() === 'schedule') {
        <span class="ck-trig__label">{{ i18n.t('flow.triggers.schedules') }}</span>
        <p class="ck-trig__muted">{{ i18n.t('flow.triggers.schedules.execution_note') }}</p>

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
                  <span>{{ s.timezone }}</span>
                  <span class="ck-trig__pill" [attr.data-on]="s.enabled">
                    {{ s.enabled ? i18n.t('flow.triggers.on') : i18n.t('flow.triggers.off') }}
                  </span>
                </div>
                <p class="ck-trig__muted">
                  {{ i18n.t('flow.triggers.schedules.next') }} :
                  {{ s.enabled ? nextFire(s) : i18n.t('flow.triggers.schedules.paused') }}
                </p>
                @if (s.last_run_id; as runId) {
                  <a class="ck-trig__runs" [navLink]="{ type: 'run', ref: runId }">
                    {{ i18n.t('flow.triggers.schedules.last_run') }}
                  </a>
                }
                @if (s.input_payload && hasPayload(s.input_payload)) {
                  <details>
                    <summary class="ck-trig__muted">{{ i18n.t('flow.triggers.schedules.payload') }}</summary>
                    <pre class="ck-trig__payload">{{ payloadText(s.input_payload) }}</pre>
                  </details>
                }
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

          <details class="ck-trig__setup" [open]="scheduleFormOpen()" (toggle)="scheduleFormOpen.set($any($event.target).open)">
            <summary>{{ i18n.t('flow.triggers.schedules.create') }}</summary>
            <div class="ck-trig__form">
            <label class="ck-trig__field">
              {{ i18n.t('flow.triggers.schedules.name') }}
            <input
              class="ck-trig__input"
              type="text"
              [attr.placeholder]="i18n.t('flow.triggers.schedules.name')"
              [(ngModel)]="newSchedName"
            />
            </label>
            <label class="ck-trig__field">
              {{ i18n.t('flow.triggers.schedules.cron') }}
            <input
              class="ck-trig__input"
              type="text"
              [attr.placeholder]="i18n.t('flow.triggers.schedules.cron')"
              [(ngModel)]="newSchedCron"
            />
            </label>
            <label class="ck-trig__field">
              {{ i18n.t('flow.triggers.schedules.timezone') }}
              <input class="ck-trig__input" type="text" placeholder="Europe/Paris"
                [(ngModel)]="newSchedTimezone" />
            </label>
            <label class="ck-trig__field">
              {{ i18n.t('flow.triggers.schedules.payload') }}
              <textarea class="ck-trig__input ck-trig__json" rows="3" spellcheck="false"
                [(ngModel)]="newSchedPayload"></textarea>
            </label>
            <p class="ck-trig__muted">{{ i18n.t('flow.triggers.setup_note') }}</p>
            @if (scheduleError(); as error) {
              <p class="ck-trig__error" role="alert">{{ i18n.t(error) }}</p>
            }
            <button
              type="button"
              class="ck-trig__btn"
              [disabled]="busy() || !newSchedCron.trim()"
              (click)="createSchedule()"
            >
              <ck-glyph name="bolt" [size]="12" color="currentColor" />
              {{ i18n.t('flow.triggers.save_paused') }}
            </button>
            </div>
          </details>
        }

      }
      @if (kind() === 'webhook') {
        <span class="ck-trig__label">{{ i18n.t('flow.triggers.webhooks') }}</span>
        <p class="ck-trig__muted">{{ i18n.t('flow.triggers.webhooks.delivery_note') }}</p>

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

          <details class="ck-trig__setup" [open]="hookFormOpen()" (toggle)="hookFormOpen.set($any($event.target).open)">
            <summary>{{ i18n.t('flow.triggers.webhooks.create') }}</summary>
            <div class="ck-trig__form">
            <label class="ck-trig__field">
              {{ i18n.t('flow.triggers.webhooks.name') }}
            <input
              class="ck-trig__input"
              type="text"
              [attr.placeholder]="i18n.t('flow.triggers.webhooks.name')"
              [(ngModel)]="newHookName"
            />
            </label>
            <p class="ck-trig__muted">{{ i18n.t('flow.triggers.webhooks.signature_note') }}</p>
            <p class="ck-trig__muted">{{ i18n.t('flow.triggers.setup_note') }}</p>
            <button
              type="button"
              class="ck-trig__btn"
              [disabled]="busy()"
              (click)="createHook()"
            >
              <ck-glyph name="bolt" [size]="12" color="currentColor" />
              {{ i18n.t('flow.triggers.save_paused') }}
            </button>
            </div>
          </details>
        }
      }
    </section>
  `,
})
export class FlowTriggersPanelComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly api = inject(ApiService);
  private readonly toastr = inject(ToastrService);
  readonly i18n = inject(I18nService);

  readonly systemId = input.required<string>();
  readonly kind = input<'schedule' | 'webhook'>('schedule');

  readonly schedules = signal<RunSchedule[]>([]);
  readonly hooks = signal<WebhookHook[]>([]);
  readonly schedLoad = signal<LoadState>('loading');
  readonly hookLoad = signal<LoadState>('loading');
  readonly busy = signal(false);
  readonly lastSecret = signal<string | null>(null);
  readonly scheduleError = signal<string | null>(null);
  readonly scheduleFormOpen = signal(false);
  readonly hookFormOpen = signal(false);

  newSchedName = '';
  newSchedCron = '0 * * * *';
  newSchedTimezone = 'UTC';
  newSchedPayload = '{}';
  newHookName = '';

  constructor() {
    effect(() => {
      const id = this.systemId();
      const kind = this.kind();
      this.lastSecret.set(null);
      this.schedules.set([]);
      this.hooks.set([]);
      this.busy.set(false);
      this.scheduleError.set(null);
      this.scheduleFormOpen.set(false);
      this.hookFormOpen.set(false);
      if (id) {
        if (kind === 'schedule') this.fetchSchedules(id);
        else this.fetchHooks(id);
      }
    });
  }

  nextFire(schedule: RunSchedule): string {
    return scheduleInstant(schedule.next_fire_at, this.i18n.locale(), schedule.timezone);
  }

  hasPayload(payload: Record<string, unknown>): boolean {
    return Object.keys(payload).length > 0;
  }

  payloadText(payload: Record<string, unknown>): string {
    return JSON.stringify(payload, null, 2);
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
    this.api.get<{ schedules: RunSchedule[] }>(`/systems/${id}/schedules`).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        if (id !== this.systemId()) return;
        this.schedules.set(res.schedules ?? []);
        this.schedLoad.set('loaded');
      },
      error: () => { if (id === this.systemId()) this.schedLoad.set('error'); },
    });
  }

  private fetchHooks(id: string): void {
    this.hookLoad.set('loading');
    this.api.get<{ hooks: WebhookHook[] }>(`/systems/${id}/hooks`).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        if (id !== this.systemId()) return;
        this.hooks.set(res.hooks ?? []);
        this.hookLoad.set('loaded');
      },
      error: () => { if (id === this.systemId()) this.hookLoad.set('error'); },
    });
  }

  createSchedule(): void {
    const id = this.systemId();
    const cron = this.newSchedCron.trim();
    if (!id || !cron || this.busy()) return;
    this.scheduleError.set(null);
    const input = schedulePayload(this.newSchedPayload);
    if (input === null) {
      this.scheduleError.set('flow.triggers.schedules.payload_invalid');
      return;
    }
    if (!validScheduleTimezone(this.newSchedTimezone)) {
      this.scheduleError.set('flow.triggers.schedules.timezone_invalid');
      return;
    }
    this.busy.set(true);
    this.api
      .post<RunSchedule>(`/systems/${id}/schedules`, {
        name: this.newSchedName.trim() || this.i18n.t('flow.triggers.schedules.default_name'),
        cron_expr: cron,
        timezone: this.newSchedTimezone.trim(),
        enabled: false,
        input_payload: input,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          if (id !== this.systemId()) return;
          this.schedules.update((list) => [row, ...list]);
          this.scheduleFormOpen.set(false);
          this.busy.set(false);
          this.toastr.success(
            this.i18n.t('flow.triggers.schedules.created'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
        error: (error: { status?: number }) => {
          if (id !== this.systemId()) return;
          this.scheduleError.set(error.status === 400
            ? 'flow.triggers.schedules.cron_invalid'
            : 'flow.triggers.schedules.create_failed');
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
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          if (id !== this.systemId()) return;
          this.schedules.update((list) => list.map((x) => (x.id === row.id ? row : x)));
          this.busy.set(false);
        },
        error: () => {
          if (id !== this.systemId()) return;
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
        name: this.newHookName.trim() || this.i18n.t('flow.triggers.webhooks.default_name'),
        event_type: 'webhook.received',
        enabled: false,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          if (id !== this.systemId()) return;
          this.hooks.update((list) => [row, ...list]);
          this.hookFormOpen.set(false);
          this.lastSecret.set(row.secret ?? null);
          this.busy.set(false);
          this.toastr.success(
            this.i18n.t('flow.triggers.webhooks.created'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
        error: () => {
          if (id !== this.systemId()) return;
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
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          if (id !== this.systemId()) return;
          this.hooks.update((list) => list.map((x) => (x.id === row.id ? row : x)));
          this.busy.set(false);
        },
        error: () => {
          if (id !== this.systemId()) return;
          this.busy.set(false);
          this.toastr.error(
            this.i18n.t('flow.triggers.webhooks.update_failed'),
            this.i18n.t('flow.triggers.toast.title'),
          );
        },
      });
  }
}
