import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';

interface SystemAgent {
  id: string;
  name: string;
  description: string;
  status: string;
  rag_mode?: string;
}

interface Template {
  id: string;
  label: string;
  icon: string;
  prompt: string;
}

@Component({
  selector: 'app-systems-grid',
  standalone: true,
  imports: [
    RouterLink,
    FormsModule,
    IconComponent,
    SectionHeaderComponent,
    StatusPulseComponent,
    EmptyStateComponent,
    SkeletonComponent,
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
            class="px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-600 text-white font-medium text-sm shadow-glow-sm transition inline-flex items-center gap-1.5"
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

    @if (loading()) {
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
        />
      </div>
    } @else {
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (agent of agents(); track agent.id) {
          <a
            [routerLink]="[agent.id]"
            class="group t-card t-elevated rounded-md p-5 relative overflow-hidden hover:-translate-y-0.5 transition-transform"
          >
            <div class="flex items-start gap-3">
              <div
                class="w-10 h-10 rounded-md flex items-center justify-center bg-gradient-to-br from-brand-500/20 to-violet-500/20 ring-1 ring-brand-500/30 text-brand-400 shadow-glow-sm shrink-0"
              >
                <app-icon [name]="agentIcon(agent)" [size]="18" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5">
                  <h3 class="font-semibold text-white truncate">{{ agent.name }}</h3>
                  <app-status-pulse [tone]="agent.status === 'active' ? 'success' : 'warning'" />
                </div>
                <p class="text-xs text-gray-400 line-clamp-2 leading-relaxed">
                  {{ agent.description || 'No description yet.' }}
                </p>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-white/5">
              <div>
                <div class="text-[9px] uppercase tracking-wider text-gray-500 font-semibold">Runs</div>
                <div class="text-sm font-semibold text-white tabular-nums">{{ stub(agent.id, 1) }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-wider text-gray-500 font-semibold">ROI</div>
                <div class="text-sm font-semibold text-emerald-400 tabular-nums">+{{ stub(agent.id, 2) }}%</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-wider text-gray-500 font-semibold">Saved</div>
                <div class="text-sm font-semibold text-white tabular-nums">{{ stub(agent.id, 3) }}h</div>
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
  `,
})
export class SystemsGridComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  agents = signal<SystemAgent[]>([]);
  loading = signal(true);
  prompt = '';

  readonly templates: Template[] = [
    { id: 'contract', label: 'Contract Analysis', icon: 'file-text', prompt: 'Analyze contracts and flag risk clauses' },
    { id: 'support', label: 'Customer Support', icon: 'message-square', prompt: 'Answer customer questions from docs' },
    { id: 'code', label: 'Code Review', icon: 'code-2', prompt: 'Review pull requests for bugs and style' },
    { id: 'research', label: 'Market Research', icon: 'microscope', prompt: 'Synthesize competitor intelligence' },
    { id: 'onboarding', label: 'HR Onboarding', icon: 'user-plus', prompt: 'Guide new hires through their first weeks' },
    { id: 'insights', label: 'Data Insights', icon: 'bar-chart-3', prompt: 'Extract KPIs from CSVs and reports' },
  ];

  ngOnInit(): void {
    this.api.get<{ agents: SystemAgent[] } | SystemAgent[]>('/agents').subscribe({
      next: (res) => {
        const list = Array.isArray(res) ? res : (res?.agents ?? []);
        this.agents.set(list.map((a) => ({ ...a, description: a.description ?? '' })));
        this.loading.set(false);
      },
      error: () => {
        this.agents.set([]);
        this.loading.set(false);
      },
    });
  }

  applyTemplate(tpl: Template): void {
    this.prompt = tpl.prompt;
  }

  startFromPrompt(): void {
    if (!this.prompt.trim()) return;
  }

  agentIcon(agent: SystemAgent): string {
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
