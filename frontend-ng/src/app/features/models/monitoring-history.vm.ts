import type { ScheduledMonitoringReport } from './retraining-evidence.vm';
import type { CurvePoint } from './models.vm';

export interface MonitoringSeries { key: string; label: string; feature?: string; points: CurvePoint[]; dates: string[]; }
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** Observations retain their position when a metric is missing; no invented zero. */
export function monitoringSeries(history: ScheduledMonitoringReport['history'] = []): MonitoringSeries[] {
  const rows = [...history].sort((a,b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
  const series = new Map<string, MonitoringSeries>();
  function add(key: string, label: string, value: unknown, index: number, feature?: string) {
    if (!finite(value)) return;
    const item = series.get(key) ?? { key, label, feature, points: [], dates: rows.map(row=>row.created_at) };
    item.points.push({ x: index + 1, y: value }); series.set(key, item);
  }
  rows.forEach((row,index) => {
    add('score', 'models.correctness.score_psi', row.score_drift?.value, index);
    const concept = row.concept_drift;
    if (concept?.metrics?.length) for (const metric of concept.metrics) add('concept:'+metric.metric, 'models.correctness.metric.'+metric.metric, metric.value, index);
    else add('concept:roc_auc', 'models.correctness.metric.roc_auc', concept?.rolling_auc, index);
    for (const feature of row.data_drift?.features ?? []) {
      add('psi:'+feature.name, 'models.correctness.feature_psi', feature.value, index, feature.name);
      add('p:'+feature.name, 'models.correctness.feature_p', feature.test?.p_value_adjusted, index, feature.name);
    }
  });
  return [...series.values()];
}

export function monitoringDomain(points: readonly CurvePoint[]) {
  const xs = points.map(p=>p.x), ys = points.map(p=>p.y);
  const min = Math.min(...ys, 0), max = Math.max(...ys, 1);
  return { minX: Math.min(...xs, 1), maxX: Math.max(...xs, 2), minY: min, maxY: max };
}
