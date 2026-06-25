/**
 * `<app-flow-node>` — the custom Foblex node, rendered as an Angular
 * component and styled exclusively with `--ck-*` design tokens (no Material).
 *
 * It is mounted by the canvas with `[fNode]` on its host, so the Foblex
 * connector directives it renders (`fNodeInput` / `fNodeOutput`) resolve the
 * `F_NODE` token from the host element injector.
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
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { FlowNodeView } from './flow-foblex.adapter';
import { FlowManifestService } from './flow-manifest.service';
import { FlowRunService } from './flow-run.service';

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
  imports: [FFlowModule],
  styleUrl: './flow-node.component.scss',
  template: `
    <div
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
            [title]="breakpoint() ? 'Remove breakpoint' : 'Set breakpoint'"
            [attr.aria-pressed]="breakpoint()"
            aria-label="Toggle breakpoint"
          ></button>
        }
        <span class="ck-flow-node__pill">{{ typeLabel() }}</span>
        @if (badge(); as b) {
          <span
            class="ck-flow-node__badge"
            [attr.data-status]="b.status"
            [attr.data-operational]="b.operational"
            [title]="(b.operational ? 'Configured · ' : 'Not configured · ') + b.status"
          >
            {{ b.label }}
          </span>
        }
      </header>

      <div class="ck-flow-node__title">{{ label() }}</div>
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
  /** Optional: present whenever the node renders inside the builder shell. */
  private readonly run = inject(FlowRunService, { optional: true });

  readonly view = input.required<FlowNodeView>();
  readonly selected = input(false);

  private readonly node = computed<CanonicalFlowNode>(() => this.view().node);

  /** Breakpoint affordance shows only while the step-debugger is armed. */
  readonly debugArmed = computed(() => (this.run ? this.run.debugMode() !== 'off' : false));
  readonly breakpoint = computed(() => this.run?.isBreakpoint(this.node().id) ?? false);
  /** Pulse overlay while this node is the one currently executing / paused. */
  readonly runActive = computed(() => this.run?.isActiveNode(this.node().id) ?? false);

  onToggleBreakpoint(event: MouseEvent): void {
    event.stopPropagation();
    event.preventDefault();
    this.run?.toggleBreakpoint(this.node().id);
  }

  readonly kind = computed(() => this.node().kind ?? 'task');

  readonly label = computed(
    () => this.node().label || String(this.node().type),
  );

  readonly typeLabel = computed(() => {
    const node = this.node();
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    if (typeof cfg['skill_slug'] === 'string' && cfg['skill_slug']) return 'SKILL';
    if (typeof cfg['runtime_ref'] === 'string' && cfg['runtime_ref']) return 'RUNTIME';
    switch (node.kind ?? 'task') {
      case 'source':
        return 'TRIGGER';
      case 'sink':
        return 'OUTPUT';
      case 'decision':
        return 'ROUTER';
      case 'fork':
        return 'FORK';
      case 'join':
        return 'JOIN';
      case 'loop':
        return 'LOOP';
      case 'retry':
        return 'RETRY';
      case 'hitl':
        return 'HITL';
      case 'subflow':
        return 'SUBFLOW';
      default:
        return String(node.type).toUpperCase().slice(0, 12);
    }
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
