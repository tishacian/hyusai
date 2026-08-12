import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { MicroBarComponent } from './micro-bar.component';
import { StatReadoutComponent } from './stat-readout.component';
import { TagComponent } from './tag.component';
import { formatYieldPercent } from './yield-format';
import type { Outcome, Run, SkillInvocation } from '@app/core/canonical-api.service';

/**
 * Canonical Run Outcome card — the block that turns a raw Run into
 * the decision-grade summary the Hypervisor and the System view live on:
 *
 *   DECISION   CONFIDENCE  VALUE  COST  EFFICIENCY
 *
 * Rendered as cockpit readouts (mono ALL-CAPS labels, tabular numerics,
 * semantic colours) with the skill invocation ledger rolled up below.
 */
@Component({
  selector: 'ck-run-outcome-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MicroBarComponent, StatReadoutComponent, TagComponent],
  template: `
    <div class="ck-surface rounded-md" style="padding: 16px 18px; display:flex; flex-direction:column; gap:14px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <div style="display:flex; align-items:center; gap:8px;">
          <ck-tag [tone]="statusTone()" variant="soft">{{ run.status || 'pending' }}</ck-tag>
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
            RUN · {{ shortId() }}
          </span>
          @if (run.trigger) {
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
              · {{ run.trigger }}
            </span>
          }
        </div>
        <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-3);">
          {{ durationLabel() }}
        </span>
      </div>

      <div style="display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:18px;">
        <ck-stat-readout
          label="DECISION"
          [value]="decisionLabel()"
          [tone]="decisionTone()"
          [size]="18"
        />
        <ck-stat-readout
          label="CONFIDENCE"
          [value]="percentage(outcome.confidence)"
          [tone]="confidenceTone()"
          [size]="18"
        />
        <ck-stat-readout
          label="VALUE"
          [value]="currency(outcome.value_estimated)"
          tone="pos"
          [size]="18"
        />
        <ck-stat-readout
          label="COST"
          [value]="currency(outcome.cost_internal)"
          tone="cool"
          [size]="18"
        />
        <ck-stat-readout
          label="EFFICIENCY"
          [value]="efficiencyLabel(outcome.efficiency)"
          [tone]="efficiencyTone()"
          [size]="18"
        />
      </div>

      @if (outcome.confidence !== null && outcome.confidence !== undefined) {
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); min-width:78px;">CONFIDENCE</span>
          <ck-micro-bar
            [value]="confidenceRatio() * 100"
            [max]="100"
            [width]="160"
            [tone]="confidenceTone() === 'neg' ? 'neg' : confidenceTone() === 'warn' ? 'warn' : 'pos'"
            [glow]="true"
          />
          <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-3);">
            {{ percentage(outcome.confidence) }}
          </span>
        </div>
      }

      @if (run.skill_invocations && run.skill_invocations.length > 0) {
        <details [open]="expanded()">
          <summary
            (click)="toggleExpanded($event)"
            class="ck-mono"
            style="cursor:pointer; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3); list-style:none;"
          >
            SKILL LEDGER · {{ run.skill_invocations.length }}
          </summary>
          <ul style="margin-top:10px; display:flex; flex-direction:column; gap:4px; list-style:none; padding:0;">
            @for (inv of run.skill_invocations; track inv.id || inv.skill_slug || $index) {
              <li
                style="display:grid; grid-template-columns: 20px minmax(0, 1fr) 60px 70px; gap:12px; align-items:center; padding:6px 8px; border-radius:4px; background:var(--ck-bg-inset);"
              >
                <span
                  [style.backgroundColor]="invocationDot(inv)"
                  style="width:6px; height:6px; border-radius:999px; justify-self:center;"
                ></span>
                <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                  {{ inv.skill_slug || inv.skill_id || '—' }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-3); text-align:right;">
                  {{ inv.latency_ms != null ? inv.latency_ms + ' ms' : '—' }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-3); text-align:right;">
                  {{ inv.cost != null ? currencyShort(inv.cost) : '—' }}
                </span>
              </li>
            }
          </ul>
        </details>
      }

      @if (run.error) {
        <div
          class="ck-mono"
          style="font-size:11px; color:var(--ck-status-neg-fg); background:var(--ck-status-neg-bg); padding:8px 10px; border-radius:4px;"
        >
          ERROR · {{ run.error }}
        </div>
      }
    </div>
  `,
})
export class RunOutcomeCardComponent {
  @Input({ required: true }) run!: Run;

  protected readonly expanded = signal(false);

  get outcome(): Outcome {
    return this.run?.outcome ?? {};
  }

  toggleExpanded(ev: Event) {
    ev.preventDefault();
    this.expanded.update((v) => !v);
  }

  protected shortId = computed(() => (this.run?.id ?? '').slice(0, 8));

  protected durationLabel = computed(() => {
    const d = this.run?.duration_ms;
    if (d == null) return '—';
    if (d < 1000) return `${d} ms`;
    return `${(d / 1000).toFixed(2)} s`;
  });

  protected decisionLabel = computed(() => {
    const d = this.outcome?.decision;
    if (!d) return this.run?.status === 'failed' ? 'BLOCKED' : '—';
    return String(d).toUpperCase();
  });

  protected decisionTone = computed(() => {
    const d = (this.outcome?.decision || '').toLowerCase();
    if (this.run?.status === 'failed') return 'neg' as const;
    if (!d) return 'neutral' as const;
    if (['approve', 'approved', 'accept', 'ok', 'success', 'completed'].includes(d)) return 'pos' as const;
    if (['reject', 'rejected', 'block', 'blocked', 'deny'].includes(d)) return 'neg' as const;
    if (['review', 'hitl', 'escalate', 'flag', 'warn'].includes(d)) return 'warn' as const;
    return 'cool' as const;
  });

  protected confidenceTone = computed(() => {
    const c = this.outcome?.confidence;
    if (c == null) return 'neutral' as const;
    if (c >= 0.8) return 'pos' as const;
    if (c >= 0.6) return 'cool' as const;
    if (c >= 0.4) return 'warn' as const;
    return 'neg' as const;
  });

  protected confidenceRatio = computed(() => {
    const c = this.outcome?.confidence;
    if (c == null) return 0;
    return Math.max(0, Math.min(1, c));
  });

  protected efficiencyTone = computed(() => {
    const e = this.outcome?.efficiency;
    if (e == null) return 'neutral' as const;
    if (e >= 1.5) return 'pos' as const;
    if (e >= 1) return 'cool' as const;
    if (e >= 0.5) return 'warn' as const;
    return 'neg' as const;
  });

  protected statusTone = computed(() => {
    switch (this.run?.status) {
      case 'completed': return 'pos' as const;
      case 'failed':    return 'neg' as const;
      case 'running':   return 'cool' as const;
      case 'pending':   return 'neutral' as const;
      case 'cancelled': return 'warn' as const;
      default:          return 'neutral' as const;
    }
  });

  protected percentage(value: number | null | undefined): string {
    if (value == null) return '—';
    return `${Math.round(value * 100)}%`;
  }

  protected efficiencyLabel(value: number | null | undefined): string {
    return formatYieldPercent(value);
  }

  protected currency(value: number | null | undefined): string {
    if (value == null) return '—';
    const sym = (this.outcome?.currency === 'EUR') ? '€' : '$';
    if (Math.abs(value) >= 1000) return `${sym}${(value / 1000).toFixed(1)}k`;
    return `${sym}${value.toFixed(2)}`;
  }

  protected currencyShort(value: number): string {
    const sym = (this.outcome?.currency === 'EUR') ? '€' : '$';
    if (value < 0.01) return `${sym}${value.toFixed(4)}`;
    if (value < 1) return `${sym}${value.toFixed(3)}`;
    return `${sym}${value.toFixed(2)}`;
  }

  protected invocationDot(inv: SkillInvocation): string {
    switch (inv.status) {
      case 'completed': return 'var(--ck-signal-pos)';
      case 'failed':    return 'var(--ck-signal-neg)';
      case 'running':   return 'var(--ck-signal-cool)';
      default:          return 'var(--ck-fg-4)';
    }
  }
}
