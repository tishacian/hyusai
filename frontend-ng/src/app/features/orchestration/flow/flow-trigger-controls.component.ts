/**
 * `<app-flow-trigger-controls>` — per-System event-trigger piloting, surfaced
 * in the inspector when an SFTP/deposit trigger node is selected.
 *
 * It reads + writes the Phase-3 trigger state through
 * `GET|PATCH /systems/{id}/event-trigger` (which merges into
 * `System.settings['event_trigger']`). It exposes:
 *   - the GLOBAL master switch + the System's effective mode (read-only),
 *   - a dry_run ⇄ live mode toggle,
 *   - the circuit-breaker status with a re-arm (reset) action,
 *   - a deep link to the System's Runs (where `simulated` dry-run journals show).
 *
 * Governance stays code-enforced on the backend — this never bypasses the
 * allowlist; it only sets mode / re-arms the breaker.
 */
import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';

interface EventTriggerState {
  system_id: string;
  master_enabled: boolean;
  mode: string;
  disabled: boolean;
  disabled_reason?: string | null;
  disabled_at?: string | null;
}

type LoadState = 'loading' | 'loaded' | 'error';

@Component({
  selector: 'app-flow-trigger-controls',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  styleUrl: './flow-trigger-controls.component.scss',
  template: `
    <section class="ck-trig">
      <span class="ck-trig__label">{{ i18n.t('flow.triggers.piloting') }}</span>

      @if (loadState() === 'loading') {
        <p class="ck-trig__muted">{{ i18n.t('flow.triggers.piloting.loading') }}</p>
      } @else if (loadState() === 'error') {
        <p class="ck-trig__muted">
          {{ i18n.t('flow.triggers.piloting.error') }}
          <button type="button" class="ck-trig__linkbtn" (click)="reload()">
            {{ i18n.t('flow.triggers.retry') }}
          </button>
        </p>
      } @else if (state(); as s) {
        <dl class="ck-trig__kv">
          <dt>{{ i18n.t('flow.triggers.piloting.global') }}</dt>
          <dd>
            <span class="ck-trig__pill" [attr.data-on]="s.master_enabled">
              {{
                s.master_enabled
                  ? i18n.t('flow.triggers.piloting.global.on')
                  : i18n.t('flow.triggers.piloting.global.off')
              }}
            </span>
          </dd>
          <dt>{{ i18n.t('flow.triggers.piloting.mode') }}</dt>
          <dd>
            <span class="ck-trig__pill" [attr.data-tone]="s.mode === 'live' ? 'live' : 'dry'">
              {{
                s.mode === 'live'
                  ? i18n.t('flow.triggers.piloting.mode.live')
                  : i18n.t('flow.triggers.piloting.mode.dry')
              }}
            </span>
          </dd>
        </dl>

        @if (!s.master_enabled) {
          <p class="ck-trig__muted">{{ i18n.t('flow.triggers.piloting.global.note') }}</p>
        }

        <button
          type="button"
          class="ck-trig__btn"
          [disabled]="busy()"
          (click)="toggleMode(s)"
        >
          <ck-glyph [name]="s.mode === 'live' ? 'pause' : 'play'" [size]="12" color="currentColor" />
          {{
            s.mode === 'live'
              ? i18n.t('flow.triggers.piloting.to_dry')
              : i18n.t('flow.triggers.piloting.to_live')
          }}
        </button>

        @if (s.disabled) {
          <div class="ck-trig__breaker" role="status">
            <div class="ck-trig__breaker-head">
              <ck-glyph name="warn" [size]="13" color="currentColor" />
              <span>{{ i18n.t('flow.triggers.piloting.breaker.open') }}</span>
            </div>
            @if (s.disabled_reason; as reason) {
              <p class="ck-trig__breaker-reason">
                {{ i18n.t('flow.triggers.piloting.breaker.cause', { reason }) }}
              </p>
            }
            <button
              type="button"
              class="ck-trig__btn ck-trig__btn--rearm"
              [disabled]="busy()"
              (click)="rearm()"
            >
              <ck-glyph name="check" [size]="12" color="currentColor" />
              {{ i18n.t('flow.triggers.piloting.breaker.rearm') }}
            </button>
          </div>
        } @else {
          <p class="ck-trig__ok">
            <ck-glyph name="shield" [size]="12" color="currentColor" />
            {{ i18n.t('flow.triggers.piloting.breaker.armed') }}
          </p>
        }

        <a
          class="ck-trig__runs"
          [routerLink]="['/systems', systemId()]"
          [queryParams]="{ facet: 'runs' }"
        >
          <ck-glyph name="ledger" [size]="12" color="currentColor" />
          {{ i18n.t('flow.triggers.piloting.runs') }}
        </a>
      }
    </section>
  `,
})
export class FlowTriggerControlsComponent {
  private readonly api = inject(ApiService);
  private readonly toastr = inject(ToastrService);
  readonly i18n = inject(I18nService);

  /** The System whose triggers we pilot. */
  readonly systemId = input.required<string>();

  readonly state = signal<EventTriggerState | null>(null);
  readonly loadState = signal<LoadState>('loading');
  readonly busy = signal(false);

  constructor() {
    // Re-fetch whenever the bound System changes (single-frame, deterministic).
    effect(() => {
      const id = this.systemId();
      if (id) this.fetch(id);
    });
  }

  reload(): void {
    const id = this.systemId();
    if (id) this.fetch(id);
  }

  private fetch(id: string): void {
    this.loadState.set('loading');
    this.api.get<EventTriggerState>(`/systems/${id}/event-trigger`).subscribe({
      next: (res) => {
        this.state.set(res);
        this.loadState.set('loaded');
      },
      error: () => {
        this.state.set(null);
        this.loadState.set('error');
      },
    });
  }

  toggleMode(s: EventTriggerState): void {
    const next = s.mode === 'live' ? 'dry_run' : 'live';
    this.patch(
      { mode: next },
      this.i18n.t(
        next === 'live'
          ? 'flow.triggers.piloting.live_done'
          : 'flow.triggers.piloting.dry_done',
      ),
    );
  }

  rearm(): void {
    this.patch({ disabled: false }, this.i18n.t('flow.triggers.piloting.breaker.rearmed'));
  }

  private patch(body: { mode?: string; disabled?: boolean }, successMsg: string): void {
    const id = this.systemId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api.patch<EventTriggerState>(`/systems/${id}/event-trigger`, body).subscribe({
      next: (res) => {
        this.state.set(res);
        this.busy.set(false);
        this.toastr.success(successMsg, this.i18n.t('flow.triggers.toast.title'));
      },
      error: () => {
        this.busy.set(false);
        this.toastr.error(
          this.i18n.t('flow.triggers.piloting.failed'),
          this.i18n.t('flow.triggers.toast.title'),
        );
      },
    });
  }
}
