import { AdoptionService } from '@app/core/adoption.service';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
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
/** L36 — where the chat was opened from: Work reads sources in place, without Cockpit links. */
export type ChatSurface = 'cockpit' | 'work';

/** A Work page (`/work`, `/work/…`): the business side of the product. */
export function isWorkUrl(url: string | null | undefined): boolean {
  return /^\/work(?:[/?#]|$)/.test(url ?? '');
}

@Injectable({ providedIn: 'root' })
export class ChatOverlayService {
  private readonly workspace = inject(WorkspaceService);
  /** Optional: a bare injector (unit specs) opens in Cockpit mode. */
  private readonly router = inject(Router, { optional: true });

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
  /**
   * Bumped on every open that carries a prompt, so the retained chat panel
   * prefills again even when the text equals the previous one (L27, ⌘K).
   */
  readonly initialPromptRevision = signal(0);
  readonly autoStartVoiceLoop = signal(false);
  /** Resume a durable session when opened from Conversations › Reprendre. */
  readonly sessionId = signal<string | null>(null);
  /** Display label for « Conversation · Liée à {objet} ». */
  readonly linkedLabel = signal<string | null>(null);
  /** L30 — the proof rail is open beside the thread, so the panel widens. */
  readonly proofOpen = signal(false);
  /** A pointer opened the proof: only then may the panel animate its widening. */
  readonly proofAnimate = signal(false);
  /** Source scope the thread reads from, shown in the overlay's meta line. */
  readonly threadScope = signal<string | null>(null);
  /** L36 — Work or Cockpit, fixed at each opening (explicit, else from the page it opens on). */
  readonly surface = signal<ChatSurface>('cockpit');

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
    sessionId?: string | null;
    linkedLabel?: string | null;
    surface?: ChatSurface;
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
    if (options?.initialPrompt) this.initialPromptRevision.update((revision) => revision + 1);
    this.autoStartVoiceLoop.set(!!options?.autoStartVoiceLoop);
    this.sessionId.set(options?.sessionId ?? null);
    this.linkedLabel.set(options?.linkedLabel ?? null);
    this.surface.set(options?.surface ?? (isWorkUrl(this.router?.url) ? 'work' : 'cockpit'));
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
    this.sessionId.set(null);
    this.linkedLabel.set(null);
    this.proofOpen.set(false);
    this.proofAnimate.set(false);
    this.surface.set('cockpit');
  }

  toggle(): void {
    if (this.isOpen()) this.close();
    else this.open();
  }
}
