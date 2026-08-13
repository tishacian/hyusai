/**
 * Cross-surface primitives: shared verbs, empty and error states.
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const COMMON_FR = {
  // --- Common actions / verbs --------------------------------------
  'common.save': 'Enregistrer',
  'common.cancel': 'Annuler',
  'common.close': 'Fermer',
  'common.delete': 'Supprimer',
  'common.edit': 'Modifier',
  'common.create': 'Créer',
  'common.search': 'Rechercher',
  'common.loading': 'Chargement…',
  'common.retry': 'Réessayer',
  'common.refresh': 'Actualiser',
  'common.back': 'Retour',
  'common.next': 'Suivant',
  'common.confirm': 'Confirmer',
  'common.copy': 'Copier',
  'common.copied': 'Copié',
  'common.open': 'Ouvrir',
  'common.signout': 'Se déconnecter',
  'common.signin': 'Se connecter',
  'common.signup': "S'inscrire",
  'common.yes': 'Oui',
  'common.no': 'Non',
  'common.all': 'Tout',
  'common.none': 'Aucun',
  // --- Empty / error states ----------------------------------------
  'state.empty.title': 'Rien à afficher',
  'state.empty.description': 'Les données apparaîtront ici dès qu\'elles seront disponibles.',
  'state.error.title': 'Une erreur est survenue',
  'state.error.network': 'Erreur réseau. Vérifiez votre connexion.',
  'state.error.retry': 'Réessayer',
  'state.error.stream_timeout': 'La réponse prend trop de temps. La session a été arrêtée proprement.',
  // --- Help affordance (ck-help button chrome; the panel content keeps
  // --- its own language preference, see CONVENTION.md §5) -----------
  'common.help.about': 'Aide sur {name}',
  'common.help.language': "Langue de l'aide",
  'common.help.switch_language': "Afficher l'aide en {name}",

  // --- Shared tabs chrome (ck-tabs) ---------------------------------
  'common.tabs.more': 'Plus',
  'common.tabs.more_title': 'Autres onglets',
  'common.tabs.aria': "Facettes de l'objet",

  // --- Object perspective chrome (ck-object-perspective) ------------
  'common.perspective.loading': 'Chargement de la projection {lens}…',
  'common.perspective.error': 'Cette projection est temporairement indisponible.',
  'common.perspective.empty': "Aucun bloc n'est configuré pour cette facette.",
  'common.perspective.snapshot': 'Instantané {id}',
  // {name} in apposition: the object labels are of mixed gender (« Exécution »,
  // « Système »…), so the sentence keeps a neutral subject.
  'common.perspective.title.build': 'Comment cet objet ({name}) est construit',
  'common.perspective.title.operate': 'Comment cet objet ({name}) fonctionne',
  'common.perspective.title.steer': 'Ce qui doit être optimisé',
  'common.perspective.title.govern': 'Qui peut agir et ce qui a changé',
  'common.perspective.state.available': 'Disponible',
  'common.perspective.state.not_measured': 'Non mesuré',
  'common.perspective.state.not_configured': 'Non configuré',
  'common.perspective.state.restricted': 'Accès restreint',
  'common.perspective.state.unavailable': 'Indisponible',
  'common.perspective.yes': 'Oui',
  'common.perspective.no': 'Non',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof COMMON_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const COMMON_EN: Record<keyof typeof COMMON_FR, string> = {
  // --- Common actions / verbs --------------------------------------
  'common.save': 'Save',
  'common.cancel': 'Cancel',
  'common.close': 'Close',
  'common.delete': 'Delete',
  'common.edit': 'Edit',
  'common.create': 'Create',
  'common.search': 'Search',
  'common.loading': 'Loading…',
  'common.retry': 'Retry',
  'common.refresh': 'Refresh',
  'common.back': 'Back',
  'common.next': 'Next',
  'common.confirm': 'Confirm',
  'common.copy': 'Copy',
  'common.copied': 'Copied',
  'common.open': 'Open',
  'common.signout': 'Sign out',
  'common.signin': 'Sign in',
  'common.signup': 'Sign up',
  'common.yes': 'Yes',
  'common.no': 'No',
  'common.all': 'All',
  'common.none': 'None',
  // --- Empty / error states ----------------------------------------
  'state.empty.title': 'Nothing to show',
  'state.empty.description': 'Data will show here as soon as it is available.',
  'state.error.title': 'Something went wrong',
  'state.error.network': 'Network error. Check your connection.',
  'state.error.retry': 'Retry',
  'state.error.stream_timeout': 'The answer is taking too long. The session was stopped cleanly.',
  // --- Help affordance (ck-help button chrome; the panel content keeps
  // --- its own language preference, see CONVENTION.md §5) -----------
  'common.help.about': 'Help about {name}',
  'common.help.language': 'Help language',
  'common.help.switch_language': 'Switch help language to {name}',

  // --- Shared tabs chrome (ck-tabs) ---------------------------------
  'common.tabs.more': 'More',
  'common.tabs.more_title': 'More tabs',
  'common.tabs.aria': 'Object facets',

  // --- Object perspective chrome (ck-object-perspective) ------------
  'common.perspective.loading': 'Loading the {lens} projection…',
  'common.perspective.error': 'This projection is temporarily unavailable.',
  'common.perspective.empty': 'No block is configured for this facet.',
  'common.perspective.snapshot': 'Snapshot {id}',
  'common.perspective.title.build': 'How this {name} is built',
  'common.perspective.title.operate': 'How this {name} is operating',
  'common.perspective.title.steer': 'What should be optimized',
  'common.perspective.title.govern': 'Who can act and what changed',
  'common.perspective.state.available': 'Available',
  'common.perspective.state.not_measured': 'Not measured',
  'common.perspective.state.not_configured': 'Not configured',
  'common.perspective.state.restricted': 'Access restricted',
  'common.perspective.state.unavailable': 'Unavailable',
  'common.perspective.yes': 'Yes',
  'common.perspective.no': 'No',
};
