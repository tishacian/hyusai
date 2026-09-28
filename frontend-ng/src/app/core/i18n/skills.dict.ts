/**
 * Skills and capabilities: catalog, detail, authoring, lifecycle.
 *
 * Accepted key prefixes: 'skills.', 'capabilities.'. See `./CONVENTION.md`.
 *
 * Three groups deserve a word:
 *
 * * `skills.runtime.<kind>` and `skills.cert.<level>` mirror API values, so
 *   the key is built at the call site and falls back to the raw value. The
 *   label is the lexicon term; the raw kind stays available as a secondary
 *   line, never as the primary label.
 * * `skills.schema.*` belongs to `<ck-schema-builder>`, the contract editor
 *   this surface owns and the Flow inspector reuses.
 * * `skills.import.*` speaks the words of the Business Requirements template
 *   (outcome, requirement, decision) beside the platform words, so the wizard
 *   bridges the two vocabularies instead of inventing a third. `skills.wizard.hint.*`
 *   asks each step's question in plain language, with an example;
 *   `skills.wizard.brd.*` is the pointer into that document for whoever has
 *   one, and is rendered as a secondary line next to a `ck-help`, never as the
 *   instruction itself.
 */

export const SKILLS_FR = {
  // -- Catalog ------------------------------------------------------------
  'skills.title': 'Registre des skills',
  'skills.list.eyebrow': 'Build · Skills',
  'skills.list.description':
    'Opérations typées, versionnées et certifiées — les briques que les systèmes orchestrent.',
  'skills.list.search': 'Filtrer les skills…',
  'skills.list.new': 'Nouvelle skill',
  'skills.list.new.hint': 'Définir une skill appartenant à cet espace de travail',
  'skills.list.import': 'Importer un BRD',
  'skills.list.import.hint':
    'Lire un document Business Requirements et en tirer des brouillons de skills',
  'skills.list.loading': 'Chargement du registre…',
  'skills.list.empty': 'Aucune skill ne correspond',
  'skills.list.filter.all': 'Toutes',
  'skills.list.totals': 'Totaux du registre',
  'skills.list.total.skills': 'Skills',
  'skills.list.total.calls': 'Appels',
  'skills.list.total.latency': 'Latence moy.',
  'skills.list.total.success': 'Taux de succès',
  'skills.list.column.cert': 'Cert',
  'skills.list.column.skill': 'Skill',
  'skills.list.column.type': 'Type',
  'skills.list.column.calls': 'Appels',
  'skills.list.column.latency': 'Lat. moy.',
  'skills.list.column.cost': 'Coût',
  'skills.list.column.success': 'Succès',
  'skills.list.column.price': 'Prix unitaire',
  'skills.cost.observed': 'Coût observé',
  'skills.cost.not_measured': 'Non mesuré',
  'skills.cost.observed.hint': 'Somme des coûts renseignés pour les invocations accessibles ; la couverture peut être partielle. Le prix catalogue est distinct.',
  'skills.cost.catalog.hint': 'Tarif catalogue par unité, distinct du coût observé. Un tarif nul ne prouve pas une exécution gratuite.',
  'skills.list.open': 'Ouvrir',
  'skills.list.open.hint': 'Ouvrir le détail de la skill',
  'skills.provenance.hint':
    'Cette skill répond depuis un modèle entraîné ici. Ouvrir sa fiche.',

  // -- Certification levels (API values) ----------------------------------
  'skills.cert.basic': 'Base',
  'skills.cert.production': 'Production',
  'skills.cert.enterprise': 'Entreprise',

  // -- Detail panel -------------------------------------------------------
  'skills.detail.input': "Contrat d'entrée",
  'skills.detail.output': 'Contrat de sortie',
  'skills.detail.execution': 'Exécution',
  'skills.detail.performance': 'Performance observée',
  'skills.detail.provider': 'Fournisseur',
  'skills.detail.owned': 'Skill de cet espace de travail',
  'skills.detail.close': 'Fermer',
  'skills.exec.mode': 'Mode',
  'skills.exec.timeout': 'Délai maximum',
  'skills.exec.retryable': 'Réessayable',
  'skills.exec.idempotent': 'Idempotente',

  'skills.execution.title': "Paramètres d’exécution",
  'skills.execution.edit': "Modifier l’exécution",
  'skills.execution.load_error': "Impossible de charger les skills disponibles pour l’édition. Réessayez.",
  'skills.execution.model_hint': "Si le contrat autorise une entrée model, elle est prioritaire sur ce réglage. L’exécution conserve le modèle effectivement utilisé.",
  'skills.param.model': 'Modèle',
  'skills.models.inherit': 'Hériter du modèle configuré',
  'skills.models.saved': 'Valeur enregistrée, absente du catalogue actuel',
  'skills.models.load_error': 'Impossible de charger le catalogue de modèles. Réessayez.',
  'skills.models.resolve_error': 'La configuration effective ne peut pas être résolue. Vérifiez la connexion dans le portail.',
  'skills.models.legacy_azure': 'OpenAI public (ancien identifiant : azure)',
  'skills.models.legacy_azure_hint': 'Cet ancien réglage utilise OpenAI public et la connexion du déploiement. Il ne correspond pas à Azure OpenAI.',
  'skills.models.workspace': 'Suivre le routage de cet espace',
  'skills.models.unavailable': 'À configurer ou incompatible',
  'skills.models.connection_unreachable': 'Connexion indisponible',
  'skills.models.open_portal': 'Voir les connexions et tester · nouvel onglet',
  'skills.models.refresh': 'Actualiser les modèles',
  'skills.models.effective_provider': 'Fournisseur effectif',
  'skills.models.connection_source': 'Origine de la connexion',
  'skills.models.model_source': 'Origine du choix de modèle',
  'skills.models.fallback_used': 'Un modèle de repli a été utilisé.',
  'skills.models.fallback_plan': 'Modèles de repli prévus par cet espace',
  'skills.models.source.workspace': 'Configuration de cet espace',
  'skills.models.source.env': 'Configuration du déploiement',
  'skills.models.source.global': 'Défaut du déploiement',
  'skills.models.source.system': 'Défaut du système',
  'skills.models.source.executor': 'Réglage de la Skill',
  'skills.models.source.input': 'Entrée de cette exécution',
  'skills.models.source.legacy': 'Défaut historique conservé',
  'skills.models.source.unknown': 'Origine non renseignée',
  'skills.models.source.none': 'Connexion locale sans clé',
  'skills.models.source.not_configured': 'Connexion à configurer',
  'skills.execution.unavailable': "Aucun paramètre d’exécution n’est exposé pour cette skill.",

  'skills.execution.current': 'Définition actuelle de la Skill',
  'skills.execution.published': 'Configuration de la version publiée',
  'skills.execution.published_hint': 'Les tests du brouillon utilisent la définition actuelle. Les exécutions de la version publiée conservent les réglages ci-dessous.',
  'skills.execution.open_definition': 'Ouvrir la définition actuelle',

  // -- Lifecycle ----------------------------------------------------------
  'skills.action.edit': 'Modifier',
  'skills.action.delete': 'Supprimer',
  'skills.delete.ask': 'Supprimer {name} définitivement ?',
  'skills.delete.confirm': 'Supprimer',
  'skills.delete.cancel': 'Annuler',
  'skills.notice.created': '{slug} créée.',
  'skills.notice.updated': '{slug} enregistrée.',
  'skills.notice.deleted': '{slug} supprimée.',
  'skills.notice.claimed': 'Rattachée à {name}.',
  'skills.notice.claim_failed':
    "La skill est créée mais n'a pas pu être rattachée à la capability : {reason}",
  'skills.notice.published_bindings':
    'Publiée dans : {names}. Ces versions gardent le contrat figé à leur publication.',

  // -- Authoring wizard ---------------------------------------------------
  'skills.wizard.eyebrow': 'Skill de cet espace de travail',
  'skills.wizard.title.create': 'Nouvelle skill',
  'skills.wizard.title.edit': 'Modifier la skill',
  'skills.wizard.subtitle':
    "Le slug est dérivé du nom local et de cet espace de travail. La certification reste Base.",
  'skills.wizard.subtitle.edit':
    "Le slug ne change pas : il est déjà inscrit dans les flows qui appellent cette skill.",
  'skills.wizard.step.intent': 'Intention',
  'skills.wizard.step.contract': 'Contrat',
  'skills.wizard.step.runtime': 'Exécution',
  'skills.wizard.step.review': 'Revue',
  'skills.wizard.hint.intent':
    "Que doit produire cette skill, et pour quel résultat métier ? Par exemple : retrouver le délai de traitement contractuel d'un ticket.",
  'skills.wizard.hint.contract':
    "Ce que la skill reçoit pour travailler, et ce qu'elle rend en retour. Par exemple : elle reçoit un numéro de ticket, elle rend un délai et une échéance.",
  'skills.wizard.hint.runtime': 'Comment le travail est réellement fait.',
  'skills.wizard.hint.review': 'Ce qui part au serveur, et ce que le serveur décide à votre place.',
  'skills.wizard.brd.intent':
    "Vous partez d'un document d'exigences métier (BRD) ? Ses résultats attendus et ses exigences fonctionnelles répondent à ces deux questions (§4 et §5).",
  'skills.wizard.brd.contract':
    "Vous partez d'un BRD ? Les décisions que l'agent doit prendre (D-x) nomment les entrées dont cette skill a besoin.",
  'skills.wizard.brd.review':
    "Vous partez d'un BRD ? Vérifiez que le nom et la capability correspondent à l'exigence dont vous partez : c'est ce qui garde la trace du document jusqu'à la skill qui tourne.",
  'skills.wizard.back': 'Précédent',
  'skills.wizard.next': 'Suivant',
  'skills.wizard.cancel': 'Annuler',
  'skills.wizard.create': 'Créer la skill',
  'skills.wizard.creating': 'Création…',
  'skills.wizard.save': 'Enregistrer',
  'skills.wizard.saving': 'Enregistrement…',

  // -- Presets ------------------------------------------------------------
  'skills.preset.label': 'Point de départ',
  'skills.preset.scratch': 'Page blanche',
  'skills.preset.scratch.summary': 'Tout déclarer soi-même.',
  'skills.preset.llm.summary':
    "Un prompt que vous rédigez, envoyé au modèle de l'espace de travail.",
  'skills.preset.wrapper.summary':
    "Rejouer une skill fournie par la plateforme avec des entrées fixées d'avance.",

  // -- Intent step --------------------------------------------------------
  'skills.field.local_name': 'Nom local',
  'skills.field.local_name.hint': 'Sert à dériver le slug. Lettres, chiffres et tirets bas.',
  'skills.field.name': "Nom d'affichage",
  'skills.field.description': 'Description',
  'skills.field.description.hint':
    "Ce que la skill fait, en une phrase. Par exemple : « Retourne le délai contractuel d'un ticket. » Depuis un BRD, la formulation de l'exigence (FR-x) convient telle quelle.",
  'skills.field.type': 'Type',
  'skills.field.category': 'Catégorie',
  'skills.field.category.hint': 'Décide du groupe dans lequel la palette du flow la range.',
  'skills.field.category.none': '— aucune —',
  'skills.field.capability': 'Portée par la capability',
  'skills.field.capability.hint':
    "Le résultat métier auquel cette skill contribue. Sans rattachement, elle reste visible au catalogue mais aucune capability ne la porte. Depuis un BRD : colonne « Maps to capability » (§5).",
  'skills.field.capability.none': '— aucune pour le moment —',

  // -- Contract step ------------------------------------------------------
  'skills.contract.input': "Contrat d'entrée",
  'skills.contract.input.hint': 'Ce que la skill attend de recevoir à chaque exécution.',
  'skills.contract.output': 'Contrat de sortie',
  'skills.contract.output.hint': 'Ce que la skill garantit de rendre.',

  // -- Runtime step -------------------------------------------------------
  'skills.runtime.label': 'Comment le travail est fait',
  'skills.runtime.technical': 'Terme technique',
  'skills.runtime.registry_call': 'Encapsuler une skill du socle',
  'skills.runtime.prompt_template': 'Gabarit LLM',
  'skills.runtime.choose': '— choisir —',
  'skills.runtime.target.choose': '— choisir une skill du catalogue —',
  'skills.runtime.optional': 'facultatif',
  'skills.param.provider': 'Fournisseur de modèle',
  'skills.param.template': 'Prompt',
  'skills.param.skill_slug': 'Skill encapsulée',
  'skills.param.frozen_input': 'Entrées prédéfinies',

  // -- Runtime status badge (<ck-runtime-status>) --------------------------
  'skills.runtime.status.bound': 'Prête',
  'skills.runtime.status.bound.hint': "L'implémentation renvoie de vrais résultats.",
  'skills.runtime.status.stub': 'Simulée',
  'skills.runtime.status.stub.hint':
    'Substitut de démonstration — renvoie une réponse vide ou fabriquée.',
  'skills.runtime.status.unbound': 'Sans implémentation',
  'skills.runtime.status.unbound.hint':
    "Déclarée, mais aucune implémentation n'y est encore rattachée.",
  'skills.runtime.status.catalog_only': 'Référencée seulement',
  'skills.runtime.status.catalog_only.hint':
    "Présente au catalogue, mais inconnue du moteur d'exécution.",
  'skills.runtime.status.unknown': 'Inconnue',
  'skills.runtime.status.unknown.hint': "État d'exécution inconnu.",

  // -- Preset inputs ------------------------------------------------------
  'skills.preset_inputs.hint':
    "Valeurs fixées d'avance, fusionnées par-dessus ce que le flow envoie à l'exécution.",
  'skills.preset_inputs.empty':
    "Choisissez d'abord la skill à encapsuler : ses entrées apparaîtront ici.",
  'skills.preset_inputs.no_contract':
    "Cette skill ne déclare pas de contrat d'entrée. Utilisez l'onglet JSON pour prédéfinir des valeurs.",
  'skills.preset_inputs.extra': 'Valeurs sans champ correspondant, conservées telles quelles : {keys}',
  'skills.preset_inputs.advanced': 'JSON avancé',
  'skills.preset_inputs.form': 'Formulaire',

  // -- Review step --------------------------------------------------------
  'skills.review.slug': 'Slug',
  'skills.review.slug.derived': 'Dérivé par le serveur du nom local et de cet espace de travail.',
  'skills.review.slug.frozen': 'Inchangeable : les flows qui appellent cette skill le connaissent.',
  'skills.review.cert': 'Certification',
  'skills.review.cert.value': 'Base',
  'skills.review.cert.hint':
    "Une skill créée ici ne peut pas revendiquer une certification que personne ne lui a accordée.",
  'skills.review.runtime': 'Exécution',
  'skills.review.capability': 'Capability',

  // -- Validation ---------------------------------------------------------
  'skills.problem.local_name': 'Un nom local est requis.',
  'skills.problem.name': "Un nom d'affichage est requis.",
  'skills.problem.runtime': 'Choisissez comment le travail est fait.',
  'skills.problem.required': '{field} est requis par ce mode.',
  'skills.problem.enum': '{field} doit valoir une de ces valeurs : {options}.',
  'skills.problem.maxlength': '{field} dépasse {max} caractères.',
  'skills.problem.json': "{field} n'est pas du JSON valide.",
  'skills.problem.json_object': '{field} doit être un objet JSON, pas une liste ni une valeur simple.',
  'skills.error.create': "La skill n'a pas été créée.",
  'skills.error.update': "La skill n'a pas été enregistrée.",
  'skills.error.delete': "La skill n'a pas été supprimée.",

  // -- Schema builder -----------------------------------------------------
  'skills.schema.tab.fields': 'Champs',
  'skills.schema.tab.json': 'JSON avancé',
  'skills.schema.field.name': 'Nom',
  'skills.schema.field.type': 'Type',
  'skills.schema.field.required': 'Requis',
  'skills.schema.field.description': 'Description',
  'skills.schema.field.default': 'Valeur par défaut',
  'skills.schema.field.items': 'Type des éléments',
  'skills.schema.field.enum': 'Valeurs autorisées',
  'skills.schema.field.enum.hint':
    'Séparées par des virgules ; laissez vide pour accepter toute valeur.',
  'skills.schema.add': 'Ajouter un champ',
  'skills.schema.add_nested': 'Ajouter un sous-champ',
  'skills.schema.remove': 'Retirer',
  'skills.schema.empty': 'Aucun champ. Ajoutez le premier, ou rédigez le contrat en JSON.',
  'skills.schema.locked.title': 'Ce contrat va au-delà de ce que les champs expriment',
  'skills.schema.locked.body':
    "Rien n'est perdu : modifiez-le dans l'onglet JSON, les champs reviendront dès qu'il y rentrera à nouveau.",
  'skills.schema.json.invalid': "JSON invalide — rien n'a été enregistré.",
  'skills.schema.json.not_object':
    'Un contrat doit être un objet JSON, pas une liste ni une valeur simple.',
  'skills.schema.type.string': 'Texte',
  'skills.schema.type.number': 'Nombre',
  'skills.schema.type.integer': 'Entier',
  'skills.schema.type.boolean': 'Oui / non',
  'skills.schema.type.object': 'Objet',
  'skills.schema.type.array': 'Liste',

  // -- Business Requirements import ---------------------------------------
  "skills.brdSystem.title": "Du BRD au système",
  "skills.brdSystem.description": "Relisez les exigences, examinez la proposition, puis créez votre draft.",
  "skills.brdSystem.original": "Ouvrir le BRD original",
  "skills.brdSystem.name": "Nom du système",
  "skills.brdSystem.family": "Type de besoin",
  "skills.brdSystem.summary": "Synthèse documentaire",
  "skills.brdSystem.intervention": "Préparation d’intervention",
  "skills.brdSystem.tools": "Skills disponibles pour ce système",
  "skills.brdSystem.toolsHelp": "Sélectionnez les outils nécessaires. Pour une intervention, prévoyez les notices et l’historique.",
  "skills.brdSystem.generate": "Proposer un système",
  "skills.brdSystem.generating": "Proposition en cours… Vous pouvez reprendre cette page après rechargement.",
  "skills.brdSystem.applying": "Création du draft…",
  "skills.brdSystem.operations": "Opérations proposées",
  "skills.brdSystem.notTested": "Les opérations et les tests sont proposés. Aucun cas n’a encore été exécuté.",
  "skills.brdSystem.uncovered": "Non couverte",
  "skills.brdSystem.proposed": "Couverture proposée",
  "skills.brdSystem.details": "Examiner les contrats, prompts, mappings et tests",
  "skills.brdSystem.review": "J’ai relu cette proposition et ses exigences non couvertes.",
  "skills.brdSystem.apply": "Créer le système en brouillon",
  "skills.brdSystem.revise": "Nouvelle proposition",
  "skills.brdSystem.created": "Draft créé. Ouvrez le Flow pour examiner sa configuration et lancer les tests.",
  "skills.brdSystem.open": "Ouvrir le Flow",
  "skills.brdSystem.testsHelp": "Exécute les cas relus sur le draft actuel. Les appels consomment le budget du workspace ; les revues humaines restent explicites.",
  "skills.brdSystem.testCases": "Tester les cas",
  "skills.brdSystem.newTest": "Nouvel essai sur le draft actuel",
  "skills.brdSystem.refreshTests": "Actualiser les résultats",
  "skills.brdSystem.inspectRun": "Examiner l’exécution",
  "skills.brdSystem.noSuite": "Aucune suite de tests disponible pour ce système.",
  "skills.brdSystem.verdict.pending": "En attente du résultat",
  "skills.brdSystem.verdict.human": "Revue humaine requise",
  "skills.brdSystem.verdict.passed": "Contrôles réussis",
  "skills.brdSystem.verdict.failed": "Contrôle en échec",
  "skills.brdSystem.verdict.unevaluated": "Non évalué",
  "skills.brdSystem.failed": "L’opération n’a pas abouti. Réessayez ou vérifiez la configuration du workspace.",
  'skills.import.title': "Importer un document d'exigences métier",
  'skills.import.description':
    "Conservez le BRD et ses exigences dans ce workspace pour préparer un système. La création du brouillon reste une action explicite.",
  'skills.import.pick': 'Choisir un fichier .docx',
  'skills.import.parsing': 'Lecture du document…',
  'skills.import.failed':
    "Le document n'a pas pu être lu ({reason}). Vous pouvez créer la skill à la main.",
  'skills.import.empty':
    "Aucune ligne exploitable trouvée. Vérifiez que les tableaux du modèle sont remplis.",
  'skills.import.close': 'Fermer',
  'skills.import.context': 'Contexte',
  'skills.import.outcomes': 'Résultats métier attendus',
  'skills.import.requirements': 'Exigences fonctionnelles',
  'skills.import.decisions': "Décisions prises par l'agent",
  'skills.import.guardrails': 'Règles et interdits',
  'skills.import.column.id': 'Réf.',
  'skills.import.column.requirement': 'Exigence',
  'skills.import.column.priority': 'Priorité',
  'skills.import.column.capability': 'Capability visée',
  'skills.import.column.decision': 'Décision',
  'skills.import.column.outcome': 'Résultat',
  'skills.import.column.rule': 'Règle',
  'skills.import.draft': 'Ouvrir un brouillon',
  'skills.import.ignored':
    "Non repris : processus, exigences non fonctionnelles, sources de données, indicateurs, hors périmètre et signatures. Le modèle opérationnel cible n'est pas lu.",
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof SKILLS_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const SKILLS_EN: Record<keyof typeof SKILLS_FR, string> = {
  // -- Catalog ------------------------------------------------------------
  'skills.title': 'Skill registry',
  'skills.list.eyebrow': 'Build · Skills',
  'skills.list.description':
    'Typed, versioned, certified operations — the building blocks systems orchestrate.',
  'skills.list.search': 'Filter skills…',
  'skills.list.new': 'New skill',
  'skills.list.new.hint': 'Define a skill owned by this workspace',
  'skills.list.import': 'Import a BRD',
  'skills.list.import.hint': 'Read a Business Requirements document and draft skills from it',
  'skills.list.loading': 'Loading the registry…',
  'skills.list.empty': 'No skill matches',
  'skills.list.filter.all': 'All',
  'skills.list.totals': 'Registry totals',
  'skills.list.total.skills': 'Skills',
  'skills.list.total.calls': 'Calls',
  'skills.list.total.latency': 'Avg latency',
  'skills.list.total.success': 'Success rate',
  'skills.list.column.cert': 'Cert',
  'skills.list.column.skill': 'Skill',
  'skills.list.column.type': 'Type',
  'skills.list.column.calls': 'Calls',
  'skills.list.column.latency': 'Avg lat',
  'skills.list.column.cost': 'Cost',
  'skills.list.column.success': 'Success',
  'skills.list.column.price': 'Unit price',
  'skills.cost.observed': 'Observed cost',
  'skills.cost.not_measured': 'Not measured',
  'skills.cost.observed.hint': 'Sum of reported costs for accessible invocations; coverage may be partial. The catalog price is separate.',
  'skills.cost.catalog.hint': 'Catalog unit price, separate from observed cost. A zero price does not establish that execution is free.',
  'skills.list.open': 'Open',
  'skills.list.open.hint': 'Open the skill detail',
  'skills.provenance.hint':
    'This skill answers from a model trained here. Open its card.',

  // -- Certification levels (API values) ----------------------------------
  'skills.cert.basic': 'Basic',
  'skills.cert.production': 'Production',
  'skills.cert.enterprise': 'Enterprise',

  // -- Detail panel -------------------------------------------------------
  'skills.detail.input': 'Input contract',
  'skills.detail.output': 'Output contract',
  'skills.detail.execution': 'Execution',
  'skills.detail.performance': 'Live performance',
  'skills.detail.provider': 'Provider',
  'skills.detail.owned': 'Skill owned by this workspace',
  'skills.detail.close': 'Close',
  'skills.exec.mode': 'Mode',
  'skills.exec.timeout': 'Timeout',
  'skills.exec.retryable': 'Retryable',
  'skills.exec.idempotent': 'Idempotent',

  'skills.execution.title': 'Execution settings',
  'skills.execution.edit': 'Edit execution',
  'skills.execution.load_error': 'Could not load the skills available for editing. Try again.',
  'skills.execution.model_hint': 'If the contract accepts a model input, it overrides this setting. The Run records the model actually used.',
  'skills.param.model': 'Model',
  'skills.models.inherit': 'Inherit the configured model',
  'skills.models.saved': 'Saved value, absent from the current catalogue',
  'skills.models.load_error': 'Could not load the model catalogue. Try again.',
  'skills.models.resolve_error': 'The effective configuration could not be resolved. Check the connection in the portal.',
  'skills.models.legacy_azure': 'Public OpenAI (previous identifier: azure)',
  'skills.models.legacy_azure_hint': 'This previous setting uses public OpenAI and the deployment connection. It does not use Azure OpenAI.',
  'skills.models.workspace': 'Use workspace routing',
  'skills.models.unavailable': 'Needs configuration or is incompatible',
  'skills.models.connection_unreachable': 'Connection unavailable',
  'skills.models.open_portal': 'View connections and test · new tab',
  'skills.models.refresh': 'Refresh models',
  'skills.models.effective_provider': 'Effective provider',
  'skills.models.connection_source': 'Connection source',
  'skills.models.model_source': 'Model selection source',
  'skills.models.fallback_used': 'A fallback model was used.',
  'skills.models.fallback_plan': 'Fallback models configured for this workspace',
  'skills.models.source.workspace': 'Workspace configuration',
  'skills.models.source.env': 'Deployment configuration',
  'skills.models.source.global': 'Deployment default',
  'skills.models.source.system': 'System default',
  'skills.models.source.executor': 'Skill setting',
  'skills.models.source.input': 'Execution input',
  'skills.models.source.legacy': 'Preserved historical default',
  'skills.models.source.unknown': 'Source not recorded',
  'skills.models.source.none': 'Local connection without a key',
  'skills.models.source.not_configured': 'Connection needs configuration',
  'skills.execution.unavailable': 'No execution parameters are exposed for this skill.',

  'skills.execution.current': 'Current Skill definition',
  'skills.execution.published': 'Published version configuration',
  'skills.execution.published_hint': 'Draft tests use the current definition. Published version Runs keep the settings below.',
  'skills.execution.open_definition': 'Open current definition',

  // -- Lifecycle ----------------------------------------------------------
  'skills.action.edit': 'Edit',
  'skills.action.delete': 'Delete',
  'skills.delete.ask': 'Delete {name} for good?',
  'skills.delete.confirm': 'Delete',
  'skills.delete.cancel': 'Cancel',
  'skills.notice.created': '{slug} created.',
  'skills.notice.updated': '{slug} saved.',
  'skills.notice.deleted': '{slug} deleted.',
  'skills.notice.claimed': 'Carried by {name}.',
  'skills.notice.claim_failed':
    'The skill exists but no capability could be made to carry it: {reason}',
  'skills.notice.published_bindings':
    'Published in: {names}. Those versions keep the contract frozen at their publication.',

  // -- Authoring wizard ---------------------------------------------------
  'skills.wizard.eyebrow': 'Workspace skill',
  'skills.wizard.title.create': 'New skill',
  'skills.wizard.title.edit': 'Edit skill',
  'skills.wizard.subtitle':
    'The slug is derived from the local name and this workspace. Certification stays Basic.',
  'skills.wizard.subtitle.edit':
    'The slug does not change: the flows that call this skill already carry it.',
  'skills.wizard.step.intent': 'Intent',
  'skills.wizard.step.contract': 'Contract',
  'skills.wizard.step.runtime': 'Execution',
  'skills.wizard.step.review': 'Review',
  'skills.wizard.hint.intent':
    'What should this skill produce, and for which business outcome? For example: find the contractual handling time of a ticket.',
  'skills.wizard.hint.contract':
    'What the skill receives to do its work, and what it hands back. For example: it receives a ticket number, it hands back a delay and a due date.',
  'skills.wizard.hint.runtime': 'How the work actually gets done.',
  'skills.wizard.hint.review': 'What is sent to the server, and what the server decides for you.',
  'skills.wizard.brd.intent':
    'Working from a business requirements document (BRD)? Its business outcomes and functional requirements answer both questions (§4 and §5).',
  'skills.wizard.brd.contract':
    'Working from a BRD? The decisions the agent has to make (D-x) name the inputs this skill needs.',
  'skills.wizard.brd.review':
    'Working from a BRD? Check that the name and the capability match the requirement you started from — that is what keeps the trail from the document to the running skill.',
  'skills.wizard.back': 'Back',
  'skills.wizard.next': 'Next',
  'skills.wizard.cancel': 'Cancel',
  'skills.wizard.create': 'Create skill',
  'skills.wizard.creating': 'Creating…',
  'skills.wizard.save': 'Save',
  'skills.wizard.saving': 'Saving…',

  // -- Presets ------------------------------------------------------------
  'skills.preset.label': 'Start from',
  'skills.preset.scratch': 'A blank page',
  'skills.preset.scratch.summary': 'Declare everything yourself.',
  'skills.preset.llm.summary': "A prompt you write, sent to the workspace's model.",
  'skills.preset.wrapper.summary':
    'Replay a skill the platform provides, with inputs fixed in advance.',

  // -- Intent step --------------------------------------------------------
  'skills.field.local_name': 'Local name',
  'skills.field.local_name.hint': 'The slug is derived from it. Letters, digits and underscores.',
  'skills.field.name': 'Display name',
  'skills.field.description': 'Description',
  'skills.field.description.hint':
    'What the skill does, in one sentence. For example: “Returns the contractual handling time of a ticket.” From a BRD, the wording of the requirement (FR-x) fits as it is.',
  'skills.field.type': 'Type',
  'skills.field.category': 'Category',
  'skills.field.category.hint': 'Decides the group the flow palette files it under.',
  'skills.field.category.none': '— none —',
  'skills.field.capability': 'Carried by the capability',
  'skills.field.capability.hint':
    'The business outcome this skill contributes to. With none, it stays visible in the catalog but no capability carries it. From a BRD: the “Maps to capability” column (§5).',
  'skills.field.capability.none': '— none for now —',

  // -- Contract step ------------------------------------------------------
  'skills.contract.input': 'Input contract',
  'skills.contract.input.hint': 'What the skill expects to receive on every run.',
  'skills.contract.output': 'Output contract',
  'skills.contract.output.hint': 'What the skill guarantees to hand back.',

  // -- Runtime step -------------------------------------------------------
  'skills.runtime.label': 'How the work is done',
  'skills.runtime.technical': 'Technical term',
  'skills.runtime.registry_call': 'Wrap a core skill',
  'skills.runtime.prompt_template': 'LLM prompt template',
  'skills.runtime.choose': '— choose —',
  'skills.runtime.target.choose': '— choose a catalog skill —',
  'skills.runtime.optional': 'optional',
  'skills.param.provider': 'Model provider',
  'skills.param.template': 'Prompt',
  'skills.param.skill_slug': 'Wrapped skill',
  'skills.param.frozen_input': 'Preset inputs',

  // -- Runtime status badge (<ck-runtime-status>) --------------------------
  'skills.runtime.status.bound': 'Ready',
  'skills.runtime.status.bound.hint': 'The implementation returns real results.',
  'skills.runtime.status.stub': 'Simulated',
  'skills.runtime.status.stub.hint':
    'Demo stand-in — returns an empty or made-up answer.',
  'skills.runtime.status.unbound': 'No implementation',
  'skills.runtime.status.unbound.hint': 'Declared, but nothing implements it yet.',
  'skills.runtime.status.catalog_only': 'Listed only',
  'skills.runtime.status.catalog_only.hint':
    'Present in the catalog, but the execution engine has never seen it.',
  'skills.runtime.status.unknown': 'Unknown',
  'skills.runtime.status.unknown.hint': 'Runtime status unknown.',

  // -- Preset inputs ------------------------------------------------------
  'skills.preset_inputs.hint':
    'Values fixed in advance, merged over whatever the flow sends at run time.',
  'skills.preset_inputs.empty': 'Pick the skill to wrap first: its inputs will appear here.',
  'skills.preset_inputs.no_contract':
    'This skill declares no input contract. Use the JSON tab to preset values.',
  'skills.preset_inputs.extra': 'Values with no matching field, kept as they are: {keys}',
  'skills.preset_inputs.advanced': 'Advanced JSON',
  'skills.preset_inputs.form': 'Form',

  // -- Review step --------------------------------------------------------
  'skills.review.slug': 'Slug',
  'skills.review.slug.derived': 'Derived by the server from the local name and this workspace.',
  'skills.review.slug.frozen': 'Unchangeable: the flows calling this skill know it by this name.',
  'skills.review.cert': 'Certification',
  'skills.review.cert.value': 'Basic',
  'skills.review.cert.hint':
    'A skill authored here cannot claim a certification nobody granted it.',
  'skills.review.runtime': 'Execution',
  'skills.review.capability': 'Capability',

  // -- Validation ---------------------------------------------------------
  'skills.problem.local_name': 'A local name is required.',
  'skills.problem.name': 'A display name is required.',
  'skills.problem.runtime': 'Choose how the work gets done.',
  'skills.problem.required': '{field} is required by this mode.',
  'skills.problem.enum': '{field} must be one of: {options}.',
  'skills.problem.maxlength': '{field} exceeds {max} characters.',
  'skills.problem.json': '{field} is not valid JSON.',
  'skills.problem.json_object': '{field} must be a JSON object, not a list or a single value.',
  'skills.error.create': 'The skill was not created.',
  'skills.error.update': 'The skill was not saved.',
  'skills.error.delete': 'The skill was not deleted.',

  // -- Schema builder -----------------------------------------------------
  'skills.schema.tab.fields': 'Fields',
  'skills.schema.tab.json': 'Advanced JSON',
  'skills.schema.field.name': 'Name',
  'skills.schema.field.type': 'Type',
  'skills.schema.field.required': 'Required',
  'skills.schema.field.description': 'Description',
  'skills.schema.field.default': 'Default',
  'skills.schema.field.items': 'Item type',
  'skills.schema.field.enum': 'Allowed values',
  'skills.schema.field.enum.hint': 'Comma-separated; leave empty to accept any value.',
  'skills.schema.add': 'Add a field',
  'skills.schema.add_nested': 'Add a sub-field',
  'skills.schema.remove': 'Remove',
  'skills.schema.empty': 'No field yet. Add the first one, or write the contract as JSON.',
  'skills.schema.locked.title': 'This contract goes beyond what the fields express',
  'skills.schema.locked.body':
    'Nothing is lost: edit it in the JSON tab, and the fields come back as soon as it fits them again.',
  'skills.schema.json.invalid': 'Invalid JSON — nothing was saved.',
  'skills.schema.json.not_object':
    'A contract must be a JSON object, not a list or a single value.',
  'skills.schema.type.string': 'Text',
  'skills.schema.type.number': 'Number',
  'skills.schema.type.integer': 'Integer',
  'skills.schema.type.boolean': 'Yes / no',
  'skills.schema.type.object': 'Object',
  'skills.schema.type.array': 'List',

  // -- Business Requirements import ---------------------------------------
  "skills.brdSystem.title": "From BRD to System",
  "skills.brdSystem.description": "Review the requirements, examine the proposal, then create your draft.",
  "skills.brdSystem.original": "Open original BRD",
  "skills.brdSystem.name": "System name",
  "skills.brdSystem.family": "Requirement family",
  "skills.brdSystem.summary": "Document summary",
  "skills.brdSystem.intervention": "Intervention preparation",
  "skills.brdSystem.tools": "Skills available to this System",
  "skills.brdSystem.toolsHelp": "Select the required tools. For intervention preparation, include manuals and intervention history.",
  "skills.brdSystem.generate": "Propose a System",
  "skills.brdSystem.generating": "Generating the proposal… You can resume this page after reloading.",
  "skills.brdSystem.applying": "Creating the draft…",
  "skills.brdSystem.operations": "Proposed operations",
  "skills.brdSystem.notTested": "Operations and tests are proposed. No case has been executed yet.",
  "skills.brdSystem.uncovered": "Not covered",
  "skills.brdSystem.proposed": "Proposed coverage",
  "skills.brdSystem.details": "Inspect contracts, prompts, mappings and tests",
  "skills.brdSystem.review": "I have reviewed this proposal and its uncovered requirements.",
  "skills.brdSystem.apply": "Create System draft",
  "skills.brdSystem.revise": "New proposal",
  "skills.brdSystem.created": "Draft created. Open the Flow to inspect its configuration and run the tests.",
  "skills.brdSystem.open": "Open the Flow",
  "skills.brdSystem.testsHelp": "Run reviewed cases on the current draft. Calls use the workspace budget; human reviews remain explicit.",
  "skills.brdSystem.testCases": "Test cases",
  "skills.brdSystem.newTest": "New attempt on current draft",
  "skills.brdSystem.refreshTests": "Refresh results",
  "skills.brdSystem.inspectRun": "Inspect Run",
  "skills.brdSystem.noSuite": "No test suite is available for this System.",
  "skills.brdSystem.verdict.pending": "Awaiting result",
  "skills.brdSystem.verdict.human": "Human review required",
  "skills.brdSystem.verdict.passed": "Checks passed",
  "skills.brdSystem.verdict.failed": "Check failed",
  "skills.brdSystem.verdict.unevaluated": "Not evaluated",
  "skills.brdSystem.failed": "The operation failed. Retry or check the workspace configuration.",
  'skills.import.title': 'Import a business requirements document',
  'skills.import.description':
    'Keep the BRD and its requirements in this workspace to prepare a System. Creating the draft remains an explicit action.',
  'skills.import.pick': 'Choose a .docx file',
  'skills.import.parsing': 'Reading the document…',
  'skills.import.failed':
    'The document could not be read ({reason}). You can still author the skill by hand.',
  'skills.import.empty':
    'No usable row found. Check that the template tables are filled in.',
  'skills.import.close': 'Close',
  'skills.import.context': 'Context',
  'skills.import.outcomes': 'Business outcomes',
  'skills.import.requirements': 'Functional requirements',
  'skills.import.decisions': 'Decisions the agent makes',
  'skills.import.guardrails': 'Rules and prohibitions',
  'skills.import.column.id': 'Ref.',
  'skills.import.column.requirement': 'Requirement',
  'skills.import.column.priority': 'Priority',
  'skills.import.column.capability': 'Target capability',
  'skills.import.column.decision': 'Decision',
  'skills.import.column.outcome': 'Outcome',
  'skills.import.column.rule': 'Rule',
  'skills.import.draft': 'Open a draft',
  'skills.import.ignored':
    'Not taken in: process steps, non-functional requirements, data sources, KPIs, out of scope and signatures. The target operating model is not read.',
};
