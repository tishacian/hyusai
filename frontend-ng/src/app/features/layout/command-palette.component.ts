import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  OnDestroy,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Run,
  type Skill,
  type System,
} from '@app/core/canonical-api.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { GlyphComponent, KbdComponent, TagComponent } from '@app/shared/cockpit';
import { agentiumSurfaceRoute } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';

type Tone = 'pos' | 'cool' | 'violet' | 'warn' | 'neg';

interface CommandItem {
  id: string;
  label: string;
  hint: string;
  tone: Tone;
  kind: 'view' | 'system' | 'capability' | 'run' | 'skill' | 'action' | 'chat';
  route: string;
  fragment?: string;
  keywords: string;
  /**
   * Optional imperative action triggered instead of navigating. Used by the
   * chat commands (Vague D / D0) which open the global overlay rather than
   * pushing a route.
   */
  action?: () => void;
  /** Workspace generation that produced a tenant-owned catalog item. */
  workspaceEpoch?: number;
}

/**
 * Global ⌘K command palette — lets the user fuzzy-jump into any
 * view, system, capability, run or skill. Mirrors the "Semantic Zoom"
 * entry point from the mockup and is the single interaction the
 * cockpit exposes for navigation across hierarchies.
 */
@Component({
  selector: 'app-command-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, KbdComponent, TagComponent],
  template: `
    @if (open()) {
      <div
        (click)="close()"
        [style.position]="'fixed'"
        [style.inset]="'0'"
        [style.zIndex]="80"
        [style.background]="'rgba(2, 6, 23, 0.74)'"
        [style.backdropFilter]="'blur(14px) saturate(120%)'"
        style="-webkit-backdrop-filter: blur(14px) saturate(120%);"
      >
        <div
          (click)="$event.stopPropagation()"
          [style.position]="'absolute'"
          [style.top.px]="120"
          [style.left]="'50%'"
          [style.transform]="'translateX(-50%)'"
          [style.width.px]="620"
          [style.maxWidth]="'92vw'"
          [style.background]="'var(--ck-bg-surface)'"
          [style.border]="'1px solid var(--ck-stroke-strong)'"
          [style.borderRadius.px]="10"
          [style.boxShadow]="'0 30px 80px rgba(2,6,23,0.6), 0 0 0 1px var(--ck-stroke-soft)'"
          [style.overflow]="'hidden'"
        >
          <!-- Input -->
          <div
            [style.display]="'flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="12"
            [style.padding]="'14px 18px'"
            [style.borderBottom]="'1px solid var(--ck-hair)'"
          >
            <ck-glyph name="focus" [size]="14" />
            <input
              #queryInput
              type="search"
              [value]="query()"
              (input)="onQuery($event)"
              (keydown)="onKey($event)"
              [placeholder]="i18n.t('palette.placeholder')"
              class="ck-mono"
              [style.flex]="'1 1 auto'"
              [style.background]="'transparent'"
              [style.border]="'0'"
              [style.outline]="'none'"
              [style.fontSize.px]="13"
              [style.color]="'var(--ck-fg-1)'"
              autocomplete="off"
            />
            <ck-kbd>ESC</ck-kbd>
          </div>

          <!-- Results -->
          <div class="ck-scroll" [style.maxHeight.px]="360" [style.overflow]="'auto'">
            @if (!results().length) {
              <div
                class="ck-mono"
                [style.padding]="'28px'"
                [style.textAlign]="'center'"
                [style.color]="'var(--ck-fg-4)'"
                [style.fontSize.px]="11"
                [style.letterSpacing]="'0.14em'"
                [style.textTransform]="'uppercase'"
              >
                @if (loading()) { {{ i18n.t('common.loading') }} } @else { {{ i18n.t('palette.empty') }} · "{{ query() }}" }
              </div>
            }
            @for (r of results(); track r.id; let i = $index) {
              <button
                type="button"
                (click)="go(r)"
                (mouseenter)="selectedIndex.set(i)"
                [style.width]="'100%'"
                [style.display]="'grid'"
                [style.gridTemplateColumns]="'24px 1fr auto'"
                [style.gap.px]="12"
                [style.alignItems]="'center'"
                [style.padding]="'10px 18px'"
                [style.borderBottom]="'1px solid var(--ck-hair)'"
                [style.background]="selectedIndex() === i ? 'var(--ck-bg-inset)' : 'transparent'"
                [style.textAlign]="'left'"
                [style.cursor]="'pointer'"
                [style.transition]="'background 120ms ease'"
              >
                <ck-glyph [name]="glyphFor(r.kind)" [size]="14" />
                <div [style.display]="'flex'" [style.flexDirection]="'column'" [style.gap.px]="2" [style.minWidth]="0">
                  <span
                    [style.fontSize.px]="13"
                    [style.color]="'var(--ck-fg-1)'"
                    [style.fontWeight]="'500'"
                    [style.whiteSpace]="'nowrap'"
                    [style.overflow]="'hidden'"
                    [style.textOverflow]="'ellipsis'"
                  >{{ r.label }}</span>
                  <span
                    class="ck-mono"
                    [style.fontSize.px]="10"
                    [style.color]="'var(--ck-fg-4)'"
                    [style.whiteSpace]="'nowrap'"
                    [style.overflow]="'hidden'"
                    [style.textOverflow]="'ellipsis'"
                  >{{ r.hint }}</span>
                </div>
                <ck-tag [tone]="r.tone" variant="outline">{{ kindLabel(r.kind) }}</ck-tag>
              </button>
            }
          </div>

          <!-- Footer hint -->
          <div
            class="ck-mono"
            [style.display]="'flex'"
            [style.alignItems]="'center'"
            [style.justifyContent]="'space-between'"
            [style.padding]="'10px 18px'"
            [style.fontSize.px]="9"
            [style.letterSpacing]="'0.14em'"
            [style.textTransform]="'uppercase'"
            [style.color]="'var(--ck-fg-4)'"
            [style.background]="'var(--ck-bg-inset)'"
          >
            <span>
              <ck-kbd>↑</ck-kbd>
              <ck-kbd>↓</ck-kbd>
              {{ i18n.t('palette.footer.navigate') }}
            </span>
            <span>
              <ck-kbd>↵</ck-kbd>
              {{ i18n.t('palette.footer.open') }} · {{ i18n.t('palette.footer.results', { count: results().length }) }}
            </span>
          </div>
        </div>
      </div>
    }
  `,
})
export class CommandPaletteComponent implements OnInit, OnDestroy {
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly chatOverlay = inject(ChatOverlayService);
  private readonly workspace = inject(WorkspaceService);
  private readonly navigation = inject(ZoomContextService);
  protected readonly i18n = inject(I18nService);

  readonly open = signal(false);
  readonly query = signal('');
  readonly loading = signal(false);
  readonly selectedIndex = signal(0);

  private readonly capabilities = signal<Capability[]>([]);
  private readonly runs = signal<Run[]>([]);
  private readonly skills = signal<Skill[]>([]);
  private readonly systems = signal<System[]>([]);
  private indexSubscriptions = new Subscription();
  private refreshSubscription: Subscription | null = null;
  private indexGeneration = 0;
  private destroyed = false;
  private unregisterContextReset: () => void = () => undefined;

  private get viewCommands(): CommandItem[] {
    const commands: CommandItem[] = [
    { id: 'view.hypervisor', label: this.i18n.t('palette.view.hypervisor'), hint: this.i18n.t('palette.view.hypervisor.hint'), tone: 'cool', kind: 'view', route: agentiumSurfaceRoute('hypervisor'), keywords: 'dashboard balance overview portfolio' },
    { id: 'view.steering', label: this.i18n.t('palette.view.steering'), hint: this.i18n.t('palette.view.steering.hint'), tone: 'violet', kind: 'view', route: agentiumSurfaceRoute('steering'), keywords: 'levers policy control governance' },
    { id: 'view.review-queue', label: this.i18n.t('palette.view.review_queue'), hint: this.i18n.t('palette.view.review_queue.hint'), tone: 'warn', kind: 'view', route: agentiumSurfaceRoute('review-queue'), keywords: 'review eval evaluation queue triage hallucination threshold' },
    { id: 'view.eval-thresholds', label: this.i18n.t('palette.view.eval_thresholds'), hint: this.i18n.t('palette.view.eval_thresholds.hint'), tone: 'violet', kind: 'view', route: `${agentiumSurfaceRoute('presets')}/evaluation`, keywords: 'evaluation thresholds preset composite hallucination' },
    { id: 'view.capabilities', label: this.i18n.t('palette.view.capabilities'), hint: this.i18n.t('palette.view.capabilities.hint'), tone: 'pos', kind: 'view', route: agentiumSurfaceRoute('capabilities'), keywords: 'catalog capability marketplace' },
    { id: 'view.skills', label: this.i18n.t('palette.view.skills'), hint: this.i18n.t('palette.view.skills.hint'), tone: 'cool', kind: 'view', route: agentiumSurfaceRoute('skills'), keywords: 'skills registry atomic' },
    { id: 'view.systems', label: this.i18n.t('palette.view.systems'), hint: this.i18n.t('palette.view.systems.hint'), tone: 'cool', kind: 'view', route: agentiumSurfaceRoute('systems'), keywords: 'system composition deployments' },
    { id: 'view.knowledge', label: this.i18n.t('palette.view.knowledge'), hint: this.i18n.t('palette.view.knowledge.hint'), tone: 'violet', kind: 'view', route: agentiumSurfaceRoute('knowledge'), keywords: 'knowledge rag documents collections' },
    {
      id: 'view.expert-capture',
      label: this.i18n.t('palette.view.expert_capture'),
      hint: this.i18n.t('palette.view.expert_capture.hint'),
      tone: 'pos',
      kind: 'view',
      route: agentiumSurfaceRoute('knowledge-capture'),
      keywords: 'expert capture knowledge interview voice context capability',
    },
    { id: 'view.chat', label: this.i18n.t('palette.view.chat'), hint: this.i18n.t('palette.view.chat.hint'), tone: 'pos', kind: 'view', route: agentiumSurfaceRoute('chat'), keywords: 'chat ask question playground session test' },
    { id: 'view.observability', label: this.i18n.t('palette.view.observability'), hint: this.i18n.t('palette.view.observability.hint'), tone: 'warn', kind: 'view', route: agentiumSurfaceRoute('observability'), keywords: 'observability quality performance metrics' },
    { id: 'view.runs', label: this.i18n.t('palette.view.runs'), hint: this.i18n.t('palette.view.runs.hint'), tone: 'warn', kind: 'view', route: agentiumSurfaceRoute('runs'), keywords: 'runs traces executions logs history' },
    { id: 'action.new-system', label: this.i18n.t('palette.action.new_system'), hint: this.i18n.t('palette.action.new_system.hint'), tone: 'pos', kind: 'action', route: `${agentiumSurfaceRoute('systems')}/new`, keywords: 'create new build wizard' },
    ];
    if (this.workspace.experienceV1Enabled()) {
      commands.push(
        {
          id: 'view.create',
          label: this.i18n.t('palette.view.create'),
          hint: this.i18n.t('palette.view.create.hint'),
          tone: 'pos',
          kind: 'view',
          route: agentiumSurfaceRoute('create'),
          keywords: 'create hub studio business application experience',
        },
        {
          id: 'view.scratchpad',
          label: this.i18n.t('palette.view.scratchpad'),
          hint: this.i18n.t('palette.view.scratchpad.hint'),
          tone: 'cool',
          kind: 'view',
          route: agentiumSurfaceRoute('orchestration'),
          keywords: 'flow builder scratchpad orchestration canvas',
        },
      );
    }
    return commands;
  }

  /**
   * Drop-and-ask upload gating. Reads the per-workspace
   * `settings.features.chat_document_upload` flag (enabled by default;
   * only an explicit `false` disables it) so the palette hides the
   * `chat.drop` command when chat document upload is off.
   */
  private get chatUploadEnabled(): boolean {
    const features = this.workspace.current()?.settings?.['features'] as
      | Record<string, unknown>
      | undefined;
    return features?.['chat_document_upload'] !== false;
  }

  private get chatCommands(): CommandItem[] {
    const commands: CommandItem[] = [
      {
        id: 'chat.ask',
        label: this.i18n.t('palette.chat.ask'),
        hint: this.i18n.t('palette.chat.ask.hint'),
        tone: 'pos',
        kind: 'chat',
        route: '',
        keywords: 'ask quick question chat playground rag',
        action: () => this.openChat({ mode: 'quick' }),
      },
      {
        id: 'chat.system',
        label: this.i18n.t('palette.chat.system'),
        hint: this.i18n.t('palette.chat.system.hint'),
        tone: 'cool',
        kind: 'chat',
        route: '',
        keywords: 'chat system scoped test demo',
        action: () => this.openChat({ mode: 'system' }),
      },
    ];
    if (this.chatUploadEnabled) {
      commands.push({
        id: 'chat.drop',
        label: this.i18n.t('palette.chat.drop'),
        hint: this.i18n.t('palette.chat.drop.hint'),
        tone: 'violet',
        kind: 'chat',
        route: '',
        keywords: 'drop upload files documents ephemeral context session pdf rag',
        action: () => this.openChat({ mode: 'drop' }),
      });
    }
    return commands;
  }

  readonly results = computed(() => {
    const q = this.query().trim().toLowerCase();
    const workspaceEpoch = this.workspace.contextEpoch();
    const caps: CommandItem[] = this.capabilities().map((c) => ({
      id: `cap.${c.id}`,
      label: c.name,
      hint: `${(c.tier || 'UNIVERSAL').toUpperCase()} · ${c.skill_ids?.length || 0} skills`,
      tone: (c.tier === 'client' ? 'cool' : c.tier === 'industry' ? 'violet' : 'pos') as Tone,
      kind: 'capability',
      route: this.navigation.objectUrl('capability', c.id),
      workspaceEpoch,
      keywords: `${c.slug} ${c.industry || ''} ${c.description || ''}`.toLowerCase(),
    }));
    const sks: CommandItem[] = this.skills().map((s) => ({
      id: `sk.${s.id}`,
      label: s.name,
      hint: `${(s.certification_level || 'basic').toUpperCase()} · ${s.type || 'generic'}`,
      tone: 'cool' as Tone,
      kind: 'skill',
      route: this.navigation.objectUrl('skill', s.slug),
      workspaceEpoch,
      keywords: `${s.slug} ${s.type || ''} ${s.description || ''}`.toLowerCase(),
    }));
    const sys: CommandItem[] = this.systems().map((s) => ({
      id: `sys.${s.id}`,
      label: s.name,
      hint: `${this.i18n.t('palette.kind.system')} · ${s.status || 'draft'}`,
      tone: (s.status === 'active' ? 'pos' : 'warn') as Tone,
      kind: 'system',
      route: this.navigation.objectUrl('system', s.id),
      workspaceEpoch,
      keywords: `${s.objective || ''} ${s.status || ''}`.toLowerCase(),
    }));
    const runs: CommandItem[] = this.runs().map((run) => ({
      id: `run.${run.id}`,
      label: `Run ${run.id.slice(0, 12)}${run.id.length > 12 ? '…' : ''}`,
      hint: `${run.status.toUpperCase()} · ${this.i18n.t('palette.kind.system')} ${run.system_id}`,
      tone: (run.status === 'completed'
        ? 'pos'
        : run.status === 'failed' || run.status === 'cancelled'
          ? 'neg'
          : 'warn') as Tone,
      kind: 'run',
      route: this.navigation.objectUrl('run', run.id),
      workspaceEpoch,
      keywords: `${run.id} ${run.system_id} ${run.capability_id || ''} ${run.status}`.toLowerCase(),
    }));

    const all = [...this.chatCommands, ...this.viewCommands, ...caps, ...sys, ...runs, ...sks];
    if (!q) return all.slice(0, 40);
    return all
      .filter(
        (c) =>
          c.label.toLowerCase().includes(q) ||
          c.hint.toLowerCase().includes(q) ||
          c.keywords.includes(q),
      )
      .slice(0, 40);
  });

  constructor() {
    effect(() => {
      const _ = this.results();
      this.selectedIndex.set(0);
    });
    this.unregisterContextReset = this.workspace.registerContextReset((transition) => {
      this.resetWorkspaceIndex();
      queueMicrotask(() => {
        if (
          !this.destroyed
          && this.workspace.currentSlug() === transition.nextSlug
          && this.workspace.contextEpoch() === transition.nextEpoch
        ) {
          this.loadIndex();
        }
      });
    });
  }

  private openChat(options: Parameters<ChatOverlayService['open']>[0]): void {
    const scope = this.workspace.captureRequestScope();
    this.refreshSubscription?.unsubscribe();
    this.refreshSubscription = this.workspace.refreshCurrentWorkspace().subscribe({
      next: () => {
        if (this.workspace.isRequestScopeCurrent(scope)) this.chatOverlay.open(options);
      },
      error: () => {
        if (this.workspace.isRequestScopeCurrent(scope)) this.chatOverlay.open(options);
      },
    });
  }

  ngOnInit(): void {
    this.loadIndex();
  }

  private loadIndex(): void {
    const generation = ++this.indexGeneration;
    const scope = this.workspace.captureRequestScope();
    this.indexSubscriptions.unsubscribe();
    this.indexSubscriptions = new Subscription();
    this.loading.set(true);
    const isCurrent = () => (
      generation === this.indexGeneration
      && this.workspace.isRequestScopeCurrent(scope)
    );
    this.indexSubscriptions.add(
      this.canonical.listCapabilities().subscribe((capabilities) => {
        if (isCurrent()) this.capabilities.set(capabilities);
      }),
    );
    this.indexSubscriptions.add(
      this.canonical.listSkills().subscribe((skills) => {
        if (isCurrent()) this.skills.set(skills);
      }),
    );
    this.indexSubscriptions.add(
      this.canonical.listRuns().subscribe((runs) => {
        if (isCurrent()) this.runs.set(runs);
      }),
    );
    this.indexSubscriptions.add(
      this.canonical.listSystems().subscribe({
        next: (systems) => {
          if (!isCurrent()) return;
          this.systems.set(systems);
          this.loading.set(false);
        },
        error: () => {
          if (isCurrent()) this.loading.set(false);
        },
      }),
    );
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.unregisterContextReset();
    this.resetWorkspaceIndex();
  }

  private resetWorkspaceIndex(): void {
    this.indexGeneration += 1;
    this.indexSubscriptions.unsubscribe();
    this.indexSubscriptions = new Subscription();
    this.refreshSubscription?.unsubscribe();
    this.refreshSubscription = null;
    this.capabilities.set([]);
    this.runs.set([]);
    this.skills.set([]);
    this.systems.set([]);
    this.loading.set(false);
    this.close();
  }

  @HostListener('window:keydown', ['$event'])
  onGlobalKey(ev: KeyboardEvent): void {
    const isMod = ev.metaKey || ev.ctrlKey;
    if (isMod && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      this.toggle();
    } else if (ev.key === 'Escape' && this.open()) {
      ev.preventDefault();
      this.close();
    }
  }

  /**
   * Programmatic open hook — consumed by the side-rail footer affordance
   * ("Jump to…") which dispatches `ck:command-palette:open` on the window
   * so it does not have to duplicate the ⌘K keybinding logic.
   */
  @HostListener('window:ck:command-palette:open')
  onExternalOpen(): void {
    if (!this.open()) this.toggle();
  }

  toggle(): void {
    this.open.update((o) => !o);
    if (this.open()) {
      this.query.set('');
      this.selectedIndex.set(0);
      setTimeout(() => {
        const el = document.querySelector<HTMLInputElement>('app-command-palette input[type="search"]');
        el?.focus();
      }, 20);
    }
  }

  close(): void {
    this.open.set(false);
  }

  onQuery(ev: Event): void {
    this.query.set((ev.target as HTMLInputElement).value);
  }

  onKey(ev: KeyboardEvent): void {
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      this.selectedIndex.update((i) => Math.min(this.results().length - 1, i + 1));
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      this.selectedIndex.update((i) => Math.max(0, i - 1));
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      const r = this.results()[this.selectedIndex()];
      if (r) this.go(r);
    }
  }

  go(r: CommandItem): void {
    this.close();
    if (
      r.workspaceEpoch !== undefined
      && r.workspaceEpoch !== this.workspace.contextEpoch()
    ) {
      return;
    }
    if (r.action) {
      r.action();
      return;
    }
    this.router.navigateByUrl(r.route);
  }

  glyphFor(kind: CommandItem['kind']): 'flow' | 'cube' | 'sliders' | 'bolt' | 'focus' | 'pulse' {
    switch (kind) {
      case 'system':     return 'flow';
      case 'capability': return 'cube';
      case 'run':        return 'pulse';
      case 'skill':      return 'sliders';
      case 'action':     return 'bolt';
      case 'chat':       return 'pulse';
      case 'view':
      default:           return 'focus';
    }
  }

  kindLabel(kind: CommandItem['kind']): string {
    if (kind === 'run') return this.i18n.t('palette.view.runs').toUpperCase();
    return this.i18n.t(`palette.kind.${kind}`).toUpperCase();
  }
}
