/**
 * Missions page (`/tasks`) — goal-oriented background tasks:
 * plan → act → verify → report.
 *
 * `tasks.status.<value>` mirrors the API's task/step statuses, so lookups
 * by value work with the mandatory raw-value fallback (CONVENTION.md §3).
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const TASKS_FR = {
  'tasks.eyebrow': 'Exécuter · Missions',
  'tasks.title': 'Missions autonomes',
  'tasks.description':
    'Des tâches orientées objectif : planifier → agir → vérifier → rendre compte — exécutées en arrière-plan.',
  'tasks.new.cta': 'Nouvelle mission',
  'tasks.stats.total': 'Total',

  // --- Statuses (mirror the API values) -----------------------------
  'tasks.status.pending': 'En attente',
  'tasks.status.running': 'En cours',
  'tasks.status.in_progress': 'En cours',
  'tasks.status.completed': 'Terminée',
  'tasks.status.failed': 'Échec',

  // --- List ----------------------------------------------------------
  'tasks.recent.title': 'Missions récentes',
  'tasks.empty.title': "Aucune mission pour l'instant",
  'tasks.empty.description':
    "Lancez une mission d'agent autonome pour automatiser un travail en plusieurs étapes.",

  // --- Create dialog ---------------------------------------------------
  'tasks.create.heading': 'Nouvelle mission autonome',
  'tasks.create.description':
    "Décrivez l'objectif. L'agent va planifier, exécuter et rendre compte.",
  'tasks.create.title.placeholder': 'Titre (optionnel)',
  'tasks.create.goal.placeholder': "Décrivez ce que l'agent doit accomplir…",
  'tasks.create.routing.default': 'Routage par défaut',
  'tasks.create.submit': 'Créer et exécuter',

  // --- Detail drawer ---------------------------------------------------
  'tasks.detail.run': 'Exécuter',
  'tasks.detail.rerun': 'Relancer',
  'tasks.detail.goal': 'Objectif',
  'tasks.detail.progress': 'Progression',
  'tasks.detail.steps': 'Étapes',
  'tasks.detail.waiting': 'En attente du plan…',
  'tasks.detail.step.fallback': 'étape',
  'tasks.detail.output': 'sortie',
  'tasks.detail.artifacts': 'Artefacts',
  'tasks.detail.error': 'Erreur',
  'tasks.detail.error.unknown': 'Erreur inconnue',

  // --- Toasts ----------------------------------------------------------
  'tasks.toast.title': 'Tâches',
  'tasks.toast.queued': "Mission mise en file d'attente",
  'tasks.toast.create.error': 'Échec de la création',
  'tasks.toast.stream.error': 'Erreur du flux de mission',
  'tasks.toast.complete': 'Mission terminée',
  'tasks.toast.failed': 'Échec de la mission',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof TASKS_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const TASKS_EN: Record<keyof typeof TASKS_FR, string> = {
  'tasks.eyebrow': 'Run · Missions',
  'tasks.title': 'Autonomous missions',
  'tasks.description':
    'Goal-oriented tasks: plan → act → verify → report — running in the background.',
  'tasks.new.cta': 'New mission',
  'tasks.stats.total': 'Total',

  // --- Statuses (mirror the API values) -----------------------------
  'tasks.status.pending': 'Pending',
  'tasks.status.running': 'Running',
  'tasks.status.in_progress': 'In progress',
  'tasks.status.completed': 'Completed',
  'tasks.status.failed': 'Failed',

  // --- List ----------------------------------------------------------
  'tasks.recent.title': 'Recent missions',
  'tasks.empty.title': 'No missions yet',
  'tasks.empty.description':
    'Launch an autonomous agent mission to automate multi-step work.',

  // --- Create dialog ---------------------------------------------------
  'tasks.create.heading': 'New autonomous mission',
  'tasks.create.description':
    'Describe the goal. The agent will plan, execute and report.',
  'tasks.create.title.placeholder': 'Title (optional)',
  'tasks.create.goal.placeholder': 'Describe what the agent should achieve…',
  'tasks.create.routing.default': 'Default routing',
  'tasks.create.submit': 'Create & run',

  // --- Detail drawer ---------------------------------------------------
  'tasks.detail.run': 'Run',
  'tasks.detail.rerun': 'Rerun',
  'tasks.detail.goal': 'Goal',
  'tasks.detail.progress': 'Progress',
  'tasks.detail.steps': 'Steps',
  'tasks.detail.waiting': 'Waiting for the plan…',
  'tasks.detail.step.fallback': 'step',
  'tasks.detail.output': 'output',
  'tasks.detail.artifacts': 'Artifacts',
  'tasks.detail.error': 'Error',
  'tasks.detail.error.unknown': 'Unknown error',

  // --- Toasts ----------------------------------------------------------
  'tasks.toast.title': 'Tasks',
  'tasks.toast.queued': 'Mission queued',
  'tasks.toast.create.error': 'Failed to create',
  'tasks.toast.stream.error': 'Mission stream error',
  'tasks.toast.complete': 'Mission complete',
  'tasks.toast.failed': 'Mission failed',
};
