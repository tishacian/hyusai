import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from "@angular/core";
import { FormsModule } from "@angular/forms";
import { DecimalPipe } from "@angular/common";
import { ApiService } from "@app/core/api.service";
import { WorkspaceService } from "@app/core/workspace.service";
import { AdoptionService } from "@app/core/adoption.service";
import { I18nService } from "@app/core/i18n.service";
import { NavLinkDirective } from "@app/shared/cockpit";
interface Objective {
  metric: string;
  target: number;
  period_start: string;
  period_end: string;
  owner: string;
  comparison_reference: string;
}
interface Metric {
  metric: string;
  value: number | null;
  unit: string;
  sample_count: number;
  source: string;
  delta: number | null;
  complete: boolean;
}
interface Metrics {
  system_id: string;
  objective: Objective | null;
  metrics: Metric[];
  demonstration: boolean;
  complete: boolean;
  can_edit: boolean;
  run_ids: string[];
  period_start: string;
  period_end: string;
}
@Component({
  selector: "app-operational-objective",
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DecimalPipe, NavLinkDirective],
  template: `@if (adoption.enabled()) {
    <section class="objective">
      <h3>{{ t("objective") }}</h3>
      @if (!systemId()) {
        <label
          >{{ t("select_system") }}
          <select [ngModel]="selected()" (ngModelChange)="selected.set($event)">
            <option value="">—</option>
            @for (s of systems(); track s.system_id) {
              <option [value]="s.system_id">{{ s.name }}</option>
            }
          </select></label
        >
      }
      @if (error()) {
        <p role="alert">{{ t("objective_error") }}</p>
        <button type="button" (click)="load()">
          {{ i18n.t("common.retry") }}
        </button>
      }
      @if (data(); as d) {
        @if (d.demonstration) {
          <p role="note">{{ t("demo") }}</p>
        }
        <p>{{ t("value_explanation") }}</p>
        @if (d.objective; as o) {
          <p>
            <strong>{{ t(o.metric) }}</strong> · {{ t("target") }}
            {{ o.target }} · {{ o.period_start }} → {{ o.period_end }} ·
            {{ o.owner }}
          </p>
          <p>{{ t("reference") }}: {{ o.comparison_reference }}</p>
        } @else {
          <p>{{ t("objective_missing") }}</p>
        }
        <p>
          {{ d.period_start.slice(0, 10) }} → {{ d.period_end.slice(0, 10) }}
        </p>
        <dl>
          @for (m of d.metrics; track m.metric) {
            <div>
              <dt>{{ t(m.metric) }}</dt>
              <dd>
                {{
                  m.value === null ? t("missing") : (m.value | number: "1.0-2")
                }}
                {{ m.value === null ? "" : m.unit }} · {{ m.sample_count }}
                {{ t("samples") }}
                @if (m.delta !== null) {
                  <p>
                    {{ t("delta") }}: {{ m.delta | number: "1.0-2" }}
                    {{ m.unit }}
                  </p>
                } @else if (!m.complete || d.objective?.metric === m.metric) {
                  <small>{{ t("incomplete") }}</small>
                }
                <details>
                  <summary>{{ t("provenance") }}</summary>
                  <code>{{ m.source }}</code>
                </details>
              </dd>
            </div>
          }
        </dl>
        <p>{{ t("no_impact") }}</p>
        <a
          [navLink]="{
            type: 'system',
            ref: d.system_id,
            lens: 'steer',
            facet: 'overview',
          }"
          >{{ t("value_loop") }}</a
        >
        @for (id of d.run_ids.slice(0, 3); track id) {
          <a [navLink]="{ type: 'run', lens: 'operate', ref: id }"
            >{{ t("inspect_run") }} · {{ id.slice(0, 8) }}</a
          >
        }
        @if (d.can_edit) {
          <details>
            <summary>{{ t("edit") }}</summary>
            <form (ngSubmit)="save()">
              <label
                >{{ t("metric")
                }}<select name="metric" [(ngModel)]="draft.metric">
                  @for (key of metrics; track key) {
                    <option [value]="key">{{ t(key) }}</option>
                  }
                </select></label
              >
              <label
                >{{ t("target")
                }}<input
                  type="number"
                  name="target"
                  min="0"
                  step="any"
                  [(ngModel)]="draft.target"
                  required
              /></label>
              <label
                >{{ t("from")
                }}<input
                  type="date"
                  name="start"
                  [(ngModel)]="draft.period_start"
                  required
              /></label>
              <label
                >{{ t("until")
                }}<input
                  type="date"
                  name="end"
                  [(ngModel)]="draft.period_end"
                  required
              /></label>
              <label
                >{{ t("owner")
                }}<input
                  name="owner"
                  [(ngModel)]="draft.owner"
                  maxlength="160"
                  required
              /></label>
              <label
                >{{ t("reference")
                }}<input
                  name="reference"
                  [(ngModel)]="draft.comparison_reference"
                  maxlength="500"
                  required
              /></label>
              <button type="submit" [disabled]="saving()">
                {{ t("save") }}
              </button>
            </form>
          </details>
        }
      }
    </section>
  }`,
  styles: [
    `
      .objective {
        margin: 1rem 0;
        padding: 1rem;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 0.6rem;
      }
      dl {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
        gap: 1rem;
      }
      dd {
        margin: 0;
      }
      dt {
        font-weight: 600;
      }
      p {
        line-height: 1.5;
      }
      label {
        display: block;
        margin: 0.6rem 0;
      }
      input,
      select {
        display: block;
        max-width: 100%;
        padding: 0.5rem;
        background: var(--ck-bg-base);
        color: inherit;
        border: 1px solid var(--ck-stroke-2);
      }
      a {
        display: inline-block;
        margin: 0.5rem;
      }
      small {
        display: block;
        color: var(--ck-fg-3);
      }
      button,
      summary {
        min-height: 2rem;
      }
      button {
        border: 1px solid var(--ck-stroke-2);
        padding: 0.5rem 1rem;
        border-radius: 0.4rem;
        background: var(--ck-bg-panel);
        color: var(--ck-fg-1);
      }
      button:disabled { opacity: 0.5; }
      a { text-decoration: underline; }
      :focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 3px; }
    `,
  ],
})
export class OperationalObjectiveComponent {
  readonly api = inject(ApiService);
  readonly workspace = inject(WorkspaceService);
  readonly adoption = inject(AdoptionService);
  readonly i18n = inject(I18nService);
  readonly systemId = input<string | null>(null);
  readonly selected = signal("");
  readonly data = signal<Metrics | null>(null);
  readonly error = signal(false);
  readonly saving = signal(false);
  readonly systems = signal<{ system_id: string; name: string }[]>([]);
  readonly metrics = [
    "completed_volume",
    "mean_duration_ms",
    "human_waits",
    "human_validation_rate",
    "measured_cost_usd",
  ];
  draft: Objective = {
    metric: "completed_volume",
    target: 1,
    period_start: "",
    period_end: "",
    owner: "",
    comparison_reference: "",
  };
  constructor() {
    // The component may survive a tenant change in the Impact shell.
    inject(DestroyRef).onDestroy(
      this.workspace.registerContextReset(() => {
        this.selected.set("");
        this.systems.set([]);
        this.data.set(null);
        this.error.set(false);
        this.saving.set(false);
      }),
    );
    effect(() => {
      this.workspace.currentSlug();
      if (this.adoption.enabled()) {
        if (this.systemId() || this.selected()) this.load();
        else this.loadSystems();
      }
    });
  }
  t(key: string): string {
    return this.i18n.t("experience.adoption." + key);
  }
  loadSystems(): void {
    const scope = this.workspace.captureRequestScope();
    this.api
      .get<{
        systems: { system_id: string; name: string }[];
      }>("/assistant/systems", undefined, {
        workspaceSlug: scope.workspaceSlug,
      })
      .subscribe({
        next: (d) => {
          if (this.workspace.isRequestScopeCurrent(scope))
            this.systems.set(d.systems);
        },
        error: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) this.error.set(true);
        },
      });
  }
  load(): void {
    const id = this.systemId() || this.selected();
    if (!id) return;
    const scope = this.workspace.captureRequestScope();
    this.data.set(null);
    this.error.set(false);
    this.api
      .get<Metrics>(
        `/systems/${encodeURIComponent(id)}/operational-metrics`,
        undefined,
        { workspaceSlug: scope.workspaceSlug },
      )
      .subscribe({
        next: (d) => {
          if (
            !this.workspace.isRequestScopeCurrent(scope) ||
            id !== (this.systemId() || this.selected())
          )
            return;
          this.data.set(d);
          this.draft = d.objective
            ? { ...d.objective }
            : {
                metric: "completed_volume",
                target: 1,
                period_start: "",
                period_end: "",
                owner: "",
                comparison_reference: "",
              };
        },
        error: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) this.error.set(true);
        },
      });
  }
  save(): void {
    const id = this.systemId() || this.selected();
    if (!id || this.saving()) return;
    const scope = this.workspace.captureRequestScope();
    this.saving.set(true);
    this.api
      .put<Objective>(
        `/systems/${encodeURIComponent(id)}/operational-objective`,
        this.draft,
        { workspaceSlug: scope.workspaceSlug },
      )
      .subscribe({
        next: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) {
            this.saving.set(false);
            this.load();
          }
        },
        error: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) {
            this.saving.set(false);
            this.error.set(true);
          }
        },
      });
  }
}
