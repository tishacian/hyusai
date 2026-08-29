/**
 * Showcase notes for Nawa's Hikma S/4 MCP servers.
 * Hostnames decide the SAP service (labels in old credential files were swapped).
 * No PDF contract aliases — live tool names stay as advertised.
 */

export type McpShowcaseLane = 'pr' | 'inbox' | 'po' | 'gr';
export type McpShowcaseReadiness = 'ready' | 'partial' | 'caution' | 'unknown';

export interface McpShowcaseInsight {
  lane: McpShowcaseLane;
  step: number;
  service: string;
  readiness: McpShowcaseReadiness;
  notes: Array<'host' | 'writes' | 'by_key' | 'slow' | 'gr' | 'inbox'>;
}

const LANE_STEP: Record<McpShowcaseLane, number> = {
  pr: 1,
  inbox: 2,
  po: 3,
  gr: 4,
};

const LANE_SERVICE: Record<McpShowcaseLane, string> = {
  pr: 'API_PURCHASEREQ_PROCESS_SRV',
  po: 'API_PURCHASEORDER_PROCESS_SRV',
  gr: 'API_MATERIAL_DOCUMENT_SRV',
  inbox: '/IWPGW/TASKPROCESSING v2',
};

const INBOX_GAPS = [
  'comment',
  'processinglog',
  'workflowlog',
  'approvalhistory',
  'popdf',
] as const;

export function hostOfMcpUrl(url: string): string {
  const raw = (url || '').trim();
  if (!raw) return '';
  try {
    return new URL(raw).host.toLowerCase();
  } catch {
    return raw.toLowerCase();
  }
}

/** Hostname wins over server id — the host is what the SAP service actually is. */
export function resolveShowcaseLane(serverId: string, url = ''): McpShowcaseLane | null {
  const host = hostOfMcpUrl(url);
  if (host.includes('goods-receipt')) return 'gr';
  if (host.includes('inbox')) return 'inbox';
  if (host.includes('-pr-mcp') || /s4-pr(?:-|\.|$)/.test(host)) return 'pr';
  if (host.includes('-po-mcp') || /s4-po(?:-|\.|$)/.test(host)) return 'po';
  const id = (serverId || '').trim().toLowerCase();
  if (id === 'sap_gr') return 'gr';
  if (id === 'sap_inbox') return 'inbox';
  if (id === 'sap') return 'pr';
  if (id === 'hikma') return 'po';
  return null;
}

export function inferShowcaseReadiness(
  lane: McpShowcaseLane,
  toolNames: readonly string[],
): McpShowcaseReadiness {
  const names = toolNames.map((name) => (name || '').toLowerCase()).filter(Boolean);
  if (!names.length) return 'unknown';
  const blob = names.join(' ');
  if (lane === 'gr') return 'caution';
  if (lane === 'inbox') {
    const hasTask = blob.includes('workflowtask') || blob.includes('taskprocessing') || blob.includes('task');
    const missing = INBOX_GAPS.filter((gap) => !blob.includes(gap));
    if (hasTask && missing.length) return 'partial';
    return hasTask ? 'ready' : 'unknown';
  }
  if (lane === 'pr') {
    return blob.includes('purchaserequisition') || blob.includes('purchasereq') ? 'ready' : 'unknown';
  }
  if (lane === 'po') {
    return blob.includes('purchaseorder') ? 'ready' : 'unknown';
  }
  return 'unknown';
}

export function showcaseInsight(
  serverId: string,
  url = '',
  toolNames: readonly string[] = [],
): McpShowcaseInsight | null {
  const lane = resolveShowcaseLane(serverId, url);
  if (!lane) return null;
  const notes: McpShowcaseInsight['notes'] = ['host', 'writes', 'by_key', 'slow'];
  if (lane === 'gr') notes.push('gr');
  if (lane === 'inbox') notes.push('inbox');
  return {
    lane,
    step: LANE_STEP[lane],
    service: LANE_SERVICE[lane],
    readiness: inferShowcaseReadiness(lane, toolNames),
    notes,
  };
}

export function sortShowcaseServers<T extends { id: string; url?: string }>(rows: T[]): T[] {
  return [...rows].sort((left, right) => {
    const leftLane = resolveShowcaseLane(left.id, left.url || '');
    const rightLane = resolveShowcaseLane(right.id, right.url || '');
    const leftStep = leftLane ? LANE_STEP[leftLane] : 50;
    const rightStep = rightLane ? LANE_STEP[rightLane] : 50;
    if (leftStep !== rightStep) return leftStep - rightStep;
    return left.id.localeCompare(right.id);
  });
}
