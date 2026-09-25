import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import { Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import { ThinkingOrbComponent } from '@app/shared/cockpit';
import { RunWaterfallComponent } from './run-waterfall.component';
import { arrivalProvenanceState } from './arrival-provenance';
import {
  invocationRetries,
  invocationTokens,
  traceStepSummary,
} from './run-trace.vm';
import { observabilityNumber, observabilityText } from '../observability/observability-labels';

/**
 * Trace page (O4) — where time is spent on one Run. Cascade lives only here.
 */
@Component({
  selector: 'app-run-trace',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RunWaterfallComponent, ThinkingOrbComponent],
  template: `
    <section class="trace-page" data-testid="run-trace-page" aria-labelledby="trace-title">
      <header class="trace-head">
        <div>
          <h2 id="trace-title">{{ i18n.t('runs.trace.title') }}</h2>
          <p>{{ i18n.t('runs.trace.subtitle') }}</p>
        </div>
        @if (running()) {
          <div class="orb" data-testid="run-trace-orb">
            <ck-thinking-orb state="working" [size]="20" [label]="i18n.t('runs.trace.orb')" />
            <span>{{ i18n.t('runs.trace.orb') }}</span>
          </div>
        }
      </header>

      <dl class="summary">
        <div>
          <dt>{{ i18n.t('runs.trace.total') }}</dt>
          <dd>{{ seconds(summary().totalMs) }} s</dd>
        </div>
        <div>
          <dt>{{ i18n.t('runs.trace.longest') }}</dt>
          <dd>
            {{ summary().longestLabel || '—' }}
            @if (summary().longestMs > 0) {
              <span class="copper"> · {{ seconds(summary().longestMs) }} s</span>
            }
          </dd>
        </div>
        <div>
          <dt>{{ i18n.t('runs.detail.kpi.status') }}</dt>
          <dd>{{ status(run().status) }}</dd>
        </div>
      </dl>

      <app-run-waterfall
        [run]="run()"
        [highlightLongest]="true"
        [fromTraceId]="run().id"
      />

      <section class="attrs" aria-label="{{ i18n.t('runs.trace.attributes') }}">
        <h3>{{ i18n.t('runs.trace.attributes') }}</h3>
        @for (inv of invocations(); track inv.id || $index) {
          <article class="attr-row" [class.failed]="inv.status === 'failed'">
            <button type="button" class="skill" (click)="openInvocation(inv)" [disabled]="!inv.id">
              {{ inv.skill_slug || inv.skill_id || inv.id || '—' }}
            </button>
            <span>{{ status(inv.status) }}</span>
            <span class="tabular">{{ i18n.t('runs.trace.retries') }}: {{ retries(inv) }}</span>
            <span class="tabular">{{ i18n.t('runs.trace.tokens') }}: {{ tokensLabel(inv) }}</span>
          </article>
        } @empty {
          <p>{{ i18n.t('runs.detail.trail.empty') }}</p>
        }
      </section>
    </section>
  `,
  styles: [
    `
      :host {
        display: block;
        margin: 24px 0;
      }
      .trace-page {
        padding: 24px;
        background: var(--ck-bg-panel);
        border: 1px solid var(--ck-stroke-2);
        border-radius: 6px;
        color: var(--ck-fg-1);
      }
      .trace-head {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: flex-start;
        margin-bottom: 20px;
      }
      h2 {
        font-size: 22px;
        font-weight: 600;
        margin: 0 0 6px;
      }
      p {
        margin: 0;
        color: var(--ck-fg-3);
        font-size: 13px;
      }
      .orb {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-family: var(--ck-font-mono);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ck-fg-2);
      }
      .summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 16px;
        margin: 0 0 8px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--ck-stroke-2);
      }
      dt {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
        margin-bottom: 4px;
      }
      dd {
        margin: 0;
        font-size: 14px;
      }
      .copper {
        color: var(--ck-copper);
      }
      .attrs {
        margin-top: 8px;
      }
      h3 {
        font-size: 16px;
        font-weight: 600;
        margin: 0 0 12px;
      }
      .attr-row {
        display: grid;
        grid-template-columns: minmax(120px, 1.4fr) 1fr 1fr 1fr;
        gap: 12px;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--ck-stroke-2);
        font-size: 13px;
      }
      .attr-row.failed {
        color: var(--ck-signal-neg);
      }
      .skill {
        background: none;
        border: 0;
        padding: 0;
        text-align: left;
        color: var(--ck-signal-cool);
        font-family: var(--ck-font-mono);
        font-size: 12px;
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 2px;
      }
      .skill:disabled {
        color: var(--ck-fg-2);
        text-decoration: none;
        cursor: default;
      }
      .tabular {
        font-variant-numeric: tabular-nums;
      }
      @media (max-width: 700px) {
        .summary,
        .attr-row {
          grid-template-columns: 1fr;
        }
      }
    `,
  ],
})
export class RunTraceComponent {
  readonly run = input.required<Run>();
  readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);

  readonly invocations = computed(() => this.run().skill_invocations || []);
  readonly summary = computed(() => traceStepSummary(this.run()));
  readonly running = computed(() => {
    const status = this.run().status;
    return status === 'running' || status === 'pending' || status === 'hitl_pending' || status === 'debug_pending';
  });

  seconds(ms: number): string {
    return observabilityNumber(ms / 1000, this.i18n.locale(), 2);
  }

  status(value: unknown): string {
    return observabilityText(this.i18n, 'status', value);
  }

  retries(inv: SkillInvocation): number {
    return invocationRetries(inv);
  }

  tokensLabel(inv: SkillInvocation): string {
    const tokens = invocationTokens(inv);
    return tokens == null ? '—' : observabilityNumber(tokens, this.i18n.locale(), 0);
  }

  openInvocation(inv: SkillInvocation): void {
    if (!inv.id) return;
    const runId = this.run().id;
    void this.router.navigateByUrl(
      this.navigation.objectUrl('skill_invocation', inv.id, { runId }),
      {
        state: arrivalProvenanceState({
          kind: 'trace',
          traceId: runId,
          backUrl: `/runs/${encodeURIComponent(runId)}?facet=trace`,
        }),
      },
    );
  }
}
