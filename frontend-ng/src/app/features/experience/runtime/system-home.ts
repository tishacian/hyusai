/**
 * Compile a baseline form_result Experience document from a published
 * execution contract. Pure: the publication panel and the preview page
 * both call this; nothing here talks to Angular or HTTP.
 */

import type { ExperienceDocument, ExperienceNode } from './model';

export interface ContractIngress {
  ingress_id: string;
  source_node_id?: string;
  kind: string;
  input_schema?: unknown;
}

export interface SystemHomeLabels {
  subtitle: string;
  submit: string;
  missingEntry: string;
  approvalTitle: string;
  approvalBody: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function firstManualIngress(contract: unknown): ContractIngress | null {
  if (!isRecord(contract)) return null;
  const raw = contract['ingresses'];
  if (!Array.isArray(raw)) return null;
  for (const item of raw) {
    if (!isRecord(item) || item['kind'] !== 'manual') continue;
    if (typeof item['ingress_id'] !== 'string' || !item['ingress_id']) continue;
    return {
      ingress_id: item['ingress_id'],
      source_node_id:
        typeof item['source_node_id'] === 'string' ? item['source_node_id'] : undefined,
      kind: 'manual',
      input_schema: item['input_schema'],
    };
  }
  return null;
}

export function hasHitlHint(
  contract: unknown,
  graphKinds: readonly string[] = [],
): boolean {
  if (graphKinds.includes('hitl')) return true;
  if (!isRecord(contract)) return false;
  const raw = contract['ingresses'];
  if (!Array.isArray(raw)) return false;
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const id = String(item['ingress_id'] ?? '');
    const source = String(item['source_node_id'] ?? '');
    if (/hitl/i.test(id) || /hitl/i.test(source)) return true;
  }
  return false;
}

export function slugify(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function headedSlug(name: string): string {
  const base = slugify(name);
  if (!base) return 'app';
  return /^[a-z]/.test(base) ? base : `app-${base}`;
}

export function uniqueSlug(name: string, nonce: string): string {
  return `${headedSlug(name)}-${nonce}`.slice(0, 120);
}

export function uniqueBindingKey(name: string, ingressId: string, nonce: string): string {
  const ingress = slugify(ingressId).replace(/-/g, '.') || 'submit';
  return `home.${headedSlug(name)}.${ingress}.${nonce}`.slice(0, 120);
}

export function compileSystemHome(input: {
  systemName: string;
  bindingKey: string;
  ingress: ContractIngress | null;
  hasHitl: boolean;
  labels: SystemHomeLabels;
}): ExperienceDocument {
  const title = input.systemName.trim();
  const components: ExperienceNode[] = [
    {
      type: 'header',
      id: 'home-head',
      props: { title, subtitle: input.labels.subtitle },
    },
  ];
  if (input.ingress) {
    components.push({
      type: 'form',
      id: 'home-form',
      props: {
        bindingKey: input.bindingKey,
        schema: input.ingress.input_schema ?? { type: 'object', properties: {} },
      },
    });
    components.push({
      type: 'action_button',
      id: 'home-action',
      props: { bindingKey: input.bindingKey, label: input.labels.submit },
    });
  } else {
    components.push({
      type: 'callout',
      id: 'home-missing',
      props: { body: input.labels.missingEntry },
    });
  }
  if (input.hasHitl) {
    components.push({
      type: 'approval_card',
      id: 'home-approval',
      props: {
        title: input.labels.approvalTitle,
        body: input.labels.approvalBody,
      },
    });
  }
  components.push(
    { type: 'runtime_status', id: 'home-status' },
    { type: 'result', id: 'home-result' },
    { type: 'evidence', id: 'home-evidence' },
    { type: 'history', id: 'home-history' },
  );
  return {
    pages: [
      {
        id: 'form_result',
        title,
        components,
      },
    ],
  };
}
