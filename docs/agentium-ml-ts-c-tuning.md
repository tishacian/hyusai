# TS-C — réglage automatique des prévisions sous budget

Le formulaire conserve ses réglages par défaut. `spec.tuning=budget` active une recherche Optuna sur les réglages du régresseur (gradient boosting, forêt ou Ridge), avec `tuning_trials` (5–100), `tuning_folds` (2–5) et `tuning_budget_s` (30–1500 secondes, plafonné à 60 % du délai d’entraînement). Le budget par défaut est adapté au délai configuré. Les formes single, panel et multivariate sont prises en charge ; ETS, ARIMA et le naïf saisonnier sont refusés. Les retards, le calendrier et les covariables restent ceux du formulaire.

Les derniers `backtest_folds × horizon` pas sont exclus de la recherche. Le sous-processus reçoit uniquement le préfixe d’entraînement, sans chemin du fichier source. Chaque essai refait les mêmes plis temporels croissants sur ce préfixe et minimise la MAE moyenne par série. L’essai zéro reprend exactement le formulaire, y compris la profondeur automatique d’une forêt ; un candidat ne le remplace que si sa validation est meilleure. Cette garantie concerne la validation interne, pas le backtest final. Le naïf saisonnier est évalué aux mêmes origines, en répétant uniquement la dernière saison déjà connue.

La recherche est tuable même pendant un fit natif. Ses résultats terminés sont sauvegardés après chaque essai. Si le budget expire avant le premier essai terminé, les réglages du formulaire sont conservés et un avertissement explicite est enregistré. Les historiques trop courts (y compris ceux sans une saison complète avant les plis internes) et les panneaux dont une série ne couvre pas toute la validation sont refusés. L’interpolation globale peut lire le futur : son association au réglage automatique est refusée ; le refus des trous et le remplissage par zéro sont disponibles.

Le backtest final conserve ses métriques et intervalles habituels. Le modèle choisi est ensuite ajusté sur toute l’histoire pour la prévision. `metrics.tuning` expose `metric=mae`, `direction=min`, `start`, `best`, `trials`, `baseline`, `validation`, `budget_s`, `elapsed_s` et `stopped_by`. `validation` donne les bornes temporelles du préfixe et le début du backtest réservé. La sélection met à jour les réglages effectifs du modèle. Chaque essai enregistré devient un run enfant MLflow portant son score, sa durée, son état et ses réglages.

Optuna est déjà dans les dépendances communes ; aucune dépendance, migration ou image supplémentaire. L’API n’importe pas Optuna. Le déploiement reconstruit backend, worker et ml-ts avec le code, puis frontend avec le formulaire.

## Qualification backend

- 16 tests TS-C : validation du contrat et du budget courant, recherche réelle sur les trois formes et la stratégie directe, reproductibilité, profondeur automatique, arrêt forcé, essai échoué, historique incomplet, artefact MLflow rechargé et prévision après le fit final.
- Une perturbation des seules valeurs du backtest réservé conserve exactement tous les scores des essais et le candidat choisi ; elle modifie bien les métriques du backtest.
- 77 tests existants passent : harness de prévision réel, validation des prévisions et Optuna tabulaire.
- Le test d’enregistrement des runs enfants MLflow (avec réglages) et les trois contrôles d’import API passent. Aucun import Optuna/skforecast n’est ajouté au chargement des routes.
- Ruff ciblé, vérification du diff et scan des secrets passent.

## Formulaire et qualification d’intégration

Le studio et l’atelier Flow utilisent les mêmes contrôles de réglage temporel.
Les limites et valeurs initiales viennent du catalogue ; une réouverture conserve
les réglages enregistrés. Une ancienne API sans cette capacité continue de
recevoir une spécification de prévision ordinaire. Un budget déjà enregistré
reste visible mais ne peut pas être lancé tant que le catalogue ne le propose
pas. Le formulaire explique également les refus d’algorithme, d’interpolation
et de valeurs hors limites.

La carte du modèle distingue la validation interne utilisée pour choisir les
réglages, sa référence naïve saisonnière et le backtest réservé. La progression
indique les essais de réglage avant l’ajustement et le backtest.

- 153 tests frontend ciblés passent, ainsi que cinq parcours navigateur FR/EN
  et mobile : preuve temporelle, bornes du catalogue, refus d’interpolation et
  conservation des paramètres à la réouverture du Flow.
- Compilation Angular, i18n, contrôles UI et navigation passent.
- Après intégration de TS-A et TS-B, 31 tests backend passent, comprenant le
  réentraînement réellement approuvé, Optuna réel et les imports de l’API.
- 132 tests frontend couvrent ensemble le suivi des réels, la revue humaine,
  les spécifications de prévision et les résultats du réglage.
- Le build production unique passe avec les avertissements Angular, CSS,
  budget initial et dagre déjà présents.
- Les revues indépendantes backend et frontend ne laissent aucun blocage.

Ordre d’intégration : TS-A, TS-B, TS-C. La fusion dans la branche de livraison
et le déploiement suivent la validation de ces branches. Les changements validés sont
synchronisés vers Bitbucket, dépôt source du déploiement.
