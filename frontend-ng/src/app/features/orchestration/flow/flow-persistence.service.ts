/**
 * FlowPersistenceService — P4 persistence / autosave / export·share·import.
 *
 * Component-scoped (provided by `<app-flow-toolbar>`, NOT `providedIn: 'root'`)
 * so it resolves the SAME `FlowStore` instance the builder provides and the
 * `ActivatedRoute` of the routed `FlowBuilderComponent`. It owns NO graph
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
 *     Ctrl+Y redo, Delete/Backspace removes the selected node (ignored while
 *     typing in a field). The shell no longer binds any shortcuts.
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
import { ActivatedRoute, Router } from '@angular/router';
import { switchMap, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type FlowValidationIssue,
} from '@app/core/canonical-api.service';
import {
  FlowSerializerService,
  type CanonicalFlow,
  type CanonicalFlowEdge,
  type CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowManifestService } from './flow-manifest.service';

/** Explicit, user-visible persistence state surfaced in the toolbar pill. */
export type SaveState = 'saved' | 'unsaved' | 'saving' | 'error';

/** What kicked off a persist — only manual/promote surface success toasts. */
type SaveTrigger = 'autosave' | 'manual';

/** Versioned localStorage envelope so the shape can evolve safely. */
interface DraftEnvelope {
  v: 1;
  saved_at: number;
  flow: CanonicalFlow;
}

/** Single scratchpad draft slot. Keyed sanely under an app namespace; a
 *  per-system variant could be added later by appending the id. */
const SCRATCH_DRAFT_KEY = 'agentium.flow.draft.scratch';
const DRAFT_ENVELOPE_VERSION = 1 as const;

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

function isFlowLike(value: unknown): value is CanonicalFlow {
  return !!value && Array.isArray((value as { nodes?: unknown }).nodes);
}

@Injectable()
export class FlowPersistenceService {
  private readonly store = inject(FlowStore);
  private readonly serializer = inject(FlowSerializerService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly manifest = inject(FlowManifestService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);

  /** The System this builder is bound to, or `null` for the scratchpad. */
  readonly systemId = signal<string | null>(null);
  readonly promoting = signal(false);
  readonly lastSavedAt = signal<number | null>(null);
  readonly draftAvailable = signal(false);

  /**
   * Server-side validation issues from the last backend save — the structured
   * `dag_validator` payload (errors on a rejected save, warnings on an accepted
   * one). The design-time validation strip reads this so save-time backend
   * diagnostics render alongside the client checks, with no translation.
   */
  readonly serverIssues = signal<FlowValidationIssue[]>([]);

  private readonly saving = signal(false);
  private readonly errored = signal(false);

  /** Explicit save state for the toolbar — derived so it can never drift from
   *  the store's `dirty` flag. */
  readonly saveState = computed<SaveState>(() => {
    if (this.saving()) return 'saving';
    if (this.errored()) return 'error';
    return this.store.dirty() ? 'unsaved' : 'saved';
  });

  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;
  /** Suppresses autosave retry-storms after a failed save until the user edits
   *  again. Plain field (non-reactive) on purpose. */
  private autosaveBlocked = false;
  private lastNodesRef: CanonicalFlowNode[] | null = null;
  private lastEdgesRef: CanonicalFlowEdge[] | null = null;

  constructor() {
    this.systemId.set(this.readSystemId());
    this.draftAvailable.set(this.hasDraft());

    // Scratchpad hydration precedence: shared link > local draft. (The shell
    // has already loaded the default starter graph by now; we override it.)
    if (!this.systemId()) {
      if (!this.tryRestoreShareLink()) this.tryRestoreDraft();
    }

    effect(() => {
      const nodes = this.store.nodes();
      const edges = this.store.edges();
      const dirty = this.store.dirty();
      const changed = nodes !== this.lastNodesRef || edges !== this.lastEdgesRef;
      this.lastNodesRef = nodes;
      this.lastEdgesRef = edges;
      if (changed) {
        this.autosaveBlocked = false;
        this.errored.set(false);
      }
      if (!dirty || this.saving() || this.promoting() || this.autosaveBlocked) {
        return;
      }
      if (!changed) return;
      this.scheduleAutosave();
    });

    const onKeydown = (event: KeyboardEvent) => this.handleKeydown(event);
    document.addEventListener('keydown', onKeydown);
    this.destroyRef.onDestroy(() => {
      document.removeEventListener('keydown', onKeydown);
      if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    });
  }

  // ---- public actions (toolbar / shortcuts) --------------------------------

  /** Flush immediately (Save button / Ctrl·Cmd+S). */
  saveNow(): void {
    if (this.autosaveTimer) {
      clearTimeout(this.autosaveTimer);
      this.autosaveTimer = null;
    }
    this.persist('manual');
  }

  /** Download the live flow as a JSON file (CanonicalFlow). */
  exportJson(): void {
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
    try {
      const parsed = JSON.parse(text) as unknown;
      if (!isFlowLike(parsed)) throw new Error('not a flow');
      this.store.load(parsed);
      this.toastr.success('Flow imported.', 'Flow builder');
      return true;
    } catch {
      this.toastr.error('Could not parse that file as a flow.', 'Import failed');
      return false;
    }
  }

  /**
   * Promote the scratchpad draft into a real System: create the System, then
   * persist the flow through the canonical save path, clear the local draft,
   * and navigate to the bound flow route.
   */
  promoteToSystem(name?: string): void {
    if (this.systemId() || this.promoting()) return;
    const resolved =
      name ?? window.prompt('Name this System', 'Scratchpad flow')?.trim();
    if (!resolved) return;

    this.promoting.set(true);
    const flow = this.serializer.annotateSidecars(this.store.snapshot());
    this.canonical
      .createSystem({ name: resolved, objective: 'Promoted from scratchpad flow' })
      .pipe(
        switchMap((system) => {
          if (!system) return of({ system: null, save: null });
          return this.canonical
            .saveSystemFlow(system.id, flow as unknown as Record<string, unknown>)
            .pipe(switchMap((save) => of({ system, save })));
        }),
      )
      .subscribe(({ system, save }) => {
        this.promoting.set(false);
        if (!system) {
          this.toastr.error('Could not create the System.', 'Promotion failed');
          return;
        }
        if (save && !save.ok) {
          this.toastr.warning(
            `System created, but the flow needs fixes: ${save.message}`,
            'Promotion',
          );
        } else {
          this.toastr.success(`Promoted to System "${system.name}".`, 'Flow builder');
        }
        this.store.markSaved();
        this.clearDraft();
        this.router.navigate(['/systems', system.id, 'flow']);
      });
  }

  /** Discard the persisted scratchpad draft. */
  clearDraft(): void {
    try {
      localStorage.removeItem(SCRATCH_DRAFT_KEY);
    } catch {
      /* storage unavailable — nothing to clear */
    }
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
        !this.store.dirty() ||
        this.saving() ||
        this.promoting() ||
        this.autosaveBlocked
      ) {
        return;
      }
      this.persist('autosave');
    }, AUTOSAVE_DEBOUNCE_MS);
  }

  private saveDraft(trigger: SaveTrigger): void {
    try {
      const envelope: DraftEnvelope = {
        v: DRAFT_ENVELOPE_VERSION,
        saved_at: Date.now(),
        flow: this.store.snapshot(),
      };
      localStorage.setItem(SCRATCH_DRAFT_KEY, JSON.stringify(envelope));
      this.store.markSaved();
      this.lastSavedAt.set(envelope.saved_at);
      this.draftAvailable.set(true);
      this.errored.set(false);
      if (trigger === 'manual') {
        this.toastr.success('Draft saved locally.', 'Scratchpad');
      }
    } catch {
      this.autosaveBlocked = true;
      this.errored.set(true);
      this.toastr.error('Could not save draft to local storage.', 'Scratchpad');
    }
  }

  private saveToBackend(trigger: SaveTrigger): void {
    const sid = this.systemId();
    if (!sid) return;
    this.saving.set(true);
    this.errored.set(false);
    const flow = this.serializer.annotateSidecars(this.store.snapshot());
    this.canonical
      .saveSystemFlow(sid, flow as unknown as Record<string, unknown>)
      .subscribe((res) => {
        this.saving.set(false);
        if (res.ok) {
          this.store.markSaved();
          this.lastSavedAt.set(Date.now());
          // Surface accepted-save warnings (e.g. soft variable/port hints) in
          // the validation strip; clears when the backend reports none.
          this.serverIssues.set(res.warnings);
          // Bindings may have changed — refresh node badges + inspector status.
          this.manifest.reload();
          if (trigger === 'manual') {
            this.toastr.success('Flow saved to System.', 'Flow builder');
          }
        } else {
          this.autosaveBlocked = true;
          this.errored.set(true);
          // Structural rejection (reason==='invalid') carries the DAG errors;
          // pipe them into the strip. A transport failure leaves the strip as-is.
          if (res.reason === 'invalid') this.serverIssues.set(res.issues);
          this.toastr.error(res.message, 'Save failed');
        }
      });
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
    try {
      const raw = localStorage.getItem(SCRATCH_DRAFT_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as Partial<DraftEnvelope> | CanonicalFlow;
      const flow = (parsed as DraftEnvelope).flow ?? (parsed as CanonicalFlow);
      return isFlowLike(flow) ? flow : null;
    } catch {
      return null;
    }
  }

  private tryRestoreDraft(): boolean {
    const flow = this.readDraft();
    if (!flow) return false;
    this.store.load(flow);
    this.draftAvailable.set(true);
    this.toastr.info('Restored your local draft.', 'Scratchpad');
    return true;
  }

  private tryRestoreShareLink(): boolean {
    const match = (location.hash || '').match(/[#&]flow=([^&]+)/);
    if (!match) return false;
    try {
      const flow = JSON.parse(decodeFlowPayload(decodeURIComponent(match[1]))) as unknown;
      if (!isFlowLike(flow)) return false;
      this.store.load(flow);
      this.toastr.info('Flow loaded from shared link.', 'Flow builder');
      return true;
    } catch {
      return false;
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
      if (key === 's') {
        event.preventDefault();
        this.saveNow();
      } else if (key === 'z') {
        event.preventDefault();
        if (event.shiftKey) this.store.redo();
        else this.store.undo();
      } else if (key === 'y') {
        // Windows-style redo.
        event.preventDefault();
        this.store.redo();
      }
      return;
    }

    if ((event.key === 'Delete' || event.key === 'Backspace') && !editable) {
      const id = this.store.selectedNodeId();
      if (id) {
        event.preventDefault();
        this.store.removeNode(id);
      }
    }
  }
}
