import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { CanonicalApiService, Run } from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  KbdComponent,
  LiveDotComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import { SystemsStore, SystemAgent } from './systems.store';

interface AgentStats {
  runs: number;
  avgLatency: number;
  lastRun: string | null;
}

interface Template {
  id: string;
  label: string;
  description: string;
  prompt: string;
}

/**
 * Systems grid — catalog of every System deployed in the workspace.
 * Cockpit-grade: eyebrow + title + description via PageFrame, quick-start
 * composer on top, grid of mono-labeled cards below. No legacy section header.
 */
@Component({
  selector: 'app-systems-grid',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    FormsModule,
    PageFrameComponent,
    GlyphComponent,
    KbdComponent,
    LiveDotComponent,
    StatReadoutComponent,
    TagComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Build · Systems"
      title="Your deployed systems"
      description="Each System is a composition of a Capability, a Context and a Policy. Launch one from scratch or start from a goal."
      [status]="agents().length + ' ACTIVE'"
    >
      <a
        actions
        routerLink="/systems/new"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
        [style.padding]="'6px 12px'"
        [style.height.px]="28"
        [style.background]="'var(--ck-signal-cool)'"
        [style.color]="'var(--ck-on-signal)'"
        [style.border]="'none'"
        [style.borderRadius.px]="4"
        [style.fontFamily]="'var(--ck-font-mono)'"
        [style.fontSize.px]="11"
        [style.fontWeight]="600"
        [style.letterSpacing]="'0.08em'"
        [style.textTransform]="'uppercase'"
        [style.cursor]="'pointer'"
        [style.textDecoration]="'none'"
      >
        <ck-glyph name="bolt" [size]="12" />
        New system
      </a>

      <!-- Quick-start composer -->
      <section
        class="ck-hero-ambient"
        [style.position]="'relative'"
        [style.padding]="'22px 24px'"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="6"
        [style.marginBottom.px]="24"
      >
        <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="10" [style.marginBottom.px]="12">
          <span class="ck-label" [style.color]="'var(--ck-signal-cool)'">QUICK START</span>
          <ck-live-dot tone="cool" />
        </div>
        <h2
          [style.fontFamily]="'var(--ck-font-sans)'"
          [style.fontSize.px]="20"
          [style.fontWeight]="500"
          [style.letterSpacing]="'-0.01em'"
          [style.color]="'var(--ck-fg-1)'"
          [style.margin]="'0 0 6px 0'"
          [style.maxWidth.ch]="64"
        >What would you like your AI team to achieve today?</h2>
        <p [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="12" [style.margin]="'0 0 14px 0'" [style.maxWidth.ch]="72">
          Describe a goal and we'll compose a Capability, Context and Policy around it.
        </p>

        <form (ngSubmit)="startFromPrompt()" [style.display]="'flex'" [style.gap.px]="8" [style.maxWidth.px]="720">
          <div [style.position]="'relative'" [style.flex]="'1 1 auto'">
            <span [style.position]="'absolute'" [style.left.px]="10" [style.top.px]="9" [style.pointerEvents]="'none'" [style.color]="'var(--ck-signal-cool)'">
              <ck-glyph name="focus" [size]="14" />
            </span>
            <input
              type="text"
              [(ngModel)]="prompt"
              name="prompt"
              [style.width]="'100%'"
              [style.padding]="'8px 12px 8px 32px'"
              [style.height.px]="32"
              [style.background]="'var(--ck-bg-inset)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="4"
              [style.color]="'var(--ck-fg-1)'"
              [style.fontSize.px]="13"
              placeholder="Summarise incoming contracts and flag risks…"
            />
          </div>
          <button
            type="submit"
            [disabled]="!prompt.trim()"
            [style.padding]="'0 14px'"
            [style.height.px]="32"
            [style.background]="'var(--ck-signal-cool)'"
            [style.color]="'var(--ck-on-signal)'"
            [style.border]="'none'"
            [style.borderRadius.px]="4"
            [style.fontFamily]="'var(--ck-font-mono)'"
            [style.fontSize.px]="11"
            [style.fontWeight]="600"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
            [style.cursor]="prompt.trim() ? 'pointer' : 'not-allowed'"
            [style.opacity]="prompt.trim() ? 1 : 0.4"
          >Compose</button>
        </form>

        <div [style.display]="'flex'" [style.flexWrap]="'wrap'" [style.gap.px]="6" [style.marginTop.px]="14">
          @for (tpl of templates; track tpl.id) {
            <button
              type="button"
              (click)="applyTemplate(tpl)"
              [style.padding]="'3px 10px'"
              [style.background]="'transparent'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="99"
              [style.color]="'var(--ck-fg-3)'"
              [style.fontFamily]="'var(--ck-font-mono)'"
              [style.fontSize.px]="10"
              [style.letterSpacing]="'0.08em'"
              [style.textTransform]="'uppercase'"
              [style.cursor]="'pointer'"
              [title]="tpl.description"
            >{{ tpl.label }}</button>
          }
        </div>
      </section>

      <!-- Grid header -->
      <div [style.display]="'flex'" [style.alignItems]="'center'" [style.justifyContent]="'space-between'" [style.marginBottom.px]="12">
        <span class="ck-label">SYSTEMS · {{ agents().length }}</span>
        <span class="ck-mono" [style.fontSize.px]="10" [style.color]="'var(--ck-fg-4)'" [style.letterSpacing]="'0.10em'">
          <ck-kbd>⌘K</ck-kbd> to navigate
        </span>
      </div>

      @if (store.loading()) {
        <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(auto-fill, minmax(320px, 1fr))'" [style.gap.px]="12">
          @for (_ of [0, 1, 2, 3, 4, 5]; track $index) {
            <div
              [style.height.px]="160"
              [style.background]="'var(--ck-bg-panel)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="6"
              [style.opacity]="0.5"
            ></div>
          }
        </div>
      } @else if (agents().length === 0) {
        <div
          [style.padding]="'48px 32px'"
          [style.background]="'var(--ck-bg-panel)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="6"
          [style.textAlign]="'center'"
        >
          <div [style.display]="'inline-flex'" [style.color]="'var(--ck-signal-cool)'"><ck-glyph name="cube" [size]="24" /></div>
          <h3
            [style.fontFamily]="'var(--ck-font-sans)'"
            [style.fontSize.px]="18"
            [style.fontWeight]="500"
            [style.color]="'var(--ck-fg-1)'"
            [style.margin]="'12px 0 6px 0'"
          >No systems yet</h3>
          <p [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="13" [style.margin]="'0 auto 18px'" [style.maxWidth.ch]="54">
            Your first AI system is just a prompt away. Compose one from scratch or pick a template above.
          </p>
          <a
            routerLink="/systems/new"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="6"
            [style.padding]="'6px 14px'"
            [style.height.px]="30"
            [style.background]="'var(--ck-signal-cool)'"
            [style.color]="'var(--ck-on-signal)'"
            [style.borderRadius.px]="4"
            [style.fontFamily]="'var(--ck-font-mono)'"
            [style.fontSize.px]="11"
            [style.fontWeight]="600"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
            [style.textDecoration]="'none'"
          >
            <ck-glyph name="bolt" [size]="12" />
            Create your first system
          </a>
        </div>
      } @else {
        <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(auto-fill, minmax(340px, 1fr))'" [style.gap.px]="12">
          @for (agent of agents(); track agent.id) {
            <a
              [routerLink]="[agent.id]"
              [style.position]="'relative'"
              [style.display]="'flex'"
              [style.flexDirection]="'column'"
              [style.gap.px]="12"
              [style.padding]="'16px'"
              [style.background]="'var(--ck-bg-panel)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="6"
              [style.color]="'inherit'"
              [style.textDecoration]="'none'"
              [style.transition]="'border-color 120ms var(--ck-ease-out), transform 120ms'"
              onmouseover="this.style.borderColor='var(--ck-stroke-3)'"
              onmouseout="this.style.borderColor='var(--ck-stroke-2)'"
            >
              <div [style.display]="'flex'" [style.alignItems]="'flex-start'" [style.gap.px]="10">
                <div
                  [style.width.px]="32"
                  [style.height.px]="32"
                  [style.flex]="'0 0 32px'"
                  [style.borderRadius.px]="4"
                  [style.background]="'var(--ck-bg-inset)'"
                  [style.border]="'1px solid var(--ck-stroke-2)'"
                  [style.display]="'inline-flex'"
                  [style.alignItems]="'center'"
                  [style.justifyContent]="'center'"
                  [style.color]="'var(--ck-signal-cool)'"
                >
                  <ck-glyph name="cube" [size]="16" />
                </div>
                <div [style.flex]="'1 1 auto'" [style.minWidth.px]="0">
                  <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8">
                    <span
                      [style.fontFamily]="'var(--ck-font-sans)'"
                      [style.fontSize.px]="14"
                      [style.fontWeight]="500"
                      [style.color]="'var(--ck-fg-1)'"
                      [style.overflow]="'hidden'"
                      [style.textOverflow]="'ellipsis'"
                      [style.whiteSpace]="'nowrap'"
                    >{{ agent.name }}</span>
                    @if (agent.draft) {
                      <ck-tag tone="warn" variant="outline">DRAFT</ck-tag>
                    } @else {
                      <ck-live-dot tone="pos" />
                    }
                  </div>
                  <p
                    [style.fontSize.px]="11"
                    [style.color]="'var(--ck-fg-3)'"
                    [style.margin]="'4px 0 0 0'"
                    [style.lineHeight]="1.5"
                    [style.display]="'-webkit-box'"
                    [style.overflow]="'hidden'"
                    style="-webkit-line-clamp: 2; -webkit-box-orient: vertical;"
                  >{{ agent.description || 'No description yet.' }}</p>
                </div>
              </div>

              <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(3, 1fr)'" [style.gap.px]="8" [style.paddingTop.px]="12" [style.borderTop]="'1px solid var(--ck-stroke-1)'">
                <ck-stat-readout label="RUNS"   [value]="statsFor(agent.id).runs > 0 ? statsFor(agent.id).runs.toString() : '—'" tone="cool" [size]="14" />
                <ck-stat-readout label="AVG MS" [value]="statsFor(agent.id).avgLatency > 0 ? statsFor(agent.id).avgLatency.toString() : '—'" tone="pos" [size]="14" />
                <ck-stat-readout label="LAST"   [value]="statsFor(agent.id).lastRun ?? '—'" tone="violet" [size]="14" />
              </div>

              <div [style.display]="'flex'" [style.alignItems]="'center'" [style.justifyContent]="'space-between'">
                <ck-tag tone="cool" variant="soft">
                  {{ agent.rag_mode || 'OmniRAG' }}
                </ck-tag>
                <span [style.color]="'var(--ck-fg-4)'">
                  <ck-glyph name="arrow-right" [size]="12" />
                </span>
              </div>
            </a>
          }
        </div>
      }
    </ck-page-frame>
  `,
})
export class SystemsGridComponent implements OnInit {
  protected readonly store = inject(SystemsStore);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);

  prompt = '';
  private readonly runs = signal<Run[]>([]);

  readonly statsByAgent = computed<Record<string, AgentStats>>(() => {
    const out: Record<string, AgentStats> = {};
    for (const r of this.runs()) {
      const id = r.system_id ?? '';
      if (!id) continue;
      const cur = out[id] ?? { runs: 0, avgLatency: 0, lastRun: null };
      cur.runs += 1;
      if (r.duration_ms) {
        cur.avgLatency =
          cur.runs === 1
            ? Math.round(r.duration_ms)
            : Math.round(((cur.avgLatency * (cur.runs - 1)) + r.duration_ms) / cur.runs);
      }
      const ts = r.ended_at ?? r.started_at ?? null;
      if (ts && (!cur.lastRun || ts > cur.lastRun)) cur.lastRun = ts;
      out[id] = cur;
    }
    return out;
  });

  statsFor(id: string): AgentStats {
    const s = this.statsByAgent()[id];
    if (!s) return { runs: 0, avgLatency: 0, lastRun: null };
    return { ...s, lastRun: s.lastRun ? this.formatRelative(s.lastRun) : null };
  }

  private formatRelative(iso: string): string {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '';
    const diff = Date.now() - t;
    const minute = 60_000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (diff < minute) return 'now';
    if (diff < hour) return Math.round(diff / minute) + 'm';
    if (diff < day) return Math.round(diff / hour) + 'h';
    return Math.round(diff / day) + 'd';
  }

  readonly agents = this.store.systems;

  readonly templates: Template[] = [
    { id: 'contract',   label: 'Contract Analysis', description: 'Flag risky clauses in contracts',       prompt: 'Analyze contracts and flag risk clauses' },
    { id: 'support',    label: 'Customer Support',  description: 'Answer questions from your docs',        prompt: 'Answer customer questions from docs' },
    { id: 'code',       label: 'Code Review',       description: 'Review PRs for bugs and style',          prompt: 'Review pull requests for bugs and style' },
    { id: 'research',   label: 'Market Research',   description: 'Synthesize competitor intel',            prompt: 'Synthesize competitor intelligence' },
    { id: 'onboarding', label: 'HR Onboarding',     description: 'Guide new hires in the first weeks',     prompt: 'Guide new hires through their first weeks' },
    { id: 'insights',   label: 'Data Insights',     description: 'Extract KPIs from CSVs',                 prompt: 'Extract KPIs from CSVs and reports' },
  ];

  ngOnInit(): void {
    this.store.load().subscribe();
    // Canonical `/runs` — the legacy `/traces/traces` alias is deprecated.
    this.canonical.listRuns().subscribe({
      next: (rows) => this.runs.set(rows ?? []),
      error: () => this.runs.set([]),
    });
  }

  applyTemplate(tpl: Template): void {
    this.prompt = tpl.prompt;
  }

  startFromPrompt(): void {
    const p = this.prompt.trim();
    if (!p) return;
    this.router.navigate(['/systems/new'], {
      queryParams: {
        prompt: p,
        name: this.suggestNameFromPrompt(p),
      },
    });
  }

  private suggestNameFromPrompt(p: string): string {
    const words = p.replace(/[^a-zA-Z0-9\s]/g, '').trim().split(/\s+/).slice(0, 4);
    if (words.length === 0) return 'New system';
    return words
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  }

  agentIcon(agent: SystemAgent): string {
    // Legacy helper, retained for back-compat with any remaining callers; the
    // grid now renders a single canonical glyph.
    return 'cube';
  }
}
