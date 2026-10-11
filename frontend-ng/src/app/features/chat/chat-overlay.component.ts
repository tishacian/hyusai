import { AssistantPilotComponent } from './assistant-pilot.component';
import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { NavLinkDirective } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { navigationLeafUrl } from '@app/core/navigation.catalog';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ChatOverlayService } from './chat-overlay.service';
import { ChatWorkspaceComponent } from './chat-workspace.component';

/** Width the proof rail adds beside the thread (px). */
export const CHAT_PROOF_RAIL_WIDTH = 380;

function isSentinelShowcaseProfile(profile: Record<string, unknown> | null): boolean {
  if (!profile) return false;
  return profile['key'] === 'vigie_executive'
    || profile['showcase_mode'] === 'sentinel_ci'
    || profile['design_mode'] === 'sentinel_ci'
    || profile['tone'] === 'ministerial';
}

/**
 * `ChatOverlayComponent` — shell-level side-panel that hosts the global
 * chat workspace. Mounted once inside `ShellComponent` so the chat is
 * reachable from any view without tearing down context.
 *
 * L11 keeps `app-chat-workspace` alive across close/reopen (`retainContent`)
 * so an in-flight stream is not aborted (`chat.toast.stream_lost`).
 */
@Component({
  selector: 'app-chat-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CkPanelComponent,
    IconComponent,
    ChatWorkspaceComponent,
    AssistantPilotComponent,
    NavLinkDirective,
  ],
  template: `
    <ck-panel
      [open]="overlay.isOpen()"
      [retainContent]="everOpened()"
      (openChange)="onOpenChange($event)"
      position="side"
      [modal]="overlay.blocksPage()"
      [title]="title()"
      [width]="panelWidth()"
      [extraWidth]="proofExtraWidth()"
      [animateWidth]="overlay.proofAnimate()"
      [resizable]="!overlay.narrow() && !expanded()"
      resizeStorageKey="agentium.chat-panel-width"
    >
      <div class="chat-overlay-frame" [class.sentinel-chat-overlay]="sentinelShowcase()" [class.adoption-companion]="overlay.adoption.enabled()">
        <div class="chat-overlay-toolbar">
          @if (threadMeta(); as meta) {
            <span class="chat-overlay-meta" data-testid="chat-overlay-meta">{{ meta }}</span>
          } @else {
            <span class="chat-overlay-hint">
              {{ i18n.t('chat.overlay.hint') }}
            </span>
          }
          <div class="chat-overlay-toolbar-actions">
            @if (!inWork()) {
              <!-- The history lives in Cockpit: never linked from Work (L36). -->
              <a
                [navLink]="{ surface: 'conversations' }"
                class="chat-overlay-history"
                data-testid="chat-overlay-history"
                (click)="overlay.close()"
              >
                <app-icon name="history" [size]="13" />
                {{ i18n.t('chat.overlay.history') }}
              </a>
            }
            @if (pilotAvailable()) {
              <button
                type="button"
                class="chat-overlay-expand"
                (click)="togglePilot()"
                [attr.aria-pressed]="overlay.pilot()"
              >
                {{ i18n.t(overlay.pilot() ? 'experience.adoption.pilot.back' : 'experience.adoption.pilot.switch') }}
              </button>
            }
            @if ((!overlay.adoption.enabled() || !overlay.narrow()) && (overlay.adoption.enabled() || !inWork())) {
              <button
                type="button"
                class="chat-overlay-expand"
                (click)="expandToWorkspaceChat()"
                [title]="i18n.t('chat.overlay.expand.hint')"
              >
                <app-icon name="maximize" [size]="13" />
                {{ i18n.t(overlay.adoption.enabled() && overlay.expanded() ? 'experience.adoption.reduce' : 'chat.overlay.expand') }}
              </button>
            }
          </div>
        </div>
        @if (pilotAvailable() && overlay.pilot()) {
          <app-assistant-pilot [initialSystemId]="overlay.preselectedSystemId()" />
        } @else {
          <app-chat-workspace
            [inline]="true"
            [startMode]="overlay.startMode()"
            [initialSystemId]="overlay.preselectedSystemId()"
            [initialContextId]="overlay.preselectedContextId()"
            [assistantProfileKey]="overlay.assistantProfile()"
            [initialPrompt]="overlay.initialPrompt()"
            [initialPromptRevision]="overlay.initialPromptRevision()"
            [autoStartVoiceLoop]="overlay.autoStartVoiceLoop()"
            [resumeSessionId]="overlay.sessionId()"
            [proofThread]="true"
            [surface]="overlay.surface()"
          />
        }
        <footer class="chat-overlay-footer" data-testid="chat-overlay-footer">
          {{ i18n.t(inWork() ? 'experience.work.chat.footer' : 'chat.overlay.footer') }}
        </footer>
      </div>
    </ck-panel>
  `,
  styles: [`
    :host { display: contents; }
    :host ::ng-deep ck-panel > div[role="complementary"] > div:last-child {
      padding: 0 !important;
    }
    .chat-overlay-frame {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      background: var(--ck-bg-base, #0a0e14);
    }
    .chat-overlay-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex: 0 0 auto;
      min-height: 34px;
      padding: 6px 10px;
      border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
      background: var(--ck-tint-faint, rgba(255, 255, 255, 0.018));
    }
    .chat-overlay-toolbar-actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .chat-overlay-hint {
      color: var(--ck-fg-3);
      font-size: 12px;
      line-height: 1.3;
    }
    .chat-overlay-meta {
      min-width: 0;
      overflow: hidden;
      color: var(--ck-fg-3);
      font-size: 12px;
      line-height: 1.3;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    /* Sentence case, sans, same shape as its two neighbours (Tokens v2). */
    .chat-overlay-history {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 3px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      font-size: 12px;
      font-weight: 500;
      text-decoration: none;
    }
    .chat-overlay-history:hover { border-color: var(--ck-stroke-hot); background: var(--ck-bg-raised); }
    .chat-overlay-history:focus-visible,
    .chat-overlay-expand:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .chat-overlay-expand {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 3px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      font-size: 12px;
      font-weight: 500;
      transition: border-color 140ms ease, background-color 140ms ease;
    }
    .chat-overlay-expand:hover {
      border-color: var(--ck-stroke-hot, rgba(103, 213, 246, 0.36));
      background: var(--ck-bg-raised);
    }
    .adoption-companion .chat-overlay-expand {
      color: var(--ck-fg-1);
      background: var(--ck-bg-panel);
      border-color: var(--ck-stroke-2);
      min-height: 32px;
    }
    .adoption-companion .chat-overlay-hint { color: var(--ck-fg-3); }
    .sentinel-chat-overlay .chat-overlay-expand {
      border-color: rgba(101, 214, 110, 0.28);
      background: rgba(7, 14, 11, 0.76);
      color: #d9ffdf;
    }
    .chat-overlay-frame app-chat-workspace,
    .chat-overlay-frame app-assistant-pilot {
      flex: 1 1 auto;
      min-height: 0;
    }
    .chat-overlay-footer {
      flex: 0 0 auto;
      padding: 8px 12px;
      border-top: 1px solid var(--ck-stroke-2);
      color: var(--ck-fg-3);
      font-size: 11px;
      line-height: 1.3;
    }
  `],
})
export class ChatOverlayComponent {
  readonly overlay = inject(ChatOverlayService);
  protected readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);

  /** Once true, ck-panel keeps the workspace mounted across close/reopen. */
  readonly everOpened = signal(false);

  constructor() {
    effect(() => {
      if (this.overlay.isOpen()) this.everOpened.set(true);
    });
  }

  readonly activeProfile = computed<Record<string, unknown> | null>(() => {
    const settings = this.workspace.current()?.settings as Record<string, unknown> | undefined;
    const key = this.overlay.assistantProfile() || (settings?.['assistant_profile_default'] as string | undefined);
    if (!key) return null;
    const profiles = Array.isArray(settings?.['assistant_profiles'])
      ? settings?.['assistant_profiles'] as Record<string, unknown>[]
      : [];
    return profiles.find((profile) => profile['key'] === key) ?? null;
  });

  readonly title = computed<string>(() => {
    this.i18n.locale();
    const linked = this.overlay.linkedLabel();
    if (linked) {
      return this.i18n.t('chat.overlay.thread_title', { name: linked });
    }
    const profile = this.activeProfile();
    if (profile?.['label']) return `Interroger ${profile['label']}`;
    switch (this.overlay.startMode()) {
      case 'drop':   return this.i18n.t('palette.hint.drop_files');
      case 'system': return this.i18n.t('palette.hint.chat_system');
      case 'quick':
      default:       return this.i18n.t('chat.overlay.title');
    }
  });

  /** « Dans : {objet} · Sources : {collection} », only with what is known. */
  readonly threadMeta = computed<string | null>(() => {
    this.i18n.locale();
    const parts: string[] = [];
    const linked = this.overlay.linkedLabel();
    if (linked) parts.push(this.i18n.t('chat.overlay.meta.in', { name: linked }));
    const scope = this.showsThread() ? this.overlay.threadScope() : null;
    if (scope) parts.push(this.i18n.t('chat.overlay.meta.sources', { label: scope }));
    return parts.length ? parts.join(' · ') : null;
  });

  private readonly showsThread = computed(() => !(this.pilotAvailable() && this.overlay.pilot()));

  /** The proof rail widens the panel beside the thread, never on a phone. */
  readonly proofExtraWidth = computed(() =>
    this.showsThread() && this.overlay.proofOpen() && !this.overlay.narrow() && !this.expanded()
      ? CHAT_PROOF_RAIL_WIDTH
      : 0,
  );

  /** The System pilot is a Cockpit tool: never offered from Work (L36). */
  readonly pilotAvailable = computed(
    () => this.overlay.adoption.enabled() && !this.overlay.assistantProfile() && this.overlay.startMode() !== 'drop'
      && this.overlay.surface() !== 'work',
  );

  readonly panelWidth = computed<string>(() => {
    if (this.expanded()) return '100vw';
    if (this.overlay.narrow()) return '100vw';
    return isSentinelShowcaseProfile(this.activeProfile()) ? '680px' : '560px';
  });

  readonly expanded = computed(() => this.overlay.adoption.enabled() && this.overlay.expanded());

  /** L36 — opened from Work: no way out to a Cockpit page from here. */
  readonly inWork = computed(() => this.overlay.surface() === 'work');

  readonly sentinelShowcase = computed<boolean>(() => isSentinelShowcaseProfile(this.activeProfile()));

  onOpenChange(open: boolean): void {
    if (!open) this.overlay.close();
  }

  @HostListener('window:resize')
  onResize(): void { this.overlay.narrow.set(window.innerWidth <= 700); }

  togglePilot(): void {
    this.overlay.pilot.update((value) => !value);
  }

  expandToWorkspaceChat(): void {
    if (this.overlay.adoption.enabled()) { this.overlay.expanded.update(value => !value); return; }
    const navigate = () => {
      const slug = this.workspace.currentSlug() || this.workspace.current()?.slug;
      if (!slug) return;
      const queryParams: Record<string, string> = {
        mode: this.overlay.startMode(),
      };
      const systemId = this.overlay.preselectedSystemId();
      const contextId = this.overlay.preselectedContextId();
      const assistantProfile = this.overlay.assistantProfile();
      const initialPrompt = this.overlay.initialPrompt();
      const autoStartVoiceLoop = this.overlay.autoStartVoiceLoop();
      if (systemId) queryParams['systemId'] = systemId;
      if (contextId) queryParams['contextId'] = contextId;
      if (assistantProfile) queryParams['assistantProfile'] = assistantProfile;
      if (initialPrompt) queryParams['initialPrompt'] = initialPrompt;
      if (autoStartVoiceLoop) queryParams['autoStartVoiceLoop'] = 'true';
      this.overlay.close();
      const base = navigationLeafUrl('workspace-chat-page', { slug });
      const extra = new URLSearchParams(queryParams).toString();
      void this.router.navigateByUrl(extra ? `${base}${base.includes('?') ? '&' : '?'}${extra}` : base);
    };

    if (this.workspace.current()) {
      navigate();
      return;
    }
    this.workspace.refreshCurrentWorkspace().subscribe({
      next: navigate,
      error: navigate,
    });
  }

  @HostListener('window:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    const isMod = ev.metaKey || ev.ctrlKey;
    if (isMod && (ev.key === 'j' || ev.key === 'J')) {
      ev.preventDefault();
      if (this.overlay.isOpen()) {
        this.overlay.close();
      } else {
        this.overlay.open({ mode: 'quick' });
        this.workspace.refreshCurrentWorkspace().subscribe({
          next: () => undefined,
          error: () => undefined,
        });
      }
    }
  }
}
