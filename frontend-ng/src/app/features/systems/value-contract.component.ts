import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { gapLine, jobLineText, type AutomationGapView } from '@app/features/orchestration/flow/automation-job';
import {
  CONTRACT_INDICATORS,
  SOURCE_KINDS,
  formProblem,
  initialForm,
  proposalBody,
  refusalKey,
  type ContractForm,
  type ContractState,
  type ContractTerms,
} from './value-contract.vm';

/**
 * The value contract of an automation (ADR 0003 lot 3): a System
 * administrator proposes it, the owner it names approves or rejects it, and
 * only then does Work, Hypervisor and the Flow show it.
 */
@Component({
  selector: 'app-value-contract',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    @if (state(); as s) {
      @if (s.automation || s.current || s.pending) {
        <section class="value-contract" [attr.aria-label]="i18n.t('systems.value_contract.title')">
          <h3>{{ i18n.t('systems.value_contract.title') }}</h3>
          <p>{{ i18n.t('systems.value_contract.explanation') }}</p>
          @if (error()) {
            <p role="alert">{{ i18n.t(error()) }}</p>
          }
          @if (s.current; as c) {
            <h4>{{ i18n.t('systems.value_contract.current', { revision: c.revision, owner: c.owner, date: day(c.decided_at) }) }}</h4>
            <dl>
              @for (row of terms(c); track row.label) {
                <dt>{{ i18n.t(row.label) }}</dt>
                <dd>{{ row.value }}</dd>
              }
            </dl>
            <p>{{ gapText(s.gap) }}</p>
          } @else {
            <p>{{ i18n.t('systems.value_contract.none') }}</p>
          }
          @if (s.pending; as p) {
            <h4>{{ i18n.t('systems.value_contract.pending', { revision: p.revision, owner: p.owner, author: p.proposed_by }) }}</h4>
            <dl>
              @for (row of terms(p); track row.label) {
                <dt>{{ i18n.t(row.label) }}</dt>
                <dd>{{ row.value }}</dd>
              }
            </dl>
            @if (s.can_decide) {
              <label>
                {{ i18n.t('systems.value_contract.note') }}
                <textarea rows="2" maxlength="500" [ngModel]="note()" (ngModelChange)="note.set($event)"></textarea>
              </label>
              <button type="button" [disabled]="busy()" (click)="decide(p, true)">{{ i18n.t('systems.value_contract.approve') }}</button>
              <button type="button" [disabled]="busy()" (click)="decide(p, false)">{{ i18n.t('systems.value_contract.reject') }}</button>
            } @else {
              <p role="status">{{ i18n.t('systems.value_contract.waiting', { owner: p.owner }) }}</p>
            }
          }
          @if (s.can_propose) {
            <details [open]="!s.current && !s.pending">
              <summary>{{ i18n.t(s.current || s.pending ? 'systems.value_contract.propose_revision' : 'systems.value_contract.propose') }}</summary>
              <form class="value-contract-form" (ngSubmit)="propose()">
                <label>
                  {{ i18n.t('systems.value_contract.field.owner') }}
                  <select name="owner" [(ngModel)]="form.owner_user_id">
                    <option value="">—</option>
                    @for (option of s.owner_options; track option.user_id) {
                      <option [value]="option.user_id">{{ option.label }}</option>
                    }
                  </select>
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.indicator') }}
                  <select name="indicator" [(ngModel)]="form.indicator">
                    @for (indicator of indicators; track indicator) {
                      <option [value]="indicator">{{ i18n.t('experience.adoption.' + indicator) }}</option>
                    }
                  </select>
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.target') }}
                  <input name="target" type="number" min="0" step="any" [(ngModel)]="form.target" />
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.period_start') }}
                  <input name="period_start" type="date" [(ngModel)]="form.period_start" />
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.period_end') }}
                  <input name="period_end" type="date" [(ngModel)]="form.period_end" />
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.value_per_unit') }}
                  <input name="value_per_unit" type="number" min="0" step="any" [(ngModel)]="form.value_per_unit" />
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.currency') }}
                  <input name="currency" maxlength="3" [(ngModel)]="form.currency" />
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.unit') }}
                  <input name="unit" maxlength="40" [(ngModel)]="form.unit" />
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.source_kind') }}
                  <select name="source_kind" [(ngModel)]="form.source_kind">
                    @for (kind of sourceKinds; track kind) {
                      <option [value]="kind">{{ i18n.t('systems.value_contract.source.' + kind) }}</option>
                    }
                  </select>
                </label>
                <label>
                  {{ i18n.t('systems.value_contract.field.source_reference') }}
                  <input name="source_reference" maxlength="500" [(ngModel)]="form.source_reference" />
                </label>
                @if (problem(); as key) {
                  <p role="status">{{ i18n.t(key) }}</p>
                }
                <button type="submit" [disabled]="busy()">{{ i18n.t('systems.value_contract.submit') }}</button>
              </form>
            </details>
          }
        </section>
      }
    }
  `,
  styles: `
    .value-contract {
      display: grid;
      gap: 8px;
      margin: 0 0 1rem;
      padding: 12px;
      border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      border-radius: 12px;
      h3, h4, p, dl { margin: 0; }
      h3 { font-size: 1rem; }
      h4 { font-size: 0.9rem; }
      dl { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; }
      dt { color: var(--ck-fg-3); }
      dd { margin: 0; }
      textarea, select, input, button { font: inherit; }
    }
    .value-contract-form { display: grid; gap: 6px; max-width: 32rem; }
    .value-contract-form label { display: grid; gap: 2px; }
    :focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 3px; }
  `,
})
export class ValueContractComponent {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  protected readonly state = signal<ContractState | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly problem = signal<string | null>(null);
  protected readonly note = signal('');
  protected readonly indicators = CONTRACT_INDICATORS;
  protected readonly sourceKinds = SOURCE_KINDS;
  protected form: ContractForm = initialForm({ prefill: {} } as ContractState);

  constructor() {
    inject(DestroyRef).onDestroy(
      this.workspace.registerContextReset(() => {
        this.state.set(null);
        this.error.set('');
      }),
    );
    effect(() => {
      this.workspace.currentSlug();
      if (this.systemId()) this.load();
    });
  }

  protected terms(contract: ContractTerms): Array<{ label: string; value: string }> {
    return [
      { label: 'systems.value_contract.field.owner', value: contract.owner },
      {
        label: 'systems.value_contract.field.indicator',
        value: this.i18n.t(`experience.adoption.${contract.indicator}`),
      },
      { label: 'systems.value_contract.field.target', value: `${contract.target} ${contract.unit}` },
      { label: 'systems.value_contract.field.period', value: `${contract.period_start} → ${contract.period_end}` },
      {
        label: 'systems.value_contract.field.convention',
        value: `${contract.convention.value_per_unit} ${contract.convention.currency} / ${contract.convention.unit}`,
      },
      {
        label: 'systems.value_contract.field.source',
        value: `${this.i18n.t(`systems.value_contract.source.${contract.source.kind}`)} — ${contract.source.reference}`,
      },
    ];
  }

  protected gapText(gap: Record<string, unknown>): string {
    return jobLineText(this.i18n.t, gapLine(gap as AutomationGapView));
  }

  protected day(value: string | null): string {
    return value ? value.slice(0, 10) : '';
  }

  protected propose(): void {
    const s = this.state();
    if (!s || this.busy()) return;
    const problem = formProblem(this.form);
    this.problem.set(problem);
    if (problem) return;
    this.send(`/systems/${encodeURIComponent(this.systemId())}/value-contract`, proposalBody(this.form, s.latest_revision));
  }

  protected decide(contract: ContractTerms, approve: boolean): void {
    if (this.busy()) return;
    const note = this.note().trim();
    this.send(
      `/systems/${encodeURIComponent(this.systemId())}/value-contract/${contract.revision}/${approve ? 'approve' : 'reject'}`,
      { content_sha256: contract.content_sha256, ...(note ? { note } : {}) },
    );
  }

  private send(path: string, body: Record<string, unknown>): void {
    this.busy.set(true);
    this.error.set('');
    this.api.post<ContractState>(path, body).subscribe({
      next: (state) => this.accept(state),
      error: (error: unknown) => {
        this.busy.set(false);
        const http = error instanceof HttpErrorResponse ? error : null;
        this.error.set(refusalKey(http?.error?.detail?.code, http?.status));
      },
    });
  }

  private load(): void {
    this.api.get<ContractState>(`/systems/${encodeURIComponent(this.systemId())}/value-contract`).subscribe({
      next: (state) => this.accept(state),
      error: () => this.state.set(null),
    });
  }

  private accept(state: ContractState): void {
    this.state.set(state);
    this.form = initialForm(state);
    this.note.set('');
    this.problem.set(null);
    this.busy.set(false);
  }
}
