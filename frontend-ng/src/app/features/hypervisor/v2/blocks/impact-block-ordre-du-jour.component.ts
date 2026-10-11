import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ImpactBlockShellComponent } from './impact-block-shell.component';

export interface OrdreOption {
  id: string;
  label: string;
  recommended?: boolean;
}

export interface OrdrePoint {
  id: string;
  title: string;
  origin?: 'human' | 'agent' | string | null;
  options?: OrdreOption[];
}

@Component({
  selector: 'app-impact-block-agenda',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ImpactBlockShellComponent],
  template: `
    <app-impact-block-shell [type]="blockType" [title]="resolvedTitle()" [width]="width || null">
      @if (!points.length) {
        <p class="ck-mono impact-empty" data-testid="impact-block-ordre-empty">
          {{ i18n.t('hypervisor.v2.block.ordre_du_jour.empty') }}
        </p>
      } @else {
        <ul class="impact-list" [attr.data-mode]="mode()">
          @for (point of visiblePoints(); track point.id) {
            <li class="impact-point" [attr.data-testid]="'impact-block-ordre-point-' + point.id">
              <div class="impact-row">
                <span class="impact-grow">{{ point.title }}</span>
                @if (point.origin === 'agent') {
                  <span class="ck-mono impact-agent" data-testid="impact-ordre-agent-mark">
                    {{ i18n.t('hypervisor.v2.block.ordre_du_jour.agent') }}
                  </span>
                }
              </div>
              @if (point.options?.length) {
                <ul class="impact-options">
                  @for (option of point.options; track option.id) {
                    <li [class.is-recommended]="option.recommended">
                      <button
                        type="button"
                        class="impact-option"
                        [class.is-recommended]="option.recommended"
                        (click)="logDecision.emit({ pointId: point.id, optionId: option.id })"
                      >{{ option.label }}</button>
                    </li>
                  }
                </ul>
              }
            </li>
          }
        </ul>
      }
    </app-impact-block-shell>
  `,
  styles: [`
    .impact-empty { margin: 0; color: var(--ck-fg-2); font-size: 12px; }
    .impact-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
    .impact-point { display: flex; flex-direction: column; gap: 8px; }
    .impact-row { display: flex; align-items: baseline; gap: 12px; }
    .impact-grow { flex: 1; min-width: 0; }
    .impact-agent { color: var(--ck-fg-2); font-size: 11px; }
    .impact-options { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .impact-option {
      display: block; width: 100%; text-align: left; padding: 8px 0;
      border: 0; border-bottom: 1px solid var(--ck-stroke-2); background: transparent;
      color: inherit; cursor: pointer;
    }
    .impact-option.is-recommended { font-weight: 600; }
    :host-context(.hv2-theme-presentation) .impact-grow { font-size: 48px; font-weight: 600; letter-spacing: -0.04em; }
    :host-context(.hv2-theme-presentation) .impact-option {
      border: 0; border-bottom: 1px solid var(--ck-stroke-2); background: transparent; padding: 10px 0;
    }
  `],
})
export class ImpactBlockOrdreDuJourComponent {
  /** Contract block type id (L13b); label comes from i18n. */
  readonly blockType = 'ordre_du_jour';
  @Input() source: string | null = null;
  @Input() title: string | null = null;
  @Input() width: string | null = null;
  @Input() settings: Record<string, unknown> = {};
  @Input() exit: string | null = null;
  @Input() points: OrdrePoint[] = [];
  @Output() logDecision = new EventEmitter<{ pointId: string; optionId: string }>();

  constructor(readonly i18n: I18nService) {}

  resolvedTitle(): string {
    return this.title || this.i18n.t('hypervisor.v2.block.ordre_du_jour');
  }

  mode(): string {
    const mode = this.settings['mode'];
    return typeof mode === 'string' ? mode : 'prep';
  }

  visiblePoints(): OrdrePoint[] {
    if (this.mode() !== 'seance') return this.points;
    return this.points.slice(0, 1);
  }
}
