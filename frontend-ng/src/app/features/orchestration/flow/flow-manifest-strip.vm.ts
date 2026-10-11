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

/**
 * The dictionary lookup, injected rather than imported, so the projection stays
 * Angular-free and the spec can assert on keys instead of on copy.
 */
export type Translate = (key: string, params?: Record<string, string | number>) => string;

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

/**
 * Engine mode → the key that names it in plain words. `STRICT DAG` and its
 * siblings were the raw dispatcher verdicts, printed as-is on the chip; they
 * are the execution-mode jargon the lexicon replaces. The raw mode stays in
 * the chip's `title`, which is where a technical term belongs.
 *
 * The three canonical modes share their wording with the toolbar badge in
 * `flow-manifest.service.ts`; the other two are dispatcher identities with no
 * lexicon term of their own, so they borrow the closest plain phrase.
 */
const MODE_KEYS: Record<string, string> = {
  dag_strict: 'flow.runtime.mode.dag_strict',
  dag_overlay: 'flow.runtime.mode.dag_overlay',
  sequential_legacy: 'flow.runtime.mode.sequential_legacy',
  run_engine_dag: 'flow.runtime.mode.dag_strict',
  chat_runtime: 'flow.runtime.mode.chat',
};

function modeLabel(mode: string, t: Translate): string {
  const key = MODE_KEYS[mode];
  return key ? t(key) : mode;
}

function effectiveConfig(
  cfg: Record<string, unknown> | undefined | null,
  t: Translate,
): { value: string; title: string } {
  const keys = cfg ? Object.keys(cfg) : [];
  if (keys.length === 0) {
    return { value: '—', title: t('flow.manifest.config.none') };
  }
  const title = keys
    .slice(0, 12)
    .map((k) => `${k} = ${shortValue(cfg![k])}`)
    .join('\n');
  return {
    value: t('flow.manifest.config.keys', { count: keys.length }),
    title:
      keys.length > 12
        ? `${title}\n${t('flow.manifest.more', { count: keys.length - 12 })}`
        : title,
  };
}

function retrievalChip(
  lrd: FlowRuntimeManifest['latest_retrieval_decision'],
  t: Translate,
): ManifestStripChip {
  if (!lrd) {
    return {
      key: 'retrieval',
      label: t('flow.manifest.chip.retrieval'),
      value: t('flow.manifest.retrieval.none'),
      tone: 'neutral',
      title: t('flow.manifest.retrieval.none_recorded'),
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
    label: t('flow.manifest.chip.retrieval'),
    value: String(route),
    tone: lrd.status === 'failed' ? 'neg' : 'pos',
    title: lines.length > 0 ? lines.join('\n') : t('flow.manifest.retrieval.latest'),
  };
}

/**
 * Map a runtime manifest into the strip VM. Returns `null` when no manifest is
 * available (the `/orchestration` scratchpad never loads one).
 */
export function manifestToStripVm(
  manifest: FlowRuntimeManifest | null | undefined,
  t: Translate,
): ManifestStripVm | null {
  if (!manifest) return null;

  const totalUnits = manifest.summary?.nodes ?? manifest.unit_catalog?.length ?? 0;
  const operational = manifest.summary?.operational_units ?? 0;
  const skillUnits = manifest.summary?.skill_units ?? 0;
  const source = manifest.source ?? '—';
  const mode = manifest.runtime_mode ?? manifest.execution_mode ?? null;
  const config = effectiveConfig(manifest.effective_config, t);

  const chips: ManifestStripChip[] = [
    {
      key: 'units',
      label: t('flow.manifest.chip.units'),
      value: t('flow.manifest.units.value', { live: operational, total: totalUnits }),
      tone: totalUnits === 0 ? 'neutral' : operational > 0 ? 'pos' : 'warn',
      title: t('flow.manifest.units.title', {
        total: totalUnits,
        live: operational,
        skills: skillUnits,
      }),
    },
    {
      key: 'source',
      label: t('flow.manifest.chip.source'),
      value: mode ? `${source} · ${modeLabel(mode, t)}` : String(source),
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
      label: t('flow.manifest.chip.config'),
      value: config.value,
      tone: config.value === '—' ? 'neutral' : 'cool',
      title: config.title,
    },
    retrievalChip(manifest.latest_retrieval_decision, t),
  ];

  return {
    systemName: manifest.system_name || manifest.system_id || 'System',
    chips,
  };
}
