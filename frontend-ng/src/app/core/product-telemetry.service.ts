import { Injectable, OnDestroy, inject } from '@angular/core';
import { Router } from '@angular/router';
import { ApiService } from './api.service';
import { I18nService } from './i18n.service';
import type { Locale } from './locale';
import {
  navigationSurfaceForRoute,
  privacySafeNavigationRoute,
} from './navigation-telemetry.service';
import { WorkspaceService } from './workspace.service';
import { AuthStore } from '../store/auth.store';

/**
 * Single namespace for the activation funnel (P2.3). Every product milestone
 * lives under it so an analyst can select the whole funnel with one
 * `event_type_prefix` filter, and so no feature component has to invent an
 * event name of its own.
 */
export const PRODUCT_ACTIVATION_NAMESPACE = 'product.activation';

/**
 * The eight milestones of the supported journey, in funnel order. This list is
 * deliberately closed: anything else belongs to a different telemetry concern.
 */
export type ProductActivationMilestone =
  | 'signed_in'
  | 'model_ready'
  | 'knowledge_added'
  | 'first_question_sent'
  | 'first_answer_completed'
  | 'source_opened'
  | 'failure_recovered'
  | 'system_published';

export const PRODUCT_ACTIVATION_MILESTONES: readonly ProductActivationMilestone[] = [
  'signed_in',
  'model_ready',
  'knowledge_added',
  'first_question_sent',
  'first_answer_completed',
  'source_opened',
  'failure_recovered',
  'system_published',
] as const;

/** Stable audit `event_type` per milestone. Written out for greppability. */
export const PRODUCT_ACTIVATION_EVENTS: Readonly<Record<ProductActivationMilestone, string>> =
  Object.freeze({
    signed_in: 'product.activation.signed_in',
    model_ready: 'product.activation.model_ready',
    knowledge_added: 'product.activation.knowledge_added',
    first_question_sent: 'product.activation.first_question_sent',
    first_answer_completed: 'product.activation.first_answer_completed',
    source_opened: 'product.activation.source_opened',
    failure_recovered: 'product.activation.failure_recovered',
    system_published: 'product.activation.system_published',
  });

/**
 * Which failed action the user got back from. Closed set, because the funnel
 * asks "which failures are recoverable in practice", not "what went wrong".
 */
export type ProductRecoveryKind =
  | 'chat_retry'
  | 'model_setup_return'
  | 'model_setup_save'
  | 'knowledge_upload';

/**
 * Coarse elapsed-time buckets. Raw durations are a weak fingerprint and are
 * useless for a funnel anyway; the bucket answers "did this feel fast".
 */
export type ProductElapsedBucket = 'lt_2s' | 'lt_5s' | 'lt_15s' | 'lt_60s' | 'gte_60s';

export function productElapsedBucket(elapsedMs: number): ProductElapsedBucket {
  const elapsed = Math.max(0, elapsedMs);
  if (elapsed < 2_000) return 'lt_2s';
  if (elapsed < 5_000) return 'lt_5s';
  if (elapsed < 15_000) return 'lt_15s';
  if (elapsed < 60_000) return 'lt_60s';
  return 'gte_60s';
}

/**
 * The complete detail contract. Every field is a bounded, enumerable token:
 * a masked route template, a surface id from the navigation catalog, a UI
 * locale, and two optional closed enums. Nothing here can carry prompt or
 * answer text, a filename, a source title, a credential, a provider endpoint,
 * an e-mail address, a raw error, an identifier or any other free user string.
 */
export interface ProductActivationDetails {
  schema_version: 1;
  milestone: ProductActivationMilestone;
  surface: string;
  route: string;
  locale: Locale;
  recovery_kind?: ProductRecoveryKind;
  elapsed_bucket?: ProductElapsedBucket;
}

export interface ProductActivationOptions {
  /**
   * Local-only key that keeps a re-render, a replayed subscription or a
   * double-click from emitting the same occurrence twice. It is never sent.
   */
  dedupeKey?: string;
  recoveryKind?: ProductRecoveryKind;
  /** Measured elapsed time; only its bucket is emitted. */
  elapsedMs?: number;
}

const SESSION_LEDGER_PREFIX = 'agentium:product-activation:v1';
/** Bound the in-memory occurrence guard; a long session must not leak. */
const OCCURRENCE_GUARD_LIMIT = 256;

/**
 * Best-effort activation telemetry for the supported product journey.
 *
 * Feature components call one of the two record methods at an authoritative
 * success point and carry on; nothing here blocks, awaits, throws into the
 * caller, or changes what the user asked for. Route visits are deliberately
 * not instrumented — arriving somewhere is not succeeding at anything.
 */
@Injectable({ providedIn: 'root' })
export class ProductTelemetryService implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthStore);

  /** Fallback ledger when `sessionStorage` is unavailable or refuses writes. */
  private readonly memoryLedger = new Set<string>();
  private readonly occurrenceGuard = new Set<string>();
  private unregisterPrincipalReset: (() => void) | null = null;

  /**
   * Bind the ledger to the authenticated principal's lifetime.
   *
   * Called from an APP_INITIALIZER so the service exists before the first
   * principal transition can happen. A lazily created telemetry service would
   * miss a sign-out that occurred before any instrumented surface was opened,
   * and the next principal in the same tab would inherit the ledger.
   *
   * Idempotent: repeated calls keep the single registration.
   */
  start(): void {
    if (this.unregisterPrincipalReset) return;
    this.unregisterPrincipalReset = this.auth.registerContextReset(() => {
      // AuthStore runs its resetters while the previous principal is still
      // current, so `isAuthenticated()` here describes the state being LEFT.
      //
      // Leaving an authenticated principal is a sign-out or a user switch:
      // the activation session ends and the ledger must not leak into the
      // next principal. Leaving an unauthenticated one is a sign-in — which
      // includes the bootstrap re-validation after a page reload — so a
      // reload inside one authenticated session keeps the ledger and cannot
      // re-emit a "first" milestone that session already recorded.
      if (!this.auth.isAuthenticated()) return;
      this.resetLedger();
    });
  }

  ngOnDestroy(): void {
    this.unregisterPrincipalReset?.();
    this.unregisterPrincipalReset = null;
  }

  /**
   * Record a milestone at most once per authenticated browser session and
   * workspace. This is the required semantics for the "first" question and
   * answer, and the natural semantics for every other funnel step: the funnel
   * asks whether a user reached a milestone, not how often they repeated it.
   */
  recordOnce(milestone: ProductActivationMilestone, options: ProductActivationOptions = {}): void {
    const workspaceSlug = this.workspace.currentSlug();
    if (!workspaceSlug) return;
    const key = `${SESSION_LEDGER_PREFIX}:${workspaceSlug}:${milestone}`;
    if (this.ledgerHas(key)) return;
    this.ledgerAdd(key);
    this.emit(milestone, options);
  }

  /**
   * Record one genuine occurrence of a repeatable milestone. `dedupeKey`
   * identifies the occurrence locally so Angular re-rendering or a retried
   * subscription cannot emit it twice.
   */
  recordOccurrence(
    milestone: ProductActivationMilestone,
    options: ProductActivationOptions & { dedupeKey: string },
  ): void {
    const workspaceSlug = this.workspace.currentSlug();
    if (!workspaceSlug) return;
    const guard = `${workspaceSlug}:${milestone}:${options.dedupeKey}`;
    if (this.occurrenceGuard.has(guard)) return;
    if (this.occurrenceGuard.size >= OCCURRENCE_GUARD_LIMIT) this.occurrenceGuard.clear();
    this.occurrenceGuard.add(guard);
    this.emit(milestone, options);
  }

  private emit(milestone: ProductActivationMilestone, options: ProductActivationOptions): void {
    let details: ProductActivationDetails;
    try {
      const url = this.router.url || '/';
      details = {
        schema_version: 1,
        milestone,
        surface: navigationSurfaceForRoute(url),
        route: privacySafeNavigationRoute(url),
        locale: this.i18n.locale(),
        ...(options.recoveryKind ? { recovery_kind: options.recoveryKind } : {}),
        ...(typeof options.elapsedMs === 'number' && Number.isFinite(options.elapsedMs)
          ? { elapsed_bucket: productElapsedBucket(options.elapsedMs) }
          : {}),
      };
    } catch {
      // A telemetry detail we cannot build safely is one we do not send.
      return;
    }
    try {
      this.api
        .post('/audit', {
          event_type: PRODUCT_ACTIVATION_EVENTS[milestone],
          details,
          severity: 'info',
        })
        .subscribe({
          next: () => {
            // Telemetry never blocks or changes the user action.
          },
          error: () => {
            // Audit ingestion is intentionally best-effort.
          },
        });
    } catch {
      // Neither does a transport that refuses to start.
    }
  }

  private ledgerHas(key: string): boolean {
    if (this.memoryLedger.has(key)) return true;
    try {
      return window.sessionStorage.getItem(key) !== null;
    } catch {
      return false;
    }
  }

  private ledgerAdd(key: string): void {
    this.memoryLedger.add(key);
    try {
      window.sessionStorage.setItem(key, '1');
    } catch {
      // The in-memory ledger still deduplicates for this page.
    }
  }

  private resetLedger(): void {
    this.memoryLedger.clear();
    this.occurrenceGuard.clear();
    try {
      const storage = window.sessionStorage;
      const stale: string[] = [];
      for (let index = 0; index < storage.length; index++) {
        const key = storage.key(index);
        if (key && key.startsWith(`${SESSION_LEDGER_PREFIX}:`)) stale.push(key);
      }
      for (const key of stale) storage.removeItem(key);
    } catch {
      // Clearing memory is enough to stop this page re-using the ledger.
    }
  }
}
