/**
 * Pure view helpers for the Systems list (`/systems`).
 */
import type { SystemAgent } from './systems.store';

export type SystemCategoryFilter = 'business' | 'model_operations' | 'all';

export function systemCategory(system: Pick<SystemAgent, 'category' | 'settings'>): 'business' | 'model_operations' {
  if (system.category) return system.category;
  const modelId = system.settings?.['ml_monitoring_model_id'];
  return typeof modelId === 'string' && !!modelId.trim() ? 'model_operations' : 'business';
}

export function filterSystems<T extends Pick<SystemAgent, 'category' | 'settings'>>(systems: T[], filter: SystemCategoryFilter): T[] {
  return filter === 'all' ? systems : systems.filter(system => systemCategory(system) === filter);
}

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
