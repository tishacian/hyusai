import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { Subscription } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import { MandateApiService } from './mandate-api.service';
import { SystemMandateComponent } from './system-mandate.component';
import type { MandateDelegationOption, MandateDraftState, MandateMode, MandateSpec, MandateValidation } from './mandate.models';
import { MANDATE_BOOLEAN_FIELDS, MANDATE_LIST_FIELDS, MANDATE_NUMBER_FIELDS, mandateEditorDiff, mandateField, mandateJson, withMandateField } from './mandate-editor.vm';

type ListKey = typeof MANDATE_LIST_FIELDS[number]['key'];
type DelegationRule = NonNullable<NonNullable<MandateSpec['capabilities']>['allowed_delegations']>[number];

@Component({
  selector: 'app-mandate-editor', standalone: true,
  imports: [JsonPipe, NavLinkDirective, SystemMandateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './mandate-editor.component.css',
  template: `
    @if (readOnly()) { <app-system-mandate [systemId]="systemId()" /> }
    @else {
      <section class="editor" data-testid="mandate-editor" aria-labelledby="mandate-editor-title">
        <header class="editor-heading">
          <div><p class="eyebrow">{{ t('edit') }}</p><h2 id="mandate-editor-title">{{ t('title') }}</h2><p>{{ t('subtitle') }}</p></div>
          <a class="ck-btn-quiet" [navLink]="{leaf:'system-flow',ref:systemId()}">{{ t('open_flow') }}</a>
        </header>
        @if (loading()) { <p role="status">{{ i18n.t('mandate.loading') }}</p> }
        @else if (state(); as value) {
          <div class="versions"><span>{{ i18n.t('mandate_system.editor.draft', {revision:value.draft.revision}) }}</span><span>{{ value.published.version_number == null ? t('no_publication') : i18n.t('mandate_system.editor.published', {version:value.published.version_number!}) }}</span></div>
          @if (value.published.policy_binding === 'legacy' && value.published.version_id) { <p class="editor-notice">{{ t('legacy') }}</p> }
          @if (value.draft.policy_binding !== 'frozen' || value.draft.spec_is_seed) { <p class="editor-notice">{{ t('seed') }}</p> }
          @if (error(); as problem) {
            <div class="editor-error" role="alert"><p>{{ t(problem) }}</p>
              @if (conflict() || revoked()) { <p>{{ t('reload_hint') }}</p><button type="button" (click)="load()" [disabled]="busy()">{{ t('reload') }}</button> }
            </div>
          }
          @if (saved()) { <p class="editor-saved" role="status">{{ t('saved') }}</p> }
          <form #editorForm (submit)="$event.preventDefault(); save(editorForm)" class="editor-grid">
            <fieldset class="editor-fields" [disabled]="!editable() || busy()">
              <section class="editor-card">
                <label class="field" for="mandate-mode"><span>{{ t('mode') }}</span><select id="mandate-mode" (change)="setMode($event)">
                  @for (choice of modes; track choice) { <option [value]="choice" [selected]="choice === mode()">{{ t('mode.' + choice) }}</option> }
                </select></label><p>{{ t('mode_hint.' + mode()) }}</p>
              </section>
              @for (field of listFields; track field.path) {
                <section class="editor-card">
                  <h3>{{ t(field.key === 'collections' ? 'sources' : field.key) }}</h3>
                  <fieldset class="options"><legend>{{ t(field.key) }}</legend>
                    @for (option of value.options[field.key]; track option.id) {
                      <label class="option"><input type="checkbox" [checked]="listValues(field.path).includes(option.id)" (change)="toggleReference(field.path, option.id, $event)" /><span>{{ option.label }}</span></label>
                    } @empty { <p>{{ t('no_options') }}</p> }
                    @for (ref of retainedReferences(field.key, field.path); track ref) {
                      <div class="retained"><span><strong>{{ ref }}</strong><small>{{ t('unavailable_reference') }}</small></span><button type="button" (click)="removeReference(field.path, ref)" [attr.aria-label]="t('remove') + ' ' + ref">{{ t('remove') }}</button></div>
                    }
                  </fieldset>
                  @if (listValues(field.path).length === 0) { <p>{{ t('empty_list') }}</p> }
                </section>
              }
              <section class="editor-card">
                <h3>{{ t('delegations') }}</h3><p>{{ t('delegation_hint') }}</p>
                @for (option of value.options.delegations; track delegationKey(option)) {
                  <div class="delegation"><label class="option"><input type="checkbox" [checked]="hasDelegation(option)" (change)="toggleDelegation(option, $event)" /><span>{{ option.label }}</span></label>
                    <details><summary>{{ t('contracts') }}</summary><pre>{{ delegationRule(option) | json }}</pre></details>
                  </div>
                } @empty { <p>{{ t('no_options') }}</p> }
                @for (rule of retainedDelegations(); track $index) {
                  <div class="retained"><span><strong>{{ delegationLabel(rule) }}</strong><small>{{ t('unavailable_reference') }}</small></span><button type="button" (click)="removeDelegation(rule)" [attr.aria-label]="t('remove') + ' ' + delegationLabel(rule)">{{ t('remove') }}</button></div>
                }
                @if (!delegations().length) { <p>{{ t('empty_delegations') }}</p> }
                @if (actions().length) { <details><summary>{{ t('actions') }}</summary><ul>@for (action of actions(); track action) { <li>{{ action }}</li> }</ul></details> }
                <p>{{ t('actions_hint') }}</p>
              </section>
              <section class="editor-card">
                <h3>{{ t('review') }}</h3>
                @for (field of booleans.slice(0, 3); track field.path) { <label class="option"><input type="checkbox" [checked]="fieldValue(field.path) === true" (change)="setBoolean(field.path, $event)" /><span>{{ t(field.key) }}</span></label> }
                <div class="number-grid">
                  @for (field of numbers.slice(0, 2); track field.path) { <label class="field"><span>{{ t(field.key) }}</span><input type="number" [name]="field.key" [value]="numberValue(field.path, field.scale)" [min]="field.min" [attr.max]="field.max" [step]="field.step" (input)="setNumber(field.path, field.scale, $event)" /></label> }
                </div><p>{{ t('optional') }}</p>
              </section>
              <section class="editor-card">
                <h3>{{ t('limits') }}</h3><div class="number-grid">
                  @for (field of numbers.slice(2); track field.path) { <label class="field"><span>{{ t(field.key) }}</span><input type="number" [name]="field.key" [value]="numberValue(field.path, field.scale)" [min]="field.min" [attr.max]="field.max" [step]="field.step" (input)="setNumber(field.path, field.scale, $event)" /></label> }
                </div><p>{{ t('optional') }}</p>
                <label class="option"><input type="checkbox" [checked]="fieldValue('valves.hard_abort') === true" (change)="setBoolean('valves.hard_abort', $event)" /><span>{{ t('hard_abort') }}</span></label><p>{{ t('hard_abort_hint') }}</p>
              </section>
            </fieldset>
            <aside class="editor-review">
              <section class="editor-card">
                <h3>{{ t('diff') }}</h3><span class="change-count">{{ i18n.t('mandate_system.editor.diff_count', {count:changes().length}) }}</span>
                <div class="diff-labels"><span>{{ t('reference') }}</span><span>{{ t('candidate') }}</span></div>
                <ol class="diff-list">
                  @for (change of changes(); track change.path) { <li><strong>{{ t(change.key) }}</strong><div><del>{{ displayValue(change.before, change.path) }}</del><ins>{{ displayValue(change.after, change.path) }}</ins></div></li> }
                  @empty { <li>{{ t('no_diff') }}</li> }
                </ol>
                <label class="reviewed"><input type="checkbox" [checked]="reviewed()" [disabled]="!editable() || busy() || !needsSave()" (change)="reviewed.set($any($event.target).checked)" /><span>{{ t('reviewed') }}</span></label>
                <button type="button" class="ck-cta primary" [disabled]="!canSave()" (click)="save(editorForm)">{{ t(saving() ? 'saving' : 'save') }}</button>
                @if (dirty()) { <p class="unsaved" role="status">{{ t('unsaved') }}</p> }
              </section>
              <section class="editor-card">
                <h3>{{ t('validation') }}</h3><p>{{ t('static_hint') }}</p>
                @if (validation(); as result) {
                  <ul class="checks">@for (check of result.checks; track check.code + (check.field || '')) {
                    <li [attr.data-state]="check.status"><div class="check-heading"><span>{{ checkLabel(check.code) }}</span><strong>{{ t('validation.' + check.status) }}</strong></div>
                      @if (check.status === 'failed') { <p>{{ checkReason(check) }}</p> }
                      @if (check.details || check.reason_code || check.message) { <details><summary>{{ t('technical_details') }}</summary><pre>{{ check | json }}</pre></details> }
                    </li>
                  }</ul>
                  <p>{{ t(result.valid ? 'validation_ready' : 'validation_pending') }}</p>
                }
                <button type="button" class="secondary" [disabled]="!editable() || busy() || needsSave()" (click)="validate()">{{ t(validating() ? 'validating' : 'validate') }}</button>
              </section>
              <section class="editor-card">
                @if (canPublish()) { <a class="ck-cta primary" [navLink]="{leaf:'system-flow',ref:systemId()}">{{ t('open_publication') }}</a> }
                @else { <button type="button" class="primary" disabled>{{ t('open_publication') }}</button> }
                <p>{{ t('publication_hint') }}</p>
              </section>
            </aside>
          </form>
        } @else if (error(); as problem) { <p role="alert">{{ t(problem) }}</p><button type="button" (click)="load()">{{ i18n.t('common.retry') }}</button> }
      </section>
    }
  `,
})
export class MandateEditorComponent {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(MandateApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  readonly state = signal<MandateDraftState | null>(null);
  readonly draft = signal<MandateSpec | null>(null);
  readonly validation = signal<MandateValidation | null>(null);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly validating = signal(false);
  readonly readOnly = signal(false);
  readonly error = signal<string | null>(null);
  readonly conflict = signal(false);
  readonly revoked = signal(false);
  readonly saved = signal(false);
  readonly reviewed = signal(false);
  readonly listFields = MANDATE_LIST_FIELDS;
  readonly numbers = MANDATE_NUMBER_FIELDS;
  readonly booleans = MANDATE_BOOLEAN_FIELDS;
  readonly modes: MandateMode[] = ['compat', 'shadow', 'enforce'];
  readonly busy = computed(() => this.loading() || this.saving() || this.validating());
  readonly editable = computed(() => this.state()?.permissions.can_edit === true && !this.conflict() && !this.revoked());
  readonly mode = computed<MandateMode>(() => this.draft()?.enforcement_mode ?? 'compat');
  readonly dirty = computed(() => !!this.state() && mandateJson(this.draft()) !== mandateJson(this.state()!.draft.spec));
  readonly needsSave = computed(() => this.dirty() || this.state()?.draft.policy_binding !== 'frozen' || this.state()?.draft.spec_is_seed === true);
  readonly canSave = computed(() => this.editable() && !this.busy() && this.needsSave() && this.reviewed() && !!this.draft());
  readonly canPublish = computed(() => this.editable() && !this.busy() && !this.needsSave() && this.validation()?.valid === true);
  readonly changes = computed(() => mandateEditorDiff(this.state()?.published.spec ?? null, this.draft()));
  readonly delegations = computed(() => this.draft()?.capabilities?.allowed_delegations ?? []);
  readonly actions = computed(() => this.draft()?.capabilities?.allowed_actions ?? []);
  private requests = new Subscription();
  private generation = 0;

  constructor() {
    const unregister = this.workspace.registerContextReset(() => this.reset());
    this.destroyRef.onDestroy(() => {unregister(); this.reset();});
    effect(() => {this.systemId(); this.workspace.contextEpoch(); untracked(() => this.load());});
  }
  t(key: string) { return this.i18n.t(`mandate_system.editor.${key}`); }
  fieldValue(path: string) { return mandateField(this.draft(), path); }
  listValues(path: string): string[] { const value = this.fieldValue(path); return Array.isArray(value) ? value as string[] : []; }
  numberValue(path: string, scale: number) { const value = this.fieldValue(path); return typeof value === 'number' ? value * scale : ''; }
  retainedReferences(key: ListKey, path: string) { const choices = this.state()?.options[key] ?? []; return this.listValues(path).filter(ref => !choices.some(option => option.id === ref)); }
  setBoolean(path: string, event: Event) { this.edit(path, (event.target as HTMLInputElement).checked); }
  setNumber(path: string, scale: number, event: Event) { const input = event.target as HTMLInputElement; if (input.validity.badInput) return; this.edit(path, input.value === '' ? null : Number(input.value) / scale); }
  setMode(event: Event) { const mode = (event.target as HTMLSelectElement).value as MandateMode; if (!this.modes.includes(mode)) return; this.edit('version', 2); this.edit('enforcement_mode', mode); }
  toggleReference(path: string, ref: string, event: Event) { this.edit(path, (event.target as HTMLInputElement).checked ? [...new Set([...this.listValues(path), ref])] : this.listValues(path).filter(value => value !== ref)); }
  removeReference(path: string, ref: string) { this.edit(path, this.listValues(path).filter(value => value !== ref)); }
  delegationRule(option: MandateDelegationOption) { return {system_id: option.system_id, input_contract: option.input_contract ?? {}, output_contract: option.output_contract ?? {}, branches: option.branches ?? []}; }
  delegationKey(rule: MandateDelegationOption | DelegationRule) { return typeof rule === 'string' ? rule : mandateJson({system_id: rule.system_id, input_contract: rule.input_contract ?? {}, output_contract: rule.output_contract ?? {}, branches: rule.branches ?? []}); }
  delegationLabel(rule: DelegationRule) { return typeof rule === 'string' ? rule : rule.system_id; }
  hasDelegation(option: MandateDelegationOption) { return this.delegations().some(rule => this.delegationKey(rule) === this.delegationKey(option)); }
  retainedDelegations() { return this.delegations().filter(rule => !(this.state()?.options.delegations ?? []).some(option => this.delegationKey(rule) === this.delegationKey(option))); }
  toggleDelegation(option: MandateDelegationOption, event: Event) {
    const rules = this.delegations().filter(rule => this.delegationKey(rule) !== this.delegationKey(option));
    this.edit('capabilities.allowed_delegations', (event.target as HTMLInputElement).checked ? [...rules, this.delegationRule(option)] : rules);
  }
  removeDelegation(rule: DelegationRule) { this.edit('capabilities.allowed_delegations', this.delegations().filter(value => this.delegationKey(value) !== this.delegationKey(rule))); }
  displayValue(value: unknown, path: string): string {
    if (value == null || (Array.isArray(value) && !value.length)) return this.t('missing');
    if (typeof value === 'boolean') return this.t(value ? 'yes' : 'no');
    if (path === 'enforcement_mode') return this.t(`mode.${value}`);
    if (Array.isArray(value)) {
      const list = this.listFields.find(field => field.path === path);
      return value.map(item => {
        if (typeof item === 'string') return list ? this.state()?.options[list.key].find(option => option.id === item)?.label ?? item : item;
        if (typeof item === 'object' && item) { const id = (item as {system_id?: string}).system_id; return this.state()?.options.delegations.find(option => option.system_id === id)?.label ?? id ?? mandateJson(item); }
        return String(item);
      }).join(', ');
    }
    const numeric = this.numbers.find(field => field.path === path);
    if (numeric && typeof value === 'number') return new Intl.NumberFormat(this.i18n.locale(), {maximumSignificantDigits: 8}).format(value * numeric.scale);
    return String(value);
  }
  checkLabel(code: string) { const key = `mandate_system.editor.check.${code}`; const translated = this.i18n.t(key); return translated === key ? this.t('validation') : translated; }
  checkReason(check: MandateValidation['checks'][number]): string {
    const key = `mandate_system.editor.reason.${check.reason_code ?? check.field ?? ''}`;
    const translated = this.i18n.t(key);
    return translated !== key ? translated : check.message || this.t('check_fix');
  }

  private edit(path: string, value: unknown): void {
    const draft = this.draft(); if (!draft || !this.editable() || this.busy()) return;
    this.draft.set(withMandateField(draft, path, value)); this.reviewed.set(false); this.saved.set(false); this.validation.set(null); this.error.set(null);
  }
  load(): void {
    this.reset(); const id = this.systemId(); if (!id) return;
    const generation = this.generation; const scope = this.workspace.captureRequestScope(); this.loading.set(true);
    this.requests.add(this.api.draft(id, scope).subscribe({
      next: value => { if (!this.current(id, generation, scope)) return; this.loading.set(false); this.accept(value); },
      error: err => {
        if (!this.current(id, generation, scope)) return;
        this.loading.set(false);
        const code = err?.error?.detail?.code;
        if (err?.status === 403 || ['FLOW_PUBLICATION_DISABLED', 'FLOW_DRAFT_STATE_MISSING'].includes(code)) this.readOnly.set(true);
        else this.error.set(err?.status === 422 && code === 'MANDATE_POLICY_CONTAINS_CREDENTIALS' ? 'reason.MANDATE_POLICY_CONTAINS_CREDENTIALS' : 'load_error');
      },
    }));
  }
  save(form?: HTMLFormElement): void {
    if (!this.canSave() || (form && !form.reportValidity())) return;
    const state = this.state()!; const id = this.systemId(); const generation = this.generation; const scope = this.workspace.captureRequestScope();
    const spec = structuredClone(this.draft()!); this.saving.set(true); this.error.set(null); this.saved.set(false);
    this.requests.add(this.api.saveDraft(id, {expected_revision: state.draft.revision, expected_snapshot_sha256: state.draft.snapshot_sha256, spec}, scope).subscribe({
      next: value => { if (!this.current(id, generation, scope)) return; this.saving.set(false); if (this.accept(value)) this.saved.set(true); },
      error: err => { if (!this.current(id, generation, scope)) return; this.saving.set(false); this.handleError(err, 'save_error'); },
    }));
  }
  validate(): void {
    if (!this.editable() || this.busy() || this.needsSave() || !this.state()) return;
    const id = this.systemId(); const generation = this.generation; const scope = this.workspace.captureRequestScope(); const revision = this.state()!.draft.revision;
    this.validating.set(true); this.validation.set(null); this.error.set(null);
    this.requests.add(this.api.validateDraft(id, {expected_revision: revision, expected_snapshot_sha256: this.state()!.draft.snapshot_sha256}, scope).subscribe({
      next: value => { if (!this.current(id, generation, scope) || this.state()?.draft.revision !== revision) return; this.validating.set(false); if (typeof value?.valid === 'boolean' && Array.isArray(value.checks)) this.validation.set(value); else this.error.set('validation_error'); },
      error: err => { if (!this.current(id, generation, scope)) return; this.validating.set(false); this.handleError(err, 'validation_error'); },
    }));
  }
  private accept(value: MandateDraftState): boolean {
    if (value?.system_id !== this.systemId() || !Number.isInteger(value.draft?.revision) || !value.draft?.snapshot_sha256 || typeof value.permissions?.can_edit !== 'boolean' || typeof value.validation?.valid !== 'boolean' || !Array.isArray(value.validation?.checks) || !value.options || !this.listFields.every(field => Array.isArray(value.options[field.key])) || !Array.isArray(value.options.delegations)) { this.error.set('load_error'); return false; }
    this.state.set(value); this.draft.set(structuredClone(value.draft.spec)); this.validation.set(value.validation); this.reviewed.set(false); this.readOnly.set(!value.permissions.can_edit); return true;
  }
  private handleError(error: {status?: number}, fallback: string): void {
    if (error?.status === 409) {this.conflict.set(true); this.error.set('conflict');}
    else if (error?.status === 403) {this.revoked.set(true); this.error.set('denied');}
    else this.error.set(error?.status === 422 ? 'invalid' : fallback);
  }
  private current(id: string, generation: number, scope: ReturnType<WorkspaceService['captureRequestScope']>) { return id === this.systemId() && generation === this.generation && this.workspace.isRequestScopeCurrent(scope); }
  private reset(): void {
    this.generation++; this.requests.unsubscribe(); this.requests = new Subscription();
    this.state.set(null); this.draft.set(null); this.validation.set(null); this.error.set(null); this.conflict.set(false); this.revoked.set(false); this.reviewed.set(false); this.readOnly.set(false); this.saved.set(false); this.loading.set(false); this.saving.set(false); this.validating.set(false);
  }
}
