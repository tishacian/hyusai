/**
 * Rule-based Studio assistant. Chat/completion is a full session stream,
 * not a one-shot patch client — intents stay local and the label stays honest.
 *
 * A JSON object `{ op, targetId, props? }` is accepted the same way, then
 * validated against the certified catalog (no unknown types, no absolute layout).
 */

import type { ExperienceDocument } from '../runtime/model';
import { a11yPayload } from '../runtime/style';
import { applyPatch, findNode, isCertified, type DocumentPatch } from './studio-document';

export interface AssistantProposal {
  summary: string;
  patch: DocumentPatch;
  before: ExperienceDocument;
  after: ExperienceDocument;
}

const EMPTY = /empty[-\s]?state|état vide|etat vide|empty state|aucun[e]?\s+élément|nothing (?:here|to show)|état\s+vide/i;
const RENAME = /renomm(?:er|e)|rename/i;
const APPROVAL = /approval[_\s-]?card|carte d['’]approbation|approbation/i;
const COMPACT = /compact|compacte/i;
const COMFY = /comfortable|confortable/i;
const TITLE = /(?:titre|title)\s/i;
const LAYOUT_KEYS = new Set([
  'position',
  'top',
  'left',
  'right',
  'bottom',
  'x',
  'y',
  'absolute',
  'transform',
]);

export function proposeAssistantPatch(
  prompt: string,
  doc: ExperienceDocument,
  pageId: string,
  labels: { empty: string; approvalTitle: string; approvalBody: string },
  targetId?: string | null,
): AssistantProposal | null {
  const text = prompt.trim();
  if (!text) return null;
  const page = doc.pages.find((item) => item.id === pageId) ?? doc.pages[0];
  if (!page) return null;

  const fromJson = tryJsonPatch(text, doc, page.id);
  if (fromJson) return wrap(doc, fromJson, 'json_patch');

  let patch: DocumentPatch | null = null;
  let summary = '';
  if (EMPTY.test(text)) {
    const selected = targetId ? findNode(doc, targetId) : null;
    if (selected && needsEmpty(selected.node.type)) {
      patch = {
        kind: 'update_node',
        pageId: selected.pageId,
        nodeId: selected.node.id ?? targetId,
        props: { a11y: a11yPayload(selected.node, 'emptyText', labels.empty) },
      };
      summary = 'set_empty_state';
    } else {
      patch = { kind: 'set_empty_state', pageId: page.id, body: labels.empty };
      summary = 'set_empty_state';
    }
  } else if (RENAME.test(text)) {
    const title = quoted(text) || trailingName(text) || page.title;
    patch = { kind: 'rename_page', pageId: page.id, title };
    summary = 'rename_page';
  } else if (APPROVAL.test(text)) {
    patch = {
      kind: 'add_approval_card',
      pageId: page.id,
      title: labels.approvalTitle,
      body: labels.approvalBody,
    };
    summary = 'add_approval_card';
  } else if (COMPACT.test(text) || COMFY.test(text)) {
    const density = COMPACT.test(text) ? 'compact' : 'comfortable';
    const selected = targetId ? findNode(doc, targetId) : null;
    if (selected?.node.id) {
      patch = {
        kind: 'update_node',
        pageId: selected.pageId,
        nodeId: selected.node.id,
        props: { density },
      };
    } else {
      patch = { kind: 'update_page', pageId: page.id, props: { density } };
    }
    summary = 'set_density';
  } else if (TITLE.test(text) && targetId) {
    const selected = findNode(doc, targetId);
    const title = quoted(text);
    if (selected?.node.id && title) {
      patch = {
        kind: 'update_node',
        pageId: selected.pageId,
        nodeId: selected.node.id,
        props: { title },
      };
      summary = 'update_props';
    }
  }
  if (!patch || !acceptAssistantPatch(patch)) return null;
  return wrap(doc, patch, summary);
}

export function patchFromJson(
  raw: unknown,
  doc: ExperienceDocument,
  pageId: string,
): DocumentPatch | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const rec = raw as Record<string, unknown>;
  const op = typeof rec['op'] === 'string' ? rec['op'] : '';
  const targetId = typeof rec['targetId'] === 'string' ? rec['targetId'] : '';
  const props = isRecord(rec['props']) ? rec['props'] : undefined;
  if (hasForbiddenLayout(props)) return null;

  if (op === 'update') {
    const found = findNode(doc, targetId);
    if (!found?.node.id) return null;
    const patch: DocumentPatch = {
      kind: 'update_node',
      pageId: found.pageId,
      nodeId: found.node.id,
      props: props ?? {},
    };
    return acceptAssistantPatch(patch) ? patch : null;
  }
  if (op === 'add') {
    const type =
      (typeof rec['type'] === 'string' && rec['type'])
      || (typeof props?.['type'] === 'string' ? String(props['type']) : '');
    if (!isCertified(type)) return null;
    const page = doc.pages.find((item) => item.id === targetId) ?? doc.pages.find((item) => item.id === pageId);
    if (!page) return null;
    const rest = { ...(props ?? {}) };
    delete rest['type'];
    const patch: DocumentPatch = {
      kind: 'add_component',
      pageId: page.id,
      node: { type, props: rest },
    };
    return acceptAssistantPatch(patch) ? patch : null;
  }
  if (op === 'rename') {
    const title =
      (typeof rec['title'] === 'string' && rec['title'])
      || (typeof props?.['title'] === 'string' ? String(props['title']) : '');
    if (!title.trim()) return null;
    const page = doc.pages.find((item) => item.id === targetId) ?? doc.pages.find((item) => item.id === pageId);
    if (!page) return null;
    return { kind: 'rename_page', pageId: page.id, title };
  }
  return null;
}

export function acceptAssistantPatch(patch: DocumentPatch): boolean {
  if (patch.kind === 'add_component') {
    return isCertified(patch.node.type) && !hasForbiddenLayout(patch.node.props);
  }
  if (patch.kind === 'update_node') return !hasForbiddenLayout(patch.props);
  if (patch.kind === 'update_page') return !hasForbiddenLayout(patch.props);
  return true;
}

export function hasForbiddenLayout(props?: Record<string, unknown>): boolean {
  if (!props) return false;
  if (Object.keys(props).some((key) => LAYOUT_KEYS.has(key))) return true;
  return props['position'] === 'absolute';
}

function tryJsonPatch(text: string, doc: ExperienceDocument, pageId: string): DocumentPatch | null {
  if (!text.startsWith('{')) return null;
  try {
    return patchFromJson(JSON.parse(text) as unknown, doc, pageId);
  } catch {
    return null;
  }
}

function wrap(doc: ExperienceDocument, patch: DocumentPatch, summary: string): AssistantProposal {
  return { summary, patch, before: doc, after: applyPatch(doc, patch) };
}

function needsEmpty(type: string): boolean {
  return type === 'form' || type === 'table' || type === 'queue' || type === 'approval_card';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function quoted(text: string): string {
  const match = text.match(/[«"“']([^»"”']+)[»"”']/) || text.match(/\s(?:en|to)\s+(.+)$/i);
  return (match?.[1] ?? '').trim();
}

function trailingName(text: string): string {
  const match = text.match(/(?:renomm(?:er|e)|rename)\s+(?:la\s+page\s+|page\s+)?(.+)$/i);
  return (match?.[1] ?? '').replace(/^["«']|["»']$/g, '').trim();
}
