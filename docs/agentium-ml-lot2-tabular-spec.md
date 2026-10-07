# Agentium ML — Lot 2 : extensions tabulaires (spec de reprise)

> Rédigée le 2026-10-07, à la fin du Lot 3 (prévision). Elle est destinée à l'agent qui reprend le chantier.
> Plan d'ensemble : `~/.claude/plans/fais-un-plan-d-int-gration-partitioned-token.md`, section « Lot 2 ». Ce document le précise et l'emporte en cas d'écart.
> Base : `demo/agentic` @ `579d99be`.

## 0. À lire avant de commencer

### État de départ

- **Fusionnés et déployés sur la VM** : Lots 0, 0b-2, 1 (familles, migration `122_ml_families`) et 3 (prévision skforecast, image `ml-ts`, nœud Flow, explicabilité TS). La réconciliation explicite du catalogue Skills est fusionnée (`579d99be`) mais pas encore déployée.
- **La famille tabulaire n'a encore aucun champ de spec.** La tuyauterie existe pourtant de bout en bout, et le Lot 2 s'y branche :
  - `TrainBody.spec` est analysé par `Family.parse_spec`, qui refuse en `ML_SPEC_INVALID` ;
  - le spec est stocké dans `MLModel.spec_json` ;
  - il est transmis au harness par `manifest["spec"]` (`tabular_ml._write_manifest`) ;
  - il est journalisé dans MLflow en `spec.*` (`_register_version`) ;
  - il est projeté par le Flow via `_TRAIN_PARAM_KEYS`, qui contient déjà `spec`.
- **Le registre des métriques** (`backend/app/services/ml/metrics.py`) donne le sens de chaque métrique ; le front l'adopte. Toute nouvelle métrique y est déclarée, sinon elle n'est ni classée ni colorée.
- **Les knobs sont typés** (`backend/app/services/ml/knobs.py`) : `int / float / enum / bool / int_list`.
- **Un test est rouge avant le Lot 2** : `test_every_seeded_slug_has_a_wrapper_and_a_category`. `openai_llm_v1` et `azure_openai_llm_v1` ont un wrapper mais aucune ligne de catalogue (commit b3a50bac). C'est une décision produit : ne pas y toucher.
- **Une mesure reste à faire sur la VM** : la latence de Play pour une prévision (`/forecast`, RPC `ml_ts_rpc`). Elle ne relève pas de ce lot.

### Règles de travail

Elles ne sont pas négociables.

**Git et branches**
- `git` est une fonction shell cassée sur ce poste : utiliser **`/opt/homebrew/bin/git`**.
- Sous zsh, `$VAR` contenant des espaces n'est pas découpé. Écrire les boucles dans un script **bash**.
- Travailler dans un worktree dédié, branché depuis `origin/demo/agentic`, une branche par PR (`feat/ml-lot2-<lettre>-<sujet>`).
- Pousser avec une refspec explicite : `/opt/homebrew/bin/git push -u origin <branche>:<branche>`. Les worktrees existants ont `origin/demo/agentic` comme upstream ; un `push` nu irait au mauvais endroit.
- **Ne jamais fusionner dans `demo/agentic` sans l'accord explicite de l'utilisateur, à chaque fois.** Proposer la fusion (`--no-ff`, depuis le worktree d'intégration `../omnirag-cost-release`), puis attendre.
- Commiter et pousser le travail en cours tôt : le scratchpad est effacé au redémarrage.

**Environnements de test**
- Backend : créer un venv avec `uv venv`, puis `uv pip install -r backend/requirements.txt -c backend/constraints-demo-app.txt pytest pytest-asyncio`.
- Les tests qui ont besoin de PostgreSQL utilisent `pgserver` (voir la mémoire « Outillage de vérification locale »).
- Frontend : `export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22` avant tout `npm`.
- Lancer `npm run build:prod` **une seule fois par PR**, à la fin.
- e2e mockés : `E2E_CHROME_V2_MOCKED=1`, Chrome local.

**Ressources de la machine**
- Le disque du Mac est plein à environ 99 %. Ne pas générer de gros jeux de données ni d'artefacts hors du scratchpad, et nettoyer après soi.
- Deux ou trois agents en parallèle au maximum.

**Déploiement et produit**
- L'utilisateur déploie lui-même (`scripts/agentium-vm-deploy.sh`, environ 15 min). Le push ne déploie rien.
- Le design reste sobre (Tokens v2) : l'effet vient des données, pas du décor. Neutre par défaut ; l'ambre et le rouge sont réservés aux vrais signaux.
- Écrire comme le code environnant : docstrings qui disent *pourquoi*, mêmes conventions de nommage, i18n FR et EN systématique.
- `/api/v1/build-info` est une attestation publique à forme exacte. N'y ajouter aucun état métier.

## 1. Périmètre et ordre des PR

Chaque PR doit pouvoir être livrée seule, rester verte et rester **rétro-compatible**. Un modèle déjà entraîné doit se servir, se comparer et s'afficher exactement comme avant. Toutes les options nouvelles sont **désactivées par défaut**.

| PR | Contenu | Migration | Image |
|---|---|---|---|
| **2a** | Spec tabulaire (squelette), borne des forêts aléatoires, feedback typé en régression | non | non |
| **2b** | Intervalles conformes en régression : entraînement, service, score batch, Play | non | non |
| **2c** | Calibration des probabilités et seuil de décision (classification binaire) | non | non |
| **2d** | Réglage automatique Optuna sous budget | non | **oui** (backend et worker : ajout d'`optuna`) |
| **2e** | Pack d'explicabilité : arbre d'erreur, surrogate, PDP/ICE, équité | non | non |
| 2f (option) | Encodeur de texte exposé, rôle « texte » dans le plan | non | non |

**Aucune migration n'est prévue.** Tout tient dans `spec_json`, `params_json` et `metrics_json`. Si une PR semble en exiger une, s'arrêter et en discuter avec l'utilisateur.

**Exclus de ce lot** : segmentation (KMeans/HDBSCAN), ensembles de prédiction conformes en classification, intervalles adaptatifs (CQR), monitoring de la couverture en production, `label_value` numérique sur `ml_predictions`, dépendances lourdes (fairlearn, shap, mapie dans l'image API).

## 2. Socle commun (PR 2a)

### 2.1 Champs de spec de la famille tabulaire

Les champs sont déclarés dans `backend/app/services/ml/families/tabular.py` (`TABULAR.spec_fields`). Ils sont plats, parce que `SpecField` est plat ; la visibilité passe par `when`. Les types existants sont dans `SPEC_FIELD_KINDS` (`ml/families/base.py`). Si un type manque, l'ajouter dans `base.py` avec son `parse` et son `payload`.

| Clé | Type | Défaut | Bornes / choix | Visible si | PR |
|---|---|---|---|---|---|
| `intervals` | enum | `"off"` | `off`, `conformal` | task = regression | 2b |
| `calibration` | enum | `"off"` | `off`, `auto`, `sigmoid`, `isotonic` | task = classification | 2c |
| `threshold` | enum | `"default"` | `default`, `f1`, `youden` | task = classification | 2c |
| `tuning` | enum | `"off"` | `off`, `budget` | toujours | 2d |
| `tuning_trials` | int | 30 | 5–100 | tuning = budget | 2d |
| `tuning_budget_s` | int | 300 | 30–1500 | tuning = budget | 2d |
| `explain` | enum | `"off"` | `off`, `pack` | toujours | 2e |
| `fairness_columns` | columns | `[]` | 3 au maximum, catégorielles | explain = pack | 2e |

PR 2a ajoute le mécanisme. Chaque PR suivante ajoute ensuite ses propres champs ; ne pas déclarer un champ avant que son effet existe.

**Comment `when` connaît la tâche.** `when` lit les valeurs du spec. Il faut donc soit injecter la tâche résolue dans les valeurs passées à `_shown` côté serveur, soit exposer `task` comme pseudo-champ. Choisir la solution la moins intrusive et la tester des deux côtés : `parse_spec` côté serveur, rendu des champs côté front.

**Refus codés.** Un champ incompatible avec la tâche (`calibration` sur une régression, par exemple) est **ignoré et retiré** du spec stocké, avec un avertissement au plan. Ce n'est pas un refus : un nœud Flow dont on change la cible ne doit pas devenir invalide. Un contenu invalide, comme une colonne d'équité absente ou numérique continue, renvoie `ML_SPEC_INVALID` avec `details.field`.

### 2.2 Le harness reçoit le spec, et rien d'autre

`manifest["spec"]` est déjà transmis. Le harness (`backend/app/resources/ml_train_harness.py`) est **autonome** : il est exécuté par chemin, sans `import app.*`. Tout ce qu'il lui faut doit passer par le manifest.

### 2.3 Étapes de progression

`TRAIN_STEPS` (`tabular_ml.py:107`) gagne, dans l'ordre :

```
queued, reading, tuning, fitting, calibrating, scoring, validating, explaining, saving
```

- `tuning:k/N` ;
- `calibrating` couvre la calibration et les résidus conformes : `calibrating:k/K` quand des folds sont rejoués ;
- `explaining`.

Une étape n'est émise que si l'option correspondante est active. Côté front, `trainChecklist` (dans `models.vm.ts`) et les dictionnaires i18n doivent connaître ces étapes. Le Lot 3 avait oublié ce point (`FORECAST_TRAIN_STEPS`) : ne pas le refaire.

### 2.4 Borne des forêts aléatoires

**Le problème.** Le Lot 3 a mesuré une forêt aléatoire non bornée sur 72 cellules × 56 jours : pic à 5,5 Go, puis un artefact de plusieurs Go qui a rempli le disque (OSError 28). La forêt tabulaire a le même défaut sur un gros dataset.

**Le correctif.**
- Dans `estimator_params` (`tabular_ml.py:305`), retirer la condition `task == FORECASTING`. Toute forêt aléatoire dont `max_depth` vaut `None` reçoit `max_leaf_nodes = FOREST_LEAVES`.
- Renommer `FORECAST_FOREST_LEAVES` en `FOREST_LEAVES`, à 2048, et garder le commentaire en le généralisant.
- Une profondeur choisie explicitement reste sans plafond de feuilles.

**Effet sur les modèles existants.** Le passage en croissance best-first change les arbres, même quand la limite n'est pas atteinte. Un réentraînement produit donc une version légèrement différente. Le dire dans la PR. Les artefacts existants ne sont pas touchés.

**Tests**
- `test_ml_training.py` : une forêt « auto » reçoit `max_leaf_nodes` pour les trois tâches ; une profondeur explicite ne le reçoit pas.
- Harness réel : 50 000 lignes synthétiques (`make_regression`), artefact inférieur à 150 Mo. Libérer le disque après le test.

### 2.5 Feedback typé en régression

**Le problème.** `tabular_monitoring.attach_feedback` accepte n'importe quelle chaîne. `materialize_labeled` (ligne 558) écrit alors `row.label` tel quel comme cible : une régression réentraînée sur ce dataset reçoit une cible texte.

**Le correctif.**
- `attach_feedback` : pour un modèle de régression, le label doit se lire comme un nombre fini. Sinon, erreur 422 `ML_FEEDBACK_NOT_NUMERIC`.
- `materialize_labeled` : convertir en float pour la régression, écarter et compter les lignes illisibles (`lineage.skipped`).

**Tests** : `test_tabular_monitoring.py`.

## 3. PR 2b — Intervalles conformes (régression)

**But.** Chaque prédiction de régression peut porter une borne basse et une borne haute au niveau demandé, avec une couverture mesurée honnêtement sur le test.

### Entraînement (harness)

**Méthode : conformal par validation croisée**, résidus absolus. Pas de split conformal, qui retirerait des données au fit.
- `sklearn.model_selection.cross_val_predict(clone(pipeline), x_train, y_train, cv=K)` avec K = `cv` si `cv >= 2`, sinon 5. L'étape `calibrating:k/K` est émise via le `_NarratedSplitter` existant.
- Résidus : `r = |y_train - ŷ_oof|`.
- Pour chaque niveau de `LEVELS = (0.8, 0.9, 0.95)` : `q = quantile(r, ceil((n+1)·level)/n, method="higher")`.
- Le modèle final reste celui ajusté sur tout `x_train`, comme aujourd'hui.

**Couverture mesurée sur le test**, jamais utilisé pour calibrer : pour chaque niveau, la part de `y_test` dans `[ŷ − q, ŷ + q]`, et la largeur moyenne `2q`.

Résultat dans `metrics.intervals` :

```json
{"method": "cv_conformal_abs", "folds": 5, "residual_rows": 7500,
 "levels": [{"level": 0.8, "q": 3.21, "coverage": 0.81, "width": 6.42}, ...],
 "default_level": 0.9}
```

**Aucune classe applicative dans l'artefact.** Le pipeline sauvegardé reste un pipeline sklearn pur. Les quantiles vivent dans `metrics_json`.

### Service

- `tabular_predict.predict_rows` accepte `interval_level: float | None`.
  - Si le modèle a des `intervals` et qu'un niveau est demandé, ou à défaut `default_level`, chaque réponse gagne `lower`, `upper` et `level`.
  - Un niveau non stocké renvoie 422 `ML_INTERVAL_LEVEL_UNKNOWN`, avec `details.levels`. Pas d'interpolation silencieuse.
  - Un modèle sans intervalles ignore le paramètre : rétro-compatible.
- Endpoint `/predict` (`api/v1/endpoints/ml_models.py`) et chemin public par clé API : paramètre optionnel `interval_level`.
- Schéma de sortie : `predict_output_schema` déclare `lower`/`upper` quand le modèle en a. Une Skill publiée se met à jour par `refresh_published_skill`.
- `score_dataset` / `_score_into` ajoutent `<target>_lower` et `<target>_upper` (noms dédoublonnés par `_unique_name`).
- `journal_call` stocke les bornes dans les réponses journalisées, pour un futur monitoring de la couverture.

### Tests

- Harness sur 5 000 lignes synthétiques bruitées : couverture du test à ±0,05 du niveau pour les trois niveaux ; `q` croissant avec le niveau.
- `test_ml_predict.py` : bornes présentes et `lower ≤ prediction ≤ upper` ; niveau inconnu en 422 ; modèle ancien inchangé (aucune clé ajoutée).
- `test_ml_predict_api.py` : paramètre accepté par la route de session et par la route à clé API.
- Score batch : colonnes ajoutées.

## 4. PR 2c — Calibration et seuil (classification)

**But.** Des probabilités dignes de ce nom (Brier et log loss en baisse), et un seuil de décision choisi puis écrit dans le contrat plutôt que 0,5 par défaut.

### Calibration (harness)

- Si `calibration != "off"`, découper le train de façon stratifiée (`random_state` = seed) en une partie d'ajustement (80 %) et une partie de calibration (20 %).
  - Si la partie de calibration compte moins de 200 lignes, ou moins de 20 lignes de la classe la plus rare : pas de calibration. Avertissement `ML_CALIBRATION_TOO_FEW` dans `metrics.warnings`. Ce n'est pas un échec.
- Ajuster le pipeline sur la partie d'ajustement, puis `CalibratedClassifierCV(FrozenEstimator(pipeline), method=m)` sur la partie de calibration.
  - `auto` : `isotonic` si la partie de calibration a au moins 1 000 lignes, sinon `sigmoid`.
  - **Attention** : sklearn 1.9 n'a plus `cv="prefit"`. Le motif correct est `FrozenEstimator`, importé de `sklearn.frozen`.
- **Le rapport skore est construit sur le modèle calibré** : c'est lui qui est servi. Les métriques du test sont donc celles de ce qu'on sert.
- `metrics.calibration` :

  ```json
  {"method": "isotonic", "fit_rows": 6000, "calibration_rows": 1500,
   "before": {"brier_score": 0.142, "log_loss": 0.45, "curve": [{"x": 0.05, "y": 0.03}, ...]},
   "after":  {"brier_score": 0.121, "log_loss": 0.39, "curve": [...]}}
  ```

  - Courbes : `sklearn.calibration.calibration_curve(y_test == positive, proba, n_bins=10, strategy="quantile")`, en binaire seulement. En multiclasse, Brier et log loss uniquement.
  - « Avant » désigne le pipeline non calibré, évalué sur le même test.
  - Si « après » est pire, on le garde quand même : c'est un choix d'auteur. La carte le montre en ambre.

### Seuil (binaire seulement)

- `threshold = f1` : le seuil qui maximise F1 sur la **partie de calibration**, ou à défaut sur des prédictions `cross_val_predict` du train. Jamais sur le test.
- `threshold = youden` : le seuil qui maximise TPR − FPR, sur les mêmes données.
- **Artefact portable** : envelopper le modèle servi (calibré ou non) dans `sklearn.model_selection.FixedThresholdClassifier(estimator, threshold=t, pos_label=positive)`. `predict` applique le seuil et `predict_proba` reste inchangé. Un `mlflow models serve` hors Agentium se comporte donc comme Agentium.
- `metrics.decision = {"threshold": 0.37, "criterion": "f1", "default_metrics": {...}, "tuned_metrics": {...}}`. Les métriques du test sont données aux deux seuils, pour que la carte montre ce que le seuil change (précision et rappel).

### Audit obligatoire : le modèle servi n'est plus un `Pipeline`

Chercher et corriger toute introspection qui suppose un pipeline nu : `named_steps`, `steps[`, `[:-1]`, `get_feature_names_out`, `classes_`, `feature_names_in_`. Les endroits à couvrir :
- `ml_train_harness.py` : `_trusted_types`, `_importances`, `infer_signature` ;
- `tabular_predict.py` : `_classes_of`, `explain_row`, `_ranked_names` ;
- `tabular_ml.py` : `pipeline_provenance` ;
- monitoring ;
- `ml_comparison.py`.

**Solution recommandée** : une fonction pure `inner_pipeline(model)` qui déroule `FixedThresholdClassifier.estimator` → `CalibratedClassifierCV.estimator` → `FrozenEstimator.estimator`. La placer dans un module léger importable par l'API, et la dupliquer (en quelques lignes, commentée) dans le harness, qui reste autonome.

**skops** : vérifier que `TRUSTED_MODULE_PREFIXES` et `_trusted_types` couvrent `sklearn.calibration.*`, `sklearn.frozen.*`, `sklearn.isotonic.*` et `sklearn.model_selection._classification_threshold.*`. Tester un aller-retour `mlflow.sklearn.load_model` puis prédiction.

### Tests

- Harness : une forêt aléatoire sur `make_classification` (souvent sous-confiante) a un Brier qui baisse après `sigmoid`.
- Le seuil `f1` ne lit jamais le test : vérifier par construction, par exemple en faisant échouer la lecture du test dans un monkeypatch.
- `test_ml_predict.py` : un modèle seuillé prédit la classe positive à proba 0,4 quand t = 0,37 ; `explain_row` fonctionne sur un modèle calibré.
- Aller-retour d'artefact (skops et MLflow).
- `ml_comparison` compare un modèle calibré et un non calibré.

## 5. PR 2d — Réglage Optuna sous budget

**But.** Un bouton « Régler automatiquement » qui trouve de meilleurs knobs **dans un budget**, sans jamais faire pire que les knobs du formulaire, et qui le prouve.

### Dépendance et image

- Ajouter `optuna` à `backend/requirements.txt` et l'épingler, avec ses dépendances transitives manquantes (`colorlog` probablement ; `alembic`, `SQLAlchemy`, `PyYAML` et `tqdm` y sont déjà), dans `backend/constraints-demo-app.txt`.
  - Ce fichier est commun au backend et au worker, et un test épingle leurs préfixes ensemble : ajouter optuna aux deux garde la mise en cache des couches partagées.
  - optuna est en Python pur et léger.
- `test_api_import_footprint.py` interdit déjà l'**import** d'optuna par `app.main` : vérifier que la liste le contient. Optuna ne s'importe que dans le harness.
- Mettre à jour `test_demo_dependency_constraints.py` si besoin, mesurer les images (`scripts/agentium-image-budget.sh`) et noter les tailles dans `docs/agentium-release-process.md` (références et budgets, §4).

### Une seule traduction knob → paramètre d'estimateur

**Le piège.** Aujourd'hui, `estimator_params` (`tabular_ml.py:305`) traduit les knobs côté serveur : inversion `alpha` → `C` pour la régression logistique, sentinelle `auto_at` → `None`, `random_state`, `n_jobs`, plafond de feuilles. Le harness, lui, reçoit des `params` déjà traduits. Sous réglage, c'est le harness qui tire les knobs : il lui faut la même traduction. **Ne pas la dupliquer.**

**Le correctif.**
- Extraire la traduction dans un module pur, sans `import app.*` : par exemple `backend/app/resources/ml_knob_translation.py`, avec `translate(algo_key, task, knobs, *, random_state, forest_leaves) -> dict`.
- `tabular_ml.estimator_params` l'appelle.
- Le harness le charge par chemin, comme `ml_forecast_harness._tabular_reader()` charge `ml_train_harness.py`.
- Test de propriété : pour des knobs tirés au hasard, `estimator_params(...) == translate(...)`.

### Espace de recherche

- Écrit par le serveur dans `manifest["tuning"]`, **dans le vocabulaire des knobs** :

  ```json
  {"trials": 30, "budget_s": 300, "metric": "roc_auc", "direction": "max", "folds": 3,
   "start": {"max_iter": 150, "learning_rate": 0.1, "max_leaf_nodes": 31},
   "space": [{"key": "learning_rate", "kind": "float", "low": 0.01, "high": 0.5, "log": true}, ...]}
  ```

- Ajouter `log: bool = False` à `Knob`, et dans son `payload`. Le mettre à `True` pour `learning_rate` et `alpha`.
- `auto_at` est exclu de l'espace réglé : une profondeur réglée est toujours finie. C'est plus sûr pour la mémoire.
- `enum` donne `suggest_categorical` ; `bool` donne une catégorie à deux valeurs ; `int_list` n'est pas réglé.
- `start` contient les knobs du formulaire, résolus par `algo.resolve`.
- `metric` et `direction` viennent du registre (`ml/metrics.py`) : binaire → `roc_auc`, sur les probabilités ; multiclasse → `balanced_accuracy` ; régression → `r2`. Le harness n'importe pas le registre.

### Boucle (harness)

- `optuna.create_study(direction=..., sampler=TPESampler(seed=random_state))`, puis `study.enqueue_trial(start)`. **L'essai 0 est le formulaire** : le meilleur essai est donc au moins aussi bon que lui en validation croisée, par construction.
- **Objectif** : moyenne de `cross_val_score(clone(pipeline_avec_params), x_train, y_train, cv=_fold_splitter(folds, task, y_train), scoring=...)`, sur le **train uniquement**. Le test reste le juge final, jamais regardé pendant le réglage.
- Élagage : `trial.report` après chaque fold, avec `MedianPruner(n_startup_trials=5)`.
- `study.optimize(objective, n_trials=trials, timeout=budget_s, n_jobs=1, catch=(Exception,))`. Un essai qui échoue est noté `failed`, pas fatal.
- Progression : `tuning:{k}/{trials}` à chaque essai terminé.
- **Budget global** : le serveur refuse (`ML_SPEC_INVALID`, champ `tuning_budget_s`) un budget supérieur à `0.6 × ml_train_timeout_s`. Le reste du temps sert au fit final, au rapport et à la sauvegarde. Garder aussi en tête `ml_train_cpu_limit_s` (1 800 s, RLIMIT_CPU).
- Le fit final utilise les meilleurs knobs, traduits par le même `translate`.

`metrics.tuning` :

```json
{"metric": "roc_auc", "direction": "max", "trials_run": 30, "trials_pruned": 8, "trials_failed": 0,
 "stopped_by": "trials|budget", "budget_s": 300, "elapsed_s": 212.4, "folds": 3,
 "start": {"knobs": {...}, "score": 0.861, "std": 0.012},
 "best":  {"knobs": {...}, "score": 0.884, "std": 0.009, "trial": 17},
 "trials": [{"n": 0, "score": 0.861, "state": "complete", "duration_ms": 5400}, ...]}
```

La liste `trials` est plafonnée à 100 entrées et ne contient pas les knobs essai par essai, pour la taille. Les knobs du meilleur essai et du départ sont donnés en entier.

### Côté serveur

- `_apply_summary` écrit `model.knobs = algo.resolve(best.knobs)` et `params_json.estimator_params = estimator_params(...)`. **La carte affiche donc les knobs réellement ajustés.**
- MLflow : si `_register_version` ouvre un run, journaliser les essais en runs enfants (`nested=True`), depuis le résumé, côté worker. Le harness ne parle jamais au serveur de tracking. Si aucun run n'est ouvert aujourd'hui, se limiter à `params["tuned"]=true` et aux métriques `tuning.*` : ne pas inventer de run.
- Plan (`/ml-models/plan`) : avertissement si le budget dépasse le délai restant, et estimation grossière (`trials × folds × durée d'un fit`) quand une version précédente donne une durée.

### Tests

- Propriété `translate` ≡ `estimator_params`.
- Harness sur un petit dataset : l'essai 0 a exactement les knobs du formulaire ; `best.score ≥ start.score` ; `elapsed_s ≤ budget_s + marge` avec un budget de 10 s ; deux runs donnent le même meilleur essai à seed égale (TPE seedé, `n_jobs=1`) ; le test n'est jamais lu pendant le réglage.
- `test_ml_training.py` : refus d'un budget trop grand ; `model.knobs` mis à jour après le résumé.
- Import : optuna absent de `app.main`.

## 6. PR 2e — Pack d'explicabilité

**But.** Répondre à « où le modèle se trompe-t-il, comment décide-t-il, et traite-t-il tous les groupes pareil ? », sur le test, sous budget, sans nouvelle dépendance.

La référence fonctionnelle est papAI, dans `../papai-ml/src/explanation/` :
- `global_interpretability/tree_based/error_analysis/` ;
- `tree_based/surrogate/` ;
- `global_interpretability/partial_dependence.py` ;
- `fairness/fairness.py`.

S'en inspirer pour le *quoi*. **Ne pas copier le code ni dépendre de ces paquets.**

Tout est calculé dans le harness, à l'étape `explaining`, sur au plus `EXPLAIN_ROWS = 5 000` lignes du test (échantillon seedé), avec un budget total de 60 s. Chaque élément est protégé : en cas d'erreur, on écrit `{"error": "..."}` à la place, et le fit n'échoue pas. Le résultat va dans `metrics.explain`, d'au plus 200 Ko en JSON (tronquer, sinon écrire `{"error": "too_large"}`).

### 1. Arbre d'erreur

- Matrice : `inner_pipeline(model)[:-1].transform(x)`, avec les noms de `get_feature_names_out()` (lisibles, du type `region_North`).
- Cible : `y_pred != y` en classification, `|y − ŷ|` en régression.
- `DecisionTreeClassifier` ou `DecisionTreeRegressor(max_depth=3, min_samples_leaf=max(20, 2 % des lignes), random_state=seed)`.
- Sortie : les feuilles triées par `(taux d'erreur − taux global) × support`, cinq au plus :

  ```json
  {"rule": [{"feature": "tenure", "op": "<=", "value": 3.5}, ...],
   "rows": 412, "error": 0.31, "global_error": 0.12, "lift": 2.6}
  ```

- Stable à seed égale (testé).

### 2. Surrogate

- Arbre de profondeur 3 ajusté sur `(X_transformé, prédictions du modèle)`.
- `fidelity` : accuracy (classification) ou R² (régression) du surrogate face au modèle, sur un échantillon distinct.
- Exporter les règles comme ci-dessus.
- La carte n'affiche les règles que si la fidélité atteint au moins 0,7. En dessous, elle dit que le modèle est trop complexe pour un arbre de profondeur 3.

### 3. PDP/ICE

- `sklearn.inspection.partial_dependence(model_servi, x_sample, features=[col], kind="both", grid_resolution=20, categorical_features=...)` sur les **colonnes brutes** : le pipeline accepte un DataFrame.
- Colonnes : les quatre premières de `metrics.importances`.
- 1 000 lignes au maximum ; 30 courbes ICE, amincies.
- En classification binaire : probabilité de la classe positive.
- Sortie par colonne :

  ```json
  {"feature": "tenure", "kind": "numeric|categorical", "grid": [...], "average": [...], "ice": [[...], ...]}
  ```

### 4. Équité (si `fairness_columns`)

- Les colonnes sont lues avec les features : modifier le `pd.read_parquet(columns=...)` du harness. Elles peuvent **ne pas** être des features.
- Validation serveur : la colonne existe, elle est catégorielle ou de faible cardinalité (12 groupes au maximum), et il y en a 3 au plus. Sinon `ML_SPEC_INVALID`.
- Par groupe, sur le test : `n`, taux de sélection (part prédite positive), TPR, FPR, accuracy en classification binaire ; MAE et biais moyen (ŷ − y) en régression. En multiclasse : accuracy seule.
- Disparités :
  - `selection_ratio = min/max` des taux de sélection ; signal si inférieur à 0,8 (règle des quatre cinquièmes) ;
  - `equalized_odds_diff = max(|ΔTPR|, |ΔFPR|)` ;
  - en régression, écart max des MAE rapporté à la MAE globale.
- Les groupes de moins de 30 lignes sont marqués `low_support` et exclus des ratios.
- Calcul en numpy et pandas uniquement, **sans fairlearn**.

### Tests

- Arbre d'erreur et surrogate déterministes à seed égale.
- Fidélité dans [0, 1].
- PDP : forme `(grid, average)` cohérente, catégorielles gérées.
- Équité : jeu de données construit à la main avec un biais planté, ratio inférieur à 0,8 détecté, faible support exclu.
- Budget : un `EXPLAIN_BUDGET_S` minuscule produit des `{"error": "budget"}` sans faire échouer le fit.

## 7. PR 2f (optionnelle) — Texte

**Ce qui existe.** skrub encode déjà en `StringEncoder` (TF-IDF + SVD) une colonne texte de plus de 40 valeurs distinctes.

**Ce qu'on ajoute.**
- Champ de spec `text_encoder: auto | string | minhash`.
- Dans le harness, après `tabular_pipeline`, appliquer `set_params(high_cardinality=...)` au `TableVectorizer`, comme on le fait déjà pour l'imputeur.
- **Pas de `TextEncoder`** : il exige torch.
- Le plan expose `columns[].role = "text"` (chaîne de haute cardinalité, longueur moyenne d'au moins 20 caractères).

**Démonstration** : classification de tickets synthétiques.

## 8. Frontend (transverse, une part par PR)

**Fichiers**
- `features/models/model-train.component.ts` (studio) ;
- `features/flow/.../flow-train-workshop.component.ts` (atelier Flow) ;
- `features/models/model-view.component.ts` (carte : Evidence, Play) ;
- `model-playground.component.ts` ;
- `models.vm.ts` et `models.service.ts`.

**Formulaire**
- Les options tabulaires se rendent **à partir des `spec_fields` du catalogue**, comme le fait `forecast-spec.component.ts` pour la prévision.
- Créer un composant partagé `tabular-options.component.ts`, utilisé par le studio et par l'atelier Flow. Pas de liste de champs codée en dur.
- Sobriété : une section repliée « Options avancées » ; chaque option a une ligne d'explication.

**Carte, onglet Evidence** : graphiques dans la grille `ck-charts` existante, avec les couleurs du thème.
- Réglage : score par essai (nuage), départ contre meilleur, motif d'arrêt, knobs avant et après.
- Calibration : courbes de fiabilité avant et après, diagonale, Brier avant et après.
- Seuil : précision et rappel aux deux seuils.
- Intervalles : couverture par niveau face au niveau nominal, et largeur.
- Explicabilité : règles de l'arbre d'erreur (liste lisible) ; surrogate avec puce de fidélité ; PDP/ICE en petits multiples ; table d'équité avec signaux.

**Play**
- Régression : bande `[lower, upper]` et sélecteur de niveau.
- Classification seuillée : le seuil affiché à côté de la probabilité.
- Le snippet cURL inclut `interval_level`.

**Helpers** : purs dans `models.vm.ts` ou un nouveau `tabular-evidence.vm.ts`, avec leur spec.

**i18n** : FR et EN dans `core/i18n/models.dict.ts`, pour les étapes, les champs, les codes d'erreur (`ML_INTERVAL_LEVEL_UNKNOWN`, `ML_FEEDBACK_NOT_NUMERIC`, `ML_CALIBRATION_TOO_FEW`) et les libellés. Lancer `npm run check:i18n`.

**Tests**
- Specs enregistrées dans `scripts/run-unit.mjs`.
- e2e mocké `e2e/tests/33-models-tabular-extensions-mocked.spec.ts`, avec la fixture `e2e/fixtures/ml-tabular-extensions.json`, en thème sombre/FR et clair/EN, sur le modèle de `31-models-forecast-mocked.spec.ts`.
- Pièges déjà rencontrés : cliquer une colonne via `[data-testid="column-select"][data-name=...]` (pas le texte, qui ouvre une infobulle), et utiliser `exact: true` sur les boutons homonymes dans un dialogue.

## 9. Déploiement

**Toutes les PR**
- Aucune migration.
- Si une PR modifie une Skill du catalogue (schéma de sortie de `ml_predict_*`, description de `ml_train_sklearn_v1`), le dire dans la PR. Après `up` sur la VM, l'utilisateur lance `scripts/agentium-vm-deploy.sh catalog-check`, puis `catalog-apply` si le catalogue est en retard (`docs/agentium-release-process.md` §6b).

**PR 2d**
- Elle reconstruit les images backend et worker (optuna).
- Vérifier les budgets d'image (`AGENTIUM_IMAGE_BUDGET_MB_BACKEND=1160`, `WORKER=1800`) et mettre à jour les tailles de référence dans le doc de release.

**Ordre recommandé** : fusionner et déployer 2a et 2b ensemble, puis 2c, puis 2d, puis 2e. Chaque fusion se fait avec l'accord de l'utilisateur.

## 10. Critères d'acceptation du lot

**Rétro-compatibilité**
- Les tests ML existants restent verts sans modification de leur intention : les fichiers listés en §11, plus le dossier `app/tests/infra` en entier (919 tests verts à `579d99be`).
- Un modèle entraîné avant le Lot 2 se sert, se compare et s'affiche à l'identique.

**Réglage**
- Budget respecté (`elapsed_s ≤ budget_s + 10 %`).
- `best ≥ start` en validation croisée.
- Score de test rapporté pour le modèle final.

**Calibration**
- Brier en baisse sur le cas de test de référence.
- Courbes affichées.
- Seuil choisi hors test.

**Intervalles**
- Couverture du test à ±0,05 du niveau sur des données synthétiques.
- Bornes servies par `/predict`, l'API à clé et le score batch.

**Explicabilité**
- Arbre d'erreur stable par seed.
- Fidélité du surrogate affichée.
- Biais planté détecté par l'équité.
- Budget respecté.

**Contrôles de fin**
- Frontend : `check:i18n`, specs, e2e mocké, puis `build:prod` une fois par PR.
- Parcours navigateur : `/models` → entraîner avec options → Evidence → Play.
- Sur la VM, après déploiement : entraîner une régression avec intervalles et une classification calibrée et réglée sur un dataset de démo, puis lancer Play deux fois (latence à froid puis à chaud).

## 11. Repères dans le code

| Sujet | Fichier |
|---|---|
| Cycle de vie, catalogue d'algos, knobs → params, manifest, résumé | `backend/app/services/tabular_ml.py` (`ALGOS` l.211, `estimator_params` l.305, `validate_training` l.427, `_write_manifest` l.1444, `run_training` l.1529, `_apply_summary` l.1787) |
| Harness d'entraînement (autonome) | `backend/app/resources/ml_train_harness.py` (`main` l.573, `_NarratedSplitter`, `_fold_splitter`, `_importances`, `_trusted_types`, `_persist_report`) |
| Familles, champs de spec | `backend/app/services/ml/families/{base,tabular,forecasting}.py` |
| Knobs typés | `backend/app/services/ml/knobs.py` |
| Registre des métriques | `backend/app/services/ml/metrics.py` |
| Service, journal, score batch, Skill publiée | `backend/app/services/tabular_predict.py` (`predict_rows` l.807, `_rows_from` l.677, `explain_row` l.742, `score_dataset` l.969, `predict_output_schema` l.1393, `serving_block` l.1741) |
| Monitoring et feedback | `backend/app/services/tabular_monitoring.py` (`attach_feedback` l.512, `materialize_labeled` l.558) |
| API | `backend/app/api/v1/endpoints/ml_models.py` |
| Réglages | `backend/app/core/config.py` (`ml_train_*` l.644–669) |
| Exemple de harness qui en charge un autre par chemin | `backend/app/resources/ml_forecast_harness.py` (`_tabular_reader`) |
| Tests ML | `backend/app/tests/services/test_ml_{training,families,predict,registry,comparison}.py`, `test_tabular_monitoring.py`, `backend/app/tests/api/test_ml_{models,predict}_api.py`, `test_ml_catalog_copy_contract.py`, `backend/app/tests/infra/test_{api_import_footprint,demo_dependency_constraints}.py` |
| Front | `frontend-ng/src/app/features/models/*`, `core/i18n/models.dict.ts`, `e2e/tests/31-models-forecast-mocked.spec.ts` (modèle d'e2e) |

## 12. Pièges connus

- **Fuite du test.** Ni le réglage, ni la calibration, ni le seuil, ni les quantiles conformes ne lisent le test. Il sert à mesurer, jamais à choisir. Tester cette propriété explicitement.
- **Wrappers sklearn.** Calibration et seuil cassent toute introspection de `Pipeline` (voir l'audit §4). Une API qui charge un modèle calibré sans `inner_pipeline` plante à l'explication, pas à la prédiction : c'est donc invisible sans test dédié.
- **Postgres JSON refuse `NaN` et `Infinity`.** Tout nombre passe par `_number()` dans le harness (déjà en place).
- **Double traduction des knobs.** Voir §5 : une seule implémentation, testée par propriété.
- **Mémoire.** RLIMIT_AS est à 6 144 Mo et RLIMIT_CPU à 1 800 s dans `supervise_harness`. `n_jobs=1` partout (forêts, `cross_val_score`, optuna).
- **`metrics_json` grossit.** Plafonner les listes (essais, courbes, ICE) et mesurer la taille du résumé dans un test.
- **Le front classe « plus haut = mieux » ce qu'il ne connaît pas** : c'est corrigé par le registre. Toute nouvelle métrique classable va dans `ml/metrics.py`.
- **Disque local plein.** Les tests de harness écrivent dans `tmp_path` : ne pas garder d'artefacts.
