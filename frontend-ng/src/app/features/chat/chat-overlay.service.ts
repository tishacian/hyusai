import { AdoptionService } from '@app/core/adoption.service';
import { Injectable, computed, inject, signal } from '@angular/core';
import { WorkspaceService } from '@app/core/workspace.service';

/**
 * `ChatOverlayService` — coordinates the global chat side-panel.
 *
 * The chat surface is accessible from three entry points (Vague D / D0):
 *  - Icône `message-square` in the title bar
 *  - Keyboard shortcut `⌘J` / `Ctrl+J` (global)
 *  - Command palette commands (Ask…, Chat with system, Drop and ask)
 *
 * Each entry point calls `open()` with a hint about the desired start
 * mode ("quick" | "system" | "drop") so the overlay can pre-select the
 * right affordance. The overlay itself owns the lifecycle of the
 * ephemeral Context (drop-and-ask sessions).
 *
 * The route `/chat` keeps the standard Agentium chat surface, while
 * `/workspace/:slug/chat` provides a direct expanded workspace URL that
 * can be opened from the panel without replacing this quick access.
 */
export type ChatStartMode = 'quick' | 'system' | 'drop';

@Injectable({ providedIn: 'root' })
export class ChatOverlayService {
  private readonly workspace = inject(WorkspaceService);

  readonly adoption = inject(AdoptionService);
  readonly isOpen = signal(false);
  readonly expanded = signal(false);
  /** Opt-in System pilot; the designed chat workspace stays the default companion. */
  readonly pilot = signal(false);
  readonly narrow = signal(typeof window !== 'undefined' && window.innerWidth <= 700);
  readonly blocksPage = computed(() => this.isOpen() && (!this.adoption.enabled() || this.expanded() || this.narrow()));
  readonly startMode = signal<ChatStartMode>('quick');
  readonly preselectedSystemId = signal<string | null>(null);
  readonly preselectedContextId = signal<string | null>(null);
  readonly assistantProfile = signal<string | null>(null);
  readonly initialPrompt = signal<string | null>(null);
  readonly autoStartVoiceLoop = signal(false);

  constructor() {
    this.workspace.registerContextReset(() => this.reset());
  }

  /**
   * Drop-and-ask upload gating. Reads the per-workspace
   * `settings.features.chat_document_upload` flag (enabled by default;
   * only an explicit `false` disables it).
   */
  private chatUploadEnabled(): boolean {
    const features = this.workspace.current()?.settings?.['features'] as
      | Record<string, unknown>
      | undefined;
    return features?.['chat_document_upload'] !== false;
  }

  open(options?: {
    mode?: ChatStartMode;
    systemId?: string | null;
    contextId?: string | null;
    assistantProfile?: string | null;
    initialPrompt?: string | null;
    autoStartVoiceLoop?: boolean;
    pilot?: boolean;
  }): void {
    let mode = options?.mode ?? 'quick';
    this.pilot.set(!!options?.pilot);
    // When chat document upload is disabled for the workspace, the
    // drop-and-ask surface is hidden, so fall back to a quick ask.
    if (mode === 'drop' && !this.chatUploadEnabled()) {
      mode = 'quick';
    }
    this.startMode.set(mode);
    this.preselectedSystemId.set(options?.systemId ?? null);
    this.preselectedContextId.set(options?.contextId ?? null);
    this.assistantProfile.set(options?.assistantProfile ?? null);
    this.initialPrompt.set(options?.initialPrompt ?? null);
    this.autoStartVoiceLoop.set(!!options?.autoStartVoiceLoop);
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }

  reset(): void {
    this.isOpen.set(false);
    this.expanded.set(false);
    this.pilot.set(false);
    this.startMode.set('quick');
    this.preselectedSystemId.set(null);
    this.preselectedContextId.set(null);
    this.assistantProfile.set(null);
    this.initialPrompt.set(null);
    this.autoStartVoiceLoop.set(false);
  }

  toggle(): void {
    if (this.isOpen()) this.close();
    else this.open();
  }
}
