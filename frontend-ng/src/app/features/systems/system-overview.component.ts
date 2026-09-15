import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import type { SystemOverview } from '@app/core/canonical-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';

@Component({
  selector: 'app-system-overview',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (loading) {
      <div class="overview-loading" aria-live="polite" aria-label="Loading System overview">
        <div class="skeleton skeleton-wide"></div>
        <div class="skeleton"></div>
        <div class="skeleton skeleton-short"></div>
      </div>
    } @else if (error || !overview) {
      <section class="overview-error" role="alert">
        <app-icon name="alert-triangle" [size]="18" />
        <div>
          <h2>Overview unavailable</h2>
          <p>Agentium could not load this System's operational facts. No fallback metrics are shown.</p>
        </div>
        <button type="button" class="ck-btn-quiet" (click)="retry.emit()">Try again</button>
      </section>
    } @else {
      <div class="overview" data-testid="canonical-system-overview">
        <section class="readiness" [attr.data-state]="overview.readiness.state">
          <div class="readiness-mark" aria-hidden="true">
            <app-icon [name]="readinessIcon()" [size]="20" />
          </div>
          <div class="readiness-copy">
            <p class="eyebrow">Current state</p>
            <h2>{{ overview.readiness.label }}</h2>
            <p>{{ readinessSummary() }}</p>
          </div>
          <button
            type="button"
            class="ck-cta primary-action"
            (click)="navigate.emit(overview.readiness.primary_action.href)"
          >
            {{ overview.readiness.primary_action.label }}
            <app-icon name="arrow-right" [size]="14" />
          </button>
        </section>

        @if (overview.readiness.blockers.length > 0) {
          <section class="blockers" aria-labelledby="system-blockers-title">
            <h3 id="system-blockers-title">What needs attention</h3>
            <ul>
              @for (blocker of overview.readiness.blockers; track blocker.code) {
                <li>
                  <app-icon name="alert-circle" [size]="16" />
                  <span>{{ blocker.message }}</span>
                  <button type="button" (click)="navigate.emit(blocker.action.href)">{{ blocker.action.label }}</button>
                </li>
              }
            </ul>
          </section>
        }

        <section class="facts" aria-label="System evidence">
          <div class="fact-group run-facts">
            <div class="section-heading">
              <div>
                <p class="eyebrow">Last {{ overview.window }}</p>
                <h3>Runs</h3>
              </div>
              <button type="button" (click)="navigate.emit('/systems/' + overview.system.id + '?facet=runs')">View all</button>
            </div>
            <dl>
              <div>
                <dt>Total</dt>
                <dd>{{ overview.runs.total }}</dd>
              </div>
              <div>
                <dt>Success</dt>
                <dd>{{ overview.runs.success_rate === null ? 'Not measured' : overview.runs.success_rate + '%' }}</dd>
              </div>
              <div>
                <dt>Failed</dt>
                <dd [class.fact-negative]="overview.runs.failed > 0">{{ overview.runs.failed }}</dd>
              </div>
              <div>
                <dt>Average latency</dt>
                <dd>{{ overview.runs.avg_latency_ms === null ? 'Not measured' : overview.runs.avg_latency_ms + ' ms' }}</dd>
              </div>
            </dl>
            @if (overview.runs.latest; as latest) {
              <div class="latest-run">
                <span class="run-status" [attr.data-status]="latest.status">{{ latest.status }}</span>
                <span>Latest run</span>
                <code>{{ latest.id.slice(0, 8) }}</code>
                <span class="latest-time">{{ formatDate(latest.started_at) }}</span>
              </div>
            } @else {
              <p class="empty-fact">No runs yet. Use the action above when this System is ready.</p>
            }
          </div>

          <div class="fact-group evidence-facts">
            <div class="section-heading">
              <div>
                <p class="eyebrow">Evidence</p>
                <h3>Published and measured</h3>
              </div>
            </div>
            <dl>
              <div>
                <dt>Flow</dt>
                <dd>{{ publicationLabel() }}</dd>
              </div>
              <div>
                <dt>Quality</dt>
                <dd>{{ overview.quality.score === null ? 'Not measured' : overview.quality.score + ' / 100' }}</dd>
              </div>
              <div>
                <dt>Quality samples</dt>
                <dd>{{ overview.quality.sample_count }}</dd>
              </div>
              <div>
                <dt>Window generated</dt>
                <dd>{{ formatDate(overview.generated_at) }}</dd>
              </div>
            </dl>
            <p class="evidence-note">Values appear only when Agentium has System-scoped evidence.</p>
          </div>
        </section>
      </div>
    }
  `,
  styles: [`
    :host { display: block; }
    .overview { display: grid; gap: 1.25rem; }
    .readiness { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 1rem; align-items: center; padding: 1.25rem; border: 1px solid var(--ck-stroke-2); border-radius: .65rem; background: var(--ck-bg-panel); }
    .readiness[data-state='ready'] { border-color: var(--ck-status-ok-line); }
    .readiness[data-state='blocked'], .readiness[data-state='needs_setup'] { border-color: var(--ck-status-warn-line); }
    .readiness-mark { display: grid; place-items: center; width: 2.5rem; height: 2.5rem; border-radius: 50%; color: var(--ck-fg-2); background: var(--ck-bg-inset); }
    .readiness[data-state='ready'] .readiness-mark { color: var(--ck-status-ok-fg); background: var(--ck-status-ok-bg); }
    .readiness[data-state='blocked'] .readiness-mark, .readiness[data-state='needs_setup'] .readiness-mark { color: var(--ck-status-warn-fg); background: var(--ck-status-warn-bg); }
    .eyebrow { margin: 0 0 .3rem; color: var(--ck-fg-4); font: 600 .66rem/1 var(--ck-font-mono); letter-spacing: .12em; text-transform: uppercase; }
    h2, h3, p { margin-top: 0; }
    h2 { margin-bottom: .3rem; color: var(--ck-fg-1); font-size: 1.15rem; font-weight: 650; }
    h3 { margin-bottom: 0; color: var(--ck-fg-1); font-size: .95rem; font-weight: 650; }
    .readiness-copy > p:last-child { max-width: 70ch; margin-bottom: 0; color: var(--ck-fg-3); font-size: .84rem; line-height: 1.5; }
    .primary-action { display: inline-flex; align-items: center; gap: .45rem; padding: .65rem .85rem; border-radius: .4rem; font-size: .82rem; font-weight: 650; white-space: nowrap; }
    .blockers { padding: 1rem 1.1rem; border: 1px solid var(--ck-status-warn-line); border-radius: .55rem; background: var(--ck-status-warn-bg); }
    .blockers h3 { margin-bottom: .7rem; }
    .blockers ul { display: grid; gap: .6rem; margin: 0; padding: 0; list-style: none; }
    .blockers li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: .6rem; align-items: start; color: var(--ck-fg-2); font-size: .8rem; line-height: 1.45; }
    .blockers li app-icon { color: var(--ck-status-warn-fg); margin-top: .1rem; }
    .blockers button, .section-heading button { padding: 0; border: 0; color: var(--ck-signal-cool); background: transparent; font-size: .76rem; font-weight: 600; white-space: nowrap; cursor: pointer; }
    .facts { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(17rem, .85fr); gap: 1.25rem; }
    .fact-group { padding-top: .25rem; }
    .run-facts { padding-right: 1.25rem; border-right: 1px solid var(--ck-stroke-soft); }
    .section-heading { display: flex; align-items: end; justify-content: space-between; gap: 1rem; padding-bottom: .85rem; border-bottom: 1px solid var(--ck-stroke-soft); }
    dl { margin: 0; }
    dl > div { display: grid; grid-template-columns: minmax(8rem, 1fr) auto; gap: 1rem; padding: .7rem 0; border-bottom: 1px solid var(--ck-stroke-soft); }
    dt { color: var(--ck-fg-4); font-size: .76rem; }
    dd { margin: 0; color: var(--ck-fg-1); font: 600 .78rem/1.35 var(--ck-font-mono); text-align: right; }
    .fact-negative { color: var(--ck-status-neg-fg); }
    .latest-run { display: flex; align-items: center; gap: .55rem; margin-top: .85rem; color: var(--ck-fg-3); font-size: .74rem; }
    .run-status { padding: .18rem .4rem; border-radius: .3rem; color: var(--ck-fg-2); background: var(--ck-bg-inset); font: 600 .65rem/1 var(--ck-font-mono); text-transform: uppercase; }
    .run-status[data-status='completed'] { color: var(--ck-status-ok-fg); background: var(--ck-status-ok-bg); }
    .run-status[data-status='failed'] { color: var(--ck-status-neg-fg); background: var(--ck-status-neg-bg); }
    .latest-run code { color: var(--ck-fg-2); }
    .latest-time { margin-left: auto; color: var(--ck-fg-4); }
    .empty-fact, .evidence-note { margin: .85rem 0 0; color: var(--ck-fg-4); font-size: .75rem; line-height: 1.45; }
    .overview-error { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: .8rem; align-items: center; padding: 1rem; border: 1px solid var(--ck-status-neg-line); border-radius: .55rem; color: var(--ck-status-neg-fg); background: var(--ck-status-neg-bg); }
    .overview-error h2 { margin-bottom: .2rem; font-size: .95rem; }
    .overview-error p { margin-bottom: 0; color: var(--ck-fg-3); font-size: .78rem; }
    .overview-error button { padding: .5rem .7rem; }
    .overview-loading { display: grid; gap: .8rem; padding: 1.25rem; border: 1px solid var(--ck-stroke-soft); border-radius: .55rem; }
    .skeleton { width: 46%; height: .8rem; border-radius: .3rem; background: var(--ck-bg-inset); animation: pulse 1.6s ease-in-out infinite; }
    .skeleton-wide { width: 72%; height: 1.2rem; }
    .skeleton-short { width: 28%; }
    @keyframes pulse { 50% { opacity: .45; } }
    @media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
    @media (max-width: 800px) {
      .readiness, .overview-error { grid-template-columns: auto minmax(0, 1fr); }
      .primary-action, .overview-error button { grid-column: 1 / -1; justify-content: center; }
      .facts { grid-template-columns: 1fr; }
      .run-facts { padding-right: 0; padding-bottom: 1.25rem; border-right: 0; border-bottom: 1px solid var(--ck-stroke-soft); }
      .blockers li { grid-template-columns: auto minmax(0, 1fr); }
      .blockers button { grid-column: 2; justify-self: start; }
    }
  `],
})
export class SystemOverviewComponent {
  @Input() overview: SystemOverview | null = null;
  @Input() loading = false;
  @Input() error = false;
  @Output() readonly retry = new EventEmitter<void>();
  @Output() readonly navigate = new EventEmitter<string>();

  readinessIcon(): string {
    switch (this.overview?.readiness.state) {
      case 'ready': return 'check-circle-2';
      case 'paused': return 'pause-circle';
      case 'retired': return 'archive';
      default: return 'alert-triangle';
    }
  }

  readinessSummary(): string {
    if (!this.overview) return '';
    switch (this.overview.readiness.state) {
      case 'ready': return 'The active published Flow passed runtime readiness checks.';
      case 'paused': return 'Existing history remains available, but new runs are disabled.';
      case 'retired': return 'This System is read-only and no longer accepts work.';
      default: return this.overview.readiness.blockers[0]?.message ?? 'Complete setup before running this System.';
    }
  }

  publicationLabel(): string {
    const version = this.overview?.publication.version_number;
    return version === null || version === undefined ? 'Not published' : `Version ${version}`;
  }

  formatDate(value: string | null): string {
    if (!value) return 'Not measured';
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? 'Not measured'
      : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }
}
