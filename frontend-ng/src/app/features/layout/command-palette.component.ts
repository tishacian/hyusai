import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import {
  CanonicalApiService,
  type Capability,
  type Skill,
  type System,
} from '@app/core/canonical-api.service';
import { GlyphComponent, KbdComponent, TagComponent } from '@app/shared/cockpit';

type Tone = 'pos' | 'cool' | 'violet' | 'warn' | 'neg';

interface CommandItem {
  id: string;
  label: string;
  hint: string;
  tone: Tone;
  kind: 'view' | 'system' | 'capability' | 'skill' | 'action';
  route: string;
  fragment?: string;
  keywords: string;
}

/**
 * Global ⌘K command palette — lets the user fuzzy-jump into any
 * view, system, capability or skill. Mirrors the "Semantic Zoom"
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
              placeholder="Jump to capability, system, skill or view…"
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
                @if (loading()) { Indexing the cockpit… } @else { Nothing matches "{{ query() }}" }
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
                <ck-tag [tone]="r.tone" variant="outline">{{ r.kind.toUpperCase() }}</ck-tag>
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
              navigate
            </span>
            <span>
              <ck-kbd>↵</ck-kbd>
              open · {{ results().length }} results
            </span>
          </div>
        </div>
      </div>
    }
  `,
})
export class CommandPaletteComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);

  readonly open = signal(false);
  readonly query = signal('');
  readonly loading = signal(false);
  readonly selectedIndex = signal(0);

  private readonly capabilities = signal<Capability[]>([]);
  private readonly skills = signal<Skill[]>([]);
  private readonly systems = signal<System[]>([]);

  private readonly viewCommands: CommandItem[] = [
    { id: 'view.hypervisor', label: 'Hypervisor · Executive cockpit', hint: 'Portfolio balance · ROI · signals', tone: 'cool', kind: 'view', route: '/hypervisor', keywords: 'dashboard balance overview portfolio' },
    { id: 'view.steering', label: 'Steering · Control plane', hint: 'Levers · policies · simulate', tone: 'violet', kind: 'view', route: '/steering', keywords: 'levers policy control governance' },
    { id: 'view.capabilities', label: 'Capability catalog', hint: 'Universal · Industry · Client', tone: 'pos', kind: 'view', route: '/capabilities', keywords: 'catalog capability marketplace' },
    { id: 'view.skills', label: 'Skill registry', hint: 'Atomic certified skills', tone: 'cool', kind: 'view', route: '/skills', keywords: 'skills registry atomic' },
    { id: 'view.systems', label: 'Systems · Compositions', hint: 'All deployed systems', tone: 'cool', kind: 'view', route: '/systems', keywords: 'system composition deployments' },
    { id: 'view.knowledge', label: 'Knowledge base', hint: 'Contexts & collections', tone: 'violet', kind: 'view', route: '/knowledge', keywords: 'knowledge rag documents collections' },
    { id: 'view.observability', label: 'Observability', hint: 'Traces · metrics · runs', tone: 'warn', kind: 'view', route: '/observability', keywords: 'traces runs logs metrics' },
    { id: 'action.new-system', label: 'New system builder', hint: 'Objective → Capability → Context → Policy', tone: 'pos', kind: 'action', route: '/systems/new', keywords: 'create new build wizard' },
  ];

  readonly results = computed(() => {
    const q = this.query().trim().toLowerCase();
    const caps: CommandItem[] = this.capabilities().map((c) => ({
      id: `cap.${c.id}`,
      label: c.name,
      hint: `${(c.tier || 'UNIVERSAL').toUpperCase()} · ${c.skill_ids?.length || 0} skills`,
      tone: (c.tier === 'client' ? 'cool' : c.tier === 'industry' ? 'violet' : 'pos') as Tone,
      kind: 'capability',
      route: '/capabilities',
      keywords: `${c.slug} ${c.industry || ''} ${c.description || ''}`.toLowerCase(),
    }));
    const sks: CommandItem[] = this.skills().map((s) => ({
      id: `sk.${s.id}`,
      label: s.name,
      hint: `${(s.certification_level || 'basic').toUpperCase()} · ${s.type || 'generic'}`,
      tone: 'cool' as Tone,
      kind: 'skill',
      route: '/skills',
      keywords: `${s.slug} ${s.type || ''} ${s.description || ''}`.toLowerCase(),
    }));
    const sys: CommandItem[] = this.systems().map((s) => ({
      id: `sys.${s.id}`,
      label: s.name,
      hint: `System · ${s.status || 'draft'}`,
      tone: (s.status === 'active' ? 'pos' : 'warn') as Tone,
      kind: 'system',
      route: `/systems/${s.id}`,
      keywords: `${s.objective || ''} ${s.status || ''}`.toLowerCase(),
    }));

    const all = [...this.viewCommands, ...caps, ...sys, ...sks];
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
  }

  ngOnInit(): void {
    this.loadIndex();
  }

  private loadIndex(): void {
    this.loading.set(true);
    this.canonical.listCapabilities().subscribe((c) => this.capabilities.set(c));
    this.canonical.listSkills().subscribe((s) => this.skills.set(s));
    this.canonical.listSystems().subscribe((s) => {
      this.systems.set(s);
      this.loading.set(false);
    });
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
    this.router.navigateByUrl(r.route);
  }

  glyphFor(kind: CommandItem['kind']): 'flow' | 'cube' | 'sliders' | 'bolt' | 'focus' {
    switch (kind) {
      case 'system':     return 'flow';
      case 'capability': return 'cube';
      case 'skill':      return 'sliders';
      case 'action':     return 'bolt';
      case 'view':
      default:           return 'focus';
    }
  }
}
