/**
 * `FlowRecipeService` — the builder's window onto the managed Python
 * environment a recipe node declares.
 *
 * One instance per builder shell (provided next to the other flow services):
 * the inspector summary and the recipe workshop read the SAME resolved env,
 * so opening the workshop never re-asks what the inspector already knows.
 * Resolution is deduplicated by the normalized spec (requirements + registry
 * fields): editing the spec is what invalidates the cached row.
 *
 * The service never mutates the graph. It only talks to the recipe plane API:
 * `resolve` (spec → env row), `build` ("prepare now") and a bounded watch that
 * follows a `building` env to its settled state.
 */
import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  CanonicalApiService,
  type PythonEnvDto,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { recipeSpecKey, type RecipeNodeParams } from './flow-recipe.vm';

/** A `building` env is refreshed at this cadence until it settles. */
const ENV_WATCH_INTERVAL_MS = 2_000;
/** Bounded watch: covers the server-side build timeout with margin. */
const ENV_WATCH_MAX_ATTEMPTS = 360;

export type FlowRecipeEnvState = 'idle' | 'resolving' | 'resolved' | 'error';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

@Injectable()
export class FlowRecipeService {
  private readonly canonical = inject(CanonicalApiService);
  private readonly i18n = inject(I18nService);
  private readonly destroyRef = inject(DestroyRef);

  readonly env = signal<PythonEnvDto | null>(null);
  /** Deployment switch from the API envelope; null until first resolve. */
  readonly featureEnabled = signal<boolean | null>(null);
  readonly state = signal<FlowRecipeEnvState>('idle');
  readonly error = signal<string | null>(null);
  /** True while a "prepare now" dispatch or its watch is in flight. */
  readonly preparing = signal(false);
  /** Spec key of the row currently held — lets callers detect staleness. */
  readonly resolvedKey = signal<string | null>(null);

  private resolvedSpecKey: string | null = null;
  private inflight: Promise<PythonEnvDto | null> | null = null;
  private watchTimer: ReturnType<typeof setInterval> | null = null;
  private watchAttempts = 0;

  constructor() {
    this.destroyRef.onDestroy(() => this.stopWatch());
  }

  /**
   * Resolve the env row for a spec, deduplicated by spec key. `force`
   * re-resolves the same spec (refresh button, post-build confirmation).
   */
  async ensureResolved(
    params: RecipeNodeParams,
    force = false,
  ): Promise<PythonEnvDto | null> {
    const key = recipeSpecKey(params);
    if (!force && key === this.resolvedSpecKey && this.state() === 'resolved') {
      return this.env();
    }
    if (this.inflight && key === this.resolvedSpecKey) return this.inflight;

    this.stopWatch();
    this.resolvedSpecKey = key;
    this.resolvedKey.set(key);
    this.state.set('resolving');
    this.error.set(null);
    const request = (async () => {
      try {
        const response = await firstValueFrom(
          this.canonical.resolvePythonEnv({
            requirements_text: params.requirements_text,
            index_url: params.index_url.trim() || null,
            extra_index_urls: params.extra_index_urls
              .map((url) => url.trim())
              .filter(Boolean),
          }),
        );
        if (this.resolvedSpecKey !== key) return this.env();
        this.env.set(response.env);
        this.featureEnabled.set(response.feature?.enabled ?? null);
        this.state.set('resolved');
        if (response.env.status === 'building') this.startWatch();
        return response.env;
      } catch (error: unknown) {
        if (this.resolvedSpecKey !== key) return this.env();
        this.env.set(null);
        this.state.set('error');
        this.error.set(this.errorMessage(error));
        return null;
      } finally {
        if (this.resolvedSpecKey === key) this.inflight = null;
      }
    })();
    this.inflight = request;
    return request;
  }

  /** "Prepare now": dispatch the async build, then follow it to settled. */
  async prepare(): Promise<void> {
    const env = this.env();
    if (!env || this.preparing()) return;
    this.preparing.set(true);
    this.error.set(null);
    try {
      const response = await firstValueFrom(this.canonical.buildPythonEnv(env.id));
      this.env.set(response.env);
      if (response.env.status === 'building' || response.env.status === 'pending') {
        this.startWatch();
      } else {
        this.preparing.set(false);
      }
    } catch (error: unknown) {
      this.error.set(this.errorMessage(error));
      this.preparing.set(false);
    }
  }

  /** Re-read the current env row once (used by the watch and the refresh). */
  async refresh(): Promise<void> {
    const env = this.env();
    if (!env) return;
    try {
      const response = await firstValueFrom(this.canonical.getPythonEnv(env.id));
      // Only accept the row if the spec has not moved on meanwhile.
      if (this.env()?.id === response.env.id) {
        this.env.set(response.env);
        this.featureEnabled.set(response.feature?.enabled ?? this.featureEnabled());
      }
    } catch {
      // Transient read fault: the next tick retries; resolve errors stay loud.
    }
  }

  /** Drop the cache so the next `ensureResolved` asks the server again. */
  invalidate(): void {
    this.stopWatch();
    this.resolvedSpecKey = null;
    this.resolvedKey.set(null);
    this.inflight = null;
    this.env.set(null);
    this.state.set('idle');
    this.error.set(null);
  }

  private startWatch(): void {
    this.stopWatch();
    this.preparing.set(true);
    this.watchAttempts = 0;
    this.watchTimer = setInterval(() => {
      this.watchAttempts += 1;
      const env = this.env();
      const active = env && (env.status === 'building' || env.status === 'pending');
      if (!active || this.watchAttempts > ENV_WATCH_MAX_ATTEMPTS) {
        this.stopWatch();
        return;
      }
      void this.refresh();
    }, ENV_WATCH_INTERVAL_MS);
  }

  private stopWatch(): void {
    if (this.watchTimer !== null) {
      clearInterval(this.watchTimer);
      this.watchTimer = null;
    }
    this.preparing.set(false);
  }

  /** Canonical `{code, message}` payloads become their message; anything else
   * becomes the shared transport sentence. */
  errorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detail = isRecord(error.error) ? error.error['detail'] : null;
      if (isRecord(detail) && typeof detail['message'] === 'string') return detail['message'];
      if (typeof detail === 'string' && detail) return detail;
      return this.i18n.t('flow.workbench.error.http', { status: error.status || 'network' });
    }
    return error instanceof Error && error.message
      ? error.message
      : this.i18n.t('flow.workbench.error.failed');
  }
}
