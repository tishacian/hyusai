import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { CaptureEngine } from '../capture-engine';
import { composePublicationName } from '../capture-templates';

interface CategoryOption {
  id: string;
  labelKey: string;
}

const CUSTOM_DESTINATION = '__custom__';

/**
 * Publication surface (Option A) — the REAL knowledge-base publication step.
 * Comes after Finalisation (report generation) and Revue (fiche acceptance):
 * the expert picks a final title, a category and a destination collection, then
 * pushes the accepted fiche to the KB via {@link CaptureEngine.publish}. On
 * success it surfaces the export link; on failure it surfaces the engine error
 * with a retry. Returning to the dashboard is delegated to the shell via
 * {@link done}.
 */
@Component({
  selector: 'app-capture-fil-publish',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, DocumentPreviewComponent],
  template: `
    <div style="display:flex; flex-direction:column; gap:18px; max-width:720px;">
      <div>
        <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
          Capture · Publication
        </span>
        <h2 style="margin:6px 0 4px; font-size:22px; font-weight:680; color:var(--ck-fg-1);">
          {{ i18n.t('capture.publish.cta') }}
        </h2>
        <p style="margin:0; font-size:13.5px; color:var(--ck-fg-3); line-height:1.55; max-width:62ch;">
          @if (engine.template(); as tpl) {
            {{
              i18n.t('capture.publish.template_intro', {
                subject: templateSubject(),
                collection: tpl.publication.collection,
                sourceType: tpl.publication.source_type,
              })
            }}
          } @else {
            {{ i18n.t('capture.publish.intro') }}
          }
        </p>
      </div>

      @if (published()) {
        <div
          class="ck-surface"
          style="border-radius:var(--ck-radius-lg); padding:32px 28px; display:flex; flex-direction:column; align-items:center; gap:14px; text-align:center;"
        >
          <ck-glyph name="check" [size]="26" color="var(--ck-signal-pos)" />
          <div style="font-size:16px; font-weight:600; color:var(--ck-fg-1);">{{ i18n.t('capture.publish.published') }}</div>
          <div style="font-size:13px; color:var(--ck-fg-4); max-width:48ch; line-height:1.5;">
            {{ i18n.t('capture.publish.published_body', { title: published()?.final_title || finalTitle() }) }}
            @if (published()?.destination_scope) {
              <span> · collection <strong>{{ published()?.destination_scope }}</strong></span>
            }
            .
          </div>
          @if (previewUrl()) {
            <button
              type="button"
              (click)="previewOpen.set(true)"
              style="display:inline-flex; align-items:center; gap:7px; font-size:13px; color:var(--ck-signal-cool); border:0; background:transparent; cursor:pointer;"
            >
              <ck-glyph name="zoom-in" [size]="14" color="currentColor" /> {{ i18n.t('capture.publish.open') }}
            </button>
          }
          @if (engine.proposalId()) {
            <div style="display:flex; gap:10px; flex-wrap:wrap; justify-content:center; margin-top:4px;">
              <button
                type="button"
                (click)="downloadExport('pdf')"
                [disabled]="exportBusy()"
                style="display:inline-flex; align-items:center; gap:7px; padding:8px 14px; border-radius:var(--ck-radius-md); border:1px solid color-mix(in oklab, var(--ck-signal-cool) 45%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 10%, transparent); color:var(--ck-signal-cool); font-size:13px; font-weight:600; cursor:pointer;"
              >
                <ck-glyph name="ledger" [size]="13" color="currentColor" />
                {{ exportBusy() === 'pdf' ? i18n.t('capture.publish.exporting_pdf') : i18n.t('capture.publish.export_pdf') }}
              </button>
              <button
                type="button"
                (click)="downloadExport('docx')"
                [disabled]="exportBusy()"
                style="display:inline-flex; align-items:center; gap:7px; padding:8px 14px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:13px; font-weight:600; cursor:pointer;"
              >
                <ck-glyph name="ledger" [size]="13" color="currentColor" />
                {{ exportBusy() === 'docx' ? i18n.t('capture.publish.exporting_docx') : i18n.t('capture.publish.export_docx') }}
              </button>
            </div>
            @if (exportError()) {
              <div style="font-size:12px; color:var(--ck-signal-neg);">{{ exportError() }}</div>
            }
          }
          <button
            type="button"
            (click)="done.emit()"
            style="display:inline-flex; align-items:center; gap:7px; padding:10px 16px; margin-top:6px; border-radius:var(--ck-radius-md); border:none; font-size:14px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal); cursor:pointer;"
          >
            <ck-glyph name="arrow-right" [size]="14" color="currentColor" /> {{ i18n.t('capture.publish.back_dashboard') }}
          </button>
        </div>
      } @else {
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:20px; display:flex; flex-direction:column; gap:16px;">
          <label style="display:flex; flex-direction:column; gap:6px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">{{ i18n.t('capture.publish.final_title') }}</span>
            <input
              [value]="finalTitle()"
              (input)="finalTitle.set($any($event.target).value)"
              [placeholder]="i18n.t('capture.publish.final_title_placeholder')"
              style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
            />
            @if (publicationNamePreview(); as pubName) {
              <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-4);">
                Convention EX70 · {{ pubName }}
                <button
                  type="button"
                  (click)="finalTitle.set(pubName)"
                  style="margin-left:8px; border:none; background:transparent; color:var(--ck-signal-cool); cursor:pointer; font-size:11px; padding:0;"
                >
                  {{ i18n.t('capture.publish.use') }}
                </button>
              </span>
            }
          </label>

          <label style="display:flex; flex-direction:column; gap:6px; max-width:320px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">{{ i18n.t('capture.publish.category') }}</span>
            <select
              [value]="category()"
              (change)="category.set($any($event.target).value)"
              style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
            >
              @for (c of categories; track c.id) {
                <option [value]="c.id">{{ i18n.t(c.labelKey) }}</option>
              }
            </select>
          </label>

          <div style="display:flex; flex-direction:column; gap:6px; max-width:420px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">{{ i18n.t('capture.publish.destination') }}</span>
            <div style="display:flex; align-items:center; gap:8px;">
              <ck-glyph name="layers" [size]="14" color="var(--ck-fg-4)" />
              <select
                [value]="destination()"
                (change)="destination.set($any($event.target).value)"
                style="flex:1; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
              >
                @for (col of destinationOptions(); track col) {
                  <option [value]="col">{{ col }}</option>
                }
                <option [value]="custom">{{ i18n.t('capture.publish.custom') }}</option>
              </select>
            </div>
            @if (destination() === custom) {
              <input
                [value]="customDestination()"
                (input)="customDestination.set($any($event.target).value)"
                [placeholder]="i18n.t('capture.publish.custom_placeholder')"
                style="margin-top:4px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-mono); font-size:13.5px; padding:9px 12px;"
              />
            }
          </div>

          <label style="display:flex; align-items:center; gap:9px; cursor:pointer;">
            <input
              type="checkbox"
              [checked]="includeUnresolved()"
              (change)="includeUnresolved.set($any($event.target).checked)"
            />
            <span style="font-size:13px; color:var(--ck-fg-2);">{{ i18n.t('capture.publish.include_unresolved') }}</span>
          </label>
        </div>

        @if (engine.lastError()) {
          <div style="display:flex; align-items:center; gap:8px; color:var(--ck-signal-neg); font-size:12.5px;">
            <ck-glyph name="warn" [size]="14" color="currentColor" /> {{ engine.lastError() }}
            <button
              type="button"
              (click)="submit()"
              style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-2); border-radius:var(--ck-radius-sm); padding:4px 10px; cursor:pointer; font-size:12px;"
            >
              {{ i18n.t('capture.retry') }}
            </button>
          </div>
        }

        <div style="display:flex; align-items:center; gap:14px;">
          <button
            type="button"
            (click)="submit()"
            [disabled]="!canSubmit() || busy()"
            style="display:inline-flex; align-items:center; gap:7px; padding:11px 18px; border-radius:var(--ck-radius-md); border:none; font-size:14px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
            [style.opacity]="!canSubmit() || busy() ? 0.5 : 1"
            [style.cursor]="!canSubmit() || busy() ? 'not-allowed' : 'pointer'"
          >
            <ck-glyph name="bolt" [size]="14" color="currentColor" />
            {{ busy() ? i18n.t('capture.publish.publishing') : i18n.t('capture.publish.cta') }}
          </button>
        </div>
      }
    </div>
    <app-document-preview
      [open]="previewOpen() && !!published()"
      [previewUrl]="previewUrl()"
      [title]="published()?.final_title || finalTitle()"
      [subtitle]="published()?.collection || ''"
      (closed)="previewOpen.set(false)"
    />
  `,
})
export class CaptureFilPublishComponent {
  readonly i18n = inject(I18nService);

  protected readonly engine = inject(CaptureEngine);
  private readonly api = inject(ApiService);

  /** Emitted once publication succeeds — the shell returns to the dashboard. */
  @Output() done = new EventEmitter<void>();

  protected readonly custom = CUSTOM_DESTINATION;

  protected readonly categories: CategoryOption[] = [
    { id: 'technique', labelKey: 'capture.publish.category.technique' },
    { id: 'commercial', labelKey: 'capture.publish.category.commercial' },
    { id: 'processus', labelKey: 'capture.publish.category.processus' },
    { id: 'securite', labelKey: 'capture.publish.category.securite' },
    { id: 'autre', labelKey: 'capture.publish.category.autre' },
  ];

  /**
   * What is being published, as one interpolated value: the template label,
   * qualified by the intervention type and its document reference when the
   * session carries one. Assembling it here keeps the intro a single sentence
   * in the dictionary instead of a chain of translated fragments.
   */
  protected readonly templateSubject = computed(() => {
    const label = this.engine.template()?.label ?? '';
    const type = this.engine.interventionType();
    return type ? `${label} · ${type.label} (${type.doc_ref})` : label;
  });

  protected readonly publicationNamePreview = computed(() => {
    if (!this.engine.template()) return '';
    return composePublicationName(this.engine.headerFields());
  });

  protected readonly finalTitle = signal(
    (() => {
      const suggested = this.engine.template()
        ? composePublicationName(this.engine.headerFields())
        : '';
      return (
        suggested
        || this.engine.proposal()?.proposal?.title
        || this.engine.session()?.title
        || ''
      );
    })(),
  );
  protected readonly category = signal('technique');
  /**
   * Preselect backend-suggested destination (`proposal.publication`, from
   * template defaults / `_apply_publication_defaults`), else template.collection.
   * The user can still pick any collection.
   */
  protected readonly destination = signal(
    (
      this.engine.proposal()?.proposal?.publication?.destination
      || this.engine.proposal()?.proposal?.publication?.destination_scope
      || this.engine.template()?.publication.collection
      || ''
    ).trim(),
  );
  protected readonly customDestination = signal('');
  protected readonly includeUnresolved = signal(true);
  protected readonly busy = signal(false);
  protected readonly exportBusy = signal<'pdf' | 'docx' | null>(null);
  protected readonly exportError = signal<string | null>(null);

  protected readonly published = this.engine.publication;

  protected readonly previewOpen = signal(false);
  protected readonly previewUrl = computed(() => this.published()?.export_urls?.preview_url || null);

  /** Loaded collections, with the preselected default prepended when unlisted. */
  protected readonly destinationOptions = computed(() => {
    const cols = this.engine.collections();
    const dest = this.destination();
    return dest && dest !== CUSTOM_DESTINATION && !cols.includes(dest) ? [dest, ...cols] : cols;
  });

  protected readonly chosenDestination = computed(() => {
    const dest = this.destination();
    return dest === CUSTOM_DESTINATION ? this.customDestination().trim() : dest.trim();
  });

  protected readonly canSubmit = computed(
    () => this.finalTitle().trim().length > 0 && this.chosenDestination().length > 0,
  );

  constructor() {
    void this.engine.loadCollections();
  }

  protected async submit(): Promise<void> {
    if (!this.canSubmit() || this.busy()) return;
    this.busy.set(true);
    await this.engine.publish({
      category: this.category(),
      destination_scope: this.chosenDestination(),
      final_title: this.finalTitle().trim(),
      include_unresolved_questions: this.includeUnresolved(),
    });
    this.busy.set(false);
  }

  protected async downloadExport(format: 'pdf' | 'docx'): Promise<void> {
    const proposalId = this.engine.proposalId();
    if (!proposalId || this.exportBusy()) return;
    this.exportBusy.set(format);
    this.exportError.set(null);
    try {
      const blob = await firstValueFrom(this.api.downloadCaptureProposalExport(proposalId, format));
      const stem =
        this.published()?.final_title?.trim()
        || this.finalTitle().trim()
        || 'rapport-fse';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${stem}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      this.exportError.set(
        this.i18n.t('capture.publish.export_failed', { format: format.toUpperCase() }),
      );
    } finally {
      this.exportBusy.set(null);
    }
  }
}
