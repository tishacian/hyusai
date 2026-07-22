import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import type { ObjectLens } from '@app/core/navigation.catalog';
import type {
  ObjectPerspectiveFact,
  ObjectPerspectiveResponse,
} from './object-perspective.models';

const STATE_LABELS: Record<ObjectPerspectiveFact['state'], string> = {
  available: 'Available',
  not_measured: 'Not measured',
  not_configured: 'Not configured',
  restricted: 'Access restricted',
  unavailable: 'Unavailable',
};

@Component({
  selector: 'ck-object-perspective',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="object-perspective"
      [attr.data-object-type]="perspective()?.identity?.object_type || null"
      [attr.data-object-id]="perspective()?.identity?.object_id || null"
      [attr.data-perspective-lens]="lens()"
      [attr.data-perspective-facet]="facet()"
    >
      @if (loading()) {
        <div class="perspective-state" data-testid="object-perspective-loading">
          Loading the {{ lens() }} projection…
        </div>
      } @else if (error()) {
        <div class="perspective-state perspective-state-error" data-testid="object-perspective-error">
          This projection is temporarily unavailable.
        </div>
      } @else if (perspective(); as payload) {
        <header class="perspective-heading">
          <div>
            <p class="perspective-eyebrow">{{ lens() }} · {{ facet() }}</p>
            <h2>{{ lensTitle() }}</h2>
          </div>
          <span class="perspective-snapshot" [title]="payload.generated_at">
            Snapshot {{ shortSnapshot(payload.snapshot_id) }}
          </span>
        </header>

        <div class="perspective-grid">
          @for (block of blocks(); track block.id) {
            <article
              class="perspective-block"
              [attr.data-block-id]="block.id"
              [attr.data-testid]="'object360-' + payload.identity.object_type + '-' + lens() + '-' + block.id"
            >
              <header>
                <h3>{{ block.title }}</h3>
                @if (block.description) { <p>{{ block.description }}</p> }
              </header>
              <dl>
                @for (fact of block.facts; track fact.key) {
                  <div class="perspective-fact" [attr.data-fact-key]="fact.key">
                    <dt>{{ fact.label }}</dt>
                    <dd>
                      @if (fact.state === 'available') {
                        <span class="fact-value">{{ formatValue(fact.value) }}</span>
                        @if (fact.unit) { <span class="fact-unit">{{ fact.unit }}</span> }
                      } @else {
                        <span class="fact-state" [attr.data-state]="fact.state">
                          {{ stateLabel(fact.state) }}
                        </span>
                      }
                    </dd>
                    @if (fact.description) { <small>{{ fact.description }}</small> }
                    @if (fact.state === 'available' && (fact.source || fact.as_of || fact.sample_count != null)) {
                      <small>
                        @if (fact.source) { <span>{{ fact.source }}</span> }
                        @if (fact.sample_count != null) { <span> · n={{ fact.sample_count }}</span> }
                        @if (fact.as_of) { <span> · {{ fact.as_of }}</span> }
                      </small>
                    }
                  </div>
                }
              </dl>
            </article>
          } @empty {
            <div class="perspective-state" data-testid="object-perspective-empty">
              No block is configured for this facet.
            </div>
          }
        </div>
      }
    </section>
  `,
  styles: [`
    .object-perspective { display:flex; flex-direction:column; gap:18px; }
    .perspective-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
    .perspective-heading h2 { margin:4px 0 0; color:var(--ck-fg-1); font-size:18px; font-weight:650; }
    .perspective-eyebrow, .perspective-snapshot { font-family:var(--ck-font-mono); text-transform:uppercase; letter-spacing:.14em; }
    .perspective-eyebrow { margin:0; color:var(--ck-signal-cool); font-size:10px; }
    .perspective-snapshot { color:var(--ck-fg-4); font-size:9px; }
    .perspective-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }
    .perspective-block { min-width:0; padding:16px; border:1px solid var(--ck-stroke-soft); border-radius:var(--ck-radius-md); background:var(--ck-bg-panel); }
    .perspective-block h3 { margin:0; color:var(--ck-fg-1); font-size:14px; font-weight:650; }
    .perspective-block header p { margin:5px 0 0; color:var(--ck-fg-4); font-size:11px; line-height:1.5; }
    .perspective-block dl { display:flex; flex-direction:column; gap:10px; margin:14px 0 0; }
    .perspective-fact { display:grid; grid-template-columns:minmax(90px,.8fr) minmax(0,1.2fr); gap:4px 12px; padding-top:10px; border-top:1px dashed var(--ck-stroke-soft); }
    .perspective-fact dt { color:var(--ck-fg-4); font-size:11px; }
    .perspective-fact dd { margin:0; color:var(--ck-fg-1); font-family:var(--ck-font-mono); font-size:11px; text-align:right; overflow-wrap:anywhere; }
    .perspective-fact small { grid-column:1/-1; color:var(--ck-fg-4); font-family:var(--ck-font-mono); font-size:9px; text-align:right; }
    .fact-unit { margin-left:4px; color:var(--ck-fg-4); }
    .fact-state { color:var(--ck-fg-3); }
    .fact-state[data-state="restricted"] { color:var(--ck-signal-warn); }
    .fact-state[data-state="unavailable"] { color:var(--ck-signal-neg); }
    .perspective-state { padding:28px; border:1px dashed var(--ck-stroke-soft); border-radius:var(--ck-radius-md); color:var(--ck-fg-4); font-family:var(--ck-font-mono); font-size:11px; text-align:center; }
    .perspective-state-error { color:var(--ck-signal-neg); }
  `],
})
export class ObjectPerspectiveComponent {
  readonly objectLabel = input.required<string>();
  readonly lens = input.required<ObjectLens>();
  readonly facet = input.required<string>();
  readonly perspective = input<ObjectPerspectiveResponse | null>(null);
  readonly loading = input(false);
  readonly error = input(false);

  readonly blocks = computed(() => this.perspective()?.facets?.[this.facet()]?.blocks ?? []);

  lensTitle(): string {
    const titles: Record<ObjectLens, string> = {
      build: `How this ${this.objectLabel()} is built`,
      operate: `How this ${this.objectLabel()} is operating`,
      steer: `What should be optimized`,
      govern: `Who can act and what changed`,
    };
    return titles[this.lens()];
  }

  stateLabel(state: ObjectPerspectiveFact['state']): string { return STATE_LABELS[state]; }
  shortSnapshot(value: string): string { return value.length > 10 ? value.slice(0, 10) : value; }

  formatValue(value: unknown): string {
    if (value == null) return 'Unavailable';
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map((item) => this.simpleValue(item)).join(' · ');
    try { return JSON.stringify(value); } catch { return String(value); }
  }

  private simpleValue(value: unknown): string {
    if (value == null) return '—';
    if (typeof value === 'object') {
      const record = value as Record<string, unknown>;
      return String(record['name'] ?? record['label'] ?? record['slug'] ?? record['id'] ?? JSON.stringify(value));
    }
    return String(value);
  }
}
