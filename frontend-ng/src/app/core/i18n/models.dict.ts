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
  'models.refusal.ml_label_review_required': 'Confirmez les étiquettes dans la porte humaine du Flow avant de les utiliser comme cible.',
  'models.refusal.ml_label_review_changed': 'La provenance a changé depuis la soumission. Sélectionnez de nouveau le dataset revu.',
  'models.refusal.ml_label_review_invalid': 'Les étiquettes ne correspondent pas à leur preuve de revue. Reprenez la revue du dataset.',
  'models.refusal.ml_distillation_source_required': 'Le coût d’inférence concerne uniquement la cible confirmée d’un dataset étiqueté par LLM puis revu.',
  'models.spec.distillation_inference_cost_per_1000': 'Coût estimatif du modèle pour 1 000 prédictions (USD)',
  'models.spec.distillation_inference_cost_per_1000.hint': 'Facultatif, de 0 à 1 000 USD, uniquement pour la cible confirmée d’un dataset étiqueté par LLM puis revu. Vide signifie indisponible ; zéro doit être renseigné explicitement.',
  'models.distillation.title': 'Distillation après revue humaine',
  'models.distillation.held_out': 'Comparaisons sur les mêmes {count} lignes de test, exclues de l’entraînement.',
  'models.distillation.agreement': 'Accord du modèle avec le LLM',
  'models.distillation.reviewed_accuracy': 'Exactitude du modèle face aux étiquettes humaines',
  'models.distillation.teacher_accuracy': 'Exactitude du LLM face aux étiquettes humaines',
  'models.distillation.llm_cost': 'Coût estimatif du LLM pour 1 000 étiquettes',
  'models.distillation.model_cost': 'Coût estimatif du modèle pour 1 000 prédictions',
  'models.distillation.cost_hint': 'Montants en USD : estimation du LLM selon les tarifs déclarés et estimation d’inférence renseignée par l’auteur. Ce ne sont pas des factures fournisseur.',
  'models.distillation.unknown_attempts': '{count} tentatives sans consommation connue restent incluses au budget réservé du LLM.',
  'models.distillation.reviewed': '{total} lignes confirmées par une personne, dont {corrected} classes corrigées.',
  'models.distillation.teacher': 'Modèle de langage source',
  'models.distillation.dataset': 'Ouvrir le dataset revu',
  'models.distillation.unavailable': 'Indisponible',
  'models.spec.intervals': 'Intervalles de prédiction',
  'models.spec.intervals.off': 'Désactivés',
  'models.spec.intervals.conformal': 'Validation croisée',
  'models.spec.intervals.hint': 'Estimer une plage de valeurs à partir des erreurs de validation croisée, sans retirer de données de l’entraînement.',
  'models.intervals.title': 'Couverture des intervalles',
  'models.intervals.level': 'Niveau demandé',
  'models.intervals.coverage': 'Couverture sur le test',
  'models.intervals.width': 'Largeur moyenne',
  'models.intervals.hint': 'Calcul sur {rows} lignes d’entraînement, en {folds} partitions. La couverture est mesurée sur le test, face au niveau demandé.',
  'models.intervals.band': 'Intervalle à {level}',
  'models.serving.error.ml_interval_level_unknown': 'Ce niveau n’a pas été calculé. Choisissez un des niveaux proposés.',
  'models.spec.calibration': "Calibration des probabilités",
  'models.spec.calibration.hint': "Ajuste les probabilités sur 20 % du train. Le test mesure le résultat sans intervenir dans cet ajustement.",
  'models.spec.calibration.off': "Désactivée",
  'models.spec.calibration.auto': "Automatique",
  'models.spec.calibration.sigmoid': "Sigmoïde",
  'models.spec.calibration.isotonic': "Isotonique",
  'models.spec.threshold': "Seuil de décision",
  'models.spec.threshold.hint': "Classification binaire : choisit le seuil sur la calibration, ou par validation croisée du train.",
  'models.spec.threshold.default': "Par défaut (50 %)",
  'models.spec.threshold.f1': "Meilleur F1",
  'models.spec.threshold.youden': "Indice de Youden",
  'models.calibration.title': "Fiabilité des probabilités",
  'models.calibration.rows': "{fit} lignes ajustées · {calibration} lignes de calibration",
  'models.calibration.before': "Avant calibration",
  'models.calibration.after': "Après calibration",
  'models.calibration.hint': "Mesuré sur le même test. Pour Brier et log loss, plus bas est préférable.",
  'models.calibration.worse': "La calibration dégrade au moins une mesure sur le test. Le choix de calibration reste appliqué.",
  'models.calibration.x': "Probabilité annoncée",
  'models.calibration.y': "Fréquence observée",
  'models.decision.title': "Seuil de décision",
  'models.decision.hint': "Choisi hors test selon « {criterion} ». Les résultats ci-dessous sont mesurés sur le test.",
  'models.decision.default': "Seuil 50 %",
  'models.decision.tuned': "Seuil choisi",
  'models.play.threshold': "Seuil de décision : {threshold}",
  "models.error.ML_CALIBRATION_TOO_FEW": "Calibration ignorée : il faut au moins 200 lignes de calibration et 20 exemples de chaque classe.",
  "models.error.ML_THRESHOLD_TOO_FEW": "Seuil par défaut conservé : trop peu d’exemples de chaque classe pour la validation croisée.",
  "models.error.ML_THRESHOLD_BINARY_ONLY": "Le seuil personnalisé est ignoré : il ne s’applique qu’à deux classes.",
  'models.spec.tuning': "Réglage automatique",
  'models.spec.tuning.off': "Désactivé",
  'models.spec.tuning.budget': "Régler automatiquement",
  'models.spec.tuning.hint': "Compare les réglages par validation croisée, dans le budget choisi.",
  'models.spec.tuning_trials': "Nombre maximal d’essais",
  'models.spec.tuning_trials.hint': "Le premier essai reprend vos réglages. De 5 à 100 essais.",
  'models.spec.tuning_budget_s': "Budget de réglage (secondes)",
  'models.spec.tuning_budget_s.hint': "Au plus 60 % du délai d’entraînement, pour garder du temps au modèle final.",
  'models.tuning.title': "Réglage automatique",
  'models.tuning.validation': "{metric} · validation croisée sur {folds} plis du train",
  'models.tuning.chart': "Score de validation par essai",
  'models.tuning.trial': "Essai",
  'models.tuning.start': "Départ",
  'models.tuning.best': "Meilleur",
  'models.tuning.trials': "Nombre d’essais atteint",
  'models.tuning.budget': "Budget épuisé",
  'models.tuning.counts': "{run} essais · {pruned} élagués · {failed} échoués",
  'models.tuning.baseline_unavailable': "Le départ n’a pas pu être évalué dans le budget. Vos réglages sont conservés, sans gain mesuré.",
  'models.tuning.knobs': "Réglages avant et après",
  'models.tuning.setting': "Réglage",
  'models.tuning.auto': "Automatique",
  'models.tuning.hint': "Le meilleur score est choisi sur le train. Les scores de la carte sont mesurés sur le test, resté à l’écart du réglage.",
  'models.warning.ml_tuning_estimate': "Durée indicative des essais : {estimated_s} s (budget : {budget_s} s), estimée depuis la version précédente.",
  'models.warning.ml_tuning_budget_limited': "Le budget peut arrêter la recherche avant tous les essais.",
  'models.explain.missing': "est manquant",
  'models.explain.present': "est renseigné",
  'models.explain.or': "ou",
  'models.spec.explain': "Explications du modèle",
  'models.spec.explain.hint': "Explore les erreurs, un arbre simplifié et l’effet des variables sur le test, dans un budget de 60 secondes.",
  'models.spec.explain.off': "Désactivées",
  'models.spec.explain.pack': "Pack d’explications",
  'models.spec.fairness_columns': "Comparer des groupes",
  'models.spec.fairness_columns.hint': "Jusqu’à 3 colonnes de 12 groupes au maximum, même si le modèle ne les utilise pas.",
  'models.explain.errors.title': "Où le modèle se trompe",
  'models.explain.rows': "Mesuré sur {rows} lignes du test.",
  'models.explain.errors.global': "Erreur globale : {value}",
  'models.explain.errors.rule': "{rows} lignes · erreur {value}",
  'models.explain.surrogate.title': "Une version simplifiée de la décision",
  'models.explain.surrogate.fidelity': "Fidélité : {value}",
  'models.explain.surrogate.hint': "Arbre de profondeur 3. La fidélité est mesurée sur des lignes distinctes de celles qui ont servi à ajuster cet arbre.",
  'models.explain.surrogate.complex': "Le modèle est trop complexe pour qu’un arbre de profondeur 3 l’explique fidèlement (moins de 70 %).",
  'models.explain.support': "{rows} lignes",
  'models.explain.all': "Toutes les lignes",
  'models.explain.and': "et",
  'models.explain.budget': "Budget d’explication atteint ; les autres résultats restent disponibles.",
  'models.explain.section_unavailable': "Cette explication n’a pas pu être calculée. Le modèle reste disponible.",
  'models.explain.pdp.title': "Effet de {feature}",
  'models.explain.pdp.average': "Effet moyen",
  'models.explain.pdp.hint': "Trait fort : effet moyen. Traits fins : variations sur des lignes individuelles, en conservant les autres valeurs.",
  'models.explain.pdp.class': "Probabilité de la classe {label}",
  'models.explain.fairness.title': "Comparaison des groupes · {column}",
  'models.explain.fairness.hint': "Les groupes de moins de 30 lignes sont affichés mais exclus des ratios.",
  'models.explain.fairness.selection_ratio': "Rapport des taux de sélection : {value}",
  'models.explain.fairness.odds': "Écart maximal TPR/FPR : {value}",
  'models.explain.fairness.mae_gap': "Écart des MAE rapporté à l’erreur globale : {value}",
  'models.explain.fairness.signal': "Le rapport des taux de sélection est inférieur à 80 %.",
  'models.explain.fairness.group': "Groupe",
  'models.explain.fairness.rows': "Lignes",
  'models.explain.fairness.low_support': "Faible effectif",
  'models.explain.metric.selection_rate': "Taux de sélection",
  'models.explain.metric.tpr': "Vrais positifs",
  'models.explain.metric.fpr': "Faux positifs",
  'models.explain.metric.accuracy': "Exactitude",
  'models.explain.metric.mae': "MAE",
  'models.explain.metric.bias': "Biais moyen",


  'models.spec.text_encoder': "Encodage du texte",
  'models.spec.text_encoder.auto': "Automatique",
  'models.spec.text_encoder.string': "TF-IDF et SVD",
  'models.spec.text_encoder.minhash': "MinHash",
  'models.spec.text_encoder.hint': "Pour les colonnes contenant beaucoup de textes distincts. Automatique conserve le comportement habituel.",
  'models.tabular.text_columns': "Colonnes de texte détectées : {columns}",

  // ---- chrome de page -----------------------------------------------------
  'models.eyebrow': 'Données & modèles · Modèles',
  'models.title': 'Modèles',
  'models.list.go_data': 'Jeux de données',
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
  'models.list.filter.forecasting': 'Prévisions',
  'models.list.filter.serving': 'En service',
  'models.list.col.model': 'Modèle',
  'models.list.col.target': 'Cible',
  'models.list.col.dataset': 'Jeu d’entraînement',
  'models.list.col.served': 'Version servie',
  'models.list.col.score': 'Score',
  'models.list.col.monitor': 'Suivi',
  'models.list.meta': '{rows} lignes · {features} variables · {duration}',
  'models.list.target': 'Prédit {target}',
  'models.list.dataset': 'depuis {dataset}',
  'models.list.dataset.none': '—',
  'models.list.monitor.ok': 'Stable',
  'models.list.monitor.watch': 'Attention',
  'models.list.monitor.alert': 'Alerte',
  'models.list.monitor.none': '—',
  'models.list.served': 'v{version} répond',
  'models.list.served.progress': 'v{version} en cours',
  'models.list.served.none': 'aucune ne répond',

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
  'models.task.forecasting': 'Prévision',
  'models.task.forecasting.hint':
    'Prédit la suite d’une série datée : la charge de la cellule demain, les ventes du mois prochain, avec un intervalle.',
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
  'models.algo.ets': 'Lissage exponentiel (ETS)',
  'models.algo.arima': 'ARIMA saisonnier',
  'models.algo.seasonal_naive': 'Naïf saisonnier',
  'models.algo.ets.hint':
    'Un modèle statistique par série : tendance et saisonnalité, avec ses propres intervalles. Solide sur peu d’historique.',
  'models.algo.arima.hint':
    'Le classique des séries temporelles : autocorrélation et saisonnalité, une série à la fois.',
  'models.algo.seasonal_naive.hint':
    'Répète la dernière saison. Le repère que toute prévision doit battre.',
  'models.tag.tabular': 'Tabulaire',
  'models.tag.fast': 'Rapide',
  'models.tag.robust': 'Robuste',
  'models.tag.explainable': 'Explicable',
  'models.tag.baseline': 'Référence',
  'models.tag.interpretable': 'Interprétable',
  'models.tag.statistical': 'Statistique',
  'models.tag.seasonal': 'Saisonnier',

  // ---- studio d'entraînement ---------------------------------------------
  'models.studio.title': 'Entraîner un modèle',
  'models.studio.subtitle':
    'Trois décisions : sur quoi, quoi prédire, avec quel algorithme.',
  'models.studio.close': 'Fermer',
  'models.studio.dataset.label': 'Jeu de données',
  'models.studio.dataset.placeholder': 'Choisir un jeu de données',
  'models.studio.dataset.meta': '{rows} lignes · {columns} colonnes',
  'models.studio.dataset.sample': 'Ce que le modèle va lire',
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
  'models.studio.plan.forecast': '{horizon} pas prévus · {folds} backtests',
  'models.studio.forecast.no_time':
    'Ce jeu n’a pas de colonne de date : une prévision a besoin de dates.',
  'models.studio.forecast.unused': 'Non utilisée',
  'models.studio.forecast.no_covariates': 'Aucune autre colonne utilisable.',
  'models.studio.forecast.lags_auto': 'Selon la fréquence',
  'models.studio.forecast.lags_invalid': 'Des nombres entiers positifs, séparés par des virgules.',
  'models.studio.plan.features': '{count} variables retenues',
  'models.studio.submit': 'Lancer l’entraînement',
  'models.studio.submitting': 'Lancement…',
  'models.studio.queued': '« {name} » est en cours d’entraînement',
  'models.studio.failed': 'Le lancement a échoué',

  // ---- carte modèle -------------------------------------------------------
  'models.detail.back': 'Retour aux modèles',
  'models.detail.gone.title': 'Ce modèle est introuvable',
  'models.detail.gone.description':
    'Il a été supprimé, ou le lien pointe vers un identifiant qui n’existe pas dans cet espace de travail.',
  'models.detail.tab.evidence': 'Résultats',
  'models.detail.tab.play': 'Prédire',
  'models.detail.tab.compare': 'Comparaison',
  'models.detail.tab.monitor': 'Suivi',
  'models.detail.tab.contract': 'Contrat d’entrée',
  'models.detail.tab.versions': 'Versions',
  'models.detail.tab.setup': 'Réglages',
  'models.detail.serving': 'En service',
  'models.detail.challenger': 'Prétendante',
  'models.detail.challenger_hint':
    'La meilleure version qui ne répond pas : le registre la nomme « challenger », donc models:/<modèle>@challenger la résout sans passer par Agentium.',
  'models.detail.promote': 'Mettre la v{version} en service',
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
  'models.detail.error.title': 'L’entraînement a échoué',
  'models.detail.trained_at': 'Entraîné le {date}',
  'models.detail.dataset': 'Jeu de données',
  'models.detail.dataset.open': 'Ouvrir le jeu de données',
  'models.detail.provenance': 'Provenance',
  'models.detail.origin_system': 'Entraîné par une exécution de Système',
  'models.detail.system_chip': 'Système',
  'models.detail.run_chip': 'Exécution',
  'models.detail.provenance.dataset': '{name}',
  'models.detail.provenance.transform': '{name} · {engine}',
  'models.detail.provenance.model': '{name} v{version}',
  'models.detail.provenance.scored': '{name}',

  // ---- progression d'entraînement ----------------------------------------
  // Les codes que l'ouvrier et le harnais publient dans `status_detail`.
  'models.tabular.options': 'Options avancées',
  'models.tabular.option.hint': 'Configurer {field} pour cet entraînement.',
  'models.error.ml_feedback_not_numeric': 'L’issue réelle doit être un nombre fini pour un modèle de régression.',
  'models.warning.ml_spec_field_ignored': 'L’option {field} est ignorée car elle ne s’applique pas à cette configuration.',
  'models.progress.step.tuning': 'Réglage automatique',
  'models.progress.step.tuning.counted': 'Réglage automatique — essai {fold}/{folds}',
  'models.progress.step.calibrating': 'Calibration du modèle',
  'models.progress.step.calibrating.counted': 'Calibration — pli {fold}/{folds}',
  'models.progress.step.explaining': 'Analyse des explications',
  'models.progress.step.queued': 'En file d’attente',
  'models.progress.step.reading': 'Lecture du jeu de données',
  'models.progress.step.fitting': 'Ajustement du modèle',
  'models.progress.step.fitting.counted': 'Ajustement sur {rows} lignes',
  'models.progress.step.scoring': 'Évaluation sur les lignes de test',
  'models.progress.step.validating': 'Validation croisée sur {folds} plis',
  'models.progress.step.validating.counted': 'Validation croisée — pli {fold}/{folds}',
  'models.progress.step.backtesting': 'Backtest sur {folds} horizons passés',
  'models.progress.step.backtesting.counted': 'Backtest — horizon {fold}/{folds}',
  'models.progress.step.saving': 'Enregistrement de l’artefact',
  'models.progress.step.done': 'Terminé',
  'models.progress.settled': 'Modèle {name} v{version} prêt — {metric} {value}',
  'models.progress.settled.plain': 'Modèle {name} v{version} prêt',
  'models.progress.failed': 'Entraînement de {name} v{version} échoué',

  // ---- résultats ----------------------------------------------------------
  'models.evidence.scores': 'Scores sur les lignes de test',
  'models.evidence.scores.forecast': 'Scores du backtest',
  'models.evidence.rows': '{total} lignes · {train} en apprentissage · {test} en test',
  'models.evidence.forecast': 'Prévisions rejouées sur le passé',
  'models.evidence.forecast.hint':
    'Chaque horizon est prévu avec les seules données d’avant lui. La bande est l’intervalle à {level}, calibré sur les erreurs des horizons précédents.',
  'models.evidence.forecast.series': 'Série',
  'models.evidence.forecast.actual': 'Réel',
  'models.evidence.forecast.pred': 'Prévu',
  'models.evidence.forecast.interval': 'Intervalle',
  'models.evidence.forecast.rows': '{total} lignes · {history} pas d’historique · {series} série(s)',
  'models.evidence.forecast.setup': '{frequency} · horizon {horizon} · {folds} backtests · {method}',
  'models.evidence.forecast.method.conformal': 'intervalle conforme',
  'models.evidence.forecast.method.model': 'intervalle du modèle',
  'models.evidence.forecast.filled': '{count} pas comblés ({fill})',
  'models.evidence.horizon': 'Erreur par pas d’horizon',
  'models.evidence.horizon.hint':
    'L’erreur absolue moyenne à chaque pas : la vitesse à laquelle la prévision se dégrade.',
  'models.evidence.horizon.step': '+{step}',
  'models.evidence.series': 'Erreur par série',
  'models.evidence.series.hint':
    'Les séries les moins bien prévues d’abord. Un MASE sous 1 fait mieux que répéter la valeur précédente.',
  'models.evidence.baseline.better': '{share} d’erreur en moins que répéter la dernière saison',
  'models.evidence.baseline.worse': '{share} d’erreur en plus que répéter la dernière saison',
  'models.evidence.coverage': 'Couverture {coverage} pour {level} visés',
  'models.explain.title': 'Ce qui fait la prévision',
  'models.explain.groups': 'Par famille de variables',
  'models.explain.groups.hint':
    'Part de chaque famille dans les prévisions du modèle : SHAP moyen mesuré sur son historique d’entraînement.',
  'models.explain.lags': 'Le passé qu’elle reprend',
  'models.explain.lags.hint':
    'Poids de chaque valeur passée de la série. Un pic à 7 j veut dire que la prévision suit surtout la même heure la semaine précédente.',
  'models.explain.step': 'Modèle direct : explication du premier pas de l’horizon.',
  'models.explain.group.lags': 'Passé récent de la série',
  'models.explain.group.calendar': 'Calendrier',
  'models.explain.group.future': 'Covariables connues à l’avance',
  'models.explain.group.past': 'Autres séries',
  'models.explain.group.static': 'Attributs de la série',
  'models.explain.group.series': 'Identité de la série',
  'models.explain.group.other': 'Autres',
  'models.explain.span.hours': '{n} h',
  'models.explain.span.days': '{n} j',
  'models.explain.span.weeks': '{n} sem.',
  'models.explain.span.months': '{n} mois',
  'models.explain.span.years': '{n} an',
  'models.explain.span.steps': '{n} pas',
  'models.explain.calendar.hour': 'Heure du jour',
  'models.explain.calendar.day_of_week': 'Jour de la semaine',
  'models.explain.calendar.day_of_month': 'Jour du mois',
  'models.explain.calendar.day_of_year': 'Jour de l’année',
  'models.explain.calendar.is_weekend': 'Week-end',
  'models.explain.calendar.week': 'Semaine de l’année',
  'models.explain.calendar.month': 'Mois',
  'models.explain.calendar.quarter': 'Trimestre',
  'models.explain.calendar.year': 'Année',
  'models.explain.feature.series': 'Série',
  'models.explain.model': 'Paramètres du modèle',
  'models.explain.model.hint':
    'Un modèle statistique s’explique par ses paramètres ajustés : lissage du niveau et de la saison (ETS), coefficients (ARIMA).',
  'models.explain.model.aic': 'AIC {aic}',
  'models.explain.naive':
    'Le naïf saisonnier répète la dernière saison ({season} pas) : il n’a rien d’autre à expliquer.',
  'models.explain.unavailable': 'L’explication n’a pas pu être calculée pour ce modèle.',
  'models.explain.approximate':
    'Forêt profonde : attributions approchées (Saabas), additives mais moins fines que la SHAP exacte.',
  'models.analysis.title': 'Anatomie de la série',
  'models.analysis.hint':
    'Mesurée sur l’historique seul : saisonnalité et tendance (décomposition STL), autocorrélation, stationnarité (test ADF).',
  'models.analysis.season.strong': 'Saisonnalité forte ({value}) · période {period}',
  'models.analysis.season.moderate': 'Saisonnalité modérée ({value}) · période {period}',
  'models.analysis.season.weak': 'Saisonnalité faible ({value})',
  'models.analysis.trend.strong': 'Tendance forte ({value})',
  'models.analysis.trend.moderate': 'Tendance modérée ({value})',
  'models.analysis.trend.weak': 'Tendance faible ({value})',
  'models.analysis.stationary': 'Revient à son niveau (ADF p {p})',
  'models.analysis.unit_root': 'Dérive sans revenir (ADF p {p})',
  'models.analysis.acf': 'Ressemblance avec son passé',
  'models.analysis.acf.hint':
    'Autocorrélation aux retards du modèle et aux multiples de la saison : ce qui justifie de regarder si loin en arrière.',
  'models.analysis.acf.noise': 'bruit',
  'models.analysis.suggested': 'Retards que suggère l’autocorrélation partielle : {lags}',
  'models.diagnostic.title': 'Le régresseur seul, un pas en avant',
  'models.diagnostic.hint':
    'Réentraîné sur les {train} lignes les plus anciennes et jugé par skore sur les {test} suivantes. Bon ici et faible au backtest : l’erreur vient de la récursion qui s’accumule ; faible ici aussi : des variables.',
  'models.diagnostic.fit': 'Prévu contre réel (un pas)',
  'models.explain.peak.title': 'Pourquoi ce pic',
  'models.explain.peak.sentence': 'Partant d’une base de {base}, {series} atteint {pred} le {when}.',
  'models.explain.peak.groups': 'Ce qui l’a monté ou baissé',
  'models.explain.peak.features': 'Variables les plus fortes',
  'models.excursions.title': 'Hors de l’intervalle',
  'models.excursions.hint':
    '{count} réels du backtest sont sortis de la bande ({share}) ; les plus loin d’abord.',
  'models.excursions.above': '{actual} au-dessus de {bound}',
  'models.excursions.below': '{actual} sous {bound}',
  'models.evidence.roc': 'Courbe ROC',
  'models.evidence.roc.hint':
    'Plus la courbe monte vite vers le coin haut-gauche, mieux le modèle sépare. La diagonale est le hasard. Survolez la courbe pour lire un point de fonctionnement.',
  'models.evidence.roc.x': 'Faux positifs',
  'models.evidence.roc.y': 'Vrais positifs',
  'models.evidence.roc.point': '{tpr} de vrais positifs pour {fpr} de faux positifs',
  'models.evidence.pr': 'Précision / rappel',
  'models.evidence.pr.hint':
    'Ce que coûte chaque point de rappel en précision. La ligne basse est la proportion de positifs. Survolez la courbe pour lire un point de fonctionnement.',
  'models.evidence.pr.x': 'Rappel',
  'models.evidence.pr.y': 'Précision',
  'models.evidence.pr.point': 'Précision {precision} à {recall} de rappel',
  'models.evidence.fit': 'Prédit contre réel',
  'models.evidence.fit.hint':
    'Chaque point est une ligne de test. Plus le nuage colle à la diagonale, plus le modèle tombe juste.',
  'models.evidence.fit.x': 'Réel',
  'models.evidence.fit.y': 'Prédit',
  'models.evidence.fit.point': 'Prédit {predicted} pour un réel de {actual}',
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
  'models.evidence.delta.against': 'Écarts mesurés contre la v{version}',

  // ---- comparaison de versions -------------------------------------------
  'models.compare.hint':
    'Deux versions du même modèle, sur les mêmes métriques. Seules celles que les deux ont produites sont comparables.',
  'models.compare.metric': 'Métrique',
  'models.compare.before': 'Avant',
  'models.compare.after': 'Après',
  'models.compare.move': 'Écart',
  'models.compare.none.title': 'Rien à comparer pour l’instant',
  'models.compare.none.description':
    'La comparaison s’ouvre dès qu’une deuxième version a été entraînée : réentraînez pour voir bouger les scores.',
  'models.compare.verdict.better':
    'v{version} : {metric} {delta} contre la v{previous}. Ce réentraînement mérite d’être mis en service.',
  'models.compare.verdict.worse':
    'v{version} : {metric} {delta} contre la v{previous}. Gardez la version précédente en service.',
  'models.compare.verdict.flat':
    'v{version} : {metric} inchangé contre la v{previous}. Rien n’oblige à changer ce qui répond.',

  // ---- suivi (dérive + feedback) ------------------------------------------
  'models.monitor.empty.title': 'Rien à mesurer',
  'models.monitor.empty.description':
    'Chaque prédiction est journalisée. Appelez le modèle, puis revenez ici.',
  'models.monitor.window': '{predictions} appels · {labeled} annotés',
  'models.monitor.data': 'Dérive des données',
  'models.monitor.score': 'Dérive des scores',
  'models.monitor.concept': 'Dérive du concept',
  'models.monitor.status.ok': 'Stable',
  'models.monitor.status.watch': 'Attention',
  'models.monitor.status.alert': 'Alerte',
  'models.monitor.status.unknown': 'Pas encore',
  'models.monitor.features': 'Variables',
  'models.monitor.auc': 'AUC d’entraînement et AUC glissante',
  'models.monitor.auc.x': 'Fenêtre',
  'models.monitor.auc.y': 'AUC',
  'models.monitor.feedback': 'Issue réelle',
  'models.monitor.feedback.hint':
    'Collez l’identifiant renvoyé par la prédiction, puis l’issue réelle.',
  'models.monitor.feedback.id': 'Prédiction',
  'models.monitor.feedback.label': 'Issue',
  'models.monitor.feedback.submit': 'Enregistrer',
  'models.monitor.feedback.done': 'Issue enregistrée',
  'models.monitor.feedback.failed': 'L’enregistrement a échoué',
  'models.monitor.dataset': 'Créer un jeu de données',
  'models.monitor.dataset.hint':
    'Les lignes annotées deviennent un jeu que l’atelier peut réentraîner.',
  'models.monitor.dataset.done': 'Jeu « {name} » créé',
  'models.monitor.dataset.failed': 'Pas assez de lignes annotées',
  'models.monitor.retrain': 'Réentraîner sur ce jeu',

  // ---- comparaison sur les mêmes lignes -----------------------------------
  'models.compare.same.title': 'Comparer sur les mêmes lignes',
  'models.compare.same.hint':
    'Le tableau ci-dessus rapproche deux résultats enregistrés, chacun mesuré sur son propre découpage. Ici les deux modèles sont réévalués sur un seul jeu de test : l’écart devient une propriété des modèles, pas de l’échantillonnage.',
  'models.compare.same.action': 'Réévaluer les deux versions',
  'models.compare.same.running': 'Réévaluation en cours…',
  'models.compare.same.provenance':
    '{rows} lignes de test · {dataset} v{version} · table jointe calculée par skore',
  'models.compare.same.warn.TRAINED_ON_ANOTHER_DATASET':
    'Une des versions a été entraînée sur un autre jeu de données : certaines de ces lignes ont pu servir à son apprentissage, sa colonne peut donc être flattée.',
  'models.compare.same.warn.DIFFERENT_SPLIT_SIZE':
    'Les deux versions n’ont pas été entraînées avec la même taille de test ; le découpage utilisé ici est celui de la version la plus récente.',
  'models.compare.failed': 'Ces deux versions n’ont pas pu être évaluées sur les mêmes lignes.',
  'models.compare.error.ml_compare_same_version':
    'Une version ne se compare pas à elle-même.',
  'models.compare.error.ml_compare_cross_workspace':
    'Ces deux modèles appartiennent à des espaces de travail différents.',
  'models.compare.error.ml_compare_different_question':
    'Ces versions ne répondent pas à la même question : un seul tableau ne peut pas les classer.',
  'models.compare.error.ml_compare_not_tabular':
    'Seuls les modèles tabulaires sont re-notés sur un même découpage ; une prévision se compare par son backtest.',
  'models.compare.error.ml_compare_no_common_dataset':
    'Aucun des deux jeux d’entraînement ne porte toutes les colonnes nécessaires aux deux modèles.',
  'models.compare.error.ml_compare_dataset_too_large':
    'Ce jeu de données dépasse le plafond de lignes autorisé pour une comparaison.',
  'models.compare.error.ml_compare_split_failed':
    'Le découpage de test n’a pas pu être reconstruit sur ce jeu de données.',
  'models.compare.error.ml_compare_failed':
    'Ces deux versions n’ont pas pu être évaluées sur les mêmes lignes.',

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
  'models.metric.log_loss': 'Log loss',
  'models.metric.brier_score': 'Score de Brier',
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
  'models.metric.log_loss.hint':
    'Pénalise les erreurs commises avec assurance. Plus bas est meilleur : il dit si la probabilité est honnête, pas seulement la réponse.',
  'models.metric.brier_score.hint':
    'Erreur quadratique moyenne de la probabilité annoncée. Plus bas est meilleur — le chiffre derrière une jauge qu’on veut croire.',
  'models.metric.mase': 'MASE',
  'models.metric.rmsse': 'RMSSE',
  'models.metric.smape': 'sMAPE',
  'models.metric.coverage': 'Couverture',
  'models.metric.interval_width': 'Largeur d’intervalle',
  'models.metric.mase.hint':
    'Erreur rapportée à celle d’une prévision qui répète la dernière saison. Sous 1, le modèle fait mieux que cette référence.',
  'models.metric.rmsse.hint':
    'Comme la MASE, mais les grosses erreurs pèsent plus. Sous 1, mieux que répéter la dernière saison.',
  'models.metric.smape.hint': 'Écart moyen en pourcentage, symétrique entre sur- et sous-prévision.',
  'models.metric.coverage.hint':
    'Part des valeurs réelles tombées dans l’intervalle annoncé. À comparer au niveau demandé, pas à maximiser.',
  'models.metric.interval_width.hint': 'Largeur moyenne de l’intervalle, dans l’unité de la colonne prévue.',
  'models.family.tabular': 'Tabulaire',
  'models.family.forecasting': 'Prévision',
  'models.spec.time_column': 'Colonne de date',
  'models.spec.time_column.hint': 'L’horodatage de chaque mesure. Il fixe l’ordre et le pas de la série.',
  'models.spec.shape': 'Forme',
  'models.spec.shape.hint': 'Une série, un panel de séries semblables, ou une série prévue à partir d’autres.',
  'models.spec.shape.single': 'Une série',
  'models.spec.shape.panel': 'Panel de séries',
  'models.spec.shape.multivariate': 'Multivariée',
  'models.spec.series_columns': 'Colonnes de série',
  'models.spec.series_columns.hint': 'Ce qui distingue une série d’une autre dans le panel : la cellule, le magasin.',
  'models.spec.horizon': 'Horizon',
  'models.spec.horizon.hint': 'Combien de pas prévoir, dans l’unité de la fréquence.',
  'models.spec.frequency': 'Fréquence',
  'models.spec.frequency.hint': 'Le pas entre deux mesures. « Auto » le déduit des dates.',
  'models.spec.frequency.auto': 'Auto',
  'models.spec.frequency.h': 'Horaire',
  'models.spec.frequency.d': 'Quotidienne',
  'models.spec.frequency.w': 'Hebdomadaire',
  'models.spec.frequency.ms': 'Mensuelle',
  'models.spec.frequency.qs': 'Trimestrielle',
  'models.spec.strategy': 'Stratégie',
  'models.spec.strategy.hint': 'Récursive : un modèle qui réutilise ses prévisions. Directe : un modèle par pas d’horizon.',
  'models.spec.strategy.recursive': 'Récursive',
  'models.spec.strategy.direct': 'Directe',
  'models.spec.lags': 'Retards',
  'models.spec.lags.hint': 'Les valeurs passées que le modèle regarde : 1 = le pas précédent, 24 = la même heure hier.',
  'models.spec.exog': 'Covariables',
  'models.spec.exog.hint': 'Les autres colonnes qui aident à prévoir, avec ce que l’on en sait à l’avance.',
  'models.spec.exog.future': 'Connue à l’avance',
  'models.spec.exog.static': 'Propre à la série',
  'models.spec.exog.past': 'Connue jusqu’à maintenant',
  'models.spec.calendar': 'Calendrier',
  'models.spec.calendar.hint': 'Ajoute l’heure, le jour de la semaine et le mois comme variables.',
  'models.spec.interval_level': 'Niveau d’intervalle',
  'models.spec.interval_level.hint': 'La part des valeurs réelles que l’intervalle doit contenir.',
  'models.spec.backtest_folds': 'Backtests',
  'models.spec.backtest_folds.hint': 'Combien d’horizons passés rejouer pour mesurer l’erreur, sans que le modèle les ait vus.',
  'models.spec.fill': 'Trous dans la série',
  'models.spec.fill.hint': 'Que faire d’un pas ou d’une valeur manquante.',
  'models.spec.fill.refuse': 'Refuser',
  'models.spec.fill.interpolate': 'Interpoler',
  'models.spec.fill.zero': 'Mettre à zéro',
  'models.family.reason.no_worker': 'Aucun worker capable d’entraîner ces modèles n’est actif.',
  'models.family.reason.runtime_missing': 'L’environnement d’entraînement de cette famille n’est pas installé.',
  'models.family.reason.disabled': 'L’entraînement est désactivé sur ce déploiement.',

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

  // ---- atelier de prédiction ---------------------------------------------
  'models.play.unavailable.title': 'Ce modèle ne répond pas encore',
  'models.play.unavailable.no_forecast_worker':
    'Aucun worker de prévision ne répond pour le moment : démarrez le service ml-ts pour interroger ce modèle.',
  'models.play.forecast.ask': 'Ce que vous demandez',
  'models.play.forecast.run': 'Prévoir',
  'models.play.forecast.covariates':
    'Valeurs prévues de {names}, appliquées à chaque pas de l’horizon.',
  'models.play.forecast.covariates_undated':
    'Ce modèle a besoin de valeurs futures, mais son pas ne permet pas de les dater ici : passez-les par l’API.',
  'models.play.forecast.answer': 'Ce que le modèle prévoit',
  'models.play.forecast.empty': 'Choisissez un horizon et lancez la prévision.',
  'models.play.forecast.timing.cached': 'répondu en {ms} ms',
  'models.play.forecast.timing.cold': 'répondu en {ms} ms, dont {load} ms de chargement',
  'models.play.forecast.peak': 'Pic prévu : {value} le {when}. À {level}, il peut monter jusqu’à {upper}.',
  'models.play.forecast.peak_plain': 'Pic prévu : {value} le {when}.',
  'models.play.forecast.failed': 'La prévision a échoué.',
  'models.play.unavailable.untrained':
    'Un modèle répond une fois entraîné : lancez l’entraînement, le formulaire se construira depuis son contrat.',
  'models.play.unavailable.disabled':
    'La prédiction n’est pas activée sur cette instance. Un administrateur peut l’ouvrir dans la configuration.',
  'models.play.inputs': 'Le client à évaluer',
  'models.play.inputs.hint':
    'Champs construits depuis le contrat du modèle et pré-remplis avec une ligne typique de l’entraînement. Changez une valeur, la réponse suit.',
  'models.play.run': 'Prédire',
  'models.play.reset': 'Revenir à la ligne typique',
  'models.play.answer': 'Ce que le modèle répond',
  'models.play.idle': 'Lancez une prédiction pour voir la réponse.',
  'models.play.probability': 'probabilité que {target} vaille {label}',
  'models.play.predicted': 'Réponse : {label}',
  'models.play.estimate': '{target} estimé',
  'models.play.range': 'plage vue à l’entraînement',
  'models.play.range.bounds': '{min} → {max}',
  'models.play.why': 'Ce qui a fait cette réponse',
  'models.play.why.typical': 'valeur typique : {value}',
  'models.play.why.hint':
    'Chaque barre est mesurée : le modèle est réinterrogé avec ce seul champ ramené à sa valeur typique, l’écart est ce qu’il a coûté.',
  'models.play.timing': 'Répondu en {ms} ms',
  'models.play.prediction_id': 'Prédiction {id}',
  'models.play.served': 'répondu par la v{version}',
  'models.play.failed': 'La prédiction a échoué',
  'models.play.curl': 'Le même appel, depuis un système',
  'models.play.curl.hint':
    'Exactement la requête que ce formulaire vient d’envoyer : même route, même corps, seule la preuve d’identité change.',
  'models.play.copy': 'Copier',
  'models.play.copied': 'Copié',

  // ---- clés API -----------------------------------------------------------
  'models.keys.title': 'Clés d’accès',
  'models.keys.hint':
    'Une clé n’ouvre que la prédiction de ce modèle, et rien d’autre de l’API. Le secret n’est montré qu’une fois.',
  'models.keys.name.placeholder': 'Nom de la clé',
  'models.keys.name.default': 'Clé de démonstration',
  'models.keys.mint': 'Créer une clé',
  'models.keys.minted': 'Clé créée',
  'models.keys.minted.hint':
    'Copiez-la maintenant : elle n’est stockée que sous forme de hachage et ne sera plus jamais affichée.',
  'models.keys.col.name': 'Nom',
  'models.keys.col.prefix': 'Préfixe',
  'models.keys.col.uses': 'Appels',
  'models.keys.col.state': 'État',
  'models.keys.live': 'Active',
  'models.keys.revoked': 'Révoquée',
  'models.keys.revoke': 'Révoquer',
  'models.keys.revoked.toast': '« {name} » ne répond plus',
  'models.keys.uses': '{count} appels',

  // ---- publier comme skill ------------------------------------------------
  'models.publish.title': 'Publier comme skill',
  'models.publish.hint':
    'Le modèle devient une skill de l’espace de travail, typée depuis son contrat : appelable dans un système ou dans le chat, figée sur cette lignée.',
  'models.publish.action': 'Publier comme skill',
  'models.publish.live': 'Publiée',
  'models.publish.open': 'Ouvrir dans le catalogue',
  'models.publish.withdraw': 'Retirer du catalogue',
  'models.publish.done':
    '« {name} » est dans le catalogue de skills — cliquez pour l’ouvrir',
  'models.publish.withdrawn': 'La skill a été retirée du catalogue',
  'models.publish.provenance': 'Modèle {name} v{version} — {evidence}',

  // ---- refus du plan de service ------------------------------------------
  'models.serving.error.ml_predict_disabled':
    'La prédiction n’est pas activée sur cette instance.',
  'models.serving.error.ml_predict_rows_required':
    'Aucune ligne à prédire n’a été envoyée.',
  'models.serving.error.ml_predict_row_not_object':
    'Chaque ligne doit être un objet champ → valeur.',
  'models.serving.error.ml_predict_too_many_rows':
    'Trop de lignes dans un seul appel : découpez la demande.',
  'models.serving.error.ml_predict_field_unknown':
    'Un champ envoyé ne fait pas partie du contrat du modèle.',
  'models.serving.error.ml_predict_field_missing':
    'Il manque un champ que le modèle attend.',
  'models.serving.error.ml_predict_field_not_numeric':
    'Un champ numérique a reçu une valeur qui n’est pas un nombre.',
  'models.serving.error.ml_predict_field_not_boolean':
    'Un champ booléen a reçu une valeur qui n’est ni vraie ni fausse.',
  'models.serving.error.ml_predict_failed':
    'Le modèle n’a pas pu répondre sur cette ligne.',
  'models.serving.error.ml_contract_missing':
    'Ce modèle n’a pas de contrat d’entrée : réentraînez-le.',
  'models.serving.error.ml_artifact_unloadable':
    'L’artefact du modèle est introuvable ou illisible dans le stockage.',
  'models.serving.error.ml_nothing_serves':
    'Aucune version de ce modèle n’est en service.',
  'models.serving.error.ml_version_unknown':
    'Cette version n’existe pas dans cette lignée.',
  'models.serving.error.ml_model_not_ready': 'Seul un modèle entraîné peut répondre.',
  'models.serving.error.ml_model_not_found':
    'Ce modèle n’existe pas dans cet espace de travail.',
  'models.serving.error.ml_score_too_many_rows':
    'Ce jeu de données dépasse le plafond de lignes autorisé au scoring.',
  'models.serving.error.ml_score_column_missing':
    'Il manque au jeu de données une colonne que le modèle attend.',
  'models.serving.error.ml_key_limit':
    'Ce modèle a atteint son nombre maximal de clés actives.',
  'models.serving.error.ml_key_not_found': 'Cette clé n’existe pas sur ce modèle.',
  'models.serving.error.ml_key_required': 'Aucune preuve d’identité fournie.',
  'models.serving.error.ml_key_invalid': 'Cette clé n’est pas reconnue.',
  'models.serving.error.ml_key_revoked': 'Cette clé a été révoquée.',
  'models.serving.error.ml_key_wrong_model':
    'Cette clé a été créée pour un autre modèle.',
  'models.serving.error.ml_publish_name_taken':
    'Une skill porte déjà ce nom dans cet espace de travail.',
  'models.serving.error.ml_publish_name_invalid':
    'Le nom du modèle ne donne pas un identifiant de skill valide.',
  'models.serving.error.ml_use_forecast_route':
    'Un modèle de prévision répond pour un horizon, pas pour des lignes : il est servi par le worker de prévision.',
  'models.serving.error.ml_forecast_timeout':
    'Le worker de prévision n’a pas répondu à temps. Réessayez dans un instant.',
  'models.serving.error.ml_forecast_input_invalid':
    'Les valeurs futures envoyées ne couvrent pas l’horizon demandé.',
  'models.serving.error.ml_forecast_params_invalid':
    'L’horizon et le niveau d’intervalle doivent être des nombres valides.',
  'models.serving.error.ml_forecast_horizon_invalid':
    'Cet horizon dépasse ce que ce modèle sait prévoir.',
  'models.serving.error.ml_forecast_failed':
    'La prévision a échoué dans le worker.',
  'models.serving.error.ml_forecast_too_many_rows':
    'Trop de lignes de valeurs futures pour un seul appel.',
  'models.serving.error.ml_artifact_tampered':
    'L’artefact stocké n’est pas celui produit par l’entraînement : il est refusé.',
  'models.serving.error.ml_artifact_unverified':
    'Ce modèle a été enregistré sans les empreintes que le service vérifie.',
  'models.serving.error.ml_use_predict_route':
    'Ce modèle répond pour des lignes : utilisez /predict.',
  'models.serving.error.ml_family_unavailable':
    'Aucun worker capable de servir ce modèle n’est actif pour le moment.',

  // ---- versions -----------------------------------------------------------
  'models.versions.label': 'v{version}',
  'models.versions.current': 'Version affichée',
  'models.versions.serving': 'Répond',
  'models.versions.challenger': 'Prétendante',
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
  'models.setup.evaluation': 'Évaluation conservée',
  'models.setup.evaluation.value': '{size} — rapport skore {skore}, rechargeable',
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
  'models.refusal.ml_spec_invalid':
    'La définition du problème contient un champ invalide pour cette famille de modèles.',
  'models.refusal.ml_family_unavailable':
    'Aucun worker capable d’entraîner cette famille de modèles n’est actif pour le moment.',
  'models.refusal.ml_model_not_ready': 'Seul un modèle entraîné peut répondre.',
  'models.refusal.ml_model_not_found':
    'Ce modèle n’existe pas dans cet espace de travail.',
  'models.refusal.ml_ts_time_column_required': 'Choisissez la colonne de date de la série.',
  'models.refusal.ml_ts_time_column_not_datetime':
    'Cette colonne n’est pas une date : la série ne peut pas être ordonnée.',
  'models.refusal.ml_ts_column_reused':
    'Cette colonne est déjà la cible ou la colonne de date.',
  'models.refusal.ml_ts_exog_not_numeric':
    'Une covariable doit être numérique, sauf si elle est propre à la série.',
  'models.refusal.ml_ts_past_needs_multivariate':
    'Une colonne connue seulement jusqu’à maintenant ne sert qu’en prévision multivariée.',
  'models.refusal.ml_ts_static_needs_panel':
    'Une colonne propre à la série n’a de sens que dans un panel.',
  'models.refusal.ml_ts_multivariate_needs_series':
    'Une prévision multivariée a besoin d’au moins une autre série connue jusqu’à maintenant.',
  'models.refusal.ml_ts_duplicate_timestamps':
    'Des dates se répètent : ce jeu contient plusieurs séries. Indiquez les colonnes qui les distinguent.',
  'models.refusal.ml_ts_too_many_series':
    'Trop de séries pour un seul modèle de panel sur ce déploiement.',
  'models.refusal.ml_ts_algo_shape_mismatch':
    'Cet algorithme traite une série à la fois : choisissez un régresseur pour un panel ou une prévision multivariée.',
  'models.refusal.ml_ts_history_too_short':
    'Trop peu d’historique pour cet horizon, ces retards et ces backtests.',

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
  'models.error.ml_runtime_missing':
    'Le worker qui a reçu l’entraînement n’a pas les bibliothèques de cette famille de modèles.',
  'models.error.ml_ts_series_unusable':
    'La série a des trous, des dates en double ou aucun pas régulier. Choisissez une politique de remplissage ou corrigez les données.',
  'models.error.ml_ts_history_too_short':
    'Une fois la série mise au pas, il reste trop peu d’historique pour cet horizon.',

  // ---- plan désactivé -----------------------------------------------------
  'models.disabled.title': 'Plan modèles désactivé',
  'models.disabled.description':
    'L’entraînement de modèles n’est pas activé sur cette instance. Un administrateur peut l’ouvrir dans la configuration.',
} as const;

export const MODELS_EN: Record<keyof typeof MODELS_FR, string> = {
  'models.refusal.ml_label_review_required': 'Confirm the labels at the Flow human gate before using them as a training target.',
  'models.refusal.ml_label_review_changed': 'Provenance changed after submission. Select the reviewed dataset again.',
  'models.refusal.ml_label_review_invalid': 'The labels do not match their review evidence. Review the dataset again.',
  'models.refusal.ml_distillation_source_required': 'Inference cost applies only to the confirmed target of a dataset labeled by an LLM and then reviewed.',
  'models.spec.distillation_inference_cost_per_1000': 'Estimated model cost per 1,000 predictions (USD)',
  'models.spec.distillation_inference_cost_per_1000.hint': 'Optional, from 0 to 1,000 USD, only for the confirmed target of a dataset labeled by an LLM and then reviewed. Blank means unavailable; zero must be entered explicitly.',
  'models.distillation.title': 'Distillation after human review',
  'models.distillation.held_out': 'Comparisons on the same {count} test rows, excluded from training.',
  'models.distillation.agreement': 'Model agreement with the LLM',
  'models.distillation.reviewed_accuracy': 'Model accuracy against human labels',
  'models.distillation.teacher_accuracy': 'LLM accuracy against human labels',
  'models.distillation.llm_cost': 'Estimated LLM cost per 1,000 labels',
  'models.distillation.model_cost': 'Estimated model cost per 1,000 predictions',
  'models.distillation.cost_hint': 'Amounts in USD: the LLM estimate uses declared token prices and the inference estimate is supplied by the author. These are not provider invoices.',
  'models.distillation.unknown_attempts': '{count} attempts with unknown usage remain included in the reserved LLM budget.',
  'models.distillation.reviewed': '{total} rows confirmed by a person, including {corrected} corrected classes.',
  'models.distillation.teacher': 'Source language model',
  'models.distillation.dataset': 'Open the reviewed dataset',
  'models.distillation.unavailable': 'Unavailable',
  'models.spec.intervals': 'Prediction intervals',
  'models.spec.intervals.off': 'Off',
  'models.spec.intervals.conformal': 'Cross-validation',
  'models.spec.intervals.hint': 'Estimate a range from cross-validation errors, keeping all training rows in the final fit.',
  'models.intervals.title': 'Interval coverage',
  'models.intervals.level': 'Requested level',
  'models.intervals.coverage': 'Test coverage',
  'models.intervals.width': 'Mean width',
  'models.intervals.hint': 'Computed from {rows} training rows across {folds} folds. Coverage is measured on the test against the requested level.',
  'models.intervals.band': '{level} interval',
  'models.serving.error.ml_interval_level_unknown': 'This level was not calibrated. Choose one of the available levels.',
  'models.spec.calibration': "Probability calibration",
  'models.spec.calibration.hint': "Adjusts probabilities on 20% of training data. The test measures the result without influencing this adjustment.",
  'models.spec.calibration.off': "Off",
  'models.spec.calibration.auto': "Automatic",
  'models.spec.calibration.sigmoid': "Sigmoid",
  'models.spec.calibration.isotonic': "Isotonic",
  'models.spec.threshold': "Decision threshold",
  'models.spec.threshold.hint': "Binary classification: choose the threshold on calibration data, or with cross-validation of training data.",
  'models.spec.threshold.default': "Default (50%)",
  'models.spec.threshold.f1': "Best F1",
  'models.spec.threshold.youden': "Youden index",
  'models.calibration.title': "Probability reliability",
  'models.calibration.rows': "{fit} fitted rows · {calibration} calibration rows",
  'models.calibration.before': "Before calibration",
  'models.calibration.after': "After calibration",
  'models.calibration.hint': "Measured on the same test. Lower Brier and log loss are better.",
  'models.calibration.worse': "Calibration worsens at least one test measure. The selected calibration remains applied.",
  'models.calibration.x': "Predicted probability",
  'models.calibration.y': "Observed frequency",
  'models.decision.title': "Decision threshold",
  'models.decision.hint': "Chosen outside the test using “{criterion}”. Results below are measured on the test.",
  'models.decision.default': "50% threshold",
  'models.decision.tuned': "Selected threshold",
  'models.play.threshold': "Decision threshold: {threshold}",
  "models.error.ML_CALIBRATION_TOO_FEW": "Calibration skipped: at least 200 calibration rows and 20 examples per class are required.",
  "models.error.ML_THRESHOLD_TOO_FEW": "Default threshold kept: too few examples per class for cross-validation.",
  "models.error.ML_THRESHOLD_BINARY_ONLY": "Custom threshold ignored: it only applies to two classes.",
  'models.spec.tuning': "Automatic tuning",
  'models.spec.tuning.off': "Off",
  'models.spec.tuning.budget': "Tune automatically",
  'models.spec.tuning.hint': "Compare settings using cross-validation within the chosen budget.",
  'models.spec.tuning_trials': "Maximum trials",
  'models.spec.tuning_trials.hint': "The first trial uses your settings. From 5 to 100 trials.",
  'models.spec.tuning_budget_s': "Tuning budget (seconds)",
  'models.spec.tuning_budget_s.hint': "At most 60% of the training timeout, leaving time for the final model.",
  'models.tuning.title': "Automatic tuning",
  'models.tuning.validation': "{metric} · cross-validation on {folds} training folds",
  'models.tuning.chart': "Validation score by trial",
  'models.tuning.trial': "Trial",
  'models.tuning.start': "Start",
  'models.tuning.best': "Best",
  'models.tuning.trials': "Trial limit reached",
  'models.tuning.budget': "Budget exhausted",
  'models.tuning.counts': "{run} trials · {pruned} pruned · {failed} failed",
  'models.tuning.baseline_unavailable': "The baseline could not be evaluated within the budget. Your settings are retained, with no measured gain.",
  'models.tuning.knobs': "Settings before and after",
  'models.tuning.setting': "Setting",
  'models.tuning.auto': "Automatic",
  'models.tuning.hint': "The best score is selected on training data. Card scores are measured on the test set, kept separate from tuning.",
  'models.warning.ml_tuning_estimate': "Indicative trial duration: {estimated_s} s (budget: {budget_s} s), estimated from the previous version.",
  'models.warning.ml_tuning_budget_limited': "The budget may stop the search before all trials complete.",
  'models.explain.missing': "is missing",
  'models.explain.present': "is present",
  'models.explain.or': "or",
  'models.spec.explain': "Model explanations",
  'models.spec.explain.hint': "Explore errors, a simplified tree and feature effects on the test, within a 60-second budget.",
  'models.spec.explain.off': "Off",
  'models.spec.explain.pack': "Explanation pack",
  'models.spec.fairness_columns': "Compare groups",
  'models.spec.fairness_columns.hint': "Up to 3 columns with at most 12 groups each, even when the model does not use them.",
  'models.explain.errors.title': "Where the model makes errors",
  'models.explain.rows': "Measured on {rows} test rows.",
  'models.explain.errors.global': "Overall error: {value}",
  'models.explain.errors.rule': "{rows} rows · error {value}",
  'models.explain.surrogate.title': "A simplified view of the decision",
  'models.explain.surrogate.fidelity': "Fidelity: {value}",
  'models.explain.surrogate.hint': "Depth-3 tree. Fidelity is measured on rows separate from those used to fit this tree.",
  'models.explain.surrogate.complex': "The model is too complex for a depth-3 tree to explain faithfully (below 70%).",
  'models.explain.support': "{rows} rows",
  'models.explain.all': "All rows",
  'models.explain.and': "and",
  'models.explain.budget': "Explanation budget reached; other results remain available.",
  'models.explain.section_unavailable': "This explanation could not be calculated. The model remains available.",
  'models.explain.pdp.title': "Effect of {feature}",
  'models.explain.pdp.average': "Average effect",
  'models.explain.pdp.hint': "Strong line: average effect. Thin lines: changes for individual rows, keeping other values fixed.",
  'models.explain.pdp.class': "Probability of class {label}",
  'models.explain.fairness.title': "Group comparison · {column}",
  'models.explain.fairness.hint': "Groups with fewer than 30 rows are shown but excluded from ratios.",
  'models.explain.fairness.selection_ratio': "Selection-rate ratio: {value}",
  'models.explain.fairness.odds': "Maximum TPR/FPR gap: {value}",
  'models.explain.fairness.mae_gap': "MAE gap relative to overall error: {value}",
  'models.explain.fairness.signal': "The selection-rate ratio is below 80%.",
  'models.explain.fairness.group': "Group",
  'models.explain.fairness.rows': "Rows",
  'models.explain.fairness.low_support': "Low support",
  'models.explain.metric.selection_rate': "Selection rate",
  'models.explain.metric.tpr': "True positive rate",
  'models.explain.metric.fpr': "False positive rate",
  'models.explain.metric.accuracy': "Accuracy",
  'models.explain.metric.mae': "MAE",
  'models.explain.metric.bias': "Mean bias",


  'models.spec.text_encoder': "Text encoding",
  'models.spec.text_encoder.auto': "Automatic",
  'models.spec.text_encoder.string': "TF-IDF and SVD",
  'models.spec.text_encoder.minhash': "MinHash",
  'models.spec.text_encoder.hint': "For columns with many distinct texts. Automatic preserves the usual behavior.",
  'models.tabular.text_columns': "Detected text columns: {columns}",

  'models.eyebrow': 'Data & Models · Models',
  'models.title': 'Models',
  'models.list.go_data': 'Datasets',
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
  'models.list.filter.forecasting': 'Forecasts',
  'models.list.filter.serving': 'Serving',
  'models.list.col.model': 'Model',
  'models.list.col.target': 'Target',
  'models.list.col.dataset': 'Training dataset',
  'models.list.col.served': 'Served version',
  'models.list.col.score': 'Score',
  'models.list.col.monitor': 'Monitor',
  'models.list.meta': '{rows} rows · {features} features · {duration}',
  'models.list.target': 'Predicts {target}',
  'models.list.dataset': 'from {dataset}',
  'models.list.dataset.none': '—',
  'models.list.monitor.ok': 'Steady',
  'models.list.monitor.watch': 'Watch',
  'models.list.monitor.alert': 'Alert',
  'models.list.monitor.none': '—',
  'models.list.served': 'v{version} answers',
  'models.list.served.progress': 'v{version} in progress',
  'models.list.served.none': 'none answers',

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
  'models.task.forecasting': 'Forecasting',
  'models.task.forecasting.hint':
    'Predicts what comes next in a dated series: tomorrow’s cell load, next month’s sales, with an interval.',
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
  'models.algo.ets': 'Exponential smoothing (ETS)',
  'models.algo.arima': 'Seasonal ARIMA',
  'models.algo.seasonal_naive': 'Seasonal naive',
  'models.algo.ets.hint':
    'One statistical model per series: trend and seasonality, with its own intervals. Solid on short history.',
  'models.algo.arima.hint':
    'The time-series classic: autocorrelation and seasonality, one series at a time.',
  'models.algo.seasonal_naive.hint':
    'Repeats the last season. The yardstick every forecast has to beat.',
  'models.tag.tabular': 'Tabular',
  'models.tag.fast': 'Fast',
  'models.tag.robust': 'Robust',
  'models.tag.explainable': 'Explainable',
  'models.tag.baseline': 'Baseline',
  'models.tag.interpretable': 'Interpretable',
  'models.tag.statistical': 'Statistical',
  'models.tag.seasonal': 'Seasonal',

  'models.studio.title': 'Train a model',
  'models.studio.subtitle':
    'Three decisions: on what, what to predict, with which algorithm.',
  'models.studio.close': 'Close',
  'models.studio.dataset.label': 'Dataset',
  'models.studio.dataset.placeholder': 'Choose a dataset',
  'models.studio.dataset.meta': '{rows} rows · {columns} columns',
  'models.studio.dataset.sample': 'What the model will read',
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
  'models.studio.plan.forecast': '{horizon} steps ahead · {folds} backtests',
  'models.studio.forecast.no_time': 'This dataset has no date column: a forecast needs dates.',
  'models.studio.forecast.unused': 'Not used',
  'models.studio.forecast.no_covariates': 'No other usable column.',
  'models.studio.forecast.lags_auto': 'From the frequency',
  'models.studio.forecast.lags_invalid': 'Positive whole numbers, separated by commas.',
  'models.studio.plan.features': '{count} features kept',
  'models.studio.submit': 'Start training',
  'models.studio.submitting': 'Starting…',
  'models.studio.queued': '“{name}” is training',
  'models.studio.failed': 'Starting the training run failed',

  'models.detail.back': 'Back to models',
  'models.detail.gone.title': 'That model cannot be found',
  'models.detail.gone.description':
    'It was deleted, or the link points at an id that does not exist in this workspace.',
  'models.detail.tab.evidence': 'Results',
  'models.detail.tab.play': 'Predict',
  'models.detail.tab.compare': 'Comparison',
  'models.detail.tab.monitor': 'Monitoring',
  'models.detail.tab.contract': 'Input contract',
  'models.detail.tab.versions': 'Versions',
  'models.detail.tab.setup': 'Settings',
  'models.detail.serving': 'Serving',
  'models.detail.challenger': 'Challenger',
  'models.detail.challenger_hint':
    'The best version that is not answering. The registry names it “challenger”, so models:/<model>@challenger resolves it without going through Agentium.',
  'models.detail.promote': 'Put v{version} in service',
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
  'models.detail.error.title': 'Training failed',
  'models.detail.trained_at': 'Trained on {date}',
  'models.detail.dataset': 'Dataset',
  'models.detail.dataset.open': 'Open the dataset',
  'models.detail.provenance': 'Provenance',
  'models.detail.origin_system': 'Trained by a System run',
  'models.detail.system_chip': 'System',
  'models.detail.run_chip': 'Run',
  'models.detail.provenance.dataset': '{name}',
  'models.detail.provenance.transform': '{name} · {engine}',
  'models.detail.provenance.model': '{name} v{version}',
  'models.detail.provenance.scored': '{name}',

  'models.tabular.options': 'Advanced options',
  'models.tabular.option.hint': 'Configure {field} for this training run.',
  'models.error.ml_feedback_not_numeric': 'Ground truth must be a finite number for a regression model.',
  'models.warning.ml_spec_field_ignored': 'The {field} option is ignored because it does not apply to this configuration.',
  'models.progress.step.tuning': 'Tuning the model',
  'models.progress.step.tuning.counted': 'Tuning — trial {fold}/{folds}',
  'models.progress.step.calibrating': 'Calibrating the model',
  'models.progress.step.calibrating.counted': 'Calibrating — fold {fold}/{folds}',
  'models.progress.step.explaining': 'Explaining the model',
  'models.progress.step.queued': 'Queued',
  'models.progress.step.reading': 'Reading the dataset',
  'models.progress.step.fitting': 'Fitting the model',
  'models.progress.step.fitting.counted': 'Fitting on {rows} rows',
  'models.progress.step.scoring': 'Scoring the test rows',
  'models.progress.step.validating': 'Cross-validating over {folds} folds',
  'models.progress.step.validating.counted': 'Cross-validating — fold {fold}/{folds}',
  'models.progress.step.backtesting': 'Backtesting over {folds} past horizons',
  'models.progress.step.backtesting.counted': 'Backtesting — horizon {fold}/{folds}',
  'models.progress.step.saving': 'Saving the artifact',
  'models.progress.step.done': 'Done',
  'models.progress.settled': 'Model {name} v{version} ready — {metric} {value}',
  'models.progress.settled.plain': 'Model {name} v{version} ready',
  'models.progress.failed': 'Training {name} v{version} failed',

  'models.evidence.scores': 'Scores on the test rows',
  'models.evidence.scores.forecast': 'Backtest scores',
  'models.evidence.rows': '{total} rows · {train} for learning · {test} for testing',
  'models.evidence.forecast': 'Forecasts replayed on the past',
  'models.evidence.forecast.hint':
    'Each horizon is forecast from the data before it only. The band is the {level} interval, calibrated on the errors of the earlier horizons.',
  'models.evidence.forecast.series': 'Series',
  'models.evidence.forecast.actual': 'Actual',
  'models.evidence.forecast.pred': 'Forecast',
  'models.evidence.forecast.interval': 'Interval',
  'models.evidence.forecast.rows': '{total} rows · {history} steps of history · {series} series',
  'models.evidence.forecast.setup': '{frequency} · horizon {horizon} · {folds} backtests · {method}',
  'models.evidence.forecast.method.conformal': 'conformal interval',
  'models.evidence.forecast.method.model': 'model interval',
  'models.evidence.forecast.filled': '{count} steps filled ({fill})',
  'models.evidence.horizon': 'Error per step ahead',
  'models.evidence.horizon.hint': 'Mean absolute error at each step: how fast the forecast degrades.',
  'models.evidence.horizon.step': '+{step}',
  'models.evidence.series': 'Error per series',
  'models.evidence.series.hint':
    'Worst-forecast series first. A MASE below 1 beats repeating the previous value.',
  'models.evidence.baseline.better': '{share} less error than repeating the last season',
  'models.evidence.baseline.worse': '{share} more error than repeating the last season',
  'models.evidence.coverage': 'Coverage {coverage} for {level} asked',
  'models.explain.title': 'What the forecast leans on',
  'models.explain.groups': 'By family of features',
  'models.explain.groups.hint':
    'Each family’s share of the model’s forecasts: mean SHAP measured over its training history.',
  'models.explain.lags': 'The past it repeats',
  'models.explain.lags.hint':
    'Weight of each past value of the series. A peak at 7 d means the forecast mostly follows the same hour the week before.',
  'models.explain.step': 'Direct model: the first step of the horizon is explained.',
  'models.explain.group.lags': 'The series’ recent past',
  'models.explain.group.calendar': 'Calendar',
  'models.explain.group.future': 'Covariates known in advance',
  'models.explain.group.past': 'Other series',
  'models.explain.group.static': 'Series attributes',
  'models.explain.group.series': 'Which series',
  'models.explain.group.other': 'Other',
  'models.explain.span.hours': '{n} h',
  'models.explain.span.days': '{n} d',
  'models.explain.span.weeks': '{n} wk',
  'models.explain.span.months': '{n} mo',
  'models.explain.span.years': '{n} yr',
  'models.explain.span.steps': '{n} steps',
  'models.explain.calendar.hour': 'Hour of day',
  'models.explain.calendar.day_of_week': 'Day of week',
  'models.explain.calendar.day_of_month': 'Day of month',
  'models.explain.calendar.day_of_year': 'Day of year',
  'models.explain.calendar.is_weekend': 'Weekend',
  'models.explain.calendar.week': 'Week of year',
  'models.explain.calendar.month': 'Month',
  'models.explain.calendar.quarter': 'Quarter',
  'models.explain.calendar.year': 'Year',
  'models.explain.feature.series': 'Series',
  'models.explain.model': 'Model parameters',
  'models.explain.model.hint':
    'A statistical model is explained by its fitted parameters: level and season smoothing (ETS), coefficients (ARIMA).',
  'models.explain.model.aic': 'AIC {aic}',
  'models.explain.naive':
    'The seasonal naive repeats the last season ({season} steps): there is nothing else to explain.',
  'models.explain.unavailable': 'The explanation could not be computed for this model.',
  'models.explain.approximate':
    'Deep forest: approximate attributions (Saabas), additive but coarser than exact SHAP.',
  'models.analysis.title': 'Anatomy of the series',
  'models.analysis.hint':
    'Measured on the history alone: seasonality and trend (STL decomposition), autocorrelation, stationarity (ADF test).',
  'models.analysis.season.strong': 'Strong seasonality ({value}) · period {period}',
  'models.analysis.season.moderate': 'Moderate seasonality ({value}) · period {period}',
  'models.analysis.season.weak': 'Weak seasonality ({value})',
  'models.analysis.trend.strong': 'Strong trend ({value})',
  'models.analysis.trend.moderate': 'Moderate trend ({value})',
  'models.analysis.trend.weak': 'Weak trend ({value})',
  'models.analysis.stationary': 'Returns to its level (ADF p {p})',
  'models.analysis.unit_root': 'Wanders without returning (ADF p {p})',
  'models.analysis.acf': 'How it resembles its past',
  'models.analysis.acf.hint':
    'Autocorrelation at the model’s lags and the season’s multiples: why it is worth looking that far back.',
  'models.analysis.acf.noise': 'noise',
  'models.analysis.suggested': 'Lags the partial autocorrelation suggests: {lags}',
  'models.diagnostic.title': 'The regressor alone, one step ahead',
  'models.diagnostic.hint':
    'Refitted on the {train} oldest rows and judged by skore on the next {test}. Good here and weak in the backtest: the error is the recursion compounding; weak here too: the features.',
  'models.diagnostic.fit': 'Forecast against actual (one step)',
  'models.explain.peak.title': 'Why this peak',
  'models.explain.peak.sentence': 'From a base of {base}, {series} reaches {pred} at {when}.',
  'models.explain.peak.groups': 'What raised or lowered it',
  'models.explain.peak.features': 'Strongest features',
  'models.excursions.title': 'Outside the interval',
  'models.excursions.hint': '{count} backtest actuals left the band ({share}); the furthest first.',
  'models.excursions.above': '{actual} above {bound}',
  'models.excursions.below': '{actual} below {bound}',
  'models.evidence.roc': 'ROC curve',
  'models.evidence.roc.hint':
    'The faster the curve climbs to the top-left corner, the better the model separates. The diagonal is chance. Hover the curve to read an operating point.',
  'models.evidence.roc.x': 'False positives',
  'models.evidence.roc.y': 'True positives',
  'models.evidence.roc.point': '{tpr} of true positives for {fpr} of false positives',
  'models.evidence.pr': 'Precision / recall',
  'models.evidence.pr.hint':
    'What each point of recall costs in precision. The low line is the share of positives. Hover the curve to read an operating point.',
  'models.evidence.pr.x': 'Recall',
  'models.evidence.pr.y': 'Precision',
  'models.evidence.pr.point': 'Precision {precision} at {recall} recall',
  'models.evidence.fit': 'Predicted against actual',
  'models.evidence.fit.hint':
    'Every point is a test row. The closer the cloud hugs the diagonal, the closer the model is.',
  'models.evidence.fit.x': 'Actual',
  'models.evidence.fit.y': 'Predicted',
  'models.evidence.fit.point': 'Predicted {predicted} for an actual of {actual}',
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
  'models.evidence.delta.against': 'Deltas measured against v{version}',

  'models.compare.hint':
    'Two versions of the same model, on the same metrics. Only the ones both produced can be compared.',
  'models.compare.metric': 'Metric',
  'models.compare.before': 'Before',
  'models.compare.after': 'After',
  'models.compare.move': 'Delta',
  'models.compare.none.title': 'Nothing to compare yet',
  'models.compare.none.description':
    'Comparison opens as soon as a second version has been trained: retrain to watch the scores move.',
  'models.compare.verdict.better':
    'v{version}: {metric} {delta} against v{previous}. This retrain is worth putting in service.',
  'models.compare.verdict.worse':
    'v{version}: {metric} {delta} against v{previous}. Keep the previous version in service.',
  'models.compare.verdict.flat':
    'v{version}: {metric} unchanged against v{previous}. Nothing forces a change to what answers.',

  'models.monitor.empty.title': 'Nothing to measure',
  'models.monitor.empty.description':
    'Every prediction is journalled. Call the model, then come back here.',
  'models.monitor.window': '{predictions} calls · {labeled} labeled',
  'models.monitor.data': 'Data drift',
  'models.monitor.score': 'Score drift',
  'models.monitor.concept': 'Concept drift',
  'models.monitor.status.ok': 'Steady',
  'models.monitor.status.watch': 'Watch',
  'models.monitor.status.alert': 'Alert',
  'models.monitor.status.unknown': 'Not yet',
  'models.monitor.features': 'Features',
  'models.monitor.auc': 'Training AUC and rolling AUC',
  'models.monitor.auc.x': 'Window',
  'models.monitor.auc.y': 'AUC',
  'models.monitor.feedback': 'Ground truth',
  'models.monitor.feedback.hint':
    'Paste the id the prediction returned, then the real outcome.',
  'models.monitor.feedback.id': 'Prediction',
  'models.monitor.feedback.label': 'Outcome',
  'models.monitor.feedback.submit': 'Save',
  'models.monitor.feedback.done': 'Outcome saved',
  'models.monitor.feedback.failed': 'Saving the outcome failed',
  'models.monitor.dataset': 'Create a dataset',
  'models.monitor.dataset.hint':
    'The labeled rows become a dataset the studio can retrain on.',
  'models.monitor.dataset.done': 'Dataset “{name}” created',
  'models.monitor.dataset.failed': 'Not enough labeled rows',
  'models.monitor.retrain': 'Retrain on this dataset',

  'models.compare.same.title': 'Compare on the same rows',
  'models.compare.same.hint':
    'The table above puts two recorded results side by side, each measured on its own split. Here both models are re-scored over a single test split, so the gap becomes a property of the models rather than of the sampling.',
  'models.compare.same.action': 'Re-score both versions',
  'models.compare.same.running': 'Re-scoring…',
  'models.compare.same.provenance':
    '{rows} test rows · {dataset} v{version} · joint table computed by skore',
  'models.compare.same.warn.TRAINED_ON_ANOTHER_DATASET':
    'One version was trained on a different dataset, so some of these rows may have taught it. Its column can read better than it would on unseen data.',
  'models.compare.same.warn.DIFFERENT_SPLIT_SIZE':
    'The two versions were not trained with the same test size; the split used here is the newer version’s.',
  'models.compare.failed': 'These two versions could not be scored on the same rows.',
  'models.compare.error.ml_compare_same_version':
    'A version cannot be compared with itself.',
  'models.compare.error.ml_compare_cross_workspace':
    'These two models belong to different workspaces.',
  'models.compare.error.ml_compare_different_question':
    'These versions do not answer the same question, so one table cannot rank them.',
  'models.compare.error.ml_compare_not_tabular':
    'Only tabular models are re-scored on a shared split; a forecast compares by its backtest.',
  'models.compare.error.ml_compare_no_common_dataset':
    'Neither training dataset carries every column the two models need.',
  'models.compare.error.ml_compare_dataset_too_large':
    'This dataset is over the row ceiling allowed for a comparison.',
  'models.compare.error.ml_compare_split_failed':
    'The test split could not be rebuilt on this dataset.',
  'models.compare.error.ml_compare_failed':
    'These two versions could not be scored on the same rows.',

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
  'models.metric.log_loss': 'Log loss',
  'models.metric.brier_score': 'Brier score',
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
  'models.metric.log_loss.hint':
    'Penalises confident mistakes. Lower is better: it reads whether the probability is honest, not just the answer.',
  'models.metric.brier_score.hint':
    'Mean squared error of the predicted probability. Lower is better — the number behind a gauge you intend to believe.',
  'models.metric.mase': 'MASE',
  'models.metric.rmsse': 'RMSSE',
  'models.metric.smape': 'sMAPE',
  'models.metric.coverage': 'Coverage',
  'models.metric.interval_width': 'Interval width',
  'models.metric.mase.hint':
    'Error relative to a forecast that repeats the last season. Below 1, the model beats that baseline.',
  'models.metric.rmsse.hint':
    'Like MASE, but large errors weigh more. Below 1, better than repeating the last season.',
  'models.metric.smape.hint': 'Mean error as a percentage, symmetric between over- and under-forecasting.',
  'models.metric.coverage.hint':
    'Share of actual values that fell inside the stated interval. Compare it with the requested level; do not maximise it.',
  'models.metric.interval_width.hint': 'Mean width of the interval, in the unit of the forecast column.',
  'models.family.tabular': 'Tabular',
  'models.family.forecasting': 'Forecasting',
  'models.spec.time_column': 'Date column',
  'models.spec.time_column.hint': 'When each value was measured. It sets the order and the step of the series.',
  'models.spec.shape': 'Shape',
  'models.spec.shape.hint': 'One series, a panel of similar series, or one series forecast from others.',
  'models.spec.shape.single': 'One series',
  'models.spec.shape.panel': 'Panel of series',
  'models.spec.shape.multivariate': 'Multivariate',
  'models.spec.series_columns': 'Series columns',
  'models.spec.series_columns.hint': 'What tells one series of the panel from another: the cell, the store.',
  'models.spec.horizon': 'Horizon',
  'models.spec.horizon.hint': 'How many steps to forecast, in the unit of the frequency.',
  'models.spec.frequency': 'Frequency',
  'models.spec.frequency.hint': 'The step between two values. “Auto” infers it from the dates.',
  'models.spec.frequency.auto': 'Auto',
  'models.spec.frequency.h': 'Hourly',
  'models.spec.frequency.d': 'Daily',
  'models.spec.frequency.w': 'Weekly',
  'models.spec.frequency.ms': 'Monthly',
  'models.spec.frequency.qs': 'Quarterly',
  'models.spec.strategy': 'Strategy',
  'models.spec.strategy.hint': 'Recursive: one model that feeds on its own forecasts. Direct: one model per step ahead.',
  'models.spec.strategy.recursive': 'Recursive',
  'models.spec.strategy.direct': 'Direct',
  'models.spec.lags': 'Lags',
  'models.spec.lags.hint': 'The past values the model looks at: 1 = the previous step, 24 = the same hour yesterday.',
  'models.spec.exog': 'Covariates',
  'models.spec.exog.hint': 'Other columns that help the forecast, with what is known about them in advance.',
  'models.spec.exog.future': 'Known in advance',
  'models.spec.exog.static': 'Attribute of the series',
  'models.spec.exog.past': 'Known up to now',
  'models.spec.calendar': 'Calendar',
  'models.spec.calendar.hint': 'Adds the hour, the day of the week and the month as features.',
  'models.spec.interval_level': 'Interval level',
  'models.spec.interval_level.hint': 'The share of actual values the interval should contain.',
  'models.spec.backtest_folds': 'Backtests',
  'models.spec.backtest_folds.hint': 'How many past horizons to replay to measure the error, unseen by the model.',
  'models.spec.fill': 'Gaps in the series',
  'models.spec.fill.hint': 'What to do with a missing step or value.',
  'models.spec.fill.refuse': 'Refuse',
  'models.spec.fill.interpolate': 'Interpolate',
  'models.spec.fill.zero': 'Fill with zero',
  'models.family.reason.no_worker': 'No worker that can train these models is running.',
  'models.family.reason.runtime_missing': 'This family’s training environment is not installed.',
  'models.family.reason.disabled': 'Training is disabled on this deployment.',

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

  'models.play.unavailable.title': 'This model does not answer yet',
  'models.play.unavailable.no_forecast_worker':
    'No forecasting worker is answering right now: start the ml-ts service to query this model.',
  'models.play.forecast.ask': 'What you ask',
  'models.play.forecast.run': 'Forecast',
  'models.play.forecast.covariates': 'Planned values of {names}, applied to every step of the horizon.',
  'models.play.forecast.covariates_undated':
    'This model needs future values, but its step cannot be dated here: send them through the API.',
  'models.play.forecast.answer': 'What the model forecasts',
  'models.play.forecast.empty': 'Pick a horizon and run the forecast.',
  'models.play.forecast.timing.cached': 'answered in {ms} ms',
  'models.play.forecast.timing.cold': 'answered in {ms} ms, {load} ms of it loading',
  'models.play.forecast.peak': 'Forecast peak: {value} at {when}. At {level}, it may reach {upper}.',
  'models.play.forecast.peak_plain': 'Forecast peak: {value} at {when}.',
  'models.play.forecast.failed': 'The forecast failed.',
  'models.play.unavailable.untrained':
    'A model answers once it is trained: start a training run and the form will be built from its contract.',
  'models.play.unavailable.disabled':
    'Prediction is not enabled on this deployment. An administrator can open it in the configuration.',
  'models.play.inputs': 'The customer to score',
  'models.play.inputs.hint':
    'Fields built from the model’s contract and pre-filled with a typical training row. Change one value and the answer follows.',
  'models.play.run': 'Predict',
  'models.play.reset': 'Back to the typical row',
  'models.play.answer': 'What the model answers',
  'models.play.idle': 'Run a prediction to see the answer.',
  'models.play.probability': 'probability that {target} is {label}',
  'models.play.predicted': 'Answer: {label}',
  'models.play.estimate': '{target}, estimated',
  'models.play.range': 'range seen in training',
  'models.play.range.bounds': '{min} → {max}',
  'models.play.why': 'What made this answer',
  'models.play.why.typical': 'typical value: {value}',
  'models.play.why.hint':
    'Every bar is measured: the model is asked again with that one field back at its typical value, and the gap is what it cost.',
  'models.play.timing': 'Answered in {ms} ms',
  'models.play.prediction_id': 'Prediction {id}',
  'models.play.served': 'answered by v{version}',
  'models.play.failed': 'The prediction failed',
  'models.play.curl': 'The same call, from a system',
  'models.play.curl.hint':
    'Exactly the request this form just sent: same route, same body, only the proof of identity differs.',
  'models.play.copy': 'Copy',
  'models.play.copied': 'Copied',

  'models.keys.title': 'Access keys',
  'models.keys.hint':
    'A key opens this model’s prediction and nothing else on the API. The secret is shown once.',
  'models.keys.name.placeholder': 'Key name',
  'models.keys.name.default': 'Demo key',
  'models.keys.mint': 'Create a key',
  'models.keys.minted': 'Key created',
  'models.keys.minted.hint':
    'Copy it now: only a hash is stored and it will never be shown again.',
  'models.keys.col.name': 'Name',
  'models.keys.col.prefix': 'Prefix',
  'models.keys.col.uses': 'Calls',
  'models.keys.col.state': 'State',
  'models.keys.live': 'Live',
  'models.keys.revoked': 'Revoked',
  'models.keys.revoke': 'Revoke',
  'models.keys.revoked.toast': '“{name}” no longer answers',
  'models.keys.uses': '{count} calls',

  'models.publish.title': 'Publish as a skill',
  'models.publish.hint':
    'The model becomes a workspace skill, typed from its contract: callable in a system or in chat, frozen on this lineage.',
  'models.publish.action': 'Publish as a skill',
  'models.publish.live': 'Published',
  'models.publish.open': 'Open in the catalog',
  'models.publish.withdraw': 'Withdraw from the catalog',
  'models.publish.done': '“{name}” is in the skill catalog — click to open it',
  'models.publish.withdrawn': 'The skill was withdrawn from the catalog',
  'models.publish.provenance': 'Model {name} v{version} — {evidence}',

  'models.serving.error.ml_predict_disabled':
    'Prediction is not enabled on this deployment.',
  'models.serving.error.ml_predict_rows_required': 'No row to predict was sent.',
  'models.serving.error.ml_predict_row_not_object':
    'Every row must be a field-to-value object.',
  'models.serving.error.ml_predict_too_many_rows':
    'Too many rows in a single call: split the request.',
  'models.serving.error.ml_predict_field_unknown':
    'A field that was sent is not part of the model’s contract.',
  'models.serving.error.ml_predict_field_missing':
    'A field the model expects is missing.',
  'models.serving.error.ml_predict_field_not_numeric':
    'A numeric field was given a value that is not a number.',
  'models.serving.error.ml_predict_field_not_boolean':
    'A boolean field was given a value that is neither true nor false.',
  'models.serving.error.ml_predict_failed':
    'The model could not answer on this row.',
  'models.serving.error.ml_contract_missing':
    'This model has no input contract: retrain it.',
  'models.serving.error.ml_artifact_unloadable':
    'The model artifact is missing from storage or cannot be read.',
  'models.serving.error.ml_nothing_serves':
    'No version of this model is in service.',
  'models.serving.error.ml_version_unknown':
    'That version does not exist in this lineage.',
  'models.serving.error.ml_model_not_ready': 'Only a trained model can answer.',
  'models.serving.error.ml_model_not_found':
    'That model does not exist in this workspace.',
  'models.serving.error.ml_score_too_many_rows':
    'This dataset is over the row ceiling allowed for scoring.',
  'models.serving.error.ml_score_column_missing':
    'The dataset is missing a column the model expects.',
  'models.serving.error.ml_key_limit':
    'This model has reached its maximum number of live keys.',
  'models.serving.error.ml_key_not_found':
    'That key does not exist on this model.',
  'models.serving.error.ml_key_required': 'No proof of identity was given.',
  'models.serving.error.ml_key_invalid': 'That key is not recognized.',
  'models.serving.error.ml_key_revoked': 'That key was revoked.',
  'models.serving.error.ml_key_wrong_model':
    'That key was created for another model.',
  'models.serving.error.ml_publish_name_taken':
    'A skill already carries that name in this workspace.',
  'models.serving.error.ml_publish_name_invalid':
    'The model’s name does not yield a valid skill identifier.',
  'models.serving.error.ml_use_forecast_route':
    'A forecasting model answers for a horizon, not for rows: the forecasting worker serves it.',
  'models.serving.error.ml_forecast_timeout':
    'The forecasting worker did not answer in time. Try again in a moment.',
  'models.serving.error.ml_forecast_input_invalid':
    'The future values sent do not cover the requested horizon.',
  'models.serving.error.ml_forecast_params_invalid':
    'The horizon and the interval level must be valid numbers.',
  'models.serving.error.ml_forecast_horizon_invalid':
    'This horizon is beyond what this model can forecast.',
  'models.serving.error.ml_forecast_failed':
    'The forecast failed in the worker.',
  'models.serving.error.ml_forecast_too_many_rows':
    'Too many rows of future values for one call.',
  'models.serving.error.ml_artifact_tampered':
    'The stored artifact is not the one training produced: it is refused.',
  'models.serving.error.ml_artifact_unverified':
    'This model was saved without the fingerprints serving checks.',
  'models.serving.error.ml_use_predict_route':
    'This model answers rows: use /predict.',
  'models.serving.error.ml_family_unavailable':
    'No worker that can serve this model is running right now.',

  'models.versions.label': 'v{version}',
  'models.versions.current': 'Shown version',
  'models.versions.serving': 'Answers',
  'models.versions.challenger': 'Challenger',
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
  'models.setup.evaluation': 'Evaluation kept',
  'models.setup.evaluation.value': '{size} — skore {skore} report, reloadable',
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
  'models.refusal.ml_spec_invalid':
    'The problem definition holds a field this model family does not accept.',
  'models.refusal.ml_family_unavailable':
    'No worker that can train this model family is running right now.',
  'models.refusal.ml_model_not_ready': 'Only a trained model can answer.',
  'models.refusal.ml_model_not_found':
    'This model does not exist in this workspace.',
  'models.refusal.ml_ts_time_column_required': 'Pick the date column of the series.',
  'models.refusal.ml_ts_time_column_not_datetime':
    'This column is not a date, so the series cannot be ordered.',
  'models.refusal.ml_ts_column_reused':
    'This column is already the target or the date column.',
  'models.refusal.ml_ts_exog_not_numeric':
    'A covariate must be numeric, unless it is an attribute of the series.',
  'models.refusal.ml_ts_past_needs_multivariate':
    'A column only known up to now can only be used by a multivariate forecast.',
  'models.refusal.ml_ts_static_needs_panel':
    'An attribute of the series only makes sense in a panel.',
  'models.refusal.ml_ts_multivariate_needs_series':
    'A multivariate forecast needs at least one other series known up to now.',
  'models.refusal.ml_ts_duplicate_timestamps':
    'Dates repeat: this dataset holds several series. Name the columns that tell them apart.',
  'models.refusal.ml_ts_too_many_series':
    'Too many series for one panel model on this deployment.',
  'models.refusal.ml_ts_algo_shape_mismatch':
    'This algorithm handles one series at a time: pick a regressor for a panel or a multivariate forecast.',
  'models.refusal.ml_ts_history_too_short':
    'Not enough history for this horizon, these lags and these backtests.',

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
  'models.error.ml_runtime_missing':
    'The worker that received the training lacks this model family’s libraries.',
  'models.error.ml_ts_series_unusable':
    'The series has gaps, repeated dates or no regular step. Pick a fill policy or fix the data.',
  'models.error.ml_ts_history_too_short':
    'Once the series is on its step, too little history is left for this horizon.',

  'models.disabled.title': 'Model plane disabled',
  'models.disabled.description':
    'Model training is not enabled on this deployment. An administrator can open it in the configuration.',
};
