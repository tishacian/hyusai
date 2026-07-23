import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  ApiService,
  type CaptureSessionDocument,
  type CaptureViewReference,
  type ProposalFact,
  type ProposalOpenQuestion,
} from '@app/core/api.service';
import { GlyphComponent, LiveDotComponent } from '@app/shared/cockpit';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { CaptureEngine } from './capture-engine';
import { ViewTileComponent } from './view-tile.component';
import {
  INDEX_STATE_DISPLAY,
  type CaptureTone,
  type ReportBlock,
  type ReportOpenQuestionRef,
  type ReportSectionCard,
  type ReportSubsectionCard,
  buildReportFiche,
  clockLabel,
  flattenReportList,
  indexStatusOf,
  paletteVar,
  refKey,
  reportFactText,
  reportSourceLabel,
  reportUnassignedFacts,
  toneVar,
  viewLocation,
  viewTitle,
  viewTone,
} from './capture-presentation';
import {
  composePublicationName,
  fieldAppliesToIntervention,
  headerValueAsDisplay,
} from './capture-templates';

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
    <!-- Page-scroll model: the shell <main> owns the scroll (a fixed 100vh calc
         here ignored the 52px business header and broke scrolling). The fiche
         grows naturally; the inspector stays visible via position:sticky. -->
    <div style="display:grid; grid-template-columns:minmax(0,1fr) 396px; align-items:start; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); overflow:visible; min-height:460px; background:var(--ck-bg-base);">
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
          <!-- quick access to the open-questions management panel (bottom of fiche) -->
          @if (hasProposal() && openQuestions().length) {
            <button
              type="button"
              (click)="scrollToQuestions()"
              [title]="'Aller au panneau de gestion des questions ouvertes'"
              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:5px 11px; border-radius:999px; border:1px solid color-mix(in oklab, var(--ck-signal-warn) 45%, transparent); background:color-mix(in oklab, var(--ck-signal-warn) 10%, transparent); color:var(--ck-signal-warn); font-size:11.5px; font-weight:600;"
            >
              <ck-glyph name="warn" [size]="12" color="currentColor" />
              Questions ouvertes ({{ openQuestions().length }}@if (blockingQuestionCount(); as b) {&nbsp;dont {{ b }} bloquante{{ b > 1 ? 's' : '' }}})
            </button>
          }
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

        <!-- review toolbar: status, read/edit toggle, AI instruction, acceptance -->
        @if (hasProposal()) {
          <div style="flex:none; padding:11px 24px; border-bottom:1px solid var(--ck-stroke-2); display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span
              style="display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:999px; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset);"
              [title]="'Statut de la proposition'"
            >
              <ck-glyph name="pulse" [size]="12" [color]="statusColor()" />
              <span class="ck-mono" style="font-size:10px; letter-spacing:0.08em; text-transform:uppercase;" [style.color]="statusColor()">{{ statusLabel() }}</span>
            </span>

            <button
              type="button"
              (click)="toggleEdit()"
              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:12px;"
            >
              <ck-glyph [name]="editMode() ? 'layers' : 'bolt'" [size]="13" color="currentColor" />
              {{ editMode() ? 'Voir la fiche' : 'Éditer le markdown' }}
            </button>

            @if (editMode()) {
              <button
                type="button"
                (click)="save()"
                style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); border:1px solid color-mix(in oklab, var(--ck-signal-cool) 50%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 14%, transparent); color:var(--ck-signal-cool); font-size:12px; font-weight:600;"
              >
                <ck-glyph name="check" [size]="13" color="currentColor" /> Enregistrer
              </button>
            }

            <span style="display:inline-flex; align-items:center; gap:6px; margin-left:auto;">
              <input
                #instr
                type="text"
                placeholder="Instruction IA (ex. resserrer la synthèse)…"
                (keydown.enter)="applyInstr(instr.value); instr.value=''"
                style="width:230px; max-width:40vw; padding:6px 10px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); color:var(--ck-fg-1); font-size:12px;"
              />
              <button
                type="button"
                (click)="applyInstr(instr.value); instr.value=''"
                [title]="'Appliquer une instruction IA au rapport'"
                style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:5px; padding:6px 10px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:12px;"
              >
                <ck-glyph name="bolt" [size]="13" color="var(--ck-signal-violet)" /> Appliquer
              </button>
            </span>

            <button
              type="button"
              (click)="exportReport()"
              [title]="'Exporter le rapport en Markdown'"
              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:12px;"
            >
              <ck-glyph name="arrow-down" [size]="13" color="currentColor" /> Markdown
            </button>
            <button
              type="button"
              (click)="downloadBrandedExport('pdf')"
              [disabled]="!!brandedExportBusy()"
              [title]="'Exporter le rapport PDF brandé Andritz'"
              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); border:1px solid color-mix(in oklab, var(--ck-signal-cool) 45%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 10%, transparent); color:var(--ck-signal-cool); font-size:12px; font-weight:600;"
            >
              <ck-glyph name="ledger" [size]="13" color="currentColor" />
              {{ brandedExportBusy() === 'pdf' ? 'PDF…' : 'PDF Andritz' }}
            </button>
            <button
              type="button"
              (click)="downloadBrandedExport('docx')"
              [disabled]="!!brandedExportBusy()"
              [title]="'Exporter le rapport DOCX brandé Andritz'"
              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:12px;"
            >
              <ck-glyph name="ledger" [size]="13" color="currentColor" />
              {{ brandedExportBusy() === 'docx' ? 'DOCX…' : 'DOCX' }}
            </button>
            @if (brandedExportError()) {
              <span style="font-size:11.5px; color:var(--ck-signal-neg);">{{ brandedExportError() }}</span>
            }

            <button
              type="button"
              (click)="requestChanges()"
              [disabled]="changesRequested() || reviewBusy()"
              [title]="'Marque la fiche « à retravailler » : corrections à apporter (jointes en notes), ni acceptée ni rejetée. Utile pour la reprendre plus tard ou la repasser à quelqu\\'un.'"
              style="appearance:none; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); font-size:12px; border:1px solid color-mix(in oklab, var(--ck-signal-warn) 50%, transparent); background:color-mix(in oklab, var(--ck-signal-warn) 12%, transparent); color:var(--ck-signal-warn);"
              [style.cursor]="changesRequested() ? 'default' : 'pointer'"
              [style.opacity]="changesRequested() ? '0.55' : '1'"
            >
              <ck-glyph name="layers" [size]="13" color="currentColor" /> À retravailler
            </button>

            <button
              type="button"
              (click)="reject()"
              [disabled]="rejected() || reviewBusy()"
              [title]="'Rejeter la fiche : écartée et non publiable (motif en notes)'"
              style="appearance:none; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); font-size:12px; border:1px solid color-mix(in oklab, var(--ck-signal-neg) 50%, transparent); background:color-mix(in oklab, var(--ck-signal-neg) 12%, transparent); color:var(--ck-signal-neg);"
              [style.cursor]="rejected() ? 'default' : 'pointer'"
              [style.opacity]="rejected() ? '0.55' : '1'"
            >
              <ck-glyph name="x" [size]="13" color="currentColor" /> Rejeter
            </button>

            <button
              type="button"
              (click)="accept()"
              [disabled]="accepted() || reviewBusy()"
              [title]="accepted() ? 'Rapport déjà accepté' : 'Accepter le rapport (requis avant publication)'"
              style="appearance:none; display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:var(--ck-radius-md); font-size:12px; font-weight:650;"
              [style.cursor]="accepted() ? 'default' : 'pointer'"
              [style.opacity]="accepted() ? '0.55' : '1'"
              [style.border]="'1px solid color-mix(in oklab, var(--ck-signal-pos) 55%, transparent)'"
              [style.background]="'color-mix(in oklab, var(--ck-signal-pos) ' + (accepted() ? '10' : '18') + '%, transparent)'"
              [style.color]="'var(--ck-signal-pos)'"
            >
              <ck-glyph name="check" [size]="13" color="currentColor" /> Accepter le rapport
            </button>

            @if (accepted()) {
              <button
                type="button"
                (click)="publish.emit()"
                [title]="'Publier la fiche acceptée vers la base de connaissances'"
                style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:var(--ck-radius-md); font-size:12px; font-weight:650; border:1px solid color-mix(in oklab, var(--ck-signal-cool) 55%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
              >
                <ck-glyph name="arrow-right" [size]="13" color="currentColor" /> Publier vers la base de connaissances
              </button>
            }

            <!-- shared review notes (review_notes for reject / changes-requested) -->
            <textarea
              [value]="reviewNotes()"
              (input)="onReviewNotes($event)"
              rows="1"
              placeholder="Notes de revue (jointes au rejet ou au marquage « à retravailler »)…"
              style="flex-basis:100%; resize:vertical; min-height:34px; max-height:120px; margin-top:2px; padding:7px 11px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:12px; line-height:1.5;"
            ></textarea>

            <!-- legend: what each review verb does (the verbs were unclear) -->
            <p style="flex-basis:100%; margin:2px 0 0; font-size:11px; line-height:1.5; color:var(--ck-fg-4);">
              <b style="color:var(--ck-signal-pos);">Accepter</b> : prête à publier vers la base de connaissances ·
              <b style="color:var(--ck-signal-warn);">À retravailler</b> : corrections à apporter (statut + notes), reprise possible plus tard ·
              <b style="color:var(--ck-signal-neg);">Rejeter</b> : écartée, non publiable. Vous pouvez aussi corriger directement (Éditer le markdown / instruction IA).
            </p>

            <!-- decision feedback: makes accept/reject/à-retravailler outcomes visible (never silent) -->
            @if (reviewFeedback(); as fb) {
              <div
                role="status"
                style="flex-basis:100%; margin-top:4px; display:flex; align-items:center; gap:8px; padding:8px 11px; border-radius:var(--ck-radius-md); font-size:12px; font-weight:600; border:1px solid;"
                [style.color]="fb.ok ? 'var(--ck-signal-pos)' : 'var(--ck-signal-neg)'"
                [style.border-color]="'color-mix(in oklab, ' + (fb.ok ? 'var(--ck-signal-pos)' : 'var(--ck-signal-neg)') + ' 45%, transparent)'"
                [style.background]="'color-mix(in oklab, ' + (fb.ok ? 'var(--ck-signal-pos)' : 'var(--ck-signal-neg)') + ' 12%, transparent)'"
              >
                <ck-glyph [name]="fb.ok ? 'check' : 'warn'" [size]="13" color="currentColor" />
                {{ fb.message }}
              </div>
            }
          </div>
        }

        <div class="ck-ambient-grid" style="padding:30px 0;">
          <!-- empty: proposal not generated yet -->
          @if (!hasProposal()) {
            <div style="min-height:360px; display:grid; place-items:center; padding:40px 28px; text-align:center;">
              <div style="display:flex; flex-direction:column; align-items:center; gap:14px; max-width:360px;">
                <ck-live-dot tone="violet" />
                <ck-glyph name="pulse" [size]="26" color="var(--ck-fg-4)" />
                <div style="font-size:15px; font-weight:600; color:var(--ck-fg-2);">Rapport en cours de génération…</div>
                <div class="ck-mono" style="font-size:11px; line-height:1.6; color:var(--ck-fg-4);">
                  La fiche structurée et ses sources apparaîtront ici dès que la synthèse de séance est prête.
                </div>
              </div>
            </div>
          } @else {
            <div style="max-width:680px; margin:0 auto; padding:0 28px;">
              <!-- edit mode: raw markdown -->
              @if (editMode()) {
                <h2 class="ck-mono" style="margin:0 0 12px; font-size:12px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-cool);">
                  Markdown du rapport
                </h2>
                <textarea
                  [value]="draft()"
                  (input)="onDraft($event)"
                  spellcheck="false"
                  style="width:100%; min-height:60vh; resize:vertical; padding:14px 16px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); color:var(--ck-fg-1); font-family:var(--ck-font-mono); font-size:12.5px; line-height:1.65;"
                ></textarea>
              } @else {
                <!-- read mode: structured fiche -->
                <h2 class="ck-mono" style="margin:0 0 16px; font-size:12px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-cool);">
                  {{ template() ? 'Fiche intervention FSE' : 'Fiche structurée' }}
                </h2>

                @if (template() && (interventionType() || publicationNamePreview())) {
                  <div style="margin:0 0 14px; display:flex; flex-wrap:wrap; gap:8px 14px; align-items:baseline;">
                    @if (interventionType(); as it) {
                      <span style="font-size:13px; color:var(--ck-fg-2);">
                        <span style="font-weight:600; color:var(--ck-fg-1);">{{ it.label }}</span>
                        <span class="ck-mono" style="margin-left:8px; font-size:11px; color:var(--ck-fg-4);">{{ it.doc_ref }}</span>
                      </span>
                    }
                    @if (publicationNamePreview(); as pubName) {
                      <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-4);">Publication · {{ pubName }}</span>
                    }
                  </div>
                }

                @if (headerRows().length) {
                  <div style="margin:0 0 18px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); overflow:hidden; background:var(--ck-bg-panel);">
                    <div style="padding:10px 16px; border-bottom:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset);">
                      <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Identification</span>
                    </div>
                    <dl style="margin:0; padding:12px 16px; display:grid; grid-template-columns:minmax(0,140px) minmax(0,1fr); gap:8px 14px;">
                      @for (row of headerRows(); track row.key) {
                        <dt class="ck-mono" style="font-size:10.5px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-fg-4); padding-top:2px;">{{ row.label }}</dt>
                        <dd style="margin:0; font-size:13.5px; color:var(--ck-fg-1);">{{ row.value || '—' }}</dd>
                      }
                    </dl>
                  </div>
                }

                @for (card of fiche(); track card.key) {
                  <article
                    [id]="sectionDomId(card.key)"
                    style="margin:0 0 16px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); overflow:hidden; background:var(--ck-bg-panel); transition:outline-color var(--ck-dur-med);"
                    [style.outline]="flashedSectionKey() === card.key ? '2px solid var(--ck-signal-cool)' : 'none'"
                  >
                    <header style="display:flex; align-items:center; gap:11px; padding:11px 16px; border-bottom:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset);">
                      <span class="ck-mono" style="flex:none; display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:6px; font-size:11px; font-weight:700; color:var(--ck-signal-cool); background:color-mix(in oklab, var(--ck-signal-cool) 16%, transparent); border:1px solid color-mix(in oklab, var(--ck-signal-cool) 35%, transparent);">{{ card.index }}</span>
                      <h3 style="margin:0; font-size:14px; font-weight:650; color:var(--ck-fg-1);">{{ card.title }}</h3>
                    </header>
                    <div style="padding:13px 16px; display:flex; flex-direction:column; gap:11px;">
                      @for (block of card.blocks; track $index) {
                        @if (block.kind === 'heading') {
                          <h4 class="ck-mono" style="margin:0; font-size:11px; letter-spacing:0.05em; text-transform:uppercase; color:var(--ck-signal-cool); font-weight:700;">{{ block.text }}</h4>
                        } @else if (block.kind === 'list') {
                          <ul style="margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:6px;">
                            @for (row of listRows(block); track $index) {
                              <li style="display:flex; gap:8px; font-size:14px; line-height:1.65; color:var(--ck-fg-2);" [style.paddingLeft.px]="row.depth * 16">
                                <span style="flex:none; margin-top:8px; width:5px; height:5px; border-radius:999px; background:var(--ck-fg-5);"></span>
                                <span>{{ row.text }}</span>
                              </li>
                            }
                          </ul>
                        } @else if (block.text) {
                          <p style="margin:0; font-size:14.5px; line-height:1.7; color:var(--ck-fg-1); text-wrap:pretty;">{{ block.text }}</p>
                        }
                      }

                      @for (fact of card.facts; track $index) {
                        <p style="margin:0; display:flex; gap:8px; font-size:14px; line-height:1.65; color:var(--ck-fg-2);">
                          <span style="flex:none; margin-top:8px; width:5px; height:5px; border-radius:999px; background:var(--ck-fg-5);"></span>
                          <span>
                            {{ factText(fact) }}
                            @if (markerFor(fact); as m) {
                              <button
                                type="button"
                                class="ck-mono"
                                (click)="select(m.key)"
                                [title]="viewTitleOf(m.ref) + ' · ' + locationOf(m.ref)"
                                style="appearance:none; cursor:pointer; vertical-align:super; margin-left:3px; display:inline-flex; align-items:center; gap:3px; padding:1px 6px 1px 5px; border-radius:999px; line-height:1; font-size:9.5px; font-weight:700;"
                                [style.color]="tintOf(m.ref)"
                                [style.border]="'1px solid ' + (m.key === selectedKey() ? tintOf(m.ref) : 'color-mix(in oklab, ' + tintOf(m.ref) + ' 40%, transparent)')"
                                [style.background]="'color-mix(in oklab, ' + tintOf(m.ref) + ' ' + (m.key === selectedKey() ? '22' : '9') + '%, transparent)'"
                              >
                                <ck-glyph name="crosshair" [size]="9" color="currentColor" /> {{ m.n }}
                              </button>
                            }
                          </span>
                        </p>
                      }

                      @for (sub of card.subsections; track sub.key) {
                        <section
                          [id]="sectionDomId(sub.key)"
                          style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); padding:11px 13px; display:flex; flex-direction:column; gap:9px;"
                          [style.outline]="flashedSectionKey() === sub.key ? '2px solid var(--ck-signal-cool)' : 'none'"
                        >
                          <h4 style="margin:0; font-size:12.5px; font-weight:600; color:var(--ck-fg-1);">{{ sub.title }}</h4>
                          @for (block of sub.blocks; track $index) {
                            @if (block.kind === 'heading') {
                              <h5 class="ck-mono" style="margin:0; font-size:10px; letter-spacing:0.05em; text-transform:uppercase; color:var(--ck-signal-cool); font-weight:700;">{{ block.text }}</h5>
                            } @else if (block.kind === 'list') {
                              <ul style="margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:5px;">
                                @for (row of listRows(block); track $index) {
                                  <li style="display:flex; gap:8px; font-size:13px; line-height:1.6; color:var(--ck-fg-3);" [style.paddingLeft.px]="row.depth * 16">
                                    <span style="flex:none; margin-top:7px; width:4px; height:4px; border-radius:999px; background:var(--ck-fg-5);"></span>
                                    <span>{{ row.text }}</span>
                                  </li>
                                }
                              </ul>
                            } @else if (block.text) {
                              <p style="margin:0; font-size:13px; line-height:1.6; color:var(--ck-fg-2);">{{ block.text }}</p>
                            }
                          }
                          @for (fact of sub.facts; track $index) {
                            <p style="margin:0; display:flex; gap:8px; font-size:13px; line-height:1.6; color:var(--ck-fg-3);">
                              <span style="flex:none; margin-top:7px; width:4px; height:4px; border-radius:999px; background:var(--ck-fg-5);"></span>
                              <span>
                                {{ factText(fact) }}
                                @if (markerFor(fact); as m) {
                                  <button
                                    type="button"
                                    class="ck-mono"
                                    (click)="select(m.key)"
                                    [title]="viewTitleOf(m.ref) + ' · ' + locationOf(m.ref)"
                                    style="appearance:none; cursor:pointer; vertical-align:super; margin-left:3px; display:inline-flex; align-items:center; gap:3px; padding:1px 6px 1px 5px; border-radius:999px; line-height:1; font-size:9px; font-weight:700;"
                                    [style.color]="tintOf(m.ref)"
                                    [style.border]="'1px solid ' + (m.key === selectedKey() ? tintOf(m.ref) : 'color-mix(in oklab, ' + tintOf(m.ref) + ' 40%, transparent)')"
                                    [style.background]="'color-mix(in oklab, ' + tintOf(m.ref) + ' ' + (m.key === selectedKey() ? '22' : '9') + '%, transparent)'"
                                  >
                                    <ck-glyph name="crosshair" [size]="9" color="currentColor" /> {{ m.n }}
                                  </button>
                                }
                              </span>
                            </p>
                          }
                          <!-- provenance markers of the reformulated prose (facts hidden by synthesis) -->
                          @if (sub.blocks.length && sectionMarkers(sub).length) {
                            <div style="display:flex; flex-wrap:wrap; align-items:center; gap:5px;">
                              <span class="ck-mono" style="font-size:9px; letter-spacing:0.08em; text-transform:uppercase; color:var(--ck-fg-5); margin-right:2px;">Ancres</span>
                              @for (m of sectionMarkers(sub); track m.key) {
                                <button
                                  type="button"
                                  class="ck-mono"
                                  (click)="select(m.key)"
                                  [title]="viewTitleOf(m.ref) + ' · ' + locationOf(m.ref)"
                                  style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:3px; padding:1px 6px 1px 5px; border-radius:999px; line-height:1.4; font-size:9px; font-weight:700;"
                                  [style.color]="tintOf(m.ref)"
                                  [style.border]="'1px solid ' + (m.key === selectedKey() ? tintOf(m.ref) : 'color-mix(in oklab, ' + tintOf(m.ref) + ' 40%, transparent)')"
                                  [style.background]="'color-mix(in oklab, ' + tintOf(m.ref) + ' ' + (m.key === selectedKey() ? '22' : '9') + '%, transparent)'"
                                >
                                  <ck-glyph name="crosshair" [size]="9" color="currentColor" /> {{ m.n }}
                                </button>
                              }
                            </div>
                          }
                          @if (sub.openQuestions.length) {
                            <div style="border-radius:var(--ck-radius-sm); border:1px solid color-mix(in oklab, var(--ck-signal-warn) 30%, transparent); background:color-mix(in oklab, var(--ck-signal-warn) 7%, transparent); padding:7px 9px; display:flex; flex-direction:column; gap:4px;">
                              <span class="ck-mono" style="font-size:9.5px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-warn);">Questions ouvertes</span>
                              @for (q of sub.openQuestions; track $index) {
                                <button
                                  type="button"
                                  (click)="jumpToQuestion(q)"
                                  [title]="'Voir cette question dans le panneau de gestion'"
                                  style="appearance:none; cursor:pointer; background:none; border:none; padding:0; text-align:left; font-size:12px; line-height:1.55; color:var(--ck-fg-2); text-decoration:underline dotted color-mix(in oklab, var(--ck-signal-warn) 55%, transparent); text-underline-offset:3px;"
                                >
                                  {{ q.text }}
                                </button>
                              }
                            </div>
                          }
                          @if (sub.sources.length) {
                            <div style="display:flex; flex-wrap:wrap; gap:6px;">
                              @for (src of sub.sources; track $index) {
                                <span class="ck-mono" style="display:inline-flex; align-items:center; gap:5px; padding:3px 8px; border-radius:999px; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); font-size:10px; color:var(--ck-fg-3); max-width:100%;">
                                  <ck-glyph name="ledger" [size]="10" color="var(--ck-fg-4)" />
                                  <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ sourceLabel(src) }}</span>
                                </span>
                              }
                            </div>
                          }
                        </section>
                      }

                      <!-- provenance markers of the reformulated prose (facts hidden by synthesis) -->
                      @if (card.blocks.length && sectionMarkers(card).length) {
                        <div style="display:flex; flex-wrap:wrap; align-items:center; gap:5px;">
                          <span class="ck-mono" style="font-size:9.5px; letter-spacing:0.08em; text-transform:uppercase; color:var(--ck-fg-5); margin-right:2px;">Ancres</span>
                          @for (m of sectionMarkers(card); track m.key) {
                            <button
                              type="button"
                              class="ck-mono"
                              (click)="select(m.key)"
                              [title]="viewTitleOf(m.ref) + ' · ' + locationOf(m.ref)"
                              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:3px; padding:1px 6px 1px 5px; border-radius:999px; line-height:1.4; font-size:9.5px; font-weight:700;"
                              [style.color]="tintOf(m.ref)"
                              [style.border]="'1px solid ' + (m.key === selectedKey() ? tintOf(m.ref) : 'color-mix(in oklab, ' + tintOf(m.ref) + ' 40%, transparent)')"
                              [style.background]="'color-mix(in oklab, ' + tintOf(m.ref) + ' ' + (m.key === selectedKey() ? '22' : '9') + '%, transparent)'"
                            >
                              <ck-glyph name="crosshair" [size]="9" color="currentColor" /> {{ m.n }}
                            </button>
                          }
                        </div>
                      }

                      @if (card.openQuestions.length) {
                        <div style="border-radius:var(--ck-radius-sm); border:1px solid color-mix(in oklab, var(--ck-signal-warn) 30%, transparent); background:color-mix(in oklab, var(--ck-signal-warn) 7%, transparent); padding:8px 10px; display:flex; flex-direction:column; gap:5px;">
                          <span class="ck-mono" style="font-size:10px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-warn);">Questions ouvertes</span>
                          @for (q of card.openQuestions; track $index) {
                            <button
                              type="button"
                              (click)="jumpToQuestion(q)"
                              [title]="'Voir cette question dans le panneau de gestion'"
                              style="appearance:none; cursor:pointer; background:none; border:none; padding:0; text-align:left; font-size:12.5px; line-height:1.55; color:var(--ck-fg-2); text-decoration:underline dotted color-mix(in oklab, var(--ck-signal-warn) 55%, transparent); text-underline-offset:3px;"
                            >
                              {{ q.text }}
                            </button>
                          }
                        </div>
                      }
                    </div>
                    @if (card.sources.length) {
                      <footer style="padding:9px 16px; border-top:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); display:flex; flex-wrap:wrap; align-items:center; gap:6px;">
                        <span class="ck-mono" style="font-size:9.5px; letter-spacing:0.08em; text-transform:uppercase; color:var(--ck-fg-5); margin-right:2px;">Sources</span>
                        @for (src of card.sources; track $index) {
                          <span class="ck-mono" style="display:inline-flex; align-items:center; gap:5px; padding:3px 8px; border-radius:999px; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); font-size:10px; color:var(--ck-fg-3); max-width:100%;">
                            <ck-glyph name="ledger" [size]="10" color="var(--ck-fg-4)" />
                            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ sourceLabel(src) }}</span>
                          </span>
                        }
                      </footer>
                    }
                  </article>
                }

                <!-- hors plan -->
                @if (unassigned().length) {
                  <article style="margin:0 0 16px; border:1px dashed var(--ck-stroke-2); border-radius:var(--ck-radius-lg); background:var(--ck-bg-panel); padding:13px 16px; display:flex; flex-direction:column; gap:7px;">
                    <h3 class="ck-mono" style="margin:0 0 2px; font-size:11px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-fg-4); display:flex; align-items:center; gap:7px;">
                      <ck-glyph name="layers" [size]="13" color="var(--ck-fg-4)" /> Hors plan
                    </h3>
                    @for (fact of unassigned(); track $index) {
                      <p style="margin:0; display:flex; gap:8px; font-size:13px; line-height:1.6; color:var(--ck-fg-3);">
                        <span style="flex:none; margin-top:7px; width:4px; height:4px; border-radius:999px; background:var(--ck-fg-5);"></span>
                        <span>{{ fact }}</span>
                      </p>
                    }
                  </article>
                }

                @if (!fiche().length && !unassigned().length) {
                  <p style="font-size:13px; color:var(--ck-fg-4); font-style:italic; margin:0 0 16px;">
                    Aucune section structurée pour ce rapport. Basculez en édition pour rédiger le markdown.
                  </p>
                }

                <!-- pointed sources (provenance) — a COMPACT index of pointed
                     pieces, not a second verbatim transcript. Each chip selects
                     the source (opens it in the inspector). We no longer re-print
                     the raw statement here: the reformulated fiche above already
                     carries inline markers, so this stays a provenance index and
                     avoids the "raw transcript + reformulation" duplication. -->
                <section style="margin:18px 0 0; border-top:1px solid var(--ck-stroke-2); padding-top:16px;">
                  <h3 class="ck-mono" style="margin:0 0 11px; font-size:11px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-cool); display:flex; align-items:center; gap:7px;">
                    <ck-glyph name="crosshair" [size]="13" color="var(--ck-signal-cool)" /> Sources pointées ({{ sources().length }})
                  </h3>
                  @if (sources().length) {
                    <div style="display:flex; flex-wrap:wrap; gap:6px;">
                      @for (src of sources(); track src.key) {
                        <button
                          type="button"
                          (click)="select(src.key)"
                          [title]="statementOf(src.ref)"
                          style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; max-width:100%; padding:4px 10px 4px 7px; border-radius:999px; font-size:11px; transition:background var(--ck-dur-med), border-color var(--ck-dur-med);"
                          [style.color]="src.key === selectedKey() ? tintOf(src.ref) : 'var(--ck-fg-3)'"
                          [style.border]="'1px solid ' + (src.key === selectedKey() ? tintOf(src.ref) : 'var(--ck-stroke-2)')"
                          [style.background]="'color-mix(in oklab, ' + tintOf(src.ref) + ' ' + (src.key === selectedKey() ? '16' : '0') + '%, var(--ck-bg-base))'"
                        >
                          <span class="ck-mono" style="flex:none; font-weight:700;">{{ src.n }}</span>
                          <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ viewTitleOf(src.ref) }}</span>
                          <span class="ck-mono" style="flex:none; color:var(--ck-fg-5);">{{ locationOf(src.ref) }}</span>
                        </button>
                      }
                    </div>
                    <!-- reverse provenance: sections of the fiche citing the selected anchor -->
                    @if (selected(); as sel) {
                      @if (sectionRefsFor(sel).length) {
                        <div style="margin-top:9px; display:flex; flex-wrap:wrap; align-items:center; gap:6px;">
                          <span class="ck-mono" style="font-size:9.5px; letter-spacing:0.08em; text-transform:uppercase; color:var(--ck-fg-5);">Référencée dans</span>
                          @for (section of sectionRefsFor(sel); track section.key) {
                            <button
                              type="button"
                              (click)="scrollToSection(section.key)"
                              [title]="'Aller à la section « ' + section.title + ' »'"
                              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:5px; max-width:100%; padding:3px 9px; border-radius:999px; border:1px solid color-mix(in oklab, var(--ck-signal-cool) 40%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 8%, transparent); color:var(--ck-signal-cool); font-size:11px;"
                            >
                              <ck-glyph name="arrow-up" [size]="10" color="currentColor" />
                              <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ section.title }}</span>
                            </button>
                          }
                        </div>
                      }
                    }
                  } @else {
                    <p style="font-size:13px; color:var(--ck-fg-4); font-style:italic;">
                      Aucune source pointée pour cette séance. Les affirmations sourcées apparaissent ici à mesure que des pièces sont
                      pointées pendant la séance.
                    </p>
                  }
                </section>

                <!-- open-questions management -->
                @if (openQuestions().length) {
                  <section id="kc-oq-panel" style="margin:22px 0 0; border-top:1px solid var(--ck-stroke-2); padding-top:16px; display:flex; flex-direction:column; gap:10px; scroll-margin-top:70px;">
                    <h3 class="ck-mono" style="margin:0; font-size:11px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ck-signal-warn); display:flex; align-items:center; gap:7px;">
                      <ck-glyph name="warn" [size]="13" color="var(--ck-signal-warn)" /> Questions ouvertes ({{ openQuestions().length }})
                    </h3>
                    @for (q of openQuestions(); track $index) {
                      <div
                        [id]="'kc-oq-' + $index"
                        style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-panel); padding:11px 13px; display:flex; flex-direction:column; gap:8px; scroll-margin-top:70px;"
                        [style.opacity]="isResolved(q) ? '0.6' : '1'"
                        [style.outline]="flashedQuestionIndex() === $index ? '2px solid var(--ck-signal-warn)' : 'none'"
                      >
                        <div style="display:flex; align-items:flex-start; gap:8px;">
                          <span style="flex:1; font-size:13.5px; line-height:1.6; color:var(--ck-fg-1);">{{ questionText(q) }}</span>
                          @if (q.source === 'previous_report') {
                            <span
                              class="ck-mono"
                              style="flex:none; font-size:9px; letter-spacing:0.06em; text-transform:uppercase; padding:2px 7px; border-radius:999px; font-weight:700; color:var(--ck-signal-warn); border:1px solid color-mix(in oklab, var(--ck-signal-warn) 55%, transparent); background:color-mix(in oklab, var(--ck-signal-warn) 12%, transparent);"
                              title="Repris du rapport N-1"
                            >N-1</span>
                          }
                          @if (criticalityBadge(q); as crit) {
                            <span
                              class="ck-mono"
                              style="flex:none; font-size:9px; letter-spacing:0.06em; text-transform:uppercase; padding:2px 7px; border-radius:999px; font-weight:700;"
                              [style.color]="crit.color"
                              [style.border]="'1px solid color-mix(in oklab, ' + crit.color + ' 55%, transparent)'"
                              [style.background]="'color-mix(in oklab, ' + crit.color + ' 12%, transparent)'"
                            >{{ crit.label }}</span>
                          }
                          <span class="ck-mono" style="flex:none; font-size:9px; letter-spacing:0.06em; text-transform:uppercase; padding:2px 7px; border-radius:999px; border:1px solid var(--ck-stroke-2);" [style.color]="questionStatusColor(q)">{{ questionStatusLabel(q) }}</span>
                        </div>
                        @if (q.answer || q.answered_text; as ans) {
                          <p style="margin:0; font-size:12.5px; line-height:1.55; color:var(--ck-fg-3); padding-left:9px; border-left:2px solid color-mix(in oklab, var(--ck-signal-pos) 50%, transparent);">{{ ans }}</p>
                        }
                        @if (!isResolved(q)) {
                          <div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap;">
                            <input
                              #ans
                              type="text"
                              placeholder="Répondre…"
                              (keydown.enter)="answer(q, ans.value); ans.value=''"
                              style="flex:1; min-width:160px; padding:6px 10px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); color:var(--ck-fg-1); font-size:12px;"
                            />
                            <button
                              type="button"
                              (click)="answer(q, ans.value); ans.value=''"
                              [disabled]="!questionId(q)"
                              [title]="questionId(q) ? 'Répondre à la question' : 'Question non adressable (id manquant)'"
                              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:5px; padding:6px 10px; border-radius:var(--ck-radius-md); border:1px solid color-mix(in oklab, var(--ck-signal-pos) 50%, transparent); background:color-mix(in oklab, var(--ck-signal-pos) 12%, transparent); color:var(--ck-signal-pos); font-size:12px;"
                              [style.opacity]="questionId(q) ? '1' : '0.5'"
                            >
                              <ck-glyph name="check" [size]="12" color="currentColor" /> Répondre
                            </button>
                            <button
                              type="button"
                              (click)="defer(q)"
                              [title]="'Différer la question'"
                              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:5px; padding:6px 10px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-3); font-size:12px;"
                            >
                              <ck-glyph name="arrow-right" [size]="12" color="currentColor" /> Différer
                            </button>
                            <button
                              type="button"
                              (click)="invalidate(q)"
                              [title]="'Invalider la question'"
                              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:5px; padding:6px 10px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-4); font-size:12px;"
                            >
                              <ck-glyph name="x" [size]="12" color="currentColor" /> Invalider
                            </button>
                          </div>
                        }
                      </div>
                    }
                  </section>
                }
              }
            </div>
          }
        </div>
      </div>

      <!-- inspector — sticky so it stays in view while the fiche scrolls the page -->
      <div style="display:flex; flex-direction:column; background:var(--ck-bg-panel); min-width:0; position:sticky; top:12px; align-self:start; max-height:calc(100dvh - 76px);">
        <div style="flex:none; padding:14px 18px; border-bottom:1px solid var(--ck-stroke-2); display:flex; align-items:center; gap:8px;">
          <ck-glyph name="focus" [size]="15" color="var(--ck-fg-3)" />
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
            Source & provenance
          </span>
        </div>

        @if (selected(); as sel) {
          <div class="ck-scroll" style="flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:16px; min-height:0;">
            @if (previewUrlFor(sel); as url) {
              <!-- Real pointed document rendered in place (no dialog), page +
                   highlighted passage — replaces the empty striped placeholder. -->
              <div style="border-radius:var(--ck-radius-md); overflow:hidden; border:1px solid var(--ck-stroke-2);">
                <app-document-preview
                  [inline]="true"
                  [previewUrl]="url"
                  [page]="sel.page ?? null"
                  [highlight]="highlightFor(sel)"
                  [heightPx]="320"
                />
              </div>
            } @else {
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
            }

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
              <!-- reverse provenance: fiche sections citing this anchor -->
              @if (sectionRefsFor(sel).length) {
                <div style="display:flex; flex-direction:column; gap:5px;">
                  <span class="ck-mono" style="font-size:9px; letter-spacing:0.1em; text-transform:uppercase; color:var(--ck-fg-5);">Citée dans</span>
                  @for (section of sectionRefsFor(sel); track section.key) {
                    <button
                      type="button"
                      (click)="scrollToSection(section.key)"
                      [title]="'Aller à la section « ' + section.title + ' »'"
                      style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:6px; align-self:flex-start; max-width:100%; padding:4px 10px; border-radius:999px; border:1px solid color-mix(in oklab, var(--ck-signal-cool) 40%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 8%, transparent); color:var(--ck-signal-cool); font-size:11.5px;"
                    >
                      <ck-glyph name="arrow-up" [size]="11" color="currentColor" />
                      <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ section.title }}</span>
                    </button>
                  }
                </div>
              }
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

  /** Advance to the real KB publication surface once the report is accepted. */
  @Output() publish = new EventEmitter<void>();

  protected readonly selectedKey = signal<string | null>(null);

  protected readonly previewOpen = signal(false);
  protected readonly previewUrl = signal<string | null>(null);
  protected readonly previewTitle = signal('');
  protected readonly previewPage = signal<number | null>(null);
  protected readonly previewHighlight = signal<string | null>(null);

  /** Read (structured fiche) vs edit (raw markdown) toggle. */
  protected readonly editMode = signal(false);
  /** Working copy of the markdown while editing (seeded on entering edit). */
  protected readonly draft = signal('');

  /** Shared review notes for reject / changes-requested (review_notes). */
  protected readonly reviewNotes = signal('');

  /** Transient outcome banner for the last review decision (success / failure). */
  protected readonly reviewFeedback = signal<{ ok: boolean; message: string } | null>(null);
  /** Guards the review buttons while a decision round-trip is in flight. */
  protected readonly reviewBusy = signal(false);
  /** Guards branded PDF/DOCX export downloads. */
  protected readonly brandedExportBusy = signal<'pdf' | 'docx' | null>(null);
  protected readonly brandedExportError = signal<string | null>(null);

  private async runReview(
    status: 'accepted' | 'rejected' | 'changes_requested',
    okMessage: string,
  ): Promise<void> {
    if (this.reviewBusy()) return;
    this.reviewBusy.set(true);
    this.reviewFeedback.set(null);
    const notes = this.reviewNotes().trim() || undefined;
    const ok = await this.engine.reviewProposal(status, notes);
    this.reviewBusy.set(false);
    this.reviewFeedback.set({
      ok,
      message: ok ? okMessage : this.engine.lastError() || 'Échec de la décision — réessayez.',
    });
  }

  constructor() {
    // Safety net: the shell normally calls loadProposal() when entering review,
    // but if we land here cold (deep link / refresh) and the proposal is still
    // null while a session exists, fetch it ourselves.
    if (!this.engine.proposal() && this.engine.sessionId()) {
      void this.engine.loadProposal();
    }
  }

  protected readonly sources = computed<ReportSource[]>(() => {
    let n = 0;
    // Key on the journaled event id first: two marks on the same doc+page share
    // one refKey, which collides both Angular tracking and the selection state.
    return this.engine
      .anchors()
      .filter((ref) => ref.document_id || ref.statement || ref.filename || ref.title)
      .map((ref) => ({ key: ref.event_id ?? refKey(ref), n: ++n, ref }));
  });

  // ---- structured fiche (P0 #2) ------------------------------------------
  protected readonly hasProposal = computed(() => this.engine.proposal() != null);
  protected readonly fiche = computed<ReportSectionCard[]>(() => buildReportFiche(this.engine.proposal()));
  protected readonly unassigned = computed(() => reportUnassignedFacts(this.engine.proposal()));
  protected readonly reportMarkdown = computed(() => this.engine.proposal()?.proposal?.report_markdown ?? '');
  /** Review-panel questions, criticality-ordered: blocking first, then priority
   * descending (raw backend scale kept), stable for ties. */
  protected readonly openQuestions = computed<ProposalOpenQuestion[]>(() => {
    const raw = this.engine.proposal()?.proposal?.open_questions ?? [];
    return raw
      .map((q, i) => ({ q, i }))
      .sort((a, b) => {
        const blocking = Number(Boolean(b.q.blocking)) - Number(Boolean(a.q.blocking));
        if (blocking !== 0) return blocking;
        const priority = this.priorityOf(b.q) - this.priorityOf(a.q);
        if (priority !== 0) return priority;
        return a.i - b.i;
      })
      .map((entry) => entry.q);
  });
  protected readonly blockingQuestionCount = computed(
    () => this.openQuestions().filter((q) => Boolean(q.blocking)).length,
  );
  protected readonly accepted = computed(() => {
    const s = (this.engine.proposal()?.status ?? '').toLowerCase();
    return s === 'accepted' || s === 'published';
  });

  /** Brief visual pulse on the fiche section a reverse-provenance jump lands on. */
  protected readonly flashedSectionKey = signal<string | null>(null);
  /** Brief visual pulse on the management-panel question a fiche label jumps to. */
  protected readonly flashedQuestionIndex = signal<number | null>(null);

  /** Reverse provenance map: journaled anchor event id → fiche sections citing it. */
  private readonly sectionsByEvent = computed(() => {
    const map = new Map<string, Array<{ key: string; title: string }>>();
    const add = (node: ReportSubsectionCard, title: string) => {
      for (const eventId of node.sourceEventIds) {
        const list = map.get(eventId) ?? [];
        if (!list.some((entry) => entry.key === node.key)) list.push({ key: node.key, title });
        map.set(eventId, list);
      }
    };
    for (const card of this.fiche()) {
      add(card, `${card.index}. ${card.title}`);
      for (const sub of card.subsections) add(sub, `${card.index}. ${card.title} · ${sub.title}`);
    }
    return map;
  });

  /** Lookup so a fiche fact can resolve its journaled anchor (inline marker). */
  private readonly sourceIndex = computed(() => {
    const byEvent = new Map<string, ReportSource>();
    const byStatement = new Map<string, ReportSource>();
    for (const src of this.sources()) {
      if (src.ref.event_id) byEvent.set(src.ref.event_id, src);
      const stmt = this.normStatement(src.ref.statement);
      if (stmt) byStatement.set(stmt, src);
    }
    return { byEvent, byStatement };
  });

  private static readonly STATUS_DISPLAY: Record<string, { label: string; tone: CaptureTone | 'neutral' }> = {
    draft: { label: 'Brouillon', tone: 'cool' },
    pending: { label: 'En attente', tone: 'warn' },
    pending_review: { label: 'En revue', tone: 'warn' },
    in_review: { label: 'En revue', tone: 'warn' },
    changes_requested: { label: 'Corrections demandées', tone: 'warn' },
    accepted: { label: 'Accepté', tone: 'pos' },
    rejected: { label: 'Rejeté', tone: 'neg' },
    published: { label: 'Publié', tone: 'pos' },
  };
  protected readonly statusLabel = computed(() => {
    const raw = (this.engine.proposal()?.status ?? '').toLowerCase();
    return ReportProvenanceComponent.STATUS_DISPLAY[raw]?.label ?? (raw || '—');
  });
  protected readonly statusColor = computed(() => {
    const raw = (this.engine.proposal()?.status ?? '').toLowerCase();
    return paletteVar(ReportProvenanceComponent.STATUS_DISPLAY[raw]?.tone ?? 'cool');
  });

  protected readonly selected = computed<CaptureViewReference | null>(() => {
    const key = this.selectedKey();
    return this.sources().find((s) => s.key === key)?.ref ?? null;
  });

  protected readonly title = computed(() => this.engine.session()?.title ?? 'Rapport de capture');
  protected readonly template = this.engine.template;
  protected readonly interventionType = this.engine.interventionType;
  protected readonly publicationNamePreview = computed(() => {
    if (!this.template()) return '';
    return composePublicationName(this.engine.headerFields());
  });
  protected readonly headerRows = computed(() => {
    const tpl = this.template();
    if (!tpl) return [];
    const values = this.engine.headerFields();
    const typeId = this.engine.interventionTypeId();
    return tpl.required_fields
      .filter((field) => fieldAppliesToIntervention(field, typeId))
      .map((field) => ({
        key: field.key,
        label: field.label,
        value: headerValueAsDisplay(values[field.key]),
      }));
  });
  protected readonly reference = computed(() => {
    const proposal = this.engine.proposalId();
    const sessionId = this.engine.sessionId();
    const tpl = this.template();
    if (tpl) {
      const ref = headerValueAsDisplay(this.engine.headerFields()['reference']);
      if (ref) return ref;
    }
    return proposal ? `proposition ${proposal}` : sessionId ? `séance ${sessionId}` : '—';
  });
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

  // ---- fiche / edit / review actions -------------------------------------
  protected toggleEdit(): void {
    if (!this.editMode()) this.draft.set(this.reportMarkdown());
    this.editMode.update((v) => !v);
  }

  protected onDraft(event: Event): void {
    this.draft.set((event.target as HTMLTextAreaElement).value);
  }

  protected async save(): Promise<void> {
    await this.engine.saveReport(this.draft());
    this.editMode.set(false);
  }

  protected applyInstr(text: string): void {
    const instruction = text.trim();
    if (!instruction) return;
    void this.engine.applyInstruction(instruction);
  }

  protected accept(): void {
    if (this.accepted()) return;
    void this.runReview('accepted', 'Fiche acceptée — prête à publier.');
  }

  /** Whether the operator has demanded changes (workflow state). */
  protected readonly changesRequested = computed(
    () => (this.engine.proposal()?.status ?? '').toLowerCase() === 'changes_requested',
  );
  /** Whether the report has been rejected (workflow state). */
  protected readonly rejected = computed(
    () => (this.engine.proposal()?.status ?? '').toLowerCase() === 'rejected',
  );

  protected requestChanges(): void {
    void this.runReview('changes_requested', 'Fiche marquée « à retravailler ».');
  }

  protected reject(): void {
    void this.runReview('rejected', 'Fiche rejetée — non publiable.');
  }

  protected onReviewNotes(event: Event): void {
    this.reviewNotes.set((event.target as HTMLTextAreaElement).value);
  }

  /** Export the report as Markdown (available as soon as a proposal is loaded). */
  protected exportReport(): void {
    void this.engine.exportReport();
  }

  protected async downloadBrandedExport(format: 'pdf' | 'docx'): Promise<void> {
    const proposalId = this.engine.proposalId();
    if (!proposalId || this.brandedExportBusy()) return;
    this.brandedExportBusy.set(format);
    this.brandedExportError.set(null);
    try {
      const blob = await firstValueFrom(this.api.downloadCaptureProposalExport(proposalId, format));
      const stem = (this.title() || 'rapport-fse').trim().replace(/[^\w.\-]+/g, '_');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${stem}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      this.brandedExportError.set(`Export ${format.toUpperCase()} impossible.`);
    } finally {
      this.brandedExportBusy.set(null);
    }
  }

  protected factText(fact: ProposalFact): string {
    return reportFactText(fact);
  }

  protected sourceLabel = reportSourceLabel;

  protected listRows(block: ReportBlock): Array<{ text: string; depth: number }> {
    return flattenReportList(block.items ?? []);
  }

  /** Resolve a fiche fact to its journaled anchor (inline provenance marker). */
  protected markerFor(fact: ProposalFact): ReportSource | null {
    const index = this.sourceIndex();
    const eventId = fact.source_event_id ?? undefined;
    if (eventId && index.byEvent.has(eventId)) return index.byEvent.get(eventId) ?? null;
    const stmt = this.normStatement(fact.statement ?? fact.text);
    if (stmt && index.byStatement.has(stmt)) return index.byStatement.get(stmt) ?? null;
    return null;
  }

  private normStatement(value: string | null | undefined): string {
    return (value ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  // ---- section anchors & reverse provenance (P3) --------------------------

  /** Anchor markers of a synthesized section (its facts are hidden by the prose). */
  protected sectionMarkers(node: ReportSubsectionCard): ReportSource[] {
    const byEvent = this.sourceIndex().byEvent;
    const markers: ReportSource[] = [];
    for (const eventId of node.sourceEventIds) {
      const src = byEvent.get(eventId);
      if (src) markers.push(src);
    }
    return markers;
  }

  /** Fiche sections citing the given anchor (reverse chip → section link). */
  protected sectionRefsFor(ref: CaptureViewReference): Array<{ key: string; title: string }> {
    const eventId = ref.event_id;
    if (!eventId) return [];
    return this.sectionsByEvent().get(eventId) ?? [];
  }

  protected sectionDomId(key: string): string {
    return `kc-section-${key}`;
  }

  protected scrollToSection(key: string): void {
    document.getElementById(this.sectionDomId(key))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    this.flashedSectionKey.set(key);
    setTimeout(() => {
      if (this.flashedSectionKey() === key) this.flashedSectionKey.set(null);
    }, 1600);
  }

  // ---- open-questions navigation (P2) --------------------------------------

  protected scrollToQuestions(): void {
    document.getElementById('kc-oq-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  /** Jump from a fiche section's question label to the management panel entry. */
  protected jumpToQuestion(ref: ReportOpenQuestionRef): void {
    const list = this.openQuestions();
    const wanted = this.normStatement(ref.text);
    const index = list.findIndex((q) => {
      if (ref.gapId) {
        const id = String(q.gap_id ?? q.id ?? q.question_id ?? '').trim();
        if (id && id === ref.gapId) return true;
      }
      return this.normStatement(this.questionText(q)) === wanted;
    });
    if (index < 0) {
      this.scrollToQuestions();
      return;
    }
    document.getElementById(`kc-oq-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    this.flashedQuestionIndex.set(index);
    setTimeout(() => {
      if (this.flashedQuestionIndex() === index) this.flashedQuestionIndex.set(null);
    }, 1600);
  }

  // ---- open questions -----------------------------------------------------

  /** Numeric priority, defensively parsed (backend mixes 0-3 and 0..1 scales). */
  private priorityOf(q: ProposalOpenQuestion): number {
    const raw = q.priority ?? q.severity;
    const n = typeof raw === 'number' ? raw : parseFloat(String(raw ?? ''));
    return Number.isFinite(n) ? n : 0;
  }

  /** Criticality badge: blocking (red), high priority (warn) — per-item scale
   * inferred defensively (values > 1 read on the 0-3 scale, else 0..1). */
  protected criticalityBadge(q: ProposalOpenQuestion): { label: string; color: string } | null {
    if (q.blocking) return { label: 'Bloquante', color: 'var(--ck-signal-neg)' };
    const p = this.priorityOf(q);
    const high = p > 1 ? p >= 2 : p >= 0.7;
    return high ? { label: 'Priorité haute', color: 'var(--ck-signal-warn)' } : null;
  }

  protected questionText(q: ProposalOpenQuestion): string {
    return String(
      (q as Record<string, unknown>)['text'] || q.follow_up || q.reason || q.gap_id || 'Question ouverte',
    ).trim();
  }
  protected questionId(q: ProposalOpenQuestion): string {
    return String(q.question_id ?? q.id ?? '').trim();
  }
  protected questionStatus(q: ProposalOpenQuestion): string {
    return String(q.status ?? 'open').toLowerCase();
  }
  protected isResolved(q: ProposalOpenQuestion): boolean {
    return ['answered', 'invalid', 'dismissed'].includes(this.questionStatus(q));
  }
  protected questionStatusLabel(q: ProposalOpenQuestion): string {
    const s = this.questionStatus(q);
    if (s === 'answered') return 'Répondue';
    if (s === 'invalid' || s === 'dismissed') return 'Invalide';
    if (s === 'deferred') return 'Différée';
    return 'Ouverte';
  }
  protected questionStatusColor(q: ProposalOpenQuestion): string {
    const s = this.questionStatus(q);
    if (s === 'answered') return 'var(--ck-signal-pos)';
    if (s === 'invalid' || s === 'dismissed') return 'var(--ck-fg-4)';
    if (s === 'deferred') return 'var(--ck-signal-cool)';
    return 'var(--ck-signal-warn)';
  }

  protected answer(q: ProposalOpenQuestion, text: string): void {
    const id = this.questionId(q);
    const value = text.trim();
    if (!id || !value) return;
    void this.engine.answerOpenQuestion(id, value);
  }
  protected defer(q: ProposalOpenQuestion): void {
    void this.engine.patchOpenQuestions([
      { question_id: this.questionId(q) || null, question_text: this.questionText(q), status: 'deferred' },
    ]);
  }
  protected invalidate(q: ProposalOpenQuestion): void {
    void this.engine.patchOpenQuestions([
      { question_id: this.questionId(q) || null, question_text: this.questionText(q), status: 'invalid' },
    ]);
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
    // Same fallback chain as La Scène: anchor-carried collection first, then
    // the matched session document, then the session-level collection slug —
    // otherwise resumed/review sessions show the placeholder instead of the doc.
    const refAny = ref as { collection?: string | null; collection_name?: string | null };
    const collection =
      refAny.collection ??
      refAny.collection_name ??
      doc?.collection ??
      doc?.collection_name ??
      this.engine.documentsCollection();
    if (!documentId || !collection) return null;
    let url = `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview?collection_name=${encodeURIComponent(collection)}`;
    const filename = ref.filename ?? doc?.filename;
    if (filename) url += `&filename=${encodeURIComponent(filename)}`;
    return url;
  }

  /** Passage to highlight inside the (inline or modal) preview for a source. */
  protected highlightFor(ref: CaptureViewReference): string | null {
    const statement = this.statementOf(ref);
    return statement && statement.length >= 8 ? statement : null;
  }

  protected openPreview(url: string, ref: CaptureViewReference): void {
    this.previewUrl.set(url);
    this.previewTitle.set(viewTitle(ref));
    this.previewPage.set(ref.page ?? null);
    this.previewHighlight.set(this.highlightFor(ref));
    this.previewOpen.set(true);
  }
}
