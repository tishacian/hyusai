# Intégration Skore dans Hyusai

## Décision et périmètre

Base de travail : `demo/agentic`, commit `7e41de642c6254b3b88f508cb37be79ff5844fed`.
Cible du premier lot : Skore **0.27.0**, publié le 9 octobre 2026.

**MinIO/ObjectStore conserve les octets et MLflow conserve le registre et les
références existantes. Aucun second stockage d'expériences n'est introduit.**
Ne pas créer de `skore.Project`, de base locale Skore, de serveur de tracking
supplémentaire ou de dépendance à Skore Hub. Les fichiers temporaires du harness
restent des fichiers de travail, transférés par le worker vers l'ObjectStore
existant. Le rapport facultatif `report/state.joblib` et son tag MLflow existant
gardent leurs chemins et leur politique de conservation.

Skore Lib (MIT) fournit les évaluations compatibles. Hyusai reste responsable
des exécutions, de la provenance, des autorisations et de la promotion des modèles.
Les intégrations d'agents restent au lot 5 ; cette migration ne requiert aucun
service Probabl hébergé.

## État de départ

- `requirements.txt` autorise Skore 0.25 ; `constraints-demo-app.txt` le fige
  précisément en 0.25.0. API, worker, ml-ts et ml-deep partagent ces contraintes.
- Le harness tabulaire utilise `EstimatorReport`, `CrossValidationReport` et
  les DataFrames `.frame()`. La comparaison utilise `ComparisonReport`.
- La calibration, les seuils F1/Youden, Optuna, les intervalles, les explications
  et les runtimes spécialisés existent déjà : les conserver et les qualifier.
- Le forecasting utilise aussi Skore pour diagnostiquer le régresseur à un pas,
  indépendamment de ses métriques de backtest : inclure ce chemin dans les tests.
- Le rapport principal est préentraîné et test-only. Il ne contient pas le train
  nécessaire à certains checks ; ne pas lui attacher artificiellement un train.
- Les comparaisons reconstruisent encore leur holdout ; le manifeste de
  partition et les diagnostics structurés restent à réaliser.

## Lots et critères de sortie

| Lot | Contenu | Critères de sortie | État |
| --- | --- | --- | --- |
| 1 — Compatibilité 0.27 | Mettre à jour plage et contraintes ; centraliser les lectures de métriques dans un adaptateur sans I/O ; préserver les réponses API et les artefacts. | Évaluations réelles classification/régression/CV/comparaison ; calibration et seuils ; qualification explicite de la relecture des anciens états ; sauvegarde/rechargement MLflow ; contraintes cohérentes. | Réalisé et qualifié localement ; réserve de livraison sur les anciens états |
| 2 — Provenance et partitions | Enregistrer dataset/version/empreinte, identifiants de lignes, stratégie, graine, cible et classe positive ; utiliser ces partitions en comparaison. | Reproduction indépendante de l'ordre de lecture et de la configuration courante ; exclusion vérifiable des lignes d'entraînement ; anciens modèles marqués lorsque la preuve manque. | Planifié |
| 3 — Diagnostics | Exécuter les checks applicables sur les rapports de développement ; enregistrer code, explication, portée, statut et version ; limiter les checks coûteux. | Cas contrôlés de surapprentissage/fuite ; non-applicable, ignoré et erreur distincts d'un résultat favorable ; budget et annulation respectés. | Planifié |
| 4 — Métriques et décision métier | Définir classe positive et agrégation explicitement ; corriger F1 macro ; unifier métriques et conventions de calibration ; conserver l'entraînement spécialisé par fold. | Comparaison avec scorers de référence, classes rares, courbes avant/après et modèle servi identique au modèle évalué ; aucune sélection sur le test final. | Planifié |
| 5 — Interface et agents | Présenter preuves/limites dans les fiches et comparaisons ; proposer des améliorations via le Flow et les gates existants. | Navigation de l'alerte à sa preuve ; autorisations par workspace ; proposition, entraînement et promotion restent des décisions distinctes. | Planifié |
| 6 — Activation | Qualifier images, tailles, latences et compatibilité des artefacts ; activer progressivement les diagnostics. | Images identifiées, tests de bout en bout, procédure de retour vérifiée ; aucun réentraînement implicite. | Planifié |

Ordre : 1 → 2 → 3 → 4 → 5 → 6. Chaque lot est livré séparément avec ses tests
et sa qualification. L'autorisation actuelle porte sur la roadmap et le lot 1,
pas sur un déploiement ni l'activation des lots suivants.

## Contrats à préserver

L'adaptateur du lot 1 est un module Python utilisable par les scripts autonomes
et par l'API. Il transforme les sorties publiques Skore en données Hyusai ; il
ne crée ni client réseau, ni registre, ni stockage. Les contrats `scores`,
`primary`, `cv`, comparaison, courbes et `report_state` restent compatibles.
Un format de métriques inattendu doit échouer explicitement, plutôt que choisir
silencieusement la première colonne d'un tableau ambigu.

Le lot 1 ne change pas la signification historique de F1, la classe positive,
les seuils, le découpage ni les règles de promotion : ces évolutions sont
identifiées au lot 4 et devront documenter les différences de scores.

Pour les lots suivants, le résumé d'évaluation versionné sera stocké dans les
artefacts et métadonnées existants. Le rapport Skore complet reste facultatif.
La compatibilité future de `to_dict()` n'est pas présumée : elle est vérifiée
sur les versions qualifiées. Préserver les anciens artefacts et leurs versions,
sans réécriture générale lors d'une migration.

La qualification du lot 1 a mis en évidence deux différences :

- Skore 0.27 ajoute `default_score` (la méthode `.score()` de l'estimateur).
  L'adaptateur conserve les métriques nommées du contrat Hyusai et exclut cette
  nouvelle ligne, pour éviter une modification implicite des comparaisons.
- Les états joblib 0.25 testés ne se chargent pas directement en 0.27 : ils
  référencent `skore._utils._skrub`, supprimé. Leur relecture est qualifiée dans
  le runtime 0.25 d'origine. Les nouveaux états sont qualifiés en 0.27.
  Aucun alias de module privé ni conversion automatique n'est ajouté.

Avant livraison, conserver l'image/runtime 0.25 et sa recette de dépendances
pour relire les anciens rapports à partir du même ObjectStore. Cela ne crée
aucun second stockage. La disponibilité de ce runtime est un prérequis de
livraison ; les tests locaux ne prouvent pas sa disponibilité en production.
L'application ne possède pas aujourd'hui de lecteur de rapports persistés :
la comparaison recharge les modèles et reconstruit une évaluation. Tout futur
lecteur devra sélectionner un runtime compatible avec la version déjà inscrite
dans les métadonnées du rapport, ou signaler explicitement l'incompatibilité.

Les rapports de développement/CV alimentent les itérations. Le test final
indépendant est réservé à l'évaluation finale ; il ne pilote ni le tuning, ni
les corrections répétées proposées par l'agent. Un check exécuté sur le modèle
de base ne doit pas être présenté comme un diagnostic du modèle calibré servi.

Le schéma de restitution pourra être commun aux familles, mais Skore n'est pas
un évaluateur universel de clustering, forecasting, modèles de fondation ou RAG.
Conserver leurs évaluateurs spécifiques et indiquer moteur et portée.

## Qualification du lot 1

Les résultats, commandes, limites et consignes de livraison sont consignés dans
`docs/agentium-skore-lot1-verification.md`. Ne déclarer ni les images qualifiées,
ni la migration déployée à partir de seuls tests Python locaux.

Références :

- [Release Skore 0.27.0](https://github.com/probabl-ai/skore/releases/tag/skore%2F0.27.0)
- [Métadonnées et licence](https://pypi.org/project/skore/0.27.0/)
- [Contrôles méthodologiques](https://docs.skore.probabl.ai/stable/user_guide/automated_checks.html)
- [Qualification des extensions existantes](agentium-ml-lot2-verification.md)
- [Stockage du registre](../backend/app/services/ml_registry.py)
- [Processus de livraison](agentium-release-process.md)
