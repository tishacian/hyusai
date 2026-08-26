/**
 * What a settled node shows on the canvas — pure view-model.
 *
 * The point of the data plane living inside the Flow Builder is that a run is
 * *visible*: you press Execute and the numbers land on the graph. The backend
 * already puts them on the `node_end` frame (`dag._node_data_badge`), so this
 * module only decides which of them is worth the twelve characters a node card
 * can spare, and in which order.
 *
 * The ranking is deliberate and it is the whole design:
 *
 *  1. A **metric** wins. On a training node "AUC 0.87" is the answer to the
 *     only question anybody asks of a fit, and a row count next to it would
 *     dilute it.
 *  2. A **row transition** comes next — "8 412 → 6 903" is what a transform
 *     *did*, and it is legible at a glance in a way "6 903 rows" is not.
 *  3. A bare **row count** for a node that only produced (an ingest, a score
 *     with no upstream count).
 *  4. Otherwise the **duration**, which every node has.
 *
 * The model that answered rides along as a second, quieter chip when there is
 * one, because "scored by churn-risk v3" is the provenance thread of the whole
 * story and it belongs on the node that scored, not only in a lineage panel.
 *
 * Angular-free on purpose so `run-unit.mjs` can exercise it in plain Node: the
 * ranking above is an argument, and an argument has to be assertable.
 */

/** The badge block the backend merges into a `node_end` checkpoint. */
export interface NodeRunData {
  rows_in?: number;
  rows_out?: number;
  metric?: { key: string; value: number };
  model?: { slug: string; version?: number };
  model_id?: string;
  predictions?: number;
  /** The dataset the node WROTE, so a surface can open the rows it produced. */
  dataset_id?: string;
}

/** Everything the canvas knows about one node's last execution. */
export interface NodeRunSummary {
  nodeId: string;
  status: string;
  /** Wall time of the node, as the walker measured it. */
  latencyMs?: number;
  skillSlug?: string;
  error?: string;
  data?: NodeRunData;
}

/** A translated-at-render badge: the key names the sentence, params fill it. */
export interface NodeRunBadge {
  /** Which shape it is — drives the tone, and is what tests assert on. */
  kind: 'metric' | 'rows_delta' | 'rows' | 'predictions' | 'duration';
  key: string;
  params: Record<string, string | number>;
  /** True when the node failed: the badge is still shown, in the failed tone. */
  failed: boolean;
  /** Provenance chip, when a model answered on this node. */
  model?: string;
  /** The duration, always, so the card can show it next to the figure. */
  duration?: string;
}

/** Statuses a node reaches that mean "it ran and it did not work". */
const FAILED_STATUSES: readonly string[] = ['failed', 'error', 'timeout'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === 'boolean') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Normalise the `data` block of a checkpoint, dropping anything unusable. */
export function readNodeRunData(value: unknown): NodeRunData | undefined {
  if (!isRecord(value)) return undefined;
  const data: NodeRunData = {};
  const rowsIn = finiteNumber(value['rows_in']);
  if (rowsIn !== null) data.rows_in = rowsIn;
  const rowsOut = finiteNumber(value['rows_out']);
  if (rowsOut !== null) data.rows_out = rowsOut;
  const predictions = finiteNumber(value['predictions']);
  if (predictions !== null) data.predictions = predictions;
  const written = value['dataset_id'];
  if (typeof written === 'string' && written.trim()) data.dataset_id = written.trim();
  const metric = value['metric'];
  if (isRecord(metric)) {
    const key = typeof metric['key'] === 'string' ? metric['key'].trim() : '';
    const metricValue = finiteNumber(metric['value']);
    if (key && metricValue !== null) data.metric = { key, value: metricValue };
  }
  const model = value['model'];
  if (isRecord(model)) {
    const slug = typeof model['slug'] === 'string' ? model['slug'].trim() : '';
    const version = finiteNumber(model['version']);
    if (slug) {
      data.model = { slug, ...(version !== null ? { version } : {}) };
    }
  }
  if (typeof value['model_id'] === 'string' && value['model_id'].trim()) {
    data.model_id = value['model_id'].trim();
  }
  return Object.keys(data).length > 0 ? data : undefined;
}

/** Project one `node_end` checkpoint (or SSE frame) into a run summary. */
export function readNodeRunSummary(frame: unknown): NodeRunSummary | null {
  if (!isRecord(frame)) return null;
  const nodeId = typeof frame['node_id'] === 'string' ? frame['node_id'].trim() : '';
  if (!nodeId) return null;
  const latency = finiteNumber(frame['latency_ms']);
  const status =
    typeof frame['status'] === 'string' && frame['status'].trim()
      ? frame['status'].trim()
      : 'completed';
  return {
    nodeId,
    status,
    ...(latency !== null ? { latencyMs: latency } : {}),
    ...(typeof frame['skill_slug'] === 'string' && frame['skill_slug']
      ? { skillSlug: frame['skill_slug'] }
      : {}),
    ...(typeof frame['error'] === 'string' && frame['error']
      ? { error: frame['error'] }
      : {}),
    ...(readNodeRunData(frame['data']) ? { data: readNodeRunData(frame['data']) } : {}),
  };
}

/**
 * A metric value as a card shows it.
 *
 * Three decimals for a score in `[0, 1]` (an AUC of 0.871 and one of 0.87 are
 * different models), and a thousands-separated integer part for anything on a
 * target's own scale — an RMSE of 1 284 € is not "1284".
 */
export function formatMetricValue(value: number, locale = 'en'): string {
  const magnitude = Math.abs(value);
  if (magnitude < 1) {
    return value.toLocaleString(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 3,
    });
  }
  return value.toLocaleString(locale, { maximumFractionDigits: magnitude < 100 ? 2 : 0 });
}

/** A duration a human reads without counting zeros. */
export function formatDuration(ms: number, locale = 'en'): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds.toLocaleString(locale, { maximumFractionDigits: seconds < 10 ? 1 : 0 })} s`;
  }
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

/** `churn-risk v3`, or just the slug when the version is unknown. */
export function modelChip(model: NodeRunData['model']): string | undefined {
  if (!model) return undefined;
  return model.version === undefined ? model.slug : `${model.slug} v${model.version}`;
}

/**
 * The one badge a node card shows for its last execution.
 *
 * Returns `null` for a node that has not run, and for one that is still
 * running: an in-flight node already pulses, and a figure from the previous run
 * next to that pulse would be a lie about the current one.
 */
export function nodeRunBadge(
  summary: NodeRunSummary | null | undefined,
  locale = 'en',
): NodeRunBadge | null {
  if (!summary) return null;
  if (summary.status === 'running' || summary.status === 'pending') return null;
  const failed = FAILED_STATUSES.includes(summary.status);
  const data = summary.data ?? {};
  const duration =
    summary.latencyMs !== undefined
      ? formatDuration(summary.latencyMs, locale)
      : undefined;
  const model = modelChip(data.model);
  const shell = { failed, ...(model ? { model } : {}), ...(duration ? { duration } : {}) };

  if (data.metric) {
    return {
      ...shell,
      kind: 'metric',
      key: 'flow.node.run.metric',
      params: {
        metric: data.metric.key,
        value: formatMetricValue(data.metric.value, locale),
      },
    };
  }
  if (data.rows_in !== undefined && data.rows_out !== undefined) {
    return {
      ...shell,
      kind: 'rows_delta',
      key: 'flow.node.run.rows_delta',
      params: {
        from: data.rows_in.toLocaleString(locale),
        to: data.rows_out.toLocaleString(locale),
      },
    };
  }
  const rows = data.rows_out ?? data.rows_in;
  if (rows !== undefined) {
    return {
      ...shell,
      kind: 'rows',
      key: 'flow.node.run.rows',
      params: { rows: rows.toLocaleString(locale), count: rows },
    };
  }
  if (data.predictions !== undefined) {
    return {
      ...shell,
      kind: 'predictions',
      key: 'flow.node.run.predictions',
      params: { count: data.predictions },
    };
  }
  if (duration) {
    return {
      ...shell,
      kind: 'duration',
      key: 'flow.node.run.duration',
      params: { duration },
    };
  }
  return null;
}

/**
 * The dictionary keys a metric name resolves through.
 *
 * A metric arrives as the harness named it (`roc_auc`, `r2`), and the models
 * dictionary already translates those for the model card. Reusing that entry
 * rather than duplicating it in the flow dictionary is what keeps "AUC" spelled
 * the same on the card and on the node.
 */
export function metricLabelKey(metric: string): string {
  return `models.metric.${metric}`;
}
