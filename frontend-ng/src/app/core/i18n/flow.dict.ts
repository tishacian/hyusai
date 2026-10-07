/**
 * Flow builder: canvas, palette, inspector, workbench, terminal,
 * publication, versions.
 *
 * Ordered by surface, in the order a builder meets them: the shell, the
 * toolbar, the canvas, the palette, the inspector and its editors, then the
 * operating surfaces (run controls, terminal, workbench) and the release
 * surfaces (publication, versions).
 *
 * Two-register rule: the plain word is the key's value; the raw engine term
 * (node kind, runtime status, execution mode, content hash) is served by a
 * `*.raw` / `*.detail` key rendered on a secondary line or in a `title`.
 *
 * Accepted key prefixes: 'flow.'. See `./CONVENTION.md`.
 */

export const FLOW_FR = {
  'flow.sources.title': 'Source de données',
  'flow.sources.palette': 'Sources du workspace',
  'flow.sources.connector': 'Connecteur',
  'flow.sources.configured_reference': 'Configuration enregistrée · référence',
  'flow.sources.collection': 'Collection documentaire',
  'flow.sources.live': 'Lecture en direct',
  'flow.sources.reference': 'Référence',
  'flow.sources.live_help': 'Les étapes liées reçoivent cette référence. Seules celles dont l’outil sait lire PostgreSQL l’interrogent, avec les droits du workspace ; pour les autres, la liaison documente la dépendance. L’aperçu est un échantillon ; un import DataOps crée un dataset versionné distinct.',
  'flow.sources.reference_help': 'Ce nœud fournit une référence au connecteur. L’étape consommatrice réalise la lecture ou l’action avec son propre contrat.',
  'flow.sources.setup': 'Ouvrir le connecteur',
  'flow.sources.browse': 'Parcourir les tables',
  'flow.sources.refresh': 'Actualiser',
  'flow.sources.loading': 'Chargement des sources…',
  'flow.sources.retry': 'Réessayer',
  'flow.sources.catalog_error': 'Catalogue indisponible. Les références enregistrées sont conservées.',
  'flow.sources.empty': 'Aucune source configurée dans ce workspace.',
  'flow.sources.unavailable': 'indisponible',
  'flow.sources.missing': 'Le connecteur référencé n’est plus configuré dans ce workspace.',
  'flow.sources.admin_required': 'Un administrateur du workspace peut parcourir et prévisualiser les tables.',
  'flow.sources.resources': 'Périmètre · {count} tables',
  'flow.sources.resources_one': 'Périmètre · {count} table',
  'flow.sources.remove': 'Retirer la table {table} du périmètre',
  'flow.sources.no_resources': 'Sélectionnez les tables accessibles aux étapes liées.',
  'flow.sources.checked': 'Connexion vérifiée le {at}',
  'flow.sources.no_tables': 'Aucune table accessible avec ce compte.',
  'flow.sources.choose_table': 'Choisir une table',
  'flow.sources.columns': '{count} colonnes',
  'flow.sources.preview': 'Aperçu · 25 lignes',
  'flow.sources.bound': 'Dans le périmètre',
  'flow.sources.add_resource': 'Ajouter au périmètre',
  'flow.sources.sample': 'Échantillon lu le {at}',
  'flow.sources.consumers': 'Étapes liées',
  'flow.sources.no_consumers': 'Aucune étape liée à cette source.',
  'flow.sources.connect': 'Relier une étape',
  'flow.sources.choose_consumer': 'Choisir une étape du Flow',
  'flow.sources.tables_count': '{count} tables',
  "flow.versions.blocked.matches_published": "Le brouillon enregistré correspond déjà à cette version publiée.",
  "flow.versions.blocked.current": "Il s’agit déjà de la version courante.",
  "flow.versions.blocked.history": "L’historique n’a pas pu être chargé. Actualisez-le avant de restaurer une version.",
  "flow.versions.blocked.local_changes": "Enregistrez ou abandonnez vos modifications locales avant de restaurer une version.",
  "flow.versions.blocked.pending": "Une restauration est déjà en cours.",
  "flow.versions.blocked.write": "Attendez la fin du chargement ou de l’enregistrement du Flow.",
  "flow.versions.evidence.missing_payload": "Le contenu de la version enregistrée n’a pas été renvoyé.",
  "flow.versions.evidence.wrong_payload": "Le contenu reçu ne correspond pas à la version sélectionnée dans l’historique.",
  "flow.versions.evidence.malformed_flow": "Le Flow de cette version est mal formé.",
  "flow.versions.evidence.malformed_contract": "Le contrat d’exécution de cette version est mal formé.",
  "flow.versions.evidence.missing_diff": "La comparaison sémantique du serveur n’a pas été renvoyée.",
  "flow.versions.evidence.missing_digest": "L’empreinte de cette version est absente.",
  "flow.versions.evidence.wrong_digest": "L’empreinte reçue ne correspond pas à celle de la version dans l’historique.",
  "flow.versions.evidence.wrong_base": "La comparaison sémantique ne décrit pas la version sélectionnée.",
  "flow.versions.evidence.wrong_base_digest": "L’empreinte de référence de la comparaison ne correspond pas à cette version.",
  "flow.versions.evidence.wrong_revision": "La comparaison sémantique ne décrit pas la révision courante du brouillon enregistré.",
  "flow.versions.evidence.wrong_target_digest": "L’empreinte cible de la comparaison ne correspond pas au brouillon enregistré.",
  "flow.versions.history_error": "L’historique n’a pas pu être chargé. Les versions affichées peuvent ne plus être à jour.",
  "flow.versions.preview.local_changes": "Enregistrez ou abandonnez vos modifications locales avant de vérifier la restauration.",
  "flow.versions.preview.reload": "Rechargez d’abord le brouillon enregistré et la version publiée.",
  "flow.versions.preview.unverified": "L’aperçu exact n’a pas pu être vérifié.",
  "flow.versions.preview.verification_failed": "Impossible de vérifier le contenu de la version et la comparaison sémantique du serveur.",
  "flow.versions.preview.load_failed": "Impossible de charger le contenu de cette version.",
  "flow.versions.preview.failed": "L’aperçu exact a échoué.",
  "flow.versions.more_error": "Impossible de charger les versions supplémentaires.",
  "flow.versions.restore_hint.published": "Restaurer cette version dans le brouillon enregistré ; la version publiée reste inchangée",
  "flow.versions.restore_hint.draft": "Restaurer cette version en ajoutant une copie de son graphe",
  "flow.versions.confirm.verify_first": "Chargez et vérifiez la version exacte avant de confirmer.",
  "flow.versions.blocked.title": "Restauration bloquée",
  "flow.versions.blocked.restore_title": "Restauration bloquée",
  "flow.versions.confirm.local_changes": "Enregistrez ou abandonnez vos modifications locales avant de restaurer.",
  "flow.versions.confirm.reload_system": "Rechargez le système enregistré avant de restaurer.",
  "flow.versions.rollback_unknown": "Le résultat de la restauration est inconnu. Rechargement du Flow enregistré.",
  "flow.versions.rollback_verification": "Vérification de la restauration",
  "flow.versions.rollback_title": "Restauration",
  "flow.versions.restore.reload_draft": "Rechargez le brouillon enregistré avant de restaurer une version.",
  "flow.versions.restore.success_title": "Brouillon restauré",
  "flow.versions.restore.unknown": "Le résultat de la restauration est inconnu. Rechargement du brouillon enregistré.",
  "flow.versions.restore.verification": "Vérification de la restauration",
  "flow.versions.diff.server_unavailable": "Comparaison sémantique du serveur indisponible",
  "flow.versions.rollback_message": "Restauration vers la v{version}",
  "flow.versions.rollback_success": "Version v{version} restaurée (nouvelle v{newVersion}).",
  "flow.versions.restore.success": "Version v{version} restaurée dans le brouillon enregistré. Le Flow publié reste inchangé.",
  "flow.versions.diff.counts_match": "Comptages identiques · ouvrez l’aperçu pour comparer le contenu",
  "flow.versions.diff.counts": "Écart de comptage : {counts} · ouvrez l’aperçu pour comparer le contenu",
  "flow.versions.graph_counts": "{nodes} nœuds · {edges} connexions",
  "flow.versions.diff.breaking": "{count} rupture",
  "flow.versions.diff.behavioral": "{count} comportement",
  "flow.versions.diff.presentation": "{count} présentation",
  "flow.versions.diff.node_order": "↕ ordre des nœuds",
  "flow.versions.diff.edge_order": "↕ ordre des connexions",
  "flow.versions.diff.contract": "~contrat",
  "flow.versions.diff.server_equal": "= brouillon (vérifié par le serveur)",
  "flow.versions.diff.flow": "~Flow",
  "flow.versions.diff.pinned_contract": "Contrat fixé · non comparable au brouillon",
  "flow.versions.diff.unavailable_contract": "Contrat indisponible · non comparable au brouillon",
  "flow.versions.diff.canvas_equal": "= canevas",

  // ---- shell -------------------------------------------------------------
  'flow.builder.crumb.systems': 'Systèmes',
  'flow.builder.crumb.here': 'Éditeur de Flow',
  'flow.builder.crumb.scratchpad': 'Flow libre',
  'flow.builder.title': 'Éditeur de Flow',
  'flow.builder.boundary.draft': 'Brouillon serveur r{revision}',
  'flow.builder.boundary.detail':
    "Tester le brouillon exécute cette révision enregistrée. Le lanceur opérateur et le point d'entrée continuent de servir la version publiée v{version} jusqu'à une publication explicite.",
  'flow.builder.boundary.contract':
    "Publication requise : la base de migration reste non exécutable tant que ce brouillon n'est pas publié.",
  'flow.builder.runtime.details': "Détails d'exécution",
  'flow.builder.runtime.surface': "Surface d'exécution",
  'flow.builder.runtime.mode': "Mode d'exécution",
  'flow.builder.autosave.paused': 'Sauvegarde automatique en pause.',
  'flow.builder.autosave.paused.body':
    "Ce remplacement massif ou destructif reste local tant que vous ne l'enregistrez pas explicitement.",
  'flow.builder.autosave.reload': 'Recharger le Flow du serveur',
  'flow.builder.autosave.review': 'Relire et enregistrer',
  'flow.builder.autosave.discard': 'Abandonner les modifications locales',
  'flow.builder.autosave.hold': 'Sauvegarde automatique suspendue',
  'flow.builder.autosave.hold.hint':
    "L'atelier d'essai est ouvert : rien n'est enregistré automatiquement. Fermez-le, ou enregistrez explicitement.",
  'flow.builder.empty.title': 'Commencez votre premier Flow',
  'flow.builder.empty.body':
    'Trois étapes suffisent : ce qui le démarre, le travail (une skill, ou une boucle agent qui choisit la prochaine), où part le résultat.',
  'flow.builder.empty.step1': '1 · Déclencheur — ce qui démarre le Flow',
  'flow.builder.empty.step2': '2 · Skill ou Boucle agent — le travail, ou l’enveloppe qui choisit',
  'flow.builder.empty.step3': '3 · Sortie — où part le résultat',
  'flow.builder.empty.cta': 'Ajouter le premier nœud',
  'flow.builder.handle.aria': 'Insérer un nœud connecté',
  'flow.builder.handle.insert.target': 'Insérer un nœud cible',
  'flow.builder.handle.insert.source': 'Insérer un nœud source',
  'flow.builder.handle.empty': 'Aucun nœud compatible en type.',
  'flow.builder.handle.more': 'Chercher parmi les {count} compatibles…',
  'flow.builder.load.loading': 'Chargement du Flow enregistré…',
  'flow.builder.load.loading.body':
    "L'édition et l'exécution restent verrouillées jusqu'à la fin du chargement.",
  'flow.builder.load.error': 'Chargement du Flow bloqué',
  'flow.builder.load.retry': 'Réessayer un rechargement strict',
  'flow.builder.error.malformed': 'Le Flow enregistré est mal formé.',
  'flow.builder.error.rollback': 'La restauration a renvoyé un Flow mal formé.',
  'flow.builder.error.generic':
    "Le Système n'a pas pu être chargé. Aucun graphe de repli n'a été ouvert, le Flow enregistré ne peut donc pas être écrasé par accident.",
  'flow.builder.clear.title': 'Vider ce Flow ?',
  'flow.builder.clear.description':
    "Cette action retire localement {nodes} nœuds et {edges} liaisons. La sauvegarde automatique se met en pause ; le Flow enregistré est inchangé tant que vous n'enregistrez pas explicitement.",
  'flow.builder.clear.confirm': 'Vider et mettre la sauvegarde en pause',
  'flow.builder.clear.cancel': 'Conserver le Flow',
  'flow.builder.replace.title': 'Remplacer le Flow actif ?',
  'flow.builder.replace.description':
    "Ce remplacement change le graphe d'exécution d'un Système actif. Il sera envoyé une seule fois, avec une autorité de remplacement explicite ; la sauvegarde automatique reste en pause.",
  'flow.builder.replace.confirm': 'Remplacer le Flow actif',
  'flow.builder.replace.cancel': 'Continuer la relecture',
  'flow.builder.view.aria': "Mode d'affichage du Flow",
  'flow.builder.view.canvas': 'Canevas',
  'flow.builder.view.outline': 'Plan accessible',

  // ---- accessible outline ----------------------------------------------
  'flow.outline.title': 'Plan du Flow',
  'flow.outline.help':
    "Sélectionnez une étape pour l’inspecter. Flèches haut/bas pour parcourir ; Alt + flèche haut/bas pour changer son ordre. Les positions et les liaisons sont modifiables au clavier ci-dessous.",
  'flow.outline.count': 'Étapes : {count}',
  'flow.outline.nodes': 'Étapes dans l’ordre',
  'flow.outline.inspect': 'Sélectionner et inspecter {name}',
  'flow.outline.routes': 'Entrantes {incoming} · sortantes {outgoing}',
  'flow.outline.move': 'Ordre et position sur le canevas',
  'flow.outline.move.aria': 'Déplacer {name}',
  'flow.outline.order.before': 'Placer {name} une ligne plus tôt',
  'flow.outline.order.after': 'Placer {name} une ligne plus tard',
  'flow.outline.order.before.short': 'Plus tôt',
  'flow.outline.order.after.short': 'Plus tard',
  'flow.outline.position.x': 'Position X',
  'flow.outline.position.y': 'Position Y',
  'flow.outline.empty': 'Aucune étape. Ajoutez-en une depuis la palette.',
  'flow.outline.connections': 'Liaisons',
  'flow.outline.connect': 'Créer une liaison',
  'flow.outline.connect.source': 'Depuis la sortie',
  'flow.outline.connect.source.placeholder': 'Choisir une sortie…',
  'flow.outline.connect.target': "Vers l’entrée",
  'flow.outline.connect.target.placeholder': 'Choisir une entrée compatible…',
  'flow.outline.connect.no_target': 'Aucune entrée compatible disponible.',
  'flow.outline.connect.duplicate': 'Cette liaison existe déjà.',
  'flow.outline.connect.action': 'Créer la liaison',
  'flow.outline.connections.current': 'Liaisons actuelles',
  'flow.outline.disconnect': 'Supprimer la liaison {edge}',
  'flow.outline.disconnect.short': 'Supprimer',
  'flow.outline.connections.empty': 'Aucune liaison.',
  'flow.outline.connector.option': '{node} · port {port}',
  'flow.outline.port.default': 'par défaut',
  'flow.outline.edge.label':
    '{source}, port {sourcePort}, vers {target}, port {targetPort}',
  'flow.outline.announcement.reordered': '{name} a changé de place.',
  'flow.outline.announcement.moved': 'La position de {name} a été modifiée.',
  'flow.outline.announcement.connected': 'Liaison créée : {edge}.',
  'flow.outline.announcement.disconnected': 'Liaison supprimée : {edge}.',

  // ---- execution mode & runtime status (plain word, raw kept as detail) ---
  'flow.runtime.mode.dag_strict': 'Exécution en graphe',
  'flow.runtime.mode.dag_overlay': 'Mode compatibilité',
  'flow.runtime.mode.sequential_legacy': 'Exécution pas à pas',
  'flow.runtime.mode.chat': 'Exécution dans le chat',
  'flow.runtime.mode.unknown': "Mode d'exécution inconnu",
  'flow.runtime.surface.draft': "Essai du brouillon",
  'flow.runtime.surface.published': 'Exécution publiée',

  // ---- toolbar -----------------------------------------------------------
  'flow.toolbar.aria': 'Outils du Flow',
  'flow.toolbar.nodes': '{count} nœuds',
  'flow.toolbar.state.saving': 'Enregistrement…',
  'flow.toolbar.state.hold': 'Sauvegarde auto en pause',
  'flow.toolbar.state.unsaved': 'Non enregistré',
  'flow.toolbar.state.error': 'Échec de sauvegarde',
  'flow.toolbar.state.saved': 'Enregistré',
  'flow.toolbar.state.title.review':
    "Relecture requise — la sauvegarde automatique est en pause jusqu'à ce que vous enregistriez ou abandonniez ce remplacement.",
  'flow.toolbar.state.title.paused':
    'Sauvegarde automatique en pause — relisez ces modifications, puis enregistrez.',
  'flow.toolbar.state.title.saving': 'Enregistrement en cours…',
  'flow.toolbar.state.title.unsaved':
    'Modifications non enregistrées — sauvegarde automatique, ou Ctrl/Cmd+S.',
  'flow.toolbar.state.title.error':
    'La dernière sauvegarde a échoué — modifiez à nouveau pour réessayer.',
  'flow.toolbar.state.title.saved': 'Toutes les modifications sont enregistrées.',
  'flow.toolbar.version.draft': 'Brouillon r{revision}',
  'flow.toolbar.version.published': 'Publié v{version}',
  'flow.toolbar.version.fingerprint': 'Empreinte de contenu : {hash}',
  'flow.toolbar.palette.expand': 'Ouvrir la palette de nœuds',
  'flow.toolbar.palette.collapse': 'Replier la palette de nœuds',
  'flow.toolbar.palette.aria': 'Basculer la palette de nœuds',
  'flow.toolbar.inspector.expand': "Ouvrir l'inspecteur de nœud",
  'flow.toolbar.inspector.collapse': "Replier l'inspecteur de nœud",
  'flow.toolbar.inspector.aria': "Basculer l'inspecteur de nœud",
  'flow.toolbar.undo': 'Annuler (Ctrl/Cmd+Z)',
  'flow.toolbar.undo.aria': 'Annuler',
  'flow.toolbar.redo': 'Rétablir (Ctrl/Cmd+Maj+Z)',
  'flow.toolbar.redo.aria': 'Rétablir',
  'flow.toolbar.zoom_in': 'Zoom avant',
  'flow.toolbar.zoom_out': 'Zoom arrière',
  'flow.toolbar.fit': 'Ajuster',
  'flow.toolbar.fit.aria': 'Ajuster à la vue',
  'flow.toolbar.arrange': 'Ranger',
  'flow.toolbar.arrange.hint':
    'Réorganiser automatiquement — repositionne tous les nœuds (Ctrl/Cmd+Z pour annuler)',
  'flow.toolbar.arrange.aria': 'Réorganiser tous les nœuds',
  'flow.toolbar.validate': 'Vérifier',
  'flow.toolbar.validate.busy': 'Vérification…',
  'flow.toolbar.validate.hint': 'Vérifier la révision courante du Flow sur le serveur',
  'flow.toolbar.validate.hint.busy': 'Vérification de la révision courante du Flow…',
  'flow.toolbar.validate.aria': 'Vérifier le Flow courant',
  'flow.toolbar.save': 'Enregistrer',
  'flow.toolbar.save.busy': 'Enregistrement…',
  'flow.toolbar.save.aria': 'Enregistrer le Flow',
  'flow.toolbar.save.blocked':
    "Corrigez les erreurs de vérification serveur avant d'enregistrer",
  'flow.toolbar.save.system': 'Enregistrer le Flow dans le Système (Ctrl/Cmd+S)',
  'flow.toolbar.save.scratch': 'Enregistrer le brouillon libre en local (Ctrl/Cmd+S)',
  'flow.toolbar.publish': 'Publier',
  'flow.toolbar.publish.hint':
    "Relire l'écart sémantique et publier une version immuable (n'active pas le Système)",
  'flow.toolbar.publish.aria': 'Relire et publier le brouillon serveur',
  'flow.toolbar.promote': 'Vers un Système',
  'flow.toolbar.promote.busy': 'Enregistrement…',
  'flow.toolbar.promote.hint': 'Enregistrer ce brouillon libre comme un vrai Système',
  'flow.toolbar.promote.aria': 'Enregistrer comme Système',
  'flow.toolbar.operate': 'Exploiter',
  'flow.toolbar.operate.hint': 'Exécuter, déboguer, rejouer et tester ce Flow',
  'flow.toolbar.more': 'Plus',
  'flow.toolbar.more.hint': "Options d'affichage, import / export, partage et vidage",
  'flow.toolbar.more.aria': 'Autres actions',
  'flow.toolbar.workbench': "Atelier d'essai",
  'flow.toolbar.workbench.hint':
    "Tester le Flow local exact sans l'enregistrer ni le publier",
  'flow.toolbar.workbench.blocked':
    "Transformez ce brouillon libre en Système avant de lancer des essais",
  'flow.toolbar.workbench.aria': "Basculer l'atelier d'essai local",
  'flow.toolbar.focus': 'Plein écran',
  'flow.toolbar.focus.exit': 'Quitter le plein écran',
  'flow.toolbar.focus.hint': 'Afficher le canevas en plein écran',
  'flow.toolbar.focus.exit.hint': 'Quitter le plein écran du canevas',
  'flow.toolbar.focus.aria': 'Basculer le plein écran du canevas',
  'flow.toolbar.compact.expand': 'Afficher les libellés de la barre',
  'flow.toolbar.compact.collapse': 'Compacter la barre',
  'flow.toolbar.compact.aria': 'Basculer la barre compacte',
  'flow.toolbar.routing': 'Tracé des liaisons : {mode}',
  'flow.toolbar.routing.aria': 'Changer le tracé des liaisons',
  'flow.toolbar.export': 'Exporter',
  'flow.toolbar.export.hint': 'Exporter le Flow en JSON',
  'flow.toolbar.export.aria': 'Exporter le Flow',
  'flow.toolbar.import': 'Importer',
  'flow.toolbar.import.hint': 'Importer un Flow JSON (aller-retour)',
  'flow.toolbar.import.aria': 'Importer un Flow',
  'flow.toolbar.share': 'Partager',
  'flow.toolbar.share.hint': 'Copier un lien de partage vers ce Flow',
  'flow.toolbar.share.aria': 'Partager le Flow',
  'flow.toolbar.clear': 'Vider le canevas',
  'flow.toolbar.clear.aria': 'Vider le canevas',

  // ---- node card ---------------------------------------------------------
  'flow.node.delete': 'Supprimer le nœud {name}',
  'flow.node.delete.hint': 'Supprimer le nœud {name} (Suppr/Retour arrière)',
  'flow.node.run_step': 'Exécuter cette étape : {name}',
  'flow.node.run_step.hint': 'Ouvrir l’aperçu isolé de {name}',
  'flow.node.breakpoint.set': 'Poser un point d’arrêt',
  'flow.node.breakpoint.remove': 'Retirer le point d’arrêt',
  'flow.node.breakpoint.aria': 'Basculer le point d’arrêt',
  'flow.node.configured': 'Configuré',
  'flow.node.not_configured': 'Pas encore configuré',
  'flow.node.kind.source': 'DÉCLENCHEUR',
  'flow.node.kind.sink': 'SORTIE',
  'flow.node.kind.asset': 'DONNÉES',
  'flow.node.kind.decision': 'DÉCISION',
  'flow.node.kind.fork': 'DIVISION',
  'flow.node.kind.join': 'FUSION',
  'flow.node.kind.loop': 'BOUCLE',
  'flow.node.kind.agent_loop': 'BOUCLE AGENT',
  'flow.node.agent_loop.empty_objective': 'Objectif encore vide — ouvrez l’inspecteur',
  'flow.node.kind.retry': 'RÉESSAI',
  'flow.node.kind.hitl': 'PORTE HUMAINE',
  'flow.node.kind.subflow': 'SOUS-FLOW',
  'flow.node.kind.skill': 'SKILL',
  'flow.node.kind.runtime': 'EXÉCUTION',
  'flow.node.run.rows_delta': '{from} → {to} lignes',
  'flow.node.run.rows': '{rows} lignes',
  'flow.node.run.predictions': '{count} prédiction(s)',
  'flow.node.run.metric': '{metric} {value}',
  'flow.node.run.duration': '{duration}',
  'flow.node.run.model': 'Modèle qui a répondu sur ce nœud',

  // ---- palette -----------------------------------------------------------
  'flow.palette.aria': 'Palette de nœuds',
  'flow.palette.heading.context': 'Se connecte ici',
  'flow.palette.heading.matches': 'Résultats',
  'flow.palette.heading.all': 'Toutes les skills',
  'flow.palette.heading.add': 'Ajouter un nœud',
  'flow.palette.heading.count': 'Nombre de {name}',
  'flow.palette.context.connects': 'Se connecte à',
  'flow.palette.context.clear': 'Tout afficher',
  'flow.palette.search': 'Chercher ou décrire une étape…',
  'flow.palette.search.context': 'Chercher ce qui se connecte ici…',
  'flow.palette.search.results': '{count} résultats compatibles.',
  'flow.palette.search.results.aria': 'Résultats de la recherche de nœuds',
  'flow.palette.catalog.loading': 'Chargement du catalogue de skills…',
  'flow.palette.catalog.error': 'Catalogue de skills indisponible.',
  'flow.palette.catalog.retry': 'Réessayer',
  'flow.palette.empty.context': 'Aucun nœud compatible en type.',
  'flow.palette.empty.query': 'Rien de disponible ne correspond à « {query} ».',
  'flow.palette.empty.show_all': 'Afficher tous les nœuds',
  'flow.palette.overflow': '{count} de plus — affinez la recherche.',
  'flow.palette.unavailable.one':
    '1 skill du registre correspond mais n’est pas disponible dans cet espace de travail.',
  'flow.palette.unavailable.many':
    '{count} skills du registre correspondent mais ne sont pas disponibles dans cet espace de travail.',
  'flow.palette.unavailable.link': 'Ajuster la visibilité du catalogue',
  'flow.palette.unavailable.toggle': '{count} dans le registre, indisponibles ici',
  'flow.palette.back': 'Capabilities',
  'flow.palette.section.capabilities': 'Capabilities',
  'flow.palette.section.most_used': 'Utilisées dans cet espace de travail',
  'flow.palette.section.structure': 'Structure',
  'flow.palette.section.empty.skills': 'Aucune skill disponible dans cet espace de travail.',
  'flow.palette.section.empty.capabilities':
    'Aucune capability ne porte de skill dans cet espace de travail.',
  'flow.palette.advanced': 'Avancé — tout le registre',
  'flow.palette.row.in_flow': 'dans ce Flow',
  'flow.palette.row.in_flow.hint': 'Déjà utilisée dans ce Flow',
  'flow.palette.row.usage': '{count} exécutions dans cet espace de travail',
  'flow.palette.row.runtime': 'État d’exécution : {status}',

  // ---- validation strip --------------------------------------------------
  'flow.checklist.aria': 'Liste de contrôle du Flow',
  'flow.checklist.title': 'Liste de contrôle',
  'flow.checklist.checking': 'Vérification de la révision courante…',
  'flow.checklist.server_error': 'Vérification serveur indisponible',
  'flow.checklist.errors.one': '1 erreur',
  'flow.checklist.errors.many': '{count} erreurs',
  'flow.checklist.warnings.one': '1 avertissement',
  'flow.checklist.warnings.many': '{count} avertissements',
  'flow.checklist.reveal': 'Afficher le nœud {name}',
  'flow.checklist.server_tag': 'serveur',
  'flow.checklist.server_tag.hint': 'Fait autorité pour l’empreinte courante du graphe',
  'flow.checklist.code.hint': 'Code de diagnostic {code} — à citer au support.',

  // ---- diagnostic codes → what is missing, and what to do ----------------
  // Keyed by the code the client serializer and the server analyser share.
  // A `{name}` message is only used when the row carries a node; otherwise
  // the raw server sentence is shown rather than a leftover placeholder.
  'flow.checklist.code.flow_invalid':
    'Le Flow enregistré n’a pas pu être lu. Rechargez-le, ou restaurez une version antérieure.',
  'flow.checklist.code.nodes_invalid':
    'La liste des nœuds du Flow n’est pas lisible. Rechargez le Flow avant de continuer à l’éditer.',
  'flow.checklist.code.node_invalid':
    'Le nœud « {name} » est mal formé : il lui manque l’identité ou la nature attendue par le moteur.',
  'flow.checklist.code.edges_invalid':
    'La liste des liaisons du Flow n’est pas lisible. Rechargez le Flow avant de continuer à l’éditer.',
  'flow.checklist.code.edge_invalid':
    'Une liaison est mal formée. Supprimez-la sur le canevas et retracez-la.',
  'flow.checklist.code.node_id_duplicate':
    'Deux nœuds portent le même identifiant. Renommez ou supprimez l’un des deux : chaque nœud a besoin du sien.',
  'flow.checklist.code.edge_duplicate':
    'Cette liaison existe déjà entre les deux mêmes ports. Retirez le doublon.',
  'flow.checklist.code.dangling_edge':
    'Une liaison pointe vers un nœud qui n’existe plus. Supprimez la liaison, ou remettez le nœud manquant.',
  'flow.checklist.code.cycle_detected':
    'Les étapes reviennent en arrière sur elles-mêmes. Retirez la liaison qui remonte, ou utilisez un nœud Boucle pour une répétition contrôlée.',
  'flow.checklist.code.unreachable_node':
    'Le nœud « {name} » n’est jamais atteint : rien en amont n’y mène. Reliez-le, ou supprimez-le.',
  'flow.checklist.code.node_orphan':
    'Le nœud « {name} » n’a aucune liaison. Reliez-le au reste du Flow, ou supprimez-le.',
  'flow.checklist.code.port_type_mismatch':
    'Ces deux ports ne transportent pas le même type de valeur. Reliez des ports de même type, ou insérez une étape qui le convertit.',
  'flow.checklist.code.flow_output_sink_required':
    'Ce Flow n’a nulle part où livrer son résultat. Ajoutez un nœud Sortie.',
  'flow.checklist.code.flow_output_sink_ambiguous':
    'Ce Flow a plusieurs nœuds Sortie. Gardez-en exactement un, pour que le résultat ait une seule destination.',
  'flow.checklist.code.ingress_kind_invalid':
    'Ce point d’entrée déclare une manière de démarrer que le Flow ne prend pas en charge. Choisissez Manuelle, Conversation, HTTP, Planification ou Événement interne.',
  'flow.checklist.code.ingress_node_kind_invalid':
    'Seul un nœud Déclencheur peut porter un point d’entrée. Déplacez-le sur le nœud qui démarre le Flow.',
  'flow.checklist.code.ingress_source_not_root':
    'Un point d’entrée ne peut rien avoir en amont. Retirez les liaisons qui y arrivent.',
  'flow.checklist.code.task_no_skill':
    'L’étape « {name} » n’a pas encore de Skill. Ouvrez-la et choisissez celle qui fait le travail.',
  'flow.checklist.code.task_runtime_ref_invalid':
    'Cette étape désigne une Skill que la plateforme ne sait pas résoudre. Choisissez-en une dans la palette.',
  'flow.checklist.code.decision_no_branches':
    'La Décision « {name} » a moins de deux branches. Ajoutez des branches pour qu’il y ait un vrai choix.',
  'flow.checklist.code.decision_branch_invalid':
    'Une branche de cette Décision n’a pas de nom utilisable. Donnez à chaque branche un nom court, sans espace au début ni à la fin.',
  'flow.checklist.code.decision_condition_invalid':
    'Une condition de branche ne peut pas être lue. Ouvrez la Décision et corrigez la condition refusée.',
  'flow.checklist.code.decision_condition_unbound':
    'Une condition de branche lit un nom que rien ne fournit. Associez-le dans les Valeurs nommées, ou corrigez son orthographe.',
  'flow.checklist.code.decision_branch_duplicate':
    'Deux branches de cette Décision portent le même nom. Renommez-en une pour que les liaisons restent distinctes.',
  'flow.checklist.code.decision_default_invalid':
    'La branche par défaut désigne une branche inexistante. Choisissez l’une des branches listées sur la Décision.',
  'flow.checklist.code.decision_branch_unwired':
    'Une branche de cette Décision ne mène nulle part. Tracez sa liaison vers l’étape suivante.',
  'flow.checklist.code.loop_no_budget':
    'La Boucle « {name} » n’a pas de nombre maximum d’itérations. Fixez-en un pour qu’une exécution ne tourne pas indéfiniment.',
  'flow.checklist.code.agent_loop_no_budget':
    'La Boucle agent « {name} » n’a pas de nombre maximum de tours. Fixez-en un pour que le choix de la prochaine skill s’arrête.',
  'flow.checklist.code.agent_loop_allowlist':
    'La Boucle agent « {name} » doit lister entre 1 et 8 skills autorisées. C’est l’enveloppe : le modèle ne voit que cette liste.',
  'flow.checklist.code.retry_no_target':
    'Le Réessai « {name} » n’a pas de nombre maximum de tentatives. Fixez-en un pour qu’un échec finisse par s’arrêter.',
  'flow.checklist.code.hitl_no_prompt':
    'L’étape d’approbation « {name} » ne demande rien. Rédigez la question que lira la personne qui approuve.',
  'flow.checklist.code.asset_no_collection':
    'Ce nœud Données ne désigne aucune collection de connaissances. Ouvrez-le et choisissez la collection à lire.',
  'flow.checklist.code.asset_binding_mismatch':
    'Ce nœud Données et l’étape qui le lit ne désignent pas la même collection. Alignez-les sur une seule collection.',
  'flow.checklist.code.retrieval_scope_node_invalid':
    'Seule une étape de recherche peut porter un périmètre de recherche. Déplacez le périmètre sur l’étape de recherche, ou retirez-le.',
  'flow.checklist.code.retrieval_collections_invalid':
    'Les collections de cette étape de recherche ne peuvent pas être lues. Resélectionnez-les dans l’inspecteur.',
  'flow.checklist.code.retrieval_documents_invalid':
    'Les documents de cette étape de recherche ne peuvent pas être lus. Resélectionnez-les, ou laissez la sélection vide pour lire tous les documents.',
  'flow.checklist.code.branch_edge_invalid':
    'Cette liaison revendique une branche que son origine ne déclare pas. Retracez-la depuis la branche de Décision à laquelle elle appartient.',
  'flow.checklist.code.branch_label_invalid':
    'Les voies parallèles de « {name} » ne correspondent pas aux branches déclarées. Donnez à chaque voie un nom distinct, existant sur le nœud.',
  'flow.checklist.code.fork_fanout_invalid':
    'La Division « {name} » a moins de deux voies sortantes. Une division a besoin d’au moins deux chemins pour avoir un sens.',
  'flow.checklist.code.data_source_invalid':
    'La liaison de données de « {name} » est incomplète ou invalide. Vérifiez le connecteur, les tables du périmètre et les étapes reliées.',
  'flow.checklist.code.fork_unjoined':
    'La Division « {name} » ne se recompose jamais. Ajoutez un nœud Fusion que toutes les voies atteignent.',
  'flow.checklist.code.join_fanin_invalid':
    'La Fusion « {name} » a moins de deux voies entrantes. Reliez les voies qu’elle doit recomposer.',
  'flow.checklist.code.join_strategy_invalid':
    'La Fusion « {name} » utilise une manière de fusionner que le moteur ne prend pas en charge. Choisissez l’une des stratégies proposées.',
  'flow.checklist.code.join_without_matching_fork':
    'La Fusion « {name} » n’a aucune division en amont à recomposer. Retirez-la, ou ajoutez la division correspondante.',
  'flow.checklist.code.variable_unresolved':
    'Une entrée lit une valeur que rien en amont ne fournit. Associez-la à une sortie amont dans l’inspecteur.',
  'flow.checklist.code.variable_contract_invalid':
    'Une entrée ou une sortie de cette étape ne respecte pas le contrat du Flow. Ouvrez l’étape et corrigez le champ nommé.',

  // ---- runtime manifest strip -------------------------------------------
  'flow.manifest.aria': 'Résumé du contrat d’exécution',
  'flow.manifest.title': 'Contrat d’exécution',
  'flow.manifest.loading': 'Chargement…',
  'flow.manifest.chip.units': 'Étapes',
  'flow.manifest.chip.source': 'Origine',
  'flow.manifest.chip.config': 'Réglages',
  'flow.manifest.chip.retrieval': 'Recherche',
  'flow.manifest.units.value': '{live}/{total} actives',
  'flow.manifest.units.title':
    '{total} étape(s) · {live} active(s) · {skills} portée(s) par une skill',
  'flow.manifest.config.none': 'Aucun réglage effectif résolu',
  'flow.manifest.config.keys': '{count} réglage(s)',
  'flow.manifest.more': '… (+{count} de plus)',
  'flow.manifest.retrieval.none': 'aucune encore',
  'flow.manifest.retrieval.none_recorded':
    'Aucune recherche documentaire enregistrée pour ce système',
  'flow.manifest.retrieval.latest': 'Dernière recherche documentaire',

  // ---- inspector ---------------------------------------------------------
  'flow.inspector.aria': 'Inspecteur de nœud',
  'flow.inspector.empty.title': 'Aucun nœud sélectionné',
  'flow.inspector.empty.body':
    'Sélectionnez un nœud sur le canevas pour l’inspecter. Ou chargez le départ Déclencheur → Boucle agent → Porte humaine → Sortie.',
  'flow.inspector.close': 'Fermer (Échap)',
  'flow.inspector.close.aria': 'Fermer l’inspecteur',
  'flow.inspector.unsaved': 'Non enregistré',
  'flow.inspector.unsaved.hint':
    'Modifications non enregistrées — utilisez Enregistrer dans la barre d’outils',
  'flow.inspector.section.identity': 'Identité',
  'flow.inspector.section.identity.hint': 'Références techniques de ce nœud',
  'flow.inspector.identity.id': 'Identifiant',
  'flow.inspector.identity.type': 'Type',
  'flow.inspector.identity.kind': 'Nature',
  'flow.inspector.field.label': 'Nom',
  'flow.inspector.field.label.placeholder': 'Nom du nœud',
  'flow.inspector.field.description': 'Description',
  'flow.inspector.field.description.placeholder': 'Ce que fait ce nœud',
  'flow.inspector.section.ports': 'Entrées et sorties',
  'flow.inspector.section.decision': 'Branches de décision',
  'flow.inspector.error_policy.title': 'En cas d’erreur',
  'flow.inspector.error_policy.label': 'Comportement',
  'flow.inspector.error_policy.continue': 'Continuer — l’erreur passe en aval',
  'flow.inspector.error_policy.fail': 'Arrêter l’exécution',
  'flow.inspector.error_policy.route': 'Router vers la porte d’erreur',
  'flow.inspector.error_policy.route_hint':
    'Reliez le port « error » à la porte d’erreur. Les autres sorties sont coupées.',
  'flow.inspector.join.title': 'Quorum de sources',
  'flow.inspector.join.min_success': 'Nombre minimum de branches réussies',
  'flow.inspector.join.hint':
    'Vide : comportement historique. Un nombre : le Join échoue sous ce quorum.',
  'flow.inspector.section.agent_loop': 'Enveloppe de la boucle agent',
  'flow.inspector.agent_loop.hint':
    'Le mou = quelle skill appeler ensuite. Les writes restent derrière une approbation. Le modèle ne voit que la liste autorisée.',
  'flow.inspector.agent_loop.objective': 'Objectif',
  'flow.inspector.agent_loop.objective.placeholder':
    'Le résultat à atteindre, pas les étapes — ex. réinitialiser le mot de passe AD sous la politique ITSD',
  'flow.inspector.agent_loop.done_when': 'Terminé quand (un critère par ligne)',
  'flow.inspector.agent_loop.done_when.placeholder': 'identity_verified\naudit_log_v1',
  'flow.inspector.agent_loop.allowlist': 'Skills que la boucle peut appeler (1 à 8)',
  'flow.inspector.agent_loop.allowlist.placeholder': 'azure_llm_v1\naudit_log_v1',
  'flow.inspector.agent_loop.allowlist.count': '{count} / 8 skills dans l’enveloppe',
  'flow.inspector.agent_loop.turns': 'Tours max.',
  'flow.inspector.agent_loop.confidence': 'Seuil de confiance',
  'flow.inspector.agent_loop.privilege': 'Niveau de privilège',
  'flow.inspector.agent_loop.privilege.recommend': 'Recommander seulement — aucun write',
  'flow.inspector.agent_loop.privilege.act': 'Agir (lab seulement)',
  'flow.inspector.agent_loop.privilege.act_with_approval': 'Agir après approbation',
  'flow.inspector.agent_loop.on_budget': 'Budget épuisé',
  'flow.inspector.agent_loop.on_budget.exit': 'Sortir — aucun write de plus',
  'flow.inspector.agent_loop.on_budget.ask_human': 'Demander une personne',
  'flow.inspector.agent_loop.cost': 'Budget $ (optionnel)',
  'flow.inspector.agent_loop.deadline': 'Délai en minutes (optionnel)',
  'flow.inspector.agent_loop.envelope':
    '{objective} · {turns} tours · {skills}/8 skills · {privilege}',
  'flow.inspector.agent_loop.apply_itsd': 'Remplir depuis l’overlay mot de passe',
  'flow.inspector.agent_loop.load_starter':
    'Charger Déclencheur → Boucle agent → Porte humaine → Sortie',
  'flow.inspector.section.human_gate': 'Pause structurée',
  'flow.inspector.human_gate.hint':
    'La boucle s’arrête ici, puis reprend dans la même exécution. Jamais un redémarrage.',
  'flow.inspector.human_gate.prompt': 'Question posée à la personne',
  'flow.inspector.human_gate.prompt.placeholder': 'Approuver cette écriture ?',
  'flow.inspector.human_gate.kind': 'Type de décision',
  'flow.inspector.human_gate.kind.choice': 'Choix A / B',
  'flow.inspector.human_gate.kind.validate_draft': 'Valider un brouillon',
  'flow.inspector.human_gate.kind.missing_file': 'Fournir un fichier manquant',
  'flow.inspector.human_gate.kind.approve_write': 'Approuver une écriture',
  'flow.inspector.decision.add': '+ Branche',
  'flow.inspector.decision.hint':
    'Les conditions sont évaluées de haut en bas. La première qui correspond gagne ; la branche par défaut ne sert que si aucune ne correspond.',
  'flow.inspector.decision.routes': '{count} liaison(s)',
  'flow.inspector.decision.up': 'Monter',
  'flow.inspector.decision.up.aria': 'Monter la branche',
  'flow.inspector.decision.down': 'Descendre',
  'flow.inspector.decision.down.aria': 'Descendre la branche',
  'flow.inspector.decision.remove': 'Supprimer la branche et ses liaisons',
  'flow.inspector.decision.route_label': 'Nom de la branche',
  'flow.inspector.decision.condition': 'Condition',
  'flow.inspector.decision.default': 'Branche par défaut',
  'flow.inspector.decision.default.none': 'Aucune — échouer si rien ne correspond',
  'flow.inspector.decision.invalid_label': '(nom invalide)',
  'flow.inspector.section.asset': 'Collection de connaissances',
  'flow.inspector.asset.collection': 'Collection',
  'flow.inspector.asset.collection.none': '— Sélectionner une collection —',
  'flow.inspector.asset.slug': 'Identifiant de collection',
  'flow.inspector.asset.slug.placeholder': 'ma-collection',
  'flow.inspector.asset.loading': 'Chargement des collections…',
  'flow.inspector.asset.error': 'Collections indisponibles — saisie manuelle.',
  'flow.inspector.asset.retry': 'Réessayer',
  'flow.inspector.asset.empty': 'Aucune collection indexée — saisie manuelle.',
  'flow.inspector.asset.workspace_scoped': 'Limitée à cet espace de travail',
  'flow.inspector.asset.open': 'Ouvrir la collection',
  'flow.inspector.asset.open_knowledge': 'Ouvrir les connaissances',
  'flow.inspector.section.retrieval': 'Périmètre de recherche',
  'flow.inspector.retrieval.hint':
    'Ce périmètre appartient à ce nœud de recherche. Il ne change ni le réglage par défaut de l’espace de travail, ni un autre nœud de recherche.',
  'flow.inspector.retrieval.collections': 'Collections',
  'flow.inspector.retrieval.collections.aria': 'Collections utilisées par ce nœud de recherche',
  'flow.inspector.retrieval.slugs': 'Identifiants de collections',
  'flow.inspector.retrieval.documents': 'Documents',
  'flow.inspector.retrieval.documents.aria': 'Documents utilisés par ce nœud de recherche',
  'flow.inspector.retrieval.documents.loading':
    'Chargement des documents des collections sélectionnées…',
  'flow.inspector.retrieval.documents.error': 'Certains catalogues de documents sont indisponibles.',
  'flow.inspector.retrieval.documents.retry': 'Réessayer',
  'flow.inspector.retrieval.documents.stored': 'référence enregistrée',
  'flow.inspector.retrieval.documents.all':
    'Aucun document sélectionné signifie tous les documents des collections choisies.',
  'flow.inspector.retrieval.documents.more':
    'D’autres documents existent au-delà des pages chargées.',
  'flow.inspector.retrieval.documents.load_more': 'Charger la page suivante',
  'flow.inspector.retrieval.documents.empty': 'Aucun document sélectionnable dans ce périmètre.',
  'flow.inspector.retrieval.no_scope':
    'Aucun périmètre explicite : les réglages par défaut de l’espace de travail s’appliquent.',
  'flow.inspector.retrieval.error.documents':
    'Sélectionnez au maximum 1000 documents pour un nœud de recherche.',
  'flow.inspector.retrieval.error.collections':
    'Sélectionnez au maximum 32 collections pour un nœud de recherche.',
  'flow.inspector.section.entry': 'Point d’entrée',
  'flow.inspector.section.output_contract': 'Contrat de sortie',
  'flow.inspector.output_contract.label': 'Schéma de sortie publié',
  'flow.inspector.output_contract.hint.output':
    'Vérifié avant que le résultat de l’exécution ne devienne visible.',
  'flow.inspector.output_contract.hint.task':
    'Vérifié à chaque sortie de nœud : une réponse mal formée échoue ici plutôt que dans la Décision qui la lit.',
  'flow.inspector.output_contract.fallback.output':
    'Aucun schéma déclaré — la publication en dérive un depuis les entrées de ce nœud et accepte tout champ supplémentaire.',
  'flow.inspector.output_contract.fallback.task':
    'Aucun schéma déclaré : à la publication, cette étape reprend le contrat de sortie de la Skill liée et le conserve tel quel pour cette version.',
  'flow.inspector.section.trigger': 'Déclencheur',
  'flow.inspector.trigger.sftp': 'Ouvrir le dépôt SFTP',
  'flow.inspector.section.mcp': 'Serveur MCP',
  'flow.inspector.mcp.open': 'Ouvrir le connecteur MCP',
  'flow.inspector.mcp.server': 'Serveur {id}',
  'flow.inspector.mcp.credential': 'Identifiants : {source}',
  'flow.inspector.mcp.disabled': 'Connecteur MCP désactivé sur ce workspace',
  'flow.inspector.trigger.unavailable':
    'Le pilotage des déclencheurs est disponible une fois le Flow enregistré dans un Système.',
  'flow.inspector.section.danger': 'Supprimer ce nœud',
  'flow.inspector.danger.delete': 'Supprimer le nœud',
  'flow.inspector.danger.delete.aria': 'Supprimer le nœud',
  'flow.inspector.danger.delete.hint':
    'Supprimer ce nœud et ses liaisons (Suppr/Retour arrière)',
  'flow.inspector.danger.body':
    'Supprime « {name} » et toutes les liaisons qui y sont rattachées. La touche Suppr ou Retour arrière fait la même chose sur le nœud sélectionné, et Ctrl/Cmd+Z le ramène.',

  // ---- entry point editor ------------------------------------------------
  'flow.entry.kind': 'Manière de démarrer',
  'flow.entry.kind.derived': 'Déduite à la publication',
  'flow.entry.kind.derived.value': 'Déduite à la publication — {name}',
  'flow.entry.kind.manual': 'Manuelle — bouton Exécuter, ou appel API',
  'flow.entry.kind.chat': 'Conversation — la surface de discussion du Système',
  'flow.entry.kind.http': 'HTTP — webhook entrant',
  'flow.entry.kind.schedule': 'Planification — cron',
  'flow.entry.kind.event': 'Événement interne — dépôt SFTP, dépôt promu',
  'flow.entry.note.manual':
    'Les exécutions démarrent depuis Exécuter ou depuis une demande d’exécution. Le contenu envoyé est l’entrée de l’exécution.',
  'flow.entry.note.chat': 'Les exécutions démarrent depuis un tour de conversation sur ce Système.',
  'flow.entry.note.http':
    'Les exécutions démarrent sur un appel entrant. Enregistrez le webhook ci-dessous pour qu’il puisse se déclencher.',
  'flow.entry.note.schedule':
    'Les exécutions démarrent sur un tic de planification. Enregistrez la planification ci-dessous pour qu’elle puisse se déclencher.',
  'flow.entry.note.event':
    'Les exécutions démarrent sur un événement interne émis par la plateforme.',
  'flow.entry.event.unsaved':
    'La distribution des événements ne peut pas être vérifiée tant que ce Flow n’est pas enregistré dans un Système.',
  'flow.entry.event.checking': 'Vérification de la distribution des événements…',
  'flow.entry.event.unreadable':
    'La distribution des événements n’a pas pu être lue pour ce Système.',
  'flow.entry.event.off':
    'Les déclencheurs par événement sont désactivés pour cet espace de travail. La publication reste autorisée, mais aucun événement ne démarrera d’exécution tant qu’un administrateur ne les aura pas activés.',
  'flow.entry.event.dry_run':
    'Les déclencheurs par événement sont activés mais en simulation : un événement correspondant est enregistré sans démarrer d’exécution. Passez en réel ci-dessous.',
  'flow.entry.event.live': 'Les déclencheurs par événement sont actifs pour ce Système.',
  'flow.entry.registration.http':
    'Déclarer une manière de démarrer n’est pas un enregistrement. Créez le webhook dans le panneau Déclencheurs ci-dessous, ou dans',
  'flow.entry.registration.schedule':
    'Déclarer une manière de démarrer n’est pas un enregistrement. Créez la planification dans le panneau Déclencheurs ci-dessous, ou dans',
  'flow.entry.registration.link': 'Déclencheurs',
  'flow.entry.schema.label': 'Schéma du contenu d’entrée',
  'flow.entry.schema.hint.manual':
    'Vérifié pour chaque entrée d’exécution avant que l’exécution ne soit acceptée — c’est ce que la fenêtre d’entrée doit satisfaire.',
  'flow.entry.schema.hint.other':
    'Vérifié pour chaque contenu entrant avant que l’exécution ne soit acceptée.',
  'flow.entry.schema.fallback':
    'Aucun schéma déclaré — la publication en dérive un depuis les sorties de ce nœud et accepte tout champ supplémentaire.',

  // ---- decision named inputs --------------------------------------------
  'flow.bindings.title': 'Valeurs nommées',
  'flow.bindings.add': '+ Valeur nommée',
  'flow.bindings.hint':
    'Chaque nom ci-dessous est lisible par les conditions ci-dessus, exactement tel qu’il est écrit.',
  'flow.bindings.no_candidates':
    'Rien en amont ne produit encore de valeur. Reliez un nœud à cette Décision avant de nommer ce qu’elle lit.',
  'flow.bindings.name.aria': 'Nom de la valeur',
  'flow.bindings.source.aria': 'Sortie amont associée',
  'flow.bindings.source.none': '— choisir une sortie amont —',
  'flow.bindings.source.legacy': 'ancien chemin : {path}',
  'flow.bindings.source.missing': '{name} (introuvable)',
  'flow.bindings.remove': 'Retirer cette valeur nommée',
  'flow.bindings.reads': 'Vos conditions lisent :',
  'flow.bindings.not_bound': 'sans source',
  'flow.bindings.warning':
    'Un nom sans source est lu comme vide : un test d’égalité ne correspond alors jamais, une comparaison fait échouer l’exécution. Associez-le ci-dessus, ou corrigez l’orthographe dans la condition.',

  // ---- manifest fields ---------------------------------------------------
  'flow.params.title': 'Paramètres d’exécution',
  'flow.params.variables': 'Valeurs d’entrée',
  'flow.params.configured': 'Configuré',
  'flow.params.not_configured': 'Pas encore configuré',
  'flow.params.configured.hint': 'Configuré — ce nœud pilote une surface réelle',
  'flow.params.not_configured.hint': 'Pas complètement configuré',
  'flow.params.skill': 'Skill',
  'flow.params.runtime': 'Référence technique',
  'flow.params.required': 'obligatoire',
  'flow.params.empty':
    'Ce nœud n’a aucun paramètre d’exécution modifiable dans le contrat.',
  'flow.params.no_unit':
    'Aucune unité du contrat d’exécution ne correspond à ce nœud — il n’est pas encore relié à un contrat vivant.',
  'flow.params.error.json': 'JSON invalide — la valeur n’a pas été enregistrée.',
  'flow.params.variable.none': '— aucune source —',
  'flow.params.variable.legacy': 'ancien : {path}',
  'flow.params.variable.incompatible': '{label} · {schema} — ce n’est pas un {expected}',
  'flow.params.variable.no_upstream':
    'Rien en amont ne produit encore de valeur — reliez d’abord un nœud à celui-ci.',
  'flow.params.variable.no_match':
    'Aucune sortie amont n’est un {expected}. Associez une sortie compatible, ou lisez la valeur sur une Décision comme valeur nommée.',
  'flow.params.variable.describe':
    'Associer l’entrée « {name} » ({schema}) à une sortie amont.',
  'flow.params.variable.supplied':
    'Fournie à l’exécution par la source associée à « {name} ».',

  // ---- run controls ------------------------------------------------------
  'flow.run.aria': 'Commandes d’exécution',
  'flow.run.simulate': 'Simuler',
  'flow.run.simulate.hint': 'Essai à blanc côté navigateur — aucun appel au serveur',
  'flow.run.execute': 'Exécuter',
  'flow.run.execute.draft': 'Tester le brouillon',
  'flow.run.execute.automation': 'Exécuter',
  'flow.run.execute.automation.hint':
    'Exécuter le brouillon maintenant — aucun modèle ni publication requis',
  'flow.run.execute.aria': 'Exécuter sur le serveur',
  'flow.run.execute.running': 'Exécution…',
  'flow.run.execute.unavailable': 'Exécution indisponible.',
  'flow.run.execute.hint':
    '{surface} — appels réels aux skills sur l’autorité de Flow explicitement choisie',
  'flow.run.execute.hint.debug':
    'Exécuter avec le débogueur attaché — le moteur s’arrête aux étapes / points d’arrêt',
  'flow.run.debug': 'Débogage : {mode}',
  'flow.run.debug.aria': 'Changer le mode de débogage',
  'flow.run.debug.unavailable': 'Débogage indisponible.',
  'flow.run.debug.unavailable.sequential':
    'Débogage indisponible : l’exécution pas à pas n’a pas de débogueur de graphe.',
  'flow.run.debug.hint': 'Mode de débogage : {mode} — cliquer pour changer',
  'flow.run.debug.breakpoints.toast':
    'Activez les points d’arrêt avec la pastille de chaque nœud (visible quand le débogage est actif).',
  'flow.run.debug.breakpoints.title': 'Débogueur',
  'flow.run.replay': 'Rejouer',
  'flow.run.replay.hint': 'Rejouer les points de contrôle de cette exécution dans le terminal',
  'flow.run.replay.aria': 'Rejouer l’exécution',
  'flow.run.versions': 'Versions',
  'flow.run.versions.hint': 'Ouvrir l’historique des versions',
  'flow.run.versions.blocked':
    'Transformez ce brouillon en Système, ou attendez la fin du chargement, pour suivre les versions',
  'flow.run.versions.toast':
    'L’historique des versions est suivi par Système — transformez d’abord ce brouillon libre.',
  'flow.run.terminal': 'Afficher ou masquer le terminal',
  'flow.run.terminal.aria': 'Basculer le terminal',
  'flow.run.input.title': 'Entrée de l’exécution',
  'flow.run.input.close': 'Fermer la fenêtre d’entrée',
  'flow.run.input.hint':
    'Saisissez l’objet JSON exposé au Flow. Les données de débogage sont injectées séparément par l’éditeur.',
  'flow.run.input.hint.automation':
    'Le texte est déjà préparé. Lancez, ou remplacez-le. La publication vient après.',
  'flow.automation.turn.title': 'Modifier cette automatisation',
  'flow.automation.turn.hint':
    'Décrivez le changement. La publication et l’approbation restent hors de ce tour.',
  'flow.automation.turn.send': 'Envoyer',
  'flow.automation.turn.sending': 'Lecture du brouillon…',
  'flow.automation.turn.read': 'Lu : {blocks}',
  'flow.automation.turn.verified': 'Le brouillon enregistré correspond au patch.',
  'flow.automation.turn.run': 'Exécution {status}',
  'flow.automation.turn.retrieve': 'Passage : {passage} — source {source}',
  'flow.automation.turn.retrieve.empty': 'Aucun passage cité.',
  'flow.automation.turn.sealed': 'L’écriture SAP est restée scellée.',
  'flow.automation.turn.called': 'L’écriture SAP a été appelée.',
  'flow.automation.turn.pause': 'En attente d’approbation.',
  'flow.automation.turn.error': 'Le tour s’est arrêté : {message}',
  'flow.automation.turn.stopped': 'Le tour s’est arrêté.',
  'flow.automation.work.title': 'Dans Work',
  'flow.automation.work.unpublished': 'Cette automatisation apparaît dans Work quand elle est publiée.',
  'flow.automation.work.objective': 'Objectif : {text}',
  'flow.automation.work.objective.absent': 'Aucun objectif n’est énoncé.',
  'flow.automation.work.convention': 'Convention déclarée : {rate}',
  'flow.automation.work.convention.absent': 'Aucune convention de valeur n’est déclarée.',
  'flow.automation.work.contract': 'Contrat de valeur r{revision}, approuvé par {owner} : {rate}.',
  'flow.automation.work.target': 'Cible : {target} {unit} ({indicator}), {start} → {end}. Source : {source}.',
  'flow.automation.work.gap.absent': 'Aucun écart mesuré.',
  'flow.automation.work.gap.measured': 'Écart mesuré : {delta} {unit} ({value} pour une cible de {target}).',
  'flow.automation.work.gap.in_progress': 'Période en cours : {value} sur {target} {unit} à ce jour, jusqu’au {end}.',
  'flow.automation.work.gap.not_started': 'La période du contrat commence le {start}.',
  'flow.automation.work.gap.not_comparable': 'Aucun écart mesuré : les preuves de la période sont incomplètes.',
  'flow.automation.work.proof': 'Preuve : exécution {run}',
  'flow.automation.work.proof.absent': 'Aucune exécution publiée ne sert encore de preuve.',
  'flow.preparation.title': 'Préparation',
  'flow.preparation.ready': 'Prêt',
  'flow.preparation.not_ready': 'Pas prêt',
  'flow.preparation.not_checked': 'Contrôle non effectué',
  'flow.preparation.not_applicable': 'Sans objet',
  'flow.preparation.blocked': 'Bloqué',
  'flow.preparation.model': 'Modèle',
  'flow.preparation.provider': 'Fournisseur',
  'flow.preparation.source': 'Source',
  'flow.preparation.indexing': 'Indexation',
  'flow.preparation.rights': 'Droits',
  'flow.preparation.worker': 'Exécutant',
  'flow.review.title': 'Réserve',
  'flow.review.intro': 'Un résultat ne convient pas ? Émettez une réserve sur la dernière exécution, corrigez le Flow, puis vérifiez que l’exécution suivante applique la correction.',
  'flow.review.start': 'Émettre une réserve',
  'flow.review.continue': 'Reprendre',
  'flow.review.close': 'Replier',
  'flow.review.note_placeholder': 'Ce qui ne va pas dans ce résultat, et ce qu’il aurait dû être.',
  'flow.review.save_hint': 'La réserve porte sur la dernière exécution de cette automatisation.',
  'flow.review.reread_hint': 'Corrigez le Flow, enregistrez-le, puis relisez le brouillon.',
  'flow.review.later_label': 'Exécution suivante',
  'flow.review.step': 'Étape {step} sur 4 · {label}',
  'flow.review.done': 'Boucle fermée',
  'flow.review.steps.1': 'Réserve',
  'flow.review.steps.2': 'Relecture',
  'flow.review.steps.3': 'Correction',
  'flow.review.steps.4': 'Vérification',
  'flow.review.empty': 'Aucun résultat sur cette automatisation.',
  'flow.review.note': 'Ce qui ne va pas',
  'flow.review.save': 'Enregistrer la réserve',
  'flow.review.reread': 'Relire le brouillon',
  'flow.review.read': 'Relu : {blocks}',
  'flow.review.confirm': 'Confirmer la correction relue',
  'flow.review.compare': 'Comparer',
  'flow.review.same': 'Même automatisation : la réserve et l’exécution suivante portent sur le même objet.',
  'flow.review.later': 'Exécution suivante : {status}.',
  'flow.review.need_later': 'Un résultat suivant de la même automatisation manque encore.',
  'flow.review.ran_correction': 'Le résultat suivant a exécuté le brouillon corrigé.',
  'flow.review.other_draft': 'Le résultat suivant a exécuté un autre graphe que le brouillon corrigé.',
  'flow.review.error': 'La boucle s’est arrêtée.',
  'flow.review.refused.unchanged_draft': 'Le brouillon est encore celui qu’a exécuté le résultat réservé. Corrigez-le, puis relisez-le.',
  'flow.review.refused.stale_reread': 'Le brouillon a changé depuis la relecture. Relisez-le avant de confirmer.',
  'flow.review.refused.not_later': 'Ce résultat a démarré avant le résultat réservé. Choisissez un résultat suivant.',
  'flow.dossiers.title': 'Dossiers',
  'flow.dossiers.empty': 'Aucun dossier versionné.',
  'flow.dossiers.version': 'Version {version}',
  'flow.dossiers.proof': 'Preuve présente',
  'flow.dossiers.proof.absent': 'Preuve absente',
  'flow.dossiers.waiting': 'En attente d’une personne',
  'flow.chart.title': 'Graphique figé',
  'flow.chart.empty': 'Aucun point.',
  'flow.chart.no_run': 'Ce point n’a pas de résultat.',
  'flow.chart.run': 'Résultat : {status}',
  'flow.proof.present': 'Même preuve : présente.',
  'flow.proof.absent': 'Même preuve : absente.',
  'flow.proof.sealed': 'Écriture scellée, non appelée.',
  'flow.run.input.prefill': 'Pré-rempli depuis le contrat du point d’entrée',
  'flow.run.input.entry': 'Point d’entrée du brouillon',
  'flow.run.input.entry.choose': 'Choisir un point d’entrée…',
  'flow.run.input.entry.authority': 'Autorité de la demande :',
  'flow.run.input.json': 'Objet JSON',
  'flow.run.input.json.automation': 'Entrée',
  'flow.run.input.cancel': 'Annuler',
  'flow.run.input.dispatching': 'Envoi…',
  'flow.run.input.submit': 'Lancer l’exécution',
  'flow.run.input.submit.draft': 'Lancer l’essai du brouillon',
  'flow.run.input.submit.automation': 'Exécuter',
  'flow.run.input.submit.debug': 'Lancer l’exécution de débogage',
  'flow.run.execute.debug': 'Exécution de débogage',

  // ---- terminal ----------------------------------------------------------
  'flow.terminal.aria': 'Terminal d’exécution',
  'flow.terminal.title': 'Terminal d’exécution',
  'flow.terminal.lines': '{count} lignes',
  'flow.terminal.clear': 'Vider le journal',
  'flow.terminal.collapse': 'Replier le terminal',
  'flow.terminal.status.idle': 'Au repos',
  'flow.terminal.status.running': 'En cours',
  'flow.terminal.status.paused': 'En pause',
  'flow.terminal.status.done': 'Terminé',
  'flow.terminal.status.error': 'Erreur',
  'flow.terminal.empty':
    'Simulez pour un essai à blanc côté navigateur, ou Exécutez pour lancer sur le serveur et voir la sortie en direct ici.',
  'flow.terminal.approval.title': 'Approbation humaine requise',
  'flow.terminal.approval.paused': 'EN PAUSE',
  'flow.terminal.approval.prompt': 'Une personne doit approuver cette étape pour continuer.',
  'flow.terminal.approval.node': 'Nœud',
  'flow.terminal.approval.ttl': 'Délai restant',
  'flow.terminal.approval.buffered': 'En attente',
  'flow.terminal.approval.memory': 'Mémoire',
  'flow.terminal.approval.reject': 'Refuser',
  'flow.terminal.approval.accept': 'Approuver',
  'flow.terminal.debug.title': 'Débogueur en pause',
  'flow.terminal.debug.prompt': 'En pause après',
  'flow.terminal.debug.prompt.tail': '— inspectez le contexte et avancez.',
  'flow.terminal.debug.last_output': 'Dernière sortie',
  'flow.terminal.debug.context': 'Instantané du contexte',
  'flow.terminal.debug.stop': 'Arrêter',
  'flow.terminal.debug.continue': 'Continuer',
  'flow.terminal.debug.step': 'Pas à pas',
  'flow.terminal.no_data': '— aucune donnée —',

  // ---- workbench ---------------------------------------------------------
  'flow.workbench.aria': 'Atelier d’essai local',
  'flow.workbench.title': 'Essayer ce Flow avant de l’enregistrer',
  'flow.workbench.status.dirty':
    'Exécute votre canevas non enregistré tel quel. Rien n’est enregistré ni publié — mais les Skills sont réelles, et leurs effets aussi.',
  'flow.workbench.status.clean':
    'Exécute le canevas courant tel quel. Rien n’est enregistré ni publié — mais les Skills sont réelles, et leurs effets aussi.',
  'flow.workbench.detail.toggle': 'Ce que cette exécution touche',
  'flow.workbench.detail.graph': 'Graphe',
  'flow.workbench.detail.graph.dirty':
    'Le canevas non enregistré, envoyé avec son empreinte : le serveur refuse tout ce qui aurait changé depuis.',
  'flow.workbench.detail.graph.clean':
    'Le canevas courant, envoyé avec son empreinte : le serveur refuse tout ce qui aurait changé depuis.',
  'flow.workbench.detail.saving': 'Sauvegarde',
  'flow.workbench.detail.saving.body':
    'La sauvegarde automatique reste suspendue tant que ce panneau est ouvert.',
  'flow.workbench.detail.publishing': 'Publication',
  'flow.workbench.detail.publishing.body':
    'Jamais publié. La version publiée et le point d’entrée qui la sert ne bougent pas.',
  'flow.workbench.detail.effects': 'Effets réels',
  'flow.workbench.detail.effects.body':
    'Les Skills s’exécutent réellement. Ce qu’elles écrivent, envoient ou appellent hors de {brand} se produit pour de vrai.',
  'flow.workbench.detail.runtime': 'Exécution',
  'flow.workbench.consent':
    'Je comprends que cet essai appelle de vraies Skills et peut provoquer des effets externes. La confirmation ne vaut que pour la révision courante du Flow.',
  'flow.workbench.tab.chat': 'Conversation',
  'flow.workbench.tab.node': 'Nœud',
  'flow.workbench.tab.golden': 'Jeu de référence',
  'flow.workbench.tabs.aria': 'Mode de l’atelier',
  'flow.workbench.close': 'Fermer l’atelier local',
  'flow.workbench.entry': 'Point d’entrée',
  'flow.workbench.entry.choose': 'Choisir un point d’entrée…',
  'flow.workbench.chat.empty':
    'Testez le graphe exact du canevas. Le Flow est vérifié et lié à son empreinte, mais il n’est ni enregistré ni publié.',
  'flow.workbench.chat.context': 'Entrée complémentaire (JSON)',
  'flow.workbench.chat.message': 'Message',
  'flow.workbench.chat.send': 'Lancer l’essai',
  'flow.workbench.busy': 'Exécution…',
  'flow.workbench.node.target': 'Nœud Skill sélectionné',
  'flow.workbench.node.none': 'Sélectionnez un nœud portant une Skill exécutable.',
  'flow.workbench.node.input': 'Entrée manuelle (JSON)',
  'flow.workbench.node.run': 'Exécuter le nœud sélectionné',
  'flow.workbench.golden.cases': 'Cas de référence (JSON · 20 max)',
  'flow.workbench.golden.run': 'Exécuter le jeu de référence',
  'flow.workbench.golden.busy': 'Exécution du jeu…',
  'flow.workbench.golden.summary':
    '{completed}/{total} exécutions terminées · contrôles : {passed} réussis, {failed} échoués · {unevaluated} non évalués',
  'flow.workbench.golden.expected': 'Attendu',
  'flow.workbench.golden.expected.none': 'Aucun résultat attendu : la réponse ne sera pas évaluée.',
  'flow.workbench.golden.actual': 'Sortie réelle',
  'flow.workbench.golden.open_run': 'Ouvrir l’exécution',
  'flow.workbench.golden.human': 'En attente de revue humaine',
  'flow.workbench.golden.paused': 'Exécution en pause',
  'flow.workbench.golden.stopped': 'Exécution interrompue · non évaluée',
  'flow.workbench.golden.passed': 'Contrôle réussi',
  'flow.workbench.golden.failed': 'Contrôle échoué',
  'flow.workbench.golden.unevaluated': 'Exécution terminée · non évaluée',
  'flow.workbench.golden.pending': 'Exécution en cours',
  'flow.workbench.error.message': 'Saisissez un message avant de lancer l’essai local.',
  'flow.workbench.error.object': 'Saisissez un objet JSON.',
  'flow.workbench.error.json': 'Saisissez du JSON valide.',
  'flow.workbench.error.array': 'Saisissez un tableau JSON valide.',
  'flow.workbench.error.golden_size': 'Un jeu de référence contient entre 1 et 20 cas.',
  'flow.workbench.error.golden_object': 'Le cas {index} doit être un objet.',
  'flow.workbench.error.golden_id':
    'Les identifiants de cas doivent être uniques, non vides et sans espaces autour.',
  'flow.workbench.error.golden_input': 'Le cas « {id} » a besoin d’un objet d’entrée.',
  'flow.workbench.error.node': 'Sélectionnez un nœud portant une Skill exécutable.',
  'flow.workbench.error.no_entry': 'Le Flow courant n’a aucun point d’entrée exécutable.',
  'flow.workbench.error.choose_entry':
    'Choisissez l’un des {count} points d’entrée du Flow avant de lancer l’atelier.',
  'flow.workbench.error.consent':
    'Confirmez que cet essai appelle de vraies Skills et peut provoquer des effets externes.',
  'flow.workbench.error.unserialisable': '[Résultat non affichable]',
  'flow.workbench.error.entry_missing':
    'Le point d’entrée sélectionné n’existe plus dans le Flow courant.',
  'flow.workbench.error.entry_no_text':
    'Le point d’entrée sélectionné n’a aucun champ texte. Ajoutez un champ query, message, prompt, text ou input à son schéma d’entrée.',
  'flow.workbench.error.entry_rejects':
    'Le point d’entrée sélectionné n’accepte pas : {keys}.',
  'flow.workbench.error.entry_requires':
    'Le point d’entrée sélectionné exige aussi : {keys}. Ajoutez-les au JSON input_ref.',
  'flow.workbench.error.entry_gone': 'Le point d’entrée sélectionné n’existe plus.',
  'flow.workbench.error.golden_ids':
    'Les identifiants de cas de référence doivent être uniques, non vides et sans espaces superflus.',
  'flow.workbench.error.busy': 'Attendez la fin de l’essai en cours.',
  'flow.workbench.error.no_system': 'L’atelier n’est rattaché à aucun Système chargé.',
  'flow.workbench.error.context_changed':
    'Le Flow ou l’espace de travail a changé pendant l’essai. Relancez-le sur l’instantané courant.',
  'flow.workbench.error.diagnostics': 'Le Flow courant a des diagnostics serveur bloquants.',
  'flow.workbench.error.digest':
    'Le serveur n’a pas renvoyé d’empreinte canonique de Flow valide.',
  'flow.workbench.error.runtime_unsupported':
    'Le serveur a renvoyé un mode d’exécution de Flow non pris en charge.',
  'flow.workbench.error.runtime_legacy':
    'L’atelier exige une exécution en graphe. Le mode séquentiel hérité n’exécute pas la topologie du graphe édité.',
  'flow.workbench.error.golden_mismatch':
    'La réponse du lot de référence ne correspond pas au Flow validé ni au jeu de cas.',
  'flow.workbench.error.golden_identity':
    'Une exécution de référence n’a pas son identité de cas gérée par le serveur.',
  'flow.workbench.error.golden_duplicates':
    'Le lot de référence contient des identités de cas dupliquées ou manquantes.',
  'flow.workbench.error.golden_diff':
    'La sortie ne correspond pas à la valeur attendue (comparaison partielle).',
  'flow.workbench.error.run_status': 'Exécution arrêtée avec le statut {status}.',
  'flow.workbench.error.evidence':
    'Les preuves de l’exécution ne correspondent pas à la requête d’atelier validée.',
  'flow.workbench.error.poll_identity':
    'L’identité de l’exécution interrogée a changé de façon inattendue.',
  'flow.workbench.error.timeout':
    '{label} ne s’est pas terminée en {minutes} minutes. Son exécution durable peut encore être en file ou en cours.',
  'flow.workbench.timeout.interactive': 'L’essai d’atelier',
  'flow.workbench.timeout.golden': 'L’essai de référence',
  'flow.workbench.timeout.recipe': 'L’essai de recette',
  'flow.workbench.error.http': 'La requête de l’atelier a échoué (HTTP {status}).',
  'flow.workbench.error.failed': 'La requête de l’atelier a échoué.',

  // ---- éditeur de schéma de contrat (partagé inspector / ateliers) --------
  'flow.schema.declared': 'Déclaré — c’est ce que la publication fige.',
  'flow.schema.derive_from_ports': 'Dériver des ports',
  'flow.schema.clear': 'Effacer',

  // ---- recette Python (nœud, inspector, atelier de rédaction) -------------
  'flow.inspector.section.recipe': 'Recette Python',
  'flow.recipe.inspector.hint':
    'Un script Python (main(inputs) → dict) exécuté dans un Environnement Python géré, hors du processus API, avec suivi de statut et annulation.',
  'flow.recipe.inspector.open': 'Ouvrir l’atelier de recette',
  'flow.recipe.inspector.open.aria': 'Ouvrir l’atelier de recette Python',
  'flow.recipe.inspector.script': 'Script',
  'flow.recipe.inspector.timeout': 'Délai max',
  'flow.recipe.inspector.timeout.value': '{seconds} s',
  'flow.recipe.inspector.env': 'Environnement',
  'flow.recipe.inspector.env.base': 'Base (aucune bibliothèque)',
  'flow.recipe.workshop.title': 'Atelier de recette Python',
  'flow.recipe.workshop.close': 'Fermer l’atelier de recette',
  'flow.recipe.editor.label': 'Script',
  'flow.recipe.editor.contract': 'def main(inputs: dict) -> dict:',
  'flow.recipe.editor.lines': '{count} ligne(s)',
  'flow.recipe.editor.aria': 'Script Python de la recette',
  'flow.recipe.tabs.aria': 'Panneaux de la recette',
  'flow.recipe.tab.env': 'Environnement',
  'flow.recipe.tab.io': 'Entrées/Sorties',
  'flow.recipe.tab.test': 'Test',
  'flow.recipe.env.requirements': 'Bibliothèques (une par ligne)',
  'flow.recipe.env.requirements.placeholder': 'ex. pandas==2.2.3',
  'flow.recipe.env.import': 'Importer requirements.txt',
  'flow.recipe.env.import.aria': 'Importer un fichier requirements.txt local',
  'flow.recipe.env.packages': '{count} bibliothèque(s)',
  'flow.recipe.env.invalid_lines':
    'Ligne refusée (les options pip ne sont pas autorisées) : {line}',
  'flow.recipe.env.registry': 'Registre (index pip)',
  'flow.recipe.env.registry.placeholder': 'pip par défaut (PyPI)',
  'flow.recipe.env.extra_registries': 'Registres supplémentaires (un par ligne)',
  'flow.recipe.env.extra_registries.placeholder': 'Aucun',
  'flow.recipe.env.timeout': 'Délai max (s)',
  'flow.recipe.env.state': 'Environnement Python',
  'flow.recipe.env.refresh': 'Actualiser',
  'flow.recipe.env.disabled':
    'L’exécution de recettes est désactivée sur ce déploiement — les essais échoueront tant qu’elle n’est pas activée.',
  'flow.recipe.env.stale':
    'Le spec a changé — actualisez pour résoudre le nouvel environnement.',
  'flow.recipe.env.locked': 'versions verrouillées',
  'flow.recipe.env.prepare': 'Préparer maintenant',
  'flow.recipe.env.preparing': 'Préparation…',
  'flow.recipe.env.resolving': 'Résolution de l’environnement…',
  'flow.recipe.env.status.pending': 'À construire',
  'flow.recipe.env.status.building': 'Construction',
  'flow.recipe.env.status.ready': 'Prêt',
  'flow.recipe.env.status.failed': 'En échec',
  'flow.recipe.env.status.evicted': 'Évincé',
  'flow.recipe.execution.status.queued': 'En attente',
  'flow.recipe.execution.status.env_building': 'Préparation de l’environnement',
  'flow.recipe.execution.status.running': 'En cours',
  'flow.recipe.execution.status.succeeded': 'Réussie',
  'flow.recipe.execution.status.failed': 'En échec',
  'flow.recipe.execution.status.cancelled': 'Annulée',
  'flow.recipe.execution.status.timed_out': 'Délai dépassé',
  'flow.recipe.reason.cancel_requested': 'Exécution annulée à la demande.',
  'flow.recipe.reason.env_not_found':
    'L’Environnement Python n’existe plus — relancez pour le reconstruire.',
  'flow.recipe.reason.worker_lost':
    'Le service d’exécution a été interrompu en cours de route ; par prudence, le script n’a pas été rejoué.',
  'flow.recipe.reason.disabled':
    'L’exécution de recettes est désactivée sur ce déploiement.',
  'flow.recipe.reason.output_too_large': 'La sortie dépasse la taille maximale autorisée.',
  'flow.recipe.reason.output_not_object': 'main doit retourner un dict (objet JSON).',
  'flow.recipe.reason.output_unreadable': 'La sortie n’a pas pu être lue comme du JSON.',
  'flow.recipe.reason.timeout': 'Délai dépassé après {seconds} s.',
  'flow.recipe.reason.env_build_failed': 'La construction de l’environnement a échoué.',
  'flow.recipe.reason.exit': 'Le script s’est terminé avec le code {code}.',
  'flow.recipe.reason.unknown': 'L’exécution a échoué.',
  'flow.recipe.io.hint':
    'Le contrat du nœud : ce que la recette reçoit dans inputs, et la forme du dict que main retourne.',
  'flow.recipe.io.input.label': 'Schéma d’entrée',
  'flow.recipe.io.input.hint': 'Ce que la recette reçoit dans inputs.',
  'flow.recipe.io.input.fallback': 'Sans schéma, la recette reçoit l’objet amont tel quel.',
  'flow.recipe.io.output.label': 'Schéma de sortie',
  'flow.recipe.io.output.hint': 'La forme du dict que main doit retourner.',
  'flow.recipe.io.output.fallback': 'Sans schéma, la sortie est publiée telle quelle.',
  'flow.recipe.test.no_system':
    'Le test isolé exige un Système chargé — il n’est pas disponible sur le Flow libre.',
  'flow.recipe.test.input': 'Entrée d’essai (JSON)',
  'flow.recipe.test.run': 'Exécuter la recette',
  'flow.recipe.test.busy': 'Exécution…',
  'flow.recipe.test.cancel': 'Annuler l’exécution',
  'flow.recipe.test.cancel_requested':
    'Annulation demandée — la recette s’arrête au prochain point de contrôle.',
  'flow.recipe.test.output': 'Sortie',
  'flow.recipe.test.duration': 'Durée : {seconds} s',
  'flow.recipe.test.dispatching': 'Envoi de l’essai…',

  // ---- atelier SQL (node sql_transform_v1) -------------------------------
  'flow.inspector.section.transform': 'Transformation SQL',
  'flow.transform.inspector.hint':
    'La requête est portée par le graphe : elle est versionnée avec le Flow et produit un nouveau jeu de données à chaque exécution.',
  'flow.transform.inspector.open': 'Ouvrir l’atelier SQL',
  'flow.transform.inspector.open.aria': 'Ouvrir l’atelier de transformation SQL',
  'flow.transform.inspector.statement': 'Requête',
  'flow.transform.inspector.output': 'Sortie',
  'flow.transform.inspector.output.auto': 'Nom du node',
  'flow.transform.inspector.sources': 'Entrées épinglées',
  'flow.transform.inspector.sources.none': 'Aucune — les jeux de données amont sont utilisés',
  'flow.transform.inspector.sources.count': '{count} épinglée(s)',
  'flow.transform.workshop.title': 'Atelier SQL',
  'flow.transform.workshop.close': 'Fermer l’atelier SQL',
  'flow.transform.editor.label': 'Requête',
  'flow.transform.editor.engine': 'duckdb · lecture seule',
  'flow.transform.editor.lines': '{count} ligne(s)',
  'flow.transform.editor.aria': 'Requête SQL de la transformation',
  'flow.transform.editor.placeholder': 'SELECT * FROM input',
  'flow.transform.run': 'Tester la requête',
  'flow.transform.run.busy': 'Exécution…',
  'flow.transform.run.shortcut': 'Ctrl + Entrée',
  'flow.transform.tabs.aria': 'Panneaux de la transformation',
  'flow.transform.tab.sources': 'Entrées',
  'flow.transform.tab.output': 'Sortie',

  // entrées
  'flow.transform.sources.hint':
    'Épinglez les jeux de données que la requête interroge. À l’exécution, les jeux de données arrivant des nodes amont s’ajoutent automatiquement.',
  'flow.transform.sources.add': 'Épingler un jeu de données',
  'flow.transform.sources.remove': 'Retirer',
  'flow.transform.sources.empty':
    'Aucune entrée épinglée : épinglez un jeu de données pour écrire et tester la requête ici.',
  'flow.transform.sources.loading': 'Chargement des jeux de données…',
  'flow.transform.sources.none_available':
    'Aucun jeu de données prêt dans cet espace de travail. Importez-en un depuis la page Données.',
  'flow.transform.sources.rows': '{rows} lignes · {columns} colonnes',
  'flow.transform.sources.alias': 'aussi : {aliases}',
  'flow.transform.sources.columns': 'Colonnes',
  // Neutre par moteur : le bouton écrit un select, un script ou un modèle dbt.
  'flow.transform.sources.starter': 'Exemple de départ',
  'flow.transform.sources.starter.aria': 'Écrire un exemple de départ sur {view}',
  'flow.transform.sources.insert.aria': 'Insérer la colonne {column} de {view} dans l’éditeur',
  'flow.transform.sources.catalog': 'Tables interrogeables',

  // sortie
  'flow.transform.output.name': 'Nom du jeu de données produit',
  'flow.transform.output.name.placeholder': 'ex. clients enrichis',
  'flow.transform.output.hint':
    'Chaque exécution écrit une nouvelle version de ce jeu de données, avec son lignage vers les entrées.',
  'flow.transform.output.versioning':
    'Versionné : v1, v2, v3… La page Données affiche l’historique complet.',
  'flow.transform.output.open_data': 'Voir la page Données',

  // résultat
  'flow.transform.result.title': 'Résultat',
  'flow.transform.result.empty':
    'Lancez la requête pour voir les lignes, le schéma et le profil des colonnes.',
  'flow.transform.result.caption': 'calculé en {duration} ms',
  'flow.transform.result.truncated': 'Aperçu limité à {limit} lignes',
  'flow.transform.result.no_rows': 'La requête n’a retourné aucune ligne.',

  // refus
  'flow.transform.error.SQL_EMPTY': 'Écrivez une requête SELECT avant de lancer le test.',
  'flow.transform.error.SQL_TOO_LONG': 'La requête est trop longue pour être exécutée.',
  'flow.transform.error.SQL_MULTIPLE_STATEMENTS':
    'Une seule requête à la fois : une transformation produit une table.',
  'flow.transform.error.SQL_FORBIDDEN_KEYWORD':
    'Mot-clé refusé : une transformation lit ses entrées et retourne des lignes, elle ne modifie rien.',
  'flow.transform.error.SQL_NOT_READ_ONLY':
    'Seules les requêtes en lecture sont autorisées (SELECT, WITH, FROM).',
  'flow.transform.error.SQL_FORBIDDEN_FUNCTION':
    'Fonction refusée : interrogez les entrées déclarées plutôt que des fichiers.',
  'flow.transform.error.SQL_EXECUTION_FAILED': 'Le moteur a refusé la requête.',
  'flow.transform.error.SQL_RESULT_TOO_LARGE':
    'Le résultat dépasse la taille maximale : filtrez ou agrégez davantage.',
  'flow.transform.error.SQL_NO_COLUMNS': 'La requête ne retourne aucune colonne.',
  'flow.transform.error.TRANSFORM_NO_INPUT':
    'Épinglez un jeu de données ou connectez un node amont avant de lancer la transformation.',
  'flow.transform.error.TRANSFORM_WORKSPACE_REQUIRED':
    'La transformation doit s’exécuter dans le contexte d’un espace de travail.',
  'flow.transform.error.DATASET_NOT_FOUND': 'Le jeu de données référencé n’existe plus.',
  'flow.transform.error.DATASET_NOT_READY':
    'Le jeu de données est encore en préparation — réessayez dans un instant.',
  'flow.transform.error.TABULAR_DISABLED': 'Le plan data est désactivé sur cette instance.',
  'flow.transform.error.unknown': 'La transformation a échoué.',
  'flow.transform.error.at_line': 'Ligne {line}, colonne {column}',

  // ---- atelier Polars (node polars_transform_v1) -------------------------
  // Même atelier, autre langage : seules les phrases propres au moteur
  // changent, tout le reste est partagé avec le bloc SQL ci-dessus.
  'flow.inspector.section.transform.polars': 'Transformation Polars',
  'flow.transform.polars.inspector.hint':
    'Le script est porté par le graphe : il est versionné avec le Flow et s’exécute dans un environnement Python managé et isolé, jamais dans le processus de l’application.',
  'flow.transform.polars.inspector.open': 'Ouvrir l’atelier Polars',
  'flow.transform.polars.inspector.open.aria': 'Ouvrir l’atelier de transformation Polars',
  'flow.transform.polars.inspector.script': 'Script',
  'flow.transform.polars.workshop.title': 'Atelier Polars',
  'flow.transform.polars.workshop.close': 'Fermer l’atelier Polars',
  'flow.transform.polars.editor.label': 'Script',
  'flow.transform.polars.editor.engine': 'polars · environnement managé',
  'flow.transform.polars.editor.aria': 'Script Polars de la transformation',
  'flow.transform.polars.editor.placeholder':
    'def transform(inputs): return inputs["input"]',
  'flow.transform.polars.run': 'Tester le script',
  'flow.transform.polars.sources.hint':
    'Épinglez les jeux de données que le script reçoit. Chaque entrée est une DataFrame dans le dictionnaire « inputs » ; les jeux de données amont s’ajoutent automatiquement à l’exécution.',
  'flow.transform.polars.result.empty':
    'Lancez le script pour voir les lignes, le schéma et le profil des colonnes produits.',

  // phases d’un essai mis en file (le worker porte l’environnement managé)
  'flow.transform.phase.queued': 'En file…',
  'flow.transform.phase.env_building': 'Préparation de l’environnement…',
  'flow.transform.phase.running': 'Exécution…',
  'flow.transform.run.cancel': 'Arrêter',
  'flow.transform.stdout': 'Sortie du script',

  // environnement
  'flow.transform.tab.environment': 'Librairies',
  'flow.transform.tab.environment.imposed': 'Environnement',
  'flow.transform.environment.hint':
    'Déclarez les librairies supplémentaires du projet : l’environnement est identifié par son empreinte, préparé au premier essai puis réutilisé.',
  'flow.transform.environment.imposed.hint':
    'L’environnement est imposé : le script tourne sur le moteur épinglé, sans librairie supplémentaire.',
  'flow.transform.environment.requirements': 'Librairies (une par ligne)',
  'flow.transform.environment.requirements.placeholder':
    'scikit-learn==1.5.0\nstatsmodels==0.14.2',
  'flow.transform.environment.count': '{count} librairie(s) déclarée(s)',
  'flow.transform.environment.timeout': 'Budget temps (secondes)',

  // refus propres au moteur Python
  'flow.transform.error.POLARS_CODE_REQUIRED':
    'Écrivez une fonction transform(inputs) avant de lancer l’essai.',
  'flow.transform.error.POLARS_CODE_TOO_LARGE': 'Le script dépasse la taille autorisée.',
  'flow.transform.error.POLARS_EXECUTION_DISABLED':
    'Les transformations Python sont désactivées sur cette instance : le plan d’environnements managés n’est pas activé.',
  'flow.transform.error.POLARS_ENV_NOT_READY':
    'L’environnement Python de cette transformation n’a pas pu être préparé.',
  'flow.transform.error.POLARS_SCRIPT_RAISED': 'Le script a levé une exception.',
  'flow.transform.error.POLARS_TRANSFORM_MISSING':
    'Définissez « def transform(inputs) » : c’est le point d’entrée que le node appelle.',
  'flow.transform.error.POLARS_RESULT_NOT_TABULAR':
    'transform() doit retourner une DataFrame polars (une LazyFrame, un dict de colonnes ou une liste de lignes conviennent aussi).',
  'flow.transform.error.POLARS_RESULT_UNWRITABLE':
    'Le résultat n’a pas pu être écrit sur le disque de travail.',
  'flow.transform.error.POLARS_RESULT_MISSING':
    'Le script n’a produit aucune table : retournez une DataFrame.',
  'flow.transform.error.POLARS_RESULT_TOO_LARGE':
    'Le résultat dépasse la taille maximale : filtrez ou agrégez davantage.',
  'flow.transform.error.POLARS_HARNESS_ERROR':
    'L’exécution du script a échoué avant d’atteindre transform().',
  'flow.transform.error.POLARS_TIMEOUT':
    'Le script a dépassé son budget temps et a été arrêté.',
  'flow.transform.error.POLARS_CANCELLED': 'Essai arrêté à votre demande.',

  // ---- atelier dbt (node dbt_transform_v1) -------------------------------
  // Le seul moteur qui peut refuser son propre résultat : les tests de données
  // déclarés dans schema.yml sont une condition de publication, pas un rapport.
  'flow.inspector.section.transform.dbt': 'Transformation dbt',
  'flow.transform.dbt.inspector.hint':
    'Le projet dbt est porté par le graphe : plusieurs modèles liés par ref(), les entrées adressées par source(), et des tests de données qui conditionnent la publication du jeu de données.',
  'flow.transform.dbt.inspector.open': 'Ouvrir l’atelier dbt',
  'flow.transform.dbt.inspector.open.aria': 'Ouvrir l’atelier de transformation dbt',
  'flow.transform.dbt.inspector.project': 'Modèle publié',
  'flow.transform.dbt.workshop.title': 'Atelier dbt',
  'flow.transform.dbt.workshop.close': 'Fermer l’atelier dbt',
  'flow.transform.dbt.editor.label': 'Modèle',
  'flow.transform.dbt.editor.engine': 'dbt-duckdb · environnement managé',
  'flow.transform.dbt.editor.aria': 'Modèle dbt de la transformation',
  'flow.transform.dbt.editor.placeholder': "select * from {{ ref('stg_input') }}",
  'flow.transform.dbt.run': 'Construire le projet',
  'flow.transform.dbt.sources.hint':
    'Épinglez les jeux de données que le projet reçoit. Chaque entrée est adressable par source(\'inputs\', \'nom\') ; les jeux de données amont s’ajoutent automatiquement à l’exécution.',
  'flow.transform.dbt.result.empty':
    'Construisez le projet pour voir les lignes du modèle publié, son schéma et le verdict des tests.',

  // rail de fichiers du projet
  'flow.transform.files.aria': 'Fichiers du projet dbt',
  'flow.transform.files.add': 'Nouveau modèle',
  'flow.transform.files.remove': 'Supprimer',
  'flow.transform.files.publish': 'Publier',
  'flow.transform.files.publish.hint':
    'Faire de ce modèle le jeu de données produit par le node.',
  'flow.transform.files.published': 'publié',
  'flow.transform.files.published.hint':
    'C’est ce modèle qui devient le jeu de données versionné à chaque exécution.',
  'flow.transform.files.materialize': 'Matérialiser',
  'flow.transform.files.materialize.hint':
    'Versionner aussi ce modèle comme jeu de données à chaque exécution, à côté du modèle publié.',
  'flow.transform.files.materialize.off': 'Ne plus matérialiser',
  'flow.transform.files.materialized': 'dataset',
  'flow.transform.files.materialized.hint':
    'Ce modèle est aussi versionné comme jeu de données à chaque exécution.',
  'flow.transform.files.rename.aria': 'Nom de relation du modèle',
  'flow.transform.files.tests.label': 'Tests',

  // verdict de construction
  'flow.transform.dbt.build.passed':
    '{models} modèle(s) construit(s) · {tests} test(s) passé(s)',
  'flow.transform.dbt.build.refused': '{count} test(s) en échec — rien n’est publié',
  'flow.transform.dbt.build.failures': '{count} ligne(s)',

  // refus propres au moteur dbt
  'flow.transform.error.DBT_MODELS_REQUIRED':
    'Écrivez au moins un modèle avant de construire le projet.',
  'flow.transform.error.DBT_MODEL_NAME_INVALID':
    'Un nom de modèle est un nom de relation : minuscules, chiffres et « _ », commençant par une lettre.',
  'flow.transform.error.DBT_MODEL_NAME_DUPLICATE':
    'Deux modèles portent le même nom : dbt ne saurait pas lequel ref() désigne.',
  'flow.transform.error.DBT_MODEL_EMPTY': 'Ce modèle est vide : écrivez un select.',
  'flow.transform.error.DBT_MODEL_TOO_LARGE': 'Ce modèle dépasse la taille autorisée.',
  'flow.transform.error.DBT_MODEL_SHADOWS_SOURCE':
    'Un modèle porte le nom d’une entrée : renommez-le pour que source() reste sans ambiguïté.',
  'flow.transform.error.DBT_TOO_MANY_MODELS':
    'Le projet dépasse le nombre de modèles autorisé pour un node.',
  'flow.transform.error.DBT_TESTS_TOO_LARGE': 'Le fichier de tests dépasse la taille autorisée.',
  'flow.transform.error.DBT_OUTPUT_MODEL_MISSING':
    'Le modèle publié n’existe pas dans le projet.',
  'flow.transform.error.DBT_EXECUTION_DISABLED':
    'Les transformations dbt sont désactivées sur cette instance : le plan d’environnements managés n’est pas activé.',
  'flow.transform.error.DBT_BUILD_FAILED': 'dbt a refusé de construire le projet.',
  'flow.transform.error.DBT_TESTS_FAILED':
    'Des tests de données ont échoué : le node ne publie pas un résultat qu’il sait faux.',
  'flow.transform.error.DBT_RESULT_NO_COLUMNS':
    'Le modèle publié ne retourne aucune colonne.',
  'flow.transform.error.DBT_RESULT_UNWRITABLE':
    'Le résultat n’a pas pu être écrit sur le disque de travail.',
  'flow.transform.error.DBT_RESULT_MISSING':
    'Le projet n’a produit aucune table : vérifiez le modèle publié.',
  'flow.transform.error.DBT_RESULT_TOO_LARGE':
    'Le résultat dépasse la taille maximale : filtrez ou agrégez davantage.',
  'flow.transform.error.DBT_HARNESS_ERROR':
    'L’exécution du projet a échoué avant que dbt ne démarre.',
  'flow.transform.error.DBT_TIMEOUT':
    'Le projet a dépassé son budget temps et a été arrêté.',
  'flow.transform.error.DBT_CANCELLED': 'Construction arrêtée à votre demande.',

  // ---- plan modèle : nodes train / predict / score -----------------------
  // Trois formes, pas trois options d’un même node : un ajustement s’écrit —
  // donc un atelier — tandis qu’une prédiction se choisit — donc une section
  // d’inspecteur. Le vocabulaire des refus partagés reste celui de la page
  // Modèles : une même raison ne mérite pas deux phrases à tenir à jour.
  'flow.inspector.section.train': 'Entraînement du modèle',
  'flow.ml.train.inspector.hint':
    'La cible, les variables, l’algorithme et la découpe sont portés par le graphe : une charge entrante ne peut pas réécrire ce que ce node apprend.',
  'flow.ml.train.inspector.target': 'Cible',
  'flow.ml.train.inspector.target.none': 'à choisir',
  'flow.ml.train.inspector.dataset': 'Jeu de données',
  'flow.ml.train.inspector.dataset.wire': 'celui reçu en amont',
  'flow.ml.train.inspector.output': 'Modèle produit',
  'flow.ml.train.inspector.output.auto': 'nommé d’après la cible',
  'flow.ml.train.inspector.open': 'Ouvrir l’atelier d’entraînement',
  'flow.ml.train.inspector.open.aria': 'Ouvrir l’atelier d’entraînement du modèle',

  // atelier d’entraînement
  'flow.ml.train.title': 'Atelier d’entraînement',
  'flow.ml.train.close': 'Fermer l’atelier d’entraînement',
  'flow.ml.train.run': 'Entraîner',
  'flow.ml.train.busy': 'Entraînement…',
  'flow.ml.train.cancel': 'Arrêter',
  'flow.ml.train.target': 'Colonne à prédire',
  'flow.ml.train.target.hint':
    'Seules les colonnes qu’un modèle peut apprendre sont proposées, et leur type détermine la tâche.',
  'flow.ml.train.target.none':
    'Aucune colonne de ce jeu de données ne peut servir de cible.',
  'flow.ml.train.distinct': '{count} valeurs distinctes',
  'flow.ml.train.dataset.required':
    'Épinglez un jeu de données pour voir ses colonnes.',
  'flow.ml.train.task': 'Tâche',
  'flow.ml.train.task.suggested': 'Déduite du type de la colonne cible.',
  'flow.ml.train.features': 'Variables explicatives',
  'flow.ml.train.features.count': '{selected} / {total}',
  'flow.ml.train.features.all': 'Toutes',
  'flow.ml.train.features.hint':
    'Par défaut, toutes les colonnes sauf la cible. Une colonne unique par ligne est signalée : elle ferait mémoriser le tableau au modèle au lieu de le faire généraliser.',
  'flow.ml.train.algo': 'Algorithme',
  'flow.ml.train.knobs': 'Réglages',
  'flow.ml.train.knobs.reset': 'Par défaut',
  'flow.ml.train.split': 'Lignes de test',
  'flow.ml.train.split.hint':
    'Ces lignes ne servent pas à l’ajustement : ce sont elles qui produisent les scores.',
  'flow.ml.train.cv': 'Validation croisée',
  'flow.ml.train.cv.off': 'Désactivée',
  'flow.ml.train.cv.folds': '{folds} plis',
  'flow.ml.train.cv.hint':
    'La validation croisée donne un écart-type par métrique — plus long, mais un score isolé peut être un coup de chance.',
  'flow.ml.train.evidence.empty':
    'Lancez un entraînement : les étapes s’affichent ici, puis les scores obtenus sur les lignes de test.',
  'flow.ml.train.sample': 'Les lignes sur lesquelles l’ajustement va lire',
  'flow.ml.train.registered': 'Enregistré : {name} v{version}',
  'flow.ml.train.open_card': 'Voir la fiche',
  'flow.ml.train.tabs.aria': 'Panneaux de l’atelier d’entraînement',
  'flow.ml.train.tab.dataset': 'Données',
  'flow.ml.train.tab.test': 'Test',
  'flow.ml.train.tab.output': 'Modèle',
  'flow.ml.train.dataset': 'Jeu de données',
  'flow.ml.train.dataset.hint':
    'Épinglé par lignée : le node suit la dernière version prête. Sans épingle, il apprend sur le jeu de données reçu en amont.',
  'flow.ml.train.dataset.loading': 'Chargement…',
  'flow.ml.train.dataset.wire': 'Celui reçu en amont',
  'flow.ml.train.dataset.meta': '{rows} lignes · {columns} colonnes',
  'flow.ml.train.plan': 'Ce que ferait cet ajustement',
  'flow.ml.train.plan.rows': '{rows} lignes, dont {test} en test',
  'flow.ml.train.plan.features': '{count} variables retenues',
  'flow.ml.train.name': 'Nom du modèle',
  'flow.ml.train.name.hint':
    'Le nom de la lignée ; chaque entraînement en crée une nouvelle version.',
  'flow.ml.train.name.placeholder': 'Déduit de la cible',
  'flow.ml.train.versioning':
    'Un entraînement n’est jamais un essai à blanc : l’artefact EST le produit, donc chaque exécution enregistre une version dans le registre.',
  'flow.ml.train.open_models': 'Ouvrir les modèles',

  // nodes de service : une section, pas un atelier
  'flow.inspector.section.predict': 'Prédiction',
  'flow.inspector.section.score': 'Scoring du jeu de données',
  'flow.ml.predict.inspector.hint':
    'Ce node répond pour un enregistrement, pendant l’exécution. Le modèle appelé est porté par le graphe, jamais par la charge entrante.',
  'flow.ml.score.inspector.hint':
    'Ce node lit un jeu de données et en écrit une version scorée, colonnes de prédiction comprises.',
  'flow.inspector.section.forecast': 'Prévision des séries',
  'flow.ml.forecast.inspector.hint':
    'Prévoit chaque série du modèle sur son horizon et écrit un jeu de données : une ligne par série et par pas, avec l’intervalle. Les nodes en aval reçoivent aussi le pic de chaque série.',
  'flow.ml.forecast.empty':
    'Aucun modèle de prévision entraîné dans cet espace de travail : entraînez-en un (nature « Prévision ») avant de brancher ce node.',
  'flow.ml.forecast.horizon': 'Horizon',
  'flow.ml.forecast.horizon.hint':
    'Laissés vides, l’horizon et le niveau sont ceux du modèle. Un jeu branché en amont ne sert que pour les valeurs futures dont le modèle a besoin.',
  'flow.ml.forecast.level': 'Niveau d’intervalle',
  'flow.ml.forecast.level.model': 'Celui du modèle',
  'flow.ml.serving.model': 'Modèle',
  'flow.ml.serving.model.none': 'Aucun modèle choisi',
  'flow.ml.serving.version': 'Version',
  'flow.ml.serving.version.champion': 'Suivre le champion',
  'flow.ml.serving.version.pinned': 'v{version} figée',
  'flow.ml.serving.version.hint':
    'Suivre le champion, c’est répondre avec la version promue du moment ; figer une version, c’est répondre toujours la même chose.',
  'flow.ml.serving.empty':
    'Aucun modèle entraîné dans cet espace de travail : entraînez-en un avant de brancher ce node.',
  'flow.ml.serving.output': 'Jeu de données produit',
  'flow.ml.serving.output.auto': 'Déduit du modèle',
  'flow.ml.serving.output.produced': 'Les lignes écrites à la dernière exécution',
  'flow.ml.serving.output.open': 'Ouvrir le jeu de données',
  'flow.ml.serving.explain': 'Contributions par ligne',
  'flow.ml.serving.explain.hint':
    'Ajoute à la réponse les variables qui ont le plus pesé — utile pour une synthèse en aval, un peu plus coûteux à calculer.',

  // refus propres aux nodes du plan modèle (le reste parle le dictionnaire
  // de la page Modèles)
  'flow.ml.error.ml_no_dataset':
    'Branchez un jeu de données en amont, ou épinglez-en un sur le node, avant d’entraîner.',
  'flow.ml.error.ml_score_dataset_required':
    'Branchez un jeu de données en amont, ou épinglez-en un sur le node, avant de scorer.',
  'flow.ml.error.ml_model_required':
    'Choisissez le modèle avec lequel ce node répond.',
  'flow.ml.error.ml_target_in_features':
    'La cible ne peut pas figurer parmi ses propres variables explicatives.',
  'flow.ml.error.unknown': 'La demande a été refusée sans motif exploitable.',
  'flow.ml.run.cancelled': 'Entraînement arrêté à votre demande.',

  'flow.validation.error.server': 'Le Flow courant n’a pas pu être validé par le serveur.',
  'flow.run.input.error.json':
    'Saisissez du JSON valide.',
  'flow.run.input.error.object':
    'L’entrée d’exécution doit être un objet JSON.',
  'flow.run.input.error.debug_reserved':
    '« _debug » est réservé aux commandes du débogueur.',
  'flow.run.entry.none':
    'Ce brouillon n’a aucun point d’entrée. Ajoutez-en un avant de lancer un essai.',
  'flow.run.entry.select':
    'Sélectionnez le point d’entrée du brouillon avant de lancer l’essai.',
  'flow.run.entry.choose':
    'Choisissez l’un des {count} points d’entrée du brouillon avant de lancer l’essai.',
  'flow.run.entry.required':
    'Choisissez un point d’entrée du brouillon avant de lancer l’essai.',
  'flow.run.log.already_running':
    'Une exécution est déjà en cours.',
  'flow.run.log.sim_empty':
    'Ajoutez au moins un nœud avant de simuler.',
  'flow.run.log.sim_start':
    'Simulation côté navigateur — aucun appel au serveur.',
  'flow.run.log.sim_done':
    'Simulation terminée (essai à blanc).',
  'flow.run.log.debug_reserved':
    'Exécution refusée — « _debug » est réservé aux commandes du débogueur.',
  'flow.run.log.dispatching':
    'Envoi de l’exécution au serveur…',
  'flow.run.log.no_hash':
    'Exécution bloquée — le Flow enregistré n’a pas d’empreinte de référence.',
  'flow.run.log.debugger_attached':
    'Débogueur attaché · mode={mode} · points d’arrêt={count}',
  'flow.run.log.trigger_rejected':
    'Le serveur a refusé la demande de déclenchement.',
  'flow.run.log.scheduled':
    'Exécution {id}… planifiée (statut={status}).',
  'flow.run.log.approval_accepted':
    'L’opérateur a approuvé l’étape en attente.',
  'flow.run.log.approval_declined':
    'L’opérateur a refusé l’étape en attente.',
  'flow.run.log.approval_rejected':
    'Approbation humaine refusée par le serveur.',
  'flow.run.log.approval_network':
    'Erreur réseau pendant l’approbation humaine.',
  'flow.run.log.operator_action':
    'Opérateur → {action}',
  'flow.run.log.debug_rejected':
    'Débogueur refusé par le serveur.',
  'flow.run.log.debug_network':
    'Erreur réseau pendant l’action de débogage.',
  'flow.run.log.replay_none':
    'Aucun point de contrôle à rejouer sur cette exécution.',
  'flow.run.log.replay_start':
    'Relecture de {count} points de contrôle de l’exécution {id}…',
  'flow.run.log.replay_done':
    'Relecture terminée.',
  'flow.run.log.validation_blocked':
    'Bloqué — {count} erreur(s) de validation. Corrigez avant de lancer :',
  'flow.run.log.stream_interrupted':
    'Flux direct interrompu — repli sur l’interrogation périodique.',
  'flow.run.log.connection_lost':
    'Connexion au serveur perdue (flux + interrogation).',
  'flow.run.log.poll_lost':
    'Connexion perdue pendant l’interrogation de l’exécution.',
  'flow.run.log.failed':
    'Exécution en échec',
  'flow.run.log.failed_detail':
    'Exécution en échec · {detail}',
  'flow.run.log.no_output':
    'Exécution terminée sans charge utile de sortie.',
  'flow.run.log.walker_booted':
    'Moteur démarré — exécution du graphe.',
  'flow.run.log.decision_matched':
    'Décision {node} · correspondance{branch}',
  'flow.run.log.decision_default':
    'Décision {node} · par défaut{branch}',
  'flow.run.log.decision_no_match':
    'Décision {node} · aucune branche correspondante',
  'flow.run.log.decision_unroutable':
    'Décision {node} · non routable{branch}',
  'flow.run.log.decision_error':
    'Décision {node} · erreur d’évaluation',
  'flow.run.log.finished':
    'Exécution terminée · statut={status}',
  'flow.run.log.draft_changed':
    'Le brouillon serveur a changé avant la création de l’essai. Rechargez-le avant de continuer.',
  'flow.run.blocked.scratchpad':
    'Un brouillon libre ne peut pas s’exécuter — promouvez-le en Système d’abord.',
  'flow.run.blocked.hydration':
    'Exécution verrouillée tant que le Flow persisté n’est pas strictement chargé.',
  'flow.run.blocked.saving':
    'Exécution verrouillée pendant la sauvegarde ou le changement de version.',
  'flow.run.blocked.save_failed':
    'Exécution verrouillée : la dernière sauvegarde a échoué.',
  'flow.run.blocked.unsaved':
    'Enregistrez le Flow courant avant de l’exécuter.',
  'flow.run.blocked.no_hash':
    'Exécution verrouillée : le Flow enregistré n’a pas d’empreinte de référence.',
  'flow.run.blocked.server_changed':
    'Le Flow a changé sur le serveur. Rechargez le Flow de référence avant de l’exécuter.',
  'flow.run.blocked.validation_failed':
    'Exécution verrouillée : le Flow courant n’a pas pu être validé par le serveur.',
  'flow.run.blocked.validation_pending':
    'Exécution verrouillée tant que le Flow courant n’est pas validé par le serveur.',
  'flow.run.blocked.validation_refreshing':
    'Exécution verrouillée pendant la mise à jour de la validation serveur sur l’empreinte enregistrée.',
  'flow.run.blocked.server_errors':
    'Exécution verrouillée par les erreurs de validation serveur en cours.',
  'flow.run.blocked.local_errors':
    'Exécution verrouillée par des erreurs de validation du Flow.',
  'flow.run.blocked.breakpoints':
    'Le débogage par points d’arrêt exige au moins un nœud sélectionné.',
  'flow.run.blocked.revision_missing':
    'Exécution verrouillée : la révision du brouillon serveur est absente.',
  'flow.run.blocked.draft_mode_unknown':
    'Exécution verrouillée : le mode d’exécution du brouillon est inconnu.',
  'flow.run.blocked.contract_loading':
    'Exécution verrouillée tant que le contrat d’exécution de ce Système n’est pas chargé.',
  'flow.run.blocked.contract_no_hash':
    'Exécution verrouillée : le contrat d’exécution n’a pas d’empreinte de Flow.',
  'flow.run.blocked.contract_refreshing':
    'Exécution verrouillée pendant la mise à jour du contrat d’exécution sur le Flow enregistré.',
  'flow.run.blocked.server_mode_unknown':
    'Exécution verrouillée : le mode d’exécution serveur est inconnu.',
  'flow.run.error.network':
    'Erreur réseau lors du déclenchement de l’exécution.',
  'flow.run.error.denied':
    'Exécution refusée — vous n’avez pas la permission d’exécuter ce Système.',
  'flow.run.error.flow_changed':
    'Exécution refusée — le Flow enregistré a changé. Rechargez avant de réessayer.',
  'flow.run.error.invalid_input':
    'Exécution refusée — l’entrée d’exécution ou la configuration de débogage est invalide.',
  'flow.run.error.http':
    'Exécution refusée par le serveur (HTTP {status}).',

  // ---- publication -------------------------------------------------------
  'flow.publish.eyebrow': 'Brouillon → Publié',
  'flow.publish.title': 'Relire la publication',
  'flow.publish.subtitle':
    'Crée une version immuable. Cela n’active jamais le Système et ne le relance pas.',
  'flow.publish.close': 'Fermer la relecture de publication',
  'flow.publish.diff.loading': 'Chargement de l’écart sémantique…',
  'flow.publish.diff.error': 'Écart de publication indisponible.',
  'flow.publish.diff.aria': 'Résumé de l’écart sémantique',
  'flow.publish.diff.changes.aria': 'Changements sémantiques',
  'flow.publish.diff.breaking': '{count} incompatibles',
  'flow.publish.diff.behavioral': '{count} de comportement',
  'flow.publish.diff.presentation': '{count} de présentation',
  'flow.publish.diff.empty': 'Aucun changement sémantique détecté.',
  'flow.publish.ack':
    'J’ai relu les changements incompatibles et j’accepte explicitement leur impact en production.',
  'flow.publish.message': 'Message de version',
  'flow.publish.message.placeholder':
    'Ce qui change, pourquoi, et ce que les opérateurs doivent savoir',
  'flow.publish.cancel': 'Annuler',
  'flow.publish.submit': 'Publier une version immuable',
  'flow.publish.submitting': 'Publication…',

  // ---- versions ----------------------------------------------------------
  'flow.versions.title': 'Historique du Flow',
  'flow.versions.subtitle': 'Journal en ajout seul · restaurez n’importe quelle version',
  'flow.versions.total': '{count} versions',
  'flow.versions.refresh': 'Actualiser',
  'flow.versions.refresh.aria': 'Actualiser les versions',
  'flow.versions.loading': 'Chargement…',
  'flow.versions.empty':
    'Aucun historique. La première sauvegarde de ce Système crée la v1.',
  'flow.versions.tag.published': 'Publiée',
  'flow.versions.tag.current': 'Courante',
  'flow.versions.tag.rollback': 'Restauration',
  'flow.versions.preview': 'Aperçu',
  'flow.versions.preview.retry': 'Réessayer l’aperçu',
  'flow.versions.preview.hint': 'Charger et afficher l’écart sémantique',
  'flow.versions.restore': 'Restaurer cette version',
  'flow.versions.load_more': 'Charger les versions plus anciennes',
  'flow.versions.confirm.aria': 'Confirmer la restauration',
  'flow.versions.confirm.published':
    'Restaurer la v{version} dans le brouillon serveur et remplacer le canevas. La version publiée et le statut du Système restent inchangés.',
  'flow.versions.confirm.draft':
    'Créer une version qui copie le graphe de la v{version} et remplace le canevas. L’historique est en ajout seul — rien n’est supprimé.',
  'flow.versions.confirm.loading':
    'Chargement de la charge immuable exacte et de l’écart sémantique faisant autorité…',
  'flow.versions.confirm.retry': 'Réessayer l’aperçu exact',
  'flow.versions.confirm.ready': 'Aperçu exact prêt · {diff}',
  'flow.versions.confirm.message.aria': 'Message de restauration',
  'flow.versions.confirm.message.placeholder': 'restauration vers la v{version}',
  'flow.versions.confirm.cancel': 'Annuler',
  'flow.versions.confirm.submit': 'Restaurer le brouillon',
  'flow.versions.confirm.submit.draft': 'Confirmer',
  'flow.versions.confirm.pending': 'Restauration…',

  // ---- triggers (schedules, webhooks, piloting) --------------------------
  'flow.triggers.schedules': 'Planifications (cron)',
  'flow.triggers.schedules.loading': 'Chargement des planifications…',
  'flow.triggers.schedules.error': 'Planifications indisponibles.',
  'flow.triggers.schedules.empty': 'Aucune planification.',
  'flow.triggers.schedules.name': 'Nom',
  'flow.triggers.schedules.cron': 'Cron (ex. 0 * * * *)',
  'flow.triggers.schedules.create': 'Créer',
  'flow.triggers.schedules.created': 'Planification créée.',
  'flow.triggers.schedules.create_failed': 'La création de la planification a échoué.',
  'flow.triggers.schedules.update_failed': 'La mise à jour de la planification a échoué.',
  'flow.triggers.webhooks': 'Webhooks',
  'flow.triggers.webhooks.loading': 'Chargement des webhooks…',
  'flow.triggers.webhooks.error': 'Webhooks indisponibles.',
  'flow.triggers.webhooks.empty': 'Aucun webhook.',
  'flow.triggers.webhooks.name': 'Nom du webhook',
  'flow.triggers.webhooks.create': 'Créer un webhook',
  'flow.triggers.webhooks.created': 'Webhook créé — copiez le secret.',
  'flow.triggers.webhooks.create_failed': 'La création du webhook a échoué.',
  'flow.triggers.webhooks.update_failed': 'La mise à jour du webhook a échoué.',
  'flow.triggers.webhooks.secret': 'Secret (copiez-le maintenant) :',
  'flow.triggers.retry': 'Réessayer',
  'flow.triggers.on': 'ACTIF',
  'flow.triggers.off': 'INACTIF',
  'flow.triggers.enable': 'Activer',
  'flow.triggers.disable': 'Désactiver',
  'flow.triggers.toast.title': 'Déclencheurs',
  'flow.triggers.piloting': 'Pilotage des déclencheurs',
  'flow.triggers.piloting.loading': 'Chargement de l’état…',
  'flow.triggers.piloting.error': 'État indisponible.',
  'flow.triggers.piloting.global': 'Plateforme',
  'flow.triggers.piloting.global.on': 'Activés',
  'flow.triggers.piloting.global.off': 'Désactivés',
  'flow.triggers.piloting.mode': 'Mode du Système',
  'flow.triggers.piloting.mode.live': 'Réel',
  'flow.triggers.piloting.mode.dry': 'Simulation',
  'flow.triggers.piloting.global.note':
    'Les déclencheurs sont désactivés au niveau de la plateforme — le mode ci-dessous ne s’applique qu’une fois activés.',
  'flow.triggers.piloting.to_dry': 'Repasser en simulation',
  'flow.triggers.piloting.to_live': 'Passer en réel',
  'flow.triggers.piloting.live_done': 'Mode réel activé.',
  'flow.triggers.piloting.dry_done': 'Mode simulation rétabli.',
  'flow.triggers.piloting.breaker.open': 'Coupe-circuit ouvert — déclencheur désarmé',
  'flow.triggers.piloting.breaker.cause': 'Cause : {reason}',
  'flow.triggers.piloting.breaker.rearm': 'Réarmer',
  'flow.triggers.piloting.breaker.rearmed': 'Déclencheur réarmé.',
  'flow.triggers.piloting.breaker.armed': 'Coupe-circuit armé',
  'flow.triggers.piloting.runs': 'Voir les exécutions déclenchées',
  'flow.triggers.piloting.failed': 'La mise à jour du déclencheur a échoué.',

  // --- palette · descriptions des primitives structurelles (P3) -----------
  // Clé construite au rendu depuis le `type` de l’entrée
  // (`flow.palette.desc.<type>`), avec repli sur la description brute :
  // les skills du catalogue backend (type 'skill') sont des données et ne
  // sont jamais mappées ici. Voir flow-palette.component.ts.
  'flow.palette.desc.source': 'Entrée / objectif du Flow',
  'flow.palette.desc.source.collection': 'Collection de connaissances comme source de données',
  'flow.palette.desc.source.sftp_arrival':
    'Déclencheur à l’arrivée de fichiers (clôture de staging / réconciliation)',
  'flow.palette.desc.source.deposit_promoted':
    'Se déclenche quand un opérateur promeut des fichiers du dépôt vers une collection',
  'flow.palette.desc.source.schedule':
    'Déclencheur planifié par cron (géré dans le panneau Déclencheurs)',
  'flow.palette.desc.source.webhook': 'Déclencheur webhook entrant signé HMAC',
  'flow.palette.desc.task.role_agent':
    'Un rôle, une consigne et un contrat JSON strict en sortie',
  'flow.palette.desc.decision': 'Branche selon une condition',
  'flow.palette.desc.fork': 'Déploie des branches parallèles',
  'flow.palette.desc.join': 'Rassemble des branches parallèles',
  'flow.palette.desc.loop': 'Répète jusqu’à un budget ou une condition',
  'flow.palette.desc.agent_loop':
    'Boucle bornée : choisit la prochaine skill autorisée jusqu’à l’objectif',
  'flow.palette.desc.hitl': 'Pause pour une décision humaine, puis reprise',
  'flow.palette.label.agent_loop': 'Boucle agent',
  'flow.palette.label.task.role_agent': 'Agent à rôle',
  'flow.palette.label.hitl': 'Porte humaine',
  'flow.palette.desc.sink': 'Là où le Flow livre son résultat',
  // Groupe sentinelle de la palette : skills visibles sans Capability porteuse
  // (nom/indice fabriqués par la VM, traduits au rendu via le slug sentinelle).
  'flow.palette.uncarried.name': 'Sans Capability',
  'flow.palette.uncarried.hint': 'Visibles ici sans Capability pour les porter',
  'flow.promote.title': 'Créer le Système',
  'flow.promote.lead': 'Ce brouillon libre devient un Système. L’objectif est facultatif.',
  'flow.promote.name': 'Nom',
  'flow.promote.objective': 'Objectif (facultatif)',
  'flow.promote.submit': 'Créer le Système',
  'flow.promote.toast_title': 'Promotion',
  'flow.promote.success': 'Promu en Système « {name} ».',
  'flow.promote.error.name_required': 'Le nom est obligatoire.',
  'flow.promote.error.failed': 'Le Système n’a pas pu être créé. Votre brouillon local a été conservé.',
  'flow.promote.error.verify': 'Le Système a été créé, mais le flux n’a pas pu être vérifié. Relisez-le avant de réessayer.',
  'flow.promote.error.race': 'Le Système a été créé à partir d’une révision antérieure. Les modifications locales plus récentes restent dans ce brouillon.',

} as const satisfies Record<string, string>;

export const FLOW_EN: Record<keyof typeof FLOW_FR, string> = {
  'flow.sources.title': 'Data source',
  'flow.sources.palette': 'Workspace sources',
  'flow.sources.connector': 'Connector',
  'flow.sources.configured_reference': 'Saved configuration · reference',
  'flow.sources.collection': 'Document collection',
  'flow.sources.live': 'Live read',
  'flow.sources.reference': 'Reference',
  'flow.sources.live_help': 'Linked steps receive this reference. Only steps whose tool reads PostgreSQL query it, under the workspace’s rights; for other steps, the link documents the dependency. The preview is a sample; a DataOps import creates a separate versioned dataset.',
  'flow.sources.reference_help': 'This node supplies a connector reference. The consuming step reads or acts under its own contract.',
  'flow.sources.setup': 'Open connector',
  'flow.sources.browse': 'Browse tables',
  'flow.sources.refresh': 'Refresh',
  'flow.sources.loading': 'Loading sources…',
  'flow.sources.retry': 'Retry',
  'flow.sources.catalog_error': 'Catalog unavailable. Saved references are preserved.',
  'flow.sources.empty': 'No configured sources in this workspace.',
  'flow.sources.unavailable': 'unavailable',
  'flow.sources.missing': 'The referenced connector is no longer configured in this workspace.',
  'flow.sources.admin_required': 'A workspace administrator can browse and preview tables.',
  'flow.sources.resources': 'Scope · {count} tables',
  'flow.sources.resources_one': 'Scope · {count} table',
  'flow.sources.remove': 'Remove table {table} from scope',
  'flow.sources.no_resources': 'Select the tables accessible to linked steps.',
  'flow.sources.checked': 'Connection checked at {at}',
  'flow.sources.no_tables': 'No tables accessible to this account.',
  'flow.sources.choose_table': 'Choose a table',
  'flow.sources.columns': '{count} columns',
  'flow.sources.preview': 'Preview · 25 rows',
  'flow.sources.bound': 'In scope',
  'flow.sources.add_resource': 'Add to scope',
  'flow.sources.sample': 'Sample read at {at}',
  'flow.sources.consumers': 'Linked steps',
  'flow.sources.no_consumers': 'No step linked to this source.',
  'flow.sources.connect': 'Link a step',
  'flow.sources.choose_consumer': 'Choose a Flow step',
  'flow.sources.tables_count': '{count} tables',
  "flow.versions.blocked.matches_published": "The server draft already matches this published version.",
  "flow.versions.blocked.current": "This is already the current version.",
  "flow.versions.blocked.history": "Version history could not be loaded. Refresh before restoring.",
  "flow.versions.blocked.local_changes": "Save or discard your local changes before restoring a version.",
  "flow.versions.blocked.pending": "A restore is already running.",
  "flow.versions.blocked.write": "Wait for the Flow to finish loading or saving.",
  "flow.versions.evidence.missing_payload": "The immutable version payload was not returned.",
  "flow.versions.evidence.wrong_payload": "The immutable version payload does not match the selected history row.",
  "flow.versions.evidence.malformed_flow": "The immutable version contains a malformed Flow payload.",
  "flow.versions.evidence.malformed_contract": "The immutable version contains a malformed execution contract.",
  "flow.versions.evidence.missing_diff": "The authoritative semantic diff was not returned.",
  "flow.versions.evidence.missing_digest": "The immutable version digest is missing.",
  "flow.versions.evidence.wrong_digest": "The immutable version digest does not match the history row.",
  "flow.versions.evidence.wrong_base": "The semantic diff does not describe the selected immutable version.",
  "flow.versions.evidence.wrong_base_digest": "The semantic diff base digest does not match the immutable version.",
  "flow.versions.evidence.wrong_revision": "The semantic diff does not describe the current server draft revision.",
  "flow.versions.evidence.wrong_target_digest": "The semantic diff target digest does not match the current server draft.",
  "flow.versions.history_error": "Could not load version history. Existing rows may be stale.",
  "flow.versions.preview.local_changes": "Save or discard local changes before loading rollback evidence.",
  "flow.versions.preview.reload": "Reload the authoritative Draft/Published pointers first.",
  "flow.versions.preview.unverified": "The exact preview could not be verified.",
  "flow.versions.preview.verification_failed": "Could not verify the immutable payload and authoritative semantic diff.",
  "flow.versions.preview.load_failed": "Could not load the immutable version payload.",
  "flow.versions.preview.failed": "Exact preview failed.",
  "flow.versions.more_error": "Could not load more versions.",
  "flow.versions.restore_hint.published": "Restore this immutable version into the server draft; the published pointer stays unchanged",
  "flow.versions.restore_hint.draft": "Restore this version by appending a copy of its graph",
  "flow.versions.confirm.verify_first": "Load and verify the exact immutable version before confirming.",
  "flow.versions.blocked.title": "Rollback blocked",
  "flow.versions.blocked.restore_title": "Restore blocked",
  "flow.versions.confirm.local_changes": "Save or discard local changes before rolling back.",
  "flow.versions.confirm.reload_system": "Reload the authoritative System before rolling back.",
  "flow.versions.rollback_unknown": "Rollback outcome is unknown. Reloading the authoritative Flow.",
  "flow.versions.rollback_verification": "Rollback verification",
  "flow.versions.rollback_title": "Rollback",
  "flow.versions.restore.reload_draft": "Reload the authoritative server draft before restoring a version.",
  "flow.versions.restore.success_title": "Draft restored",
  "flow.versions.restore.unknown": "Restore outcome is unknown. Reloading the authoritative server draft.",
  "flow.versions.restore.verification": "Restore verification",
  "flow.versions.diff.server_unavailable": "authoritative semantic diff unavailable",
  "flow.versions.rollback_message": "rollback to v{version}",
  "flow.versions.rollback_success": "Rolled back to v{version} (new v{newVersion}).",
  "flow.versions.restore.success": "v{version} restored to the server draft. Published Flow unchanged.",
  "flow.versions.diff.counts_match": "counts match · preview for semantic diff",
  "flow.versions.diff.counts": "{counts} counts · preview for semantic diff",
  "flow.versions.graph_counts": "{nodes} nodes · {edges} edges",
  "flow.versions.diff.breaking": "{count} breaking",
  "flow.versions.diff.behavioral": "{count} behavioral",
  "flow.versions.diff.presentation": "{count} presentation",
  "flow.versions.diff.node_order": "↕n order",
  "flow.versions.diff.edge_order": "↕e order",
  "flow.versions.diff.contract": "~contract",
  "flow.versions.diff.server_equal": "= draft (server verified)",
  "flow.versions.diff.flow": "~flow",
  "flow.versions.diff.pinned_contract": "pinned contract · not comparable to draft",
  "flow.versions.diff.unavailable_contract": "contract unavailable · not comparable to draft",
  "flow.versions.diff.canvas_equal": "= canvas",

  // ---- shell -------------------------------------------------------------
  'flow.builder.crumb.systems': 'Systems',
  'flow.builder.crumb.here': 'Flow builder',
  'flow.builder.crumb.scratchpad': 'Scratchpad Flow',
  'flow.builder.title': 'Flow builder',
  'flow.builder.boundary.draft': 'Server draft r{revision}',
  'flow.builder.boundary.detail':
    'Test draft runs this saved revision. The operator runner and the entry point keep serving Published v{version} until you publish explicitly.',
  'flow.builder.boundary.contract':
    'Publication required: the migration baseline stays non-executable until this draft is published.',
  'flow.builder.runtime.details': 'Runtime details',
  'flow.builder.runtime.surface': 'Execution surface',
  'flow.builder.runtime.mode': 'Execution mode',
  'flow.builder.autosave.paused': 'Autosave paused.',
  'flow.builder.autosave.paused.body':
    'This bulk or destructive replacement stays local until you save it explicitly.',
  'flow.builder.autosave.reload': 'Reload the server Flow',
  'flow.builder.autosave.review': 'Review & save',
  'flow.builder.autosave.discard': 'Discard local changes',
  'flow.builder.autosave.hold': 'Autosave on hold',
  'flow.builder.autosave.hold.hint':
    'The workbench is open, so nothing is saved automatically. Close it, or save explicitly.',
  'flow.builder.empty.title': 'Start your first Flow',
  'flow.builder.empty.body':
    'Three steps make a Flow: what starts it, the work (a skill, or an agent loop that chooses the next one), where the result goes.',
  'flow.builder.empty.step1': '1 · Trigger — what starts the Flow',
  'flow.builder.empty.step2': '2 · Skill or Agent loop — the work, or the envelope that chooses',
  'flow.builder.empty.step3': '3 · Output — where the result goes',
  'flow.builder.empty.cta': 'Add the first node',
  'flow.builder.handle.aria': 'Insert connected node',
  'flow.builder.handle.insert.target': 'Insert a target node',
  'flow.builder.handle.insert.source': 'Insert a source node',
  'flow.builder.handle.empty': 'No type-compatible node.',
  'flow.builder.handle.more': 'Search all {count} compatible…',
  'flow.builder.load.loading': 'Loading the saved Flow…',
  'flow.builder.load.loading.body':
    'Editing and running stay locked until loading completes.',
  'flow.builder.load.error': 'Flow loading blocked',
  'flow.builder.load.retry': 'Retry a strict reload',
  'flow.builder.error.malformed': 'The saved Flow is malformed.',
  'flow.builder.error.rollback': 'The rollback returned a malformed Flow.',
  'flow.builder.error.generic':
    'The System could not be loaded. No fallback graph was opened, so the saved Flow cannot be overwritten by accident.',
  'flow.builder.clear.title': 'Clear this Flow?',
  'flow.builder.clear.description':
    'This removes {nodes} nodes and {edges} edges locally. Autosave pauses; the saved Flow is unchanged until you save explicitly.',
  'flow.builder.clear.confirm': 'Clear and pause autosave',
  'flow.builder.clear.cancel': 'Keep the Flow',
  'flow.builder.replace.title': 'Replace the active Flow?',
  'flow.builder.replace.description':
    'This replacement changes the execution graph of an active System. It is sent once, with explicit replacement authority; autosave stays paused.',
  'flow.builder.replace.confirm': 'Replace the active Flow',
  'flow.builder.replace.cancel': 'Keep reviewing',
  'flow.builder.view.aria': 'Flow view mode',
  'flow.builder.view.canvas': 'Canvas',
  'flow.builder.view.outline': 'Accessible outline',

  // ---- accessible outline ----------------------------------------------
  'flow.outline.title': 'Flow outline',
  'flow.outline.help':
    'Select a step to inspect it. Use Up/Down to navigate and Alt + Up/Down to change its order. Positions and connections can be edited with the keyboard below.',
  'flow.outline.count': 'Steps: {count}',
  'flow.outline.nodes': 'Steps in order',
  'flow.outline.inspect': 'Select and inspect {name}',
  'flow.outline.routes': 'Incoming {incoming} · outgoing {outgoing}',
  'flow.outline.move': 'Order and canvas position',
  'flow.outline.move.aria': 'Move {name}',
  'flow.outline.order.before': 'Move {name} one row earlier',
  'flow.outline.order.after': 'Move {name} one row later',
  'flow.outline.order.before.short': 'Earlier',
  'flow.outline.order.after.short': 'Later',
  'flow.outline.position.x': 'X position',
  'flow.outline.position.y': 'Y position',
  'flow.outline.empty': 'No steps. Add one from the palette.',
  'flow.outline.connections': 'Connections',
  'flow.outline.connect': 'Create a connection',
  'flow.outline.connect.source': 'From output',
  'flow.outline.connect.source.placeholder': 'Choose an output…',
  'flow.outline.connect.target': 'To input',
  'flow.outline.connect.target.placeholder': 'Choose a compatible input…',
  'flow.outline.connect.no_target': 'No compatible input is available.',
  'flow.outline.connect.duplicate': 'This connection already exists.',
  'flow.outline.connect.action': 'Create connection',
  'flow.outline.connections.current': 'Current connections',
  'flow.outline.disconnect': 'Remove connection {edge}',
  'flow.outline.disconnect.short': 'Remove',
  'flow.outline.connections.empty': 'No connections.',
  'flow.outline.connector.option': '{node} · port {port}',
  'flow.outline.port.default': 'default',
  'flow.outline.edge.label':
    '{source}, port {sourcePort}, to {target}, port {targetPort}',
  'flow.outline.announcement.reordered': '{name} was reordered.',
  'flow.outline.announcement.moved': '{name} position was changed.',
  'flow.outline.announcement.connected': 'Connection created: {edge}.',
  'flow.outline.announcement.disconnected': 'Connection removed: {edge}.',

  // ---- execution mode & runtime status -----------------------------------
  'flow.runtime.mode.dag_strict': 'Runs as a graph',
  'flow.runtime.mode.dag_overlay': 'Compatibility mode',
  'flow.runtime.mode.sequential_legacy': 'Runs step by step',
  'flow.runtime.mode.chat': 'Runs in chat',
  'flow.runtime.mode.unknown': 'Execution mode unknown',
  'flow.runtime.surface.draft': 'Draft test-run',
  'flow.runtime.surface.published': 'Published run',

  // ---- toolbar -----------------------------------------------------------
  'flow.toolbar.aria': 'Flow tools',
  'flow.toolbar.nodes': '{count} nodes',
  'flow.toolbar.state.saving': 'Saving…',
  'flow.toolbar.state.hold': 'Autosave paused',
  'flow.toolbar.state.unsaved': 'Unsaved',
  'flow.toolbar.state.error': 'Save failed',
  'flow.toolbar.state.saved': 'Saved',
  'flow.toolbar.state.title.review':
    'Review required — autosave is paused until you explicitly save or discard this replacement.',
  'flow.toolbar.state.title.paused':
    'Autosave paused — review these changes, then press Save.',
  'flow.toolbar.state.title.saving': 'Saving…',
  'flow.toolbar.state.title.unsaved':
    'Unsaved changes — autosaves, or press Ctrl/Cmd+S.',
  'flow.toolbar.state.title.error': 'The last save failed — edit again to retry.',
  'flow.toolbar.state.title.saved': 'All changes saved.',
  'flow.toolbar.version.draft': 'Draft r{revision}',
  'flow.toolbar.version.published': 'Published v{version}',
  'flow.toolbar.version.fingerprint': 'Content fingerprint: {hash}',
  'flow.toolbar.palette.expand': 'Expand the node palette',
  'flow.toolbar.palette.collapse': 'Collapse the node palette',
  'flow.toolbar.palette.aria': 'Toggle node palette',
  'flow.toolbar.inspector.expand': 'Expand the node inspector',
  'flow.toolbar.inspector.collapse': 'Collapse the node inspector',
  'flow.toolbar.inspector.aria': 'Toggle node inspector',
  'flow.toolbar.undo': 'Undo (Ctrl/Cmd+Z)',
  'flow.toolbar.undo.aria': 'Undo',
  'flow.toolbar.redo': 'Redo (Ctrl/Cmd+Shift+Z)',
  'flow.toolbar.redo.aria': 'Redo',
  'flow.toolbar.zoom_in': 'Zoom in',
  'flow.toolbar.zoom_out': 'Zoom out',
  'flow.toolbar.fit': 'Fit',
  'flow.toolbar.fit.aria': 'Fit to view',
  'flow.toolbar.arrange': 'Arrange',
  'flow.toolbar.arrange.hint':
    'Auto-arrange — repositions all nodes (Ctrl/Cmd+Z to undo)',
  'flow.toolbar.arrange.aria': 'Auto-arrange all nodes',
  'flow.toolbar.validate': 'Validate',
  'flow.toolbar.validate.busy': 'Validating…',
  'flow.toolbar.validate.hint': 'Validate the current Flow revision on the server',
  'flow.toolbar.validate.hint.busy': 'Validating the current Flow revision…',
  'flow.toolbar.validate.aria': 'Validate current flow',
  'flow.toolbar.save': 'Save',
  'flow.toolbar.save.busy': 'Saving…',
  'flow.toolbar.save.aria': 'Save flow',
  'flow.toolbar.save.blocked': 'Fix the current server validation errors before saving',
  'flow.toolbar.save.system': 'Save the Flow to the System (Ctrl/Cmd+S)',
  'flow.toolbar.save.scratch': 'Save the scratchpad draft locally (Ctrl/Cmd+S)',
  'flow.toolbar.publish': 'Publish',
  'flow.toolbar.publish.hint':
    'Review the semantic diff and publish an immutable version (does not activate the System)',
  'flow.toolbar.publish.aria': 'Review and publish server draft',
  'flow.toolbar.promote': 'To System',
  'flow.toolbar.promote.busy': 'Saving…',
  'flow.toolbar.promote.hint': 'Save this scratchpad draft as a real System',
  'flow.toolbar.promote.aria': 'Save as System',
  'flow.toolbar.operate': 'Operate',
  'flow.toolbar.operate.hint': 'Run, debug, replay and test this Flow',
  'flow.toolbar.more': 'More',
  'flow.toolbar.more.hint': 'View options, import / export, share and clear',
  'flow.toolbar.more.aria': 'More actions',
  'flow.toolbar.workbench': 'Workbench',
  'flow.toolbar.workbench.hint':
    'Test the exact local Flow without saving or publishing it',
  'flow.toolbar.workbench.blocked':
    'Promote this scratchpad to a System before running previews',
  'flow.toolbar.workbench.aria': 'Toggle local Flow workbench',
  'flow.toolbar.focus': 'Focus',
  'flow.toolbar.focus.exit': 'Exit focus',
  'flow.toolbar.focus.hint': 'Focus canvas in fullscreen',
  'flow.toolbar.focus.exit.hint': 'Exit canvas focus / fullscreen',
  'flow.toolbar.focus.aria': 'Toggle canvas focus mode',
  'flow.toolbar.compact.expand': 'Expand toolbar labels',
  'flow.toolbar.compact.collapse': 'Compact toolbar',
  'flow.toolbar.compact.aria': 'Toggle compact toolbar',
  'flow.toolbar.routing': 'Routing: {mode}',
  'flow.toolbar.routing.aria': 'Cycle routing',
  'flow.toolbar.export': 'Export',
  'flow.toolbar.export.hint': 'Export flow as JSON',
  'flow.toolbar.export.aria': 'Export flow',
  'flow.toolbar.import': 'Import',
  'flow.toolbar.import.hint': 'Import flow JSON (round-trip)',
  'flow.toolbar.import.aria': 'Import flow',
  'flow.toolbar.share': 'Share',
  'flow.toolbar.share.hint': 'Copy a shareable link to this flow',
  'flow.toolbar.share.aria': 'Share flow',
  'flow.toolbar.clear': 'Clear canvas',
  'flow.toolbar.clear.aria': 'Clear canvas',

  // ---- node card ---------------------------------------------------------
  'flow.node.delete': 'Delete node {name}',
  'flow.node.delete.hint': 'Delete node {name} (Delete/Backspace)',
  'flow.node.run_step': 'Run this step: {name}',
  'flow.node.run_step.hint': 'Open the isolated preview for {name}',
  'flow.node.breakpoint.set': 'Set breakpoint',
  'flow.node.breakpoint.remove': 'Remove breakpoint',
  'flow.node.breakpoint.aria': 'Toggle breakpoint',
  'flow.node.configured': 'Configured',
  'flow.node.not_configured': 'Not configured yet',
  'flow.node.kind.source': 'TRIGGER',
  'flow.node.kind.sink': 'OUTPUT',
  'flow.node.kind.asset': 'DATA',
  'flow.node.kind.decision': 'DECISION',
  'flow.node.kind.fork': 'SPLIT',
  'flow.node.kind.join': 'MERGE',
  'flow.node.kind.loop': 'LOOP',
  'flow.node.kind.agent_loop': 'AGENT LOOP',
  'flow.node.agent_loop.empty_objective': 'Objective still empty — open the inspector',
  'flow.node.kind.retry': 'RETRY',
  'flow.node.kind.hitl': 'HUMAN GATE',
  'flow.node.kind.subflow': 'SUBFLOW',
  'flow.node.kind.skill': 'SKILL',
  'flow.node.kind.runtime': 'RUNTIME',
  'flow.node.run.rows_delta': '{from} → {to} rows',
  'flow.node.run.rows': '{rows} rows',
  'flow.node.run.predictions': '{count} prediction(s)',
  'flow.node.run.metric': '{metric} {value}',
  'flow.node.run.duration': '{duration}',
  'flow.node.run.model': 'Model that answered on this node',

  // ---- palette -----------------------------------------------------------
  'flow.palette.aria': 'Node palette',
  'flow.palette.heading.context': 'Connects here',
  'flow.palette.heading.matches': 'Matches',
  'flow.palette.heading.all': 'All skills',
  'flow.palette.heading.add': 'Add node',
  'flow.palette.heading.count': '{name} count',
  'flow.palette.context.connects': 'Connects to',
  'flow.palette.context.clear': 'Show all',
  'flow.palette.search': 'Search or describe a step…',
  'flow.palette.search.context': 'Search what connects here…',
  'flow.palette.search.results': '{count} compatible results.',
  'flow.palette.search.results.aria': 'Node search results',
  'flow.palette.catalog.loading': 'Loading the skill catalog…',
  'flow.palette.catalog.error': 'Skill catalog unavailable.',
  'flow.palette.catalog.retry': 'Retry',
  'flow.palette.empty.context': 'No type-compatible node.',
  'flow.palette.empty.query': 'Nothing available matches “{query}”.',
  'flow.palette.empty.show_all': 'Show every node',
  'flow.palette.overflow': '{count} more — refine the search to narrow it.',
  'flow.palette.unavailable.one':
    '1 registry skill matches but is not available in this workspace.',
  'flow.palette.unavailable.many':
    '{count} registry skills match but are not available in this workspace.',
  'flow.palette.unavailable.link': 'Adjust catalog visibility',
  'flow.palette.unavailable.toggle': '{count} in the registry, not available here',
  'flow.palette.back': 'Capabilities',
  'flow.palette.section.capabilities': 'Capabilities',
  'flow.palette.section.most_used': 'Used in this workspace',
  'flow.palette.section.structure': 'Structure',
  'flow.palette.section.empty.skills': 'No skill is available in this workspace.',
  'flow.palette.section.empty.capabilities':
    'No capability carries a skill in this workspace.',
  'flow.palette.advanced': 'Advanced — the whole registry',
  'flow.palette.row.in_flow': 'in flow',
  'flow.palette.row.in_flow.hint': 'Already used in this Flow',
  'flow.palette.row.usage': '{count} runs in this workspace',
  'flow.palette.row.runtime': 'Runtime status: {status}',

  // ---- validation strip --------------------------------------------------
  'flow.checklist.aria': 'Flow validation checklist',
  'flow.checklist.title': 'Checklist',
  'flow.checklist.checking': 'Checking the current revision…',
  'flow.checklist.server_error': 'Server validation unavailable',
  'flow.checklist.errors.one': '1 error',
  'flow.checklist.errors.many': '{count} errors',
  'flow.checklist.warnings.one': '1 warning',
  'flow.checklist.warnings.many': '{count} warnings',
  'flow.checklist.reveal': 'Reveal node {name}',
  'flow.checklist.server_tag': 'server',
  'flow.checklist.server_tag.hint': 'Authoritative for the current graph fingerprint',
  'flow.checklist.code.hint': 'Diagnostic code {code} — quote it to support.',

  // ---- diagnostic codes → what is missing, and what to do ----------------
  'flow.checklist.code.flow_invalid':
    'The saved Flow could not be read. Reload it, or restore an earlier version.',
  'flow.checklist.code.nodes_invalid':
    'The node list of this Flow cannot be read. Reload the Flow before editing it further.',
  'flow.checklist.code.node_invalid':
    'Node “{name}” is malformed: it is missing the identity or the kind the engine expects.',
  'flow.checklist.code.edges_invalid':
    'The connection list of this Flow cannot be read. Reload the Flow before editing it further.',
  'flow.checklist.code.edge_invalid':
    'One connection is malformed. Delete it on the canvas and draw it again.',
  'flow.checklist.code.node_id_duplicate':
    'Two nodes share the same identifier. Rename or delete one of them — every node needs its own.',
  'flow.checklist.code.edge_duplicate':
    'This connection already exists between the same two ports. Remove the duplicate.',
  'flow.checklist.code.dangling_edge':
    'A connection points at a node that no longer exists. Delete the connection, or add the missing node back.',
  'flow.checklist.code.cycle_detected':
    'The steps lead back onto themselves. Remove the connection that goes backwards, or use a Loop node for a controlled repetition.',
  'flow.checklist.code.unreachable_node':
    'Node “{name}” is never reached: nothing upstream leads to it. Connect it, or delete it.',
  'flow.checklist.code.node_orphan':
    'Node “{name}” has no connection at all. Connect it to the rest of the Flow, or delete it.',
  'flow.checklist.code.port_type_mismatch':
    'These two ports do not carry the same kind of value. Connect ports of the same type, or insert a step that converts it.',
  'flow.checklist.code.flow_output_sink_required':
    'This Flow has nowhere to deliver its result. Add one Output node.',
  'flow.checklist.code.flow_output_sink_ambiguous':
    'This Flow has several Output nodes. Keep exactly one, so the result has a single destination.',
  'flow.checklist.code.ingress_kind_invalid':
    'This entry point declares a way of starting the Flow does not support. Choose Manual, Chat, HTTP, Schedule or Internal event.',
  'flow.checklist.code.ingress_node_kind_invalid':
    'Only a Trigger node can hold an entry point. Move it onto the node that starts the Flow.',
  'flow.checklist.code.ingress_source_not_root':
    'An entry point cannot have anything upstream of it. Remove the connections arriving on it.',
  'flow.checklist.code.task_no_skill':
    'Step “{name}” has no Skill yet. Open it and pick the one that does the work.',
  'flow.checklist.code.task_runtime_ref_invalid':
    'This step names a Skill the platform cannot resolve. Pick one from the palette instead.',
  'flow.checklist.code.decision_no_branches':
    'Decision “{name}” has fewer than two branches. Add branches so there is a real choice to make.',
  'flow.checklist.code.decision_branch_invalid':
    'One branch of this Decision has no usable name. Give every branch a short name, with no leading or trailing space.',
  'flow.checklist.code.decision_condition_invalid':
    'A branch condition cannot be read. Open the Decision and fix the condition it refuses.',
  'flow.checklist.code.decision_condition_unbound':
    'A branch condition reads a name nothing supplies. Bind it under Named inputs, or correct its spelling.',
  'flow.checklist.code.decision_branch_duplicate':
    'Two branches of this Decision share the same name. Rename one so the routes stay distinct.',
  'flow.checklist.code.decision_default_invalid':
    'The default branch names a branch that does not exist. Pick one of the branches listed on the Decision.',
  'flow.checklist.code.decision_branch_unwired':
    'One branch of this Decision leads nowhere. Draw its connection to the next step.',
  'flow.checklist.code.loop_no_budget':
    'Loop “{name}” has no maximum number of iterations. Set one so a run cannot spin forever.',
  'flow.checklist.code.agent_loop_no_budget':
    'Agent loop “{name}” has no maximum number of turns. Set one so choosing the next skill has to stop.',
  'flow.checklist.code.agent_loop_allowlist':
    'Agent loop “{name}” must list between 1 and 8 allowed skills. That list is the envelope: the model sees nothing else.',
  'flow.checklist.code.retry_no_target':
    'Retry “{name}” has no maximum number of attempts. Set one so a failure eventually stops.',
  'flow.checklist.code.hitl_no_prompt':
    'Approval step “{name}” asks nothing. Write the question the approver will read.',
  'flow.checklist.code.asset_no_collection':
    'This Data node names no knowledge collection. Open it and choose the collection to read.',
  'flow.checklist.code.asset_binding_mismatch':
    'This Data node and the step reading it name different collections. Align them on one collection.',
  'flow.checklist.code.retrieval_scope_node_invalid':
    'Only a search step can carry a search scope. Move the scope onto the search step, or remove it.',
  'flow.checklist.code.retrieval_collections_invalid':
    'The collections of this search step cannot be read. Select them again in the inspector.',
  'flow.checklist.code.retrieval_documents_invalid':
    'The documents of this search step cannot be read. Select them again, or leave the selection empty to read every document.',
  'flow.checklist.code.branch_edge_invalid':
    'This connection claims a branch its origin does not declare. Draw it again from the Decision branch it belongs to.',
  'flow.checklist.code.branch_label_invalid':
    'The parallel lanes of “{name}” do not match its declared branches. Give every lane a distinct name that exists on the node.',
  'flow.checklist.code.fork_fanout_invalid':
    'Split “{name}” has fewer than two outgoing lanes. A split needs at least two paths to be worth splitting.',
  'flow.checklist.code.data_source_invalid':
    'The data link of “{name}” is incomplete or invalid. Check the connector, the tables in scope and the linked steps.',
  'flow.checklist.code.fork_unjoined':
    'Split “{name}” never comes back together. Add a Merge node that every lane reaches.',
  'flow.checklist.code.join_fanin_invalid':
    'Merge “{name}” has fewer than two incoming lanes. Connect the lanes it is meant to bring back together.',
  'flow.checklist.code.join_strategy_invalid':
    'Merge “{name}” uses a way of merging the engine does not support. Choose one of the offered strategies.',
  'flow.checklist.code.join_without_matching_fork':
    'Merge “{name}” has no split upstream to recombine. Remove it, or add the split it belongs to.',
  'flow.checklist.code.variable_unresolved':
    'An input reads a value nothing upstream provides. Bind it to an upstream output in the inspector.',
  'flow.checklist.code.variable_contract_invalid':
    'An input or an output of this step does not respect the Flow contract. Open the step and correct the field it names.',

  // ---- runtime manifest strip -------------------------------------------
  'flow.manifest.aria': 'Runtime contract summary',
  'flow.manifest.title': 'Runtime contract',
  'flow.manifest.loading': 'Loading…',
  'flow.manifest.chip.units': 'Steps',
  'flow.manifest.chip.source': 'Origin',
  'flow.manifest.chip.config': 'Settings',
  'flow.manifest.chip.retrieval': 'Retrieval',
  'flow.manifest.units.value': '{live}/{total} live',
  'flow.manifest.units.title': '{total} step(s) · {live} live · {skills} carried by a skill',
  'flow.manifest.config.none': 'No effective setting resolved',
  'flow.manifest.config.keys': '{count} setting(s)',
  'flow.manifest.more': '… (+{count} more)',
  'flow.manifest.retrieval.none': 'none yet',
  'flow.manifest.retrieval.none_recorded': 'No document retrieval recorded for this System yet',
  'flow.manifest.retrieval.latest': 'Latest document retrieval',

  // ---- inspector ---------------------------------------------------------
  'flow.inspector.aria': 'Node inspector',
  'flow.inspector.empty.title': 'No node selected',
  'flow.inspector.empty.body':
    'Select a node on the canvas to inspect it. Or load the Trigger → Agent loop → Human gate → Output start.',
  'flow.inspector.close': 'Close (Esc)',
  'flow.inspector.close.aria': 'Close inspector',
  'flow.inspector.unsaved': 'Unsaved',
  'flow.inspector.unsaved.hint': 'Unsaved changes — use Save in the toolbar',
  'flow.inspector.section.identity': 'Identity',
  'flow.inspector.section.identity.hint': 'Technical references for this node',
  'flow.inspector.identity.id': 'ID',
  'flow.inspector.identity.type': 'Type',
  'flow.inspector.identity.kind': 'Kind',
  'flow.inspector.field.label': 'Label',
  'flow.inspector.field.label.placeholder': 'Node label',
  'flow.inspector.field.description': 'Description',
  'flow.inspector.field.description.placeholder': 'What this node does',
  'flow.inspector.section.ports': 'Inputs and outputs',
  'flow.inspector.section.decision': 'Decision branches',
  'flow.inspector.error_policy.title': 'On error',
  'flow.inspector.error_policy.label': 'Behaviour',
  'flow.inspector.error_policy.continue': 'Continue — the error flows downstream',
  'flow.inspector.error_policy.fail': 'Stop the run',
  'flow.inspector.error_policy.route': 'Route to the error gate',
  'flow.inspector.error_policy.route_hint':
    'Connect the “error” port to the error gate. Other outputs are pruned.',
  'flow.inspector.join.title': 'Source quorum',
  'flow.inspector.join.min_success': 'Minimum successful branches',
  'flow.inspector.join.hint':
    'Empty keeps the historical behaviour. A number fails the Join below that quorum.',
  'flow.inspector.section.agent_loop': 'Agent loop envelope',
  'flow.inspector.agent_loop.hint':
    'Softness = which skill to call next. Writes still go through approval. The model only sees the allowed list.',
  'flow.inspector.agent_loop.objective': 'Objective',
  'flow.inspector.agent_loop.objective.placeholder':
    'The result to reach, not the steps — e.g. reset the AD password under ITSD policy',
  'flow.inspector.agent_loop.done_when': 'Done when (one criterion per line)',
  'flow.inspector.agent_loop.done_when.placeholder': 'identity_verified\naudit_log_v1',
  'flow.inspector.agent_loop.allowlist': 'Skills the loop may call (1 to 8)',
  'flow.inspector.agent_loop.allowlist.placeholder': 'azure_llm_v1\naudit_log_v1',
  'flow.inspector.agent_loop.allowlist.count': '{count} / 8 skills in the envelope',
  'flow.inspector.agent_loop.turns': 'Max turns',
  'flow.inspector.agent_loop.confidence': 'Confidence floor',
  'flow.inspector.agent_loop.privilege': 'Privilege tier',
  'flow.inspector.agent_loop.privilege.recommend': 'Recommend only — no writes',
  'flow.inspector.agent_loop.privilege.act': 'Act (lab only)',
  'flow.inspector.agent_loop.privilege.act_with_approval': 'Act after approval',
  'flow.inspector.agent_loop.on_budget': 'When the budget is spent',
  'flow.inspector.agent_loop.on_budget.exit': 'Exit — no further writes',
  'flow.inspector.agent_loop.on_budget.ask_human': 'Ask a person',
  'flow.inspector.agent_loop.cost': 'Budget $ (optional)',
  'flow.inspector.agent_loop.deadline': 'Deadline in minutes (optional)',
  'flow.inspector.agent_loop.envelope':
    '{objective} · {turns} turns · {skills}/8 skills · {privilege}',
  'flow.inspector.agent_loop.apply_itsd': 'Fill from the password-reset overlay',
  'flow.inspector.agent_loop.load_starter':
    'Load Trigger → Agent loop → Human gate → Output',
  'flow.inspector.section.human_gate': 'Structured pause',
  'flow.inspector.human_gate.hint':
    'The loop stops here, then resumes on the same run. Never a restart.',
  'flow.inspector.human_gate.prompt': 'Question for the person',
  'flow.inspector.human_gate.prompt.placeholder': 'Approve this write?',
  'flow.inspector.human_gate.kind': 'Decision type',
  'flow.inspector.human_gate.kind.choice': 'Choice A / B',
  'flow.inspector.human_gate.kind.validate_draft': 'Validate a draft',
  'flow.inspector.human_gate.kind.missing_file': 'Provide a missing file',
  'flow.inspector.human_gate.kind.approve_write': 'Approve a write',
  'flow.inspector.decision.add': '+ Branch',
  'flow.inspector.decision.hint':
    'Conditions run top to bottom. The first match wins; the default branch is used only when nothing matches.',
  'flow.inspector.decision.routes': '{count} route(s)',
  'flow.inspector.decision.up': 'Move up',
  'flow.inspector.decision.up.aria': 'Move branch up',
  'flow.inspector.decision.down': 'Move down',
  'flow.inspector.decision.down.aria': 'Move branch down',
  'flow.inspector.decision.remove': 'Delete branch and its routes',
  'flow.inspector.decision.route_label': 'Branch name',
  'flow.inspector.decision.condition': 'Condition',
  'flow.inspector.decision.default': 'Default branch',
  'flow.inspector.decision.default.none': 'None — fail when nothing matches',
  'flow.inspector.decision.invalid_label': '(invalid label)',
  'flow.inspector.section.asset': 'Knowledge collection',
  'flow.inspector.asset.collection': 'Collection',
  'flow.inspector.asset.collection.none': '— Select a collection —',
  'flow.inspector.asset.slug': 'Collection identifier',
  'flow.inspector.asset.slug.placeholder': 'my-collection',
  'flow.inspector.asset.loading': 'Loading collections…',
  'flow.inspector.asset.error': 'Collections unavailable — enter one by hand.',
  'flow.inspector.asset.retry': 'Retry',
  'flow.inspector.asset.empty': 'No indexed collection — enter one by hand.',
  'flow.inspector.asset.workspace_scoped': 'Limited to this workspace',
  'flow.inspector.asset.open': 'Open the collection',
  'flow.inspector.asset.open_knowledge': 'Open Knowledge',
  'flow.inspector.section.retrieval': 'Search scope',
  'flow.inspector.retrieval.hint':
    'This scope belongs to this search node. It changes neither the workspace default nor another search node.',
  'flow.inspector.retrieval.collections': 'Collections',
  'flow.inspector.retrieval.collections.aria': 'Collections used by this Retrieval node',
  'flow.inspector.retrieval.slugs': 'Collection identifiers',
  'flow.inspector.retrieval.documents': 'Documents',
  'flow.inspector.retrieval.documents.aria': 'Documents used by this Retrieval node',
  'flow.inspector.retrieval.documents.loading':
    'Loading documents for the selected collections…',
  'flow.inspector.retrieval.documents.error': 'Some document catalogues are unavailable.',
  'flow.inspector.retrieval.documents.retry': 'Retry',
  'flow.inspector.retrieval.documents.stored': 'stored reference',
  'flow.inspector.retrieval.documents.all':
    'No document selected means all documents in the selected collections.',
  'flow.inspector.retrieval.documents.more':
    'More documents are available beyond the loaded pages.',
  'flow.inspector.retrieval.documents.load_more': 'Load next page',
  'flow.inspector.retrieval.documents.empty': 'No selectable document in this scope.',
  'flow.inspector.retrieval.no_scope':
    'No explicit scope: the workspace defaults apply at run time.',
  'flow.inspector.retrieval.error.documents':
    'Select at most 1000 documents for one Retrieval node.',
  'flow.inspector.retrieval.error.collections':
    'Select at most 32 collections for one Retrieval node.',
  'flow.inspector.section.entry': 'Entry point',
  'flow.inspector.section.output_contract': 'Output contract',
  'flow.inspector.output_contract.label': 'Published output schema',
  'flow.inspector.output_contract.hint.output':
    'Validated before the Run result becomes visible.',
  'flow.inspector.output_contract.hint.task':
    'Validated on every node output, so a malformed answer fails here rather than at the Decision reading it.',
  'flow.inspector.output_contract.fallback.output':
    'No schema declared — publication derives one from this node’s input ports and accepts any extra field.',
  'flow.inspector.output_contract.fallback.task':
    'No schema declared: when published, this step adopts the bound Skill’s output contract and keeps it as-is for this version.',
  'flow.inspector.section.trigger': 'Trigger',
  'flow.inspector.trigger.sftp': 'Open the SFTP deposit',
  'flow.inspector.section.mcp': 'MCP server',
  'flow.inspector.mcp.open': 'Open the MCP connector',
  'flow.inspector.mcp.server': 'Server {id}',
  'flow.inspector.mcp.credential': 'Credentials: {source}',
  'flow.inspector.mcp.disabled': 'MCP connector is off on this workspace',
  'flow.inspector.trigger.unavailable':
    'Trigger piloting becomes available once this Flow is saved into a System.',
  'flow.inspector.section.danger': 'Remove this node',
  'flow.inspector.danger.delete': 'Delete node',
  'flow.inspector.danger.delete.aria': 'Delete node',
  'flow.inspector.danger.delete.hint':
    'Delete this node and its connections (Delete/Backspace)',
  'flow.inspector.danger.body':
    'Deletes “{name}” and every connection attached to it. The Delete or Backspace key does the same on the selected node, and Ctrl/Cmd+Z brings it back.',

  // ---- entry point editor ------------------------------------------------
  'flow.entry.kind': 'How it starts',
  'flow.entry.kind.derived': 'Derived at publication',
  'flow.entry.kind.derived.value': 'Derived at publication — {name}',
  'flow.entry.kind.manual': 'Manual — Execute, or an API call',
  'flow.entry.kind.chat': 'Chat — the System conversation surface',
  'flow.entry.kind.http': 'HTTP — inbound webhook',
  'flow.entry.kind.schedule': 'Schedule — cron',
  'flow.entry.kind.event': 'Internal event — SFTP arrival, deposit promoted',
  'flow.entry.note.manual':
    'Runs start from Execute or from a run request. The payload is the Run input.',
  'flow.entry.note.chat': 'Runs start from a chat turn on this System.',
  'flow.entry.note.http':
    'Runs start on an inbound call. Register the webhook below before it can fire.',
  'flow.entry.note.schedule':
    'Runs start on a cron tick. Register the schedule below before it can fire.',
  'flow.entry.note.event': 'Runs start on an internal event emitted by the platform.',
  'flow.entry.event.unsaved':
    'Event delivery cannot be checked until this Flow is saved into a System.',
  'flow.entry.event.checking': 'Checking event delivery…',
  'flow.entry.event.unreadable': 'Event delivery could not be read for this System.',
  'flow.entry.event.off':
    'Event triggers are switched off for this workspace. Publishing is allowed, but no event will start a Run until an administrator enables them.',
  'flow.entry.event.dry_run':
    'Event triggers are enabled but in dry-run: a matching event is recorded without starting a Run. Switch to live below.',
  'flow.entry.event.live': 'Event triggers are live for this System.',
  'flow.entry.registration.http':
    'Declaring how it starts is not a registration. Create the webhook in the Triggers panel below, or under',
  'flow.entry.registration.schedule':
    'Declaring how it starts is not a registration. Create the schedule in the Triggers panel below, or under',
  'flow.entry.registration.link': 'Triggers',
  'flow.entry.schema.label': 'Entry payload schema',
  'flow.entry.schema.hint.manual':
    'Validated against every Run input before the Run is accepted — this is what the Run input dialog has to satisfy.',
  'flow.entry.schema.hint.other':
    'Validated against every incoming payload before the Run is accepted.',
  'flow.entry.schema.fallback':
    'No schema declared — publication derives one from this node’s output ports and accepts any extra field.',

  // ---- decision named inputs --------------------------------------------
  'flow.bindings.title': 'Named inputs',
  'flow.bindings.add': '+ Named input',
  'flow.bindings.hint':
    'Each name below is readable by the conditions above, exactly as spelled.',
  'flow.bindings.no_candidates':
    'Nothing upstream produces a value yet. Connect a node into this Decision before naming what it reads.',
  'flow.bindings.name.aria': 'Binding name',
  'flow.bindings.source.aria': 'Bound upstream output',
  'flow.bindings.source.none': '— pick an upstream output —',
  'flow.bindings.source.legacy': 'legacy path: {path}',
  'flow.bindings.source.missing': '{name} (missing)',
  'flow.bindings.remove': 'Remove this named input',
  'flow.bindings.reads': 'Your conditions read:',
  'flow.bindings.not_bound': 'no source',
  'flow.bindings.warning':
    'A name with no source reads as empty: an equality test then never matches, and a comparison errors the Run. Bind it above, or correct the spelling in the condition.',

  // ---- manifest fields ---------------------------------------------------
  'flow.params.title': 'Runtime parameters',
  'flow.params.variables': 'Input values',
  'flow.params.configured': 'Configured',
  'flow.params.not_configured': 'Not configured yet',
  'flow.params.configured.hint': 'Configured — this node drives a live surface',
  'flow.params.not_configured.hint': 'Not fully configured',
  'flow.params.skill': 'Skill',
  'flow.params.runtime': 'Technical reference',
  'flow.params.required': 'required',
  'flow.params.empty': 'This node has no editable runtime parameter in the contract.',
  'flow.params.no_unit':
    'No runtime contract unit matched this node — it is not yet wired to a live contract.',
  'flow.params.error.json': 'Invalid JSON — value not saved.',
  'flow.params.variable.none': '— no source —',
  'flow.params.variable.legacy': 'legacy: {path}',
  'flow.params.variable.incompatible': '{label} · {schema} — not a {expected}',
  'flow.params.variable.no_upstream':
    'Nothing upstream produces a value yet — connect a node into this one first.',
  'flow.params.variable.no_match':
    'No upstream output is a {expected}. Bind a compatible output, or read the value on a Decision as a named input.',
  'flow.params.variable.describe':
    'Bind input “{name}” ({schema}) to an upstream output.',
  'flow.params.variable.supplied':
    'Supplied at runtime by the source bound to “{name}”.',

  // ---- run controls ------------------------------------------------------
  'flow.run.aria': 'Run controls',
  'flow.run.simulate': 'Simulate',
  'flow.run.simulate.hint': 'Client-side dry run — no backend call',
  'flow.run.execute': 'Execute',
  'flow.run.execute.draft': 'Test draft',
  'flow.run.execute.automation': 'Run',
  'flow.run.execute.automation.hint':
    'Run the draft now — no template or publication required',
  'flow.run.execute.aria': 'Execute on backend',
  'flow.run.execute.running': 'Running…',
  'flow.run.execute.unavailable': 'Execute unavailable.',
  'flow.run.execute.hint':
    '{surface} — real skill invocations against the explicitly selected Flow authority',
  'flow.run.execute.hint.debug':
    'Run with the debugger attached — the walker pauses on steps / breakpoints',
  'flow.run.debug': 'Debug: {mode}',
  'flow.run.debug.aria': 'Cycle debug mode',
  'flow.run.debug.unavailable': 'Debug unavailable.',
  'flow.run.debug.unavailable.sequential':
    'Debug unavailable: step-by-step execution has no graph debugger.',
  'flow.run.debug.hint': 'Debug mode: {mode} — click to cycle',
  'flow.run.debug.breakpoints.toast':
    'Toggle breakpoints with the dot on each node (visible while debug mode is on).',
  'flow.run.debug.breakpoints.title': 'Debugger',
  'flow.run.replay': 'Replay',
  'flow.run.replay.hint': 'Replay this run’s checkpoints into the terminal',
  'flow.run.replay.aria': 'Replay run',
  'flow.run.versions': 'Versions',
  'flow.run.versions.hint': 'Open version history',
  'flow.run.versions.blocked':
    'Promote this draft to a System, or wait for loading to finish, to track versions',
  'flow.run.versions.toast':
    'Version history is tracked per System — promote this scratchpad first.',
  'flow.run.terminal': 'Show or hide the execution terminal',
  'flow.run.terminal.aria': 'Toggle terminal',
  'flow.run.input.title': 'Run input',
  'flow.run.input.close': 'Close the Run input editor',
  'flow.run.input.hint':
    'Enter the JSON object exposed to the Flow. Debug metadata is injected separately by the builder.',
  'flow.run.input.hint.automation':
    'The input is ready. Run it, or replace it. Publishing comes after.',
  'flow.automation.turn.title': 'Edit this automation',
  'flow.automation.turn.hint':
    'Describe the change. Publishing and approval stay outside this turn.',
  'flow.automation.turn.send': 'Send',
  'flow.automation.turn.sending': 'Reading the draft…',
  'flow.automation.turn.read': 'Read: {blocks}',
  'flow.automation.turn.verified': 'The saved draft matches the patch.',
  'flow.automation.turn.run': 'Run {status}',
  'flow.automation.turn.retrieve': 'Passage: {passage} — source {source}',
  'flow.automation.turn.retrieve.empty': 'No cited passage.',
  'flow.automation.turn.sealed': 'The SAP write stayed sealed.',
  'flow.automation.turn.called': 'The SAP write was called.',
  'flow.automation.turn.pause': 'Waiting for approval.',
  'flow.automation.turn.error': 'The turn stopped: {message}',
  'flow.automation.turn.stopped': 'The turn stopped.',
  'flow.automation.work.title': 'In Work',
  'flow.automation.work.unpublished': 'This automation appears in Work when it is published.',
  'flow.automation.work.objective': 'Objective: {text}',
  'flow.automation.work.objective.absent': 'No objective is stated.',
  'flow.automation.work.convention': 'Declared convention: {rate}',
  'flow.automation.work.convention.absent': 'No value convention is declared.',
  'flow.automation.work.contract': 'Value contract r{revision}, approved by {owner}: {rate}.',
  'flow.automation.work.target': 'Target: {target} {unit} ({indicator}), {start} → {end}. Source: {source}.',
  'flow.automation.work.gap.absent': 'No measured gap.',
  'flow.automation.work.gap.measured': 'Measured gap: {delta} {unit} ({value} for a target of {target}).',
  'flow.automation.work.gap.in_progress': 'Period in progress: {value} of {target} {unit} so far, until {end}.',
  'flow.automation.work.gap.not_started': 'The contract period starts on {start}.',
  'flow.automation.work.gap.not_comparable': 'No measured gap: the evidence for the period is incomplete.',
  'flow.automation.work.proof': 'Proof: run {run}',
  'flow.automation.work.proof.absent': 'No published run is the proof yet.',
  'flow.preparation.title': 'Preparation',
  'flow.preparation.ready': 'Ready',
  'flow.preparation.not_ready': 'Not ready',
  'flow.preparation.not_checked': 'Not checked',
  'flow.preparation.not_applicable': 'Not applicable',
  'flow.preparation.blocked': 'Blocked',
  'flow.preparation.model': 'Model',
  'flow.preparation.provider': 'Provider',
  'flow.preparation.source': 'Source',
  'flow.preparation.indexing': 'Indexing',
  'flow.preparation.rights': 'Rights',
  'flow.preparation.worker': 'Runner',
  'flow.review.title': 'Objection',
  'flow.review.intro': 'Is a result wrong? Raise an objection on the latest run, correct the Flow, then check that the next run applies the correction.',
  'flow.review.start': 'Raise an objection',
  'flow.review.continue': 'Resume',
  'flow.review.close': 'Collapse',
  'flow.review.note_placeholder': 'What is wrong with this result, and what it should have been.',
  'flow.review.save_hint': 'The objection applies to this automation’s latest run.',
  'flow.review.reread_hint': 'Correct the Flow, save it, then reread the draft.',
  'flow.review.later_label': 'Later run',
  'flow.review.step': 'Step {step} of 4 · {label}',
  'flow.review.done': 'Loop closed',
  'flow.review.steps.1': 'Objection',
  'flow.review.steps.2': 'Reread',
  'flow.review.steps.3': 'Correction',
  'flow.review.steps.4': 'Check',
  'flow.review.empty': 'No result on this automation.',
  'flow.review.note': 'What is wrong',
  'flow.review.save': 'Record the objection',
  'flow.review.reread': 'Reread the draft',
  'flow.review.read': 'Reread: {blocks}',
  'flow.review.confirm': 'Confirm the reread correction',
  'flow.review.compare': 'Compare',
  'flow.review.same': 'Same automation: the objection and the later run concern the same object.',
  'flow.review.later': 'Later run: {status}.',
  'flow.review.need_later': 'A later result of the same automation is still missing.',
  'flow.review.ran_correction': 'The later result ran the corrected draft.',
  'flow.review.other_draft': 'The later result ran another graph than the corrected draft.',
  'flow.review.error': 'The loop stopped.',
  'flow.review.refused.unchanged_draft': 'The draft is still the one the objected run used. Correct it, then reread it.',
  'flow.review.refused.stale_reread': 'The draft changed after the reread. Reread it before confirming.',
  'flow.review.refused.not_later': 'This run started before the objected one. Choose a later run.',
  'flow.dossiers.title': 'Dossiers',
  'flow.dossiers.empty': 'No versioned dossier.',
  'flow.dossiers.version': 'Version {version}',
  'flow.dossiers.proof': 'Proof present',
  'flow.dossiers.proof.absent': 'Proof absent',
  'flow.dossiers.waiting': 'Waiting for a person',
  'flow.chart.title': 'Frozen chart',
  'flow.chart.empty': 'No point.',
  'flow.chart.no_run': 'This point has no result.',
  'flow.chart.run': 'Result: {status}',
  'flow.proof.present': 'Same proof: present.',
  'flow.proof.absent': 'Same proof: absent.',
  'flow.proof.sealed': 'Write sealed, not called.',
  'flow.run.input.prefill': 'Prefilled from the entry point contract of',
  'flow.run.input.entry': 'Draft entry point',
  'flow.run.input.entry.choose': 'Select an entry point…',
  'flow.run.input.entry.authority': 'Request authority:',
  'flow.run.input.json': 'JSON object',
  'flow.run.input.json.automation': 'Input',
  'flow.run.input.cancel': 'Cancel',
  'flow.run.input.dispatching': 'Dispatching…',
  'flow.run.input.submit': 'Start the run',
  'flow.run.input.submit.draft': 'Start draft test-run',
  'flow.run.input.submit.automation': 'Run',
  'flow.run.input.submit.debug': 'Start debug run',
  'flow.run.execute.debug': 'Debug run',

  // ---- terminal ----------------------------------------------------------
  'flow.terminal.aria': 'Execution terminal',
  'flow.terminal.title': 'Execution terminal',
  'flow.terminal.lines': '{count} lines',
  'flow.terminal.clear': 'Clear log',
  'flow.terminal.collapse': 'Collapse terminal',
  'flow.terminal.status.idle': 'Idle',
  'flow.terminal.status.running': 'Running',
  'flow.terminal.status.paused': 'Paused',
  'flow.terminal.status.done': 'Done',
  'flow.terminal.status.error': 'Error',
  'flow.terminal.empty':
    'Simulate for a client-side dry run, or Execute to run on the backend and stream live output here.',
  'flow.terminal.approval.title': 'Human approval required',
  'flow.terminal.approval.paused': 'PAUSED',
  'flow.terminal.approval.prompt': 'An operator must approve this step to continue.',
  'flow.terminal.approval.node': 'Node',
  'flow.terminal.approval.ttl': 'Time left',
  'flow.terminal.approval.buffered': 'Buffered',
  'flow.terminal.approval.memory': 'Memory',
  'flow.terminal.approval.reject': 'Reject',
  'flow.terminal.approval.accept': 'Approve',
  'flow.terminal.debug.title': 'Debugger paused',
  'flow.terminal.debug.prompt': 'Paused after',
  'flow.terminal.debug.prompt.tail': '— inspect the context and advance.',
  'flow.terminal.debug.last_output': 'Last output',
  'flow.terminal.debug.context': 'Context snapshot',
  'flow.terminal.debug.stop': 'Stop',
  'flow.terminal.debug.continue': 'Continue',
  'flow.terminal.debug.step': 'Step',
  'flow.terminal.no_data': '— no data —',

  // ---- workbench ---------------------------------------------------------
  'flow.workbench.aria': 'Local Flow workbench',
  'flow.workbench.title': 'Try this Flow before saving it',
  'flow.workbench.status.dirty':
    'Runs your unsaved canvas exactly as it is. Nothing is saved or published — but the Skills are real and so are their side effects.',
  'flow.workbench.status.clean':
    'Runs the current canvas exactly as it is. Nothing is saved or published — but the Skills are real and so are their side effects.',
  'flow.workbench.detail.toggle': 'What this run touches',
  'flow.workbench.detail.graph': 'Graph',
  'flow.workbench.detail.graph.dirty':
    'The unsaved canvas, sent fingerprint-bound so the server refuses anything that drifted since dispatch.',
  'flow.workbench.detail.graph.clean':
    'The current canvas, sent fingerprint-bound so the server refuses anything that drifted since dispatch.',
  'flow.workbench.detail.saving': 'Saving',
  'flow.workbench.detail.saving.body':
    'Autosave stays paused for as long as this panel is open.',
  'flow.workbench.detail.publishing': 'Publishing',
  'flow.workbench.detail.publishing.body':
    'Never published. The published version and the entry point serving it do not move.',
  'flow.workbench.detail.effects': 'Side effects',
  'flow.workbench.detail.effects.body':
    'Real Skills run. Whatever they write, send or call outside {brand} happens for real.',
  'flow.workbench.detail.runtime': 'Runtime',
  'flow.workbench.consent':
    'I understand this preview invokes real Skills and may cause external side effects. Confirmation is valid only for the current Flow revision.',
  'flow.workbench.tab.chat': 'Chat',
  'flow.workbench.tab.node': 'Node',
  'flow.workbench.tab.golden': 'Golden set',
  'flow.workbench.tabs.aria': 'Workbench mode',
  'flow.workbench.close': 'Close local workbench',
  'flow.workbench.entry': 'Entry point',
  'flow.workbench.entry.choose': 'Choose one entry point…',
  'flow.workbench.chat.empty':
    'Test the exact graph in the canvas. The Flow is validated and fingerprint-bound, but it is not saved or published.',
  'flow.workbench.chat.context': 'Additional input_ref (JSON)',
  'flow.workbench.chat.message': 'Message',
  'flow.workbench.chat.send': 'Send preview',
  'flow.workbench.busy': 'Running…',
  'flow.workbench.node.target': 'Selected Skill node',
  'flow.workbench.node.none': 'Select one task node with an executable Skill binding.',
  'flow.workbench.node.input': 'Manual input_ref (JSON)',
  'flow.workbench.node.run': 'Run selected node',
  'flow.workbench.golden.cases': 'Golden cases (JSON · max 20)',
  'flow.workbench.golden.run': 'Run golden set',
  'flow.workbench.golden.busy': 'Running set…',
  'flow.workbench.golden.summary':
    '{completed}/{total} executions finished · checks: {passed} passed, {failed} failed · {unevaluated} not evaluated',
  'flow.workbench.golden.expected': 'Expected',
  'flow.workbench.golden.expected.none': 'No expected result: the answer will not be evaluated.',
  'flow.workbench.golden.actual': 'Actual output',
  'flow.workbench.golden.open_run': 'Open Run',
  'flow.workbench.golden.human': 'Awaiting human review',
  'flow.workbench.golden.paused': 'Execution paused',
  'flow.workbench.golden.stopped': 'Execution stopped · not evaluated',
  'flow.workbench.golden.passed': 'Check passed',
  'flow.workbench.golden.failed': 'Check failed',
  'flow.workbench.golden.unevaluated': 'Execution finished · not evaluated',
  'flow.workbench.golden.pending': 'Execution in progress',
  'flow.workbench.error.message': 'Enter a message before running the local preview.',
  'flow.workbench.error.object': 'Enter a JSON object.',
  'flow.workbench.error.json': 'Enter valid JSON.',
  'flow.workbench.error.array': 'Enter a valid JSON array.',
  'flow.workbench.error.golden_size': 'A golden set must contain between 1 and 20 cases.',
  'flow.workbench.error.golden_object': 'Golden case {index} must be an object.',
  'flow.workbench.error.golden_id':
    'Golden case ids must be unique, non-empty and trimmed.',
  'flow.workbench.error.golden_input': 'Golden case “{id}” needs an input_ref object.',
  'flow.workbench.error.node': 'Select a task node with an executable Skill binding.',
  'flow.workbench.error.no_entry': 'The current Flow has no executable entry point.',
  'flow.workbench.error.choose_entry':
    'Choose one of the {count} Flow entry points before running the workbench.',
  'flow.workbench.error.consent':
    'Confirm that this Workbench run invokes real Skills and may cause external side effects.',
  'flow.workbench.error.unserialisable': '[Unserialisable result]',
  'flow.workbench.error.entry_missing':
    'The selected entry point no longer exists in the current Flow.',
  'flow.workbench.error.entry_no_text':
    'The selected entry point has no text field. Add a query, message, prompt, text or input string to its input schema.',
  'flow.workbench.error.entry_rejects': 'The selected entry point does not accept: {keys}.',
  'flow.workbench.error.entry_requires':
    'The selected entry point also requires: {keys}. Add them to input_ref JSON.',
  'flow.workbench.error.entry_gone': 'The selected entry point no longer exists.',
  'flow.workbench.error.golden_ids':
    'Golden case ids must be unique, non-empty and trimmed.',
  'flow.workbench.error.busy': 'Wait for the current workbench run to finish.',
  'flow.workbench.error.no_system': 'The workbench is not attached to a loaded System.',
  'flow.workbench.error.context_changed':
    'The Flow or workspace changed while the preview was running. Run it again on the current snapshot.',
  'flow.workbench.error.diagnostics': 'The current Flow has blocking server diagnostics.',
  'flow.workbench.error.digest': 'The server did not return a valid canonical Flow digest.',
  'flow.workbench.error.runtime_unsupported':
    'The server returned an unsupported Flow execution mode.',
  'flow.workbench.error.runtime_legacy':
    'The workbench requires a graph runtime. Legacy sequential does not execute the edited graph topology.',
  'flow.workbench.error.golden_mismatch':
    'The golden batch response does not match the validated Flow and case set.',
  'flow.workbench.error.golden_identity':
    'A golden run is missing its server-owned case identity.',
  'flow.workbench.error.golden_duplicates':
    'The golden batch contains duplicate or missing case identities.',
  'flow.workbench.error.golden_diff':
    'Output did not match the expected deep-partial value.',
  'flow.workbench.error.run_status': 'Run stopped with status {status}.',
  'flow.workbench.error.evidence':
    'The Run evidence does not match the validated workbench request.',
  'flow.workbench.error.poll_identity': 'The polled Run identity changed unexpectedly.',
  'flow.workbench.error.timeout':
    '{label} did not finish within {minutes} minutes. Its durable Run may still be queued or running.',
  'flow.workbench.timeout.interactive': 'The workbench run',
  'flow.workbench.timeout.golden': 'The golden run',
  'flow.workbench.timeout.recipe': 'The recipe run',
  'flow.workbench.error.http': 'The workbench request failed (HTTP {status}).',
  'flow.workbench.error.failed': 'The workbench request failed.',

  // ---- contract schema editor (shared inspector / workshops) --------------
  'flow.schema.declared': 'Declared — this is what publication freezes.',
  'flow.schema.derive_from_ports': 'Derive from ports',
  'flow.schema.clear': 'Clear',

  // ---- Python recipe (node, inspector, authoring workshop) ----------------
  'flow.inspector.section.recipe': 'Python recipe',
  'flow.recipe.inspector.hint':
    'A Python script (main(inputs) → dict) executed in a managed Python environment, off the API process, with status tracking and cancellation.',
  'flow.recipe.inspector.open': 'Open the recipe workshop',
  'flow.recipe.inspector.open.aria': 'Open the Python recipe workshop',
  'flow.recipe.inspector.script': 'Script',
  'flow.recipe.inspector.timeout': 'Max duration',
  'flow.recipe.inspector.timeout.value': '{seconds} s',
  'flow.recipe.inspector.env': 'Environment',
  'flow.recipe.inspector.env.base': 'Base (no libraries)',
  'flow.recipe.workshop.title': 'Python recipe workshop',
  'flow.recipe.workshop.close': 'Close the recipe workshop',
  'flow.recipe.editor.label': 'Script',
  'flow.recipe.editor.contract': 'def main(inputs: dict) -> dict:',
  'flow.recipe.editor.lines': '{count} line(s)',
  'flow.recipe.editor.aria': 'Python recipe script',
  'flow.recipe.tabs.aria': 'Recipe panels',
  'flow.recipe.tab.env': 'Environment',
  'flow.recipe.tab.io': 'Inputs/Outputs',
  'flow.recipe.tab.test': 'Test',
  'flow.recipe.env.requirements': 'Libraries (one per line)',
  'flow.recipe.env.requirements.placeholder': 'e.g. pandas==2.2.3',
  'flow.recipe.env.import': 'Import requirements.txt',
  'flow.recipe.env.import.aria': 'Import a local requirements.txt file',
  'flow.recipe.env.packages': '{count} library(ies)',
  'flow.recipe.env.invalid_lines':
    'Rejected line (pip options are not allowed): {line}',
  'flow.recipe.env.registry': 'Registry (pip index)',
  'flow.recipe.env.registry.placeholder': 'default pip (PyPI)',
  'flow.recipe.env.extra_registries': 'Extra registries (one per line)',
  'flow.recipe.env.extra_registries.placeholder': 'None',
  'flow.recipe.env.timeout': 'Max duration (s)',
  'flow.recipe.env.state': 'Python environment',
  'flow.recipe.env.refresh': 'Refresh',
  'flow.recipe.env.disabled':
    'Recipe execution is switched off on this deployment — runs will fail until it is enabled.',
  'flow.recipe.env.stale':
    'The spec changed — refresh to resolve the new environment.',
  'flow.recipe.env.locked': 'locked versions',
  'flow.recipe.env.prepare': 'Prepare now',
  'flow.recipe.env.preparing': 'Preparing…',
  'flow.recipe.env.resolving': 'Resolving the environment…',
  'flow.recipe.env.status.pending': 'To build',
  'flow.recipe.env.status.building': 'Building',
  'flow.recipe.env.status.ready': 'Ready',
  'flow.recipe.env.status.failed': 'Failed',
  'flow.recipe.env.status.evicted': 'Evicted',
  'flow.recipe.execution.status.queued': 'Queued',
  'flow.recipe.execution.status.env_building': 'Preparing the environment',
  'flow.recipe.execution.status.running': 'Running',
  'flow.recipe.execution.status.succeeded': 'Succeeded',
  'flow.recipe.execution.status.failed': 'Failed',
  'flow.recipe.execution.status.cancelled': 'Cancelled',
  'flow.recipe.execution.status.timed_out': 'Timed out',
  'flow.recipe.reason.cancel_requested': 'Execution cancelled on request.',
  'flow.recipe.reason.env_not_found':
    'The Python environment no longer exists — run again to rebuild it.',
  'flow.recipe.reason.worker_lost':
    'The execution service was interrupted mid-run; the script was not replayed as a precaution.',
  'flow.recipe.reason.disabled': 'Recipe execution is switched off on this deployment.',
  'flow.recipe.reason.output_too_large': 'The output exceeds the maximum allowed size.',
  'flow.recipe.reason.output_not_object': 'main must return a dict (JSON object).',
  'flow.recipe.reason.output_unreadable': 'The output could not be read as JSON.',
  'flow.recipe.reason.timeout': 'Timed out after {seconds} s.',
  'flow.recipe.reason.env_build_failed': 'The environment build failed.',
  'flow.recipe.reason.exit': 'The script exited with code {code}.',
  'flow.recipe.reason.unknown': 'The execution failed.',
  'flow.recipe.io.hint':
    'The node contract: what the recipe receives in inputs, and the shape of the dict main returns.',
  'flow.recipe.io.input.label': 'Input schema',
  'flow.recipe.io.input.hint': 'What the recipe receives in inputs.',
  'flow.recipe.io.input.fallback': 'Without a schema, the recipe receives the upstream object as-is.',
  'flow.recipe.io.output.label': 'Output schema',
  'flow.recipe.io.output.hint': 'The shape of the dict main must return.',
  'flow.recipe.io.output.fallback': 'Without a schema, the output is published as-is.',
  'flow.recipe.test.no_system':
    'The isolated test requires a loaded System — it is not available on the scratchpad Flow.',
  'flow.recipe.test.input': 'Test input (JSON)',
  'flow.recipe.test.run': 'Run the recipe',
  'flow.recipe.test.busy': 'Running…',
  'flow.recipe.test.cancel': 'Cancel the run',
  'flow.recipe.test.cancel_requested':
    'Cancellation requested — the recipe stops at the next checkpoint.',
  'flow.recipe.test.output': 'Output',
  'flow.recipe.test.duration': 'Duration: {seconds} s',
  'flow.recipe.test.dispatching': 'Dispatching the test run…',

  'flow.inspector.section.transform': 'SQL transform',
  'flow.transform.inspector.hint':
    'The statement is graph-owned: it is versioned with the Flow and produces a new dataset on every run.',
  'flow.transform.inspector.open': 'Open the SQL workshop',
  'flow.transform.inspector.open.aria': 'Open the SQL transform workshop',
  'flow.transform.inspector.statement': 'Statement',
  'flow.transform.inspector.output': 'Output',
  'flow.transform.inspector.output.auto': 'Node name',
  'flow.transform.inspector.sources': 'Pinned inputs',
  'flow.transform.inspector.sources.none': 'None — upstream datasets are used',
  'flow.transform.inspector.sources.count': '{count} pinned',
  'flow.transform.workshop.title': 'SQL workshop',
  'flow.transform.workshop.close': 'Close the SQL workshop',
  'flow.transform.editor.label': 'Statement',
  'flow.transform.editor.engine': 'duckdb · read-only',
  'flow.transform.editor.lines': '{count} line(s)',
  'flow.transform.editor.aria': 'SQL statement of the transform',
  'flow.transform.editor.placeholder': 'SELECT * FROM input',
  'flow.transform.run': 'Test the statement',
  'flow.transform.run.busy': 'Running…',
  'flow.transform.run.shortcut': 'Ctrl + Enter',
  'flow.transform.tabs.aria': 'Transform panels',
  'flow.transform.tab.sources': 'Inputs',
  'flow.transform.tab.output': 'Output',

  'flow.transform.sources.hint':
    'Pin the datasets the statement queries. At run time, datasets arriving from upstream nodes are added automatically.',
  'flow.transform.sources.add': 'Pin a dataset',
  'flow.transform.sources.remove': 'Remove',
  'flow.transform.sources.empty':
    'No pinned input: pin a dataset to write and test the statement here.',
  'flow.transform.sources.loading': 'Loading datasets…',
  'flow.transform.sources.none_available':
    'No ready dataset in this workspace. Import one from the Data page.',
  'flow.transform.sources.rows': '{rows} rows · {columns} columns',
  'flow.transform.sources.alias': 'also: {aliases}',
  'flow.transform.sources.columns': 'Columns',
  // Engine-neutral: the button writes a select, a script or a dbt model.
  'flow.transform.sources.starter': 'Starter example',
  'flow.transform.sources.starter.aria': 'Write a starter example over {view}',
  'flow.transform.sources.insert.aria': 'Insert column {column} from {view} into the editor',
  'flow.transform.sources.catalog': 'Queryable tables',

  'flow.transform.output.name': 'Name of the produced dataset',
  'flow.transform.output.name.placeholder': 'e.g. enriched customers',
  'flow.transform.output.hint':
    'Every run writes a new version of this dataset, with its lineage back to the inputs.',
  'flow.transform.output.versioning':
    'Versioned: v1, v2, v3… The Data page shows the full history.',
  'flow.transform.output.open_data': 'Open the Data page',

  'flow.transform.result.title': 'Result',
  'flow.transform.result.empty':
    'Run the statement to see the rows, the schema and the column profile.',
  'flow.transform.result.caption': 'computed in {duration} ms',
  'flow.transform.result.truncated': 'Preview capped at {limit} rows',
  'flow.transform.result.no_rows': 'The statement returned no rows.',

  'flow.transform.error.SQL_EMPTY': 'Write a SELECT statement before running the test.',
  'flow.transform.error.SQL_TOO_LONG': 'The statement is too long to be executed.',
  'flow.transform.error.SQL_MULTIPLE_STATEMENTS':
    'One statement at a time: a transform produces one table.',
  'flow.transform.error.SQL_FORBIDDEN_KEYWORD':
    'Keyword refused: a transform reads its inputs and returns rows, it never modifies anything.',
  'flow.transform.error.SQL_NOT_READ_ONLY':
    'Only read-only statements are allowed (SELECT, WITH, FROM).',
  'flow.transform.error.SQL_FORBIDDEN_FUNCTION':
    'Function refused: query the declared inputs instead of reading files.',
  'flow.transform.error.SQL_EXECUTION_FAILED': 'The engine refused the statement.',
  'flow.transform.error.SQL_RESULT_TOO_LARGE':
    'The result exceeds the maximum size: filter or aggregate further.',
  'flow.transform.error.SQL_NO_COLUMNS': 'The statement returns no column.',
  'flow.transform.error.TRANSFORM_NO_INPUT':
    'Pin a dataset or connect an upstream node before running the transform.',
  'flow.transform.error.TRANSFORM_WORKSPACE_REQUIRED':
    'The transform must run in the context of a workspace.',
  'flow.transform.error.DATASET_NOT_FOUND': 'The referenced dataset no longer exists.',
  'flow.transform.error.DATASET_NOT_READY':
    'The dataset is still being prepared — try again in a moment.',
  'flow.transform.error.TABULAR_DISABLED': 'The data plane is disabled on this instance.',
  'flow.transform.error.unknown': 'The transform failed.',
  'flow.transform.error.at_line': 'Line {line}, column {column}',

  // ---- Polars workshop (polars_transform_v1 node) ------------------------
  // Same workshop, other language: only the engine-specific sentences change,
  // everything else is shared with the SQL block above.
  'flow.inspector.section.transform.polars': 'Polars transform',
  'flow.transform.polars.inspector.hint':
    'The script is graph-owned: it is versioned with the Flow and runs on a managed, isolated Python environment — never in the application process.',
  'flow.transform.polars.inspector.open': 'Open the Polars workshop',
  'flow.transform.polars.inspector.open.aria': 'Open the Polars transform workshop',
  'flow.transform.polars.inspector.script': 'Script',
  'flow.transform.polars.workshop.title': 'Polars workshop',
  'flow.transform.polars.workshop.close': 'Close the Polars workshop',
  'flow.transform.polars.editor.label': 'Script',
  'flow.transform.polars.editor.engine': 'polars · managed environment',
  'flow.transform.polars.editor.aria': 'Polars script of the transform',
  'flow.transform.polars.editor.placeholder':
    'def transform(inputs): return inputs["input"]',
  'flow.transform.polars.run': 'Test the script',
  'flow.transform.polars.sources.hint':
    'Pin the datasets the script receives. Every input is a DataFrame in the `inputs` dict; datasets arriving from upstream nodes are added automatically at run time.',
  'flow.transform.polars.result.empty':
    'Run the script to see the rows, the schema and the column profile it produces.',

  // phases of a queued test run (the worker owns the managed environment)
  'flow.transform.phase.queued': 'Queued…',
  'flow.transform.phase.env_building': 'Preparing the environment…',
  'flow.transform.phase.running': 'Running…',
  'flow.transform.run.cancel': 'Stop',
  'flow.transform.stdout': 'Script output',

  // environment
  'flow.transform.tab.environment': 'Libraries',
  'flow.transform.tab.environment.imposed': 'Environment',
  'flow.transform.environment.hint':
    'Declare the project’s extra libraries here: the environment is identified by its fingerprint, prepared on the first test run and reused afterwards.',
  'flow.transform.environment.imposed.hint':
    'The environment is imposed: the script runs on the pinned engine, with no extra libraries.',
  'flow.transform.environment.requirements': 'Libraries (one per line)',
  'flow.transform.environment.requirements.placeholder':
    'scikit-learn==1.5.0\nstatsmodels==0.14.2',
  'flow.transform.environment.count': '{count} declared library(ies)',
  'flow.transform.environment.timeout': 'Time budget (seconds)',

  // refusals specific to the Python engine
  'flow.transform.error.POLARS_CODE_REQUIRED':
    'Write a transform(inputs) function before running the test.',
  'flow.transform.error.POLARS_CODE_TOO_LARGE': 'The script exceeds the allowed size.',
  'flow.transform.error.POLARS_EXECUTION_DISABLED':
    'Python transforms are disabled on this instance: the managed environment plane is not enabled.',
  'flow.transform.error.POLARS_ENV_NOT_READY':
    'The Python environment of this transform could not be prepared.',
  'flow.transform.error.POLARS_SCRIPT_RAISED': 'The script raised an exception.',
  'flow.transform.error.POLARS_TRANSFORM_MISSING':
    'Define `def transform(inputs)`: it is the entry point the node calls.',
  'flow.transform.error.POLARS_RESULT_NOT_TABULAR':
    'transform() must return a polars DataFrame (a LazyFrame, a dict of columns or a list of rows also work).',
  'flow.transform.error.POLARS_RESULT_UNWRITABLE':
    'The result could not be written to the scratch disk.',
  'flow.transform.error.POLARS_RESULT_MISSING':
    'The script produced no table: return a DataFrame.',
  'flow.transform.error.POLARS_RESULT_TOO_LARGE':
    'The result exceeds the maximum size: filter or aggregate further.',
  'flow.transform.error.POLARS_HARNESS_ERROR':
    'The script run failed before reaching transform().',
  'flow.transform.error.POLARS_TIMEOUT':
    'The script exceeded its time budget and was stopped.',
  'flow.transform.error.POLARS_CANCELLED': 'Test run stopped at your request.',

  // ---- dbt workshop (dbt_transform_v1 node) ------------------------------
  // The only engine that can refuse its own result: the data tests declared in
  // schema.yml are a publication condition, not a report.
  'flow.inspector.section.transform.dbt': 'dbt transform',
  'flow.transform.dbt.inspector.hint':
    'The dbt project is carried by the graph: several models linked by ref(), inputs addressed through source(), and data tests that gate whether the dataset is published at all.',
  'flow.transform.dbt.inspector.open': 'Open the dbt workshop',
  'flow.transform.dbt.inspector.open.aria': 'Open the dbt transform workshop',
  'flow.transform.dbt.inspector.project': 'Published model',
  'flow.transform.dbt.workshop.title': 'dbt workshop',
  'flow.transform.dbt.workshop.close': 'Close the dbt workshop',
  'flow.transform.dbt.editor.label': 'Model',
  'flow.transform.dbt.editor.engine': 'dbt-duckdb · managed environment',
  'flow.transform.dbt.editor.aria': 'dbt model of the transform',
  'flow.transform.dbt.editor.placeholder': "select * from {{ ref('stg_input') }}",
  'flow.transform.dbt.run': 'Build the project',
  'flow.transform.dbt.sources.hint':
    "Pin the datasets the project reads. Each input is addressable as source('inputs', 'name'); upstream datasets are added automatically at run time.",
  'flow.transform.dbt.result.empty':
    'Build the project to see the rows of the published model, its schema and the test verdict.',

  // project file rail
  'flow.transform.files.aria': 'dbt project files',
  'flow.transform.files.add': 'New model',
  'flow.transform.files.remove': 'Delete',
  'flow.transform.files.publish': 'Publish',
  'flow.transform.files.publish.hint':
    'Make this model the dataset the node produces.',
  'flow.transform.files.published': 'published',
  'flow.transform.files.published.hint':
    'This is the model that becomes the versioned dataset on every run.',
  'flow.transform.files.materialize': 'Materialize',
  'flow.transform.files.materialize.hint':
    'Also version this model as a dataset on every run, beside the published model.',
  'flow.transform.files.materialize.off': 'Stop materializing',
  'flow.transform.files.materialized': 'dataset',
  'flow.transform.files.materialized.hint':
    'This model is also versioned as a dataset on every run.',
  'flow.transform.files.rename.aria': 'Relation name of the model',
  'flow.transform.files.tests.label': 'Tests',

  // build verdict
  'flow.transform.dbt.build.passed': '{models} model(s) built · {tests} test(s) passed',
  'flow.transform.dbt.build.refused': '{count} test(s) failed — nothing is published',
  'flow.transform.dbt.build.failures': '{count} row(s)',

  // dbt-specific refusals
  'flow.transform.error.DBT_MODELS_REQUIRED':
    'Write at least one model before building the project.',
  'flow.transform.error.DBT_MODEL_NAME_INVALID':
    'A model name is a relation name: lowercase, digits and “_”, starting with a letter.',
  'flow.transform.error.DBT_MODEL_NAME_DUPLICATE':
    'Two models share a name: dbt would not know which one ref() addresses.',
  'flow.transform.error.DBT_MODEL_EMPTY': 'This model is empty: write a select.',
  'flow.transform.error.DBT_MODEL_TOO_LARGE': 'This model exceeds the allowed size.',
  'flow.transform.error.DBT_MODEL_SHADOWS_SOURCE':
    'A model carries the name of an input: rename it so source() stays unambiguous.',
  'flow.transform.error.DBT_TOO_MANY_MODELS':
    'The project exceeds the number of models allowed on one node.',
  'flow.transform.error.DBT_TESTS_TOO_LARGE': 'The tests file exceeds the allowed size.',
  'flow.transform.error.DBT_OUTPUT_MODEL_MISSING':
    'The published model does not exist in the project.',
  'flow.transform.error.DBT_EXECUTION_DISABLED':
    'dbt transforms are disabled on this instance: the managed environment plane is not enabled.',
  'flow.transform.error.DBT_BUILD_FAILED': 'dbt refused to build the project.',
  'flow.transform.error.DBT_TESTS_FAILED':
    'Data tests failed: the node does not publish a result it knows to be wrong.',
  'flow.transform.error.DBT_RESULT_NO_COLUMNS':
    'The published model returns no column.',
  'flow.transform.error.DBT_RESULT_UNWRITABLE':
    'The result could not be written to the scratch disk.',
  'flow.transform.error.DBT_RESULT_MISSING':
    'The project produced no table: check the published model.',
  'flow.transform.error.DBT_RESULT_TOO_LARGE':
    'The result exceeds the maximum size: filter or aggregate further.',
  'flow.transform.error.DBT_HARNESS_ERROR':
    'The project run failed before dbt started.',
  'flow.transform.error.DBT_TIMEOUT':
    'The project exceeded its time budget and was stopped.',
  'flow.transform.error.DBT_CANCELLED': 'Build stopped at your request.',

  // ---- the model plane: train / predict / score nodes --------------------
  'flow.inspector.section.train': 'Model training',
  'flow.ml.train.inspector.hint':
    'The target, the features, the estimator and the split are graph-owned: an incoming payload cannot rewrite what this node learns.',
  'flow.ml.train.inspector.target': 'Target',
  'flow.ml.train.inspector.target.none': 'to be chosen',
  'flow.ml.train.inspector.dataset': 'Dataset',
  'flow.ml.train.inspector.dataset.wire': 'whatever arrives upstream',
  'flow.ml.train.inspector.output': 'Model produced',
  'flow.ml.train.inspector.output.auto': 'named after the target',
  'flow.ml.train.inspector.open': 'Open the training studio',
  'flow.ml.train.inspector.open.aria': 'Open the model training studio',

  // the training studio
  'flow.ml.train.title': 'Training studio',
  'flow.ml.train.close': 'Close the training studio',
  'flow.ml.train.run': 'Train',
  'flow.ml.train.busy': 'Training…',
  'flow.ml.train.cancel': 'Stop',
  'flow.ml.train.target': 'Column to predict',
  'flow.ml.train.target.hint':
    'Only columns a model can learn are offered, and their type decides the task.',
  'flow.ml.train.target.none': 'No column of this dataset can serve as a target.',
  'flow.ml.train.distinct': '{count} distinct values',
  'flow.ml.train.dataset.required': 'Pin a dataset to see its columns.',
  'flow.ml.train.task': 'Task',
  'flow.ml.train.task.suggested': 'Inferred from the target column’s type.',
  'flow.ml.train.features': 'Features',
  'flow.ml.train.features.count': '{selected} / {total}',
  'flow.ml.train.features.all': 'All',
  'flow.ml.train.features.hint':
    'Every column but the target, by default. A column unique per row is flagged: it would make the model memorise the table instead of generalising.',
  'flow.ml.train.algo': 'Estimator',
  'flow.ml.train.knobs': 'Settings',
  'flow.ml.train.knobs.reset': 'Defaults',
  'flow.ml.train.split': 'Test rows',
  'flow.ml.train.split.hint':
    'These rows take no part in the fit: they are the ones that produce the scores.',
  'flow.ml.train.cv': 'Cross-validation',
  'flow.ml.train.cv.off': 'Off',
  'flow.ml.train.cv.folds': '{folds} folds',
  'flow.ml.train.cv.hint':
    'Cross-validation gives a standard deviation per metric — slower, but a single score can be luck.',
  'flow.ml.train.evidence.empty':
    'Train once: the steps show up here, then the scores earned on the test rows.',
  'flow.ml.train.sample': 'The rows the fit will read',
  'flow.ml.train.registered': 'Registered: {name} v{version}',
  'flow.ml.train.open_card': 'Open the card',
  'flow.ml.train.tabs.aria': 'Training studio panels',
  'flow.ml.train.tab.dataset': 'Data',
  'flow.ml.train.tab.test': 'Test',
  'flow.ml.train.tab.output': 'Model',
  'flow.ml.train.dataset': 'Dataset',
  'flow.ml.train.dataset.hint':
    'Pinned by lineage: the node follows the latest ready version. Unpinned, it learns on the dataset handed to it upstream.',
  'flow.ml.train.dataset.loading': 'Loading…',
  'flow.ml.train.dataset.wire': 'Whatever arrives upstream',
  'flow.ml.train.dataset.meta': '{rows} rows · {columns} columns',
  'flow.ml.train.plan': 'What this fit would be',
  'flow.ml.train.plan.rows': '{rows} rows, {test} of them held out',
  'flow.ml.train.plan.features': '{count} features kept',
  'flow.ml.train.name': 'Model name',
  'flow.ml.train.name.hint':
    'The lineage name; every training run adds a version to it.',
  'flow.ml.train.name.placeholder': 'Derived from the target',
  'flow.ml.train.versioning':
    'A fit is never a dry run: the artifact IS the product, so every run registers a version in the registry.',
  'flow.ml.train.open_models': 'Open models',

  // serving nodes: a section, not a studio
  'flow.inspector.section.predict': 'Prediction',
  'flow.inspector.section.score': 'Dataset scoring',
  'flow.ml.predict.inspector.hint':
    'This node answers for one record, inside the run. Which model answers is graph-owned, never carried by the incoming payload.',
  'flow.ml.score.inspector.hint':
    'This node reads a dataset and writes a scored version of it, prediction columns included.',
  'flow.inspector.section.forecast': 'Series forecast',
  'flow.ml.forecast.inspector.hint':
    'Forecasts every series of the model over its horizon and writes a dataset: one row per series and step, with the interval. Downstream nodes also receive each series’ peak.',
  'flow.ml.forecast.empty':
    'No trained forecasting model in this workspace: train one (task “Forecasting”) before wiring this node.',
  'flow.ml.forecast.horizon': 'Horizon',
  'flow.ml.forecast.horizon.hint':
    'Left empty, the horizon and the level are the model’s. A dataset wired upstream is only read for the future values the model needs.',
  'flow.ml.forecast.level': 'Interval level',
  'flow.ml.forecast.level.model': 'The model’s',
  'flow.ml.serving.model': 'Model',
  'flow.ml.serving.model.none': 'No model chosen',
  'flow.ml.serving.version': 'Version',
  'flow.ml.serving.version.champion': 'Follow the champion',
  'flow.ml.serving.version.pinned': 'v{version} pinned',
  'flow.ml.serving.version.hint':
    'Following the champion answers with whichever version is promoted; pinning a version answers the same thing forever.',
  'flow.ml.serving.empty':
    'No trained model in this workspace: train one before wiring this node.',
  'flow.ml.serving.output': 'Dataset produced',
  'flow.ml.serving.output.auto': 'Derived from the model',
  'flow.ml.serving.output.produced': 'The rows written on the last run',
  'flow.ml.serving.output.open': 'Open the dataset',
  'flow.ml.serving.explain': 'Per-row contributions',
  'flow.ml.serving.explain.hint':
    'Adds the features that weighed most to the answer — useful for a summary downstream, slightly more expensive to compute.',

  // refusals the model nodes own (everything else speaks the Models
  // dictionary)
  'flow.ml.error.ml_no_dataset':
    'Wire a dataset upstream, or pin one on the node, before training.',
  'flow.ml.error.ml_score_dataset_required':
    'Wire a dataset upstream, or pin one on the node, before scoring.',
  'flow.ml.error.ml_model_required': 'Choose the model this node answers with.',
  'flow.ml.error.ml_target_in_features':
    'The target cannot be one of its own features.',
  'flow.ml.error.unknown': 'The request was refused without an actionable reason.',
  'flow.ml.run.cancelled': 'Training stopped at your request.',

  'flow.validation.error.server': 'The current Flow could not be validated by the server.',
  'flow.run.input.error.json':
    'Enter valid JSON.',
  'flow.run.input.error.object':
    'Run input must be a JSON object.',
  'flow.run.input.error.debug_reserved':
    '“_debug” is reserved for the debugger controls.',
  'flow.run.entry.none':
    'This draft has no entry point. Add one before starting a test run.',
  'flow.run.entry.select':
    'Select the draft entry point before starting the test run.',
  'flow.run.entry.choose':
    'Choose one of the {count} draft entry points before starting the test run.',
  'flow.run.entry.required':
    'Choose a draft entry point before starting the test run.',
  'flow.run.log.already_running':
    'A Run is already executing.',
  'flow.run.log.sim_empty':
    'Add at least one node before simulating.',
  'flow.run.log.sim_start':
    'Client-side simulation — no server call.',
  'flow.run.log.sim_done':
    'Simulation finished (dry run).',
  'flow.run.log.debug_reserved':
    'Execute rejected — “_debug” is reserved for the debugger controls.',
  'flow.run.log.dispatching':
    'Dispatching the run to the server…',
  'flow.run.log.no_hash':
    'Execute blocked — the saved Flow has no authoritative hash.',
  'flow.run.log.debugger_attached':
    'Debugger attached · mode={mode} · breakpoints={count}',
  'flow.run.log.trigger_rejected':
    'The server rejected the trigger request.',
  'flow.run.log.scheduled':
    'Run {id}… scheduled (status={status}).',
  'flow.run.log.approval_accepted':
    'Operator approved the pending step.',
  'flow.run.log.approval_declined':
    'Operator rejected the pending step.',
  'flow.run.log.approval_rejected':
    'Human approval resolve rejected by the server.',
  'flow.run.log.approval_network':
    'Network error during human approval resolve.',
  'flow.run.log.operator_action':
    'Operator → {action}',
  'flow.run.log.debug_rejected':
    'Debugger rejected by the server.',
  'flow.run.log.debug_network':
    'Network error during debug action.',
  'flow.run.log.replay_none':
    'No checkpoints to replay on this run.',
  'flow.run.log.replay_start':
    'Replaying {count} checkpoints from run {id}…',
  'flow.run.log.replay_done':
    'Replay done.',
  'flow.run.log.validation_blocked':
    'Blocked — {count} validation error(s). Fix before running:',
  'flow.run.log.stream_interrupted':
    'Live stream interrupted — falling back to polling.',
  'flow.run.log.connection_lost':
    'Lost connection to the server (stream + poll).',
  'flow.run.log.poll_lost':
    'Lost connection while polling the run.',
  'flow.run.log.failed':
    'Run failed',
  'flow.run.log.failed_detail':
    'Run failed · {detail}',
  'flow.run.log.no_output':
    'Run completed with no output payload.',
  'flow.run.log.walker_booted':
    'Walker booted — executing the graph.',
  'flow.run.log.decision_matched':
    'Decision {node} · matched{branch}',
  'flow.run.log.decision_default':
    'Decision {node} · default{branch}',
  'flow.run.log.decision_no_match':
    'Decision {node} · no matching branch',
  'flow.run.log.decision_unroutable':
    'Decision {node} · unroutable{branch}',
  'flow.run.log.decision_error':
    'Decision {node} · evaluation error',
  'flow.run.log.finished':
    'Run finished · status={status}',
  'flow.run.log.draft_changed':
    'The server draft changed before the test run was created. Reload it before continuing.',
  'flow.run.blocked.scratchpad':
    'A scratchpad cannot Execute — promote it to a System first.',
  'flow.run.blocked.hydration':
    'Execute is locked until the persisted Flow is strictly hydrated.',
  'flow.run.blocked.saving':
    'Execute is locked while the Flow is saving or changing version.',
  'flow.run.blocked.save_failed':
    'Execute is locked because the last save failed.',
  'flow.run.blocked.unsaved':
    'Save the current Flow before Execute.',
  'flow.run.blocked.no_hash':
    'Execute is locked because the saved Flow has no authoritative hash.',
  'flow.run.blocked.server_changed':
    'The Flow changed on the server. Reload the authoritative Flow before Execute.',
  'flow.run.blocked.validation_failed':
    'Execute is locked because the current Flow could not be validated by the server.',
  'flow.run.blocked.validation_pending':
    'Execute is locked until the current Flow is validated by the server.',
  'flow.run.blocked.validation_refreshing':
    'Execute is locked while server validation refreshes to the saved Flow hash.',
  'flow.run.blocked.server_errors':
    'Execute is locked by current server validation errors.',
  'flow.run.blocked.local_errors':
    'Execute is locked by Flow validation errors.',
  'flow.run.blocked.breakpoints':
    'Breakpoint debugging requires at least one selected node.',
  'flow.run.blocked.revision_missing':
    'Execute is locked because the server draft revision is missing.',
  'flow.run.blocked.draft_mode_unknown':
    'Execute is locked because the draft execution mode is unknown.',
  'flow.run.blocked.contract_loading':
    'Execute is locked until the runtime contract is loaded for this System.',
  'flow.run.blocked.contract_no_hash':
    'Execute is locked because the runtime contract has no Flow hash.',
  'flow.run.blocked.contract_refreshing':
    'Execute is locked while the runtime contract refreshes to the saved Flow.',
  'flow.run.blocked.server_mode_unknown':
    'Execute is locked because the server execution mode is unknown.',
  'flow.run.error.network':
    'Network error while triggering the run.',
  'flow.run.error.denied':
    'Execute denied — you do not have permission to run this System.',
  'flow.run.error.flow_changed':
    'Execute rejected — the saved Flow changed. Reload before retrying.',
  'flow.run.error.invalid_input':
    'Execute rejected — the Run input or debug configuration is invalid.',
  'flow.run.error.http':
    'Execute rejected by the server (HTTP {status}).',

  // ---- publication -------------------------------------------------------
  'flow.publish.eyebrow': 'Draft → Published',
  'flow.publish.title': 'Review publication',
  'flow.publish.subtitle':
    'Creates an immutable version. It never activates or resumes the System.',
  'flow.publish.close': 'Close publication review',
  'flow.publish.diff.loading': 'Loading the semantic diff…',
  'flow.publish.diff.error': 'Publication diff unavailable.',
  'flow.publish.diff.aria': 'Semantic diff summary',
  'flow.publish.diff.changes.aria': 'Semantic changes',
  'flow.publish.diff.breaking': '{count} breaking',
  'flow.publish.diff.behavioral': '{count} behavioral',
  'flow.publish.diff.presentation': '{count} presentation',
  'flow.publish.diff.empty': 'No semantic change detected.',
  'flow.publish.ack':
    'I reviewed the breaking changes and explicitly accept their release impact.',
  'flow.publish.message': 'Release message',
  'flow.publish.message.placeholder':
    'What changed, why, and what operators should know',
  'flow.publish.cancel': 'Cancel',
  'flow.publish.submit': 'Publish immutable version',
  'flow.publish.submitting': 'Publishing…',

  // ---- versions ----------------------------------------------------------
  'flow.versions.title': 'Flow history',
  'flow.versions.subtitle': 'Append-only · restore any version',
  'flow.versions.total': '{count} versions',
  'flow.versions.refresh': 'Refresh',
  'flow.versions.refresh.aria': 'Refresh versions',
  'flow.versions.loading': 'Loading…',
  'flow.versions.empty': 'No history yet. The first save on this System seeds v1.',
  'flow.versions.tag.published': 'Published',
  'flow.versions.tag.current': 'Current',
  'flow.versions.tag.rollback': 'Rollback',
  'flow.versions.preview': 'Preview',
  'flow.versions.preview.retry': 'Retry preview',
  'flow.versions.preview.hint': 'Load and show semantic diff',
  'flow.versions.restore': 'Restore this version',
  'flow.versions.load_more': 'Load older versions',
  'flow.versions.confirm.aria': 'Confirm rollback',
  'flow.versions.confirm.published':
    'Restore v{version} into the server draft and replace the canvas. The published pointer and System status stay unchanged.',
  'flow.versions.confirm.draft':
    'Create a new version that copies v{version}’s graph and replaces the canvas. History is append-only — nothing is deleted.',
  'flow.versions.confirm.loading':
    'Loading the exact immutable payload and authoritative semantic diff…',
  'flow.versions.confirm.retry': 'Retry exact preview',
  'flow.versions.confirm.ready': 'Exact preview ready · {diff}',
  'flow.versions.confirm.message.aria': 'Rollback message',
  'flow.versions.confirm.message.placeholder': 'rollback to v{version}',
  'flow.versions.confirm.cancel': 'Cancel',
  'flow.versions.confirm.submit': 'Restore draft',
  'flow.versions.confirm.submit.draft': 'Confirm',
  'flow.versions.confirm.pending': 'Rolling back…',

  // ---- triggers ----------------------------------------------------------
  'flow.triggers.schedules': 'Schedules (cron)',
  'flow.triggers.schedules.loading': 'Loading schedules…',
  'flow.triggers.schedules.error': 'Schedules unavailable.',
  'flow.triggers.schedules.empty': 'No schedule.',
  'flow.triggers.schedules.name': 'Name',
  'flow.triggers.schedules.cron': 'Cron (e.g. 0 * * * *)',
  'flow.triggers.schedules.create': 'Create',
  'flow.triggers.schedules.created': 'Schedule created.',
  'flow.triggers.schedules.create_failed': 'Creating the schedule failed.',
  'flow.triggers.schedules.update_failed': 'Updating the schedule failed.',
  'flow.triggers.webhooks': 'Webhooks',
  'flow.triggers.webhooks.loading': 'Loading webhooks…',
  'flow.triggers.webhooks.error': 'Webhooks unavailable.',
  'flow.triggers.webhooks.empty': 'No webhook.',
  'flow.triggers.webhooks.name': 'Webhook name',
  'flow.triggers.webhooks.create': 'Create a webhook',
  'flow.triggers.webhooks.created': 'Webhook created — copy the secret.',
  'flow.triggers.webhooks.create_failed': 'Creating the webhook failed.',
  'flow.triggers.webhooks.update_failed': 'Updating the webhook failed.',
  'flow.triggers.webhooks.secret': 'Secret (copy it now):',
  'flow.triggers.retry': 'Retry',
  'flow.triggers.on': 'ON',
  'flow.triggers.off': 'OFF',
  'flow.triggers.enable': 'Enable',
  'flow.triggers.disable': 'Disable',
  'flow.triggers.toast.title': 'Triggers',
  'flow.triggers.piloting': 'Trigger piloting',
  'flow.triggers.piloting.loading': 'Loading the state…',
  'flow.triggers.piloting.error': 'State unavailable.',
  'flow.triggers.piloting.global': 'Platform',
  'flow.triggers.piloting.global.on': 'Enabled',
  'flow.triggers.piloting.global.off': 'Disabled',
  'flow.triggers.piloting.mode': 'System mode',
  'flow.triggers.piloting.mode.live': 'Live',
  'flow.triggers.piloting.mode.dry': 'Dry-run',
  'flow.triggers.piloting.global.note':
    'Triggers are switched off platform-wide — the mode below only applies once they are enabled.',
  'flow.triggers.piloting.to_dry': 'Back to dry-run',
  'flow.triggers.piloting.to_live': 'Switch to live',
  'flow.triggers.piloting.live_done': 'Live mode enabled.',
  'flow.triggers.piloting.dry_done': 'Dry-run mode restored.',
  'flow.triggers.piloting.breaker.open': 'Circuit open — trigger disarmed',
  'flow.triggers.piloting.breaker.cause': 'Cause: {reason}',
  'flow.triggers.piloting.breaker.rearm': 'Re-arm',
  'flow.triggers.piloting.breaker.rearmed': 'Trigger re-armed.',
  'flow.triggers.piloting.breaker.armed': 'Circuit armed',
  'flow.triggers.piloting.runs': 'See the triggered runs',
  'flow.triggers.piloting.failed': 'Updating the trigger failed.',

  // --- palette · structural primitive descriptions (P3) -------------------
  // Key built at render time from the entry `type`
  // (`flow.palette.desc.<type>`), falling back to the raw description:
  // backend catalog skills (type 'skill') are data and are never mapped
  // here. See flow-palette.component.ts.
  'flow.palette.desc.source': 'Flow input / objective',
  'flow.palette.desc.source.collection': 'Knowledge collection as a data source',
  'flow.palette.desc.source.sftp_arrival':
    'File-arrival trigger (staging close / reconciliation)',
  'flow.palette.desc.source.deposit_promoted':
    'Trigger when an operator promotes deposit files to a collection',
  'flow.palette.desc.source.schedule': 'Cron-driven trigger (managed in Triggers panel)',
  'flow.palette.desc.source.webhook': 'HMAC inbound webhook trigger',
  'flow.palette.desc.task.role_agent':
    'One role, one instruction and a strict JSON output contract',
  'flow.palette.desc.decision': 'Branch on a condition',
  'flow.palette.desc.fork': 'Fan out parallel branches',
  'flow.palette.desc.join': 'Fan in parallel branches',
  'flow.palette.desc.loop': 'Repeat until a budget or condition',
  'flow.palette.desc.agent_loop':
    'Bounded loop: chooses the next allowed skill until the objective',
  'flow.palette.desc.hitl': 'Pause for a human decision, then resume',
  'flow.palette.label.agent_loop': 'Agent loop',
  'flow.palette.label.task.role_agent': 'Role agent',
  'flow.palette.label.hitl': 'Human gate',
  'flow.palette.desc.sink': 'Where the Flow delivers its result',
  // Palette sentinel group: skills visible without a carrying Capability
  // (name/hint built by the VM, translated at render via the sentinel slug).
  'flow.palette.uncarried.name': 'No capability',
  'flow.palette.uncarried.hint': 'Visible here without a capability carrying them',
  'flow.promote.title': 'Create the System',
  'flow.promote.lead': 'This free draft becomes a System. The objective is optional.',
  'flow.promote.name': 'Name',
  'flow.promote.objective': 'Objective (optional)',
  'flow.promote.submit': 'Create the System',
  'flow.promote.toast_title': 'Promotion',
  'flow.promote.success': 'Promoted to System “{name}”.',
  'flow.promote.error.name_required': 'A name is required.',
  'flow.promote.error.failed': 'The System could not be created. Your local draft was kept.',
  'flow.promote.error.verify': 'The System was created, but its Flow could not be verified. Review it before retrying.',
  'flow.promote.error.race': 'The System was created from an earlier revision. Newer local edits remain in this draft.',
};
