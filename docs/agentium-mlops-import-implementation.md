# M4.3 — Import de modèles externes (formats sûrs), 18 octobre 2026

Lot développé sur `feat/mlops-m4-import`, empilé sur M4.2
(`feat/mlops-m4-requalification`, `1da40599`). Référence : §5 lot M4, point 2
de `agentium-mlops-papai-parity-plan.md`. Périmètre choisi : **formats sûrs
d'abord**. Aucune dépendance Python, aucune image, aucune migration ajoutée ;
`/api/v1/build-info` est inchangé.

## Ce qui est accepté, ce qui est refusé

**Accepté** : un dossier de modèle MLflow zippé dont `MLmodel` porte la saveur
`sklearn` avec `serialization_format: skops`, `python_function.loader_module:
mlflow.sklearn`, `model.skops` comme fichier de modèle, ni chemin de code ni
`python_model`, et une **signature par colonnes** (noms et types `double`,
`float`, `long`, `integer`, `boolean`, `string`, `datetime`). Tâches :
classification binaire ou multiclasse (avec `predict_proba` si l'estimateur
l'a) et régression.

**Refusé** (`ML_IMPORT_REJECTED`, raison dans `details.reason`) :

| Cas | Raison |
|---|---|
| pickle, cloudpickle, joblib | `pickle_serialization`, `cloudpickle_serialization`, `joblib_serialization` |
| pyfunc personnalisé, `python_model` | `custom_pyfunc` |
| chemins de code, modèle « from code » | `code_paths` |
| autre saveur que sklearn | `flavor_unsupported` |
| fichier inattendu, bibliothèque native, `.py`, `.pkl` | `unexpected_file`, `native_library`, raisons ci-dessus |
| signature absente ou par tenseurs | `signature_missing`, `signature_tensor` |
| type de colonne non servable, colonnes sans nom | `signature_type_unsupported`, `signature_unnamed` |
| types skops hors du profil du lecteur | `untrusted_types` (types listés) |
| types skops non déclarés dans `MLmodel` | `trusted_types_undeclared` |
| archive invalide, trop grande, trop d'entrées | `archive_invalid`, `archive_too_large` (413), `archive_too_many_entries` |
| chemin hors du dossier, lien, entrée chiffrée, doublon | `archive_path_unsafe`, `archive_symlink`, `archive_encrypted`, `archive_duplicate` |
| absence de `MLmodel` | `mlmodel_missing` |

Les formats qui exécutent du code au chargement exigent un pool isolé, différé
en **M4.3b** : un conteneur sans secret applicatif, un réseau limité au broker
et au stockage, un sous-processus bac à sable non « dumpable », et un service
par RPC sur ce pool, jamais dans l'API. Rien de ce lot ne les rapproche du
processus API.

## Profil de confiance `external-sklearn-skops-v1`

Profil détenu par le lecteur (`services/ml/artifact_trust.py`, `PROFILES`).
Au-delà des types que skops considère déjà sûrs (estimateurs scikit-learn,
ufuncs numpy comme `log1p`, conteneurs simples), il n'ajoute que :

- `numpy.dtype` : un descripteur de type, reconstruit sans appel de code ;
- `sklearn.tree._tree.Tree` : le stockage des nœuds des arbres de décision,
  forêts et gradient boosting. Il n'appelle aucun code, mais skops le signale
  : scikit-learn indexe ses tableaux de nœuds **sans contrôle de bornes**, et
  un fichier forgé se charge puis lit hors mémoire au `predict`. Nous l'avons
  reproduit (un enfant gauche à 10⁶ est accepté par `__setstate__` et par
  skops). Le lecteur isolé vérifie donc, avant la première prédiction d'un
  modèle importé, chaque arbre atteignable : enfants vers l'avant et dans le
  tableau (donc sans cycle), variables de coupure existantes, seuils finis.
  Un arbre invalide est refusé (`ML_IMPORT_TREE_INVALID`). Les octets ainsi
  validés sont ensuite fixés par empreinte pour le service.

`functools.partial`, les callables `builtins.*`, les fonctions numpy comme
objets (`numpy.clip`) et toute fonction de l'importateur (par exemple dans un
`FunctionTransformer`) restent hors profil, donc refusés. Le `TreePredictor`
de HistGradientBoosting en est exclu tant que ses tableaux de nœuds n'ont pas
le même contrôle : ces modèles sont refusés (`untrusted_types`).

Note d'assemblage : la branche M5 ajoute `sklearn.tree._tree.Tree` au profil
**tabulaire** (forêts du catalogue). Ce lot ajoute la même chaîne au profil
**externe**, distinct ; seule une proximité textuelle est à attendre.

## Déroulement

1. `POST /ml-models/import` (multipart : `archive`, `validation`, `task`,
   `name`, `target`, `lineage_model_id`, `description`). Action M1 stricte
   `import` (administrateurs, jamais accordée par le mode rapport) et drapeau
   `ML_IMPORT_ENABLED` (faux par défaut). L'archive est copiée avec un
   compteur d'octets (413 au-delà de `ML_IMPORT_MAX_MB`) ; un `Content-Length`
   annoncé trop grand est refusé avant copie. Le proxy doit borner le corps de
   requête : FastAPI a déjà mis le multipart sur disque quand le code s'exécute.
2. Contrôles synchrones, sans aucun chargement : enregistrement de fin de zip
   lu avant `ZipFile`, entrées bornées (`MAX_BUNDLE_FILES`), taille dépliée
   bornée par `ML_TRAIN_ARTIFACT_LIMIT_MB`, chemins relatifs sûrs, ni lien, ni
   chiffrement, ni doublon, compression stockée ou deflate seulement ;
   extraction en flux dans un répertoire privé supprimé sur tous les chemins.
   zipfile ne lit jamais plus que la taille déclarée (puis le CRC échoue),
   et les octets écrits sont recomptés. Puis lecture de `MLmodel` (YAML sûr,
   taille bornée), de la signature, et des types skops listés depuis le schéma
   du fichier, sans reconstruction. Enfin le jeu de validation est vérifié
   contre la signature par la coercition même du service.
3. L'archive et le jeu sont déposés dans
   `workspaces/{ws}/ml/imports/{job}/`, puis une tâche `agentium.ml_model_import`
   part sur la file d'entraînement de la famille. 202 avec la tâche.
4. Le worker revérifie les empreintes du dépôt, que son environnement est
   celui qui a demandé (`ML_IMPORT_READER_CHANGED` sinon), réextrait et
   réinspecte, construit le contrat d'artefact (`build_artifact_contract`,
   famille `external`, runtime = ce lecteur), puis rejoue la validation dans
   le **harness isolé de M4.2**, mode `import` : porte stricte, contrôle des
   arbres, coercition par le contrat dérivé de la signature, prédiction. Il
   mesure le temps de chargement, la latence d'une ligne et la mémoire de pointe
   ajoutée par le modèle, et compare avec `compare()` et ses tolérances.
5. Succès seulement si les sorties concordent **et** que les budgets sont
   tenus. Sinon : `ML_IMPORT_VALIDATION_FAILED` (`outputs_differ` avec les
   écarts mesurés, ou `reader_refused` avec le code du lecteur) ou
   `ML_IMPORT_BUDGET_EXCEEDED` (`load_time`, `predict_latency`, `memory`, avec
   mesures et budgets). Jamais de trace ni de texte de pilote.
6. `GET /ml-models/import/{job}` donne l'issue. Une tâche abandonnée au-delà de
   son bail est passée en échec et ses fichiers déposés sont supprimés.

**Jeu de validation** : JSON `{"rows": [...], "expected": {...}}` ;
`expected` vaut `{"labels", "classes"?, "probabilities"?}` (probabilités dans
l'ordre de `classes`, obligatoire si elles sont fournies) ou `{"values"}`.
Entre `ML_IMPORT_MIN_VALIDATION_ROWS` et `ML_IMPORT_MAX_VALIDATION_ROWS`
lignes. Les étiquettes sont normalisées comme celles du service ; un ordre de
classes différent mais de même ensemble est réaligné avant comparaison.

## Enregistrement

- Nouvelle ligne `MLModel`, famille `external`, `algo = external`, statut
  `ready`. Le contrat d'entrée vient de la signature (noms, types). Les
  valeurs typiques, bornes et choix sont estimés sur les lignes de validation
  uniquement pour préremplir le Playground ; chaque champ porte
  `hint_source: import_validation`. Aucune statistique (dérive, explications)
  n'en est dérivée : **les explications sont refusées** pour un modèle importé
  (`ML_EXTERNAL_UNSUPPORTED`, raison `explanations`).
- Provenance dans `params_json.import` : origine, empreinte de l'archive,
  exigences déclarées (`requirements.txt`), version MLflow, estimateur final,
  auteur, tâche. La validation (lignes, écarts, tolérances, mesures, budgets)
  dans `metrics_json.import`.
- Lignée : nouvelle (nom libre, refus `lineage_name_taken` si le nom existe
  déjà), ou nouvelle version d'une lignée **externe** de même tâche. Une
  nouvelle lignée sert sa première version comme un entraînement ; une
  nouvelle version ne remplace jamais le champion : la promotion suit la
  sémantique existante et la politique d'approbation M1. Un entraînement ne
  peut pas rejoindre une lignée importée (`ML_EXTERNAL_LINEAGE`).
- **Référence M4.2** : variante `import_validation` qui **stocke** les lignes
  (bornées, doublons dédupliqués) et les sorties de ce lecteur, puisqu'aucune
  partition de dataset n'existe. La capture est refusée pour un modèle importé
  (`import_validation_only`), la requalification relit les lignes stockées.
  L'objet est supprimé avec le modèle sur tous les backends de stockage.
- L'audit `ml.model.import` d'un import accepté partage la transaction de
  l'enregistrement : s'il échoue, rien n'est enregistré et les octets déposés
  sont supprimés.

## Ce qui suit l'import

- Service, journal, feedback et clés : comme un modèle tabulaire.
- Dérive des entrées : indisponible avec la raison `no_training_distribution`
  (le jeu de l'importateur n'est pas une distribution d'entraînement).
- Dérive de concept : comme en tabulaire, sur le feedback étiqueté ; sans
  référence de scores, elle se compare à la fenêtre précédente (repli M2).
- Surveillance planifiée et propositions de réentraînement : refusées
  (`ML_EXTERNAL_UNSUPPORTED`, `scheduled_monitoring`). Shadow et comparaison :
  indisponibles (pas de dataset). L'interface masque ces actions et explique.
- Export M4.1 : inchangé (il exige `input_example.json` dans le bundle, comme
  pour tout modèle).
- Requalification M4.2 : depuis les lignes stockées.

## Audit

Chaque tentative produit `ml.model.import` : acceptée (dans la transaction
d'enregistrement) ou refusée (raison, code, écarts, mesures, tailles,
empreinte de l'archive, nombre de lignes), y compris pour un non-administrateur,
le mode rapport ou le drapeau éteint. Jamais de ligne ni de valeur. L'audit
d'un refus s'écrit après rollback dans sa propre transaction ; s'il est
indisponible, le refus est maintenu et l'incident journalisé.

## Interface

Action « Importer un modèle » dans la liste (capacité `permissions.import` du
serveur, sans déduction de rôle), boîte de dialogue (archive, jeu de
validation, tâche, lignée nouvelle ou existante, nom, variable prédite),
suivi de la validation et verdict en clair : accepté avec un lien, ou refusé
avec la raison, le code du lecteur et les écarts et coûts mesurés face à leurs
budgets. Sur la fiche : badge « Importé », preuves d'import dans l'onglet
Résultats (pas de test final ni de courbes), Réentraîner et Comparer masqués,
surveillance planifiée et shadow remplacées par une explication.

## Réglages

| Réglage | Défaut |
|---|---:|
| `ML_IMPORT_ENABLED` | `false` |
| `ML_IMPORT_MAX_MB` | 128 |
| `ML_IMPORT_VALIDATION_MAX_BYTES` | 8 Mio |
| `ML_IMPORT_MIN_VALIDATION_ROWS` | 20 |
| `ML_IMPORT_MAX_VALIDATION_ROWS` | 1 000 |
| `ML_IMPORT_MAX_LOAD_MS` | 30 000 |
| `ML_IMPORT_MAX_PREDICT_MS` | 1 000 (une ligne) |
| `ML_IMPORT_MAX_MEMORY_MB` | 1 024 (pointe ajoutée par le modèle) |
| `ML_IMPORT_MAX_METADATA_BYTES` | 1 Mio |

S'y ajoutent ceux de M4.2 (tolérances, délai et mémoire du lecteur isolé) et
`ML_TRAIN_ARTIFACT_LIMIT_MB` pour la taille dépliée.

## Adaptations et pourquoi

1. **Aucune migration** : la colonne `family` n'a pas de contrainte, les
   tentatives vivent dans `workspace_jobs` (type serveur `ml_model_import`) et
   l'audit, la provenance dans les JSON du modèle. `140_mlops_model_import`
   n'a donc pas été créée.
2. **Contrôle structurel des arbres** et exclusion de `TreePredictor` : non
   prévus par le brief, imposés par l'avertissement de skops reproduit.
3. **Sorties de référence = sorties de ce lecteur**, pas celles de
   l'importateur : elles ont concordé dans les tolérances, et la référence
   M4.2 désigne ce que le modèle répond sous son environnement qualifié.
4. **Hypothèses de contrat estimées et étiquetées**, explications refusées
   plutôt qu'appuyées sur un échantillon choisi par l'importateur.
5. **Mesure mémoire** : pointe RSS du lecteur isolé après chargement et
   prédiction, moins la pointe après les imports. C'est une approximation du
   coût résident dans l'API, pas une mesure de l'API elle-même.

## Activation

Activer `ML_IMPORT_ENABLED` seulement après avoir borné le corps des requêtes
au proxy et vérifié que l'API et le worker général tournent sur la même image
(le contrat enregistre l'environnement du worker qui valide). Aucune autre
étape ; les modèles déjà présents ne sont pas affectés.

## Vérifications

Depuis `backend`, venv partagé (scikit-learn 1.9.0, skops 0.16.0, MLflow
3.15.2), `sqlglot` et `deltalake` ajoutés hors venv par `--target` :

- **7 tests positifs réels** (`test_ml_import.py`) : ColumnTransformer +
  OneHotEncoder + StandardScaler avec une forêt (3 classes), une régression
  logistique (binaire) et une forêt de régression, enregistrés par MLflow avec
  skops et une signature ; import HTTP, validation dans le lecteur isolé,
  `/predict` et journal, export M4.1, requalification depuis les lignes
  stockées après une montée simulée ; lignée externe (version 2 non
  championne, nom pris refusé) ; refus de ce qui ne s'applique pas
  (explications, dérive d'entrée, surveillance planifiée, capture,
  entraînement dans une lignée importée) ; suppression des lignes avec le
  modèle et des fichiers déposés.
- **31 tests de refus** (`test_ml_import_refusals.py`) : pickle, cloudpickle,
  joblib, autre saveur, pyfunc personnalisé, chemins de code, fonction
  personnalisée et `functools.partial` dans un `FunctionTransformer`, types
  non déclarés, signature absente et par tenseurs, étiquette fausse et
  probabilités décalées (écarts mesurés), trop peu de lignes, budget dépassé,
  zip slip, lien, entrée chiffrée, doublon, `MLmodel` absent, upload trop
  grand et bombe de décompression, répertoire qui sous-déclare ses tailles,
  arbre forgé hors bornes (refusé avant toute prédiction), HistGradientBoosting
  refusé, non-administrateurs dans les deux modes de droits, drapeau éteint,
  audit indisponible qui n'enregistre rien. Chaque refus vérifie son audit.
- Régression backend : RESULTAT_REGRESSION.
- Frontend (Node 22) : 11 tests du VM et du composant d'import ; suite complète
  RESULTAT_FRONT ; TypeScript, `check:i18n`, `check:nav-links` passent ;
  `build:prod` RESULTAT_BUILD. `check:ui-chrome` reste rouge sur l'état
  préexistant de `src/styles.scss` (7 halos, plafond 6), inchangé.

Aucune recette navigateur, VM, PostgreSQL (pas de migration) ni charge n'est
revendiquée.

## Limites

- Seuls les formats skops sklearn sont acceptés ; M4.3b (pool isolé pour
  pickle, cloudpickle, joblib, pyfunc et code) reste à faire.
- HistGradientBoosting est refusé jusqu'au contrôle de ses tableaux de nœuds.
- Les autres estimateurs que skops juge sûrs par défaut sont acceptés sur son
  jugement ; ce lot ne les audite pas un à un.
- La validation prouve la **portabilité** (mêmes sorties ici que chez
  l'importateur), pas la **qualité** : un modèle importé n'a pas de test final
  mesuré par Agentium, et la fiche le dit.
- La mesure mémoire et les budgets sont approximatifs et dépendent de la
  plateforme ; ils bornent un abus manifeste, pas une capacité fine.
