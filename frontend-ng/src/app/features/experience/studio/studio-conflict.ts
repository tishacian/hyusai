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
