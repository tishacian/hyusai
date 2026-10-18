# M5 — Explicabilité et débogage en production, 18 octobre 2026

Référence : `agentium-mlops-papai-parity-plan.md`, lot M5. Branche
`feat/mlops-m5-explainability`, partie de `demo/agentic` à `d814837b`, en
parallèle du lot M4.2. Rien n'est fusionné, déployé ni activé. Aucune
dépendance Python ni image n'est ajoutée : `shap` reste dans la seule image
ml-ts. `/api/v1/build-info` n'est pas modifié.

## Contrats livrés

### SHAP par prédiction (modèles à arbres)

- `/predict` accepte `explain_method` : `auto`, `shap` ou `counterfactual`.
  Le défaut reste `counterfactual` pour les clés API et les wrappers de Flow :
  leur réponse est inchangée (`contributions` seules, aucune clé nouvelle).
  L'onglet Play envoie `auto`.
- `auto`/`shap` : si l'estimateur final du pipeline servi est un arbre
  scikit-learn (RandomForest, ExtraTrees, GradientBoosting,
  HistGradientBoosting, DecisionTree, classifieur ou régresseur) **et** qu'un
  consommateur ml-ts écoute la file RPC (`CELERY_ML_TS_SERVE_QUEUE`) avec un
  environnement qui lit l'artefact, l'API envoie la tâche `agentium.ml_tree_shap`
  et attend au plus `ML_EXPLAIN_TIMEOUT_S`. Le worker charge le modèle par la
  voie vérifiée (`load_pipeline_traced` → `verify_model_bundle`), transforme la
  ligne avec le prétraitement du pipeline, explique l'estimateur final, puis
  **somme les valeurs de Shapley de chaque colonne encodée sur le champ d'entrée
  qui l'a produite** (`TableVectorizer.output_to_input_` de skrub 0.11, plus
  `missingindicator_<col>` d'un imputeur). Une somme sur un groupe conserve
  l'additivité.
- Réponse : `explanation = {method: tree_shap | tree_shap_approximate,
  output_space, estimator, class, base, output, contributions: [{field, value,
  contribution}], other: {fields, contribution} | null, additivity_gap,
  duration_ms}`, triée par |contribution|, `ML_EXPLAIN_SHAP_TOP_FIELDS` champs
  puis un reste « autres champs » : `base + Σ contributions + other = output`.
- Espace de sortie, tel que TreeExplainer l'explique réellement :
  `probability` pour une forêt ou un arbre classifieur (probabilité de la
  classe) ; `log_odds` pour un boosting binaire ; `raw_score` pour un boosting
  multiclasse (score brut de la classe, avant softmax) ; `value` pour un
  régresseur. En binaire, la classe expliquée est la classe positive du score
  servi ; en multiclasse, la classe prédite. Le test vérifie que la sortie
  expliquée est bien la probabilité servie (forêt) ou son logit (boosting).
- Sinon (`auto`) : le contrefactuel actuel répond et `explanation = {method:
  counterfactual, reason}` dit pourquoi : `shap_unavailable` (aucun
  consommateur ml-ts vivant, image sans `shap`, broker indisponible),
  `shap_disabled`, `not_a_tree_model`, `calibrated_model`, `unsupported_tree`,
  `timeout`, `runtime_mismatch`, `feature_mapping_unavailable`, `class_unknown`,
  `explain_failed`. `shap` demandé explicitement et indisponible → 409
  `ML_EXPLAIN_UNAVAILABLE` avec `details.reason`, sans journal.
- Une explication ne fait jamais échouer une prédiction : toute exception du
  chemin TreeSHAP devient une raison (`explain_failed`), et l'attente est bornée
  par `ML_EXPLAIN_TIMEOUT_S` (3 s par défaut : un worker chaud et l'aller-retour
  broker y tiennent largement ; un chargement à froid qui dépasse se termine
  dans le worker — `expires` ne borne que l'attente en file — et rend l'appel
  suivant chaud).
- Budget exact/approché, sur le modèle de `explain_forecast` : si une
  explication exacte dépasse `ML_EXPLAIN_SHAP_EXACT_BUDGET_S`, le worker passe
  ce modèle chargé en TreeSHAP approché (`tree_shap_approximate`), additif lui
  aussi.
- Journal et confidentialité : même règle qu'aujourd'hui. Quand les entrées ne
  sont pas conservées (`store=false` ou politique du workspace), les `value`
  de `explanation.contributions` sont retirées du journal comme celles des
  `contributions`, sans modifier la réponse ; les effets restent. Rien d'une
  valeur d'appelant n'est stocké.

### Contrefactuels (« que faudrait-il changer ? »)

- `POST /ml-models/{id}/counterfactuals` : `row`, `fields` (1 à 3 champs
  déclarés modifiables), `target` (`class` pour un classifieur — par défaut
  toute autre réponse, l'autre classe en binaire ; `min`/`max` pour une
  régression), `version` facultative comme `/predict`.
- Valeurs candidates tirées **du seul contrat d'entrée** : niveaux d'une
  catégorie, vrai/faux, ou une grille de `ML_COUNTERFACTUAL_GRID_POINTS` points
  dans `[min, max]` d'entraînement, plus la médiane ; entière quand min, max et
  médiane l'étaient. Jamais hors de la plage. Un champ sans ces faits est
  refusé avec sa raison (`no_range`, `constant`, `no_levels`,
  `unsupported_kind`, `no_alternative`) ; si aucun ne reste : 422
  `ML_COUNTERFACTUAL_FIELDS_UNSUPPORTED` avec `details.refused`.
- Recherche à 1 champ, puis 2, puis 3 ; une combinaison qui contient un
  changement déjà suffisant seul n'est pas un nouveau résultat ; arrêt dès que
  le niveau courant donne assez de résultats. Budget dur
  `ML_COUNTERFACTUAL_MAX_CANDIDATES` lignes, prédites par lots de
  `ML_COUNTERFACTUAL_BATCH_ROWS` avec le pipeline chargé de `/predict`.
  Classement : nombre de champs changés, puis distance normalisée (écart /
  plage d'entraînement ; 1 par champ catégoriel). Jusqu'à
  `ML_COUNTERFACTUAL_MAX_RESULTS` résultats choisis pour leur diversité (des
  ensembles de champs différents d'abord) et présentés dans l'ordre du
  classement, avec la nouvelle prédiction et sa probabilité. Statuts : `found`,
  `not_found`, `already_reached` ; `evaluated`, `budget`, `exhausted`.
- Droits : action `predict` (niveau lecture). Session de workspace uniquement :
  les clés API ne sont pas acceptées (voir les adaptations).
- Admission M1 : un appel = **une requête et une ligne** sur le budget de la
  lignée (`ml_governance.admit`). La question est interactive et ne contourne
  pas l'admission ; ses lignes candidates internes ne consomment pas le budget
  de lignes par minute du trafic réel. Rien n'est journalisé, aucun shadow,
  rien n'est stocké, quelle que soit la politique `store`.

### Débogage du modèle en production

- Rapport construit sur les **échantillons de production étiquetés** (feedback
  par échantillon M2 et anciens labels d'appels unitaires) **servis par cette
  version exacte** (`served_id`), dans une fenêtre facultative (`since`,
  `until` sur la date de prédiction).
- Mesure d'erreur : **la réponse réellement servie, lue dans le journal**,
  comparée au label — jamais une nouvelle prédiction. Un test le prouve : les
  réponses servies d'un groupe sont faussées dans le journal alors que le
  modèle re-prédirait juste, et l'arbre trouve ce groupe.
- `ML_PRODUCTION_DEBUG_MIN_ROWS` (50) échantillons utilisables au minimum,
  sinon statut `insufficient_data` avec les comptes ; au plus
  `ML_PRODUCTION_DEBUG_MAX_ROWS` (5 000), les plus récents (date puis id du
  journal), de façon déterministe.
- Exclusions comptées par raison : `inputs_not_retained` (`store=false`,
  politique, échantillon au-delà du plafond de 64 par appel),
  `answer_missing`, `label_invalid`, `beyond_max_rows` (labels non lus).
- `error_tree` et `fairness` de `ml_explanation_extensions.py` sont réutilisés
  via un paramètre facultatif `predicted=` (réponses servies) — plus `matrix=`
  pour l'arbre et `classes=` pour la fairness. Sans ces paramètres, le
  comportement d'entraînement est identique.
- Fairness : groupes = `spec.fairness_columns` déclarées à l'entraînement
  (et présentes dans les entrées servies) ; aucune → section absente avec
  `no_sensitive_columns` ; colonne absente des entrées → `not_in_inputs`.
- Exécution : tâche Celery `agentium.ml_production_debug` sur le worker
  général (en ligne en mode eager), limitée par
  `ML_PRODUCTION_DEBUG_TIME_LIMIT_S`. À la demande (action d'écriture auditée)
  ou depuis `monitor_cycle`, au plus une fois par
  `ML_PRODUCTION_DEBUG_INTERVAL_MINUTES` et seulement si de nouveaux labels
  sont arrivés (empreinte nombre + dernier `labeled_at`). L'identifiant
  planifié dérive de cette empreinte : un cycle rejoué ne crée rien. Le cycle
  prépare le rapport dans sa transaction (savepoint : un échec n'annule jamais
  la surveillance) et le confie au worker après son commit. Un envoi refusé
  par le broker ou une analyse perdue (deux fois la limite de temps) est
  marqué en échec avec un code et repris au cycle suivant.
- Table `ml_production_explanations` : workspace, modèle, version, déclencheur
  (`manual|scheduled`), fenêtre, comptes (étiquetés, utilisés, exclus par
  raison), métriques, rapport JSON borné (`ML_PRODUCTION_DEBUG_MAX_REPORT_BYTES`,
  l'arbre dessinable est retiré avant les règles si nécessaire), badge de
  fairness, empreinte, statut, code d'erreur, auteur, dates. Agrégats
  uniquement : règles, effectifs des nœuds, métriques par groupe, comptes —
  jamais une ligne de production. Historique borné
  (`ML_PRODUCTION_DEBUG_HISTORY`). Supprimée avec le modèle par le même chemin
  que ses clés (`delete_model`), et par cascade SQL.

### Surveillance de la fairness

- Pour chaque colonne : écart entre groupes assez grands
  (`ML_FAIRNESS_MIN_GROUP_ROWS`, 30 comme le seuil « faible effectif » de la vue
  d'entraînement), dans la même famille de métriques que cette vue : différence
  d'égalité des chances (plus grand écart de TPR ou de FPR, absolu) en
  binaire, écart d'exactitude en multiclasse, écart de MAE rapporté à la MAE
  globale en régression. Badge `ok | watch | alert` aux seuils
  `ML_FAIRNESS_WATCH_GAP` (0,05) et `ML_FAIRNESS_ALERT_GAP` (0,10) : 0,10
  d'écart de taux est la tolérance usuelle de l'égalité des chances ; 0,05
  laisse une marge d'observation avant l'alerte. Le badge du rapport est le
  pire des colonnes.
- Changement de badge → alerte M3 `fairness_gap` via
  `ml_alerts.emit_alert`, dans la transaction du rapport. Le badge précédent
  est celui du dernier rapport terminé de la version ; une première
  observation n'alerte que si elle n'est pas `ok`, comme `monitor_transition`.
  Drapeau `ML_ALERTS_ENABLED`, limitation de fréquence et déduplication par
  source de M3 s'appliquent sans changement.

### Droits et audit (M1)

- Lire les rapports : `read`. Lancer une analyse : `score` (écriture).
  Contrefactuels : `predict`.
- L'analyse manuelle est auditée `ml.model.production_debug` dans la
  transaction qui crée le rapport en file : une panne d'audit (503
  `ML_AUDIT_UNAVAILABLE`) ne laisse aucun rapport.

### Interface (fiche modèle)

- Play : TreeSHAP en liste de barres signées, tons neutres (la direction est
  l'information, pas un verdict), de la valeur de base à la sortie, ligne
  « autres champs », méthode (exacte ou approchée) et espace de sortie écrits
  en clair. En repli, les barres contrefactuelles d'aujourd'hui, précédées de
  la méthode et de la raison. Panneau « Que faudrait-il changer pour obtenir
  une autre réponse ? » : 1 à 3 champs (seuls ceux que le contrat permet de
  bouger, décidés comme le serveur), réponse ou plage visée, tableau des
  résultats.
- Preuves : section « En production » — arbre d'erreur de production tracé
  avec `<ck-decision-tree-chart>` via le composant d'explication existant,
  tableau des groupes, écarts et badge, comptes, exclusions, date et fenêtre,
  bouton « Analyser la production » conditionné à
  `serving.permissions.score` (aucune déduction de rôle dans le composant),
  relecture tant que l'analyse est en cours.
- Suivi : badge de fairness et série des écarts par colonne avec le seuil
  d'alerte. Les boîtes d'alertes M3 nomment `fairness_gap`.
- Libellés FR/EN dans le dictionnaire des modèles ; fonctions pures dans
  `explanations.vm.ts` et `production-debug.vm.ts`.

## Adaptations et pourquoi

1. **Identifiant de migration.** `139_mlops_production_explanations` fait
   33 caractères ; `alembic_version.version_num` est un `varchar(32)` (un test
   existant le vérifie). La révision, développée sous le numéro 139, est
   devenue `140_mlops_prod_explanations` à l'assemblage : `demo/agentic` avait
   pris 138 (`138_activity_measures`) et M4.2 est devenu 139.
2. **HistGradientBoosting et TreeSHAP.** shap 0.52 ne lit que les seuils
   numériques des arbres HGB : une coupure catégorielle (bitset) y serait lue
   comme un seuil, et le réordonnancement interne des colonnes catégorielles
   (`_preprocessor`) est ignoré. Le modèle HGB par défaut du catalogue coupe
   sur ses catégories (14 coupures sur le modèle de test). Le worker
   reconstruit donc chaque arbre **pour la ligne expliquée** : chaque coupure
   catégorielle devient la branche que la ligne suit selon la règle de
   `_predictor.pyx` de scikit-learn, puis les arbres sont donnés à
   `shap.TreeExplainer` sous sa forme dictionnaire documentée. Le TreeSHAP
   dépendant du chemin ne lit la ligne que pour choisir la branche suivie, donc
   le résultat est exact. Preuves : additivité fermée sur les sorties réelles
   (écart < 1e-6) et égalité avec le lecteur natif de shap quand celui-ci est
   correct (HGB sans catégorie). Le GradientBoosting multiclasse, refusé par
   shap, passe par la même forme.
3. **Profil de confiance du lecteur.** `sklearn.tree._tree.Tree` manquait au
   profil `tabular-skops-v1` : tout modèle `random_forest` du catalogue (et
   tout GradientBoosting, ExtraTrees ou DecisionTree) s'entraînait mais était
   refusé au service (`ML_ARTIFACT_UNTRUSTED_TYPES`), vérifié sur la base. Le
   type scikit-learn est ajouté ; c'était indispensable pour expliquer une forêt.
4. **Modèles calibrés.** La probabilité servie combine plusieurs modèles de
   pli calibrés ; aucun arbre ne l'explique seul : `calibrated_model`, repli.
   Un seuil de décision (`FixedThresholdClassifier`) ne change pas les
   probabilités : expliqué.
5. **Modèles linéaires.** Contrefactuel conservé : le SHAP linéaire exact
   exige les moyennes d'entraînement des colonnes transformées, que
   l'artefact ne conserve pas.
6. **Transition de fairness.** `monitor_transition` tient un seul état par
   modèle (`ml_alert_states`, badge de surveillance) : y écrire la fairness
   mélangerait deux badges. La transition est calculée depuis le rapport
   précédent, puis `emit_alert` (nouvel événement `fairness_gap`) fait le reste.
7. **Permission d'analyse.** `score` est l'action d'écriture qui autorise déjà
   à faire tourner le pipeline d'un modèle sur des données enregistrées dans le
   worker général ; une nouvelle action aurait modifié la matrice M1 publiée
   et le contrat `permissions` de l'interface.
8. **Contrefactuels sans clé API.** Une clé est de portée `predict` et chaque
   appel évalue jusqu'à 2 000 lignes en n'en payant qu'une : ouvrir la route
   aux clés offrirait un facteur d'amplification (et un outil d'extraction du
   modèle) à un détenteur de clé. Les appels ne sont pas comptés dans l'usage
   M3 : ce n'est pas un appel servi et rien n'est journalisé.
9. **Arbre d'erreur de production sur matrice encodée.** skrub remet aux
   modèles HGB des colonnes catégorielles pandas qu'un arbre de décision ne sait
   pas couper. L'arbre de production reçoit les colonnes transformées du
   pipeline, catégories en indicateurs `<colonne>_<niveau>` (nommage de skrub).
   Constat hors périmètre, non corrigé par consigne : la même limite fait
   échouer l'arbre d'erreur et le substitut **d'entraînement** des modèles HGB
   avec catégories (`ValueError`, section affichée en erreur). Le comportement
   d'entraînement est inchangé.
10. **Purge de rétention.** La purge M1 supprime la ligne de journal et, par
    cascade M2, ses labels : un échantillon purgé n'existe plus et ne peut pas
    être compté. Seuls les labels présents sans entrée conservée sont comptés
    (`inputs_not_retained`).
11. **Hook de surveillance.** Le résultat d'un cycle reste celui du contrat
    du nœud ; l'état du débogage est écrit dans l'instantané
    (`result.production_debug`), pas dans la sortie du Skill.

## Migration et activation

Migration `140_mlops_prod_explanations`, `down_revision =
"139_mlops_requalification"` (M4.2). Développée en 139 après 137, elle a été
rechaînée à l'assemblage, avec l'ordre de `CHAIN` dans
`test_tabular_migration.py` et la tête attendue par `test_public_bench.py`. Le downgrade refuse de supprimer une table non vide
(`ML_EXPLANATIONS_DOWNGRADE_NOT_EMPTY`) ; ne pas vider la table pour le
contourner.

Activation, après sauvegarde :

1. Appliquer 140 (après 135–139), puis déployer API, worker général **et image
   ml-ts construits depuis le même commit** : la tâche `agentium.ml_tree_shap`
   vit dans le code de l'image ml-ts existante. Aucune nouvelle image.
2. Vérifier le heartbeat du service ml-ts sur `ml_ts_rpc`, puis une prédiction
   d'une forêt depuis Play : la méthode affichée doit être TreeSHAP. Sans le
   profil compose `ml-ts`, le repli `shap_unavailable` est le comportement
   attendu. `ML_EXPLAIN_SHAP_ENABLED=false` coupe l'appel RPC.
3. Le débogage planifié suit la surveillance déjà configurée ; l'alerte
   `fairness_gap` suit `ML_ALERTS_ENABLED`, `false` par défaut.

## Réglages

| Réglage | Défaut | Rôle |
|---|---:|---|
| `ML_EXPLAIN_SHAP_ENABLED` | `true` | Autorise l'appel RPC TreeSHAP |
| `ML_EXPLAIN_TIMEOUT_S` | 3,0 | Attente maximale de l'API |
| `ML_EXPLAIN_SHAP_TOP_FIELDS` | 8 | Champs détaillés avant « autres champs » |
| `ML_EXPLAIN_SHAP_EXACT_BUDGET_S` | 1,0 | Au-delà, ce modèle passe en approché |
| `ML_COUNTERFACTUAL_MAX_CANDIDATES` | 2 000 | Budget dur de lignes candidates |
| `ML_COUNTERFACTUAL_BATCH_ROWS` | 500 | Taille des lots prédits |
| `ML_COUNTERFACTUAL_GRID_POINTS` | 12 | Points de grille numérique (+ médiane) |
| `ML_COUNTERFACTUAL_MAX_RESULTS` | 3 | Résultats rendus |
| `ML_PRODUCTION_DEBUG_MIN_ROWS` | 50 | Minimum d'échantillons utilisables |
| `ML_PRODUCTION_DEBUG_MAX_ROWS` | 5 000 | Plafond, les plus récents |
| `ML_PRODUCTION_DEBUG_INTERVAL_MINUTES` | 1 440 | Intervalle minimal planifié |
| `ML_PRODUCTION_DEBUG_TIME_LIMIT_S` | 300 | Limite de la tâche ; perte à 2× |
| `ML_PRODUCTION_DEBUG_MAX_REPORT_BYTES` | 200 000 | Taille du rapport stocké |
| `ML_PRODUCTION_DEBUG_HISTORY` | 50 | Rapports gardés par version |
| `ML_FAIRNESS_WATCH_GAP` | 0,05 | Badge `watch` |
| `ML_FAIRNESS_ALERT_GAP` | 0,10 | Badge `alert` |
| `ML_FAIRNESS_MIN_GROUP_ROWS` | 30 | Effectif minimal d'un groupe comparé |

Le maximum de trois champs modifiables est un contrat d'API (`MAX_FIELDS`),
pas un réglage : la recherche est combinatoire.

## Vérifications

Toutes les commandes partent de `backend/` ou `frontend-ng/` du worktree,
avec le venv et les `node_modules` partagés (scikit-learn 1.9.0, skrub 0.11.0,
skops 0.16.0, mlflow 3.15.2, shap 0.52.0 importable ; Node 22).

**Backend**

- **61 tests M5 réussis** : `test_ml_tree_explanations.py` (20),
  `test_ml_counterfactuals.py` (17), `test_ml_production_debug.py` (21),
  `test_ml_production_debug_schedule.py` (3). Modèles réels entraînés par le
  harnais de production : HGB classifieur avec coupures catégorielles, forêt
  avec champ texte (30 colonnes StringEncoder → une contribution), HGB
  régresseur, HGB numérique comparé au lecteur natif de shap, régression
  logistique pour le repli. Chemins de repli : image API sans `shap`
  (simulée, puisque `shap` est importable dans le venv de test), worker sans
  `shap`, aucun heartbeat ml-ts, délai dépassé, environnement incompatible,
  refus explicite `shap` (409, aucun journal), méthode inconnue, défaut
  inchangé ; confidentialité du journal. Contrefactuels : règles plantées
  (ET et OU), minimalité, plage d'entraînement, budget, refus, admission
  comptée une fois, droits HTTP. Débogage : zone d'erreur plantée dans les
  réponses servies, biais de groupe et alerte unique par transition (drapeau
  M3 actif) ou aucune (drapeau inactif), régression, exclusions, données
  insuffisantes, isolement de version, plafond déterministe, fenêtre, raisons
  de fairness absente, planification (limitation, idempotence, reprise d'un
  envoi refusé), hook `monitor_cycle`, atomicité de l'audit, suppression avec
  le modèle, historique borné, droits HTTP.
- **Régression élargie en `-n 4` : 609 réussis, 71 ignorés** sur 24 fichiers
  (service et API de prédiction, contrat d'artefact, gouvernance, runtime
  deep, pack d'explication d'entraînement, alertes, réentraînement et reprise,
  hooks de surveillance et d'opérations, justesse M2, registre, shadow réel,
  exports, endpoints, catalogue de tête Alembic, migrations). Les 71 ignorés
  sont les tests de migration qui exigent PostgreSQL, exécutés à part :
- **73 tests de migration réussis sur PostgreSQL 16.2 réel** (pgserver, en
  13 min 51 s) : chaîne ciblée 096 → 137 puis 139 pas à pas, comparaison
  ORM/DDL de la nouvelle table (colonnes, nullabilité, index), cascade avec le
  modèle et le workspace, refus du downgrade non vide puis downgrade et
  ré-upgrade. Ce n'est pas un rejeu de tout l'historique Alembic.
- Ruff : 0 constat sur les fichiers créés ; les fichiers existants touchés
  gardent exactement leurs constats antérieurs (`ml_models.py` 34,
  `config.py` 35, `models/__init__.py` 3, `router.py` 1,
  `ml_explanation_extensions.py` 2, `conftest.py` 1, identiques à `d814837b`).
  `ruff format` n'a été appliqué qu'aux fichiers nouveaux ou déjà formatés.
- Non relancés : `test_ml_training.py` (harnais en sous-processus, sensible à
  l'environnement local) ; le harnais n'est pas modifié et les suites M5
  l'exécutent pour fabriquer leurs modèles.

**Frontend**

- **2 366 tests unitaires réussis** (dont 25 nouveaux : spécifications pures
  des deux view-models et comportement des composants : pas de requête sans
  champ, une seule recherche à la fois, réponses d'un autre workspace
  ignorées, bouton d'analyse fermé sans `score`, relecture pendant l'analyse,
  refus traduits en clés). TypeScript, `check:i18n` (12 914 clés) et
  `check:nav-links` réussis sur l'état final.
- `check:ui-chrome` reste rouge sur l'état préexistant de `src/styles.scss`
  (7 halos, plafond 6) ; aucun constat ne vient de M5. Les plafonds ne sont
  pas relevés.
- **`build:prod` exécuté deux fois** au lieu d'une : le premier build a réussi,
  puis les captures de l'E2E ont montré que l'arbre de production réutilisé
  affichait « mesuré sur N lignes du test », ce qui est faux en production.
  Après correction (`29203b97`), le second build, sur l'état final, réussit
  avec 13 avertissements Angular, tous préexistants, aucun dans un fichier M5.
- **E2E mocké** (Chrome, build de production servi localement) : nouveau
  `53-models-production-explanations-mocked.spec.ts`, **6/6** en FR/sombre et
  EN/clair (« En production », écart de fairness et arbre, lancement d'une
  analyse, veille de fairness du Suivi, Play en `auto` avec barres TreeSHAP,
  recherche contrefactuelle). Specs voisines relancées sur le même build :
  `43` et `52` réussissent ; `33`, `34`, `37` et `44` donnent 18 réussites et
  **11 échecs, identiques sur la base `d814837b`** reconstruite à part (mêmes
  tests, mêmes signatures : bouton « Entraîner » introuvable sur la liste,
  champ « Prédiction » du feedback désactivé faute de `permissions.feedback`
  dans ces anciens doublons). Ils ne sont pas causés par M5 et ne sont pas
  corrigés ici.

## Limites

- TreeSHAP : seulement la famille tabulaire en service dans l'API, estimateurs
  arbres de scikit-learn ; HGB régresseur à perte non identité (poisson,
  gamma), modèles calibrés, linéaires, KNN, familles `tabular_deep`,
  `tabular_foundation`, clustering : contrefactuel. Les prévisions gardent
  leur propre explication (`explain_forecast`).
- Déploiements sans profil `ml-ts` : toujours `shap_unavailable`.
- Le premier appel d'un gros modèle peut dépasser le délai et répondre par le
  contrefactuel (`timeout`).
- Contrefactuels : le contrat ne conserve ni quantiles ni distribution ; la
  grille est uniforme dans la plage d'entraînement, les catégories à trop de
  niveaux et les dates sont refusées. Ce sont des réponses du modèle, pas des
  causes. Pas de contrainte de plausibilité jointe entre champs.
- Débogage en production : famille tabulaire uniquement ; 64 échantillons
  journalisés au plus par appel ; colonnes sensibles limitées à celles qui
  sont des entrées du modèle, trois au plus et douze groupes au plus (limites
  de la fonction d'entraînement réutilisée) ; en régression l'écart est relatif
  à la MAE globale.
- Non qualifiés ici : un vrai worker ml-ts derrière RabbitMQ (le chemin RPC est
  testé avec un `send_task` simulé et en mode eager), la VM, la charge, une
  destination SMTP/webhook réelle.
