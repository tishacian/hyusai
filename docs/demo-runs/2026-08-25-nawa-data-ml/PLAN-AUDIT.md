# Audit de complétion — « Plan Data/ML Agentium »

Audit exigence par exigence du plan `/opt/cursor/artifacts/plans/plan_data_ml_agentium_1b3559c9.plan.md`
contre l'état réel de l'arbre, conduit le 27/08/2026 en lecture seule. Révision servie sur
`omnirag-demo` au moment de l'audit : `29aa898159b5`.

## Ce que cet audit est, et ce qu'il n'est pas

Chaque exigence est jugée sur une preuve nommée — un fichier, un symbole, un test — et non
sur la présence d'un fichier au nom plausible. Quatre verdicts :

| Verdict | Sens |
|---|---|
| **Tenu** | La preuve montre le comportement nommé par le plan. |
| **Tenu autrement** | L'intention du plan est satisfaite, par un moyen que le plan ne nommait pas. Documenté ici parce qu'un lecteur du plan chercherait la mauvaise chose. |
| **Écart** | Une partie de l'exigence manque. Ce qui manque est nommé. |
| **Manquant** | Le livrable n'existe pas. |

Ce que l'audit **ne** couvre pas : le rendu à l'écran. Un composant qui compile et porte les
bonnes classes peut rendre mal. Les points qui demandent un navigateur ou un worker vivant
sont listés en fin de chaque section plutôt que comptés comme tenus.

---

## Phase 1 — Socle datasets

Neuf exigences, neuf **tenues**. `TabularDataset` porte les champs nommés, la clé Parquet
suit le motif `workspaces/<ws>/tabular/datasets/<id>/data.parquet`, la migration `096` crée
la table, le stockage passe par la façade `ObjectStore`, la suppression est un *soft delete*
qui respecte la policy append-only de MinIO, l'ingest est bien la tâche Celery
`agentium.dataset_ingest` en polars, les quatre routes existent, et la page Data est
enregistrée sous le verbe Build avec son dictionnaire FR/EN complet.

Preuves : `backend/app/models/tabular.py`, `backend/app/services/tabular_datasets.py`
(`dataset_prefix`, `profile_frame`, `soft_delete`), `backend/alembic/versions/096_tabular_data_plane.py`,
`backend/app/api/v1/endpoints/datasets.py`, `backend/app/workers/tasks.py` (`dataset_ingest`),
`frontend-ng/src/app/features/data/`, `frontend-ng/src/app/core/i18n/data.dict.ts`.

## Les six paris UI/UX

| Pari | Verdict | Ce qui manque |
|---|---|---|
| 1 — un seul composant table, réutilisé partout | **Écart** | `DataTableComponent` existe avec tout ce que le pari demande (en-tête collant, icône de type, `tabular-nums`, nulls estompés, badge « n lignes · k colonnes », mini-histogrammes, popover de stats) et il est réutilisé par le détail dataset, l'onglet Test des transformations et la sortie du batch score. Le **picker de colonnes du train** ne l'utilise pas : il rend `ck-column-spark`. |
| 2 — colonnes profilées à l'ingest | **Tenu** | — |
| 3 — zéro spinner muet | **Écart** | L'ingest et l'entraînement écrivent bien leurs étapes dans `status_detail`, le front polle et rend une check-list, avec toast de fin chiffré. **Le batch score n'a rien de tout ça** : pas de flux d'étapes, pas de check-list, pas de toast. C'est le tiers manquant d'un pari qui en nommait trois. |
| 4 — le canvas montre la donnée qui coule | **Tenu** | `_node_data_badge` côté moteur, `nodeRunBadge` côté canvas. Rendu à confirmer sur un run réel. |
| 5 — Playground de prédiction | **Tenu** | Formulaire depuis la signature, cadran animé, contributions, cURL à côté. |
| 6 — la provenance comme fil rouge | **Écart** | Les chips de lignage du détail dataset, les colonnes badgées « scoré par », le chip de provenance de la skill et le lien profond du toast de publication sont tous là. Le **lignage de la model card** est une chaîne de versions plus un lien vers le dataset, pas le fil complet dataset → transfo → modèle → dataset scoré que le plan décrit. |

Hygiène : squelettes de chargement **tenus** sur les quatre pages, kit viz unique **tenu**
(`features/data/viz/` : `curve-chart`, `confusion-matrix`, `bar-list`), courbes chart.js avec
aire remplie et diagonale de référence **tenues**, matrice de confusion en CSS grid sans
dépendance **tenue**, FR/EN **tenu**. Les empty states existent avec un CTA unique mais
rendent une icône dans une tuile, pas l'illustration dessinée que le plan demandait — **écart
mineur**, assumé tel quel.

## Phase 2 — Node SQL

| Exigence | Verdict | Note |
|---|---|---|
| Skill `sql_transform_v1` + wrapper duckdb, matérialisation en dataset | **Tenu** | `tabular_transforms.py` (`execute_sql`, `run_sql_transform`, `register_frame`) |
| Garde `WITH`/`SELECT` uniquement | **Tenu autrement** | `validate_sql` est plus stricte que le plan sur les effets de bord et plus large sur les formes lues : elle accepte aussi `FROM`, `TABLE`, `VALUES`, `DESCRIBE`, `SUMMARIZE`. Les entrées sont montées en tables avec alias de vue, pas en vues seules. |
| Injection `_transform` dans `dag.py` + strip des enveloppes d'échec | **Tenu** | `_apply_transform_node_config`, `_passthrough_without_recipe` |
| Éditeur CodeMirror SQL + autocomplétion depuis les schémas d'entrée | **Tenu** | `@codemirror/lang-sql` en dépendance, `sqlSchema` alimenté par `editorSqlSchema`. L'autocomplétion porte les **noms** de colonnes ; les types s'affichent dans la sidebar. |
| Sidebar de colonnes cliquables | **Tenu** | `insertColumn` |
| Onglet Entrées, picker par port | **Tenu** | tab `sources` |
| Onglet Test : check-list, erreur pointée, badge « 142 ms · 6 903 lignes », table partagée | **Écart** | Tout le comportement existe — check-list `transform-steps`, saut à la ligne fautive `jump-to-error`, résultat en `ck-data-table` — mais il n'y a **pas d'onglet nommé Test** (bouton Run et panneau de résultat sous l'éditeur), et le badge est **scindé** : la durée dans la légende, les lignes et colonnes dans une puce séparée. |
| Capability universelle « Tabular Transforms » | **Tenu** | seed `tabular_transforms`, tier universal, trois skills réclamées |

## Phase 3 — Node Polars

| Exigence | Verdict | Note |
|---|---|---|
| Skill `polars_transform_v1`, code auteur `transform(dfs)`, harness isolé, venv content-addressed `polars==1.x` | **Tenu** | `polars_harness.py`, `tabular_polars.py`, `polars==1.44.0` épinglé en configuration. Le paramètre s'appelle `inputs` et non `dfs` — même contrat. |
| Le template gère lecture/écriture Parquet et l'enregistrement du dataset de sortie | **Tenu** | `_settle_result` → `register_frame` |
| Atelier = réutilisation de l'atelier recette | **Tenu autrement** | Composant distinct `app-flow-transform-workshop` partageant les mêmes briques (CodeMirror, polling `RecipeExecution`), pas une réutilisation directe. |
| **Sans onglet requirements** (environnement imposé) | **Manquant** | L'atelier Polars **expose** un onglet Environnement avec un `requirements_text` éditable, pour des extras au-dessus du polars épinglé. C'est l'inverse de ce que le plan demandait. Décision à prendre : retirer l'onglet, ou amender le plan en assumant les extras. |

## Phase 4 — Node dbt

| Exigence | Verdict | Note |
|---|---|---|
| Skill `dbt_transform_v1`, mini-projet dans la config du node | **Tenu** | `models`, `tests_yml`, `output_model` |
| Scaffold `dbt_project.yml` + `profiles.yml`, `dbt build` en venv `dbt-core`+`dbt-duckdb` | **Tenu** | `dbt_harness.py`, requirement épinglé `dbt-duckdb==1.9.4` / `dbt-core==1.12.3` |
| Remontée de `run_results`, tests dbt inclus | **Tenu** | `_build_report`, `dbt-report` côté front |
| Matérialise **les modèles sélectionnés** en datasets | **Écart** | Un seul modèle publié → un seul dataset. Le pluriel du plan n'est pas honoré ; cohérent avec le « périmètre serré » annoncé, mais c'est une restriction réelle. |
| Atelier minimal : liste de fichiers, éditeur, log de run | **Tenu** | log structuré plutôt que sortie CLI brute |

## Phase 5 — Entraînement sklearn + registry

| Exigence | Verdict | Note |
|---|---|---|
| Modèle `MLModel` avec les champs nommés | **Tenu** | `backend/app/models/tabular.py`, migrations 096 puis 097 |
| Artefacts MLmodel sur l'object store, `s3://` via `MLFLOW_S3_ENDPOINT_URL` + boto3, `file://` en dev, pas de joblib nu | **Tenu autrement** | `mlflow.sklearn.save_model(..., signature=..., input_example=...)` puis upload, et non `log_model`. Les clés sont sous `workspaces/…/ml/models/…` et non sous un préfixe `mlflow/`. L'intention du plan — artefacts portables, signature et exemple embarqués, aucun serveur à opérer — est tenue. À noter : l'état skore est stocké en joblib **à part**, ce qui n'est pas le modèle. |
| Skill `ml_train_sklearn_v1` + tâche Celery, `skrub.tabular_pipeline` | **Tenu autrement** | `tabular_pipeline(estimator)` et non `tabular_pipeline(task)`. HistGradientBoosting par défaut, `linear` et `random_forest` réellement sélectionnables jusqu'au harness. |
| `skore.EstimatorReport`, courbes plafonnées à 500 points, importances par permutation, option validation croisée avec écart par fold | **Tenu** | Bout en bout vérifié : case dans l'UI → API → `CrossValidationReport` → `metrics_json.cv` → rendu avec l'écart-type, et la progression « Fold 3/5 » dans la check-list. |
| État du rapport persisté via `get_state()` en artefact du run MLflow | **Tenu autrement, assumé** (adjugé le 27/08/2026) | Deux raisons de ne pas « corriger ». D'abord `get_state()` n'existe pas : skore 0.25.0 expose `to_dict()`/`from_dict()`, sa voie documentée de persistance — le plan nommait une API imaginaire. Ensuite, l'artefact de run contredirait la décision d'architecture écrite en tête de `ml_registry.py` : aucun octet ne passe par MLflow, les artefacts vivent une seule fois sur l'`ObjectStore` et le registre pointe des `source` explicites. L'intention — qu'un lecteur du registre retrouve l'évaluation — est tenue par le tag `agentium.skore_report_state` qui porte l'URI absolue de l'état. Preuves : `test_ml_registry.py` (le tag du run égale `store.uri(key)`), `test_ml_training.py` (`EstimatorReport.from_dict` rejoue les métriques publiées à 1e-6 près). |
| Registry adossé au Postgres, base `mlflow`, sqlite en repli, alias `champion` déplaçable depuis la carte | **Tenu** | `ml_registry.py` (`registry_uri`, `set_alias`), route `POST /{model_id}/champion` |
| Page Models + model card présentation-grade | **Tenu** | Bandeau héros, tuiles avec delta, courbes remplies avec diagonale, heatmap CSS grid, importances triées, versions, chips |
| Onglet Comparaison depuis `skore.ComparisonReport` | **Tenu** | `ml_comparison.compare()`, route `GET /{id}/comparison` |
| Atelier du node train : picker → colonnes profilées → spec → **onglet Test** avec check-list puis métriques | **Écart** | Tout le flux existe, y compris les sparklines et la check-list de folds, mais il n'y a **pas d'onglet nommé Test** : le run et la check-list vivent dans le panneau Evidence. |

## Phase 6 — Predict & MLOps

| Exigence | Verdict | Note |
|---|---|---|
| Cache par process de `pyfunc.load_model`, entrées validées contre la signature, skills `ml_predict_v1` et `ml_batch_score_v1` | **Tenu autrement** | Le cache et la validation existent (`_cache`, `load_pipeline`, `coerce_rows`). Il n'y a **pas de tâche Celery predict dédiée** : l'inférence tourne en process, appelée depuis le walker et depuis l'API. Pour une prédiction unitaire c'est le bon choix, mais le plan nommait une tâche worker. |
| `POST /ml-models/{id}/predict`, clés scopées par modèle hachées au repos, header `X-API-Key`, mint/revoke depuis la carte, payload `{"inputs": […]}` | **Tenu** | `MLModelApiKey.key_sha256`, `mint_api_key`, `revoke_api_key`, tests dans `test_ml_predict_api.py` |
| Playground : dropdowns catégoriels **depuis `stats_json` du dataset d'entraînement**, bornes numériques, pré-remplissage depuis `input_example` | **Tenu autrement** | Les choix et les bornes sont calculés **au moment du fit** par `_input_contract` et rangés dans `signature_json`, pas relus dans `stats_json` au moment de servir. Résultat identique et arguablement meilleur — c'est le contrat du modèle qui parle — mais un lecteur du plan chercherait `stats_json`. |
| « Publier comme skill » : `registry_call` → `ml_predict_v1`, `frozen_input {model_id}`, schémas dérivés de la signature et **figés à la publication**, toast avec lien profond, chip de provenance | **Écart** | Le chemin, les schémas, le toast et le chip existent. Deux réserves : une **republication réécrit** les schémas depuis la signature courante, et le chip de provenance suit **l'alias champion** plutôt que la version figée à la publication. |
| Badges canvas depuis les enveloppes, badge « scoré par » sur les colonnes ajoutées, durée par node | **Tenu** | `_node_data_badge`, `scoredColumns`, `data-testid="scored-column"` |

## Phase 7 — Démo Nawa + déploiement VM

| Exigence | Verdict | Note |
|---|---|---|
| Générateur télécom déterministe, ~8k lignes, label bruité, AUC honnête | **Tenu** | `gen_nawa_telecom_data.py` : 8 000 abonnés, 8 412 lignes brutes, AUC mesurées 0.836617 / 0.864133 / 0.853761 |
| Seed : workspace `nawa`, datasets, System « Churn Radar » source → sql → polars → train → score → node LLM → sink, dbt sur les KPI réseau, skill workspace branchée sur un agent | **Écart** | Le graphe, le dbt et le desk agentique existent. La skill publiée s'appelle **« Predict · Churn Radar »** et non « Churn Predict » — cosmétique, mais le plan la nommait. |
| Le seed laisse chaque page pleine : lignages complets, 3 versions à AUC distinctes, historique de runs, clé déjà mintée | **Tenu** | `seed_model_history`, `promote_if_nobody_has`, `publish_and_mint`, et le vérificateur de plan confirme l'état sur la VM |
| **Runbook en 7 temps, qui est aussi le scénario de la vidéo** | **Écart** | Le runbook existe et est riche, mais son ordre diverge matériellement du plan : le temps ① ouvre un dataset existant au lieu d'un upload CSV en direct ; le ③ montre l'inspecteur Polars au lieu d'un run de canvas en direct ; **le temps ⑥ n'a pas l'étape « question posée dans le chat qui appelle le modèle »** ; le cURL du temps ⑦ du plan est dans le temps ⑥ du runbook, dont le ⑦ est Radio Watch / dbt. Le runbook cite encore la révision `4483dd1a34eb`. |
| Déploiement : dump avant `096`, base `mlflow`, routine de dump étendue, canaris carakai, e2e driver API, **vidéo**, journal | **Écart** | Tout est fait et journalisé (`docs/ops/agentium-safe-vm-deployment.md`, `scripts/agentium-data-plane-dump.sh`, `scripts/e2e_data_ml_live.py`) sauf un livrable : **il n'existe aucune vidéo durable**. Ni dans le dépôt, ni dans `/opt/cursor/artifacts/`. Des captures éphémères traînent dans `/tmp` sur la VM et suivent un script dont les temps divergent du plan. |

---

## Les écarts qui restent, par ordre de ce qu'ils coûtent

1. **La vidéo de démo n'existe pas comme artefact durable.** C'est un livrable nommé du plan, et le seul de la phase 7 qui manque entièrement. À refaire contre la révision servie, dans l'ordre des sept temps du plan.
2. **Le runbook ne suit pas les sept temps du plan.** Upload CSV en direct absent, run de canvas en direct absent, question dans le chat absente, et les temps ⑥/⑦ inversés. Deux sorties possibles : refaire le runbook sur l'ordre du plan, ou amender le plan en assumant l'ordre choisi — mais pas laisser les deux se contredire.
3. **Le batch score n'a pas de progression lisible.** Le pari n°3 nommait trois tâches et n'en couvre que deux. C'est le seul pari UI/UX avec un tiers entièrement absent.
4. **L'onglet requirements du node Polars contredit le plan.** Petit, mais c'est une contradiction franche plutôt qu'un manque : à trancher dans un sens ou dans l'autre.
5. **Trois tests backend rouges** sur le dépôt de fichiers immuable (`secure_deposit`) — **fermé le 27/08/2026** : le cache `lru_cache` de `_physical_sha256`, clé sur des horodatages qui se répètent dans le même tick, est retiré ; la lecture est payée à chaque vérification. 33 tests verts, [PR #21](https://bitbucket.org/datategy-root/omnirag/pull-requests/21).
6. **La consultation par abonné sur la page métier** reste parquée avec quatre tests rouges de fixture ([PR #18](https://bitbucket.org/datategy-root/omnirag/pull-requests/18)).
7. **Le correctif d'atteignabilité du panneau de réponse** est écrit et testé mais non déployé ni vérifié dans un navigateur ([PR #20](https://bitbucket.org/datategy-root/omnirag/pull-requests/20)).
8. **Écarts assumés ou en cours de fermeture** (registre tenu depuis le 27/08/2026, hors esprit démo) : l'état skore hors artefact MLflow est **adjugé** — voir la ligne P5, le plan nommait une API inexistante et un stockage que l'architecture rejette. Restent à fermer par le code : le picker de colonnes du train sur la table partagée ; le fil de lignage complet de la model card ; le dbt multi-modèles ; les onglets nommés « Test » ; les schémas de skill figés à la publication et le chip de provenance sur la version figée. Restent assumés : les empty states en icônes.

## Ce qui demande une preuve d'exécution, et laquelle

Ces points sont hors de portée d'une lecture de code et ne sont donc comptés nulle part
ci-dessus comme tenus :

- **Upload CSV de bout en bout** : déposer un CSV, voir la check-list avancer `queued → reading → profiling:N → writing`, le dataset passer `ready`, le toast donner le compte, puis les histogrammes s'ouvrir dans le popover d'en-tête.
- **Badges de canvas sur un run réel** : exécuter Churn Radar et voir `8 412 → 6 903`, l'AUC sur le node d'entraînement et une durée par node.
- **Playground** : changer un catégoriel et un curseur, presser Predict, voir le cadran s'animer et les contributions apparaître — et, sur v3, que la version est bien épinglée.
- **Un agent qui appelle le modèle** : faire tourner le Churn Desk et vérifier que `decide_next_v1` choisit la skill publiée.
- **L'artefact MLmodel** : ouvrir un répertoire de modèle réel et vérifier que `requirements.txt` et `python_env.yaml` portent les épingles déployées.
- **La base `mlflow` sur un vrai Postgres** : `ensure_database()` puis première écriture de registre, les tests tournant sur sqlite.
