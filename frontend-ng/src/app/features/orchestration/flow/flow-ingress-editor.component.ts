/**
 * `<app-flow-ingress-editor>` — what actually starts this Flow, and with what.
 *
 * A source node is the Flow's entry point, but until now nothing in the
 * inspector said *how* it is entered. Publication derives an ingress kind from
 * the node type (`flow_contracts._ingress_kind`) and the operator never saw the
 * result, so a Trigger node looked identical whether it was reachable by
 * Execute, by cron, or by an internal event that the workspace does not even
 * have switched on.
 *
 * This editor makes both halves visible and editable:
 *   - the ingress KIND, written to `config.ingress_kind`, with the derived
 *     value shown whenever nothing is declared, and
 *   - the ingress PAYLOAD SCHEMA (`config.input_schema`), which becomes the
 *     frozen contract every Run's `input_ref` is validated against.
 *
 * Availability is reported, never assumed. `event` only reaches a Run when
 * event triggers are enabled for the System, so the option stays selectable
 * (an operator may be authoring ahead of an ops change) but is labelled with
 * what would actually happen today.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { FlowStore } from './flow.store';
import { FlowIngressAvailabilityService } from './flow-ingress-availability.service';
import { FlowSchemaEditorComponent } from './flow-schema-editor.component';
import {
  INGRESS_KINDS,
  derivedIngressKind,
  isIngressKind,
  type IngressKind,
} from './flow-contract-bindings.vm';

const KIND_LABELS: Record<IngressKind, string> = {
  manual: 'Manual — Execute, or an API call',
  chat: 'Chat — the System conversation surface',
  http: 'HTTP — inbound webhook',
  schedule: 'Schedule — cron',
  event: 'Event — internal (SFTP arrival, deposit promoted)',
};

const KIND_NOTES: Record<IngressKind, string> = {
  manual: 'Runs start from Execute or from a run request. The payload is the Run input.',
  chat: 'Runs start from a chat turn on this System.',
  http: 'Runs start on an inbound call. Register the webhook below before it can fire.',
  schedule: 'Runs start on a cron tick. Register the schedule below before it can fire.',
  event: 'Runs start on an internal event emitted by the platform.',
};

@Component({
  selector: 'app-flow-ingress-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FlowSchemaEditorComponent],
  styleUrl: './flow-ingress-editor.component.scss',
  template: `
    @if (node(); as n) {
      <div class="ck-ingress">
        <label class="ck-ingress__field">
          <span class="ck-ingress__label">Entry kind</span>
          <select
            class="ck-ingress__select"
            data-testid="ingress-kind-select"
            [value]="declaredKind() ?? ''"
            (change)="onKind($event)"
          >
            <option value="">
              Derived at publication{{ derived() ? ' — ' + derived() : '' }}
            </option>
            @for (kind of kinds; track kind) {
              <option [value]="kind" [selected]="kind === declaredKind()">
                {{ labelFor(kind) }}
              </option>
            }
          </select>
        </label>

        @if (effectiveKind(); as kind) {
          <p class="ck-ingress__note">{{ noteFor(kind) }}</p>

          @if (kind === 'event') {
            @if (!systemId()) {
              <p class="ck-ingress__note ck-ingress__note--warn" role="status">
                Event delivery cannot be checked until this Flow is saved into a
                System.
              </p>
            } @else if (availability.state() === 'loading') {
              <p class="ck-ingress__note">Checking event delivery…</p>
            } @else if (availability.state() === 'error') {
              <p class="ck-ingress__note ck-ingress__note--warn" role="status">
                Event delivery could not be read for this System.
              </p>
            } @else if (!availability.eventsEnabled()) {
              <p
                class="ck-ingress__note ck-ingress__note--warn"
                role="status"
                data-testid="ingress-event-unavailable"
              >
                Event triggers are switched off for this workspace. Publishing is
                allowed, but no event will start a Run until an administrator
                enables them.
              </p>
            } @else if (availability.mode() === 'dry_run') {
              <p class="ck-ingress__note ck-ingress__note--warn" role="status">
                Event triggers are enabled but in dry-run: a matching event is
                recorded without starting a Run. Switch to live below.
              </p>
            } @else {
              <p class="ck-ingress__note ck-ingress__note--ok" role="status">
                Event triggers are live for this System.
              </p>
            }
          }

          @if (kind === 'http' || kind === 'schedule') {
            <p class="ck-ingress__note">
              A declared kind is not a registration. Create the
              {{ kind === 'http' ? 'webhook' : 'schedule' }} in the Triggers
              panel below, or under
              <a class="ck-ingress__link" routerLink="/orchestration/triggers">
                Triggers</a>.
            </p>
          }
        }

        <app-flow-schema-editor
          configKey="input_schema"
          label="Entry payload schema"
          deriveFrom="outputs"
          [hint]="schemaHint()"
          fallbackHint="No schema declared — publication derives one from this node's output ports and accepts any extra field."
        />
      </div>
    }
  `,
})
export class FlowIngressEditorComponent {
  private readonly store = inject(FlowStore);
  protected readonly availability = inject(FlowIngressAvailabilityService);

  readonly systemId = input<string | null>(null);

  protected readonly kinds = INGRESS_KINDS;
  protected readonly node = this.store.selectedNode;

  protected readonly declaredKind = computed<IngressKind | null>(() => {
    const raw = ((this.node()?.config ?? {}) as Record<string, unknown>)['ingress_kind'];
    return isIngressKind(raw) ? raw : null;
  });

  protected readonly derived = computed<IngressKind | null>(() => {
    const node = this.node();
    return node ? derivedIngressKind(node) : null;
  });

  protected readonly effectiveKind = computed<IngressKind | null>(
    () => this.declaredKind() ?? this.derived(),
  );

  protected readonly schemaHint = computed(() =>
    this.effectiveKind() === 'manual'
      ? 'Validated against every Run input before the Run is accepted — this is what the Run input dialog has to satisfy.'
      : 'Validated against every incoming payload before the Run is accepted.',
  );

  constructor() {
    effect(() => {
      if (this.effectiveKind() !== 'event') return;
      this.availability.ensureLoaded(this.systemId());
    });
  }

  protected labelFor(kind: IngressKind): string {
    return KIND_LABELS[kind];
  }

  protected noteFor(kind: IngressKind): string {
    return KIND_NOTES[kind];
  }

  protected onKind(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    const value = (event.target as HTMLSelectElement).value;
    this.store.updateNodeConfig(id, 'ingress_kind', isIngressKind(value) ? value : null);
  }
}
