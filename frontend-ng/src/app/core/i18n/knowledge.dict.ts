/**
 * Knowledge base — collections browser, upload and counters chrome.
 * (Knowledge *capture* — Le Fil — lives in `capture.dict.ts`.)
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const KNOWLEDGE_FR = {
  'knowledge.title': 'Connaissances',

  // --- Object header ------------------------------------------------
  // Eyebrow rendered uppercase by the header's CSS; natural case here.
  'knowledge.header.eyebrow': 'Créer · Knowledge',
  'knowledge.header.subtitle': 'Ingérez des documents et donnez à chaque système un contexte à jour.',
  'knowledge.header.capture': 'Capture',
  'knowledge.header.upload': 'Téléverser',

  // --- KPI strip (labels rendered uppercase by CSS; hints are tooltips)
  'knowledge.kpi.collections': 'Collections',
  'knowledge.kpi.collections_hint': 'Nombre total de collections dans ce workspace.',
  'knowledge.kpi.documents': 'Documents',
  'knowledge.kpi.documents_hint': 'Nombre total de documents, toutes collections confondues.',
  'knowledge.kpi.chunks': 'Segments',
  'knowledge.kpi.chunks_hint': "Nombre total de segments — l'unité d'indexation.",
  'knowledge.kpi.vector_db': 'Base vectorielle',
  'knowledge.kpi.indexing': 'indexation…',
  'knowledge.kpi.ready': 'prête',

  // --- Dropzone -------------------------------------------------------
  'knowledge.dropzone.prefix': 'Déposez des fichiers ici ou',
  'knowledge.dropzone.browse': 'cliquez pour parcourir',
  'knowledge.dropzone.target': '→ cible :',
  'knowledge.dropzone.formats': 'PDF · TXT · MD · DOCX · CSV · JSON',
  'knowledge.upload.progress': 'Ingestion de {count} fichier(s)…',

  // --- Collections grid ------------------------------------------------
  'knowledge.collections.new': 'Nouvelle collection',
  'knowledge.collections.error.title': 'Impossible de charger les collections',
  'knowledge.collections.error.description':
    "Les collections n'ont pas pu être chargées. Réessayez avant de créer, supprimer ou téléverser des documents.",
  'knowledge.collections.empty.title': "Aucune collection pour l'instant",
  'knowledge.collections.empty.description':
    'Téléversez votre premier document ou créez une collection pour commencer.',
  'knowledge.collections.docs_count': '{count} docs',
  'knowledge.collections.chunks_count': '{count} segment(s)',
  'knowledge.collections.restricted': 'Restreinte',
  'knowledge.collections.indexed': 'Indexée',
  'knowledge.collections.indexing': 'Indexation…',
  'knowledge.collections.index_error': 'Erreur d’indexation',
  'knowledge.collections.not_indexed': 'Non indexée',
  'knowledge.collections.status_unknown': 'État inconnu',
  'knowledge.collections.open_detail': 'Ouvrir le détail de la collection',
  'knowledge.collections.browse': 'Parcourir les documents',
  'knowledge.collections.search_in': 'Rechercher dans cette collection',
  'knowledge.collections.delete': 'Supprimer la collection',
  'knowledge.collections.access.title': 'Accès',
  'knowledge.collections.access.manage': 'Gérer l’accès',
  'knowledge.collections.access.admins_note': 'Les administrateurs du workspace gardent toujours l’accès.',
  'knowledge.collections.access.read.legend': 'Qui peut lire',
  'knowledge.collections.access.write.legend': 'Qui peut ajouter des documents',
  'knowledge.collections.access.all_members': 'Tous les membres du workspace',
  'knowledge.collections.access.selected': 'Des rôles, groupes ou personnes choisis',
  'knowledge.collections.access.write.hint': 'Les lecteurs n’ajoutent jamais de documents, et il faut pouvoir lire la collection pour y en ajouter.',
  'knowledge.collections.access.admins_only': 'Personne n’est choisi : seuls les administrateurs y ont accès.',
  'knowledge.collections.access.roles': 'Rôles',
  'knowledge.collections.access.groups': 'Groupes',
  'knowledge.collections.access.people': 'Personnes',
  'knowledge.collections.access.loading_people': 'Chargement des membres…',
  'knowledge.collections.access.error.write_needs_read': 'Pour ajouter des documents, il faut aussi pouvoir lire la collection : {names}.',
  'knowledge.collections.access.saved': 'Accès à {name} mis à jour',
  'knowledge.collections.access.save_failed': 'L’accès n’a pas pu être enregistré. Réessayez.',
  'knowledge.collections.access.upload_denied': 'Vous ne pouvez pas ajouter de documents à cette collection',

  // --- Search drawer ---------------------------------------------------
  'knowledge.search.title': 'Rechercher dans les connaissances',
  'knowledge.search.all_collections': 'Toutes les collections',
  'knowledge.search.placeholder': 'Posez une question sémantique…',
  'knowledge.search.hybrid': 'Recherche hybride (sparse + vectorielle)',
  'knowledge.search.error.title': 'Recherche impossible',
  'knowledge.search.error.description':
    "La recherche a échoué. Réessayez avant d'utiliser les résultats.",
  'knowledge.search.empty.title': 'Aucun résultat',
  'knowledge.search.empty.description':
    'Essayez une autre requête ou désactivez la recherche hybride.',
  'knowledge.search.unknown_file': 'inconnu',

  // --- Browse drawer ---------------------------------------------------
  'knowledge.browse.title': 'Documents',
  'knowledge.browse.error.title': 'Impossible de charger les documents',
  'knowledge.browse.error.description':
    "Les documents n'ont pas pu être chargés. Réessayez avant de prévisualiser ou de supprimer des fichiers.",
  'knowledge.browse.empty.title': 'Collection vide',
  'knowledge.browse.empty.description': 'Téléversez des documents dans cette collection.',
  'knowledge.browse.prev_page': 'Page précédente',
  'knowledge.browse.next_page': 'Page suivante',
  'knowledge.browse.preview': 'Prévisualiser',
  'knowledge.browse.delete_doc': 'Supprimer le document',

  // --- Preview drawer --------------------------------------------------
  'knowledge.preview.subtitle': 'Aperçu du document',
  'knowledge.preview.binary':
    'Ce document est un fichier binaire. Ouvrez-le ou téléchargez-le pour le consulter.',
  'knowledge.preview.open_file': 'Ouvrir le fichier',
  'knowledge.preview.error': "Impossible de charger l'aperçu",

  // --- Create collection dialog ----------------------------------------
  'knowledge.create.description':
    'Les collections isolent vos documents. Les noms sont propres au workspace.',
  'knowledge.create.placeholder': 'ex. politiques, recherche',

  // --- Delete confirmations --------------------------------------------
  'knowledge.delete_collection.title': 'Supprimer la collection {name}',
  'knowledge.delete_collection.description':
    'Tous les documents et segments de cette collection seront supprimés. Cette action est irréversible.',
  'knowledge.delete_document.title': 'Supprimer {name}',
  'knowledge.delete_document.description':
    'Ce document et ses segments seront retirés de la collection.',

  // --- Toasts (UI fallbacks; the API `detail` takes precedence) --------
  'knowledge.toast.retry_before_upload':
    'Rechargez les collections avant de téléverser des documents.',
  'knowledge.toast.retry_before_create':
    'Rechargez les collections avant de créer une collection.',
  'knowledge.toast.upload_partial': '{successful}/{total} ingérés · {failed} en échec',
  'knowledge.toast.upload_partial_title': 'Téléversement partiel',
  'knowledge.toast.upload_success': '{count} fichier(s) ingéré(s)',
  'knowledge.toast.upload_complete_title': 'Téléversement terminé',
  'knowledge.toast.upload_failed': 'Échec du téléversement',
  'knowledge.toast.upload_error_title': 'Erreur de téléversement',
  'knowledge.toast.collection_created': 'Collection "{name}" créée',
  'knowledge.toast.create_failed': 'Échec de la création',
  'knowledge.toast.collection_deleted': 'Collection "{name}" supprimée',
  'knowledge.toast.delete_failed': 'Échec de la suppression',
  'knowledge.toast.document_deleted': '"{name}" supprimé',

  // --- L19 facets ------------------------------------------------------
  'knowledge.facets_aria': 'Facettes de la collection',
  'knowledge.facet.overview': 'Vue d’ensemble',
  'knowledge.facet.documents': 'Documents',
  'knowledge.facet.content': 'Contenu',
  'knowledge.facet.usage': 'Utilisation',
  'knowledge.facet.graph': 'Graphe',
  'knowledge.facet.content_panels_aria': 'Panels de contenu',
  'knowledge.content.chunks': 'Segments',
  'knowledge.content.structure': 'Structure',
  'knowledge.content.facts': 'Faits',
  'knowledge.content.ocr': 'OCR',
  'knowledge.content.table-facts': 'Faits tabulaires',
  'knowledge.action.guides': 'Guides',
  'knowledge.action.table_facts': 'Faits tabulaires',
  'knowledge.action.bindings': 'Liaisons',
  'knowledge.usage.chat_scopes_title': 'Portées de chat',
  'knowledge.usage.chat_scopes_loading': 'Chargement des portées…',
  'knowledge.usage.chat_scopes_empty': 'Aucune portée de chat n’interroge cette collection.',
  'knowledge.usage.chat_scopes_queried_by': 'Interrogée par les portées {scopes}.',
  'knowledge.usage.edit_in_admin': 'Modifier dans Administrer',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof KNOWLEDGE_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const KNOWLEDGE_EN: Record<keyof typeof KNOWLEDGE_FR, string> = {
  'knowledge.title': 'Knowledge',

  // --- Object header ------------------------------------------------
  'knowledge.header.eyebrow': 'Create · Knowledge',
  'knowledge.header.subtitle': 'Ingest documents and give every system fresh context.',
  'knowledge.header.capture': 'Capture',
  'knowledge.header.upload': 'Upload',

  // --- KPI strip (labels rendered uppercase by CSS; hints are tooltips)
  'knowledge.kpi.collections': 'Collections',
  'knowledge.kpi.collections_hint': 'Total number of collections in this workspace.',
  'knowledge.kpi.documents': 'Documents',
  'knowledge.kpi.documents_hint': 'Aggregate document count across all collections.',
  'knowledge.kpi.chunks': 'Chunks',
  'knowledge.kpi.chunks_hint': 'Aggregate chunk count — the indexing unit.',
  'knowledge.kpi.vector_db': 'Vector DB',
  'knowledge.kpi.indexing': 'indexing…',
  'knowledge.kpi.ready': 'ready',

  // --- Dropzone -------------------------------------------------------
  'knowledge.dropzone.prefix': 'Drop files here or',
  'knowledge.dropzone.browse': 'click to browse',
  'knowledge.dropzone.target': '→ target:',
  'knowledge.dropzone.formats': 'PDF · TXT · MD · DOCX · CSV · JSON',
  'knowledge.upload.progress': 'Ingesting {count} file(s)…',

  // --- Collections grid ------------------------------------------------
  'knowledge.collections.new': 'New collection',
  'knowledge.collections.error.title': 'Unable to load collections',
  'knowledge.collections.error.description':
    'Collections could not be loaded. Retry before creating, deleting or uploading documents.',
  'knowledge.collections.empty.title': 'No collections yet',
  'knowledge.collections.empty.description':
    'Upload your first document or create a collection to get started.',
  'knowledge.collections.docs_count': '{count} docs',
  'knowledge.collections.chunks_count': '{count} chunks',
  'knowledge.collections.restricted': 'Restricted',
  'knowledge.collections.indexed': 'Indexed',
  'knowledge.collections.indexing': 'Indexing…',
  'knowledge.collections.index_error': 'Indexing error',
  'knowledge.collections.not_indexed': 'Not indexed',
  'knowledge.collections.status_unknown': 'Unknown status',
  'knowledge.collections.open_detail': 'Open collection detail',
  'knowledge.collections.browse': 'Browse documents',
  'knowledge.collections.search_in': 'Search in this collection',
  'knowledge.collections.delete': 'Delete collection',
  'knowledge.collections.access.title': 'Access',
  'knowledge.collections.access.manage': 'Manage access',
  'knowledge.collections.access.admins_note': 'Workspace admins always keep access.',
  'knowledge.collections.access.read.legend': 'Who can read',
  'knowledge.collections.access.write.legend': 'Who can add documents',
  'knowledge.collections.access.all_members': 'All workspace members',
  'knowledge.collections.access.selected': 'Selected roles, groups or people',
  'knowledge.collections.access.write.hint': 'Viewers never add documents, and adding documents requires reading the collection.',
  'knowledge.collections.access.admins_only': 'Nobody is selected: only admins have access.',
  'knowledge.collections.access.roles': 'Roles',
  'knowledge.collections.access.groups': 'Groups',
  'knowledge.collections.access.people': 'People',
  'knowledge.collections.access.loading_people': 'Loading members…',
  'knowledge.collections.access.error.write_needs_read': 'Adding documents also requires reading the collection: {names}.',
  'knowledge.collections.access.saved': 'Access to {name} updated',
  'knowledge.collections.access.save_failed': 'Access could not be saved. Try again.',
  'knowledge.collections.access.upload_denied': 'You cannot add documents to this collection',

  // --- Search drawer ---------------------------------------------------
  'knowledge.search.title': 'Search knowledge',
  'knowledge.search.all_collections': 'All collections',
  'knowledge.search.placeholder': 'Ask semantic question…',
  'knowledge.search.hybrid': 'Use hybrid (sparse + vector)',
  'knowledge.search.error.title': 'Unable to search knowledge',
  'knowledge.search.error.description': 'Search failed. Retry before using results.',
  'knowledge.search.empty.title': 'No results',
  'knowledge.search.empty.description': 'Try a different query or disable hybrid.',
  'knowledge.search.unknown_file': 'unknown',

  // --- Browse drawer ---------------------------------------------------
  'knowledge.browse.title': 'Documents',
  'knowledge.browse.error.title': 'Unable to load documents',
  'knowledge.browse.error.description':
    'Documents could not be loaded. Retry before previewing or deleting files.',
  'knowledge.browse.empty.title': 'Empty collection',
  'knowledge.browse.empty.description': 'Upload documents to this collection.',
  'knowledge.browse.prev_page': 'Previous page',
  'knowledge.browse.next_page': 'Next page',
  'knowledge.browse.preview': 'Preview',
  'knowledge.browse.delete_doc': 'Delete document',

  // --- Preview drawer --------------------------------------------------
  'knowledge.preview.subtitle': 'Document preview',
  'knowledge.preview.binary': 'This document is a binary file. Open or download it to view.',
  'knowledge.preview.open_file': 'Open file',
  'knowledge.preview.error': 'Could not load preview',

  // --- Create collection dialog ----------------------------------------
  'knowledge.create.description': 'Collections isolate your documents. Names are workspace-scoped.',
  'knowledge.create.placeholder': 'e.g. policies, research',

  // --- Delete confirmations --------------------------------------------
  'knowledge.delete_collection.title': 'Delete collection {name}',
  'knowledge.delete_collection.description':
    'All documents and chunks in this collection will be deleted. This cannot be undone.',
  'knowledge.delete_document.title': 'Delete {name}',
  'knowledge.delete_document.description':
    'This document and its chunks will be removed from the collection.',

  // --- Toasts (UI fallbacks; the API `detail` takes precedence) --------
  'knowledge.toast.retry_before_upload': 'Retry loading collections before uploading documents.',
  'knowledge.toast.retry_before_create': 'Retry loading collections before creating a collection.',
  'knowledge.toast.upload_partial': '{successful}/{total} ingested · {failed} failed',
  'knowledge.toast.upload_partial_title': 'Upload partial',
  'knowledge.toast.upload_success': '{count} file(s) ingested',
  'knowledge.toast.upload_complete_title': 'Upload complete',
  'knowledge.toast.upload_failed': 'Failed to upload',
  'knowledge.toast.upload_error_title': 'Upload error',
  'knowledge.toast.collection_created': 'Collection "{name}" created',
  'knowledge.toast.create_failed': 'Failed to create',
  'knowledge.toast.collection_deleted': 'Collection "{name}" deleted',
  'knowledge.toast.delete_failed': 'Failed to delete',
  'knowledge.toast.document_deleted': '"{name}" deleted',

  // --- L19 facets ------------------------------------------------------
  'knowledge.facets_aria': 'Collection facets',
  'knowledge.facet.overview': 'Overview',
  'knowledge.facet.documents': 'Documents',
  'knowledge.facet.content': 'Content',
  'knowledge.facet.usage': 'Usage',
  'knowledge.facet.graph': 'Graph',
  'knowledge.facet.content_panels_aria': 'Content panels',
  'knowledge.content.chunks': 'Chunks',
  'knowledge.content.structure': 'Structure',
  'knowledge.content.facts': 'Facts',
  'knowledge.content.ocr': 'OCR',
  'knowledge.content.table-facts': 'Table facts',
  'knowledge.action.guides': 'Guides',
  'knowledge.action.table_facts': 'Table facts',
  'knowledge.action.bindings': 'Bindings',
  'knowledge.usage.chat_scopes_title': 'Chat scopes',
  'knowledge.usage.chat_scopes_loading': 'Loading scopes…',
  'knowledge.usage.chat_scopes_empty': 'No chat scope queries this collection.',
  'knowledge.usage.chat_scopes_queried_by': 'Queried by scopes {scopes}.',
  'knowledge.usage.edit_in_admin': 'Edit in Administrate',
};
