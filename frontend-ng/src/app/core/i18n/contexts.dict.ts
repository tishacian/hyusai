/**
 * Contexts — versioned bags of state attached to Systems (list + detail).
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const CONTEXTS_FR = {
  // --- List page -------------------------------------------------------
  'contexts.page.eyebrow': 'Steer · Contextes',
  'contexts.page.title': 'Contextes',
  'contexts.page.subtitle':
    'Des ensembles d’état versionnés attachés aux Systèmes. Chaque Exécution référence un instantané de Contexte.',
  'contexts.page.new_via_builder': 'Nouveau via le Builder',
  'contexts.kpi.total': 'Total',
  'contexts.kpi.total_hint': 'Tous les contextes de ce workspace.',
  'contexts.kpi.pinned': 'Épinglés',
  'contexts.kpi.pinned_hint': 'Référencés par au moins un Système.',
  'contexts.kpi.unused': 'Inutilisés',
  'contexts.kpi.unused_hint': 'Contextes orphelins qu’aucun Système ne référence.',
  'contexts.kpi.stale': 'Remaniés v3+',
  'contexts.kpi.stale_hint': 'Contextes modifiés 3 fois ou plus.',
  'contexts.empty.title': 'Aucun contexte pour l’instant',
  'contexts.empty.description': 'Les contextes se créent avec un nouveau système (étape Contexte).',
  'contexts.empty.open_builder': 'Créer un système',
  'contexts.list.in_use': 'Utilisé',
  'contexts.list.orphan': 'Orphelin',
  'contexts.list.system_col': 'Système',
  'contexts.list.last_run': 'Dernière exécution',
  'contexts.list.meta': '{data} données · {mem} mém. · {systems} systèmes',
  // --- Detail view -------------------------------------------------------
  'contexts.view.eyebrow': 'Contextes · Contexte',
  'contexts.view.title_fallback': 'Contexte',
  'contexts.view.subtitle_one':
    '{data} réfs de données · {memory} réfs mémoire · 1 Système lié.',
  'contexts.view.subtitle_many':
    '{data} réfs de données · {memory} réfs mémoire · {systems} Systèmes liés.',
  'contexts.view.impact': 'Impact',
  'contexts.view.loading': 'Chargement du contexte…',
  'contexts.view.facets_aria': 'Facettes du contexte',
  'contexts.view.tab.overview': 'Aperçu',
  'contexts.view.tab.data': 'Réfs de données',
  'contexts.view.tab.memory': 'Réfs mémoire',
  'contexts.view.tab.permissions': 'Permissions',
  'contexts.view.tab.systems': 'Systèmes',
  'contexts.view.name': 'Nom',
  'contexts.view.version': 'Version',
  'contexts.view.created': 'Créé',
  'contexts.view.save_name': 'Enregistrer le nom',
  'contexts.view.data_description':
    'Les collections de connaissances que les Exécutions s’appuyant sur ce Contexte peuvent citer.',
  'contexts.view.data_placeholder': 'nom de la collection',
  'contexts.view.memory_description':
    'Les compartiments de mémoire persistante (historiques de chat, bases vectorielles) que le Contexte ouvre à l’exécution.',
  'contexts.view.memory_placeholder': 'clé mémoire',
  'contexts.view.remove': 'Retirer',
  'contexts.view.add_ref': 'Ajouter une réf',
  'contexts.view.save_refs': 'Enregistrer les réfs',
  'contexts.view.permissions_description':
    'Permissions libres (JSON). Consommées par le moteur d’exécution pour contrôler l’accès aux outils et aux ressources.',
  'contexts.view.save_permissions': 'Enregistrer les permissions',
  'contexts.view.reset': 'Réinitialiser',
  'contexts.view.systems_empty_title': 'Aucun Système lié',
  'contexts.view.systems_empty_description':
    'Aucun Système ne référence ce Contexte comme context_id principal.',
  'contexts.view.impact_eyebrow': 'Contexte · impact',
  'contexts.view.impact_title': 'Impact en aval',
  'contexts.view.impact_safe':
    'Aucun Système ne référence actuellement ce Contexte. Le modifier ou le supprimer est sans risque.',
  'contexts.view.impact_warning_one':
    '1 Système référence ce Contexte. Les changements se propagent à la prochaine Exécution.',
  'contexts.view.impact_warning_many':
    '{count} Systèmes référencent ce Contexte. Les changements se propagent à la prochaine Exécution.',
  'contexts.view.kpi.data_hint': 'Nombre de réfs de connaissances déclarées sur ce contexte.',
  'contexts.view.kpi.memory_hint': 'Nombre de compartiments mémoire ouverts à l’exécution.',
  'contexts.view.kpi.systems_hint': 'Systèmes actuellement liés via context_id.',
  'contexts.view.kpi.version_hint': 'S’incrémente à chaque enregistrement.',
  // --- Toasts and confirmations -------------------------------------------
  'contexts.toast.not_found': 'Contexte introuvable',
  'contexts.toast.load_failed': 'Impossible de charger le contexte',
  'contexts.toast.deleted': '{name} supprimé',
  'contexts.toast.delete_failed': 'Échec de la suppression',
  'contexts.toast.saved': 'v{version} enregistrée',
  'contexts.toast.updated_title': 'Contexte mis à jour',
  'contexts.toast.update_failed': 'Échec de la mise à jour',
  'contexts.confirm.delete': 'Supprimer « {name} » ?',
  'contexts.confirm.delete_bound_one':
    'Supprimer « {name} » ? 1 Système perdra son épinglage de contexte.',
  'contexts.confirm.delete_bound_many':
    'Supprimer « {name} » ? {count} Systèmes perdront leur épinglage de contexte.',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof CONTEXTS_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const CONTEXTS_EN: Record<keyof typeof CONTEXTS_FR, string> = {
  // --- List page -------------------------------------------------------
  'contexts.page.eyebrow': 'Steer · Contexts',
  'contexts.page.title': 'Contexts',
  'contexts.page.subtitle':
    'Versioned bags of state attached to Systems. Each Run references a Context snapshot.',
  'contexts.page.new_via_builder': 'New via Builder',
  'contexts.kpi.total': 'Total',
  'contexts.kpi.total_hint': 'All contexts in this workspace.',
  'contexts.kpi.pinned': 'Pinned',
  'contexts.kpi.pinned_hint': 'Referenced by at least one System.',
  'contexts.kpi.unused': 'Unused',
  'contexts.kpi.unused_hint': 'Orphan contexts that no System references.',
  'contexts.kpi.stale': 'Stale v3+',
  'contexts.kpi.stale_hint': 'Contexts that have been edited 3+ times.',
  'contexts.empty.title': 'No contexts yet',
  'contexts.empty.description': 'Contexts are created from the System Builder (Context step).',
  'contexts.empty.open_builder': 'Open System Builder',
  'contexts.list.in_use': 'In use',
  'contexts.list.orphan': 'Orphan',
  'contexts.list.system_col': 'System',
  'contexts.list.last_run': 'Last run',
  'contexts.list.meta': '{data} data · {mem} mem · {systems} systems',
  // --- Detail view -------------------------------------------------------
  'contexts.view.eyebrow': 'Contexts · Context',
  'contexts.view.title_fallback': 'Context',
  'contexts.view.subtitle_one': '{data} data refs · {memory} memory refs · 1 System bound.',
  'contexts.view.subtitle_many':
    '{data} data refs · {memory} memory refs · {systems} Systems bound.',
  'contexts.view.impact': 'Impact',
  'contexts.view.loading': 'Loading context…',
  'contexts.view.facets_aria': 'Context facets',
  'contexts.view.tab.overview': 'Overview',
  'contexts.view.tab.data': 'Data refs',
  'contexts.view.tab.memory': 'Memory refs',
  'contexts.view.tab.permissions': 'Permissions',
  'contexts.view.tab.systems': 'Systems',
  'contexts.view.name': 'Name',
  'contexts.view.version': 'Version',
  'contexts.view.created': 'Created',
  'contexts.view.save_name': 'Save name',
  'contexts.view.data_description':
    'Knowledge collections the Runs powered by this Context can cite.',
  'contexts.view.data_placeholder': 'collection name',
  'contexts.view.memory_description':
    'Persistent memory bins (chat histories, vector stores) the Context opens at run time.',
  'contexts.view.memory_placeholder': 'memory key',
  'contexts.view.remove': 'Remove',
  'contexts.view.add_ref': 'Add ref',
  'contexts.view.save_refs': 'Save refs',
  'contexts.view.permissions_description':
    'Free-form permissions bag (JSON). Consumed by the run engine to gate tool and resource access.',
  'contexts.view.save_permissions': 'Save permissions',
  'contexts.view.reset': 'Reset',
  'contexts.view.systems_empty_title': 'No Systems bound',
  'contexts.view.systems_empty_description':
    'No System references this Context as its primary context_id.',
  'contexts.view.impact_eyebrow': 'Context · impact',
  'contexts.view.impact_title': 'Downstream impact',
  'contexts.view.impact_safe':
    'No System currently references this Context. Editing or deleting it is safe.',
  'contexts.view.impact_warning_one':
    '1 System references this Context. Changes propagate on next Run.',
  'contexts.view.impact_warning_many':
    '{count} Systems reference this Context. Changes propagate on next Run.',
  'contexts.view.kpi.data_hint': 'Number of knowledge refs declared on this context.',
  'contexts.view.kpi.memory_hint': 'Number of memory bins opened at run time.',
  'contexts.view.kpi.systems_hint': 'Systems currently bound via context_id.',
  'contexts.view.kpi.version_hint': 'Increments on every save.',
  // --- Toasts and confirmations -------------------------------------------
  'contexts.toast.not_found': 'Context not found',
  'contexts.toast.load_failed': 'Could not load context',
  'contexts.toast.deleted': '{name} deleted',
  'contexts.toast.delete_failed': 'Delete failed',
  'contexts.toast.saved': 'v{version} saved',
  'contexts.toast.updated_title': 'Context updated',
  'contexts.toast.update_failed': 'Update failed',
  'contexts.confirm.delete': 'Delete "{name}"?',
  'contexts.confirm.delete_bound_one': 'Delete "{name}"? 1 System will lose their context pin.',
  'contexts.confirm.delete_bound_many':
    'Delete "{name}"? {count} Systems will lose their context pin.',
};
