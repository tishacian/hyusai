/**
 * Conversation detail page — `/conversations/:id`.
 *
 * Fil « Conversations › {titre} » comes from ZoomContext (L9). Chip « Liée à »
 * and « Reprendre dans le calque » live here; others' sessions are read-only.
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
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { AuthStore } from '@app/store/auth.store';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { PageFrameComponent, TagComponent, NavLinkDirective } from '@app/shared/cockpit';
import { ChatOverlayService } from './chat-overlay.service';
import type { ConversationLinkedObject, ConversationSessionSummary } from './conversations.component';

interface SessionMessage {
  id?: string;
  role: string;
  content: string;
  timestamp?: string | null;
}

interface SessionDetail extends ConversationSessionSummary {
  messages?: SessionMessage[];
}

@Component({
  selector: 'app-conversation-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    PageFrameComponent,
    EmptyStateComponent,
    TagComponent,
    NavLinkDirective,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('conversations.eyebrow')"
      [title]="title()"
      [description]="subtitle()"
    >
      <div actions style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;">
        @if (linkedLabel(); as label) {
          <ck-tag tone="cool" variant="outline" data-testid="conversation-linked-chip">
            {{ i18n.t('nav.zoom.linked_to', { name: label }) }}
          </ck-tag>
        }
        @if (readOnly()) {
          <span class="ck-mono" style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-4);" data-testid="conversation-readonly">
            {{ i18n.t('conversations.readonly') }}
          </span>
        } @else {
          <button
            type="button"
            class="ck-mono"
            style="padding:6px 12px;border-radius:3px;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;border:1px solid var(--ck-stroke-2);color:var(--ck-fg-1);background:var(--ck-bg-inset);"
            (click)="resumeInOverlay()"
            data-testid="conversation-resume"
          >
            {{ i18n.t('conversations.resume') }}
          </button>
        }
        <a
          [navLink]="{ surface: 'conversations' }"
          class="ck-mono"
          style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--ck-fg-3);text-decoration:underline;"
        >
          {{ i18n.t('conversations.back_to_list') }}
        </a>
      </div>

      @if (loading()) {
        <div class="ck-mono" style="font-size:11px;padding:48px;text-align:center;color:var(--ck-fg-4);">
          {{ i18n.t('common.loading') }}
        </div>
      } @else if (error(); as message) {
        <app-empty-state icon="warn" [title]="i18n.t('conversations.error.title')" [description]="message" />
      } @else {
        <section class="ck-surface rounded-md" style="padding:18px 22px;display:flex;flex-direction:column;gap:14px;">
          @if (!messages().length) {
            <p class="ck-mono" style="font-size:11px;color:var(--ck-fg-4);">{{ i18n.t('conversations.detail.empty') }}</p>
          } @else {
            @for (msg of messages(); track msg.id || $index) {
              <article style="display:flex;flex-direction:column;gap:4px;">
                <div class="ck-mono" style="font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:var(--ck-fg-4);">
                  {{ msg.role }}
                  @if (msg.timestamp) {
                    <span> · {{ msg.timestamp | date: 'MMM d, HH:mm' }}</span>
                  }
                </div>
                <div style="color:var(--ck-fg-2);font-size:13px;line-height:1.5;white-space:pre-wrap;">{{ msg.content }}</div>
              </article>
            }
          }
        </section>
      }
    </ck-page-frame>
  `,
})
export class ConversationPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly overlay = inject(ChatOverlayService);
  private readonly auth = inject(AuthStore);
  readonly i18n = inject(I18nService);

  readonly session = signal<SessionDetail | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  private paramSub: Subscription | null = null;

  readonly title = computed(() => {
    const s = this.session();
    return (s?.title && s.title.trim()) || this.i18n.t('conversations.untitled');
  });

  readonly subtitle = computed(() => {
    const s = this.session();
    if (!s) return '';
    const count = s.message_count ?? s.messages?.length ?? 0;
    return this.i18n.t('conversations.detail.subtitle', { count });
  });

  readonly linkedLabel = computed(() => {
    const linked = this.linkedObject();
    return linked?.label || null;
  });

  readonly messages = computed(() => this.session()?.messages ?? []);

  readonly readOnly = computed(() => {
    const s = this.session();
    if (!s) return true;
    const me = this.auth.userId();
    if (!me) return false;
    return !!s.user_id && s.user_id !== me;
  });

  ngOnInit(): void {
    this.paramSub = this.route.paramMap.subscribe((params) => {
      const id = params.get('conversationId');
      if (id) this.load(id);
    });
  }

  ngOnDestroy(): void {
    this.paramSub?.unsubscribe();
  }

  /** Test helper — load a session id without routing. */
  loadSession(id: string): void {
    this.load(id);
  }

  resumeInOverlay(): void {
    const s = this.session();
    if (!s || this.readOnly()) return;
    const linked = this.linkedObject();
    this.overlay.open({
      mode: linked?.type === 'system' ? 'system' : 'quick',
      systemId: linked?.type === 'system' ? linked.id ?? null : null,
      sessionId: s.id,
      linkedLabel: linked?.label ?? null,
    });
  }

  private linkedObject(): ConversationLinkedObject | null {
    const meta = this.session()?.meta_data;
    const raw = meta && typeof meta === 'object' ? meta['linked_object'] : null;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    return raw as ConversationLinkedObject;
  }

  private load(id: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .get<SessionDetail>(`/sessions/${encodeURIComponent(id)}?include_messages=true`)
      .subscribe({
        next: (detail) => {
          this.session.set(detail);
          this.loading.set(false);
        },
        error: () => {
          this.session.set(null);
          this.error.set(this.i18n.t('conversations.error.load'));
          this.loading.set(false);
        },
      });
  }
}
