import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, NgClass, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';

/**
 * Read-only admin view of a workspace member's chat session. Dedicated to the
 * governance "Chat history" screen so the user's own chat sidebar interface
 * (``ChatSessionSummary`` in chat-panel) stays untouched. Carries the session
 * author (``user_id`` + ``author_label``) which the admin list needs.
 */
export interface AdminSessionSummary {
  id: string;
  user_id?: string | null;
  author_label?: string | null;
  author_email?: string | null;
  title?: string | null;
  status?: 'active' | 'archived' | 'deleted' | string;
  created_at?: string | null;
  last_activity?: string | null;
  message_count?: number;
  meta_data?: Record<string, unknown> | null;
}

interface AdminSessionMessage {
  id?: string;
  role: 'user' | 'assistant' | string;
  content: string;
  timestamp?: string | null;
  meta_data?: Record<string, unknown> | null;
}

interface AdminSessionDetail extends AdminSessionSummary {
  messages?: AdminSessionMessage[];
}

interface AdminSessionListResponse {
  sessions?: AdminSessionSummary[];
  total?: number;
}

/**
 * Expert-capture session as returned by ``GET /knowledge-capture/sessions``.
 * Admins/reviewers receive every member's session (contributors are scoped to
 * their own). Folded into the same admin table as RAG chat sessions so a single
 * governance view exposes both conversation kinds.
 */
interface CaptureSessionSummary {
  id: string;
  created_by_user_id?: string | null;
  created_by_label?: string | null;
  title?: string | null;
  objective?: string | null;
  status?: string | null;
  system_id?: string | null;
  context_id?: string | null;
  turn_count?: number;
  archived?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  last_activity?: string | null;
  transcript?: CaptureTurnRaw[];
  metrics?: Record<string, unknown> | null;
}

interface CaptureTurnRaw {
  id?: string;
  speaker?: string | null;
  text?: string | null;
  text_raw?: string | null;
  text_amended?: string | null;
  question_id?: string | null;
  turn_kind?: string | null;
  created_at?: string | null;
}

interface CaptureSessionDetail extends CaptureSessionSummary {
  captured_facts?: Array<Record<string, unknown>>;
}

interface CaptureSessionListResponse {
  sessions?: CaptureSessionSummary[];
}

interface CaptureEvent {
  id: string;
  event_type: string;
  speaker?: string | null;
  sequence?: number;
  text?: string | null;
  text_raw?: string | null;
  text_amended?: string | null;
  status?: string | null;
  source?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown> | null;
}

interface CaptureEventListResponse {
  events?: CaptureEvent[];
}

interface CaptureProposal {
  id: string;
  status?: string | null;
  proposal?: Record<string, unknown> | null;
  review_notes?: string | null;
  reviewer?: string | null;
  created_at?: string | null;
  reviewed_at?: string | null;
}

interface CaptureProposalListResponse {
  proposals?: CaptureProposal[];
}

interface MemberOption {
  user_id: string;
  label: string;
}

type StatusFilter = 'active' | 'archived' | 'all';

/** What kind of session a unified row represents. */
type SessionKind = 'chat' | 'capture' | 'correction';

/**
 * One row in the unified admin table. Common columns (author/date/status/count)
 * are flattened so chat and expert-capture sessions render side by side; the
 * original payload is kept on ``chat`` / ``capture`` for the detail drawer.
 */
interface UnifiedRow {
  id: string;
  kind: SessionKind;
  userId: string | null;
  authorLabel: string;
  authorEmail: string | null;
  title: string;
  status: string;
  createdAt: string | null;
  lastActivity: string | null;
  count: number;
  context: string;
  chat?: AdminSessionSummary;
  capture?: CaptureSessionSummary;
}

/** A read-only capture conversation entry (transcript turn or business event). */
interface CaptureEntry {
  speaker: string;
  label: string;
  text: string;
  rawText: string | null;
  timestamp: string | null;
}

/** Inline markdown token for the read-only transcript renderer. */
interface InlineToken {
  kind: 'text' | 'strong' | 'em' | 'code';
  value: string;
}

/** Block-level markdown node — mirrors the chat-panel answer renderer
 *  (paragraph / heading / list / code) but flattened for a read-only view. */
type TranscriptBlock =
  | { kind: 'paragraph'; tokens: InlineToken[] }
  | { kind: 'heading'; level: 2 | 3 | 4; tokens: InlineToken[] }
  | { kind: 'list'; ordered: boolean; items: InlineToken[][] }
  | { kind: 'code'; value: string };

/** A turn ready to render: assistant content is pre-parsed into blocks so the
 *  OnPush template never re-parses markdown during change detection. */
interface TranscriptTurn {
  role: 'user' | 'assistant' | string;
  content: string;
  timestamp?: string | null;
  blocks: TranscriptBlock[];
}

/** Capture business-event types worth surfacing when a session has no recorded
 *  transcript (notably voice chat-corrections, which store the raw dictation and
 *  the expert-edited text on a single event). */
const MEANINGFUL_CAPTURE_EVENTS = new Set([
  'chat_correction_voice',
  'expert_turn_finalized',
  'transcript_turn_recorded',
]);

@Component({
  selector: 'app-chat-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    DatePipe,
    NgClass,
    NgTemplateOutlet,
    IconComponent,
    SectionHeaderComponent,
    EmptyStateComponent,
    SkeletonComponent,
    DrawerComponent,
  ],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('governance.breadcrumb')"
      [title]="i18n.t('governance.chat.title')"
      icon="message-square"
      [subtitle]="i18n.t('governance.chat.subtitle')"
    >
      <button
        type="button"
        (click)="reload()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('common.refresh') }}
      </button>
    </app-section-header>

    <div class="flex flex-wrap items-center gap-3 mb-4">
      <select
        [ngModel]="memberFilter()"
        (ngModelChange)="setMember($event)"
        class="ch-select"
        [title]="i18n.t('governance.chat.filter.member')"
      >
        <option value="">{{ i18n.t('governance.chat.filter.member.all') }}</option>
        @for (m of members(); track m.user_id) {
          <option [value]="m.user_id">{{ m.label }}</option>
        }
      </select>

      <div class="flex items-center gap-1 p-1 rounded bg-black/20 border border-white/5">
        @for (f of kindFilters; track f.key) {
          <button
            type="button"
            (click)="setKind(f.key)"
            class="px-2.5 py-1 text-xs rounded transition"
            [class.bg-cyan-500\\/20]="kindFilter() === f.key"
            [class.text-cyan-300]="kindFilter() === f.key"
            [class.text-gray-400]="kindFilter() !== f.key"
            [class.hover:text-gray-200]="kindFilter() !== f.key"
          >
            {{ i18n.t(f.labelKey) }}
          </button>
        }
      </div>

      <div class="flex items-center gap-1 p-1 rounded bg-black/20 border border-white/5">
        @for (f of statusFilters; track f.key) {
          <button
            type="button"
            (click)="setStatus(f.key)"
            class="px-2.5 py-1 text-xs rounded transition"
            [class.bg-cyan-500\\/20]="status() === f.key"
            [class.text-cyan-300]="status() === f.key"
            [class.text-gray-400]="status() !== f.key"
            [class.hover:text-gray-200]="status() !== f.key"
          >
            {{ i18n.t(f.labelKey) }}
          </button>
        }
      </div>

      <span class="text-[11px] text-gray-500 font-mono ml-auto">
        {{ rows().length === 1 ? i18n.t('governance.chat.count.one') : i18n.t('governance.chat.count.many', { count: rows().length }) }}
      </span>
    </div>

    @if (error(); as message) {
      <div class="mb-4 rounded-md p-3 bg-red-500/10 ring-1 ring-red-400/25 text-sm text-red-100">
        {{ message }}
      </div>
    }

    <section class="ck-surface rounded-md overflow-hidden">
      @if (loading()) {
        <div class="p-6 space-y-3">
          @for (_ of skeletonRows; track $index) {
            <app-skeleton variant="line" height="44px" />
          }
        </div>
      } @else if (rows().length === 0) {
        <app-empty-state
          icon="message-square"
          [title]="i18n.t('governance.chat.empty.title')"
          [description]="i18n.t('governance.chat.empty.description')"
        />
      } @else {
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-white/5">
                <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.chat.column.author') }}</th>
                <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.chat.column.type') }}</th>
                <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.chat.column.title') }}</th>
                <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.chat.column.last_activity') }}</th>
                <th class="px-5 py-3 font-semibold text-center">{{ i18n.t('governance.chat.column.count') }}</th>
                <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.chat.column.context') }}</th>
                <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.chat.column.status') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              @for (row of rows(); track row.kind + ':' + row.id) {
                <tr
                  class="hover:bg-white/[0.02] transition cursor-pointer"
                  (click)="openDetail(row)"
                >
                  <td class="px-5 py-3">
                    <div class="flex items-center gap-2 min-w-0">
                      <span class="h-7 w-7 shrink-0 rounded-full bg-white/[0.04] ring-1 ring-cyan-400/30 flex items-center justify-center text-[11px] font-semibold text-cyan-200">
                        {{ authorInitial(row) }}
                      </span>
                      <div class="min-w-0">
                        <div class="truncate text-white font-medium">{{ row.authorLabel }}</div>
                        @if (row.authorEmail && row.authorEmail !== row.authorLabel) {
                          <div class="truncate text-[11px] text-gray-500">{{ row.authorEmail }}</div>
                        }
                      </div>
                    </div>
                  </td>
                  <td class="px-5 py-3">
                    <span
                      class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full uppercase tracking-wider"
                      [ngClass]="kindClass(row.kind)"
                    >
                      <app-icon [name]="kindIcon(row.kind)" [size]="11" />
                      {{ kindLabel(row.kind) }}
                    </span>
                  </td>
                  <td class="px-5 py-3 text-gray-200 max-w-xs">
                    <span class="block truncate">{{ row.title }}</span>
                  </td>
                  <td class="px-5 py-3 text-gray-400 whitespace-nowrap">
                    {{ (row.lastActivity || row.createdAt) | date: 'MMM d, HH:mm' }}
                  </td>
                  <td class="px-5 py-3 text-gray-300 text-center font-mono">{{ row.count }}</td>
                  <td class="px-5 py-3 text-gray-400 font-mono text-xs">{{ row.context }}</td>
                  <td class="px-5 py-3">
                    <span
                      class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full uppercase tracking-wider"
                      [ngClass]="statusClass(row.status)"
                    >
                      {{ statusLabel(row.status) }}
                    </span>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        @if (hasMore()) {
          <div class="px-5 py-3 flex items-center justify-between border-t border-white/5">
            <span class="text-[11px] text-gray-500 font-mono">
              {{ i18n.t('governance.chat.showing', { count: rows().length }) }}
            </span>
            <button
              type="button"
              (click)="loadMore()"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
            >
              <app-icon name="chevron-down" [size]="12" /> {{ i18n.t('governance.load_more') }}
            </button>
          </div>
        }
      }
    </section>

    <!-- Read-only detail drawer. Chat sessions reuse the chat-panel message
         renderer; capture/correction sessions render their transcript, voice
         raw/amended text and the proposed fiche read-only. No CTA, no edit. -->
    <app-drawer
      [open]="drawerOpen()"
      [title]="drawerTitle()"
      [subtitle]="drawerSubtitle()"
      icon="message-square"
      [width]="640"
      (close)="closeDetail()"
    >
      @if (selectedRow(); as row) {
        <div class="space-y-5">
          <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">{{ i18n.t('governance.chat.column.author') }}</dt>
              <dd class="text-gray-200 mt-0.5">{{ row.authorLabel }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">{{ i18n.t('governance.chat.column.type') }}</dt>
              <dd class="text-gray-200 mt-0.5">{{ kindLabel(row.kind) }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">{{ i18n.t('governance.chat.column.status') }}</dt>
              <dd class="text-gray-200 mt-0.5">{{ statusLabel(row.status) }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">{{ i18n.t('governance.chat.column.last_activity') }}</dt>
              <dd class="text-gray-200 mt-0.5">{{ row.lastActivity | date: 'MMM d, y HH:mm' }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">{{ i18n.t('governance.chat.detail.created') }}</dt>
              <dd class="text-gray-200 mt-0.5">{{ row.createdAt | date: 'MMM d, y HH:mm' }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">{{ i18n.t('governance.chat.column.context') }}</dt>
              <dd class="text-gray-200 mt-0.5 font-mono text-[11px]">{{ row.context }}</dd>
            </div>
          </dl>

          @if (row.kind !== 'chat' && captureObjective()) {
            <div class="rounded-md bg-white/[0.03] ring-1 ring-white/5 px-3 py-2.5">
              <div class="text-[10px] uppercase tracking-wider text-gray-500 mb-1">{{ i18n.t('governance.chat.detail.objective') }}</div>
              <div class="text-sm text-gray-200 leading-relaxed">{{ captureObjective() }}</div>
            </div>
          }

          <!-- Inline markdown token renderer shared by every block. -->
          <ng-template #inline let-tokens>
            @for (tok of tokens; track $index) {
              @if (tok.kind === 'strong') {
                <strong class="font-semibold text-white">{{ tok.value }}</strong>
              } @else if (tok.kind === 'em') {
                <em class="italic">{{ tok.value }}</em>
              } @else if (tok.kind === 'code') {
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[0.92em]">{{ tok.value }}</code>
              } @else {
                {{ tok.value }}
              }
            }
          </ng-template>

          <div class="border-t border-white/10 pt-4">
            <h3 class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
              <app-icon name="message-circle" [size]="13" class="text-cyan-400" />
              {{ i18n.t('governance.chat.detail.transcript') }}
            </h3>

            @if (detailLoading()) {
              <div class="space-y-3">
                @for (_ of skeletonRows; track $index) {
                  <app-skeleton variant="line" height="56px" />
                }
              </div>
            } @else if (row.kind === 'chat') {
              @if (turns().length === 0) {
                <app-empty-state
                  icon="inbox"
                  size="sm"
                  [title]="i18n.t('governance.chat.detail.empty.title')"
                  [description]="i18n.t('governance.chat.detail.empty.description')"
                />
              } @else {
                <div class="space-y-4">
                  @for (turn of turns(); track $index) {
                    @if (turn.role === 'user') {
                      <div class="flex justify-end">
                        <div class="max-w-[85%] bg-cyan-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed shadow-sm">
                          {{ turn.content }}
                        </div>
                      </div>
                    } @else {
                      <div class="flex justify-start">
                        <div class="max-w-[85%] bg-white/[0.04] text-gray-100 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm leading-relaxed ring-1 ring-white/5">
                          @for (block of turn.blocks; track $index) {
                            @if (block.kind === 'heading') {
                              <h4 class="mt-2 first:mt-0 mb-1 text-[0.95rem] font-semibold text-white">
                                <ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: block.tokens }" />
                              </h4>
                            } @else if (block.kind === 'list') {
                              @if (block.ordered) {
                                <ol class="my-1.5 list-decimal pl-5 space-y-0.5">
                                  @for (item of block.items; track $index) {
                                    <li><ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: item }" /></li>
                                  }
                                </ol>
                              } @else {
                                <ul class="my-1.5 list-disc pl-5 space-y-0.5">
                                  @for (item of block.items; track $index) {
                                    <li><ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: item }" /></li>
                                  }
                                </ul>
                              }
                            } @else if (block.kind === 'code') {
                              <pre class="my-2 max-w-full overflow-auto rounded-md bg-white/[0.06] p-2 text-xs leading-relaxed"><code>{{ block.value }}</code></pre>
                            } @else {
                              <p class="my-1 first:mt-0 last:mb-0">
                                <ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: block.tokens }" />
                              </p>
                            }
                          }
                        </div>
                      </div>
                    }
                  }
                </div>
              }
            } @else {
              <!-- Capture / correction transcript: expert vs system turns, with
                   the raw dictation surfaced above the expert-edited text. -->
              @if (captureEntries().length === 0) {
                <app-empty-state
                  icon="inbox"
                  size="sm"
                  [title]="i18n.t('governance.chat.detail.capture_empty.title')"
                  [description]="i18n.t('governance.chat.detail.capture_empty.description')"
                />
              } @else {
                <div class="space-y-4">
                  @for (entry of captureEntries(); track $index) {
                    @if (entry.speaker === 'expert') {
                      <div class="flex justify-end">
                        <div class="max-w-[85%] bg-cyan-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed shadow-sm">
                          <div class="text-[10px] uppercase tracking-wider text-white/70 mb-1">{{ entry.label }}</div>
                          @if (entry.rawText) {
                            <div class="mb-1.5 rounded bg-black/15 px-2 py-1 text-[12px] text-white/80">
                              <span class="text-[9px] uppercase tracking-wider text-white/60 mr-1">{{ i18n.t('governance.chat.detail.raw') }}</span>
                              {{ entry.rawText }}
                            </div>
                          }
                          <div class="whitespace-pre-wrap">{{ entry.text }}</div>
                        </div>
                      </div>
                    } @else {
                      <div class="flex justify-start">
                        <div class="max-w-[85%] bg-white/[0.04] text-gray-100 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm leading-relaxed ring-1 ring-white/5">
                          <div class="text-[10px] uppercase tracking-wider text-gray-500 mb-1">{{ entry.label }}</div>
                          <div class="whitespace-pre-wrap">{{ entry.text }}</div>
                        </div>
                      </div>
                    }
                  }
                </div>
              }
            }
          </div>

          @if (row.kind !== 'chat' && !detailLoading() && captureProposalBlocks().length > 0) {
            <div class="border-t border-white/10 pt-4">
              <h3 class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
                <app-icon name="file-text" [size]="13" class="text-cyan-400" />
                {{ i18n.t('governance.chat.detail.proposal') }}
                @if (captureProposalStatus(); as st) {
                  <span class="ml-1 inline-flex items-center px-1.5 py-0.5 text-[9px] rounded-full" [ngClass]="statusClass(st)">
                    {{ statusLabel(st) }}
                  </span>
                }
              </h3>
              <div class="rounded-md bg-white/[0.03] ring-1 ring-white/5 px-4 py-3 text-sm text-gray-100 leading-relaxed">
                @for (block of captureProposalBlocks(); track $index) {
                  @if (block.kind === 'heading') {
                    <h4 class="mt-2 first:mt-0 mb-1 text-[0.95rem] font-semibold text-white">
                      <ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: block.tokens }" />
                    </h4>
                  } @else if (block.kind === 'list') {
                    @if (block.ordered) {
                      <ol class="my-1.5 list-decimal pl-5 space-y-0.5">
                        @for (item of block.items; track $index) {
                          <li><ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: item }" /></li>
                        }
                      </ol>
                    } @else {
                      <ul class="my-1.5 list-disc pl-5 space-y-0.5">
                        @for (item of block.items; track $index) {
                          <li><ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: item }" /></li>
                        }
                      </ul>
                    }
                  } @else if (block.kind === 'code') {
                    <pre class="my-2 max-w-full overflow-auto rounded-md bg-white/[0.06] p-2 text-xs leading-relaxed"><code>{{ block.value }}</code></pre>
                  } @else {
                    <p class="my-1 first:mt-0 last:mb-0">
                      <ng-container [ngTemplateOutlet]="inline" [ngTemplateOutletContext]="{ $implicit: block.tokens }" />
                    </p>
                  }
                }
              </div>
            </div>
          }
        </div>
      }
    </app-drawer>
  `,
  styles: [`
    .ch-select {
      appearance: none;
      min-height: 2rem;
      min-width: 12rem;
      border-radius: 0.375rem;
      border: 1px solid rgba(255, 255, 255, 0.1);
      background-color: rgba(2, 6, 23, 0.68);
      background-image:
        linear-gradient(45deg, transparent 50%, rgba(148, 163, 184, 0.9) 50%),
        linear-gradient(135deg, rgba(148, 163, 184, 0.9) 50%, transparent 50%);
      background-position:
        calc(100% - 14px) 50%,
        calc(100% - 9px) 50%;
      background-size: 5px 5px, 5px 5px;
      background-repeat: no-repeat;
      color: #e5e7eb;
      font-size: 0.75rem;
      line-height: 1rem;
      padding: 0.375rem 2rem 0.375rem 0.75rem;
    }
    .ch-select:focus {
      outline: none;
      border-color: rgba(103, 232, 249, 0.42);
      box-shadow: 0 0 0 1px rgba(103, 232, 249, 0.24);
    }
  `],
})
export class ChatHistoryComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly rows = signal<UnifiedRow[]>([]);
  readonly members = signal<MemberOption[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly memberFilter = signal<string>('');
  readonly status = signal<StatusFilter>('active');
  readonly kindFilter = signal<'all' | SessionKind>('all');
  private readonly pageSize = 50;
  private readonly limit = signal(this.pageSize);
  private readonly hasMoreFlag = signal(false);

  readonly selectedRow = signal<UnifiedRow | null>(null);
  readonly drawerOpen = signal(false);
  readonly detailLoading = signal(false);

  // Chat detail state.
  readonly turns = signal<TranscriptTurn[]>([]);

  // Capture detail state.
  readonly captureObjective = signal<string>('');
  readonly captureEntries = signal<CaptureEntry[]>([]);
  readonly captureProposalStatus = signal<string | null>(null);
  readonly captureProposalBlocks = signal<TranscriptBlock[]>([]);

  readonly skeletonRows = Array(6);

  readonly kindFilters: { key: 'all' | SessionKind; labelKey: string }[] = [
    { key: 'all', labelKey: 'governance.chat.filter.kind.all' },
    { key: 'chat', labelKey: 'governance.chat.filter.kind.chat' },
    { key: 'capture', labelKey: 'governance.chat.filter.kind.capture' },
    { key: 'correction', labelKey: 'governance.chat.filter.kind.correction' },
  ];

  readonly statusFilters: { key: StatusFilter; labelKey: string }[] = [
    { key: 'active', labelKey: 'governance.chat.filter.status.active' },
    { key: 'archived', labelKey: 'governance.chat.filter.status.archived' },
    { key: 'all', labelKey: 'governance.chat.filter.status.all' },
  ];

  readonly hasMore = computed(() => this.hasMoreFlag());

  readonly drawerTitle = computed(
    () => this.selectedRow()?.title || this.i18n.t('governance.chat.detail.session'),
  );

  readonly drawerSubtitle = computed(() => {
    const row = this.selectedRow();
    if (!row) return undefined;
    const unit = row.kind === 'chat' ? 'message' : 'turn';
    const countKey =
      `governance.chat.detail.count.${unit}.` + (row.count === 1 ? 'one' : 'many');
    return `${row.authorLabel} · ${this.kindLabel(row.kind)} · ${this.i18n.t(countKey, { count: row.count })}`;
  });

  ngOnInit(): void {
    this.loadMembers();
    this.reload();
  }

  private loadMembers(): void {
    this.workspace.getIamSummary().subscribe({
      next: (summary) => {
        this.members.set(
          summary.members
            .map((m) => ({ user_id: m.user_id, label: m.email || m.username }))
            .sort((a, b) => a.label.localeCompare(b.label)),
        );
      },
      error: () => this.members.set([]),
    });
  }

  reload(): void {
    this.limit.set(this.pageSize);
    this.fetchSessions();
  }

  loadMore(): void {
    this.limit.update((v) => v + this.pageSize);
    this.fetchSessions();
  }

  setStatus(status: StatusFilter): void {
    if (this.status() === status) return;
    this.status.set(status);
    this.reload();
  }

  setKind(kind: 'all' | SessionKind): void {
    if (this.kindFilter() === kind) return;
    this.kindFilter.set(kind);
    this.reload();
  }

  setMember(userId: string): void {
    this.memberFilter.set(userId || '');
    this.reload();
  }

  private fetchSessions(): void {
    this.loading.set(true);
    this.error.set(null);
    const status = this.status();
    const member = this.memberFilter();
    const limit = this.limit();
    const kind = this.kindFilter();

    const chatParams: Record<string, string> = {
      include_admin: 'true',
      status,
      limit: String(limit),
      offset: '0',
    };
    if (member) chatParams['user_id'] = member;

    const captureParams: Record<string, string> = { limit: String(limit) };
    if (status !== 'active') captureParams['include_archived'] = 'true';

    let chatError: string | null = null;
    const chat$ =
      kind === 'capture' || kind === 'correction'
        ? of<AdminSessionListResponse>({ sessions: [] })
        : this.api
            .get<AdminSessionListResponse | AdminSessionSummary[]>('/sessions', chatParams)
            .pipe(
              catchError((err) => {
                chatError =
                  err?.status === 403
                    ? this.i18n.t('governance.chat.error.forbidden')
                    : this.i18n.t('governance.chat.error.chat');
                return of<AdminSessionListResponse>({ sessions: [] });
              }),
            );

    const capture$ =
      kind === 'chat'
        ? of<CaptureSessionListResponse>({ sessions: [] })
        : this.api
            .get<CaptureSessionListResponse>('/knowledge-capture/sessions', captureParams)
            .pipe(catchError(() => of<CaptureSessionListResponse>({ sessions: [] })));

    forkJoin({ chat: chat$, capture: capture$ }).subscribe({
      next: ({ chat, capture }) => {
        const chatRows = Array.isArray(chat) ? chat : chat?.sessions ?? [];
        const captureRows = capture?.sessions ?? [];
        this.mergeRows(chatRows, captureRows, { status, member, kind });
        this.hasMoreFlag.set(chatRows.length >= limit || captureRows.length >= limit);
        this.error.set(chatError);
        this.loading.set(false);
      },
      error: () => {
        this.rows.set([]);
        this.loading.set(false);
        this.error.set(this.i18n.t('governance.chat.error.load'));
      },
    });
  }

  private mergeRows(
    chatRows: AdminSessionSummary[],
    captureRows: CaptureSessionSummary[],
    filters: { status: StatusFilter; member: string; kind: 'all' | SessionKind },
  ): void {
    const merged: UnifiedRow[] = [];

    if (filters.kind === 'all' || filters.kind === 'chat') {
      for (const s of chatRows) merged.push(this.chatToRow(s));
    }

    for (const c of captureRows) {
      const row = this.captureToRow(c);
      if (filters.kind !== 'all' && row.kind !== filters.kind) continue;
      // Capture endpoint has no per-member filter — narrow client-side.
      if (filters.member && (row.userId || '') !== filters.member) continue;
      // The capture endpoint cannot scope to "archived only"; do it here.
      if (filters.status === 'archived' && !c.archived) continue;
      merged.push(row);
    }

    merged.sort((a, b) => this.activityMs(b) - this.activityMs(a));
    this.rows.set(merged);
  }

  private activityMs(row: UnifiedRow): number {
    const value = row.lastActivity || row.createdAt;
    const parsed = value ? Date.parse(value) : NaN;
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  private chatToRow(s: AdminSessionSummary): UnifiedRow {
    return {
      id: s.id,
      kind: 'chat',
      userId: s.user_id ?? null,
      authorLabel:
        (s.author_label || '').trim() ||
        (s.author_email || '').trim() ||
        s.user_id ||
        this.i18n.t('governance.chat.author.unknown'),
      authorEmail: s.author_email ?? null,
      title: (s.title || '').trim() || this.i18n.t('governance.chat.untitled.chat'),
      status: s.status || 'active',
      createdAt: s.created_at ?? null,
      lastActivity: s.last_activity || s.created_at || null,
      count: s.message_count ?? 0,
      context: this.chatContext(s),
      chat: s,
    };
  }

  private captureToRow(c: CaptureSessionSummary): UnifiedRow {
    const status = c.status || 'planned';
    return {
      id: c.id,
      kind: status === 'chat_correction' ? 'correction' : 'capture',
      userId: c.created_by_user_id ?? null,
      authorLabel:
        (c.created_by_label || '').trim() ||
        c.created_by_user_id ||
        this.i18n.t('governance.chat.author.unknown'),
      authorEmail: null,
      title:
        (c.title || '').trim() ||
        (c.objective || '').trim() ||
        this.i18n.t('governance.chat.untitled.capture'),
      status,
      createdAt: c.created_at ?? null,
      lastActivity: c.last_activity || c.updated_at || c.created_at || null,
      count: c.turn_count ?? (c.transcript?.length ?? 0),
      context: this.captureContext(c),
      capture: c,
    };
  }

  openDetail(row: UnifiedRow): void {
    this.selectedRow.set(row);
    this.turns.set([]);
    this.captureEntries.set([]);
    this.captureObjective.set('');
    this.captureProposalStatus.set(null);
    this.captureProposalBlocks.set([]);
    this.drawerOpen.set(true);
    this.detailLoading.set(true);

    if (row.kind === 'chat') {
      this.loadChatDetail(row);
    } else {
      this.loadCaptureDetail(row);
    }
  }

  private loadChatDetail(row: UnifiedRow): void {
    this.api
      .get<AdminSessionDetail>(`/sessions/${encodeURIComponent(row.id)}`, {
        include_messages: 'true',
        include_jobs: 'true',
      })
      .subscribe({
        next: (detail) => {
          this.turns.set((detail.messages || []).map((m) => this.toTurn(m)));
          this.detailLoading.set(false);
        },
        error: () => {
          this.detailLoading.set(false);
          this.error.set(this.i18n.t('governance.chat.error.conversation'));
        },
      });
  }

  private loadCaptureDetail(row: UnifiedRow): void {
    const id = encodeURIComponent(row.id);
    forkJoin({
      detail: this.api
        .get<CaptureSessionDetail>(`/knowledge-capture/sessions/${id}`)
        .pipe(catchError(() => of<CaptureSessionDetail | null>(null))),
      events: this.api
        .get<CaptureEventListResponse>(`/knowledge-capture/sessions/${id}/events`)
        .pipe(catchError(() => of<CaptureEventListResponse>({ events: [] }))),
      proposals: this.api
        .get<CaptureProposalListResponse>('/knowledge-capture/proposals', { session_id: row.id })
        .pipe(catchError(() => of<CaptureProposalListResponse>({ proposals: [] }))),
    }).subscribe({
      next: ({ detail, events, proposals }) => {
        const objective = (detail?.objective || row.capture?.objective || '').trim();
        this.captureObjective.set(objective);
        this.captureEntries.set(
          this.buildCaptureEntries(detail?.transcript || row.capture?.transcript || [], events?.events || []),
        );
        const proposal = (proposals?.proposals || [])[0] || null;
        this.captureProposalStatus.set(proposal?.status ?? null);
        this.captureProposalBlocks.set(this.renderMarkdown(this.proposalContent(proposal)));
        this.detailLoading.set(false);
      },
      error: () => {
        this.detailLoading.set(false);
        this.error.set(this.i18n.t('governance.chat.error.capture'));
      },
    });
  }

  closeDetail(): void {
    this.drawerOpen.set(false);
    this.selectedRow.set(null);
    this.turns.set([]);
    this.captureEntries.set([]);
    this.captureObjective.set('');
    this.captureProposalStatus.set(null);
    this.captureProposalBlocks.set([]);
  }

  // ---- presentation helpers -------------------------------------------------

  authorInitial(row: UnifiedRow): string {
    return (row.authorLabel || '').charAt(0).toUpperCase() || '?';
  }

  kindLabel(kind: SessionKind): string {
    switch (kind) {
      case 'capture':
        return this.i18n.t('governance.chat.kind.capture');
      case 'correction':
        return this.i18n.t('governance.chat.kind.correction');
      default:
        return this.i18n.t('governance.chat.kind.chat');
    }
  }

  kindIcon(kind: SessionKind): string {
    switch (kind) {
      case 'capture':
        return 'mic';
      case 'correction':
        return 'edit-3';
      default:
        return 'message-square';
    }
  }

  kindClass(kind: SessionKind): string {
    switch (kind) {
      case 'capture':
        return 'bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30';
      case 'correction':
        return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
      default:
        return 'bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30';
    }
  }

  /** Status comes from the API; translate known values, fall back to the raw one. */
  statusLabel(status?: string): string {
    const value = status || 'active';
    const key = 'governance.chat.status.' + value;
    const label = this.i18n.t(key);
    return label === key ? value.replace(/_/g, ' ') : label;
  }

  statusClass(status?: string): string {
    switch (status) {
      case 'archived':
        return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
      case 'deleted':
      case 'rejected':
        return 'bg-red-500/15 text-red-300 ring-1 ring-red-500/30';
      case 'completed':
      case 'published':
      case 'accepted':
        return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30';
      case 'pending_review':
      case 'changes_requested':
        return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
      default:
        return 'bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/30';
    }
  }

  private chatContext(s: AdminSessionSummary): string {
    const meta = s.meta_data || {};
    const parts: string[] = [];
    const system = this.metaString(meta, 'system_id');
    const context = this.metaString(meta, 'context_id');
    if (system) parts.push(system);
    if (context) parts.push(context);
    if (parts.length) return parts.join(' · ');
    return (
      this.metaString(meta, 'assistant_profile') ||
      this.metaString(meta, 'knowledge_scope') ||
      this.metaString(meta, 'created_from') ||
      '—'
    );
  }

  private captureContext(c: CaptureSessionSummary): string {
    const parts: string[] = [];
    if (c.system_id) parts.push(c.system_id);
    if (c.context_id) parts.push(c.context_id);
    if (parts.length) return parts.join(' · ');
    const domain = this.metaString(c.metrics || {}, 'capture_domain');
    if (domain) return domain;
    const origin = this.metaString(c.metrics || {}, 'origin');
    if (origin) return origin.replace(/_/g, ' ');
    return '—';
  }

  private metaString(meta: Record<string, unknown>, key: string): string {
    const value = meta[key];
    return typeof value === 'string' ? value : '';
  }

  // ---- capture transcript building ------------------------------------------

  private buildCaptureEntries(transcript: CaptureTurnRaw[], events: CaptureEvent[]): CaptureEntry[] {
    const entries: CaptureEntry[] = [];

    for (const turn of transcript || []) {
      const text = (turn.text || turn.text_amended || turn.text_raw || '').trim();
      const raw = (turn.text_raw || '').trim();
      if (!text && !raw) continue;
      const speaker = (turn.speaker || 'expert').toLowerCase();
      entries.push({
        speaker: speaker === 'expert' ? 'expert' : 'system',
        label: this.speakerLabel(speaker, turn.turn_kind),
        text: text || raw,
        rawText: turn.text_amended && raw && raw !== text ? raw : null,
        timestamp: turn.created_at ?? null,
      });
    }

    // Fall back to business events when the session has no transcript (the case
    // for chat-corrections, where the voice event carries raw + amended text).
    if (entries.length === 0) {
      for (const ev of events || []) {
        if (!MEANINGFUL_CAPTURE_EVENTS.has(ev.event_type)) continue;
        const amended = (ev.text_amended || '').trim();
        const raw = (ev.text_raw || '').trim();
        const text = (ev.text || amended || raw).trim();
        if (!text && !raw) continue;
        const speaker = (ev.speaker || 'expert').toLowerCase();
        entries.push({
          speaker: speaker === 'expert' ? 'expert' : 'system',
          label: this.eventLabel(ev.event_type),
          text: text || raw,
          rawText: amended && raw && raw !== amended ? raw : null,
          timestamp: ev.created_at ?? null,
        });
      }
    }

    return entries;
  }

  private speakerLabel(speaker: string, turnKind?: string | null): string {
    if (speaker === 'expert') {
      if (turnKind === 'correction') return this.i18n.t('governance.chat.speaker.expert_correction');
      if (turnKind === 'complement') return this.i18n.t('governance.chat.speaker.expert_complement');
      return this.i18n.t('governance.chat.speaker.expert');
    }
    if (speaker === 'operator') return this.i18n.t('governance.chat.speaker.operator');
    return this.i18n.t('governance.chat.speaker.interviewer');
  }

  private eventLabel(eventType: string): string {
    switch (eventType) {
      case 'chat_correction_voice':
        return this.i18n.t('governance.chat.event.chat_correction_voice');
      case 'expert_turn_finalized':
        return this.i18n.t('governance.chat.speaker.expert');
      default:
        return eventType.replace(/_/g, ' ');
    }
  }

  private proposalContent(proposal: CaptureProposal | null): string {
    if (!proposal) return '';
    const payload = (proposal.proposal || {}) as Record<string, unknown>;
    const recommended = (payload['recommended_ingestion'] || {}) as Record<string, unknown>;
    const content = recommended['content'] ?? payload['report_markdown'] ?? '';
    return typeof content === 'string' ? content.trim() : '';
  }

  // ---- read-only transcript rendering (mirrors chat-panel approach) ---------

  private toTurn(message: AdminSessionMessage): TranscriptTurn {
    const role = message.role === 'assistant' ? 'assistant' : 'user';
    const content = message.content || '';
    return {
      role,
      content,
      timestamp: message.timestamp ?? null,
      blocks: role === 'assistant' ? this.renderMarkdown(content) : [],
    };
  }

  private renderMarkdown(content: string): TranscriptBlock[] {
    const text = (content || '').replace(/\r\n?/g, '\n');
    if (!text.trim()) return [];
    const lines = text.split('\n');
    const blocks: TranscriptBlock[] = [];
    let paragraph: string[] = [];
    let list: { ordered: boolean; items: InlineToken[][] } | null = null;
    let code: string[] | null = null;

    const flushParagraph = () => {
      const value = paragraph.join('\n').trim();
      if (value) blocks.push({ kind: 'paragraph', tokens: this.inlineTokens(value) });
      paragraph = [];
    };
    const flushList = () => {
      if (list && list.items.length) {
        blocks.push({ kind: 'list', ordered: list.ordered, items: list.items });
      }
      list = null;
    };

    for (const raw of lines) {
      const line = raw.replace(/\s+$/g, '');
      if (/^\s*```/.test(line)) {
        if (code) {
          blocks.push({ kind: 'code', value: code.join('\n') });
          code = null;
        } else {
          flushParagraph();
          flushList();
          code = [];
        }
        continue;
      }
      if (code) {
        code.push(raw);
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      if (heading) {
        flushParagraph();
        flushList();
        const level = Math.min(4, Math.max(2, heading[1].length + 1)) as 2 | 3 | 4;
        blocks.push({ kind: 'heading', level, tokens: this.inlineTokens(heading[2]) });
        continue;
      }
      const bullet = /^\s*([-*•]|\d+[.)])\s+(.+)$/.exec(line);
      if (bullet) {
        flushParagraph();
        const ordered = /\d/.test(bullet[1]);
        if (!list) list = { ordered, items: [] };
        list.items.push(this.inlineTokens(bullet[2]));
        continue;
      }
      flushList();
      paragraph.push(line);
    }
    if (code) blocks.push({ kind: 'code', value: code.join('\n') });
    flushParagraph();
    flushList();
    return blocks;
  }

  private inlineTokens(text: string): InlineToken[] {
    const tokens: InlineToken[] = [];
    const pattern = /(\*\*([^*]+)\*\*|__([^_]+)__|\*([^*]+)\*|_([^_]+)_|`([^`]+)`)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) tokens.push({ kind: 'text', value: text.slice(last, match.index) });
      const strong = match[2] ?? match[3];
      const em = match[4] ?? match[5];
      if (strong != null) tokens.push({ kind: 'strong', value: strong });
      else if (em != null) tokens.push({ kind: 'em', value: em });
      else if (match[6] != null) tokens.push({ kind: 'code', value: match[6] });
      last = pattern.lastIndex;
    }
    if (last < text.length) tokens.push({ kind: 'text', value: text.slice(last) });
    return tokens.length ? tokens : [{ kind: 'text', value: text }];
  }
}
