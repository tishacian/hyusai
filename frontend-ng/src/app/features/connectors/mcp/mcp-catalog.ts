/**
 * Group live MCP tool names into objects an operator can scan.
 * Labels come from the advertised name (and description). No PDF aliases.
 */

export type McpToolKind = 'read' | 'write' | 'other';

export interface McpCatalogTool {
  name: string;
  description: string;
  kind: McpToolKind;
  verb: string;
  entity: string;
  label: string;
}

export interface McpCatalogGroup {
  entity: string;
  label: string;
  read: McpCatalogTool[];
  write: McpCatalogTool[];
  other: McpCatalogTool[];
}

const READ_PREFIXES = ['get_', 'list_', 'query_', 'search_', 'read_'] as const;
const WRITE_PREFIXES = ['post_', 'patch_', 'put_', 'delete_', 'create_', 'update_', 'reject_'] as const;
const WRITE_NAMES = new Set(['reject_pr', 'create_po', 'handle_rejection']);

export function classifyMcpToolKind(name: string): McpToolKind {
  const lower = (name || '').toLowerCase();
  if (WRITE_PREFIXES.some((prefix) => lower.startsWith(prefix)) || WRITE_NAMES.has(lower)) {
    return 'write';
  }
  if (lower.startsWith('bapi_') && /create|commit|rollback/.test(lower)) return 'write';
  if (READ_PREFIXES.some((prefix) => lower.startsWith(prefix))) return 'read';
  if (lower.includes('reject') || lower.startsWith('handle_')) return 'write';
  return 'other';
}

function stripVerb(name: string): { verb: string; rest: string } {
  const lower = name.toLowerCase();
  for (const prefix of [...READ_PREFIXES, ...WRITE_PREFIXES, 'handle_'] as const) {
    if (lower.startsWith(prefix)) {
      return { verb: prefix.replace(/_$/, ''), rest: name.slice(prefix.length) };
    }
  }
  const idx = name.indexOf('_');
  if (idx > 0) return { verb: name.slice(0, idx), rest: name.slice(idx + 1) };
  return { verb: name, rest: name };
}

function groupEntity(entity: string): string {
  const stripped = entity
    .replace(/_by_key$/i, '')
    .replace(/(Header|Item|Type|Text)$/, '');
  return stripped || entity;
}

export function humanizeMcpName(value: string): string {
  const spaced = (value || '')
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim();
  if (!spaced) return value;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function describeMcpTool(name: string, description?: string): McpCatalogTool {
  const { verb, rest } = stripVerb(name);
  const entityRaw = rest.startsWith('A_') ? rest.slice(2) : rest;
  const entity = groupEntity(entityRaw);
  return {
    name,
    description: (description || '').trim(),
    kind: classifyMcpToolKind(name),
    verb,
    entity,
    label: humanizeMcpName(entity),
  };
}

export function groupMcpTools(
  tools: Array<{ name?: string; description?: string } | string>,
): McpCatalogGroup[] {
  const groups = new Map<string, McpCatalogGroup>();
  for (const item of tools) {
    const name = typeof item === 'string' ? item : item.name || '';
    const description = typeof item === 'string' ? '' : item.description || '';
    if (!name.trim()) continue;
    const tool = describeMcpTool(name.trim(), description);
    let group = groups.get(tool.entity);
    if (!group) {
      group = { entity: tool.entity, label: tool.label, read: [], write: [], other: [] };
      groups.set(tool.entity, group);
    }
    group[tool.kind].push(tool);
  }
  return [...groups.values()].sort((left, right) => {
    const delta = groupPriority(left.entity) - groupPriority(right.entity);
    return delta !== 0 ? delta : left.label.localeCompare(right.label);
  });
}

function groupPriority(entity: string): number {
  const lower = (entity || '').toLowerCase();
  if (lower.includes('purchaserequisition')) return 0;
  if (lower.includes('purchaseorder')) return 1;
  if (lower.includes('material') || lower.includes('goodreceipt') || lower.includes('inbox')) {
    return 2;
  }
  if (lower.startsWith('yy1') || lower.includes('cfd') || lower.includes('unitofmeasure')) {
    return 9;
  }
  return 5;
}
