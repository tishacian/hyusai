/**
 * `<app-flow-trigger-controls>` — per-System event-trigger piloting, surfaced
 * in the inspector when an SFTP/deposit trigger node is selected.
 *
 * It reads + writes the Phase-3 trigger state through
 * `GET|PATCH /systems/{id}/event-trigger` (which merges into
 * `System.settings['event_trigger']`). It exposes:
 *   - the GLOBAL master switch + the System's effective mode (read-only),
 *   - a dry_run ⇄ live mode toggle,
 *   - the circuit-breaker status with a "Réarmer" (reset) action,
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
      <span class="ck-trig__label">Pilotage des déclencheurs</span>

      @if (loadState() === 'loading') {
        <p class="ck-trig__muted">Chargement de l'état…</p>
      } @else if (loadState() === 'error') {
        <p class="ck-trig__muted">
          État indisponible.
          <button type="button" class="ck-trig__linkbtn" (click)="reload()">Réessayer</button>
        </p>
      } @else if (state(); as s) {
        <dl class="ck-trig__kv">
          <dt>Global</dt>
          <dd>
            <span class="ck-trig__pill" [attr.data-on]="s.master_enabled">
              {{ s.master_enabled ? 'Activés' : 'Désactivés' }}
            </span>
          </dd>
          <dt>Mode système</dt>
          <dd>
            <span class="ck-trig__pill" [attr.data-tone]="s.mode === 'live' ? 'live' : 'dry'">
              {{ s.mode === 'live' ? 'Live' : 'Dry-run' }}
            </span>
          </dd>
        </dl>

        @if (!s.master_enabled) {
          <p class="ck-trig__muted">
            Les déclencheurs sont désactivés globalement — le mode ci-dessous ne s'applique
            qu'une fois activés au niveau de la plateforme.
          </p>
        }

        <button
          type="button"
          class="ck-trig__btn"
          [disabled]="busy()"
          (click)="toggleMode(s)"
        >
          <ck-glyph [name]="s.mode === 'live' ? 'pause' : 'play'" [size]="12" color="currentColor" />
          {{ s.mode === 'live' ? 'Repasser en dry-run' : 'Passer en live' }}
        </button>

        @if (s.disabled) {
          <div class="ck-trig__breaker" role="status">
            <div class="ck-trig__breaker-head">
              <ck-glyph name="warn" [size]="13" color="currentColor" />
              <span>Circuit ouvert — déclencheur désarmé</span>
            </div>
            @if (s.disabled_reason) {
              <p class="ck-trig__breaker-reason">Cause : {{ s.disabled_reason }}</p>
            }
            <button
              type="button"
              class="ck-trig__btn ck-trig__btn--rearm"
              [disabled]="busy()"
              (click)="rearm()"
            >
              <ck-glyph name="check" [size]="12" color="currentColor" />
              Réarmer
            </button>
          </div>
        } @else {
          <p class="ck-trig__ok">
            <ck-glyph name="shield" [size]="12" color="currentColor" />
            Circuit armé
          </p>
        }

        <a
          class="ck-trig__runs"
          [routerLink]="['/systems', systemId()]"
          [queryParams]="{ facet: 'runs' }"
        >
          <ck-glyph name="ledger" [size]="12" color="currentColor" />
          Voir les runs déclenchés
        </a>
      }
    </section>
  `,
})
export class FlowTriggerControlsComponent {
  private readonly api = inject(ApiService);
  private readonly toastr = inject(ToastrService);

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
    this.patch({ mode: next }, next === 'live' ? 'Mode live activé.' : 'Mode dry-run rétabli.');
  }

  rearm(): void {
    this.patch({ disabled: false }, 'Déclencheur réarmé.');
  }

  private patch(body: { mode?: string; disabled?: boolean }, successMsg: string): void {
    const id = this.systemId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api.patch<EventTriggerState>(`/systems/${id}/event-trigger`, body).subscribe({
      next: (res) => {
        this.state.set(res);
        this.busy.set(false);
        this.toastr.success(successMsg, 'Déclencheurs');
      },
      error: () => {
        this.busy.set(false);
        this.toastr.error('La mise à jour du déclencheur a échoué.', 'Déclencheurs');
      },
    });
  }
}
