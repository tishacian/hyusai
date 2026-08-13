/**
 * Resources, connectors and apps — the catalog surfaces
 * (`/resources`, `/connectors`, `/apps`) and the per-entry catalog copy.
 *
 * The `resources.catalog.<id>.description` keys mirror the static entries of
 * `features/resources/resources.catalog.ts` by their stable `id`; the pages
 * build the key at render time and fall back to the raw description, so a
 * catalog entry without a key (or a workspace-defined one) still displays.
 * The RPA Bridge entry deliberately has no key: its description contains the
 * third party's word "jobs", which the lexicon bans from dictionary values —
 * the raw fallback renders it, covered by the catalog file's allowlist.
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const RESOURCES_FR = {
  // --- /resources — page shell -------------------------------------
  'resources.breadcrumb': 'Configurer',
  'resources.title': 'Ressources',
  'resources.subtitle': 'Modèles, connecteurs et apps à disposition de vos systèmes.',
  'resources.subtitle.demo': 'Connecteurs et apps à disposition de vos systèmes.',
  'resources.kpi.runtime': 'Runtime',
  'resources.kpi.runtime.value': 'Géré',
  'resources.kpi.models': 'Modèles',
  'resources.kpi.providers': 'Fournisseurs',
  'resources.kpi.connectors': 'Connecteurs',
  'resources.kpi.connectors.hint': '{configured} configurés · {coming} à venir',
  'resources.kpi.apps': 'Apps activées',
  'resources.kpi.apps.hint': 'Aller à /apps · {count} disponibles',
  'resources.kpi.apps.title':
    'Gérer les apps packagées & intégrations — catalogue de {count} entrées',
  'resources.tab.models': 'Modèles',
  'resources.tab.providers': 'Fournisseurs',
  'resources.tab.serving': 'Serving',
  'resources.tab.connectors': 'Connecteurs',

  // --- /resources — Models tab -------------------------------------
  'resources.models.managed.title': 'Runtime géré',
  'resources.models.managed.description':
    'Les détails des fournisseurs et du catalogue de modèles sont masqués par la présentation demo-safe.',
  'resources.models.title': 'Modèles disponibles',
  'resources.models.count': '{models} / {providers} fournisseurs',
  'resources.models.empty.title': 'Aucun modèle configuré',
  'resources.models.empty.description':
    'Configurez un fournisseur dans les réglages backend ou démarrez une instance Ollama.',
  'resources.models.usage.one': '1 système',
  'resources.models.usage.many': '{count} systèmes',
  'resources.models.pinned_by': 'Épinglé par : {systems}',
  'resources.models.status.ready': 'prêt',

  // --- /resources — Providers tab ----------------------------------
  'resources.providers.routing.title': 'Routage du workspace',
  'resources.providers.routing.description':
    'Fournisseur/modèle principal et chaîne de repli pour ce workspace.',
  'resources.providers.routing.source': 'source {value}',
  'resources.providers.routing.provider': 'Fournisseur',
  'resources.providers.routing.model': 'Modèle par défaut',
  'resources.providers.routing.fallback': 'Chaîne de repli',
  'resources.providers.routing.saving': 'Enregistrement…',
  'resources.providers.routing.save': 'Enregistrer le routage',
  'resources.providers.key_set': 'clé définie',
  'resources.providers.api_key': 'Clé API',
  'resources.providers.api_key.keep': '(laisser vide pour conserver)',
  'resources.providers.save_key': 'Enregistrer la clé',
  'resources.providers.clear_key': 'Effacer',
  'resources.providers.empty.title': 'Aucun fournisseur signalé',
  'resources.providers.empty.description':
    "Le statut des fournisseurs apparaîtra dès que l'API du plan de modèles sera disponible.",
  'resources.providers.distribution.title': 'Distribution du routage',
  'resources.providers.distribution.empty.title': 'Aucune donnée de distribution',
  'resources.providers.distribution.empty.description':
    "Les décomptes d'invocations apparaissent une fois le trafic routé enregistré.",

  // --- /resources — Serving tab ------------------------------------
  'resources.serving.attach.title': 'Attacher un nœud de serving',
  'resources.serving.attach.description':
    'Pointez ce workspace vers un hôte omnirag-llm-portal. Le jeton est stocké chiffré et jamais renvoyé.',
  'resources.serving.attach.name': 'Nom',
  'resources.serving.attach.url': 'URL de base',
  'resources.serving.attach.token': 'Jeton du portail',
  'resources.serving.attach.token.placeholder': 'secret partagé',
  'resources.serving.attach.busy': 'Attachement…',
  'resources.serving.attach.submit': 'Attacher le nœud',
  'resources.serving.empty.title': 'Aucun nœud de serving attaché',
  'resources.serving.empty.description':
    'Attachez un hôte omnirag-llm-portal ci-dessus pour piloter le serving GPU local / Ollama depuis cette page.',
  'resources.serving.node.fallback': 'Nœud de serving',
  'resources.serving.node.short': 'nœud',
  'resources.serving.create': 'Créer une instance',
  'resources.serving.detach': 'Détacher',
  'resources.serving.gpu.util': '{value} % util.',
  'resources.serving.instances.empty': "Aucune instance sur ce nœud pour l'instant.",
  'resources.serving.instance.start': 'Démarrer',
  'resources.serving.instance.stop': 'Arrêter',
  'resources.serving.instance.status_unknown': 'inconnu',
  'resources.serving.create.engine': 'Moteur',
  'resources.serving.create.model': 'Modèle',
  'resources.serving.create.model.placeholder': 'ex. llama3.2:3b',
  'resources.serving.create.port': 'Port',

  // --- /resources — Connectors tab ---------------------------------
  'resources.connectors.banner.title':
    'Configuration seulement · la plupart des connecteurs sont des entrées de catalogue',
  'resources.connectors.banner.before': 'Seuls les connecteurs marqués',
  'resources.connectors.banner.connected': 'connecté',
  'resources.connectors.banner.after':
    "(pastille verte) sont câblés de bout en bout. Les autres stockent la configuration localement pour la feuille de route — aucun appel runtime n'est effectué.",
  'resources.connectors.banner.request': 'Demander',

  // --- /resources — portal errors & toasts -------------------------
  'resources.portal.forbidden':
    "Le portail de modèles n'est pas disponible pour ce workspace (403).",
  'resources.portal.load_failed': 'Échec du chargement : {label}',
  'resources.toast.routing': 'Routage',
  'resources.toast.routing.required': 'Fournisseur et modèle sont requis',
  'resources.toast.routing.saved': 'Routage du workspace enregistré',
  'resources.toast.routing.save_failed': "Échec de l'enregistrement du routage",
  'resources.toast.credentials': 'Identifiants',
  'resources.toast.credentials.empty': 'Saisissez une valeur à enregistrer',
  'resources.toast.credentials.saved': 'Identifiants {provider} enregistrés',
  'resources.toast.credentials.save_failed': "Échec de l'enregistrement des identifiants",
  'resources.toast.credentials.cleared': 'Clé workspace {provider} effacée',
  'resources.toast.credentials.clear_failed': "Échec de l'effacement des identifiants",
  'resources.toast.serving': 'Serving',
  'resources.toast.serving.required': 'Nom et URL de base sont requis',
  'resources.toast.serving.attached': 'Nœud de serving attaché',
  'resources.toast.serving.attach_failed': "Échec de l'attachement du nœud",
  'resources.toast.serving.detached': 'Nœud de serving détaché',
  'resources.toast.serving.detach_failed': 'Échec du détachement du nœud',
  'resources.toast.instance.created': 'Instance créée',
  'resources.toast.instance.create_failed': "Échec de la création de l'instance",
  'resources.toast.instance.deleted': 'Instance supprimée',
  'resources.toast.instance.delete_failed': "Échec de la suppression de l'instance",
  'resources.toast.instance.started': 'Instance démarrée',
  'resources.toast.instance.start_failed': "Échec du démarrage de l'instance",
  'resources.toast.instance.stopped': 'Instance arrêtée',
  'resources.toast.instance.stop_failed': "Échec de l'arrêt de l'instance",

  // --- /connectors — page ------------------------------------------
  'connectors.breadcrumb': 'Gouverner',
  'connectors.title': 'Connecteurs',
  'connectors.subtitle':
    'Catalogue de connecteurs du workspace {name}. La configuration reste dans le périmètre du workspace.',
  'connectors.back_to_resources': 'Ressources',
  'connectors.kpi.supported': 'Pris en charge',
  'connectors.kpi.configured': 'Configurés',
  'connectors.kpi.available': 'Disponibles',
  'connectors.kpi.planned': 'Planifiés',
  'connectors.category.count': '{count} connecteurs',
  'connectors.status.connected': 'connecté',
  'connectors.status.configured': 'configuré',
  'connectors.status.ready': 'prêt',
  'connectors.status.available': 'disponible',
  'connectors.status.beta': 'bêta',
  'connectors.status.soon': 'bientôt',
  'connectors.status.planned': 'planifié',
  'connectors.card.config_saved': 'Config enregistrée',
  'connectors.card.scoped': 'Périmètre workspace',
  'connectors.open.sftp': 'Ouvrir le dépôt sécurisé',
  'connectors.open.sap_hana': 'Ouvrir la configuration SAP HANA',
  'connectors.open.rpa_bridge': 'Ouvrir la configuration RPA Bridge',
  'connectors.open.agenda': "Ouvrir l'agenda",
  'connectors.open.monitor': 'Ouvrir le moniteur',
  'connectors.open.sharepoint': 'Ouvrir la configuration SharePoint',
  'connectors.setup.edit': 'Modifier la configuration',
  'connectors.setup.preview': 'Prévisualiser la configuration',
  'connectors.setup.connect': 'Configurer la connexion',
  'connectors.action.configure': 'Configurer',
  'connectors.action.test': 'Tester',
  'connectors.action.clear': 'Effacer',
  'connectors.drawer.fallback_title': 'Connecteur',
  'connectors.drawer.setup_fallback_title': 'Configuration du connecteur',
  'connectors.drawer.live.before': "Point d'accès backend actif sur",
  'connectors.drawer.live.after': 'Enregistrez la configuration puis lancez',
  'connectors.drawer.live.test': 'Tester la connexion',
  'connectors.drawer.coming':
    'Adaptateur backend pas encore livré — la configuration est enregistrée localement pour la préremplir et migrer plus tard.',
  'connectors.drawer.local':
    "La configuration est stockée localement. L'adaptateur backend la reprendra automatiquement une fois enregistré.",
  'connectors.drawer.planned':
    'Adaptateur planifié. Le brouillon de configuration est enregistré localement pour la revue de démonstration.',
  'connectors.drawer.draft':
    'Le brouillon de configuration est stocké dans ce navigateur pour la démonstration du workspace courant.',
  'connectors.workspace.fallback': 'workspace courant',
  'connectors.toast.title': 'Connecteur',
  'connectors.toast.saved': 'Configuration {name} enregistrée',
  'connectors.toast.cleared': 'Configuration {name} effacée',
  'connectors.toast.setup_saved': 'Configuration {name} enregistrée',
  'connectors.toast.setup_cleared': 'Configuration {name} effacée',
  'connectors.toast.connection_test': 'Test de connexion',
  'connectors.toast.connector_test': 'Test du connecteur',
  'connectors.toast.reachable': '{name} joignable',
  'connectors.toast.unreachable': '{name} est injoignable — vérifiez le backend',
  'connectors.toast.simulated': 'Test simulé',
  'connectors.toast.no_adapter':
    "{name} n'a pas encore d'adaptateur actif. La configuration est stockée localement.",
  'connectors.toast.planned':
    "L'adaptateur {name} est planifié. Le brouillon de configuration est prêt.",
  'connectors.toast.shape_ok': 'Structure de configuration {name} validée',

  // --- /apps — page --------------------------------------------------
  'apps.eyebrow': 'Gouverner · Apps',
  'apps.title': 'Apps & intégrations',
  'apps.subtitle':
    "Extensions packagées et intégrations que l'orchestrateur peut brancher sur n'importe quel système — à ne pas confondre avec /skills, le registre atomique.",
  'apps.request_wiring': 'Demander le câblage',
  'apps.banner.catalog.lead':
    "Ces apps annoncent des intégrations orchestrateur mais ne sont pas encore liées à un runtime backend. Les activer les fait apparaître dans l'assistant Builder sans les connecter à un service réel. Utilisez",
  'apps.banner.catalog.tail':
    'pour en prioriser une. Pour les primitives skill atomiques, rendez-vous sur',
  'apps.banner.wired.title': 'Câblage runtime actif',
  'apps.banner.wired.one':
    "1 app câblée activée — les skills et les connecteurs sont synchronisés côté serveur. Les cartes uniquement au catalogue restent des marqueurs d'intention jusqu'à leur câblage.",
  'apps.banner.wired.many':
    "{count} apps câblées activées — les skills et les connecteurs sont synchronisés côté serveur. Les cartes uniquement au catalogue restent des marqueurs d'intention jusqu'à leur câblage.",
  'apps.load_error':
    'Impossible de charger les apps du workspace depuis le serveur — affichage du cache local.',
  'apps.filter.enabled': 'Activées',
  'apps.filter.wired': 'Câblées',
  'apps.filter.ready': 'Prêtes',
  'apps.filter.beta': 'Bêta',
  'apps.badge.wired': 'câblée',
  'apps.badge.wired.hint': 'Liée à une skill backend et à un connecteur',
  'apps.badge.catalog.hint': 'Présente au catalogue mais pas encore liée à un runtime',
  'apps.card.id': 'ID : {id}',
  'apps.kpi.total': 'Apps au total',
  'apps.kpi.enabled': 'Activées',
  'apps.kpi.enabled.hint_on': "Prêtes à l'emploi",
  'apps.kpi.enabled.hint_off': 'Activez-en quelques-unes',
  'apps.kpi.wired': 'Câblées',
  'apps.kpi.wired.hint': '{count} disponibles',
  'apps.kpi.beta': 'En bêta',
  'apps.footer.lead': "L'activation d'une app",
  'apps.footer.wired_word': 'câblée',
  'apps.footer.tail':
    "synchronise ses skills dans le catalogue du workspace et expose le connecteur dans le Builder. Les activations uniquement au catalogue restent des marqueurs d'intention tant qu'un connecteur backend n'est pas livré.",
  'apps.toast.title': 'Apps',
  'apps.toast.enabled': '{name} activée',
  'apps.toast.disabled': '{name} désactivée',
  'apps.toast.update_failed': 'Impossible de mettre à jour les apps',

  // --- Catalog — connector categories (looked up by stable id) -----
  'connectors.category.microsoft': 'Microsoft 365',
  'connectors.category.channels': 'Canaux de communication',
  'connectors.category.data_storage': 'Données & stockage',

  // --- Catalog — per-entry descriptions (looked up by stable id, ---
  // --- raw-description fallback; rpa_bridge intentionally absent) ---
  'resources.catalog.dynamics365.description':
    'Données ERP / CRM, fiches fournisseurs, bons de commande.',
  'resources.catalog.teams.description':
    'Notifications et conversations agent via les canaux Teams.',
  'resources.catalog.sharepoint.description':
    'Bibliothèques de documents, référentiels de politiques, authentification OTP déléguée.',
  'resources.catalog.outlook.description':
    'Déclencheurs sur e-mails entrants, événements de calendrier, synchronisation des tâches.',
  'resources.catalog.institutional_calendar.description':
    'Agenda partagé du workspace, lisible et modifiable par les assistants autorisés.',
  'resources.catalog.telegram.description':
    "Interaction par chat via l'API de bot Telegram.",
  'resources.catalog.whatsapp.description':
    "Accès au Système via l'API WhatsApp Cloud.",
  'resources.catalog.smtp.description':
    'Déclencheurs agent par e-mail entrant & sortant.',
  'resources.catalog.rest_api.description':
    "Intégrations sur mesure via des points d'accès REST documentés.",
  'resources.catalog.mqtt.description':
    'Messagerie événementielle temps réel et IoT.',
  'resources.catalog.visual_streams.description':
    "Capture d'instantanés depuis des flux publics ou autorisés, observations et synchronisation vers les Connaissances.",
  'resources.catalog.postgresql.description':
    'Requêtes sur données structurées et analytique.',
  'resources.catalog.sap_hana.description':
    'Interrogez SAP HANA Cloud pour des données ERP / maintenance structurées depuis les skills du Flow Builder.',
  'resources.catalog.s3.description':
    'Stockage objet cloud pour documents, embeddings, artefacts.',
  'resources.catalog.sftp.description':
    'Liens de téléversement externes avec accès par mot de passe et revue intermédiaire avant ingestion dans les Connaissances.',
  'resources.catalog.elasticsearch.description':
    'Recherche plein texte et analytique de logs.',
  'resources.catalog.web_search.description':
    'Recherchez sur Internet des informations et actualités en temps réel.',
  'resources.catalog.code_interpreter.description':
    'Exécutez du Python et analysez des données par programmation.',
  'resources.catalog.sql_query.description':
    'Interrogez des bases de données structurées et exportez les résultats.',
  'resources.catalog.api_connector.description':
    'Appelez des API REST externes avec une authentification personnalisée.',
  'resources.catalog.email_sender.description':
    'Rédigez et envoyez des e-mails depuis un Flow.',
  'resources.catalog.file_generator.description':
    "Exportez la sortie de l'agent en PDF, Excel ou CSV.",
  'resources.catalog.calendar_access.description':
    'Lisez et écrivez les événements et plannings du calendrier.',
  'resources.catalog.memory.description':
    'Stockez et récupérez du contexte entre les sessions.',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof RESOURCES_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const RESOURCES_EN: Record<keyof typeof RESOURCES_FR, string> = {
  // --- /resources — page shell -------------------------------------
  'resources.breadcrumb': 'Configure',
  'resources.title': 'Resources',
  'resources.subtitle': 'Models, connectors and apps available to your systems.',
  'resources.subtitle.demo': 'Connectors and apps available to your systems.',
  'resources.kpi.runtime': 'Runtime',
  'resources.kpi.runtime.value': 'Managed',
  'resources.kpi.models': 'Models',
  'resources.kpi.providers': 'Providers',
  'resources.kpi.connectors': 'Connectors',
  'resources.kpi.connectors.hint': '{configured} configured · {coming} coming',
  'resources.kpi.apps': 'Apps enabled',
  'resources.kpi.apps.hint': 'Go to /apps · {count} available',
  'resources.kpi.apps.title':
    'Manage packaged apps & integrations — catalog of {count} entries',
  'resources.tab.models': 'Models',
  'resources.tab.providers': 'Providers',
  'resources.tab.serving': 'Serving',
  'resources.tab.connectors': 'Connectors',

  // --- /resources — Models tab -------------------------------------
  'resources.models.managed.title': 'Managed runtime',
  'resources.models.managed.description':
    'Provider and model catalog details are hidden by demo-safe presentation.',
  'resources.models.title': 'Available models',
  'resources.models.count': '{models} / {providers} providers',
  'resources.models.empty.title': 'No models configured',
  'resources.models.empty.description':
    'Configure a provider in backend settings or start an Ollama instance.',
  'resources.models.usage.one': '1 system',
  'resources.models.usage.many': '{count} systems',
  'resources.models.pinned_by': 'Pinned by: {systems}',
  'resources.models.status.ready': 'ready',

  // --- /resources — Providers tab ----------------------------------
  'resources.providers.routing.title': 'Workspace routing',
  'resources.providers.routing.description':
    'Primary provider/model and fallback chain for this workspace.',
  'resources.providers.routing.source': 'source {value}',
  'resources.providers.routing.provider': 'Provider',
  'resources.providers.routing.model': 'Default model',
  'resources.providers.routing.fallback': 'Fallback chain',
  'resources.providers.routing.saving': 'Saving…',
  'resources.providers.routing.save': 'Save routing',
  'resources.providers.key_set': 'key set',
  'resources.providers.api_key': 'API key',
  'resources.providers.api_key.keep': '(leave blank to keep)',
  'resources.providers.save_key': 'Save key',
  'resources.providers.clear_key': 'Clear',
  'resources.providers.empty.title': 'No providers reported',
  'resources.providers.empty.description':
    'Provider status will appear once the model plane API is available.',
  'resources.providers.distribution.title': 'Routing distribution',
  'resources.providers.distribution.empty.title': 'No distribution data',
  'resources.providers.distribution.empty.description':
    'Invocation counts appear after routed traffic is recorded.',

  // --- /resources — Serving tab ------------------------------------
  'resources.serving.attach.title': 'Attach serving node',
  'resources.serving.attach.description':
    'Point this workspace at an omnirag-llm-portal host. Token is stored encrypted and never echoed.',
  'resources.serving.attach.name': 'Name',
  'resources.serving.attach.url': 'Base URL',
  'resources.serving.attach.token': 'Portal token',
  'resources.serving.attach.token.placeholder': 'shared secret',
  'resources.serving.attach.busy': 'Attaching…',
  'resources.serving.attach.submit': 'Attach node',
  'resources.serving.empty.title': 'No serving node attached',
  'resources.serving.empty.description':
    'Attach an omnirag-llm-portal host above to manage local GPU / Ollama serving from here.',
  'resources.serving.node.fallback': 'Serving node',
  'resources.serving.node.short': 'node',
  'resources.serving.create': 'Create instance',
  'resources.serving.detach': 'Detach',
  'resources.serving.gpu.util': '{value}% util',
  'resources.serving.instances.empty': 'No instances on this node yet.',
  'resources.serving.instance.start': 'Start',
  'resources.serving.instance.stop': 'Stop',
  'resources.serving.instance.status_unknown': 'unknown',
  'resources.serving.create.engine': 'Engine',
  'resources.serving.create.model': 'Model',
  'resources.serving.create.model.placeholder': 'e.g. llama3.2:3b',
  'resources.serving.create.port': 'Port',

  // --- /resources — Connectors tab ---------------------------------
  'resources.connectors.banner.title':
    'Configuration only · most connectors are catalog placeholders',
  'resources.connectors.banner.before': 'Only connectors marked',
  'resources.connectors.banner.connected': 'connected',
  'resources.connectors.banner.after':
    '(green pulse) are wired end-to-end. Others store configuration locally for the roadmap — no runtime calls are made.',
  'resources.connectors.banner.request': 'Request',

  // --- /resources — portal errors & toasts -------------------------
  'resources.portal.forbidden':
    'Model portal is not available for this workspace (403).',
  'resources.portal.load_failed': 'Failed to load {label}',
  'resources.toast.routing': 'Routing',
  'resources.toast.routing.required': 'Provider and model are required',
  'resources.toast.routing.saved': 'Workspace routing saved',
  'resources.toast.routing.save_failed': 'Failed to save routing',
  'resources.toast.credentials': 'Credentials',
  'resources.toast.credentials.empty': 'Enter a value to save',
  'resources.toast.credentials.saved': '{provider} credentials saved',
  'resources.toast.credentials.save_failed': 'Failed to save credentials',
  'resources.toast.credentials.cleared': '{provider} workspace key cleared',
  'resources.toast.credentials.clear_failed': 'Failed to clear credentials',
  'resources.toast.serving': 'Serving',
  'resources.toast.serving.required': 'Name and base URL are required',
  'resources.toast.serving.attached': 'Serving node attached',
  'resources.toast.serving.attach_failed': 'Failed to attach node',
  'resources.toast.serving.detached': 'Serving node detached',
  'resources.toast.serving.detach_failed': 'Failed to detach node',
  'resources.toast.instance.created': 'Instance created',
  'resources.toast.instance.create_failed': 'Failed to create instance',
  'resources.toast.instance.deleted': 'Instance deleted',
  'resources.toast.instance.delete_failed': 'Failed to delete instance',
  'resources.toast.instance.started': 'Instance started',
  'resources.toast.instance.start_failed': 'Failed to start instance',
  'resources.toast.instance.stopped': 'Instance stopped',
  'resources.toast.instance.stop_failed': 'Failed to stop instance',

  // --- /connectors — page ------------------------------------------
  'connectors.breadcrumb': 'Govern',
  'connectors.title': 'Connectors',
  'connectors.subtitle':
    'Workspace-scoped connector catalog for {name}. Setup stays inside the workspace boundary.',
  'connectors.back_to_resources': 'Resources',
  'connectors.kpi.supported': 'Supported',
  'connectors.kpi.configured': 'Configured',
  'connectors.kpi.available': 'Available',
  'connectors.kpi.planned': 'Planned',
  'connectors.category.count': '{count} connectors',
  'connectors.status.connected': 'connected',
  'connectors.status.configured': 'configured',
  'connectors.status.ready': 'ready',
  'connectors.status.available': 'available',
  'connectors.status.beta': 'beta',
  'connectors.status.soon': 'soon',
  'connectors.status.planned': 'planned',
  'connectors.card.config_saved': 'Config saved',
  'connectors.card.scoped': 'Workspace scoped',
  'connectors.open.sftp': 'Open secure deposit',
  'connectors.open.sap_hana': 'Open SAP HANA setup',
  'connectors.open.rpa_bridge': 'Open RPA Bridge setup',
  'connectors.open.agenda': 'Open agenda',
  'connectors.open.monitor': 'Open monitor',
  'connectors.open.sharepoint': 'Open SharePoint setup',
  'connectors.setup.edit': 'Edit setup',
  'connectors.setup.preview': 'Preview setup',
  'connectors.setup.connect': 'Set up connection',
  'connectors.action.configure': 'Configure',
  'connectors.action.test': 'Test',
  'connectors.action.clear': 'Clear',
  'connectors.drawer.fallback_title': 'Connector',
  'connectors.drawer.setup_fallback_title': 'Connector setup',
  'connectors.drawer.live.before': 'Backend endpoint live at',
  'connectors.drawer.live.after': 'Save configuration then hit',
  'connectors.drawer.live.test': 'Test connection',
  'connectors.drawer.coming':
    'Backend adapter not shipped yet — configuration is saved locally so you can pre-fill it and migrate later.',
  'connectors.drawer.local':
    'Configuration is stored locally. Backend adapter will pick it up automatically once registered.',
  'connectors.drawer.planned':
    'Adapter planned. The setup draft is saved locally for showcase review.',
  'connectors.drawer.draft':
    'Setup draft is stored in this browser for the current workspace showcase.',
  'connectors.workspace.fallback': 'current workspace',
  'connectors.toast.title': 'Connector',
  'connectors.toast.saved': '{name} configuration saved',
  'connectors.toast.cleared': '{name} configuration cleared',
  'connectors.toast.setup_saved': '{name} setup saved',
  'connectors.toast.setup_cleared': '{name} setup cleared',
  'connectors.toast.connection_test': 'Connection test',
  'connectors.toast.connector_test': 'Connector test',
  'connectors.toast.reachable': '{name} reachable',
  'connectors.toast.unreachable': '{name} is unreachable — check the backend',
  'connectors.toast.simulated': 'Simulated test',
  'connectors.toast.no_adapter':
    "{name} doesn't have a live adapter yet. Config is stored locally.",
  'connectors.toast.planned': '{name} adapter is planned. Setup draft is ready.',
  'connectors.toast.shape_ok': '{name} setup shape validated',

  // --- /apps — page --------------------------------------------------
  'apps.eyebrow': 'Govern · Apps',
  'apps.title': 'Apps & integrations',
  'apps.subtitle':
    'Packaged extensions and integrations the orchestrator can plug into any system — not to be confused with /skills, the atomic registry.',
  'apps.request_wiring': 'Request wiring',
  'apps.banner.catalog.lead':
    'These apps advertise orchestrator integrations but are not yet bound to a backend runtime. Toggling them surfaces them in the Builder wizard but does not connect to a live service. Use',
  'apps.banner.catalog.tail':
    'to prioritise one. For atomic skill primitives, head to',
  'apps.banner.wired.title': 'Runtime wiring active',
  'apps.banner.wired.one':
    '1 wired app enabled — skills and connectors are synced server-side. Catalog-only cards remain intent flags until wired.',
  'apps.banner.wired.many':
    '{count} wired apps enabled — skills and connectors are synced server-side. Catalog-only cards remain intent flags until wired.',
  'apps.load_error': 'Could not load workspace apps from server — showing local cache.',
  'apps.filter.enabled': 'Enabled',
  'apps.filter.wired': 'Wired',
  'apps.filter.ready': 'Ready',
  'apps.filter.beta': 'Beta',
  'apps.badge.wired': 'wired',
  'apps.badge.wired.hint': 'Bound to a backend skill and connector',
  'apps.badge.catalog.hint': 'Listed in the catalog but not yet bound to a runtime',
  'apps.card.id': 'ID: {id}',
  'apps.kpi.total': 'Total apps',
  'apps.kpi.enabled': 'Enabled',
  'apps.kpi.enabled.hint_on': 'Ready to be used',
  'apps.kpi.enabled.hint_off': 'Turn some on',
  'apps.kpi.wired': 'Wired',
  'apps.kpi.wired.hint': '{count} available',
  'apps.kpi.beta': 'In beta',
  'apps.footer.lead': 'Enabling a',
  'apps.footer.wired_word': 'wired',
  'apps.footer.tail':
    'app syncs its skills into the workspace catalog and exposes the connector in the Builder. Catalog-only toggles remain intent flags until a backend connector ships.',
  'apps.toast.title': 'Apps',
  'apps.toast.enabled': '{name} enabled',
  'apps.toast.disabled': '{name} disabled',
  'apps.toast.update_failed': 'Could not update apps',

  // --- Catalog — connector categories (looked up by stable id) -----
  'connectors.category.microsoft': 'Microsoft 365',
  'connectors.category.channels': 'Communication channels',
  'connectors.category.data_storage': 'Data & storage',

  // --- Catalog — per-entry descriptions (looked up by stable id, ---
  // --- raw-description fallback; rpa_bridge intentionally absent) ---
  'resources.catalog.dynamics365.description':
    'ERP / CRM data, vendor records, purchase orders.',
  'resources.catalog.teams.description':
    'Notifications and agent conversations via Teams channels.',
  'resources.catalog.sharepoint.description':
    'Document libraries, policy repositories, delegated OTP auth.',
  'resources.catalog.outlook.description':
    'Inbound email triggers, calendar events, task sync.',
  'resources.catalog.institutional_calendar.description':
    'Shared workspace agenda, readable and editable by authorized assistants.',
  'resources.catalog.telegram.description': 'Chat interaction via Telegram bot API.',
  'resources.catalog.whatsapp.description': 'System access via WhatsApp Cloud API.',
  'resources.catalog.smtp.description': 'Inbound & outbound email agent triggers.',
  'resources.catalog.rest_api.description':
    'Custom integrations via documented REST endpoints.',
  'resources.catalog.mqtt.description': 'IoT and real-time event-driven messaging.',
  'resources.catalog.visual_streams.description':
    'Snapshot capture from public or authorized streams, observations and Knowledge sync.',
  'resources.catalog.postgresql.description':
    'Structured data queries and analytics.',
  'resources.catalog.sap_hana.description':
    'Query SAP HANA Cloud for structured ERP / maintenance data from Flow Builder skills.',
  'resources.catalog.s3.description':
    'Cloud object storage for documents, embeddings, artifacts.',
  'resources.catalog.sftp.description':
    'External upload links with password access and staged review before Knowledge ingestion.',
  'resources.catalog.elasticsearch.description':
    'Full-text search and log analytics.',
  'resources.catalog.web_search.description':
    'Search the internet for real-time information and news.',
  'resources.catalog.code_interpreter.description':
    'Execute Python and analyze data programmatically.',
  'resources.catalog.sql_query.description':
    'Query structured databases and export results.',
  'resources.catalog.api_connector.description':
    'Call external REST APIs with custom authentication.',
  'resources.catalog.email_sender.description':
    'Draft and send emails from a Flow.',
  'resources.catalog.file_generator.description':
    'Export agent output as PDF, Excel, or CSV.',
  'resources.catalog.calendar_access.description':
    'Read and write calendar events and schedules.',
  'resources.catalog.memory.description':
    'Store and retrieve context across sessions.',
};
