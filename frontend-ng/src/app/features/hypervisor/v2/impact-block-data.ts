/**
 * Pure mappers from Mission Room / Hypervisor payloads into Impact block
 * inputs (L13b live wiring). No HTTP — callers fetch existing APIs.
 */

import type { DecisionRow, HypervisorSignal } from '@app/core/canonical-api.service';
import type { AlerteItem } from './blocks/impact-block-alertes.component';
import type { EcheancierItem } from './blocks/impact-block-echeancier.component';
import type { FluxItem } from './blocks/impact-block-flux.component';
import type { IndicateurItem } from './blocks/impact-block-indicateurs.component';
import type { OrdreOption, OrdrePoint } from './blocks/impact-block-ordre-du-jour.component';
import type { HypervisorRegisterRow } from './hypervisor-v2-series';

export interface ImpactAgendaRaw {
  id?: string;
  title?: string;
  time?: string;
  end_time?: string;
  date?: string;
  location?: string;
  status?: string;
  priority?: string;
  metadata?: {
    agenda_items?: Array<{
      id?: string;
      title?: string;
      origin?: string;
      options?: Array<{ id?: string; label?: string; recommended?: boolean }>;
    }>;
    [key: string]: unknown;
  };
}

export interface ImpactTimelineRaw {
  agenda?: ImpactAgendaRaw[];
}

export interface ImpactNewsSignalRaw {
  id?: string;
  title?: string;
  source_category?: string | null;
  sentiment?: string | null;
  confidence?: number | null;
  zone?: string | null;
  risk_level?: string | null;
}

export interface ImpactNewsRaw {
  signals?: ImpactNewsSignalRaw[];
  all_signals?: ImpactNewsSignalRaw[];
  executive_alerts?: ImpactNewsSignalRaw[];
}

export interface ImpactMapZoneRaw {
  id?: string;
  zone_id?: string;
  name?: string;
  level?: number | null;
}

export interface ImpactMapRaw {
  zones?: ImpactMapZoneRaw[];
}

export interface ImpactMonitorRaw {
  zones?: Array<{
    id?: string;
    name?: string;
    level?: string | number | null;
    tone?: string | null;
    signals?: string[];
  }>;
  news_signals?: ImpactNewsSignalRaw[];
  visual_observations?: Array<{
    id?: string;
    summary?: string;
    level_label?: string;
    source_id?: string;
  }>;
}

export interface ImpactMacroIndicatorRaw {
  key?: string;
  label?: string;
  current?: number | null;
  value?: number | null;
  unit?: string | null;
  source?: string | null;
}

export interface ImpactMacroRaw {
  indicators?: ImpactMacroIndicatorRaw[];
  sovereign_indicators?: ImpactMacroIndicatorRaw[];
  macro_indicators_sovereign?: ImpactMacroIndicatorRaw[];
  source?: string | null;
  fetched_at?: string | null;
}

export interface ImpactCarteZone {
  id: string;
  name: string;
  level?: number | null;
}

function asId(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return fallback;
}

function asTitle(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

export function mapTimelineToEcheancier(timeline: ImpactTimelineRaw | null | undefined): EcheancierItem[] {
  const agenda = timeline?.agenda ?? [];
  return agenda
    .map((item, index) => {
      const title = asTitle(item.title);
      if (!title) return null;
      return {
        id: asId(item.id, `agenda-${index}`),
        title,
        starts_at: item.date && item.time ? `${item.date}T${item.time}` : item.time || item.date || null,
        ends_at: item.end_time || null,
        place: item.location || null,
        status: item.status || null,
        priority: item.priority || null,
      } satisfies EcheancierItem;
    })
    .filter((item): item is EcheancierItem => item != null);
}

export function mapNewsToFlux(news: ImpactNewsRaw | null | undefined): FluxItem[] {
  const signals = news?.all_signals?.length
    ? news.all_signals
    : (news?.signals ?? []);
  return signals
    .map((signal, index) => {
      const title = asTitle(signal.title);
      if (!title) return null;
      return {
        id: asId(signal.id, `flux-${index}`),
        title,
        klass: signal.source_category || null,
        tone: signal.sentiment || null,
        engagement: typeof signal.confidence === 'number' ? signal.confidence : null,
      } satisfies FluxItem;
    })
    .filter((item): item is FluxItem => item != null);
}

export function mapMapToZones(map: ImpactMapRaw | null | undefined): ImpactCarteZone[] {
  return (map?.zones ?? [])
    .map((zone, index) => {
      const id = asId(zone.id ?? zone.zone_id, `zone-${index}`);
      const name = asTitle(zone.name);
      if (!name) return null;
      return {
        id,
        name,
        level: typeof zone.level === 'number' ? zone.level : null,
      } satisfies ImpactCarteZone;
    })
    .filter((zone): zone is ImpactCarteZone => zone != null);
}

export function mapMonitorToAlertes(
  monitor: ImpactMonitorRaw | null | undefined,
  news: ImpactNewsRaw | null | undefined = null,
): AlerteItem[] {
  const fromNews = (news?.executive_alerts ?? []).map((signal, index) => ({
    id: asId(signal.id, `alert-news-${index}`),
    title: asTitle(signal.title, '—'),
    severity: signal.risk_level || null,
    zone: signal.zone || null,
  }));
  const fromMonitorSignals = (monitor?.news_signals ?? []).map((signal, index) => ({
    id: asId(signal.id, `alert-monitor-${index}`),
    title: asTitle(signal.title, '—'),
    severity: signal.risk_level || null,
    zone: signal.zone || null,
  }));
  const fromZones = (monitor?.zones ?? []).flatMap((zone, zoneIndex) => {
    const zoneId = asId(zone.id, `zone-${zoneIndex}`);
    const zoneName = asTitle(zone.name, zoneId);
    const signals = zone.signals?.length ? zone.signals : [zoneName];
    return signals.map((text, signalIndex) => ({
      id: `${zoneId}-sig-${signalIndex}`,
      title: asTitle(text, zoneName),
      severity: typeof zone.level === 'string' ? zone.level : zone.tone || null,
      zone: zoneName,
    }));
  });
  const fromObservations = (monitor?.visual_observations ?? []).map((row, index) => ({
    id: asId(row.id, `obs-${index}`),
    title: asTitle(row.summary, '—'),
    severity: row.level_label || null,
    zone: row.source_id || null,
  }));
  return [...fromNews, ...fromMonitorSignals, ...fromZones, ...fromObservations]
    .filter((item) => item.title && item.title !== '—');
}

export function mapSignalsToAlertes(signals: readonly HypervisorSignal[]): AlerteItem[] {
  return signals.map((signal) => ({
    id: signal.id,
    title: signal.label,
    severity: signal.tone,
    zone: signal.system_id || null,
  }));
}

export function mapAgendaMetadataToOrdre(
  timeline: ImpactTimelineRaw | null | undefined,
  eventId: string | null | undefined,
): OrdrePoint[] {
  const agenda = timeline?.agenda ?? [];
  const target = eventId
    ? agenda.find((item) => item.id === eventId) ?? agenda[0]
    : agenda[0];
  const items = target?.metadata?.agenda_items;
  if (!items?.length) return [];
  return items
    .map((point, index) => {
      const title = asTitle(point.title);
      if (!title) return null;
      const options: OrdreOption[] = (point.options ?? [])
        .map((option, optionIndex) => {
          const label = asTitle(option.label);
          if (!label) return null;
          return {
            id: asId(option.id, `opt-${index}-${optionIndex}`),
            label,
            recommended: option.recommended === true,
          } satisfies OrdreOption;
        })
        .filter((option): option is OrdreOption => option != null);
      return {
        id: asId(point.id, `point-${index}`),
        title,
        origin: point.origin || null,
        options,
      } satisfies OrdrePoint;
    })
    .filter((point): point is OrdrePoint => point != null);
}

/** Fallback when no meeting agenda_items: proposed Impact decisions as points. */
export function mapDecisionsToOrdre(decisions: readonly DecisionRow[]): OrdrePoint[] {
  return decisions
    .filter((row) => row.status === 'proposed')
    .map((row) => ({
      id: row.id,
      title: row.title,
      origin: row.agent_suggested ? 'agent' : (row.origin || 'human'),
      options: [],
    }));
}

export function mapMacroToIndicateurs(
  macro: ImpactMacroRaw | null | undefined,
): IndicateurItem[] {
  const rows = [
    ...(macro?.sovereign_indicators ?? []),
    ...(macro?.macro_indicators_sovereign ?? []),
    ...(macro?.indicators ?? []),
  ];
  const seen = new Set<string>();
  const out: IndicateurItem[] = [];
  for (const [index, row] of rows.entries()) {
    const id = asId(row.key, `ind-${index}`);
    if (seen.has(id)) continue;
    seen.add(id);
    const label = asTitle(row.label, id);
    const raw = row.current ?? row.value;
    const measured = typeof raw === 'number' && Number.isFinite(raw);
    const unit = typeof row.unit === 'string' && row.unit.trim() ? ` ${row.unit.trim()}` : '';
    out.push({
      id,
      label,
      value: measured ? `${raw}${unit}` : '—',
      state: measured ? 'measured' : 'absent',
      source: row.source || macro?.source || null,
      freshness: macro?.fetched_at || null,
    });
    if (out.length >= 6) break;
  }
  return out;
}

/** Fallback indicateurs from the portfolio series already on screen. */
export function mapRegisterToIndicateurs(
  register: readonly HypervisorRegisterRow[],
): IndicateurItem[] {
  return register.slice(0, 6).map((row) => {
    const measured = row.basisStatus === 'measured';
    const declared = row.basisStatus === 'declared';
    const fact = measured || declared
      ? (row.valueDeclared.state === 'available' ? row.valueDeclared : row.hours)
      : null;
    const value = fact && fact.state === 'available' && fact.value != null
      ? String(fact.value)
      : '—';
    return {
      id: row.systemId,
      label: row.name,
      value,
      state: measured ? 'measured' : declared ? 'declared' : 'absent',
      source: row.outputUnit,
    } satisfies IndicateurItem;
  });
}
