import { AssistantPilotComponent } from './assistant-pilot.component';
import { ChangeDetectionStrategy, Component, HostListener, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { navigationLeafUrl } from '@app/core/navigation.catalog';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ChatOverlayService } from './chat-overlay.service';
import { ChatWorkspaceComponent } from './chat-workspace.component';

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
 * Lifecycle is driven by `ChatOverlayService`:
 *  - `open()` from the title-bar icon, the global ⌘J shortcut, or a
 *    command palette command → `isOpen.set(true)`.
 *  - `close()` from the panel close button, Escape (via `PanelHostService`)
 *    or another explicit call.
 *
 * The panel embeds `<app-chat-workspace [inline]="true">` in compact
 * layout: dropzone collapsible above the chat instead of the two-column
 * layout used on the full-screen `/chat` route.
 */
@Component({
  selector: 'app-chat-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkPanelComponent, IconComponent, ChatWorkspaceComponent, AssistantPilotComponent],
  template: `
    <ck-panel
      [open]="overlay.isOpen()"
      (openChange)="onOpenChange($event)"
      position="side"
      [modal]="overlay.blocksPage()"
      [eyebrow]="i18n.t('titlebar.chat.tooltip')"
      [title]="title()"
      [width]="panelWidth()"
    >
      @if (overlay.isOpen()) {
        <div class="chat-overlay-frame" [class.sentinel-chat-overlay]="sentinelShowcase()" [class.adoption-companion]="overlay.adoption.enabled()">
          <div class="chat-overlay-toolbar">
            <span class="chat-overlay-hint">
              {{ i18n.t('chat.overlay.hint') }}
            </span>
            @if (!overlay.adoption.enabled() || !overlay.narrow()) { <button
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
          @if (overlay.adoption.enabled() && !overlay.assistantProfile() && overlay.startMode() !== 'drop') {
            <app-assistant-pilot [initialSystemId]="overlay.preselectedSystemId()" />
          } @else {
          <app-chat-workspace
            [inline]="true"
            [startMode]="overlay.startMode()"
            [initialSystemId]="overlay.preselectedSystemId()"
            [initialContextId]="overlay.preselectedContextId()"
            [assistantProfileKey]="overlay.assistantProfile()"
            [initialPrompt]="overlay.initialPrompt()"
            [autoStartVoiceLoop]="overlay.autoStartVoiceLoop()"
          />
          }
        </div>
      }
    </ck-panel>
  `,
  styles: [`
    :host { display: contents; }
    /* The ck-panel paints its own shell; we just make sure the workspace
       fills the entire panel body (which defaults to 18px padding).
       We override by pulling the workspace flush with the panel edges. */
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
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.018);
    }
    .chat-overlay-hint {
      color: var(--ck-fg-4, rgba(177, 190, 210, 0.68));
      font: 700 9px/1 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    .chat-overlay-expand {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 7px;
      border: 1px solid rgba(103, 213, 246, 0.18);
      background: rgba(34, 211, 238, 0.08);
      color: rgb(207, 250, 254);
      font-size: 11px;
      font-weight: 700;
      transition: 140ms ease;
    }
    .chat-overlay-expand:hover {
      border-color: rgba(103, 213, 246, 0.36);
      background: rgba(34, 211, 238, 0.14);
      color: rgb(245, 248, 252);
    }
    .adoption-companion .chat-overlay-expand {color:var(--ck-fg-1);background:var(--ck-bg-panel);border-color:var(--ck-stroke-2);min-height:32px;}
    .adoption-companion .chat-overlay-hint {color:var(--ck-fg-3);}
    .sentinel-chat-overlay .chat-overlay-expand {
      border-color: rgba(101, 214, 110, 0.28);
      background:
        linear-gradient(135deg, rgba(101, 214, 110, 0.10), rgba(242, 140, 56, 0.06)),
        rgba(7, 14, 11, 0.76);
      color: #d9ffdf;
    }
    .sentinel-chat-overlay .chat-overlay-expand:hover {
      border-color: rgba(242, 140, 56, 0.38);
      background:
        linear-gradient(135deg, rgba(101, 214, 110, 0.14), rgba(242, 140, 56, 0.10)),
        rgba(8, 18, 13, 0.86);
      color: #fff6e8;
    }
    .chat-overlay-frame app-chat-workspace {
      flex: 1 1 auto;
      min-height: 0;
    }
  `],
})
export class ChatOverlayComponent {
  readonly overlay = inject(ChatOverlayService);
  protected readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);

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
    // Read locale so the title re-renders when the user toggles FR/EN.
    this.i18n.locale();
    const profile = this.activeProfile();
    if (profile?.['label']) return `Interroger ${profile['label']}`;
    switch (this.overlay.startMode()) {
      case 'drop':   return this.i18n.t('palette.hint.drop_files');
      case 'system': return this.i18n.t('palette.hint.chat_system');
      case 'quick':
      default:       return this.i18n.t('palette.hint.ask');
    }
  });

  readonly panelWidth = computed<string>(() => {
    if (this.overlay.adoption.enabled() && (this.overlay.expanded() || this.overlay.narrow())) return '100vw';
    return isSentinelShowcaseProfile(this.activeProfile()) ? '680px' : '560px';
  });

  readonly sentinelShowcase = computed<boolean>(() => isSentinelShowcaseProfile(this.activeProfile()));

  onOpenChange(open: boolean): void {
    if (!open) this.overlay.close();
  }

  @HostListener('window:resize')
  onResize(): void { this.overlay.narrow.set(window.innerWidth <= 700); }

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

  /**
   * Global keyboard shortcut: ⌘J (macOS) / Ctrl+J (Linux/Windows).
   * We override the browser default (⌘J opens Downloads on Chrome) —
   * acceptable for an SPA since the overlay is a more productive use of
   * that shortcut for this surface.
   */
  @HostListener('window:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    const isMod = ev.metaKey || ev.ctrlKey;
    if (isMod && (ev.key === 'j' || ev.key === 'J')) {
      ev.preventDefault();
      if (this.overlay.isOpen()) {
        this.overlay.close();
      } else {
        // Match TitleBar.openChat — open immediately, refresh in the
        // background so ⌘J never feels gated on the workspace HTTP
        // round-trip.
        this.overlay.open({ mode: 'quick' });
        this.workspace.refreshCurrentWorkspace().subscribe({
          next: () => undefined,
          error: () => undefined,
        });
      }
    }
  }
}
