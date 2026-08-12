import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { CaptureSessionDocument, CaptureShareLevelItem } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from './capture-engine';
import { cleanFilename } from './capture-presentation';

interface TriageRow {
  key: string;
  documentId: string | null;
  doc: CaptureSessionDocument;
  pointed: boolean;
  reason: string;
}

/**
 * End-of-capture confirmation (Phase 4 / D5 / §5.3, simplified). Every attached
 * document is shared IN FULL — the former share-level triage (entier / extrait /
 * aucun) was dropped by product decision: attachments always ship whole to the
 * KB. This step is now a light recap of what will be indexed, with a single
 * CTA that emits `share_level: 'full'` for every document (the backend
 * share-level plumbing is unchanged, we just never send anything else).
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
          {{ i18n.t('capture.triage.eyebrow') }}
        </span>
        <h2 style="margin:10px 0 8px; font-size:24px; font-weight:680; color:var(--ck-fg-1); letter-spacing:-0.01em;">
          {{ i18n.t('capture.triage.heading') }}
        </h2>
        <p style="margin:0; font-size:14px; line-height:1.55; color:var(--ck-fg-3); max-width:580px;">
          {{ i18n.t('capture.triage.share_lead') }}
          <b style="color:var(--ck-fg-2);">{{ i18n.t('capture.triage.in_full') }}</b>
          {{ i18n.t('capture.triage.share_tail') }}
        </p>

        <div style="margin-top:24px; display:flex; flex-direction:column; gap:10px;">
          @if (rows().length === 0) {
            <div style="padding:16px; border:1px dashed var(--ck-stroke-3); border-radius:var(--ck-radius-md); color:var(--ck-fg-5); font-size:13px;">
              {{ i18n.t('capture.triage.empty') }}
            </div>
          }
          @for (row of rows(); track row.key) {
            <div
              style="display:flex; align-items:center; gap:16px; padding:14px 16px; border-radius:var(--ck-radius-lg); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel);"
            >
              <div
                style="width:34px; height:42px; flex:none; border-radius:var(--ck-radius-sm); display:grid; place-items:center; background:repeating-linear-gradient(0deg, var(--ck-stroke-1) 0 5px, transparent 5px 6px); border:1px solid color-mix(in oklab, var(--ck-signal-pos) 40%, transparent); color:var(--ck-signal-pos);"
              >
                <ck-glyph name="ledger" [size]="15" color="currentColor" />
              </div>
              <div style="flex:1; min-width:0;">
                <div class="ck-mono" style="font-size:12.5px; color:var(--ck-fg-1); font-weight:600;">{{ docName(row) }}</div>
                <div style="font-size:12px; color:var(--ck-fg-4); margin-top:3px;">{{ row.reason }}</div>
              </div>
              <span
                class="ck-mono"
                style="flex:none; display:inline-flex; align-items:center; gap:6px; font-size:10.5px; letter-spacing:0.08em; text-transform:uppercase; color:var(--ck-signal-pos);"
              >
                <span style="width:5px; height:5px; border-radius:50%; background:var(--ck-signal-pos);"></span>
                {{ i18n.t('capture.triage.full') }}
              </span>
            </div>
          }
        </div>

        <div
          style="margin-top:22px; padding:14px 16px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); display:flex; gap:11px; align-items:flex-start;"
        >
          <ck-glyph name="layers" [size]="16" color="var(--ck-signal-violet)" />
          <span style="font-size:12.5px; line-height:1.5; color:var(--ck-fg-3);">
            {{ i18n.t('capture.triage.indexing_lead') }}
            <b style="color:var(--ck-fg-2);">{{ i18n.t('capture.triage.indexing_strong') }}</b>
            {{ i18n.t('capture.triage.indexing_tail') }}
          </span>
        </div>

        <div style="margin-top:24px; display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
          <button
            type="button"
            (click)="proceed()"
            style="display:inline-flex; align-items:center; gap:7px; padding:11px 18px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-size:14px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
          >
            <ck-glyph name="arrow-right" [size]="14" color="currentColor" />
            {{ i18n.t('capture.triage.open_report') }}
          </button>
          <span style="font-size:12.5px; color:var(--ck-fg-4);">
            {{ i18n.t('capture.triage.recap', { count: rows().length }) }}
          </span>
        </div>
      </div>
    }
  `,
})
export class CaptureTriageDialogComponent {
  readonly i18n = inject(I18nService);

  protected readonly engine = inject(CaptureEngine);

  /** Host-controlled visibility (the finalize surface owns this step). */
  @Input() open = false;
  /** Emits `full` for every attached document; the host persists + finalizes. */
  @Output() confirm = new EventEmitter<CaptureShareLevelItem[]>();

  protected readonly rows = computed<TriageRow[]>(() =>
    this.engine.documents().map((doc) => {
      const pointed = (doc.referenced_views_count ?? 0) > 0;
      return {
        key: doc.document_id ?? doc.filename ?? doc.title ?? 'doc',
        documentId: doc.document_id ?? null,
        doc,
        pointed,
        reason: pointed
          ? this.i18n.t('capture.triage.pointed_count', {
              count: doc.referenced_views_count ?? 0,
            })
          : this.i18n.t('capture.triage.context_piece'),
      };
    }),
  );

  protected proceed(): void {
    const items: CaptureShareLevelItem[] = this.rows()
      .filter((r) => r.documentId)
      .map((r) => ({ document_id: r.documentId as string, share_level: 'full' }));
    this.confirm.emit(items);
  }

  protected docName(row: TriageRow): string {
    return row.doc.filename ?? row.doc.title ?? cleanFilename(row.doc.filename) ?? 'document';
  }
}
