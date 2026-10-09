/**
 * `FlowMlService` — the model workshop's window onto the model plane.
 *
 * One instance per builder shell, next to `FlowTransformService`, and the same
 * posture: it owns the reads an author needs while configuring a node, and it
 * never touches the graph.
 *
 *  - **the dataset catalog** — the ready datasets, so a fit is pointed at a
 *    table instead of at a typed slug;
 *  - **the plan** — `POST /ml-models/plan` on every meaningful edit, which is
 *    what makes the studio no-code: the target list only offers columns that can
 *    be predicted, the task arrives inferred from the column's type, and a
 *    column unique per row is called out as memorisation *before* a fit;
 *  - **the model registry** — the ready versions, so a serving node picks a
 *    lineage from a list rather than naming one that may not exist;
 *  - **one training run** — dispatched and followed to terminal, publishing the
 *    step the worker is on so a minute-long fit reads as work.
 *
 * The training run is the one place this differs in kind from the transform
 * workshop, and the difference is worth being explicit about: a transform
 * preview persists nothing, while a fit **registers a real version**. There is
 * no such thing as a throwaway fit — the artifact IS the product — so the
 * workshop calls the same endpoint the Models page calls, the version lands in
 * the registry, and the copy says so rather than pretending otherwise.
 */
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { DataService, type DatasetDto } from '@app/features/data/data.service';
import { ModelsService } from '@app/features/models/models.service';
import { isActiveStatus, splitError } from '@app/features/models/models.vm';
import type {
  CodedRefusal,
  ModelDto,
  ModelTask,
  PlanColumn,
  TrainingPlan,
} from '@app/features/models/models.vm';
import { mlFailure, type MlFailure } from './flow-ml.vm';

/** What the studio asks the plan endpoint about. */
export interface MlPlanQuery {
  dataset_id?: string;
  dataset_slug?: string;
  target?: string;
  task?: ModelTask;
  features?: string[];
  algo?: string;
  knobs?: Record<string, number>;
  /** A family's problem definition (a forecast's date column, horizon, …). */
  spec?: Record<string, unknown>;
}

/**
 * The spec a Test dispatches — the node's params, as the API names them.
 *
 * `target` is required here and optional on `MlPlanQuery` for the reason the
 * two calls differ: a plan answers "what would this be" for a spec still being
 * written, while a fit needs to know what it is predicting.
 */
export interface MlTrainRequest extends MlPlanQuery {
  target: string;
  name?: string;
  knobs?: Record<string, number>;
  test_size?: number;
  cross_validation?: number;
}

/** Poll cadence while a fit settles; a fit is seconds to minutes. */
const RUN_POLL_MS = 1200;
/** Stop following a row after this long — the worker's own timeout is harder. */
const RUN_POLL_TIMEOUT_MS = 20 * 60 * 1000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

@Injectable()
export class FlowMlService {
  private readonly models = inject(ModelsService);
  private readonly data = inject(DataService);
  private readonly destroyRef = inject(DestroyRef);

  /** Ready datasets available to pin; loaded once per builder shell. */
  readonly datasets = signal<DatasetDto[]>([]);
  readonly datasetsLoading = signal(false);
  /** Every model version of the workspace; the picker filters to the ready ones. */
  readonly registry = signal<ModelDto[]>([]);
  readonly registryLoading = signal(false);
  readonly catalog = computed(() => this.models.catalog());

  /** The plan's answer about the current spec, and its refusal if it has one. */
  readonly columns = signal<PlanColumn[]>([]);
  readonly plan = signal<TrainingPlan | null>(null);
  readonly refusal = signal<CodedRefusal | null>(null);
  readonly planning = signal(false);

  /** The run a Test is following, live. Kept after it settles: the metrics of
   * the version that was just fitted are the answer the author asked for. */
  readonly run = signal<ModelDto | null>(null);
  /** The lineage the run belongs to, so a score can be read as a move. */
  readonly runVersions = signal<ModelDto[]>([]);
  readonly busy = signal(false);
  readonly failure = signal<MlFailure | null>(null);

  private datasetsLoaded = false;
  private registryLoaded = false;
  private disposed = false;

  constructor() {
    this.destroyRef.onDestroy(() => {
      this.disposed = true;
    });
  }

  /** Load the pinnable datasets once (ready rows only: a pin must be usable). */
  async ensureDatasets(force = false): Promise<void> {
    if (this.datasetsLoaded && !force) return;
    this.datasetsLoaded = true;
    this.datasetsLoading.set(true);
    try {
      const rows = await this.data.refresh();
      if (this.disposed) return;
      this.datasets.set(rows.filter((row) => row.status === 'ready'));
    } catch {
      // The picker degrades to "no dataset available" and the workshop stays
      // usable for an author whose input arrives on the wire.
      this.datasetsLoaded = false;
    } finally {
      this.datasetsLoading.set(false);
    }
  }

  /** Load the registry and the algorithm catalog the studio renders. */
  async ensureRegistry(force = false): Promise<void> {
    if (this.registryLoaded && !force) return;
    this.registryLoaded = true;
    this.registryLoading.set(true);
    try {
      this.registry.set(await this.models.refresh());
    } catch {
      this.registryLoaded = false;
    } finally {
      this.registryLoading.set(false);
    }
  }

  /**
   * Ask what a spec *would* be, without fitting anything.
   *
   * A refusal here is not an error: it is rendered against the field that caused
   * it while the author keeps editing, which is why it lands on `refusal` rather
   * than on `failure`. `failure` is for a request that did not get an answer at
   * all.
   */
  async refreshPlan(query: MlPlanQuery): Promise<void> {
    if (!query.dataset_id && !query.dataset_slug) {
      this.columns.set([]);
      this.plan.set(null);
      this.refusal.set(null);
      return;
    }
    this.planning.set(true);
    try {
      const response = await this.models.plan(query);
      if (this.disposed) return;
      this.columns.set(response.columns ?? []);
      this.plan.set(response.plan);
      this.refusal.set(response.refusal);
      this.failure.set(null);
    } catch (error: unknown) {
      if (this.disposed) return;
      this.plan.set(null);
      this.failure.set(this.toFailure(error));
    } finally {
      this.planning.set(false);
    }
  }

  /**
   * Fit the authored spec for real and follow the run to terminal.
   *
   * The same call the Models page makes, deliberately: a node's fit and a
   * studio's fit must not be two code paths that can disagree about what a
   * spec means.
   */
  async test(request: MlTrainRequest): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.failure.set(null);
    this.run.set(null);
    this.runVersions.set([]);
    try {
      const queued = await this.models.train(request);
      if (this.disposed) return;
      this.run.set(queued);
      const settled = await this.follow(queued);
      if (this.disposed || !settled) return;
      if (settled.status !== 'ready') {
        this.failure.set(this.runFailure(settled));
      }
    } catch (error: unknown) {
      if (this.disposed) return;
      this.failure.set(this.toFailure(error));
    } finally {
      this.busy.set(false);
    }
  }

  /** Ask the worker to stop the fit it is on (cooperative, like a recipe test). */
  async cancel(): Promise<void> {
    const row = this.run();
    if (!row || row.cancel_requested) return;
    try {
      this.run.set(await this.models.cancel(row.id));
    } catch {
      // The poll loop is authoritative: it reports the terminal status.
    }
  }

  /** Drop the last run — the spec changed, so it no longer describes it. */
  clearRun(): void {
    this.run.set(null);
    this.runVersions.set([]);
    this.failure.set(null);
  }

  /** Poll one model row until it settles (or until the shell goes away). */
  private async follow(row: ModelDto): Promise<ModelDto | null> {
    let current = row;
    const giveUpAt = Date.now() + RUN_POLL_TIMEOUT_MS;
    while (isActiveStatus(current.status)) {
      if (this.disposed) return null;
      if (Date.now() > giveUpAt) {
        void this.cancel();
        return null;
      }
      await sleep(RUN_POLL_MS);
      if (this.disposed) return null;
      // The detail read rather than the list: it carries the metrics block the
      // result panel renders, and the sibling versions that turn a score into a
      // move ("AUC 0.91, +0.03 on v2") rather than a bare number.
      const detail = await this.models.detail(current.id);
      current = detail.model;
      this.run.set(current);
      this.runVersions.set(detail.versions ?? []);
    }
    return current;
  }

  /**
   * A settled-but-not-ready run's own refusal, coded and translatable.
   *
   * The worker writes `CODE: detail`, and `mlFailure` is what decides whose
   * sentence a code is: a fit that refused refuses for the same reason whether
   * it was dispatched from the Models page or from a node, so the model plane's
   * dictionary answers it and there is one sentence to keep true.
   */
  private runFailure(row: ModelDto): MlFailure {
    if (row.status === 'cancelled') return { key: 'flow.ml.run.cancelled' };
    const { code, detail } = splitError(row.error);
    return mlFailure(code, detail);
  }

  private toFailure(error: unknown): MlFailure {
    if (error instanceof HttpErrorResponse) {
      const detail = error.error?.detail;
      if (detail && typeof detail === 'object') {
        return mlFailure(
          typeof detail['code'] === 'string' ? detail['code'] : null,
          typeof detail['message'] === 'string' ? detail['message'] : null,
        );
      }
      return mlFailure(null, typeof detail === 'string' ? detail : error.message);
    }
    return mlFailure(null, error instanceof Error ? error.message : null);
  }
}
