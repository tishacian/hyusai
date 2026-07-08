/**
 * Canonical `/runs/:runId` detail view.
 *
 * Shows the Run timeline (skill invocations), input/outcome payloads,
 * errors and checkpoints. Replaces the legacy trace drawer — the Run is
 * now a full-page drill-down, reachable from Systems, Runs list, or any
 * Decision trail that references it.
 */
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, PageFrameComponent, RunOutcomeCardComponent } from '@app/shared/cockpit';
import { CanonicalApiService, type RetrievalDecisionTrace, type Run, type SkillInvocation } from '@app/core/canonical-api.service';
import { ZoomContextService } from '@app/core/zoom-context.service';

@Component({
  selector: 'app-run-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    IconComponent,
    EmptyStateComponent,
    PageFrameComponent,
    RunOutcomeCardComponent,
    HelpTooltipComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Measure · Runs"
      [title]="titleLabel()"
      [description]="descriptionLabel()"
      [status]="run()?.status || ''"
    >
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
        <a
          routerLink="/runs"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        >
          <app-icon name="arrow-left" [size]="12" />
          All runs
        </a>
        @if (run()?.system_id) {
          <a
            [routerLink]="['/systems', run()!.system_id]"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          >
            <app-icon name="box" [size]="12" />
            Open system
          </a>
        }
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          (click)="refresh()"
          [disabled]="loading()"
        >
          <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" />
          Refresh
        </button>
      </div>

      @if (loading() && !run()) {
        <div class="animate-pulse space-y-3">
          <div class="h-24 bg-white/[0.03] rounded-lg"></div>
          <div class="h-64 bg-white/[0.03] rounded-lg"></div>
        </div>
      } @else if (!run()) {
        <app-empty-state
          icon="alert-triangle"
          title="Run not found"
          description="This run may have been purged, or the id is incorrect."
        />
      } @else {
        <!-- Canonical Outcome card — value / cost / confidence / efficiency + decision. -->
        <div class="mb-6">
          <ck-run-outcome-card [run]="run()!" />

          <!-- Operator override strip — live next to the Outcome so operators
               can declare "actual" value when the auto-derivation is off. -->
          <div class="mt-3 rounded-lg border border-white/5 bg-white/[0.02] p-3">
            <div class="flex items-center gap-3 flex-wrap">
              <div class="flex items-center gap-2">
                <span class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
                  VALUE SOURCE
                </span>
                <span
                  class="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded"
                  [class.text-emerald-300]="run()!.outcome?.value_source === 'operator'"
                  [class.bg-emerald-500\\/10]="run()!.outcome?.value_source === 'operator'"
                  [class.text-cyan-300]="run()!.outcome?.value_source === 'auto'"
                  [class.bg-cyan-500\\/10]="run()!.outcome?.value_source === 'auto'"
                  [class.text-gray-400]="!run()!.outcome?.value_source || run()!.outcome?.value_source === 'unset'"
                  [class.bg-white\\/5]="!run()!.outcome?.value_source || run()!.outcome?.value_source === 'unset'"
                >
                  {{ run()!.outcome?.value_source || 'unset' }}
                </span>
              </div>

              @if (!overrideMode()) {
                <div class="ml-auto flex items-center gap-2">
                  <ck-help id="runs.outcome.override" />
                  <button
                    type="button"
                    (click)="enableOverride()"
                    class="inline-flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition font-mono tracking-wider"
                  >
                    <app-icon name="edit-3" [size]="11" />
                    OVERRIDE VALUE
                  </button>
                </div>
              } @else {
                <div class="flex items-center gap-2 flex-wrap ml-auto">
                  <input
                    type="number"
                    step="0.01"
                    [value]="overrideValue()"
                    (input)="overrideValue.set(+asInput($event).value)"
                    placeholder="Actual value"
                    class="font-mono text-xs tabular-nums"
                    style="width:110px; padding:4px 8px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2); border-radius:3px; color:var(--ck-fg-1);"
                  />
                  <input
                    type="text"
                    [value]="overrideNote()"
                    (input)="overrideNote.set(asInput($event).value)"
                    placeholder="Why this override?"
                    class="font-mono text-xs"
                    style="min-width:200px; padding:4px 8px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2); border-radius:3px; color:var(--ck-fg-1);"
                  />
                  <button
                    type="button"
                    (click)="submitOverride()"
                    [disabled]="submittingOverride()"
                    class="inline-flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-medium font-mono tracking-wider"
                    style="background:var(--ck-signal-pos); color:var(--ck-on-signal);"
                    [style.opacity]="submittingOverride() ? '0.4' : '1'"
                  >
                    {{ submittingOverride() ? 'SAVING…' : 'SAVE' }}
                  </button>
                  <button
                    type="button"
                    (click)="cancelOverride()"
                    class="inline-flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 font-mono tracking-wider"
                  >
                    CANCEL
                  </button>
                </div>
              }
            </div>
            @if (run()!.outcome?.operator_value_note) {
              <p class="text-[11px] text-gray-400 mt-2 font-mono">
                <span class="text-gray-500">NOTE:</span>
                {{ run()!.outcome!.operator_value_note }}
              </p>
            }
          </div>
        </div>

        <!-- Error banner -->
        @if (run()?.error) {
          <div class="rounded-lg border border-red-500/30 bg-red-500/10 p-3 mb-6">
            <div class="flex items-start gap-2">
              <app-icon name="alert-triangle" [size]="14" class="text-red-400 mt-0.5" />
              <div class="min-w-0">
                <div class="text-xs font-semibold text-red-300 mb-1">
                  Run failed
                </div>
                <div class="text-xs font-mono text-red-200/80 break-all">
                  {{ run()!.error }}
                </div>
              </div>
            </div>
          </div>
        }

        @if (retrievalDecisionTrace(); as trace) {
          <section class="rounded-lg border border-emerald-400/20 bg-emerald-400/[0.04] mb-6">
            <header class="px-4 py-2.5 border-b border-emerald-400/10 flex items-center gap-2">
              <app-icon name="git-branch" [size]="14" class="text-emerald-300" />
              <h2 class="text-xs uppercase tracking-wider text-emerald-200 font-semibold">
                Retrieval decision
              </h2>
              <span class="ml-auto font-mono text-[10px] text-emerald-300/70">
                {{ trace.trace_source || 'runtime' }}
              </span>
            </header>
            <div class="grid grid-cols-1 gap-3 px-4 py-3 md:grid-cols-4">
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">Route</div>
                <div class="mt-1 font-mono text-sm text-white">{{ routeLabel(trace) }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">Query type</div>
                <div class="mt-1 font-mono text-sm text-gray-200">{{ trace.query_type || '—' }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">Latency</div>
                <div class="mt-1 font-mono text-sm text-gray-200">{{ trace.latency_profile || 'default' }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">Controls</div>
                <div class="mt-1 font-mono text-sm text-gray-200">{{ qualityLine(trace) }}</div>
              </div>
            </div>
            <div class="px-4 pb-3 grid gap-2 md:grid-cols-2">
              <div class="rounded border border-white/5 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">Reason</div>
                <p class="mt-1 text-sm text-gray-300">{{ trace.route_reason || trace.summary || 'Runtime route selected.' }}</p>
              </div>
              <div class="rounded border border-white/5 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">Tradeoff</div>
                <p class="mt-1 text-sm text-gray-300">{{ trace.tradeoff || 'No tradeoff recorded.' }}</p>
              </div>
            </div>
            <details class="mx-4 mb-4 rounded border border-white/5 bg-black/20">
              <summary class="cursor-pointer px-3 py-2 text-[10px] uppercase tracking-wider text-gray-400 font-mono">
                Decision JSON
              </summary>
              <pre class="px-3 pb-3 text-[10px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ asJson(trace) }}</pre>
            </details>
          </section>
        }

        <!-- Skill timeline -->
        <section class="rounded-lg border border-white/5 bg-white/[0.02] mb-6">
          <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
            <app-icon name="list-tree" [size]="14" class="text-cyan-400" />
            <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">
              Skill trail
            </h2>
            <span class="ml-auto font-mono text-[10px] text-gray-500">
              {{ skillInvocations().length }} step{{ skillInvocations().length === 1 ? '' : 's' }}
            </span>
          </header>
          @if (skillInvocations().length === 0) {
            <div class="px-4 py-8 text-center text-xs text-gray-500 font-mono">
              No skill invocations captured for this run.
            </div>
          } @else {
            <ol class="divide-y divide-white/5">
              @for (inv of skillInvocations(); track $index; let idx = $index) {
                <li class="px-4 py-3 flex items-start gap-3">
                  <div class="flex-shrink-0 w-6 h-6 rounded-full bg-white/5 ring-1 ring-white/10 flex items-center justify-center font-mono text-[10px] text-gray-400">
                    {{ idx + 1 }}
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-baseline justify-between gap-3">
                      <div class="font-mono text-sm text-white truncate">
                        {{ inv.skill_slug || inv.skill_id || 'skill' }}
                      </div>
                      <div class="flex items-center gap-2 flex-shrink-0">
                        <span
                          class="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded"
                          [class.text-emerald-300]="inv.status === 'completed'"
                          [class.bg-emerald-500\\/10]="inv.status === 'completed'"
                          [class.text-red-300]="inv.status === 'failed'"
                          [class.bg-red-500\\/10]="inv.status === 'failed'"
                          [class.text-cyan-300]="inv.status === 'running'"
                          [class.bg-cyan-500\\/10]="inv.status === 'running'"
                          [class.text-gray-400]="inv.status === 'pending' || !inv.status"
                          [class.bg-white\\/5]="inv.status === 'pending' || !inv.status"
                        >
                          {{ inv.status || 'pending' }}
                        </span>
                        @if (inv.latency_ms != null) {
                          <span class="text-[10px] font-mono text-gray-400 tabular-nums">
                            {{ formatDuration(inv.latency_ms) }}
                          </span>
                        }
                        @if (inv.cost != null && inv.cost > 0) {
                          <span class="text-[10px] font-mono text-amber-300 tabular-nums">
                            \${{ inv.cost.toFixed(4) }}
                          </span>
                        }
                      </div>
                    </div>
                    @if (inv.started_at) {
                      <div class="text-[10px] font-mono text-gray-500 mt-0.5">
                        {{ formatTime(inv.started_at) }}
                      </div>
                    }
                    @if (inv.error) {
                      <div class="mt-2 text-[11px] font-mono text-red-300/90 bg-red-500/5 rounded px-2 py-1.5 break-all">
                        {{ inv.error }}
                      </div>
                    }
                    @if (hasInvocationDetails(inv)) {
                      <details class="mt-2 rounded border border-white/5 bg-black/20">
                        <summary class="cursor-pointer px-2 py-1.5 text-[10px] uppercase tracking-wider text-gray-400 font-mono">
                          Invocation audit
                        </summary>
                        <pre class="px-2 pb-2 text-[10px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ invocationDetailsJson(inv) }}</pre>
                      </details>
                    }
                  </div>
                </li>
              }
            </ol>
          }
        </section>

        <!-- Payloads -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <section class="rounded-lg border border-white/5 bg-white/[0.02]">
            <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <app-icon name="arrow-right-to-line" [size]="14" class="text-cyan-300" />
              <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">Input</h2>
            </header>
            <pre class="px-4 py-3 text-[11px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ inputJson() }}</pre>
          </section>
          <section class="rounded-lg border border-white/5 bg-white/[0.02]">
            <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <app-icon name="target" [size]="14" class="text-emerald-300" />
              <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">Outcome</h2>
            </header>
            <pre class="px-4 py-3 text-[11px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ outcomeJson() }}</pre>
          </section>
        </div>

        @if (checkpoints().length > 0) {
          <section class="rounded-lg border border-white/5 bg-white/[0.02] mt-3">
            <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <app-icon name="bookmark" [size]="14" class="text-sky-300" />
              <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">Checkpoints</h2>
              <span class="ml-auto font-mono text-[10px] text-gray-500">{{ checkpoints().length }}</span>
            </header>
            <ul class="divide-y divide-white/5">
              @for (cp of checkpoints(); track $index) {
                <li class="px-4 py-2 text-[11px] font-mono text-gray-300 break-all">
                  {{ asJson(cp) }}
                </li>
              }
            </ul>
          </section>
        }
      }
    </ck-page-frame>
  `,
})
export class RunViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly zoom = inject(ZoomContextService);

  readonly runId = signal<string>('');
  readonly run = signal<Run | null>(null);
  readonly loading = signal(false);

  readonly overrideMode = signal(false);
  readonly overrideValue = signal<number>(0);
  readonly overrideNote = signal<string>('');
  readonly submittingOverride = signal(false);

  readonly skillInvocations = computed<SkillInvocation[]>(
    () => this.run()?.skill_invocations ?? [],
  );
  readonly checkpoints = computed<Array<Record<string, unknown>>>(
    () => this.run()?.checkpoints ?? [],
  );

  readonly titleLabel = computed(() => {
    const id = this.runId();
    if (!id) return 'Run';
    return `Run ${id.slice(0, 12)}…`;
  });

  readonly descriptionLabel = computed(() => {
    const r = this.run();
    if (!r) return 'Drill-down on a single execution.';
    const bits: string[] = [];
    if (r.trigger) bits.push(`Trigger: ${r.trigger}`);
    if (r.system_id) bits.push(`System: ${r.system_id}`);
    if (r.started_at) bits.push(`Started: ${this.formatTime(r.started_at)}`);
    return bits.join(' · ') || 'Drill-down on a single execution.';
  });

  readonly inputJson = computed(() => {
    const r = this.run() as (Run & { input?: unknown; input_ref?: unknown }) | null;
    return this.asJson(r?.input ?? r?.input_ref ?? {});
  });

  readonly outcomeJson = computed(() => this.asJson(this.run()?.outcome ?? {}));

  readonly retrievalDecisionTrace = computed<RetrievalDecisionTrace | null>(() => {
    const run = this.run();
    if (!run) return null;
    const output = run.output_ref ?? {};
    const direct = this.traceFrom(output);
    if (direct) return direct;
    for (const invocation of run.skill_invocations ?? []) {
      const trace =
        this.traceFrom(invocation.metrics)
        ?? this.traceFrom(invocation.output_ref)
        ?? this.traceFrom(invocation.trace);
      if (trace) return trace;
    }
    return null;
  });

  ngOnInit(): void {
    this.route.paramMap.subscribe((params) => {
      const id = params.get('runId') ?? '';
      if (!id) {
        this.router.navigate(['/runs']);
        return;
      }
      this.runId.set(id);
      this.zoom.setCurrentRun(id);
      this.refresh();
    });
  }

  refresh(): void {
    const id = this.runId();
    if (!id) return;
    this.loading.set(true);
    this.canonical.getRun(id).subscribe({
      next: (r) => {
        this.run.set(r);
        if (r?.system_id) this.zoom.setCurrentSystem(r.system_id);
        this.loading.set(false);
      },
      error: () => {
        this.run.set(null);
        this.loading.set(false);
      },
    });
  }

  formatTime(ts: string | undefined): string {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return ts;
    }
  }

  formatDuration(ms: number): string {
    if (!Number.isFinite(ms)) return '—';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  asJson(v: unknown): string {
    if (v === undefined || v === null) return '{}';
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return String(v);
    }
  }

  routeLabel(trace: RetrievalDecisionTrace): string {
    return String(trace.selected_route || 'retrieval').replace(/_/g, ' ');
  }

  qualityLine(trace: RetrievalDecisionTrace): string {
    const quality = this.isRecord(trace.quality_controls) ? trace.quality_controls : {};
    const sparse = quality['sparse_status'] ? `sparse ${quality['sparse_status']}` : null;
    const cross = quality['cross_encoder_status'] ? `cross ${quality['cross_encoder_status']}` : null;
    return [sparse, cross].filter(Boolean).join(' · ') || '—';
  }

  private traceFrom(payload?: Record<string, unknown> | null): RetrievalDecisionTrace | null {
    if (!this.isRecord(payload)) return null;
    if (this.isRecord(payload['retrieval_decision_trace'])) {
      return payload['retrieval_decision_trace'] as RetrievalDecisionTrace;
    }
    const metrics = payload['retrieval_metrics'];
    if (this.isRecord(metrics) && this.isRecord(metrics['retrieval_decision_trace'])) {
      return metrics['retrieval_decision_trace'] as RetrievalDecisionTrace;
    }
    return null;
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  hasInvocationDetails(inv: SkillInvocation): boolean {
    return !!(
      inv.input_ref ||
      inv.output_ref ||
      inv.metrics ||
      inv.trace
    );
  }

  invocationDetailsJson(inv: SkillInvocation): string {
    return this.asJson({
      input_ref: inv.input_ref ?? {},
      output_ref: inv.output_ref ?? {},
      metrics: inv.metrics ?? {},
      trace: inv.trace ?? {},
    });
  }

  asInput(ev: Event): HTMLInputElement {
    return ev.target as HTMLInputElement;
  }

  enableOverride(): void {
    const current = this.run()?.outcome?.value_estimated ?? 0;
    this.overrideValue.set(Number(current) || 0);
    this.overrideNote.set(this.run()?.outcome?.operator_value_note ?? '');
    this.overrideMode.set(true);
  }

  cancelOverride(): void {
    this.overrideMode.set(false);
  }

  submitOverride(): void {
    const id = this.runId();
    if (!id || this.submittingOverride()) return;
    this.submittingOverride.set(true);
    this.canonical
      .overrideRunOutcome(id, {
        value: this.overrideValue(),
        note: this.overrideNote() || undefined,
      })
      .subscribe({
        next: (updated) => {
          if (updated) this.run.set(updated as unknown as Run);
          this.submittingOverride.set(false);
          this.overrideMode.set(false);
        },
        error: () => {
          this.submittingOverride.set(false);
        },
      });
  }
}
