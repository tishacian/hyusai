import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ToastrService } from 'ngx-toastr';
import { CanonicalApiService, type Context, type System } from '@app/core/canonical-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { TagComponent } from '@app/shared/cockpit';
import { ChatPanelComponent } from './chat-panel.component';
import { type ChatStartMode } from './chat-overlay.service';

/**
 * `ChatWorkspaceComponent` — the global chat surface (Vague D / D0).
 *
 * Three modes co-exist on the same layout:
 *  - `quick`   — no System selected; uses workspace RAG defaults.
 *  - `system`  — a System scopes the conversation (policy, skills, knowledge).
 *  - `drop`    — an ephemeral `Context` is created; dropped files are indexed
 *                into the workspace's default `documents` collection so the
 *                existing RAG pipeline grounds answers on them without any
 *                backend rework. The ephemeral Context tracks the doc ids
 *                in `data_refs` for traceability, and can be promoted to a
 *                permanent Context via `POST /contexts/{id}/persist`.
 *
 * Used both by:
 *  - `ChatOverlayComponent` — mounted inside a `ck-panel` side-panel
 *    (560px), triggered by the title-bar icon / ⌘J / palette commands.
 *  - Route `/chat` — full-screen wrapping container for focus mode and
 *    drop-and-ask demo sessions.
 *
 * The [inline] input switches between compact overlay layout (stacked,
 * dropzone collapsible) and the full-screen two-column layout.
 */
@Component({
  selector: 'app-chat-workspace',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent, TagComponent, ChatPanelComponent],
  template: `
    <div class="t-shell" [class.t-inline]="inline()">
      <!-- Header — system picker + mode badge -->
      <header class="t-header">
        <div class="t-header-left">
          <ck-tag [tone]="modeTone()" variant="solid">{{ modeLabel() }}</ck-tag>
          <span class="t-header-hint">{{ modeHint() }}</span>
        </div>
        <div class="t-header-right">
          <label class="t-picker-label">System</label>
          <select
            class="t-picker"
            [(ngModel)]="selectedSystemId"
            (ngModelChange)="onSystemChange($event)"
          >
            <option [ngValue]="null">— Quick ask (workspace defaults)</option>
            @for (s of systems(); track s.id) {
              <option [ngValue]="s.id">{{ s.name }}</option>
            }
          </select>
        </div>
      </header>

      <!-- Body: two-column (side panel in inline mode, full split in full-screen) -->
      <div class="t-body">
        <!-- Drop-and-ask sidebar -->
        <aside class="t-sidebar" [class.t-sidebar-collapsed]="!dropOpen() && inline()">
          <div class="t-sidebar-head">
            <span class="ck-mono t-sidebar-eyebrow">Session docs</span>
            @if (inline()) {
              <button
                type="button"
                class="t-mini-btn"
                (click)="dropOpen.set(!dropOpen())"
                [title]="dropOpen() ? 'Collapse dropzone' : 'Expand dropzone'"
              >
                <app-icon [name]="dropOpen() ? 'chevron-up' : 'chevron-down'" [size]="12" />
              </button>
            }
          </div>

          @if (dropOpen() || !inline()) {
            <!-- Dropzone -->
            <div
              class="t-dropzone"
              [class.t-dropzone-hot]="dragging()"
              (dragover)="onDragOver($event)"
              (dragleave)="onDragLeave($event)"
              (drop)="onDrop($event)"
              (click)="fileInput.click()"
            >
              <input
                #fileInput
                type="file"
                multiple
                class="t-file-input"
                (change)="onFileSelect($event)"
                accept=".pdf,.txt,.md,.docx,.csv,.json"
              />
              <div class="t-drop-icon">
                <app-icon name="cloud-upload" [size]="18" />
              </div>
              <div class="t-drop-text">
                Drop files <span class="t-drop-accent">or click</span>
              </div>
              <div class="t-drop-hint">PDF · TXT · MD · DOCX · CSV · JSON</div>
              @if (uploading()) {
                <div class="t-drop-progress">
                  <app-icon name="loader-2" [size]="12" class="animate-spin" />
                  Indexing {{ uploadingCount() }}…
                </div>
              }
            </div>

            <!-- Attached docs -->
            @if (sessionDocs().length > 0) {
              <div class="t-docs">
                <div class="t-docs-head">
                  <span class="ck-mono t-docs-count">
                    {{ sessionDocs().length }} file(s)
                  </span>
                  @if (ephemeralContextId()) {
                    <button
                      type="button"
                      class="t-persist-btn"
                      (click)="persistContext()"
                      [disabled]="persisting()"
                      title="Keep this session context permanently"
                    >
                      <app-icon [name]="persisting() ? 'loader-2' : 'save'" [size]="11" [class.animate-spin]="persisting()" />
                      Persist
                    </button>
                  }
                </div>
                <ul class="t-docs-list">
                  @for (d of sessionDocs(); track d) {
                    <li class="t-doc-item">
                      <app-icon name="file-text" [size]="11" />
                      <span class="t-doc-name">{{ d }}</span>
                    </li>
                  }
                </ul>
              </div>
            } @else {
              <div class="t-empty-hint">
                No docs yet. Drop PDFs or click browse to ground answers on
                your own files.
              </div>
            }
          }
        </aside>

        <!-- Chat panel -->
        <section class="t-chat">
          <app-chat-panel
            [systemId]="selectedSystemId"
            [contextId]="ephemeralContextId()"
          />
        </section>
      </div>
    </div>
  `,
  styles: [`
    :host {
      display: block;
      height: 100%;
      width: 100%;
    }
    .t-shell {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--ck-bg-base, #0a0e14);
      color: var(--ck-fg-1);
    }
    .t-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--ck-stroke-2);
      flex-shrink: 0;
      min-height: 44px;
    }
    .t-header-left {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .t-header-hint {
      font-size: 11px;
      color: var(--ck-fg-4);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .t-header-right {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .t-picker-label {
      font-family: var(--ck-font-mono);
      font-size: 9px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ck-fg-4);
    }
    .t-picker {
      background: var(--ck-bg-inset);
      border: 1px solid var(--ck-stroke-2);
      border-radius: 4px;
      color: var(--ck-fg-1);
      font-size: 12px;
      padding: 4px 8px;
      min-width: 200px;
      max-width: 260px;
    }
    .t-body {
      flex: 1 1 auto;
      display: flex;
      min-height: 0;
      overflow: hidden;
    }
    .t-sidebar {
      width: 280px;
      flex: 0 0 280px;
      border-right: 1px solid var(--ck-stroke-2);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      overflow-y: auto;
      background: rgba(255, 255, 255, 0.01);
    }
    /* In inline (overlay) mode the sidebar stacks above the chat. */
    .t-inline .t-body {
      flex-direction: column;
    }
    .t-inline .t-sidebar {
      width: 100%;
      flex: 0 0 auto;
      border-right: 0;
      border-bottom: 1px solid var(--ck-stroke-2);
      padding: 10px 12px;
      gap: 8px;
    }
    .t-inline .t-sidebar-collapsed {
      padding: 6px 12px;
    }
    .t-sidebar-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .t-sidebar-eyebrow {
      font-size: 9px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ck-fg-4);
    }
    .t-mini-btn {
      background: transparent;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      color: var(--ck-fg-3);
      padding: 2px 4px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
    }
    .t-dropzone {
      position: relative;
      border: 1px dashed var(--ck-stroke-2);
      border-radius: 6px;
      padding: 14px 12px;
      text-align: center;
      cursor: pointer;
      transition: border-color 120ms, background 120ms;
      background: transparent;
    }
    .t-dropzone:hover {
      border-color: var(--ck-signal-cool);
      background: rgba(125, 211, 252, 0.04);
    }
    .t-dropzone-hot {
      border-color: var(--ck-signal-cool) !important;
      background: rgba(125, 211, 252, 0.08) !important;
    }
    .t-file-input { display: none; }
    .t-drop-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--ck-signal-cool);
      margin-bottom: 4px;
    }
    .t-drop-text {
      font-size: 12px;
      color: var(--ck-fg-1);
    }
    .t-drop-accent { color: var(--ck-signal-cool); }
    .t-drop-hint {
      font-size: 10px;
      color: var(--ck-fg-4);
      margin-top: 2px;
    }
    .t-drop-progress {
      position: absolute;
      inset: auto 0 6px 0;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 10px;
      color: var(--ck-signal-cool);
    }
    .t-docs {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 4px;
      border-top: 1px dashed var(--ck-stroke-2);
    }
    .t-docs-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .t-docs-count {
      font-size: 9px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--ck-fg-3);
    }
    .t-persist-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      background: rgba(125, 211, 252, 0.08);
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      color: var(--ck-signal-cool);
      font-family: var(--ck-font-mono);
      font-size: 9px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      cursor: pointer;
      transition: background 120ms;
    }
    .t-persist-btn:hover:not([disabled]) {
      background: rgba(125, 211, 252, 0.14);
    }
    .t-persist-btn[disabled] { opacity: 0.5; cursor: wait; }
    .t-docs-list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .t-doc-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      color: var(--ck-fg-2);
      padding: 2px 4px;
    }
    .t-doc-name {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .t-empty-hint {
      font-size: 10px;
      color: var(--ck-fg-4);
      line-height: 1.5;
      padding-top: 4px;
    }
    .t-chat {
      flex: 1 1 auto;
      min-width: 0;
      min-height: 0;
      display: flex;
      overflow: hidden;
    }
    .t-chat > * {
      flex: 1 1 auto;
      width: 100%;
      min-height: 0;
    }
    @keyframes chatSpin { to { transform: rotate(360deg); } }
    .animate-spin { animation: chatSpin 1s linear infinite; }
  `],
})
export class ChatWorkspaceComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly http = inject(HttpClient);
  private readonly toast = inject(ToastrService);

  /** When `true`, render the compact (overlay) layout. Full-screen otherwise. */
  readonly inline = input<boolean>(false);
  /** Optional hint about which start mode to pre-select. */
  readonly startMode = input<ChatStartMode>('quick');
  /** Optional System id pre-selected (from palette command or query param). */
  readonly initialSystemId = input<string | null>(null);
  /** Optional ephemeral Context id to reuse (e.g. URL-shared session). */
  readonly initialContextId = input<string | null>(null);

  readonly systems = signal<System[]>([]);
  selectedSystemId: string | null = null;

  readonly ephemeralContextId = signal<string | null>(null);
  readonly sessionDocs = signal<string[]>([]);

  readonly dragging = signal(false);
  readonly uploading = signal(false);
  readonly uploadingCount = signal(0);
  readonly persisting = signal(false);

  /** Collapsed state of the dropzone in inline mode (always open full-screen). */
  readonly dropOpen = signal(true);

  readonly modeLabel = computed<string>(() => {
    if (this.ephemeralContextId()) return 'Drop-and-ask';
    if (this.selectedSystemId) return 'System chat';
    return 'Quick ask';
  });

  readonly modeTone = computed<'cool' | 'violet' | 'pos'>(() => {
    if (this.ephemeralContextId()) return 'violet';
    if (this.selectedSystemId) return 'cool';
    return 'pos';
  });

  readonly modeHint = computed<string>(() => {
    if (this.ephemeralContextId()) return 'Session docs ground the answer';
    if (this.selectedSystemId) {
      const s = this.systems().find((x) => x.id === this.selectedSystemId);
      return s?.objective || 'Scoped to selected system';
    }
    return 'No system — workspace defaults';
  });

  ngOnInit(): void {
    this.selectedSystemId = this.initialSystemId() ?? null;
    this.ephemeralContextId.set(this.initialContextId() ?? null);
    // Inline overlay: keep dropzone collapsed unless drop-mode was asked.
    if (this.inline() && this.startMode() !== 'drop') {
      this.dropOpen.set(false);
    }
    this.loadSystems();
  }

  private loadSystems(): void {
    this.canonical.listSystems().subscribe({
      next: (list) => this.systems.set(list || []),
      error: () => this.systems.set([]),
    });
  }

  onSystemChange(id: string | null): void {
    this.selectedSystemId = id;
  }

  onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(true);
  }
  onDragLeave(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
  }
  onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    const files = e.dataTransfer?.files;
    if (files && files.length) this.uploadFiles(files);
  }
  onFileSelect(e: Event): void {
    const input = e.target as HTMLInputElement;
    if (input.files && input.files.length) this.uploadFiles(input.files);
    input.value = '';
  }

  /**
   * Upload dropped files to the workspace's default `documents` collection
   * (reuses the existing `/api/v1/documents/upload-batch` endpoint) and
   * either creates or extends an ephemeral Context with the resulting
   * file list in `data_refs`. The Context id is then handed to
   * `<app-chat-panel>` as `contextId` so downstream audit logs can link
   * each message to the drop-and-ask session.
   *
   * We intentionally index into the workspace default collection (instead
   * of a per-session collection) so the existing RAG pipeline grounds
   * answers on the new documents without any backend rework. Users can
   * later `Persist` the Context, which promotes it to permanent while
   * keeping the documents in the workspace knowledge base.
   */
  private uploadFiles(files: FileList): void {
    this.uploading.set(true);
    this.uploadingCount.set(files.length);
    const formData = new FormData();
    Array.from(files).forEach((f) => formData.append('files', f));
    formData.append('collection_name', 'documents');

    this.http
      .post<{ total: number; successful: number; failed: number }>(
        '/api/v1/documents/upload-batch',
        formData,
      )
      .subscribe({
        next: (res) => {
          this.uploading.set(false);
          const added = Array.from(files).map((f) => f.name);
          this.sessionDocs.update((prev) => [...prev, ...added]);
          this.ensureEphemeralContext(added);
          if (res.failed > 0) {
            this.toast.warning(
              `${res.successful}/${res.total} indexed · ${res.failed} failed`,
              'Drop-and-ask',
            );
          } else {
            this.toast.success(
              `${res.successful} file(s) indexed — ask anything.`,
              'Drop-and-ask',
            );
          }
        },
        error: (err) => {
          this.uploading.set(false);
          this.toast.error(
            err?.error?.detail || 'Failed to upload',
            'Drop-and-ask',
          );
        },
      });
  }

  private ensureEphemeralContext(newDocs: string[]): void {
    const existing = this.ephemeralContextId();
    if (existing) {
      this.canonical
        .updateContext(existing, {
          data_refs: [...this.sessionDocs()],
        })
        .subscribe();
      return;
    }
    this.canonical
      .createContext({
        name: `Drop-and-ask · ${new Date().toLocaleString()}`,
        data_refs: newDocs,
        ephemeral: true,
        ttl_hours: 24,
      })
      .subscribe({
        next: (ctx) => {
          if (ctx) this.ephemeralContextId.set(ctx.id);
        },
      });
  }

  persistContext(): void {
    const id = this.ephemeralContextId();
    if (!id || this.persisting()) return;
    this.persisting.set(true);
    this.canonical.persistContext(id).subscribe({
      next: (ctx) => {
        this.persisting.set(false);
        if (ctx) {
          this.toast.success(
            `Saved as "${ctx.name}"`,
            'Session persisted',
          );
        }
      },
      error: () => {
        this.persisting.set(false);
        this.toast.error('Failed to persist session', 'Drop-and-ask');
      },
    });
  }
}
