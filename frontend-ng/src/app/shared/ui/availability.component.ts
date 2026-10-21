import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { AVAILABILITY_DIMENSIONS, availability, type Availability, type AvailabilityValue } from './load-state';

/** Independent evidence for each availability dimension (UI/UX plan D08). */
@Component({
  selector: 'app-availability',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <dl class="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2" data-testid="availability">
      @for (dimension of dimensions; track dimension) {
        <div class="min-w-0" [attr.data-testid]="'availability-' + dimension">
          <dt class="font-medium">{{ i18n.t('state.availability.' + dimension) }}</dt>
          <dd class="m-0 break-words">
            {{ i18n.t(valueKey(value()[dimension].value)) }}
            @if (value()[dimension].reason; as reason) {
              <span class="text-[var(--ck-fg-2)]"> · {{ reason }}</span>
            }
          </dd>
        </div>
      }
    </dl>
  `,
})
export class AvailabilityComponent {
  readonly i18n = inject(I18nService);
  readonly value = input<Availability>(availability());
  readonly dimensions = AVAILABILITY_DIMENSIONS;

  valueKey(value: AvailabilityValue): string {
    return value === 'unknown' ? 'state.availability.unknown'
      : value ? 'state.availability.yes' : 'state.availability.no';
  }
}
