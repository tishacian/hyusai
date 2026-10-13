# Plan DataOps et juge typé d’Agentium

> **État du 13 octobre 2026** : implémentation locale sur `codex/dataops-typed-judge`, à partir de `66ce576b482e931a180673d9eca76fbe9e84cb0b` du miroir GitHub. Aucun déploiement, aucune fusion ni qualification fournisseur n’est affirmé ici.
> **Recette** : workspace Showcase, sans client pilote exigé ; scoring quotidien de 2 millions de lignes, recette haute à 3 millions. Narration de plusieurs centaines de pages/images est **différée à la demande de l’utilisateur**. La route envisagée est Gemini via OpenRouter ; son raccordement et sa qualification viendront plus tard.
> **Lecture** : les §§0–4 décrivent le lot effectivement construit. Les §§5–30 conservent le détail de conception historique : les contrats HTTP, paramètres et limites d’exécution actuels sont ceux des schémas et services cités en §3. Les placements éphémères et connecteurs décrits dans ces annexes restent des extensions conditionnelles.

## 0. Ordre, état et critères de sortie

La restructuration rend le dépôt reprenable, testable et déployable. Elle reste un préalable de livraison. La préparation, l’interface et le stockage en plusieurs parts gardent leur place ; les promesses, les actifs documentaires/référentiels et le juge typé complètent le plan.

| Lot | Livrable et recette | État local | Condition de clôture en environnement |
|---|---|---|---|
| **R0** | Terminer les phases de l’ADR 0004 ; modules et wrappers dans leurs packages ; build reproductible | Nouvelle structure utilisée pour tout ce lot | Toutes les phases livrées et `build-info` correspondant à la révision réellement déployée ; non vérifié sur VM ici |
| **S0** | Écritures HANA réservées aux admins, drapeau fermé, suppression du mot de passe de plateforme de repli, TLS vérifié, erreurs expurgées, politique réseau | Implémenté et testé ; SSRF en mode rapport par défaut | Recette HANA/TLS et passage à `enforce` après inventaire ; révocation externe du token Docker Hub papAI à confirmer |
| **D0** | Runner DuckDB hors API, file `dataops`, environnement minimal, budgets mémoire/spill, mort du parent | Modifications de l’ancienne branche D0 reportées dans la nouvelle structure | Worker déployé et smoke réel ; pas de fusion implicite de l’ancienne branche |
| **C0** | Contrats des usages, unité de travail, sortie, recette et destination | [Scoring](agentium-showcase-scoring-contract.md) prêt ; [narration](agentium-showcase-narration-contract.md) conservé comme brouillon différé | Scoring dans Showcase avec vrais source, modèle et responsable |
| **A1** | Actifs immuables dataset/model/document_set/reference, filiation, qualifications, « à requalifier » | Implémenté ; droits natifs, hashes et propagation aux descendants testés | Migration 126, ObjectStore partagé, sauvegarde/restauration vérifiée |
| **P1** | Promesse versionnée par System, responsable, calendrier, entrées fraîches, tentatives, budgets, incidents | Implémenté ; fenêtres indépendantes d’un Run et raccordement au scheduler publié | Installer le watchdog extérieur ; vérifier les incidents et les leases en environnement |
| **D1a** | Spec v1, compilateur sûr, huit opérations, catalogue de 59 actions uniques, types, déterminisme | Implémenté ; sémantique et refus testés | Limites et distributions du workspace confirmées |
| **D1b** | API, `data_prep_v1`, bloc graph-owned, ports explicites, aperçu borné | Implémenté ; parcours publié réel testé jusqu’au reçu | Activation ciblée `dataops` et publication du System |
| **D2** | Préparation no-code, inspecteurs Flow, éditeur/lecture du juge, Work | Implémenté ; tests, TypeScript, contrôles UI et build production réussis | Recette dans un navigateur de l’environnement livré |
| **D3** | Une table Delta immuable par version, parts en flux, profils, échantillons, lecteurs compatibles | Implémenté ; plusieurs parts réellement exercées à 3 M de lignes | Restaurer SQL + objets + journaux sur le stockage cible ; aucun downgrade lecteur avant rollback des écrivains |
| **M1** | Scoring en batches bornés, modèle/version figés, identifiants et colonnes conservés, aucun appel LLM par ligne | Implémenté ; modèles tabulaires/clustering, régression et intervalles natifs | Qualification sur modèle et données Showcase réels |
| **J1/J2** | Questions réellement posées, réponses typées, abstention, preuves, coût, calibration indépendante et seuil humain | Implémenté avec `evaluate_v2` ; `evaluate_v1` reste versionné | Gemini/OpenRouter, transport vision et corpus à qualifier plus tard ; aucune confiance de substitution |
| **W1** | Candidat exact, revue liée à trois empreintes, publication atomique, reçu et téléchargement vérifié | Implémenté ; test complet avec vraie décision humaine persistée | Destination actuelle `work:showcase-scoring` ; système externe à traiter lorsqu’il est désigné |
| **N1** | Adaptation du moteur externe narration aux mêmes contrats | Hors lot actif ; flag fermé et seed brouillon | Reprise seulement lorsque demandée, avec moteur et route de modèle qualifiés |
| **D4/D5/D6/D7/I1/I2** | Kubernetes éphémère, Spark, extensions et autres connecteurs/Iceberg | Différés | Besoin mesuré qui dépasse le socle permanent ; le Helm de déploiement client reste utile dès maintenant |

**Ordre de livraison** : R0 + S0 + reprise D0 ; C0 en parallèle ; A1 + P1 ; D1a/D1b/D2/D3 + M1 ; J1/J2 et W1. Les contrats et le socle d’actifs se prêtent au travail parallèle, avec deux ou trois agents au maximum. L’unification complète des deux usages sera reçue lors de la reprise de narration ; le scoring utilise déjà les mêmes actifs, fenêtres, budgets, revue et reçus.

## 1. Contrats de service et socle commun

Chaque contrat publié appartient à un System et à un responsable actif du workspace. Il déclare calendrier, échéance, budget cumulé, entrées, schéma de sortie et destination. Une nouvelle révision ne modifie pas une fenêtre déjà ouverte. Les transitions couvrent les quatre promesses : entrées à jour, traitement complet, résultat accepté, livraison reçue.

Une source se sélectionne par `ServiceDefinition.inputs` : `payload_key`, `kind`, `logical_key`, fraîcheur maximale, qualification requise et politique optionnelle. `representation: native_id` fournit l’identifiant natif d’un dataset/modèle ; `asset_ref` fournit la référence gouvernée. Le serveur choisit la dernière version autorisée lors de l’ouverture, vérifie sa fraîcheur et sa qualification, puis fige références et qualifications dans `ServiceWindow.input_snapshot_json`. Une reprise conserve ces références ; une requalification intervenue depuis l’inspection bloque son usage. Le Flow Showcase n’épingle pas l’ancien dataset par-dessus cette entrée quotidienne.

Les actifs conservent manifeste, objets, références natives, parents et empreintes. La qualification est une version indépendante ; « à requalifier » se propage aux descendants sans modifier l’historique. Un actif gouverné retient ses versions natives. Les preuves et les téléchargements revérifient les droits natifs ; un reçu ne crée aucun droit supplémentaire.

Les fenêtres existent même si aucun Run ne démarre. Le tick publié crée les périodes, fige les entrées et envoie le vrai SystemVersion par l’ingress/outbox existant. Les tentatives et checkpoints utilisent leases et fences. Un worker perdu, une source périmée, une revue en retard ou une livraison absente crée un incident durable attribué au responsable. Les incidents se consultent dans Work ; aucun canal email ou Slack n’est implicitement ajouté.

Le ledger partagé réserve les dépenses avant appel, par fenêtre/stage/clé idempotente. Coûts inconnus et appels interrompus gardent leur réserve ; les usages non mesurés restent `null`. Un dépassement ou une facture contradictoire bloque la publication. Les allocations par stage sont facultatives et leur somme ne dépasse pas l’enveloppe globale. Voir [les promesses](ops/service-contracts.md) et [le budget partagé](ops/service-window-budget.md).

## 2. Parcours de préparation, scoring et juge

### Préparation et stockage

La spec v1 ferme les champs, borne étapes/sorties et expose `prepare`, `join`, `union`, `aggregate`, `pivot`, `unpivot`, `split`, `sample`. Les 59 actions incluent les alias compatibles ; elles ne désignent pas 59 algorithmes indépendants. Le compilateur quote les identifiants, refuse les collisions de casse, valide les expressions SQL par liste d’autorisation et impose UTC. Les tirages et départages sont déterministes. Les sels de hash sont des secrets de workspace dédiés, référencés par version ; le navigateur ne reçoit jamais leurs valeurs.

L’inférence de types se fait sur un schéma vide. L’aperçu lit exclusivement l’échantillon persisté ou l’ancien aperçu stocké, avec bornes de taille, concurrence et durée ; il ne matérialise pas le dataset complet. En exécution, le runner lit des fichiers locaux vérifiés dans DuckDB avec spill, écrit des batches et ne détient ni session applicative ni secret de connexion. Les sources, la spec et les modèles sont figés à la soumission. Les fences d’exécution empêchent une annulation ou un timeout de rendre ensuite les sorties `ready`.

Les sorties sont des tables Delta distinctes par version, chacune écrite une seule fois avec commit 0. Les fichiers sont immuables et le journal est publié en dernier ; les sorties d’un même nœud deviennent prêtes dans une transaction SQL unique. Le lecteur autorise seulement les fichiers annoncés, vérifie hashes/protocole/chemins et sait lire les anciens Parquet. La mise à jour des lecteurs précède l’activation des écrivains Delta. Fermer le flag d’écriture n’efface aucune version Delta.

### Scoring quotidien

Le parcours publié est entrée → `data_prep_v1` → `ml_batch_score_v1` → sortie gouvernée. Le worker charge un vrai modèle natif une fois et score par batches de 65 536 lignes. Il conserve les identifiants et colonnes sources, ajoute prédictions/intervalles sans collision, contrôle cardinalité et valeurs finies, et limite le journal à 64 exemples. Toute erreur échoue le lot ; aucune ligne n’est exclue silencieusement.

La recette haute réelle du 13 octobre a traversé ingestion, préparation et scoring avec **3 000 000 de lignes synthétiques variées**, 32 colonnes d’entrée puis 35 de sortie et 6 parts Delta à chaque phase : **271,26 s**, zéro ligne exclue, pic RSS observable **3,25 GiB**. Un superviseur RSS avait un seuil de 4 GiB. Cela ne qualifie ni un cgroup 4 GiB, ni un quota 2 CPU, ni S3, ni la qualité métier du modèle. Le [runbook Showcase](ops/dataops-showcase.md) décrit la mesure et ses limites.

Un autre test passe par le vrai SystemVersion publié, l’ingress/outbox, le DAG, la préparation et le modèle natif sur 5 000 lignes. Une nouvelle source gouvernée arrive après publication, avec une colonne supplémentaire : la fenêtre choisit et fige cette version, le Flow conserve la colonne et les identifiants, les prédictions concordent avec l’API native. Le test réconcilie ensuite la fenêtre, persiste une revue humaine, publie le reçu idempotent et vérifie les octets téléchargés.

### Juge typé et approbation

`evaluate_v2` pose les questions `boolean`, `choice`, `multi_choice`, `score`, `probability`, avec critères et preuves. Les réponses distinguent `answered`, `abstained`, `invalid`. Les citations textuelles sont vérifiées par offsets/extrait ; les images demandent les octets autorisés, un transport qualifié et une citation par hash/zone/description. La route vient du Model Plane gouverné, jamais de champs privés fournis par le payload.

La qualité, une probabilité demandée et la confiance sont distinctes. Sans corpus qualifié concordant avec rubrique/modèle/source/langue/tâche, `confidence = null`. La calibration demande deux annotateurs humains distincts, adjudication par un troisième si nécessaire, séparation par famille, premier essai enregistré et test indépendant verrouillé. Elle mesure précision, rappel, défauts critiques manqués, couverture et métriques probabilistes applicables. J2450 vise les erreurs de traduction ; il n’est pas un score général de narration.

Le moteur de service applique le seuil d’approbation : une confiance inconnue ne peut déclencher une publication automatique. Work vérifie `expected_fence`, le digest du candidat et le digest de qualification, puis la complétude technique, la politique et le budget. Revue et reçu sont liés à ce résultat exact. Voir [le plan du juge](agentium-typed-judge-plan.md) et [le protocole de qualification](ops/typed-judge-qualification.md). Le raccordement Gemini via OpenRouter est différé ; les tests de transport ne constituent pas une qualification du fournisseur réel.

## 3. Carte de l’implémentation après restructuration

Les chemins ci-dessous sont relatifs au dépôt ; ils remplacent les anciens renvois au fichier monolithique des wrappers.

| Domaine | Fichiers de référence |
|---|---|
| Contrats DataOps | `backend/app/schemas/data_prep.py`, `backend/app/services/dataops/compiler.py`, `operations.py`, `steps.py` |
| Runner et cycle de vie | `backend/app/resources/dataops_runner.py`, `backend/app/services/dataops/sql_execution.py`, `preparation.py`, `watchdog.py`, `backend/app/workers/tasks.py` |
| Aperçu, stockage et scoring | `backend/app/services/dataops/preview.py`, `storage.py`, `ingestion.py`, `scoring.py`, `backend/app/services/tabular_datasets.py` |
| API DataOps | `backend/app/api/v1/endpoints/dataops.py` : catalog, compile, preview, executions, cancel, validate-expression, hash-salts |
| Flow et Skills | `backend/app/services/run_engine/dag.py`, `execution_contract.py`, `backend/app/services/skills_registry/wrappers/skills.py`, `wrappers/registry.py`, `skills_registry/seed.py`, `skill_effects.py` |
| Actifs et promesses | `backend/app/models/service_contract.py`, `backend/app/schemas/service_contract.py`, `backend/app/services/governed_assets.py`, `service_promises.py`, `service_engine.py`, `window_budget.py`, `backend/alembic/versions/126_service_contracts.py` |
| API Work | `backend/app/api/v1/endpoints/service_contracts.py` : assets/sources, contracts, windows/candidate/objects, review, publication, receipts/download, incidents |
| Juge et calibration | `backend/app/schemas/typed_evaluation.py`, `backend/app/services/evaluation/typed_judge.py`, `typed_calibration.py`, `backend/app/api/v1/endpoints/typed_calibration.py`, `backend/app/services/model_plane/execution.py` |
| Interface | `frontend-ng/src/app/features/data/`, `features/orchestration/flow/flow-dataops-inspector.component.ts`, `features/experience/work/service-delivery.*`, `features/runs/skill-invocation-view.component.ts` |
| Showcase et exploitation | `backend/scripts/seed_dataops_showcase.py`, `benchmark_dataops_showcase.py`, `dataops_watchdog.py`, `ops/helm/agentium/values-dataops-showcase.yaml`, `scripts/agentium-data-plane-dump.sh` |
| S0 | `backend/app/api/v1/endpoints/hana.py`, `backend/app/services/connectors/hana/service.py`, `network_policy.py`, [runbook HANA](ops/hana-security-s0.md) |

## 4. Activation et livraison vérifiable

Les options d’écriture et de service restent fermées par défaut. `dataops_enabled`, `dataops_write_delta_enabled`, `ml_score_streaming_enabled` et `service_contracts_enabled` sont des réglages serveur ; certaines options existent aussi sous `workspace.settings.features`. Un payload de Run ne les ouvre pas. `narration_enabled=false` conserve ce parcours hors lot, même si sa Skill existe en bêta.

1. Livrer les lecteurs, la migration 126 et les workers permanents selon le processus de release ; contrôler la révision de `build-info`.
2. Vérifier ObjectStore partagé, secrets dédiés, rétention et restauration sur le stockage cible. Conserver les limites mémoire/spill et la concurrence 1 du worker `dataops`.
3. Activer les features seulement pour Showcase, fournir ses vrais datasets/modèle/responsable et préparer les contrats avec le seed. Une source ou un modèle incomplet conserve le service en brouillon ; le seed ne crée aucun résultat ni approbation factice.
4. Installer le watchdog indépendant, publier le System et son contrat, provoquer une fenêtre absente/entrée périmée/worker perdu et contrôler l’incident attribué.
5. Exécuter les recettes scoring 2 M/3 M en environnement, comparer cardinalités/prédictions/ressources, inspecter les objets, réaliser la revue humaine et le reçu Work.
6. Conserver les rapports, la révision livrée et les preuves de restauration. Gemini/OpenRouter, narration, HANA réel et Kubernetes installé demandent leurs propres qualifications ; les tests locaux ne les remplacent pas.

Le Helm client fournit un worker permanent et le watchdog ; il n’implémente pas le calcul Kubernetes à la demande. Spark, autres profils de connecteurs et Iceberg attendent une demande et des volumes observés.

---

# Référence de conception détaillée antérieure

Les sections suivantes sont conservées pour les choix sémantiques et les extensions futures. Elles décrivent aussi des contrats proposés avant l’implémentation. En cas de différence avec le code, utiliser le §3 et les schémas versionnés actuels. Les tableaux de lots, déploiement et « reste à faire » de cette référence ne remplacent pas l’état du §0.

## 5. Contrat de spécification d'un nœud

### 5.1 Paramètres du nœud (`config.params`, projetés dans `_data_prep`)

`_DATA_PREP_PARAM_KEYS = ("spec", "sources", "outputs", "placement", "timeout_s")`. Tout paramètre du nœud doit y figurer (`dag.py:2469-2473`). Il n'y a pas de `output_name` séparé : `outputs[].name` fait foi.

```json
{
  "spec": {"version": 1, "operation": "prepare", "params": {"steps": []}},
  "sources": [{"port": "in", "dataset_id": "…"}],
  "outputs": [{"port": "out", "name": "Clients préparés"}],
  "placement": "auto",
  "timeout_s": null
}
```

- **`sources`** : épingles optionnelles par port. La sémantique est **celle d'aujourd'hui** (`tabular_datasets.py:1131-1179`) : `dataset_id` désigne une version exacte, `dataset_slug` la dernière version `ready`. Un port épinglé ignore son arête amont.
- **`outputs`** : un par port de sortie, `out` sauf pour `split`. `name` est obligatoire et son slug est unique dans le nœud (`DATAPREP_OUTPUT_NAME_DUPLICATE`, comparaison sur `slugify(name)`).
- **`placement`** : `auto`, `local`, `pod` ou `spark`. Il est soumis à la politique du workspace.
- **`spec.version`** : un entier, avec migrations à la lecture (`spec.migrate`). Une version inconnue donne `DATAPREP_SPEC_VERSION`.
- **`inputs_map`** est **refusé** sur un nœud data_prep (validateur). Les entrées passent seulement par les ports et les épingles.

### 5.2 Ports persistés par opération (D-12)

| Opération | `node.inputs` | `node.outputs` |
|---|---|---|
| prepare, aggregate, unpivot, sample | `in` | `out` |
| join | `left`, `right` | `out` |
| union | `in_1` … `in_n` (2 à 16, ajout et retrait dans l'atelier) | `out` |
| split | `in` | Un port par sortie (2 à 8), nommé par l'auteur, slug `[a-z][a-z0-9_]{0,30}` |

**Règles de validation**
- Une arête vers join, union ou split doit porter `to_port`.
- Une arête depuis un split doit porter `from_port`.
- Un port d'entrée requis non câblé et non épinglé est refusé (`DATAPREP_PORT_MISSING`).
- Deux arêtes vers le même port sont refusées.

Le `output_schema` de la Skill se réduit à **une seule propriété `out`**. Les autres ports sont posés par la palette selon l'opération (§17).

### 5.3 Sous-schémas communs

**Référence de colonne** : un nom exact, casse comprise. Une colonne absente donne `DATAPREP_COLUMN_MISSING`, avec l'identifiant de l'étape.

**Sélecteur de colonnes**, résolu à la compilation :

| `mode` | Champs | Ordre | papAI |
|---|---|---|---|
| `names` | `names[]` | Celui de la liste | SINGLE / MULTIPLE (noms absents ignorés chez papAI, refusés ici) |
| `pattern` | `regex` (RE2), `match: full\|contains` (défaut `full`) | Celui du schéma | PATTERN, correspondance complète en Java (le front papAI testait une sous-chaîne) |
| `kinds` | `kinds[]` (`integer`, `decimal`, `text`, `boolean`, `date`, `datetime`, `other`) | Celui du schéma | Nouveau |
| `all` | — | Celui du schéma | ALL |

S'y ajoute `exclude[]`. Une sélection vide donne `DATAPREP_EMPTY_SELECTION`.

**Littéraux** : JSON typé, converti par `CAST` vers le type cible. Une conversion impossible donne `DATAPREP_LITERAL_TYPE`.

**Nouvelle colonne**
- `output` et `position: after_input|end` ;
- `replace: false` (défaut) : refus si le nom existe déjà (`DATAPREP_COLUMN_EXISTS`).

**Champs communs d'une étape**
- `id` : UUID stable, qui sert aux erreurs, à l'aperçu par étape et à l'annulation ;
- `kind` ;
- `enabled` ;
- `comment` (≤ 500 caractères).

**Ordre de départage** (D-14) : le compilateur ajoute `__row_fp` (empreinte canonique de la ligne, §8.4) en dernier critère de **tout** `ORDER BY` qui choisit des lignes : ffill/bfill, first/last, dédoublonnage, `row_number`, split par ordre, sample `first`.

**Limites** :

| Réglage | Défaut |
|---|---|
| `dataops_max_steps` | 200 |
| Taille de la spec | 256 Ko |
| `dataops_max_union_inputs` | 16 |
| Sorties de split | 8 au plus |
| `dataops_max_pivot_values` | 200 |
| Longueur d'une formule | 4 000 caractères |
| Profondeur d'une formule | 64 |

---

## 6. Catalogue exhaustif

**Conventions**
- Une valeur nulle en entrée donne une valeur nulle en sortie, sauf mention contraire.
- Les comparaisons suivent la logique SQL à trois valeurs.
- La compilation produit du SQL **portable**. Les fonctions propres à un dialecte passent par le shim (§8.3).
- Sur Spark (ANSI activé), toute conversion, division ou opération pouvant échouer passe par `try_*`.

### 6.1 Opérations (nœuds)

| Opération | Paramètres | Sémantique et compilation | Écart avec papAI |
|---|---|---|---|
| **prepare** | `steps[]` (§6.2) | Une CTE par étape active, schéma connu après chaque étape | `CleaningStmt` |
| **join** | `how`, `on[]`, `null_equal`, `select`, `suffix`, `merge_keys` | Détaillé sous ce tableau | `EQ` null-safe par défaut chez papAI, `NATURAL` à égalité standard, ordre du DataFrame, suffixes `_1`, ni semi ni anti |
| **union** | `mode`, `allow_missing`, `bindings[]`, `distinct` | Détaillé sous ce tableau | papAI : `unionByName`, liaisons limitées à 2 entrées |
| **aggregate** | `group_by[]`, `aggregations[]`, `pivot?` | Détaillé sous ce tableau | papAI : pivot sur plusieurs colonnes concaténées par `_` (collisions de nulls), jusqu'à 10 000 valeurs dynamiques, `first`/`last` non déterministes. **Pivot sur une seule colonne en v1** (écart documenté) |
| **unpivot** | `id_columns`, `value_columns`, `name_column` (`variable`), `value_column` (`value`), `drop_nulls` | `UNION ALL` des projections. Supertype commun, sinon `DATAPREP_UNPIVOT_TYPES` | Absent de papAI |
| **split** | `method`, `outputs[]`, `seed`, `key`, `stratify_by`, `order_by`, `else_port` | Détaillé sous ce tableau | papAI : pas de seed, poids non vérifiés, « random » en blocs contigus |
| **sample** | `method`, `n` ou `fraction`, `seed`, `order_by`, `stratify_by` | Détaillé sous ce tableau | papAI : `orderBy(rand())` non seedé, mode `Last` |

**join en détail**
- **Types** (`how`) : `inner`, `left`, `right`, `full`, `cross`, `semi`, `anti`.
- **Conditions** (`on[]`) : `{left, op: eq|ne|lt|le|gt|ge|contains|starts_with, right}`, combinées par ET.
  - Au moins une condition est exigée, sauf pour `cross`.
  - Sans aucune condition `eq`, l'avertissement `DATAPREP_JOIN_NO_EQUALITY` signale une boucle imbriquée coûteuse.
- **Clés nulles** : avec `null_equal: false`, égalité standard. Avec `true`, `IS NOT DISTINCT FROM`.
- **Colonnes** (`select.left` / `select.right`) : toutes par défaut. Ordre : gauche puis droite, selon la sélection.
- **Collisions** : `suffix.right` (défaut `_right`). Si un conflit subsiste, `DATAPREP_COLUMN_EXISTS`.
- **`merge_keys`** (défaut `false`) : remplace les paires de clés `eq` par une seule colonne `coalesce(l, r)`. Utile pour un `full`.
- **`semi` / `anti`** : `WHERE [NOT] EXISTS`.
- **Aide « mêmes noms »** : remplit `on[]` (elle remplace `NATURAL`).

**union en détail**
- **Modes** : `by_name` (défaut), `by_position` ou `bindings[{output, sources[]}]`.
- **`allow_missing`** (défaut `true`) : une colonne absente vaut `NULL`.
- **Schéma unifié** : calculé à la compilation par la table de supertypes (§7). Types incompatibles : `DATAPREP_UNION_TYPES`.
- **Compilation** : chaque entrée est projetée avec `CAST` et `NULL`, puis assemblée par `UNION ALL`. Pas de `UNION BY NAME`, absent de Spark SQL.
- **`distinct`** : un `DISTINCT` sur la sortie.

**aggregate en détail**
- **Agrégats** (`aggregations[{op, column, output, …}]`) :
  - `op` : `count_rows`, `count`, `count_distinct`, `sum`, `mean`, `min`, `max`, `std`, `std_pop`, `var`, `median`, `quantile(p)`, `mode`, `string_agg(sep, order_by)`, `first(order_by)`, `last(order_by)` ;
  - `mode` départage vers la plus petite valeur ;
  - `first` et `last` exigent `order_by` ;
  - pas de `any_value`, non déterministe.
- **Pivot** : `{column, values[] (figées), aggregations[], naming: "{value}"|"{value}_{op}_{column}", null_label: "(vide)", others: drop|column}`.
  - Compilé en agrégation conditionnelle `agg(CASE WHEN p = v THEN x END)`.
  - Les valeurs hors liste sont ignorées (`drop`) ou agrégées dans une colonne `others_label` (`column`).
- **Types de sortie** : chaque sortie d'agrégat reçoit un **`CAST` explicite** (§7), car `sum(int)` diffère entre DuckDB et Spark.

**split en détail**
- **Exactitude** : le rang est **entier**, `rn = row_number() OVER (PARTITION BY strate ORDER BY h, __row_fp)` avec `h = hash canonique(key ‖ seed)`, et `n = count(*)` de la partition. On affecte la sortie *i* si `floor(n·c_{i-1}) < rn ≤ floor(n·c_i)`, où `c` est la suite des ratios cumulés. C'est exact, à une ligne près par strate.
- **Méthodes** :
  - `random` : sans strate ;
  - `stratified` : partition sur `stratify_by` ;
  - `order` : l'ordre est `order_by, __row_fp` au lieu de `h` ;
  - `condition` : les `outputs[{port, filter}]` sont évalués dans l'ordre, la première vraie gagne. **`else_port` est obligatoire** : il reçoit toutes les lignes qui ne satisfont aucune condition.
- **Garanties** : les sorties sont disjointes et complètes. La somme des ratios doit valoir 1 ± 1e-9, sinon `DATAPREP_SPLIT_RATIOS`.
- **Exécution** : une passe, routée par `__dp_output` (§10.2).
- **Sur Spark** : deux passes. D'abord un histogramme de 65 536 seaux de hachage par strate, puis des seuils exacts, avec départage par `row_number` dans le seul seau frontière. On évite ainsi un tri global (D-20).

**sample en détail**
- **`first`** : `n` lignes selon `order_by` (obligatoire) puis `__row_fp`.
- **`random`** : tri sur `h` puis `LIMIT n`. Avec `fraction`, **compte exact** `round(N·f)`.
- **`stratified`** : `n` ou `fraction` par strate, même principe que le split.

**Absents, et remplacés**
- `SplitColumnStmt` → deux nœuds Préparer avec `select_columns`.
- `SqlRecipeStmt` → nœud dbt.
- `SqlExtensionStmt` → nœud SQL, sans paramètres.
- « Convertir en nœud SQL » sur tout nœud data_prep, avec les exceptions de §20.
- Les `extra_datasets` d'un nœud dbt ne sont **pas routables** vers des ports en v1 : seul le dataset principal entre.

### 6.2 Étapes de l'opération Préparer

Types refusés : `DATAPREP_TYPE_MISMATCH`, avec l'identifiant de l'étape.

**Colonnes**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `select_columns` | `columns` | Garde, dans l'ordre de la sélection | Projection | Inverse de DropColumns, SplitColumn |
| `drop_columns` | `columns` | Retire. Une colonne absente est une erreur | Projection du complément | DropColumns (absentes ignorées) |
| `rename_columns` | `mapping[{from,to}]` | Exact, collisions refusées, **aucun assainissement global** | `AS` | ColumnRename (assainit tout) |
| `move_columns` | `columns`, `position: start\|end\|before\|after`, `anchor?` | Bloc, dans l'ordre de la sélection, ancre exclue | Projection | MoveColumns (avant/après cassé) |
| `copy_column` | `column`, `output`, `position` | — | `AS` | CopyColumn |
| `concat_columns` | `columns`, `separator`, `output`, `nulls: skip\|propagate\|empty` (défaut `skip`) | Concatène en texte | `concat_ws` / `concat` / `coalesce` | ConcatenateColumns (`concat_ws`) |
| `normalize_column_names` | `style: snake\|lower\|ascii\|papai`, `dedupe: suffix\|fail` | `papai` reproduit `[$ ,;{}()\n\t=]` → `_`, un `_` devant un chiffre initial, puis `_k` | Alias | Assainissement implicite rendu explicite |
| `add_column` | `output`, `value`, `type` | Constante | `CAST(lit)` | — |

**Typage**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `cast` | `columns`, `to`, `on_error`, `float_to_int` | Détaillé sous ce tableau | Détaillée sous ce tableau | ColumnTypeCast : `decimal(38,19)`, HALF_UP, numérique → date en secondes epoch |
| `parse_date` | `column`, `format` (strftime) ou `preset`, `to: date\|timestamp\|timestamp_tz\|auto`, `output?` | Une valeur non analysable donne NULL, et l'aperçu compte les échecs. Presets ci-dessous | `try_strptime` / `try_to_timestamp(col, java)` | ParseDate (LEGACY : `SSSSSS` lu comme millisecondes, `[ ]` non géré) |
| `format_date` | `column`, `format`, `output` | — | `strftime` / `date_format` | — |
| `from_epoch` | `column`, `unit: s\|ms\|us`, `output` | Horodatage UTC | Shim | Implicite dans `castB` |
| `parse_number` | `column`, `decimal_separator`, `thousands_separator?`, `output?` | Gère la virgule décimale | `try_cast(replace())` | Sens `decimal_comma` |
| `to_boolean` | `columns`, `true_values[]`, `false_values[]`, `case_sensitive` | Les valeurs hors listes donnent NULL. Défauts : true, t, yes, y, 1, oui / false, f, no, n, 0, non | `CASE` | Partie de NegateBoolean |

`cast` en détail :
- **Cibles** (`to`) : `integer`, `bigint`, `double`, `decimal(p,s)`, `text`, `boolean`, `date`, `timestamp`, `timestamp_tz`.
- **`on_error: null|fail`** : avec `null`, une conversion impossible donne NULL et l'aperçu compte les échecs ; avec `fail`, le nœud échoue (`DATAPREP_CAST_FAILED`).
- **`float_to_int: round_half_up|truncate`** (défaut `round_half_up`) : le décimal vers l'entier est arrondi explicitement. Depuis du texte, on passe par `try_cast(x AS DOUBLE)`, puis l'arrondi, puis l'entier.
- **Compilation** : `TRY_CAST` (DuckDB), `try_cast` (Spark).

Presets de `parse_date` : `iso_date` (`%Y-%m-%d`), `iso_datetime` (`%Y-%m-%dT%H:%M:%S`), `iso_datetime_tz`, `fr_date` (`%d/%m/%Y`), `fr_datetime` (`%d/%m/%Y %H:%M:%S`), `us_date` (`%m/%d/%Y`), `compact` (`%Y%m%d`), `rfc2822`.

**Valeurs manquantes**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `drop_nulls` | `columns`, `how: any\|all`, `nan_as_null` (défaut `true`) | — | `WHERE` | DropNull (« any » + NaN) |
| `fill_nulls` | `columns`, `method`, `value?`, `order_by?`, `partition_by?` | Détaillé sous ce tableau | Détaillée sous ce tableau | FillNull |

`fill_nulls` en détail :
- **Méthodes** : `constant`, `mean`, `median`, `min`, `max`, `mode`, `ffill`, `bfill`.
- **`ffill`** prend la valeur **précédente** non nulle, **`bfill`** la **suivante**, comme pandas. Les deux exigent `order_by`, complété par `__row_fp`.
- **Statistiques** : par `CROSS JOIN` sur l'agrégat (par partition : jointure sur `partition_by`), d'après D-20.
- **Colonne entière** : la statistique est arrondie selon la règle de `cast`.
- **Constante non convertible** : refusée.
- **Compilation** :
  - `ffill` : `last_value(x IGNORE NULLS) OVER (PARTITION BY p ORDER BY o, __row_fp ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` ;
  - `bfill` : symétrique (`first_value … CURRENT ROW AND UNBOUNDED FOLLOWING`) ;
  - syntaxe `IGNORE NULLS` adaptée par le shim pour Spark.
- **Écarts avec papAI** : ffill et bfill inversés, ni ordre ni partition, méthode `random` non seedée, moyenne tronquée, constante ignorée en silence.

**Doublons**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `deduplicate` | `columns` (défaut : toutes), `keep: first\|last\|smallest_fp` (défaut `smallest_fp`), `order_by` (pour `first` / `last`) | Déterministe | Sous-requête `row_number() … = 1` (pas de `QUALIFY`) | DropDuplicates non déterministe |

**Filtres**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `filter_rows` | `conditions[{column, op, value?, values?, case_sensitive, normalize_accents}]`, `combine: and\|or`, `keep_nulls_on_ne` | Détaillé sous ce tableau | `WHERE` | FilterRows (NEQ garde les NULL) |
| `filter_range` | `column`, `min?`, `max?`, `min_inclusive`, `max_inclusive` (défaut `true`) | Nombre ou date. NULL exclu. Bornes typées, refus à la compilation si invalides | Comparaisons | FilterNumericalRange et FilterDatetimeRange (borne invalide = tout filtré chez papAI) |
| `filter_expression` | `expression` | Filtre avancé. Les `col_*` sont calculés dans une CTE précédente | `WHERE` | — |
| `flag_rows` | `output`, `conditions…`, `combine`, `flag_when: match\|no_match` | Booléen **jamais NULL** : `coalesce(condition, false)`, puis négation si `no_match`. `is_null` reste vrai sur les NULL | `CASE` | FlagRowsOnValue (« exclude » coché par défaut) |

`filter_rows` en détail :
- **Opérateurs** : `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `between`, `in`, `not_in`, `is_null`, `is_not_null`, `contains`, `starts_with`, `ends_with`, `matches` (RE2), `is_true`, `is_false`.
- **NULL** : une comparaison avec NULL est fausse, donc `ne` exclut les NULL, sauf avec `keep_nulls_on_ne`.
- **Texte** : `lower()` pour l'insensibilité à la casse, `remove_accents` (shim, §8.3) des deux côtés, **motif compris**.

**Texte**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `text_transform` | `columns`, `operation: trim\|ltrim\|rtrim\|lower\|upper\|title\|remove_accents\|collapse_spaces` | En place | Shim | Modes de normalisation |
| `replace_values` | `columns`, `pairs[{from,to}]`, `match: exact\|substring\|regex`, `case_sensitive`, `normalize_accents` | Détaillé sous ce tableau | `CASE` / `replace` / `regexp_replace` | ReplaceValues (paires enchaînées) |
| `split_column` | `column`, `separator` ou `regex`, `outputs[]`, `remainder: last\|drop` | Partie *i* dans `outputs[i]` ; avec `last`, le reste dans la dernière sortie. **Partie absente → NULL**, via `CASE` sur le nombre de parties (`split_part` rendrait `''`) | Shim | SplitParser |
| `extract_regex` | `column`, `pattern` (RE2), `outputs[{group, name}]` | **Sans correspondance → NULL**, via `CASE WHEN regexp_matches(…)` (`regexp_extract` rendrait `''`). Plus de sorties que de groupes : refus | Shim | RegexParser (`''`) |
| `count_occurrences` | `column`, `pattern` (non vide), `match: substring\|regex`, `case_sensitive`, `output` | NULL → NULL (papAI rendait -2). Motif vide refusé. Motif normalisé comme la colonne | Arithmétique sur `length` ; regex : `length(regexp_extract_all)` (shim) | CountOccurrences |
| `substring` | `column`, `start` (base 1), `length?`, `output?` | — | `substr` | — |
| `pad` | `column`, `length`, `char`, `side`, `output?` | — | `lpad` / `rpad` | — |
| `length` | `column`, `output` | Nombre de caractères | `length` | — |

`replace_values` en détail :
- Avec `exact`, la correspondance est **simultanée** : la première paire qui correspond gagne.
- Avec `substring` et `regex`, les paires s'appliquent dans l'ordre. Le remplacement regex utilise `\1` (traduit en `$1` pour Spark).
- Un `to` non convertible vers le type de la colonne est refusé.

**Dates**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `extract_date_parts` | `column`, `parts[]`, `naming` (défaut `{column}_{part}`) | `parts` : `year`, `quarter`, `month`, `iso_week`, `day`, `iso_day_of_week` (1 = lundi), `day_of_year`, `hour`, `minute`, `second`, `epoch_seconds`. Collisions de noms contrôlées | Shim | DatetimeExtraction (1 = dimanche, noms non contrôlés) |
| `date_diff` | `start`, `end`, `unit`, `output` | **Unités complètes écoulées**, pas un comptage de frontières | DuckDB `date_sub` / Spark `timestampdiff` (shim) | — |
| `date_add` | `column`, `amount`, `unit`, `output?` | — | Shim | — |
| `truncate_date` | `column`, `unit`, `output?` | — | `date_trunc` | — |
| `convert_timezone` | `column`, `from`, `to`, `output?` | — | Shim | — |

**Nombres**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `round` | `columns`, `decimals`, `mode: half_up\|half_even\|floor\|ceil\|truncate` | Mode explicite | Shim | RoundColumn |
| `bin` | `column`, `mode`, `labels?`, `output` | Détaillé sous ce tableau | `CASE` | Discretize (max mal placé sans `useMaximumValue`) |
| `scale` | `columns`, `method: zscore\|minmax\|robust`, `output_suffix?` | Statistiques par `CROSS JOIN`. Un écart nul donne NULL | Agrégats et jointure | Partie de l'Anonymization de papAI |
| `negate_boolean` | `columns` | Booléen seulement (passer d'abord par `to_boolean`) | `NOT` | NegateBoolean (convertissait le texte et les nombres) |
| `math` | `columns`, `function` (`abs`, `sqrt`, `ln`, `log10`, `exp`, `sign`, `ceil`, `floor`) | — | Fonctions (`try_*` sur Spark) | Fonctions de formule |

`bin` en détail :
- **Modes** : `fixed_width{width, min?, max?}`, `edges{edges[]}` ou `quantiles{n}`.
  - Les quantiles sont des bornes calculées par agrégat puis jointure.
  - Les bornes `min` et `max` absentes sont calculées sur la donnée.
- **Intervalles** : fermés à gauche, ouverts à droite, avec les débordements `< min` et `>= max`.
- **Libellés** : générés (`[0 ; 5[`) ou fournis. La sortie est du texte.

**Calcul**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `formula` | `output`, `expression`, `position` | Expression typée (§6.3). Le type de sortie est normalisé par un `CAST` explicite | Expression | FormulaEdition (tout en double) |
| `conditional_column` | `output`, `cases[{when, then}]`, `else` | Le premier cas vrai gagne | `CASE` | — |
| `map_values` | `column`, `pairs[{from,to}]`, `default: keep\|null\|value`, `output?` | Correspondance. Accepte NULL et nombres comme clés | `CASE` (`IS NOT DISTINCT FROM`) | ReplaceValues exact |

**Fenêtres**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `window` | `output`, `function`, `column?`, `partition_by[]`, `order_by[]` (exigé sauf pour `count`/`sum` sans ordre), `offset?`, `size?` | `function` : `row_number`, `rank`, `dense_rank`, `percent_rank`, `lag`, `lead`, `cumulative_sum`, `cumulative_count`, `cumulative_mean`, `moving_mean(size)`, `moving_sum(size)`, `first_value`, `last_value`, `ntile(n)`. Départage par `__row_fp`. Une fenêtre **sans partition** est refusée sur T2 (`DATAOPS_GLOBAL_WINDOW_ON_SPARK`) | `OVER (…)` | Absent |

**Confidentialité**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `hash` | `columns`, `salt: workspace\|none` (défaut `workspace`), `output: replace\|suffix` | Détaillé sous ce tableau | `sha256` / `sha2(…,256)` | Anonymization : SHA-512 sans sel |
| `mask` | `columns`, `keep_first`, `keep_last`, `char` | — | `substr` + `repeat` | — |

`hash` en détail :
- Résultat : `sha256(sel ‖ texte canonique)` (§8.4), en hexadécimal.
- **Le sel ne figure jamais dans le SQL** (revue C4) :
  - il est passé comme **paramètre lié** (manifeste `params`, `$salt` dans DuckDB, `args` dans Spark) ;
  - il est masqué dans `compile`, dans la filiation et dans `RecipeExecution.input_json` ;
  - il est dérivé du registre de secrets et **versionné** (`salt_version` dans la spec) ;
  - **l'éjection vers SQL est refusée** pour une étape `hash` salée.

**Ordre**

| Étape | Paramètres | Sémantique | Compilation | papAI |
|---|---|---|---|---|
| `sort` | `keys[{column, direction, nulls: first\|last}]` | Ordre **de la sortie**. Placée ailleurs qu'en dernière étape, elle produit l'avertissement `DATAPREP_SORT_NOT_LAST` | `ORDER BY` final, plus `__row_fp` | OrderBy (absentes ignorées) |

**Hors v1** (renvoyé à D6) : étapes tableaux et maps, aplatissement JSON (`J_*`), types sémantiques.

### 6.3 Langage de formules

**Syntaxe** : une expression SQL en dialecte DuckDB, analysée par `sqlglot.parse_one`.
- Colonnes nues ou entre guillemets doubles, textes entre guillemets simples.
- Arbre autorisé :
  - colonnes, littéraux et parenthèses ;
  - `+ - * / %`, ainsi que `^`, réécrit en `power` ;
  - comparaisons, `AND`, `OR`, `NOT`, `IS [NOT] NULL` ;
  - `IN` sur une liste littérale, `BETWEEN`, `LIKE` / `ILIKE` ;
  - `CASE`, `CAST` / `TRY_CAST` vers les types autorisés ;
  - les fonctions **du catalogue**.

**Refusé** (`DATAPREP_FORMULA_FORBIDDEN`, avec la position) : sous-requête, table, `*`, fonction hors catalogue ou non déterministe, fenêtre libre.

**Catalogue** (`functions.py`). Chaque fonction porte son nom, son arité, ses types, sa règle de retour, son rendu DuckDB et Spark et sa clé i18n :

| Famille | Fonctions |
|---|---|
| Nombres | `abs`, `round`, `floor`, `ceil`, `trunc`, `sqrt`, `cbrt`, `power`, `exp`, `ln`, `log10`, `log2`, `sign`, `mod`, `greatest`, `least`, `pi` |
| Trigonométrie | `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2` |
| Texte | `lower`, `upper`, `trim`, `ltrim`, `rtrim`, `length`, `substr`, `left`, `right`, `replace`, `concat`, `concat_ws`, `lpad`, `rpad`, `strpos`, `starts_with`, `ends_with`, `contains`, `regexp_matches`, `regexp_extract` (NULL sans correspondance), `regexp_replace`, `split_part` (NULL hors limites), `remove_accents`, `initcap` |
| Dates | `date_trunc`, `date_part`, `date_diff` (unités complètes), `date_add`, `make_date`, `parse_date`, `format_date`, `year`, `month`, `day`, `hour`, `iso_week`, `iso_day_of_week` |
| Valeurs nulles | `coalesce`, `nullif`, `ifnull` |
| Conditions | `if(cond, a, b)`, réécrit en `CASE` |
| Types | `cast`, `try_cast` |
| Agrégats de colonne | `col_mean`, `col_sum`, `col_min`, `col_max`, `col_std`, `col_median`, `col_count`, compilés en **CTE d'agrégat jointe** (D-20), utilisables aussi dans `filter_expression` |

**Spark** : `/`, `%`, `+` et `*` sont rendus par `try_divide`, `try_mod`, `try_add` et `try_multiply` (ANSI).

**Typage** : `DESCRIBE` sur les vues vides typées (§7). Une erreur est renvoyée avec sa position (`DATAPREP_FORMULA_INVALID`).

---

## 7. Typage et schémas

- **Source unique des types : le pied de page Parquet** de chaque entrée, lu par pyarrow.
  - À la conception, on enregistre `schema.empty_table()` dans DuckDB. Le cache est indexé par `(dataset_id, version)` ; le pied de page est lu une fois et gardé en mémoire de processus.
  - À l'exécution, le runner enregistre le même dataset Arrow (`dataops_runner.py:113-117`).
  - **Les types sont donc identiques par construction** : catégoriels, horodatages en ns, etc. (revue I1).
  - `schema_json.dtype`, une chaîne polars, n'est pas utilisé pour typer.
- **Par étape** : `DESCRIBE` de la CTE `s_k` sur les vues vides donne le schéma exact sans lire de données. Le cache est indexé par l'empreinte jusqu'à *k* et les empreintes de schéma.
- **Normalisation des types de sortie** : chaque sortie d'agrégat, de formule, de `scale` et de `bin` reçoit un `CAST` explicite vers un type de la **table portable** ci-dessous. HUGEINT (`sum(int)`) devient `decimal(38,0)` ; les décimaux suivent des règles explicites de précision.
- **Supertypes** (union, dépivotage, `coalesce`) : la règle DuckDB, vérifiée paire par paire. Texte et nombre ensemble est refusé.
- **Table portable DuckDB → Spark** (T2). Tout autre type est refusé sur T2 (`DATAOPS_TYPE_UNSUPPORTED_ON_SPARK`), ou converti en texte par une étape explicite.

  | DuckDB | Spark |
  |---|---|
  | TINYINT, SMALLINT, INTEGER, BIGINT | tinyint, smallint, int, bigint |
  | UTINYINT, USMALLINT | smallint, int (élargis) |
  | UINTEGER, UBIGINT | bigint, decimal(20,0) |
  | HUGEINT | decimal(38,0) |
  | FLOAT, DOUBLE | float, double |
  | DECIMAL(p,s) | decimal(p,s) |
  | VARCHAR | string |
  | BOOLEAN | boolean |
  | DATE | date |
  | TIMESTAMP, TIMESTAMP_NS / MS / S | timestamp_ntz (µs ; ns tronqués avec avertissement) |
  | TIMESTAMPTZ | timestamp |
  | TIME | string |
  | INTERVAL | refusé |
  | BLOB | binary |
  | UUID | string |
  | ENUM | string |
  | LIST | array |
  | STRUCT | struct |

- **Égalité des schémas** : un test vérifie que T0 et T2 produisent le même schéma, une fois normalisé, sur tout le corpus golden.
- **Noms** : conservés, quotés, 255 caractères au plus. Doublons exacts et collisions de casse refusés (`DATAPREP_DUPLICATE_COLUMN`). Un dataset d'entrée concerné doit passer par `normalize_column_names`, ce que l'atelier propose.
- **Fuseau horaire** : `SET TimeZone='UTC'` sur toutes les connexions (runner, aperçu, typage). `spark.sql.session.timeZone=UTC`.

---

## 8. Compilation

### 8.1 Pipeline (`compile.py`)

1. Valider la spec (pydantic, `extra="forbid"`).
2. Lire les schémas d'entrée (pieds de page Parquet).
3. Pour chaque étape active :
   - valider ses paramètres (erreurs typées avec l'identifiant de l'étape) ;
   - émettre la CTE `"s<k>"` en arbre sqlglot ;
   - typer la CTE.
4. Normaliser les types de sortie et émettre la projection finale explicite.
5. Produire `CompiledPlan` :
   - `sql_duckdb` ;
   - `params` (sel, etc.) ;
   - `output_schema` et `step_schemas` ;
   - `warnings` ;
   - `fingerprint = sha256(spec canonique ‖ versions des entrées ‖ version du compilateur)`.

`sql_spark` n'est **ni produit ni testé avant D5**. D1 ne prépare que l'interface du shim.

### 8.2 Règles d'émission

- **Quoting** : identifiants quotés par sqlglot, littéraux typés par `CAST`, paramètres liés pour les secrets.
- **Formes portables uniquement** : pas de `QUALIFY`, `EXCLUDE`, `UNION BY NAME`, `PIVOT`, `USING SAMPLE` ni `OVER ()` global.
- **Ordre de sortie** : seul le `sort` final le garantit.
- **Exemple corrigé** : `prepare[cast(age: text → integer), fill_nulls(age, median), filter_rows(age ≥ 18)]`.

  ```sql
  WITH "s1" AS (SELECT "id", TRY_CAST(round(TRY_CAST("age" AS DOUBLE)) AS INTEGER) AS "age", "city" FROM "in"),
       "s2_stats" AS (SELECT median("age") AS "m_age" FROM "s1"),
       "s2" AS (SELECT "id", coalesce("age", TRY_CAST(round("m_age") AS INTEGER)) AS "age", "city"
                FROM "s1" CROSS JOIN "s2_stats"),
       "s3" AS (SELECT * FROM "s2" WHERE "age" >= CAST(18 AS INTEGER))
  SELECT "id", "age", "city" FROM "s3"
  ```

### 8.3 Shim de dialectes (`dialects.py`)

**Registre** `fonction neutre → {duckdb, spark}`, qui couvre :

| Domaine | DuckDB | Spark | Remarque |
|---|---|---|---|
| Formats de date | strftime | Motif Java | Table de conversion testée |
| `remove_accents` | **`translate()`** | **`translate()`** | Même table sur les deux moteurs, pour la parité. Pas de `strip_accents` d'un côté et de `normalize` de l'autre |
| Arrondis | Par mode | Par mode | — |
| `split_part` avec reste | Shim, NULL hors limites | Shim, NULL hors limites | — |
| Regex | `regexp_*` RE2 | `regexp_*` Java | Validation RE2 à la compilation (lookarounds et backreferences refusés), remplacements `\1` → `$1` |
| `sha256` | `sha256` | `sha2(…,256)` | — |
| Dates | `date_sub` (unités complètes), `date_add` | `timestampdiff`, intervalles | Fuseaux |
| `IGNORE NULLS` | Syntaxe DuckDB | `last_value(x, true)` | — |
| Conversions et arithmétique | `TRY_CAST` | `try_cast`, `try_to_timestamp`, `try_divide`, `try_mod`, `try_add`, `try_multiply` | — |

**Gate** : la suite golden tourne sur les deux moteurs (§22). Un écart se corrige dans le shim.

### 8.4 Empreinte canonique (hachage, split, départage)

**Spike S-D1-2.** Une forme texte canonique par type, identique sur DuckDB et Spark :

| Type | Forme canonique |
|---|---|
| Entiers | Décimal |
| Décimaux | Décimal plein avec l'échelle |
| Flottants | `printf('%.17g')`. Équivalence Java à vérifier ; à défaut, les flottants sont exclus des clés de hachage et l'auteur les convertit explicitement |
| Dates | `YYYY-MM-DD` |
| Horodatages | ISO en UTC à la microseconde |
| Booléens | `true` / `false` |
| NULL | `\N` |

Les valeurs sont jointes par `\x1f`. `__row_fp = md5(canonique(toutes les colonnes))`. Le format est épinglé par des tests golden.

---

## 9. Aperçu

- **Principe** : l'aperçu ne lit que des **échantillons persistés**, jamais un dataset complet dans l'API (revue I6).
- **Endpoint** `POST /dataops/preview`, sans état.
  - Requête : `{spec, inputs: [{port, dataset_id? | upstream?}], step_id?, limit ≤ 500}`.
  - Réponse : `{rows, schema, stats, step_schemas, counts, warnings, sample{rows, of_rows, version}, duration_ms}`.
- **Résolution des entrées, port par port** :
  1. l'épingle ;
  2. le dataset produit par le nœud amont au **dernier test** du brouillon, pour **le port choisi**. Le badge expose `outputs{port: dataset_id}` (§15) ;
  3. la **chaîne amont data_prep**, envoyée par le front (`upstream: {spec, inputs}` récursif, profondeur ≤ 10, taille ≤ 1 Mo), compilée en CTE ;
  4. sinon `DATAPREP_INPUT_UNAVAILABLE`, avec une indication.
- **Contrôles de sécurité** : chaque `dataset_id`, y compris ceux des chaînes amont, doit appartenir au workspace de l'appelant (`DATAPREP_INPUT_FORBIDDEN`). Les specs amont sont validées comme une spec normale.
- **Échantillon persisté** (dès D1b) : `…/<id>/sample.parquet`, 10 000 lignes, réservoir seedé.
  - Il est calculé **une fois par version** par une tâche `dataops` (`dataops_build_sample`), à la création de la version ou, pour un ancien dataset, à la première demande. La version passe par l'état `sample_pending` et l'aperçu affiche « échantillon en préparation ».
  - Les étapes globales (agrégats, fenêtres, dédoublonnage, proportions, quantiles) sont calculées **sur l'échantillon**, et l'interface l'indique.
- **Exécution** : **connexion DuckDB scellée** (accès externe coupé, système de fichiers local désactivé, configuration verrouillée), dans un **thread** du processus API (`run_in_threadpool`).
  - Budget : `dataops_preview_memory_mb` (512), 2 threads, `dataops_preview_timeout_s` (10 s, interruption).
  - Au plus `dataops_preview_concurrency` (2) aperçus simultanés par processus.
- **Cache** : LRU, clé `(empreinte jusqu'à k, versions d'échantillon)`, 60 s, 64 entrées.
- **`pivot-values`** : sur l'échantillon dans l'API. Sur le complet, c'est une tâche `dataops` asynchrone dont le front suit le résultat.
- **Aides par opération** : cardinalités de jointure (appariées et non appariées, facteur d'expansion), correspondance des colonnes d'une union, nombre de groupes, effectifs par sortie d'un split, échecs de conversion.

---

## 10. Exécution et placements

### 10.1 Chemin d'exécution

1. **Walker** : `_data_prep_port_inputs` remplit `_data_prep.inputs = {port: dataset_ref}` (§15).
2. **Wrapper** : compile, choisit le placement, puis **réserve les N versions de sortie**. La réservation est protégée par un verrou consultatif par slug et réessayée en cas de conflit d'unicité (revue I4).
3. **Soumission** : `RecipeExecution` (D1b) ou `compute_runs` (D4).
4. **Runner**, puis **commit atomique** des N sorties en **une transaction**. En cas d'échec, toutes les réservations passent en `failed`.
5. **Enveloppe** : `{**dataset_reference(out ou première sortie), "outputs": {port: dataset_reference}, "operation", "placement", "duration_ms"}`.

**Règle de propriété des slugs.** Une sortie ne peut pas créer une nouvelle version d'un slug appartenant à un dataset produit ailleurs (upload, autre nœud ou autre System) : `DATAPREP_OUTPUT_SLUG_TAKEN`. Seule exception, l'option explicite `outputs[].append_version_of`.

### 10.2 Runner v2 (manifeste, rétrocompatible avec D0)

```json
{"views": [{"name": "in", "paths": ["…/part-0.parquet", "…"]}], "aliases": {…},
 "sql": "…", "params": {"salt": "…"},
 "outputs": [{"port": "train", "dir": "…/out_train", "format": "delta"}, {"port": "test", "dir": "…/out_test", "format": "delta"}],
 "route_column": "__dp_output",
 "io": {"kind": "local"},
 "row_limit": …, "max_output_bytes": …, "part_max_bytes": 536870912,
 "duckdb": {"memory_mb": …, "threads": …, "temp_directory": …, "max_temp_mb": …, "timezone": "UTC"},
 "profile": {"preview_rows": 50, "histogram_bins": 12, "top_values": 6, "sample_rows": 10000, "seed": 42}}
```

- **Une passe** : chaque lot Arrow est réparti par `route_column` avec `pyarrow.compute.filter`, et la colonne est retirée à l'écriture.
- **Paramètres liés** : DuckDB `execute(sql, params)`.
- **Profil et échantillon** : calculés **par sortie** (D3).
- **Mort du parent** : sous Linux, le runner pose `prctl(PR_SET_PDEATHSIG, SIGKILL)`, sur le modèle de `ml_shadow_harness.py:19`. Il meurt donc avec le worker, ce qui rend sûr le « fail-closed » quand la ligne est retrouvée `running` (revue C3).
- **E/S** : en T0, le runner écrit sur disque local et **le worker téléverse** les parts. En T1/T2, le runner écrit directement en S3.
- **Codes de sortie** : 6 = route inconnue ; 7 = paramètre manquant.

### 10.3 Placement automatique (`placement.py`)

1. Estimer le volume : `octets des entrées × facteur`. Facteurs : prepare 1,5 ; join 3 ; aggregate 1 ; union 1 ; split 1 ; sample 0,2.
2. **T0** si l'estimation est au plus `dataops_local_max_bytes` (2 Gio).
3. Sinon **T1** si le calcul k8s est activé, disponible et autorisé, jusqu'à `dataops_pod_max_bytes` (200 Gio). Le profil S, M ou L dépend de l'estimation.
4. Sinon **T2** si Spark est activé.
5. **Sans niveau supérieur** (VM), **repli sur T0 avec spill** jusqu'au plafond dur `dataops_local_hard_max_bytes` (20 Gio), avec l'avertissement `DATAOPS_PLACEMENT_DEGRADED`. Ainsi un join d'environ 700 Mo n'est jamais refusé (revue I12).
6. Au-delà : `DATAOPS_PLACEMENT_UNAVAILABLE`, avec la raison.

Un placement forcé est soumis à la politique du workspace. Les opérations refusées sur T2 (fenêtre globale, type non portable) restent en T0/T1, avec leur raison.

### 10.4 Délais, attentes et redémarrages (revue C3)

| Couche | Règle |
|---|---|
| Délai du nœud | `timeout_s`, plafonné par `dataops_max_timeout_s` (dédié, défaut 3 600 s ; **distinct** de `recipe_execution_max_timeout_s` = 600). Défauts : T0 300 s, T1 1 800 s, T2 3 600 s |
| Runner T0 | Le worker `dataops` tient le message Celery pendant le run (`acks_late`). Le **`consumer_timeout` RabbitMQ** est réglé explicitement dans Compose et dans le chart, au moins égal à `dataops_max_timeout_s` T0 + 5 min. Un T0 ne dépasse jamais `dataops_t0_max_timeout_s` (900 s) |
| Lanceur T1/T2 (D4) | **Ne tient aucun message longtemps.** Une tâche courte crée l'objet, puis des **ticks courts par bail** (beat, toutes les 15 s) observent, renouvellent le bail et finalisent. Aucun `sleep` dans une tâche |
| Walker | Attend la ligne jusqu'à délai + lancement + 30 s, puis demande l'annulation |
| `timeout_ms` de la Skill | Indicatif : le moteur ne l'applique pas aujourd'hui. Il est aligné sur `dataops_max_timeout_s` |
| **Redémarrage de l'API pendant l'attente** | Le calcul continue et commite. Le Run passe en `lost` par la réconciliation existante. Une **relance réutilise les sorties** grâce à l'empreinte (§10.5) au lieu de recalculer. Plus tard : suspension et reprise du Run, comme un HITL (D6) |
| Redélivrance d'un T0 | Ligne trouvée `running` → `failed` (`sql_worker_lost_after_claim`). C'est sûr grâce à `PDEATHSIG` |

### 10.5 Idempotence et relances (revue I5)

- **Clé d'exécution** : `operational_job_id("dataops", run_id, node_id, fingerprint, attempt)`, où `attempt` vient du compteur de tentatives du nœud dans le walker (relance ou itération de boucle).
- **Réutilisation** : si une exécution réussie existe déjà pour `(run_id, node_id, fingerprint)` sur la même tentative logique, ses sorties sont réutilisées. Un échec donne une nouvelle tentative.
- La Skill est déclarée `retryable: true`, `idempotent: true` (réutilisation par empreinte).
- **Balayage** : une tâche beat passe en `failed` les versions réservées (`ingesting`) dont l'exécution est terminale depuis plus de 5 minutes.

---

## 11. Stockage (D3)

**Disposition** (D-21, détail en §29.3)
- **Ancienne forme**, inchangée : `…/datasets/<id>/data.parquet`.
- **Nouvelle forme** : une **table Delta Lake par version**, dans `…/datasets/<id>/delta/` :
  - fichiers Parquet ;
  - journal `_delta_log/00000000000000000000.json`, **unique commit (version 0)**, écrit en dernier par un écrivain unique.
- **Protocole minimal** (`minReaderVersion` 1, `minWriterVersion` 2, ni deletion vectors ni column mapping) : la table est lisible par tout lecteur Delta, et aussi comme simple liste de fichiers Parquet.
- **`storage_key`** désigne `data.parquet` ou le dossier `delta`. La forme se reconnaît au suffixe, sans migration.
- **Les lecteurs utilisent uniquement la liste des fichiers actifs du journal Delta**, jamais un listage du dossier, puisque des orphelins peuvent subsister.
- **Pas de `VACUUM`** : chaque table n'a qu'une version.

**Déploiement en deux temps** (revue I8) :
1. Release N : **les lecteurs** acceptent les deux formes.
2. Release N+1 : on active `dataops_write_delta_enabled`, qui fait écrire en Delta. Une image antérieure à D3 ne sait pas lire Delta : le retour arrière se fait en désactivant ce drapeau, et les versions déjà écrites en Delta restent lisibles par N.

**Helpers** (`tabular_datasets.py`) :
- `dataset_files(dataset) -> list[key]` : pour Delta, les fichiers actifs du journal (`DeltaTable.file_uris()`). Les lecteurs qui acceptent une liste de Parquet fonctionnent donc **sans connaître Delta** ;
- `materialize_dataset(dataset, dir) -> list[Path]` ;
- `dataset_digest(dataset)` : inchangé pour l'ancienne forme, ce qui garde les empreintes stockées ; pour Delta, `sha256` du commit 0, qui contient chemins, tailles et statistiques ;
- `open_dataset_arrow(dataset)` : pour Delta, `DeltaTable(uri, storage_options).to_pyarrow_dataset()`, scan paresseux local ou S3. DuckDB scellé l'enregistre **sans extension**.

**Lecteurs à adapter** (inventaire complet, revue I8)

| Lecteur | Changement |
|---|---|
| `materialize` → `materialize_dataset` | Les appelants reçoivent une liste |
| `read_frame`, `read_rows`, `read_page` | `pl.scan_parquet(liste)` |
| In-process SQL, aperçu et enrichissement (`tabular_transforms.py:398-405`) | Liste. L'épingle d'enrichissement passe par `dataset_digest` |
| `sql_execution.write_manifest` (`:154`) | `views[].paths` |
| ML : entraînement (`tabular_ml.py:2247` → `ml_train_harness.py:881`), clustering, prévision (`ml_forecast_harness.py:596`), foundation (`ml_foundation_harness.py:339`), comparaison (`ml_comparison.py:148,158`) | `data_path` devient un répertoire ou une liste |
| Scoring (`tabular_predict.py:1158`), prévision (`forecast_serving.py:797`, `forecast_monitoring.py:115-120`) | Helpers |
| Empreintes : `ml_retraining.py:337-342`, `llm_dataset_labeling.py:325-340`, `llm_label_review.py:54` | `dataset_digest` |
| Polars (`tabular_polars.py:341-356`, `polars_harness.py:81`) et dbt (`tabular_dbt.py:518-542`, `dbt_harness.py:103`) | Listes de fichiers |
| `work_datasets.read_projected_rows` (`:193-232`) | `open_dataset_arrow` |
| Dump (`scripts/agentium-data-plane-dump.sh:228-238`) et son test (`test_data_plane_dump.py:296`) | Dossier Delta complet : journal et fichiers actifs |

**Commit atomique**
1. Les N versions sont réservées (`ingesting`).
2. Le runner écrit une table Delta par sortie : fichiers, puis commit 0, avec un **put conditionnel** (`If-None-Match`, pris en charge par MinIO). L'option delta-rs exacte est fixée au spike S-D3-1.
3. La plateforme lit chaque commit et valide les lignes, le schéma et les statistiques.
4. Elle passe les N versions en `ready` **dans une transaction**.
5. En cas d'échec, toutes passent en `failed`. Les tables orphelines sont supprimées par le **job de purge existant** : rôle `tabular-purge` (`scripts/agentium_hf_storage_policies.py:94-112`), étendu à `datasets/*/delta/*`.

**Préalable MinIO** :
- **inventorier les appelants de suppression** (dont `notice_campaign_recovery.py:452`, un `delete_prefix` non protégé) ;
- les rediriger vers l'identité de purge ;
- aligner le chart (aujourd'hui `s3:DeleteObject`, `minio-init.yaml:87-94`) sur Compose (Get/Put + versioning).

**Profil calculé en flux par le runner.** Les agrégats DuckDB produisent la forme `stats_json` attendue :
- `nulls`, `null_ratio` ;
- `distinct` : exact, +1 s'il y a des NULL ;
- `min`, `max`, `mean`, `std` ;
- `histogram` : 12 intervalles de largeur égale ;
- `top_values` (6), `mean_length`, `preview` (50 lignes) ;
- **ajout des quartiles `q25`, `q50`, `q75`**, clés supplémentaires rétrocompatibles (parité avec le `SummaryVo` de papAI).

**Statistiques du journal Delta** : min, max et nombre de NULL par fichier. Elles servent à l'élagage dans l'aperçu et les filtres.

**L'algorithme du runner devient la référence.** Le test de parité avec `profile_frame` tolère les égalités de `hist` et de `value_counts`, et la version de polars est épinglée.

**Échantillon** : écrit au commit, pour chaque sortie.

**Limites avant D3** : les sorties de D1b passent par `register_parquet_file`, qui fait une lecture polars complète dans la mémoire du worker et applique le plafond de 5 M lignes (`tabular_datasets.py:910-919`). D3 supprime cette limite pour les sorties dataops. Le budget devient `dataops_max_output_mb` par placement.

**Téléchargement** : `GET /datasets/{id}/download?format=parquet|csv`, en flux, avec contrôle d'accès au workspace.

---

## 12. Pilotage du calcul (D4)

**Table `compute_runs`** (migration `NNN_compute_runs`, numéro à relire ; identifiant ≤ 32 caractères)

| Colonne | Rôle |
|---|---|
| `id` | `operational_job_id(…, attempt)` (§10.5) |
| `workspace_id`, `system_id`, `run_id`, `node_id`, `attempt` | Rattachement |
| `kind` | `sql_transform`, `data_prep`, `connector_read`, `connector_write` |
| `fingerprint` | Empreinte de compilation |
| `placement`, `profile` | Placement et ressources |
| `status`, `stage`, `progress` | État, étape, compteur |
| `lease_token`, `lease_expires_at`, `deadline_at`, `cancel_requested` | Pilotage |
| `k8s_namespace`, `k8s_kind`, `k8s_name`, `k8s_uid` | Objet piloté |
| `manifest_uri`, `logs_uri` | ObjectStore |
| `input_json`, `output_json`, `metrics_json` | Entrées, sortie, mesures |
| `cost_usd` | Coût |
| `error_code`, `error` | Erreur |
| `created_at`, `started_at`, `finished_at` | Horodatage |

**Machine à états** : `queued` → `admitted` → `launching` → `running` → `committing` → `succeeded`. Depuis n'importe quel état : `failed`, `cancelled`, `timed_out` ou `lost`, tous terminaux.

**Mécanique**
- **Bail et CAS** : sur le modèle de `ml_shadow._claim` et `run_shadow` (`ml_shadow.py:221-255`, `405-429`).
- **Admission** :
  - verrou consultatif par workspace avec comptage (`ml_shadow.py:169-193`) ;
  - verrou global (`huggingface/registry.admission_lock`, `:57-79`).
- **Ticks courts** (§10.4) :
  - `dataops_compute_tick` (15 s) : observe les objets, renouvelle les baux, finalise ;
  - `dataops_compute_reaper` (60 s) :
    - bail expiré → `lost` ;
    - échéance dépassée → suppression de l'objet, puis `timed_out` ;
    - objet sans ligne active (label) → supprimé ;
    - ligne sans objet → `lost`.
- **File de contrôle dédiée `dataops_control`**, consommée **seulement** par `agentium-worker-dataops`. Les ticks et le lanceur ne sont ainsi jamais affamés par un long T0, puisque le prefetch vaut 1 (revue I9).
- **Annulation** : drapeau, suppression de l'objet (Foreground), puis `cancelled`.
- **Logs** : la fin des logs (256 Ko) est archivée dans `…/compute/<id>/`.
- **Disponibilité** : heartbeat `ml_runtime_heartbeats` avec le runtime `dataops-k8s`, écrit après une SelfSubjectAccessReview (déjà permise par `system:basic-user`).
- **Bascule de D4**, avec double lecture pendant une release (revue) :
  - le SQL et data_prep passent à `compute_runs` ;
  - la tâche `agentium.dataops_sql_execute` et la lecture de `RecipeExecution` sont gardées une release, pour drainer les exécutions en vol ;
  - le walker utilise `_await_compute_run`.

**Quotas et politique**
- Stockés dans `Workspace.settings.dataops` (clé protégée, ajoutée au préservateur `auth.py:1195-1230`) :

  ```
  {allowed_placements, max_concurrent_runs, max_core_hours_per_day, max_profile, max_input_gb, max_timeout_s}
  ```

- Modifiés par `PUT /dataops/policy/{workspace_id}`, réservé à l'administrateur de la plateforme.
- Refus : `DATAOPS_QUOTA_EXCEEDED{quota, used, limit}`.

**Coût** (revue I13)
- Réglages `dataops_core_hour_usd` et `dataops_gb_hour_usd`. `cost_usd` est calculé sur les requêtes et la durée.
- **Nouveau canal de coût mesuré** : l'enveloppe de sortie porte `_cost_evidence{usd, basis}`. Le moteur l'applique à `SkillInvocation.cost` après l'exécution. Aujourd'hui le coût est résolu au tarif du catalogue, avant l'exécution (`engine.py:1068-1073`, `skill_invocation_snapshot.py:62`).
- Le Run agrège déjà les coûts (`engine.py:1410-1414`). Un test couvre ce canal.

---

## 13. Kubernetes (D4)

**Namespace** : `agentium-compute`, configurable.

**Workers** (revue I9)
- Avec `dataops.compute.enabled=true`, le chart crée un **Deployment `agentium-worker-dataops`** (queues `dataops,dataops_control`, ServiceAccount `agentium-compute-launcher`). Le worker principal **retire alors `dataops`** de ses files : `CELERY_QUEUES` est surchargé dans l'`env` du Deployment, pas dans la configmap partagée.
- Sans calcul activé, le worker unique consomme `cpu,recipes,dataops,dataops_control`.
- `check-k8s-scaffold.sh` couvre **les deux modes**.

**Rôles**
- `agentium-compute-launcher`, Role dans le namespace de calcul :
  - `batch/jobs` : create, get, list, watch, delete, patch ;
  - `pods` : get, list, watch, delete ;
  - `pods/log` : get ;
  - `events` : list ;
  - `secrets` : create, delete ;
  - `sparkapplications.spark.apache.org` (D5).
  - Pas de ClusterRole SSAR.
- `agentium-compute-runner` : `automountServiceAccountToken: false`.
- `agentium-spark-driver` (D5) : pods, services et configmaps dans le namespace. **C'est une exception documentée au principe « aucun jeton d'API »** : le driver Spark crée ses exécuteurs.

**Séquence de création d'un Job**
1. Créer le Job avec `suspend: true`.
2. Créer le Secret de l'exécution, avec ownerReference vers le Job.
3. Lever la suspension.

Ainsi aucun pod ne démarre sans son Secret, et le Secret disparaît avec le Job.

**Modèle de pod T1**
- Image du runner par digest.
- `securityContext` restreint (runAsNonRoot, readOnlyRootFilesystem, drop ALL, seccomp RuntimeDefault).
- Requêtes égales aux limites, selon le profil.
- `emptyDir` avec `sizeLimit` pour le spill.
- `nodeSelector` et `tolerations` du pool de calcul.
- Identifiants temporaires depuis le Secret.
- `activeDeadlineSeconds`, `ttlSecondsAfterFinished: 300`, `backoffLimit: 0`.
- Labels `agentium.io/compute-run` et `agentium.io/workspace-hash`.

**Profils** :

| Profil | CPU | Mémoire | Disque éphémère |
|---|---|---|---|
| S | 2 | 8 Gio | 50 Gio |
| M | 4 | 16 Gio | 100 Gio |
| L | 8 | 32 Gio | 200 Gio |

DuckDB reçoit 75 % de la mémoire.

**NetworkPolicy**
- Runner : en sortie, DNS + MinIO (+ CIDR de l'objet externe et des connexions déclarées, D7) ; en entrée, rien.
- Spark : en plus, trafic driver ↔ exécuteurs dans le namespace et **sortie du driver vers kube-apiserver**.

**ResourceQuota et LimitRange** : pilotés par les valeurs du chart.

**Pool de nœuds (Terraform)**
- OVH : second nodepool en autoscale, avec la teinte `agentium.io/compute=true:NoSchedule` et un label. Le minimum à 0 est à vérifier (S-D4-3) ; sinon 1 nœud, avec son coût documenté.
- AKS : `azurerm_kubernetes_cluster_node_pool` avec autoscaling, teintes et labels.

**Identifiants objet par exécution** (S-D4-2, revue I11)
- **Cible** : STS MinIO `AssumeRole` avec une session policy limitée :
  - `GetObject` sur les clés d'entrée ;
  - `ListBucket` avec une condition de préfixe ;
  - `PutObject` et les actions multipart sur le préfixe de staging ;
  - `DurationSeconds` ≥ délai + lancement.
- **Sans STS** : identité `compute` grossière (Get sur les datasets, Put sur `parts/` et `compute/`, Deny Delete). **T1 n'est alors disponible qu'en mono-tenant** (réglage `dataops_compute_single_tenant=true`), et marqué indisponible en multi-tenant. Les URL présignées ne remplacent pas STS : `S3FileSystem` ne sait pas les utiliser, et le nombre de parts n'est pas connu d'avance.

**Image `agentium-dataops-runner`**
- Sur le modèle de `Dockerfile.agentium-hub-fetch` : duckdb, pyarrow et `dataops_runner.py`, épinglés par les contraintes de l'application.
- Ajouts nécessaires :
  - `PYTHON_IGNORES` et `RUNTIME_READS` (`test_python_image_context.py`) ;
  - `IMAGE_CONTRACTS` (`test_image_provenance_contract.py`) ;
  - la boucle de `agentium-image-budget.sh:28` ;
  - le `KEYS` de `build-lab-images.sh:20-28,61-64` ;
  - la doc de release.

**Kubernetes ≥ 1.34 pour D5** : OVH est en 1.31, soit **trois montées de version successives** (runbook à écrire).

---

## 14. Spark (D5)

**Opérateur** : release Helm séparée gérée par le rôle Ansible `spark_operator` (chart 1.8.0, application 1.0.0, épinglée), qui ne surveille que `agentium-compute`. Notre chart vérifie la présence du CRD (`lookup`).

**SparkApplication** :

```yaml
apiVersion: spark.apache.org/v1
kind: SparkApplication
metadata: {name: dp-<id8>, namespace: agentium-compute, labels: {agentium.io/compute-run: <id>}}
spec:
  pyFiles: "local:///opt/agentium/spark_runner.py"   # forme exacte : spike S-D5-1
  runtimeVersions: {sparkVersion: "4.2.x"}
  sparkConf: {…, spark.kubernetes.container.image: <digest>,
              spark.kubernetes.authenticate.driver.serviceAccountName: agentium-spark-driver}
  driverSpec: {podTemplateSpec: {…}}
  executorSpec: {podTemplateSpec: {…}}
  applicationTolerations:
    restartConfig: {restartPolicy: Never}
    applicationTimeoutConfig: {driverStartTimeoutMillis: 300000, executorStartTimeoutMillis: 300000}
    instanceConfig: {initExecutors: N, minExecutors: 1, maxExecutors: N}
    resourceRetainPolicy: OnFailure
    ttlAfterStopMillis: 600000
```

**États de l'opérateur → `compute_runs`**

| États `currentStateSummary` | État `compute_runs` |
|---|---|
| `Submitted`, `ScheduledToRestart`, `DriverRequested`, `DriverStarted`, `DriverReady`, `InitializedBelowThresholdExecutors` | `launching` |
| `RunningHealthy`, `RunningWithBelowThresholdExecutors`, `RunningWithPartialCapacity` | `running` |
| `Succeeded` | `committing` |
| `Failed`, `DriverEvicted`, `SchedulingFailure`, `DriverStartTimedOut`, `ExecutorsStartTimedOut`, `DriverReadyTimedOut` | `failed`, avec un code par cause |
| `ResourceReleased`, `TerminatedWithoutReleaseResources` | Nettoyage confirmé, ou alerte |

**Un état inconnu est conservé et déclenche une alerte**, sans changer l'état. La liste exacte est vérifiée au spike S-D5-1.

**Runner** (`spark_runner.py`)
1. Lire le manifeste.
2. Lire les entrées avec `spark.read.parquet(liste de parts)` et les déclarer en vues.
3. Exécuter `spark.sql(sql_spark, args=params)`.
4. **Écrire en Delta, un chemin par sortie** : `df.write.format("delta").mode("errorifexists")`, dans le dossier `delta/` de chaque dataset réservé. Le DataFrame est filtré par `__dp_output` et mis en cache. Écrivain unique : le LogStore S3 par défaut suffit. L'image embarque **delta-spark 4.4** (prise en charge de Spark 4.2).
5. Écrire `result.json`.

Aucune UDF Python.

**Profil, échantillon et aperçu** : après le run Spark, un **passage de profilage DuckDB** (un Job T1 léger) lit les parts et produit le profil et l'échantillon, comme pour T0.

**Image `agentium-spark`** : `apache/spark` 4.2.x Python, épinglée par digest, plus `hadoop-aws` et le bundle AWS alignés sur la version Hadoop de l'image, et le runner. On ne remplace pas `jars/`.

**Configuration par défaut**
- AQE avec coalescence et `skewJoin`.
- Broadcast à 64 Mo.
- `dynamicAllocation` avec `shuffleTracking`.
- `maxPartitionBytes` à 128 Mo.
- `caseSensitive=false`, `session.timeZone=UTC`, `ansi.enabled=true`.
- S3A : endpoint, `path.style`, committer **magic**.
- Event log sur S3.
- `executor.deleteOnTermination`.
- UI non exposée.

**Dimensionnement**
- `exécuteurs = clamp(ceil(octets × facteur / (mémoire exécuteur × 0,6)), 1, profil.max)`.
- Driver de 2 Gio et 1 cœur, exécuteurs de 4 Gio et 2 cœurs.
- L'estimation et la mesure sont enregistrées pour calibrer le facteur.

**Parité** : suite golden sur Spark `local[2]` (marqueur `spark`, Java 17+, CI de nuit) et égalité des schémas avec T0.

**Spikes**
- S-D5-1 : forme PySpark exacte et liste complète des états.
- S-D5-2 : `translate` et formats de date.
- S-D5-3 : committer magic sur MinIO.
- S-D5-4 : temps de démarrage et coût d'un petit job (calibrage du seuil de T2).

---

## 15. Intégration Flow (D1b)

**Skill `data_prep_v1`** (`seed.py`)
- Catégorie `Data`, capacité `tabular_transforms` (`:3818-3840`).
- `execution.mode: sync`, `timeout_ms` aligné sur `dataops_max_timeout_s`, `retryable: true`, `idempotent: true`.
- `output_schema = {properties: {out: …}}`.
- Une ligne dans `_REGISTRY` (`services/skills_registry/wrappers/registry.py`) et dans `SKILL_CATEGORIES`.

**DAG** (`dag.py`)
- `_DATA_PREP_SKILL_SLUG`, `_DATA_PREP_PARAM_KEYS`.
- Le tuple `("_data_prep", …)` dans `_GRAPH_OWNED_BLOCKS` (`:2222-2235`).
- La docstring de `_passthrough_without_recipe` mise à jour.
- Le slug dans `GRAPH_OWNED_CONFIG_SKILLS` (`execution_contract.py:33-47`).

**Entrées par port** (revue C1)
- Nouvelle fonction `_data_prep_port_inputs(graph, state, node)`, appelée **après** la boucle `_GRAPH_OWNED_BLOCKS` (`dag.py:2489-2496`).
- Pour chaque arête entrante, elle lit la sortie amont (pool de variables) et sélectionne `outputs[from_port]` si l'amont expose `outputs`, sinon la référence du dataset amont. Elle écrit `node_input["_data_prep"]["inputs"][to_port]`.
- **Rien n'est écrit dans `merged_input` ni dans `state.ctx`.** `_passthrough_without_recipe` retire tout le bloc, et une valeur fournie par l'amont ou par l'appelant n'est jamais lue.
- **Pour toute cible (SQL, Polars, ML) dont l'amont est un split** : si l'arête porte `from_port`, la fusion à plat ne transmet que la branche. C'est appliqué dans `_merge_predecessor_outputs` pour les seuls amonts `data_prep_v1`, avec des tests de rétrocompatibilité.

**Badge et sorties** (revue I7) : `_node_data_badge` (`dag.py:4660-4709`) expose `outputs{port: {dataset_id, rows}}`. `_envelope_rows` lit `outputs` (aujourd'hui les clés en `_` sont ignorées, `:4634-4636`). Le front résout l'aperçu amont par `from_port`.

**Wrapper `_data_prep_v1`**
- `data_prep_config_missing` sans bloc ; workspace exigé ;
- entrées depuis `_data_prep.inputs` et les épingles ;
- compilation, réservation, soumission, suivi ;
- `ValueError("DATAPREP_…: …")` ;
- `_cost_evidence` (D4).

**Validation à la publication** : `data_prep_issues(flow)`, fonction pure appelée par `dag_validator.validate_flow`, comme `data_source_issues` (`dag_validator.py:859-871`). Elle vérifie :
- la spec ;
- les ports (§5.2) : arêtes nommées, ports requis ;
- le refus de `inputs_map` ;
- les noms de sortie (unicité des slugs) ;
- les limites ;
- et, pour D7, l'exigence d'un HITL avant export quand la politique le demande.

Code `data_prep_invalid`.

**Filiation**
- `lineage_json` : `engine`, `placement`, `operation`, `steps[{kind, id}]`, `spec_fingerprint`, `sources`, `runner`.
- Clés publiques ajoutées à `_PUBLIC_LINEAGE_KEYS` (`tabular_datasets.py:1007-1022`) : **`prep`** (opération et nombre d'étapes par kind) et **`placement`**.
- Le SQL reste privé ; le sel n'y figure jamais.

**Visibilité** : `feature_enabled(workspace, "data_prep")` (`workspace_features.py:116-125`) et le verdict de visibilité de `/skills` filtrent la palette, puisqu'un réglage global ne suffit pas à masquer des nœuds.

**Catalogue au déploiement** : `catalog-apply` n'existe que sur le chemin VM (`agentium-vm-deploy.sh:322-326`). Sur k8s : un **Job Helm post-upgrade** `python -m app.cli.reconcile_catalog --apply`, à ajouter en D1b (revue I14).

---

## 16. API

| Méthode | Route | Rôle | Droits |
|---|---|---|---|
| GET | `/dataops/catalog` | `feature{enabled, placements[]}`, opérations, étapes et champs (descripteurs avec **clés i18n**), fonctions, kinds, limites | Membre |
| POST | `/dataops/preview` | §9 | Membre, propriété des datasets vérifiée |
| POST | `/dataops/compile` | `{sql (DuckDB formaté, sel masqué), output_schema, step_schemas, warnings}` | Membre |
| POST | `/dataops/validate-expression` | `{type, errors[{message, line, column}]}` | Membre |
| POST | `/dataops/pivot-values` | Valeurs distinctes : échantillon en synchrone, complet en tâche asynchrone | Membre |
| GET | `/dataops/runs` (`?run_id&node_id`), `/dataops/runs/{id}` | `compute_runs` (D4) | Membre |
| POST | `/dataops/runs/{id}/cancel` | Annulation | Droits d'exécution du System |
| GET | `/dataops/runs/{id}/logs` | Logs archivés | Administrateur du workspace |
| PUT | `/dataops/policy/{workspace_id}` | Politique et quotas | Administrateur de la plateforme |
| GET | `/datasets/{id}/download` | Parquet ou CSV en flux (D3) | Membre |

**Libellés** : les descripteurs portent des clés i18n (`flow.dataprep.step.<kind>.*`) ; les textes FR/EN sont dans `flow.dict.ts`. Un test lit `flow.dict.ts` et vérifie que toutes les clés servies par le catalogue y existent.

Codes d'erreur en annexe B.

---

## 17. Interface (D2, Tokens v2)

**Palette**
- Nouvelle fonction **`skillToPaletteItems`**, à côté de `skillToPaletteItem` (`flow.types.ts:546`). Elle déploie `data_prep_v1` en 7 éléments, de clé composite `data_prep_v1#<operation>`.
- Ports posés à la dépose selon §5.2.
- Clés à adapter : `flow-palette.vm.ts:66-70`, `flow-builder.component.ts:523`, le `@for track` et `paletteItemSlug`.
- Libellés distincts, dont **« Joindre des tables »**, à ne pas confondre avec la primitive de contrôle « Join » (`flow.types.ts:316-329`).
- **Icônes Lucide** via `iconForSkill`.

**Nœud**
- Sous-titre résumé : « 5 étapes », « gauche ⋈ droite · 2 clés », « 3 sorties ».
- Ports nommés ; ajout et retrait des entrées d'union.
- Badge lignes entrée/sortie par port.

**Inspecteur** : résumé, « Ouvrir l'atelier », noms des sorties, placement (avancé), délai, aperçu du dataset écrit **pour le port choisi**.

**Coque commune des ateliers**
- En-tête : état des entrées par port, origine de l'entrée (épingle, dernier test ou chaîne amont).
- Volet gauche, centre (`<ck-data-table>` avec profil) et volet droit (formulaire généré depuis le catalogue).
- Pied : mention « calculé sur l'échantillon (10 000 lignes) », « Voir le SQL », « Convertir en nœud SQL » (désactivé pour une étape `hash` salée).

**Atelier Préparer**
- Catalogue d'étapes avec recherche, groupé comme en §6.2.
- Réordonnancement par glisser-déposer et au clavier ; activer, dupliquer, supprimer, commenter.
- Pastille d'erreur par étape.
- Aperçu à l'étape sélectionnée, avec les puces de différence de schéma.
- Actions d'en-tête de colonne préremplies.
- Annuler/rétablir sur 50 états ; debounce de 400 ms.

**Ateliers dédiés**

| Atelier | Contenu |
|---|---|
| Joindre | Type ; paires de clés appariées automatiquement ; option nul = nul ; `merge_keys` ; sélection par côté avec suffixe ; cardinalités ; alertes d'explosion et de jointure sans égalité |
| Empiler | Grille de correspondance, élargissements, option distinct |
| Agréger/Pivoter | Groupes, agrégats, pivot (valeurs proposées, plafond, `others`) |
| Dépivoter | Colonnes identifiantes et de valeurs, type commun |
| Découper | Méthode, sorties (nom, ratio ou condition), `else_port`, seed, stratification, effectifs |
| Échantillonner | Méthode, `order_by`, n ou fraction, seed, stratification |

**Éditeur de formules** : `<ck-code-editor language="sql">`, autocomplétion (colonnes et fonctions), validation en direct, type obtenu, aide.

**Données**
- Action « Préparer ce dataset » (`data-view.component.ts:80-97`), qui peut glisser en D6.
- Résumé `prep` dans l'onglet filiation.

**i18n** : `flow.dict.ts` et `data.dict.ts`, plus le test de parité des clés du catalogue (§16) et `check:i18n`.

**Tests**
- `flow-data-prep.vm.spec.ts` et `flow-data-prep-ui-contract.spec.ts`, enregistrés dans `run-unit.mjs`.
- e2e mocké **`e2e/tests/50-flow-data-prep-mocked.spec.ts`** (sombre/FR, clair/EN), scénario :
  1. déposer Préparer et ajouter 5 étapes ;
  2. aperçu ;
  3. joindre deux datasets épinglés sur `left` et `right` ;
  4. découper en 2 sorties ;
  5. vérifier les paramètres, ports et arêtes écrits.
- `build:prod` une fois.

---

## 18. Sécurité

| Menace | Mesure |
|---|---|
| Injection SQL | Identifiants et littéraux émis par sqlglot, paramètres liés pour les secrets, formules sur liste d'autorisation |
| Formule malveillante | Liste d'autorisation de l'arbre, catalogue fermé, plafonds de longueur et de profondeur, tests d'attaque |
| Regex catastrophique | Sous-ensemble RE2 sans backtracking, sur les trois moteurs |
| Accès aux fichiers ou au réseau | Runner scellé (accès externe coupé, configuration verrouillée). Aperçu scellé, système de fichiers local compris |
| Ressources | Budgets, RLIMIT, `PDEATHSIG`, sémaphore d'aperçus, délais, quotas |
| Entre workspaces | Propriété des datasets vérifiée (aperçu, chaînes amont, exécution). STS par exécution ou mono-tenant (§13). Labels hachés |
| Kubernetes | Namespace dédié, PodSecurity `restricted`, pas de jeton d'API sauf pour le driver Spark (exception documentée), NetworkPolicy, images par digest, RBAC minimal, Job suspendu jusqu'à la création de son Secret |
| Secrets | Ni dans les manifestes, ni dans les arguments, ni dans le SQL. Sel lié et masqué. Secret par exécution, supprimé avec le Job |
| Connecteurs (D7) | Garde de sortie, TLS vérifié, écriture verrouillée, profils limités à des listes blanches par famille |
| Audit | `compute_runs`, filiation, logs archivés |

---

## 19. Observabilité

- **Étapes publiées** sur la ligne et sur le badge : `queued`, `admitted`, `launching`, `reading`, `computing`, `writing`, `profiling`, `committing`.
- **Logs structurés** : `compute_run_id`, `workspace_id`, `placement`, `fingerprint`.
- **Mesures** : octets et lignes en entrée et en sortie, spill, durées, cœur·s, Go·s, estimation contre mesure.
- **Alertes** : état d'opérateur inconnu, reaper actif, quotas atteints.

---

## 20. Compatibilité et migration

- Nœuds SQL, Polars et dbt inchangés, Flows existants inchangés.
- `spec.version` avec migrations à la lecture.
- **Éjection vers SQL** : à sens unique, en dialecte DuckDB, avec un avertissement. **Refusée** si la spec contient un `hash` salé.
- Lecture mono-fichier prise en charge indéfiniment.
- Bascule `RecipeExecution` → `compute_runs` avec double lecture pendant une release (D4).

---

## 21. Réglages, déploiement et retour arrière

**Réglages** : annexe C.

**Par lot**

| Lot | Migration | `catalog-apply` (VM) / Job Helm (k8s) | Images | Infra | Retour arrière |
|---|---|---|---|---|---|
| S0 | Non | Oui (Skill HANA en lecture seule) | Backend et worker | — | Revert de la PR. Le garde SSRF est en mode rapport |
| D0 | Non | Non | Backend et worker | Correctif de `check-k8s-scaffold`, `consumer_timeout` | Revert : le SQL revient en process |
| D1b | Non | Oui | Backend et worker | Job Helm de réconciliation du catalogue | Drapeau `data_prep` du workspace désactivé |
| D2 | Non | Non | Frontend | — | Drapeau |
| D3 | Non | Non | Backend et worker (+ `deltalake`, budget mesuré) | Politique MinIO, purge | `dataops_write_delta_enabled=false` |
| D4 | `compute_runs` | Non | + runner | Chart 0.3.0, Terraform, `consumer_timeout` | `dataops_compute_enabled=false` ; downgrade alembic après drainage |
| D5 | Non | Non | + Spark | Ansible `spark_operator`, Kubernetes ≥ 1.34 | `dataops_spark_enabled=false` |
| D7 | `connections` (schéma) + **commande applicative** de reprise des données | Oui | Pilotes dans les images worker et runner | NetworkPolicy des connexions | Anciennes clés `settings` lues en repli pendant une release |

---

## 22. Plan de tests

| Niveau | Contenu |
|---|---|
| Unitaires | Spec, compilation par étape, typage, formules, shim, empreinte canonique, placement, quotas, machine à états, bail, idempotence, propriété des slugs |
| **Golden** | Détaillé sous ce tableau |
| Propriétés | Typage de conception = schéma réel. Déterminisme : deux exécutions donnent la même empreinte. Split : disjoint, complet, exact à une ligne près par strate. Commit tout-ou-rien |
| Intégration | Flow en mode eager : Préparer → Joindre (`left`/`right`) → Découper → deux nœuds SQL sur des branches distinctes. Fusion par ports en mode strict et overlay. Usurpation d'un `_data_prep` par l'amont refusée. Rétrocompatibilité des Flows |
| Concurrence | Deux exécutions vers le même slug : versions distinctes sans IntegrityError |
| Sécurité | Injections, guillemets dans les identifiants, sel absent de toute sortie, runner scellé, accès à un dataset d'un autre workspace refusé |
| Performance | Détaillé sous ce tableau |
| Front | Specs, contrat d'interface, e2e `50-…`, `check:i18n`, `build:prod` |
| Déploiement | Runbook VM (T0) : `catalog-check`, nœud de démonstration, filiation `placement`. Runbook lab : lancement, annulation, échéance, reaper, quotas, montée de version de Kubernetes |
| Acceptation métier | `fixtures/dataops/prepare_history.sql` refait en no-code (avec `timestamp_tz`) : schéma et empreinte des lignes triées identiques. Même exercice pour l'étape A2 du miroir Nawa |

**Golden** :
- Arborescence `backend/app/tests/dataops/golden/<op|step>/<cas>/` : `spec.json`, `inputs/<port>.parquet` (ou `.json` avec `.schema.json`), `expected[/<port>]…`.
- Au moins 3 cas par étape : nominal, NULL, types limites.
- Cas de papAI repris là où la sémantique est identique.
- Exécution sur DuckDB ; parité Spark avec le marqueur `spark` (D5).

**Performance** :
- Jeux pyarrow de 1 Gio et 10 Gio.
- **Environnement fixé** : worker VM 4 vCPU / 16 Go, pod T1 profil M, Spark avec 4 exécuteurs.
- Seuils d'acceptation : T0 réussit 10 Gio par spill en moins de 15 min ; T1 et T2 produisent la même empreinte que T0.

---

## 23. Lots détaillés

### S0 — Correctifs de sécurité préalables (1 PR, urgent)

1. **Écritures HANA**
   - `POST /hana/query` laisse tout membre exécuter du DML, avec `allow_writes` lu dans le corps (`hana.py:44-48,112-134`).
   - La Skill `sap_hana_query_v1` lit `allow_writes` dans sa charge utile (`services/skills_registry/wrappers/skills.py`).
   - **Correctif** : écriture réservée aux administrateurs, derrière un drapeau ; Skill en lecture seule.
2. **Mot de passe de plateforme HANA** : `HANA_CONNECTOR_PASSWORD`, repli **global** envoyé à n'importe quel hôte configuré par un administrateur de workspace (`hana/service.py:33,140,163-165`). Il est **récupérable** puisque le certificat n'est pas vérifié (`:237`). **Correctif** : supprimer le repli, ou le lier à un hôte fixé par la plateforme.
3. **HANA, divers**
   - codes d'erreur fermés à la place du texte du pilote (`hana.py:105-109,130-134,150-154`) ;
   - validation du certificat activable, puis active par défaut ;
   - repli de démonstration seulement en mode démo explicite, et signalé ;
   - appels hdbcli bloquants dans des handlers `async` (`hana.py:93-160`), déplacés dans un threadpool.
4. **Garde SSRF**, d'abord **en mode rapport** :
   - journalisation et alerte pour les hôtes privés, de bouclage, link-local et de métadonnées ;
   - liste blanche amorcée avec les hôtes déjà configurés ;
   - passage en refus à la release suivante.
5. **Hors dépôt** : révoquer le token Docker Hub en clair dans `papai-latest/spark-service/docs/README_prerelease.md`.

**Critères** : un membre ne peut plus écrire, le repli de mot de passe est absent, aucun texte de pilote n'est renvoyé, tests verts.

### D0 — Moteur SQL assaini (fait, à finaliser)

**Reste avant fusion**
1. **Bloquant** : `ops/scripts/check-k8s-scaffold.sh:41` attend `CELERY_QUEUES: "cpu,recipes"`, guillemet fermant compris ; la valeur est maintenant `cpu,recipes,dataops`. Mettre aussi à jour `docs/ops/agentium-kubernetes.md:27`.
2. Ajouter `placement` à `_PUBLIC_LINEAGE_KEYS`, sinon le critère d'acceptation n'est pas vérifiable.
3. `PDEATHSIG` dans le runner (§10.2).
4. `consumer_timeout` RabbitMQ explicite (Compose et chart).
5. Documenter que les entrées sont **copiées entièrement** dans le scratch, et dimensionner l'emptyDir du worker `dataops`.
6. Fusion sur accord de l'utilisateur.

**Critères** : CI verte (dont `check-k8s-scaffold`), et sur la VM un nœud SQL dont la filiation publique porte `"placement": "local"`.

### D1a — Moteur de préparation (4 PR)

| PR | Contenu |
|---|---|
| **a** | spec, compilateur, typage (pieds de page Parquet), empreinte canonique (S-D1-2), étapes des familles colonnes, typage, valeurs manquantes, filtres et ordre ; runner v2 (routage, paramètres liés, UTC) ; `sqlglot` épinglé |
| **b** | Opérations join, union, aggregate (pivot), unpivot, split (rangs entiers), sample |
| **c** | Formules et catalogue de fonctions, regex RE2 |
| **d** | Étapes texte, dates, nombres, fenêtres, confidentialité (sel lié) |

**Critères** :
- chaque élément du catalogue compile, se type et passe ses cas golden ;
- le typage égale le schéma réel ;
- une formule interdite est refusée avec sa position ;
- le sel n'apparaît dans aucune sortie.

### D1b — Flow et API (2 PR)

| PR | Contenu |
|---|---|
| 1 | Walker (`_data_prep_port_inputs`, branches de split, badge), Skill, capacité, wrapper, réservation et commit atomique, idempotence, propriété des slugs, validateur, filiation, drapeau de workspace, Job Helm de réconciliation du catalogue |
| 2 | API (catalog, preview, compile, validate-expression, pivot-values), échantillon persisté (`dataops_build_sample`, `sample_pending`), test de parité des clés i18n |

**Critère** : un Flow Préparer → Joindre → Découper → deux SQL s'exécute de bout en bout en eager et en mode strict, chaque sortie arrivant au bon nœud.

### D2 — Interface (4 PR)

Coque et palette → atelier Préparer → autres ateliers → éditeur de formules.

**Critères** :
- e2e `50-…` vert en FR et EN ;
- `check:i18n` et `build:prod` verts ;
- **e2e existants des ateliers SQL, Polars, dbt, ML et prévision (`31`, `32`, `49`) verts**, ce qui rend vérifiable l'absence de régression.

### D3 — Stockage (3 PR)

Lecteurs (release N) → écrivains derrière drapeau, commit, purge, profil, échantillon (N+1) → téléchargement et dump.

**Critères** :
- sur le lab, une sortie de 3 Gio s'écrit en parts ;
- tous les lecteurs de l'inventaire passent sur les deux formes ;
- les empreintes stockées restent valides.

### D4 — Calcul éphémère T1 (4 PR)

1. `compute_runs` avec la bascule de T0 et la double lecture.
2. Lanceur, ticks, reaper, chart (Deployment, RBAC, NetworkPolicy, quotas), image runner, E/S S3.
3. Quotas, politique et canal de coût.
4. Terraform et runbooks.

Spikes S-D4-1 (client `kubernetes` ou httpx), S-D4-2 (STS), S-D4-3 (autoscaling depuis 0).

**Critères (lab)** :
- `auto` choisit T1 au-delà du seuil, avec la même empreinte que T0 ;
- l'annulation, l'échéance et le reaper fonctionnent ;
- les quotas refusent proprement ;
- le coût est mesuré et affiché ;
- en multi-tenant sans STS, T1 est indisponible avec sa raison.

### D5 — Spark éphémère T2 (3 PR)

1. Spikes et rôle Ansible de l'opérateur.
2. Image, runner, lanceur et états.
3. Parité golden, profilage DuckDB après le run, dimensionnement.

**Prérequis** : Kubernetes ≥ 1.34.

**Critères** :
- parité golden et des schémas ;
- sur le lab, même empreinte que T0 sur 10 Gio ;
- seuil T2 fixé à la valeur mesurée où T2 devient moins cher ou plus rapide que T1 (rapport S-D5-4).

### D6 — Compléments

- **Types sémantiques** : les 24 de papAI, inférés sur l'échantillon (seuil 25 %, ordre de priorité de papAI), pour suggérer des étapes.
- **JSON, struct et list** : `unnest`, sélection de clés.
- **Fusion de chaînes** : plusieurs nœuds data_prep consécutifs sur un même placement deviennent une seule requête.
- **Incrémental.**
- **Suspension et reprise** d'un Run pendant un long calcul.
- **Routage des `extra_datasets` de dbt** vers des ports.
- **Pivot sur plusieurs colonnes.**
- **« Préparer ce dataset »**, si cela n'a pas été fait en D2.

### D7 — Connecteurs de bases paramétrables, import à l'échelle, nœud d'export (4 PR)

**Objectif.** Ajouter une base se fait **par configuration** : un profil déclaratif et le pilote présent dans l'image, sans code Python propre à la base.

**Existant** (audit du 2026-10-12)
- Pas de modèle de connexion : JSON dans `workspace.settings`, une seule instance par type.
- Deux registres synchronisés à la main : `ConnectorSpec` non typé (`generic/service.py:59-80`) et `resources.catalog.ts:23-344`.
- Une pile par moteur :
  - PostgreSQL : psycopg2, `pg_catalog`, 10 000 lignes, processus web ;
  - HANA : hdbcli, regex.
- Ni MySQL, Oracle, SQL Server, Snowflake ni BigQuery. Aucun mode d'écriture, aucune lecture partitionnée, aucune protection SSRF.
- L'audit des connecteurs est versionné dans `docs/ops/connector-framework-audit-2026-09-22.md`. Il date du 22 septembre, avant l'explorateur PostgreSQL et le registre de secrets.

#### D7.1 Modèle « Connexion »

**Table `connections`** :

| Colonne | Rôle |
|---|---|
| `id`, `workspace_id`, `name` (unique), `profile_key`, `profile_version` | Identité |
| `values` (JSON, sans secret) | Paramètres |
| `secret_refs` (`{param: "secret://workspace/…"}`) | Références au registre |
| `access: read\|read_write` (défaut `read`) | Écriture verrouillée à la naissance |
| `allowed_schemas[]`, `allowed_tables[]` | Restrictions |
| `last_test`, `created_by`, horodatages | Suivi |

- **Plusieurs connexions par profil.**
- **Le registre de secrets est obligatoire.** Sans `SECRET_REGISTRY_FERNET_KEY` ni OpenBao, la création d'une connexion est refusée (`CONNECTOR_REGISTRY_REQUIRED`). Pas de repli sur les enveloppes (`secrets/compat.py`).
- **Reprise de l'existant** par une **commande applicative idempotente**, avec un mode à sec : `python -m app.cli.migrate_connections --dry-run|--apply`. Ce n'est pas une migration Alembic : il faut les clés Fernet, les enveloppes et le registre. Elle convertit `settings.generic_connectors.postgresql` et `settings.connectors.sap_hana`. Les anciennes clés sont lues en repli pendant une release.

#### D7.2 Profil de moteur (déclaratif)

**Fichiers** `backend/app/resources/connectors/profiles/<key>.yaml`, validés par pydantic (`ConnectorProfile`, `extra="forbid"`) et versionnés.
- Profils de plateforme possibles en base (table `connector_profiles`, réservée à l'administrateur de la plateforme), **limités à une liste blanche par famille** pour `connect_args` et `session` : aucun SQL libre en `on_connect`, aucune option dangereuse comme MySQL `local_infile` (revue I15).
- Un profil n'est disponible que si ses paquets sont importables (`find_spec`). Sinon : « pilote absent ».
- **Le formulaire du front est généré** depuis `GET /connections/profiles` : une seule source de vérité.

**Exemple :**

```yaml
key: postgresql
version: 1
label_key: connections.profile.postgresql
family: sqlalchemy
packages: [psycopg2]
url: {drivername: postgresql+psycopg2, host: "{host}", port: "{port}", database: "{database}",
      username: "{username}", password: "{password}"}      # assemblé par sqlalchemy.URL.create
params:
  - {key: host, type: host, required: true}
  - {key: port, type: integer, default: 5432, min: 1, max: 65535}
  - {key: database, type: string, required: true}
  - {key: username, type: string, required: true}
  - {key: password, type: secret, required: true}
  - {key: sslmode, type: enum, choices: [disable, require, verify-ca, verify-full], default: verify-full, advanced: true}
  - {key: ssl_root_cert, type: secret_file, when: {sslmode: [verify-ca, verify-full]}, advanced: true}
connect_args: {sslmode: "{sslmode}", sslrootcert: "{ssl_root_cert:path}", connect_timeout: 10, application_name: agentium}
session: {read_only: true, statement_timeout_ms: "{statement_timeout_ms}", lock_timeout_ms: 1000}   # traduit par la famille
introspection: {method: inspector, exclude_schemas: [pg_catalog, information_schema]}
types: {overrides: {numeric: decimal, jsonb: text, json: text, uuid: text, interval: text, "time": text}}
read: {engines: [adbc_postgresql, sqlalchemy], fetch_size: 10000, partitioning: true, keyset: true}
write: {modes: [append, overwrite, upsert], bulk: copy, upsert: on_conflict, create_table: true}
jdbc: {driver_class: org.postgresql.Driver, url: "jdbc:postgresql://{host}:{port}/{database}"}
limits: {preview_rows: 100, statement_timeout_ms: 30000}
test: {query: "SELECT 1"}
```

**Types de paramètres** : `string`, `integer`, `boolean`, `enum`, `host` (garde de sortie), `secret`, `secret_file` (fichier 0600 éphémère), `json`. Plus `when`, `advanced`, `default`, `min`, `max`, `pattern`.

**Profils livrés**

| Profil | Pilote Python | Lecture rapide | Upsert | Notes |
|---|---|---|---|---|
| `postgresql` | psycopg2 (présent) | ADBC PostgreSQL, sinon curseur serveur | `on_conflict` | Remplace la pile actuelle |
| `mysql` / `mariadb` | `pymysql` | `SSCursor` | `on_duplicate_key` | — |
| `sqlserver` | `pymssql` | curseur | `merge` | Licence LGPL (S-D7-3) |
| `oracle` | `oracledb` (thin) | `arraysize` | `merge` | — |
| `snowflake` | `snowflake-connector-python` + `snowflake-sqlalchemy` | `fetch_arrow_batches` | `merge` | — |
| `bigquery` | `google-cloud-bigquery` + `sqlalchemy-bigquery` | API Storage (Arrow) | `merge` | — |
| `sap_hana` | hdbcli + `sqlalchemy-hana` | curseur | `upsert_statement` | **Générateur sqlglot propre à HANA** : aucun dialecte HANA connu, à vérifier sur la version épinglée (S-D7-2). Certificat vérifié par défaut |
| `duckdb_parquet` | duckdb | natif | — | Lecture seule |
| `unity_catalog` | API REST UC (httpx) + `deltalake` | Identifiants temporaires (credential vending), puis lecture Delta | Plus tard (tables gérées par le catalogue) | UC OSS 0.6 et Databricks UC. Famille `uc_rest` (§29.4) |
| `delta_sharing` | `delta-sharing` | Arrow | — | Lecture seule des partages reçus. Profil de partage en `secret_file` |
| `databricks_sql` | `databricks-sql-connector` + dialecte SQLAlchemy `databricks` | curseur / Arrow | `merge` | SQL Warehouse. Licences à valider (S-D7-3) |

Les pilotes forment une couche dédiée des images worker et runner, avec un budget mesuré.

#### D7.3 Adaptateurs génériques (seul code, une fois par famille)

| Famille | Rôle |
|---|---|
| `sqlalchemy` | `URL.create` + `connect_args` en liste blanche ; `Inspector` ; quoting ; mappage de types par affinité avec surcharges ; lecture en flux (`stream_results`) vers des lots Arrow ; session en lecture seule traduite par dialecte |
| `adbc` | Lecture et ingestion Arrow (PostgreSQL et SQLite maintenus par Arrow ; Snowflake, BigQuery et Redshift par l'ADBC Driver Foundry) |
| `dbapi` | Repli par curseur |
| `spark_jdbc` | T2 : `spark.read.jdbc` partitionné, écriture en staging puis MERGE |

**Lecture**
- Modes : `table`, ou `query` (un seul SELECT d'auteur, validé par sqlglot dans le dialecte du profil ; pour HANA, validateur dédié).
- **Partitionnement générique** : `min` et `max` sur une colonne numérique ou date, N plages bornées, parts Parquet.
- Pagination par clé (`keyset`), et mode `incremental` par filigrane mémorisé dans la filiation.

**Écriture**
- Modes : `append`, `overwrite` (`TRUNCATE` puis insertion, en transaction si possible) ou `upsert(keys)`.
- Upsert :
  1. table de staging ;
  2. chargement en masse ;
  3. fusion **générée par sqlglot** (`ON CONFLICT`, `ON DUPLICATE KEY`, `MERGE`, ou `UPSERT` HANA par le générateur dédié) ;
  4. suppression de la staging.
- Création de la table cible par le mappage de types inverse.

**Exécution** : comme DataOps, sur la file `dataops` (T0 : runner connecteur en sous-processus ; T1 : pod). Les identifiants passent par un **fichier 0600** dans le scratch, lu puis effacé. Les bornes sont des réglages.

#### D7.4 Garde réseau et sécurité

**Garde de sortie** :
1. Résoudre l'hôte.
2. Refuser les adresses privées, de bouclage, link-local et de métadonnées, sauf `connector_allowed_networks`.
3. **Se connecter à l'IP résolue**, contre le rebinding (`hostaddr` pour PostgreSQL ; sinon une seconde résolution qui doit être identique, S-D7-4).

En T1/T2, la NetworkPolicy n'autorise que les CIDR des connexions déclarées.

**TLS** vérifié par défaut.

**Lecture seule sur trois niveaux** : compte de base recommandé, session en lecture seule, SQL généré ou SELECT validé.

**Écriture**
- La connexion doit être `read_write`, ce que seul un administrateur active.
- **Aperçu à sec** obligatoire (lignes à insérer et à mettre à jour).
- HITL en amont si la politique l'exige (validateur).

**Erreurs** : codes fermés, jamais le texte du pilote.

#### D7.5 Flow, API, interface

**Nœuds Flow**
- **`connector_read_v1`** (« Lire une base », bloc `_connector_read`) : produit un dataset.
- **`connector_write_v1`** (« Écrire dans une base », bloc `_connector_write`) : prend un dataset et produit un rapport `{inserted, updated, rows}`.
- `source.connector` reste pour les lectures en direct existantes.

**API**

| Méthode | Route |
|---|---|
| GET | `/connections/profiles` |
| GET, POST | `/connections` |
| GET, PUT, DELETE | `/connections/{id}` |
| POST | `/connections/{id}/test` |
| GET | `/connections/{id}/catalog`, `/connections/{id}/table` |
| POST | `/connections/{id}/preview`, `/connections/{id}/import` |
| POST | `/connector-write/dry-run` |

Configuration réservée aux administrateurs du workspace, catalogue ouvert aux membres.

**Interface** : page Connexions générique (formulaire généré, test, explorateur généralisé, aperçu, import), ateliers des deux nœuds. Les pages PostgreSQL et HANA spécifiques sont retirées après la bascule.

#### D7.6 PR, réglages, tests, critères

**PR** : modèle et commande de reprise → lecture → écriture → interface.

**Réglages** : `connector_allowed_networks`, `connector_preview_rows` (100), `connector_import_max_rows` et `connector_import_max_mb`, `connector_statement_timeout_ms`, `connector_write_batch_rows` (10 000), `connector_partitions_max` (32).

**Tests**
- Contrat de chaque profil : schéma, URL, upsert générable.
- Intégration par profil sur conteneur (PostgreSQL et MySQL en local ; Oracle Free, SQL Server, HANA Express en CI lab) : test, introspection, lecture partitionnée, `append`, `overwrite`, `upsert`, refus d'écriture sur une connexion `read`.
- SSRF et rebinding.
- Aucun texte de pilote dans les erreurs.
- Reprise des données (à sec, puis application, puis relance idempotente).
- Cohérence entre le formulaire et le profil.
- Refus des options hors liste blanche.

**Critères**
- **Un profil de test ajouté sans code passe toute la suite en CI.**
- Import PostgreSQL de 10 M lignes partitionné.
- Upsert de 1 M lignes vers PostgreSQL et SQL Server, avec des comptes exacts.
- Connexions migrées fonctionnelles.

**Spikes**
- S-D7-1 : débit ADBC contre SQLAlchemy.
- S-D7-2 : MERGE et UPSERT avec sqlglot sur 7 dialectes, et HANA.
- S-D7-3 : licences et tailles des pilotes.
- S-D7-4 : connexion à l'IP résolue pour chaque pilote.

---

## 24. Risques et mitigations

| Risque | Mitigation |
|---|---|
| Dérive DuckDB ↔ Spark | Formes portables, shim, golden et égalité des schémas comme gate |
| Lacunes de sqlglot (transpilation, HANA) | Catalogue fermé, tests par fonction, générateurs dédiés |
| Empreinte canonique non portable (flottants) | Spike S-D1-2 ; repli : flottants exclus des clés |
| Régression du walker | Entrées dans le bloc graph-owned, fusion des branches limitée aux amonts `data_prep_v1`, tests strict et overlay |
| Attentes interrompues (API redémarrée, consumer timeout RabbitMQ) | Ticks par bail, `consumer_timeout` explicite, réutilisation par empreinte |
| Versions concurrentes | Verrou par slug, réessai, propriété des slugs |
| Aperçu lent ou coûteux | Échantillons persistés uniquement, délai, cache |
| Confusion « Join » | Libellé et icône distincts |
| Kubernetes < 1.34 | T1 disponible, T2 indisponible avec sa raison, runbook de montée de version |
| Pas de STS | T1 en mono-tenant seulement |
| Autoscaling à 0 indisponible | Minimum 1 nœud, avec son coût |
| Suppressions MinIO cassées par l'alignement | Inventaire préalable, identité de purge |
| Taille des images (pilotes) | Couches dédiées, budgets |
| Licences des pilotes | Spike S-D7-3 avant de livrer |
| Delta : taille de la roue `deltalake`, fonctionnalités de protocole que certains lecteurs ignorent | Budget d'image. Protocole minimal sans deletion vectors ni column mapping |
| Dépendance à l'écosystème Databricks | Delta est un projet de la Linux Foundation au protocole publié, avec plusieurs implémentations indépendantes (delta-rs, DuckDB, Spark). La lecture par liste de fichiers reste possible sans Delta |

---

## 25. Spikes (questions ouvertes)

| Spike | Question | Lot |
|---|---|---|
| S-D1-1 | Rendu sqlglot complet du catalogue (DuckDB) | D1a |
| S-D1-2 | Empreinte canonique identique DuckDB / Spark (flottants, horodatages) | D1a |
| S-D4-1 | Client `kubernetes` ou httpx sur l'API (modèle OpenBao) | D4 |
| S-D4-2 | STS MinIO et session policy | D4 |
| S-D4-3 | Autoscaling depuis 0 sur OVH MKS | D4 |
| S-D5-1 | Forme PySpark de l'opérateur ASF et liste complète des états | D5 |
| S-D5-2 | `translate` et formats de date sur Spark | D5 |
| S-D5-3 | Committer magic sur MinIO | D5 |
| S-D5-4 | Coût et démarrage d'un petit job (seuil de T2) | D5 |
| S-D3-1 | delta-rs sur MinIO : option exacte du put conditionnel, écriture en flux de N sorties en une passe, taille de fichier cible | D3 |
| S-D3-2 | Lecture par liste de fichiers (protocole minimal), statistiques du journal, coût de l'empreinte | D3 |
| S-D7-1 à 4 | Voir D7.6 | D7 |
| S-D7-5 | UC OSS 0.6 et Databricks UC : API REST, credential vending vers S3, Azure et MinIO | D7 |
| S-D7-6 | Client Delta Sharing : roue `delta-kernel-rust-sharing-wrapper` disponible pour linux/amd64 | D7 |

---

## 26. Pièges papAI à ne pas reproduire

- **Statut** : « available » avant tout calcul.
- **Fenêtres** : ffill et bfill inversés, sans ordre.
- **Hasard non seedé** : split en blocs contigus, `rand()` partout.
- **Agrégats** : collecte sur le driver et agrégats de formule calculés au moment du plan.
- **Histogrammes** : non bornés, dates dans le fuseau de la JVM.
- **Dates** : format LEGACY (`SSSSSS`, `[ ]`).
- **Noms** : assainissement global, renommage de struct qui donne NULL.
- **SQL** : `ScriptTransformation` autorisé, `;` dans une chaîne.
- **Identifiants** : clés S3 dans une configuration partagée, recette et identifiants dans les arguments.
- **Images et pilotage** : images `latest`, heartbeat codé en dur.
- **Échecs silencieux** : colonnes absentes ignorées, constantes ignorées.
- **Interface** : erreurs non rattachées à une étape, aucun debounce.

---

## 27. Hors périmètre

- Import des recettes papAI.
- UDF Python sur Spark, et Spark Connect.
- Delta et Iceberg.
- Cluster Spark permanent.
- Calcul éphémère sur VM, et GPU.
- Sources non relationnelles (MongoDB, Elasticsearch, Cassandra) et import HTTP générique, qui restent couverts par les connecteurs REST et MCP.
- Paramètres SQL de `SqlExtension`.
- Unity Catalog OSS comme catalogue interne, et serveur Delta Sharing fournisseur (§29.5).
- Spark Declarative Pipelines, Photon, Databricks Runtime, DBSQL (§29.5).

---

## 28. Documentation à livrer

| Lot | Documents |
|---|---|
| S0 | `docs/ops/secrets.md` (repli HANA retiré), note de sécurité |
| D0 | `docs/agentium-release-process.md` (déjà fait), `docs/ops/agentium-kubernetes.md` (files) |
| D1b / D2 | **Guide utilisateur** : opérations, étapes, formules, codes d'erreur, échantillon. Release process : drapeau, `catalog-apply` / Job Helm |
| D3 | Format Delta des versions (protocole minimal, commit, lecture par liste de fichiers), purge, procédure en deux releases |
| D4 | `docs/ops/agentium-kubernetes.md` (namespace de calcul, RBAC, NetworkPolicy, profils, quotas), runbooks (reaper, annulation, quotas, Terraform), `docs/ops/secrets.md` (identité compute, STS) |
| D5 | Opérateur Spark (Ansible), montée de version de Kubernetes, image Spark |
| D7 | **Guide d'écriture d'un profil de connecteur**, page Connexions, procédure de reprise des connexions, profils Databricks (Unity Catalog, Delta Sharing, SQL) et Snowflake |
| I1 / I2 | Guide Iceberg : profils `iceberg_rest`, procédure Snowflake (catalog-linked database), exposition et composant Polaris |

---

## 29. Écosystème open source de Databricks et formats de table

Analyse du 2026-10-13. Les versions et dates viennent des sources citées en §29.7. **Un point contradictoire entre sources est marqué « à vérifier » et rattaché à un spike.**

### 29.1 Inventaire et verdict

| Projet (origine Databricks) | Licence et gouvernance | État vérifié | Verdict pour Agentium | Où |
|---|---|---|---|---|
| **Delta Lake** (protocole, delta-spark) | Apache 2.0, Linux Foundation | 4.4.x : Spark 4.2, API UC Delta Table, colonnes identité et générées. 4.1.0 le 2026-03-01 : Spark 4.1, tables gérées par catalogue | **Adopté** comme format des versions produites par DataOps | D3 (§11), D5 |
| **delta-rs / `deltalake`** (Rust et Python, sans JVM) | Apache 2.0, projet delta-io | Python 1.6.6 (2026-09-24), crate 0.32.4. La 1.0 a apporté CDF, contraintes, évolution de schéma pour tous les écrivains et deletion vectors. MinIO listé comme stockage pris en charge | **Adopté** : écriture et lecture en T0/T1 et dans l'API | D3, D7 |
| Extension DuckDB **`delta`** | MIT (DuckDB) | Non expérimentale depuis le 2026-05-07 : lecture, `INSERT` (plusieurs `INSERT` d'une transaction = une version Delta), voyage dans le temps. Pas d'`UPDATE`, `DELETE` ni `MERGE` | **Optionnelle.** Le produit lit via delta-rs → Arrow, sans extension, ce qui reste compatible avec le scellement (`INSTALL` bloqué) | §10 |
| **Unity Catalog OSS** | Apache 2.0, LF AI & Data | 0.6.0 (2026-08-20) : API REST ouverte, Iceberg REST, credential vending. Lignage, ABAC et audit encore sur la feuille de route | **Pas comme catalogue interne.** **Adopté comme cible de connecteur** (UC OSS et Databricks UC) | D7 |
| Extension DuckDB **`unity_catalog`** | MIT | `ATTACH` vers UC OSS ou Databricks, `INSERT` ; pas de DDL (`CREATE TABLE` passe par Spark ou la CLI UC) | Optionnelle (lab, diagnostic) | D7 |
| **Delta Sharing** (protocole, connecteur Python `delta-sharing` 1.3.x) | Protocole ouvert (delta-io). Serveur de référence « pour le développement ». **Licence du dépôt à vérifier** | Client stable. Dépendance `delta-kernel-rust-sharing-wrapper` : roue absente sur certaines plateformes | **Client adopté** (profil `delta_sharing`, lecture des partages reçus). **Fournisseur hors périmètre** | D7, §27 |
| **Databricks SQL** (`databricks-sql-connector`, dialecte SQLAlchemy `databricks`) | Open source, licence à vérifier (S-D7-3) | Stable | **Adopté** comme profil `databricks_sql` (SQL Warehouse) | D7 |
| **MLflow** | Apache 2.0, Linux Foundation | Déjà en production (3.15.2) | Déjà intégré | Plan ML |
| **Apache Spark** | Apache 2.0, ASF | 4.2, pris en charge par Delta 4.4 | Déjà retenu pour T2 | D5 |
| **Spark Declarative Pipelines** (ex-DLT, donné à Apache Spark, SPIP-51727) | Apache 2.0, ASF | Annoncé en juin 2025, intégration dans Spark en cours. Release exacte à vérifier | **Non adopté** : le Flow est l'orchestrateur. SDP dupliquerait le DAG et lierait les pipelines à Spark | §27 |
| **Delta Kernel** (Java, Rust) | Apache 2.0 | Utilisé en interne par delta-rs et DuckDB | Indirect | — |
| Photon, Databricks Runtime, DBSQL, Lakehouse Federation, DLT managé, UniForm managé | Propriétaires | — | **Exclus** | §27 |

### 29.2 Pourquoi Delta Lake est l'état de l'art *pour nos contraintes*

**Nos contraintes**
1. Écrire en Python, sans JVM, depuis un runner autonome (T0/T1).
2. **Aucun service de catalogue supplémentaire** : le catalogue d'Agentium (Postgres : datasets, versions, filiation, IAM) reste la source de vérité.
3. Lecture native par les trois moteurs du plan : DuckDB, Polars, Spark.
4. Interopérabilité avec les clients qui ont déjà un lakehouse.
5. Frugalité et maturité.

| Critère | **Delta Lake** | Apache Iceberg | DuckLake | Apache Hudi | Manifeste maison (version précédente du plan) |
|---|---|---|---|---|---|
| Gouvernance | Linux Foundation, protocole publié | ASF, spec v3 (statut GA variable selon les sources) ; catalogue de référence **Apache Polaris**, projet de premier niveau depuis le 2026-02-18 | DuckDB Foundation (MIT) ; **1.0 le 2026-04-13**, « prête pour la production » ; 1.1 annoncée en septembre ou au 2026-10-21 | ASF | — |
| Écriture Python sans JVM | **Oui** (delta-rs 1.6) | Oui (pyiceberg) | Oui (DuckDB) | Surtout JVM | Oui |
| Commit sans service de catalogue | **Oui** : journal dans le stockage, put conditionnel | **Non** : catalogue (REST ou SQL) requis pour l'atomicité | **Non** : base SQL requise (notre Postgres conviendrait) | Oui | Oui (Postgres) |
| Spark natif (T2) | **Oui** (delta-spark 4.4, Spark 4.2) | Oui | **Non** : pas de connecteur Spark mûr, ce qui casserait la parité T0/T2 | Oui | Non (lecture Parquet seulement) |
| DuckDB | Lecture + `INSERT`, non expérimental (mai 2026) | Lecture (extension `iceberg`) | Natif | Limité | Lecture Parquet |
| Polars | `scan_delta` / `write_delta` | `scan_iceberg` | Via DuckDB | — | Lecture Parquet |
| Interopérabilité clients | **Clients Databricks** (UC, Delta Sharing) ; UniForm donne une lecture Iceberg (côté Databricks) | Écosystème multi-éditeurs le plus large (Snowflake, Trino, Dremio…) | Écosystème DuckDB | Plus réduit | Aucune |
| Coût d'intégration | Une roue Python, aucun service | Un service de catalogue en plus | Couplage à DuckDB, pas de Spark | JVM | Code maison à maintenir |

**Conclusion**
- **Delta Lake est le seul format qui satisfait les cinq contraintes à la fois.** Il remplace notre manifeste maison, qui réinventait un journal de commit sans interopérabilité.
- **Iceberg** est l'autre état de l'art, avec l'écosystème multi-éditeurs le plus large. Il imposerait un catalogue REST (Polaris ou équivalent) en plus de celui d'Agentium.
- **DuckLake** colle le mieux à notre pile (Postgres + Parquet + DuckDB). Il est **à surveiller**, mais encore jeune et sans Spark. On réexamine à DuckLake 1.1, ou dès qu'un connecteur Spark existe.
- Le plan garde une porte de sortie : une table Delta à version unique **reste une liste de fichiers Parquet lisible sans Delta** (`dataset_files`).

#### 29.2.1 Pourquoi Iceberg exige un catalogue, et pas Delta

**Comment Iceberg commite.** L'état d'une table Iceberg est un arbre de métadonnées :

```
fichier de métadonnées (vN.metadata.json : schéma, partitions, liste des snapshots, snapshot courant)
  → manifest list (Avro, un par snapshot)
    → manifests (Avro)
      → fichiers de données (Parquet)
```

- **Chaque commit écrit un nouveau fichier de métadonnées complet.** La table « courante » n'est rien d'autre qu'un **pointeur** vers le dernier de ces fichiers.
- La spécification fonde l'isolation sur un **échange atomique de ce pointeur** (*compare-and-swap*) : un écrivain ne réussit que si le pointeur désigne toujours la version qu'il a lue. Sinon il relit et réessaie (concurrence optimiste).
- **Ce pointeur n'est pas dans le stockage objet : il est dans le catalogue.** Hive Metastore, catalogue JDBC/SQL, catalogue REST (Polaris, Lakekeeper, UC OSS…), Glue ou Nessie : chacun garde l'association `nom de table → emplacement de la métadonnée courante` et réalise l'échange atomique.
- **Le stockage objet seul ne suffit pas.** Le catalogue « Hadoop », fondé sur les fichiers, repose sur un **renommage atomique** (`version-hint.text`). La documentation d'Iceberg le réserve à HDFS ou à un système équivalent, et le dit **non sûr en écritures concurrentes sur S3**, où un renommage est une copie suivie d'une suppression. MinIO est dans ce cas.
- **Même la lecture dépend du catalogue pour trouver la version courante.** Sans lui, il faut donner le chemin exact du fichier de métadonnées :
  - DuckDB : `iceberg_scan('…/vN.metadata.json')`, ou deviner la version en option explicitement « non sûre » ;
  - pyiceberg : `StaticTable`, en lecture seule ;
  - Polars : `scan_iceberg(chemin)`.

  Les écrivains (pyiceberg, Spark) passent toujours par un objet catalogue.

**Comment Delta commite.** Le journal est **dans le stockage** : `_delta_log/00000000000000000N.json`.
- Un commit consiste à créer le fichier N+1 **s'il n'existe pas** : put conditionnel `If-None-Match`, que MinIO prend en charge, ou un verrou externe pour les anciens S3.
- Tout lecteur liste le journal (et ses checkpoints) pour trouver la version courante.
- **Le catalogue est optionnel.** Delta 4.x ajoute des tables « gérées par catalogue », où Unity Catalog arbitre les commits pour les transactions multi-tables et la gouvernance. Le protocole fonctionne sans.

**Ce que cela imposerait à Agentium si l'on choisissait Iceberg**

| Option de catalogue | Ce qu'elle implique | Verdict |
|---|---|---|
| Service REST (Apache Polaris, Lakekeeper, UC OSS en Iceberg REST) | Service de plus (Java ou Rust) avec sa base, sa haute disponibilité, ses sauvegardes et ses montées de version. Ses comptes et son RBAC sont à synchroniser avec l'IAM d'Agentium. Les pods de calcul doivent le joindre (NetworkPolicy, identifiants) | Coût d'exploitation sans bénéfice interne : nous avons déjà un catalogue |
| Catalogue JDBC/SQL dans le Postgres d'Agentium (`SqlCatalog` de pyiceberg, `JdbcCatalog` de Spark) | Pas de nouveau service. Mais **le runner et le driver Spark doivent accéder à la base de l'application**, ce qui contredit le principe 3 (pas de secret applicatif dans le calcul) et couple les runners au schéma de la base | Refusé pour des raisons de sécurité |
| Catalogue éphémère par exécution (SQLite ou en mémoire dans le runner, chemin de métadonnées stocké dans la ligne du dataset) | Possible pour une table écrite une fois par un écrivain unique, mais **à contre-courant** du design d'Iceberg. Fragile côté Spark (catalogue Hadoop sur S3) | Bricolage, non retenu |
| Lecture seule par chemin de métadonnées | Suffit pour lire, pas pour écrire | Partiel |

**Conclusion.**
- Avec Iceberg, la fonction de catalogue est **obligatoire pour écrire** et **nécessaire pour retrouver la version courante**. Pour Agentium, cela signifie soit un service en plus, soit l'exposition de sa base aux pods de calcul.
- Avec Delta, la table se suffit à elle-même dans le stockage, et le catalogue d'Agentium reste le seul catalogue.
- L'atout d'Iceberg (un catalogue partagé par de nombreux moteurs et écrivains concurrents) répond à un besoin que notre stockage interne n'a pas : un écrivain unique par version, et un catalogue applicatif déjà présent.
- **On reconsidère Iceberg si un client exige d'interroger les datasets Agentium depuis Snowflake, Trino ou Dremio.** Il s'agirait alors d'une **couche d'exposition** (catalogue REST Polaris, ou UniForm), pas de notre format interne.

### 29.3 Intégration de Delta (remplace le manifeste de §11)

| Aspect | Choix |
|---|---|
| Granularité | **Une table Delta par version de dataset**, écrite une fois (version 0), par un seul écrivain. Le modèle de versions d'Agentium reste inchangé, et il n'y a aucun conflit de commit concurrent |
| Commit | Fichiers Parquet, puis `_delta_log/00000000000000000000.json` en dernier, par put conditionnel (`If-None-Match`, pris en charge par MinIO). Option delta-rs exacte : spike S-D3-1. Le commit Agentium des N lignes `ready` reste une transaction Postgres |
| Protocole | Minimal (reader 1 / writer 2), **sans deletion vectors ni column mapping** : lisible par tout lecteur Delta, et comme simple liste de Parquet |
| Écriture T0/T1 | `deltalake.write_deltalake(uri, RecordBatchReader, mode="error", storage_options=…)`, une par sortie. Avec un split, la passe unique alimente N flux, ou bien on écrit les parts puis on commite. Choix au spike S-D3-1 |
| Écriture T2 | `df.write.format("delta")` (delta-spark 4.4 dans l'image Spark) |
| Lecture | delta-rs `to_pyarrow_dataset()` → `connection.register` (DuckDB scellé, sans extension) ; Polars `scan_delta` ; Spark `format("delta")` ; anciens lecteurs : `dataset_files()` |
| Statistiques | Min, max et NULL par fichier, issus du journal : élagage dans l'aperçu et les filtres |
| Empreinte | `sha256` du commit 0 |
| Rétention | Pas de `VACUUM` : une seule version par table |
| Plus tard (D6) | **Tables vivantes** : Delta muable avec `MERGE` et CDF, pour l'incrémental et l'upsert de D7. Lecture Iceberg (UniForm) si la version ouverte le permet |

### 29.4 Unity Catalog, Delta Sharing et Databricks SQL dans D7

- **Profil `unity_catalog`** (famille `uc_rest`, client HTTP du dépôt).
  - Paramètres : `endpoint`, `token` (secret), `catalog`, `schema`.
  - Introspection par l'API REST UC : catalogues, schémas, tables, colonnes.
  - Lecture : **demande d'identifiants temporaires** (credential vending), puis lecture des fichiers par delta-rs (S3, ADLS, GCS).
  - Fonctionne sur UC OSS et sur Databricks UC.
  - Écriture plus tard, via les tables gérées par le catalogue (UC arbitre les commits).
- **Profil `delta_sharing`** : profil de partage en `secret_file` ; liste des partages, schémas et tables ; lecture en Arrow ; lecture seule.
- **Profil `databricks_sql`** : dialecte SQLAlchemy `databricks` sur SQL Warehouse ; lecture, et upsert par `MERGE` généré.
- Garde de sortie, codes d'erreur et règles d'écriture de D7.4 inchangés.
- **Le credential vending d'UC valide le choix fait pour T1** : identifiants objet par exécution, via STS (S-D4-2).

### 29.5 Ce qui n'est pas adopté, et pourquoi

| Projet | Raison |
|---|---|
| **UC OSS comme catalogue interne** | Il dupliquerait le catalogue, la filiation et l'IAM d'Agentium. La version 0.x n'a ni lignage, ni ABAC, ni audit, et ajoute un service Java. **À réexaminer** si un client exige qu'Agentium expose ses datasets à des moteurs tiers par une API de catalogue standard. Apache Polaris (Iceberg REST) est alors l'autre candidat |
| **Serveur Delta Sharing fournisseur** | Le serveur ouvert est destiné au développement. Partager des datasets Agentium vers l'extérieur viendra avec un serveur de production (UC OSS ou dédié), sur demande client |
| **Spark Declarative Pipelines** | Le Flow est l'orchestrateur. On ne double pas le DAG |
| **Photon, DBR, DBSQL, Lakehouse Federation, UniForm managé** | Propriétaires |

### 29.6 Conséquences sur le plan

- **D3**
  - Nouvelle dépendance `deltalake` (pin dans les contraintes, budget d'image).
  - Le drapeau `dataops_write_parts_enabled` devient `dataops_write_delta_enabled`.
  - Spikes S-D3-1 et S-D3-2.
- **D5** : delta-spark 4.4 dans l'image Spark ; écriture Delta native.
- **D7** : profils `unity_catalog`, `delta_sharing`, `databricks_sql` ; spikes S-D7-5 et S-D7-6.
- **D6** : tables vivantes, et UniForm sous réserve.
- **Documentation (§28)** : format Delta des versions, et guide des profils Databricks.

### 29.7 Sources

- [Delta Lake 4.1.0 Released](https://delta.io/blog/2026-03-01-delta-lake-4-1-0-released/)
- [Releases delta-io/delta (4.4.x)](https://github.com/delta-io/delta/releases)
- [deltalake sur PyPI](https://pypi.org/project/deltalake/)
- [deltalake sur docs.rs](https://docs.rs/crate/deltalake/latest)
- [Delta Lake 4.0 Preview (delta-rs 1.0)](https://delta.io/blog/delta-lake-4-0/)
- [DuckDB — Delta Grows Up: Writes, Unity Catalog and Time Travel (2026-05-07)](https://duckdb.org/2026/05/07/delta-uc-updates)
- [DuckDB — extension delta](https://duckdb.org/docs/current/core_extensions/delta.html)
- [Unity Catalog (Wikipedia, 0.6.0)](https://en.wikipedia.org/wiki/Unity_Catalog)
- [Open sourcing Unity Catalog](https://www.databricks.com/blog/open-sourcing-unity-catalog)
- [Accès externe à Unity Catalog via API ouvertes](https://www.databricks.com/blog/secure-external-access-unity-catalog-assets-open-apis)
- [Limites d'Unity Catalog en 2026 (Atlan)](https://atlan.com/know/databricks-unity-catalog-limitations/)
- [DuckLake v1.0 (2026-04-13)](https://duckdb.org/2026/04/13/ducklake-10)
- [DuckLake — calendrier de release](https://ducklake.select/release_calendar)
- [Apache Polaris devient projet de premier niveau (2026-02-18)](https://www.dremio.com/press-releases/apache-polaris-graduates-to-top-level-apache-project-establishing-the-open-catalog-standard-for-apache-iceberg/)
- [Snowflake — Apache Polaris et l'Iceberg REST Catalog](https://www.snowflake.com/en/blog/engineering/apache-polaris-iceberg-rest-catalog/?lang=de)
- [Iceberg vs Delta vs Hudi 2026 (RisingWave)](https://risingwave.com/blog/apache-iceberg-vs-delta-lake-vs-hudi-2026/)
- [delta-sharing sur PyPI](https://pypi.org/project/delta-sharing/)
- [Spark Declarative Pipelines (InfoQ, juillet 2025)](https://www.infoq.com/news/2025/07/databricks-declarative-pipelines)
- [Écritures conditionnelles MinIO](https://www.min.io/blog/leading-the-way-minios-conditional-write-feature-for-modern-data-workloads)
- [object_store — S3ConditionalPut (MinIO, mode etag)](https://docs.tvix.dev/rust/object_store/aws/enum.S3ConditionalPut.html)

---

## 30. Iceberg optionnel, à activer sur besoin (cible Snowflake et lakehouses ouverts)

> **Principe.** Delta reste le format **interne** (D-21). Iceberg n'est **pas** un second format interne. C'est une **couche d'interopérabilité**, activée par drapeau et par niveau, quand un client l'exige. Rien n'est à exploiter tant qu'elle n'est pas activée.

### 30.1 Pourquoi Iceberg est la bonne voie vers Snowflake

- **Snowflake mise sur Iceberg et les catalogues REST pour son interopérabilité ouverte :**
  - **écriture dans des tables Iceberg gérées par un catalogue externe**, via les *catalog-linked databases*, compatibles avec tout catalogue REST (Databricks UC, AWS Glue, Snowflake Open Catalog) : GA en octobre 2025 ;
  - catalogue REST Amazon S3 Tables : GA le 2026-08-10 ;
  - endpoint Iceberg REST *Horizon*, pour que Spark, Trino, DuckDB ou PyIceberg lisent ces tables : préversion le 2026-08-18.
- **Snowflake ne s'appuie pas sur Delta pour cela.** Si l'on veut que Snowflake lise ou écrive les mêmes fichiers que nous, sans copie, le passage obligé est Iceberg avec un catalogue REST.
- **Mais la plupart des besoins Snowflake ne demandent pas Iceberg.** Lire une table Snowflake ou y pousser un dataset préparé (append, overwrite, upsert) passe par le **profil `snowflake` natif de D7**, avec le pilote Python et `MERGE` généré. C'est le **niveau I0**, livré avec D7.

### 30.2 Niveaux d'activation

| Niveau | Quoi | Catalogue à exploiter par nous | Quand l'activer |
|---|---|---|---|
| **I0** (D7, toujours) | Profil `snowflake` natif : lecture, `append`, `overwrite`, `upsert` par `MERGE`, avec copie | Aucun | Dès D7 |
| **I1** | **Iceberg comme cible de connecteur**. Famille de profils `iceberg_rest` : lire et écrire des tables Iceberg **dans le catalogue REST du client** (Snowflake Open Catalog, Apache Polaris, AWS Glue / S3 Tables, Databricks UC en Iceberg REST, Lakekeeper, Nessie). Snowflake les voit ensuite par une catalog-linked database | **Aucun : c'est celui du client** | Un client a un lakehouse Iceberg ou veut un partage sans copie avec Snowflake |
| **I2** | **Exposition des datasets Agentium en Iceberg** : métadonnées Iceberg posées sur les mêmes fichiers Parquet que la version Delta, enregistrées dans un catalogue REST | Le catalogue du client, **ou** un composant optionnel **Apache Polaris** déployé avec Agentium | Un client veut interroger les datasets Agentium **sur place** depuis Snowflake, Trino ou Dremio, **et** le stockage lui est accessible |
| **I3** | Iceberg comme format interne | — | **Non prévu.** Voir les critères de réexamen (§30.6) |

### 30.3 Niveau I1 : Iceberg comme cible de connecteur

- **Famille `iceberg_rest`**, à côté de `sqlalchemy`, `adbc`, `uc_rest` et `spark_jdbc` (D7.3).
  - Moteur T0/T1 : **pyiceberg** (Python pur et pyarrow ; 0.11.0 sortie le 2026-02-09), dans le runner connecteur.
  - Moteur T2 : `iceberg-spark-runtime` configuré sur le catalogue REST.
  - Alternative à évaluer : l'extension DuckDB `iceberg` (écriture via catalogue REST, `MERGE INTO` annoncé en 1.5.3). Elle devrait être **pré-installée dans l'image**, puisque le scellement interdit `INSTALL`.
- **Paramètres du profil**
  - `catalog_uri`, `warehouse`, `namespace`, `table` ;
  - authentification : OAuth2 *client credentials*, jeton porteur, ou SigV4 pour S3 Tables, avec les secrets dans le registre ;
  - options : `credential_vending: true` (préféré) ou identifiants de stockage du client en `secret` ; `nested_namespaces`.
- **Opérations**
  - Lecture : scan Arrow, avec prédicats poussés au catalogue (planification côté serveur depuis Iceberg 1.11).
  - Écriture : `append`, `overwrite` (table entière ou filtrée), `upsert` (API native si pyiceberg l'offre, sinon staging puis réécriture filtrée), création de table depuis le schéma Arrow.
  - Mêmes règles qu'en D7.4 : connexion `read_write` activée par un administrateur, aperçu à sec, HITL si la politique l'exige.
- **Données** : une copie des fichiers de notre MinIO vers le stockage du client, faite par le runner avec les identifiants délivrés par son catalogue. Ensuite, Snowflake lit et écrit **sans copie**.
- **Sécurité** : garde de sortie (D7.4), NetworkPolicy vers l'endpoint du catalogue et le stockage du client, identifiants délivrés par le catalogue et de courte durée. Pas de clé de stockage permanente quand le catalogue sait en délivrer.

### 30.4 Niveau I2 : exposition des datasets Agentium en Iceberg

- **Métadonnées sans réécriture des données**
  - Une version Delta (protocole minimal, noms physiques = noms logiques) est enregistrée comme table Iceberg **sur les mêmes fichiers Parquet**, par l'ajout de fichiers existants (`add_files` de pyiceberg, à confirmer au spike S-I-1).
  - Le *name mapping* compense l'absence d'identifiants de champs Iceberg dans nos Parquet (S-I-3).
  - Déclenchement : au commit, si le dataset est marqué « exposé », ou à la demande (action « Publier en Iceberg »).
- **Catalogue** : celui du client (Polaris, Snowflake Open Catalog, Glue) si les fichiers sont dans son stockage. Sinon, **composant optionnel Apache Polaris** (projet Apache de premier niveau depuis le 2026-02-18) :
  - persistance dans une **base dédiée**, pas celle de l'application ;
  - un catalogue Polaris par workspace exposé ;
  - rôles dérivés de l'IAM Agentium ;
  - credential vending vers notre stockage ;
  - activé par `polaris.enabled` dans le chart.
- **Pas d'UniForm.**
  - Selon la documentation Delta, UniForm exige le *column mapping* (protocole lecteur 2 / écrivain 7). Or le column mapping renomme les colonnes physiques des Parquet, ce qui casse la lecture par liste de fichiers (§11) et le protocole minimal (D-21).
  - Côté open source, UniForm passe par delta-spark ; sa prise en charge par delta-rs n'est pas confirmée.
- **Condition préalable incontournable : le stockage doit être joignable par le consommateur.** Un MinIO privé chez le client n'est en général pas joignable par Snowflake (SaaS). L'exposition I2 suppose donc un stockage cloud (S3, ADLS, GCS) ou l'emplacement du client. Sinon, I1 est la seule voie.

### 30.5 Livraison

| Niveau | PR | Prérequis | Drapeaux | Critères d'acceptation (lab) |
|---|---|---|---|---|
| I1 | 2 : lecture, puis écriture | D7 (connexions, runner connecteur), D3 | `connector_iceberg_enabled` | Écrire un dataset dans un Polaris de lab et dans un compte Snowflake de lab (Open Catalog), puis le relire depuis Snowflake via une catalog-linked database, et depuis DuckDB : mêmes lignes, même schéma. Upsert de 100 000 lignes : comptes exacts |
| I2 | 3 : métadonnées Iceberg sur une version Delta ; composant Polaris (chart, base dédiée, rôles) ; action « Publier » et filiation | I1, D3, D4 si identifiants par exécution | `dataops_iceberg_exposure_enabled`, `polaris.enabled` | Un dataset Agentium interrogé sur place par Snowflake et Trino. Aucune copie des fichiers de données. Révocation de l'exposition effective |

### 30.6 Critères pour réexaminer I3 (Iceberg comme format interne)

On réouvre la question si au moins deux de ces conditions sont réunies :
- **la majorité des clients** exigent l'exposition I2 ;
- Delta adopte nativement l'arbre de métadonnées Iceberg (la proposition « Delta 5 / Iceberg v4 » n'est encore qu'une proposition) ;
- delta-rs ou DuckDB perdent leur avance sur l'écriture Python sans service ;
- un catalogue REST devient de toute façon obligatoire chez nous, par exemple pour I2.

L'abstraction de format (`dataset_files`, `open_dataset_arrow`, §11) limite le coût d'une bascule.

### 30.7 Spikes

| Spike | Question |
|---|---|
| S-I-1 | Capacités de pyiceberg sur la version épinglée : `append`, `overwrite` filtré, upsert natif, `add_files`, OAuth2, credential vending ; testées sur Polaris et Snowflake Open Catalog |
| S-I-2 | Bout en bout avec Snowflake : catalog-linked database, lecture et écriture d'une table écrite par Agentium, espaces de noms imbriqués |
| S-I-3 | Identifiants de champs et *name mapping* pour `add_files` sur nos Parquet |
| S-I-4 | Extension DuckDB `iceberg` comme écrivain alternatif : pré-installation hors ligne, `MERGE INTO` |
| S-I-5 | Polaris : persistance dans une base dédiée, correspondance avec les rôles d'Agentium, credential vending vers MinIO |

### 30.8 Sources

- [Snowflake : écriture dans les tables Iceberg gérées en externe (catalog-linked databases), GA oct. 2025](https://docs.snowflake.com/release-notes/2025/other/2025-10-17-iceberg-external-writes-cld-ga)
- [Snowflake : Write support for externally managed Iceberg tables](https://docs.snowflake.com/en/user-guide/tables-iceberg-externally-managed-writes)
- [Snowflake : intégration du catalogue REST Amazon S3 Tables, GA 2026-08-10](https://docs.snowflake.com/en/release-notes/2026/other/2026-08-10-amazon-s3-tables-iceberg-rest-catalog-integration-ga)
- [Snowflake : Horizon Iceberg REST pour moteurs externes, préversion 2026-08-18](https://docs.snowflake.com/en/release-notes/2026/other/2026-08-18-externally-managed-iceberg-tables-horizon-irc-preview)
- [Snowflake : Apache Iceberg tables](https://docs.snowflake.com/en/user-guide/tables-iceberg)
- [Snowflake : configurer une intégration de catalogue](https://docs.snowflake.com/en/user-guide/tables-iceberg-configure-catalog-integration)
- [Snowflake : CREATE ICEBERG TABLE (catalogue REST)](https://docs.snowflake.com/en/sql-reference/sql/create-iceberg-table-rest)
- [Apache Iceberg : procès-verbaux du board (PyIceberg 0.11.0)](https://whimsy-vm9.apache.org/board/minutes/Iceberg.html)
- [Apache Iceberg en 2026 : catalogues et évolutions (RisingWave)](https://risingwave.com/blog/apache-iceberg-streaming-2026)
- [État des catalogues Iceberg, juin 2026](https://amdatalakehouse.substack.com/p/the-state-of-apache-iceberg-catalogs)
- [Delta Lake : UniForm (exigences)](https://docs.delta.io/3.1.0/delta-uniform.html)
- [Delta Lake : UniForm (documentation courante)](https://docs.delta.io/delta-uniform/)
- [Apache Polaris projet de premier niveau](https://www.dremio.com/press-releases/apache-polaris-graduates-to-top-level-apache-project-establishing-the-open-catalog-standard-for-apache-iceberg/)

---

## Annexe A — Couverture de papAI

**Instructions d'import et d'export**

| papAI | Agentium | Lot |
|---|---|---|
| Csv, Excel, Json, Parquet Import | Upload existant | Existant |
| ApiImportStmt | Connecteurs REST et MCP | Hors périmètre |
| MySql, Postgres, Oracle, SqlServer, BigQuery, Snowflake Import | Profils D7 | D7 |
| MongoDb, ElasticSearch, Cassandra | — | Hors périmètre |
| ParquetExportStmt | Téléchargement | D3 |
| Exports vers bases (Append, Overwrite, Upsert) | `connector_write_v1` | D7 |

**Transformations**

| papAI | Agentium | Lot |
|---|---|---|
| CleaningStmt | prepare | D1–D2 |
| UnionStmt | union | D1–D2 |
| GroupByStmt (pivot **mono-colonne** en v1) | aggregate | D1–D2 |
| JoinStmt | join | D1–D2 |
| SplitColumnStmt | Deux nœuds prepare | — |
| SplitRowStmt | split | D1–D2 |
| SqlRecipeStmt | Nœud dbt | Existant |
| SqlExtensionStmt | Nœud SQL, sans paramètres | Existant |

**Profilage**

| papAI | Agentium | Lot |
|---|---|---|
| SampleStmt | sample + échantillon persisté | D1 |
| StatisticsStmt | Profil, avec quartiles ajoutés | D3 |
| MeaningStmt | Types sémantiques | D6 |
| MetadataStmt | `row_count` | Existant |

**Étapes** (les 26) : rename → `rename_columns` ; drop → `drop_columns` ; copy → `copy_column` ; move → `move_columns` ; concat → `concat_columns` ; typecast → `cast` ; dropnull → `drop_nulls` ; fillnull → `fill_nulls` ; dropduplicates → `deduplicate` ; filterrows → `filter_rows` ; numerical et datetime range → `filter_range` ; flagrows → `flag_rows` ; replacevalues → `replace_values` / `map_values` ; countoccurrences → `count_occurrences` ; splitparser → `split_column` ; regexparser → `extract_regex` ; parsedate → `parse_date` ; datetimeextraction → `extract_date_parts` ; round → `round` ; discretize → `bin` ; negate → `negate_boolean` + `to_boolean` ; anonymization → `hash` + `scale` ; orderby → `sort` ; formula → `formula` ; sparksqlextension → nœud SQL ou éjection. Étapes tableaux, maps et `J_*` → D6.

## Annexe B — Codes d'erreur

**Spec et compilation**

| Code | Cas |
|---|---|
| `DATAPREP_SPEC_INVALID`, `DATAPREP_SPEC_VERSION` | Spec invalide, version inconnue |
| `DATAPREP_STEP_UNKNOWN` | Étape inconnue |
| `DATAPREP_COLUMN_MISSING`, `DATAPREP_COLUMN_EXISTS`, `DATAPREP_DUPLICATE_COLUMN` | Colonne absente, déjà existante, en doublon (casse comprise) |
| `DATAPREP_EMPTY_SELECTION` | Sélection vide |
| `DATAPREP_TYPE_MISMATCH`, `DATAPREP_LITERAL_TYPE`, `DATAPREP_CAST_FAILED` | Type refusé, littéral non convertible, conversion échouée |
| `DATAPREP_ORDER_REQUIRED` | Ordre exigé |
| `DATAPREP_FORMULA_INVALID`, `DATAPREP_FORMULA_FORBIDDEN` | Formule invalide, élément interdit (avec position) |
| `DATAPREP_REGEX_UNSUPPORTED` | Regex hors sous-ensemble RE2 |
| `DATAPREP_UNION_TYPES`, `DATAPREP_UNPIVOT_TYPES` | Types incompatibles |
| `DATAPREP_PIVOT_TOO_MANY_VALUES` | Trop de valeurs de pivot |
| `DATAPREP_SPLIT_RATIOS` | Ratios invalides |
| `DATAPREP_PORT_MISSING`, `DATAPREP_PORT_UNNAMED`, `DATAPREP_INPUTS_MAP_FORBIDDEN` | Port non câblé, arête sans nom de port, `inputs_map` refusé |
| `DATAPREP_OUTPUT_NAME_DUPLICATE`, `DATAPREP_OUTPUT_SLUG_TAKEN` | Nom de sortie en doublon, slug appartenant à un autre producteur |
| `DATAPREP_INPUT_UNAVAILABLE`, `DATAPREP_INPUT_FORBIDDEN` | Entrée indisponible, dataset d'un autre workspace |
| `DATAPREP_EJECT_REFUSED` | Éjection refusée (sel) |

**Avertissements** : `DATAPREP_SORT_NOT_LAST`, `DATAPREP_JOIN_NO_EQUALITY`, `DATAOPS_PLACEMENT_DEGRADED`.

**Aperçu et exécution**

| Code | Cas |
|---|---|
| `DATAPREP_PREVIEW_TIMEOUT` | Aperçu trop long |
| `SQL_RESULT_TOO_LARGE`, `SQL_OUTPUT_TOO_LARGE` | Trop de lignes, sortie trop volumineuse |
| `SQL_EXECUTION_FAILED`, `SQL_TIMEOUT` | Échec du moteur, délai dépassé |

**Calcul**

| Code | Cas |
|---|---|
| `DATAOPS_PLACEMENT_UNAVAILABLE` | Placement indisponible |
| `DATAOPS_QUOTA_EXCEEDED` | Quota dépassé |
| `DATAOPS_COMPUTE_LOST`, `DATAOPS_TIMEOUT` | Calcul perdu, délai dépassé |
| `DATAOPS_TYPE_UNSUPPORTED_ON_SPARK`, `DATAOPS_GLOBAL_WINDOW_ON_SPARK` | Type ou fenêtre non portable sur Spark |
| `DATAOPS_SPARK_*` | Une cause par état d'échec de l'opérateur |

**Connecteurs**

| Code | Cas |
|---|---|
| `CONNECTOR_PROFILE_UNKNOWN`, `CONNECTOR_DRIVER_MISSING` | Profil inconnu, pilote absent |
| `CONNECTOR_REGISTRY_REQUIRED` | Registre de secrets non configuré |
| `CONNECTOR_PARAM_INVALID` | Paramètre invalide |
| `CONNECTOR_EGRESS_DENIED` | Hôte refusé par le garde de sortie |
| `CONNECTOR_AUTH_FAILED`, `CONNECTOR_UNREACHABLE`, `CONNECTOR_TLS_FAILED` | Authentification, réseau, TLS |
| `CONNECTOR_PERMISSION_DENIED`, `CONNECTOR_TIMEOUT` | Droits, délai |
| `CONNECTOR_SOURCE_CHANGED` | La source a changé |
| `CONNECTOR_QUERY_FORBIDDEN` | Requête d'auteur refusée |
| `CONNECTOR_READ_ONLY` | Écriture sur une connexion en lecture |
| `CONNECTOR_IMPORT_LIMIT` | Plafond d'import dépassé |
| `CONNECTOR_WRITE_FAILED`, `CONNECTOR_UPSERT_KEYS_REQUIRED` | Échec d'écriture, clés d'upsert manquantes |
| `CONNECTOR_OPTION_FORBIDDEN` | Option hors liste blanche |

## Annexe C — Réglages

**Existants (D0)**
- `celery_dataops_queue`
- `dataops_duckdb_memory_mb`, `dataops_duckdb_threads`
- `dataops_spill_max_mb`
- `dataops_runner_memory_limit_mb`
- `dataops_max_output_mb`
- `dataops_sql_timeout_s`
- `dataops_preview_memory_mb`

**Nouveaux, DataOps**
- `celery_dataops_control_queue`
- `dataops_max_timeout_s`, `dataops_t0_max_timeout_s`
- `dataops_preview_timeout_s`, `dataops_preview_concurrency`
- `dataops_max_steps`, `dataops_max_union_inputs`, `dataops_max_pivot_values`
- `dataops_sample_rows`, `dataops_part_max_mb`, `dataops_write_delta_enabled`
- `dataops_local_max_bytes`, `dataops_local_hard_max_bytes`, `dataops_pod_max_bytes`
- `dataops_compute_enabled`, `dataops_compute_namespace`, `dataops_compute_single_tenant`
- `dataops_spark_enabled`
- `dataops_core_hour_usd`, `dataops_gb_hour_usd`
- `dataops_default_timeout_{local,pod,spark}_s`

**Nouveaux, Iceberg (§30)**
- `connector_iceberg_enabled`
- `dataops_iceberg_exposure_enabled`
- `polaris.enabled` (chart)

**Nouveaux, workspace**
- Drapeau `features.data_prep`
- Politique `settings.dataops`

**Nouveaux, connecteurs** : voir D7.6.

## Annexe D — Reprise par un autre agent (mode opératoire)

> **À lire en premier.** Ce plan se suffit à lui-même.
> - Les mentions « revue C1 », « revue I9 », etc. désignent la revue critique du 2026-10-12. **Ses correctifs sont déjà intégrés au texte** : inutile de la chercher.
> - Les numéros de ligne cités datent du 2026-10-12. Revérifiez-les avant d'éditer.

### D.1 Où sont les choses

| Élément | Emplacement |
|---|---|
| Dépôt Agentium (backend Python/FastAPI/Celery, `frontend-ng/` Angular, `ops/` Helm/Terraform/Ansible, `docker/`, `scripts/`) | `~/Developer/DATATEGY/papAI/omnirag*` (worktrees d'un même dépôt) |
| Worktree d'intégration, branche `demo/agentic` (celle qui est déployée). **Elle peut contenir des fichiers non suivis de l'utilisateur : ne jamais les toucher** | `../omnirag-cost-release` |
| Worktree du lot D0, branche `feat/dataops-d0-engine` (e0cdab0a, 71014222, poussée, **non fusionnée**) | `../omnirag-dataops` |
| Référence papAI **à jour**. `~/Developer/DATATEGY/papAI/` ne contient que des copies anciennes | `~/Developer/DATATEGY/papai-latest/` (`spark-service`, `core`, `ansible`, `frontend`) |
| Audit des connecteurs (22 septembre 2026) | `docs/ops/connector-framework-audit-2026-09-22.md` |
| Code D0 livré | `backend/app/resources/dataops_runner.py`, `backend/app/services/dataops/sql_execution.py`, tests `backend/app/tests/services/test_dataops_sql_execution.py` |

### D.2 Règles Git et livraison (non négociables)

**Git**
- La commande `git` du shell est une fonction cassée. Utiliser **`/opt/homebrew/bin/git`**.
- Sous zsh, une variable contenant des espaces n'est pas découpée : écrire les boucles en **bash**.

**Branches et poussée**
- Une branche par PR, créée depuis `origin/demo/agentic` dans **un nouveau worktree** :

  ```
  /opt/homebrew/bin/git -C ../omnirag-cost-release worktree add ../omnirag-<lot> -b feat/dataops-<lot> origin/demo/agentic
  ```

- Les worktrees ont `origin/demo/agentic` pour upstream. Pousser **toujours avec une refspec explicite** : `/opt/homebrew/bin/git push -u origin <branche>:<branche>`.
- Commiter et pousser le travail en cours tôt : le scratchpad de session est effacé au redémarrage.

**Commits**
- Format : `type(scope): sujet` (ex. `feat(dataops): …`, `test(dataops): …`, `docs(ops): …`), corps qui explique le *pourquoi*.
- Ligne de co-auteur exigée par l'environnement de l'agent.

**Fusion**
- **Toujours sur accord explicite de l'utilisateur**, à chaque fois.
- Elle se fait en `--no-ff` depuis `../omnirag-cost-release`, puis on pousse `demo/agentic`.

**Déploiement**
- C'est **l'utilisateur** qui déploie (VM : `scripts/agentium-vm-deploy.sh`, environ 15 min). Le push ne déploie rien.
- Après le déploiement : `catalog-check` / `catalog-apply` si des Skills changent, et `/api/v1/build-info` (`revision_verified`).

**Bitbucket SSH** : réglé dans `~/.ssh/config`. En cas d'échec : `ssh-add --apple-load-keychain`.

### D.3 Environnement de test local (macOS)

- **Backend** :

  ```
  uv venv --python 3.12 <venv> && uv pip install --python <venv>/bin/python -r backend/requirements.txt -c backend/constraints-demo-app.txt pytest pytest-asyncio
  ```

  Puis, depuis `backend/` : `<venv>/bin/python -m pytest <fichiers> -q -p no:cacheprovider -W ignore`.
- **Infra** : `backend/app/tests/infra` est long (environ 12 min). Le lancer en arrière-plan.
- **Ruff** : `../omnirag-cost-release/backend/.venv/bin/ruff`. Vérifier et formater **seulement les fichiers touchés**, car le dépôt a des écarts préexistants.
- **PostgreSQL réel**, sans Docker :

  ```
  pip install --target <scratch>/pgdeps --python-version 3.12 --only-binary=:all: --no-deps pgserver
  ```

  Puis `initdb` et `pg_ctl` sur le port 55432 (socket Unix désactivé).
- **Frontend** : `export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22`.
  - Dans un nouveau worktree, faire un lien vers `node_modules` : `ln -s ../../omnirag-cost-release/frontend-ng/node_modules node_modules`, ignoré par git.
  - Tests : `npm run test:unit` (specs **enregistrées** dans `scripts/run-unit.mjs`), `npm run check:i18n`.
  - **`build:prod` une seule fois par lot**, à la fin.
- **e2e mocké** :

  ```
  E2E_CHROME_V2_MOCKED=1 E2E_CHROMIUM_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" E2E_BASE_URL=http://127.0.0.1:4300
  ```

  Servir le build par `PORT=4300 node e2e/serve-dist.mjs`. Une URL contenant « localhost » relance `ng serve`.
- **Pièges de test connus** :
  - dans `<ck-data-table>`, cliquer une colonne via `[data-testid=column-select][data-name=…]` (le nom ouvre une infobulle) ;
  - utiliser `exact: true` pour les boutons homonymes ;
  - le mode `worker_eager_mode=True` (monkeypatch) exécute les tâches Celery dans le test.
- **Machine** : disque presque plein (environ 6 Go libres). Ne générer de gros jeux de données que dans le scratchpad, puis les supprimer.
- **Agents en parallèle** : 2 ou 3 au maximum (au-delà, la limite d'usage tombe vite).

### D.4 Conventions de code

- Écrire comme le code voisin. Les docstrings et commentaires expliquent le **pourquoi**. Mêmes conventions de nommage.
- Toute limite devient un réglage `app/core/config.py`. Tout refus a un code `CODE: message`, traduit côté front (`flow.dataprep.error.<CODE>`).
- **i18n FR/EN systématique** (`core/i18n/*.dict.ts`, parité imposée par le typage).
- **Interface sobre (Tokens v2)** : neutre par défaut, l'ambre et le rouge réservés aux vrais signaux.
- `/api/v1/build-info` est une attestation publique à forme exacte : ne rien y ajouter.
- Nouvelle dépendance Python : `backend/requirements.txt` + pin dans `backend/constraints-demo-app.txt` (vérifié par `test_demo_dependency_constraints.py`). Mesurer les images (`scripts/agentium-image-budget.sh`).
- Nouvelle Skill : entrée dans `seed.py`, ligne `_REGISTRY` dans `services/skills_registry/wrappers/registry.py`, `SKILL_CATEGORIES`, capacité. Le test `test_every_seeded_slug_has_a_wrapper_and_a_category` doit rester vert.
- Nouveau bloc graph-owned : `_GRAPH_OWNED_BLOCKS` (`dag.py`) + `GRAPH_OWNED_CONFIG_SKILLS` (`execution_contract.py`). Leur égalité est testée dans `test_run_engine_dag_graph.py`.
- Nouveau service Compose ou worker : le reporter dans
  - `scripts/agentium-vm-deploy.sh` (liste de `up`, contrôle de stockage) ;
  - `scripts/agentium_runtime_env_bundle.py` (`VM_APPLICATION_STORAGE_MOUNTS`) ;
  - les overlays `docker/compose.agentium.{openbao,registry}.yml` ;
  - les tests `backend/app/tests/infra/test_agentium_vm_storage_guard.py` et `test_openbao_compose.py` ;
  - le chart (`ops/helm/agentium`), `ops/scripts/check-k8s-scaffold.sh` et `docs/agentium-release-process.md`.

### D.5 Premières actions, dans l'ordre

1. **S0** (§23) : une PR autonome depuis `origin/demo/agentic`. Signaler à l'utilisateur le token Docker Hub de papAI à révoquer.
2. **Finitions de D0** (§23) dans `../omnirag-dataops` (si le worktree a disparu : `/opt/homebrew/bin/git worktree prune`, puis le recréer depuis la branche distante `feat/dataops-d0-engine`). **Rebaser d'abord sur `origin/demo/agentic`**, puisque la branche part de 70a78810. Ensuite :
   - corriger `ops/scripts/check-k8s-scaffold.sh:41` et `docs/ops/agentium-kubernetes.md:27` ;
   - ajouter `placement` aux clés publiques de filiation ;
   - `PDEATHSIG` ;
   - `consumer_timeout` ;
   - relancer les tests, pousser, **demander l'accord de fusion**.
3. **D1a-a**, en commençant par les spikes S-D1-1 et S-D1-2 :
   - commiter le rapport de spike dans `docs/` ;
   - puis la spec, le compilateur, le typage et le runner v2 ;
   - corpus golden sous `backend/app/tests/dataops/golden/`.
4. Pour chaque lot, dans cet ordre :
   - PR découpées selon §23 ;
   - tests §22 ;
   - documentation §28 ;
   - ligne du tableau §21 (migration, `catalog-apply`, images, retour arrière) dans la description de la PR ;
   - **accord de l'utilisateur avant toute fusion**.
