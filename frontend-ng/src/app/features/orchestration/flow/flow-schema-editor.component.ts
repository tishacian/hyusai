/**
 * `<app-flow-schema-editor>` — declare one node contract schema.
 *
 * Writes a JSON Schema object into `config.<configKey>` on the selected node.
 * The backend already reads two such keys and freezes them into the immutable
 * execution contract at publication:
 *   - `input_schema`  on a source node → the entry payload contract,
 *   - `output_schema` on a Skill node  → the node's frozen output contract.
 *
 * Before this editor both keys could only be authored by hand-editing the Flow
 * JSON, so an entry point fell back to a schema derived from its ports and a
 * Skill node published whatever the mutable catalogue happened to say. "Derive
 * from ports" reproduces that fallback exactly (mirroring the backend's
 * `_ports_schema`) so declaring a contract starts from the current behaviour
 * rather than a blank page.
 *
 * The editing surface itself is `<ck-schema-builder>`, shared with the Skill
 * authoring wizard: a contract is the same object on both screens, so writing
 * one should not be two different exercises. This component keeps what is
 * specific to a Flow node — where the schema is stored, and the port-derived
 * starting point. Every input of this component is unchanged: the inspector
 * and the entry-point editor call it exactly as before.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import type { CanonicalFlowNode, NodePort } from '@app/core/flow-serializer.service';
import { SchemaBuilderComponent } from '@app/shared/schema-builder/schema-builder.component';
import { FlowStore } from './flow.store';
import { schemaFromPorts } from './flow-contract-bindings.vm';

@Component({
  selector: 'app-flow-schema-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-schema-editor.component.scss',
  imports: [SchemaBuilderComponent],
  template: `
    <div class="ck-schema">
      <ck-schema-builder
        [label]="label()"
        [hint]="hint()"
        [value]="stored()"
        (valueChange)="write($event)"
      />
      @if (declared()) {
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
          (click)="write(null)"
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

  readonly stored = computed<Record<string, unknown> | null>(() => {
    const value = ((this.node()?.config ?? {}) as Record<string, unknown>)[this.configKey()];
    return isSchemaObject(value) ? value : null;
  });

  readonly declared = computed(() => this.stored() !== null);

  deriveFromPorts(): void {
    const node = this.node();
    if (!node) return;
    this.write(schemaFromPorts(portsOf(node, this.deriveFrom())) as Record<string, unknown>);
  }

  write(schema: Record<string, unknown> | null): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(id, this.configKey(), schema);
  }
}

function isSchemaObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function portsOf(node: CanonicalFlowNode, side: 'inputs' | 'outputs'): NodePort[] {
  return (side === 'inputs' ? node.inputs : node.outputs) ?? [];
}
