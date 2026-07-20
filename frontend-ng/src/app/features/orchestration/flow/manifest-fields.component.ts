/**
 * `<app-manifest-fields>` — the P2 manifest-driven editable parameter form.
 *
 * Rendered INSIDE the inspector (the inspector declares + uses it directly;
 * it does not rely on shell projection). It turns the backend manifest's
 * per-node `editable_fields` into real, typed controls and writes every edit
 * straight back to the EXACT `runtime_read_path` through the FlowStore's
 * dotted-path writers — so e.g. editing `top_k` updates
 * `nodes.runtime.settings_budget.data.retrieval_defaults.top_k`, marks the
 * graph dirty, and round-trips on reload.
 *
 * Write-back resolution (manifest `source` → store writer → runtime_read_path):
 *   - `node.data`          → updateNodeData(id, key)            → nodes.<id>.data.<key>
 *   - `node.config`        → updateNodeConfig(id, key)          → nodes.<id>.config.<key>
 *   - `skill.input_schema` → updateNodeConfig(id, params.<key>) → nodes.<id>.config.params.<key>
 *
 * The displayed value is read LIVE from the selected store node (not the
 * manifest's stale `current_value`), so edits and reloads stay consistent.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import type { FlowManifestField } from '@app/core/canonical-api.service';
import {
  FlowSerializerService,
  isValidVariableRef,
  type CanonicalFlow,
  type NodePort,
  type VariableRef,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowManifestService } from './flow-manifest.service';
import {
  LEGACY_VARIABLE_VALUE,
  decodeCandidateValue,
  encodeCandidateValue,
  filterCompatibleCandidates,
  upstreamOutputs,
  variableRefFor,
  variableRefLabel,
  type VariableCandidate,
} from './flow-variable.service';

type ControlKind =
  | 'text'
  | 'textarea'
  | 'number'
  | 'boolean'
  | 'select'
  | 'json'
  // v3 variable-membrane: bind a node input port to an upstream output
  // (writes a typed VariableRef into config.inputs_map).
  | 'variable';

/** One `<option>` of the variable picker (`control === 'variable'`). */
interface VariableOption {
  value: string;
  label: string;
}

interface FieldVM {
  key: string;
  label: string;
  control: ControlKind;
  type: string;
  required: boolean;
  description: string | null;
  options: string[];
  source: string;
  runtimeReadPath: string;
  /** String value for text/number/textarea/select inputs. */
  stringValue: string;
  /** Checked value for boolean inputs. */
  boolValue: boolean;
  /** Pretty-printed value for the JSON editor. */
  jsonValue: string;
  invalid: boolean;
  error: string | null;
  /** Options for the variable picker (`control === 'variable'` only). */
  variableOptions?: VariableOption[];
}

/** A value is a typed VariableRef (v3) — same shape test as the serializer. */
function isVariableRef(value: unknown): value is VariableRef {
  return isValidVariableRef(value);
}

function getPath(root: Record<string, unknown> | undefined, path: string): unknown {
  if (!root) return undefined;
  let cursor: unknown = root;
  for (const seg of path.split('.').filter((s) => s.length > 0)) {
    if (cursor == null || typeof cursor !== 'object') return undefined;
    cursor = (cursor as Record<string, unknown>)[seg];
  }
  return cursor;
}

function humanize(key: string): string {
  const last = key.split('.').pop() ?? key;
  return last
    .replace(/[_.]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

@Component({
  selector: 'app-manifest-fields',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  styleUrl: './manifest-fields.component.scss',
  template: `
    @if (node(); as n) {
      @if (fields().length > 0 || unit()) {
        <section class="ck-mf">
          @if (unit(); as u) {
            <header class="ck-mf__head">
              <span class="ck-mf__label">Runtime parameters</span>
              <span
                class="ck-mf__status"
                [attr.data-status]="u.runtime_status ?? 'manifest_only'"
                [title]="
                  (u.operational ? 'Configured — drives a live surface' : 'Not fully configured') +
                  ' (' + (u.runtime_status ?? 'manifest_only') + ')'
                "
              >
                <ck-glyph
                  [name]="u.operational ? 'check' : 'warn'"
                  [size]="11"
                  color="currentColor"
                />
                {{ u.operational ? 'Configured' : 'Not configured' }}
              </span>
            </header>

            @if (u.runtime_ref || u.skill_slug) {
              <dl class="ck-mf__refs">
                @if (u.skill_slug) {
                  <dt>Skill</dt>
                  <dd class="mono">{{ u.skill_slug }}</dd>
                }
                @if (u.runtime_ref) {
                  <dt>Runtime</dt>
                  <dd class="mono">{{ u.runtime_ref }}</dd>
                }
              </dl>
            }
          } @else {
            <header class="ck-mf__head">
              <span class="ck-mf__label">Input variables</span>
            </header>
          }

          @if (fields().length > 0) {
            <div class="ck-mf__fields">
              @for (f of fields(); track f.source + ':' + f.key) {
                <div class="ck-mf__field" [class.is-invalid]="f.invalid">
                  <label class="ck-mf__row" [attr.for]="'mf-' + f.key">
                    <span class="ck-mf__name">
                      {{ f.label }}
                      @if (f.required) {
                        <span class="ck-mf__req" aria-hidden="true">*</span>
                        <span class="sr-only">required</span>
                      }
                    </span>

                    @switch (f.control) {
                      @case ('variable') {
                        <select
                          [id]="'mf-' + f.key"
                          class="ck-mf__control"
                          [value]="f.stringValue"
                          (change)="onVariable(f, $event)"
                        >
                          @for (opt of f.variableOptions ?? []; track opt.value) {
                            <option [value]="opt.value" [selected]="opt.value === f.stringValue">
                              {{ opt.label }}
                            </option>
                          }
                        </select>
                      }
                      @case ('boolean') {
                        <input
                          [id]="'mf-' + f.key"
                          type="checkbox"
                          class="ck-mf__check"
                          [checked]="f.boolValue"
                          (change)="onBool(f, $event)"
                        />
                      }
                      @case ('select') {
                        <select
                          [id]="'mf-' + f.key"
                          class="ck-mf__control"
                          [value]="f.stringValue"
                          [attr.aria-invalid]="f.invalid"
                          (change)="onSelect(f, $event)"
                        >
                          <option value="">—</option>
                          @for (opt of f.options; track opt) {
                            <option [value]="opt" [selected]="opt === f.stringValue">
                              {{ opt }}
                            </option>
                          }
                        </select>
                      }
                      @case ('number') {
                        <input
                          [id]="'mf-' + f.key"
                          type="number"
                          class="ck-mf__control"
                          [step]="f.type === 'integer' ? 1 : 'any'"
                          [value]="f.stringValue"
                          [attr.aria-invalid]="f.invalid"
                          (change)="onNumber(f, $event)"
                        />
                      }
                      @case ('textarea') {
                        <textarea
                          [id]="'mf-' + f.key"
                          class="ck-mf__control ck-mf__control--area"
                          rows="3"
                          [value]="f.stringValue"
                          [attr.aria-invalid]="f.invalid"
                          (change)="onText(f, $event)"
                        ></textarea>
                      }
                      @case ('json') {
                        <textarea
                          [id]="'mf-' + f.key"
                          class="ck-mf__control ck-mf__control--area ck-mf__control--mono"
                          rows="4"
                          [value]="f.jsonValue"
                          [attr.aria-invalid]="f.invalid"
                          spellcheck="false"
                          (change)="onJson(f, $event)"
                        ></textarea>
                      }
                      @default {
                        <input
                          [id]="'mf-' + f.key"
                          type="text"
                          class="ck-mf__control"
                          [value]="f.stringValue"
                          [attr.aria-invalid]="f.invalid"
                          (change)="onText(f, $event)"
                        />
                      }
                    }
                  </label>

                  @if (f.error) {
                    <p class="ck-mf__msg ck-mf__msg--err">{{ f.error }}</p>
                  } @else if (f.description) {
                    <p class="ck-mf__msg">{{ f.description }}</p>
                  }
                  <code class="ck-mf__path" [title]="f.runtimeReadPath">{{ f.runtimeReadPath }}</code>
                </div>
              }
            </div>
          } @else {
            <p class="ck-mf__empty">
              This node has no editable runtime parameters in the manifest.
            </p>
          }
        </section>
      } @else if (loaded()) {
        <section class="ck-mf">
          <p class="ck-mf__empty">
            No runtime manifest unit matched this node — it is not yet wired to a
            live runtime contract.
          </p>
        </section>
      }
    }
  `,
})
export class ManifestFieldsComponent {
  private readonly store = inject(FlowStore);
  private readonly manifest = inject(FlowManifestService);
  private readonly serializer = inject(FlowSerializerService);

  private readonly errors = signal<Record<string, string>>({});

  readonly node = this.store.selectedNode;
  readonly unit = computed(() => this.manifest.unitFor(this.node()?.id));
  readonly loaded = computed(() => this.manifest.manifest() !== null);

  /** Manifest-derived editable parameter fields (`node.data`/`config`/
   *  `skill.input_schema`). Empty when the node has no manifest unit. */
  private readonly manifestFields = computed<FieldVM[]>(() => {
    const node = this.node();
    const unit = this.unit();
    if (!node || !unit) return [];
    const errs = this.errors();
    const dataBag = node.data ?? {};
    const configBag = (node.config ?? {}) as Record<string, unknown>;
    return (unit.editable_fields ?? []).map((field) =>
      this.toVm(field, dataBag, configBag, errs[this.errorKey(field)] ?? null),
    );
  });

  /** Upstream output candidates for the selected node, enriched with manifest
   *  output schemas for nodes that declare no canonical ports. */
  private readonly upstreamCandidates = computed<VariableCandidate[]>(() => {
    const id = this.node()?.id;
    if (!id) return [];
    const nodes = this.store.nodes();
    const edges = this.store.edges();
    const order = this.serializer.topoSort({ nodes, edges } as CanonicalFlow);
    return upstreamOutputs(id, nodes, edges, {
      order,
      outputSchemaFor: (nid) =>
        this.manifest.unitFor(nid)?.implementation?.output_schema,
    });
  });

  /** v3 variable-membrane: one picker per input port of the selected node.
   *  Each binds `config.inputs_map.<port>` to a type-compatible upstream
   *  output (a typed VariableRef). Shows even on the scratchpad (no manifest)
   *  since candidates come from the client-side graph. */
  private readonly variableFields = computed<FieldVM[]>(() => {
    const node = this.node();
    if (!node) return [];
    const inputs = node.inputs ?? [];
    if (inputs.length === 0) return [];
    const id = node.id;
    const candidates = this.upstreamCandidates();
    const inputsMap = ((node.config as Record<string, unknown> | undefined)?.[
      'inputs_map'
    ] ?? {}) as Record<string, unknown>;
    return inputs.map((port) => this.variableVm(id, port, candidates, inputsMap[port.name]));
  });

  /** Variable bindings first (data membrane), then manifest parameters. */
  readonly fields = computed<FieldVM[]>(() => [
    ...this.variableFields(),
    ...this.manifestFields(),
  ]);

  // ---- write-back -------------------------------------------------------
  /** Write the picked upstream output as a typed VariableRef into
   *  `config.inputs_map.<port>` (or clear it). A legacy dot-path string is
   *  left untouched until the user picks a candidate or clears it. */
  onVariable(field: FieldVM, ev: Event): void {
    const id = this.store.selectedNodeId();
    if (!id) return;
    const value = (ev.target as HTMLSelectElement).value;
    if (value === LEGACY_VARIABLE_VALUE) return;
    if (value === '') {
      this.store.updateNodeConfig(id, `inputs_map.${field.key}`, null);
      return;
    }
    const decoded = decodeCandidateValue(value);
    if (!decoded) return;
    this.store.updateNodeConfig(
      id,
      `inputs_map.${field.key}`,
      variableRefFor(decoded.node_id, decoded.port),
    );
  }

  onText(field: FieldVM, ev: Event): void {
    this.writeField(field, (ev.target as HTMLInputElement | HTMLTextAreaElement).value);
  }

  onSelect(field: FieldVM, ev: Event): void {
    const value = (ev.target as HTMLSelectElement).value;
    this.writeField(field, value === '' ? null : value);
  }

  onNumber(field: FieldVM, ev: Event): void {
    const raw = (ev.target as HTMLInputElement).value;
    if (raw === '') {
      this.writeField(field, null);
      return;
    }
    const parsed = field.type === 'integer' ? Number.parseInt(raw, 10) : Number.parseFloat(raw);
    if (Number.isFinite(parsed)) this.writeField(field, parsed);
  }

  onBool(field: FieldVM, ev: Event): void {
    this.writeField(field, (ev.target as HTMLInputElement).checked);
  }

  onJson(field: FieldVM, ev: Event): void {
    const raw = (ev.target as HTMLTextAreaElement).value.trim();
    if (!raw) {
      this.clearError(field);
      this.writeField(field, null);
      return;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      this.clearError(field);
      this.writeField(field, parsed);
    } catch {
      this.setError(field, 'Invalid JSON — value not saved.');
    }
  }

  /** Route the value to the exact bag the manifest `source` points at. */
  private writeField(field: FieldVM, value: unknown): void {
    const id = this.store.selectedNodeId();
    if (!id) return;
    if (field.source === 'node.config') {
      this.store.updateNodeConfig(id, field.key, value);
    } else if (field.source === 'skill.input_schema') {
      this.store.updateNodeConfig(id, `params.${field.key}`, value);
    } else {
      this.store.updateNodeData(id, field.key, value);
    }
  }

  // ---- render-model -----------------------------------------------------
  /** Build a variable-picker FieldVM for one input `port`. Candidates are
   *  filtered to schemas compatible with the port; the current binding (a
   *  typed VariableRef or a legacy dot-path string) stays displayed. */
  private variableVm(
    nodeId: string,
    port: NodePort,
    candidates: VariableCandidate[],
    current: unknown,
  ): FieldVM {
    const compatible = filterCompatibleCandidates(candidates, port.schema);
    const options: VariableOption[] = [{ value: '', label: '— unbound —' }];
    let value = '';

    if (typeof current === 'string') {
      options.push({ value: LEGACY_VARIABLE_VALUE, label: `legacy: ${current}` });
      value = LEGACY_VARIABLE_VALUE;
    }

    let refValue = '';
    if (isVariableRef(current)) {
      refValue = encodeCandidateValue(current.node_id, current.path[0] ?? '');
      value = refValue;
    }

    let refListed = false;
    for (const c of compatible) {
      const v = encodeCandidateValue(c.node_id, c.port);
      options.push({ value: v, label: `${c.label} · ${c.schema}` });
      if (v === refValue) refListed = true;
    }
    if (isVariableRef(current) && !refListed && refValue) {
      options.push({ value: refValue, label: variableRefLabel(current) });
    }

    return {
      key: port.name,
      label: humanize(port.name),
      control: 'variable',
      type: port.schema,
      required: Boolean(port.required),
      description:
        port.description ??
        `Bind input "${port.name}" (${port.schema}) to an upstream output.`,
      options: [],
      source: 'node.inputs_map',
      runtimeReadPath: `nodes.${nodeId}.config.inputs_map.${port.name}`,
      stringValue: value,
      boolValue: false,
      jsonValue: '',
      invalid: false,
      error: null,
      variableOptions: options,
    };
  }

  private toVm(
    field: FlowManifestField,
    dataBag: Record<string, unknown>,
    configBag: Record<string, unknown>,
    error: string | null,
  ): FieldVM {
    const options = Array.isArray(field.enum) ? field.enum.map(String) : [];
    const control = this.controlFor(field, options);
    const value = this.liveValue(field, dataBag, configBag);
    const required = Boolean(field.required);
    const missing = value === undefined || value === null || value === '';
    return {
      key: field.key,
      label: humanize(field.key),
      control,
      type: String(field.type ?? 'string'),
      required,
      description: field.description ?? null,
      options,
      source: field.source,
      runtimeReadPath: this.runtimeReadPath(field),
      stringValue: this.asString(value),
      boolValue: value === true,
      jsonValue: this.asJson(value),
      invalid: Boolean(error) || (required && missing),
      error,
    };
  }

  private controlFor(field: FlowManifestField, options: string[]): ControlKind {
    if (options.length > 0) return 'select';
    switch (String(field.type ?? 'string')) {
      case 'boolean':
        return 'boolean';
      case 'integer':
      case 'number':
        return 'number';
      case 'object':
      case 'array':
        return 'json';
      case 'text':
        return 'textarea';
      default:
        return 'text';
    }
  }

  private liveValue(
    field: FlowManifestField,
    dataBag: Record<string, unknown>,
    configBag: Record<string, unknown>,
  ): unknown {
    if (field.source === 'node.config') return getPath(configBag, field.key);
    if (field.source === 'skill.input_schema') return getPath(configBag, `params.${field.key}`);
    return getPath(dataBag, field.key);
  }

  private runtimeReadPath(field: FlowManifestField): string {
    const id = this.node()?.id ?? '?';
    if (field.source === 'node.config') return `nodes.${id}.config.${field.key}`;
    if (field.source === 'skill.input_schema') return `nodes.${id}.config.params.${field.key}`;
    return `nodes.${id}.data.${field.key}`;
  }

  private asString(value: unknown): string {
    if (value === undefined || value === null) return '';
    if (typeof value === 'object') return '';
    return String(value);
  }

  private asJson(value: unknown): string {
    if (value === undefined || value === null) return '';
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  private errorKey(field: FlowManifestField): string {
    return `${field.source}:${field.key}`;
  }

  private setError(field: FieldVM, message: string): void {
    this.errors.update((prev) => ({ ...prev, [`${field.source}:${field.key}`]: message }));
  }

  private clearError(field: FieldVM): void {
    this.errors.update((prev) => {
      if (!(`${field.source}:${field.key}` in prev)) return prev;
      const next = { ...prev };
      delete next[`${field.source}:${field.key}`];
      return next;
    });
  }
}
