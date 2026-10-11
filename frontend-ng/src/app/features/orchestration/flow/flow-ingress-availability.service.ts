/**
 * `FlowIngressAvailabilityService` — is an event-driven entry point actually
 * live for this System?
 *
 * The Trigger inspector must not offer an entry kind that silently does
 * nothing. Event dispatch is gated by `enable_event_triggers` (global switch
 * OR per-workspace opt-in), which the workspace `settings.features` map the
 * shell already holds does NOT reliably carry — the authoritative reading is
 * the same `GET /systems/{id}/event-trigger` projection the run engine uses.
 *
 * Cached per System and shared, so a keystroke in the inspector never issues a
 * request. `<app-flow-trigger-controls>` keeps its own fetch: it is the
 * piloting surface (mode toggle, circuit breaker) and owns write-back.
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '@app/core/api.service';

interface EventTriggerProjection {
  master_enabled?: boolean;
  global_enabled?: boolean;
  mode?: string;
}

type LoadState = 'idle' | 'loading' | 'loaded' | 'error';

@Injectable({ providedIn: 'root' })
export class FlowIngressAvailabilityService {
  private readonly api = inject(ApiService);

  /** Plain field, not a signal: the fetch guard must never become a
   *  dependency of the render-driven effect that calls `ensureLoaded`. */
  private requestedSystemId: string | null = null;

  private readonly _state = signal<LoadState>('idle');
  private readonly _eventsEnabled = signal(false);
  private readonly _mode = signal<string | null>(null);

  readonly state = this._state.asReadonly();

  /** True once the backend confirmed event triggers can fire for this System.
   *  Unknown (loading / error / never asked) reads as false, so the inspector
   *  never claims an availability it has not observed. */
  readonly eventsEnabled = computed(() => this._state() === 'loaded' && this._eventsEnabled());

  /** `live` or `dry_run`, as the run engine itself resolves it. An enabled
   *  System in `dry_run` records the dispatch without starting a Run. */
  readonly mode = computed(() => (this._state() === 'loaded' ? this._mode() : null));

  /** Fetch once per System. Safe to call from a render-driven effect. */
  ensureLoaded(systemId: string | null): void {
    if (!systemId || this.requestedSystemId === systemId) return;
    this.requestedSystemId = systemId;
    this._state.set('loading');
    this.api
      .get<EventTriggerProjection>(`/systems/${systemId}/event-trigger`)
      .subscribe({
        next: (response) => {
          if (this.requestedSystemId !== systemId) return;
          this._eventsEnabled.set(response?.master_enabled === true);
          this._mode.set(typeof response?.mode === 'string' ? response.mode : null);
          this._state.set('loaded');
        },
        error: () => {
          if (this.requestedSystemId !== systemId) return;
          this._eventsEnabled.set(false);
          this._mode.set(null);
          this._state.set('error');
        },
      });
  }
}
