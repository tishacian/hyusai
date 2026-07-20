import { ChangeDetectionStrategy, Component, EventEmitter, Output, computed, inject, signal } from '@angular/core';
import type { CaptureShareLevelItem, ProposalOpenQuestion } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from '../capture-engine';
import { CaptureTriageDialogComponent } from '../triage-dialog.component';
import {
  applicableTemplateFields,
  asCheckboxGroup,
  toCheckboxGroupPayload,
  asEquipmentRows,
  asStringArray,
  emptyEquipmentRow,
  headerValueAsDisplay,
  isHeaderFieldFilled,
  type CaptureHeaderValue,
  type CaptureTemplateField,
  type EquipmentProgressRow,
} from '../capture-templates';

/**
 * Finalisation surface (Option A) — hosts the end-of-capture triage then
 * triggers {@link CaptureEngine.finalize} (generate the report) and routes the
 * shell onward to the review fiche once the proposal is ready. Indexing stays a
 * background concern surfaced on the report; the real KB publication is a
 * separate downstream surface (`app-capture-fil-publish`).
 *
 * When a CaptureTemplate is active, shows a checklist of required header fields
 * (with editors for structured kinds) and soft-blocks generation until the
 * operator confirms override if incomplete.
 */
@Component({
  selector: 'app-capture-fil-finalize',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, CaptureTriageDialogComponent],
  template: `
    <div style="max-width:780px; display:flex; flex-direction:column; gap:16px;">
      @if (template(); as tpl) {
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:14px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <ck-glyph name="ledger" [size]="15" color="var(--ck-signal-cool)" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              Champs obligatoires · {{ tpl.label }}
              @if (engine.interventionType(); as it) {
                · {{ it.label }}
              }
            </span>
          </div>

          @for (field of checklistFields(); track field.key) {
            <div style="display:flex; flex-direction:column; gap:8px; padding-top:10px; border-top:1px solid var(--ck-stroke-2);">
              <div style="display:flex; align-items:center; gap:8px;">
                <ck-glyph
                  [name]="fieldOk(field) ? 'check' : 'warn'"
                  [size]="14"
                  [color]="fieldOk(field) ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
                />
                <span style="font-size:13px; font-weight:600; color:var(--ck-fg-1);">
                  {{ field.label }}{{ field.required ? ' *' : '' }}
                </span>
              </div>

              @if (field.kind === 'equipment_progress') {
                <div style="overflow-x:auto; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md);">
                  <table style="width:100%; border-collapse:collapse; font-size:12.5px;">
                    <thead>
                      <tr style="background:var(--ck-bg-inset); text-align:left;">
                        <th style="padding:8px 10px; font-weight:600; color:var(--ck-fg-3);">Équipement</th>
                        <th style="padding:8px 10px; font-weight:600; color:var(--ck-fg-3); width:72px;">%</th>
                        <th style="padding:8px 10px; font-weight:600; color:var(--ck-fg-3);">Problème / risque</th>
                        <th style="padding:8px 10px; font-weight:600; color:var(--ck-fg-3);">Mesure</th>
                        <th style="padding:8px 10px; font-weight:600; color:var(--ck-fg-3);">Responsable</th>
                        <th style="padding:8px 6px; width:36px;"></th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (row of equipmentRows(field.key); track $index; let i = $index) {
                        <tr style="border-top:1px solid var(--ck-stroke-2);">
                          <td style="padding:4px 6px;">
                            <input [value]="row.equipment" (input)="patchEquipment(field.key, i, 'equipment', $any($event.target).value)" style="width:100%; border:1px solid var(--ck-stroke-2); border-radius:6px; background:var(--ck-bg-inset); color:var(--ck-fg-1); padding:6px 8px; font-size:12.5px;" />
                          </td>
                          <td style="padding:4px 6px;">
                            <input type="number" min="0" max="100" [value]="row.percent" (input)="patchEquipment(field.key, i, 'percent', $any($event.target).value)" style="width:100%; border:1px solid var(--ck-stroke-2); border-radius:6px; background:var(--ck-bg-inset); color:var(--ck-fg-1); padding:6px 8px; font-size:12.5px;" />
                          </td>
                          <td style="padding:4px 6px;">
                            <input [value]="row.problem_risk || ''" (input)="patchEquipment(field.key, i, 'problem_risk', $any($event.target).value)" style="width:100%; border:1px solid var(--ck-stroke-2); border-radius:6px; background:var(--ck-bg-inset); color:var(--ck-fg-1); padding:6px 8px; font-size:12.5px;" />
                          </td>
                          <td style="padding:4px 6px;">
                            <input [value]="row.measure || ''" (input)="patchEquipment(field.key, i, 'measure', $any($event.target).value)" style="width:100%; border:1px solid var(--ck-stroke-2); border-radius:6px; background:var(--ck-bg-inset); color:var(--ck-fg-1); padding:6px 8px; font-size:12.5px;" />
                          </td>
                          <td style="padding:4px 6px;">
                            <input [value]="row.responsible || ''" (input)="patchEquipment(field.key, i, 'responsible', $any($event.target).value)" style="width:100%; border:1px solid var(--ck-stroke-2); border-radius:6px; background:var(--ck-bg-inset); color:var(--ck-fg-1); padding:6px 8px; font-size:12.5px;" />
                          </td>
                          <td style="padding:4px 6px; text-align:center;">
                            <button type="button" (click)="removeEquipmentRow(field.key, i)" title="Supprimer" style="border:none; background:transparent; color:var(--ck-fg-4); cursor:pointer; font-size:14px;">×</button>
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
                <button
                  type="button"
                  (click)="addEquipmentRow(field.key)"
                  style="align-self:flex-start; border:1px dashed var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); border-radius:var(--ck-radius-sm); padding:5px 10px; cursor:pointer; font-size:12px;"
                >
                  + Ajouter une ligne
                </button>
              } @else if (field.kind === 'checkbox_group') {
                <div style="display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset);">
                  @for (opt of field.options || []; track opt.value) {
                    <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:var(--ck-fg-2); cursor:pointer;">
                      <input
                        type="checkbox"
                        [checked]="checkboxSelected(field.key, opt.value)"
                        (change)="toggleCheckbox(field.key, opt.value, $any($event.target).checked)"
                      />
                      {{ opt.label }}
                    </label>
                  }
                  @if (needsCheckboxDescription(field.key)) {
                    <input
                      [value]="checkboxDescription(field.key)"
                      (input)="setCheckboxDescription(field.key, $any($event.target).value)"
                      placeholder="Description des modifications *"
                      style="margin-top:4px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-base); color:var(--ck-fg-1); font-size:13px; padding:8px 10px;"
                    />
                  }
                </div>
              } @else if (field.kind === 'select_multi') {
                <div style="display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset);">
                  @for (opt of field.options || []; track opt.value) {
                    <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:var(--ck-fg-2); cursor:pointer;">
                      <input
                        type="checkbox"
                        [checked]="multiSelected(field.key, opt.value)"
                        (change)="toggleMulti(field.key, opt.value, $any($event.target).checked)"
                      />
                      {{ opt.label }}
                    </label>
                  }
                </div>
              } @else {
                <input
                  [type]="field.kind === 'date' ? 'date' : 'text'"
                  [value]="headerText(field.key)"
                  (input)="setTextField(field.key, $any($event.target).value)"
                  style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-size:14px; padding:8px 12px;"
                />
              }
            </div>
          }

          @if (incompleteRequired()) {
            <div style="display:flex; flex-direction:column; gap:8px; padding-top:8px; border-top:1px solid var(--ck-stroke-2);">
              <div style="font-size:12.5px; color:var(--ck-signal-warn); line-height:1.45;">
                Des champs obligatoires manquent. Vous pouvez tout de même générer le rapport (soft-block) —
                les trous resteront visibles en revue.
              </div>
              <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:13px; color:var(--ck-fg-2);">
                <input
                  type="checkbox"
                  [checked]="forceGenerate()"
                  (change)="forceGenerate.set($any($event.target).checked)"
                />
                Générer malgré les champs incomplets
              </label>
            </div>
          }
        </div>
      }

      @if (finalizing()) {
        <div
          class="ck-surface"
          style="border-radius:var(--ck-radius-lg); padding:40px 28px; display:flex; flex-direction:column; align-items:center; gap:14px; text-align:center;"
        >
          <span class="ck-live-dot violet"></span>
          <div style="font-size:16px; font-weight:600; color:var(--ck-fg-1);">
            Fin de séance · génération du rapport…
          </div>
          <div style="font-size:13px; color:var(--ck-fg-4); max-width:48ch; line-height:1.5;">
            {{ engine.finalizeStage().message || 'Restructuration de la séance en fiche de connaissance.' }}
            L'indexation lourde démarrera en arrière-plan à l'ouverture du rapport.
          </div>
          @if (error()) {
            <div style="display:flex; align-items:center; gap:8px; color:var(--ck-signal-neg); font-size:12.5px; margin-top:6px;">
              <ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}
              <button
                type="button"
                (click)="retry()"
                style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-2); border-radius:var(--ck-radius-sm); padding:4px 10px; cursor:pointer; font-size:12px;"
              >
                Réessayer
              </button>
            </div>
          }
        </div>
      } @else if (canOpenTriage()) {
        <app-capture-triage-dialog [open]="true" (confirm)="onConfirm($event)" />
      } @else {
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:24px; display:flex; flex-direction:column; gap:12px;">
          <div style="font-size:14px; color:var(--ck-fg-2); line-height:1.5;">
            Complétez les champs ci-dessus ou cochez « Générer malgré les champs incomplets » pour ouvrir le triage.
          </div>
        </div>
      }
    </div>
  `,
})
export class CaptureFilFinalizeComponent {
  protected readonly engine = inject(CaptureEngine);

  /** Emitted once the proposal (report) is ready — the shell opens the review fiche. */
  @Output() finalized = new EventEmitter<void>();

  protected readonly finalizing = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly forceGenerate = signal(false);
  private lastItems: CaptureShareLevelItem[] = [];

  protected readonly template = this.engine.template;

  protected readonly checklistFields = computed(() => {
    const tpl = this.template();
    if (!tpl) return [] as CaptureTemplateField[];
    return applicableTemplateFields(tpl, this.engine.interventionTypeId());
  });

  protected readonly incompleteRequired = computed(() => {
    const checklist = this.engine.proposal()?.proposal?.finalize_checklist;
    if (checklist && typeof checklist.required_fields_complete === 'boolean') {
      return !checklist.required_fields_complete;
    }
    return this.checklistFields().some((field) => !this.fieldOk(field));
  });

  protected readonly canOpenTriage = computed(
    () => !this.template() || !this.incompleteRequired() || this.forceGenerate(),
  );

  constructor() {
    if (this.engine.documents().length === 0) void this.engine.loadDocuments();
  }

  protected fieldOk(field: CaptureTemplateField): boolean {
    const backendMissing = this.backendMissingRequired();
    if (backendMissing) return !backendMissing.has(field.key);
    return isHeaderFieldFilled(field, this.engine.headerFields()[field.key]);
  }

  protected headerText(key: string): string {
    return headerValueAsDisplay(this.engine.headerFields()[key]);
  }

  protected setTextField(key: string, value: string): void {
    this.engine.patchHeaderFields({ [key]: value });
  }

  protected equipmentRows(key: string): EquipmentProgressRow[] {
    const rows = asEquipmentRows(this.engine.headerFields()[key]);
    return rows.length ? rows : [emptyEquipmentRow()];
  }

  protected addEquipmentRow(key: string): void {
    const rows = [...this.equipmentRows(key), emptyEquipmentRow()];
    this.engine.patchHeaderFields({ [key]: rows });
  }

  protected removeEquipmentRow(key: string, index: number): void {
    const rows = this.equipmentRows(key).filter((_, i) => i !== index);
    this.engine.patchHeaderFields({ [key]: rows.length ? rows : [emptyEquipmentRow()] });
  }

  protected patchEquipment(
    key: string,
    index: number,
    prop: keyof EquipmentProgressRow,
    value: string,
  ): void {
    const rows = this.equipmentRows(key).map((row, i) =>
      i === index ? { ...row, [prop]: value } : row,
    );
    this.engine.patchHeaderFields({ [key]: rows });
  }

  protected multiSelected(key: string, option: string): boolean {
    return asStringArray(this.engine.headerFields()[key]).includes(option);
  }

  protected toggleMulti(key: string, option: string, checked: boolean): void {
    const current = asStringArray(this.engine.headerFields()[key]);
    const next = checked
      ? (current.includes(option) ? current : [...current, option])
      : current.filter((v) => v !== option);
    this.engine.patchHeaderFields({ [key]: next });
  }

  protected checkboxSelected(key: string, option: string): boolean {
    return asCheckboxGroup(this.engine.headerFields()[key]).values.includes(option);
  }

  protected checkboxDescription(key: string): string {
    return asCheckboxGroup(this.engine.headerFields()[key]).description;
  }

  protected needsCheckboxDescription(key: string): boolean {
    const values = asCheckboxGroup(this.engine.headerFields()[key]).values;
    return values.some((v) => v !== 'none');
  }

  protected toggleCheckbox(key: string, option: string, checked: boolean): void {
    const group = asCheckboxGroup(this.engine.headerFields()[key]);
    let values = [...group.values];
    if (option === 'none' && checked) {
      values = ['none'];
    } else if (checked) {
      values = values.filter((v) => v !== 'none');
      if (!values.includes(option)) values.push(option);
    } else {
      values = values.filter((v) => v !== option);
    }
    this.engine.patchHeaderFields({
      [key]: toCheckboxGroupPayload(values, group.description) satisfies CaptureHeaderValue,
    });
  }

  protected setCheckboxDescription(key: string, description: string): void {
    const group = asCheckboxGroup(this.engine.headerFields()[key]);
    this.engine.patchHeaderFields({
      [key]: toCheckboxGroupPayload(group.values, description),
    });
  }

  /** Missing required fields from proposal finalize_checklist / blocking OQs. */
  private backendMissingRequired(): Map<string, string> | null {
    const proposal = this.engine.proposal()?.proposal;
    if (!proposal) return null;
    const checklist = proposal.finalize_checklist;
    const missing = new Map<string, string>();
    for (const row of checklist?.missing_required_fields ?? []) {
      const key = String(row.key || '').trim();
      if (!key) continue;
      missing.set(key, String(row.label || key).trim() || key);
    }
    for (const q of proposal.open_questions ?? []) {
      if (!this.isBlockingRequiredField(q)) continue;
      const key = String(q.required_field_key || '').trim();
      if (!key || missing.has(key)) continue;
      const label = String(q.follow_up || q.text || key)
        .replace(/^Champ obligatoire manquant\s*:\s*/i, '')
        .trim() || key;
      missing.set(key, label);
    }
    if (checklist || missing.size) return missing;
    return null;
  }

  private isBlockingRequiredField(q: ProposalOpenQuestion): boolean {
    if (q.source === 'capture_template_required_field') return true;
    if (q.blocking && q.required_field_key) return true;
    return false;
  }

  protected async onConfirm(items: CaptureShareLevelItem[]): Promise<void> {
    this.lastItems = items;
    await this.run();
  }

  protected retry(): void {
    void this.run();
  }

  private async run(): Promise<void> {
    if (!this.canOpenTriage()) {
      this.error.set('Complétez les champs obligatoires ou confirmez la génération incomplète.');
      return;
    }
    this.finalizing.set(true);
    this.error.set(null);
    await this.engine.persistHeaderFields();
    // Persist the triage first, then finalize over the LIVE WS so the backend
    // streams capture.finalize.progress stages to the banner; close the realtime
    // leg only once the proposal is ready (indexing continues server-side).
    await this.engine.setShareLevels(this.lastItems);
    const proposalId = await this.engine.finalize();
    this.engine.disconnect();
    if (proposalId || this.engine.finalizeStage().stage === 'done') {
      this.finalized.emit();
      return;
    }
    this.error.set(this.engine.lastError() || 'La génération du rapport a échoué.');
  }
}
