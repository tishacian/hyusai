/**
 * Suivre › Conversations — personal (and admin workspace) history.
 *
 * Rows open `/conversations/:id`. « Nouvelle conversation » opens the overlay.
 * Admin facet `?facet=mine|workspace` adds author column + filter and includes
 * capture sessions in the workspace scope.
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, ParamMap, Router, RouterLink } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError, distinctUntilChanged, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { PageFrameComponent } from '@app/shared/cockpit';
import { ChatOverlayService } from './chat-overlay.service';

export type ConversationsFacet = 'mine' | 'workspace';

export interface ConversationLinkedObject {
  type?: string;
  id?: string;
  label?: string;
  lens?: string;
}

export interface ConversationSessionSummary {
  id: string;
  user_id?: string | null;
  author_label?: string | null;
  author_email?: string | null;
  title?: string | null;
  status?: string;
  last_activity?: string | null;
  created_at?: string | null;
  message_count?: number;
  meta_data?: Record<string, unknown> | null;
}

interface SessionListResponse {
  sessions?: ConversationSessionSummary[];
  total?: number;
}

interface CaptureSessionSummary {
  id: string;
  created_by_user_id?: string | null;
  created_by_label?: string | null;
  title?: string | null;
  objective?: string | null;
  status?: string | null;
  turn_count?: number;
  archived?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  last_activity?: string | null;
}

interface CaptureSessionListResponse {
  sessions?: CaptureSessionSummary[];
}

type RowKind = 'chat' | 'capture';

interface ConversationRow {
  id: string;
  kind: RowKind;
  title: string;
  linkedLabel: string | null;
  linkedId: string | null;
  messageCount: number;
  lastActivity: string | null;
  authorLabel: string | null;
  authorId: string | null;
}

@Component({
  selector: 'app-conversations',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    DatePipe,
    RouterLink,
    PageFrameComponent,
    EmptyStateComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('conversations.eyebrow')"
      [title]="i18n.t('nav.conversations')"
      [description]="i18n.t('conversations.description')"
    >
      <div actions style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;">
        @if (isAdmin()) {
          <div
            class="flex items-center gap-1"
            style="padding:3px;background:var(--ck-bg-inset);border:1px solid var(--ck-stroke-2);border-radius:3px;"
            data-testid="conversations-facet-toggle"
          >
            <button
              type="button"
              class="ck-mono"
              style="padding:5px 10px;border-radius:3px;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;"
              [style.background]="facet() === 'mine' ? 'var(--ck-bg-raised)' : 'transparent'"
              [style.color]="facet() === 'mine' ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
              (click)="setFacet('mine')"
            >
              {{ i18n.t('conversations.facet.mine') }}
            </button>
            <button
              type="button"
              class="ck-mono"
              style="padding:5px 10px;border-radius:3px;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;"
              [style.background]="facet() === 'workspace' ? 'var(--ck-bg-raised)' : 'transparent'"
              [style.color]="facet() === 'workspace' ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
              (click)="setFacet('workspace')"
            >
              {{ i18n.t('conversations.facet.workspace') }}
            </button>
          </div>
        }
        <button
          type="button"
          class="ck-mono"
          style="padding:6px 12px;border-radius:3px;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;border:1px solid var(--ck-stroke-2);color:var(--ck-fg-1);background:var(--ck-bg-inset);"
          (click)="openNew()"
          data-testid="conversations-new"
        >
          {{ i18n.t('conversations.new') }}
        </button>
      </div>

      <div class="flex flex-col gap-4">
        <section class="ck-surface rounded-md" style="padding:12px 18px;">
          <div class="flex items-center gap-3 flex-wrap">
            <label class="ck-mono" style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);" for="conversations-search">
              {{ i18n.t('conversations.search') }}
            </label>
            <input
              id="conversations-search"
              name="q"
              [(ngModel)]="searchDraft"
              (keyup.enter)="applySearch()"
              class="ck-mono"
              style="height:28px;min-width:180px;padding:0 9px;background:var(--ck-bg-inset);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:3px;font-size:11px;"
              [placeholder]="i18n.t('conversations.search.placeholder')"
            />
            <button
              type="button"
              class="ck-mono"
              style="padding:5px 10px;border-radius:3px;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;border:1px solid var(--ck-stroke-2);color:var(--ck-fg-2);"
              (click)="applySearch()"
            >
              {{ i18n.t('common.refresh') }}
            </button>

            <label class="ck-mono" style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);" for="conversations-linked">
              {{ i18n.t('conversations.filter.linked') }}
            </label>
            <select
              id="conversations-linked"
              class="ck-mono"
              style="height:28px;padding:0 8px;background:var(--ck-bg-inset);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:3px;font-size:11px;"
              [ngModel]="linkedFilter()"
              (ngModelChange)="setLinkedFilter($event)"
            >
              <option value="">{{ i18n.t('conversations.filter.linked.all') }}</option>
              @for (opt of linkedOptions(); track opt.id) {
                <option [value]="opt.id">{{ opt.label }}</option>
              }
            </select>

            @if (showAuthorColumn()) {
              <label class="ck-mono" style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);" for="conversations-author">
                {{ i18n.t('conversations.filter.author') }}
              </label>
              <select
                id="conversations-author"
                class="ck-mono"
                style="height:28px;padding:0 8px;background:var(--ck-bg-inset);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:3px;font-size:11px;"
                [ngModel]="authorFilter()"
                (ngModelChange)="setAuthorFilter($event)"
                data-testid="conversations-author-filter"
              >
                <option value="">{{ i18n.t('conversations.filter.author.all') }}</option>
                @for (m of members(); track m.user_id) {
                  <option [value]="m.user_id">{{ m.label }}</option>
                }
              </select>

              <label class="ck-mono" style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);" for="conversations-kind">
                {{ i18n.t('conversations.filter.kind') }}
              </label>
              <select
                id="conversations-kind"
                class="ck-mono"
                style="height:28px;padding:0 8px;background:var(--ck-bg-inset);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:3px;font-size:11px;"
                [ngModel]="kindFilter()"
                (ngModelChange)="setKindFilter($event)"
              >
                <option value="all">{{ i18n.t('conversations.filter.kind.all') }}</option>
                <option value="chat">{{ i18n.t('conversations.filter.kind.chat') }}</option>
                <option value="capture">{{ i18n.t('conversations.filter.kind.capture') }}</option>
              </select>
            }

            <span class="ml-auto ck-mono" style="font-size:10px;color:var(--ck-fg-4);">
              {{ i18n.t('conversations.count', { count: rows().length }) }}
            </span>
          </div>
        </section>

        <section class="ck-surface rounded-md" style="padding:0;overflow:hidden;">
          @if (loading()) {
            <div class="ck-mono" style="font-size:11px;padding:48px;text-align:center;color:var(--ck-fg-4);">
              {{ i18n.t('common.loading') }}
            </div>
          } @else if (!rows().length) {
            <app-empty-state
              icon="message-square"
              [title]="i18n.t('conversations.empty.title')"
              [description]="i18n.t('conversations.empty.description')"
            />
          } @else {
            <table class="w-full text-sm">
              <thead>
                <tr class="text-left ck-mono" style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);border-bottom:1px solid var(--ck-stroke-2);">
                  @if (showAuthorColumn()) {
                    <th class="px-5 py-3 font-medium" data-testid="conversations-author-column">
                      {{ i18n.t('conversations.column.author') }}
                    </th>
                  }
                  <th class="px-5 py-3 font-medium">{{ i18n.t('conversations.column.title') }}</th>
                  <th class="px-5 py-3 font-medium">{{ i18n.t('conversations.column.linked') }}</th>
                  <th class="px-5 py-3 font-medium text-center">{{ i18n.t('conversations.column.messages') }}</th>
                  <th class="px-5 py-3 font-medium">{{ i18n.t('conversations.column.activity') }}</th>
                </tr>
              </thead>
              <tbody>
                @for (row of rows(); track row.kind + ':' + row.id) {
                  <tr
                    class="transition"
                    style="border-bottom:1px solid var(--ck-hair);cursor:pointer;"
                    [routerLink]="row.kind === 'chat' ? ['/conversations', row.id] : undefined"
                    [attr.data-testid]="'conversations-row-' + row.id"
                  >
                    @if (showAuthorColumn()) {
                      <td class="px-5 py-3" style="color:var(--ck-fg-2);">{{ row.authorLabel || '—' }}</td>
                    }
                    <td class="px-5 py-3" style="color:var(--ck-fg-1);font-weight:500;">
                      {{ row.title }}
                      @if (row.kind === 'capture') {
                        <span class="ck-mono" style="margin-left:8px;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);">
                          {{ i18n.t('conversations.kind.capture') }}
                        </span>
                      }
                    </td>
                    <td class="px-5 py-3" style="color:var(--ck-fg-3);">
                      @if (row.linkedLabel) {
                        {{ i18n.t('nav.zoom.linked_to', { name: row.linkedLabel }) }}
                      } @else {
                        —
                      }
                    </td>
                    <td class="px-5 py-3 text-center ck-mono" style="color:var(--ck-fg-3);">{{ row.messageCount }}</td>
                    <td class="px-5 py-3 whitespace-nowrap" style="color:var(--ck-fg-4);">
                      {{ row.lastActivity ? (row.lastActivity | date: 'MMM d, HH:mm') : '—' }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          }
        </section>
      </div>
    </ck-page-frame>
  `,
})
export class ConversationsComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly overlay = inject(ChatOverlayService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly rows = signal<ConversationRow[]>([]);
  readonly loading = signal(false);
  readonly facet = signal<ConversationsFacet>('mine');
  readonly linkedFilter = signal('');
  readonly authorFilter = signal('');
  readonly kindFilter = signal<'all' | RowKind>('all');
  readonly members = signal<Array<{ user_id: string; label: string }>>([]);
  readonly linkedOptions = signal<Array<{ id: string; label: string }>>([]);
  searchDraft = '';
  private searchQ = '';
  private querySub: Subscription | null = null;
  private requestGeneration = 0;

  readonly isAdmin = computed(() => this.workspace.isAdmin());
  readonly showAuthorColumn = computed(() => this.isAdmin() && this.facet() === 'workspace');

  ngOnInit(): void {
    this.querySub = this.route.queryParamMap
      .pipe(
        map((params) => this.facetFromQuery(params)),
        distinctUntilChanged(),
      )
      .subscribe((facet) => {
        this.facet.set(facet);
        if (this.isAdmin() && facet === 'workspace') this.loadMembers();
        this.reload();
      });
  }

  ngOnDestroy(): void {
    this.querySub?.unsubscribe();
  }

  /** Exposed for storeSpecs — restore facet from the URL. */
  setScopeFromQuery(params: ParamMap): void {
    this.facet.set(this.facetFromQuery(params));
  }

  private facetFromQuery(params: ParamMap): ConversationsFacet {
    if (!this.workspace.isAdmin()) return 'mine';
    return params.get('facet') === 'workspace' ? 'workspace' : 'mine';
  }

  setFacet(facet: ConversationsFacet): void {
    if (!this.isAdmin() || this.facet() === facet) return;
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  applySearch(): void {
    this.searchQ = this.searchDraft.trim();
    this.reload();
  }

  setLinkedFilter(value: string): void {
    this.linkedFilter.set(value || '');
    this.reload();
  }

  setAuthorFilter(value: string): void {
    this.authorFilter.set(value || '');
    this.reload();
  }

  setKindFilter(value: 'all' | RowKind): void {
    this.kindFilter.set(value || 'all');
    this.reload();
  }

  openNew(): void {
    this.overlay.open({ mode: 'quick' });
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

  private reload(): void {
    const generation = ++this.requestGeneration;
    this.loading.set(true);
    const workspaceScope = this.showAuthorColumn();
    const chatParams: Record<string, string> = {
      status: 'all',
      limit: '100',
      offset: '0',
    };
    if (this.searchQ) chatParams['q'] = this.searchQ;
    if (this.linkedFilter()) {
      chatParams['linked_type'] = 'system';
      chatParams['linked_id'] = this.linkedFilter();
    }
    if (workspaceScope) {
      chatParams['include_admin'] = 'true';
      if (this.authorFilter()) chatParams['user_id'] = this.authorFilter();
    }

    const kind = this.kindFilter();
    const chat$ =
      workspaceScope && kind === 'capture'
        ? of<SessionListResponse>({ sessions: [] })
        : this.api.get<SessionListResponse>('/sessions', chatParams).pipe(
            catchError(() => of<SessionListResponse>({ sessions: [] })),
          );

    const capture$ =
      workspaceScope && kind !== 'chat'
        ? this.api
            .get<CaptureSessionListResponse>('/knowledge-capture/sessions', {
              limit: '100',
              include_archived: 'true',
            })
            .pipe(catchError(() => of<CaptureSessionListResponse>({ sessions: [] })))
        : of<CaptureSessionListResponse>({ sessions: [] });

    forkJoin({ chat: chat$, capture: capture$ }).subscribe({
      next: ({ chat, capture }) => {
        if (generation !== this.requestGeneration) return;
        const chatRows = (chat.sessions ?? []).map((s) => this.chatToRow(s));
        let captureRows = (capture.sessions ?? []).map((s) => this.captureToRow(s));
        if (this.authorFilter()) {
          captureRows = captureRows.filter((r) => r.authorId === this.authorFilter());
        }
        if (this.searchQ) {
          const q = this.searchQ.toLowerCase();
          captureRows = captureRows.filter((r) => r.title.toLowerCase().includes(q));
        }
        const merged =
          kind === 'chat'
            ? chatRows
            : kind === 'capture'
              ? captureRows
              : [...chatRows, ...captureRows].sort((a, b) =>
                  String(b.lastActivity || '').localeCompare(String(a.lastActivity || '')),
                );
        this.rows.set(merged);
        this.refreshLinkedOptions(chat.sessions ?? []);
        this.loading.set(false);
      },
      error: () => {
        if (generation !== this.requestGeneration) return;
        this.rows.set([]);
        this.loading.set(false);
      },
    });
  }

  private refreshLinkedOptions(sessions: ConversationSessionSummary[]): void {
    const map = new Map<string, string>();
    for (const session of sessions) {
      const linked = this.linkedObject(session);
      if (linked?.id) map.set(linked.id, linked.label || linked.id);
    }
    this.linkedOptions.set(
      [...map.entries()]
        .map(([id, label]) => ({ id, label }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    );
  }

  private linkedObject(session: ConversationSessionSummary): ConversationLinkedObject | null {
    const meta = session.meta_data;
    const raw = meta && typeof meta === 'object' ? meta['linked_object'] : null;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    return raw as ConversationLinkedObject;
  }

  private chatToRow(session: ConversationSessionSummary): ConversationRow {
    const linked = this.linkedObject(session);
    return {
      id: session.id,
      kind: 'chat',
      title: (session.title && session.title.trim()) || this.i18n.t('conversations.untitled'),
      linkedLabel: linked?.label || null,
      linkedId: linked?.id || null,
      messageCount: session.message_count ?? 0,
      lastActivity: session.last_activity || session.created_at || null,
      authorLabel: session.author_label || session.author_email || null,
      authorId: session.user_id || null,
    };
  }

  private captureToRow(session: CaptureSessionSummary): ConversationRow {
    return {
      id: session.id,
      kind: 'capture',
      title:
        (session.title && session.title.trim())
        || (session.objective && session.objective.trim())
        || this.i18n.t('conversations.untitled'),
      linkedLabel: null,
      linkedId: null,
      messageCount: session.turn_count ?? 0,
      lastActivity: session.last_activity || session.updated_at || session.created_at || null,
      authorLabel: session.created_by_label || null,
      authorId: session.created_by_user_id || null,
    };
  }
}
