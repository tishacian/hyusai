/**
 * `<ck-dataset-preview>` — a dataset's rows, wherever a surface needs to see them.
 *
 * The dataset detail page reads its first window off the detail response, which
 * the ingest worker already folded into the row. Every other surface has only a
 * dataset id: the training studio, which is about to fit on a table its author
 * has never looked at, and a settled transform or score node, whose whole output
 * is a table nobody has opened yet.
 *
 * So this fetches — `GET /datasets/{id}/preview`, the paged read of the Parquet
 * — and renders through the one shared `ck-data-table`, which is what makes a
 * preview look the same on the canvas as it does on the Data page. Nothing is
 * fetched until an id arrives, and nothing is re-fetched when the same id
 * arrives twice: a node re-selected on the canvas must not re-read the file.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import type {
  TabularColumn,
  TabularColumnStats,
  TabularRow,
} from '@app/shared/ui/data-table.vm';
import { DataService } from './data.service';

/** Rows per window — the same size the ingest cache holds. */
const PAGE_SIZE = 25;

@Component({
  selector: 'ck-dataset-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, DataTableComponent],
  template: `
    @if (failed()) {
      <p class="ck-dsp__note" role="alert" data-testid="dataset-preview-failed">
        <app-icon name="alert-triangle" [size]="12" />
        {{ i18n.t('data.preview.failed') }}
      </p>
    } @else if (!datasetId()) {
      <p class="ck-dsp__note">{{ i18n.t('data.preview.none') }}</p>
    } @else {
      <ck-data-table
        [columns]="columns()"
        [rows]="rows()"
        [stats]="stats()"
        [rowCount]="total()"
        [caption]="caption()"
        [maxHeight]="maxHeight()"
        [emptyLabel]="loading() ? i18n.t('data.preview.loading') : ''"
      >
        <span caption-actions class="ck-dsp__pager">
          @if (loading()) {
            <app-icon name="loader-2" [size]="12" class="animate-spin" />
          }
          <button
            type="button"
            class="ck-dsp__step"
            data-testid="dataset-preview-prev"
            [disabled]="!canPrev() || loading()"
            [attr.aria-label]="i18n.t('data.detail.preview.prev')"
            [title]="i18n.t('data.detail.preview.prev')"
            (click)="page(-1)"
          >
            <app-icon name="chevron-left" [size]="13" />
          </button>
          <button
            type="button"
            class="ck-dsp__step"
            data-testid="dataset-preview-next"
            [disabled]="!canNext() || loading()"
            [attr.aria-label]="i18n.t('data.detail.preview.next')"
            [title]="i18n.t('data.detail.preview.next')"
            (click)="page(1)"
          >
            <app-icon name="chevron-right" [size]="13" />
          </button>
        </span>
      </ck-data-table>
    }
  `,
  styles: [
    `
      .ck-dsp__note {
        display: flex;
        align-items: center;
        gap: 5px;
        font-size: 11.5px;
        color: var(--ck-fg-4, #8891a0);
        margin: 0;
      }
      .ck-dsp__pager {
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }
      .ck-dsp__step {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 4px;
        color: var(--ck-fg-3, #9aa4b2);
        background: var(--ck-bg-inset, rgba(255, 255, 255, 0.04));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-dsp__step:hover:not(:disabled) {
        color: var(--ck-signal-cool, #7dd3fc);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.35);
      }
      .ck-dsp__step:disabled {
        opacity: 0.35;
        cursor: default;
      }
    `,
  ],
})
export class DatasetPreviewComponent {
  protected readonly i18n = inject(I18nService);
  private readonly data = inject(DataService);

  readonly datasetId = input<string | null>(null);
  /**
   * Columns and profile from the caller, when it already has them.
   *
   * The training studio does: its column catalogue is the same schema, with the
   * histograms the picker draws. Passing them keeps the sparklines on the table
   * header identical to the ones on the chips beside it, and saves a read.
   */
  readonly columnsHint = input<TabularColumn[]>([]);
  readonly statsHint = input<Record<string, TabularColumnStats> | null>(null);
  readonly maxHeight = input<string>('260px');

  protected readonly rows = signal<TabularRow[]>([]);
  protected readonly fetchedColumns = signal<TabularColumn[]>([]);
  protected readonly total = signal<number | null>(null);
  protected readonly offset = signal(0);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);

  /** The id the rows on screen belong to — guards a re-read of the same table. */
  private loaded: string | null = null;

  protected readonly columns = computed<TabularColumn[]>(() => {
    const hint = this.columnsHint();
    return hint.length ? hint : this.fetchedColumns();
  });
  protected readonly stats = computed(() => this.statsHint());

  protected readonly canPrev = computed(() => this.offset() > 0);
  protected readonly canNext = computed(() => {
    const total = this.total();
    if (total === null) return false;
    return this.offset() + this.rows().length < total;
  });

  constructor() {
    effect(() => {
      const id = this.datasetId();
      if (!id) {
        this.reset();
        return;
      }
      if (id === this.loaded) return;
      this.loaded = id;
      void this.fetch(id, 0);
    });
  }

  protected caption(): string {
    if (!this.rows().length) return '';
    const locale = this.i18n.locale();
    return this.i18n.t('data.detail.preview.caption', {
      from: (this.offset() + 1).toLocaleString(locale),
      to: (this.offset() + this.rows().length).toLocaleString(locale),
    });
  }

  protected async page(step: number): Promise<void> {
    const id = this.datasetId();
    if (!id || this.loading()) return;
    const size = this.rows().length || PAGE_SIZE;
    const next = Math.max(0, this.offset() + step * size);
    if (next === this.offset()) return;
    await this.fetch(id, next);
  }

  private async fetch(id: string, offset: number): Promise<void> {
    this.loading.set(true);
    this.failed.set(false);
    try {
      const page = await this.data.preview(id, { offset, limit: PAGE_SIZE });
      // A window past the end is not an answer to replace the one on screen.
      if (!page.rows.length && offset > 0) return;
      this.rows.set(page.rows);
      this.offset.set(page.offset);
      this.total.set(page.total);
      this.fetchedColumns.set(page.schema ?? []);
    } catch {
      this.failed.set(true);
      this.rows.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  private reset(): void {
    this.loaded = null;
    this.rows.set([]);
    this.fetchedColumns.set([]);
    this.total.set(null);
    this.offset.set(0);
    this.failed.set(false);
  }
}
