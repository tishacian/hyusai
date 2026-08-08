/**
 * `<app-flow-schema-editor>` — declare one node contract schema by hand.
 *
 * Writes a JSON Schema object into `config.<configKey>` on the selected node.
 * The backend already reads two such keys and freezes them into the immutable
 * execution contract at publication:
 *   - `input_schema`  on a source node → the ingress payload contract,
 *   - `output_schema` on a Skill node  → the node's frozen output contract.
 *
 * Before this editor both keys could only be authored by hand-editing the Flow
 * JSON, so an ingress fell back to a schema derived from its ports and a Skill
 * node published whatever the mutable catalogue happened to say. "Derive from
 * ports" reproduces that fallback exactly (mirroring the backend's
 * `_ports_schema`) so declaring a contract starts from the current behaviour
 * rather than a blank page.
 *
 * Edits commit on `change` (blur), never per keystroke: a half-typed object is
 * not a contract.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import type { CanonicalFlowNode, NodePort } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { schemaFromPorts } from './flow-contract-bindings.vm';

@Component({
  selector: 'app-flow-schema-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-schema-editor.component.scss',
  template: `
    <div class="ck-schema">
      <span class="ck-schema__label">{{ label() }}</span>
      @if (hint(); as text) {
        <p class="ck-schema__hint">{{ text }}</p>
      }
      <textarea
        class="ck-schema__editor"
        rows="7"
        spellcheck="false"
        autocomplete="off"
        [attr.aria-label]="label()"
        [attr.aria-invalid]="error() !== null"
        [value]="text()"
        (change)="onCommit($event)"
      ></textarea>
      @if (error(); as message) {
        <p class="ck-schema__hint ck-schema__hint--error" role="alert">{{ message }}</p>
      } @else if (declared()) {
        <p class="ck-schema__hint">Declared — this is what publication freezes.</p>
      } @else {
        <p class="ck-schema__hint">{{ fallbackHint() }}</p>
      }
      <div class="ck-schema__actions">
        <button type="button" class="ck-schema__btn" (click)="deriveFromPorts()">
          Derive from ports
        </button>
        <button
          type="button"
          class="ck-schema__btn"
          [disabled]="!declared()"
          (click)="clear()"
        >
          Clear
        </button>
      </div>
    </div>
  `,
})
export class FlowSchemaEditorComponent {
  private readonly store = inject(FlowStore);

  /** Config key written on the selected node (`input_schema` / `output_schema`). */
  readonly configKey = input.required<string>();
  readonly label = input('JSON Schema');
  readonly hint = input<string | null>(null);
  /** Sentence shown while no schema is declared, describing the fallback. */
  readonly fallbackHint = input('No schema declared — the node ports are used instead.');
  /** Which port list "Derive from ports" reads. */
  readonly deriveFrom = input<'inputs' | 'outputs'>('outputs');

  private readonly node = this.store.selectedNode;
  /** Rejected text kept on screen so an invalid edit is never silently lost. */
  private readonly draft = signal<string | null>(null);
  readonly error = signal<string | null>(null);

  private readonly stored = computed<unknown>(
    () => ((this.node()?.config ?? {}) as Record<string, unknown>)[this.configKey()],
  );

  readonly declared = computed(() => isSchemaObject(this.stored()));

  readonly text = computed(() => {
    const draft = this.draft();
    if (draft !== null) return draft;
    const stored = this.stored();
    return isSchemaObject(stored) ? JSON.stringify(stored, null, 2) : '';
  });

  onCommit(event: Event): void {
    this.write((event.target as HTMLTextAreaElement).value);
  }

  deriveFromPorts(): void {
    const node = this.node();
    if (!node) return;
    this.write(JSON.stringify(schemaFromPorts(portsOf(node, this.deriveFrom())), null, 2));
  }

  clear(): void {
    this.write('');
  }

  private write(raw: string): void {
    const id = this.node()?.id;
    if (!id) return;
    const trimmed = raw.trim();
    if (!trimmed) {
      this.draft.set(null);
      this.error.set(null);
      this.store.updateNodeConfig(id, this.configKey(), null);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      this.draft.set(raw);
      this.error.set('Invalid JSON — the schema was not saved.');
      return;
    }
    if (!isSchemaObject(parsed)) {
      this.draft.set(raw);
      this.error.set('A JSON Schema must be an object, not an array or a scalar.');
      return;
    }
    this.draft.set(null);
    this.error.set(null);
    this.store.updateNodeConfig(id, this.configKey(), parsed);
  }
}

function isSchemaObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function portsOf(node: CanonicalFlowNode, side: 'inputs' | 'outputs'): NodePort[] {
  return (side === 'inputs' ? node.inputs : node.outputs) ?? [];
}
