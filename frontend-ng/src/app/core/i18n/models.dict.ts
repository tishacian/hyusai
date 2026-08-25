/**
 * i18n — Model plane (training studio, model card, registry).
 *
 * Keys under the `models.` prefix. The demo is played in French, so FR is the
 * copy that gets read aloud: it must be idiomatic, not translated-sounding.
 *
 * Two vocabulary rules this file follows, because a model card is where jargon
 * usually creeps in:
 *
 * - a metric keeps its industry name (`AUC`, `R²`, `MAE`) and gets its meaning
 *   from the hint next to it, because renaming a metric would make the screen
 *   unreadable to the one person in the room who knows what it is;
 * - everything else is plain: "the column to predict", not "the label"; "what
 *   weighs on the prediction", not "feature importance".
 */

export const MODELS_FR = {
  // ---- chrome de page -----------------------------------------------------
  'models.eyebrow': 'Plan modèles',
  'models.title': 'Modèles',
  'models.subtitle':
    'Entraînez un modèle sur un jeu de données, comparez ses versions et choisissez celle qui répond.',

  // ---- KPIs ---------------------------------------------------------------
  'models.kpi.models': 'Modèles',
  'models.kpi.serving': 'En service',
  'models.kpi.best': 'Meilleur score',
  'models.kpi.rows': 'Lignes',
  'models.kpi.features': 'Variables',
  'models.kpi.duration': 'Entraînement',
  'models.kpi.artifact': 'Poids',
  'models.kpi.versions': 'Versions',
  'models.kpi.score': 'Score',

  // ---- liste --------------------------------------------------------------
  'models.list.empty.title': 'Aucun modèle',
  'models.list.empty.description':
    'Choisissez un jeu de données et la colonne à prédire : le prétraitement, la découpe et les métriques sont calculés pour vous.',
  'models.list.empty.no_dataset':
    'Importez d’abord un jeu de données : un modèle s’entraîne sur des colonnes profilées.',
  'models.list.train': 'Entraîner un modèle',
  'models.list.import_data': 'Aller aux données',
  'models.list.refresh': 'Rafraîchir',
  'models.list.filter.all': 'Tous',
  'models.list.filter.classification': 'Classifications',
  'models.list.filter.regression': 'Régressions',
  'models.list.filter.serving': 'En service',
  'models.list.meta': '{rows} lignes · {features} variables · {duration}',
  'models.list.target': 'Prédit {target}',
  'models.list.dataset': 'depuis {dataset}',

  // ---- statuts ------------------------------------------------------------
  'models.status.pending': 'En attente',
  'models.status.training': 'Entraînement',
  'models.status.ready': 'Prêt',
  'models.status.failed': 'Échec',
  'models.status.cancelled': 'Interrompu',

  // ---- tâches et algorithmes ---------------------------------------------
  'models.task.classification': 'Classification',
  'models.task.regression': 'Régression',
  'models.task.classification.hint':
    'Prédit une catégorie : le client résilie ou non, la cellule sature ou non.',
  'models.task.regression.hint':
    'Prédit un nombre : le revenu du mois prochain, le trafic de la cellule.',
  'models.algo.gradient_boosting': 'Gradient boosting',
  'models.algo.random_forest': 'Forêt aléatoire',
  'models.algo.linear': 'Modèle linéaire',
  'models.algo.knn': 'Plus proches voisins',
  'models.algo.gradient_boosting.hint':
    'Le choix par défaut sur du tabulaire : rapide, solide, peu sensible aux échelles.',
  'models.algo.random_forest.hint':
    'Robuste et facile à expliquer, un peu plus lent à entraîner.',
  'models.algo.linear.hint':
    'La référence à battre : si un modèle plus lourd ne fait pas mieux, il ne sert à rien.',
  'models.algo.knn.hint':
    'Décide par ressemblance avec les lignes connues. Utile comme repère.',
  'models.tag.tabular': 'Tabulaire',
  'models.tag.fast': 'Rapide',
  'models.tag.robust': 'Robuste',
  'models.tag.explainable': 'Explicable',
  'models.tag.baseline': 'Référence',
  'models.tag.interpretable': 'Interprétable',

  // ---- studio d'entraînement ---------------------------------------------
  'models.studio.title': 'Entraîner un modèle',
  'models.studio.subtitle':
    'Trois décisions : sur quoi, quoi prédire, avec quel algorithme.',
  'models.studio.close': 'Fermer',
  'models.studio.dataset.label': 'Jeu de données',
  'models.studio.dataset.placeholder': 'Choisir un jeu de données',
  'models.studio.dataset.meta': '{rows} lignes · {columns} colonnes',
  'models.studio.target.label': 'Colonne à prédire',
  'models.studio.target.placeholder': 'Choisir la colonne',
  'models.studio.target.hint':
    'La colonne que le modèle devra retrouver. Son type décide de la nature du modèle.',
  'models.studio.target.distinct': '{count} valeurs distinctes',
  'models.studio.task.label': 'Nature du modèle',
  'models.studio.task.suggested': 'Déduit de la colonne',
  'models.studio.features.label': 'Variables explicatives',
  'models.studio.features.hint':
    'Les colonnes que le modèle a le droit de regarder. Tout est sélectionné par défaut.',
  'models.studio.features.all': 'Tout',
  'models.studio.features.none': 'Rien',
  'models.studio.features.count': '{selected} sur {total}',
  'models.studio.algo.label': 'Algorithme',
  'models.studio.knobs.label': 'Réglages',
  'models.studio.knobs.auto': 'auto',
  'models.studio.knobs.reset': 'Valeurs par défaut',
  'models.studio.knob.max_iter': 'Itérations',
  'models.studio.knob.learning_rate': 'Pas d’apprentissage',
  'models.studio.knob.max_leaf_nodes': 'Feuilles par arbre',
  'models.studio.knob.n_estimators': 'Arbres',
  'models.studio.knob.max_depth': 'Profondeur',
  'models.studio.knob.min_samples_leaf': 'Lignes par feuille',
  'models.studio.knob.alpha': 'Régularisation',
  'models.studio.knob.n_neighbors': 'Voisins',
  'models.studio.split.label': 'Part de test',
  'models.studio.split.hint':
    'La part des lignes mise de côté pour noter le modèle sur ce qu’il n’a jamais vu.',
  'models.studio.cv.label': 'Validation croisée',
  'models.studio.cv.off': 'Désactivée',
  'models.studio.cv.folds': '{folds} plis',
  'models.studio.cv.hint':
    'Rejoue l’entraînement sur plusieurs découpes pour vérifier que le score n’est pas un coup de chance.',
  'models.studio.name.label': 'Nom du modèle',
  'models.studio.name.placeholder': 'Laisser vide pour reprendre le nom proposé',
  'models.studio.plan.title': 'Ce qui va être entraîné',
  'models.studio.plan.estimator': 'Estimateur',
  'models.studio.plan.rows': '{rows} lignes, dont {test} en test',
  'models.studio.plan.features': '{count} variables retenues',
  'models.studio.submit': 'Lancer l’entraînement',
  'models.studio.submitting': 'Lancement…',
  'models.studio.queued': '« {name} » est en cours d’entraînement',
  'models.studio.failed': 'Le lancement a échoué',

  // ---- carte modèle -------------------------------------------------------
  'models.detail.back': 'Retour aux modèles',
  'models.detail.tab.evidence': 'Résultats',
  'models.detail.tab.contract': 'Contrat d’entrée',
  'models.detail.tab.versions': 'Versions',
  'models.detail.tab.setup': 'Réglages',
  'models.detail.serving': 'En service',
  'models.detail.promote': 'Mettre en service',
  'models.detail.promoted': '« {name} » v{version} répond désormais',
  'models.detail.promote_hint':
    'Une seule version répond par modèle : celle-ci prendra la place de la précédente.',
  'models.detail.retrain': 'Réentraîner',
  'models.detail.cancel': 'Interrompre',
  'models.detail.cancelled': 'L’entraînement a été interrompu',
  'models.detail.delete': 'Supprimer',
  'models.detail.delete_confirm':
    'Supprimer « {name} » v{version} ? Le modèle et ses résultats disparaissent définitivement.',
  'models.detail.deleted': '« {name} » a été supprimé',
  'models.detail.progress.title': 'Entraînement en cours',
  'models.detail.progress.queued': 'En file d’attente',
  'models.detail.error.title': 'L’entraînement a échoué',
  'models.detail.trained_at': 'Entraîné le {date}',
  'models.detail.dataset': 'Jeu de données',
  'models.detail.dataset.open': 'Ouvrir le jeu de données',

  // ---- résultats ----------------------------------------------------------
  'models.evidence.scores': 'Scores sur les lignes de test',
  'models.evidence.rows': '{total} lignes · {train} en apprentissage · {test} en test',
  'models.evidence.roc': 'Courbe ROC',
  'models.evidence.roc.hint':
    'Plus la courbe monte vite vers le coin haut-gauche, mieux le modèle sépare. La diagonale est le hasard.',
  'models.evidence.pr': 'Précision / rappel',
  'models.evidence.pr.hint':
    'Ce que coûte chaque point de rappel en précision. La ligne basse est la proportion de positifs.',
  'models.evidence.fit': 'Prédit contre réel',
  'models.evidence.fit.hint':
    'Chaque point est une ligne de test. Plus le nuage colle à la diagonale, plus le modèle tombe juste.',
  'models.evidence.confusion': 'Matrice de confusion',
  'models.evidence.confusion.hint':
    'Chaque ligne est une valeur réelle, chaque colonne ce que le modèle a répondu. La diagonale est ce qu’il a eu bon.',
  'models.evidence.confusion.actual': 'Réel',
  'models.evidence.confusion.predicted': 'Prédit',
  'models.evidence.importances': 'Ce qui pèse sur la prédiction',
  'models.evidence.importances.hint':
    'Mesuré en brouillant chaque colonne à tour de rôle : ce qui fait chuter le score compte.',
  'models.evidence.importances.negative': 'Cette colonne dégrade le score',
  'models.evidence.balance': 'Répartition des classes',
  'models.evidence.balance.hint':
    'À lire avant tout score : sur une classe rare, une bonne exactitude peut ne rien vouloir dire.',
  'models.evidence.cv': 'Validation croisée',
  'models.evidence.cv.summary': '{mean} en moyenne sur {folds} plis (écart {std})',
  'models.evidence.cv.failed': 'La validation croisée n’a pas abouti',
  'models.evidence.columns': 'Colonnes utilisées',
  'models.evidence.dropped': 'Colonnes écartées',
  'models.evidence.dropped.constant': '{name} — une seule valeur',
  'models.evidence.none': 'Aucun résultat : ce modèle n’a pas encore été entraîné.',

  // ---- métriques ----------------------------------------------------------
  'models.metric.roc_auc': 'AUC',
  'models.metric.accuracy': 'Exactitude',
  'models.metric.balanced_accuracy': 'Exactitude équilibrée',
  'models.metric.f1': 'F1',
  'models.metric.precision': 'Précision',
  'models.metric.recall': 'Rappel',
  'models.metric.r2': 'R²',
  'models.metric.mae': 'MAE',
  'models.metric.rmse': 'RMSE',
  'models.metric.mape': 'MAPE',
  'models.metric.roc_auc.hint':
    'Probabilité que le modèle classe un positif au-dessus d’un négatif. 0,5 est le hasard.',
  'models.metric.accuracy.hint': 'Part des lignes de test où le modèle a répondu juste.',
  'models.metric.balanced_accuracy.hint':
    'L’exactitude moyenne par classe : insensible au déséquilibre.',
  'models.metric.f1.hint': 'Compromis entre précision et rappel.',
  'models.metric.precision.hint': 'Parmi les positifs annoncés, ceux qui en étaient.',
  'models.metric.recall.hint': 'Parmi les positifs réels, ceux que le modèle a trouvés.',
  'models.metric.r2.hint':
    'Part de la variation expliquée. 1 est parfait, 0 vaut la moyenne.',
  'models.metric.mae.hint': 'Écart moyen, dans l’unité de la colonne prédite.',
  'models.metric.rmse.hint': 'Comme la MAE, mais les grosses erreurs pèsent plus.',
  'models.metric.mape.hint': 'Écart moyen en pourcentage de la valeur réelle.',

  // ---- contrat d'entrée ---------------------------------------------------
  'models.contract.title': 'Ce que le modèle attend en entrée',
  'models.contract.hint':
    'Écrit à l’entraînement et vérifié à chaque prédiction : une ligne qui ne respecte pas ce contrat est refusée.',
  'models.contract.field': 'Champ',
  'models.contract.kind': 'Nature',
  'models.contract.range': 'Plage',
  'models.contract.choices': 'Valeurs',
  'models.contract.default': 'Défaut',
  'models.contract.kind.number': 'Nombre',
  'models.contract.kind.category': 'Catégorie',
  'models.contract.kind.datetime': 'Date',
  'models.contract.output': 'En sortie',
  'models.contract.output.classification': 'Une classe parmi : {classes}',
  'models.contract.output.regression': 'Une valeur de {target}',
  'models.contract.example': 'Exemple de ligne',

  // ---- versions -----------------------------------------------------------
  'models.versions.label': 'v{version}',
  'models.versions.current': 'Version affichée',
  'models.versions.serving': 'Répond',
  'models.versions.trained': 'Entraîné le {date}',
  'models.versions.hint':
    'Chaque entraînement crée une version. Réentraîner ne remplace pas celle qui répond : c’est vous qui décidez.',

  // ---- réglages -----------------------------------------------------------
  'models.setup.estimator': 'Estimateur',
  'models.setup.knobs': 'Réglages retenus',
  'models.setup.split': 'Part de test',
  'models.setup.cv': 'Validation croisée',
  'models.setup.scale': 'Colonnes remises à l’échelle',
  'models.setup.target': 'Colonne prédite',
  'models.setup.features': 'Variables explicatives',
  'models.setup.artifact': 'Artefact',
  'models.setup.preprocessing': 'Prétraitement',
  'models.setup.preprocessing.value':
    'Automatique : chaque colonne est encodée selon son type.',

  // ---- refus (rendus dans le formulaire) ---------------------------------
  'models.refusal.ml_train_disabled':
    'L’entraînement de modèles n’est pas activé sur cette instance.',
  'models.refusal.dataset_not_ready':
    'Ce jeu de données est encore en préparation.',
  'models.refusal.ml_dataset_unprofiled':
    'Ce jeu de données n’a pas encore de profil de colonnes.',
  'models.refusal.ml_target_required': 'Choisissez la colonne à prédire.',
  'models.refusal.ml_target_unknown':
    'Cette colonne n’existe pas dans le jeu de données.',
  'models.refusal.ml_task_unknown':
    'Un modèle est soit une classification, soit une régression.',
  'models.refusal.ml_target_not_numeric':
    'Cette colonne n’est pas numérique : entraînez une classification.',
  'models.refusal.ml_target_too_many_classes':
    'Cette colonne a trop de valeurs distinctes pour être classée.',
  'models.refusal.ml_target_single_class':
    'Cette colonne n’a qu’une valeur : il n’y a rien à séparer.',
  'models.refusal.ml_feature_unknown':
    'Une des variables choisies n’existe pas dans le jeu de données.',
  'models.refusal.ml_features_required':
    'Il faut au moins une variable en plus de la colonne à prédire.',
  'models.refusal.ml_too_many_features': 'Trop de variables sélectionnées.',
  'models.refusal.ml_rows_insufficient':
    'Ce jeu de données a trop peu de lignes pour entraîner un modèle.',
  'models.refusal.ml_rows_too_many':
    'Ce jeu de données dépasse le plafond de lignes autorisé à l’entraînement.',
  'models.refusal.ml_algo_unknown': 'Cet algorithme n’est pas proposé.',
  'models.refusal.ml_algo_task_mismatch':
    'Cet algorithme ne sait pas traiter cette nature de modèle.',
  'models.refusal.ml_model_not_ready': 'Seul un modèle entraîné peut répondre.',
  'models.refusal.ml_model_not_found':
    'Ce modèle n’existe pas dans cet espace de travail.',

  // ---- avertissements -----------------------------------------------------
  'models.warning.ml_feature_identifier':
    '« {feature} » est unique à chaque ligne : le modèle l’apprendra par cœur sans rien généraliser.',

  // ---- échecs d'entraînement ---------------------------------------------
  'models.error.ml_timeout':
    'L’entraînement a dépassé le temps imparti. Réduisez les réglages ou le nombre de lignes.',
  'models.error.ml_fit_failed':
    'L’algorithme a refusé les données telles quelles.',
  'models.error.ml_target_unusable':
    'La colonne à prédire ne permet pas d’entraîner : classe unique, trop rare, ou non numérique.',
  'models.error.ml_rows_insufficient':
    'Trop peu de lignes utilisables une fois les valeurs manquantes retirées.',
  'models.error.ml_artifact_unwritable':
    'Le modèle n’a pas pu être écrit dans le stockage.',
  'models.error.ml_harness_error':
    'L’entraînement s’est arrêté sur une erreur interne.',
  'models.error.ml_summary_missing':
    'L’entraînement n’a produit aucun résultat exploitable.',
  'models.error.ml_dataset_unavailable':
    'Le jeu de données d’entraînement n’est plus disponible.',
  'models.error.ml_artifact_empty': 'L’entraînement n’a produit aucun artefact.',
  'models.error.ml_train_disabled':
    'L’entraînement de modèles a été désactivé pendant l’exécution.',

  // ---- plan désactivé -----------------------------------------------------
  'models.disabled.title': 'Plan modèles désactivé',
  'models.disabled.description':
    'L’entraînement de modèles n’est pas activé sur cette instance. Un administrateur peut l’ouvrir dans la configuration.',
} as const;

export const MODELS_EN: Record<keyof typeof MODELS_FR, string> = {
  'models.eyebrow': 'Model plane',
  'models.title': 'Models',
  'models.subtitle':
    'Train a model on a dataset, compare its versions and choose the one that answers.',

  'models.kpi.models': 'Models',
  'models.kpi.serving': 'Serving',
  'models.kpi.best': 'Best score',
  'models.kpi.rows': 'Rows',
  'models.kpi.features': 'Features',
  'models.kpi.duration': 'Training',
  'models.kpi.artifact': 'Size',
  'models.kpi.versions': 'Versions',
  'models.kpi.score': 'Score',

  'models.list.empty.title': 'No model yet',
  'models.list.empty.description':
    'Pick a dataset and the column to predict: preprocessing, the split and the metrics are computed for you.',
  'models.list.empty.no_dataset':
    'Import a dataset first: a model trains on profiled columns.',
  'models.list.train': 'Train a model',
  'models.list.import_data': 'Go to data',
  'models.list.refresh': 'Refresh',
  'models.list.filter.all': 'All',
  'models.list.filter.classification': 'Classifications',
  'models.list.filter.regression': 'Regressions',
  'models.list.filter.serving': 'Serving',
  'models.list.meta': '{rows} rows · {features} features · {duration}',
  'models.list.target': 'Predicts {target}',
  'models.list.dataset': 'from {dataset}',

  'models.status.pending': 'Queued',
  'models.status.training': 'Training',
  'models.status.ready': 'Ready',
  'models.status.failed': 'Failed',
  'models.status.cancelled': 'Stopped',

  'models.task.classification': 'Classification',
  'models.task.regression': 'Regression',
  'models.task.classification.hint':
    'Predicts a category: whether the customer churns, whether the cell saturates.',
  'models.task.regression.hint':
    'Predicts a number: next month’s revenue, the cell’s traffic.',
  'models.algo.gradient_boosting': 'Gradient boosting',
  'models.algo.random_forest': 'Random forest',
  'models.algo.linear': 'Linear model',
  'models.algo.knn': 'Nearest neighbours',
  'models.algo.gradient_boosting.hint':
    'The default on tabular data: fast, solid, indifferent to column scales.',
  'models.algo.random_forest.hint':
    'Robust and easy to explain, a little slower to train.',
  'models.algo.linear.hint':
    'The baseline to beat: if a heavier model does not do better, it earns nothing.',
  'models.algo.knn.hint':
    'Decides by resemblance to the rows it knows. Useful as a yardstick.',
  'models.tag.tabular': 'Tabular',
  'models.tag.fast': 'Fast',
  'models.tag.robust': 'Robust',
  'models.tag.explainable': 'Explainable',
  'models.tag.baseline': 'Baseline',
  'models.tag.interpretable': 'Interpretable',

  'models.studio.title': 'Train a model',
  'models.studio.subtitle':
    'Three decisions: on what, what to predict, with which algorithm.',
  'models.studio.close': 'Close',
  'models.studio.dataset.label': 'Dataset',
  'models.studio.dataset.placeholder': 'Choose a dataset',
  'models.studio.dataset.meta': '{rows} rows · {columns} columns',
  'models.studio.target.label': 'Column to predict',
  'models.studio.target.placeholder': 'Choose the column',
  'models.studio.target.hint':
    'The column the model has to recover. Its type decides the kind of model.',
  'models.studio.target.distinct': '{count} distinct values',
  'models.studio.task.label': 'Kind of model',
  'models.studio.task.suggested': 'Inferred from the column',
  'models.studio.features.label': 'Features',
  'models.studio.features.hint':
    'The columns the model is allowed to look at. Everything is selected by default.',
  'models.studio.features.all': 'All',
  'models.studio.features.none': 'None',
  'models.studio.features.count': '{selected} of {total}',
  'models.studio.algo.label': 'Algorithm',
  'models.studio.knobs.label': 'Settings',
  'models.studio.knobs.auto': 'auto',
  'models.studio.knobs.reset': 'Defaults',
  'models.studio.knob.max_iter': 'Iterations',
  'models.studio.knob.learning_rate': 'Learning rate',
  'models.studio.knob.max_leaf_nodes': 'Leaves per tree',
  'models.studio.knob.n_estimators': 'Trees',
  'models.studio.knob.max_depth': 'Depth',
  'models.studio.knob.min_samples_leaf': 'Rows per leaf',
  'models.studio.knob.alpha': 'Regularization',
  'models.studio.knob.n_neighbors': 'Neighbours',
  'models.studio.split.label': 'Test share',
  'models.studio.split.hint':
    'The share of rows held back to score the model on what it never saw.',
  'models.studio.cv.label': 'Cross-validation',
  'models.studio.cv.off': 'Off',
  'models.studio.cv.folds': '{folds} folds',
  'models.studio.cv.hint':
    'Replays the training on several splits to check the score is not luck.',
  'models.studio.name.label': 'Model name',
  'models.studio.name.placeholder': 'Leave empty to keep the suggested name',
  'models.studio.plan.title': 'What is about to be trained',
  'models.studio.plan.estimator': 'Estimator',
  'models.studio.plan.rows': '{rows} rows, {test} of them held for testing',
  'models.studio.plan.features': '{count} features kept',
  'models.studio.submit': 'Start training',
  'models.studio.submitting': 'Starting…',
  'models.studio.queued': '“{name}” is training',
  'models.studio.failed': 'Starting the training run failed',

  'models.detail.back': 'Back to models',
  'models.detail.tab.evidence': 'Results',
  'models.detail.tab.contract': 'Input contract',
  'models.detail.tab.versions': 'Versions',
  'models.detail.tab.setup': 'Settings',
  'models.detail.serving': 'Serving',
  'models.detail.promote': 'Put in service',
  'models.detail.promoted': '“{name}” v{version} now answers',
  'models.detail.promote_hint':
    'One version answers per model: this one takes the place of the previous.',
  'models.detail.retrain': 'Retrain',
  'models.detail.cancel': 'Stop',
  'models.detail.cancelled': 'The training run was stopped',
  'models.detail.delete': 'Delete',
  'models.detail.delete_confirm':
    'Delete “{name}” v{version}? The model and its results are gone for good.',
  'models.detail.deleted': '“{name}” was deleted',
  'models.detail.progress.title': 'Training in progress',
  'models.detail.progress.queued': 'Queued',
  'models.detail.error.title': 'Training failed',
  'models.detail.trained_at': 'Trained on {date}',
  'models.detail.dataset': 'Dataset',
  'models.detail.dataset.open': 'Open the dataset',

  'models.evidence.scores': 'Scores on the test rows',
  'models.evidence.rows': '{total} rows · {train} for learning · {test} for testing',
  'models.evidence.roc': 'ROC curve',
  'models.evidence.roc.hint':
    'The faster the curve climbs to the top-left corner, the better the model separates. The diagonal is chance.',
  'models.evidence.pr': 'Precision / recall',
  'models.evidence.pr.hint':
    'What each point of recall costs in precision. The low line is the share of positives.',
  'models.evidence.fit': 'Predicted against actual',
  'models.evidence.fit.hint':
    'Every point is a test row. The closer the cloud hugs the diagonal, the closer the model is.',
  'models.evidence.confusion': 'Confusion matrix',
  'models.evidence.confusion.hint':
    'Each row is an actual value, each column what the model answered. The diagonal is what it got right.',
  'models.evidence.confusion.actual': 'Actual',
  'models.evidence.confusion.predicted': 'Predicted',
  'models.evidence.importances': 'What weighs on the prediction',
  'models.evidence.importances.hint':
    'Measured by shuffling each column in turn: whatever makes the score drop counts.',
  'models.evidence.importances.negative': 'This column degrades the score',
  'models.evidence.balance': 'Class balance',
  'models.evidence.balance.hint':
    'Read this before any score: on a rare class, a good accuracy can mean nothing.',
  'models.evidence.cv': 'Cross-validation',
  'models.evidence.cv.summary': '{mean} on average over {folds} folds (spread {std})',
  'models.evidence.cv.failed': 'Cross-validation did not complete',
  'models.evidence.columns': 'Columns used',
  'models.evidence.dropped': 'Columns dropped',
  'models.evidence.dropped.constant': '{name} — a single value',
  'models.evidence.none': 'No results: this model has not been trained yet.',

  'models.metric.roc_auc': 'AUC',
  'models.metric.accuracy': 'Accuracy',
  'models.metric.balanced_accuracy': 'Balanced accuracy',
  'models.metric.f1': 'F1',
  'models.metric.precision': 'Precision',
  'models.metric.recall': 'Recall',
  'models.metric.r2': 'R²',
  'models.metric.mae': 'MAE',
  'models.metric.rmse': 'RMSE',
  'models.metric.mape': 'MAPE',
  'models.metric.roc_auc.hint':
    'The chance the model ranks a positive above a negative. 0.5 is a coin toss.',
  'models.metric.accuracy.hint': 'Share of test rows the model answered right.',
  'models.metric.balanced_accuracy.hint':
    'Accuracy averaged per class: indifferent to imbalance.',
  'models.metric.f1.hint': 'The trade-off between precision and recall.',
  'models.metric.precision.hint': 'Of the positives announced, those that were.',
  'models.metric.recall.hint': 'Of the actual positives, those the model found.',
  'models.metric.r2.hint':
    'Share of the variation explained. 1 is perfect, 0 is the mean.',
  'models.metric.mae.hint': 'Average error, in the predicted column’s own unit.',
  'models.metric.rmse.hint': 'Like MAE, but large errors weigh more.',
  'models.metric.mape.hint': 'Average error as a percentage of the actual value.',

  'models.contract.title': 'What the model expects as input',
  'models.contract.hint':
    'Written at training time and enforced on every prediction: a row that breaks this contract is refused.',
  'models.contract.field': 'Field',
  'models.contract.kind': 'Kind',
  'models.contract.range': 'Range',
  'models.contract.choices': 'Values',
  'models.contract.default': 'Default',
  'models.contract.kind.number': 'Number',
  'models.contract.kind.category': 'Category',
  'models.contract.kind.datetime': 'Date',
  'models.contract.output': 'Output',
  'models.contract.output.classification': 'One class among: {classes}',
  'models.contract.output.regression': 'A value of {target}',
  'models.contract.example': 'Example row',

  'models.versions.label': 'v{version}',
  'models.versions.current': 'Shown version',
  'models.versions.serving': 'Answers',
  'models.versions.trained': 'Trained on {date}',
  'models.versions.hint':
    'Every training run creates a version. Retraining does not replace the one that answers: that call is yours.',

  'models.setup.estimator': 'Estimator',
  'models.setup.knobs': 'Settings used',
  'models.setup.split': 'Test share',
  'models.setup.cv': 'Cross-validation',
  'models.setup.scale': 'Columns rescaled',
  'models.setup.target': 'Predicted column',
  'models.setup.features': 'Features',
  'models.setup.artifact': 'Artifact',
  'models.setup.preprocessing': 'Preprocessing',
  'models.setup.preprocessing.value':
    'Automatic: every column is encoded according to its type.',

  'models.refusal.ml_train_disabled':
    'Model training is not enabled on this deployment.',
  'models.refusal.dataset_not_ready': 'This dataset is still being prepared.',
  'models.refusal.ml_dataset_unprofiled':
    'This dataset has no column profile yet.',
  'models.refusal.ml_target_required': 'Choose the column to predict.',
  'models.refusal.ml_target_unknown': 'This column is not in the dataset.',
  'models.refusal.ml_task_unknown':
    'A model is either a classification or a regression.',
  'models.refusal.ml_target_not_numeric':
    'This column is not numeric: train a classification instead.',
  'models.refusal.ml_target_too_many_classes':
    'This column holds too many distinct values to classify.',
  'models.refusal.ml_target_single_class':
    'This column holds one value only: there is nothing to separate.',
  'models.refusal.ml_feature_unknown':
    'One of the chosen features is not in the dataset.',
  'models.refusal.ml_features_required':
    'A model needs at least one feature besides the column to predict.',
  'models.refusal.ml_too_many_features': 'Too many features selected.',
  'models.refusal.ml_rows_insufficient':
    'This dataset has too few rows to train a model.',
  'models.refusal.ml_rows_too_many':
    'This dataset is above the row ceiling allowed for training.',
  'models.refusal.ml_algo_unknown': 'This algorithm is not offered.',
  'models.refusal.ml_algo_task_mismatch':
    'This algorithm does not handle that kind of model.',
  'models.refusal.ml_model_not_ready': 'Only a trained model can answer.',
  'models.refusal.ml_model_not_found':
    'This model does not exist in this workspace.',

  'models.warning.ml_feature_identifier':
    '“{feature}” is unique per row: the model will memorise it and generalize nothing.',

  'models.error.ml_timeout':
    'Training ran out of time. Lower the settings or the number of rows.',
  'models.error.ml_fit_failed': 'The algorithm refused the data as it stands.',
  'models.error.ml_target_unusable':
    'The column to predict cannot be trained on: single class, too rare, or not numeric.',
  'models.error.ml_rows_insufficient':
    'Too few usable rows once missing values are dropped.',
  'models.error.ml_artifact_unwritable':
    'The model could not be written to storage.',
  'models.error.ml_harness_error': 'Training stopped on an internal error.',
  'models.error.ml_summary_missing': 'Training produced no usable result.',
  'models.error.ml_dataset_unavailable':
    'The training dataset is no longer available.',
  'models.error.ml_artifact_empty': 'Training produced no artifact.',
  'models.error.ml_train_disabled':
    'Model training was disabled while the run was in flight.',

  'models.disabled.title': 'Model plane disabled',
  'models.disabled.description':
    'Model training is not enabled on this deployment. An administrator can open it in the configuration.',
};
