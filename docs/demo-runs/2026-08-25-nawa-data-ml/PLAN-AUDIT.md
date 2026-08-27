# Audit de complétion — Data / ML / MLOps

Registre vivant sur `demo/agentic`. Parti de l'audit en lecture seule du
27/08/2026 ([PR #20](https://bitbucket.org/datategy-root/omnirag/pull-requests/20)),
tenu à jour à chaque lot. C'est la source de vérité : le fichier n'existait
pas sur `demo/agentic` avant cette page.

Quatre verdicts :

| Verdict | Sens |
|---|---|
| **Tenu** | La preuve montre le comportement nommé. Daté, avec PR + test. |
| **Tenu autrement** | L'intention est satisfaite par un autre moyen. Ne pas « corriger ». |
| **Écart** | Une partie manque. Ce qui manque est nommé. |
| **Manquant** | Le livrable n'existe pas. |

Un Tenu sur une PR ouverte n'est **pas** un Tenu sur `demo/agentic` tant que
la PR n'est pas fusionnée et déployée. La colonne *arbre* le dit.

Ce que l'audit ne couvre pas : le rendu à l'écran. Les preuves d'exécution
vivantes (CSV, canvas, Playground, agent, MLmodel, Postgres `mlflow`) restent
listées en bas.

Hors esprit démo. Hors périmètre : vidéo, runbook de présentation, consultation
abonné ([PR #18](https://bitbucket.org/datategy-root/omnirag/pull-requests/18)).

---

## Lignes fermées (datées)

| Date | Ligne | Verdict | Arbre | Preuve |
|---|---|---|---|---|
| 27/08/2026 | skore `get_state()` en artefact MLflow | **Tenu autrement** | `demo/agentic` | skore 0.25.0 n'a pas `get_state()`. Tag `agentium.skore_report_state` (URI ObjectStore). `test_ml_registry.py`, `test_ml_training.py`. Adjugé, ne plus rouvrir. |
| 27/08/2026 | Cache SHA `lru_cache` sur `_physical_sha256` | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #21](https://bitbucket.org/datategy-root/omnirag/pull-requests/21) empilé sur [PR #30](https://bitbucket.org/datategy-root/omnirag/pull-requests/30). Lecture à chaque vérification. |
| 27/08/2026 | Panneau predict atteignable + progression batch-score + ce registre | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #20](https://bitbucket.org/datategy-root/omnirag/pull-requests/20) empilé sur #30. |
| 27/08/2026 | Contrat publié = version qui sert (name / description / schémas) | **Tenu** | PR #30, non fusionné dans `demo/agentic` | `cursor/skill-publish-frozen-34ca` @ `7741a60a`. Le slug nomme la lignée ; promouvoir change la réponse sans republier. Ne pas figer la version dans `frozen_input`. |
| 27/08/2026 | dbt : un dataset par modèle sélectionné | **Tenu** | PR #30, non fusionné dans `demo/agentic` | `cursor/dbt-multi-models-34ca` @ `7941c1bf` (`output_models`). |
| 27/08/2026 | Polars : environnement imposé, extras ignorés | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #24](https://bitbucket.org/datategy-root/omnirag/pull-requests/24) @ `837a4221`. `effective_requirements` = pin seul. |
| 27/08/2026 | Picker train sur `DataTableComponent` | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #25](https://bitbucket.org/datategy-root/omnirag/pull-requests/25) @ `b33de3b1`. |
| 27/08/2026 | Badge SQL réunifié + onglet Test du train | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #26](https://bitbucket.org/datategy-root/omnirag/pull-requests/26) @ `16ffda5c`. |
| 27/08/2026 | Lignage carte : dataset → transform → modèle → scorés | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #27](https://bitbucket.org/datategy-root/omnirag/pull-requests/27) @ `c8273ff0`. |
| 27/08/2026 | Journal de prédictions + `prediction_id` | **Tenu** | PR #30, non fusionné dans `demo/agentic` | [PR #28](https://bitbucket.org/datategy-root/omnirag/pull-requests/28). Migration `098`. |
| 27/08/2026 | `POST /ml-models/{id}/feedback` | **Tenu** | PR #30, non fusionné dans `demo/agentic` | Même lot. Rattache la vérité terrain au `prediction_id`. |
| 27/08/2026 | `tabular_monitoring` — PSI, dérive des scores, AUC glissante | **Tenu** | PR #30, non fusionné dans `demo/agentic` | `test_tabular_monitoring.py`. Seuils ok / watch / alert. |
| 27/08/2026 | Onglet Monitoring + badge liste + boucle dataset → retrain | **Tenu** | PR #30, non fusionné dans `demo/agentic` | `data-testid="monitor-panel"`, `monitor-badge`. |
| 27/08/2026 | QA : badge liste = pire des trois signaux | **Tenu** | PR #30 | `badges_for` inclut le PSI features. `test_the_list_badge_agrees_with_the_tab_when_features_drift`. |
| 27/08/2026 | QA : score batch journalise un échantillon | **Tenu** | PR #30 | `score_dataset` écrit `frame.select(wanted).head(_JOURNAL_ROW_CAP)`. |
| 27/08/2026 | QA : provenance suit `parent_ids` | **Tenu** | PR #30 | `test_the_dataset_chip_follows_parent_ids_not_sql_in_order`. |

## Assumé, ne plus rouvrir

| Ligne | Pourquoi |
|---|---|
| Figer la version dans `frozen_input` à la publication | Le slug nomme la lignée. Promouvoir change la réponse. Ce qu'il fallait : name / description / schémas suivent le champion. |
| Tâche Celery predict dédiée | Inférence in-process assumée. |
| Garde SQL élargie au-delà de WITH/SELECT | `validate_sql` est déjà plus stricte sur les effets de bord. |
| Empty states illustrés | Toujours en dernier, seulement si le reste est vert. Pas encore. |

## Encore ouvert

| Ligne | État | Note |
|---|---|---|
| Fusion des PRs dans `demo/agentic` | **Écart** | Empilées sur `cursor/mlops-coverage-34ca` / [PR #30](https://bitbucket.org/datategy-root/omnirag/pull-requests/30). `demo/agentic` reste à `dc896dad`. |
| Déploiement sur la VM | **Écart** | GO opérateur reçu pour cette passe (« puis on deploie »). Recette du 27/08 : dump → migrate `098` → up. |
| Témoin télécom vivant | **Écart** | La VM sert encore `29aa898159b5`. Pas de `e2e_data_ml_live.py` : pas de secret, et le driver mute `nawa`. |
| Consultation abonné | **Écart** | PR #18, hors périmètre de ce lot. |
| Vidéo + runbook 7 temps | **Écart** | Hors périmètre. |

---

## Témoin live (27/08/2026, avant cette passe)

```
GET https://agentium.papai.ai/api/v1/build-info
{"service":"backend","revision":"29aa898159b563ab90185b75e2444bdbeb5c924a","revision_verified":true,"version":"1.0.0-demo"}
```

nginx 1.24, `Last-Modified: Thu, 27 Aug 2026 04:07:55 GMT`. Health `healthy`.

---

## Audit historique (PR #20, 27/08/2026, lecture seule)

Les tableaux ci-dessous sont l'état *sur `demo/agentic`*, pas sur les
branches. Les lignes depuis fermées ci-dessus restent **Écart / Manquant**
ici tant qu'elles ne sont pas fusionnées.

### Phase 1 — Socle datasets

Neuf exigences, neuf **tenues**. Preuves : `tabular.py`, `tabular_datasets.py`,
migration `096`, `datasets.py`, `dataset_ingest`, `frontend-ng/src/app/features/data/`.

### Les six paris UI/UX

| Pari | Verdict sur `demo/agentic` | Branche qui ferme |
|---|---|---|
| 1 — un seul composant table | **Écart** (picker train encore en `ck-column-spark`) | PR #25 |
| 2 — colonnes profilées à l'ingest | **Tenu** | — |
| 3 — zéro spinner muet | **Écart** (batch score sans progression) | PR #20 |
| 4 — canvas, la donnée qui coule | **Tenu** (rendu à confirmer sur un run réel) | — |
| 5 — Playground | **Tenu** | — |
| 6 — provenance comme fil rouge | **Écart** (v1→v2 seulement) | PR #27 |

Empty states illustrés : **écart mineur**, assumé.

### Phase 2 — Node SQL

Garde SQL **Tenu autrement**. Badge « 142 ms · 6 903 lignes » **Écart** sur
`demo/agentic`, **Tenu** sur PR #26. Pas d'onglet Test SQL : assumé — enfouir
Run serait une régression.

### Phase 3 — Node Polars

Environnement imposé **Manquant** sur `demo/agentic`, **Tenu** sur PR #24.

### Phase 4 — Node dbt

Un dataset par modèle sélectionné **Écart** sur `demo/agentic`, **Tenu** sur
`cursor/dbt-multi-models-34ca`.

### Phase 5 — Entraînement

skore `get_state()` **Tenu autrement, assumé**. Onglet Test du train **Écart**
sur `demo/agentic`, **Tenu** sur PR #26.

### Phase 6 — Predict

Celery predict **Tenu autrement** (in-process). Publier comme skill : schémas
de la carte ouverte **Écart** sur `demo/agentic`, **Tenu** sur
`cursor/skill-publish-frozen-34ca` (suivre le champion, pas figer la version).
Journal / feedback / drift **Manquant** sur `demo/agentic`, **Tenu** sur PR #28.

### Phase 7 — Témoin + déploiement

Générateur et seed **Tenu** (nom de skill cosmétique). Runbook / vidéo **Écart**,
hors périmètre. Déploiement **Écart** : voir le témoin live ci-dessus.

---

## Preuves d'exécution encore dues

Hors lecture de code, donc jamais comptées Tenu ici :

- Upload CSV de bout en bout (check-list `queued → reading → profiling → writing`)
- Badges de canvas sur un run Churn Radar réel
- Playground : cadran, contributions, pin v3
- Un agent qui appelle la skill publiée
- Artefact MLmodel aux pins déployées
- Base `mlflow` sur un vrai Postgres
- Une fois D déployé : predict → feedback → dérive → retrain
