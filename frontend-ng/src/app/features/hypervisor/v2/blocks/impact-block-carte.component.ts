import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ImpactBlockShellComponent } from './impact-block-shell.component';

export interface CarteZone {
  id: string;
  name: string;
  level?: number | null;
}

@Component({
  selector: 'app-impact-block-carte',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ImpactBlockShellComponent],
  template: `
    <app-impact-block-shell type="carte" [title]="resolvedTitle()" [width]="width || null">
      <div class="impact-carte" data-testid="impact-block-carte-canvas">
        @if (!zones.length) {
          <p class="ck-mono impact-empty" data-testid="impact-block-carte-empty">
            {{ i18n.t('hypervisor.v2.block.carte.empty') }}
          </p>
        } @else {
          <ul class="impact-list">
            @for (zone of zones; track zone.id) {
              <li>
                <button
                  type="button"
                  class="impact-zone"
                  [class.is-selected]="zone.id === selectedZoneId"
                  [attr.data-testid]="'impact-block-carte-zone-' + zone.id"
                  (click)="zoneSelect.emit(zone.id)"
                >
                  <span>{{ zone.name }}</span>
                  @if (zone.level != null) {
                    <span class="ck-mono impact-muted">{{ zone.level }}</span>
                  }
                </button>
              </li>
            }
          </ul>
        }
        <p class="ck-mono impact-attr" data-testid="impact-block-carte-attribution">{{ attribution }}</p>
      </div>
    </app-impact-block-shell>
  `,
  styles: [`
    .impact-carte { display: flex; flex-direction: column; gap: 10px; }
    .impact-empty { margin: 0; color: var(--ck-fg-2); font-size: 12px; }
    .impact-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .impact-zone {
      display: flex; width: 100%; align-items: baseline; justify-content: space-between;
      gap: 12px; padding: 8px 0; border: 0; border-bottom: 1px solid var(--ck-stroke-2);
      background: transparent; color: inherit; text-align: left; cursor: pointer;
    }
    .impact-zone.is-selected { color: var(--ck-fg-1); font-weight: 600; }
    .impact-muted { color: var(--ck-fg-2); font-size: 11px; }
    .impact-attr { margin: 0; color: var(--ck-fg-2); font-size: 10px; }
    :host-context(.hv2-theme-presentation) .impact-zone { font-size: 48px; font-weight: 600; letter-spacing: -0.04em; }
  `],
})
export class ImpactBlockCarteComponent {
  @Input() source: string | null = null;
  @Input() title: string | null = null;
  @Input() width: string | null = null;
  @Input() settings: Record<string, unknown> = {};
  @Input() exit: string | null = null;
  @Input() zones: CarteZone[] = [];
  @Input() selectedZoneId: string | null = null;
  @Input() attribution = '';
  @Output() zoneSelect = new EventEmitter<string>();

  constructor(readonly i18n: I18nService) {}

  resolvedTitle(): string {
    return this.title || this.i18n.t('hypervisor.v2.block.carte');
  }
}
