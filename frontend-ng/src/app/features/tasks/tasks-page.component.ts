import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { SseChunk, SseService } from '@app/core/sse.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { GlyphComponent, PageFrameComponent, StatReadoutComponent } from '@app/shared/cockpit';

interface Agent {
  id: string;
  name: string;
}

interface TaskSummary {
  id: string;
  title: string;
  description?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  agent_id?: string;
  progress?: number;
  created_at?: string | null;
  completed_at?: string | null;
  total_duration_ms?: number | null;
}

interface TaskStep {
  id?: string;
  name?: string;
  step_type?: string;
  status?: string;
  output?: unknown;
  error?: string | null;
}

interface TaskDetail extends TaskSummary {
  steps?: TaskStep[];
  artifacts?: Record<string, unknown>;
  error?: string | null;
}

interface TaskEvent {
  type: string;
  step?: TaskStep;
  progress?: number;
  steps?: TaskStep[];
  artifacts?: Record<string, unknown>;
  message?: string;
  total_duration_ms?: number;
}

@Component({
  selector: 'app-tasks-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    IconComponent,
    StatReadoutComponent,
    EmptyStateComponent,
    DrawerComponent,
    PageFrameComponent,
    GlyphComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Run · Missions"
      title="Autonomous missions"
      description="Goal-oriented tasks: plan → act → verify → report — running in the background."
    >
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
        <button
          type="button"
          (click)="refresh()"
          [disabled]="loading()"
          class="ck-mono"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="6"
          [style.height.px]="28"
          [style.padding]="'0 12px'"
          [style.background]="'transparent'"
          [style.color]="'var(--ck-fg-2)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.letterSpacing]="'0.08em'"
          [style.textTransform]="'uppercase'"
          [style.cursor]="'pointer'"
        >
          <ck-glyph name="orbit" [size]="12" />
          Refresh
        </button>
        <button
          type="button"
          (click)="openCreate()"
          class="ck-mono"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="6"
          [style.height.px]="28"
          [style.padding]="'0 12px'"
          [style.background]="'var(--ck-signal-cool)'"
          [style.color]="'var(--ck-bg-base)'"
          [style.border]="'none'"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.fontWeight]="600"
          [style.letterSpacing]="'0.08em'"
          [style.textTransform]="'uppercase'"
          [style.cursor]="'pointer'"
        >
          <ck-glyph name="bolt" [size]="12" />
          New mission
        </button>
      </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <ck-stat-readout variant="tile" label="Total" [value]="tasks().length" icon="list-todo" />
      <ck-stat-readout variant="tile"
        label="Running"
        [value]="runningCount()"
        icon="loader-2"
        [trend]="runningCount() > 0 ? 'up' : null"
      />
      <ck-stat-readout variant="tile" label="Completed" [value]="completedCount()" icon="check-circle-2" />
      <ck-stat-readout variant="tile" label="Failed" [value]="failedCount()" icon="x-circle" />
    </div>

    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="history" [size]="16" class="text-brand-400" />
          Recent missions
        </h3>
      </div>

      @if (loading() && tasks().length === 0) {
        <div class="divide-y divide-white/5">
          @for (_ of [0, 1, 2, 3]; track $index) {
            <div class="px-5 py-4 animate-pulse">
              <div class="h-3 w-60 bg-white/5 rounded"></div>
            </div>
          }
        </div>
      } @else if (tasks().length === 0) {
        <app-empty-state
          icon="list-todo"
          title="No missions yet"
          description="Launch an autonomous agent mission to automate multi-step work."
        />
      } @else {
        <ul class="divide-y divide-white/5">
          @for (t of tasks(); track t.id) {
            <li
              class="px-5 py-3 cursor-pointer hover:bg-white/5 transition"
              (click)="openDetail(t)"
            >
              <div class="flex items-center gap-3">
                <div
                  class="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                  [class.bg-brand-500\\/15]="t.status === 'running'"
                  [class.text-brand-300]="t.status === 'running'"
                  [class.bg-emerald-500\\/15]="t.status === 'completed'"
                  [class.text-emerald-300]="t.status === 'completed'"
                  [class.bg-red-500\\/15]="t.status === 'failed'"
                  [class.text-red-300]="t.status === 'failed'"
                  [class.bg-white\\/5]="t.status === 'pending'"
                  [class.text-gray-400]="t.status === 'pending'"
                >
                  <app-icon [name]="iconFor(t.status)" [size]="14" [class.animate-spin]="t.status === 'running'" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-white truncate">{{ t.title }}</div>
                  <div class="text-[11px] text-gray-500 truncate mt-0.5">
                    <span class="capitalize">{{ t.status }}</span>
                    <span class="mx-1">·</span>
                    {{ formatDate(t.created_at) }}
                    @if (t.total_duration_ms) {
                      <span class="mx-1">·</span>
                      {{ t.total_duration_ms.toFixed(0) }} ms
                    }
                  </div>
                </div>
                <div class="w-32 shrink-0">
                  <div class="h-1.5 rounded-full bg-white/5 overflow-hidden">
                    <div
                      class="h-full transition-all duration-300"
                      [class.bg-brand-500]="t.status === 'running'"
                      [class.bg-emerald-500]="t.status === 'completed'"
                      [class.bg-red-500]="t.status === 'failed'"
                      [class.bg-gray-600]="t.status === 'pending'"
                      [style.width.%]="t.status === 'completed' ? 100 : t.progress ?? 0"
                    ></div>
                  </div>
                </div>
                <app-icon name="chevron-right" [size]="14" class="text-gray-500 shrink-0" />
              </div>
            </li>
          }
        </ul>
      }
    </section>
    </ck-page-frame>

    <!-- Create dialog -->
    @if (createOpen()) {
      <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" (click)="createOpen.set(false)"></div>
        <div
          class="relative glass-blur rounded-lg border border-white/10 shadow-elevated max-w-lg w-full p-6"
        >
          <div class="flex items-start gap-4 mb-4">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center bg-brand-500/15 text-brand-400 shrink-0"
            >
              <app-icon name="rocket" [size]="20" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold text-white mb-1">New autonomous mission</h2>
              <p class="text-sm text-gray-400">
                Describe the goal. The agent will plan, execute and report.
              </p>
            </div>
          </div>
          <div class="space-y-3">
            <input
              [(ngModel)]="newTitle"
              placeholder="Title (optional)"
              class="w-full px-3 py-2 bg-black/30 border border-white/10 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
            <textarea
              [(ngModel)]="newDescription"
              placeholder="Describe what the agent should achieve…"
              rows="5"
              class="w-full px-3 py-2 bg-black/30 border border-white/10 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 resize-none"
            ></textarea>
            <select
              [(ngModel)]="newAgentId"
              class="w-full px-3 py-2 bg-black/30 border border-white/10 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
            >
              <option value="">Default routing</option>
              @for (a of agents(); track a.id) {
                <option [value]="a.id">{{ a.name }}</option>
              }
            </select>
          </div>
          <div class="mt-6 flex justify-end gap-2">
            <button
              type="button"
              (click)="createOpen.set(false)"
              class="px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-white/5 rounded"
            >
              Cancel
            </button>
            <button
              type="button"
              (click)="createAndRun()"
              [disabled]="!newDescription.trim() || creating()"
              class="px-4 py-2 text-sm font-medium text-white bg-brand-500 hover:bg-brand-600 rounded disabled:opacity-40 flex items-center gap-1.5"
            >
              <app-icon
                [name]="creating() ? 'loader-2' : 'play'"
                [size]="14"
                [class.animate-spin]="creating()"
              />
              Create &amp; run
            </button>
          </div>
        </div>
      </div>
    }

    <!-- Detail drawer -->
    <app-drawer
      [open]="detail() !== null"
      [title]="detail()?.title ?? ''"
      [subtitle]="detailSubtitle()"
      icon="list-todo"
      (close)="closeDetail()"
    >
      @if (detail(); as d) {
        <div class="space-y-4">
          <div class="flex items-center gap-2">
            <span
              class="text-[10px] uppercase tracking-wider font-semibold px-2 py-1 rounded-full ring-1 capitalize"
              [class.bg-brand-500\\/10]="d.status === 'running'"
              [class.text-brand-300]="d.status === 'running'"
              [class.ring-brand-500\\/30]="d.status === 'running'"
              [class.bg-emerald-500\\/10]="d.status === 'completed'"
              [class.text-emerald-300]="d.status === 'completed'"
              [class.ring-emerald-500\\/30]="d.status === 'completed'"
              [class.bg-red-500\\/10]="d.status === 'failed'"
              [class.text-red-300]="d.status === 'failed'"
              [class.ring-red-500\\/30]="d.status === 'failed'"
              [class.bg-white\\/5]="d.status === 'pending'"
              [class.text-gray-400]="d.status === 'pending'"
              [class.ring-white\\/10]="d.status === 'pending'"
            >
              {{ d.status }}
            </span>
            @if (d.status !== 'running') {
              <button
                type="button"
                class="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
                (click)="runTask(d.id)"
              >
                <app-icon name="play" [size]="13" />
                {{ d.status === 'pending' ? 'Run' : 'Rerun' }}
              </button>
            }
          </div>

          <div>
            <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
              Goal
            </div>
            <div class="text-sm text-gray-200 whitespace-pre-wrap">{{ d.description }}</div>
          </div>

          @if (d.status === 'running' || (d.progress ?? 0) > 0) {
            <div>
              <div class="flex items-center justify-between text-xs text-gray-400 mb-1">
                <span>Progress</span>
                <span class="font-mono">{{ d.progress ?? 0 }}%</span>
              </div>
              <div class="h-1.5 rounded-full bg-white/5 overflow-hidden">
                <div
                  class="h-full bg-gradient-to-r from-brand-400 to-violet-500 transition-all duration-300"
                  [style.width.%]="d.progress ?? 0"
                ></div>
              </div>
            </div>
          }

          <div>
            <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">
              Steps
            </div>
            @if ((d.steps?.length ?? 0) === 0) {
              <div class="text-xs text-gray-500">Waiting for the plan…</div>
            } @else {
              <ol class="space-y-2">
                @for (s of d.steps ?? []; track $index; let i = $index) {
                  <li
                    class="rounded ring-1 ring-white/5 p-3"
                    [class.bg-red-500\\/5]="s.status === 'failed' || !!s.error"
                    [class.bg-emerald-500\\/5]="s.status === 'completed'"
                    [class.bg-black\\/20]="s.status !== 'failed' && s.status !== 'completed' && !s.error"
                  >
                    <div class="flex items-center justify-between">
                      <div class="flex items-center gap-2 min-w-0">
                        <span
                          class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0"
                          [class.bg-emerald-500\\/20]="s.status === 'completed'"
                          [class.text-emerald-300]="s.status === 'completed'"
                          [class.bg-brand-500\\/20]="s.status === 'running' || s.status === 'in_progress'"
                          [class.text-brand-300]="s.status === 'running' || s.status === 'in_progress'"
                          [class.bg-red-500\\/20]="s.status === 'failed' || !!s.error"
                          [class.text-red-300]="s.status === 'failed' || !!s.error"
                          [class.bg-white\\/5]="!s.status || s.status === 'pending'"
                          [class.text-gray-400]="!s.status || s.status === 'pending'"
                        >
                          {{ i + 1 }}
                        </span>
                        <span class="text-sm text-white truncate">
                          {{ s.name || s.step_type || 'step' }}
                        </span>
                      </div>
                      @if (s.status) {
                        <span class="text-[10px] text-gray-500 capitalize shrink-0">
                          {{ s.status }}
                        </span>
                      }
                    </div>
                    @if (s.error) {
                      <div class="text-[11px] text-red-300 mt-1 font-mono">{{ s.error }}</div>
                    }
                    @if (s.output) {
                      <details class="mt-2">
                        <summary class="text-[11px] text-gray-500 cursor-pointer hover:text-gray-300">
                          output
                        </summary>
                        <pre
                          class="mt-1 text-[11px] text-gray-200 bg-black/30 rounded p-2 font-mono whitespace-pre-wrap"
                        >{{ jsonPretty(s.output) }}</pre>
                      </details>
                    }
                  </li>
                }
              </ol>
            }
          </div>

          @if (d.artifacts && hasKeys(d.artifacts)) {
            <div>
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">
                Artifacts
              </div>
              <pre
                class="text-[11px] text-gray-200 bg-black/30 rounded p-3 font-mono whitespace-pre-wrap max-h-64 overflow-auto"
              >{{ jsonPretty(d.artifacts) }}</pre>
            </div>
          }

          @if (d.error) {
            <div class="rounded bg-red-500/10 ring-1 ring-red-500/30 p-3 text-xs text-red-300">
              <div class="font-semibold mb-1">Error</div>
              <div class="font-mono whitespace-pre-wrap">{{ d.error }}</div>
            </div>
          }
        </div>
      }
    </app-drawer>
  `,
})
export class TasksPageComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly sse = inject(SseService);
  private readonly toast = inject(ToastrService);

  tasks = signal<TaskSummary[]>([]);
  agents = signal<Agent[]>([]);
  loading = signal(false);
  detail = signal<TaskDetail | null>(null);

  createOpen = signal(false);
  creating = signal(false);
  newTitle = '';
  newDescription = '';
  newAgentId = '';

  readonly runningCount = computed(
    () => this.tasks().filter((t) => t.status === 'running').length,
  );
  readonly completedCount = computed(
    () => this.tasks().filter((t) => t.status === 'completed').length,
  );
  readonly failedCount = computed(
    () => this.tasks().filter((t) => t.status === 'failed').length,
  );

  readonly detailSubtitle = computed(() => {
    const d = this.detail();
    if (!d) return '';
    const parts: string[] = [];
    if (d.total_duration_ms) parts.push(`${d.total_duration_ms.toFixed(0)} ms`);
    if (d.agent_id) parts.push(d.agent_id);
    return parts.join(' · ');
  });

  ngOnInit(): void {
    this.refresh();
    // Canonical `/systems` — `/agents` is a deprecated alias.
    this.api.get<{ systems: Agent[] } | Agent[]>('/systems').subscribe({
      next: (res) => {
        const list = Array.isArray(res) ? res : res?.systems ?? [];
        this.agents.set(list);
      },
      error: () => this.agents.set([]),
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.api.get<{ tasks: TaskSummary[] }>('/tasks?limit=50').subscribe({
      next: (res) => {
        this.tasks.set(res?.tasks ?? []);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  openCreate(): void {
    this.newTitle = '';
    this.newDescription = '';
    this.newAgentId = '';
    this.createOpen.set(true);
  }

  createAndRun(): void {
    const description = this.newDescription.trim();
    if (!description) return;
    this.creating.set(true);
    this.api
      .post<{ id: string }>('/tasks', {
        title: this.newTitle.trim(),
        description,
        agent_id: this.newAgentId || null,
      })
      .subscribe({
        next: (res) => {
          this.creating.set(false);
          this.createOpen.set(false);
          this.toast.success('Mission queued', 'Tasks');
          this.refresh();
          if (res?.id) {
            // Seed the detail drawer with a pending shell and stream the run.
            const pending: TaskDetail = {
              id: res.id,
              title: this.newTitle.trim() || description.slice(0, 80),
              description,
              status: 'pending',
              steps: [],
            };
            this.detail.set(pending);
            this.runTask(res.id);
          }
        },
        error: (err) => {
          this.creating.set(false);
          this.toast.error(err?.error?.detail ?? 'Failed to create', 'Tasks');
        },
      });
  }

  openDetail(t: TaskSummary): void {
    this.detail.set({ ...t, steps: [] });
    this.api.get<TaskDetail>(`/tasks/${t.id}`).subscribe({
      next: (res) => {
        if (res && !(res as unknown as { error?: string }).error) this.detail.set(res);
      },
      error: () => {},
    });
  }

  closeDetail(): void {
    this.detail.set(null);
    // Refresh the list in case a run just completed.
    this.refresh();
  }

  runTask(taskId: string): void {
    // Update status optimistically.
    this.detail.update((d) => (d && d.id === taskId ? { ...d, status: 'running', progress: 0 } : d));
    this.tasks.update((list) =>
      list.map((t) => (t.id === taskId ? { ...t, status: 'running', progress: 0 } : t)),
    );

    this.sse.stream(`/api/v1/tasks/${taskId}/run`, {}).subscribe({
      next: (chunk: SseChunk) => {
        const evt = this.extractEvent(chunk);
        if (!evt) return;
        this.applyEvent(taskId, evt);
      },
      error: () => this.toast.error('Mission stream error', 'Tasks'),
      complete: () => this.refresh(),
    });
  }

  private applyEvent(taskId: string, evt: TaskEvent): void {
    if (evt.type === 'task_plan' && evt.steps) {
      this.detail.update((d) => (d && d.id === taskId ? { ...d, steps: evt.steps, status: 'running' } : d));
    } else if (evt.type === 'task_step' && evt.step) {
      this.detail.update((d) => {
        if (!d || d.id !== taskId) return d;
        const steps = this.mergeStep(d.steps ?? [], evt.step!);
        return { ...d, steps, progress: evt.progress ?? d.progress };
      });
    } else if (evt.type === 'task_step_complete' && evt.step) {
      this.detail.update((d) => {
        if (!d || d.id !== taskId) return d;
        const steps = this.mergeStep(d.steps ?? [], {
          ...evt.step!,
          status: evt.step!.status ?? 'completed',
        });
        return { ...d, steps, progress: evt.progress ?? d.progress };
      });
    } else if (evt.type === 'task_complete') {
      this.detail.update((d) =>
        d && d.id === taskId
          ? {
              ...d,
              status: 'completed',
              progress: 100,
              steps: evt.steps ?? d.steps,
              artifacts: evt.artifacts ?? d.artifacts,
              total_duration_ms: evt.total_duration_ms ?? d.total_duration_ms,
            }
          : d,
      );
      this.toast.success('Mission complete', 'Tasks');
    } else if (evt.type === 'task_error') {
      this.detail.update((d) =>
        d && d.id === taskId ? { ...d, status: 'failed', error: evt.message ?? 'Unknown error' } : d,
      );
      this.toast.error(evt.message ?? 'Mission failed', 'Tasks');
    }
  }

  private mergeStep(existing: TaskStep[], incoming: TaskStep): TaskStep[] {
    const idx = incoming.id
      ? existing.findIndex((s) => s.id === incoming.id)
      : existing.findIndex((s) => s.name === incoming.name && s.step_type === incoming.step_type);
    if (idx >= 0) {
      const copy = [...existing];
      copy[idx] = { ...existing[idx], ...incoming };
      return copy;
    }
    return [...existing, incoming];
  }

  private extractEvent(chunk: SseChunk): TaskEvent | null {
    if (chunk.type === 'done') return null;
    const raw = chunk as unknown as Record<string, unknown>;
    if (typeof raw['type'] === 'string') return raw as unknown as TaskEvent;
    if (chunk.chunk_type === 'text' && typeof chunk.content === 'string') {
      try {
        return JSON.parse(chunk.content) as TaskEvent;
      } catch {
        return null;
      }
    }
    return null;
  }

  iconFor(status: string): string {
    if (status === 'completed') return 'check-circle-2';
    if (status === 'failed') return 'x-circle';
    if (status === 'running') return 'loader-2';
    return 'clock';
  }

  formatDate(iso?: string | null): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
    } catch {
      return iso;
    }
  }

  hasKeys(obj: unknown): boolean {
    return !!obj && typeof obj === 'object' && Object.keys(obj as object).length > 0;
  }

  jsonPretty(obj: unknown): string {
    try {
      return typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  }
}
