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
  type WritableSignal,
} from '@angular/core';
import { Router } from '@angular/router';
import { Observable, Subscription, map, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { NavigationResolverService } from '@app/core/navigation-resolver.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { STRICT, readFailure, settleRead, type LoadState } from '@app/shared/ui/load-state';
import { catalogLaunchHref, workIdentity, type WorkCatalogItem } from '@app/features/experience/work/work-catalog';
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
  kind: 'view' | 'application' | 'document' | 'collection' | 'connection' | 'system' | 'capability' | 'run' | 'skill' | 'action' | 'chat' | 'agent' | 'definition';
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

interface NavigationSearchResult {
  kind: 'document' | 'collection' | 'connection';
  id: string;
  label: string;
  hint: string;
  route: string;
  workspace: { id: string; slug: string; name: string };
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
  imports: [GlyphComponent, KbdComponent, TagComponent, EmptyStateComponent],
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
          (keydown)="trapFocus($event)"
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

          <label class="ck-palette-filter">
            {{ i18n.t('palette.filter.label') }}
            <select [value]="kindFilter()" (change)="setKindFilter($event)" data-testid="palette-kind-filter">
              <option value="all">{{ i18n.t('palette.filter.all') }}</option>
              @for (kind of filterKinds; track kind) {
                <option [value]="kind">{{ kindLabel(kind) }}</option>
              }
            </select>
          </label>
          @if (searchFailure(); as state) {
            <app-empty-state [state]="state" size="sm" (retry)="loadIndex()" />
          } @else if (filteredOut()) {
            <p class="ck-palette-filter" data-testid="palette-filtered-out">{{ i18n.t('palette.filter.hidden') }}</p>
          } @else if (noMatch()) {
            <p
              data-testid="palette-no-match"
              [style.margin]="'0'"
              [style.padding]="'10px 18px 4px'"
              [style.fontSize.px]="12"
              [style.color]="'var(--ck-fg-3)'"
            >{{ i18n.t('palette.empty.query', { query: trimmedQuery() }) }}</p>
          }
          @if (searchLoading()) { <p class="ck-palette-filter" role="status">{{ i18n.t('common.loading') }}</p> }

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
                  >{{ r.hint }}@if (r.workspaceEpoch !== undefined) { · {{ workspaceLabel() }} }</span>
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
    .ck-palette-filter { display: flex; align-items: center; gap: 12px; margin: 0; padding: 8px 18px; color: var(--ck-fg-3); font-size: 12px; }
    .ck-palette-filter select { min-width: 0; max-width: 60%; color: var(--ck-fg-1); background: var(--ck-bg-inset); border: 1px solid var(--ck-stroke-2); padding: 4px; }
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
  private readonly api = inject(ApiService);
  private readonly resolver = inject(NavigationResolverService, { optional: true });
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
  readonly indexFailure = signal<LoadState<unknown> | null>(null);
  private readonly remoteFailure = signal<LoadState<unknown> | null>(null);
  private readonly remoteLoading = signal(false);
  private readonly remoteResults = signal<NavigationSearchResult[]>([]);
  readonly searchFailure = computed(() => this.indexFailure() ?? this.remoteFailure());
  readonly searchLoading = computed(() => this.loading() || this.remoteLoading());
  readonly kindFilter = signal('all');
  readonly filterKinds: CommandItem['kind'][] = ['application', 'system', 'capability', 'run', 'skill', 'document', 'collection', 'connection'];
  readonly workspaceLabel = computed(() => this.workspace.current()?.name || this.workspace.currentSlug() || '');
  readonly selectedIndex = signal(0);
  readonly listboxId = 'ck-palette-listbox';
  private returnFocus: HTMLElement | null = null;

  private readonly capabilities = signal<Capability[]>([]);
  private readonly runs = signal<Run[]>([]);
  private readonly skills = signal<Skill[]>([]);
  private readonly systems = signal<System[]>([]);
  private readonly applications = signal<WorkCatalogItem[]>([]);
  private indexSubscriptions = new Subscription();
  private refreshSubscription: Subscription | null = null;
  private indexGeneration = 0;
  private destroyed = false;
  private unregisterContextReset: () => void = () => undefined;
  private remoteGeneration = 0;
  private remoteSubscription: Subscription | null = null;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

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

  private readonly unfilteredMatches = computed(() => {
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

    const apps: CommandItem[] = this.applications().map((app) => ({
      id: `app.${app.experience.id}`,
      label: workIdentity(app.experience, app.release).name,
      hint: workIdentity(app.experience, app.release).description || this.i18n.t('palette.kind.application'),
      kind: 'application',
      tone: 'pos',
      route: catalogLaunchHref(app),
      keywords: app.experience.slug.toLowerCase(),
      workspaceEpoch,
    }));
    const remote: CommandItem[] = this.remoteResults().map((row) => ({
      id: `${row.kind}.${row.id}`, kind: row.kind, label: row.label, hint: row.hint,
      route: row.route, keywords: row.label.toLowerCase(), tone: 'cool', workspaceEpoch,
    }));
    const all = [...apps, ...this.chatCommands, ...this.viewCommands, ...remote, ...caps, ...sys, ...runs, ...sks]
      .filter((item) => !item.route || !this.resolver?.resolve(item.route));
    if (!q) return all;
    return all.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        c.hint.toLowerCase().includes(q) ||
        c.keywords.includes(q),
    );
  });

  readonly trimmedQuery = computed(() => this.query().trim());
  private readonly matches = computed(() => this.unfilteredMatches().filter((item) => this.kindFilter() === 'all' || item.kind === this.kindFilter()));
  readonly filteredOut = computed(() => !this.searchLoading() && !this.searchFailure() && this.kindFilter() !== 'all' && this.matches().length === 0 && this.unfilteredMatches().length > 0);

  /** A typed query that no command matches — the agent takes over. */
  readonly noMatch = computed(() => !this.searchLoading() && !this.searchFailure() && !this.filteredOut() && this.trimmedQuery().length > 0 && this.matches().length === 0);

  readonly results = computed(() => {
    const query = this.trimmedQuery();
    const definitions = query && this.kindFilter() === 'all'
      ? lexiconMatches(query, this.locale()).map((match) => this.definitionCommand(match))
      : [];
    return composePaletteResults(
      query,
      this.matches(),
      definitions,
      query && this.kindFilter() === 'all' ? this.askAgentCommand(query) : null,
    );
  });

  readonly activeDescendant = computed(() =>
    this.results().length ? this.optionId(Math.min(this.selectedIndex(), this.results().length - 1)) : null,
  );

  /** Polite, only once the reader types: count, or how to reach the agent. */
  readonly announcement = computed(() => {
    if (!this.trimmedQuery() || this.searchLoading()) return '';
    if (this.searchFailure()) return this.i18n.t('palette.load_failed');
    if (this.filteredOut()) return this.i18n.t('palette.filter.hidden');
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

  loadIndex(): void {
    const generation = ++this.indexGeneration;
    const scope = this.workspace.captureRequestScope();
    this.indexSubscriptions.unsubscribe();
    this.indexSubscriptions = new Subscription();
    this.loading.set(true);
    this.indexFailure.set(null);
    const isCurrent = () => (
      generation === this.indexGeneration
      && this.workspace.isRequestScopeCurrent(scope)
    );
    let pending = 5;
    const load = <T>(request: Observable<T[]>, target: WritableSignal<T[]>) => {
      target.set([]);
      let settled = false;
      this.indexSubscriptions.add(settleRead(request).subscribe((state) => {
        if (!isCurrent() || state.s === 'loading') return;
        if (state.s === 'ready') target.set(state.value);
        if (state.s === 'error' || state.s === 'denied') this.indexFailure.set(state);
        if (!settled) { settled = true; pending -= 1; }
        this.loading.set(pending > 0);
      }));
    };
    load(this.canonical.listCapabilities(STRICT), this.capabilities);
    load(this.canonical.listSkills(STRICT), this.skills);
    load(this.canonical.listRuns(), this.runs);
    load(this.canonical.listSystems({ ...STRICT, workspaceSlug: scope.workspaceSlug }), this.systems);
    load(this.workspace.experienceV1Enabled()
      ? this.api.get<{ experiences: WorkCatalogItem[] }>('/work', undefined, { workspaceSlug: scope.workspaceSlug }).pipe(map((result) => result.experiences ?? []))
      : of([]), this.applications);
    if (this.query().trim().length >= 2) this.scheduleSearch();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.unregisterContextReset();
    this.resetWorkspaceIndex();
  }

  private resetWorkspaceIndex(): void {
    this.clearRemoteSearch();
    this.indexGeneration += 1;
    this.indexSubscriptions.unsubscribe();
    this.indexSubscriptions = new Subscription();
    this.refreshSubscription?.unsubscribe();
    this.refreshSubscription = null;
    this.capabilities.set([]);
    this.runs.set([]);
    this.skills.set([]);
    this.systems.set([]);
    this.applications.set([]);
    this.indexFailure.set(null);
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
    this.clearRemoteSearch();
    this.kindFilter.set('all');
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
    this.scheduleSearch();
  }

  private clearRemoteSearch(): void {
    this.remoteGeneration += 1;
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = null;
    this.remoteSubscription?.unsubscribe();
    this.remoteSubscription = null;
    this.remoteResults.set([]);
    this.remoteFailure.set(null);
    this.remoteLoading.set(false);
  }

  private scheduleSearch(): void {
    this.clearRemoteSearch();
    const q = this.query().trim();
    if (q.length < 2) return;
    const generation = this.remoteGeneration;
    const scope = this.workspace.captureRequestScope();
    this.remoteLoading.set(true);
    this.searchTimer = setTimeout(() => {
      this.remoteSubscription = this.api.get<{ results: NavigationSearchResult[] }>('/navigation/search', { q, limit: '30' }, { workspaceSlug: scope.workspaceSlug }).subscribe({
        next: (result) => {
          if (generation !== this.remoteGeneration || !this.workspace.isRequestScopeCurrent(scope)) return;
          this.remoteResults.set((result.results ?? []).filter((row) => row.workspace.slug === scope.workspaceSlug));
          this.remoteLoading.set(false);
        },
        error: (error: unknown) => {
          if (generation !== this.remoteGeneration || !this.workspace.isRequestScopeCurrent(scope)) return;
          this.remoteFailure.set(readFailure(error));
          this.remoteLoading.set(false);
        },
      });
    }, 250);
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
    }
  }

  setKindFilter(event: Event): void {
    this.kindFilter.set((event.target as HTMLSelectElement).value);
  }

  trapFocus(event: KeyboardEvent): void {
    if (event.key !== 'Tab' || !(event.currentTarget instanceof HTMLElement)) return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('input, select, button:not([disabled])'));
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
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
      case 'application': return 'cube';
      case 'collection': return 'ledger';
      case 'document': return 'ledger';
      case 'connection': return 'sliders';
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
