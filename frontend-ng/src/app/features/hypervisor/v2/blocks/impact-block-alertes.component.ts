import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ImpactBlockShellComponent } from './impact-block-shell.component';

export interface AlerteItem {
  id: string;
  title: string;
  severity?: string | null;
  zone?: string | null;
  status?: string | null;
  owner?: string | null;
}

@Component({
  selector: 'app-impact-block-alertes',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ImpactBlockShellComponent],
  template: `
    <app-impact-block-shell type="alertes" [title]="resolvedTitle()" [width]="width || null">
      @if (!items.length) {
        <p class="ck-mono impact-empty" data-testid="impact-block-alertes-empty">
          {{ i18n.t('hypervisor.v2.block.alertes.empty') }}
        </p>
      } @else {
        <ul class="impact-list">
          @for (item of items; track item.id) {
            <li class="impact-row">
              <span class="impact-grow">{{ item.title }}</span>
              @if (item.severity) {
                <span class="ck-mono impact-muted">{{ item.severity }}</span>
              }
              @if (item.zone) {
                <span class="ck-mono impact-muted">{{ item.zone }}</span>
              }
            </li>
          }
        </ul>
      }
    </app-impact-block-shell>
  `,
  styles: [`
    .impact-empty { margin: 0; color: var(--ck-fg-2); font-size: 12px; }
    .impact-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .impact-row { display: flex; align-items: baseline; gap: 12px; }
    .impact-grow { flex: 1; min-width: 0; }
    .impact-muted { color: var(--ck-fg-2); font-size: 11px; }
  `],
})
export class ImpactBlockAlertesComponent {
  @Input() source: string | null = null;
  @Input() title: string | null = null;
  @Input() width: string | null = null;
  @Input() settings: Record<string, unknown> = {};
  @Input() exit: string | null = null;
  @Input() items: AlerteItem[] = [];

  constructor(readonly i18n: I18nService) {}

  resolvedTitle(): string {
    return this.title || this.i18n.t('hypervisor.v2.block.alertes');
  }
}
