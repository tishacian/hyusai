# M4.2 — Requalification de l'environnement d'exécution, 18 octobre 2026

Lot développé sur `feat/mlops-m4-requalification` depuis `demo/agentic` à
`d814837b` (M1, M2, M3 et M4.1 assemblés). Référence : §5 lot M4, point 3 de
`agentium-mlops-papai-parity-plan.md`. Aucun déploiement, aucune nouvelle
dépendance Python, aucune nouvelle image ; `/api/v1/build-info` est inchangé.
L'import BYOM (M4.3) n'est pas commencé.

## Le problème

Le service refusait tout modèle dont l'environnement producteur enregistré
différait de celui du lecteur (`validate_model_runtime`, égalité stricte,
`ML_ARTIFACT_RUNTIME_MISMATCH`). Monter scikit-learn, skrub, numpy, pandas,
MLflow ou skops dans l'image retirait donc tout le registre du service. M4.2
remplace « refuser pour toujours » par « requalifier, puis autoriser, pour cet
artefact exact et ce lecteur exact », sans assouplir les autres contrôles.

## Contrats livrés

**Prédictions de référence.** Pour une version, Agentium enregistre les sorties
du modèle, sous son environnement producteur, sur les `ML_REFERENCE_ROWS`
premières lignes (par identifiant trié) du test final enregistré par M2. Les
lignes ne sont jamais copiées : seuls leurs identifiants (empreintes SHA-256 du
contenu typé, M2) et les sorties sont stockés. Classification : classe prédite
et vecteur complet de probabilités, ordre des classes enregistré. Régression :
valeur. L'objet est un JSON gzip borné (taille compressée et décompressée),
avec empreinte SHA-256, schéma et format vérifiés, jamais de pickle. Il est
rangé à côté de la partition d'évaluation, sous une clé adressée par son
contenu. Son résumé (empreinte, lignes, environnement producteur, artefact,
partition, date, auteur) est dans `metrics_json.runtime_reference`, comme le
résumé de partition de M2 ; la ligne modèle n'est modifiée que sous verrou.

Les lignes sont re-dérivées du dataset source avec la vérification M2 :
même identifiant et même version de dataset, empreinte de partition identique.
Un modèle sans partition vérifiable, dont le dataset a disparu ou ne correspond
plus, est refusé par `ML_REFERENCE_SOURCE_UNAVAILABLE` (action `retrain`, avec
la raison). Aucune ligne n'est inventée.

**Capture.** Elle n'a lieu que lorsque le lecteur est l'environnement
producteur (passage par la porte stricte de service), sinon
`ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED`. Trois voies : automatiquement après
chaque entraînement prêt (`ML_REFERENCE_CAPTURE_ON_TRAIN`), à la demande depuis
la fiche (tâche Celery sur le worker général) et en masse par la CLI opérateur.

**Requalification.** Sous l'environnement courant, un sous-processus isolé
charge le bundle vérifié avec tous les contrôles de service sauf l'égalité
d'environnement : empreintes, tailles, profil de confiance, liste blanche skops
et chargeur MLmodel. Il prédit les lignes de référence par le code de service
(`coerce_rows`, `build_frame`, `_predict_frame`) et renvoie ses sorties. Le
parent, et non l'enfant, compare avec les tolérances :

- classification : classes identiques sur 100 % des lignes (réglage
  d'écarts tolérés, 0 par défaut), `max |Δp| ≤ ML_REQUALIFY_PROBA_ATOL`, ordre
  des classes inchangé ;
- régression : `|Δ| ≤ atol + rtol·|réf|` sur chaque ligne ;
- clustering : étiquettes identiques (comparaison prête, mais voir les limites).

L'enfant suit le modèle du shadow et de l'entraînement : `supervise_harness`,
`PR_SET_PDEATHSIG` sous Linux, limites mémoire/CPU/fichiers, répertoire
temporaire, JSON par fichiers. Il ne reçoit ni base, ni object store, ni
secret : le parent télécharge le bundle par l'inventaire autorisé et en vérifie
les empreintes, l'enfant les revérifie juste avant de charger. Ses refus
remontent en codes uniquement.

**Attestation.** Migration `138_mlops_requalification` : table
`ml_runtime_attestations`, une ligne par tentative (workspace, modèle,
empreinte d'artefact, environnements producteur et lecteur, empreinte de la
référence, lignes comparées, écarts mesurés, tolérances appliquées, verdict
`qualified|failed`, code d'erreur, auteur, date, révocation). Un index unique
partiel garantit au plus une attestation qualifiée active par (modèle,
artefact, empreinte de l'environnement lecteur) ; une contrainte limite le
verdict à ces deux valeurs. Les échecs sont conservés comme preuves et
n'accordent rien.

**Porte de service.** `validate_model_runtime(artifact, current, attested)`
accepte l'égalité (inchangé) ou une attestation active dont l'empreinte
d'artefact, l'environnement producteur et l'environnement lecteur correspondent
tous ; un paquet `missing` reste refusé. `verify_model_bundle` et
`require_artifact_runtime` reçoivent les attestations en argument explicite.
Le service les lit pour la ligne servie, à travers la session de la ligne ; une
ligne détachée ou un namespace des harness garde la porte stricte. La clé de
cache des pipelines inclut les identifiants des attestations actives : une
révocation évince la pipeline résidente au prochain appel, dans tous les
processus, et immédiatement dans le processus qui révoque.

**Droits et audit (M1).** Nouvelle action `requalify`, réservée aux
administrateurs et stricte comme `export`/`import` : le mode rapport ne
l'accorde jamais. `ml.model.reference_capture`, `ml.model.requalify` (chaque
tentative, réussie ou non) et `ml.model.attestation_revoke` sont écrits dans la
transaction de la mutation ; un audit impossible annule la mutation et l'objet
de référence orphelin est supprimé. Une tâche demandée par un utilisateur
revérifie son rôle courant au moment d'écrire.

**API** (router `ml_runtime`, enregistré comme `ml_exports`) :

- `GET /ml-models/{id}/runtime` : environnements producteur et lecteur, écarts
  de paquets, statut (`current`, `attested`, `requalification_required`,
  `reference_missing`, `unsupported` avec raison), résumé de référence,
  attestations actives et tentatives récentes, tâches en cours, tolérances.
  Ni clé de stockage, ni ligne, ni secret.
- `POST …/runtime/reference` et `POST …/runtime/requalify` : 202, une tâche
  idempotente par (modèle, artefact[, environnement lecteur]).
- `DELETE …/runtime/attestations/{id}` : révocation auditée, idempotente ;
  une tentative échouée ne se révoque pas (`ML_ATTESTATION_NOT_ACTIVE`).

Les refus sont des `TabularError` `CODE: message` : `ML_REFERENCE_SOURCE_UNAVAILABLE`,
`ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED`, `ML_REFERENCE_MISSING`,
`ML_REFERENCE_INVALID`, `ML_REFERENCE_TOO_LARGE`, `ML_REQUALIFICATION_UNSUPPORTED`,
`ML_REQUALIFICATION_NOT_REQUIRED`, `ML_REQUALIFICATION_READER_CHANGED`, et pour
les tentatives `ML_REQUALIFICATION_OUTPUT_MISMATCH`,
`ML_REQUALIFICATION_CLASS_ORDER_CHANGED`, `ML_REQUALIFICATION_TIMEOUT`,
`ML_REQUALIFICATION_HARNESS_FAILED` ou le code de refus de l'artefact.

**Export (M4.1).** Un modèle attesté s'exporte sous le lecteur attesté. Les
attestations actives sont jointes en `runtime-attestations.json` ; le README
précise que l'archive fonctionne sous l'environnement producteur **ou** sous un
environnement lecteur attesté listé. Les autres gardes sont inchangées, et une
révocation pendant la copie refuse l'archive (`ML_EXPORT_SOURCE_CHANGED`).

**Interface.** Section « Environnement d'exécution » dans l'onglet Réglages,
après l'export : statut en clair, bibliothèques qui diffèrent (entraînement /
service actuel), état de la référence, dernière tentative avec les écarts
mesurés et leurs tolérances, boutons Enregistrer, Requalifier et Révoquer
conditionnés par `serving.permissions.requalify`. Neutre par défaut, ambre
quand les appels sont refusés mais requalifiables, rouge quand seul un
réentraînement aide ou que la dernière tentative a échoué. La note de
disponibilité renvoie vers la requalification lorsqu'une référence existe.

## Adaptations par rapport au brief et pourquoi

1. **Identifiant de révision** `138_mlops_requalification` au lieu de
   `138_mlops_runtime_requalification` : ce dernier fait 33 caractères et
   `alembic_version.version_num` est un `varchar(32)` (test existant).
2. **Capture à l'entraînement après la validation**, pas dans le harness :
   une tâche est mise en file après le commit de la version prête. Le harness
   reste inchangé, et surtout la référence est produite par le même code que la
   requalification ; une différence entre les frames brutes du harness et
   celles du service ne peut pas être prise pour une dérive d'environnement.
3. **Clé de référence adressée par le contenu** : deux captures concurrentes
   (fiche et CLI) n'écrasent jamais l'objet que l'autre a validé.
4. **Budgets de source propres** : `read_source` et `partition_for` (M2)
   acceptent un budget optionnel ; M4.2 utilise `ML_REFERENCE_SOURCE_*`,
   dimensionnés comme l'entraînement. Le budget de réentraînement (100 000
   lignes, 32 Mio) aurait refusé la plupart des modèles.
5. **Clustering refusé** (`no_evaluation_partition`) : il est servi par lignes,
   mais n'enregistre aucun test final à rejouer ; aucune ligne n'est inventée.
6. **Lecture de l'état** autorisée comme la fiche modèle (appartenance au
   workspace), sans appel M1 `read` qui écrirait un audit de mode rapport sur
   un GET.
7. **Environnement lecteur demandé** : la tâche porte l'empreinte du lecteur
   qui l'a demandée (l'API). Si le worker qui l'exécute en diffère, il refuse
   `ML_REQUALIFICATION_READER_CHANGED` sans écrire d'attestation : une
   attestation pour un autre lecteur ne servirait pas l'API.
8. **Shadow** : un challenger attesté est noté avec ses attestations, sinon
   sa disponibilité affichée et son exécution se contrediraient.
9. **Reprise des tâches sans beat** : une tâche en file depuis plus de 30 s ou
   en cours au-delà de son bail (`ML_REQUALIFY_TIMEOUT_S` + 120 s) est relancée
   par la demande suivante ; aucune tâche périodique n'est ajoutée.
10. **Action de refus** : le détail de `ML_ARTIFACT_RUNTIME_MISMATCH` vaut
    `requalify_or_retrain` ; la disponibilité propose `requalify` seulement si
    le modèle est éligible et a une référence, sinon `retrain`.

## Tolérances par défaut

- `ML_REQUALIFY_PROBA_ATOL = 1e-6` : le service arrondit les probabilités
  renvoyées à 6 décimales ; un écart inférieur ne change au plus que le
  dernier chiffre affiché, alors qu'un changement de comportement (calibration,
  seuil, division d'arbre) dépasse largement ce seuil. Les réordonnancements
  flottants d'une mise à jour BLAS/numpy restent de l'ordre de 1e-12 sur ces
  modèles ; les mesures ci-dessous donnent 0.
- `ML_REQUALIFY_MAX_LABEL_DISAGREEMENTS = 0` : une classe qui change sur une
  ligne de référence est un changement de réponse.
- `ML_REQUALIFY_REGRESSION_RTOL = 1e-6` (six chiffres significatifs, même
  ordre que les probabilités) et `ATOL = 1e-9` pour les valeurs proches de zéro,
  où une tolérance relative n'a pas de sens ; le bruit float64 est ~1e-15.

Ce sont des réglages. Chaque attestation enregistre les tolérances appliquées :
un assouplissement reste visible et daté.

## Réglages

| Réglage | Défaut |
|---|---:|
| `ML_REFERENCE_ROWS` | 256 |
| `ML_REFERENCE_MAX_BYTES` | 16 Mio (compressé et décompressé) |
| `ML_REFERENCE_SOURCE_MAX_ROWS` | 2 000 000 |
| `ML_REFERENCE_SOURCE_MAX_BYTES` | 512 Mio |
| `ML_REFERENCE_CAPTURE_ON_TRAIN` | `true` |
| `ML_REQUALIFY_MAX_LABEL_DISAGREEMENTS` | 0 |
| `ML_REQUALIFY_PROBA_ATOL` | 1e-6 |
| `ML_REQUALIFY_REGRESSION_ATOL` | 1e-9 |
| `ML_REQUALIFY_REGRESSION_RTOL` | 1e-6 |
| `ML_REQUALIFY_TIMEOUT_S` | 300 |
| `ML_REQUALIFY_MEMORY_LIMIT_MB` | 4 096 |
| `ML_REQUALIFY_HISTORY_LIMIT` | 10 |

## Migration et activation

Appliquer `138_mlops_requalification` après 137 et avant les nouveaux
processus. Le downgrade est refusé tant qu'une attestation existe : c'est la
seule trace de la raison pour laquelle un modèle se charge sous un autre
environnement. Ne pas supprimer les lignes pour contourner ce refus. Aucun
drapeau n'active la porte : sans attestation, le comportement de service est
strictement celui de M4.1. La capture après entraînement est active par défaut
et ne fait jamais échouer un entraînement.

L'API et le worker général doivent tourner sur la même image : l'attestation
porte l'environnement exact du processus qui a rejoué les références, et le
service ne l'accepte que si son propre environnement est identique.

La procédure de montée d'image est dans `agentium-mlops-delivery.md`.

## Vérifications

Depuis `backend`, venv partagé (scikit-learn 1.9.0, skrub 0.11.0, skops 0.16.0,
MLflow 3.15.2), `sqlglot` ajouté hors venv par `--target` pour importer le
router complet :

- **9 tests d'intégration réels** (`test_ml_requalification.py`) : modèles
  entraînés par le harness de production, capture automatique, montée simulée
  de scikit-learn dans le processus de service **et** dans l'enfant isolé
  (`sitecustomize`), refus puis attestation puis service identique, éviction
  sur révocation (même processus et autre processus), lecteur perturbé
  (`max |Δp| = 1e-3`, refusé), référence altérée puis réempreintée (refusée),
  empreinte cassée (`ML_REFERENCE_INVALID`), dataset absent ou autre version
  (`ML_REFERENCE_SOURCE_UNAVAILABLE`), modèle sans référence (reste refusé),
  régression qualifiée, CLI idempotente.
- **41 tests unitaires** : comparaison par tâche, porte (égalité, attestation
  complète, refus d'empreinte, de producteur, de lecteur, de paquet manquant),
  filtrage des attestations révoquées/échouées/d'un autre artefact, index
  unique, matrice de droits en mode rapport, atomicité de l'audit (capture,
  requalification, révocation), bornes et empreinte de la référence, harness
  qui garde tous les contrôles sauf l'égalité, bail des tâches.
- **14 tests HTTP** du router et **3 tests d'export** (attestation jointe,
  aucune sans attestation, révocation pendant la copie).
- **Preuve inter-versions réelle** (`test_ml_requalification_cross_version.py`,
  opt-in par `MLOPS_SKLEARN_OVERLAY`) : surcouche `--target` de scikit-learn
  1.8.0 (30 Mo) devant la 1.9.0 du venv. Le harness entraîne réellement en
  1.8.0, l'enfant de capture prédit réellement en 1.8.0, la requalification et
  le service tournent réellement en 1.9.0. Seule la vérification de métadonnées
  du *parent* de capture est simulée (le processus de test n'est pas l'image
  productrice). Résultats sur 21 lignes de référence :
  - `LogisticRegression` : **qualifiée**, 0 désaccord, `max |Δp| = 0.0`, puis
    servie en 1.9.0 ;
  - `HistGradientBoostingClassifier` : **refusée** `ML_ARTIFACT_UNTRUSTED_TYPES`
    avant tout chargement : le fichier skops de 1.8.0 contient
    `_loss.CyHalfBinomialLoss`, que skops sous 1.9.0 ne reconnaît plus comme
    type de confiance. La requalification n'élargit pas la confiance ; ce
    modèle doit être réentraîné. C'est une limite réelle d'une montée mineure
    de scikit-learn pour les boosted trees, pas un défaut du lot.
- **PostgreSQL 16.2 réel** (pgserver jetable, port 55433, arrêté ensuite) :
  10 tests ciblés de la chaîne de migrations (138 admis, comparaison ORM/DDL de
  la nouvelle table, index unique partiel et contrainte de verdict, downgrade
  refusé avec lignes puis accepté une fois vide, ré-upgrade). Chaîne ciblée
  complète : **73 tests réussis** (23 min 42 s), comparaison ORM/DDL des seize
  tables du plan, downgrade jusqu'au parent puis ré-upgrade. Ce n'est pas un
  rejeu de tout l'historique Alembic depuis une base vide ; les révisions hors
  périmètre sont estampillées, comme pour M1 à M3.
- **Régression ML élargie** en `-n 4`, deux lots. Premier lot (27 fichiers
  : prédiction, shadow réel, export, contrat d'artefact, gouvernance,
  entraînement, réentraînement, justesse M2, opérations M3, API ML, catalogue
  de surface) : **774 réussis, 1 échec** — la liste des tâches de l'image de
  famille, qui contient désormais `agentium.ml_runtime_requalification`. C'est
  un changement de contrat voulu (la tâche suit la file d'entraînement de la
  famille, qu'un consommateur `celery_ml` dédié peut détenir) ; le test est
  mis à jour et repasse. Second lot (20 fichiers : familles, distillation,
  registre, pilote TabICL, scoring publié, évaluation, alertes, portail) :
  **273 réussis, 3 ignorés, 1 échec** —
  `test_published_scoring_flow_delivers_verified_work_receipt_and_portable_bytes`,
  qui échoue à l'identique sur `d814837b` : le sous-processus SQL de la
  préparation de données n'a pas `deltalake` dans ce venv local. Ni ce test ni
  ce code ne sont modifiés par le lot.
- **Frontend** (Node 22) : 12 tests du VM et du composant ; suite complète
  **2 353 tests réussis**. TypeScript, `check:i18n` et `check:nav-links`
  passent ; l'unique `build:prod` réussit, avec les avertissements préexistants
  (budgets, NG8102/NG8107/NG8113), aucun ne provenant des fichiers du lot. `check:ui-chrome` reste rouge sur l'état préexistant de
  `src/styles.scss` (7 halos, plafond 6), inchangé ; le plafond n'est pas
  relevé.

Ruff passe sur les fichiers ajoutés ; les fichiers existants touchés gardent
leur dette de formatage préexistante, sans ligne nouvelle. Aucune recette
navigateur sur une carte réelle, aucune qualification VM ni image n'est
revendiquée.

## Limites

- Familles servies hors de l'API (`forecasting`, `forecasting_deep`,
  `tabular_deep`, `tabular_foundation`) : `ML_REQUALIFICATION_UNSUPPORTED`.
  La tâche est structurée pour qu'un runtime distant l'exécute plus tard sur sa
  propre file (le lecteur est celui qui exécute), mais rien n'est branché.
- Clustering : pas de test final enregistré, donc pas de référence.
- La requalification dépend du dataset source de la version : s'il est supprimé
  ou purgé, le modèle reste refusé après une montée et doit être réentraîné.
  Capturer **avant** la montée ne lève pas cette dépendance.
- Le nombre de lignes de référence est borné par le test final (21 lignes dans
  les tests) ; un test final minuscule donne une preuve faible, visible sur la
  fiche (« sur N lignes »).
- Une montée qui change les types sérialisés (cas des boosted trees ci-dessus)
  n'est pas requalifiable par conception.
- `PR_SET_PDEATHSIG` n'est actif que sous Linux ; les tests locaux macOS
  n'exercent pas cette garde.
