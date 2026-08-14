/**
 * Constrained document edits + an in-memory revision stack.
 * No freeform layout — pages stay a list of certified nodes.
 */

import { CERTIFIED_TYPES, parseDocument, type ExperienceDocument, type ExperienceNode } from '../runtime/model';

export type DocumentPatch =
  | { kind: 'add_component'; pageId: string; node: ExperienceNode }
  | { kind: 'remove_component'; pageId: string; nodeId: string }
  | { kind: 'rename_page'; pageId: string; title: string }
  | { kind: 'set_empty_state'; pageId: string; body: string }
  | { kind: 'add_approval_card'; pageId: string; title: string; body: string }
  | { kind: 'update_node'; pageId: string; nodeId: string; props: Record<string, unknown> }
  | { kind: 'update_page'; pageId: string; props: Record<string, unknown> };

export interface RevisionStack {
  past: ExperienceDocument[];
  present: ExperienceDocument;
  future: ExperienceDocument[];
}

const LIMIT = 40;

export function cloneDocument(doc: ExperienceDocument): ExperienceDocument {
  return JSON.parse(JSON.stringify(doc)) as ExperienceDocument;
}

export function hydrateDocument(raw: unknown): ExperienceDocument {
  const doc = parseDocument(raw);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return doc;
  const pages = (raw as Record<string, unknown>)['pages'];
  if (!Array.isArray(pages)) return doc;
  for (let i = 0; i < doc.pages.length; i++) {
    const rawPage = pages[i];
    if (!rawPage || typeof rawPage !== 'object' || Array.isArray(rawPage)) continue;
    const comps = (rawPage as Record<string, unknown>)['components'];
    if (!Array.isArray(comps)) continue;
    const page = doc.pages[i];
    if (!page) continue;
    for (let j = 0; j < page.components.length; j++) {
      const rawNode = comps[j];
      if (!rawNode || typeof rawNode !== 'object' || Array.isArray(rawNode)) continue;
      if ((rawNode as Record<string, unknown>)['empty_state'] !== true) continue;
      const node = page.components[j];
      if (!node) continue;
      node.props = { ...(node.props ?? {}), empty_state: true };
    }
  }
  return doc;
}

export function emptyStack(present: ExperienceDocument): RevisionStack {
  return { past: [], present: cloneDocument(present), future: [] };
}

export function pushRevision(stack: RevisionStack, next: ExperienceDocument): RevisionStack {
  const past = [...stack.past, cloneDocument(stack.present)];
  if (past.length > LIMIT) past.shift();
  return { past, present: cloneDocument(next), future: [] };
}

export function undoRevision(stack: RevisionStack): RevisionStack {
  const previous = stack.past[stack.past.length - 1];
  if (!previous) return stack;
  return {
    past: stack.past.slice(0, -1),
    present: cloneDocument(previous),
    future: [cloneDocument(stack.present), ...stack.future],
  };
}

export function redoRevision(stack: RevisionStack): RevisionStack {
  const next = stack.future[0];
  if (!next) return stack;
  return {
    past: [...stack.past, cloneDocument(stack.present)],
    present: cloneDocument(next),
    future: stack.future.slice(1),
  };
}

export function applyPatch(doc: ExperienceDocument, patch: DocumentPatch): ExperienceDocument {
  const next = cloneDocument(doc);
  const page = next.pages.find((item) => item.id === patch.pageId);
  if (!page) return next;
  switch (patch.kind) {
    case 'add_component':
      if (!isCertified(patch.node.type)) return next;
      page.components = [...page.components, { ...patch.node, id: patch.node.id || newNodeId(patch.node.type) }];
      return next;
    case 'remove_component':
      page.components = page.components.filter((node) => node.id !== patch.nodeId);
      return next;
    case 'rename_page': {
      const title = patch.title.trim();
      if (title) page.title = title;
      return next;
    }
    case 'set_empty_state': {
      const existing = page.components.find(
        (node) => node.id === 'empty-state' || node.props?.['empty_state'] === true,
      );
      if (existing) {
        existing.props = { ...(existing.props ?? {}), body: patch.body, empty_state: true };
        return next;
      }
      page.components = [
        ...page.components,
        {
          type: 'callout',
          id: 'empty-state',
          props: { body: patch.body, empty_state: true },
        },
      ];
      return next;
    }
    case 'add_approval_card':
      if (page.components.some((node) => node.type === 'approval_card')) return next;
      page.components = [
        ...page.components,
        {
          type: 'approval_card',
          id: newNodeId('approval_card'),
          props: { title: patch.title, body: patch.body },
        },
      ];
      return next;
    case 'update_node': {
      page.components = page.components.map((node) =>
        node.id === patch.nodeId
          ? { ...node, props: { ...(node.props ?? {}), ...patch.props } }
          : node,
      );
      return next;
    }
    case 'update_page':
      page.props = { ...(page.props ?? {}), ...patch.props };
      return next;
  }
}

export function applyPatchOnStack(stack: RevisionStack, patch: DocumentPatch): RevisionStack {
  return pushRevision(stack, applyPatch(stack.present, patch));
}

export function newNodeId(type: string): string {
  return `${type}-${Math.random().toString(36).slice(2, 8)}`;
}

export function isCertified(type: string): boolean {
  return (CERTIFIED_TYPES as readonly string[]).includes(type);
}

export function findNode(
  doc: ExperienceDocument,
  nodeId: string | null,
): { pageId: string; node: ExperienceNode } | null {
  if (!nodeId) return null;
  for (const page of doc.pages) {
    const node = page.components.find((item) => item.id === nodeId);
    if (node) return { pageId: page.id, node };
  }
  return null;
}

export function pagesPayload(doc: ExperienceDocument): Record<string, unknown> {
  return {
    pages: doc.pages.map((page) => ({
      id: page.id,
      title: page.title,
      props: page.props ?? {},
      components: page.components.map((node) => {
        const payload: Record<string, unknown> = {
          type: node.type,
          id: node.id,
          props: node.props ?? {},
        };
        if (node.props?.['empty_state'] === true) payload['empty_state'] = true;
        return payload;
      }),
    })),
  };
}
