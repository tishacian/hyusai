import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { SystemsStore } from './systems.store';

interface TabDef {
  id: 'overview' | 'design' | 'runs' | 'settings';
  label: string;
  icon: string;
}

interface WizardStep {
  title: string;
  done: boolean;
}

@Component({
  selector: 'app-system-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgClass,
    ChatPanelComponent,
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    StatusPulseComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Systems"
      [title]="agentName()"
      icon="bot"
      [subtitle]="agentDescription() || 'Configure, run and refine this AI system.'"
      [pill]="isDraft() ? 'Draft' : ''"
    >
      <app-status-pulse [tone]="isDraft() ? 'warning' : 'success'" [label]="isDraft() ? 'Draft' : 'Ready'" />
    </app-section-header>

    <div class="flex items-center gap-1 border-b border-white/5 mb-6">
      @for (tab of tabs; track tab.id) {
        <button
          type="button"
          (click)="activeTab.set(tab.id)"
          [ngClass]="{
            'text-white border-brand-500': activeTab() === tab.id,
            'text-gray-400 border-transparent hover:text-gray-200': activeTab() !== tab.id
          }"
          class="relative inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition"
        >
          <app-icon [name]="tab.icon" [size]="14" />
          {{ tab.label }}
        </button>
      }
    </div>

    <!-- Overview -->
    @if (activeTab() === 'overview') {
      <div class="space-y-6">
        <!-- OmniRAG banner -->
        <div
          class="relative overflow-hidden t-card rounded-md p-5"
          style="background: linear-gradient(135deg, rgba(0,188,212,0.08) 0%, rgba(139,92,246,0.08) 100%); border: 1px solid rgba(0,188,212,0.25);"
        >
          <div class="absolute -right-16 -top-16 w-56 h-56 rounded-full bg-brand-500/15 blur-3xl pointer-events-none"></div>
          <div class="relative flex items-center gap-3 flex-wrap">
            <app-icon name="atom" [size]="18" class="text-brand-400" />
            <span class="text-xs uppercase tracking-wider font-semibold text-brand-300">OmniRAG pipeline</span>
            <div class="flex items-center gap-2 ml-auto text-[11px] text-gray-300">
              @for (step of pipelineSteps; track step.name; let last = $last) {
                <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-white/5 ring-1 ring-white/10">
                  <app-icon [name]="step.icon" [size]="11" class="text-brand-400" />
                  {{ step.name }}
                </span>
                @if (!last) {
                  <app-icon name="chevron-right" [size]="12" class="text-gray-600" />
                }
              }
            </div>
          </div>
        </div>

        <!-- KPI row -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <app-stat-tile label="Runs" value="1,284" icon="play-circle" trend="up" delta="+12%" />
          <app-stat-tile label="Tokens" value="4.8M" icon="sparkles" trend="up" delta="+5%" />
          <app-stat-tile label="Latency" value="842" unit="ms" icon="gauge" trend="down" delta="-8%" />
          <app-stat-tile label="Quality" value="94" unit="%" icon="target" trend="up" delta="+2%" />
          <app-stat-tile label="Cost" value="$38.20" icon="trending-down" trend="down" delta="-4%" />
          <app-stat-tile label="Users" value="37" icon="users" trend="up" delta="+3" />
        </div>

        <!-- Setup wizard -->
        <section class="t-card t-elevated rounded-md p-6">
          <div class="flex items-center gap-2 mb-4">
            <app-icon name="list-checks" [size]="16" class="text-brand-400" />
            <h3 class="text-base font-semibold text-white">Setup checklist</h3>
            <span class="ml-auto text-xs text-gray-400">{{ completedSteps() }} / {{ wizard.length }} done</span>
          </div>

          <div class="w-full h-1.5 rounded-full bg-white/5 overflow-hidden mb-4">
            <div
              class="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all"
              [style.width.%]="(completedSteps() / wizard.length) * 100"
            ></div>
          </div>

          <ul class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-2">
            @for (step of wizard; track step.title; let i = $index) {
              <li
                class="flex items-center gap-2 px-3 py-2 rounded border text-sm"
                [ngClass]="step.done
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-300'
                  : 'border-white/5 bg-black/20 text-gray-400'"
              >
                <app-icon
                  [name]="step.done ? 'check-circle-2' : 'circle'"
                  [size]="14"
                  [class]="step.done ? 'text-emerald-400' : 'text-gray-500'"
                />
                <span class="text-[10px] uppercase tracking-wider text-gray-500 mr-1">{{ i + 1 }}</span>
                <span class="truncate">{{ step.title }}</span>
              </li>
            }
          </ul>
        </section>
      </div>
    }

    <!-- Design canvas -->
    @if (activeTab() === 'design') {
      <section class="t-card t-elevated rounded-md overflow-hidden h-[560px] flex">
        <aside class="w-56 border-r border-white/5 p-4 space-y-3 bg-black/20">
          <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Building blocks</div>
          @for (block of designBlocks; track block.label) {
            <div
              class="px-3 py-2 rounded bg-white/5 ring-1 ring-white/5 text-sm text-gray-200 flex items-center gap-2 cursor-grab hover:ring-brand-500/40 transition"
            >
              <app-icon [name]="block.icon" [size]="14" class="text-brand-400" />
              {{ block.label }}
            </div>
          }
        </aside>
        <div class="flex-1 relative bg-[radial-gradient(circle_at_2px_2px,rgba(148,163,184,0.14)_1px,transparent_0)] bg-[length:18px_18px]">
          <svg class="absolute inset-0 w-full h-full" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="flow" x1="0" x2="1">
                <stop offset="0%" stop-color="#00bcd4" />
                <stop offset="100%" stop-color="#8b5cf6" />
              </linearGradient>
            </defs>
            <path d="M 120 200 C 260 200 260 260 420 260 S 580 340 720 340" stroke="url(#flow)" stroke-width="2" fill="none" stroke-dasharray="6 4" />
          </svg>
          <div class="absolute left-10 top-40 t-card rounded-md px-4 py-3 w-56 shadow-elevated ring-1 ring-brand-500/20">
            <div class="text-[10px] uppercase tracking-wider text-brand-400 font-semibold mb-0.5">L1 · Input</div>
            <div class="text-sm font-medium text-white">User request</div>
          </div>
          <div class="absolute left-[340px] top-52 t-card rounded-md px-4 py-3 w-56 shadow-elevated ring-1 ring-violet-500/20">
            <div class="text-[10px] uppercase tracking-wider text-violet-400 font-semibold mb-0.5">L2 · Retrieve</div>
            <div class="text-sm font-medium text-white">Knowledge base</div>
          </div>
          <div class="absolute left-[640px] top-72 t-card rounded-md px-4 py-3 w-56 shadow-elevated ring-1 ring-emerald-500/20">
            <div class="text-[10px] uppercase tracking-wider text-emerald-400 font-semibold mb-0.5">L3 · Generate</div>
            <div class="text-sm font-medium text-white">LLM response</div>
          </div>
        </div>
      </section>
    }

    <!-- Runs -->
    @if (activeTab() === 'runs') {
      @if (isDraft()) {
        <div class="t-card t-elevated rounded-md p-6 flex items-start gap-3">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/30 shrink-0">
            <app-icon name="alert-triangle" [size]="18" />
          </div>
          <div>
            <div class="text-base font-semibold text-white">Not deployed yet</div>
            <p class="text-sm text-gray-400 mt-1 max-w-lg">
              This system is still a draft. Finish the setup checklist and launch it to start running
              conversations. The Runs tab will light up as soon as the system is active.
            </p>
          </div>
        </div>
      } @else {
        <div class="t-card t-elevated rounded-md p-0 overflow-hidden min-h-[520px]">
          <app-chat-panel [systemId]="systemId" />
        </div>
      }
    }

    <!-- Settings -->
    @if (activeTab() === 'settings') {
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <section class="t-card t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="tag" [size]="14" class="text-brand-400" /> Identity
          </h3>
          <div class="space-y-3 text-sm">
            <div>
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Name</div>
              <div class="text-white">{{ agentName() }}</div>
            </div>
            <div>
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">System ID</div>
              <div class="text-gray-300 font-mono text-xs">{{ systemId }}</div>
            </div>
          </div>
        </section>
        <section class="t-card t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="cpu" [size]="14" class="text-brand-400" /> Model
          </h3>
          <div class="space-y-3 text-sm text-gray-300">
            <div>Provider: <span class="text-white">OpenAI</span></div>
            <div>Model: <span class="text-white">gpt-4o-mini</span></div>
            <div>Temperature: <span class="text-white">0.4</span></div>
          </div>
        </section>
        <section class="t-card t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="database" [size]="14" class="text-brand-400" /> Knowledge
          </h3>
          <div class="space-y-3 text-sm text-gray-300">
            <div>Collections: <span class="text-white">2</span></div>
            <div>Retriever: <span class="text-white">OmniRAG</span></div>
            <div>Reranker: <span class="text-white">Cohere rerank-3</span></div>
          </div>
        </section>
      </div>
    }
  `,
})
export class SystemViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly store = inject(SystemsStore);

  systemId = '';
  agentName = signal('System');
  agentDescription = signal('');
  isDraft = signal(false);
  activeTab = signal<TabDef['id']>('overview');

  readonly tabs: TabDef[] = [
    { id: 'overview', label: 'Overview', icon: 'layout-dashboard' },
    { id: 'design', label: 'Design', icon: 'workflow' },
    { id: 'runs', label: 'Runs', icon: 'message-square' },
    { id: 'settings', label: 'Settings', icon: 'settings' },
  ];

  readonly wizard: WizardStep[] = [
    { title: 'Identity', done: true },
    { title: 'Knowledge', done: true },
    { title: 'Model', done: true },
    { title: 'Guardrails', done: false },
    { title: 'Launch', done: false },
  ];

  readonly pipelineSteps = [
    { name: 'Query', icon: 'message-square' },
    { name: 'Retrieve', icon: 'database' },
    { name: 'Rerank', icon: 'filter' },
    { name: 'Generate', icon: 'sparkles' },
  ];

  readonly designBlocks = [
    { label: 'Prompt', icon: 'message-square' },
    { label: 'Retriever', icon: 'database' },
    { label: 'Guardrail', icon: 'shield' },
    { label: 'Tool call', icon: 'wrench' },
    { label: 'Post-process', icon: 'wand-2' },
    { label: 'Output', icon: 'send' },
  ];

  readonly completedSteps = computed(() => this.wizard.filter((s) => s.done).length);

  ngOnInit(): void {
    this.systemId = this.route.snapshot.paramMap.get('systemId') ?? '';
    const local = this.store.findById(this.systemId);
    if (local) {
      this.agentName.set(local.name);
      this.agentDescription.set(local.description || '');
      this.isDraft.set(!!local.draft);
      return;
    }
    this.store.getById(this.systemId).subscribe({
      next: (agent) => {
        if (!agent) return;
        this.agentName.set(agent.name);
        this.agentDescription.set(agent.description || '');
        this.isDraft.set(!!agent.draft);
      },
      error: () => {},
    });
  }
}
