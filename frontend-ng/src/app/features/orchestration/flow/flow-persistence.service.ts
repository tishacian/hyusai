/**
 * FlowPersistenceService — P4 persistence / autosave / export·share·import.
 *
 * Component-scoped (provided by `FlowBuilderComponent`, not `providedIn: 'root'`)
 * so the toolbar, versions panel and validation strip resolve the same service
 * and `FlowStore` instance for the routed builder. It owns no graph
 * state — it only reads `store.snapshot()` and pushes back through the store's
 * public API (`load`, `markSaved`).
 *
 * Responsibilities (plan §4 / P4):
 *   - Scratchpad draft (no systemId): persist to `localStorage`, restore on
 *     load, and promote into a real System via the existing
 *     `CanonicalApiService` create + save path.
 *   - Debounced autosave when `store.dirty()` flips: draft → localStorage for
 *     the scratchpad, backend `saveSystemFlow` for a bound System. Explicit
 *     `saveState` (saved / unsaved / saving / error). Calls `store.markSaved()`
 *     on success.
 *   - Export JSON + shareable link (round-trips losslessly through
 *     `store.load`).
 *   - Keyboard: this service is the SINGLE owner of the builder's global
 *     shortcuts (one `document` listener, cleaned up on destroy) so nothing
 *     double-fires: Ctrl/Cmd+S save, Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z and
 *     Ctrl+Y redo, Delete/Backspace removes the selected node (ignored inside
 *     fields, controls, dialogs and ARIA interaction surfaces). The shell no
 *     longer binds any shortcuts.
 *
 * This service is deliberately self-contained: it does not edit the shell.
 */
import {
  DestroyRef,
  Injectable,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { Subscription } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type SystemFlowDiff,
  type SystemFlowDraftSaveResult,
  type SystemFlowState,
  type System,
  type SystemStatus,
} from '@app/core/canonical-api.service';
import {
  FlowSerializerService,
  type CanonicalFlow,
} from '@app/core/flow-serializer.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { FlowStore } from './flow.store';
import { FlowManifestService } from './flow-manifest.service';
import {
  FlowValidationService,
  flowValidationFingerprint,
} from './flow-validation.service';
import { blocksFlowDeleteShortcut } from './flow-keyboard-target.vm';
import { emptyScratchFlow } from './flow.types';
import {
  clearWorkspaceFlowDraft,
  persistWorkspaceFlowDraft,
  readWorkspaceFlowDraft,
} from './flow-draft.storage';

/** Explicit, user-visible persistence state surfaced in the toolbar pill. */
export type SaveState = 'saved' | 'unsaved' | 'saving' | 'error';

/** A bulk or server-conflict state that deliberately suspends autosave. */
export type FlowReviewReason =
  | 'clear'
  | 'import'
  | 'share'
  | 'destructive-change'
  | 'conflict';

/** What kicked off a persist — only manual/promote surface success toasts. */
type SaveTrigger = 'autosave' | 'manual';

/** Idle window before an edit is flushed. Coalesces rapid edits/drags into a
 *  single persist (and, for bound Systems, a single backend version). */
const AUTOSAVE_DEBOUNCE_MS = 1200;

/** URL-safe base64 of a UTF-8 string (share-link payload). */
function encodeFlowPayload(json: string): string {
  const bytes = new TextEncoder().encode(json);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function decodeFlowPayload(encoded: string): string {
  const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function isPortList(value: unknown): boolean {
  return (
    value === undefined ||
    (Array.isArray(value) &&
      value.every(
        (port) =>
          !!port &&
          typeof port === 'object' &&
          !Array.isArray(port) &&
          typeof (port as { name?: unknown }).name === 'string' &&
          ((port as { schema?: unknown }).schema === undefined ||
            typeof (port as { schema?: unknown }).schema === 'string'),
      ))
  );
}

function isFlowLike(value: unknown): value is CanonicalFlow {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const candidate = value as {
    nodes?: unknown;
    edges?: unknown;
    variable_namespaces?: unknown;
  };
  return (
    (candidate.variable_namespaces === undefined ||
      (Array.isArray(candidate.variable_namespaces) &&
        candidate.variable_namespaces.every((item) => typeof item === 'string'))) &&
    Array.isArray(candidate.nodes) &&
    candidate.nodes.every(
      (node) =>
        !!node &&
        typeof node === 'object' &&
        !Array.isArray(node) &&
        typeof (node as { id?: unknown }).id === 'string' &&
        isPortList((node as { inputs?: unknown }).inputs) &&
        isPortList((node as { outputs?: unknown }).outputs) &&
        ((node as { config?: unknown }).config === undefined ||
          (!!(node as { config?: unknown }).config &&
            typeof (node as { config?: unknown }).config === 'object' &&
            !Array.isArray((node as { config?: unknown }).config))),
    ) &&
    Array.isArray(candidate.edges) &&
    candidate.edges.every(
      (edge) =>
        !!edge &&
        typeof edge === 'object' &&
        !Array.isArray(edge) &&
        typeof (edge as { from?: unknown }).from === 'string' &&
        typeof (edge as { to?: unknown }).to === 'string',
    )
  );
}

function cloneFlow(flow: CanonicalFlow): CanonicalFlow {
  return structuredClone(flow);
}

/** Explicit NULL/empty is a real legacy persisted state. A missing field or a
 * partially-shaped payload is a protocol failure and must stay fail-closed. */
function canonicalPersistedFlow(value: unknown): CanonicalFlow | null {
  if (value === null) return { nodes: [], edges: [] };
  if (value === undefined) return null;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).length === 0) return { nodes: [], edges: [] };
  return isFlowLike(record) ? (record as unknown as CanonicalFlow) : null;
}

const CONTROL_KINDS = new Set([
  'decision',
  'fork',
  'join',
  'loop',
  'retry',
  'hitl',
  'subflow',
]);

@Injectable()
export class FlowPersistenceService {
  private readonly store = inject(FlowStore);
  private readonly serializer = inject(FlowSerializerService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly manifest = inject(FlowManifestService);
  private readonly validation = inject(FlowValidationService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly toastr = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly workspace = inject(WorkspaceService);

  /** The System this builder is bound to, or `null` for the scratchpad. */
  readonly systemId = signal<string | null>(null);
  readonly hydrationReady = signal(false);
  readonly hydrationError = signal<string | null>(null);
  readonly promoting = signal(false);
  /** Hash of the authoritative saved Flow. Execute uses it as both a local
   * readiness gate and the backend optimistic precondition. */
  readonly savedFlowSha256 = signal<string | null>(null);
  /** True only after `/flow-state` has hydrated the server draft. In this
   * mode `System.flow_definition` is never an editor source or write target. */
  readonly publicationMode = signal(false);
  readonly draftRevision = signal<number | null>(null);
  readonly draftBasePublishedVersionId = signal<string | null>(null);
  readonly publishedVersionId = signal<string | null>(null);
  readonly publishedVersionNumber = signal<number | null>(null);
  readonly publishedFlowSha256 = signal<string | null>(null);
  /** Exact immutable execution contract pinned to the published version.
   * Mutable drafts deliberately have no equivalent pinned contract. */
  readonly publishedExecutionContract = signal<Record<string, unknown> | null>(null);
  readonly publishedContractReady = signal(false);
  readonly draftUpdatedAt = signal<string | null>(null);
  readonly draftMatchesPublished = computed(
    () =>
      this.publicationMode() &&
      this.savedFlowSha256() !== null &&
      this.savedFlowSha256() === this.publishedFlowSha256(),
  );
  readonly lastSavedAt = signal<number | null>(null);
  readonly draftAvailable = signal(false);
  readonly autosavePaused = signal(false);
  /** Ephemeral authoring hold: while the in-builder Workbench is open, its
   * dirty snapshot must remain genuinely unsaved. Manual Save is still an
   * explicit operator action and is therefore never blocked by this hold. */
  readonly workbenchAutosaveHeld = signal(false);
  private readonly autosaveSuspended = computed(
    () => this.autosavePaused() || this.workbenchAutosaveHeld(),
  );
  readonly reviewRequired = signal<FlowReviewReason | null>(null);
  readonly replacementConfirmationRequested = signal(false);
  private readonly externalMutationPending = signal(false);

  /** Explicit publication review state. A publish request is impossible
   * until the currently saved draft diff has been fetched and rendered. */
  readonly publishReviewOpen = signal(false);
  readonly publishDiff = signal<SystemFlowDiff | null>(null);
  readonly publishDiffState = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  readonly publishError = signal<string | null>(null);
  readonly publishing = signal(false);
  readonly publishSucceeded = signal(false);
  readonly breakingChangeAcknowledged = signal(false);

  /** Hash-bound analyser state exposed to the strip and Execute gate. Unlike
   * historical save-response warnings, these computed values disappear on the
   * first graph edit and can never describe another revision. */
  readonly serverIssues = this.validation.currentIssues;
  readonly serverValidation = this.validation.currentResult;
  readonly serverValidationState = this.validation.state;
  readonly serverValidationError = this.validation.error;
  /** Drafts deliberately remain saveable while semantically invalid; Publish
   * and Execute stay hard-gated by the hash-bound analyser. */
  readonly saveValidationBlocked = computed(
    () => !this.publicationMode() && this.validation.currentHasErrors(),
  );

  private readonly saving = signal(false);
  private readonly errored = signal(false);
  readonly actionsDisabled = computed(
    () =>
      !this.hydrationReady() ||
      this.saving() ||
      this.publishing() ||
      this.promoting() ||
      this.externalMutationPending() ||
      this.reviewRequired() === 'conflict',
  );

  /** Explicit save state for the toolbar — derived so it can never drift from
   *  the store's `dirty` flag. */
  readonly saveState = computed<SaveState>(() => {
    if (this.saving()) return 'saving';
    if (this.errored()) return 'error';
    return this.store.dirty() ? 'unsaved' : 'saved';
  });

  readonly publicationBlockReason = computed<string | null>(() => {
    if (!this.publicationMode()) return 'Server Draft/Publish is not enabled for this workspace.';
    if (!this.hydrationReady()) return 'Reload the authoritative server draft first.';
    if (this.actionsDisabled()) return 'Wait for the current write to finish.';
    if (this.store.dirty() || this.saveState() !== 'saved') {
      return 'Save the current draft before reviewing publication.';
    }
    const draftHash = this.savedFlowSha256();
    const draftRevision = this.draftRevision();
    if (!draftHash || draftRevision === null || !this.publishedVersionId()) {
      return 'The draft publication preconditions are incomplete. Reload it.';
    }
    if (this.draftMatchesPublished() && this.publishedContractReady()) {
      return 'The draft already matches the published Flow.';
    }
    const validation = this.serverValidation();
    if (!validation || validation.flow_sha256 !== draftHash) {
      return this.serverValidationState() === 'error'
        ? 'The saved draft could not be validated.'
        : 'Validate the saved draft before publication.';
    }
    if (!validation.valid || validation.issues.some((issue) => issue.level === 'error')) {
      return 'Fix the current Flow diagnostics before publication.';
    }
    return null;
  });
  /** Reopen the published application's handoff without inventing another
   * release or requiring validation of an unchanged draft. */
  readonly canOpenPublishedHome = computed(() =>
    this.workspace.experienceStudioV1Enabled()
    && this.publicationMode() && !this.actionsDisabled()
    && !this.store.dirty() && this.saveState() === 'saved'
    && this.draftMatchesPublished() && this.publishedContractReady()
    && this.publishedExecutionContract() !== null
    && !!this.systemId() && !!this.publishedVersionId(),
  );
  readonly canReviewPublication = computed(() =>
    this.publicationBlockReason() === null || this.canOpenPublishedHome(),
  );
  readonly canConfirmPublication = computed(() => {
    const diff = this.publishDiff();
    if (
      !this.publishReviewOpen() ||
      this.publishDiffState() !== 'ready' ||
      !diff ||
      this.publishing() ||
      this.publicationBlockReason() !== null
    ) {
      return false;
    }
    return diff.summary.breaking === 0 || this.breakingChangeAcknowledged();
  });

  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;
  private promotionRequest: Subscription | null = null;
  private backendSaveRequest: Subscription | null = null;
  private publicationRequest: Subscription | null = null;
  private publicationDiffRequest: Subscription | null = null;
  /** Suppresses autosave retry-storms after a failed save until the user edits
   *  again. Plain field (non-reactive) on purpose. */
  private autosaveBlocked = false;
  private lastRevision = -1;
  private baselineFlow: CanonicalFlow | null = null;
  readonly systemStatus = signal<SystemStatus | null>(null);
  readonly systemDisplayName = signal<string | null>(null);
  /** One-shot authority, scoped to the exact graph revision the user saw. */
  private replacementIntentRevision: number | null = null;
  private sharePayloadPending = false;

  constructor() {
    const unregisterWorkspaceReset = this.workspace.registerContextReset((transition) => {
      this.cancelWorkspaceWrites();
      if (this.autosaveTimer) {
        clearTimeout(this.autosaveTimer);
        this.autosaveTimer = null;
      }
      this.autosaveBlocked = false;
      this.errored.set(false);
      this.savedFlowSha256.set(null);
      this.resetPublicationState();
      this.consumeShareLink();
      this.resetReviewGate();

      // A scratchpad is tenant-owned live state, not just a tenant-owned key.
      // Replace A's in-memory graph synchronously before B becomes current so
      // a pending/manual save can never copy A's graph into B's slot.
      if (!this.systemId()) {
        const nextDraft = this.readDraftRecord(transition.nextSlug);
        this.store.load(nextDraft?.flow ?? emptyScratchFlow());
        this.baselineFlow = cloneFlow(this.store.snapshot());
        this.hydrationReady.set(true);
        this.hydrationError.set(null);
        this.lastSavedAt.set(nextDraft?.savedAt ?? null);
        this.draftAvailable.set(nextDraft !== null);
        this.lastRevision = this.store.revision();
      } else {
        // A bound System must be fetched again in its new tenant context. Do
        // not leave the old graph interactive while the routed component dies.
        this.hydrationReady.set(false);
      }
    });

    this.systemId.set(this.readSystemId());
    this.draftAvailable.set(this.hasDraft());

    effect(() => {
      const revision = this.store.revision();
      const dirty = this.store.dirty();
      const changed = revision !== this.lastRevision;
      this.lastRevision = revision;
      if (changed) {
        this.autosaveBlocked = false;
        this.errored.set(false);
        if (
          this.hydrationReady() &&
          this.systemStatus() === 'active' &&
          this.isDestructiveReplacement(this.store.snapshot()) &&
          !this.autosavePaused()
        ) {
          this.pauseForReview('destructive-change');
        }
      }
      if (
        !this.hydrationReady() ||
        !dirty ||
        this.saving() ||
        this.promoting() ||
        this.autosaveBlocked ||
        this.autosaveSuspended()
      ) {
        return;
      }
      if (!changed) return;
      this.scheduleAutosave();
    });

    const onKeydown = (event: KeyboardEvent) => this.handleKeydown(event);
    document.addEventListener('keydown', onKeydown);
    this.destroyRef.onDestroy(() => {
      unregisterWorkspaceReset();
      this.cancelWorkspaceWrites();
      document.removeEventListener('keydown', onKeydown);
      if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    });
  }

  // ---- public actions (toolbar / shortcuts) --------------------------------

  /** Single scratchpad hydration owner. Shared links are untrusted bulk edits,
   *  while a workspace draft/default is an authoritative clean baseline. */
  hydrateScratch(): void {
    if (this.systemId()) return;
    this.cancelAutosave();
    this.resetReviewGate();
    this.hydrationError.set(null);
    this.savedFlowSha256.set(null);

    const shared = this.readShareLink();
    const draft = this.readDraftRecord(this.workspace.currentSlug());
    this.sharePayloadPending = shared !== null;
    this.store.load(draft?.flow ?? emptyScratchFlow());
    this.baselineFlow = cloneFlow(this.store.snapshot());
    this.lastSavedAt.set(draft?.savedAt ?? null);
    this.draftAvailable.set(draft !== null);
    if (shared) {
      this.pauseForReview('share');
      this.store.replaceAsEdit(shared);
      this.toastr.info(
        'Shared flow loaded for review. Autosave is paused until you save it.',
        'Flow builder',
      );
    } else {
      if (draft) this.toastr.info('Restored your local draft.', 'Scratchpad');
    }

    this.hydrationReady.set(true);
    this.lastRevision = this.store.revision();
  }

  /** Enter a strict reload barrier before issuing the GET. The old graph stays
   *  in memory only as an inert recovery aid; no editor action can reach it. */
  beginHydration(): void {
    this.cancelAutosave();
    this.cancelWorkspaceWrites();
    this.hydrationReady.set(false);
    this.hydrationError.set(null);
    this.savedFlowSha256.set(null);
    this.resetPublicationState();
    this.replacementConfirmationRequested.set(false);
  }

  /** Hydrate a bound System exactly as persisted. Empty stays empty; malformed
   *  payloads fail closed and never fall back to the starter graph. */
  hydrateSystem(system: System): boolean {
    if (this.systemId() && system.id !== this.systemId()) {
      this.markHydrationFailed('The loaded System does not match this route.');
      return false;
    }
    const flow = canonicalPersistedFlow(system.flow_definition);
    if (!flow) {
      this.markHydrationFailed(
        'This System returned a malformed flow. Reload is blocked to protect it.',
      );
      return false;
    }

    this.cancelAutosave();
    // Authoritative hydration (including rollback) supersedes every local
    // request subscription. Active writes remain protected server-side by the
    // hash precondition if their HTTP request already crossed the wire.
    this.cancelWorkspaceWrites();
    this.resetReviewGate();
    this.resetPublicationState();
    try {
      this.store.load(flow);
    } catch {
      this.markHydrationFailed(
        'This System Flow could not be normalized safely. Editing remains blocked.',
      );
      return false;
    }
    // Commit the authoritative identity/concurrency state only after the flow
    // has normalized successfully. A malformed payload must not partially
    // advance the client to a server revision it cannot render.
    this.systemId.set(system.id);
    this.systemStatus.set(system.status ?? 'draft');
    this.systemDisplayName.set(system.name);
    this.savedFlowSha256.set(system.flow_sha256 ?? null);
    this.baselineFlow = cloneFlow(this.store.snapshot());
    this.hydrationError.set(null);
    this.hydrationReady.set(true);
    this.errored.set(false);
    this.lastRevision = this.store.revision();
    return true;
  }

  /** P1 hydration path. The draft in `flowState` is the sole graph authority;
   * the System payload contributes identity/name only. */
  hydratePublicationState(system: System, flowState: SystemFlowState): boolean {
    if (
      (this.systemId() && system.id !== this.systemId()) ||
      flowState.system_id !== system.id
    ) {
      this.markHydrationFailed('The loaded server draft does not match this route.');
      return false;
    }
    const flow = canonicalPersistedFlow(flowState.draft?.flow_definition);
    if (!flow) {
      this.markHydrationFailed(
        'This System returned a malformed server draft. Editing remains blocked.',
      );
      return false;
    }
    if (
      !Number.isInteger(flowState.draft.revision) ||
      flowState.draft.revision < 1 ||
      !flowState.draft.flow_sha256 ||
      !flowState.published?.version_id ||
      !flowState.published.flow_sha256
    ) {
      this.markHydrationFailed(
        'This System returned incomplete Draft/Publish preconditions. Editing remains blocked.',
      );
      return false;
    }

    this.cancelAutosave();
    this.cancelWorkspaceWrites();
    this.resetReviewGate();
    this.resetPublicationState();
    try {
      this.store.load(flow);
    } catch {
      this.markHydrationFailed(
        'This server draft could not be normalized safely. Editing remains blocked.',
      );
      return false;
    }

    this.systemId.set(system.id);
    this.systemStatus.set(flowState.status ?? system.status ?? 'draft');
    this.systemDisplayName.set(system.name);
    this.publicationMode.set(true);
    this.draftRevision.set(flowState.draft.revision);
    this.savedFlowSha256.set(flowState.draft.flow_sha256);
    this.draftBasePublishedVersionId.set(
      flowState.draft.base_published_version_id ?? null,
    );
    this.publishedVersionId.set(flowState.published.version_id);
    this.publishedVersionNumber.set(flowState.published.version_number);
    this.publishedFlowSha256.set(flowState.published.flow_sha256);
    this.publishedExecutionContract.set(
      flowState.published.execution_contract
        ? structuredClone(flowState.published.execution_contract)
        : null,
    );
    const explicitContractReadiness =
      flowState.published.execution_contract_ready;
    this.publishedContractReady.set(
      typeof explicitContractReadiness === 'boolean'
        ? explicitContractReadiness
        : typeof flowState.published.execution_contract?.['contract_sha256'] ===
            'string',
    );
    this.draftUpdatedAt.set(flowState.draft.updated_at ?? null);
    this.lastSavedAt.set(
      flowState.draft.updated_at
        ? new Date(flowState.draft.updated_at).getTime()
        : null,
    );
    this.baselineFlow = cloneFlow(this.store.snapshot());
    this.hydrationError.set(null);
    this.hydrationReady.set(true);
    this.errored.set(false);
    this.lastRevision = this.store.revision();
    return true;
  }

  markHydrationFailed(message: string): void {
    this.cancelAutosave();
    this.cancelWorkspaceWrites();
    this.hydrationReady.set(false);
    this.hydrationError.set(message);
    this.savedFlowSha256.set(null);
    this.resetPublicationState();
    this.errored.set(true);
  }

  /** Put every mutation behind a strict reload after an optimistic conflict. */
  markRevisionConflict(
    message = 'The server draft changed. Reload it before continuing.',
  ): void {
    this.autosaveBlocked = true;
    this.errored.set(true);
    this.pauseForReview('conflict');
    this.publishError.set(message);
    this.toastr.error(message, 'Reload required');
  }

  /** Strong-clear confirmation must call this before any store mutation. */
  confirmClear(): void {
    if (this.actionsDisabled()) return;
    this.pauseForReview('clear');
    this.store.clear();
    // Even an already-empty active Flow needs a fresh, explicit authority.
    this.replacementIntentRevision = this.store.revision();
  }

  /** Continue an active destructive replacement after the second typed gate. */
  confirmReplacementAndSave(): void {
    if (!this.hydrationReady() || this.saving() || this.promoting()) return;
    this.replacementConfirmationRequested.set(false);
    this.replacementIntentRevision = this.store.revision();
    this.saveNow();
  }

  cancelReplacementConfirmation(): void {
    this.replacementConfirmationRequested.set(false);
  }

  /** Lock every editor mutation around an authoritative child operation such
   *  as version rollback. Returns false when another write already owns it. */
  beginExternalMutation(): boolean {
    if (this.actionsDisabled()) return false;
    this.cancelAutosave();
    this.externalMutationPending.set(true);
    return true;
  }

  /** Version rollback is itself an explicit graph replacement. Active
   *  Systems must carry the current hash and the rollback confirmation as
   *  one-shot replacement intent. */
  rollbackWriteOptions():
    | {
        expected_flow_sha256?: string;
        flow_write_intent?: 'replace_active_flow';
      }
    | null {
    if (this.systemStatus() !== 'active') {
      return this.savedFlowSha256()
        ? { expected_flow_sha256: this.savedFlowSha256()! }
        : {};
    }
    if (!this.savedFlowSha256()) return null;
    return {
      expected_flow_sha256: this.savedFlowSha256()!,
      flow_write_intent: 'replace_active_flow',
    };
  }

  endExternalMutation(): void {
    this.externalMutationPending.set(false);
  }

  /** Explicit discard is the only path (besides a successful save) that
   *  releases a bulk-operation autosave hold. */
  discardPendingChanges(): void {
    if (
      !this.hydrationReady() ||
      !this.baselineFlow ||
      this.saving() ||
      this.reviewRequired() === 'conflict'
    ) {
      return;
    }
    const discardedShare = this.reviewRequired() === 'share';
    this.store.load(cloneFlow(this.baselineFlow));
    if (discardedShare) this.consumeShareLink();
    this.resetReviewGate();
    this.errored.set(false);
    this.lastRevision = this.store.revision();
  }

  /** Flush immediately (Save button / Ctrl·Cmd+S). */
  saveNow(): void {
    if (this.actionsDisabled()) return;
    this.cancelAutosave();
    if (this.systemId() && this.saveValidationBlocked()) {
      this.toastr.warning(
        'Fix the current server validation errors before saving.',
        'Save blocked',
      );
      return;
    }
    if (this.reviewRequired() === 'conflict') {
      this.toastr.warning(
        'Reload the authoritative System before trying to save again.',
        'Save blocked',
      );
      return;
    }
    if (
      this.systemId() &&
      this.systemStatus() === 'active' &&
      this.isDestructiveReplacement(this.store.snapshot()) &&
      this.replacementIntentRevision !== this.store.revision()
    ) {
      this.pauseForReview(this.reviewRequired() ?? 'destructive-change');
      this.replacementConfirmationRequested.set(true);
      return;
    }
    this.persist('manual');
  }

  /** Keep a dirty Workbench snapshot local for the lifetime of the panel.
   * Releasing the hold restores the normal debounced autosave policy. */
  setWorkbenchAutosaveHold(held: boolean): void {
    if (this.workbenchAutosaveHeld() === held) return;
    this.workbenchAutosaveHeld.set(held);
    if (held) {
      this.cancelAutosave();
      return;
    }
    if (
      !this.hydrationReady() ||
      !this.store.dirty() ||
      this.saving() ||
      this.promoting() ||
      this.autosaveBlocked ||
      this.autosavePaused()
    ) {
      return;
    }
    this.scheduleAutosave();
  }

  /** Explicit non-mutating server analysis for the exact live revision. */
  validateNow(): void {
    if (!this.systemId() || !this.hydrationReady() || this.actionsDisabled()) return;
    this.validation.validateNow();
  }

  /** Load and freeze the semantic published→draft diff before the explicit
   * Publish confirmation can become available. */
  openPublicationReview(): void {
    const sid = this.systemId();
    const blocked = this.publicationBlockReason();
    if (!sid || !this.canReviewPublication()) {
      if (blocked) this.toastr.warning(blocked, 'Publish blocked');
      return;
    }
    this.publicationDiffRequest?.unsubscribe();
    this.publishReviewOpen.set(true);
    this.publishDiff.set(null);
    const publishedHome = this.canOpenPublishedHome();
    this.publishDiffState.set(publishedHome ? 'idle' : 'loading');
    this.publishError.set(null);
    this.publishSucceeded.set(publishedHome);
    this.breakingChangeAcknowledged.set(false);
    if (publishedHome) return;
    const scope = this.workspace.captureRequestScope();
    const expectedDraftHash = this.savedFlowSha256();
    const expectedPublishedHash = this.publishedFlowSha256();
    const request = this.canonical.getSystemFlowDiff(sid).subscribe({
      next: (diff) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        if (
          diff.target.flow_sha256 !== expectedDraftHash ||
          diff.base.flow_sha256 !== expectedPublishedHash
        ) {
          this.publishDiffState.set('error');
          this.markRevisionConflict(
            'The Draft/Published pointers changed while the diff was loading. Reload before publishing.',
          );
          return;
        }
        this.publishDiff.set(diff);
        this.publishDiffState.set('ready');
      },
      error: (error: unknown) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.publishDiffState.set('error');
        const message = this.publicationErrorMessage(
          error,
          'Could not load the semantic publication diff.',
        );
        this.publishError.set(message);
        if (error instanceof HttpErrorResponse && error.status === 409) {
          this.markRevisionConflict(message);
        }
      },
    });
    this.publicationDiffRequest = request.closed ? null : request;
  }

  closePublicationReview(): void {
    if (this.publishing()) return;
    this.publicationDiffRequest?.unsubscribe();
    this.publicationDiffRequest = null;
    this.publishReviewOpen.set(false);
    this.publishDiff.set(null);
    this.publishDiffState.set('idle');
    this.publishError.set(null);
    this.publishSucceeded.set(false);
    this.breakingChangeAcknowledged.set(false);
  }

  setBreakingChangeAcknowledged(value: boolean): void {
    this.breakingChangeAcknowledged.set(value);
  }

  publishDraft(message: string): void {
    const sid = this.systemId();
    const draftRevision = this.draftRevision();
    const publishedVersionId = this.publishedVersionId();
    const diff = this.publishDiff();
    const resolvedMessage = message.trim();
    if (!resolvedMessage) {
      this.publishError.set('Add a release message before publishing.');
      return;
    }
    if (
      !sid ||
      draftRevision === null ||
      !publishedVersionId ||
      !diff ||
      !this.canConfirmPublication()
    ) {
      this.publishError.set(
        this.publicationBlockReason() ??
          'Review the current semantic diff and acknowledge breaking changes first.',
      );
      return;
    }
    if (
      diff.target.flow_sha256 !== this.savedFlowSha256() ||
      diff.base.flow_sha256 !== this.publishedFlowSha256()
    ) {
      this.markRevisionConflict(
        'The reviewed diff no longer matches the Draft/Published pointers. Reload before publishing.',
      );
      return;
    }

    this.publicationRequest?.unsubscribe();
    this.publishing.set(true);
    this.publishError.set(null);
    const scope = this.workspace.captureRequestScope();
    const request = this.canonical
      .publishSystemFlow(sid, {
        expected_draft_revision: draftRevision,
        expected_published_version_id: publishedVersionId,
        message: resolvedMessage,
        breaking_change_intent:
          diff.summary.breaking > 0 ? 'acknowledged' : null,
      })
      .subscribe({
        next: (result) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.publishing.set(false);
          this.systemStatus.set(result.status ?? this.systemStatus());
          this.publishedVersionId.set(result.published.version_id);
          this.publishedVersionNumber.set(result.published.version_number);
          this.publishedFlowSha256.set(result.published.flow_sha256);
          this.publishedExecutionContract.set(
            result.published.execution_contract
              ? structuredClone(result.published.execution_contract)
              : null,
          );
          this.publishedContractReady.set(true);
          this.draftRevision.set(result.draft.revision);
          this.savedFlowSha256.set(result.draft.flow_sha256);
          this.draftBasePublishedVersionId.set(
            result.draft.base_published_version_id ?? result.published.version_id,
          );
          this.draftUpdatedAt.set(result.draft.updated_at ?? null);
          this.publishSucceeded.set(true);
          this.publishDiff.set(null);
          this.publishDiffState.set('idle');
          this.breakingChangeAcknowledged.set(false);
          this.manifest.reload();
          this.toastr.success(
            `Published as v${result.published.version_number}. System status remains ${result.status}; publication never activates it.`,
            'Flow published',
          );
        },
        error: (error: unknown) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.publishing.set(false);
          const message = this.publicationErrorMessage(
            error,
            'The draft could not be published.',
          );
          this.publishError.set(message);
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.markRevisionConflict(message);
          } else if (error instanceof HttpErrorResponse && error.status === 422) {
            this.validation.validateNow();
          }
        },
      });
    this.publicationRequest = request.closed ? null : request;
  }

  /** Download the live flow as a JSON file (CanonicalFlow). */
  exportJson(): void {
    if (!this.hydrationReady()) return;
    const flow = this.store.snapshot();
    const blob = new Blob([JSON.stringify(flow, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `flow-${this.systemId() ?? 'scratch'}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  /** Build a shareable link (flow encoded in the URL hash) and copy it. The
   *  link always targets the scratchpad route so it opens anywhere. */
  shareLink(): string {
    if (!this.hydrationReady()) return '';
    const json = JSON.stringify(this.store.snapshot());
    const payload = encodeFlowPayload(json);
    const link = `${location.origin}/orchestration#flow=${payload}`;
    const clip = navigator.clipboard;
    if (clip?.writeText) {
      clip.writeText(link).then(
        () => this.toastr.success('Share link copied to clipboard.', 'Flow builder'),
        () => this.toastr.info(link, 'Share link'),
      );
    } else {
      this.toastr.info(link, 'Share link');
    }
    return link;
  }

  /** Round-trip import from raw JSON text. Returns false on parse failure. */
  importJson(text: string): boolean {
    if (this.actionsDisabled()) return false;
    try {
      const parsed = JSON.parse(text) as unknown;
      if (!isFlowLike(parsed)) throw new Error('not a flow');
      // Prove normalization before changing the review/autosave gate.
      const normalized = this.serializer.normalize(parsed);
      this.pauseForReview('import');
      this.store.replaceAsEdit(normalized);
      this.toastr.success(
        'Flow imported for review. Autosave is paused until you save it.',
        'Flow builder',
      );
      return true;
    } catch {
      this.toastr.error('Could not parse that file as a flow.', 'Import failed');
      return false;
    }
  }

  /**
   * Promote the scratchpad draft into a real System atomically. The initial
   * graph is part of POST /systems so publication-enabled workspaces initialise
   * their Draft/Published authority from this exact snapshot and legacy
   * workspaces persist it in the same transaction. There is deliberately no
   * follow-up PATCH: a failed create can never leave a known-empty shell.
   */
  promoteToSystem(name?: string): void {
    if (this.systemId() || this.promoting() || !this.hydrationReady()) return;
    const resolved =
      name ?? window.prompt('Name this System', 'Scratchpad flow')?.trim();
    if (!resolved) return;

    this.promoting.set(true);
    const scope = this.workspace.captureRequestScope();
    const flow = this.serializer.annotateSidecars(this.store.snapshot());
    const sentRevision = this.store.revision();
    this.promotionRequest?.unsubscribe();
    const request = this.canonical
      .createSystem({
        name: resolved,
        objective: 'Promoted from scratchpad flow',
        flow_definition: flow as unknown as Record<string, unknown>,
        // Durable provenance: the catalog can label these Systems without
        // pattern-matching a name an operator is free to change.
        settings: { origin: 'scratchpad_promote' },
      })
      .subscribe({
        next: (system) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.promoting.set(false);
          if (!system) {
            this.toastr.error(
              'The System and its Flow could not be created atomically. Your local draft was kept.',
              'Promotion failed',
            );
            return;
          }

          const returnedFlow = system.flow_definition;
          const returnedFlowVerified =
            !!system.flow_sha256 &&
            isFlowLike(returnedFlow) &&
            flowValidationFingerprint(returnedFlow) === flowValidationFingerprint(flow);
          if (!returnedFlowVerified) {
            this.toastr.error(
              `System "${system.name}" (${system.id}) was created, but its Flow response could not be verified. Your local draft was kept; review that System before retrying.`,
              'Promotion needs review',
            );
            return;
          }

          if (!this.store.markSaved(sentRevision)) {
            // A local edit raced the atomic create. Keep it recoverable and
            // stay on the scratchpad rather than navigating away from it.
            persistWorkspaceFlowDraft(
              localStorage,
              scope.workspaceSlug,
              this.store.snapshot(),
            );
            this.draftAvailable.set(true);
            this.toastr.warning(
              `System "${system.name}" was created from the earlier revision. Newer local edits were kept in this scratchpad.`,
              'Promotion needs review',
            );
            return;
          }

          this.toastr.success(`Promoted to System "${system.name}".`, 'Flow builder');
          this.consumeShareLink();
          this.clearDraftForWorkspace(scope.workspaceSlug);
          void this.router.navigateByUrl(this.navigation.leafUrl('system-flow', { ref: system.id }));
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.promoting.set(false);
          this.toastr.error(
            'The System creation result could not be confirmed. Your local draft was kept.',
            'Promotion failed',
          );
        },
        complete: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) this.promoting.set(false);
        },
      });
    this.promotionRequest = request.closed ? null : request;
  }

  /** Discard the persisted scratchpad draft. */
  clearDraft(): void {
    this.clearDraftForWorkspace(this.workspace.currentSlug());
  }

  private clearDraftForWorkspace(slug: string | null): void {
    clearWorkspaceFlowDraft(localStorage, slug);
    this.draftAvailable.set(false);
  }

  // ---- persistence core ----------------------------------------------------

  private persist(trigger: SaveTrigger): void {
    if (this.systemId()) this.saveToBackend(trigger);
    else this.saveDraft(trigger);
  }

  private scheduleAutosave(): void {
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => {
      this.autosaveTimer = null;
      if (
        !this.hydrationReady() ||
        !this.store.dirty() ||
        this.saving() ||
        this.promoting() ||
        this.autosaveBlocked ||
        this.autosaveSuspended()
      ) {
        return;
      }
      this.persist('autosave');
    }, AUTOSAVE_DEBOUNCE_MS);
  }

  private saveDraft(trigger: SaveTrigger): void {
    const sentRevision = this.store.revision();
    const flow = this.store.snapshot();
    const saved = persistWorkspaceFlowDraft(
      localStorage,
      this.workspace.currentSlug(),
      flow,
    );
    if (!saved) {
      this.autosaveBlocked = true;
      this.errored.set(true);
      this.toastr.error('Could not save draft to local storage.', 'Scratchpad');
      return;
    }

    const acknowledged = this.store.markSaved(sentRevision);
    this.baselineFlow = cloneFlow(flow);
    this.lastSavedAt.set(saved.savedAt);
    this.draftAvailable.set(true);
    this.errored.set(false);
    if (acknowledged) this.resetReviewGate();
    if (acknowledged) this.consumeShareLink();
    if (trigger === 'manual') {
      this.toastr.success('Draft saved locally.', 'Scratchpad');
    }
  }

  private saveToBackend(trigger: SaveTrigger): void {
    const sid = this.systemId();
    if (!sid || this.saving() || !this.hydrationReady()) return;
    if (this.saveValidationBlocked()) {
      this.autosaveBlocked = true;
      if (trigger === 'manual') {
        this.toastr.warning(
          'Fix the current server validation errors before saving.',
          'Save blocked',
        );
      }
      return;
    }
    if (this.publicationMode()) {
      this.saveServerDraft(sid, trigger);
      return;
    }
    if (this.systemStatus() === 'active' && !this.savedFlowSha256()) {
      this.pauseForReview('conflict');
      this.autosaveBlocked = true;
      this.errored.set(true);
      this.toastr.error(
        'The active Flow has no concurrency token. Reload before saving.',
        'Save blocked',
      );
      return;
    }
    const scope = this.workspace.captureRequestScope();
    this.saving.set(true);
    this.errored.set(false);
    const flow = this.serializer.annotateSidecars(this.store.snapshot());
    const sentRevision = this.store.revision();
    const carriesReplacementIntent =
      trigger === 'manual' && this.replacementIntentRevision === sentRevision;
    // Intent is deliberately one-shot. Retrying after any failure requires a
    // fresh confirmation against the then-current revision.
    this.replacementIntentRevision = null;
    const request = this.canonical
      .saveSystemFlow(sid, flow as unknown as Record<string, unknown>, {
        ...(this.savedFlowSha256()
          ? { expected_flow_sha256: this.savedFlowSha256()! }
          : {}),
        ...(carriesReplacementIntent
          ? { flow_write_intent: 'replace_active_flow' as const }
          : {}),
      })
      .subscribe({
        next: (res) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.saving.set(false);
          if (res.ok) {
            this.baselineFlow = cloneFlow(flow);
            this.savedFlowSha256.set(res.system.flow_sha256 ?? null);
            this.systemStatus.set(res.system.status ?? this.systemStatus());
            this.systemDisplayName.set(res.system.name ?? this.systemDisplayName());
            const acknowledged = this.store.markSaved(sentRevision);
            this.lastSavedAt.set(Date.now());
            // If validation was unavailable/in flight at save time, refresh it
            // against the now-authoritative graph. A matching result is kept.
            if (
              acknowledged &&
              this.validation.currentFlowSha256() !== (res.system.flow_sha256 ?? null)
            ) {
              this.validation.validateNow();
            }
            // Bindings may have changed — refresh node badges + inspector status.
            this.manifest.reload();
            if (acknowledged) {
              this.resetReviewGate();
            } else if (this.isDestructiveReplacement(this.store.snapshot())) {
              this.pauseForReview('destructive-change');
            } else if (!this.autosaveSuspended()) {
              // A newer edit landed while this request was in flight. The
              // response only acknowledges its captured revision.
              this.scheduleAutosave();
            }
            if (trigger === 'manual') {
              this.toastr.success('Flow saved to System.', 'Flow builder');
            }
          } else {
            this.autosaveBlocked = true;
            this.errored.set(true);
            // Re-analyse the still-current revision through the canonical,
            // hash-bearing endpoint instead of retaining unbound save errors.
            if (res.reason === 'invalid' && this.store.revision() === sentRevision) {
              this.validation.validateNow();
            }
            if (res.reason === 'conflict') this.pauseForReview('conflict');
            if (res.reason === 'explicit_intent_required') {
              this.pauseForReview('destructive-change');
              this.replacementConfirmationRequested.set(true);
            }
            this.toastr.error(res.message, 'Save failed');
          }
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.saving.set(false);
          this.autosaveBlocked = true;
          this.errored.set(true);
          this.toastr.error('Unknown backend error.', 'Save failed');
        },
      });
    this.backendSaveRequest = request.closed ? null : request;
  }

  private saveServerDraft(sid: string, trigger: SaveTrigger): void {
    const expectedRevision = this.draftRevision();
    if (expectedRevision === null) {
      this.markRevisionConflict(
        'The server draft has no revision precondition. Reload before saving.',
      );
      return;
    }
    const scope = this.workspace.captureRequestScope();
    this.saving.set(true);
    this.errored.set(false);
    this.publishError.set(null);
    const flow = this.serializer.annotateSidecars(this.store.snapshot());
    const sentRevision = this.store.revision();
    // The typed destructive gate is client-side authority for draft writes.
    // It remains one-shot even though no published pointer is mutated here.
    this.replacementIntentRevision = null;
    const request = this.canonical
      .saveSystemFlowDraft(
        sid,
        flow as unknown as Record<string, unknown>,
        expectedRevision,
      )
      .subscribe({
        next: (result) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.saving.set(false);
          this.applyDraftSaveResult(result);
          this.baselineFlow = cloneFlow(flow);
          const acknowledged = this.store.markSaved(sentRevision);
          if (
            acknowledged &&
            this.validation.currentFlowSha256() !== result.flow_sha256
          ) {
            this.validation.validateNow();
          }
          if (acknowledged) {
            this.resetReviewGate();
          } else if (this.isDestructiveReplacement(this.store.snapshot())) {
            this.pauseForReview('destructive-change');
          } else if (!this.autosaveSuspended()) {
            this.scheduleAutosave();
          }
          if (trigger === 'manual') {
            this.toastr.success(
              `Server draft r${result.revision} saved. Published Flow unchanged.`,
              'Flow builder',
            );
          }
        },
        error: (error: unknown) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.saving.set(false);
          this.autosaveBlocked = true;
          this.errored.set(true);
          const message = this.publicationErrorMessage(
            error,
            'The server draft could not be saved.',
          );
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.markRevisionConflict(message);
          } else {
            this.toastr.error(message, 'Draft save failed');
          }
        },
      });
    this.backendSaveRequest = request.closed ? null : request;
  }

  private applyDraftSaveResult(result: SystemFlowDraftSaveResult): void {
    this.draftRevision.set(result.revision);
    this.savedFlowSha256.set(result.flow_sha256);
    this.draftBasePublishedVersionId.set(
      result.base_published_version_id ?? this.draftBasePublishedVersionId(),
    );
    this.draftUpdatedAt.set(result.updated_at ?? null);
    this.lastSavedAt.set(
      result.updated_at ? new Date(result.updated_at).getTime() : Date.now(),
    );
    this.errored.set(false);
  }

  private cancelWorkspaceWrites(): void {
    this.promotionRequest?.unsubscribe();
    this.promotionRequest = null;
    this.backendSaveRequest?.unsubscribe();
    this.backendSaveRequest = null;
    this.publicationRequest?.unsubscribe();
    this.publicationRequest = null;
    this.publicationDiffRequest?.unsubscribe();
    this.publicationDiffRequest = null;
    this.promoting.set(false);
    this.saving.set(false);
    this.publishing.set(false);
    this.externalMutationPending.set(false);
  }

  private cancelAutosave(): void {
    if (!this.autosaveTimer) return;
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
  }

  private pauseForReview(reason: FlowReviewReason): void {
    this.cancelAutosave();
    this.autosavePaused.set(true);
    this.reviewRequired.set(reason);
  }

  private resetReviewGate(): void {
    this.cancelAutosave();
    this.autosavePaused.set(false);
    this.reviewRequired.set(null);
    this.replacementConfirmationRequested.set(false);
    this.replacementIntentRevision = null;
  }

  private resetPublicationState(): void {
    this.systemStatus.set(null);
    this.publicationMode.set(false);
    this.draftRevision.set(null);
    this.draftBasePublishedVersionId.set(null);
    this.publishedVersionId.set(null);
    this.publishedVersionNumber.set(null);
    this.publishedFlowSha256.set(null);
    this.publishedExecutionContract.set(null);
    this.publishedContractReady.set(false);
    this.draftUpdatedAt.set(null);
    this.publishReviewOpen.set(false);
    this.publishDiff.set(null);
    this.publishDiffState.set('idle');
    this.publishError.set(null);
    this.publishSucceeded.set(false);
    this.breakingChangeAcknowledged.set(false);
    this.publishing.set(false);
    this.systemDisplayName.set(null);
  }

  private publicationErrorMessage(error: unknown, fallback: string): string {
    if (!(error instanceof HttpErrorResponse)) return fallback;
    const raw = error.error?.detail ?? error.error;
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      const detail = raw as { message?: unknown; code?: unknown };
      if (typeof detail.message === 'string' && detail.message.trim()) {
        return detail.message;
      }
      if (typeof detail.code === 'string' && detail.code.trim()) {
        return `${fallback} (${detail.code})`;
      }
    }
    if (typeof raw === 'string' && raw.trim()) return raw;
    return error.status > 0 ? `${fallback} (HTTP ${error.status})` : fallback;
  }

  private isDestructiveReplacement(flow: CanonicalFlow): boolean {
    if (this.systemStatus() !== 'active') return false;
    const baseline = this.baselineFlow;
    if (!baseline) return true;
    if (flow.nodes.length === 0) return true;

    const baselineHadControl = baseline.nodes.some((node) =>
      CONTROL_KINDS.has(String(node.kind ?? '')),
    );
    const currentHasControl = flow.nodes.some((node) =>
      CONTROL_KINDS.has(String(node.kind ?? '')),
    );
    if (baselineHadControl && !currentHasControl) return true;

    if (baseline.nodes.length > 0 && flow.nodes.length > 0) {
      const baselineIds = new Set(baseline.nodes.map((node) => String(node.id)));
      if (!flow.nodes.some((node) => baselineIds.has(String(node.id)))) return true;
    }

    return this.reviewRequired() === 'clear' ||
      this.reviewRequired() === 'import' ||
      this.reviewRequired() === 'share';
  }

  // ---- restore helpers -----------------------------------------------------

  private readSystemId(): string | null {
    return (
      this.route.snapshot.paramMap.get('systemId') ||
      this.route.snapshot.queryParamMap.get('systemId')
    );
  }

  private hasDraft(): boolean {
    return this.readDraft() != null;
  }

  private readDraft(): CanonicalFlow | null {
    return this.readDraftRecord(this.workspace.currentSlug())?.flow ?? null;
  }

  private readDraftRecord(slug: string | null) {
    return readWorkspaceFlowDraft(
      localStorage,
      slug,
      this.workspace.workspaces().map((workspace) => workspace.slug),
    );
  }

  private readShareLink(): CanonicalFlow | null {
    const match = (location.hash || '').match(/[#&]flow=([^&]+)/);
    if (!match) return null;
    try {
      const flow = JSON.parse(decodeFlowPayload(decodeURIComponent(match[1]))) as unknown;
      return isFlowLike(flow) ? flow : null;
    } catch {
      return null;
    }
  }

  private consumeShareLink(): void {
    if (!this.sharePayloadPending) return;
    this.sharePayloadPending = false;
    const raw = (location.hash || '').replace(/^#/, '');
    const params = new URLSearchParams(raw);
    params.delete('flow');
    const suffix = params.toString();
    const next = `${location.pathname ?? ''}${location.search ?? ''}${suffix ? `#${suffix}` : ''}`;
    if (globalThis.history?.replaceState) {
      globalThis.history.replaceState(globalThis.history.state, '', next);
    } else {
      location.hash = suffix ? `#${suffix}` : '';
    }
  }

  // ---- keyboard ------------------------------------------------------------

  private handleKeydown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    const editable =
      target?.tagName === 'INPUT' ||
      target?.tagName === 'TEXTAREA' ||
      target?.tagName === 'SELECT' ||
      target?.isContentEditable === true;

    const mod = event.metaKey || event.ctrlKey;
    if (mod) {
      const key = event.key.toLowerCase();
      if (editable && (key === 'z' || key === 'y')) return;
      if (key === 's') {
        event.preventDefault();
        this.saveNow();
      } else if (key === 'z') {
        if (this.actionsDisabled()) return;
        event.preventDefault();
        if (event.shiftKey) this.store.redo();
        else this.store.undo();
      } else if (key === 'y') {
        if (this.actionsDisabled()) return;
        // Windows-style redo.
        event.preventDefault();
        this.store.redo();
      }
      return;
    }

    if (
      !this.actionsDisabled() &&
      (event.key === 'Delete' || event.key === 'Backspace') &&
      !blocksFlowDeleteShortcut(event.target)
    ) {
      const id = this.store.selectedNodeId();
      if (id) {
        event.preventDefault();
        this.store.removeNode(id);
      }
    }
  }
}
