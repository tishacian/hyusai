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
import { I18nService } from '@app/core/i18n.service';
import { navigationSurfaceUrl } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { FlowStore } from './flow.store';
import { FlowIngressAvailabilityService } from './flow-ingress-availability.service';
import { FlowSchemaEditorComponent } from './flow-schema-editor.component';
import {
  INGRESS_KINDS,
  derivedIngressKind,
  isIngressKind,
  type IngressKind,
} from './flow-contract-bindings.vm';

@Component({
  selector: 'app-flow-ingress-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FlowSchemaEditorComponent, HelpTooltipComponent],
  styleUrl: './flow-ingress-editor.component.scss',
  template: `
    @if (node(); as n) {
      <div class="ck-ingress">
        <label class="ck-ingress__field">
          <span class="ck-ingress__label">
            {{ i18n.t('flow.entry.kind') }}
            <ck-help id="concept.entry-point" />
          </span>
          <select
            class="ck-ingress__select"
            data-testid="ingress-kind-select"
            [value]="declaredKind() ?? ''"
            (change)="onKind($event)"
          >
            <option value="">
              {{
                derived()
                  ? i18n.t('flow.entry.kind.derived.value', { name: labelFor(derived()!) })
                  : i18n.t('flow.entry.kind.derived')
              }}
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
                {{ i18n.t('flow.entry.event.unsaved') }}
              </p>
            } @else if (availability.state() === 'loading') {
              <p class="ck-ingress__note">{{ i18n.t('flow.entry.event.checking') }}</p>
            } @else if (availability.state() === 'error') {
              <p class="ck-ingress__note ck-ingress__note--warn" role="status">
                {{ i18n.t('flow.entry.event.unreadable') }}
              </p>
            } @else if (!availability.eventsEnabled()) {
              <p
                class="ck-ingress__note ck-ingress__note--warn"
                role="status"
                data-testid="ingress-event-unavailable"
              >
                {{ i18n.t('flow.entry.event.off') }}
              </p>
            } @else if (availability.mode() === 'dry_run') {
              <p class="ck-ingress__note ck-ingress__note--warn" role="status">
                {{ i18n.t('flow.entry.event.dry_run') }}
              </p>
            } @else {
              <p class="ck-ingress__note ck-ingress__note--ok" role="status">
                {{ i18n.t('flow.entry.event.live') }}
              </p>
            }
          }

          @if (kind === 'http' || kind === 'schedule') {
            <p class="ck-ingress__note">
              {{
                kind === 'http'
                  ? i18n.t('flow.entry.registration.http')
                  : i18n.t('flow.entry.registration.schedule')
              }}
              <a class="ck-ingress__link" [routerLink]="triggersHref()">{{
                i18n.t('flow.entry.registration.link')
              }}</a
              >.
            </p>
          }
        }

        <app-flow-schema-editor
          configKey="input_schema"
          [label]="i18n.t('flow.entry.schema.label')"
          deriveFrom="outputs"
          [hint]="schemaHint()"
          [fallbackHint]="i18n.t('flow.entry.schema.fallback')"
        />
      </div>
    }
  `,
})
export class FlowIngressEditorComponent {
  private readonly store = inject(FlowStore);
  private readonly navigation = inject(ZoomContextService);
  protected readonly availability = inject(FlowIngressAvailabilityService);
  readonly i18n = inject(I18nService);

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
    this.i18n.t(
      this.effectiveKind() === 'manual'
        ? 'flow.entry.schema.hint.manual'
        : 'flow.entry.schema.hint.other',
    ),
  );

  constructor() {
    effect(() => {
      if (this.effectiveKind() !== 'event') return;
      this.availability.ensureLoaded(this.systemId());
    });
  }

  protected labelFor(kind: IngressKind): string {
    return this.i18n.t(`flow.entry.kind.${kind}`);
  }

  protected noteFor(kind: IngressKind): string {
    return this.i18n.t(`flow.entry.note.${kind}`);
  }

  /** Dead `/orchestration/triggers` → current System's Runs facet, else Scratchpad. */
  protected readonly triggersHref = computed(() => {
    const id = this.systemId();
    if (!id) return navigationSurfaceUrl('orchestration');
    return this.navigation.objectUrl('system', id, { facet: 'runs' });
  });

  protected onKind(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    const value = (event.target as HTMLSelectElement).value;
    this.store.updateNodeConfig(id, 'ingress_kind', isIngressKind(value) ? value : null);
  }
}
