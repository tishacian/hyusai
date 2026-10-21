import { HttpErrorResponse } from '@angular/common/http';
import { computed, signal } from '@angular/core';
import { TimeoutError, timeout } from 'rxjs';
import type { ExperienceActivationService, ExperienceActivationState } from './experience-activation.service';

/** A write that has not answered after this long has an unknown outcome. */
export const ACTIVATION_WRITE_TIMEOUT_MS = 15_000;

export type ActivationReadState = 'loading' | 'loaded' | 'error';
/**
 * `unknown`: the request may or may not have reached the server (timeout,
 * network, gateway). The control stays locked until the state is read again.
 */
export type ActivationWriteOutcome = 'saving' | 'saved' | 'conflict' | 'unknown' | 'refused' | 'failed';

export function activationWriteOutcome(error: unknown): ActivationWriteOutcome {
  if (error instanceof TimeoutError) return 'unknown';
  if (error instanceof HttpErrorResponse) {
    if (error.status === 409) return 'conflict';
    if (error.status === 401 || error.status === 403) return 'refused';
    if (error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504) {
      return 'unknown';
    }
  }
  return 'failed';
}

/**
 * State of the "Work and Studio" setting for the workspace `slug()` names.
 * A response that lands after the workspace changed is dropped, so one
 * workspace's state never shows under another.
 */
export class ExperienceActivationController {
  readonly readState = signal<ActivationReadState>('loading');
  readonly state = signal<ExperienceActivationState | null>(null);
  readonly outcome = signal<ActivationWriteOutcome | null>(null);
  readonly confirmOpen = signal(false);
  /** Saving, or an outcome nobody can vouch for: no second write until re-read. */
  readonly locked = computed(() => this.outcome() === 'saving' || this.outcome() === 'unknown');

  private openedSlug = '';

  constructor(
    private readonly api: Pick<ExperienceActivationService, 'read' | 'write'>,
    private readonly slug: () => string,
    private readonly afterWrite: () => void,
    private readonly timeoutMs = ACTIVATION_WRITE_TIMEOUT_MS,
  ) {}

  /** Start on a workspace; reopening the same one keeps the current state. */
  open(slug: string): void {
    if (slug === this.openedSlug) return;
    this.openedSlug = slug;
    this.state.set(null);
    this.outcome.set(null);
    this.confirmOpen.set(false);
    this.load();
  }

  load(): void {
    const slug = this.slug();
    this.readState.set('loading');
    this.api.read(slug).subscribe({
      next: (state) => {
        if (slug !== this.slug()) return;
        this.state.set(state);
        this.readState.set('loaded');
        if (this.outcome() === 'unknown') this.outcome.set(null);
      },
      error: () => {
        if (slug !== this.slug()) return;
        this.state.set(null);
        this.readState.set('error');
      },
    });
  }

  apply(): void {
    this.confirmOpen.set(false);
    const current = this.state();
    if (!current || this.locked() || this.readState() !== 'loaded') return;
    const slug = this.slug();
    this.outcome.set('saving');
    this.api.write(slug, !current.enabled, current.enabled)
      .pipe(timeout(this.timeoutMs))
      .subscribe({
        next: (state) => {
          if (slug !== this.slug()) return;
          this.state.set(state);
          this.outcome.set('saved');
          this.afterWrite();
        },
        error: (error: unknown) => {
          if (slug !== this.slug()) return;
          const outcome = activationWriteOutcome(error);
          this.outcome.set(outcome);
          if (outcome === 'conflict') this.load();
        },
      });
  }
}
