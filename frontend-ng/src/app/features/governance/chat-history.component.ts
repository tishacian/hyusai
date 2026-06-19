import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, NgClass, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '@app/core/api.service';
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

interface MemberOption {
  user_id: string;
  label: string;
}

type StatusFilter = 'active' | 'archived' | 'all';

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
      breadcrumb="Govern"
      title="Chat history"
      icon="message-square"
      subtitle="Read-only view of every member's chat sessions across the workspace."
    >
      <button
        type="button"
        (click)="reload()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
      </button>
    </app-section-header>

    <div class="flex flex-wrap items-center gap-3 mb-4">
      <select
        [ngModel]="memberFilter()"
        (ngModelChange)="setMember($event)"
        class="ch-select"
        title="Filter by member"
      >
        <option value="">All members</option>
        @for (m of members(); track m.user_id) {
          <option [value]="m.user_id">{{ m.label }}</option>
        }
      </select>

      <div class="flex items-center gap-1 p-1 rounded bg-black/20 border border-white/5">
        @for (f of statusFilters; track f.key) {
          <button
            type="button"
            (click)="setStatus(f.key)"
            class="px-2.5 py-1 text-xs rounded transition"
            [class.bg-brand-500\\/20]="status() === f.key"
            [class.text-brand-300]="status() === f.key"
            [class.text-gray-400]="status() !== f.key"
            [class.hover:text-gray-200]="status() !== f.key"
          >
            {{ f.label }}
          </button>
        }
      </div>

      <span class="text-[11px] text-gray-500 font-mono ml-auto">
        {{ sessions().length }} session{{ sessions().length === 1 ? '' : 's' }}
      </span>
    </div>

    @if (error(); as message) {
      <div class="mb-4 rounded-md p-3 bg-red-500/10 ring-1 ring-red-400/25 text-sm text-red-100">
        {{ message }}
      </div>
    }

    <section class="t-card t-elevated rounded-md overflow-hidden">
      @if (loading()) {
        <div class="p-6 space-y-3">
          @for (_ of skeletonRows; track $index) {
            <app-skeleton variant="line" height="44px" />
          }
        </div>
      } @else if (sessions().length === 0) {
        <app-empty-state
          icon="message-square"
          title="No chat sessions"
          description="Member conversations in this workspace will show up here."
        />
      } @else {
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-white/5">
                <th class="px-5 py-3 font-semibold">Author</th>
                <th class="px-5 py-3 font-semibold">Title</th>
                <th class="px-5 py-3 font-semibold">Last activity</th>
                <th class="px-5 py-3 font-semibold text-center">Messages</th>
                <th class="px-5 py-3 font-semibold">System / Context</th>
                <th class="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              @for (session of sessions(); track session.id) {
                <tr
                  class="hover:bg-white/[0.02] transition cursor-pointer"
                  (click)="openDetail(session)"
                >
                  <td class="px-5 py-3">
                    <div class="flex items-center gap-2 min-w-0">
                      <span class="h-7 w-7 shrink-0 rounded-full bg-white/[0.04] ring-1 ring-brand-400/30 flex items-center justify-center text-[11px] font-semibold text-brand-200">
                        {{ authorInitial(session) }}
                      </span>
                      <div class="min-w-0">
                        <div class="truncate text-white font-medium">{{ authorLabel(session) }}</div>
                        @if (session.author_email && session.author_email !== authorLabel(session)) {
                          <div class="truncate text-[11px] text-gray-500">{{ session.author_email }}</div>
                        }
                      </div>
                    </div>
                  </td>
                  <td class="px-5 py-3 text-gray-200 max-w-xs">
                    <span class="block truncate">{{ sessionTitle(session) }}</span>
                  </td>
                  <td class="px-5 py-3 text-gray-400 whitespace-nowrap">
                    {{ (session.last_activity || session.created_at) | date: 'MMM d, HH:mm' }}
                  </td>
                  <td class="px-5 py-3 text-gray-300 text-center font-mono">{{ session.message_count ?? 0 }}</td>
                  <td class="px-5 py-3 text-gray-400 font-mono text-xs">{{ systemContext(session) }}</td>
                  <td class="px-5 py-3">
                    <span
                      class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full uppercase tracking-wider"
                      [ngClass]="statusClass(session.status)"
                    >
                      {{ session.status || 'active' }}
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
              Showing {{ sessions().length }}
            </span>
            <button
              type="button"
              (click)="loadMore()"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
            >
              <app-icon name="chevron-down" [size]="12" /> Load more
            </button>
          </div>
        }
      }
    </section>

    <!-- Read-only detail drawer: renders the transcript reusing the chat-panel
         message-rendering approach, with NO correction CTA and no edit/delete. -->
    <app-drawer
      [open]="drawerOpen()"
      [title]="drawerTitle()"
      [subtitle]="drawerSubtitle()"
      icon="message-square"
      [width]="640"
      (close)="closeDetail()"
    >
      @if (selected(); as session) {
        <div class="space-y-5">
          <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">Author</dt>
              <dd class="text-gray-200 mt-0.5">{{ authorLabel(session) }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">Status</dt>
              <dd class="text-gray-200 mt-0.5">{{ session.status || 'active' }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">Created</dt>
              <dd class="text-gray-200 mt-0.5">{{ session.created_at | date: 'MMM d, y HH:mm' }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">Last activity</dt>
              <dd class="text-gray-200 mt-0.5">{{ session.last_activity | date: 'MMM d, y HH:mm' }}</dd>
            </div>
            <div class="col-span-2">
              <dt class="text-gray-500 uppercase tracking-wider text-[10px]">System / Context</dt>
              <dd class="text-gray-200 mt-0.5 font-mono text-[11px]">{{ systemContext(session) }}</dd>
            </div>
          </dl>

          <div class="border-t border-white/10 pt-4">
            <h3 class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
              <app-icon name="message-circle" [size]="13" class="text-brand-400" />
              Transcript
            </h3>

            @if (detailLoading()) {
              <div class="space-y-3">
                @for (_ of skeletonRows; track $index) {
                  <app-skeleton variant="line" height="56px" />
                }
              </div>
            } @else if (turns().length === 0) {
              <app-empty-state
                icon="inbox"
                size="sm"
                title="No messages"
                description="This conversation has no recorded messages."
              />
            } @else {
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

              <div class="space-y-4">
                @for (turn of turns(); track $index) {
                  @if (turn.role === 'user') {
                    <div class="flex justify-end">
                      <div class="max-w-[85%] bg-brand-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed shadow-sm">
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
          </div>
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

  readonly sessions = signal<AdminSessionSummary[]>([]);
  readonly members = signal<MemberOption[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly memberFilter = signal<string>('');
  readonly status = signal<StatusFilter>('active');
  private readonly pageSize = 50;
  private readonly limit = signal(this.pageSize);
  private readonly hasMoreFlag = signal(false);

  readonly selected = signal<AdminSessionDetail | null>(null);
  readonly drawerOpen = signal(false);
  readonly detailLoading = signal(false);
  readonly turns = signal<TranscriptTurn[]>([]);

  readonly skeletonRows = Array(6);

  readonly statusFilters: { key: StatusFilter; label: string }[] = [
    { key: 'active', label: 'Active' },
    { key: 'archived', label: 'Archived' },
    { key: 'all', label: 'All' },
  ];

  readonly hasMore = computed(() => this.hasMoreFlag());

  readonly drawerTitle = computed(() => {
    const session = this.selected();
    return session ? this.sessionTitle(session) : 'Chat session';
  });

  readonly drawerSubtitle = computed(() => {
    const session = this.selected();
    if (!session) return undefined;
    const count = session.message_count ?? this.turns().length;
    return `${this.authorLabel(session)} · ${count} message${count === 1 ? '' : 's'}`;
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

  setMember(userId: string): void {
    this.memberFilter.set(userId || '');
    this.reload();
  }

  private fetchSessions(): void {
    this.loading.set(true);
    this.error.set(null);
    const params: Record<string, string> = {
      include_admin: 'true',
      status: this.status(),
      limit: String(this.limit()),
      offset: '0',
    };
    const member = this.memberFilter();
    if (member) params['user_id'] = member;
    this.api.get<AdminSessionListResponse | AdminSessionSummary[]>('/sessions', params).subscribe({
      next: (payload) => {
        const rows = Array.isArray(payload) ? payload : payload?.sessions ?? [];
        this.sessions.set(rows);
        this.hasMoreFlag.set(rows.length >= this.limit());
        this.loading.set(false);
      },
      error: (err) => {
        this.sessions.set([]);
        this.loading.set(false);
        this.error.set(
          err?.status === 403
            ? 'Admin role is required to view workspace chat history.'
            : 'Unable to load chat history.',
        );
      },
    });
  }

  openDetail(session: AdminSessionSummary): void {
    this.selected.set(session);
    this.turns.set([]);
    this.drawerOpen.set(true);
    this.detailLoading.set(true);
    this.api
      .get<AdminSessionDetail>(
        `/sessions/${encodeURIComponent(session.id)}`,
        { include_messages: 'true', include_jobs: 'true' },
      )
      .subscribe({
        next: (detail) => {
          this.selected.set({ ...session, ...detail });
          this.turns.set((detail.messages || []).map((m) => this.toTurn(m)));
          this.detailLoading.set(false);
        },
        error: () => {
          this.detailLoading.set(false);
          this.error.set('Unable to load this conversation.');
        },
      });
  }

  closeDetail(): void {
    this.drawerOpen.set(false);
    this.selected.set(null);
    this.turns.set([]);
  }

  // ---- presentation helpers -------------------------------------------------

  authorLabel(session: AdminSessionSummary): string {
    return (
      (session.author_label || '').trim() ||
      (session.author_email || '').trim() ||
      session.user_id ||
      'Unknown'
    );
  }

  authorInitial(session: AdminSessionSummary): string {
    return this.authorLabel(session).charAt(0).toUpperCase() || '?';
  }

  sessionTitle(session: AdminSessionSummary): string {
    return (session.title || '').trim() || 'Untitled conversation';
  }

  systemContext(session: AdminSessionSummary): string {
    const meta = session.meta_data || {};
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

  statusClass(status?: string): string {
    switch (status) {
      case 'archived':
        return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
      case 'deleted':
        return 'bg-red-500/15 text-red-300 ring-1 ring-red-500/30';
      default:
        return 'bg-brand-500/10 text-brand-300 ring-1 ring-brand-500/30';
    }
  }

  private metaString(meta: Record<string, unknown>, key: string): string {
    const value = meta[key];
    return typeof value === 'string' ? value : '';
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
