/**
 * `<app-flow-validation-strip>` — the design-time checklist (P2).
 *
 * A click-to-error panel below the manifest strip. It consumes the client
 * `FlowSerializerService.validateFlow(store.snapshot())` diagnostics
 * reactively (a computed over the store's node/edge signals) AND the
 * hash-bound server issues for the current revision (passed in as
 * `[serverIssues]` from the builder). Both are folded by
 * the Angular-free `toValidationStripVm` — the strip reimplements NO checks.
 *
 * Clicking a row selects its node (`store.setSelection`) so the inspector
 * opens on it, and emits `(focusNode)` so the shell can recentre the canvas
 * on that node. Rows with no `node_id` (graph-level issues) are inert.
 *
 * Two registers, as everywhere else: the row reads a translated sentence
 * looked up from the diagnostic code (`flow.checklist.code.<code>`), while
 * the code itself and the analyser's raw wording stay one level down, in the
 * row `title` and in `data-code` / `data-detail`, so support can still get
 * them. The codes are a tested contract and are never rewritten here.
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
import { I18nService } from '@app/core/i18n.service';
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
      @if (!v.clean || serverState() === 'scheduled' || serverState() === 'validating' || serverState() === 'error') {
        <div class="ck-vstrip" role="status" [attr.aria-label]="i18n.t('flow.checklist.aria')">
          <div class="ck-vstrip__head">
            <span class="ck-vstrip__eyebrow">{{ i18n.t('flow.checklist.title') }}</span>
            @if (serverState() === 'scheduled' || serverState() === 'validating') {
              <span class="ck-vstrip__count">{{ i18n.t('flow.checklist.checking') }}</span>
            }
            @if (serverState() === 'error') {
              <span class="ck-vstrip__count" data-level="error">
                {{ serverError() || i18n.t('flow.checklist.server_error') }}
              </span>
            }
            @if (v.errorCount > 0) {
              <span class="ck-vstrip__count" data-level="error">
                {{
                  v.errorCount === 1
                    ? i18n.t('flow.checklist.errors.one')
                    : i18n.t('flow.checklist.errors.many', { count: v.errorCount })
                }}
              </span>
            }
            @if (v.warnCount > 0) {
              <span class="ck-vstrip__count" data-level="warn">
                {{
                  v.warnCount === 1
                    ? i18n.t('flow.checklist.warnings.one')
                    : i18n.t('flow.checklist.warnings.many', { count: v.warnCount })
                }}
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
                  [attr.data-code]="row.code"
                  [attr.data-detail]="row.message"
                  [title]="diagnostic(row)"
                  (click)="onSelect(row)"
                >
                  <span class="ck-vstrip__dot" [attr.data-level]="row.level" aria-hidden="true"></span>
                  <span class="ck-vstrip__msg">{{ message(row) }}</span>
                  @if (row.origin === 'server') {
                    <span
                      class="ck-vstrip__tag"
                      [title]="i18n.t('flow.checklist.server_tag.hint')"
                      >{{ i18n.t('flow.checklist.server_tag') }}</span
                    >
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
  readonly i18n = inject(I18nService);

  /** Hash-bound issues from the canonical non-mutating server analyser. */
  readonly serverIssues = input<ValidationIssueLike[]>([]);
  readonly serverState = input<'idle' | 'scheduled' | 'validating' | 'ready' | 'error'>('idle');
  readonly serverError = input<string | null>(null);

  /** Emitted with a node id when a row is clicked — the shell recentres it. */
  readonly focusNode = output<string>();

  readonly vm = computed(() =>
    toValidationStripVm(
      this.serializer.validateFlow(this.store.snapshot()),
      this.serverIssues(),
    ),
  );

  /**
   * The sentence the builder reads, in the active locale.
   *
   * The diagnostic *code* is the contract — it is what the client serializer
   * and the server analyser agree on — so it stays the lookup key and never
   * becomes copy. `flow.checklist.code.<code>` answers it; a code no
   * dictionary knows (a newer server) falls back to the server's own
   * sentence, never to an unresolved key. A `{name}` message needs a node,
   * so a node-less row falls back the same way rather than showing the
   * placeholder.
   */
  message(row: ValidationRow): string {
    const key = `flow.checklist.code.${row.code}`;
    const name = row.nodeId ? this.nodeName(row.nodeId) : '';
    const text = this.i18n.t(key, name ? { name } : undefined);
    if (text === key || text.includes('{name}')) return row.message;
    return text;
  }

  /**
   * The technical register, one level down: the code support asks for and the
   * raw analyser sentence, which keeps the specifics (ports, schemas, branch
   * names) the plain message generalises away.
   */
  diagnostic(row: ValidationRow): string {
    return [
      row.nodeId ? this.i18n.t('flow.checklist.reveal', { name: row.nodeId }) : '',
      this.i18n.t('flow.checklist.code.hint', { code: row.code }),
      row.message,
    ]
      .filter(Boolean)
      .join(' · ');
  }

  /** The label a builder gave the node, falling back to its id. */
  private nodeName(nodeId: string): string {
    const node = this.store.nodes().find((candidate) => candidate.id === nodeId);
    return node?.label?.trim() || nodeId;
  }

  onSelect(row: ValidationRow): void {
    if (!row.nodeId) return;
    this.store.setSelection(row.nodeId);
    this.focusNode.emit(row.nodeId);
  }
}
