/**
 * i18n dictionaries — FR (first-class) and EN (progressive coverage).
 *
 * Keys are dot-notation strings scoped by surface (`titlebar.*`,
 * `nav.*`, `chat.*`, `account.*`, `auth.*`, `common.*`, …). Every
 * English entry MUST have a French counterpart; a missing FR entry
 * means the key disappears from the UI on both locales (we use FR as
 * the hard fallback — see {@link I18nService.t}).
 *
 * Keep this file sorted by surface for easy review. The type alias
 * {@link I18nKey} is exported so call sites can get compile-time
 * verification that a key actually exists:
 *
 * ```ts
 * i18n.t('titlebar.chat');        // ✓
 * i18n.t('titlebar.doesnotexist'); // TS error
 * ```
 */

export const FR_DICT = {
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

  // --- Title bar ---------------------------------------------------
  'titlebar.chat': 'Chat',
  'titlebar.chat.tooltip': 'Chat · ⌘J',
  'titlebar.palette': 'Palette de commandes',
  'titlebar.palette.tooltip': 'Palette · ⌘K',
  'titlebar.account': 'Compte',
  'titlebar.help': 'Aide',
  'titlebar.notifications': 'Notifications',
  'titlebar.theme.toggle': 'Basculer le thème',
  'titlebar.theme.light': 'Thème : Clair · cliquer → Sombre',
  'titlebar.theme.dark': 'Thème : Sombre · cliquer → Système',
  'titlebar.theme.system': 'Thème : Système · cliquer → Clair',
  'titlebar.theme.locked': 'Thème : Sombre verrouillé',
  'titlebar.workspace': 'Workspace',

  // --- Side rail / primary navigation ------------------------------
  'nav.hypervisor': 'Hyperviseur',
  'nav.build': 'Construire',
  'nav.operate': 'Opérer',
  'nav.steer': 'Piloter',
  'nav.govern': 'Gouverner',
  'nav.systems': 'Systèmes',
  'nav.runs': 'Exécutions',
  'nav.knowledge': 'Connaissances',
  'nav.intelligence': 'Veille',
  'nav.observability': 'Observabilité',
  'nav.orchestration': 'Orchestration',
  'nav.governance': 'Gouvernance',
  'nav.skills': 'Skills',
  'nav.capabilities': 'Capabilities',
  'nav.presets': 'Presets',
  'nav.contexts': 'Contextes',
  'nav.workspace': 'Workspace',
  'nav.members': 'Membres',
  'nav.settings': 'Paramètres',
  'nav.flows': 'Flow builder',
  'nav.capture': 'Capture experte',
  'nav.missions': 'Missions',
  'nav.levers': 'Leviers',
  'nav.review': 'File de revue',
  'nav.audit': 'Gouvernance',
  'nav.apps': 'Apps',
  'nav.resources': 'Ressources',
  'nav.palette': 'Aller à…',
  'nav.palette.hint': '⌘K palette',

  // --- Verb hints (side-rail second line) --------------------------
  'nav.hint.hypervisor': 'Décider · bilan, résultats, what-if',
  'nav.hint.build': 'Créer Systèmes, Capabilities, Skills, Knowledge & Flows',
  'nav.hint.operate': 'Runtime · exécutions, missions',
  'nav.hint.steer': 'Optimiser les résultats · leviers, politiques',
  'nav.hint.govern': 'Contrôle · audit, apps, ressources, presets',

  // --- Account menu ------------------------------------------------
  'account.profile': 'Profil',
  'account.security': 'Sécurité',
  'account.sessions': 'Sessions',
  'account.password': 'Mot de passe',
  'account.danger': 'Zone de danger',
  'account.locale': 'Langue',
  'account.locale.fr': 'Français',
  'account.locale.en': 'English',
  'account.theme': 'Thème',
  'account.theme.dark': 'Sombre',
  'account.theme.light': 'Clair',
  'account.theme.system': 'Système',
  'account.signout': 'Se déconnecter',

  // --- Auth flows --------------------------------------------------
  'auth.signin.title': 'Connexion',
  'auth.signin.submit': 'Se connecter',
  'auth.signin.email': 'Adresse e-mail',
  'auth.signin.password': 'Mot de passe',
  'auth.signin.forgot': 'Mot de passe oublié ?',
  'auth.signup.title': 'Inscription',
  'auth.signup.submit': 'Créer mon compte',
  'auth.signup.have_account': 'Déjà inscrit ?',
  'auth.reset.title': 'Réinitialiser le mot de passe',
  'auth.reset.submit': 'Envoyer le lien',

  // --- Chat overlay / workspace -----------------------------------
  'chat.title': 'Chat',
  'chat.placeholder': 'Posez votre question…',
  'chat.send': 'Envoyer',
  'chat.quick_ask': 'Question rapide',
  'chat.with_system': 'Avec un système',
  'chat.drop_files': 'Déposez des fichiers pour démarrer une session',
  'chat.drop_files.hint': 'Les documents sont utilisés pour cette session uniquement.',
  'chat.persist': 'Conserver le contexte',
  'chat.persist.hint': 'Transformer cette session en contexte permanent du workspace.',
  'chat.uploading': 'Envoi des fichiers…',
  'chat.empty': 'Démarrez une conversation pour voir les réponses ici.',

  // --- Command palette ---------------------------------------------
  'palette.placeholder': 'Rechercher une commande ou une destination…',
  'palette.section.views': 'Vues',
  'palette.section.actions': 'Actions',
  'palette.section.chat': 'Chat',
  'palette.section.workspace': 'Workspace',
  'palette.empty': 'Aucun résultat',
  'palette.hint.ask': 'Poser une question…',
  'palette.hint.chat_system': 'Discuter avec un système…',
  'palette.hint.drop_files': 'Déposer des fichiers et poser une question…',
  'palette.view.expert_capture': 'Capture experte',
  'palette.view.expert_capture.hint': 'Préparer un entretien guidé depuis un Context',

  // --- Systems / runs shells ---------------------------------------
  'systems.title': 'Systèmes',
  'systems.empty': "Aucun système pour l'instant.",
  'systems.create': 'Nouveau système',
  'systems.search': 'Rechercher un système…',
  'runs.title': 'Exécutions',
  'runs.empty': 'Aucune exécution récente.',
  'runs.status.running': 'En cours',
  'runs.status.completed': 'Terminé',
  'runs.status.failed': 'Échec',
  'runs.status.cancelled': 'Annulé',
  'runs.status.hitl_pending': 'En attente humaine',
  'runs.status.debug_pending': 'Pause debug',

  // --- Workspace shell ---------------------------------------------
  'workspace.general': 'Général',
  'workspace.members': 'Membres',
  'workspace.danger': 'Zone de danger',
  'workspace.invite': 'Inviter un collègue',
  'workspace.invite.placeholder': 'email@exemple.com',

  // --- Empty / error states ----------------------------------------
  'state.empty.title': 'Rien à afficher',
  'state.empty.description': 'Les données apparaîtront ici dès qu\'elles seront disponibles.',
  'state.error.title': 'Une erreur est survenue',
  'state.error.network': 'Erreur réseau. Vérifiez votre connexion.',
  'state.error.retry': 'Réessayer',
} as const satisfies Record<string, string>;

export type I18nKey = keyof typeof FR_DICT;

/**
 * English translations. Incomplete is OK — the {@link I18nService}
 * falls back through FR for any missing key, so the product never
 * breaks when EN has a hole.
 */
export const EN_DICT: Partial<Record<I18nKey, string>> & Record<string, string> = {
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

  // --- Title bar ---------------------------------------------------
  'titlebar.chat': 'Chat',
  'titlebar.chat.tooltip': 'Chat · ⌘J',
  'titlebar.palette': 'Command palette',
  'titlebar.palette.tooltip': 'Palette · ⌘K',
  'titlebar.account': 'Account',
  'titlebar.help': 'Help',
  'titlebar.notifications': 'Notifications',
  'titlebar.theme.toggle': 'Toggle theme',
  'titlebar.theme.light': 'Theme: Light · click → Dark',
  'titlebar.theme.dark': 'Theme: Dark · click → System',
  'titlebar.theme.system': 'Theme: System · click → Light',
  'titlebar.theme.locked': 'Theme: Dark locked',
  'titlebar.workspace': 'Workspace',

  // --- Side rail / primary navigation ------------------------------
  'nav.hypervisor': 'Hypervisor',
  'nav.build': 'Build',
  'nav.operate': 'Operate',
  'nav.steer': 'Steer',
  'nav.govern': 'Govern',
  'nav.systems': 'Systems',
  'nav.runs': 'Runs',
  'nav.knowledge': 'Knowledge',
  'nav.intelligence': 'Intelligence',
  'nav.observability': 'Observability',
  'nav.orchestration': 'Orchestration',
  'nav.governance': 'Governance',
  'nav.skills': 'Skills',
  'nav.capabilities': 'Capabilities',
  'nav.presets': 'Presets',
  'nav.contexts': 'Contexts',
  'nav.workspace': 'Workspace',
  'nav.members': 'Members',
  'nav.settings': 'Settings',
  'nav.flows': 'Flow builder',
  'nav.capture': 'Expert capture',
  'nav.missions': 'Missions',
  'nav.levers': 'Control plane',
  'nav.review': 'Review queue',
  'nav.audit': 'Governance',
  'nav.apps': 'Apps',
  'nav.resources': 'Resources',
  'nav.palette': 'Jump to…',
  'nav.palette.hint': '⌘K palette',

  'nav.hint.hypervisor': 'Decide · balance sheet, outcomes, what-if',
  'nav.hint.build': 'Create Systems, Capabilities, Skills, Knowledge & Flows',
  'nav.hint.operate': 'Run Systems · runtime, runs, missions',
  'nav.hint.steer': 'Optimize outcomes · levers, policies',
  'nav.hint.govern': 'Control · audit, apps, resources, presets',

  // --- Account menu ------------------------------------------------
  'account.profile': 'Profile',
  'account.security': 'Security',
  'account.sessions': 'Sessions',
  'account.password': 'Password',
  'account.danger': 'Danger zone',
  'account.locale': 'Language',
  'account.locale.fr': 'Français',
  'account.locale.en': 'English',
  'account.theme': 'Theme',
  'account.theme.dark': 'Dark',
  'account.theme.light': 'Light',
  'account.theme.system': 'System',
  'account.signout': 'Sign out',

  // --- Auth flows --------------------------------------------------
  'auth.signin.title': 'Sign in',
  'auth.signin.submit': 'Sign in',
  'auth.signin.email': 'Email address',
  'auth.signin.password': 'Password',
  'auth.signin.forgot': 'Forgot password?',
  'auth.signup.title': 'Sign up',
  'auth.signup.submit': 'Create my account',
  'auth.signup.have_account': 'Already registered?',
  'auth.reset.title': 'Reset password',
  'auth.reset.submit': 'Send link',

  // --- Chat overlay / workspace -----------------------------------
  'chat.title': 'Chat',
  'chat.placeholder': 'Ask your question…',
  'chat.send': 'Send',
  'chat.quick_ask': 'Quick ask',
  'chat.with_system': 'With a system',
  'chat.drop_files': 'Drop files to start a session',
  'chat.drop_files.hint': 'Documents are used for this session only.',
  'chat.persist': 'Keep context',
  'chat.persist.hint': 'Promote this session into a permanent workspace context.',
  'chat.uploading': 'Uploading files…',
  'chat.empty': 'Start a conversation to see answers here.',

  // --- Command palette ---------------------------------------------
  'palette.placeholder': 'Search a command or a destination…',
  'palette.section.views': 'Views',
  'palette.section.actions': 'Actions',
  'palette.section.chat': 'Chat',
  'palette.section.workspace': 'Workspace',
  'palette.empty': 'No results',
  'palette.hint.ask': 'Ask a question…',
  'palette.hint.chat_system': 'Chat with a system…',
  'palette.hint.drop_files': 'Drop files and ask…',
  'palette.view.expert_capture': 'Expert capture',
  'palette.view.expert_capture.hint': 'Prepare a guided interview from a Context',

  // --- Systems / runs shells ---------------------------------------
  'systems.title': 'Systems',
  'systems.empty': 'No systems yet.',
  'systems.create': 'New system',
  'systems.search': 'Search a system…',
  'runs.title': 'Runs',
  'runs.empty': 'No recent runs.',
  'runs.status.running': 'Running',
  'runs.status.completed': 'Completed',
  'runs.status.failed': 'Failed',
  'runs.status.cancelled': 'Cancelled',
  'runs.status.hitl_pending': 'Awaiting operator',
  'runs.status.debug_pending': 'Debug pause',

  // --- Workspace shell ---------------------------------------------
  'workspace.general': 'General',
  'workspace.members': 'Members',
  'workspace.danger': 'Danger zone',
  'workspace.invite': 'Invite a teammate',
  'workspace.invite.placeholder': 'email@example.com',

  // --- Empty / error states ----------------------------------------
  'state.empty.title': 'Nothing to show',
  'state.empty.description': 'Data will show here as soon as it is available.',
  'state.error.title': 'Something went wrong',
  'state.error.network': 'Network error. Check your connection.',
  'state.error.retry': 'Retry',
};
