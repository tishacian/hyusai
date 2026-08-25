/**
 * Data (Build > Data) — dataset list and import surface.
 *
 * Two things make this page carry a demo rather than merely work:
 *
 * - the dropzone is the primary element, not a hidden button, because the first
 *   beat of the story is "here is your CSV";
 * - a dataset being prepared shows the worker's actual step (`status_detail`)
 *   with a live pulse, so the seconds between drop and ready read as progress.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { formatBytes } from '@app/shared/ui/data-table.vm';
import { DataService, isDatasetActive, type DatasetDto } from './data.service';
import { ingestStepKey, sourceIcon, type DatasetSource } from './data.vm';

const POLL_INTERVAL_MS = 1500;

type OriginFilter = 'all' | DatasetSource;

@Component({
  selector: 'app-data-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="i18n.t('data.eyebrow')"
      [title]="i18n.t('data.title')"
      [subtitle]="i18n.t('data.subtitle')"
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
        (click)="reload()"
        [disabled]="data.loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="data.loading()" />
        {{ i18n.t('data.list.refresh') }}
      </button>
    </ck-object-header>

    <div
      class="ck-drop rounded-md p-7 text-center mb-4 cursor-pointer"
      [class.ck-drop--active]="dragging()"
      (dragover)="onDragOver($event)"
      (dragleave)="onDragLeave($event)"
      (drop)="onDrop($event)"
      (click)="picker.click()"
    >
      <input
        #picker
        type="file"
        class="hidden"
        accept=".csv,.tsv,.txt,.parquet,.json,.jsonl,.ndjson,.xlsx,.xlsm"
        (change)="onPicked($event)"
      />
      <div class="flex flex-col items-center gap-1.5">
        <app-icon name="upload-cloud" [size]="26" class="ck-drop__icon" />
        <div class="text-sm font-medium" style="color: var(--ck-fg-1)">
          {{ i18n.t('data.upload.dropzone.title') }}
        </div>
        <div class="text-[11px] ck-mono" style="color: var(--ck-fg-4)">
          {{ i18n.t('data.upload.dropzone.hint', { size: uploadLimit() }) }}
        </div>
      </div>
      @if (uploadingName()) {
        <div class="mt-3 inline-flex items-center gap-2 text-[11px] ck-mono" style="color: var(--ck-signal-cool)">
          <app-icon name="loader-2" [size]="13" class="animate-spin" />
          {{ i18n.t('data.upload.sending', { name: uploadingName()! }) }}
        </div>
      }
    </div>

    <div class="flex items-center gap-1.5 mb-3 flex-wrap">
      @for (option of originFilters; track option.key) {
        <button
          type="button"
          class="ck-chip"
          [class.ck-chip--on]="origin() === option.key"
          (click)="origin.set(option.key)"
        >
          {{ i18n.t(option.label) }}
        </button>
      }
    </div>

    @if (data.loading() && !data.datasets().length) {
      <div class="space-y-2">
        @for (_ of [0, 1, 2]; track $index) {
          <div class="ck-surface rounded-md p-5 animate-pulse">
            <div class="h-3 w-56 rounded" style="background: rgba(255,255,255,0.05)"></div>
          </div>
        }
      </div>
    } @else if (!visible().length) {
      <app-empty-state
        icon="table"
        [title]="i18n.t('data.list.empty.title')"
        [description]="i18n.t('data.list.empty.description')"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
          (click)="picker.click()"
        >
          <app-icon name="upload" [size]="14" /> {{ i18n.t('data.list.import') }}
        </button>
      </app-empty-state>
    } @else {
      <ul class="space-y-2">
        @for (row of visible(); track row.id) {
          <li>
            <a
              [routerLink]="['/data', row.id]"
              class="flex items-center gap-3 ck-surface rounded-md px-4 py-3 transition group ck-row"
            >
              <div class="ck-icon-tile" [class.ck-icon-tile--warn]="row.status === 'failed'">
                <app-icon [name]="sourceIcon(row.source)" [size]="16" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-sm font-medium truncate" style="color: var(--ck-fg-1)">
                    {{ row.name }}
                  </span>
                  <span class="ck-badge ck-mono">{{
                    i18n.t('data.versions.label', { version: row.version })
                  }}</span>
                  <span class="ck-badge ck-mono">{{
                    i18n.t('data.source.' + row.source)
                  }}</span>
                  @if (row.status !== 'ready') {
                    <span
                      class="ck-badge ck-mono"
                      [class.ck-badge--warn]="row.status === 'failed'"
                      [class.ck-badge--live]="isActive(row)"
                    >
                      {{ i18n.t('data.status.' + row.status) }}
                    </span>
                  }
                </div>
                @if (isActive(row)) {
                  <div class="text-[11px] ck-mono mt-1 flex items-center gap-1.5" style="color: var(--ck-signal-cool)">
                    <span class="ck-pulse"></span>
                    {{ i18n.t(stepKey(row.status_detail)) }}
                  </div>
                } @else if (row.status === 'failed') {
                  <div class="text-[11px] ck-mono mt-1" style="color: var(--ck-signal-neg)">
                    {{ row.error }}
                  </div>
                } @else {
                  <div class="text-[11px] ck-mono mt-1" style="color: var(--ck-fg-4)">
                    {{
                      i18n.t('data.list.meta', {
                        rows: (row.row_count ?? 0).toLocaleString(i18n.locale()),
                        columns: row.column_count ?? 0,
                        size: bytes(row.size_bytes)
                      })
                    }}
                  </div>
                }
              </div>
              <app-icon
                name="chevron-right"
                [size]="14"
                class="shrink-0 transition"
                style="color: var(--ck-fg-4)"
              />
            </a>
          </li>
        }
      </ul>
    }
  `,
  styles: [
    `
      .ck-drop {
        border: 1px dashed var(--ck-stroke-2, rgba(255, 255, 255, 0.1));
        background: transparent;
        transition:
          border-color var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease),
          background var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-drop:hover,
      .ck-drop--active {
        border-color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.06);
      }
      .ck-drop__icon {
        color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-row:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.04));
      }
      .ck-icon-tile {
        width: 36px;
        height: 36px;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.12);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.25);
      }
      .ck-icon-tile--warn {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.12);
        box-shadow: inset 0 0 0 1px rgba(239, 90, 111, 0.25);
      }
      .ck-badge {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 5px;
        border-radius: 3px;
        color: var(--ck-fg-4, #8891a0);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
      }
      .ck-badge--warn {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.08);
      }
      .ck-badge--live {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      /* A dataset being prepared must look alive, not stalled. */
      .ck-pulse {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--ck-signal-cool, #7dd3fc);
        animation: ck-pulse 1.4s ease-in-out infinite;
      }
      @keyframes ck-pulse {
        0%,
        100% {
          opacity: 0.35;
          transform: scale(0.85);
        }
        50% {
          opacity: 1;
          transform: scale(1.15);
        }
      }
      .ck-chip {
        font-size: 11px;
        padding: 4px 9px;
        border-radius: 999px;
        color: var(--ck-fg-3, #a6aebc);
        background: transparent;
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-chip:hover {
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-chip--on {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.35);
      }
    `,
  ],
})
export class DataListComponent implements OnInit {
  readonly i18n = inject(I18nService);
  protected readonly data = inject(DataService);
  private readonly toast = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly dragging = signal(false);
  protected readonly uploadingName = signal<string | null>(null);
  protected readonly origin = signal<OriginFilter>('all');

  protected readonly originFilters: { key: OriginFilter; label: string }[] = [
    { key: 'all', label: 'data.list.filter.all' },
    { key: 'upload', label: 'data.list.filter.upload' },
    { key: 'transform', label: 'data.list.filter.transform' },
    { key: 'score', label: 'data.list.filter.score' },
  ];

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  protected readonly visible = computed(() => {
    const origin = this.origin();
    const rows = this.data.datasets();
    return origin === 'all' ? rows : rows.filter((row) => row.source === origin);
  });

  protected readonly kpis = computed<CkObjectKpi[]>(() => {
    const rows = this.data.datasets();
    const ready = rows.filter((row) => row.status === 'ready');
    const totalRows = ready.reduce((sum, row) => sum + (row.row_count ?? 0), 0);
    const totalBytes = ready.reduce((sum, row) => sum + (row.size_bytes ?? 0), 0);
    return [
      {
        label: this.i18n.t('data.kpi.datasets'),
        value: String(rows.length),
        tone: 'cool',
      },
      {
        label: this.i18n.t('data.kpi.rows'),
        value: totalRows.toLocaleString(this.i18n.locale()),
      },
      { label: this.i18n.t('data.kpi.size'), value: this.bytes(totalBytes) },
    ];
  });

  ngOnInit(): void {
    void this.reload();
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  protected async reload(): Promise<void> {
    await this.data.refresh();
    this.syncPolling();
  }

  protected isActive(dataset: DatasetDto): boolean {
    return isDatasetActive(dataset);
  }

  /** The worker names its step as a code; the locale supplies the sentence. */
  protected stepKey(detail: string | null | undefined): string {
    return ingestStepKey(detail);
  }

  protected bytes(value: number | null | undefined): string {
    return formatBytes(value, this.i18n.locale());
  }

  protected uploadLimit(): string {
    return this.bytes(this.data.feature().upload_max_bytes);
  }

  protected sourceIcon(source: DatasetSource): string {
    return sourceIcon(source);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) void this.send(file);
  }

  protected onPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) void this.send(file);
    input.value = '';
  }

  private async send(file: File): Promise<void> {
    this.uploadingName.set(file.name);
    try {
      const dataset = await this.data.upload(file);
      if (dataset.status === 'ready') {
        this.toast.success(
          this.i18n.t('data.upload.done', {
            name: dataset.name,
            rows: (dataset.row_count ?? 0).toLocaleString(this.i18n.locale()),
          }),
        );
      } else {
        this.toast.info(this.i18n.t('data.upload.queued', { name: dataset.name }));
      }
      this.syncPolling();
    } catch {
      this.toast.error(this.i18n.t('data.upload.failed', { name: file.name }));
    } finally {
      this.uploadingName.set(null);
    }
  }

  /** Poll only while something is unsettled, and stop as soon as it settles. */
  private syncPolling(): void {
    if (this.data.hasActive()) {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(() => {
        void this.data.refresh().then(() => {
          if (!this.data.hasActive()) this.stopPolling();
        });
      }, POLL_INTERVAL_MS);
    } else {
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}
