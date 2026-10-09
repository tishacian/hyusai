import type { MonitoringPolicy } from './retraining-evidence.vm';
/**
 * Model plane client: the algorithm catalog, training runs and the registry.
 *
 * A fit is a Celery task of seconds to minutes, so the list and the card poll
 * while any row is unsettled and stop the moment everything is terminal — the
 * same posture as the dataset ingest watcher. `status_detail` carries the step
 * the worker is on ("Fitting HistGradientBoostingClassifier on 48,000 rows"),
 * which is what makes the wait read as work rather than as a spinner.
 *
 * `plan()` is the studio's whole feedback loop: it answers what a choice would
 * imply — the task a target suggests, the features it leaves, the columns that
 * will not generalize — or the coded refusal to render inline, without fitting
 * anything.
 *
 * The serving calls at the bottom talk to the same endpoint a customer's system
 * does, with the session this app already holds instead of an API key. That is
 * deliberate: the Playground cannot drift from the documented request shape,
 * because there is only one shape.
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import type { DatasetDto } from '@app/features/data/data.service';
import {
  isActiveStatus,
  type ApiKeyRow,
  type CodedRefusal,
  type ComparisonDto,
  type ModelCatalog,
  type ModelDto,
  type ModelTask,
  type MonitoringReport,
  type PipelineProvenance,
  type PlanColumn,
  type PredictAnswer,
  type PublishedSkillDto,
  type ServingBlock,
  type TrainingPlan,
  setMetricRegistry,
} from './models.vm';
import type { ForecastAnswer, ForecastRequestBody } from './forecast.vm';
import type { ShadowConfig, ShadowReport } from './shadow-evidence.vm';

export interface ModelListDto {
  models: ModelDto[];
  catalog: ModelCatalog;
}

export interface ModelDetailDto {
  model: ModelDto;
  dataset: DatasetDto | null;
  /** Upload → transform → this version → scored children. Not the v1→v2 chain. */
  provenance: PipelineProvenance | null;
  versions: ModelDto[];
  /**
   * The version the registry's `@challenger` alias names: the best of the
   * lineage that is not serving. Sent by the API rather than derived here, so
   * the badge and the alias cannot disagree.
   */
  challenger_id: string | null;
  catalog: ModelCatalog;
  /** The serving plane: the contract, the keys, the published Skill. */
  serving: ServingBlock;
}

export interface PlanResponseDto {
  dataset: DatasetDto;
  columns: PlanColumn[];
  catalog: ModelCatalog;
  plan: TrainingPlan | null;
  refusal: CodedRefusal | null;
}

export interface TrainRequest {
  dataset_id?: string;
  dataset_slug?: string;
  name?: string;
  description?: string;
  task?: ModelTask;
  target: string;
  features?: string[];
  algo?: string;
  knobs?: Record<string, number>;
  test_size?: number;
  cross_validation?: number;
  /** A family's problem definition (a forecast's date column, horizon, …). */
  spec?: Record<string, unknown>;
}

export const EMPTY_CATALOG: ModelCatalog = {
  enabled: true,
  tasks: ['classification', 'regression'],
  families: [],
  metrics: [],
  algos: [],
  limits: {
    min_rows: 40,
    max_rows: 2_000_000,
    max_features: 256,
    max_classes: 24,
    timeout_s: 900,
  },
  defaults: {
    task: 'classification',
    algo: 'gradient_boosting',
    test_size: 0.25,
    cross_validation: 0,
  },
};

export function isModelActive(model: ModelDto | null | undefined): boolean {
  return isActiveStatus(model?.status);
}

@Injectable({ providedIn: 'root' })
export class ModelsService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/v1/ml-models';

  readonly models = signal<ModelDto[]>([]);
  readonly catalog = signal<ModelCatalog>(EMPTY_CATALOG);
  readonly loading = signal(false);
  /** The journal id the last Playground call received. The monitoring form opens on it. */
  readonly lastPredictionId = signal<string | null>(null);

  /** True while any run is unsettled: drives the poll loop. */
  readonly hasActive = computed(() => this.models().some(isModelActive));

  async refresh(): Promise<ModelDto[]> {
    this.loading.set(true);
    try {
      const response = await firstValueFrom(this.http.get<ModelListDto>(this.base));
      this.models.set(response.models ?? []);
      if (response.catalog) this.adopt(response.catalog);
      return this.models();
    } finally {
      this.loading.set(false);
    }
  }

  /** One catalog for every surface, and the metric directions it carries. */
  private adopt(catalog: ModelCatalog): void {
    setMetricRegistry(catalog.metrics);
    this.catalog.set(catalog);
  }

  async loadCatalog(): Promise<ModelCatalog> {
    const response = await firstValueFrom(
      this.http.get<{ catalog: ModelCatalog }>(`${this.base}/catalog`),
    );
    if (response.catalog) this.adopt(response.catalog);
    return this.catalog();
  }

  /** What a training request would be, without running it. */
  async plan(body: {
    dataset_id?: string;
    dataset_slug?: string;
    target?: string;
    task?: ModelTask;
    features?: string[];
    algo?: string;
    spec?: Record<string, unknown>;
  }): Promise<PlanResponseDto> {
    const response = await firstValueFrom(
      this.http.post<PlanResponseDto>(`${this.base}/plan`, body),
    );
    if (response.catalog) this.adopt(response.catalog);
    return response;
  }

  /** A forecast now, answered by the ml-ts worker (MLflow's invocation shape). */
  forecast(modelId: string, body: ForecastRequestBody & { version?: number }): Promise<ForecastAnswer> {
    return firstValueFrom(this.http.post<ForecastAnswer>(`${this.base}/${modelId}/forecast`, body));
  }

  async train(body: TrainRequest): Promise<ModelDto> {
    const response = await firstValueFrom(
      this.http.post<{ model: ModelDto }>(this.base, body),
    );
    // Optimistic insert so the row (and its progress) shows up immediately.
    this.models.update((rows) => [response.model, ...rows]);
    return response.model;
  }

  async detail(modelId: string): Promise<ModelDetailDto> {
    const response = await firstValueFrom(this.http.get<ModelDetailDto>(`${this.base}/${modelId}`));
    // A card opened from a link has not seen the list's catalog: without its
    // registry, a forecast's sMAPE and coverage would print without their unit.
    if (response.catalog) this.adopt(response.catalog);
    return response;
  }

  /**
   * Re-score two versions over one test split and return skore's joint table.
   *
   * Different in kind from the deltas on the card, which subtract two results
   * that were each measured on their own split. This measures both on the same
   * rows, so the gap is a property of the models.
   */
  comparison(modelId: string, againstId: string): Promise<ComparisonDto> {
    return firstValueFrom(
      this.http.get<ComparisonDto>(`${this.base}/${modelId}/comparison`, {
        params: { against: againstId },
      }),
    );
  }

  async cancel(modelId: string): Promise<ModelDto> {
    const response = await firstValueFrom(
      this.http.post<{ model: ModelDto }>(`${this.base}/${modelId}/cancel`, {}),
    );
    this.replace(response.model);
    return response.model;
  }

  async promote(modelId: string): Promise<{
    model: ModelDto;
    versions: ModelDto[];
    challenger_id: string | null;
  }> {
    const response = await firstValueFrom(
      this.http.post<{
        model: ModelDto;
        versions: ModelDto[];
        challenger_id: string | null;
      }>(`${this.base}/${modelId}/champion`, {}),
    );
    // Promotion moves an alias, so every version of the lineage changed.
    for (const version of response.versions ?? []) this.replace(version);
    return response;
  }

  async remove(modelId: string): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.base}/${modelId}`));
    this.models.update((rows) => rows.filter((row) => row.id !== modelId));
  }

  // -------------------------------------------------------------------------
  // Serving
  // -------------------------------------------------------------------------

  /**
   * Score one row now, in the request.
   *
   * `inputs` rather than `rows` on purpose: it is MLflow's serving key, so the
   * cURL the card offers next to this form is the same request, and neither has
   * to be translated to match the other.
   */
  async predict(
    modelId: string,
    row: Record<string, unknown>,
    options: { explain?: boolean; version?: number; intervalLevel?: number | null } = {},
  ): Promise<PredictAnswer> {
    const answer = await firstValueFrom(
      this.http.post<PredictAnswer>(`${this.base}/${modelId}/predict`, {
        inputs: [row],
        ...(options.explain ? { explain: true } : {}),
        ...(options.version ? { version: options.version } : {}),
        ...(options.intervalLevel != null ? { interval_level: options.intervalLevel } : {}),
      }),
    );
    if (answer.prediction_id) this.lastPredictionId.set(answer.prediction_id);
    return answer;
  }

  monitoring(modelId: string): Promise<MonitoringReport> {
    return firstValueFrom(
      this.http.get<{ monitoring: MonitoringReport }>(`${this.base}/${modelId}/monitoring`),
    ).then((body) => body.monitoring);
  }

  forecastActualDatasets(): Promise<import('../data/data.service').DatasetDto[]> {
    return firstValueFrom(this.http.get<{datasets: import('../data/data.service').DatasetDto[]}>('/api/v1/datasets')).then(body => body.datasets ?? []);
  }

  configureForecastActuals(modelId: string, datasetId: string, followLatest: boolean): Promise<MonitoringReport> {
    return firstValueFrom(this.http.post<{monitoring: MonitoringReport}>(`${this.base}/${modelId}/monitoring/actuals`, {dataset_id: datasetId, follow_latest: followLatest})).then(body => body.monitoring);
  }

  async configureMonitoringPolicy(modelId: string, policy: MonitoringPolicy): Promise<MonitoringReport> {
    const { enabled, propose_retraining, interval_minutes } = policy;
    const result = await firstValueFrom(this.http.post<{monitoring: MonitoringReport}>(`/api/v1/ml-models/${modelId}/monitoring/policy`, { enabled, propose_retraining, interval_minutes }));
    return result.monitoring;
  }

  configureShadow(modelId: string, config: ShadowConfig): Promise<ShadowReport> {
    return firstValueFrom(this.http.post<{ shadow: ShadowReport }>(
      `${this.base}/${modelId}/shadow`,
      { enabled: config.enabled, sample_percent: config.sample_percent, timeout_s: config.timeout_s },
    )).then(body => body.shadow);
  }

  async feedback(
    modelId: string,
    body: { prediction_id: string; label: string },
  ): Promise<{ prediction: { id: string; label: string | null }; monitoring: MonitoringReport }> {
    return firstValueFrom(
      this.http.post<{
        prediction: { id: string; label: string | null };
        monitoring: MonitoringReport;
      }>(`${this.base}/${modelId}/feedback`, body),
    );
  }

  async materializeFeedback(modelId: string): Promise<DatasetDto> {
    const response = await firstValueFrom(
      this.http.post<{ dataset: DatasetDto }>(`${this.base}/${modelId}/feedback/dataset`, {}),
    );
    return response.dataset;
  }

  /** Mint a key. Its secret is in this response and nowhere else, ever. */
  async mintKey(
    modelId: string,
    name: string,
  ): Promise<{ key: ApiKeyRow; serving: ServingBlock }> {
    return firstValueFrom(
      this.http.post<{ key: ApiKeyRow; serving: ServingBlock }>(
        `${this.base}/${modelId}/keys`,
        { name },
      ),
    );
  }

  async revokeKey(modelId: string, keyId: string): Promise<ServingBlock> {
    const response = await firstValueFrom(
      this.http.delete<{ serving: ServingBlock }>(
        `${this.base}/${modelId}/keys/${keyId}`,
      ),
    );
    return response.serving;
  }

  async publish(
    modelId: string,
  ): Promise<{ skill: PublishedSkillDto; model: ModelDto; serving: ServingBlock }> {
    const response = await firstValueFrom(
      this.http.post<{
        skill: PublishedSkillDto;
        model: ModelDto;
        serving: ServingBlock;
      }>(`${this.base}/${modelId}/publish`, {}),
    );
    this.replace(response.model);
    return response;
  }

  async unpublish(
    modelId: string,
  ): Promise<{ withdrawn: string | null; model: ModelDto; serving: ServingBlock }> {
    const response = await firstValueFrom(
      this.http.delete<{
        withdrawn: string | null;
        model: ModelDto;
        serving: ServingBlock;
      }>(`${this.base}/${modelId}/publish`),
    );
    this.replace(response.model);
    return response;
  }

  private replace(model: ModelDto): void {
    this.models.update((rows) =>
      rows.map((row) => (row.id === model.id ? model : row)),
    );
  }
}
