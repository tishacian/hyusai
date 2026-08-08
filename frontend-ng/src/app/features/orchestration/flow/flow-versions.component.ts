/**
 * `<app-flow-versions>` — the version-history right rail.
 *
 * Restored from the deleted monolith's Versions panel, rebuilt on the shared
 * `app-drawer` (focus-trap + Escape + backdrop dismiss come for free). It lists
 * `SystemVersionSummary[]` with lazy paging, shows a node/edge diff against the
 * live canvas (hardened to exact symmetric-difference once a row's full payload
 * is prefetched), previews via `getSystemVersion`, and rolls back via
 * `rollbackSystemVersion`. It reads the current graph from the shared
 * `FlowStore` for its diff baseline. After rollback it emits the authoritative
 * System response; the builder/persistence boundary owns graph hydration.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  CanonicalApiService,
  type System,
  type SystemFlowDiff,
  type SystemVersionFull,
  type SystemVersionSummary,
} from '@app/core/canonical-api.service';
import type { CanonicalFlow } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowPersistenceService } from './flow-persistence.service';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  diffCanonicalFlows,
  formatFlowSemanticDiff,
} from './flow-semantic-diff.vm';

const PAGE_SIZE = 25;

export type FlowVersionPreviewStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface FlowVersionPreviewState {
  status: FlowVersionPreviewStatus;
  message?: string;
  fence?: string;
}

export interface FlowVersionIdentityContext {
  publicationMode: boolean;
  publishedVersionId: string | null;
  draftMatchesPublished: boolean;
}

export function isFlowVersionCurrent(
  version: SystemVersionSummary,
  index: number,
  context: FlowVersionIdentityContext,
): boolean {
  return context.publicationMode
    ? version.id === context.publishedVersionId
    : index === 0;
}

export function isFlowVersionRestoreBlocked(
  version: SystemVersionSummary,
  index: number,
  context: FlowVersionIdentityContext,
): boolean {
  return context.publicationMode
    ? version.id === context.publishedVersionId && context.draftMatchesPublished
    : index === 0;
}

export interface FlowVersionRestoreGate extends FlowVersionIdentityContext {
  historyError: boolean;
  restorePending: boolean;
  writeInProgress: boolean;
  localChanges: boolean;
}

/** Why this row cannot be restored, or `null` when it can. Every condition the
 * button disables on must be named here — a disabled control that explains a
 * different cause than the one blocking it is what made rollback unreadable. */
export function flowVersionRestoreBlockReason(
  version: SystemVersionSummary,
  index: number,
  gate: FlowVersionRestoreGate,
): string | null {
  if (isFlowVersionRestoreBlocked(version, index, gate)) {
    return gate.publicationMode
      ? 'The server draft already matches this published version.'
      : 'This is already the current version.';
  }
  if (gate.historyError) {
    return 'Version history could not be loaded. Refresh before restoring.';
  }
  if (gate.localChanges) {
    return 'Save or discard your local changes before restoring a version.';
  }
  if (gate.restorePending) return 'A restore is already running.';
  if (gate.writeInProgress) {
    return 'Wait for the Flow to finish loading or saving.';
  }
  return null;
}

export interface ExactFlowVersionPreviewEvidence {
  publicationMode: boolean;
  systemId: string;
  summary: SystemVersionSummary;
  full: SystemVersionFull | null;
  semanticDiff: SystemFlowDiff | null;
  draftRevision: number | null;
  draftFlowSha256: string | null;
}

/** Validate both immutable payload identity and the server semantic-diff fence.
 * A rollback button is never enabled from an HTTP 200 alone. */
export function exactFlowVersionPreviewError(
  evidence: ExactFlowVersionPreviewEvidence,
): string | null {
  const { full, summary, systemId } = evidence;
  if (!full) return 'The immutable version payload was not returned.';
  if (
    full.id !== summary.id ||
    full.system_id !== systemId ||
    summary.system_id !== systemId ||
    full.version_number !== summary.version_number
  ) {
    return 'The immutable version payload does not match the selected history row.';
  }
  if (
    !full.flow_definition ||
    typeof full.flow_definition !== 'object' ||
    Array.isArray(full.flow_definition)
  ) {
    return 'The immutable version contains a malformed Flow payload.';
  }
  if (
    full.execution_contract !== undefined &&
    full.execution_contract !== null &&
    (typeof full.execution_contract !== 'object' || Array.isArray(full.execution_contract))
  ) {
    return 'The immutable version contains a malformed execution contract.';
  }
  if (!evidence.publicationMode) return null;

  const diff = evidence.semanticDiff;
  if (!diff) return 'The authoritative semantic diff was not returned.';
  if (!full.flow_sha256 || !summary.flow_sha256) {
    return 'The immutable version digest is missing.';
  }
  if (full.flow_sha256 !== summary.flow_sha256) {
    return 'The immutable version digest does not match the history row.';
  }
  if (diff.base.identity !== `version:${summary.version_number}`) {
    return 'The semantic diff does not describe the selected immutable version.';
  }
  if (diff.base.flow_sha256 !== full.flow_sha256) {
    return 'The semantic diff base digest does not match the immutable version.';
  }
  if (
    evidence.draftRevision === null ||
    diff.target.identity !== `draft:${evidence.draftRevision}`
  ) {
    return 'The semantic diff does not describe the current server draft revision.';
  }
  if (
    !evidence.draftFlowSha256 ||
    diff.target.flow_sha256 !== evidence.draftFlowSha256
  ) {
    return 'The semantic diff target digest does not match the current server draft.';
  }
  return null;
}

export function formatServerFlowSemanticDiff(diff: SystemFlowDiff): string {
  const parts: string[] = [];
  if (diff.summary.breaking) parts.push(`${diff.summary.breaking} breaking`);
  if (diff.summary.behavioral) parts.push(`${diff.summary.behavioral} behavioral`);
  if (diff.summary.presentation) parts.push(`${diff.summary.presentation} presentation`);
  const paths = new Set(diff.changes.map((change) => change.path));
  if (paths.has('nodes/order')) parts.push('↕n order');
  if (paths.has('edges/order')) parts.push('↕e order');
  if (paths.has('execution_contract')) parts.push('~contract');
  return parts.length > 0 ? parts.join(' · ') : '= draft (server verified)';
}

@Component({
  selector: 'app-flow-versions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DrawerComponent, IconComponent],
  styleUrl: './flow-versions.component.scss',
  template: `
    <app-drawer
      [open]="open()"
      title="Flow history"
      subtitle="Append-only · restore any version"
      icon="history"
      [width]="380"
      (close)="close.emit()"
    >
      <div class="ck-vers">
        <header class="ck-vers__head">
          <span class="ck-vers__total">{{ total() }} versions</span>
          <button
            type="button"
            class="ck-vers__refresh"
            (click)="refresh()"
            [disabled]="loading() || !persistence.hydrationReady()"
            title="Refresh"
            aria-label="Refresh versions"
          >
            <app-icon name="refresh-cw" [size]="13" />
          </button>
        </header>

        @if (historyError(); as error) {
          <p class="ck-vers__error" role="alert">{{ error }}</p>
        }

        @if (loading() && versions().length === 0) {
          <p class="ck-vers__empty">Loading…</p>
        } @else if (!historyError() && versions().length === 0) {
          <p class="ck-vers__empty">No history yet. The first save on this System seeds v1.</p>
        } @else {
          <ol class="ck-vers__list">
            @for (v of versions(); track v.id; let i = $index) {
              <li class="ck-vers__row" [class.is-current]="isCurrent(v, i)">
                <div class="ck-vers__row-head">
                  <span class="ck-vers__num">v{{ v.version_number }}</span>
                  @if (isCurrent(v, i)) {
                    <span class="ck-vers__tag" data-tone="pos">
                      {{ persistence.publicationMode() ? 'PUBLISHED' : 'CURRENT' }}
                    </span>
                  }
                  @if (v.rolled_back_from_id) { <span class="ck-vers__tag" data-tone="warn">ROLLBACK</span> }
                  <span class="ck-vers__when">{{ relativeTime(v.created_at) }}</span>
                </div>
                <div class="ck-vers__meta">
                  <span>{{ v.created_by }}</span>
                  <span class="ck-vers__dot"></span>
                  <span>{{ v.node_count }}n · {{ v.edge_count }}e</span>
                  @if (diffLabel(v); as d) {
                    <span class="ck-vers__dot"></span>
                    <span class="ck-vers__diff">{{ d }}</span>
                  }
                </div>
                @if (v.message) {
                  <p class="ck-vers__msg">{{ v.message }}</p>
                }
                <div class="ck-vers__row-actions">
                  <button
                    type="button"
                    class="ck-vers__btn"
                    (click)="preview(v)"
                    [disabled]="previewStatus(v) === 'loading'"
                    [attr.aria-busy]="previewStatus(v) === 'loading'"
                    title="Load and show semantic diff"
                  >
                    @if (previewStatus(v) === 'loading') {
                      <app-icon name="loader-2" [size]="12" class="ck-vers__spin" /> Loading…
                    } @else {
                      <app-icon name="eye" [size]="12" />
                      {{ previewStatus(v) === 'error' ? 'Retry preview' : 'Preview' }}
                    }
                  </button>
                  <button
                    type="button"
                    class="ck-vers__btn ck-vers__btn--warn"
                    (click)="beginRollback(v)"
                    [disabled]="!!restoreBlockReason(v, i)"
                    [title]="restoreTitle(v, i)"
                  >
                    <app-icon name="rotate-ccw" [size]="12" /> Restore this version
                  </button>
                </div>
                @if (restoreBlockReason(v, i); as reason) {
                  <p class="ck-vers__restore-reason">{{ reason }}</p>
                }
                @if (previewError(v); as error) {
                  <p class="ck-vers__preview-error" role="alert">{{ error }}</p>
                }
              </li>
            }
          </ol>

          @if (versions().length < total()) {
            <button
              type="button"
              class="ck-vers__more"
              (click)="loadMore()"
              [disabled]="loadingMore()"
            >
              {{ loadingMore() ? 'Loading…' : 'Load older versions' }}
            </button>
          }
        }

        @if (rollbackTarget(); as tgt) {
          <div class="ck-vers__confirm" role="dialog" aria-label="Confirm rollback">
            <p class="ck-vers__confirm-text">
              @if (persistence.publicationMode()) {
                Restore <strong>v{{ tgt.version_number }}</strong> into the server draft and replace
                the canvas. The published pointer and System status stay unchanged.
              } @else {
                Create a new version that copies <strong>v{{ tgt.version_number }}</strong>'s graph and
                replaces the canvas. History is append-only — nothing is deleted.
              }
            </p>
            @if (previewStatus(tgt) === 'loading') {
              <p class="ck-vers__preview-state" role="status">
                Loading the exact immutable payload and authoritative semantic diff…
              </p>
            } @else if (previewError(tgt); as error) {
              <div class="ck-vers__preview-state ck-vers__preview-state--error" role="alert">
                <span>{{ error }}</span>
                <button type="button" class="ck-vers__btn" (click)="preview(tgt)">
                  Retry exact preview
                </button>
              </div>
            } @else if (previewReady(tgt)) {
              <p class="ck-vers__preview-state" data-tone="ready">
                Exact preview ready · {{ diffLabel(tgt) }}
              </p>
            }
            @if (!persistence.publicationMode()) {
              <input
                type="text"
                class="ck-vers__confirm-input"
                [value]="rollbackMessage()"
                (input)="onMessage($event)"
                [placeholder]="'rollback to v' + tgt.version_number"
                maxlength="280"
                aria-label="Rollback message"
              />
            }
            <div class="ck-vers__confirm-actions">
              <button
                type="button"
                class="ck-vers__btn"
                (click)="cancelRollback()"
                [disabled]="rollbackPending()"
              >
                Cancel
              </button>
              <button
                type="button"
                class="ck-vers__btn ck-vers__btn--primary"
                (click)="confirmRollback()"
                [disabled]="
                  rollbackPending() ||
                  persistence.actionsDisabled() ||
                  store.dirty() ||
                  !previewReady(tgt)
                "
              >
                @if (rollbackPending()) {
                  <app-icon name="loader-2" [size]="12" class="ck-vers__spin" /> Rolling back…
                } @else {
                  <app-icon name="rotate-ccw" [size]="12" />
                  {{ persistence.publicationMode() ? 'Restore draft' : 'Confirm' }}
                }
              </button>
            </div>
          </div>
        }
      </div>
    </app-drawer>
  `,
})
export class FlowVersionsComponent {
  private readonly canonical = inject(CanonicalApiService);
  protected readonly store = inject(FlowStore);
  protected readonly persistence = inject(FlowPersistenceService);
  private readonly toastr = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);

  readonly open = input(false);
  readonly systemId = input<string | null>(null);

  readonly close = output<void>();
  readonly rolledBack = output<System>();
  readonly reloadRequired = output<void>();

  readonly versions = signal<SystemVersionSummary[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly loadingMore = signal(false);
  readonly historyError = signal<string | null>(null);
  readonly rollbackTarget = signal<SystemVersionSummary | null>(null);
  readonly rollbackMessage = signal('');
  readonly rollbackPending = signal(false);

  private readonly previews = signal<Record<string, SystemVersionFull>>({});
  private readonly semanticDiffs = signal<Record<string, SystemFlowDiff>>({});
  private readonly previewStates = signal<Record<string, FlowVersionPreviewState>>({});
  private baseline: CanonicalFlow | null = null;
  private baselineRevision: number | null = null;
  private previewGeneration = 0;
  private evidenceFence: string | null = null;
  /** Tracks the current open session so reopening reloads a fresh first page. */
  private opened = false;

  constructor() {
    const unregisterReset = this.workspace.registerContextReset(() => {
      this.opened = false;
      this.versions.set([]);
      this.total.set(0);
      this.loading.set(false);
      this.loadingMore.set(false);
      this.historyError.set(null);
      this.rollbackTarget.set(null);
      this.rollbackPending.set(false);
      this.evidenceFence = null;
      this.invalidateBaseline();
    });
    this.destroyRef.onDestroy(unregisterReset);

    effect(() => {
      const isOpen = this.open();
      if (isOpen && !this.opened) {
        this.opened = true;
        untracked(() => this.refresh());
      } else if (!isOpen) {
        this.opened = false;
      }
    });

    // The live canvas is the diff target. Authoritative hydration and every
    // local revision invalidate all previously fetched evidence immediately.
    effect(() => {
      const isOpen = this.open();
      const hydrationReady = this.persistence.hydrationReady();
      const revision = this.store.revision();
      const evidenceFence = this.currentEvidenceFence();
      if (!isOpen) return;
      if (!hydrationReady) {
        if (this.baseline !== null) untracked(() => this.invalidateBaseline());
        return;
      }
      if (this.baselineRevision !== revision) {
        untracked(() => this.captureBaseline());
      }
      if (this.evidenceFence !== evidenceFence) {
        this.evidenceFence = evidenceFence;
        untracked(() => this.invalidatePreviewEvidence());
      }
    });
  }

  refresh(): void {
    const sid = this.systemId();
    if (!sid || !this.persistence.hydrationReady()) return;
    this.captureBaseline();
    this.loading.set(true);
    this.historyError.set(null);
    const scope = this.workspace.captureRequestScope();
    this.canonical.listSystemVersions(sid, {
      limit: PAGE_SIZE,
      offset: 0,
      propagateErrors: true,
    }).subscribe({
      next: (res) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false);
        this.versions.set(res.versions ?? []);
        this.total.set(res.total ?? 0);
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false);
        const message = 'Could not load version history. Existing rows may be stale.';
        this.historyError.set(message);
        this.toastr.error(message, 'Versions');
      },
    });
  }

  loadMore(): void {
    const sid = this.systemId();
    if (
      !sid ||
      this.loadingMore() ||
      !this.persistence.hydrationReady() ||
      !!this.historyError()
    ) return;
    this.loadingMore.set(true);
    const scope = this.workspace.captureRequestScope();
    this.canonical
      .listSystemVersions(sid, {
        limit: PAGE_SIZE,
        offset: this.versions().length,
        propagateErrors: true,
      })
      .subscribe({
        next: (res) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.loadingMore.set(false);
          this.versions.update((cur) => [...cur, ...(res.versions ?? [])]);
          this.total.set(res.total ?? this.total());
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.loadingMore.set(false);
          this.toastr.error('Could not load more versions.', 'Versions');
        },
      });
  }

  preview(v: SystemVersionSummary): void {
    const sid = this.systemId();
    const status = this.previewStatus(v);
    if (!sid || status === 'loading' || status === 'ready') return;
    if (!this.persistence.hydrationReady() || this.store.dirty()) {
      this.setPreviewError(v, 'Save or discard local changes before loading rollback evidence.');
      return;
    }
    const publicationMode = this.persistence.publicationMode();
    const draftRevision = this.persistence.draftRevision();
    const draftFlowSha256 = this.persistence.savedFlowSha256();
    const evidenceFence = this.currentEvidenceFence();
    if (publicationMode && (draftRevision === null || !draftFlowSha256 || !v.flow_sha256)) {
      this.setPreviewError(v, 'Reload the authoritative Draft/Published pointers first.');
      return;
    }
    const generation = this.previewGeneration;
    this.setPreviewState(v, { status: 'loading', fence: evidenceFence });
    const scope = this.workspace.captureRequestScope();
    const fullRequest = this.canonical.getSystemVersion(sid, v.version_number, {
      propagateErrors: true,
    });
    const semanticRequest = publicationMode
      ? this.canonical.getSystemFlowDiff(sid, `version:${v.version_number}`, 'draft')
      : of<SystemFlowDiff | null>(null);
    forkJoin({ full: fullRequest, semanticDiff: semanticRequest }).subscribe({
      next: ({ full, semanticDiff }) => {
        if (
          generation !== this.previewGeneration ||
          !this.workspace.isRequestScopeCurrent(scope) ||
          evidenceFence !== this.currentEvidenceFence()
        ) {
          return;
        }
        const error = exactFlowVersionPreviewError({
          publicationMode,
          systemId: sid,
          summary: v,
          full,
          semanticDiff,
          draftRevision,
          draftFlowSha256,
        });
        if (error || !full) {
          this.setPreviewError(v, error ?? 'The exact preview could not be verified.');
          return;
        }
        this.previews.update((current) => ({ ...current, [v.id]: full }));
        if (semanticDiff) {
          this.semanticDiffs.update((current) => ({ ...current, [v.id]: semanticDiff }));
        }
        this.setPreviewState(v, { status: 'ready', fence: evidenceFence });
      },
      error: () => {
        if (
          generation !== this.previewGeneration ||
          !this.workspace.isRequestScopeCurrent(scope) ||
          evidenceFence !== this.currentEvidenceFence()
        ) {
          return;
        }
        this.setPreviewError(
          v,
          publicationMode
            ? 'Could not verify the immutable payload and authoritative semantic diff.'
            : 'Could not load the immutable version payload.',
        );
      },
    });
  }

  isCurrent(v: SystemVersionSummary, index: number): boolean {
    return isFlowVersionCurrent(v, index, this.versionIdentityContext());
  }

  restoreBlocked(v: SystemVersionSummary, index: number): boolean {
    return isFlowVersionRestoreBlocked(v, index, this.versionIdentityContext());
  }

  restoreBlockReason(v: SystemVersionSummary, index: number): string | null {
    return flowVersionRestoreBlockReason(v, index, {
      ...this.versionIdentityContext(),
      historyError: !!this.historyError(),
      restorePending: this.rollbackPending(),
      writeInProgress: this.persistence.actionsDisabled(),
      localChanges: this.store.dirty(),
    });
  }

  restoreTitle(v: SystemVersionSummary, index: number): string {
    const reason = this.restoreBlockReason(v, index);
    if (reason) return reason;
    return this.persistence.publicationMode()
      ? 'Restore this immutable version into the server draft; the published pointer stays unchanged'
      : 'Restore this version by appending a copy of its graph';
  }

  previewStatus(v: SystemVersionSummary): FlowVersionPreviewStatus {
    return this.previewStates()[v.id]?.status ?? 'idle';
  }

  previewError(v: SystemVersionSummary): string | null {
    const state = this.previewStates()[v.id];
    return state?.status === 'error' ? state.message ?? 'Exact preview failed.' : null;
  }

  previewReady(v: SystemVersionSummary): boolean {
    const state = this.previewStates()[v.id];
    return state?.status === 'ready'
      && state.fence === this.currentEvidenceFence()
      && !!this.previews()[v.id];
  }

  beginRollback(v: SystemVersionSummary): void {
    const index = this.versions().findIndex((version) => version.id === v.id);
    if (index < 0 || this.restoreBlockReason(v, index)) return;
    this.rollbackTarget.set(v);
    this.rollbackMessage.set('');
    this.preview(v);
  }

  cancelRollback(): void {
    if (this.rollbackPending()) return;
    this.rollbackTarget.set(null);
    this.rollbackMessage.set('');
  }

  onMessage(ev: Event): void {
    this.rollbackMessage.set((ev.target as HTMLInputElement | null)?.value ?? '');
  }

  confirmRollback(): void {
    const sid = this.systemId();
    const tgt = this.rollbackTarget();
    if (!sid || !tgt) return;
    if (!this.previewReady(tgt)) {
      this.preview(tgt);
      this.toastr.warning(
        'Load and verify the exact immutable version before confirming.',
        'Rollback blocked',
      );
      return;
    }
    if (this.store.dirty()) {
      this.toastr.warning(
        'Save or discard local changes before rolling back.',
        'Rollback blocked',
      );
      return;
    }
    if (this.persistence.publicationMode()) {
      this.restorePublishedVersionToDraft(sid, tgt);
      return;
    }
    const writeOptions = this.persistence.rollbackWriteOptions();
    if (!writeOptions) {
      this.toastr.warning(
        'Reload the authoritative System before rolling back.',
        'Rollback blocked',
      );
      return;
    }
    if (!this.persistence.beginExternalMutation()) return;
    this.rollbackPending.set(true);
    const scope = this.workspace.captureRequestScope();
    const message = this.rollbackMessage().trim() || `rollback to v${tgt.version_number}`;
    this.canonical
      .rollbackSystemVersion(sid, tgt.version_number, message, writeOptions)
      .subscribe({
        next: (res) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.rollbackPending.set(false);
          if (!res) {
            // The request may have committed even when its response was lost.
            // Keep the graph non-interactive until a strict GET resolves truth.
            this.invalidateBaseline();
            this.persistence.beginHydration();
            this.reloadRequired.emit();
            this.toastr.warning(
              'Rollback outcome is unknown. Reloading the authoritative Flow.',
              'Rollback verification',
            );
            return;
          }
          this.rollbackTarget.set(null);
          this.rollbackMessage.set('');
          // Output delivery is synchronous: the builder/persistence owner hydrates
          // the authoritative System before we recapture the read-only diff base.
          this.rolledBack.emit(res.system);
          this.persistence.endExternalMutation();
          this.captureBaseline();
          this.refresh();
          this.toastr.success(
            `Rolled back to v${tgt.version_number} (new v${res.new_version.version_number}).`,
            'Rollback',
          );
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.rollbackPending.set(false);
          this.invalidateBaseline();
          this.persistence.beginHydration();
          this.reloadRequired.emit();
          this.toastr.warning(
            'Rollback outcome is unknown. Reloading the authoritative Flow.',
            'Rollback verification',
          );
        },
      });
  }

  private restorePublishedVersionToDraft(
    sid: string,
    tgt: SystemVersionSummary,
  ): void {
    const expectedRevision = this.persistence.draftRevision();
    if (expectedRevision === null) {
      this.toastr.warning(
        'Reload the authoritative server draft before restoring a version.',
        'Restore blocked',
      );
      return;
    }
    if (!this.persistence.beginExternalMutation()) return;
    this.rollbackPending.set(true);
    const scope = this.workspace.captureRequestScope();
    this.canonical
      .restoreSystemFlowDraft(sid, tgt.id, expectedRevision)
      .subscribe({
        next: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.rollbackPending.set(false);
          this.rollbackTarget.set(null);
          this.rollbackMessage.set('');
          // Strict flow-state hydration owns the authoritative replacement;
          // never derive it from the preview row or System mirror.
          this.invalidateBaseline();
          this.persistence.beginHydration();
          this.reloadRequired.emit();
          this.toastr.success(
            `v${tgt.version_number} restored to the server draft. Published Flow unchanged.`,
            'Draft restored',
          );
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.rollbackPending.set(false);
          this.invalidateBaseline();
          this.persistence.beginHydration();
          this.reloadRequired.emit();
          this.toastr.warning(
            'Restore outcome is unknown. Reloading the authoritative server draft.',
            'Restore verification',
          );
        },
      });
  }

  /** Count-only hint until Preview loads the payload; then a semantic diff of
   * node kind/ports/config, full edge routes and Flow metadata. */
  diffLabel(v: SystemVersionSummary): string | null {
    const baseline = this.baseline;
    if (!baseline) return null;
    const preview = this.previews()[v.id];
    if (!preview) {
      const dn = v.node_count - baseline.nodes.length;
      const de = v.edge_count - baseline.edges.length;
      if (dn === 0 && de === 0) return 'counts match · preview for semantic diff';
      const parts: string[] = [];
      if (dn !== 0) parts.push(`${dn > 0 ? '+' : ''}${dn}n`);
      if (de !== 0) parts.push(`${de > 0 ? '+' : ''}${de}e`);
      return `${parts.join(' ')} counts · preview for semantic diff`;
    }
    const serverDiff = this.semanticDiffs()[v.id];
    if (this.persistence.publicationMode()) {
      return serverDiff
        ? formatServerFlowSemanticDiff(serverDiff)
        : 'authoritative semantic diff unavailable';
    }
    const flow = preview.flow_definition as unknown as CanonicalFlow;
    return formatFlowSemanticDiff(diffCanonicalFlows(baseline, flow));
  }

  relativeTime(iso: string): string {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return iso;
    const sec = Math.round((Date.now() - t) / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.round(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.round(hr / 24);
    if (day < 14) return `${day}d ago`;
    return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  private captureBaseline(): void {
    this.baseline = this.store.snapshot();
    this.baselineRevision = this.store.revision();
    this.invalidatePreviewEvidence();
  }

  private invalidateBaseline(): void {
    this.baseline = null;
    this.baselineRevision = null;
    this.invalidatePreviewEvidence();
  }

  private invalidatePreviewEvidence(): void {
    this.previewGeneration += 1;
    this.previews.set({});
    this.semanticDiffs.set({});
    this.previewStates.set({});
  }

  private setPreviewState(
    version: SystemVersionSummary,
    state: FlowVersionPreviewState,
  ): void {
    this.previewStates.update((current) => ({ ...current, [version.id]: state }));
  }

  private setPreviewError(version: SystemVersionSummary, message: string): void {
    this.previews.update((current) => {
      const next = { ...current };
      delete next[version.id];
      return next;
    });
    this.semanticDiffs.update((current) => {
      const next = { ...current };
      delete next[version.id];
      return next;
    });
    this.setPreviewState(version, { status: 'error', message });
  }

  private versionIdentityContext(): FlowVersionIdentityContext {
    return {
      publicationMode: this.persistence.publicationMode(),
      publishedVersionId: this.persistence.publishedVersionId(),
      draftMatchesPublished: this.persistence.draftMatchesPublished(),
    };
  }

  private currentEvidenceFence(): string {
    const contract = this.persistence.publishedExecutionContract();
    const contractIdentity = contract?.['contract_sha256'] ?? contract ?? null;
    return JSON.stringify({
      systemId: this.systemId(),
      publicationMode: this.persistence.publicationMode(),
      draftRevision: this.persistence.draftRevision(),
      savedFlowSha256: this.persistence.savedFlowSha256(),
      publishedVersionId: this.persistence.publishedVersionId(),
      publishedFlowSha256: this.persistence.publishedFlowSha256(),
      publishedContractReady: this.persistence.publishedContractReady(),
      publishedExecutionContract: contractIdentity,
    });
  }
}
