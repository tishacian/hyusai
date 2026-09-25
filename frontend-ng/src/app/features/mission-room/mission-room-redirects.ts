import { agentiumSurfaceRoute } from '@app/core/navigation.catalog';

/**
 * L13a: Mission Room URLs collapse into Impact (`/hypervisor`) query params.
 * View bodies arrive in L13b; until then the param is preserved on Synthèse.
 */
export type MissionRoomImpactTarget = {
  readonly path: string;
  readonly queryParams: Readonly<Record<string, string>>;
  /** Soft proposition: open ⌘K after landing on Impact. */
  readonly openPalette?: boolean;
};

const IMPACT = agentiumSurfaceRoute('hypervisor');

function impact(queryParams: Record<string, string> = {}): MissionRoomImpactTarget {
  return { path: IMPACT, queryParams };
}

/** Map a Mission Room path (no query) to its Impact replacement. */
export function missionRoomImpactTarget(
  path: string,
): MissionRoomImpactTarget | null {
  const normalized = (path || '/').split('?')[0].split('#')[0] || '/';
  const root = '/hypervisor/mission-room';
  if (normalized !== root && !normalized.startsWith(`${root}/`)) return null;

  const rest = normalized === root ? '' : normalized.slice(root.length + 1);
  if (!rest || rest === 'cockpit') return impact({ theme: 'presentation' });

  const meeting = rest.match(/^agenda\/meeting\/([^/]+)$/);
  if (meeting?.[1]) {
    return impact({ view: 'reunion', eventId: decodeURIComponent(meeting[1]) });
  }

  if (rest === 'agenda') return impact({ view: 'agenda' });
  if (rest === 'veille-sociale' || rest === 'reputation' || rest === 'presse') {
    return impact({ view: 'veille' });
  }
  if (rest === 'securite' || rest === 'securite/monitor') {
    return impact({ view: 'securite' });
  }
  if (rest === 'strategie' || rest === 'monitor') {
    return impact({ view: 'carte' });
  }
  if (rest === 'decisions') return impact({ facet: 'decisions' });
  if (rest === 'recherche') return { ...impact(), openPalette: true };

  // Unknown legacy views land on Impact home (no Mission Room chrome).
  return impact();
}

export function missionRoomImpactUrl(path: string): string | null {
  const target = missionRoomImpactTarget(path);
  if (!target) return null;
  const params = new URLSearchParams(target.queryParams);
  const query = params.toString();
  return query ? `${target.path}?${query}` : target.path;
}
