import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import type {
  CaptureSessionDocument,
  CaptureShareLevel,
  CaptureShareLevelItem,
} from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from './capture-engine';
import { SHARE_LEVEL_DISPLAY, cleanFilename, paletteVar } from './capture-presentation';

interface TriageRow {
  key: string;
  documentId: string | null;
  doc: CaptureSessionDocument;
  pointed: boolean;
  reason: string;
  choice: CaptureShareLevel;
}

const LEVELS: CaptureShareLevel[] = ['full', 'excerpt', 'none'];

/**
 * End-of-capture triage (Phase 4 / D5 / §5.3). Segmented `share_level`
 * {full | excerpt | none}; per-doc choice is pre-deduced from usage (pointed
 * → Entier, otherwise Extrait by default) with a human reason. A pointed doc
 * downgraded to `none` triggers a non-blocking confirmation ("citable au
 * rapport, absent de la recherche KB"). Emits the chosen items; the host
 * (publish surface) persists them via the engine and finalizes.
 */
@Component({
  selector: 'app-capture-triage-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    @if (open) {
      <div style="display:flex; flex-direction:column; gap:0;">
        <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
          Fin de séance · étape légère
        </span>
        <h2 style="margin:10px 0 8px; font-size:24px; font-weight:680; color:var(--ck-fg-1); letter-spacing:-0.01em;">
          Confirmer ce qui est partagé
        </h2>
        <p style="margin:0; font-size:14px; line-height:1.55; color:var(--ck-fg-3); max-width:580px;">
          Le niveau de partage est <b style="color:var(--ck-fg-2);">déduit de votre usage</b> pendant la séance. Vous ne
          remplissez rien — vous corrigez si besoin. Tout reste réversible depuis le rapport.
        </p>

        <div style="margin-top:24px; display:flex; flex-direction:column; gap:10px;">
          @if (rows().length === 0) {
            <div style="padding:16px; border:1px dashed var(--ck-stroke-3); border-radius:var(--ck-radius-md); color:var(--ck-fg-5); font-size:13px;">
              Aucun document attaché à cette séance.
            </div>
          }
          @for (row of rows(); track row.key) {
            <div
              style="display:flex; align-items:center; gap:16px; padding:14px 16px; border-radius:var(--ck-radius-lg); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); transition:opacity var(--ck-dur-med);"
              [style.opacity]="row.choice === 'none' ? 0.62 : 1"
            >
              <div
                style="width:34px; height:42px; flex:none; border-radius:var(--ck-radius-sm); display:grid; place-items:center; background:repeating-linear-gradient(0deg, var(--ck-stroke-1) 0 5px, transparent 5px 6px);"
                [style.border]="'1px solid color-mix(in oklab, ' + accent(row) + ' 40%, transparent)'"
                [style.color]="accent(row)"
              >
                <ck-glyph name="ledger" [size]="15" color="currentColor" />
              </div>
              <div style="flex:1; min-width:0;">
                <div class="ck-mono" style="font-size:12.5px; color:var(--ck-fg-1); font-weight:600;">{{ docName(row) }}</div>
                <div style="font-size:12px; color:var(--ck-fg-4); margin-top:3px;">{{ row.reason }}</div>
                @if (row.choice === 'none' && row.pointed) {
                  <div class="ck-mono" style="font-size:10.5px; color:var(--ck-signal-warn); margin-top:5px;">
                    ⚠ citable au rapport, absent de la recherche KB
                  </div>
                }
              </div>
              <div
                role="radiogroup"
                [attr.aria-label]="'Niveau de partage — ' + docName(row)"
                style="display:inline-flex; padding:2px; border-radius:var(--ck-radius-md); background:var(--ck-bg-void); border:1px solid var(--ck-stroke-2); gap:2px;"
              >
                @for (level of levels; track level) {
                  <button
                    type="button"
                    role="radio"
                    [attr.aria-checked]="row.choice === level"
                    (click)="setChoice(row, level)"
                    style="display:inline-flex; align-items:center; gap:5px; padding:4px 10px; border-radius:var(--ck-radius-sm); cursor:pointer; border:none; font-family:var(--ck-font-sans); font-size:11.5px; font-weight:550;"
                    [style.background]="row.choice === level ? 'var(--ck-bg-panel-hi)' : 'transparent'"
                    [style.color]="row.choice === level ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                    [style.boxShadow]="row.choice === level ? 'var(--ck-shadow-card)' : 'none'"
                  >
                    <span
                      style="width:5px; height:5px; border-radius:50%;"
                      [style.background]="levelColor(level)"
                    ></span>
                    {{ levelLabel(level) }}
                  </button>
                }
              </div>
            </div>
          }
        </div>

        <div
          style="margin-top:22px; padding:14px 16px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); display:flex; gap:11px; align-items:flex-start;"
        >
          <ck-glyph name="layers" [size]="16" color="var(--ck-signal-violet)" />
          <span style="font-size:12.5px; line-height:1.5; color:var(--ck-fg-3);">
            L'<b style="color:var(--ck-fg-2);">indexation lourde</b> (extraction + vectorisation) démarre en arrière-plan
            <b style="color:var(--ck-fg-2);">dès l'ouverture du rapport</b>. Vous lisez immédiatement ; les sources
            deviennent cliquables au fil de l'indexation.
          </span>
        </div>

        @if (confirmingNone()) {
          <div
            style="margin-top:14px; padding:12px 16px; border-radius:var(--ck-radius-md); border:1px solid color-mix(in oklab, var(--ck-signal-warn) 40%, transparent); background:color-mix(in oklab, var(--ck-signal-warn) 10%, transparent); display:flex; gap:10px; align-items:center;"
          >
            <ck-glyph name="warn" [size]="15" color="var(--ck-signal-warn)" />
            <span style="font-size:12.5px; color:var(--ck-fg-2);">
              {{ pointedNoneCount() }} pièce(s) pointée(s) seront <b>citables au rapport mais absentes de la recherche KB</b>.
              Confirmer l'ouverture du rapport ?
            </span>
          </div>
        }

        <div style="margin-top:24px; display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
          <button
            type="button"
            (click)="proceed()"
            style="display:inline-flex; align-items:center; gap:7px; padding:11px 18px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-size:14px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
          >
            <ck-glyph name="arrow-right" [size]="14" color="currentColor" />
            {{ confirmingNone() ? 'Confirmer & ouvrir le rapport' : 'Ouvrir le rapport' }}
          </button>
          <span style="font-size:12.5px; color:var(--ck-fg-4);">
            {{ shareCount() }} document{{ shareCount() > 1 ? 's' : '' }} partagé{{ shareCount() > 1 ? 's' : '' }} · indexation en file
          </span>
        </div>
      </div>
    }
  `,
})
export class CaptureTriageDialogComponent {
  protected readonly engine = inject(CaptureEngine);

  /** Host-controlled visibility (the publish surface owns the triage step). */
  @Input() open = false;
  /** Emits the chosen share levels; the host persists + finalizes. */
  @Output() confirm = new EventEmitter<CaptureShareLevelItem[]>();

  protected readonly levels = LEVELS;
  private readonly overrides = signal<Record<string, CaptureShareLevel>>({});
  protected readonly confirmingNone = signal(false);

  protected readonly rows = computed<TriageRow[]>(() =>
    this.engine.documents().map((doc) => {
      const key = this.keyOf(doc);
      const pointed = (doc.referenced_views_count ?? 0) > 0;
      const deduced: CaptureShareLevel = pointed ? 'full' : (doc.share_level ?? 'excerpt');
      return {
        key,
        documentId: doc.document_id ?? null,
        doc,
        pointed,
        reason: this.reasonFor(doc, pointed),
        choice: this.overrides()[key] ?? deduced,
      };
    }),
  );

  protected readonly shareCount = computed(() => this.rows().filter((r) => r.choice !== 'none').length);
  protected readonly pointedNoneCount = computed(
    () => this.rows().filter((r) => r.pointed && r.choice === 'none').length,
  );

  protected setChoice(row: TriageRow, level: CaptureShareLevel): void {
    this.overrides.update((o) => ({ ...o, [row.key]: level }));
    this.confirmingNone.set(false);
  }

  protected proceed(): void {
    if (this.pointedNoneCount() > 0 && !this.confirmingNone()) {
      this.confirmingNone.set(true);
      return;
    }
    const items: CaptureShareLevelItem[] = this.rows()
      .filter((r) => r.documentId)
      .map((r) => ({ document_id: r.documentId as string, share_level: r.choice }));
    this.confirm.emit(items);
  }

  protected docName(row: TriageRow): string {
    return row.doc.filename ?? row.doc.title ?? cleanFilename(row.doc.filename) ?? 'document';
  }

  protected reasonFor(doc: CaptureSessionDocument, pointed: boolean): string {
    const n = doc.referenced_views_count ?? 0;
    if (pointed) return `Pointé ${n}× pendant la séance`;
    if (doc.share_level === 'none') return 'Épinglé, jamais pointé';
    return 'Pièce de contexte (extrait par défaut)';
  }

  protected levelLabel(level: CaptureShareLevel): string {
    return SHARE_LEVEL_DISPLAY[level].label;
  }

  protected levelColor(level: CaptureShareLevel): string {
    return paletteVar(SHARE_LEVEL_DISPLAY[level].tone);
  }

  protected accent(row: TriageRow): string {
    return paletteVar(SHARE_LEVEL_DISPLAY[row.choice].tone);
  }

  private keyOf(doc: CaptureSessionDocument): string {
    return doc.document_id ?? doc.filename ?? doc.title ?? 'doc';
  }
}
