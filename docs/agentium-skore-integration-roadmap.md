# Intégration Skore dans Hyusai

## Décision et périmètre

Base de travail : `demo/agentic`, commit `7e41de642c6254b3b88f508cb37be79ff5844fed`.
Cible : Skore **0.27.0**, publié le 9 octobre 2026. Vérification PyPI renouvelée
le 11 octobre 2026 : dernière version stable, Python ≥ 3.11, licence MIT.

**MinIO/ObjectStore conserve les octets et MLflow conserve le registre et les
références existantes. Aucun second stockage d'expériences n'est introduit.**
Ne pas créer de `skore.Project`, de base locale Skore, de serveur de tracking
supplémentaire ou de dépendance à Skore Hub. Les fichiers temporaires du harness
restent des fichiers de travail, transférés par le worker vers l'ObjectStore
existant. Le rapport facultatif `report/state.joblib` et son tag MLflow existant
gardent leurs chemins et leur politique de conservation.

Skore Lib (MIT) fournit les évaluations compatibles. Hyusai reste responsable
des exécutions, de la provenance, des autorisations et de la promotion des modèles.
La revue agent du lot 5 utilise les diagnostics de développement ; cette
intégration ne requiert aucun service Probabl hébergé.

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
| 2 — Provenance et partitions | Artefact JSON compressé dans l'ObjectStore existant, référence MLflow ; comparaison sur l'intersection des tests prouvés, excluant les contenus vus au train. | Empreintes indépendantes de l'ordre et de la graine courante ; corruption, dataset modifié et preuves incomplètes refusés ; anciens modèles explicitement non vérifiés. | Implémenté, qualifié localement |
| 3 — Diagnostics | Rapport de développement distinct, modèle de base cloné ; checks publics isolés, processus à budget limité et plafond de lignes. | Surapprentissage et fuite temporelle contrôlés ; statuts distincts ; timeout sans perdre le modèle, annulation par le groupe du superviseur. | Implémenté, qualifié localement ; activation désactivée par défaut |
| 4 — Métriques et décision métier | Classe positive explicite ; F1 moyen des F1 par classe ; calibration/seuil/CV cohérents ; MAPE en pourcentage et écart-type CV d'échantillon. | Scorers de référence ; classe positive à la première position ; rechargement du modèle réellement servi ; aucune sélection sur le test final. | Implémenté, qualifié localement |
| 5 — Interface et agents | Fiche d'évaluation FR/EN ; preuves et limites en comparaison ; revue en lecture seule accessible au Flow et aux agents. | Lien de la piste au contrôle ; isolation workspace ; aucune mutation, aucun entraînement ni promotion par la revue. | Implémenté, qualifié localement ; navigateur FR/EN validé |
| 6 — Activation | Script de smoke par image, mesures de taille/temps, sauvegarde vérifiant les partitions, allowlist de workspaces et retour au flag désactivé. | Builds immuables sur VM, runtime 0.25 conservé, canaries protégées et activation progressive sans réentraînement implicite. | Préparé et qualifié localement ; qualification des images et activation VM restantes |

Ordre : 1 → 2 → 3 → 4 → 5 → 6. Le lot 1 est livré séparément ; les lots 2 à 6
partagent une branche d'intégration, avec des critères de qualification distincts.
Le GO utilisateur porte désormais sur tous les lots. Les conditions de livraison
du dépôt restent applicables : source poussée sur `demo/agentic`, builds sur VM,
sauvegarde vérifiée et canaries protégées avant une activation effective.

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

Le résumé d'évaluation versionné est stocké dans les
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

## Implémentation des lots 2 à 6

Le worker écrit `report/evaluation.json.gz` à côté de `report/state.joblib`,
dans le préfixe `ml/models/<model_id>` existant. Le JSON n'embarque pas une copie
des cellules : il conserve leurs empreintes SHA-256 et les appartenances au
train/test. Les contenus identiques présents dans les deux partitions sont
signalés et exclus des comparaisons. Dataset et version doivent correspondre ;
un dataset transformé différent ne peut pas être déclaré indépendant sans
provenance de lignes inter-datasets, qui n'est pas encore disponible.

Les diagnostics sont limités aux modèles tabulaires classiques. Un clone du
modèle de base est ajusté sur une sous-partition du train, avec validation de
développement distincte. Les contrôles coûteux restent non exécutés en mode
rapide ; les contrôles hors périmètre sont ignorés. Ils ne constituent pas une
certification et ne décrivent pas le modèle calibré servi.

`ml_evaluation_review_v1` appartient à la Capability existante `tabular_models`.
Son contexte d'exécution fournit le workspace, sans substitution depuis le
payload. Il propose des hypothèses issues des contrôles de développement ; les
statuts partiels et les seuls scores de test final ne génèrent pas de pistes.
L'auteur valide le plan du Flow, déclenche l'entraînement par le mécanisme
existant et décide séparément de la promotion. Aucun nouveau mécanisme de gates,
de registre ou de stockage n'est créé.

Les commandes, mesures, contrôles de sauvegarde et étapes d'activation sont dans
[la qualification des lots 2 à 6](agentium-skore-lots-2-6-verification.md).

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
