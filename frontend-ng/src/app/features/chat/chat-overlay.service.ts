import { Injectable, signal } from '@angular/core';

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
  readonly isOpen = signal(false);
  readonly startMode = signal<ChatStartMode>('quick');
  readonly preselectedSystemId = signal<string | null>(null);
  readonly preselectedContextId = signal<string | null>(null);
  readonly assistantProfile = signal<string | null>(null);
  readonly initialPrompt = signal<string | null>(null);

  open(options?: {
    mode?: ChatStartMode;
    systemId?: string | null;
    contextId?: string | null;
    assistantProfile?: string | null;
    initialPrompt?: string | null;
  }): void {
    this.startMode.set(options?.mode ?? 'quick');
    this.preselectedSystemId.set(options?.systemId ?? null);
    this.preselectedContextId.set(options?.contextId ?? null);
    this.assistantProfile.set(options?.assistantProfile ?? null);
    this.initialPrompt.set(options?.initialPrompt ?? null);
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }

  toggle(): void {
    if (this.isOpen()) this.close();
    else this.open();
  }
}
