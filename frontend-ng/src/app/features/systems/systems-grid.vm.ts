/**
 * Pure view helpers for the Systems list (`/systems`).
 */

/**
 * « 0 actif », « 1 actif », « 3 actifs ». French keeps the singular for zero
 * and one; English "active" never changes, so both keys carry the same EN
 * value. The i18n service has no plural rule, hence the `_one` key.
 */
export function activeSystemsKey(count: number): 'systems.grid.status_active_one' | 'systems.grid.status_active' {
  return Math.abs(count) < 2 ? 'systems.grid.status_active_one' : 'systems.grid.status_active';
}

/**
 * One filled button per view (Tokens v2). With no System yet, the empty
 * state's « Créer le premier système » is the primary action and the header
 * « Nouveau système » steps back to secondary; once the list has Systems,
 * the header button leads again.
 */
export function systemsPrimaryAction(state: { loading: boolean; problem: boolean; count: number }): 'header' | 'empty-state' {
  return !state.loading && !state.problem && state.count === 0 ? 'empty-state' : 'header';
}
