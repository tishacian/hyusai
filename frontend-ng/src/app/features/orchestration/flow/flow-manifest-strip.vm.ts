/**
 * Pure projection from the backend `FlowRuntimeManifest` into the compact
 * view-model the manifest strip renders. Kept Angular-free (only a `type`
 * import, erased at build) so the non-trivial mapping is unit-testable in the
 * lightweight `node:test` harness without any DI or live backend.
 *
 * It summarises exactly four facets the strip shows — units / source /
 * effective-config / latest-retrieval-decision — and returns `null` for the
 * scratchpad / no-manifest case so the component can render its empty state.
 */
import type { FlowRuntimeManifest } from '@app/core/canonical-api.service';

export type ManifestChipTone = 'neutral' | 'cool' | 'pos' | 'warn' | 'neg';

/** One compact metric pill in the strip. */
export interface ManifestStripChip {
  key: 'units' | 'source' | 'config' | 'retrieval';
  label: string;
  value: string;
  tone: ManifestChipTone;
  /** Long-form hover detail (newline-separated). */
  title: string;
}

export interface ManifestStripVm {
  systemName: string;
  chips: ManifestStripChip[];
}

/** Compact, depth-1 stringify for a config value (capped). */
function shortValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') {
    try {
      const json = JSON.stringify(value);
      return json.length > 48 ? json.slice(0, 48) + '…' : json;
    } catch {
      return '[object]';
    }
  }
  const str = String(value);
  return str.length > 48 ? str.slice(0, 48) + '…' : str;
}

function prettyMode(mode: string): string {
  switch (mode) {
    case 'chat_runtime':
      return 'chat';
    case 'run_engine_dag':
      return 'DAG';
    case 'dag_strict':
      return 'STRICT DAG';
    case 'dag_overlay':
      return 'DAG · OVERLAY COMPAT';
    case 'sequential_legacy':
      return 'LEGACY · SEQUENTIAL';
    default:
      return mode;
  }
}

function effectiveConfig(cfg: Record<string, unknown> | undefined | null): { value: string; title: string } {
  const keys = cfg ? Object.keys(cfg) : [];
  if (keys.length === 0) {
    return { value: '—', title: 'No effective config resolved' };
  }
  const title = keys
    .slice(0, 12)
    .map((k) => `${k} = ${shortValue(cfg![k])}`)
    .join('\n');
  return {
    value: `${keys.length} ${keys.length === 1 ? 'key' : 'keys'}`,
    title: keys.length > 12 ? `${title}\n… (+${keys.length - 12} more)` : title,
  };
}

function retrievalChip(
  lrd: FlowRuntimeManifest['latest_retrieval_decision'],
): ManifestStripChip {
  if (!lrd) {
    return {
      key: 'retrieval',
      label: 'Retrieval',
      value: 'none yet',
      tone: 'neutral',
      title: 'No retrieval decision recorded for this System yet',
    };
  }
  const trace = lrd.trace;
  const route = trace?.selected_route ?? trace?.query_type ?? lrd.status ?? '—';
  const lines: string[] = [];
  if (lrd.status) lines.push(`status: ${lrd.status}`);
  if (trace?.selected_route) lines.push(`route: ${trace.selected_route}`);
  if (trace?.route_reason) lines.push(`reason: ${trace.route_reason}`);
  if (trace?.summary) lines.push(trace.summary);
  if (lrd.started_at) lines.push(`at ${lrd.started_at}`);
  if (lrd.run_id) lines.push(`run ${lrd.run_id.slice(0, 8)}`);
  return {
    key: 'retrieval',
    label: 'Retrieval',
    value: String(route),
    tone: lrd.status === 'failed' ? 'neg' : 'pos',
    title: lines.length > 0 ? lines.join('\n') : 'Latest retrieval decision',
  };
}

/**
 * Map a runtime manifest into the strip VM. Returns `null` when no manifest is
 * available (the `/orchestration` scratchpad never loads one).
 */
export function manifestToStripVm(
  manifest: FlowRuntimeManifest | null | undefined,
): ManifestStripVm | null {
  if (!manifest) return null;

  const totalUnits = manifest.summary?.nodes ?? manifest.unit_catalog?.length ?? 0;
  const operational = manifest.summary?.operational_units ?? 0;
  const skillUnits = manifest.summary?.skill_units ?? 0;
  const source = manifest.source ?? '—';
  const mode = manifest.runtime_mode ?? manifest.execution_mode ?? null;
  const config = effectiveConfig(manifest.effective_config);

  const chips: ManifestStripChip[] = [
    {
      key: 'units',
      label: 'Units',
      value: `${operational}/${totalUnits} live`,
      tone: totalUnits === 0 ? 'neutral' : operational > 0 ? 'pos' : 'warn',
      title: `${totalUnits} unit(s) · ${operational} operational · ${skillUnits} skill unit(s)`,
    },
    {
      key: 'source',
      label: 'Source',
      value: mode ? `${source} · ${prettyMode(mode)}` : String(source),
      tone: 'cool',
      title: [
        `flow_definition source: ${source}`,
        mode ? `runtime mode: ${mode}` : null,
        manifest.live_surface ? `live surface: ${manifest.live_surface}` : null,
        manifest.operational_sync != null ? `operational sync: ${manifest.operational_sync}` : null,
      ]
        .filter((line): line is string => line !== null)
        .join('\n'),
    },
    {
      key: 'config',
      label: 'Config',
      value: config.value,
      tone: config.value === '—' ? 'neutral' : 'cool',
      title: config.title,
    },
    retrievalChip(manifest.latest_retrieval_decision),
  ];

  return {
    systemName: manifest.system_name || manifest.system_id || 'System',
    chips,
  };
}
