import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ImpactBlockShellComponent } from './impact-block-shell.component';

export interface EcheancierItem {
  id: string;
  title: string;
  starts_at?: string | null;
  ends_at?: string | null;
  place?: string | null;
  status?: string | null;
  priority?: string | null;
}

@Component({
  selector: 'app-impact-block-echeancier',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ImpactBlockShellComponent],
  template: `
    <app-impact-block-shell type="echeancier" [title]="resolvedTitle()" [width]="width || null">
      @if (!items.length) {
        <p class="ck-mono impact-empty" data-testid="impact-block-echeancier-empty">
          {{ i18n.t('hypervisor.v2.block.echeancier.empty') }}
        </p>
      } @else {
        <ul class="impact-list" [attr.data-mode]="mode()">
          @for (item of items; track item.id) {
            <li class="impact-row">
              <span class="impact-grow">{{ item.title }}</span>
              @if (item.place) {
                <span class="ck-mono impact-muted">{{ item.place }}</span>
              }
              @if (item.status) {
                <span class="ck-mono impact-muted">{{ item.status }}</span>
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
    :host-context(.hv2-theme-presentation) .impact-grow { font-size: 48px; font-weight: 600; letter-spacing: -0.04em; line-height: 1.05; }
  `],
})
export class ImpactBlockEcheancierComponent {
  @Input() source: string | null = null;
  @Input() title: string | null = null;
  @Input() width: string | null = null;
  @Input() settings: Record<string, unknown> = {};
  @Input() exit: string | null = null;
  @Input() items: EcheancierItem[] = [];

  constructor(readonly i18n: I18nService) {}

  resolvedTitle(): string {
    return this.title || this.i18n.t('hypervisor.v2.block.echeancier');
  }

  mode(): string {
    const mode = this.settings['mode'];
    return typeof mode === 'string' ? mode : 'liste';
  }
}
