/**
 * `<app-flow-node>` — the custom Foblex node, rendered as an Angular
 * component and styled exclusively with `--ck-*` design tokens (no Material).
 *
 * It is mounted by the canvas with `[fNode]` on its host, so the Foblex
 * connector directives it renders (`fNodeInput` / `fNodeOutput`) resolve the
 * `F_NODE` token from the host element injector.
 *
 * The card carries `fDragHandle`: Foblex 18.6 only starts a node-move drag when
 * the pointer-down element has a `.f-drag-handle` ancestor (older versions made
 * the whole node draggable by default). Without it the node merely selects and
 * never moves. Ports stay connection-only because the connection-create
 * preparation runs before the node-drag preparation.
 *
 * P2: the runtime status badge is driven by the backend manifest's
 * `runtime_status` / `operational` for this node (the real "configured?"
 * verdict). The shared `FlowManifestService` provides it without coupling the
 * node to the manifest fetch — the shell triggers the single (deduped) fetch,
 * and each node just reads its own status by id, reactively. The status is
 * NOT written into the canonical model, so the graph is never spuriously
 * dirtied.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import { FFlowModule } from '@foblex/flow';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { FlowNodeView } from './flow-foblex.adapter';
import { FlowManifestService } from './flow-manifest.service';
import { FlowPersistenceService } from './flow-persistence.service';
import { FlowRunService } from './flow-run.service';
import { FlowStore } from './flow.store';

type NodeTone = 'brand' | 'cyan' | 'violet' | 'emerald' | 'amber' | 'rose';

interface RuntimeBadge {
  status: string;
  label: string;
  operational: boolean;
}

@Component({
  selector: 'app-flow-node',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FFlowModule, IconComponent],
  styleUrl: './flow-node.component.scss',
  template: `
    <div
      fDragHandle
      class="ck-flow-node"
      [class.is-selected]="selected()"
      [class.is-active]="runActive()"
      [class.has-breakpoint]="breakpoint()"
      [attr.data-tone]="tone()"
      [attr.data-kind]="kind()"
    >
      <span class="ck-flow-node__bar" aria-hidden="true"></span>

      <header class="ck-flow-node__head">
        @if (debugArmed()) {
          <button
            type="button"
            class="ck-flow-node__bp"
            [class.is-on]="breakpoint()"
            (click)="onToggleBreakpoint($event)"
            (mousedown)="$event.stopPropagation()"
            [title]="
              breakpoint()
                ? i18n.t('flow.node.breakpoint.remove')
                : i18n.t('flow.node.breakpoint.set')
            "
            [attr.aria-pressed]="breakpoint()"
            [attr.aria-label]="i18n.t('flow.node.breakpoint.aria')"
          ></button>
        }
        <span class="ck-flow-node__pill">{{ typeLabel() }}</span>
        <span class="ck-flow-node__spacer"></span>
        @if (badge(); as b) {
          <span
            class="ck-flow-node__badge"
            [attr.data-status]="b.status"
            [attr.data-operational]="b.operational"
            [title]="
              (b.operational
                ? i18n.t('flow.node.configured')
                : i18n.t('flow.node.not_configured')) + ' · ' + b.status
            "
          >
            {{ b.label }}
          </span>
        }
        <button
          type="button"
          class="ck-flow-node__delete"
          (click)="onDeleteNode(view().id, $event)"
          (mousedown)="$event.stopPropagation()"
          [disabled]="editingLocked()"
          [attr.aria-label]="i18n.t('flow.node.delete', { name: label() })"
          aria-keyshortcuts="Delete Backspace"
          [title]="i18n.t('flow.node.delete.hint', { name: label() })"
        >
          <app-icon name="trash-2" [size]="14" />
        </button>
      </header>

      <div class="ck-flow-node__title">
        @if (kind() === 'asset') {
          <app-icon name="database" [size]="13" class="ck-flow-node__title-icon" />
        }
        {{ label() }}
      </div>
      @if (description(); as desc) {
        <div class="ck-flow-node__desc">{{ desc }}</div>
      }

      @for (inp of view().inputs; track inp.id; let i = $index) {
        <div
          fNodeInput
          [fInputId]="inp.id"
          fInputMultiple
          class="ck-flow-port ck-flow-port--in"
          [style.top]="portOffset(i, view().inputs.length)"
          [title]="inp.name || 'input'"
        ></div>
      }
      @for (out of view().outputs; track out.id; let i = $index) {
        <div
          fNodeOutput
          [fOutputId]="out.id"
          fOutputMultiple
          class="ck-flow-port ck-flow-port--out"
          [style.top]="portOffset(i, view().outputs.length)"
          [title]="out.name || 'output'"
        ></div>
      }
    </div>
  `,
})
export class FlowNodeComponent {
  private readonly manifest = inject(FlowManifestService);
  private readonly store = inject(FlowStore);
  private readonly persistence = inject(FlowPersistenceService, { optional: true });
  /** Optional: present whenever the node renders inside the builder shell. */
  private readonly run = inject(FlowRunService, { optional: true });
  readonly i18n = inject(I18nService);

  readonly view = input.required<FlowNodeView>();
  readonly selected = input(false);

  private readonly node = computed<CanonicalFlowNode>(() => this.view().node);

  /** Breakpoint affordance shows only while the step-debugger is armed. */
  readonly debugArmed = computed(() => (this.run ? this.run.debugMode() !== 'off' : false));
  readonly breakpoint = computed(() => this.run?.isBreakpoint(this.node().id) ?? false);
  /** Pulse overlay while this node is the one currently executing / paused. */
  readonly runActive = computed(() => this.run?.isActiveNode(this.node().id) ?? false);
  readonly editingLocked = computed(() => this.persistence?.actionsDisabled() ?? false);

  onToggleBreakpoint(event: MouseEvent): void {
    event.stopPropagation();
    event.preventDefault();
    this.run?.toggleBreakpoint(this.node().id);
  }

  onDeleteNode(nodeId: string, event: MouseEvent): void {
    event.stopPropagation();
    event.preventDefault();
    if (this.editingLocked()) return;
    this.store.removeNode(nodeId);
  }

  readonly kind = computed(() => this.node().kind ?? 'task');

  readonly label = computed(
    () => this.node().label || String(this.node().type),
  );

  /**
   * The pill names the node's role in plain words. API kinds (`sink`, `hitl`)
   * never reach the label: the key carries the canonical term and the raw kind
   * stays on `data-kind` for styling and for whoever inspects the DOM.
   */
  readonly typeLabel = computed(() => {
    const node = this.node();
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    const kind = typeof cfg['skill_slug'] === 'string' && cfg['skill_slug']
      ? 'skill'
      : typeof cfg['runtime_ref'] === 'string' && cfg['runtime_ref']
        ? 'runtime'
        : (node.kind ?? 'task');
    const key = `flow.node.kind.${kind}`;
    const label = this.i18n.t(key);
    return label === key ? String(node.type).toUpperCase().slice(0, 12) : label;
  });

  readonly description = computed<string | null>(() => {
    const node = this.node();
    const data = node.data ?? {};
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    const explicit = data['description'];
    if (typeof explicit === 'string' && explicit.trim()) return explicit.trim();
    const runtime = cfg['runtime_ref'] ?? data['runtime_ref'];
    if (typeof runtime === 'string' && runtime.trim()) return runtime.trim();
    const skill = cfg['skill_slug'];
    if (typeof skill === 'string' && skill.trim()) return skill.trim();
    return null;
  });

  readonly tone = computed<NodeTone>(() => {
    const node = this.node();
    switch (node.kind ?? 'task') {
      case 'source':
      case 'sink':
        return 'emerald';
      case 'asset':
        return 'cyan';
      case 'decision':
      case 'fork':
      case 'join':
      case 'subflow':
        return 'violet';
      case 'loop':
      case 'retry':
      case 'hitl':
        return 'amber';
      default:
        break;
    }
    const type = String(node.type);
    if (type === 'guardrail' || type === 'policy') return 'rose';
    if (type === 'retrieve' || type === 'context') return 'violet';
    if (type === 'llm') return 'cyan';
    if (type === 'tool' || type === 'skill') return 'emerald';
    return 'cyan';
  });

  /**
   * P2: surface the real runtime status from the manifest (bound / stub /
   * unbound / manifest_only). Falls back to a `runtime_status` stamped on the
   * node's own data for backward compat; otherwise no badge (e.g. scratchpad
   * with no bound system).
   */
  readonly badge = computed<RuntimeBadge | null>(() => {
    const node = this.node();
    const fromManifest = this.manifest.statusFor(node.id);
    if (fromManifest) {
      return {
        status: fromManifest.status,
        operational: fromManifest.operational,
        label: fromManifest.status.replace(/_/g, ' ').toUpperCase(),
      };
    }
    const stamped = (node.data ?? {})['runtime_status'];
    if (typeof stamped === 'string' && stamped) {
      return {
        status: stamped,
        operational: stamped === 'bound',
        label: stamped.replace(/_/g, ' ').toUpperCase(),
      };
    }
    return null;
  });

  portOffset(index: number, count: number): string {
    if (count <= 1) return '50%';
    const step = 100 / (count + 1);
    return `${step * (index + 1)}%`;
  }
}
