import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { SystemsStore, SystemAgent } from './systems.store';

interface Template {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompt: string;
}

@Component({
  selector: 'app-systems-grid',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    FormsModule,
    IconComponent,
    SectionHeaderComponent,
    StatusPulseComponent,
    EmptyStateComponent,
    SkeletonComponent,
    DrawerComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Build"
      title="Systems"
      icon="layers"
      subtitle="Design, launch and monitor purpose-built AI systems."
    >
      <button
        type="button"
        (click)="openDrawer()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
      >
        <app-icon name="plus" [size]="14" /> New system
      </button>
    </app-section-header>

    <!-- Quick start hero -->
    <section
      class="relative overflow-hidden t-card t-elevated rounded-md p-6 mb-8"
      style="border-left: 3px solid var(--accent); background: linear-gradient(135deg, var(--bg-card) 0%, rgba(0,188,212,0.06) 50%, rgba(139,92,246,0.06) 100%);"
    >
      <div class="absolute -top-10 -right-10 w-48 h-48 bg-brand-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div class="absolute -bottom-12 -left-12 w-56 h-56 bg-violet-500/10 rounded-full blur-3xl pointer-events-none"></div>

      <div class="relative">
        <div class="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] font-semibold text-brand-400 mb-2">
          <app-icon name="sparkles" [size]="12" />
          Quick start
        </div>
        <h2 class="text-xl md:text-2xl font-semibold text-white leading-tight max-w-2xl">
          What would you like your AI team to achieve today?
        </h2>
        <p class="text-sm text-gray-400 mt-1.5 max-w-xl">
          Describe a goal and we'll compose agents, knowledge and orchestration around it.
        </p>

        <form (ngSubmit)="startFromPrompt()" class="mt-5 flex gap-2 max-w-2xl">
          <div class="relative flex-1">
            <app-icon
              name="wand-2"
              [size]="16"
              class="absolute left-3 top-1/2 -translate-y-1/2 text-brand-400 pointer-events-none"
            />
            <input
              type="text"
              [(ngModel)]="prompt"
              name="prompt"
              class="w-full pl-10 pr-4 py-2.5 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition"
              placeholder="Summarise incoming contracts and flag risks…"
            />
          </div>
          <button
            type="submit"
            [disabled]="!prompt.trim()"
            class="px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-600 disabled:opacity-40 text-white font-medium text-sm shadow-glow-sm transition inline-flex items-center gap-1.5"
          >
            <app-icon name="zap" [size]="14" /> Compose
          </button>
        </form>

        <div class="flex flex-wrap gap-2 mt-5">
          @for (tpl of templates; track tpl.id) {
            <button
              type="button"
              (click)="applyTemplate(tpl)"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium text-gray-300 bg-white/5 hover:bg-brand-500/10 hover:text-brand-300 ring-1 ring-white/10 hover:ring-brand-500/40 transition"
            >
              <app-icon [name]="tpl.icon" [size]="12" />
              {{ tpl.label }}
            </button>
          }
        </div>
      </div>
    </section>

    <!-- Agents grid -->
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-[0.14em]">Your systems</h2>
      <span class="text-xs text-gray-500">{{ agents().length }} total</span>
    </div>

    @if (store.loading()) {
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (_ of [0, 1, 2, 3, 4, 5]; track $index) {
          <app-skeleton height="180px" />
        }
      </div>
    } @else if (agents().length === 0) {
      <div class="t-card t-elevated rounded-md">
        <app-empty-state
          icon="layers"
          title="No systems yet"
          description="Your first AI system is just a prompt away. Compose one from scratch or pick a template above."
        >
          <button
            type="button"
            (click)="openDrawer()"
            class="inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
          >
            <app-icon name="plus" [size]="14" /> Create your first system
          </button>
        </app-empty-state>
      </div>
    } @else {
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (agent of agents(); track agent.id) {
          <a
            [routerLink]="[agent.id]"
            class="group t-card t-elevated rounded-md p-5 relative overflow-hidden hover:-translate-y-0.5 transition-transform"
          >
            @if (agent.draft) {
              <span
                class="absolute top-3 right-3 inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30"
              >
                <app-icon name="pencil" [size]="10" /> Draft
              </span>
            }
            <div class="flex items-start gap-3">
              <div
                class="w-10 h-10 rounded-md flex items-center justify-center bg-gradient-to-br from-brand-500/20 to-violet-500/20 ring-1 ring-brand-500/30 text-brand-400 shadow-glow-sm shrink-0"
              >
                <app-icon [name]="agentIcon(agent)" [size]="18" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5 pr-16">
                  <h3 class="font-semibold text-white truncate">{{ agent.name }}</h3>
                  <app-status-pulse [tone]="agent.status === 'active' ? 'success' : agent.draft ? 'warning' : 'accent'" />
                </div>
                <p class="text-xs text-gray-400 line-clamp-2 leading-relaxed">
                  {{ agent.description || 'No description yet.' }}
                </p>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-white/5">
              <div>
                <div class="text-[9px] uppercase tracking-wider text-gray-500 font-semibold">Runs</div>
                <div class="text-sm font-semibold text-white tabular-nums">{{ agent.draft ? '—' : stub(agent.id, 1) }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-wider text-gray-500 font-semibold">ROI</div>
                <div class="text-sm font-semibold text-emerald-400 tabular-nums">{{ agent.draft ? '—' : '+' + stub(agent.id, 2) + '%' }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-wider text-gray-500 font-semibold">Saved</div>
                <div class="text-sm font-semibold text-white tabular-nums">{{ agent.draft ? '—' : stub(agent.id, 3) + 'h' }}</div>
              </div>
            </div>

            <div class="mt-3 flex items-center justify-between">
              <span
                class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full bg-brand-500/10 text-brand-300 ring-1 ring-brand-500/20"
              >
                <app-icon name="database" [size]="10" />
                {{ agent.rag_mode || 'OmniRAG' }}
              </span>
              <app-icon
                name="arrow-up-right"
                [size]="14"
                class="text-gray-500 group-hover:text-brand-400 transition"
              />
            </div>
          </a>
        }
      </div>
    }

    <!-- Create drawer -->
    <app-drawer
      [open]="drawerOpen()"
      title="New system"
      subtitle="Give it a name, pick a template, refine later."
      icon="plus"
      [width]="460"
      (close)="drawerOpen.set(false)"
    >
      <form (ngSubmit)="createSystem()" class="space-y-5">
        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Name</label>
          <input
            type="text"
            [(ngModel)]="form.name"
            name="name"
            required
            class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition"
            placeholder="Contract Analyzer"
          />
        </div>

        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Description</label>
          <textarea
            [(ngModel)]="form.description"
            name="description"
            rows="2"
            class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition resize-none"
            placeholder="What does this system do in one sentence?"
          ></textarea>
        </div>

        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Template</label>
          <div class="grid grid-cols-2 gap-2">
            @for (tpl of templates; track tpl.id) {
              <button
                type="button"
                (click)="selectTemplate(tpl)"
                class="flex items-start gap-2 px-3 py-2.5 rounded border text-left transition"
                [class.border-brand-500\\/50]="form.template === tpl.id"
                [class.bg-brand-500\\/10]="form.template === tpl.id"
                [class.border-white\\/5]="form.template !== tpl.id"
                [class.bg-black\\/20]="form.template !== tpl.id"
                [class.hover:border-brand-500\\/30]="form.template !== tpl.id"
              >
                <app-icon [name]="tpl.icon" [size]="14" class="text-brand-400 mt-0.5 shrink-0" />
                <div class="min-w-0">
                  <div class="text-xs font-medium text-white truncate">{{ tpl.label }}</div>
                  <div class="text-[10px] text-gray-500 line-clamp-1">{{ tpl.description }}</div>
                </div>
              </button>
            }
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Model</label>
            <select
              [(ngModel)]="form.model"
              name="model"
              class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/60 transition"
            >
              <option value="gpt-4o-mini">GPT-4o mini</option>
              <option value="gpt-4o">GPT-4o</option>
              <option value="claude-sonnet">Claude Sonnet</option>
              <option value="mistral-large">Mistral Large</option>
            </select>
          </div>
          <div>
            <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">RAG mode</label>
            <select
              [(ngModel)]="form.rag_mode"
              name="rag_mode"
              class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/60 transition"
            >
              <option value="OmniRAG">OmniRAG</option>
              <option value="Semantic">Semantic</option>
              <option value="Hybrid">Hybrid</option>
              <option value="None">No RAG</option>
            </select>
          </div>
        </div>

        <div class="flex items-center gap-2 pt-2">
          <button
            type="submit"
            [disabled]="!form.name.trim()"
            class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-brand-500 hover:bg-brand-600 disabled:opacity-40 text-white text-sm font-medium shadow-glow-sm transition"
          >
            <app-icon name="check" [size]="14" /> Create system
          </button>
          <button
            type="button"
            (click)="drawerOpen.set(false)"
            class="px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm transition"
          >
            Cancel
          </button>
        </div>
      </form>
    </app-drawer>
  `,
})
export class SystemsGridComponent implements OnInit {
  protected readonly store = inject(SystemsStore);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  prompt = '';
  drawerOpen = signal(false);

  form = {
    name: '',
    description: '',
    template: '',
    model: 'gpt-4o-mini',
    rag_mode: 'OmniRAG',
    prompt: '',
  };

  readonly agents = this.store.systems;

  readonly templates: Template[] = [
    { id: 'contract', label: 'Contract Analysis', icon: 'file-text', description: 'Flag risky clauses in contracts', prompt: 'Analyze contracts and flag risk clauses' },
    { id: 'support', label: 'Customer Support', icon: 'message-square', description: 'Answer questions from your docs', prompt: 'Answer customer questions from docs' },
    { id: 'code', label: 'Code Review', icon: 'code-2', description: 'Review PRs for bugs and style', prompt: 'Review pull requests for bugs and style' },
    { id: 'research', label: 'Market Research', icon: 'microscope', description: 'Synthesize competitor intel', prompt: 'Synthesize competitor intelligence' },
    { id: 'onboarding', label: 'HR Onboarding', icon: 'user-plus', description: 'Guide new hires in the first weeks', prompt: 'Guide new hires through their first weeks' },
    { id: 'insights', label: 'Data Insights', icon: 'bar-chart-3', description: 'Extract KPIs from CSVs', prompt: 'Extract KPIs from CSVs and reports' },
  ];

  ngOnInit(): void {
    this.store.load().subscribe();
  }

  applyTemplate(tpl: Template): void {
    this.prompt = tpl.prompt;
  }

  selectTemplate(tpl: Template): void {
    this.form.template = tpl.id;
    if (!this.form.name) this.form.name = tpl.label;
    if (!this.form.description) this.form.description = tpl.description;
    if (!this.form.prompt) this.form.prompt = tpl.prompt;
  }

  openDrawer(prefill?: Partial<typeof this.form>): void {
    this.form = {
      name: '',
      description: '',
      template: '',
      model: 'gpt-4o-mini',
      rag_mode: 'OmniRAG',
      prompt: '',
      ...(prefill ?? {}),
    };
    this.drawerOpen.set(true);
  }

  startFromPrompt(): void {
    const p = this.prompt.trim();
    if (!p) return;
    this.openDrawer({ prompt: p, description: p, name: this.suggestNameFromPrompt(p) });
  }

  createSystem(): void {
    if (!this.form.name.trim()) return;
    const draft = this.store.createDraft({
      name: this.form.name.trim(),
      description: this.form.description.trim(),
      template: this.form.template,
      model: this.form.model,
      rag_mode: this.form.rag_mode,
      prompt: this.form.prompt,
    });
    this.drawerOpen.set(false);
    this.toastr.success(`"${draft.name}" is ready to configure`, 'System created');
    this.router.navigate(['/systems', draft.id]);
  }

  private suggestNameFromPrompt(p: string): string {
    const words = p.replace(/[^a-zA-Z0-9\s]/g, '').trim().split(/\s+/).slice(0, 4);
    if (words.length === 0) return 'New system';
    return words
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  }

  agentIcon(agent: SystemAgent): string {
    if (agent.template) {
      const map: Record<string, string> = {
        contract: 'file-text',
        support: 'message-square',
        code: 'code-2',
        research: 'microscope',
        onboarding: 'user-plus',
        insights: 'bar-chart-3',
      };
      if (map[agent.template]) return map[agent.template];
    }
    const name = (agent.name || '').toLowerCase();
    if (name.includes('support') || name.includes('chat')) return 'message-square';
    if (name.includes('code') || name.includes('dev')) return 'code-2';
    if (name.includes('contract') || name.includes('legal')) return 'file-text';
    if (name.includes('data') || name.includes('sql')) return 'database';
    if (name.includes('voice') || name.includes('mic')) return 'mic';
    return 'bot';
  }

  stub(seed: string, k: number): number {
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
    const mix = (h >>> (k * 3)) & 0xffff;
    if (k === 1) return (mix % 900) + 100;
    if (k === 2) return (mix % 40) + 10;
    return (mix % 20) + 2;
  }
}
