/**
 * Secure deposit portal — the external, pre-authentication surface and the
 * post-password deposit browser.
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const DEPOSIT_FR = {
  // --- Portal header ------------------------------------------------
  // Rendered uppercase by the container's CSS; natural case here.
  'deposit.portal.eyebrow': 'Dépôt sécurisé {brand}',
  'deposit.portal.title_fallback': 'Dépôt externe',

  // --- Password gate ------------------------------------------------
  'deposit.portal.access_required': 'Accès requis',
  'deposit.portal.password_prompt': 'Saisissez le mot de passe du dépôt',
  'deposit.portal.password': 'Mot de passe',
  'deposit.portal.open': 'Ouvrir le dépôt',
  'deposit.portal.opening': 'Ouverture…',

  // --- Dropzone and upload -------------------------------------------
  'deposit.portal.drop.title': 'Déposez vos fichiers ici',
  'deposit.portal.drop.hint': 'ou choisissez des fichiers depuis votre ordinateur',
  'deposit.portal.drop.select': 'Sélectionner des fichiers',
  'deposit.portal.drop.ready': '{count} fichier(s) prêt(s)',
  'deposit.portal.upload': 'Envoyer',
  'deposit.portal.uploading': 'Envoi…',

  // --- Deposited files ----------------------------------------------
  'deposit.portal.files.title': 'Fichiers',
  'deposit.portal.files.empty': "Aucun fichier déposé pour l'instant.",

  // --- Scope sidebar -------------------------------------------------
  'deposit.portal.scope': 'Périmètre du dépôt',
  'deposit.portal.max_file': 'Taille max. par fichier',
  'deposit.portal.expires': 'Expire',
  'deposit.portal.no_expiry': 'Sans expiration',

  // --- UI error fallbacks (the API `detail` takes precedence) --------
  'deposit.portal.error.open': "Impossible d'ouvrir ce lien de dépôt.",
  'deposit.portal.error.load_files': 'Impossible de charger les fichiers.',
  'deposit.portal.error.upload': "L'envoi a échoué.",

  // --- API statuses (looked up by value, raw-value fallback) ---------
  'deposit.link_status.active': 'Actif',
  'deposit.file_status.received': 'Reçu',
  'deposit.file_status.rejected': 'Rejeté',
  'deposit.file_status.promoted': 'Intégré',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof DEPOSIT_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const DEPOSIT_EN: Record<keyof typeof DEPOSIT_FR, string> = {
  // --- Portal header ------------------------------------------------
  'deposit.portal.eyebrow': '{brand} secure deposit',
  'deposit.portal.title_fallback': 'External deposit',

  // --- Password gate ------------------------------------------------
  'deposit.portal.access_required': 'Access required',
  'deposit.portal.password_prompt': 'Enter deposit password',
  'deposit.portal.password': 'Password',
  'deposit.portal.open': 'Open deposit',
  'deposit.portal.opening': 'Opening…',

  // --- Dropzone and upload -------------------------------------------
  'deposit.portal.drop.title': 'Drop files here',
  'deposit.portal.drop.hint': 'or choose files from your computer',
  'deposit.portal.drop.select': 'Select files',
  'deposit.portal.drop.ready': '{count} file(s) ready',
  'deposit.portal.upload': 'Upload',
  'deposit.portal.uploading': 'Uploading…',

  // --- Deposited files ----------------------------------------------
  'deposit.portal.files.title': 'Files',
  'deposit.portal.files.empty': 'No files deposited yet.',

  // --- Scope sidebar -------------------------------------------------
  'deposit.portal.scope': 'Deposit scope',
  'deposit.portal.max_file': 'Max file',
  'deposit.portal.expires': 'Expires',
  'deposit.portal.no_expiry': 'No expiry',

  // --- UI error fallbacks (the API `detail` takes precedence) --------
  'deposit.portal.error.open': 'Unable to open this deposit link.',
  'deposit.portal.error.load_files': 'Unable to load files.',
  'deposit.portal.error.upload': 'Upload failed.',

  // --- API statuses (looked up by value, raw-value fallback) ---------
  'deposit.link_status.active': 'Active',
  'deposit.file_status.received': 'Received',
  'deposit.file_status.rejected': 'Rejected',
  'deposit.file_status.promoted': 'Promoted',
};
