/**
 * Earlier builds kept every value typed in the generic connector drawer —
 * client secrets, tokens, API keys and passwords included — in `localStorage`:
 * one legacy slot, then one slot per workspace visited. Connector setup now
 * lives on the server only (`/api/v1/connectors`, secrets write-only).
 */
const RETIRED_CONNECTORS_KEY = 'agentium:connectors:v1';

/** Remove every such slot, whichever workspace wrote it. */
export function purgeRetiredConnectorStorage(
  storage?: Pick<Storage, 'length' | 'key' | 'removeItem'>,
): void {
  try {
    // Reading `localStorage` itself throws when the browser blocks storage.
    const target = storage ?? localStorage;
    const retired: string[] = [];
    for (let index = 0; index < target.length; index += 1) {
      const key = target.key(index);
      if (key !== null && (key === RETIRED_CONNECTORS_KEY || key.startsWith(`${RETIRED_CONNECTORS_KEY}:`))) {
        retired.push(key);
      }
    }
    for (const key of retired) target.removeItem(key);
  } catch {
    // No storage, so nothing can have been kept there.
  }
}
