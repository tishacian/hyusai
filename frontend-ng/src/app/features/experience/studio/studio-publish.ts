/**
 * Publish dialog gating. Creating a release is blocked when ready-check
 * reports blockers, notes are empty, or a breaking diff was not acknowledged.
 * Deploy is a later step.
 */

import { parseDocument, textFallback, type ExperienceNode } from '../runtime/model';

export interface ReadyIssue {
  code?: string;
  message?: string;
  component_id?: string;
  binding_key?: string;
  path?: string;
}

export interface ReadyBindingEvidence {
  binding_key: string;
  system_id: string;
  published_flow_version_id: string;
  ingress_id: string;
  flow_sha256?: string | null;
  input_schema_sha256?: string | null;
  output_schema_sha256?: string | null;
  confirmation_policy: string;
  on_unavailable: string;
}

export interface ReadyCheck {
  ready: boolean;
  blockers: ReadyIssue[];
  warnings: ReadyIssue[];
  bindings_sha256: string;
  bindings: ReadyBindingEvidence[];
}

export type ReleaseDiffCategory = 'presentation' | 'behavior' | 'access';

export type ReleaseDiffCode =
  | 'page_added'
  | 'page_removed'
  | 'page_changed'
  | 'pages_reordered'
  | 'component_added'
  | 'component_removed'
  | 'component_type_changed'
  | 'component_behavior_changed'
  | 'component_presentation_changed'
  | 'components_reordered'
  | 'copy_changed'
  | 'binding_added'
  | 'binding_removed'
  | 'binding_changed'
  | 'languages_changed'
  | 'theme_changed'
  | 'access_changed';

export interface ReleaseDiffItem {
  category: ReleaseDiffCategory;
  code: ReleaseDiffCode;
  label: string;
  breaking: boolean;
  before?: readonly string[];
  after?: readonly string[];
  valueKind?: 'audience' | 'binding';
}

export interface ReleaseReviewSnapshot {
  pages: unknown;
  bindings: readonly ReadyBindingEvidence[];
  access: Record<string, unknown>;
  languages: readonly string[];
  theme: Record<string, unknown>;
}

const PRESENTATION_PROPS = new Set([
  'a11y',
  'accent',
  'citations',
  'columns',
  'density',
  'description',
  'empty_state',
  'error',
  'fieldPresentation',
  'items',
  'label',
  'loading',
  'position',
  'rows',
  'submitLabel',
  'theme',
  'title',
  'value',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? String(value);
}

function sameValue(left: unknown, right: unknown): boolean {
  return stableJson(left) === stableJson(right);
}

function componentKey(node: ExperienceNode, index: number): string {
  return node.id?.trim() || `${node.type}#${index + 1}`;
}

function componentLabel(node: ExperienceNode, index: number): string {
  for (const key of ['title', 'label', 'submitLabel']) {
    const value = node.props?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (isRecord(value) && typeof value['fallback'] === 'string' && value['fallback'].trim()) {
      return value['fallback'].trim();
    }
  }
  return node.id?.trim() || `${node.type} #${index + 1}`;
}

function splitProps(node: ExperienceNode): { behavior: Record<string, unknown>; presentation: Record<string, unknown> } {
  const behavior: Record<string, unknown> = {};
  const presentation: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(node.props ?? {})) {
    (PRESENTATION_PROPS.has(key) ? presentation : behavior)[key] = value;
  }
  return { behavior, presentation };
}

function hasBehavior(node: ExperienceNode): boolean {
  return Object.keys(splitProps(node).behavior).length > 0;
}

function normalizedStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((item): item is string => typeof item === 'string' && !!item.trim()).map((item) => item.trim()))].sort()
    : [];
}

function audienceTokens(policy: Record<string, unknown>): string[] {
  const roles = normalizedStrings(policy['roles']).map((item) => `role:${item}`);
  const groups = normalizedStrings(policy['groups']).map((item) => `group:${item}`);
  if (roles.length || groups.length) return [...roles, ...groups];
  return Object.keys(policy).length === 0 ? ['unset'] : ['everyone'];
}

function themeValues(theme: Record<string, unknown>): string[] {
  return Object.keys(theme).sort().map((key) => `${key}: ${String(theme[key])}`);
}

function bindingValue(binding: ReadyBindingEvidence): string[] {
  return [
    `system:${binding.system_id}`,
    `version:${binding.published_flow_version_id}`,
    `ingress:${binding.ingress_id}`,
    `confirmation:${binding.confirmation_policy}`,
    `unavailable:${binding.on_unavailable}`,
  ];
}

function diffPages(currentRaw: unknown, previousRaw: unknown): ReleaseDiffItem[] {
  const currentDocument = parseDocument(currentRaw);
  const previousDocument = parseDocument(previousRaw);
  const current = currentDocument.pages;
  const previous = previousDocument.pages;
  const currentById = new Map(current.map((page) => [page.id, page]));
  const previousById = new Map(previous.map((page) => [page.id, page]));
  const items: ReleaseDiffItem[] = [];

  for (const page of previous) {
    if (!currentById.has(page.id)) {
      items.push({ category: 'presentation', code: 'page_removed', label: textFallback(page.title), breaking: true });
    }
  }
  for (const page of current) {
    if (!previousById.has(page.id)) {
      items.push({ category: 'presentation', code: 'page_added', label: textFallback(page.title), breaking: false });
    }
  }
  if (
    current.length === previous.length
    && current.every((page) => previousById.has(page.id))
    && current.some((page, index) => previous[index]?.id !== page.id)
  ) {
    items.push({ category: 'presentation', code: 'pages_reordered', label: '', breaking: false });
  }

  for (const page of current) {
    const before = previousById.get(page.id);
    if (!before) continue;
    const pageLabel = textFallback(page.title);
    if (!sameValue(page.title, before.title) || !sameValue(page.props, before.props)) {
      items.push({ category: 'presentation', code: 'page_changed', label: pageLabel, breaking: false });
    }

    const currentNodes = page.components;
    const previousNodes = before.components;
    const currentNodesByKey = new Map(currentNodes.map((node, index) => [componentKey(node, index), { node, index }]));
    const previousNodesByKey = new Map(previousNodes.map((node, index) => [componentKey(node, index), { node, index }]));

    for (const [key, entry] of previousNodesByKey) {
      if (!currentNodesByKey.has(key)) {
        items.push({
          category: hasBehavior(entry.node) ? 'behavior' : 'presentation',
          code: 'component_removed',
          label: componentLabel(entry.node, entry.index),
          breaking: true,
        });
      }
    }
    for (const [key, entry] of currentNodesByKey) {
      if (!previousNodesByKey.has(key)) {
        items.push({
          category: hasBehavior(entry.node) ? 'behavior' : 'presentation',
          code: 'component_added',
          label: componentLabel(entry.node, entry.index),
          breaking: false,
        });
      }
    }
    if (
      currentNodes.length === previousNodes.length
      && [...currentNodesByKey.keys()].every((key) => previousNodesByKey.has(key))
      && currentNodes.some((node, index) => componentKey(node, index) !== componentKey(previousNodes[index]!, index))
    ) {
      items.push({ category: 'presentation', code: 'components_reordered', label: pageLabel, breaking: false });
    }

    for (const [key, entry] of currentNodesByKey) {
      const previousEntry = previousNodesByKey.get(key);
      if (!previousEntry) continue;
      const label = componentLabel(entry.node, entry.index);
      if (entry.node.type !== previousEntry.node.type) {
        items.push({
          category: 'behavior',
          code: 'component_type_changed',
          label,
          breaking: true,
          before: [previousEntry.node.type],
          after: [entry.node.type],
        });
        continue;
      }
      const afterProps = splitProps(entry.node);
      const beforeProps = splitProps(previousEntry.node);
      if (!sameValue(afterProps.behavior, beforeProps.behavior)) {
        items.push({ category: 'behavior', code: 'component_behavior_changed', label, breaking: true });
      }
      if (!sameValue(afterProps.presentation, beforeProps.presentation)) {
        items.push({ category: 'presentation', code: 'component_presentation_changed', label, breaking: false });
      }
    }
  }

  const currentI18n = isRecord(currentRaw) && isRecord(currentRaw['i18n']) ? currentRaw['i18n'] : {};
  const previousI18n = isRecord(previousRaw) && isRecord(previousRaw['i18n']) ? previousRaw['i18n'] : {};
  if (!sameValue(currentI18n, previousI18n)) {
    items.push({ category: 'presentation', code: 'copy_changed', label: '', breaking: false });
  }
  return items;
}

/** Compare the reviewed draft with the last immutable release, not with editor history. */
export function releaseSemanticDiff(
  current: ReleaseReviewSnapshot,
  previous: ReleaseReviewSnapshot,
): ReleaseDiffItem[] {
  const items = diffPages(current.pages, previous.pages);
  const currentBindings = new Map(current.bindings.map((binding) => [binding.binding_key, binding]));
  const previousBindings = new Map(previous.bindings.map((binding) => [binding.binding_key, binding]));

  for (const [key, binding] of previousBindings) {
    if (!currentBindings.has(key)) {
      items.push({ category: 'behavior', code: 'binding_removed', label: key, breaking: true });
    }
  }
  for (const [key, binding] of currentBindings) {
    const before = previousBindings.get(key);
    if (!before) {
      items.push({ category: 'behavior', code: 'binding_added', label: key, breaking: false });
    } else if (!sameValue(binding, before)) {
      items.push({
        category: 'behavior',
        code: 'binding_changed',
        label: key,
        breaking: true,
        before: bindingValue(before),
        after: bindingValue(binding),
        valueKind: 'binding',
      });
    }
  }

  const currentLanguages = normalizedStrings(current.languages);
  const previousLanguages = normalizedStrings(previous.languages);
  if (!sameValue(currentLanguages, previousLanguages)) {
    items.push({
      category: 'presentation',
      code: 'languages_changed',
      label: '',
      breaking: previousLanguages.some((language) => !currentLanguages.includes(language)),
      before: previousLanguages,
      after: currentLanguages,
    });
  }
  if (!sameValue(current.theme, previous.theme)) {
    items.push({
      category: 'presentation',
      code: 'theme_changed',
      label: '',
      breaking: false,
      before: themeValues(previous.theme),
      after: themeValues(current.theme),
    });
  }
  if (!sameValue(audienceTokens(current.access), audienceTokens(previous.access))) {
    items.push({
      category: 'access',
      code: 'access_changed',
      label: '',
      breaking: true,
      before: audienceTokens(previous.access),
      after: audienceTokens(current.access),
      valueKind: 'audience',
    });
  }
  return items;
}

export function canCreateRelease(input: {
  blockers: readonly unknown[];
  notes: string;
  breakingChanges?: readonly unknown[];
  breakingAcknowledged?: boolean;
}): boolean {
  return input.blockers.length === 0
    && input.notes.trim().length > 0
    && (!(input.breakingChanges?.length) || input.breakingAcknowledged === true);
}

export function canDeploy(input: { releaseId: string | null | undefined; channel: string }): boolean {
  return !!input.releaseId && (input.channel === 'pilot' || input.channel === 'live');
}
