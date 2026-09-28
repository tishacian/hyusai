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
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import {
  composePaletteResults,
  frenchElides,
  lexiconMatches,
  type LexiconMatch,
  type PaletteLocale,
} from './command-palette.intent';

type Tone = 'pos' | 'cool' | 'violet' | 'warn' | 'neg';

interface CommandItem {
  id: string;
  label: string;
  hint: string;
  tone: Tone;
  kind: 'view' | 'system' | 'capability' | 'run' | 'skill' | 'action' | 'chat' | 'agent' | 'definition';
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
 *
 * L27 — entry by intention: a query nothing matches becomes « Ask the
 * agent », selected so Enter opens the chat prefilled (never sent); a query
 * naming a lexicon term shows « What is {term}? » with the definition in
 * place. ARIA 1.2 combobox + listbox, polite result count, no animation.
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
        <!-- Raycast-style: no open/close animation, no row transition (L27). -->
        <div
          role="dialog"
          aria-modal="true"
          [attr.aria-label]="i18n.t('titlebar.palette')"
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
          <!-- Input: an ARIA 1.2 combobox; focus never leaves it. -->
          <div
            [style.display]="'flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="12"
            [style.padding]="'14px 18px'"
            [style.borderBottom]="'1px solid var(--ck-hair)'"
          >
            <span aria-hidden="true" [style.display]="'inline-flex'"><ck-glyph name="focus" [size]="14" /></span>
            <input
              #queryInput
              type="search"
              class="ck-palette-input"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded="true"
              [attr.aria-controls]="listboxId"
              [attr.aria-activedescendant]="activeDescendant()"
              [attr.aria-label]="i18n.t('palette.input.label')"
              [value]="query()"
              (input)="onQuery($event)"
              (keydown)="onKey($event)"
              [placeholder]="i18n.t('palette.placeholder')"
              [style.flex]="'1 1 auto'"
              [style.minWidth]="'0'"
              [style.background]="'transparent'"
              [style.border]="'0'"
              [style.outline]="'none'"
              [style.fontFamily]="'var(--ck-font-sans)'"
              [style.fontSize.px]="14"
              [style.color]="'var(--ck-fg-1)'"
              autocomplete="off"
              spellcheck="false"
            />
            <span aria-hidden="true"><ck-kbd>ESC</ck-kbd></span>
          </div>

          @if (noMatch()) {
            <p
              data-testid="palette-no-match"
              [style.margin]="'0'"
              [style.padding]="'10px 18px 4px'"
              [style.fontSize.px]="12"
              [style.color]="'var(--ck-fg-3)'"
            >{{ loading() ? i18n.t('common.loading') : i18n.t('palette.empty.query', { query: trimmedQuery() }) }}</p>
          }

          <!-- Results -->
          <div
            role="listbox"
            [id]="listboxId"
            [attr.aria-label]="i18n.t('palette.results.label')"
            class="ck-scroll"
            [style.maxHeight.px]="360"
            [style.overflow]="'auto'"
          >
            @for (r of results(); track r.id; let i = $index) {
              <div
                role="option"
                [id]="optionId(i)"
                [attr.aria-selected]="selectedIndex() === i ? 'true' : 'false'"
                [attr.data-kind]="r.kind"
                (click)="go(r)"
                (mousemove)="hover(i)"
                [style.display]="'grid'"
                [style.gridTemplateColumns]="'24px 1fr auto'"
                [style.gap.px]="12"
                [style.alignItems]="'center'"
                [style.minHeight.px]="44"
                [style.padding]="'10px 18px'"
                [style.borderBottom]="'1px solid var(--ck-hair)'"
                [style.boxShadow]="selectedIndex() === i ? 'inset 2px 0 0 var(--ck-primary)' : 'none'"
                [style.background]="selectedIndex() === i ? 'var(--ck-bg-inset)' : 'transparent'"
                [style.cursor]="'pointer'"
              >
                <span aria-hidden="true" [style.display]="'inline-flex'"><ck-glyph [name]="glyphFor(r.kind)" [size]="14" /></span>
                <div [style.display]="'flex'" [style.flexDirection]="'column'" [style.gap.px]="2" [style.minWidth]="0">
                  <span
                    [style.fontSize.px]="13"
                    [style.color]="'var(--ck-fg-1)'"
                    [style.fontWeight]="'500'"
                    [style.whiteSpace]="r.kind === 'agent' ? 'normal' : 'nowrap'"
                    [style.overflow]="'hidden'"
                    [style.textOverflow]="'ellipsis'"
                    [style.overflowWrap]="'anywhere'"
                  >{{ r.label }}</span>
                  <span
                    [style.fontSize.px]="12"
                    [style.lineHeight]="'1.4'"
                    [style.color]="'var(--ck-fg-3)'"
                    [style.whiteSpace]="r.kind === 'definition' ? 'normal' : 'nowrap'"
                    [style.overflow]="'hidden'"
                    [style.textOverflow]="'ellipsis'"
                  >{{ r.hint }}</span>
                </div>
                <ck-tag [tone]="r.tone" variant="outline">{{ kindLabel(r.kind) }}</ck-tag>
              </div>
            }
          </div>

          <p class="ck-palette-status" role="status" aria-atomic="true">{{ announcement() }}</p>

          <!-- Footer hint -->
          <div
            aria-hidden="true"
            [style.display]="'flex'"
            [style.alignItems]="'center'"
            [style.justifyContent]="'space-between'"
            [style.gap.px]="12"
            [style.padding]="'10px 18px'"
            [style.fontSize.px]="12"
            [style.color]="'var(--ck-fg-3)'"
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
  styles: [`
    /* The native clear cross is off-brand blue and duplicates Escape. */
    .ck-palette-input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
    .ck-palette-status {
      position: absolute;
      width: 1px;
      height: 1px;
      margin: -1px;
      padding: 0;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
      border: 0;
    }
  `],
})
export class CommandPaletteComponent implements OnInit, OnDestroy {
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly chatOverlay = inject(ChatOverlayService);
  private readonly workspace = inject(WorkspaceService);
  private readonly navigation = inject(ZoomContextService);
  private readonly telemetry = inject(NavigationTelemetryService, { optional: true });
  protected readonly i18n = inject(I18nService);

  readonly open = signal(false);
  readonly query = signal('');
  readonly loading = signal(false);
  readonly selectedIndex = signal(0);
  readonly listboxId = 'ck-palette-listbox';
  private returnFocus: HTMLElement | null = null;

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
    { id: 'theme.presentation', label: this.i18n.t('palette.theme.presentation'), hint: this.i18n.t('palette.theme.presentation.hint'), tone: 'pos', kind: 'view', route: `${agentiumSurfaceRoute('hypervisor')}?theme=presentation`, keywords: 'presentation theme present impact sentinel mission' },
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
    if (this.workspace.experienceStudioV1Enabled()) {
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

  private readonly matches = computed(() => {
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
    if (!q) return all;
    return all.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        c.hint.toLowerCase().includes(q) ||
        c.keywords.includes(q),
    );
  });

  readonly trimmedQuery = computed(() => this.query().trim());

  /** A typed query that no command matches — the agent takes over. */
  readonly noMatch = computed(() => this.trimmedQuery().length > 0 && this.matches().length === 0);

  readonly results = computed(() => {
    const query = this.trimmedQuery();
    const definitions = query
      ? lexiconMatches(query, this.locale()).map((match) => this.definitionCommand(match))
      : [];
    return composePaletteResults(
      query,
      this.matches(),
      definitions,
      query ? this.askAgentCommand(query) : null,
    );
  });

  readonly activeDescendant = computed(() =>
    this.results().length ? this.optionId(Math.min(this.selectedIndex(), this.results().length - 1)) : null,
  );

  /** Polite, only once the reader types: count, or how to reach the agent. */
  readonly announcement = computed(() => {
    if (!this.trimmedQuery() || this.loading()) return '';
    if (this.noMatch()) return this.i18n.t('palette.announce.fallback');
    return this.i18n.t('palette.footer.results', { count: this.results().length });
  });

  private locale(): PaletteLocale {
    return this.i18n.locale?.() === 'en' ? 'en' : 'fr';
  }

  private askAgentCommand(query: string): CommandItem {
    return {
      id: 'agent.ask',
      label: this.i18n.t('palette.ask_agent', { query }),
      hint: this.i18n.t('palette.ask_agent.hint'),
      tone: 'pos',
      kind: 'agent',
      route: '',
      keywords: '',
      action: () => this.openChat({ mode: 'quick', initialPrompt: query }),
    };
  }

  /**
   * « What is {term}? »: the definition is the secondary line, so the answer
   * is read without leaving the palette; Enter asks the agent for more, with
   * the question prefilled and not sent.
   */
  private definitionCommand(match: LexiconMatch): CommandItem {
    const elided = this.locale() === 'fr' && frenchElides(match.term);
    const suffix = elided ? '.elided' : '';
    return {
      id: `define.${match.id}`,
      label: this.i18n.t(`palette.what_is${suffix}`, { term: match.term }),
      hint: match.definition,
      tone: 'cool',
      kind: 'definition',
      route: '',
      keywords: '',
      action: () => this.openChat({
        mode: 'quick',
        initialPrompt: this.i18n.t(`palette.what_is.prompt${suffix}`, { term: match.term }),
      }),
    };
  }

  optionId(index: number): string {
    return `ck-palette-option-${index}`;
  }

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
    // A workspace switch navigates; focus follows the new page, not the opener.
    this.close(false);
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
    if (this.open()) {
      this.close();
      return;
    }
    this.returnFocus = typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    this.open.set(true);
    this.query.set('');
    this.selectedIndex.set(0);
    setTimeout(() => {
      const el = document.querySelector<HTMLInputElement>('app-command-palette input[type="search"]');
      el?.focus();
    }, 20);
  }

  /** Closing by Escape, backdrop or ⌘K gives focus back to the opener. */
  close(restoreFocus = true): void {
    const wasOpen = this.open();
    this.open.set(false);
    const target = this.returnFocus;
    this.returnFocus = null;
    if (wasOpen && restoreFocus && target?.isConnected) target.focus();
  }

  onQuery(ev: Event): void {
    this.query.set((ev.target as HTMLInputElement).value);
  }

  onKey(ev: KeyboardEvent): void {
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      this.selectedIndex.update((i) => Math.min(this.results().length - 1, i + 1));
      this.revealSelected();
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      this.selectedIndex.update((i) => Math.max(0, i - 1));
      this.revealSelected();
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      const r = this.results()[this.selectedIndex()];
      if (r) this.go(r);
    } else if (ev.key === 'Tab') {
      // The combobox is the dialog's only stop; Escape leaves (shown as ESC).
      ev.preventDefault();
    }
  }

  /** Pointer selection follows real movement only, not a list scrolling under it. */
  hover(index: number): void {
    if (this.selectedIndex() !== index) this.selectedIndex.set(index);
  }

  private revealSelected(): void {
    if (typeof document === 'undefined') return;
    document.getElementById(this.optionId(this.selectedIndex()))?.scrollIntoView({ block: 'nearest' });
  }

  go(r: CommandItem): void {
    // Navigation focuses the page title and the chat focuses itself.
    this.close(false);
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
    this.telemetry?.registerTrigger('palette');
    this.router.navigateByUrl(r.route);
  }

  glyphFor(kind: CommandItem['kind']): 'flow' | 'cube' | 'sliders' | 'bolt' | 'focus' | 'pulse' | 'orbit' | 'ledger' {
    switch (kind) {
      case 'agent':      return 'orbit';
      case 'definition': return 'ledger';
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
