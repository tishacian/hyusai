import { ChangeDetectionStrategy, Component, EventEmitter, Output, computed, inject, signal } from '@angular/core';
import type { CaptureShareLevelItem, ProposalOpenQuestion } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from '../capture-engine';
import { CaptureTriageDialogComponent } from '../triage-dialog.component';

/**
 * Finalisation surface (Option A) — hosts the end-of-capture triage then
 * triggers {@link CaptureEngine.finalize} (generate the report) and routes the
 * shell onward to the review fiche once the proposal is ready. Indexing stays a
 * background concern surfaced on the report; the real KB publication is a
 * separate downstream surface (`app-capture-fil-publish`).
 *
 * When a CaptureTemplate is active, shows a checklist of required header fields
 * and soft-blocks generation until the operator confirms override if incomplete.
 */
@Component({
  selector: 'app-capture-fil-finalize',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, CaptureTriageDialogComponent],
  template: `
    <div style="max-width:780px; display:flex; flex-direction:column; gap:16px;">
      @if (template(); as tpl) {
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <ck-glyph name="ledger" [size]="15" color="var(--ck-signal-cool)" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              Champs obligatoires · {{ tpl.label }}
            </span>
          </div>
          <ul style="margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:8px;">
            @for (row of fieldChecklist(); track row.key) {
              <li style="display:flex; align-items:center; gap:10px; font-size:13px;">
                <ck-glyph
                  [name]="row.ok ? 'check' : 'warn'"
                  [size]="14"
                  [color]="row.ok ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
                />
                <span [style.color]="row.ok ? 'var(--ck-fg-2)' : 'var(--ck-fg-1)'">{{ row.label }}</span>
                <span class="ck-mono" style="margin-left:auto; font-size:11px; color:var(--ck-fg-4); max-width:40ch; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                  {{ row.ok ? row.value : 'manquant' }}
                </span>
              </li>
            }
          </ul>
          @if (incompleteRequired()) {
            <div style="display:flex; flex-direction:column; gap:8px; padding-top:4px; border-top:1px solid var(--ck-stroke-2);">
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
            Cochez « Générer malgré les champs incomplets » pour ouvrir le triage et lancer la génération.
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

  protected readonly fieldChecklist = computed(() => {
    const tpl = this.template();
    const values = this.engine.headerFields();
    const backendMissing = this.backendMissingRequired();

    if (backendMissing) {
      if (tpl) {
        return tpl.required_fields.map((field) => {
          const value = (values[field.key] || '').trim();
          return {
            key: field.key,
            label: field.label,
            value,
            ok: !backendMissing.has(field.key),
          };
        });
      }
      return [...backendMissing.entries()].map(([key, label]) => ({
        key,
        label,
        value: (values[key] || '').trim(),
        ok: false,
      }));
    }

    if (!tpl) return [];
    return tpl.required_fields.map((field) => {
      const value = (values[field.key] || '').trim();
      return {
        key: field.key,
        label: field.label,
        value,
        ok: !field.required || value.length > 0,
      };
    });
  });

  protected readonly incompleteRequired = computed(() => {
    const checklist = this.engine.proposal()?.proposal?.finalize_checklist;
    if (checklist && typeof checklist.required_fields_complete === 'boolean') {
      return !checklist.required_fields_complete;
    }
    return this.fieldChecklist().some((row) => !row.ok);
  });

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

  protected readonly canOpenTriage = computed(
    () => !this.template() || !this.incompleteRequired() || this.forceGenerate(),
  );

  constructor() {
    if (this.engine.documents().length === 0) void this.engine.loadDocuments();
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
