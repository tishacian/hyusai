import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ImpactBlockShellComponent } from './impact-block-shell.component';

export type IndicateurState = 'measured' | 'declared' | 'absent';

export interface IndicateurItem {
  id: string;
  label: string;
  value: string;
  state: IndicateurState;
  source?: string | null;
  freshness?: string | null;
}

const STATE_MARK: Record<IndicateurState, string> = {
  measured: '●',
  declared: '◐',
  absent: '○',
};

@Component({
  selector: 'app-impact-block-indicateurs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ImpactBlockShellComponent],
  template: `
    <app-impact-block-shell type="indicateurs" [title]="resolvedTitle()" [width]="width || null">
      @if (!items.length) {
        <p class="ck-mono impact-empty" data-testid="impact-block-indicateurs-empty">
          {{ i18n.t('hypervisor.v2.block.indicateurs.empty') }}
        </p>
      } @else {
        <ul class="impact-grid">
          @for (item of items.slice(0, 6); track item.id) {
            <li class="impact-kpi" [attr.data-state]="item.state" [class.is-absent]="item.state === 'absent'">
              <span class="ck-mono impact-mark" aria-hidden="true">{{ mark(item.state) }}</span>
              <span class="impact-value">{{ item.value }}</span>
              <span class="impact-label">{{ item.label }}</span>
              @if (item.source) {
                <span class="ck-mono impact-muted">{{ item.source }}</span>
              }
            </li>
          }
        </ul>
      }
    </app-impact-block-shell>
  `,
  styles: [`
    .impact-empty { margin: 0; color: var(--ck-fg-2); font-size: 12px; }
    .impact-grid {
      list-style: none; margin: 0; padding: 0;
      display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px;
    }
    .impact-kpi { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
    .impact-kpi.is-absent { border-bottom: 1px dotted var(--ck-stroke-2); padding-bottom: 6px; }
    .impact-mark { font-size: 11px; color: var(--ck-fg-2); }
    .impact-value { font-size: 24px; font-weight: 600; letter-spacing: -0.03em; line-height: 1.1; }
    .impact-label { font-size: 13px; color: var(--ck-fg-1); }
    .impact-muted { font-size: 10px; color: var(--ck-fg-2); }
    :host-context(.hv2-theme-presentation) .impact-value { font-size: 48px; }
  `],
})
export class ImpactBlockIndicateursComponent {
  @Input() source: string | null = null;
  @Input() title: string | null = null;
  @Input() width: string | null = null;
  @Input() settings: Record<string, unknown> = {};
  @Input() exit: string | null = null;
  @Input() items: IndicateurItem[] = [];

  constructor(readonly i18n: I18nService) {}

  resolvedTitle(): string {
    return this.title || this.i18n.t('hypervisor.v2.block.indicateurs');
  }

  mark(state: IndicateurState): string {
    return STATE_MARK[state] || STATE_MARK.absent;
  }
}
