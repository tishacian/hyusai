/**
 * i18n — Data plane (datasets, column profiles, transforms, models).
 *
 * Keys under the `data.` prefix. The demo is played in French, so FR is the
 * copy that gets read aloud: it must be idiomatic, not translated-sounding.
 */

export const DATA_FR = {
  // ---- navigation & page chrome ------------------------------------------
  'data.eyebrow': 'Plan data',
  'data.title': 'Données',
  'data.subtitle':
    'Jeux de données tabulaires : import, profil de colonnes, transformations et lignage.',

  // ---- KPIs --------------------------------------------------------------
  'data.kpi.datasets': 'Jeux de données',
  'data.kpi.rows': 'Lignes',
  'data.kpi.columns': 'Colonnes',
  'data.kpi.size': 'Volume',
  'data.kpi.versions': 'Versions',

  // ---- liste -------------------------------------------------------------
  'data.list.empty.title': 'Aucun jeu de données',
  'data.list.empty.description':
    'Importez un CSV, un Parquet ou un classeur Excel pour démarrer : le profil des colonnes est calculé automatiquement.',
  'data.list.import': 'Importer un fichier',
  'data.list.open': 'Ouvrir le détail',
  'data.list.meta': '{rows} lignes · {columns} colonnes · {size}',
  'data.list.filter.all': 'Toutes les origines',
  'data.list.filter.upload': 'Imports',
  'data.list.filter.transform': 'Transformations',
  'data.list.filter.score': 'Scorings',
  'data.list.refresh': 'Rafraîchir',

  // ---- origine -----------------------------------------------------------
  'data.source.upload': 'Import',
  'data.source.transform': 'Transformation',
  'data.source.score': 'Scoring',
  'data.source.generated': 'Généré',

  // ---- statuts -----------------------------------------------------------
  'data.status.pending': 'En attente',
  'data.status.ingesting': 'Préparation',
  'data.status.ready': 'Prêt',
  'data.status.failed': 'Échec',
  'data.status.deleted': 'Retiré',

  // ---- import ------------------------------------------------------------
  'data.upload.dropzone.title': 'Déposez un fichier ou cliquez pour parcourir',
  'data.upload.dropzone.hint': 'CSV, TSV, Parquet, JSON/NDJSON ou XLSX — jusqu’à {size}',
  'data.upload.sending': 'Envoi de {name}…',
  'data.upload.queued': '{name} est en file de préparation',
  'data.upload.done': '{name} est prêt — {rows} lignes',
  'data.upload.failed': 'L’import de {name} a échoué',
  'data.upload.name_label': 'Nom du jeu de données',
  'data.upload.name_placeholder': 'Laisser vide pour reprendre le nom du fichier',

  // ---- progression d'ingest ---------------------------------------------
  'data.progress.title': 'Préparation en cours',
  'data.progress.step.queued': 'En file d’attente',
  'data.progress.step.reading': 'Lecture du fichier',
  'data.progress.step.profiling': 'Profilage des colonnes',
  'data.progress.step.writing': 'Écriture de la copie Parquet',
  'data.progress.step.done': 'Terminé',
  // Once le parse a produit une hauteur, le nombre de lignes accompagne l’étape :
  // c’est ce qui distingue « ça travaille » de « votre fichier est arrivé entier ».
  'data.progress.step.queued.counted': 'En file d’attente',
  'data.progress.step.reading.counted': 'Lecture du fichier',
  'data.progress.step.profiling.counted': 'Profilage — {rows} lignes',
  'data.progress.step.writing.counted': 'Écriture Parquet — {rows} lignes',

  // ---- détail : onglets --------------------------------------------------
  'data.detail.tab.preview': 'Aperçu',
  'data.detail.tab.schema': 'Schéma',
  'data.detail.tab.lineage': 'Lignage',
  'data.detail.tab.versions': 'Versions',

  // ---- détail : aperçu ---------------------------------------------------
  'data.detail.preview.caption': '{shown} premières lignes affichées',
  'data.detail.back': 'Retour aux données',
  'data.detail.retry': 'Relancer la préparation',
  'data.detail.delete': 'Retirer',
  'data.detail.delete_confirm':
    'Retirer « {name} » ? Le jeu de données disparaît des surfaces ; les octets restent gérés par le cycle de vie du stockage.',
  'data.detail.deleted': '« {name} » a été retiré',
  'data.detail.error.title': 'La préparation a échoué',

  // ---- détail : schéma / profil -----------------------------------------
  'data.schema.column': 'Colonne',
  'data.schema.kind': 'Type',
  'data.schema.nulls': 'Valeurs nulles',
  'data.schema.distinct': 'Valeurs distinctes',
  'data.schema.range': 'Plage',
  'data.schema.mean': 'Moyenne',
  'data.schema.top': 'Valeurs fréquentes',
  'data.schema.profile': 'Profil',

  // ---- types de colonnes ------------------------------------------------
  'data.kind.integer': 'Entier',
  'data.kind.float': 'Décimal',
  'data.kind.boolean': 'Booléen',
  'data.kind.datetime': 'Date',
  'data.kind.string': 'Texte',
  'data.kind.other': 'Autre',

  // ---- lignage -----------------------------------------------------------
  'data.lineage.parents': 'En amont',
  'data.lineage.children': 'En aval',
  'data.lineage.none': 'Aucune dépendance enregistrée',
  'data.lineage.produced_by': 'Produit par {producer}',
  'data.lineage.origin': 'Fichier importé : {filename}',
  'data.lineage.run': 'Exécution {run}',
  'data.lineage.model': 'Modèle',
  'data.lineage.scored_by': 'scoré par {model}',
  'data.lineage.scored_by.hint':
    'Colonne ajoutée par le modèle {model} — elle n’était pas dans le jeu de données amont.',
  'data.lineage.added_columns': 'Colonnes ajoutées : {columns}',

  // ---- versions ----------------------------------------------------------
  'data.versions.current': 'Version courante',
  'data.versions.label': 'v{version}',
  'data.versions.created': 'Créée le {date}',

  // ---- table partagée ----------------------------------------------------
  'data.table.null': 'null',
  'data.table.empty': 'Aucune ligne à afficher',
  'data.table.distinct': '{count} distinctes',
  'data.table.nulls': '{count} nulles',
  'data.table.rows_columns': '{rows} lignes · {columns} colonnes',
  'data.table.profile.open': 'Profil de la colonne {column}',
  'data.table.profile.title': 'Profil — {column}',
  'data.table.profile.rows': 'Lignes',
  'data.table.profile.nulls': 'Nulles',
  'data.table.profile.distinct': 'Distinctes',
  'data.table.profile.min': 'Minimum',
  'data.table.profile.max': 'Maximum',
  'data.table.profile.mean': 'Moyenne',
  'data.table.profile.std': 'Écart-type',
  'data.table.profile.top': 'Valeurs les plus fréquentes',
} as const;

export const DATA_EN: Record<keyof typeof DATA_FR, string> = {
  'data.eyebrow': 'Data plane',
  'data.title': 'Data',
  'data.subtitle':
    'Tabular datasets: import, column profile, transformations and lineage.',

  'data.kpi.datasets': 'Datasets',
  'data.kpi.rows': 'Rows',
  'data.kpi.columns': 'Columns',
  'data.kpi.size': 'Size',
  'data.kpi.versions': 'Versions',

  'data.list.empty.title': 'No dataset yet',
  'data.list.empty.description':
    'Import a CSV, a Parquet file or an Excel workbook to start: the column profile is computed for you.',
  'data.list.import': 'Import a file',
  'data.list.open': 'Open detail',
  'data.list.meta': '{rows} rows · {columns} columns · {size}',
  'data.list.filter.all': 'All origins',
  'data.list.filter.upload': 'Uploads',
  'data.list.filter.transform': 'Transforms',
  'data.list.filter.score': 'Scorings',
  'data.list.refresh': 'Refresh',

  'data.source.upload': 'Upload',
  'data.source.transform': 'Transform',
  'data.source.score': 'Scoring',
  'data.source.generated': 'Generated',

  'data.status.pending': 'Queued',
  'data.status.ingesting': 'Preparing',
  'data.status.ready': 'Ready',
  'data.status.failed': 'Failed',
  'data.status.deleted': 'Retired',

  'data.upload.dropzone.title': 'Drop a file or click to browse',
  'data.upload.dropzone.hint': 'CSV, TSV, Parquet, JSON/NDJSON or XLSX — up to {size}',
  'data.upload.sending': 'Uploading {name}…',
  'data.upload.queued': '{name} is queued for preparation',
  'data.upload.done': '{name} is ready — {rows} rows',
  'data.upload.failed': 'Importing {name} failed',
  'data.upload.name_label': 'Dataset name',
  'data.upload.name_placeholder': 'Leave empty to reuse the file name',

  'data.progress.title': 'Preparation in progress',
  'data.progress.step.queued': 'Queued',
  'data.progress.step.reading': 'Reading the file',
  'data.progress.step.profiling': 'Profiling columns',
  'data.progress.step.writing': 'Writing the Parquet copy',
  'data.progress.step.done': 'Done',
  'data.progress.step.queued.counted': 'Queued',
  'data.progress.step.reading.counted': 'Reading the file',
  'data.progress.step.profiling.counted': 'Profiling — {rows} rows',
  'data.progress.step.writing.counted': 'Writing Parquet — {rows} rows',

  'data.detail.tab.preview': 'Preview',
  'data.detail.tab.schema': 'Schema',
  'data.detail.tab.lineage': 'Lineage',
  'data.detail.tab.versions': 'Versions',

  'data.detail.preview.caption': 'Showing the first {shown} rows',
  'data.detail.back': 'Back to data',
  'data.detail.retry': 'Retry preparation',
  'data.detail.delete': 'Retire',
  'data.detail.delete_confirm':
    'Retire “{name}”? The dataset disappears from the surfaces; the bytes stay with the storage lifecycle.',
  'data.detail.deleted': '“{name}” was retired',
  'data.detail.error.title': 'Preparation failed',

  'data.schema.column': 'Column',
  'data.schema.kind': 'Type',
  'data.schema.nulls': 'Nulls',
  'data.schema.distinct': 'Distinct values',
  'data.schema.range': 'Range',
  'data.schema.mean': 'Mean',
  'data.schema.top': 'Frequent values',
  'data.schema.profile': 'Profile',

  'data.kind.integer': 'Integer',
  'data.kind.float': 'Float',
  'data.kind.boolean': 'Boolean',
  'data.kind.datetime': 'Date',
  'data.kind.string': 'Text',
  'data.kind.other': 'Other',

  'data.lineage.parents': 'Upstream',
  'data.lineage.children': 'Downstream',
  'data.lineage.none': 'No recorded dependency',
  'data.lineage.produced_by': 'Produced by {producer}',
  'data.lineage.origin': 'Uploaded file: {filename}',
  'data.lineage.run': 'Run {run}',
  'data.lineage.model': 'Model',
  'data.lineage.scored_by': 'scored by {model}',
  'data.lineage.scored_by.hint':
    'Column written by model {model} — it was not in the upstream dataset.',
  'data.lineage.added_columns': 'Added columns: {columns}',

  'data.versions.current': 'Current version',
  'data.versions.label': 'v{version}',
  'data.versions.created': 'Created on {date}',

  'data.table.null': 'null',
  'data.table.empty': 'No row to display',
  'data.table.distinct': '{count} distinct',
  'data.table.nulls': '{count} null',
  'data.table.rows_columns': '{rows} rows · {columns} columns',
  'data.table.profile.open': 'Profile of column {column}',
  'data.table.profile.title': 'Profile — {column}',
  'data.table.profile.rows': 'Rows',
  'data.table.profile.nulls': 'Null',
  'data.table.profile.distinct': 'Distinct',
  'data.table.profile.min': 'Minimum',
  'data.table.profile.max': 'Maximum',
  'data.table.profile.mean': 'Mean',
  'data.table.profile.std': 'Std deviation',
  'data.table.profile.top': 'Most frequent values',
};
