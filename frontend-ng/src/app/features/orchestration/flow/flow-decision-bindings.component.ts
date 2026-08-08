/**
 * `<app-flow-decision-bindings>` — name what a Decision's conditions read.
 *
 * A Decision predicate reads bare names out of the node's resolved input
 * (`variable_pool.apply_inputs_map`), so `line_manager_approved == true` only
 * works if something binds `line_manager_approved`. The inspector previously
 * offered exactly one picker, for the declared `in` port, and that port is
 * typed `object` — so a `string` upstream (the Trigger's `goal`) was filtered
 * out and the picker read "— unbound —" with nothing to choose and no reason
 * given.
 *
 * A named binding sidesteps that: it is a key in `config.inputs_map` with no
 * declared port and therefore no port type to clash with. It appears in the
 * predicate context under exactly the name written here.
 *
 * The reference audit below is a convenience mirror of the backend's
 * `decision_condition_unbound` check, which stays authoritative — it parses the
 * expression properly, this only tokenises it.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import {
  FlowSerializerService,
  isValidVariableRef,
  type CanonicalFlow,
  type VariableRef,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowManifestService } from './flow-manifest.service';
import {
  decodeCandidateValue,
  encodeCandidateValue,
  upstreamOutputs,
  variableRefFor,
  variableRefLabel,
  type VariableCandidate,
} from './flow-variable.service';
import { conditionNames } from './flow-contract-bindings.vm';

interface BindingRow {
  name: string;
  /** Encoded candidate value, or '' when the selector is not a typed ref. */
  value: string;
  /** Set when the stored selector is a legacy dot-path string. */
  legacy: string | null;
  /** Shown when a typed ref points outside the current candidate list. */
  orphanLabel: string | null;
}

interface ReferenceRow {
  name: string;
  bound: boolean;
}

@Component({
  selector: 'app-flow-decision-bindings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-decision-bindings.component.scss',
  template: `
    <div class="ck-dbind">
      <div class="ck-dbind__head">
        <span class="ck-dbind__title">Named inputs</span>
        <button
          type="button"
          class="ck-dbind__btn"
          data-testid="decision-add-binding"
          [disabled]="candidates().length === 0"
          (click)="addBinding()"
        >
          + Named input
        </button>
      </div>

      <p class="ck-dbind__hint">
        Each name below is readable by the conditions above, exactly as spelled.
      </p>

      @if (candidates().length === 0) {
        <p class="ck-dbind__hint ck-dbind__hint--warn">
          Nothing upstream produces a value yet. Connect a node into this
          Decision before naming what it reads.
        </p>
      }

      @for (row of rows(); track row.name) {
        <div class="ck-dbind__row">
          <input
            class="ck-dbind__name"
            type="text"
            spellcheck="false"
            autocomplete="off"
            aria-label="Binding name"
            [value]="row.name"
            (change)="renameBinding(row.name, $event)"
          />
          <select
            class="ck-dbind__select"
            aria-label="Bound upstream output"
            [value]="row.value"
            (change)="rebind(row.name, $event)"
          >
            <option value="">
              {{ row.legacy ? 'legacy path: ' + row.legacy : '— pick an upstream output —' }}
            </option>
            @if (row.orphanLabel; as orphan) {
              <option [value]="row.value" selected>{{ orphan }} (missing)</option>
            }
            @for (candidate of candidates(); track candidate.node_id + candidate.port) {
              <option [value]="encode(candidate)">
                {{ candidate.label }} · {{ candidate.schema }}
              </option>
            }
          </select>
          <button
            type="button"
            class="ck-dbind__btn ck-dbind__btn--danger"
            aria-label="Remove this named input"
            (click)="removeBinding(row.name)"
          >
            ×
          </button>
        </div>
      }

      @if (references().length > 0) {
        <p class="ck-dbind__hint">Your conditions read:</p>
        <div class="ck-dbind__refs" data-testid="decision-condition-refs">
          @for (ref of references(); track ref.name) {
            <span class="ck-dbind__ref" [attr.data-bound]="ref.bound">
              {{ ref.name }}{{ ref.bound ? '' : ' · not bound' }}
            </span>
          }
        </div>
        @if (unboundCount() > 0) {
          <p class="ck-dbind__hint ck-dbind__hint--warn" role="status">
            An unbound name reads as null: an equality test silently never
            matches, a comparison errors the Run. Bind it above, or correct the
            spelling in the condition.
          </p>
        }
      }
    </div>
  `,
})
export class FlowDecisionBindingsComponent {
  private readonly store = inject(FlowStore);
  private readonly manifest = inject(FlowManifestService);
  private readonly serializer = inject(FlowSerializerService);

  private readonly node = this.store.selectedNode;

  /** Every upstream output, unfiltered: a named binding declares no type, so
   *  there is no port schema for a candidate to be incompatible with. */
  protected readonly candidates = computed<VariableCandidate[]>(() => {
    const id = this.node()?.id;
    if (!id) return [];
    const nodes = this.store.nodes();
    const edges = this.store.edges();
    return upstreamOutputs(id, nodes, edges, {
      order: this.serializer.topoSort({ nodes, edges } as CanonicalFlow),
      outputSchemaFor: (nid) => this.manifest.unitFor(nid)?.implementation?.output_schema,
    });
  });

  /** Named rows the operator has opened but not yet pointed at an output.
   *  They stay out of `inputs_map`: a key with no selector fails strict
   *  resolution at run time (`variable_pool.apply_inputs_map`). */
  private readonly drafts = signal<string[]>([]);
  private draftsNodeId: string | null = null;

  constructor() {
    effect(() => {
      const id = this.store.selectedNodeId();
      if (id === this.draftsNodeId) return;
      this.draftsNodeId = id;
      this.drafts.set([]);
    });
  }

  private readonly inputsMap = computed<Record<string, unknown>>(() => {
    const raw = ((this.node()?.config ?? {}) as Record<string, unknown>)['inputs_map'];
    return raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  });

  /** Declared ports already have a picker in `<app-manifest-fields>`; this
   *  editor owns only the keys that exist purely as names. */
  private readonly portNames = computed(
    () => new Set((this.node()?.inputs ?? []).map((port) => port.name)),
  );

  protected readonly rows = computed<BindingRow[]>(() => {
    const listed = new Set(
      this.candidates().map((candidate) => this.encode(candidate)),
    );
    const ports = this.portNames();
    const map = this.inputsMap();
    const persisted = Object.entries(map)
      .filter(([name]) => !ports.has(name))
      .map(([name, selector]) => {
        if (typeof selector === 'string') {
          return { name, value: '', legacy: selector, orphanLabel: null };
        }
        if (!isValidVariableRef(selector)) {
          return { name, value: '', legacy: null, orphanLabel: null };
        }
        const ref = selector as VariableRef;
        const value = encodeCandidateValue(ref.node_id, ref.path[0] ?? '');
        return {
          name,
          value,
          legacy: null,
          orphanLabel: listed.has(value) ? null : variableRefLabel(ref),
        };
      });
    const drafts = this.drafts()
      .filter((name) => !(name in map) && !ports.has(name))
      .map((name) => ({ name, value: '', legacy: null, orphanLabel: null }));
    return [...persisted, ...drafts];
  });

  /** Only strict resolution makes the readable name set decidable here: it
   *  keeps `passthrough_inputs` from the predecessor merge and overlays
   *  `inputs_map`. Overlay merges the whole accumulated context, so the names
   *  are listed but never called unbound — same scoping as the backend's
   *  `decision_condition_unbound`. */
  private readonly strict = computed(() => this.store.meta().io_mode === 'strict');

  private readonly boundNames = computed(() => {
    const config = (this.node()?.config ?? {}) as Record<string, unknown>;
    const passthrough = config['passthrough_inputs'];
    return new Set([
      ...Object.keys(this.inputsMap()),
      ...(Array.isArray(passthrough) ? passthrough.filter((v) => typeof v === 'string') : []),
    ]);
  });

  protected readonly references = computed<ReferenceRow[]>(() => {
    const branches = ((this.node()?.config ?? {}) as Record<string, unknown>)['branches'];
    if (!Array.isArray(branches)) return [];
    const bound = this.boundNames();
    const strict = this.strict();
    const names = new Set<string>();
    for (const branch of branches) {
      const condition = (branch as Record<string, unknown> | null)?.['condition'];
      if (typeof condition !== 'string' || !condition.trim()) continue;
      for (const name of conditionNames(condition)) names.add(name);
    }
    return [...names]
      .sort()
      .map((name) => ({ name, bound: !strict || bound.has(name) }));
  });

  protected readonly unboundCount = computed(
    () => this.references().filter((ref) => !ref.bound).length,
  );

  protected encode(candidate: VariableCandidate): string {
    return encodeCandidateValue(candidate.node_id, candidate.port);
  }

  protected addBinding(): void {
    const taken = new Set([...Object.keys(this.inputsMap()), ...this.drafts()]);
    let name = 'binding';
    for (let i = 1; taken.has(name); i += 1) name = `binding_${i}`;
    this.drafts.update((names) => [...names, name]);
  }

  protected removeBinding(name: string): void {
    this.drafts.update((names) => names.filter((draft) => draft !== name));
    if (!(name in this.inputsMap())) return;
    const next = { ...this.inputsMap() };
    delete next[name];
    this.write(next);
  }

  /** Renames preserve key order so the rows do not jump while typing. */
  protected renameBinding(name: string, event: Event): void {
    const input = event.target as HTMLInputElement;
    const raw = input.value.trim();
    const map = this.inputsMap();
    if (!raw || raw === name || raw in map || this.drafts().includes(raw)) {
      input.value = name;
      return;
    }
    this.drafts.update((names) =>
      names.map((draft) => (draft === name ? raw : draft)),
    );
    if (!(name in map)) return;
    this.write(
      Object.fromEntries(
        Object.entries(map).map(([key, value]) => [key === name ? raw : key, value]),
      ),
    );
  }

  protected rebind(name: string, event: Event): void {
    const decoded = decodeCandidateValue((event.target as HTMLSelectElement).value);
    const next = { ...this.inputsMap() };
    if (decoded) {
      next[name] = variableRefFor(decoded.node_id, decoded.port);
      this.drafts.update((names) => names.filter((draft) => draft !== name));
    } else {
      if (!(name in next)) return;
      delete next[name];
      // Keep the row on screen so clearing a binding is not the same gesture
      // as deleting the name the conditions still reference.
      this.drafts.update((names) => (names.includes(name) ? names : [...names, name]));
    }
    this.write(next);
  }

  /** Written wholesale: a rename or a removal has to drop the old key, and the
   *  store's dotted-path writer can only set one. */
  private write(next: Record<string, unknown>): void {
    const id = this.node()?.id;
    if (id) this.store.updateNodeConfig(id, 'inputs_map', next);
  }
}
