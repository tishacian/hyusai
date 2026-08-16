/**
 * Keyboard-first projection of the canonical Flow graph.
 *
 * This component owns no graph state: it reads and mutates the same FlowStore
 * as the canvas, so either surface can be used without conversion or loss.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
  output,
  signal,
  viewChildren,
} from '@angular/core';
import type {
  CanonicalFlowEdge,
  CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import { I18nService } from '@app/core/i18n.service';
import {
  connectorsToEdge,
  parseConnectorId,
  toConnectionViews,
} from './flow-foblex.adapter';
import {
  outlineSourceOptions,
  outlineTargetOptions,
  type OutlineConnectorOption,
} from './flow-outline.vm';
import { edgeKey, FlowStore } from './flow.store';

@Component({
  selector: 'app-flow-outline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-outline.component.scss',
  template: `
    <div class="flow-outline">
      <div class="flow-outline__intro">
        <div>
          <h2 id="flow-outline-title">{{ i18n.t('flow.outline.title') }}</h2>
          <p id="flow-outline-help">{{ i18n.t('flow.outline.help') }}</p>
        </div>
        <span class="flow-outline__count">
          {{ i18n.t('flow.outline.count', { count: store.nodeCount() }) }}
        </span>
      </div>

      <div class="flow-outline__grid">
        <section
          class="flow-outline__panel"
          aria-labelledby="flow-outline-nodes-title"
        >
          <h3 id="flow-outline-nodes-title">{{ i18n.t('flow.outline.nodes') }}</h3>
          <ol class="flow-outline__nodes" aria-describedby="flow-outline-help">
            @for (node of store.nodes(); track node.id; let index = $index) {
              <li
                class="flow-outline__node"
                [class.is-selected]="node.id === store.selectedNodeId()"
              >
                <button
                  #nodeButton
                  type="button"
                  class="flow-outline__select"
                  [attr.data-node-id]="node.id"
                  [attr.aria-current]="node.id === store.selectedNodeId() ? 'true' : null"
                  [attr.aria-label]="i18n.t('flow.outline.inspect', { name: nodeName(node) })"
                  aria-keyshortcuts="ArrowUp ArrowDown Home End Alt+ArrowUp Alt+ArrowDown"
                  (click)="inspect(node.id)"
                  (keydown)="onNodeKeydown($event, index)"
                >
                  <span class="flow-outline__ordinal" aria-hidden="true">{{ index + 1 }}</span>
                  <span class="flow-outline__identity">
                    <strong>{{ nodeName(node) }}</strong>
                    <span>{{ nodeRole(node) }} · {{ node.id }}</span>
                  </span>
                  <span class="flow-outline__routes">
                    {{
                      i18n.t('flow.outline.routes', {
                        incoming: incomingCount(node.id),
                        outgoing: outgoingCount(node.id),
                      })
                    }}
                  </span>
                </button>

                <details class="flow-outline__move">
                  <summary>{{ i18n.t('flow.outline.move') }}</summary>
                  <div
                    class="flow-outline__move-controls"
                    role="group"
                    [attr.aria-label]="i18n.t('flow.outline.move.aria', { name: nodeName(node) })"
                  >
                    <button
                      type="button"
                      [disabled]="editingLocked() || index === 0"
                      [attr.aria-label]="i18n.t('flow.outline.order.before', { name: nodeName(node) })"
                      (click)="reorder(node.id, -1, index)"
                    >
                      {{ i18n.t('flow.outline.order.before.short') }}
                    </button>
                    <button
                      type="button"
                      [disabled]="editingLocked() || index === store.nodeCount() - 1"
                      [attr.aria-label]="i18n.t('flow.outline.order.after', { name: nodeName(node) })"
                      (click)="reorder(node.id, 1, index)"
                    >
                      {{ i18n.t('flow.outline.order.after.short') }}
                    </button>
                    <label>
                      <span>{{ i18n.t('flow.outline.position.x') }}</span>
                      <input
                        type="number"
                        step="24"
                        [value]="node.position?.x ?? 120"
                        [disabled]="editingLocked()"
                        (change)="moveOnCanvas(node, 'x', $event)"
                      />
                    </label>
                    <label>
                      <span>{{ i18n.t('flow.outline.position.y') }}</span>
                      <input
                        type="number"
                        step="24"
                        [value]="node.position?.y ?? 120"
                        [disabled]="editingLocked()"
                        (change)="moveOnCanvas(node, 'y', $event)"
                      />
                    </label>
                  </div>
                </details>
              </li>
            } @empty {
              <li class="flow-outline__empty">{{ i18n.t('flow.outline.empty') }}</li>
            }
          </ol>
        </section>

        <section
          class="flow-outline__panel flow-outline__connections"
          aria-labelledby="flow-outline-connections-title"
        >
          <h3 id="flow-outline-connections-title">{{ i18n.t('flow.outline.connections') }}</h3>
          <fieldset class="flow-outline__composer" [disabled]="editingLocked()">
            <legend>{{ i18n.t('flow.outline.connect') }}</legend>
            <label>
              <span>{{ i18n.t('flow.outline.connect.source') }}</span>
              <select [value]="sourceId()" (change)="chooseSource($event)">
                <option value="">{{ i18n.t('flow.outline.connect.source.placeholder') }}</option>
                @for (option of sourceOptions(); track option.id) {
                  <option [value]="option.id">{{ connectorLabel(option) }}</option>
                }
              </select>
            </label>
            <label>
              <span>{{ i18n.t('flow.outline.connect.target') }}</span>
              <select
                [value]="targetId()"
                [disabled]="!selectedSource()"
                (change)="chooseTarget($event)"
              >
                <option value="">{{ i18n.t('flow.outline.connect.target.placeholder') }}</option>
                @for (option of targetOptions(); track option.id) {
                  <option [value]="option.id">{{ connectorLabel(option) }}</option>
                }
              </select>
            </label>
            @if (selectedSource() && targetOptions().length === 0) {
              <p class="flow-outline__hint">{{ i18n.t('flow.outline.connect.no_target') }}</p>
            } @else if (duplicateConnection()) {
              <p class="flow-outline__hint">{{ i18n.t('flow.outline.connect.duplicate') }}</p>
            }
            <button
              type="button"
              class="flow-outline__connect"
              [disabled]="!connectionCandidate() || duplicateConnection()"
              (click)="connect()"
            >
              {{ i18n.t('flow.outline.connect.action') }}
            </button>
          </fieldset>

          <h4>{{ i18n.t('flow.outline.connections.current') }}</h4>
          <ol class="flow-outline__edges">
            @for (edge of store.edges(); track edgeKey(edge)) {
              <li>
                <span>{{ edgeLabel(edge) }}</span>
                <button
                  type="button"
                  [disabled]="editingLocked()"
                  [attr.aria-label]="i18n.t('flow.outline.disconnect', { edge: edgeLabel(edge) })"
                  (click)="disconnect(edge)"
                >
                  {{ i18n.t('flow.outline.disconnect.short') }}
                </button>
              </li>
            } @empty {
              <li class="flow-outline__empty">{{ i18n.t('flow.outline.connections.empty') }}</li>
            }
          </ol>
        </section>
      </div>

      <p class="flow-outline__live" role="status" aria-live="polite">{{ announcement() }}</p>
    </div>
  `,
})
export class FlowOutlineComponent {
  protected readonly store = inject(FlowStore);
  protected readonly i18n = inject(I18nService);

  readonly editingLocked = input(false);
  readonly inspectNode = output<string>();

  protected readonly sourceId = signal('');
  protected readonly targetId = signal('');
  protected readonly announcement = signal('');
  protected readonly nodeButtons = viewChildren<ElementRef<HTMLButtonElement>>('nodeButton');

  protected readonly sourceOptions = computed(() => outlineSourceOptions(this.store.nodes()));
  protected readonly selectedSource = computed(() =>
    this.sourceOptions().find((option) => option.id === this.sourceId()) ?? null,
  );
  protected readonly targetOptions = computed(() =>
    outlineTargetOptions(this.store.nodes(), this.selectedSource()?.id ?? ''),
  );
  protected readonly connectionCandidate = computed<CanonicalFlowEdge | null>(() =>
    connectorsToEdge(this.sourceId(), this.targetId(), this.store.nodes()),
  );
  protected readonly duplicateConnection = computed(() => {
    const candidate = this.connectionCandidate();
    return !!candidate && this.store.edges().some((edge) => edgeKey(edge) === edgeKey(candidate));
  });

  protected readonly edgeKey = edgeKey;

  protected inspect(nodeId: string): void {
    this.store.setSelection(nodeId);
    this.inspectNode.emit(nodeId);
  }

  protected onNodeKeydown(event: KeyboardEvent, index: number): void {
    const nodes = this.store.nodes();
    let target = index;
    if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
      if (this.editingLocked()) return;
      const direction = event.key === 'ArrowUp' ? -1 : 1;
      target = index + direction;
      if (target < 0 || target >= nodes.length) return;
      event.preventDefault();
      this.reorder(nodes[index].id, direction, index);
      return;
    }
    if (event.key === 'ArrowUp') target = Math.max(0, index - 1);
    else if (event.key === 'ArrowDown') target = Math.min(nodes.length - 1, index + 1);
    else if (event.key === 'Home') target = 0;
    else if (event.key === 'End') target = nodes.length - 1;
    else return;
    event.preventDefault();
    const node = nodes[target];
    if (!node) return;
    this.inspect(node.id);
    this.focusNodeButton(target);
  }

  protected reorder(nodeId: string, direction: -1 | 1, index: number): void {
    if (this.editingLocked()) return;
    this.store.reorderNode(nodeId, direction);
    this.inspect(nodeId);
    this.announce('flow.outline.announcement.reordered', {
      name: this.nodeName(this.store.nodes()[index + direction]),
    });
    this.focusNodeButton(index + direction);
  }

  protected moveOnCanvas(
    node: CanonicalFlowNode,
    axis: 'x' | 'y',
    event: Event,
  ): void {
    const input = event.target as HTMLInputElement;
    const value = input.valueAsNumber;
    const position = node.position ?? { x: 120, y: 120 };
    if (this.editingLocked() || !Number.isFinite(value)) {
      input.value = String(position[axis]);
      return;
    }
    if (value === position[axis]) return;
    this.store.patchNode(node.id, { position: { ...position, [axis]: value } });
    this.announce('flow.outline.announcement.moved', { name: this.nodeName(node) });
  }

  protected chooseSource(event: Event): void {
    this.sourceId.set((event.target as HTMLSelectElement).value);
    this.targetId.set('');
  }

  protected chooseTarget(event: Event): void {
    this.targetId.set((event.target as HTMLSelectElement).value);
  }

  protected connect(): void {
    if (this.editingLocked() || this.duplicateConnection()) return;
    const edge = this.connectionCandidate();
    if (!edge) return;
    this.store.connect(edge);
    this.announce('flow.outline.announcement.connected', { edge: this.edgeLabel(edge) });
    this.targetId.set('');
  }

  protected disconnect(edge: CanonicalFlowEdge): void {
    if (this.editingLocked()) return;
    const label = this.edgeLabel(edge);
    this.store.disconnect(edge);
    this.announce('flow.outline.announcement.disconnected', { edge: label });
  }

  protected connectorLabel(option: OutlineConnectorOption): string {
    return this.i18n.t('flow.outline.connector.option', {
      node: option.nodeLabel,
      port: option.name || this.i18n.t('flow.outline.port.default'),
    });
  }

  protected edgeLabel(edge: CanonicalFlowEdge): string {
    const view = toConnectionViews([edge], this.store.nodes())[0];
    const source = parseConnectorId(view?.source);
    const target = parseConnectorId(view?.target);
    return this.i18n.t('flow.outline.edge.label', {
      source: this.nodeNameById(edge.from),
      sourcePort: source?.port || this.i18n.t('flow.outline.port.default'),
      target: this.nodeNameById(edge.to),
      targetPort: target?.port || this.i18n.t('flow.outline.port.default'),
    });
  }

  protected nodeName(node: CanonicalFlowNode | undefined): string {
    return node?.label?.trim() || String(node?.type ?? '');
  }

  protected nodeRole(node: CanonicalFlowNode): string {
    const config = (node.config ?? {}) as Record<string, unknown>;
    const kind = typeof config['skill_slug'] === 'string' && config['skill_slug']
      ? 'skill'
      : typeof config['runtime_ref'] === 'string' && config['runtime_ref']
        ? 'runtime'
        : (node.kind ?? 'task');
    const key = `flow.node.kind.${kind}`;
    const label = this.i18n.t(key);
    return label === key ? String(node.type) : label;
  }

  protected incomingCount(nodeId: string): number {
    return this.store.edges().filter((edge) => edge.to === nodeId).length;
  }

  protected outgoingCount(nodeId: string): number {
    return this.store.edges().filter((edge) => edge.from === nodeId).length;
  }

  private nodeNameById(nodeId: string): string {
    return this.nodeName(this.store.nodes().find((node) => node.id === nodeId)) || nodeId;
  }

  private focusNodeButton(index: number): void {
    queueMicrotask(() => this.nodeButtons()[index]?.nativeElement.focus());
  }

  private announce(key: string, params: Record<string, string | number>): void {
    this.announcement.set('');
    queueMicrotask(() => this.announcement.set(this.i18n.t(key, params)));
  }
}
