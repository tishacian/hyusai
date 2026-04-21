import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TagComponent, type CkTagTone } from './tag.component';

export type RuntimeStatus = 'bound' | 'stub' | 'unbound' | 'catalog_only' | string;

/**
 * `<ck-runtime-status>` — single source of truth for the canonical
 * 4-state runtime badge used wherever skills surface in the UI:
 *
 *   bound        · implementation ships real results (green)
 *   stub         · degraded stand-in — returns empty/synthetic payloads (amber)
 *   unbound      · declared in registry but no wrapper attached (red)
 *   catalog_only · row exists in DB but no registry entry at all (violet)
 */
@Component({
  selector: 'ck-runtime-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TagComponent],
  template: `
    <ck-tag [tone]="tone()" [variant]="variant()" [title]="title()">
      {{ label() }}
    </ck-tag>
  `,
})
export class RuntimeStatusBadgeComponent {
  readonly status = input.required<RuntimeStatus | null | undefined>();
  readonly variant = input<'solid' | 'soft' | 'outline'>('soft');

  readonly label = computed(() => {
    switch (this.status()) {
      case 'bound':
        return 'BOUND';
      case 'stub':
        return 'STUB';
      case 'unbound':
        return 'UNBOUND';
      case 'catalog_only':
        return 'CATALOG';
      default:
        return 'UNKNOWN';
    }
  });

  readonly tone = computed<CkTagTone>(() => {
    switch (this.status()) {
      case 'bound':
        return 'pos';
      case 'stub':
        return 'warn';
      case 'unbound':
        return 'neg';
      case 'catalog_only':
        return 'violet';
      default:
        return 'neutral';
    }
  });

  readonly title = computed(() => {
    switch (this.status()) {
      case 'bound':
        return 'Implementation ships real results.';
      case 'stub':
        return 'Degraded stand-in — returns empty or synthetic payloads.';
      case 'unbound':
        return 'Declared in the registry but no wrapper attached.';
      case 'catalog_only':
        return 'Declared in the catalog but not registered at runtime.';
      default:
        return 'Runtime status unknown.';
    }
  });
}
