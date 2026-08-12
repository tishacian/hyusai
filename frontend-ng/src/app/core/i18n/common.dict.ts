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
};
