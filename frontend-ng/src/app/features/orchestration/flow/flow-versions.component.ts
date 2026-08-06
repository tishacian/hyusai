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
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { ToastrService } from 'ngx-toastr';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  CanonicalApiService,
  type System,
  type SystemVersionFull,
  type SystemVersionSummary,
} from '@app/core/canonical-api.service';
import type {
  CanonicalFlow,
  CanonicalFlowEdge,
  CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowPersistenceService } from './flow-persistence.service';
import { WorkspaceService } from '@app/core/workspace.service';

const PAGE_SIZE = 25;

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
      subtitle="Append-only · roll back to any version"
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
            [disabled]="loading()"
            title="Refresh"
            aria-label="Refresh versions"
          >
            <app-icon name="refresh-cw" [size]="13" />
          </button>
        </header>

        @if (loading() && versions().length === 0) {
          <p class="ck-vers__empty">Loading…</p>
        } @else if (versions().length === 0) {
          <p class="ck-vers__empty">No history yet. The first save on this System seeds v1.</p>
        } @else {
          <ol class="ck-vers__list">
            @for (v of versions(); track v.id; let i = $index) {
              <li class="ck-vers__row" [class.is-current]="i === 0">
                <div class="ck-vers__row-head">
                  <span class="ck-vers__num">v{{ v.version_number }}</span>
                  @if (i === 0) { <span class="ck-vers__tag" data-tone="pos">CURRENT</span> }
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
                    [disabled]="i === 0"
                    title="Prefetch + show exact diff"
                  >
                    <app-icon name="eye" [size]="12" /> Preview
                  </button>
                  <button
                    type="button"
                    class="ck-vers__btn ck-vers__btn--warn"
                    (click)="beginRollback(v)"
                    [disabled]="
                      i === 0 ||
                      rollbackPending() ||
                      persistence.actionsDisabled() ||
                      store.dirty()
                    "
                    [title]="i === 0 ? 'Already current' : 'Roll back to this version'"
                  >
                    <app-icon name="rotate-ccw" [size]="12" /> Roll back
                  </button>
                </div>
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
              Create a new version that copies <strong>v{{ tgt.version_number }}</strong>'s graph and
              replaces the canvas. History is append-only — nothing is deleted.
            </p>
            <input
              type="text"
              class="ck-vers__confirm-input"
              [value]="rollbackMessage()"
              (input)="onMessage($event)"
              [placeholder]="'rollback to v' + tgt.version_number"
              maxlength="280"
              aria-label="Rollback message"
            />
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
                  store.dirty()
                "
              >
                @if (rollbackPending()) {
                  <app-icon name="loader-2" [size]="12" class="ck-vers__spin" /> Rolling back…
                } @else {
                  <app-icon name="rotate-ccw" [size]="12" /> Confirm
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
  readonly rollbackTarget = signal<SystemVersionSummary | null>(null);
  readonly rollbackMessage = signal('');
  readonly rollbackPending = signal(false);

  private readonly previews = signal<Record<number, SystemVersionFull>>({});
  private baseline: { nodes: Set<string>; edges: Set<string> } = {
    nodes: new Set(),
    edges: new Set(),
  };
  /** Tracks the current open session so reopening reloads a fresh first page. */
  private opened = false;

  constructor() {
    const unregisterReset = this.workspace.registerContextReset(() => {
      this.opened = false;
      this.versions.set([]);
      this.total.set(0);
      this.loading.set(false);
      this.loadingMore.set(false);
      this.rollbackTarget.set(null);
      this.rollbackPending.set(false);
      this.previews.set({});
    });
    this.destroyRef.onDestroy(unregisterReset);

    effect(() => {
      const isOpen = this.open();
      if (isOpen && !this.opened) {
        this.opened = true;
        this.captureBaseline();
        this.refresh();
      } else if (!isOpen) {
        this.opened = false;
      }
    });
  }

  refresh(): void {
    const sid = this.systemId();
    if (!sid) return;
    this.loading.set(true);
    this.previews.set({});
    const scope = this.workspace.captureRequestScope();
    this.canonical.listSystemVersions(sid, { limit: PAGE_SIZE, offset: 0 }).subscribe({
      next: (res) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false);
        this.versions.set(res.versions ?? []);
        this.total.set(res.total ?? 0);
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false);
        this.toastr.error('Could not load version history.', 'Versions');
      },
    });
  }

  loadMore(): void {
    const sid = this.systemId();
    if (!sid || this.loadingMore()) return;
    this.loadingMore.set(true);
    const scope = this.workspace.captureRequestScope();
    this.canonical
      .listSystemVersions(sid, { limit: PAGE_SIZE, offset: this.versions().length })
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
    if (!sid || this.previews()[v.version_number]) return;
    const scope = this.workspace.captureRequestScope();
    this.canonical.getSystemVersion(sid, v.version_number).subscribe((full) => {
      if (!this.workspace.isRequestScopeCurrent(scope)) return;
      if (full) this.previews.update((m) => ({ ...m, [v.version_number]: full }));
    });
  }

  beginRollback(v: SystemVersionSummary): void {
    if (this.persistence.actionsDisabled() || this.store.dirty()) return;
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
    if (this.store.dirty()) {
      this.toastr.warning(
        'Save or discard local changes before rolling back.',
        'Rollback blocked',
      );
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
          this.persistence.beginHydration();
          this.reloadRequired.emit();
          this.toastr.warning(
            'Rollback outcome is unknown. Reloading the authoritative Flow.',
            'Rollback verification',
          );
        },
      });
  }

  /** Node/edge delta vs the live canvas. Exact once a preview is prefetched. */
  diffLabel(v: SystemVersionSummary): string | null {
    if (this.baseline.nodes.size === 0 && this.baseline.edges.size === 0) return null;
    const preview = this.previews()[v.version_number];
    if (!preview) {
      const dn = v.node_count - this.baseline.nodes.size;
      const de = v.edge_count - this.baseline.edges.size;
      if (dn === 0 && de === 0) return '= canvas';
      const parts: string[] = [];
      if (dn !== 0) parts.push(`${dn > 0 ? '+' : ''}${dn}n`);
      if (de !== 0) parts.push(`${de > 0 ? '+' : ''}${de}e`);
      return parts.join(' ');
    }
    const flow = preview.flow_definition as unknown as CanonicalFlow;
    const otherNodes = new Set((flow?.nodes ?? []).map((n: CanonicalFlowNode) => String(n.id)));
    const otherEdges = new Set(
      (flow?.edges ?? []).map((e: CanonicalFlowEdge) => `${e.from}->${e.to}`),
    );
    let added = 0;
    let removed = 0;
    for (const n of otherNodes) if (!this.baseline.nodes.has(n)) added++;
    for (const n of this.baseline.nodes) if (!otherNodes.has(n)) removed++;
    let ea = 0;
    let er = 0;
    for (const e of otherEdges) if (!this.baseline.edges.has(e)) ea++;
    for (const e of this.baseline.edges) if (!otherEdges.has(e)) er++;
    if (added + removed + ea + er === 0) return '= canvas';
    const parts: string[] = [];
    if (added || removed) parts.push(`${added ? '+' + added : ''}${removed ? ' -' + removed : ''}n`.trim());
    if (ea || er) parts.push(`${ea ? '+' + ea : ''}${er ? ' -' + er : ''}e`.trim());
    return parts.join(' · ');
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
    const flow = this.store.snapshot();
    this.baseline = {
      nodes: new Set(flow.nodes.map((n) => String(n.id))),
      edges: new Set(flow.edges.map((e) => `${e.from}->${e.to}`)),
    };
  }
}
