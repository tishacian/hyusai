/**
 * Hash-bound, non-mutating Flow validation sidecar.
 *
 * The backend is the authority. This service only fences its responses to the
 * exact System, editor revision and JSON snapshot that was submitted. A graph
 * edit therefore hides diagnostics synchronously; a late response can never
 * attach itself to a newer graph even when the underlying HTTP request cannot
 * be cancelled in time.
 */
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import {
  CanonicalApiService,
  type FlowValidationIssue,
  type FlowValidationResponse,
} from '@app/core/canonical-api.service';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { FlowSerializerService } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';

export type FlowServerValidationState =
  | 'idle'
  | 'scheduled'
  | 'validating'
  | 'ready'
  | 'error';

interface AcceptedValidation {
  systemId: string;
  revision: number;
  fingerprint: string;
  response: FlowValidationResponse;
}

const VALIDATION_DEBOUNCE_MS = 300;

/** Deterministic JSON identity for the body sent over HTTP. This is not the
 * public SHA (only the server computes that); it prevents an editor revision
 * or future store refactor from accidentally reusing a result for different
 * JSON. */
export function flowValidationFingerprint(value: unknown): string {
  const visit = (item: unknown, inArray = false): unknown => {
    if (item === undefined || typeof item === 'function' || typeof item === 'symbol') {
      return inArray ? null : undefined;
    }
    if (typeof item === 'number' && !Number.isFinite(item)) return null;
    if (item === null || typeof item !== 'object') return item;
    if (Array.isArray(item)) return item.map((entry) => visit(entry, true));
    const source = item as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) {
      const normalized = visit(source[key]);
      if (normalized !== undefined) out[key] = normalized;
    }
    return out;
  };
  return JSON.stringify(visit(value)) ?? 'null';
}

@Injectable()
export class FlowValidationService {
  private readonly i18n = inject(I18nService);
  private readonly store = inject(FlowStore);
  private readonly serializer = inject(FlowSerializerService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService, { optional: true });
  private readonly destroyRef = inject(DestroyRef);

  private readonly boundSystemId = signal<string | null>(null);
  private readonly accepted = signal<AcceptedValidation | null>(null);
  private readonly _state = signal<FlowServerValidationState>('idle');
  private readonly _error = signal<string | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;
  private sequence = 0;
  private lastObservedKey: string | null = null;
  private readonly requests = new Set<Subscription>();

  readonly state = this._state.asReadonly();
  readonly error = this._error.asReadonly();
  readonly validating = computed(() => this._state() === 'validating');

  /** Result only while the live graph is byte-for-byte the captured request
   * body and still has the same monotonic editor revision. */
  readonly currentResult = computed<FlowValidationResponse | null>(() => {
    const accepted = this.accepted();
    if (!accepted || accepted.systemId !== this.boundSystemId()) return null;
    if (accepted.revision !== this.store.revision()) return null;
    if (accepted.fingerprint !== flowValidationFingerprint(this.store.snapshot())) return null;
    return accepted.response;
  });

  readonly currentIssues = computed<FlowValidationIssue[]>(
    () => this.currentResult()?.issues ?? [],
  );
  readonly currentFlowSha256 = computed(
    () => this.currentResult()?.flow_sha256 ?? null,
  );
  readonly currentHasErrors = computed(() => {
    const result = this.currentResult();
    return !!result && (!result.valid || result.issues.some((issue) => issue.level === 'error'));
  });

  constructor() {
    const unregisterWorkspaceReset = this.workspace?.registerContextReset(() => {
      this.bindSystem(null);
    });
    this.destroyRef.onDestroy(() => {
      unregisterWorkspaceReset?.();
      this.cancelTimer();
      for (const request of this.requests) request.unsubscribe();
      this.requests.clear();
    });
  }

  /** Bind only after strict hydration has succeeded. Rebinding, including to
   * the same id after reload/rollback, starts a fresh response generation. */
  bindSystem(systemId: string | null): void {
    this.cancelTimer();
    this.sequence += 1;
    this.boundSystemId.set(systemId);
    this.accepted.set(null);
    this._error.set(null);
    this._state.set('idle');
    this.lastObservedKey = null;
  }

  /** Called by the Builder's revision effect. Repeated observations of the
   * same graph are free; a real edit invalidates all in-flight generations
   * immediately and schedules a fresh server analysis. */
  observeCurrentFlow(): void {
    const systemId = this.boundSystemId();
    if (!systemId) return;
    const key = this.captureKey(systemId);
    if (key === this.lastObservedKey) return;
    this.lastObservedKey = key;
    this.cancelTimer();
    this.sequence += 1;
    this._error.set(null);
    this._state.set('scheduled');
    this.timer = setTimeout(() => {
      this.timer = null;
      this.validateNow();
    }, VALIDATION_DEBOUNCE_MS);
  }

  /** Force analysis now (used on initial hydration and available to explicit
   * Validate controls). The sequence fence, not request cancellation, is the
   * correctness boundary for out-of-order responses. */
  validateNow(): void {
    this.cancelTimer();
    const systemId = this.boundSystemId();
    if (!systemId) return;

    const revision = this.store.revision();
    const snapshot = this.store.snapshot();
    // Save hashes annotateSidecars(snapshot). Validate the same tree, or the
    // returned flow_sha256 never equals savedFlowSha256 and Execute stays locked.
    const flow = this.serializer.annotateSidecars(snapshot);
    const fingerprint = flowValidationFingerprint(snapshot);
    this.lastObservedKey = this.captureKey(systemId, revision, fingerprint);
    const requestSequence = ++this.sequence;
    const scope = this.workspace?.captureRequestScope() ?? null;
    this._state.set('validating');
    this._error.set(null);

    const request = this.canonical
      .validateSystemFlow(systemId, flow as unknown as Record<string, unknown>)
      .subscribe({
        next: (response) => {
          if (
            requestSequence !== this.sequence ||
            !this.contextIsCurrent(systemId, revision, fingerprint, scope)
          ) {
            return;
          }
          this.accepted.set({ systemId, revision, fingerprint, response });
          this._state.set('ready');
          this._error.set(null);
        },
        error: () => {
          if (
            requestSequence !== this.sequence ||
            !this.contextIsCurrent(systemId, revision, fingerprint, scope)
          ) {
            return;
          }
          this.accepted.set(null);
          this._state.set('error');
          this._error.set(this.i18n.t('flow.validation.error.server'));
        },
      });
    if (!request.closed) {
      this.requests.add(request);
      request.add(() => this.requests.delete(request));
    }
  }

  private captureKey(
    systemId: string,
    revision = this.store.revision(),
    fingerprint = flowValidationFingerprint(this.store.snapshot()),
  ): string {
    return `${systemId}\u0000${revision}\u0000${fingerprint}`;
  }

  private contextIsCurrent(
    systemId: string,
    revision: number,
    fingerprint: string,
    scope: WorkspaceRequestScope | null,
  ): boolean {
    return (
      this.boundSystemId() === systemId &&
      this.store.revision() === revision &&
      flowValidationFingerprint(this.store.snapshot()) === fingerprint &&
      (scope === null || !this.workspace || this.workspace.isRequestScopeCurrent(scope))
    );
  }

  private cancelTimer(): void {
    if (!this.timer) return;
    clearTimeout(this.timer);
    this.timer = null;
  }
}
