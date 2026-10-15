# Plan MLOps d'Agentium : cartographie de la reprise de papAI et besoins de développement

> **Date** : 2026-10-15.
> **Base** : `demo/agentic` (origin = 4a404d61).
>
> **Sources**
> - Inventaire fonctionnel du MLOps de papAI (`~/Developer/DATATEGY/papai-latest` : builder-service, model-interface, model-interface-service, model-analyser, scheduler-service, datategy-model-artefacts, datategy-mlflow-model-signature, core, frontend, ansible).
> - Inventaire du MLOps d'Agentium, au code (`backend/app`, `frontend-ng`, `docs`).
>
> Les deux inventaires ont été faits en lecture seule le 2026-10-15. Les numéros de ligne cités datent de ce jour : **revérifiez-les avant d'éditer**.
>
> **Règles de travail** : identiques à l'annexe D de `docs/agentium-dataops-plan.md`. En particulier, toute fusion dans `demo/agentic` se fait sur accord explicite de l'utilisateur, chaque lot est une PR autonome, et on lance `build:prod` une fois par lot.

---

## 0. Lecture rapide

**Verdict.**
- Agentium a **repris, et nettement dépassé**, ce que papAI faisait *réellement* en MLOps : registre, format d'artefact, contrat d'entrée, clés API, surveillance, shadow, réentraînement avec approbation, explicabilité, fiche modèle.
- La seule brique **non reprise** est la **« model instance »** : un modèle déployé comme service dédié, avec un builder, une passerelle et un pod par modèle. Chez papAI elle était elle-même immature (§1.2), et son absence est un **choix d'architecture** d'Agentium : service partagé et frugal.
- Les vrais besoins de développement sont ailleurs, sur trois fronts :
  - la **gouvernance** (droits, audit, limites de débit) ;
  - la **justesse** du réentraînement et de la dérive de concept ;
  - l'**exploitation** (alertes, vue transverse des endpoints, export).

| Lot | Objectif | Priorité | Taille | Dépend de |
|---|---|---|---|---|
| **M0** | Sécurité **côté papAI** (environnements encore actifs) : routes d'administration ouvertes, jetons en clair | **Urgent**, hors Agentium | S | — |
| **M1** | Gouvernance des modèles : droits par rôle, journal d'audit, clés (expiration, portée), limites de débit et quotas, consentement de stockage et rétention du journal | **P1** | M | — |
| **M2** | Justesse MLOps : données du réentraînement, dérive de concept en régression et multiclasse, historique de surveillance | **P1** | M | — |
| **M3** | Exploitation : alertes (e-mail, webhook, Hypervisor), page transverse « Endpoints », métriques agrégées (trafic, latence p50/p95, erreurs), coût d'inférence | P2 | M | M1 (audit, quotas) |
| **M4** | Portabilité : export du modèle (bundle MLflow), import de modèles externes (BYOM) en environnement isolé, montée de version de l'environnement d'exécution | P2 | M | M1 |
| **M5** | Explicabilité et débogage **en production** : SHAP par prédiction (arbres), arbre d'erreur et fairness sur les données de production étiquetées | P3 | M | M2 |
| **M6** | « Model instance » optionnelle : déploiement dédié par modèle (isolation, ressources, autoscaling, arrêt et démarrage, canary pondéré) | **Sur besoin client** | L | D4 du plan DataOps, M1, M3 |

**Ordre recommandé** : M0 (immédiat, côté papAI), puis M1 et M2 en parallèle, puis M3, puis M4. M5 et M6 attendent un besoin exprimé.

---

## 1. Cartographie de papAI

### 1.1 Deux piles MLOps

| Pile | Composants | État |
|---|---|---|
| **Nouvelle** (active) | `builder-service`, `model-interface` (publié sous deux remotes : `model-interface` et `model-interface-service`, **même code**), `scheduler-service`, `model-analyser`, pipeline GitLab « model-deployment », front `packages/ml-ops` | Jeune : un seul modèle sklearn tabulaire par déploiement |
| **Ancienne** | Routes core `/api/v1/ml-ops` : seuils de dérive, surveillance planifiée, par lot ou manuelle, e-mails, clés | **Morte** : les endpoints Python appelés ont été supprimés de papai-ml le 2025-08-13 (commit `51c11e67`) |

### 1.2 Ce que chaque composant faisait

**builder-service** (`builder-service/src/api/routes/deployment.py`)
- `POST /model-deployment` :
  - contrôle de quota (`plan.maxDeployedModel`) via core ;
  - lecture de `MLmodel.yaml` ;
  - modèle de code d'inférence, **régression et classification seulement** ;
  - génération de jetons `papai-…` (365 jours) ;
  - déclenchement d'un pipeline GitLab.
- États du cycle de vie détaillés (`life_status_enum.py`).
- **Aucune image par modèle** : le pod part de `python:x.y`, télécharge l'artefact depuis MinIO, puis lance `pip install` au démarrage.
- **Aucune API** d'arrêt, de démarrage, de mise à jour, de retour arrière ni de poids canary.

**model-interface** (`src/services/listener/api/routes.py`)
- Passerelle par déploiement : `POST /inference?allow_data_storage=`, `POST /feedback`, `GET /status`, `POST /example-inference`.
- Clés statiques dans la configuration (expiration, sans révocation dynamique).
- Validation **par noms de colonnes seulement** : la signature MLflow n'est jamais appliquée.
- Fan-out vers N modèles, avec agrégation par moyenne ou vote **pondérés**.
- Journal des prédictions et du feedback en Postgres, avec un **consentement de stockage par requête**.
- Métriques trafic, latence et erreurs en SQL, sans tableau de bord.
- Pas de limite de débit. Les traces d'erreur sont renvoyées au client.

**model-analyser** (`src/api/routes/data_drift.py`)
- Dérive par Frouros (KS et χ² par défaut ; tout détecteur par lot, MMD compris), en mode *fit* puis *compare*.
- **Appelé par rien.** Ni seuil, ni alerte, ni interface.

**scheduler-service** : ne fait que vérifier toutes les 30 s que les déploiements répondent. La vraie planification est dans core : *cron* de Flows (`ProjectCronJob`).

**Artefacts** (`datategy-model-artefacts`, `datategy-mlflow-model-signature`)
- `MLmodel.yaml` maison : signature, flavour sklearn, pytorch ou darts, environnement Python.
- Le code de signature est une copie de celui de MLflow. Sa fonction de contrôle existe mais n'est jamais appelée.

**core**
- Registre (`RegistryRun`) avec promotion par « activate run ».
- Recettes de prédiction et d'évaluation par lot. La dérive KS avec correction de Bonferroni est calculée seulement à l'évaluation.
- Les drapeaux `retrainBeforePrediction` et `retrainBeforeEvaluation` ne sont **jamais lus**.
- Pas d'environnements staging ou prod, pas d'approbation, pas d'audit.

**Front** (`frontend/packages/ml-ops`)
- Liste, création en 3 étapes, progression, détail (aperçu, endpoints, secrets).
- **Pas de playground.** Le cURL copié est faux (`/predict` au lieu de `/inference`, sans `allow_data_storage`).
- Pas de suivi de surveillance.
- L'onglet *Debug* (arbre d'analyse d'erreur) est dans la page de run d'entraînement.

**Ailleurs dans papai-ml**
- SHAP, DiCE et interprétation d'une prédiction, hors ligne.
- Fairness à l'entraînement.
- **Import de modèles externes** (`/external_experiment`).
- **Environnements Celery sur mesure** : une image Kaniko par environnement, la seule construction d'image par artefact de papAI.

### 1.3 À retenir de papAI, et à ne pas reproduire

**À retenir**
- Le **consentement de stockage par requête**.
- L'objet **déploiement**, avec ses états de vie.
- Les **poids** de routage (canary et ensembles).
- L'**import de modèles externes**.
- La **dérive multivariée** (Frouros).
- Le **quota de modèles déployés** par abonnement.

**À ne pas reproduire**
- Jetons API en clair jusque dans des ConfigMaps.
- Routes d'administration sans authentification (`/env`, `/reset-db`, `/internal/*`).
- Traces d'erreur renvoyées aux clients.
- `pip install` au démarrage du pod.
- Pipeline GitLab utilisé comme agent de déploiement.
- Un Postgres par workspace.
- RBAC du runner à l'échelle du cluster.
- Images en `latest`.

---

## 2. Cartographie d'Agentium (état au 2026-10-15)

| Domaine | Ce qui existe | Ancrages |
|---|---|---|
| Registre | `MLModel` (slug, version, famille, statut, `is_champion`, spec, runtime, metrics, signature, artefact, usage, lignage). Registre MLflow réel en base SQL (sans serveur), alias `champion` / `challenger` | `models/tabular.py` l.132-257 ; `services/ml_registry.py` l.191-345 |
| Cycle de vie | Promotion manuelle (`set_champion`) ; challenger = meilleur non servi selon la métrique ; suppression avec nettoyage complet ; comparaison skore sur les mêmes lignes de test ; lignage dataset → modèle → scores | `services/tabular_ml.py` l.1431-1651, 1722-1810 ; `services/ml_comparison.py` |
| Artefacts | MLflow sklearn + skops, signature, exemple, dépendances épinglées. **Contrat d'artefact** (empreintes sha256, profils de confiance) et **égalité stricte de l'environnement d'exécution** (sinon `ML_ARTIFACT_RUNTIME_MISMATCH`) | `resources/ml_train_harness.py` l.1247-1310 ; `services/ml/artifacts.py` ; `resources/ml_artifact_contract.py` ; `services/ml/runtime.py` l.52-77 |
| Service en ligne | `POST /ml-models/{id}/predict` en session ou par clé : contrat d'entrée strict, au plus 100 lignes, épinglage de version, intervalles conformes, explication par contrefactuel. Cache LRU de 4 modèles par processus | `services/tabular_predict.py` l.173-355, 417-586, 902-960 ; `api/v1/endpoints/ml_models.py` l.594-654 |
| Service distant | Prévision (`ml_ts_rpc`) et modèles deep / TabICL (`ml_deep_rpc`) par RPC Celery, disponibilité par heartbeat | `services/ml/forecast_serving.py` l.499-612 ; `services/ml/deep_serving.py` |
| Score par lot | Nœud Flow en process, jusqu'à 1 M lignes ; version en flux, jusqu'à 3 M lignes, derrière un drapeau | `services/tabular_predict.py` l.1072-1305 ; `services/dataops/scoring.py` |
| Clés API | Par lignée, préfixe `agpk_`, empreinte sha256, affichée une fois, 8 au plus, comparaison à temps constant, compteur d'usage. **Sans expiration ni quota** | `models/tabular.py` l.282-312 ; `services/tabular_predict.py` l.1312-1456 |
| Publication | Skill `registry_call` vers `ml_predict_v1`, qui suit le champion. Nœuds Flow train, predict, score, forecast, monitor, retrain | `services/tabular_predict.py` l.1561-1780 ; `skills_registry/wrappers/skills.py` l.2779-3160 |
| Journal | `MLPrediction` : appelant, version demandée et servie, charge utile (64 lignes au plus), sortie, durée, label | `models/tabular.py` l.315-363 ; `services/tabular_predict.py` l.996-1045 |
| Surveillance | PSI des entrées, KS / χ² avec correction de Holm (lot 5a), dérive des scores (intra-fenêtre), AUC glissante (binaire), feedback, réels de prévision, badges. **Calculée à la lecture** sur les 400 derniers appels | `services/tabular_monitoring.py` ; `resources/ml_drift.py` ; `services/ml/forecast_monitoring.py` |
| Automatisation | Shadow scoring isolé et échantillonné (lot 5b) ; surveillance planifiée et propositions de réentraînement avec approbation HITL (lot 5c) ; le résultat reste toujours challenger | `services/ml_shadow.py` ; `services/ml_retraining.py` ; `run_engine/dag.py` l.3885-3911 |
| Explicabilité | Rapports skore, importances, arbre d'erreur et surrogate **dessinés en arbres** (59b4f0ec), PDP / ICE, fairness (3 colonnes au plus), sur le jeu de test | `resources/ml_explanation_extensions.py` ; `features/models/explanation-evidence.component.ts` |
| Déploiement | **Pas d'unité de déploiement.** Tabulaire servi dans l'API et les workers ; workers ML partagés, 1 réplica (Helm `ml-workers.yaml`) | `docker/compose.agentium.yml` l.289-387 ; `ops/helm/agentium/templates/ml-workers.yaml` |
| Droits | **Appartenance au workspace seulement** pour entraîner, promouvoir, supprimer, créer des clés et publier. Contributeur exigé pour le shadow, administrateur pour la planification | `core/auth.py` l.229-275 ; `services/mlops_jobs.py` l.18-36 |
| Audit | **Aucune écriture** dans `audit_logs` (`services/audit_logger.py`, `emit_audit_event`) depuis les services ML | — |
| Alertes | Signal Hypervisor via les points de contrôle de la surveillance planifiée. **Ni e-mail ni webhook** (`services/email.py` existe) | `api/v1/endpoints/hypervisor.py` l.1085-1186 |
| Interface | Liste et studio d'entraînement ; fiche modèle avec les onglets Evidence, Play (cURL, clés, publication), Compare, Monitor, Contract, Versions, Setup ; approbation du réentraînement dans la vue du Run | `features/models/*` ; `features/runs/run-view.component.ts` l.80 |
| Export | **Aucun.** La portabilité est seulement théorique : un client MLflow branché sur la base `mlflow` et MinIO | `services/ml_registry.py` l.370 |

---

## 3. Matrice de couverture papAI → Agentium

| Capacité papAI | Où dans papAI | Agentium | Verdict | Lot |
|---|---|---|---|---|
| Registre et versions | core `RegistryRun.scala` | `ml_models` + registre MLflow | **Mieux** | — |
| Promotion | core « activate run » | `set_champion` + alias | **Mieux** (sans approbation) | M1 (approbation optionnelle) |
| Staging / prod | — | — | Absent des deux | M6 (environnement de déploiement) |
| Format d'artefact | `MLmodel.yaml` maison | MLflow natif + contrat + empreinte d'exécution | **Mieux** | — |
| Contrôle de la signature au service | Absent | Contrat d'entrée strict | **Mieux** | — |
| Montée de version de l'environnement d'exécution | Journalise les écarts de version | Refus strict | Plus sûr, mais rigide | M4 (requalification) |
| Déployer un modèle (builder) | `POST /model-deployment` | Implicite : le modèle prêt est servi | Non repris, choix d'architecture | M6 si besoin |
| Pod par modèle, ressources, états | Pipeline GitLab, manifestes | — | Non repris | M6 |
| Arrêt, démarrage, retour arrière | États sans API | Promotion d'une ancienne version | **Mieux** pour le retour arrière | M6 (arrêt / démarrage) |
| Passerelle en ligne | `POST /inference` | `POST /predict` | **Équivalent+** | — |
| Clés API | Statiques, en clair | Empreinte, révocables, compteur d'usage | **Mieux** ; pas d'expiration | M1 |
| Limites de débit et quotas | Quota de modèles déployés seulement | Aucun (`core/rate_limiter.py` inutilisé) | **Manquant** | M1 |
| Consentement de stockage par requête | `allow_data_storage` | Journal toujours actif | **Manquant** | M1 |
| Rétention du journal | — | Pas de purge | Manquant | M1 |
| Agrégation multi-modèles | Moyenne / vote pondérés | — | Manquant (faible valeur) | M6 |
| Canary, A/B | Docstring seulement | Shadow seulement | Shadow **mieux** ; pas de répartition du trafic | M6 |
| Feedback | `POST /feedback`, non exploité | Feedback exploité (surveillance, réentraînement) | **Mieux** | — |
| Métriques trafic, latence, erreurs | SQL, sans tableau de bord | Durée par appel seulement | **Partiel** | M3 |
| Santé, joignabilité | Ping toutes les 30 s | Heartbeats des workers distants | Équivalent pour le modèle d'Agentium | M6 si déploiement dédié |
| Dérive des entrées | Frouros KS / χ² (non branché) ; KS + Bonferroni à l'évaluation | PSI + KS / χ² avec Holm + badges + surveillance planifiée | **Mieux** | M2 (multivarié, optionnel) |
| Dérive de concept | Absent | AUC glissante (binaire seulement) | **Partiel** | M2 |
| Historique de surveillance | Ancienne pile, morte | 100 instantanés planifiés | **Partiel** (pas de courbes) | M2 / M3 |
| Alertes | E-mails (ancienne pile, morte) | Signal Hypervisor seulement | **Manquant** | M3 |
| Réentraînement | *Cron* de Flows ; `retrainBefore*` ignorés | Propositions avec approbation et preuves figées | **Mieux** ; **données de réentraînement discutables** | M2 |
| Score par lot | Recette de prédiction | Nœud score, en flux jusqu'à 3 M lignes | **Équivalent+** | — |
| Débogage du modèle (arbre d'erreur) | Onglet Debug (entraînement) | Arbres dessinés (test) | **Équivalent+** ; pas en production | M5 |
| SHAP, DiCE, interprétation | papai-ml hors ligne | Contrefactuel simple (top 6) | **Partiel** | M5 |
| Fairness | Entraînement | Entraînement (3 colonnes au plus) | Équivalent ; non surveillée | M5 |
| Import de modèles externes | `/external_experiment` | Poids de fondation Hugging Face seulement | **Manquant** | M4 |
| Environnements sur mesure | Image Kaniko par environnement | Familles fixes (images ml-ts, ml-deep) | Manquant (choix) | M4 / M6 |
| Quota de modèles déployés | `plan.maxDeployedModel` | — | Manquant | M1 |
| Coût d'inférence | — | Tarif 0 sur la Skill publiée | Absent des deux | M3 |
| Droits | core : EditProject, siège, abonnement | Appartenance seulement | **Régression** | M1 |
| Audit | — | — | Absent des deux | M1 |
| Export du modèle | Export de projet | — | **Manquant** | M4 |
| Interface : déploiements | Liste, progression, détail | Fiche modèle riche ; pas de vue transverse | **Mieux** localement ; vue transverse **manquante** | M3 |
| Playground | — (cURL faux) | Play + cURL + clés | **Mieux** | — |

---

## 4. Décisions

| # | Décision | Raison |
|---|---|---|
| DM-1 | **Pas d'unité de déploiement par défaut.** Le modèle prêt et champion est servi par le plan partagé (API, workers, RPC). La « model instance » devient le lot optionnel M6 | Frugalité et simplicité. La version de papAI était immature et coûteuse (un pod et un Postgres par workspace) |
| DM-2 | **Gouvernance d'abord** (M1) : droits par rôle, audit et limites avant toute exposition supplémentaire | C'est la seule régression par rapport à papAI, et un prérequis à M3, M4 et M6 |
| DM-3 | **Réentraînement sur données d'origine + données de production étiquetées**, pas sur le seul feedback | Un modèle réentraîné sur la première ligne de chaque appel étiqueté peut être nettement plus faible que celui qu'il remplace |
| DM-4 | **Alertes par canaux de notification** (e-mail via `services/email.py`, webhook signé, boîte Hypervisor), déclenchées sur **changement d'état** et avec limitation de fréquence | Le signal Hypervisor seul ne prévient personne |
| DM-5 | **Export MLflow standard** plutôt qu'un format maison | Portabilité réelle (`mlflow models serve`), sans dépendance à notre base |
| DM-6 | **Import de modèles externes uniquement en environnement isolé**, avec contrat d'artefact, validation par prédictions de référence et famille `external` | Le contrôle strict de l'environnement d'exécution ne doit pas être contourné |
| DM-7 | Aucun des pièges de papAI (§1.3) | — |

---

## 5. Lots détaillés

### M0 — Sécurité côté papAI (urgent, hors Agentium)

À vérifier **sur les environnements papAI encore actifs**. Les constats viennent de la lecture du code, pas d'un test sur un environnement réel.

1. **Routes d'administration de `builder-service` sans authentification**, joignables par l'ingress selon `ansible/.../core-virtualservice.yaml` et le VirtualService du builder :
   - `/env` renvoie toutes les variables d'environnement, donc des secrets ;
   - `/reset-db` supprime toutes les tables ;
   - `/config`, `/request-core*` et `/internal/*` sont ouvertes.

   **Action** : bloquer ces chemins à l'ingress, puis les retirer ou les authentifier.
2. **Jetons API en clair** (`hash_secret` renvoie le texte) dans les entrées du pipeline GitLab et dans les ConfigMaps. **Action** : rotation des jetons, puis stockage en Secret Kubernetes.
3. **La passerelle renvoie les traces d'erreur** aux clients (`model-interface/src/services/listener/api/app.py`). **Action** : réponse 500 générique.
4. **`model-analyser` sans authentification**, exposé via `/api/v1/mlops-analyser/`. **Action** : bloquer à l'ingress, puisque le service n'est utilisé par personne.
5. **Token Docker Hub** en clair dans `spark-service/docs/README_prerelease.md` : déjà signalé, à révoquer.

**Critère** : chaque point est vérifié sur chaque environnement actif, puis corrigé ou neutralisé à l'ingress.

### M1 — Gouvernance des modèles (P1)

**1. Droits par rôle sur les actions ML.** Contrôle centralisé `ml_permissions.require(action, workspace, user)`, branché sur les rôles canoniques (`core/iam/roles.py`).

| Action | Lecteur | Contributeur | Relecteur | Admin / Owner |
|---|---|---|---|---|
| Lire la fiche, comparer, Play en session | ✓ | ✓ | ✓ | ✓ |
| Entraîner, envoyer du feedback | — | ✓ | ✓ | ✓ |
| Configurer le shadow | — | ✓ | ✓ | ✓ |
| **Promouvoir un champion** | — | — | ✓ (ou avec approbation, ci-dessous) | ✓ |
| Supprimer une version | — | — | — | ✓ |
| Créer ou révoquer des clés, publier ou retirer une Skill | — | — | — | ✓ |
| Planification et politique de réentraînement | — | — | — | ✓ (inchangé) |

**Approbation de promotion, optionnelle**, par une politique de workspace `settings.ml.promotion_requires_approval`. La promotion devient alors une demande HITL qui réutilise `hitl.can_decide`.

**2. Journal d'audit.** `emit_audit_event` (`services/audit_logger.py`) sur chaque action sensible :
- entraînement demandé ;
- promotion ;
- suppression ;
- création et révocation de clé ;
- publication et retrait ;
- changement de politique de surveillance ;
- approbation ou rejet de réentraînement ;
- export et import (M4).

Champs : acteur, workspace, modèle, version, avant / après, et adresse IP pour les clés.

**3. Clés API**
- Expiration (`expires_at`, défaut 365 jours, réglable).
- Portée : prédiction seulement, éventuellement épinglée à une version.
- Rotation assistée : nouvelle clé, période de recouvrement, puis révocation.
- Liste blanche d'IP, optionnelle.

**4. Limites de débit et quotas**
- Brancher `core/rate_limiter.py` (aujourd'hui inutilisé) sur `/predict` et `/forecast` : par clé et par modèle, en requêtes par minute et lignes par minute. Refus en 429 avec `Retry-After`.
- Quota de **modèles exposés** (clés actives ou Skill publiée) par workspace, sur le modèle de `plan.maxDeployedModel` de papAI.

**5. Données des appelants**
- Paramètre `store=false` sur `/predict`, l'équivalent de `allow_data_storage` de papAI. Avec `store=false`, le journal ne garde que la sortie et les métriques, sans la charge utile. Le feedback est alors impossible pour cet appel, et c'est documenté.
- Politique de rétention `settings.ml.prediction_retention_days`, avec purge par tâche beat.

**Tests**
- Matrice des droits : un test par action et par rôle.
- Événements d'audit écrits.
- Clé expirée refusée.
- 429 au-delà de la limite.
- `store=false` sans charge utile en base.
- Purge de rétention.

**Critère** : un contributeur ne peut ni promouvoir, ni supprimer, ni créer une clé ; chaque action sensible laisse un événement d'audit.

### M2 — Justesse MLOps (P1)

**1. Données de réentraînement** (`services/ml_retraining.py`, `_feedback_dataset` l.374-413). Aujourd'hui, seule la première ligne de chaque appel étiqueté est utilisée. Nouvelle politique `retraining.data` :

| Mode | Données |
|---|---|
| `original_plus_feedback` (défaut) | Dataset d'entraînement d'origine + lignes de production étiquetées, avec dédoublonnage par empreinte et fenêtre temporelle optionnelle |
| `feedback_only` | Le comportement actuel, gardé en option explicite |
| `latest_dataset_version` | La dernière version du dataset de la lignée, si elle a été rafraîchie |

**Contrôles**
- Schéma compatible avec le contrat.
- Équilibre des classes et effectif minimal.
- Proportion de lignes de production plafonnée, ou pondérée.
- Le dataset combiné est **figé** (sha256) dans les preuves de la proposition.
- **Toutes les lignes** d'un appel étiqueté sont journalisées (et pas seulement la première) quand le label s'applique à l'appel entier. Sinon, le feedback se fait par ligne (`sample_id` par ligne, comme papAI).

**2. Dérive de concept pour tous les types de tâche** (`tabular_monitoring.concept_drift`) :

| Tâche | Mesure glissante, sur les lignes étiquetées | Seuils |
|---|---|---|
| Régression | MAE et RMSE, comparées au test d'entraînement | Écart relatif ≥ 10 % : surveillance ; ≥ 25 % : alerte (réglables) |
| Multiclasse | accuracy et F1 macro | Δ 0,02 / 0,05 |
| Binaire | AUC (existant) | Inchangés |

**3. Badge de surveillance pour les prévisions** dans la liste, à partir des réels.

**4. Historique**
- Instantanés de surveillance **persistés à chaque calcul planifié**, ce qui existe déjà avec 100 instantanés.
- Courbes dans l'onglet Monitor (PSI, p-valeurs, mesure de concept).
- Score de référence enregistré à l'entraînement (histogramme des scores du test), pour une **dérive des scores contre l'entraînement** et non plus seulement à l'intérieur de la fenêtre.

**5. Option : dérive multivariée** par un classifieur qui sépare entraînement et production (AUC du discriminateur), la référence papAI étant MMD via Frouros. Hors image API : calculée par le worker.

**Tests**
- Réentraînement sur `original_plus_feedback` meilleur ou égal à `feedback_only` sur un jeu synthétique avec dérive.
- Dérive de concept détectée en régression et en multiclasse sur un décalage planté.
- Historique tracé.

**Critère** : une proposition de réentraînement n'est jamais entraînée sur le seul feedback sans le dire explicitement.

### M3 — Exploitation (P2)

**1. Alertes**
- Canaux par workspace : e-mail (`services/email.py`), webhook signé HMAC, boîte Hypervisor.
- Déclenchées sur **changement d'état** du badge (ok → surveillance → alerte, et retour), sur l'échec d'une surveillance planifiée, sur l'expiration prochaine d'une clé (M1) et sur un quota atteint.
- Limitation de fréquence : un message par modèle et par état et par fenêtre.
- Journalisées dans l'audit.

**2. Page transverse « Endpoints »** (`features/models/endpoints-*`), pour chaque modèle exposé (clés actives ou Skill publiée) :
- version servie ;
- clés (création, dernier usage, expiration) ;
- trafic et lignes sur 24 h et 7 jours, latence p50 / p95, taux d'erreur ;
- badge de surveillance et dernier événement d'audit.

**3. Métriques agrégées**
- Table `ml_usage_rollups` (modèle, version, appelant, intervalle de 5 minutes : requêtes, lignes, erreurs, p50, p95), alimentée par une tâche beat depuis le journal.
- Les erreurs sont aussi journalisées avec leur code : aujourd'hui, seuls les succès sont journalisés.

**4. Coût d'inférence**
- Coût par 1 000 prédictions, issu du tarif de la Skill ou d'un modèle de coût (temps CPU mesuré × prix du lot D4 du plan DataOps).
- Affiché sur la fiche et dans la page Endpoints. Remonté dans `SkillInvocation.cost` via le canal de coût mesuré (D4 DataOps).

**Critère** : un changement d'état de surveillance produit une alerte vérifiable (e-mail de test, webhook reçu) ; la page Endpoints affiche p50 / p95 et le taux d'erreur sur des données réelles.

### M4 — Portabilité (P2)

**1. Export**
- `GET /ml-models/{id}/export` renvoie une archive : le dossier MLflow (`MLmodel`, artefact skops, `requirements.txt`), le contrat d'artefact, l'exemple d'entrée et un `README` (`mlflow models serve -m . --env-manager local`, et image Docker optionnelle via `mlflow models build-docker`).
- Réservé aux administrateurs (M1) et audité.

**2. Import de modèles externes (BYOM)**
- Envoi d'un modèle MLflow (sklearn ou pyfunc) dans une famille `external`.
- Validation dans un **worker isolé** :
  - environnement déclaré, comparé aux images disponibles ;
  - profil de confiance skops, ou pyfunc en sous-processus restreint ;
  - prédictions de référence sur l'exemple fourni ;
  - contrat d'entrée dérivé de la signature.
- Le modèle importé est servi par RPC sur un pool isolé, jamais dans l'API.
- Équivalent sûr de `/external_experiment` et des environnements sur mesure de papAI.

**3. Montée de version de l'environnement d'exécution**
- Tâche de **requalification** : recharger l'artefact sous le nouvel environnement, rejouer les prédictions de référence (test enregistré), comparer à tolérance.
- Si c'est conforme, un attestat permet le chargement inter-versions **pour ce modèle**. Sinon, un réentraînement est proposé.
- Cela remplace le refus strict sans affaiblir la sécurité.

**Critère** :
- un modèle exporté se sert avec `mlflow models serve` et rend les mêmes prédictions ;
- un modèle importé passe la validation ou est refusé avec un code ;
- une montée de version de scikit-learn ne bloque plus les modèles requalifiés.

### M5 — Explicabilité et débogage en production (P3)

- **SHAP par prédiction**, pour les modèles à arbres (`TreeExplainer`, exact et rapide), calculé côté worker (`shap` n'est pas dans l'image API) ou à la demande. Le contrefactuel actuel reste le repli pour les autres modèles.
- **Contrefactuels** simples, dans l'esprit de DiCE : « que faudrait-il changer pour basculer la décision ? », sur 1 à 3 variables modifiables déclarées.
- **Débogage du modèle en production** : le paquet d'explication (arbre d'erreur, fairness) appliqué au **dataset de feedback étiqueté**. Il est déclenché par la surveillance planifiée ou à la demande, et affiché comme « Où le modèle se trompe **en production** » avec le composant d'arbre existant.
- **Surveillance de la fairness** : les écarts par groupe sur les données de production étiquetées, avec alerte (M3).

**Critère** : un biais planté en production est détecté par la fairness de production ; une zone d'erreur de production apparaît dans l'arbre.

### M6 — « Model instance » optionnelle (sur besoin client)

À lancer **seulement** sur un besoin client explicite : SLA dédié, isolation, dépendances propres, volume.

- **Objet `ml_deployments`**
  - Modèle (lignée), version ou alias suivi (`champion` par défaut), profil de ressources.
  - Réplicas min / max, environnement (`staging` / `prod`), état (`pending` → `deploying` → `healthy` / `unhealthy` → `stopped` / `deleted`, comme le builder de papAI), URL.
  - Poids de routage.
- **Exécution**
  - Sur Kubernetes : un Deployment et un Service par déploiement, lancés par le **lanceur du lot D4** du plan DataOps (compte de service restreint, NetworkPolicy, Secret par déploiement).
  - Image : **image de service MLflow construite à partir de l'image d'exécution qualifiée**, sans `pip install` au démarrage. HPA sur le CPU ou le débit.
  - Sur VM : indisponible, avec sa raison ; le plan partagé reste la voie.
- **Routage**
  - `/predict` d'un modèle déployé passe par le déploiement.
  - **Canary pondéré** (champion / challenger, en %) et option d'**agrégation** (moyenne ou vote pondérés, comme papAI).
  - La répartition du trafic est journalisée par version.
- **Cycle de vie** : arrêt, démarrage, mise à jour de version (déploiement progressif), retour arrière, santé par sonde et heartbeat.
- **Pièges papAI exclus** : pas de pipeline GitLab, pas de Postgres par workspace, pas de RBAC cluster, pas d'image `latest`, pas de jeton en clair.

**Critère (lab)** : déployer, recevoir du trafic, faire un canary à 10 %, revenir en arrière, s'arrêter, chaque étape étant visible dans la page Endpoints (M3) et dans l'audit (M1).

---

## 6. Séquencement et PR

| Lot | PR | Migration | Images | Drapeaux |
|---|---|---|---|---|
| M0 | Hors dépôt (papAI) | — | — | — |
| M1 | 1 : droits et audit · 2 : clés (expiration, portée) et limites de débit · 3 : `store=false`, rétention et quota d'exposition | Oui (champs des clés, politique) | Backend | `ml_rbac_enforced` (d'abord en mode rapport) |
| M2 | 1 : données de réentraînement · 2 : dérive de concept et badge de prévision · 3 : historique et dérive des scores contre l'entraînement · (4 : multivarié) | Oui (référence des scores) | Backend, worker | `ml_retraining_data_mode` |
| M3 | 1 : canaux et alertes · 2 : agrégats et page Endpoints · 3 : coût d'inférence | Oui (`ml_usage_rollups`, canaux) | Backend, frontend | `ml_alerts_enabled` |
| M4 | 1 : export · 2 : requalification de l'environnement d'exécution · 3 : import BYOM | Oui (famille `external`, attestats) | Backend, worker (pool isolé) | `ml_byom_enabled` |
| M5 | 1 : SHAP et contrefactuels · 2 : débogage et fairness en production | Non | Worker | — |
| M6 | 1 : objet déploiement et lanceur · 2 : routage, canary et agrégation · 3 : interface et cycle de vie | Oui (`ml_deployments`) | + image de service | `ml_deployments_enabled` |

**Ordre** : M0 → (M1 ‖ M2) → M3 → M4 → M5 → M6 (sur demande). Deux ou trois agents au plus en parallèle.

**Mode rapport pour M1** : `ml_rbac_enforced=false` journalise les refus sans bloquer pendant une release, pour mesurer l'impact sur les usages réels avant d'imposer les droits.

---

## 7. Tests transverses

- **Back** : matrice de droits, audit, limites de débit (429), clés expirées, rétention, données de réentraînement (comparaison sur jeu synthétique), dérive de concept (régression et multiclasse), alertes (e-mail via un serveur SMTP local de test, webhook signé), agrégats, export → `mlflow models serve` → mêmes prédictions, requalification, import refusé ou accepté, SHAP (additivité), débogage en production.
- **Front** : specs des VM (page Endpoints, historique, alertes), e2e mockés en FR et EN, `check:i18n`, `build:prod` une fois par lot.
- **Lab (M6)** : déploiement, canary, retour arrière, arrêt, sous quota.

---

## 8. Risques

| Risque | Mitigation |
|---|---|
| Les droits M1 bloquent des usages existants (démos, Flows) | Mode rapport pendant une release, matrice publiée, rôles des comptes de démo ajustés |
| Le réentraînement combiné change le comportement attendu par les démos | Mode `feedback_only` gardé en option ; preuves de la proposition qui montrent les deux scores |
| Charge de l'agrégation des métriques | Agrégats par intervalles de 5 minutes, index ciblés, rétention des agrégats |
| L'import de modèles ouvre une surface d'exécution de code | Pool isolé, sous-processus restreint, aucune clé applicative, profils de confiance, réservé aux administrateurs, audit |
| M6 coûte cher à exploiter | Lot optionnel, lancé sur besoin client seulement ; réutilise le lanceur D4 |

---

## 9. Hors périmètre

- Reproduire la pile papAI (builder par GitLab, passerelle séparée, Postgres par workspace).
- Service de LLM (déjà couvert par le plan des modèles et le portail LLM).
- Entraînement distribué.
- Ensembles appris (stacking) au-delà de l'agrégation pondérée de M6.

---

## Annexe A — Inventaire papAI (fichiers de référence)

| Capacité | Fichier |
|---|---|
| Déploiement (builder) | `builder-service/src/api/routes/deployment.py`, `src/services/{artefacts,inference_code,secret_generation,gitlab,permissions}.py`, `src/schemas/atoms/life_status_enum.py` |
| Routes d'administration ouvertes | `builder-service/src/api/routes/admin.py`, `src/api/internal_app.py` |
| Passerelle | `model-interface/src/services/listener/api/{routes,api_keys,app}.py`, `src/services/{model_collection,requests}.py`, `src/services/aggregation/`, `src/services/data_storage_backend/database/` |
| Dérive | `model-analyser/src/api/routes/data_drift.py`, `src/utils/frouros_multi_detector.py` ; `papai-ml/src/services/utils/ksdrift.py` |
| Planificateur | `scheduler-service/src/jobs/fetch_model_interface_status.py` |
| Artefacts | `datategy-model-artefacts/model_artefacts/schemas/mlmodel.py` ; `datategy-mlflow-model-signature/` |
| Core | `core/.../domain/machinelearning/RegistryRun.scala`, `application/ModelRegistryApplication.scala:241`, `infrastructure/web/routes/external/DeploymentApi.scala` (ancienne pile), `infrastructure/web/routes/private/PrivateMLBuilderApi.scala` |
| Front | `frontend/packages/ml-ops/`, `frontend/src/app/modules/use-case/pages/run/run.component.html` (Debug) |
| Déploiement (infra) | `ansible/ansible/roles/gitlab_mlops_init/templates/model-deployment-repo-files/`, `roles/mlops_{builder,analyser,scheduler}` |
| Import externe, environnements sur mesure | `papai-ml/engine/api/endpoints/{external_pipeline,custom_env}.py` |

## Annexe B — Inventaire Agentium (fichiers de référence)

| Capacité | Fichier |
|---|---|
| Registre et cycle de vie | `backend/app/models/tabular.py` ; `backend/app/services/{tabular_ml,ml_registry,ml_comparison}.py` |
| Artefacts et confiance | `backend/app/resources/{ml_train_harness,ml_artifact_contract}.py` ; `backend/app/services/ml/{artifacts,artifact_trust,runtime}.py` |
| Service | `backend/app/services/tabular_predict.py` ; `backend/app/services/ml/{forecast_serving,deep_serving}.py` ; `backend/app/api/v1/endpoints/ml_models.py` |
| Surveillance | `backend/app/services/tabular_monitoring.py` ; `backend/app/resources/ml_drift.py` ; `backend/app/services/ml/forecast_monitoring.py` |
| Automatisation | `backend/app/services/{ml_shadow,ml_retraining,mlops_jobs}.py` ; `backend/app/workers/{ml_tasks,celery_ml,celery_app}.py` |
| Explicabilité | `backend/app/resources/ml_explanation_extensions.py` ; `frontend-ng/src/app/features/models/explanation-evidence.*` ; `frontend-ng/src/app/features/data/viz/decision-tree*` |
| Audit, e-mail, rôles | `backend/app/services/audit_logger.py` (`emit_audit_event`) ; `backend/app/services/email.py` (`send_email`) ; `backend/app/core/iam/roles.py` |
| Limites de débit (non branché) | `backend/app/core/rate_limiter.py` |
| Interface | `frontend-ng/src/app/features/models/*` ; `frontend-ng/src/app/features/runs/run-view.component.ts` |
| Documentation ML | `docs/agentium-ml-lot*.md`, `docs/agentium-ml-ts-*.md`, `docs/agentium-model-operations-*.md` |

## Annexe C — Nouveaux codes d'erreur et réglages

**Codes**

| Code | Cas |
|---|---|
| `ML_FORBIDDEN_ACTION` | Action refusée par le rôle (avec `details.action`) |
| `ML_API_KEY_EXPIRED` | Clé API expirée |
| `ML_RATE_LIMITED` | Limite de débit (429, avec `Retry-After`) |
| `ML_EXPOSURE_QUOTA_EXCEEDED` | Quota de modèles exposés dépassé |
| `ML_FEEDBACK_NOT_STORED` | Feedback impossible : appel avec `store=false` |
| `ML_RETRAINING_DATA_INCOMPATIBLE` | Données de réentraînement incompatibles |
| `ML_EXPORT_FORBIDDEN` | Export refusé |
| `ML_IMPORT_REJECTED` | Import refusé (avec la raison) |
| `ML_RUNTIME_REQUALIFICATION_FAILED` | Requalification de l'environnement d'exécution échouée |
| `ML_DEPLOYMENT_UNAVAILABLE` | Déploiement dédié indisponible (M6) |

**Réglages**
- `ml_rbac_enforced`
- `ml_api_key_default_ttl_days`
- `ml_predict_rate_per_minute`, `ml_predict_rows_per_minute`
- `ml_max_exposed_models`
- `ml_prediction_retention_days`
- `ml_retraining_data_mode`
- `ml_concept_regression_watch`, `ml_concept_regression_alert`
- `ml_alerts_enabled`, `ml_alert_throttle_minutes`
- `ml_byom_enabled`
- `ml_deployments_enabled`
