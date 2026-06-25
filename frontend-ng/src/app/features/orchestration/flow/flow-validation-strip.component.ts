/**
 * `<app-flow-validation-strip>` — the design-time checklist (P2).
 *
 * A click-to-error panel below the manifest strip. It consumes the client
 * `FlowSerializerService.validateFlow(store.snapshot())` diagnostics
 * reactively (a computed over the store's node/edge signals) AND the
 * server-side issues surfaced at save time (passed in as `[serverIssues]`
 * from the builder, which owns the persistence service). Both are folded by
 * the Angular-free `toValidationStripVm` — the strip reimplements NO checks.
 *
 * Clicking a row selects its node (`store.setSelection`) so the inspector
 * opens on it, and emits `(focusNode)` so the shell can recentre the canvas
 * on that node. Rows with no `node_id` (graph-level issues) are inert.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { FlowSerializerService } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import {
  toValidationStripVm,
  type ValidationIssueLike,
  type ValidationRow,
} from './flow-validation-strip.vm';

@Component({
  selector: 'app-flow-validation-strip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-validation-strip.component.scss',
  template: `
    @if (vm(); as v) {
      @if (!v.clean) {
        <div class="ck-vstrip" role="status" aria-label="Flow validation checklist">
          <div class="ck-vstrip__head">
            <span class="ck-vstrip__eyebrow">Checklist</span>
            @if (v.errorCount > 0) {
              <span class="ck-vstrip__count" data-level="error">
                {{ v.errorCount }} {{ v.errorCount === 1 ? 'error' : 'errors' }}
              </span>
            }
            @if (v.warnCount > 0) {
              <span class="ck-vstrip__count" data-level="warn">
                {{ v.warnCount }} {{ v.warnCount === 1 ? 'warning' : 'warnings' }}
              </span>
            }
          </div>

          <ul class="ck-vstrip__list">
            @for (row of v.rows; track $index) {
              <li>
                <button
                  type="button"
                  class="ck-vstrip__row"
                  [attr.data-level]="row.level"
                  [disabled]="!row.nodeId"
                  [title]="row.nodeId ? 'Reveal node ' + row.nodeId : row.code"
                  (click)="onSelect(row)"
                >
                  <span class="ck-vstrip__dot" [attr.data-level]="row.level" aria-hidden="true"></span>
                  <span class="ck-vstrip__msg">{{ row.message }}</span>
                  <span class="ck-vstrip__code">{{ row.code }}</span>
                  @if (row.origin === 'server') {
                    <span class="ck-vstrip__tag" title="From the last server save">server</span>
                  }
                </button>
              </li>
            }
          </ul>
        </div>
      }
    }
  `,
})
export class FlowValidationStripComponent {
  private readonly store = inject(FlowStore);
  private readonly serializer = inject(FlowSerializerService);

  /** Server-side issues surfaced by the persistence save path (no translation). */
  readonly serverIssues = input<ValidationIssueLike[]>([]);

  /** Emitted with a node id when a row is clicked — the shell recentres it. */
  readonly focusNode = output<string>();

  readonly vm = computed(() =>
    toValidationStripVm(
      this.serializer.validateFlow(this.store.snapshot()),
      this.serverIssues(),
    ),
  );

  onSelect(row: ValidationRow): void {
    if (!row.nodeId) return;
    this.store.setSelection(row.nodeId);
    this.focusNode.emit(row.nodeId);
  }
}
