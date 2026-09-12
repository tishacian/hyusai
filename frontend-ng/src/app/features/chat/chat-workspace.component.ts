import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ToastrService } from 'ngx-toastr';
import { Subscription } from 'rxjs';
import { CanonicalApiService, type Context, type System } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { TagComponent } from '@app/shared/cockpit';
import { ChatPanelComponent, type ChatViewMode } from './chat-panel.component';
import { ThinkingOrbComponent } from '@app/shared/cockpit';
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

function isSentinelShowcaseProfile(profile: Record<string, unknown> | null): boolean {
  if (!profile) return false;
  return profile['key'] === 'vigie_executive'
    || profile['showcase_mode'] === 'sentinel_ci'
    || profile['design_mode'] === 'sentinel_ci'
    || profile['tone'] === 'ministerial';
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
 *  - Routes `/chat` and `/workspace/:slug/chat` — full-screen/focus
 *    containers for workspace Q&A and drop-and-ask sessions.
 *
 * The [inline] input switches between compact overlay layout (stacked,
 * dropzone collapsible) and the full-screen two-column layout.
 */
@Component({
  selector: 'app-chat-workspace',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent, TagComponent, ChatPanelComponent, ThinkingOrbComponent],
  template: `
    <div class="t-shell" [class.t-inline]="inline()" [class.t-executive-shell]="executiveAssistant()">
      <!-- Header — system picker + mode badge -->
      <header class="t-header">
        @if (businessSurface()) {
          <div class="t-header-left">
            <ck-tag tone="pos" variant="solid">{{ i18n.t('chat.workspace.mode.search') }}</ck-tag>
            <span class="t-header-hint">{{ i18n.t('chat.context.workspace_search_hint') }}</span>
          </div>
          <div class="t-header-right">
            <span class="t-source-pill">{{ i18n.t('chat.context.workspace_sources_pill') }}</span>
          </div>
        } @else if (executiveAssistant()) {
          <div class="t-header-left">
            <span class="t-executive-mark">{{ assistantInitials() }}</span>
            <div class="t-executive-copy">
              <span class="t-executive-title">{{ assistantLabel() }}</span>
              <span class="t-header-hint">{{ assistantSubtitle() }}</span>
            </div>
          </div>
          <div class="t-header-right">
            <span class="t-source-pill">{{ assistantScopeLabel() }}</span>
            @if (flowBuilderSystemId()) {
              <button
                type="button"
                class="t-flow-link"
                (click)="openFlowBuilder()"
                [title]="i18n.t('chat.workspace.open_flow_builder')"
              >
                <app-icon name="workflow" [size]="13" />
                Flow
              </button>
            }
          </div>
        } @else {
          <div class="t-header-left">
            <!-- The mode badge names an internal distinction (quick / system /
                 drop) that Quick Ask does not ask the user to hold. The hint
                 alone carries the useful half. -->
            @if (!simpleMode()) {
              <ck-tag [tone]="modeTone()" variant="solid">{{ modeLabel() }}</ck-tag>
            }
            <span class="t-header-hint">{{ modeHint() }}</span>
          </div>
          <div class="t-header-right">
            <div class="t-system-control">
              <span class="t-picker-label">
                {{ i18n.t('chat.workspace.context_label') }}
                <span
                  class="t-info-dot"
                  [title]="i18n.t('chat.workspace.context_hint')"
                >
                  <app-icon name="info" [size]="10" />
                </span>
              </span>
              <div class="t-picker-wrap">
                <select
                  class="t-picker"
                  [ngModel]="selectedSystemId()"
                  (ngModelChange)="onSystemChange($event)"
                >
                  <option [ngValue]="null">{{ i18n.t('chat.workspace.mode.quick_ask') }}</option>
                  @for (s of systems(); track s.id) {
                    <option [ngValue]="s.id">{{ s.name }}</option>
                  }
                </select>
                <app-icon name="chevron-down" [size]="12" class="t-picker-chevron" />
              </div>
            </div>
            @if (flowBuilderSystemId()) {
              <button
                type="button"
                class="t-flow-link"
                (click)="openFlowBuilder()"
                [title]="i18n.t('chat.workspace.open_flow_builder')"
              >
                <app-icon name="workflow" [size]="13" />
                Flow
              </button>
            }
          </div>
        }
      </header>

      <!-- Body: two-column (side panel in inline mode, full split in full-screen) -->
      <div class="t-body">
        <!-- Drop-and-ask sidebar -->
        @if (chatUploadEnabled() && (!executiveAssistant() || startMode() === 'drop' || sessionDocs().length > 0)) {
        <aside class="t-sidebar" [class.t-sidebar-collapsed]="!dropOpen() && inline()">
          <div class="t-sidebar-head">
            <span class="ck-mono t-sidebar-eyebrow">
              {{ i18n.t('chat.workspace.session_docs') }}
              <span
                class="t-info-dot"
                [title]="i18n.t('chat.workspace.session_docs_hint')"
              >
                <app-icon name="info" [size]="10" />
              </span>
            </span>
            @if (inline()) {
              <button
                type="button"
                class="t-mini-btn"
                (click)="dropOpen.set(!dropOpen())"
                [title]="dropOpen() ? i18n.t('chat.workspace.dropzone_collapse') : i18n.t('chat.workspace.dropzone_expand')"
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
                accept=".pdf,.txt,.md,.docx,.csv,.json,.xlsx,.xlsm,.xltx,.xltm,.png,.jpg,.jpeg,.tif,.tiff,.webp"
              />
              <div class="t-drop-icon">
                <app-icon name="cloud-upload" [size]="18" />
              </div>
              <div class="t-drop-text">
                {{ i18n.t('chat.workspace.drop_files') }} <span class="t-drop-accent">{{ i18n.t('chat.workspace.or_click') }}</span>
              </div>
              <div class="t-drop-hint">PDF · DOCX · XLSX · CSV · TXT · MD · JSON</div>
              @if (uploading()) {
                <div class="t-drop-progress">
                  <ck-thinking-orb state="shaping" [size]="20" [label]="i18n.t('chat.workspace.indexing')" />
                  {{ i18n.t('chat.workspace.indexing_count', { count: uploadingCount() }) }}
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
                    {{ i18n.t(sessionDocs().length === 1 ? 'chat.workspace.files_one' : 'chat.workspace.files_many', { count: sessionDocs().length }) }}
                  </span>
                  @if (ephemeralContextId()) {
                    <button
                      type="button"
                      class="t-persist-btn"
                      (click)="persistContext()"
                      [disabled]="persisting()"
                      [title]="i18n.t('chat.persist.hint')"
                    >
                      <app-icon [name]="persisting() ? 'loader-2' : 'save'" [size]="11" [class.animate-spin]="persisting()" />
                      {{ i18n.t('chat.persist') }}
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
                        <button
                          type="button"
                          class="t-doc-remove"
                          (click)="detachSessionDoc(d)"
                          [disabled]="detachingDocKey() === docKey(d)"
                          [title]="i18n.t('chat.workspace.remove_doc', { name: displayTitle(d) })"
                          [attr.aria-label]="i18n.t('chat.workspace.remove_doc', { name: displayTitle(d) })"
                        >
                          <app-icon [name]="detachingDocKey() === docKey(d) ? 'loader-2' : 'x'" [size]="10" [class.animate-spin]="detachingDocKey() === docKey(d)" />
                        </button>
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
                                {{ i18n.t(p === 1 ? 'chat.workspace.pages_one' : 'chat.workspace.pages_many', { count: p }) }}
                              </span>
                            }
                            @if (d.meta.document_token_count !== undefined) {
                              <span class="t-doc-stat">
                                {{ i18n.t('chat.workspace.tokens', { count: formatTokens(d.meta.document_token_count) }) }}
                              </span>
                            }
                            @if (d.meta.chunks_count !== undefined && d.meta.chunks_count !== null) {
                              <span class="t-doc-stat">
                                {{ i18n.t('chat.workspace.chunks', { count: d.meta.chunks_count }) }}
                              </span>
                            }
                          </div>
                          @if (d.meta.document_author) {
                            <div class="t-doc-author">{{ i18n.t('chat.workspace.by_author', { name: d.meta.document_author }) }}</div>
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
                {{ i18n.t('chat.workspace.no_docs') }}
              </div>
            }
          }
        </aside>
        }

        <!-- Chat panel -->
        <section class="t-chat">
          <app-chat-panel
            [systemId]="effectiveSystemId()"
            [contextId]="ephemeralContextId()"
            [assistantProfileKey]="assistantProfileKey()"
            [initialPrompt]="initialPrompt()"
            [autoStartVoiceLoop]="autoStartVoiceLoop()"
            [viewMode]="effectiveViewMode()"
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
    .t-executive-mark {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: 10px;
      border: 1px solid rgba(242, 140, 56, 0.32);
      background:
        radial-gradient(circle at 35% 25%, rgba(242, 140, 56, 0.25), transparent 45%),
        var(--ck-bg-panel);
      color: var(--ck-signal-warn);
      font: 800 10px/1 var(--ck-font-mono, ui-monospace, monospace);
      font-weight: 800;
      letter-spacing: 0.05em;
      box-shadow: var(--ck-shadow-card);
    }
    .t-executive-copy {
      display: flex;
      flex-direction: column;
      gap: 1px;
      min-width: 0;
    }
    .t-executive-title {
      color: var(--ck-fg-1);
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.08em;
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
    .t-system-control {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 4px 7px 4px 9px;
      min-height: 34px;
      border-radius: 12px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-tint-faint);
      box-shadow: inset 0 1px 0 var(--ck-stroke-1);
    }
    .t-picker-label {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-family: var(--ck-font-mono);
      font-size: 9px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ck-fg-4);
    }
    .t-info-dot {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      border-radius: 999px;
      color: var(--ck-fg-3);
      background: var(--ck-tint-soft);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-2);
      cursor: help;
    }
    .t-info-dot:hover {
      color: var(--ck-signal-cool);
      background: var(--ck-tint-soft);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-hot);
    }
    .t-picker-wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
      min-width: 260px;
      max-width: 360px;
    }
    .t-picker {
      width: 100%;
      -webkit-appearance: none;
      appearance: none;
      background: var(--ck-bg-inset);
      border: 0;
      border-radius: 8px;
      color: var(--ck-fg-1);
      color-scheme: dark;
      font-size: 12px;
      font-weight: 650;
      padding: 6px 26px 6px 10px;
      outline: 0;
    }
    :host-context([data-theme="light"]) .t-picker {
      color-scheme: light;
    }
    .t-picker:focus {
      box-shadow: 0 0 0 1px var(--ck-stroke-hot);
      background: var(--ck-bg-panel);
    }
    .t-picker-chevron {
      position: absolute;
      right: 8px;
      color: var(--ck-fg-3);
      pointer-events: none;
    }
    .t-source-pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid var(--ck-stroke-hot);
      background: var(--ck-tint-soft);
      color: var(--ck-signal-cool);
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
    }
    .t-flow-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 0 9px;
      border-radius: 8px;
      border: 1px solid var(--ck-stroke-hot);
      background: var(--ck-tint-faint);
      color: var(--ck-signal-cool);
      font-size: 11px;
      font-weight: 750;
      white-space: nowrap;
      transition: 140ms ease;
    }
    .t-flow-link:hover {
      border-color: var(--ck-stroke-hot);
      background: var(--ck-tint-soft);
      color: var(--ck-fg-1);
    }
    .t-executive-shell .t-source-pill {
      border-color: rgba(101, 214, 110, 0.30);
      background:
        linear-gradient(135deg, rgba(101, 214, 110, 0.11), rgba(242, 140, 56, 0.06)),
        var(--ck-bg-panel);
      color: var(--ck-signal-pos);
      box-shadow: var(--ck-shadow-card);
    }
    .t-inline .t-source-pill {
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
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
      background: var(--ck-tint-faint);
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
      background: var(--ck-tint-faint);
    }
    .t-dropzone-hot {
      border-color: var(--ck-signal-cool) !important;
      background: var(--ck-tint-soft) !important;
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
      background: var(--ck-tint-faint);
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
      background: var(--ck-tint-soft);
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
      background: var(--ck-tint-faint);
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
    .t-doc-remove {
      width: 20px;
      height: 20px;
      flex: 0 0 20px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid transparent;
      border-radius: 4px;
      color: var(--ck-fg-4);
      background: transparent;
      cursor: pointer;
    }
    .t-doc-remove:hover:not([disabled]) {
      color: var(--ck-fg-1);
      background: var(--ck-tint-faint);
      border-color: var(--ck-stroke-2);
    }
    .t-doc-remove[disabled] {
      opacity: 0.55;
      cursor: wait;
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
      background: var(--ck-tint-soft);
      color: var(--ck-signal-cool);
      border: 1px solid var(--ck-stroke-hot);
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
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  private readonly canonical = inject(CanonicalApiService);
  readonly i18n = inject(I18nService);
  private readonly http = inject(HttpClient);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute, { optional: true });
  private readonly navigation = inject(ZoomContextService);
  private readonly destroyRef = inject(DestroyRef);
  private workspaceGeneration = 0;
  private workspaceSubscriptions = new Subscription();
  private readonly routeSubscriptions = new Subscription();
  private destroyed = false;

  /** When `true`, render the compact (overlay) layout. Full-screen otherwise. */
  readonly inline = input<boolean>(false);
  /** Optional hint about which start mode to pre-select. */
  readonly startMode = input<ChatStartMode>('quick');
  /** Optional System id pre-selected (from palette command or query param). */
  readonly initialSystemId = input<string | null>(null);
  /** Optional ephemeral Context id to reuse (e.g. URL-shared session). */
  readonly initialContextId = input<string | null>(null);
  /** Optional workspace assistant profile (AYA, support copilot, etc.). */
  readonly assistantProfileKey = input<string | null>(null);
  /** Optional prompt prefilled when the assistant opens from a workspace app. */
  readonly initialPrompt = input<string | null>(null);
  /** When true, open the chat in persistent session voice loop mode. */
  readonly autoStartVoiceLoop = input(false);
  /**
   * How much of the chat panel to render. Forwarded verbatim: this component
   * lays out the context picker and the dropzone, and takes no view on which
   * expert controls the panel shows. Containers decide (see
   * `ChatFocusComponent`), so `/chat` and the overlay keep today's behaviour.
   */
  readonly viewMode = input<ChatViewMode>('standard');
  /**
   * `/chat?mode=quick` is the canonical Ask home, so the routed surface reads
   * its own mode at the route boundary. Containers that mount this component
   * themselves (the overlay, `ChatFocusComponent`) pass `viewMode` and are
   * never affected: only a full-screen mount consults the URL.
   */
  private readonly routeQuickAsk = signal(false);
  readonly effectiveViewMode = computed<ChatViewMode>(() =>
    this.viewMode() === 'simple' || this.routeQuickAsk() ? 'simple' : 'standard',
  );
  readonly simpleMode = computed(() => this.effectiveViewMode() === 'simple');

  readonly systems = signal<System[]>([]);
  readonly selectedSystemId = signal<string | null>(null);

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
  readonly detachingDocKey = signal<string | null>(null);

  /** Collapsed state of the dropzone in inline mode (always open full-screen). */
  readonly dropOpen = signal(true);

  readonly activeAssistantProfile = computed<Record<string, unknown> | null>(() => {
    const key = this.assistantProfileKey() || this.workspace.current()?.settings?.['assistant_profile_default'];
    if (!key) return null;
    const profiles = this.workspace.current()?.settings?.['assistant_profiles'];
    if (!Array.isArray(profiles)) return null;
    return (profiles as Record<string, unknown>[]).find((profile) => profile['key'] === key) ?? null;
  });

  /**
   * Drop-and-ask upload gating. Reads the per-workspace
   * `settings.features.chat_document_upload` flag. Enabled by default
   * (opt-out): only an explicit `false` disables the chat dropzone.
   */
  readonly chatUploadEnabled = computed(() => {
    const features = this.workspace.current()?.settings?.['features'] as
      | Record<string, unknown>
      | undefined;
    return features?.['chat_document_upload'] !== false;
  });

  readonly executiveAssistant = computed(() => isSentinelShowcaseProfile(this.activeAssistantProfile()));
  readonly businessSurface = computed(() => this.navigationProfile.businessShellActive());
  readonly assistantLabel = computed(() => String(this.activeAssistantProfile()?.['label'] || this.brand()));
  readonly assistantInitials = computed(() => this.assistantLabel().slice(0, 3).toUpperCase());

  readonly assistantSubtitle = computed(() => {
    const profile = this.activeAssistantProfile();
    return String(profile?.['subtitle'] || this.i18n.t('chat.context.workspace_sources_pill'));
  });

  readonly assistantScopeLabel = computed(() => {
    const profile = this.activeAssistantProfile();
    const scopeKey = String(profile?.['default_knowledge_scope'] || '');
    const scopes = this.workspace.current()?.settings?.['knowledge_scopes'];
    if (Array.isArray(scopes)) {
      const scope = (scopes as Record<string, unknown>[]).find((item) => item['key'] === scopeKey);
      if (scope?.['label']) return this.i18n.t('chat.context.sources_scope', { label: String(scope['label']) });
    }
    return this.i18n.t('chat.context.workspace_sources_pill');
  });

  readonly workspaceChatSystem = computed<System | null>(() => {
    return this.systems().find((system) => this.isWorkspaceChatSystem(system)) ?? null;
  });

  readonly selectedSystem = computed<System | null>(() => {
    const selected = this.selectedSystemId();
    if (!selected) return null;
    return this.systems().find((system) => system.id === selected) ?? null;
  });

  readonly effectiveSystemId = computed<string | null>(() => {
    if (this.businessSurface()) return this.workspaceChatSystem()?.id ?? null;
    return this.selectedSystem()?.id ?? this.workspaceChatSystem()?.id ?? null;
  });

  readonly flowBuilderSystemId = computed<string | null>(() =>
    this.businessSurface() ? null : this.effectiveSystemId(),
  );

  readonly modeLabel = computed<string>(() => {
    if (this.businessSurface()) return this.i18n.t('chat.workspace.mode.search');
    if (this.ephemeralContextId()) return this.i18n.t('chat.workspace.mode.drop_ask');
    if (this.selectedSystem()) return this.i18n.t('chat.workspace.mode.system');
    return this.i18n.t('chat.workspace.mode.quick_ask');
  });

  readonly modeTone = computed<'cool' | 'violet' | 'pos'>(() => {
    if (this.businessSurface()) return 'pos';
    if (this.ephemeralContextId()) return 'violet';
    if (this.selectedSystem()) return 'cool';
    return 'pos';
  });

  readonly modeHint = computed<string>(() => {
    if (this.businessSurface()) return this.i18n.t('chat.context.workspace_sources');
    if (this.ephemeralContextId()) return this.i18n.t('chat.workspace.hint.session_docs');
    const selected = this.selectedSystem();
    if (selected) {
      return selected.objective || this.i18n.t('chat.workspace.hint.scoped');
    }
    const chatSystem = this.workspaceChatSystem();
    if (chatSystem) return chatSystem.objective || this.i18n.t('chat.workspace.hint.fast');
    return this.i18n.t('chat.context.workspace');
  });

  constructor() {
    const unregisterWorkspaceReset = this.workspace.registerContextReset((transition) => {
      this.resetForWorkspaceChange(transition);
    });
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      unregisterWorkspaceReset();
      this.routeSubscriptions.unsubscribe();
      this.cancelWorkspaceRequests();
    });
  }

  ngOnInit(): void {
    if (!this.inline() && this.route) {
      this.routeSubscriptions.add(
        this.route.queryParamMap.subscribe((params) => {
          this.routeQuickAsk.set(params.get('mode') === 'quick');
        }),
      );
    }
    this.selectedSystemId.set(this.businessSurface() ? null : this.initialSystemId() ?? null);
    this.ephemeralContextId.set(this.initialContextId() ?? null);
    // Inline overlay: keep dropzone collapsed unless drop-mode was asked.
    // When chat upload is disabled, never force-open the dropzone even if
    // drop-mode was requested (the sidebar is hidden anyway).
    if (this.inline() && (this.startMode() !== 'drop' || !this.chatUploadEnabled())) {
      this.dropOpen.set(false);
    }
    this.loadSystems();
  }

  private loadSystems(): void {
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceGeneration;
    const subscription = this.canonical.listSystems({ workspaceSlug: scope.workspaceSlug }).subscribe({
      next: (list) => {
        if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
        const systems = list || [];
        this.systems.set(systems);
        if (this.selectedSystemId() && !systems.some((system) => system.id === this.selectedSystemId())) {
          this.selectedSystemId.set(null);
        }
      },
      error: () => {
        if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
        this.systems.set([]);
        this.selectedSystemId.set(null);
      },
    });
    this.workspaceSubscriptions.add(subscription);
  }

  onSystemChange(id: string | null): void {
    if (this.businessSurface()) return;
    this.selectedSystemId.set(id && this.systems().some((system) => system.id === id) ? id : null);
  }

  openFlowBuilder(): void {
    const systemId = this.flowBuilderSystemId();
    if (!systemId) return;
    void this.router.navigateByUrl(this.navigation.leafUrl('system-flow', { ref: systemId }));
  }

  private isWorkspaceChatSystem(system: System): boolean {
    const flow = (system.flow_definition ?? {}) as Record<string, unknown>;
    const settings = (system.settings ?? {}) as Record<string, unknown>;
    return flow['variant'] === 'chat_transverse_v1' || settings['system_type'] === 'workspace_chat';
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
    if (!this.chatUploadEnabled()) return;
    const files = e.dataTransfer?.files;
    if (files && files.length) this.uploadFiles(files);
  }
  onFileSelect(e: Event): void {
    if (!this.chatUploadEnabled()) return;
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
    if (!this.chatUploadEnabled()) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceGeneration;
    this.uploading.set(true);
    this.uploadingCount.set(files.length);
    const formData = new FormData();
    Array.from(files).forEach((f) => formData.append('files', f));
    formData.append('collection_name', 'documents');
    // Tags this batch as a chat drop-and-ask upload so the backend can
    // enforce the `chat_document_upload` flag (the KB upload omits this).
    formData.append('source', 'chat_drop_and_ask');

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

    const subscription = this.http
      .post<UploadResponse>('/api/v1/documents/upload-batch', formData, {
        headers: this.workspaceHeaders(scope),
      })
      .subscribe({
        next: (res) => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
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
              this.fetchDocMetadata(doc.id, scope, generation);
            });
          }
          const added = (res.documents ?? [])
            .filter((d) => d.status === 'success')
            .map((d) => d.filename ?? '');
          this.ensureEphemeralContext(
            added.filter((n): n is string => !!n),
            scope,
            generation,
          );
          if (res.failed > 0) {
            this.toast.warning(
              this.i18n.t('chat.workspace.toast.partial', {
                ok: res.successful,
                total: res.total,
                failed: res.failed,
              }),
              this.i18n.t('chat.workspace.mode.drop_ask'),
            );
          } else {
            this.toast.success(
              this.i18n.t(
                res.successful === 1
                  ? 'chat.workspace.toast.indexed_one'
                  : 'chat.workspace.toast.indexed_many',
                { count: res.successful },
              ),
              this.i18n.t('chat.workspace.mode.drop_ask'),
            );
          }
        },
        error: (err) => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
          this.uploading.set(false);
          this.toast.error(
            err?.error?.detail || this.i18n.t('chat.workspace.toast.upload_failed'),
            this.i18n.t('chat.workspace.mode.drop_ask'),
          );
        },
      });
    this.workspaceSubscriptions.add(subscription);
  }

  /**
   * Fetch docmeta for a single document and patch the corresponding
   * ``SessionDoc`` entry in place. Runs out-of-band from the upload flow
   * so a slow metadata endpoint never blocks the "file indexed" toast.
   */
  private fetchDocMetadata(
    documentId: string,
    scope: WorkspaceRequestScope,
    generation: number,
  ): void {
    if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
    const subscription = this.http
      .get<{ document_id: string; metadata: DocFacts }>(
        `/api/v1/documents/${documentId}/metadata`,
        { headers: this.workspaceHeaders(scope) },
      )
      .subscribe({
        next: (res) => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
          this.sessionDocs.update((prev) =>
            prev.map((d) =>
              d.id === documentId
                ? { ...d, meta: res.metadata ?? null, metaLoading: false }
                : d,
            ),
          );
        },
        error: () => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
          this.sessionDocs.update((prev) =>
            prev.map((d) =>
              d.id === documentId
                ? { ...d, meta: null, metaLoading: false }
                : d,
            ),
          );
        },
      });
    this.workspaceSubscriptions.add(subscription);
  }

  /** Compact display title for a session doc (docmeta title > filename). */
  displayTitle(doc: SessionDoc): string {
    return (
      doc.meta?.document_title?.trim() ||
      doc.meta?.document_filename?.trim() ||
      doc.filename
    );
  }

  /** Stable key used by the template and detach flow. */
  docKey(doc: SessionDoc): string {
    return doc.id || doc.filename;
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

  private ensureEphemeralContext(
    newDocs: string[],
    scope: WorkspaceRequestScope,
    generation: number,
  ): void {
    if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
    const existing = this.ephemeralContextId();
    // Flatten SessionDoc[] → string[] (filenames) for the Context's
    // ``data_refs`` audit trail. Filenames are good enough for traceability;
    // the backend already links chunks back to document_ids via metadata.
    const allFilenames = this.sessionDocs().map((d) => d.filename);
    if (existing) {
      const subscription = this.canonical
        .updateContext(existing, {
          data_refs: allFilenames,
          environment_state: { collection: 'documents' },
          business_constraints: { source: 'drop_and_ask' },
        }, { workspaceSlug: scope.workspaceSlug })
        .subscribe({
          next: (ctx) => {
            if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
            if (ctx) return;
            this.removeSessionDocsByFilename(newDocs);
            this.toast.error(
              this.i18n.t('chat.workspace.toast.attach_failed'),
              this.i18n.t('chat.workspace.mode.drop_ask'),
            );
          },
        });
      this.workspaceSubscriptions.add(subscription);
      return;
    }
    const subscription = this.canonical
      .createContext({
        name: `Drop-and-ask · ${new Date().toLocaleString()}`,
        data_refs: newDocs,
        environment_state: { collection: 'documents' },
        business_constraints: { source: 'drop_and_ask' },
        ephemeral: true,
        ttl_hours: 24,
      }, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (ctx) => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
          if (ctx) {
            this.ephemeralContextId.set(ctx.id);
            return;
          }
          this.removeSessionDocsByFilename(newDocs);
          this.toast.error(
            this.i18n.t('chat.workspace.toast.context_failed'),
            this.i18n.t('chat.workspace.mode.drop_ask'),
          );
        },
      });
    this.workspaceSubscriptions.add(subscription);
  }

  private removeSessionDocsByFilename(filenames: string[]): void {
    const names = new Set(filenames.filter(Boolean));
    if (names.size === 0) return;
    this.sessionDocs.update((prev) => prev.filter((doc) => !names.has(doc.filename)));
  }

  detachSessionDoc(doc: SessionDoc): void {
    const key = this.docKey(doc);
    if (!key || this.detachingDocKey()) return;
    const previousDocs = this.sessionDocs();
    const nextDocs = previousDocs.filter((d) => this.docKey(d) !== key);
    if (nextDocs.length === previousDocs.length) return;

    const contextId = this.ephemeralContextId();
    if (!contextId) {
      this.sessionDocs.set(nextDocs);
      return;
    }

    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceGeneration;
    this.detachingDocKey.set(key);
    const subscription = this.canonical
      .updateContext(contextId, {
        data_refs: nextDocs.map((d) => d.filename),
        environment_state: { collection: 'documents' },
        business_constraints: { source: 'drop_and_ask' },
      }, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (ctx) => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
          if (!ctx) {
            this.detachingDocKey.set(null);
            this.toast.error(
              this.i18n.t('chat.workspace.toast.remove_failed'),
              this.i18n.t('chat.workspace.mode.drop_ask'),
            );
            return;
          }
          this.sessionDocs.set(nextDocs);
          if (nextDocs.length === 0) this.ephemeralContextId.set(null);
          this.detachingDocKey.set(null);
        },
        error: () => {
          if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
          this.detachingDocKey.set(null);
          this.toast.error(
            this.i18n.t('chat.workspace.toast.remove_failed'),
            this.i18n.t('chat.workspace.mode.drop_ask'),
          );
        },
      });
    this.workspaceSubscriptions.add(subscription);
  }

  persistContext(): void {
    const id = this.ephemeralContextId();
    if (!id || this.persisting()) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceGeneration;
    this.persisting.set(true);
    const subscription = this.canonical.persistContext(id, { workspaceSlug: scope.workspaceSlug }).subscribe({
      next: (ctx) => {
        if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
        this.persisting.set(false);
        if (ctx) {
          this.toast.success(
            this.i18n.t('chat.workspace.toast.persisted', { name: ctx.name }),
            this.i18n.t('chat.workspace.toast.persisted_title'),
          );
        } else {
          this.toast.error(
            this.i18n.t('chat.workspace.toast.persist_failed'),
            this.i18n.t('chat.workspace.mode.drop_ask'),
          );
        }
      },
      error: () => {
        if (!this.isWorkspaceContinuationCurrent(scope, generation)) return;
        this.persisting.set(false);
        this.toast.error(
          this.i18n.t('chat.workspace.toast.persist_failed'),
          this.i18n.t('chat.workspace.mode.drop_ask'),
        );
      },
    });
    this.workspaceSubscriptions.add(subscription);
  }

  /**
   * Runs synchronously while the old tenant is still the active scope. Abort
   * every continuation before WorkspaceService publishes the next tenant, then
   * clear all drop-and-ask state so no A document can be attributed to B.
   */
  private resetForWorkspaceChange(transition: WorkspaceContextTransition): void {
    this.workspaceGeneration += 1;
    this.cancelWorkspaceRequests();
    this.systems.set([]);
    this.selectedSystemId.set(null);
    this.ephemeralContextId.set(null);
    this.sessionDocs.set([]);
    this.dragging.set(false);
    this.uploading.set(false);
    this.uploadingCount.set(0);
    this.persisting.set(false);
    this.detachingDocKey.set(null);

    // The reset callback precedes publication of B. Reload only after the
    // atomic transition is visible, and only if this component survived it.
    queueMicrotask(() => {
      if (this.destroyed) return;
      if (this.workspace.currentSlug() !== transition.nextSlug) return;
      if (this.workspace.contextEpoch() !== transition.nextEpoch) return;
      this.loadSystems();
    });
  }

  private cancelWorkspaceRequests(): void {
    this.workspaceSubscriptions.unsubscribe();
    this.workspaceSubscriptions = new Subscription();
  }

  private isWorkspaceContinuationCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
  ): boolean {
    return !this.destroyed
      && generation === this.workspaceGeneration
      && this.workspace.isRequestScopeCurrent(scope);
  }

  private workspaceHeaders(scope: WorkspaceRequestScope): Record<string, string> | undefined {
    return scope.workspaceSlug ? { 'X-Workspace-Slug': scope.workspaceSlug } : undefined;
  }
}
