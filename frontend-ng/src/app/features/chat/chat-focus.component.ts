import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ChatWorkspaceComponent } from './chat-workspace.component';
import { type ChatViewMode } from './chat-panel.component';
import { type ChatStartMode } from './chat-overlay.service';

/**
 * Direct workspace chat surface.
 *
 * The overlay remains the quick-access chat. This component is the expanded
 * URL-addressable version for demos and focused work:
 * `/workspace/:slug/chat`.
 */
@Component({
  selector: 'app-chat-focus',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective, IconComponent, ChatWorkspaceComponent],
  template: `
    <div class="chat-focus-shell">
      <header class="chat-focus-header">
        <div class="chat-focus-title">
          <span class="chat-focus-mark">
            <app-icon name="message-square" [size]="16" />
          </span>
          <div class="chat-focus-copy">
            <span class="chat-focus-eyebrow">Workspace · Chat</span>
            <h1>{{ workspaceName() }} Assistant</h1>
          </div>
        </div>
        <nav class="chat-focus-actions" aria-label="Chat workspace actions">
          <a
            class="chat-focus-link"
            [navLink]="{ leaf: 'workspace-chat-knowledge', ref: workspaceSlug() }"
            title="Configure source scopes and chat defaults"
          >
            <app-icon name="settings" [size]="13" />
            Settings
          </a>
          <a
            class="chat-focus-link"
            [navLink]="{ surface: 'chat' }"
            title="Open the standard {{ brand() }} chat route"
          >
            <app-icon name="panel-left" [size]="13" />
            Standard view
          </a>
          <a
            class="chat-focus-link"
            [navLink]="{ surface: 'hypervisor' }"
            title="Return to {{ brand() }}"
          >
            <app-icon name="x" [size]="13" />
            Exit
          </a>
        </nav>
      </header>
      <main class="chat-focus-main">
        <app-chat-workspace
          [inline]="false"
          [startMode]="startMode()"
          [initialSystemId]="initialSystemId()"
          [initialContextId]="initialContextId()"
          [assistantProfileKey]="assistantProfileKey()"
          [initialPrompt]="initialPrompt()"
          [autoStartVoiceLoop]="autoStartVoiceLoop()"
          [viewMode]="viewMode()"
        />
      </main>
    </div>
  `,
  styles: [`
    :host {
      display: block;
      height: 100vh;
      width: 100%;
      overflow: hidden;
      background: var(--ck-bg-base, #0a0e14);
      color: var(--ck-fg-1, #f5f8fc);
    }
    .chat-focus-shell {
      display: grid;
      grid-template-rows: 58px minmax(0, 1fr);
      height: 100vh;
      width: 100%;
      overflow: hidden;
      /* Content-first: a flat surface, no corner glow competing with the
         answer for attention. */
      background: var(--ck-bg-base, #0a0e14);
    }
    .chat-focus-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-width: 0;
      padding: 10px 16px;
      border-bottom: 1px solid var(--ck-stroke-2, rgba(255,255,255,0.08));
      background: rgba(2, 7, 14, 0.72);
    }
    .chat-focus-title {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .chat-focus-mark {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      flex: 0 0 34px;
      border-radius: 10px;
      color: rgb(103, 213, 246);
      background: rgba(34, 211, 238, 0.10);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.24);
    }
    .chat-focus-copy {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 2px;
    }
    .chat-focus-eyebrow {
      color: var(--ck-signal-cool, #67d5f6);
      font: 750 10px/1 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      color: var(--ck-fg-1, #f5f8fc);
      font-size: 16px;
      line-height: 1.2;
      font-weight: 720;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .chat-focus-actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }
    .chat-focus-link {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 32px;
      padding: 0 10px;
      border-radius: 8px;
      border: 1px solid rgba(148, 197, 229, 0.14);
      background: rgba(255, 255, 255, 0.035);
      color: rgba(226, 236, 248, 0.78);
      font-size: 12px;
      font-weight: 650;
      text-decoration: none;
      transition: 140ms ease;
    }
    .chat-focus-link:hover {
      border-color: rgba(103, 213, 246, 0.32);
      background: rgba(34, 211, 238, 0.09);
      color: rgb(245, 248, 252);
    }
    .chat-focus-main {
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }
    @media (max-width: 760px) {
      .chat-focus-header {
        align-items: flex-start;
        flex-direction: column;
        height: auto;
      }
      .chat-focus-shell {
        grid-template-rows: auto minmax(0, 1fr);
      }
      .chat-focus-actions {
        width: 100%;
        overflow-x: auto;
        padding-bottom: 2px;
      }
    }
  `],
})
export class ChatFocusComponent implements OnInit {
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  private readonly route = inject(ActivatedRoute);
  protected readonly workspace = inject(WorkspaceService);

  readonly workspaceSlug = signal('workspace');
  readonly startMode = signal<ChatStartMode>('quick');
  readonly initialSystemId = signal<string | null>(null);
  readonly initialContextId = signal<string | null>(null);
  readonly assistantProfileKey = signal<string | null>(null);
  readonly initialPrompt = signal<string | null>(null);
  readonly autoStartVoiceLoop = signal(false);

  /**
   * Quick Ask is the simple surface; `?mode=system` and `?mode=drop` keep the
   * full panel. The mode is read here, at the route boundary, so the chat
   * panel itself never has to inspect the URL.
   */
  readonly viewMode = computed<ChatViewMode>(() =>
    this.startMode() === 'quick' ? 'simple' : 'standard',
  );

  readonly workspaceName = computed(() => {
    const current = this.workspace.current();
    return current?.name || this.workspaceSlug();
  });

  ngOnInit(): void {
    const slug = this.route.snapshot.paramMap.get('slug') || this.workspace.currentSlug() || '';
    this.workspaceSlug.set(slug || 'workspace');
    this.applyQueryParams();
    this.ensureWorkspace(slug);
  }

  private ensureWorkspace(slug: string): void {
    if (!slug) return;
    const switchIfAvailable = () => {
      if (this.workspace.currentSlug() !== slug) {
        this.workspace.switchWorkspace(slug);
      }
    };
    if (this.workspace.workspaces().length > 0) {
      switchIfAvailable();
      return;
    }
    this.workspace.loadWorkspaces().subscribe({ next: switchIfAvailable });
  }

  private applyQueryParams(): void {
    const params = this.route.snapshot.queryParamMap;
    const mode = params.get('mode');
    if (mode === 'system' || mode === 'drop' || mode === 'quick') {
      this.startMode.set(mode);
    }
    this.initialSystemId.set(params.get('systemId'));
    this.initialContextId.set(params.get('contextId'));
    this.assistantProfileKey.set(params.get('assistantProfile'));
    this.initialPrompt.set(params.get('initialPrompt'));
    this.autoStartVoiceLoop.set(params.get('autoStartVoiceLoop') === 'true');
  }
}
