/** Reapply only local edits onto the latest document, after the author has
 * reviewed base, local and remote versions. Stable node ids survive reordering. */
export interface StudioConflictMerge { value: unknown; conflicts: string[]; }

const same = (left: unknown, right: unknown): boolean => JSON.stringify(left) === JSON.stringify(right);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const keyed = (value: unknown): value is Array<Record<string, unknown> & { id: string }> => Array.isArray(value)
  && value.every(item => record(item) && typeof item['id'] === 'string')
  && new Set(value.map(item => item.id)).size === value.length;

export function reapplyStudioChanges(base: unknown, mine: unknown, theirs: unknown): StudioConflictMerge {
  const conflicts: string[] = [];
  const merge = (before: unknown, local: unknown, remote: unknown, path: string): unknown => {
    if (same(local, before)) return remote;
    if (same(remote, before) || same(local, remote)) return local;
    if (record(before) && record(local) && record(remote)) {
      const result: Record<string, unknown> = {};
      for (const key of new Set([...Object.keys(before), ...Object.keys(local), ...Object.keys(remote)])) {
        const value = merge(before[key], local[key], remote[key], `${path}/${key}`);
        if (value !== undefined) result[key] = value;
      }
      return result;
    }
    if (keyed(before) && keyed(local) && keyed(remote)) {
      const oldById = new Map(before.map(item => [item.id, item]));
      const localById = new Map(local.map(item => [item.id, item]));
      const remoteById = new Map(remote.map(item => [item.id, item]));
      const sharedIds = new Set(before.filter(item => localById.has(item.id) && remoteById.has(item.id)).map(item => item.id));
      const order = (rows: Array<{ id: string }>) => rows.filter(item => sharedIds.has(item.id)).map(item => item.id);
      if (!same(order(local), order(before)) && !same(order(remote), order(before)) && !same(order(local), order(remote))) {
        conflicts.push(`${path}/$order`);
      }
      const localOrderChanged = !same(local.map(item => item.id), before.map(item => item.id));
      const primary = localOrderChanged ? local : remote;
      const secondary = localOrderChanged ? remote : local;
      const ids = [...new Set([...primary, ...secondary].map(item => item.id))];
      return ids.map(id => merge(oldById.get(id), localById.get(id), remoteById.get(id), `${path}/${id}`)).filter(value => value !== undefined);
    }
    conflicts.push(path || '/');
    return local;
  };
  return { value: merge(base, mine, theirs, ''), conflicts };
}

export interface StudioConflictDescription {
  path: string;
  context: string[];
  field: string;
  values: unknown[];
}

/** Resolve stable ids into page and component headings without changing merge semantics. */
export function describeStudioConflict(path: string, base: unknown, mine: unknown, theirs: unknown, locale = ''): StudioConflictDescription {
  const parts = path.split('/').filter(Boolean);
  const documents = [base, mine, theirs];
  let cursors: unknown[] = [...documents];
  const context: string[] = [];
  const localized = (value: unknown, document: unknown): unknown => {
    if (!record(value) || typeof value['$i18n'] !== 'string' || typeof value['fallback'] !== 'string') return value;
    const dictionaries = record(document) && record(document['i18n']) ? document['i18n'] : {};
    const dictionary = record(dictionaries[locale]) ? dictionaries[locale] : {};
    const translated = dictionary[value['$i18n']];
    return typeof translated === 'string' ? translated : value['fallback'];
  };
  const title = (value: unknown, document: unknown): string => {
    if (!record(value)) return '';
    const props = record(value['props']) ? value['props'] : {};
    for (const raw of [value['title'], props['title'], props['label'], props['caption']]) {
      const candidate = localized(raw, document);
      if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    }
    return '';
  };
  for (const part of parts) {
    if (part === '$order') {
      cursors = cursors.map((value, index) => Array.isArray(value) ? value.map(item => title(item, documents[index]) || (record(item) ? item['id'] : '')) : value);
      break;
    }
    const isItem = cursors.some(Array.isArray);
    cursors = cursors.map(value => Array.isArray(value)
      ? value.find(item => record(item) && item['id'] === part)
      : record(value) ? value[part] : undefined);
    if (isItem) {
      const name = title(cursors[1], mine) || title(cursors[2], theirs) || title(cursors[0], base);
      if (name) context.push(name);
    }
  }
  return { path, context, field: parts.at(-1) ?? '', values: cursors.map((value, index) => localized(value, documents[index])) };
}
