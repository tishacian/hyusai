# Qualification Skore — lots 2 à 6

Date : 11 octobre 2026. Branche : `feat/skore-integration-lots-2-6`, issue du lot 1
`a9d4fdc1058b3c49d03f88b9b4dfda5e26af378b`. Base cible : `demo/agentic`.
Voir la [roadmap](agentium-skore-integration-roadmap.md) et la
[qualification du lot 1](agentium-skore-lot1-verification.md).

## Contrats et preuves

- MinIO/ObjectStore conserve les octets ; MLflow conserve le registre et le tag
  `agentium.evaluation_partition`. Aucun client Project/Hub ni second stockage.
- `evaluation.json.gz`, schéma 1, conserve dataset/version/cible/graine,
  empreintes des cellules typées et appartenances train/test. Plafonds : 128 MiB
  compressés et 192 MiB JSON décompressé. Aucun pickle n'est lu en comparaison.
- Les nouvelles comparaisons relisent le Parquet avec le lecteur de training,
  vérifient les empreintes et intersectent les tests. Tout contenu utilisé dans
  le train de l'un des modèles est exclu. Des graines différentes sont possibles ;
  la réponse rapporte les graines enregistrées et aucun faux seed courant.
- Changement de version/contenu, artefact corrompu, preuve manquante d'un côté ou
  absence d'intersection indépendante : refus `ML_COMPARE_UNVERIFIED_PARTITION`.
  Deux modèles legacy restent explorables, avec `verified=false` et avertissement.
- `metric_semantics`, schéma 2, explicite classe positive, agrégation, MAPE en %,
  écart-type CV avec `ddof=1` et F1 calculé par classe. Le changement de F1 macro
  et d'écart-type des extensions peut modifier les nombres des nouveaux modèles.
  Les anciens nombres restent intacts. Les classes positives incompatibles
  déclenchent un refus de comparaison.
- Training, comparaison et prédiction partagent les libellés de classes. La
  prédiction et la comparaison reconnaissent également la représentation des
  booléens numpy et les libellés tronqués des anciens modèles.
- Les diagnostics publics Skore sont exécutés contrôle par contrôle dans un
  processus distinct, sur un clone non ajusté et uniquement des lignes du train.
  Portée `development_base_estimator`, `served_model=false`. Le rapport final
  préentraîné reste test-only. Le processus hérite du groupe d'annulation du
  superviseur ; le budget inclut démarrage, imports, ajustement et checks.
- Les checks rapides sélectionnés sont SKD001/002/004/008/009/012/013/016.
  SKD009 est coûteux et reste `skipped` en mode rapide. Les autres sont `ignored`
  ou `not_applicable`. Une erreur est conservée par contrôle ; un timeout conserve
  les résultats partiels et ne remet pas en cause le modèle déjà entraîné.
- La revue API et `ml_evaluation_review_v1` sont en lecture seule et limitées au
  workspace autorisé. Elles lisent les diagnostics de développement, jamais les
  scores du test final pour recommander une correction. Le résultat est une
  hypothèse à examiner dans le Flow, sans exécution ni promotion.

## Qualification locale

Environnement Python 3.12.14, contraintes app complètes avec Skore 0.27.0,
skrub 0.10.1, scikit-learn 1.9.0, numpy 2.5.2, pandas 2.3.3, MLflow 3.15.2,
skops 0.14.0. PyPI vérifié ce jour : Skore 0.27.0 reste la dernière version stable
et Skore Lib est sous licence MIT.

Le smoke reproductible ne contacte aucun service de tracking ou de stockage :

```bash
cd backend
python -m scripts.qualify_skore_integration --diagnostics --output /tmp/skore-smoke.json
```

Il réalise deux entraînements réels sur 2 000 lignes synthétiques, réouvre le
modèle MLflow, vérifie ses scores sur la partition enregistrée et un round-trip
skops. En classification, la classe positive `accept` est à la première position,
avec calibration sigmoid et seuil F1 sélectionné sur le train. Les deux CV
réussissent et les diagnostics sont `completed` sur 225 lignes de train et
75 lignes de validation de développement.

| Cas | Temps total local | Diagnostics | Modèle MLflow | Partition | Rapport Skore |
| --- | ---: | ---: | ---: | ---: | ---: |
| Classification | 38,384 s | 6,918 s | 22 589 284 octets | 76 896 octets | 86 138 octets |
| Régression | 33,849 s | 5,580 s | 4 211 244 octets | 76 934 octets | 20 903 octets |

Ces mesures sont celles de cet environnement, pas une estimation des images ni
un SLO de production. Le code du harness mesuré a l'empreinte SHA-256
`b54b71fa6a5ba42c644253981e48186d09524fa0bc188dd83ed06e95d9366ded`.

Résultats enregistrés au cours de la qualification :

- 300 tests backend de la suite étendue réussis : entraînement, comparaison,
  registre, calibration, provenance, métriques, revue/API, familles, intervalles,
  texte, explications, options combinées, forecasting Skore et wrappers de Skills.
- 111 tests du périmètre prédiction/adaptateur/diagnostics également réussis,
  dont annulation réelle du groupe de processus. Les cas complémentaires
  libellés legacy, dates Parquet et conservation des checks partiels après
  timeout sont qualifiés séparément.
- 30 tests des contextes d'images, contraintes de dépendances et provenance
  réussis. Le test de torch/torchvision accepte maintenant le bloc d'installation
  conditionnel de l'API ; il exige toujours les deux packages depuis l'index CPU.
- 2 107 tests unitaires frontend réussis ; `check:i18n`, `check:nav-links`,
  `check:ui-chrome` réussis et compilation de production réussie. Les warnings
  existants de taille CSS et dépendance CommonJS restent visibles.
- 15 tests du script de sauvegarde exécutés avec PostgreSQL 16 dans un conteneur
  éphémère local. Les appels privilégiés/MinIO sont simulés par les shims existants,
  les dumps PostgreSQL sont réels. Aucun test n'est ignoré. Une partition absente
  ou corrompue empêche l'émission de `.ready` ; les objets restent dans le miroir
  du préfixe `ml/` existant.
- Trois tests navigateur locaux FR/EN réussis, avec API simulée et bundle de production :
  navigation de la proposition à la preuve, maintien de la fiche après le clic,
  absence de mutation et revue indisponible lorsque le budget est épuisé.
  Les canaries du runner protégé et le MinIO/MLflow live restent à exécuter.
- Hooks des fichiers modifiés validés : Ruff, format, ShellCheck/shfmt et contrat
  de conformité produit. Gitleaks 8.30.1 exécuté séparément sur le diff stagé,
  sans fuite détectée. Les hooks yamlfmt (aucun YAML modifié) et mise à jour des
  hooks ne font pas partie de cette qualification.

## Activation et retour

Les valeurs par défaut gardent les diagnostics désactivés. La provenance et les
conventions de métriques s'appliquent aux nouveaux entraînements uniquement.
Pour un premier workspace pilote, ajouter au fichier d'environnement existant
du worker (liste JSON, ID réel du workspace) :

```dotenv
ML_SKORE_CHECKS_ENABLED=true
ML_SKORE_CHECKS_WORKSPACES=["<workspace-id>"]
ML_SKORE_CHECKS_BUDGET_S=30
ML_SKORE_CHECKS_MAX_ROWS=2000
```

Le runtime switch **et** l'allowlist doivent autoriser le workspace. L'activation
ne parcourt pas les anciens modèles et ne déclenche aucun réentraînement.
Revenir à `ML_SKORE_CHECKS_ENABLED=false`, puis recréer le worker via le processus
de livraison normal, retire le coût des diagnostics des entraînements futurs.
Les preuves déjà produites restent consultables. Le rollback de code utilise le
tag immuable précédent, sans réécrire les artefacts.

Avant activation effective, suivre [le processus de livraison](agentium-release-process.md) :

1. Intégrer les PR sur `demo/agentic`, pousser et relever le SHA complet. La VM
   ne doit pas construire ni déployer la branche de fonctionnalité.
2. Attester et conserver le runtime/image Skore 0.25 d'origine, ainsi que sa
   recette, pour les anciens états joblib. Leur ouverture directe en 0.27 échoue.
3. Construire sur la VM les images API, worker, frontend et les runtimes ml-ts/
   ml-deep activés, avec base Python qualifiée par digest et tag SHA12 immuable.
   Exécuter le smoke ci-dessus dans chaque image Python et le contrôle des budgets
   d'images existant. Comparer les versions et empreintes du harness.
4. Exécuter le dump du plan de données. Exiger `.ready` et vérifier les nouveaux
   compteurs/digests de partitions avant le switch.
5. Déployer diagnostics désactivés, vérifier build-info et canaries protégées,
   puis activer le workspace pilote. Effectuer un entraînement explicitement
   demandé et une comparaison réelle via API, vérifier les références MLflow et
   les octets MinIO ; examiner temps, taille et statuts des diagnostics.
6. Simuler un budget épuisé et un entraînement annulé sur données synthétiques,
   vérifier l'absence de processus orphelin ; remettre le flag à false, vérifier
   qu'un prochain entraînement est marqué `disabled` et que les modèles servis
   n'ont pas changé. Étendre l'allowlist seulement après cette vérification.

La qualification des images et l'activation VM ne sont pas réalisées depuis ce
workspace : l'alias/identité SSH n'y est pas configuré, les observations de
l'environnement n'annoncent aucun secret ou outbound identity, et la politique
TCP n'autorise aucun domaine ou IP. Ne pas contourner ce manque d'accès par copie
du checkout ou désactivation des contrôles réseau. Les preuves locales ne
remplacent pas les builds VM, la disponibilité du runtime 0.25 ou les canaries.
