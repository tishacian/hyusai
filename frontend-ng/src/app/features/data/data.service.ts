/**
 * Data plane client: datasets, their profiles and their in-flight preparation.
 *
 * An ingest is a Celery task of a few seconds, so the list and detail surfaces
 * poll while any row is unsettled and stop the moment everything is terminal —
 * the same posture as the recipe execution watcher. What they poll for is not
 * just a status: `status_detail` carries the readable step the worker is on, so
 * the UI shows "Profiling 42 columns" instead of a mute spinner.
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import type {
  TabularColumn,
  TabularColumnStats,
  TabularRow,
} from '@app/shared/ui/data-table.vm';
import {
  isActiveStatus,
  type DatasetLineage,
  type DatasetSource,
  type DatasetStatus,
} from './data.vm';

export type { DatasetLineage, DatasetSource, DatasetStatus };

export interface DatasetDto {
  id: string;
  name: string;
  slug: string;
  version: number;
  description?: string | null;
  source: DatasetSource;
  status: DatasetStatus;
  status_detail?: string | null;
  error?: string | null;
  row_count?: number | null;
  column_count?: number | null;
  size_bytes?: number | null;
  schema: TabularColumn[];
  original_filename?: string | null;
  run_id?: string | null;
  node_id?: string | null;
  /** The System whose run produced the row; null for a hand upload. */
  system_id?: string | null;
  parent_ids: string[];
  produced_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  ingested_at?: string | null;
  ingest_duration_ms?: number | null;
  /** Detail-only blocks. */
  preview?: TabularRow[];
  stats?: Record<string, TabularColumnStats>;
  /** How a produced dataset was produced — the model, the engine, the extras. */
  lineage?: DatasetLineage;
}

export interface DatasetFeature {
  enabled: boolean;
  upload_max_bytes: number;
}

export interface DatasetDetailDto {
  dataset: DatasetDto;
  lineage: { parents: DatasetDto[]; children: DatasetDto[] };
  versions: DatasetDto[];
  feature: DatasetFeature;
  /** Systems and models that consume this dataset (L20b « Utilisé par »). */
  used_by?: {
    models: Array<{
      id: string;
      name: string;
      slug: string;
      version: number;
      target?: string | null;
      is_champion: boolean;
      status: string;
    }>;
    systems: Array<{ id: string; name: string }>;
  };
}

/** A window of rows read from the Parquet, past the ones cached at ingest. */
export interface DatasetPageDto {
  dataset_id: string;
  schema: TabularColumn[];
  rows: TabularRow[];
  offset: number;
  limit: number;
  total: number;
}

export function isDatasetActive(dataset: DatasetDto | null | undefined): boolean {
  return isActiveStatus(dataset?.status);
}

@Injectable({ providedIn: 'root' })
export class DataService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/v1/datasets';

  readonly datasets = signal<DatasetDto[]>([]);
  readonly loading = signal(false);
  readonly feature = signal<DatasetFeature>({
    enabled: true,
    upload_max_bytes: 256 * 1024 * 1024,
  });

  /** True while any dataset is still being prepared: drives the poll loop. */
  readonly hasActive = computed(() => this.datasets().some(isDatasetActive));

  async refresh(): Promise<DatasetDto[]> {
    this.loading.set(true);
    try {
      const response = await firstValueFrom(
        this.http.get<{ datasets: DatasetDto[]; feature: DatasetFeature }>(this.base),
      );
      this.datasets.set(response.datasets ?? []);
      if (response.feature) this.feature.set(response.feature);
      return this.datasets();
    } finally {
      this.loading.set(false);
    }
  }

  async upload(file: File, name?: string): Promise<DatasetDto> {
    const form = new FormData();
    form.append('file', file, file.name);
    if (name?.trim()) form.append('name', name.trim());
    const response = await firstValueFrom(
      this.http.post<{ dataset: DatasetDto; queued: boolean }>(
        `${this.base}/upload`,
        form,
      ),
    );
    // Optimistic insert so the row (and its progress) shows up immediately.
    this.datasets.update((rows) => [response.dataset, ...rows]);
    return response.dataset;
  }

  detail(datasetId: string): Promise<DatasetDetailDto> {
    return firstValueFrom(
      this.http.get<DatasetDetailDto>(`${this.base}/${datasetId}`),
    );
  }

  /**
   * A window of rows, read from the Parquet rather than from the ingest cache.
   *
   * The detail response already carries the first fifty rows, which is what
   * opens the page without a second request. This is the answer to "show me
   * more": every dataset here is immutable, so row 8 400 is a fact that exists
   * and simply is not in that cache.
   */
  preview(
    datasetId: string,
    options: { offset?: number; limit?: number } = {},
  ): Promise<DatasetPageDto> {
    const params: Record<string, string> = {};
    if (options.offset) params['offset'] = String(options.offset);
    if (options.limit) params['limit'] = String(options.limit);
    return firstValueFrom(
      this.http.get<DatasetPageDto>(`${this.base}/${datasetId}/preview`, { params }),
    );
  }

  reingest(datasetId: string): Promise<{ dataset: DatasetDto }> {
    return firstValueFrom(
      this.http.post<{ dataset: DatasetDto }>(`${this.base}/${datasetId}/reingest`, {}),
    );
  }

  async remove(datasetId: string): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.base}/${datasetId}`));
    this.datasets.update((rows) => rows.filter((row) => row.id !== datasetId));
  }
}
