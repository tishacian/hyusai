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
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { TagComponent } from '@app/shared/cockpit';
import { ChatPanelComponent } from './chat-panel.component';
import { type ChatStartMode } from './chat-overlay.service';

/**
 * Shape of the docmeta payload returned by
 * `GET /api/v1/documents/{id}/metadata`. All fields are optional because
 * docmeta degrades gracefully (missing PDF author, missing NLTK corpus, …)
 * and the UI must never blow up on a partial response.
 */
interface DocFacts {
  document_title?: string;
  document_filename?: string;
  document_author?: string;
  document_num_pages?: number;
  document_num_slides?: number;
  document_num_sheets?: number;
  document_word_count?: number;
  document_line_count?: number;
  document_token_count?: number;
  document_language?: string;
  document_extracted_keywords?: string[];
  chunks_count?: number;
  [key: string]: unknown;
}

interface SessionDoc {
  /** Backend document_id; undefined while the upload is in flight. */
  id?: string;
  /** Display name (original filename). */
  filename: string;
  /** Whether we're currently fetching docmeta for this doc. */
  metaLoading: boolean;
  /** Resolved docmeta payload, or `null` if the endpoint returned 404. */
  meta: DocFacts | null;
}

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
        @if (executiveAssistant()) {
          <div class="t-header-left">
            <ck-tag tone="cool" variant="solid">Question directe</ck-tag>
            <span class="t-header-hint">{{ assistantSubtitle() }}</span>
          </div>
          <div class="t-header-right">
            <span class="t-source-pill">{{ assistantScopeLabel() }}</span>
          </div>
        } @else {
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
        }
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

            <!-- Attached docs — each entry carries an expandable "Doc facts"
                 panel populated by GET /documents/{id}/metadata. We render
                 title + filename, and on docmeta arrival show top keywords
                 + page/token counts so operators can eyeball retrieval at
                 a glance without leaving the chat. -->
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
                  @for (d of sessionDocs(); track (d.id || d.filename)) {
                    <li class="t-doc-item">
                      <div class="t-doc-row">
                        <app-icon name="file-text" [size]="11" />
                        <span class="t-doc-name" [title]="displayTitle(d)">
                          {{ displayTitle(d) }}
                        </span>
                        @if (d.metaLoading) {
                          <app-icon name="loader-2" [size]="10" class="animate-spin t-doc-spin" />
                        }
                      </div>
                      @if (d.meta) {
                        <div class="t-doc-facts">
                          <!-- Counts line: pages · tokens · chunks. We keep
                               it glyph-free (the icon registry curates only
                               the icons shipped with the app bundle) and
                               rely on labels + mono font for scannability. -->
                          <div class="t-doc-stats">
                            @if (pageCount(d); as p) {
                              <span class="t-doc-stat">
                                {{ p }} page{{ p === 1 ? '' : 's' }}
                              </span>
                            }
                            @if (d.meta.document_token_count !== undefined) {
                              <span class="t-doc-stat">
                                {{ formatTokens(d.meta.document_token_count) }} tokens
                              </span>
                            }
                            @if (d.meta.chunks_count !== undefined && d.meta.chunks_count !== null) {
                              <span class="t-doc-stat">
                                {{ d.meta.chunks_count }} chunks
                              </span>
                            }
                          </div>
                          @if (d.meta.document_author) {
                            <div class="t-doc-author">by {{ d.meta.document_author }}</div>
                          }
                          @if (topKeywords(d).length > 0) {
                            <div class="t-doc-keywords">
                              @for (kw of topKeywords(d); track kw) {
                                <span class="t-doc-kw">{{ kw }}</span>
                              }
                            </div>
                          }
                        </div>
                      }
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
            [assistantProfileKey]="assistantProfileKey()"
            [initialPrompt]="initialPrompt()"
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
    .t-source-pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid rgba(125, 211, 252, 0.22);
      background: rgba(125, 211, 252, 0.08);
      color: var(--ck-signal-cool);
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
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
      /* Let the sidebar grow up to ~45% of the overlay height, then scroll
         internally. Without this cap, expanding 'Session docs' with a
         multi-page Doc facts panel pushes the chat transcript (and the
         input bar) below the viewport. */
      flex: 0 1 auto;
      max-height: 45vh;
      border-right: 0;
      border-bottom: 1px solid var(--ck-stroke-2);
      padding: 10px 12px;
      gap: 8px;
      overflow-y: auto;
    }
    .t-inline .t-sidebar-collapsed {
      padding: 6px 12px;
      max-height: none;
    }
    /* Guarantee the chat pane always keeps a viable slice of the panel
       even when session docs expand, so the input bar stays reachable. */
    .t-inline .t-chat {
      min-height: 280px;
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
      gap: 6px;
    }
    .t-doc-item {
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 11px;
      color: var(--ck-fg-2);
      padding: 4px 6px;
      border-radius: 4px;
      border: 1px solid transparent;
      transition: border-color 120ms, background 120ms;
    }
    .t-doc-item:hover {
      border-color: var(--ck-stroke-2);
      background: rgba(255, 255, 255, 0.02);
    }
    .t-doc-row {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }
    .t-doc-name {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1 1 auto;
      min-width: 0;
    }
    .t-doc-spin {
      color: var(--ck-fg-4);
      flex-shrink: 0;
    }
    /* "Doc facts" panel: compact readout of docmeta-sourced fields. */
    .t-doc-facts {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding-left: 17px;
      font-size: 10px;
      color: var(--ck-fg-3);
    }
    .t-doc-stats {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--ck-fg-4);
      font-family: var(--ck-font-mono);
      font-size: 9px;
      letter-spacing: 0.04em;
    }
    .t-doc-stat {
      display: inline-flex;
      align-items: center;
      gap: 3px;
    }
    .t-doc-stat + .t-doc-stat::before {
      content: '·';
      color: var(--ck-fg-4);
      margin-right: 3px;
      opacity: 0.6;
    }
    .t-doc-author {
      font-style: italic;
      color: var(--ck-fg-4);
      font-size: 10px;
    }
    .t-doc-keywords {
      display: flex;
      flex-wrap: wrap;
      gap: 3px;
    }
    .t-doc-kw {
      font-size: 9px;
      padding: 1px 5px;
      border-radius: 8px;
      background: rgba(125, 211, 252, 0.08);
      color: var(--ck-signal-cool);
      border: 1px solid rgba(125, 211, 252, 0.2);
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
  private readonly workspace = inject(WorkspaceService);

  /** When `true`, render the compact (overlay) layout. Full-screen otherwise. */
  readonly inline = input<boolean>(false);
  /** Optional hint about which start mode to pre-select. */
  readonly startMode = input<ChatStartMode>('quick');
  /** Optional System id pre-selected (from palette command or query param). */
  readonly initialSystemId = input<string | null>(null);
  /** Optional ephemeral Context id to reuse (e.g. URL-shared session). */
  readonly initialContextId = input<string | null>(null);
  /** Optional workspace assistant profile (VIGIE, support copilot, etc.). */
  readonly assistantProfileKey = input<string | null>(null);
  /** Optional prompt prefilled when the assistant opens from a workspace app. */
  readonly initialPrompt = input<string | null>(null);

  readonly systems = signal<System[]>([]);
  selectedSystemId: string | null = null;

  readonly ephemeralContextId = signal<string | null>(null);
  /**
   * Docs attached to the current drop-and-ask session. Each entry is
   * hydrated asynchronously with its docmeta payload so the "Doc facts"
   * panel can render title / author / pages / tokens / keywords.
   */
  readonly sessionDocs = signal<SessionDoc[]>([]);

  readonly dragging = signal(false);
  readonly uploading = signal(false);
  readonly uploadingCount = signal(0);
  readonly persisting = signal(false);

  /** Collapsed state of the dropzone in inline mode (always open full-screen). */
  readonly dropOpen = signal(true);

  readonly activeAssistantProfile = computed<Record<string, unknown> | null>(() => {
    const key = this.assistantProfileKey() || this.workspace.current()?.settings?.['assistant_profile_default'];
    if (!key) return null;
    const profiles = this.workspace.current()?.settings?.['assistant_profiles'];
    if (!Array.isArray(profiles)) return null;
    return (profiles as Record<string, unknown>[]).find((profile) => profile['key'] === key) ?? null;
  });

  readonly executiveAssistant = computed(() => this.activeAssistantProfile()?.['executive_mode'] === true);

  readonly assistantSubtitle = computed(() => {
    const profile = this.activeAssistantProfile();
    return String(profile?.['subtitle'] || 'Sources du workspace');
  });

  readonly assistantScopeLabel = computed(() => {
    const profile = this.activeAssistantProfile();
    const scopeKey = String(profile?.['default_knowledge_scope'] || '');
    const scopes = this.workspace.current()?.settings?.['knowledge_scopes'];
    if (Array.isArray(scopes)) {
      const scope = (scopes as Record<string, unknown>[]).find((item) => item['key'] === scopeKey);
      if (scope?.['label']) return `Sources : ${scope['label']}`;
    }
    return 'Sources du workspace';
  });

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

    interface UploadResponse {
      total: number;
      successful: number;
      failed: number;
      documents?: Array<{
        document_id: string | null;
        filename: string | null;
        status: string | null;
        chunks_processed: number | null;
      }>;
    }

    this.http
      .post<UploadResponse>('/api/v1/documents/upload-batch', formData)
      .subscribe({
        next: (res) => {
          this.uploading.set(false);
          const addedDocs: SessionDoc[] = (res.documents ?? [])
            .filter((d) => d.status === 'success')
            .map((d) => ({
              id: d.document_id ?? undefined,
              filename: d.filename ?? 'unknown',
              metaLoading: !!d.document_id,
              meta: null,
            }));
          // Fallback in case the backend omitted per-doc ids (older deploys
          // or error path): still surface the filenames so the UI reflects
          // the drop.
          if (addedDocs.length === 0) {
            const fallback = Array.from(files).map<SessionDoc>((f) => ({
              filename: f.name,
              metaLoading: false,
              meta: null,
            }));
            this.sessionDocs.update((prev) => [...prev, ...fallback]);
          } else {
            this.sessionDocs.update((prev) => [...prev, ...addedDocs]);
            // Hydrate each newly-indexed doc's docmeta in parallel. Failures
            // silently leave `meta: null` so the row renders without facts.
            addedDocs.forEach((doc) => {
              if (!doc.id) return;
              this.fetchDocMetadata(doc.id);
            });
          }
          const added = (res.documents ?? []).map((d) => d.filename ?? '');
          this.ensureEphemeralContext(
            added.filter((n): n is string => !!n),
          );
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

  /**
   * Fetch docmeta for a single document and patch the corresponding
   * ``SessionDoc`` entry in place. Runs out-of-band from the upload flow
   * so a slow metadata endpoint never blocks the "file indexed" toast.
   */
  private fetchDocMetadata(documentId: string): void {
    this.http
      .get<{ document_id: string; metadata: DocFacts }>(
        `/api/v1/documents/${documentId}/metadata`,
      )
      .subscribe({
        next: (res) => {
          this.sessionDocs.update((prev) =>
            prev.map((d) =>
              d.id === documentId
                ? { ...d, meta: res.metadata ?? null, metaLoading: false }
                : d,
            ),
          );
        },
        error: () => {
          this.sessionDocs.update((prev) =>
            prev.map((d) =>
              d.id === documentId
                ? { ...d, meta: null, metaLoading: false }
                : d,
            ),
          );
        },
      });
  }

  /** Compact display title for a session doc (docmeta title > filename). */
  displayTitle(doc: SessionDoc): string {
    return (
      doc.meta?.document_title?.trim() ||
      doc.meta?.document_filename?.trim() ||
      doc.filename
    );
  }

  /** Top N keywords for inline chips ("cockpit · stockage vectoriel · …"). */
  topKeywords(doc: SessionDoc, limit = 4): string[] {
    const raw = doc.meta?.document_extracted_keywords ?? [];
    return raw.slice(0, limit);
  }

  /** Best-effort "pages" value — PDFs, Office slides, Office sheets, or ø. */
  pageCount(doc: SessionDoc): number | null {
    return (
      doc.meta?.document_num_pages ??
      doc.meta?.document_num_slides ??
      doc.meta?.document_num_sheets ??
      null
    );
  }

  /** Short formatted number (e.g. 1342 → "1.3k tokens"). */
  formatTokens(count: number | undefined): string {
    if (!count && count !== 0) return '—';
    if (count >= 10_000) return `${(count / 1000).toFixed(1)}k`;
    return `${count}`;
  }

  private ensureEphemeralContext(newDocs: string[]): void {
    const existing = this.ephemeralContextId();
    // Flatten SessionDoc[] → string[] (filenames) for the Context's
    // ``data_refs`` audit trail. Filenames are good enough for traceability;
    // the backend already links chunks back to document_ids via metadata.
    const allFilenames = this.sessionDocs().map((d) => d.filename);
    if (existing) {
      this.canonical
        .updateContext(existing, {
          data_refs: allFilenames,
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
