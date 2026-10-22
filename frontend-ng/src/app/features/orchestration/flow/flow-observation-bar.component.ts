import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowObservationService } from './flow-observation.service';
import { FlowObservationWindowsService } from './flow-observation-windows.service';
import { observationRunIngress, observationRunVersion, type FlowObservationRun } from './flow-observation.vm';
import { runStatusLabel } from '@app/core/run-follow-up';

@Component({
  selector: 'app-flow-observation-bar',
  standalone: true,
  imports: [IconComponent, NavLinkDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-observation-ui.scss',
  template: `
    <section data-testid="flow-observation-bar" class="fo-bar" [attr.aria-label]="i18n.t('flow.observation.title')">
      <div class="fo-bar__identity"><app-icon name="eye" [size]="15" /><strong>{{ i18n.t('flow.observation.title') }}</strong><span>{{ i18n.t('flow.observation.read_only') }}</span></div>
      <label class="fo-bar__picker">
        <span class="fo-sr-only">{{ i18n.t('flow.observation.run') }}</span>
        <select data-testid="flow-observation-run-select" [value]="observation.selectedRunId() ?? ''" [disabled]="observation.listStatus() === 'loading' || !observation.runs().length" (change)="selectRun($event)">
          @if (!observation.runs().length) { <option value="">{{ i18n.t(observation.listStatus() === 'loading' ? 'common.loading' : 'flow.observation.no_runs') }}</option> }
          @for (run of observation.runs(); track run.id) { <option [value]="run.id" [selected]="observation.selectedRunId()===run.id">{{ runLabel(run) }}</option> }
        </select>
      </label>
      <div class="fo-actions">
        <button type="button" class="fo-icon" (click)="observation.refresh()" [disabled]="observation.listStatus() === 'loading'" [attr.aria-label]="i18n.t('common.refresh')" [title]="i18n.t('common.refresh')"><app-icon name="refresh-cw" [size]="14" /></button>
        @if (observation.currentRun(); as run) { <a class="fo-link" [navLink]="{type:'run',ref:run.id}">{{ i18n.t('flow.observation.open_run') }}<app-icon name="arrow-up-right" [size]="13" /></a> }
        @if (windows.pins().length) {
          <details class="fo-pins-menu"><summary>{{ i18n.t('flow.observation.pins_count',{count:windows.pins().length}) }}</summary><div>
            @for (pin of windows.pins(); track pin.id) { <button type="button" (click)="windows.show(pin)">{{ pin.title }}</button> }
            <button type="button" (click)="windows.clear()">{{ i18n.t('flow.observation.clear_pins') }}</button>
          </div></details>
        }
        <button type="button" class="fo-icon" (click)="observation.close()" [attr.aria-label]="i18n.t('flow.observation.close')" [title]="i18n.t('flow.observation.close')"><app-icon name="x" [size]="14" /></button>
      </div>
      <div class="fo-bar__context" role="status" [attr.data-match]="flowMatch()">
        @if (observation.error()) { <span>{{ i18n.t(observation.error() === 'forbidden' ? 'flow.observation.forbidden' : 'flow.observation.unavailable') }}</span> }
        @else if (observation.detailStatus() === 'loading') { <span>{{ i18n.t('common.loading') }}</span> }
        @else if (observation.currentRun()) { <span>{{ i18n.t('flow.observation.match.' + flowMatch()) }}</span><span class="fo-bar__hint">{{ i18n.t('flow.observation.hint') }}</span> }
      </div>
    </section>
  `,
})
export class FlowObservationBarComponent {
  readonly observation = inject(FlowObservationService);
  readonly windows = inject(FlowObservationWindowsService);
  readonly i18n = inject(I18nService);
  readonly flowMatch = input<'same' | 'different' | 'unknown'>('unknown');

  selectRun(event: Event): void { this.observation.selectRun((event.target as HTMLSelectElement).value); }

  runLabel(run: FlowObservationRun): string {
    const date = formatObservationDate(run.started_at, this.i18n.locale(), this.i18n.t('flow.observation.date_unknown'));
    const status = runStatusLabel(run, this.i18n.t);
    const ingress = observationRunIngress(run);
    const surfaceKey = run.execution_surface === 'published_manual' ? 'flow.runtime.surface.published'
      : run.execution_surface === 'draft_test' ? 'flow.runtime.surface.draft'
      : run.execution_surface === 'node_preview' ? 'flow.observation.surface.node'
      : run.execution_surface === 'builder_preview' ? 'flow.observation.surface.builder'
      : run.execution_surface === 'golden_preview' ? 'flow.observation.surface.golden' : null;
    const surface = surfaceKey ? this.i18n.t(surfaceKey) : null;
    const version = observationRunVersion(run);
    return [date, status, surface, ingress, version ? this.i18n.t('flow.observation.version',{version:version.slice(0,8)}) : null, run.id.slice(0,8)].filter(Boolean).join(' · ');
  }
}

export function formatObservationDate(value: string | null | undefined, locale: string, unknown: string): string {
  // Canonical Run timestamps are UTC; historical projections omitted the Z.
  const normalized = value && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value) ? value + 'Z' : value;
  if (!normalized || !Number.isFinite(Date.parse(normalized))) return unknown;
  return new Intl.DateTimeFormat(locale, {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZoneName:'short'}).format(new Date(normalized));
}
