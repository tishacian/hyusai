/**
 * Runs: list, detail, run statuses.
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const RUNS_FR = {
  'runs.title': 'Exécutions',
  'runs.empty': 'Aucune exécution récente.',
  'runs.status.running': 'En cours',
  'runs.status.completed': 'Terminé',
  'runs.status.failed': 'Échec',
  'runs.status.cancelled': 'Annulé',
  'runs.status.pending': 'En attente',
  'runs.status.hitl_pending': 'En attente humaine',
  'runs.status.debug_pending': 'Pause debug',

  // --- Runs list ---------------------------------------------------
  'runs.list.eyebrow': 'Mesurer · Exécutions',
  'runs.list.description':
    "Chaque exécution est un Run : son entrée, son résultat, sa trace de skills. Cliquez une ligne pour l'ouvrir.",
  'runs.list.filter.all': 'Tous les statuts',
  'runs.list.empty.title': 'Aucune exécution',
  'runs.list.empty.description': 'Déclenchez une exécution depuis un Système pour remplir cette liste.',
  'runs.list.column.identity': 'ID · Système',
  'runs.list.column.status': 'Statut',
  'runs.list.column.started': 'Démarré',
  'runs.list.column.duration': 'Durée',
  'runs.list.column.outcome': 'Résultat',
  'runs.list.column.cost': 'Coût',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof RUNS_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const RUNS_EN: Record<keyof typeof RUNS_FR, string> = {
  'runs.title': 'Runs',
  'runs.empty': 'No recent runs.',
  'runs.status.running': 'Running',
  'runs.status.completed': 'Completed',
  'runs.status.failed': 'Failed',
  'runs.status.cancelled': 'Cancelled',
  'runs.status.pending': 'Pending',
  'runs.status.hitl_pending': 'Awaiting operator',
  'runs.status.debug_pending': 'Debug pause',

  // --- Runs list ---------------------------------------------------
  'runs.list.eyebrow': 'Measure · Runs',
  'runs.list.description':
    'Every execution is a Run: its input, its outcome, its skill trail. Click a row to open it.',
  'runs.list.filter.all': 'All statuses',
  'runs.list.empty.title': 'No runs yet',
  'runs.list.empty.description': 'Trigger a run from a System to populate this list.',
  'runs.list.column.identity': 'ID · System',
  'runs.list.column.status': 'Status',
  'runs.list.column.started': 'Started',
  'runs.list.column.duration': 'Duration',
  'runs.list.column.outcome': 'Outcome',
  'runs.list.column.cost': 'Cost',
};
