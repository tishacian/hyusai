import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ApiService, type CaptureSessionDocument, type CaptureViewReference } from '@app/core/api.service';
import { GlyphComponent, LiveDotComponent } from '@app/shared/cockpit';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { CaptureEngine } from './capture-engine';
import { ViewTileComponent } from './view-tile.component';
import {
  INDEX_STATE_DISPLAY,
  clockLabel,
  indexStatusOf,
  paletteVar,
  refKey,
  toneVar,
  viewLocation,
  viewTitle,
  viewTone,
} from './capture-presentation';

interface ReportSource {
  key: string;
  n: number;
  ref: CaptureViewReference;
}

/**
 * Report + provenance inspector (Phase 6 / D5 / §5.5). Two panels (document 1fr
 * | inspector 396px). Each sourced affirmation carries a clickable marker; the
 * pointed view is highlighted (reuses {@link DocumentPreviewComponent} with its
 * `highlight` input for the live document). A "Revoir l'instant capté" link is
 * bidirectional back into Le Fil. Provenance is read from the journaled refs,
 * decoupled from indexing — which surfaces only as a discrete, non-blocking
 * background banner (Phase 4 / §5.4).
 */
@Component({
  selector: 'app-report-provenance',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, LiveDotComponent, ViewTileComponent, DocumentPreviewComponent],
  template: `
    <div style="display:grid; grid-template-columns:minmax(0,1fr) 396px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); overflow:hidden; min-height:60vh; background:var(--ck-bg-base);">
      <!-- document -->
      <div style="display:flex; flex-direction:column; min-width:0; border-right:1px solid var(--ck-stroke-2);">
        <div style="flex:none; padding:14px 24px; border-bottom:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
          <ck-glyph name="ledger" [size]="17" color="var(--ck-fg-3)" />
          <div style="min-width:0;">
            <div style="font-size:13.5px; font-weight:650; color:var(--ck-fg-1); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
              {{ title() }}
            </div>
            <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:2px;">{{ reference() }}</div>
          </div>
          <span
            style="margin-left:auto; display:inline-flex; align-items:center; gap:7px; padding:5px 10px; border-radius:999px; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset);"
          >
            <ck-live-dot [tone]="indexComplete() ? 'pos' : 'violet'" />
            <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-3);">{{ indexBanner() }}</span>
          </span>
        </div>

        <!-- global index pulse -->
        <div style="flex:none; height:3px; background:var(--ck-stroke-2); overflow:hidden;">
          <div
            style="height:100%; background:var(--ck-signal-violet); box-shadow:var(--ck-glow-violet); transition:width var(--ck-dur-med) var(--ck-ease-out);"
            [style.width.%]="indexPct()"
          ></div>
        </div>

        <div class="ck-scroll ck-ambient-grid" style="flex:1; overflow-y:auto; padding:30px 0; min-height:0;">
          <div style="max-width:660px; margin:0 auto; padding:0 28px;">
            <h2 class="ck-mono" style="margin:0 0 14px; font-size:12px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-cool);">
              Synthèse & provenance
            </h2>
            <p style="margin:0 0 18px; font-size:15.5px; line-height:1.7; color:var(--ck-fg-1); text-wrap:pretty;">
              {{ objective() }}
              <span class="ck-mono" style="margin-left:5px; font-size:9.5px; color:var(--ck-fg-5); vertical-align:super;">(synthèse)</span>
            </p>

            @for (src of sources(); track src.key) {
              <p
                style="font-size:15.5px; line-height:1.7; text-wrap:pretty; color:var(--ck-fg-1); border-radius:var(--ck-radius-sm); transition:background var(--ck-dur-med);"
                [style.background]="src.key === selectedKey() ? 'color-mix(in oklab, ' + tintOf(src.ref) + ' 9%, transparent)' : 'transparent'"
                [style.padding]="src.key === selectedKey() ? '4px 8px' : '0'"
                [style.margin]="src.key === selectedKey() ? '0 -8px 14px' : '0 0 14px'"
              >
                {{ statementOf(src.ref) }}
                <button
                  type="button"
                  class="ck-mono"
                  (click)="select(src.key)"
                  [title]="viewTitleOf(src.ref) + ' · ' + locationOf(src.ref)"
                  style="appearance:none; cursor:pointer; vertical-align:super; margin-left:3px; display:inline-flex; align-items:center; gap:3px; padding:1px 6px 1px 5px; border-radius:999px; line-height:1; font-size:9.5px; font-weight:700;"
                  [style.color]="tintOf(src.ref)"
                  [style.border]="'1px solid ' + (src.key === selectedKey() ? tintOf(src.ref) : 'color-mix(in oklab, ' + tintOf(src.ref) + ' 40%, transparent)')"
                  [style.background]="'color-mix(in oklab, ' + tintOf(src.ref) + ' ' + (src.key === selectedKey() ? '22' : '9') + '%, transparent)'"
                >
                  <ck-glyph name="crosshair" [size]="9" color="currentColor" /> {{ src.n }}
                </button>
              </p>
            }

            @if (sources().length === 0) {
              <p style="font-size:13px; color:var(--ck-fg-4); font-style:italic;">
                Aucune source pointée pour cette séance. Les affirmations sourcées apparaissent ici à mesure que des pièces sont
                pointées pendant la séance.
              </p>
            }
          </div>
        </div>
      </div>

      <!-- inspector -->
      <div style="display:flex; flex-direction:column; background:var(--ck-bg-panel); min-width:0;">
        <div style="flex:none; padding:14px 18px; border-bottom:1px solid var(--ck-stroke-2); display:flex; align-items:center; gap:8px;">
          <ck-glyph name="focus" [size]="15" color="var(--ck-fg-3)" />
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
            Source & provenance
          </span>
        </div>

        @if (selected(); as sel) {
          <div class="ck-scroll" style="flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:16px; min-height:0;">
            <div style="position:relative;">
              <app-capture-view-tile [view]="sel" size="xl" [active]="true" />
              <div
                style="position:absolute; top:26%; left:14%; width:46%; height:34%; border-radius:4px; pointer-events:none;"
                [style.border]="'2px solid ' + tintOf(sel)"
                [style.boxShadow]="'0 0 0 9999px color-mix(in oklab, var(--ck-bg-void) 38%, transparent)'"
              >
                <span
                  class="ck-mono"
                  style="position:absolute; top:-9px; left:-1px; padding:1px 7px; border-radius:3px; font-size:8.5px; font-weight:700; white-space:nowrap; color:var(--ck-on-signal);"
                  [style.background]="tintOf(sel)"
                >
                  ZONE POINTÉE
                </span>
              </div>
            </div>

            <div style="display:flex; flex-direction:column; gap:9px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <ck-glyph name="ledger" [size]="14" [color]="tintOf(sel)" />
                <span class="ck-mono" style="font-size:12px; color:var(--ck-fg-1);">{{ viewTitleOf(sel) }}</span>
              </div>
              <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <span class="prov-pill"><span class="prov-k">Vue</span><span class="prov-v">{{ locationOf(sel) }}</span></span>
                <span class="prov-pill"><span class="prov-k">Objet</span><span class="prov-v">{{ statementOf(sel) }}</span></span>
                <span class="prov-pill">
                  <span class="prov-k">Index</span>
                  <span class="prov-v" [style.color]="indexTone(sel)">{{ indexLabel(sel) }}</span>
                </span>
              </div>
            </div>

            <button
              type="button"
              (click)="revisit.emit(sel)"
              style="appearance:none; cursor:pointer; display:flex; align-items:center; gap:10px; padding:11px 13px; border-radius:var(--ck-radius-md); text-align:left; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-2);"
            >
              <ck-glyph name="arrow-up" [size]="15" color="var(--ck-signal-cool)" />
              <span style="flex:1;">
                <span style="display:block; font-size:12px; color:var(--ck-fg-1);">Revoir l'instant capté</span>
                <span class="ck-mono" style="display:block; font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                  dit à {{ momentOf(sel) }} pendant la séance
                </span>
              </span>
              <ck-glyph name="arrow-right" [size]="14" color="currentColor" />
            </button>

            @if (previewUrlFor(sel); as url) {
              <button
                type="button"
                (click)="openPreview(url, sel)"
                style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:7px; align-self:flex-start; padding:7px 12px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-2); font-size:12px;"
              >
                <ck-glyph name="zoom-in" [size]="13" color="currentColor" /> Voir le document
              </button>
            }

            <p style="margin:0; font-size:11.5px; line-height:1.5; color:var(--ck-fg-4);">
              Provenance bidirectionnelle : du rapport vers la pièce <i>et</i> vers le moment exact de la séance où l'expert l'a
              pointée.
            </p>
          </div>
        } @else {
          <div style="flex:1; display:grid; place-items:center; color:var(--ck-fg-5); font-size:12.5px; padding:24px; text-align:center;">
            Cliquez une source dans le rapport.
          </div>
        }
      </div>
    </div>

    <app-document-preview
      [open]="previewOpen()"
      [previewUrl]="previewUrl()"
      [title]="previewTitle()"
      [subtitle]="'Source pointée'"
      [page]="previewPage()"
      [highlight]="previewHighlight()"
      (closed)="previewOpen.set(false)"
    />
  `,
  styles: [
    `
      .prov-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 9px;
        border-radius: 999px;
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-inset);
      }
      .prov-k {
        font-family: var(--ck-font-mono);
        font-size: 8.5px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--ck-fg-5);
      }
      .prov-v {
        font-family: var(--ck-font-mono);
        font-size: 10.5px;
        color: var(--ck-fg-2);
        font-weight: 600;
        max-width: 200px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    `,
  ],
})
export class ReportProvenanceComponent {
  protected readonly engine = inject(CaptureEngine);
  private readonly api = inject(ApiService);

  /** Bidirectional link back to Le Fil at the captured instant. */
  @Output() revisit = new EventEmitter<CaptureViewReference>();

  protected readonly selectedKey = signal<string | null>(null);

  protected readonly previewOpen = signal(false);
  protected readonly previewUrl = signal<string | null>(null);
  protected readonly previewTitle = signal('');
  protected readonly previewPage = signal<number | null>(null);
  protected readonly previewHighlight = signal<string | null>(null);

  protected readonly sources = computed<ReportSource[]>(() => {
    let n = 0;
    return this.engine
      .anchors()
      .filter((ref) => ref.document_id || ref.statement || ref.filename || ref.title)
      .map((ref) => ({ key: refKey(ref), n: ++n, ref }));
  });

  protected readonly selected = computed<CaptureViewReference | null>(() => {
    const key = this.selectedKey();
    return this.sources().find((s) => s.key === key)?.ref ?? null;
  });

  protected readonly title = computed(() => this.engine.session()?.title ?? 'Rapport de capture');
  protected readonly reference = computed(() => {
    const proposal = this.engine.proposalId();
    const sessionId = this.engine.sessionId();
    return proposal ? `proposition ${proposal}` : sessionId ? `séance ${sessionId}` : '—';
  });
  protected readonly objective = computed(
    () => this.engine.session()?.objective ?? 'Synthèse des connaissances capturées durant la séance.',
  );

  // ---- background-index banner (D5 / §5.4) -------------------------------
  private readonly shareable = computed(() =>
    this.engine.documents().filter((d) => (d.share_level ?? 'excerpt') !== 'none'),
  );
  protected readonly indexPct = computed(() => {
    const fin = this.engine.finalizeStage();
    if (fin.total > 0) return Math.round((fin.processed / fin.total) * 100);
    const docs = this.shareable();
    if (!docs.length) return this.engine.proposalId() ? 100 : 0;
    const done = docs.filter((d) => indexStatusOf(d) === 'indexed' || indexStatusOf(d) === 'referenced').length;
    return Math.round((done / docs.length) * 100);
  });
  protected readonly indexComplete = computed(() => this.indexPct() >= 100);
  protected readonly indexBanner = computed(() => {
    const docs = this.shareable();
    const done = docs.filter((d) => indexStatusOf(d) === 'indexed').length;
    if (!docs.length) return 'sources cliquables au fil';
    return `indexation ${done}/${docs.length} · sources cliquables au fil`;
  });

  protected select(key: string): void {
    this.selectedKey.set(key);
  }

  protected statementOf(ref: CaptureViewReference): string {
    return ref.statement ?? ref.trigger_phrase ?? viewTitle(ref);
  }
  protected viewTitleOf(ref: CaptureViewReference): string {
    return viewTitle(ref);
  }
  protected locationOf(ref: CaptureViewReference): string {
    return viewLocation(ref);
  }
  protected tintOf(ref: CaptureViewReference): string {
    return toneVar(viewTone(ref));
  }
  protected momentOf(ref: CaptureViewReference): string {
    return clockLabel(ref.timecode_ms ?? null);
  }

  private docFor(ref: CaptureViewReference): CaptureSessionDocument | undefined {
    return this.engine.documents().find((d) => d.document_id && d.document_id === ref.document_id);
  }
  protected indexLabel(ref: CaptureViewReference): string {
    const doc = this.docFor(ref);
    return doc ? INDEX_STATE_DISPLAY[indexStatusOf(doc)].label : 'Référencé';
  }
  protected indexTone(ref: CaptureViewReference): string {
    const doc = this.docFor(ref);
    return doc ? paletteVar(INDEX_STATE_DISPLAY[indexStatusOf(doc)].tone) : 'var(--ck-signal-cool)';
  }

  protected previewUrlFor(ref: CaptureViewReference): string | null {
    const doc = this.docFor(ref);
    const documentId = ref.document_id ?? doc?.document_id;
    const collection = doc?.collection ?? doc?.collection_name;
    if (!documentId || !collection) return null;
    let url = `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview?collection_name=${encodeURIComponent(collection)}`;
    const filename = ref.filename ?? doc?.filename;
    if (filename) url += `&filename=${encodeURIComponent(filename)}`;
    return url;
  }

  protected openPreview(url: string, ref: CaptureViewReference): void {
    this.previewUrl.set(url);
    this.previewTitle.set(viewTitle(ref));
    this.previewPage.set(ref.page ?? null);
    const statement = this.statementOf(ref);
    this.previewHighlight.set(statement && statement.length >= 8 ? statement : null);
    this.previewOpen.set(true);
  }
}
