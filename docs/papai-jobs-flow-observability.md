# papAI : suivi des jobs et processus, timeline et état des nœuds du flow

> **Date** : 2026-10-15.
> **Base** : `demo/agentic` (origin = 47e289da).
>
> **Sources**
> - Lecture seule de `~/Developer/DATATEGY/papai-latest`, faite le 2026-10-15. Ont été lus le frontend Angular, `core` (Scala), `spark-service`, `papai-ml` et `scheduler-service`.
> - Les numéros de ligne cités datent de ce jour : **revérifiez-les avant de vous en servir**.
> - Les points marqués **(inférence)** viennent de la lecture du code. Ils n'ont pas été exécutés.
>
> **Abréviations de chemins**
> - `CORE` = `core/core/src/main/scala/com/datategy`
> - `MIG` = `core/migrations/src/main/resources/migrations`
> - `SSB` = `spark-service/src/main/scala/modules/batch`
> - `PML` = `papai-ml`
> - `FE` = `frontend/src/app`
> - `FEP` = `frontend/packages`
>
> **Objet.** Décrire comment papAI rendait visible l'avancement des traitements. Trois questions :
> 1. Qu'est-ce qu'un job et un processus, et comment leur statut évolue-t-il ?
> 2. Comment l'avancement remonte-t-il du moteur de calcul jusqu'à l'écran ?
> 3. Comment le flow affiche-t-il l'état de ses nœuds, et quelle « timeline » l'utilisateur avait-il ?
>
> Le §9 compare avec Agentium et dit ce qu'il faut garder ou éviter.

---

## 0. Lecture rapide

**Le modèle.**
- Les données suivent trois niveaux : **groupe de processus → processus → jobs**.
- Un **job** est une unité de calcul sur **une étape** du flow (`step_id`). C'est, par exemple, l'échantillon d'un dataset, ses statistiques, ou l'exécution d'une opération.
- Un **processus** regroupe les jobs d'une même action utilisateur ou d'un même déclenchement planifié.
- **Il n'existe pas d'entité « run de flow ».** Un run est un processus. Le flow est unique par projet, et il est mutable.

**La progression.**
- La progression est faite de **statuts, pas de pourcentages**.
- Il y a six statuts de job : `PENDING`, `WAITING`, `RUNNING`, `AVAILABLE`, `ERROR`, `CANCELLED`.
- Un statut terminal est définitif.
- Le statut d'un processus est **calculé** : c'est le statut de plus fort poids parmi ses jobs. L'ordre est erreur > annulé > en cours > en attente > disponible.
- Aucune progression numérique réelle n'existe : la route Python renvoie `0.42` en dur.

**La remontée.**
- Les moteurs **poussent** leurs changements d'état vers `core` par des routes privées : `spark-service` au début et à la fin d'une instruction, `papai-ml` à chaque message de progression.
- `core` met à jour le job. Il met aussi à jour l'état du nœud, stocké dans le JSON du flow. Après le commit, il publie un événement.
- Le frontend reçoit **un flux SSE par projet**, qui porte trois types d'événements.

**L'état des nœuds.** Il combine deux couches :
- une **couche persistée** dans le flow : statut de l'opération, existence de l'échantillon et des fichiers, statistiques et sens calculés ;
- une **couche dérivée côté client** : un service Angular recalcule sept états à partir du flow, des derniers jobs par étape et du flux SSE.

La couche client contient beaucoup d'heuristiques, qui compensent les incohérences du backend.

**La « timeline ».**
- C'est la **page Jobs**. Elle montre la liste des processus, et pour un processus le tableau de ses jobs triés par date de début, un onglet « Flow » qui situe l'étape dans le graphe, et un onglet « Logs ».
- S'y ajoute **l'activité d'un dataset** : les processus en amont, sur le dataset lui-même et en aval.
- Il n'y avait ni vue chronologique d'un run sur le graphe, ni photo de l'état des nœuds par run.

**Les faiblesses majeures (§8).**
- Pas de rejeu SSE : un client qui se reconnecte perd les événements.
- `startedAt` est réécrit à chaque ping « en cours ».
- Une opération repasse en `pending` à chaque ping.
- Le nettoyeur de jobs zombies modifie la base sans prévenir l'écran.
- Un arrêt pour délai dépassé est présenté comme une annulation.
- Un run planifié en échec envoie un e-mail de succès **(inférence)**.
- On compte huit vocabulaires de statuts.

---

## 1. Le modèle : groupe, processus, job

```
process_groups ──(cron)──┐            flows (1 par projet, steps = JSONB)
  id, cron_job_id?,      │              └── steps[step_id] : DataSetStep | OperationStep | …
  user_id?               │                                  ▲
                         ▼ (lien implicite : session_id)    │ step_id (pas de FK)
processes ──────────────────────────► jobs ─────────────────┘
  id, name (ProcessKind),            id, process_id (FK, cascade), job_kind, engine,
  project_id, session_id,            status, started_at, completed_at, logs (texte d'erreur),
  created_by, cancelled_at,          step_id, step_type, run_id?, credit_cost?,
  lightweight                        ressources Spark (driver/exécuteurs)
```

| Entité | Où | Ce qu'il faut savoir |
|---|---|---|
| `jobs` | `MIG/V027.0__Add_job_logs.sql:23-38`, enrichie par V067 (`run_id`), V108 (`credit_cost`), V150 (`engine`) et V156 (ressources Spark) | Classe `CORE/domain/model/process/Job.scala:20-35`. Un job naît `WAITING` (`Job.scala:106-113`). Il porte environ 60 **types** (`JobKind`, `Job.scala:229-334`), regroupés par traits : `OperationExecJob` (exécution d'une opération), `ExecJob` (entraînement, séries temporelles), `InternalJob` (échantillon, statistiques, sens, export Parquet, aperçu) et `FileImportJob`. Il y a trois **moteurs** : Spark, Python et `core` (SFTP, bucket). |
| `processes` | `MIG/V027.0:10-21`, puis V031 (`cancelled_at`), V065 (`name`) et V088 (`session_id`) | Classe `CORE/domain/model/process/Process.scala:19-30`. **Pas de colonne de statut** : il est calculé (§2). Le nom vient d'un `ProcessKind` : `OperationExecution`, `FileImport`, `MachineLearningTrain`, `SampleUpdate`, etc. Un nom illisible devient `CorruptedProcess`. |
| `process_groups` | `MIG/V027.0:1-8`, V045 | Deux variantes : `CronProcessGroup` et `ManualProcessGroup`. Seule la première sert. Un run planifié rattache son processus au groupe **seulement** par `processes.session_id = process_groups.id`. `process_group_id` n'est pas renseigné (`CronJobInstance.scala:85-98`). |
| `flows.steps` | `MIG/V001.0__Init_schema.sql:66-75` | Le flow est un JSONB **unique par projet**, sans version. L'état persisté des nœuds y vit (§5.1). `jobs.step_id` pointe dans ce JSON, sans clé étrangère. |

**Côté moteurs**, chacun a sa table et son vocabulaire. La clé de corrélation est partout l'identifiant du job dans `core`.
- `spark-service` utilise `batches` et `statements`, avec `metadata_job_id` comme clé. Ses statuts sont `waiting`, `running`, `available`, `error`, `cancelled` et `killed` (`spark-service/public/main/confs/FlywayConf/migrations/V3__SparkServerless.sql:20-33`).
- `papai-ml` utilise `celery_tasks`, avec `task_id` comme clé. Ses statuts sont `PENDING`, `RUNNING`, `SUCCESS`, `FAILURE` et `REVOKED`. La table a aussi `progress_message` (150 caractères), `logs` et `metrics` (`PML/connections/database/models/celery_tasks.py:14-45`).

---

## 2. Les statuts et leurs transitions

### 2.1 Le statut d'un job

Définition : `CORE/domain/model/process/Job.scala:213-227`.

| Statut | Ordre | Poids | Sens | Affichage (page Jobs) |
|---|---|---|---|---|
| `PENDING` | −1 | −1 | « Only used as dummy DTO » | horloge orange |
| `WAITING` | 0 | 1 | créé, en file | horloge orange « Waiting » |
| `RUNNING` | 1 | 2 | en exécution | flèches qui tournent, « Running » |
| `AVAILABLE` | 2 | 0 | succès | coche verte « Success » |
| `ERROR` | 2 | 4 | échec | croix rouge « Failed » |
| `CANCELLED` | 2 | 3 | annulé | cercle barré gris « Cancelled » |

**La règle de transition** est `newStatus.ordinal > ordinal || this == newStatus`.
- On ne fait qu'avancer, et un statut terminal ne bouge plus.
- `RUNNING → RUNNING` est permis. Avec `running()`, qui réécrit `startedAt`, cela crée le défaut n° 2 du §8.
- Les méthodes `running`, `success`, `fail` et `cancel` lèvent `InvalidJobStatusTransitionException` si la règle n'est pas respectée (`Job.scala:36-79`).
- `forceStatusChange` contourne la règle (`Job.scala:81-88`). Les chemins de débogage s'en servent.

### 2.2 Le statut d'un processus

`ProcessDetails.fromProcess` prend **le statut de plus fort poids** parmi les jobs (`CORE/application/dto/JobDto.scala:117-147`). L'ordre est :

**ERROR > CANCELLED > RUNNING > WAITING > AVAILABLE**

Un processus est donc « Success » seulement si tous ses jobs le sont. Un seul job en erreur le rend « Failed », même si les autres jobs tournent encore.

Le commentaire du code inverse les poids de `Running` et `Waiting`. Le code, lui, est correct.

### 2.3 La chaîne de traduction

Un même fait change de nom en traversant la plateforme :

| Couche | Vocabulaire | Référence |
|---|---|---|
| Spark (base) | `waiting`, `running`, `available`, `error`, `cancelled`, `killed` | `SSB/shared/statementsrep/StatusVo.scala:9-18` |
| Spark → `core` | `killed` est **renvoyé comme `cancelled`** | `SSB/shared/o2cstatementssyncersvc/O2CStatementsSyncerSvc.scala:57` |
| Celery → `core` | PENDING→`waiting`, RUNNING→`running`, SUCCESS→`available`, FAILURE→`error`, REVOKED→`cancelled` | `PML/connections/celery/task_tracker.py:170-181` |
| `core` (réception) | `StatementStatus`, en minuscules | `CORE/application/service/dto/StatementStatus.scala:7-17` |
| `core` (job) | `Job.Status`, en majuscules | §2.1 |
| `core` (nœud opération) | `OperationStatus` : `pending`, `available`, `error`, `cancelled` | `CORE/domain/model/flow/FlowStep.scala:204-211` |
| `core` (nœud dataset) | `DatasetInfoStatus` : `NOT_COMPUTED`, `COMPUTED`, plus des booléens `exists` | `CORE/domain/model/flow/DatasetInfoStatus.scala:7-11` |
| Frontend (nœud) | `waiting`, `running`, `error`, `cancelled`, `available`, `availablewithoutstats`, `computingstats` | `FE/core/services/flow-items-status-handler.service.ts:11` |
| Frontend (événement) | types de job « hérités » (`MEANING_CALCULATION`…) ramenés à des types « synthétiques » (`MEANING_COMPUTE`…) | `FE/core/services/server-sent-event/project-sse.service.ts:210` |

À cela s'ajoutent `JobStatus` (acteur cron), `CronJobStatus` (MLOps) et deux copies de `ModelInterfaceLifeStatus` (builder-service et scheduler-service).

---

## 3. Un run de bout en bout

```
Utilisateur / cron / surveillance de dossier
        │  POST /api/v1/flows/{flowId}/operations/{operationId}
        │       { milestoneRunParam, operationsToSkip, skipExport }
        ▼
core : TaskBuilder (parcours, tri topologique, fusion des lots Spark)
       crée le Process + TOUS les jobs en WAITING ──► SSE JOB_ADDED_TO_PROCESS + STATEMENT_STATE
        │
        ├── Spark : POST spark-service /statements/create ─┐
        └── Python : tâche Celery (papai-ml) ──────────────┤
                                                           │ exécution
   spark-service : PUT /api/private/v1/jobs/spark-status ◄─┤ (début et fin)
   papai-ml      : PUT /api/private/v1/jobs/py-status    ◄─┘ (à chaque message de progression)
        │
        ▼
core : updateJobFromComputeApp
       1. transition du job (§2.1)
       2. handleJobStatus → état du nœud dans flows.steps (§5.1)
       3. StatementUpdated → publié APRÈS commit ──► SSE PROCESS_STATUS_UPDATE + STATEMENT_STATE
        │
        ▼
SequentialOperationsExecutor : tâche suivante, même après un échec
        ▼
Fin du run (cron : ProjectCronJobExecuted → e-mail)
```

**1. Déclenchement.**
- Manuel : `POST /api/v1/flows/{flowId}/operations/{operationId}` (`CORE/.../FlowOperationsApi.scala:390-417`). Le frontend l'appelle depuis `FEP/shared/src/services/flow-container-execution.service.ts:43-81`.
- Le corps choisit le **périmètre du run** :
  - `RUN_FROM_SOURCE` : tout l'amont ;
  - `RUN_FROM_NEAREST_MILESTONE` : depuis le jalon le plus proche ;
  - `RUN_FROM_STEP_ID` : depuis une étape donnée ;
  - `RUN_DOWNSTREAM_STEPS` : les étapes en aval.
  - À cela s'ajoutent les opérations à sauter et l'option de sauter l'export.
- Un **jalon** est un dataset persisté (fichier ou base), un registre, un bucket ou un dataset de connexion (`CORE/domain/model/flow/FlowTraversalPredicate.scala:46-59`).
- Planifié : une tâche db-scheduler `run-subflow` passe par la file RabbitMQ `cron`, puis par `ProjectsCronJobsManager`, puis par `CronJobInstance` (`CORE/infrastructure/cron/flow/`). La surveillance d'un dossier SFTP déclenche le même chemin toutes les 5 minutes, quand l'empreinte des fichiers change.

**2. Préparation.**
- `TaskBuilder.buildTaskQueue` trie les étapes et fusionne les tâches Spark consécutives en un lot (`CORE/infrastructure/cron/flow/TaskBuilder.scala:162-212`).
- **Tous les jobs du run sont insérés d'emblée en `WAITING`.** L'utilisateur voit donc tout de suite la liste complète de ce qui va tourner.

**3. Soumission.** Le lot Spark part par `POST {spark}/api/v1/spark/statements/create`, le Python par Celery. L'identifiant du job sert de clé de corrélation partout.

**4. Remontée, par poussée.** Cela remplace un ancien mécanisme d'interrogation (core `CHANGELOG.md:121`, version 1.0.3).
- `spark-service` pousse **deux fois par instruction**, au début et à la fin, puis sur annulation ou arrêt forcé. Un échec d'envoi n'est que journalisé.
- `papai-ml` pousse **à chaque** `update_progress`. On compte 91 appels dans les modèles. Chaque envoi porte `logs` (message de progression et journal) et `metrics`.
- `core` interroge **aussi** les moteurs : Spark toutes les 5 s, Python toutes les 2,5 s. Il le fait seulement pour savoir quand passer à la tâche suivante, sans rien enregistrer.

**5. Traitement dans `core`.** `ProcessApplication.updateJobFromComputeApp` (`CORE/application/ProcessApplication.scala:295-333`) :
1. Il applique la transition. Les horodatages fournis par le moteur sont **ignorés** : on prend `Instant.now()`.
2. Il met à jour l'état du nœud dans le flow (§5.1).
3. Il ajoute un événement `StatementUpdated` au contexte. Cet événement n'est publié **qu'après le commit** de la transaction (`CORE/infrastructure/database/configuration/SlickDbService.scala:31-37`).

**6. Enchaînement.** `SequentialOperationsExecutor` passe à la tâche suivante **même après un échec** (`CORE/infrastructure/cron/flow/SequentialOperationsExecutor.scala:173-180`). Dans un lot Spark, une instruction en échec n'arrête pas non plus les suivantes (`SSB/runner/RunnerSvc.scala:142`).

---

## 4. Le canal temps réel : un flux SSE par projet

### 4.1 Côté `core`

- **Route** : `GET /api/v1/projects/{projectId}/events?token=<jwt>`.
  - Le jeton passe **dans l'URL**, parce que `EventSource` ne permet pas d'en-tête (`CORE/infrastructure/web/routes/external/ProjectApi.scala:137, 246-271`).
  - Un battement de cœur part toutes les 10 s.
- **Diffusion.**
  - Si la messagerie est activée, chaque projet a un *stream* RabbitMQ avec `max-age = 1m` (`core/core/src/main/resources/configs/rabbitmq.conf:14`). Les consommateurs lisent à partir de **maintenant** et filtrent `timestamp >= now`. **Il n'y a donc aucun rejeu** : un client qui se reconnecte perd ce qui s'est passé entre-temps.
  - Sinon, la diffusion passe par le bus d'événements Pekko en mémoire, qui ne marche que sur un seul nœud.

| Type SSE | Contenu | Émis quand |
|---|---|---|
| `STATEMENT_STATE` | `{jobId, state (MAJUSCULES), statementType (= type du job), logs?, metrics?, attributes}`. `attributes` vaut `{dataSetId}`, `{stepId}` pour une opération, `{experimentRunId, dataSetId}` pour le ML, ou `{connectionDatasetId}`. | à la création du job et à chaque changement (`CORE/infrastructure/event/project/dto/StatementState.scala:11-50`) |
| `ENTITY_STATE_UPDATE` | `{entity: ProcessDetails complet avec ses jobs, statementType: JOB_ADDED_TO_PROCESS ou PROCESS_STATUS_UPDATE, metadata: {newJobId ou modifiedJobId}}` | idem. C'est le **processus entier** qui est renvoyé. |
| `FLOW_CHANGED` | `{flowId}` | modification de la structure du flow par un coéquipier |

### 4.2 Côté frontend : un adaptateur qui normalise

`SseService` ouvre l'`EventSource` (`FE/core/services/server-sent-event/sse.service.ts:28-56`). `ProjectSseService` (`project-sse.service.ts`) l'ouvre une fois par projet, puis répartit les événements dans des sujets RxJS :

| Sujet | Contenu | Consommateurs |
|---|---|---|
| `processes$` | événements de processus | page Jobs, compteur du menu |
| `state$` | tout événement d'état | tableau des jobs, `RunProgressComponent` (runs ML) |
| `statementState$` | événements **normalisés** par étape | état des nœuds du flow (§5.2), écran dataset |
| `flowChanged$` | changement de structure | rechargement du flow |
| `metrics$` | métriques d'entraînement, par run | suivi des runs ML (arrêt anticipé `train_end`) |

L'adaptateur **corrige le backend** à trois endroits :
1. **Il fabrique des `statementState` à partir des événements de processus.** Le backend envoie certaines mises à jour (sens, statistiques, échantillon) seulement comme `PROCESS_STATUS_UPDATE`. L'adaptateur retrouve le job modifié par `metadata.modifiedJobId` et émet un événement d'étape (lignes 89-99). Il fait de même pour `JOB_ADDED_TO_PROCESS`, afin d'afficher `WAITING` tout de suite chez les autres utilisateurs (lignes 80-88).
2. **Il ramène les types de job à un vocabulaire synthétique** (ligne 210) :
   - `SAMPLE_CREATION` → `SAMPLE_COMPUTE`
   - `MEANING_*` → `MEANING_COMPUTE`
   - `STATS_*` → `STATISTIC_COMPUTE`
   - tout job d'une étape opération → `OPERATION_EXECUTION`
3. **Il filtre** `IMPORT_FROM_PARQUET_FILE`, un rechargement interne qui ferait clignoter le dataset en « en attente » (ligne 192). Il réécrit aussi les apostrophes des métriques avant de les lire en JSON (ligne 111).

---

## 5. L'état des nœuds du flow

### 5.1 La couche persistée, dans le flow

Champs portés par les étapes (`CORE/domain/model/flow/FlowStep.scala`) :
- **Opération** :
  - `status`, qui vaut `pending` par défaut ;
  - `previewOutDateWarning`.
- **Dataset** :
  - `fileSystemRef.exists` et `computedAt` ;
  - `settings.sample.fileRef` ;
  - `infoStatus.statsStatus` et `infoStatus.meaningsStatus` (`NOT_COMPUTED` ou `COMPUTED`) ;
  - `rowCount`.

Ces champs sont mis à jour par `ProcessApplication.handleJobStatus` (`CORE/application/ProcessApplication.scala:245-293`) **à chaque retour de moteur** :

| Type de job | Effet sur le nœud |
|---|---|
| `SampleCreation` | dataset : `sample.exists = succès` |
| `ExportToParquet`, `ImportFromParquetFile` | dataset : `fichier.exists = succès` |
| `MeaningCalculation`, `StatsCalculation` | dataset : `COMPUTED` si succès, sinon rien |
| tout `OperationExecJob` | opération : `available`, `error` ou `cancelled`, et **`pending` pour tout autre statut**. Hors lots Spark et recettes de modèle, chaque dataset de sortie reçoit aussi `exists = succès`. |

Trois conséquences :
- **Clignotement.** Chaque ping `RUNNING` remet l'opération à `pending` et marque ses sorties comme inexistantes. L'état persisté clignote pendant l'exécution.
- **Pas d'événement de flow.** Cette mise à jour n'émet pas `FLOW_CHANGED`. L'écran l'apprend seulement par les événements de job.
- **Remises à zéro.** Modifier une opération la remet à `pending` et arme l'alerte « aperçu périmé » (`CORE/domain/model/flow/Flow.scala:658-659`). Lancer un lot réinitialise l'échantillon et les statistiques des sorties (`CORE/application/TaskApplication.scala:69-102`). **Il n'y a aucune propagation « périmé » vers l'aval** : un dataset en aval d'une opération modifiée garde son état.

### 5.2 La couche dérivée, dans le navigateur

`FlowItemsStatusHandlerService` (`FE/core/services/flow-items-status-handler.service.ts`) tient une table `stepId → état`. Elle se remplit en trois temps.

**1. Au chargement du flow** (`deriveStatusesFromFlow`, l. 56) :
- Dataset (`deriveDatasetStatus`, l. 144) :
  - échantillon non calculé → `error` ;
  - statistiques **et** sens calculés → `available` ;
  - sinon → `availablewithoutstats`.
- Opération : `available`, `error` ou `cancelled` repris du flow. `pending` ne donne **aucun état**, et le graphe affiche alors un petit point gris.
- Un état « en cours » déjà connu par le SSE **n'est pas écrasé**. Cela neutralise le clignotement du §5.1.

**2. Rattrapage des runs en cours** (`fetchRunningJobsOnLoad`, l. 91) :
- Appel `POST /api/v1/jobs/{projectId}/latest` avec la liste des étapes. La réponse donne les jobs du **dernier processus** de chaque étape.
- Tout job `WAITING` ou `RUNNING` passe l'étape en `waiting` ou `running`. C'est ainsi qu'on voit un run lancé par un collègue avant d'ouvrir l'écran.
- Pour un dataset déjà construit, seul un recalcul d'échantillon le fait repasser « en cours ». Un recalcul de statistiques ou de sens ne change rien.

**3. En direct**, sur `statementState$` :
- **Opération** (l. 167) : l'état de l'événement **est** l'état du nœud.
- **Dataset** (l. 187) :
  - recalcul des statistiques sur un dataset construit → `computingstats` (sablier orange) ;
  - recalcul du sens → aucun changement ;
  - autre événement actif → `running` ou `waiting` ;
  - **événement terminal** → le client relit l'étape (`GET` de l'étape du flow) et recalcule son état. Deux garde-fous s'appliquent :
    - un dataset déjà construit ne repasse jamais en `error` à cause d'une lecture périmée (l. 232) ;
    - après un échantillon terminé, l'état est plafonné à `availablewithoutstats`, car le flow affiche encore les statistiques de l'exécution précédente.
- Les émissions sont regroupées sur 150 ms et dédoublonnées (l. 24).

**Lancement local.** Quand l'utilisateur lance une opération, le client la marque `waiting` sans attendre le serveur (`updateStatusOfOperationAndItsDatasets`).

### 5.3 Le rendu sur le graphe

`FlowGraphStatusService` (`FEP/shared/src/services/flow-graph-status.service.ts`) traduit l'état en une bande de couleur, une pastille et une infobulle. La légende du canvas affiche :

| Pastille | États |
|---|---|
| verte, sablier | `running`, `waiting` |
| bleue, coche | `available` |
| orange, « ! » (« Partial Success ») | `availablewithoutstats` ; sablier orange pour `computingstats` |
| rouge, croix | `error` |
| grise, tiret | `cancelled`, vide |
| petit point gris | aucun état connu (opération `pending`) |

Remarques :
- **Les couleurs se contredisent d'un élément à l'autre.**
  - Sur la pastille et la bande d'un dataset, le vert signifie « en cours » et le bleu « réussi ».
  - Le point de statut (`getStatusColor`) fait l'inverse : bleu pour « en cours », vert pour « réussi ».
- **Il existe un anneau de progression** (`node.progress`, `getProgressDashOffset`). Pourtant, le canvas principal ne lui transmet pas `inProgressItems` (`FE/modules/flow/pages/flow-container/flow-container-canvas/flow-container-canvas.component.html:18-29`). En pratique, seul l'éditeur de recette affichait une progression, à partir d'événements d'export.
- Dans le panneau latéral, une opération est « en cours » si son propre état l'est. Si elle n'a pas encore d'état, ce sont **ses datasets de sortie** qui comptent : cela couvre l'instant qui suit le lancement (`FE/modules/flow/components/flow-side-bar/flow-side-bar.component.ts:162-190`).

---

## 6. La « timeline » : page Jobs, activité, compteur

### 6.1 La page Jobs

Route `…/jobs` (`FE/modules/jobs/`). C'est la seule vue historique des traitements.

**Colonne de gauche : les processus.**
- Plus récents en tête, chargés par pages de 100 avec défilement infini.
- Chaque ligne montre une pastille de statut, le nom, l'étape concernée avec son icône, l'auteur et une date relative.
- Un processus créé pendant que la page est ouverte arrive par SSE, en tête et marqué « nouveau ». Un processus existant est mis à jour sur place.

**Panneau de détail.**
- **En-tête** : l'étape, l'auteur et l'heure, et un bouton **Annuler** si le processus est `WAITING` ou `RUNNING`.
- **Bandeau** : le statut agrégé, les jobs réussis sur le total, le temps total et, en SaaS, les crédits consommés.
  - Le temps total est la **somme** des `executionTime`, relus depuis un texte comme « 2 minutes 59.665 seconds » (`jobs-monitoring.component.ts:301`).
  - C'est un temps de calcul, pas une durée réelle : les jobs parallèles s'additionnent.
- **Tableau des jobs** : type, statut, début, fin, durée, ressources Spark (driver et exécuteurs) et crédits.
  - Les jobs sont **triés côté client** par `startedAt`, avec la mention « TODO remove reorder when BE reorder process jobs » (`jobs-list-table.component.ts:69`).
  - C'est la « timeline » au sens papAI : **une liste ordonnée**, pas un diagramme.
- **Onglet Flow** : le graphe des données centré sur l'étape du processus, pour situer le run dans le flow. Il montre le voisinage de l'étape, pas l'avancement de chaque job.
- **Onglet Logs** :
  - pour un job en erreur, `errorLog` ;
  - pour les autres statuts, **un message traduit fixe** (« job réussi », « en cours »…) (`jobs-list-table.component.ts:204`).
  - Les messages de progression Python n'y figurent pas, car `core` ne les conserve pas (§7).
- **Liens profonds** : `?runId=` sélectionne le processus qui contient le run, `?jobId=` sélectionne un job.

### 6.2 L'activité d'un dataset

L'activité d'un dataset vient de `GET /api/v1/processes/{projectId}/activity/{stepId}`. L'appel renvoie les processus des étapes en amont, du dataset lui-même et des étapes en aval (`CORE/application/ProcessApplication.scala:562-594`).

Le composant (`FE/modules/datasets/components/activities/activities.component.ts:65`) les présente en un tableau, trié par date de fin, avec trois impacts :
- « Updated dataset » pour l'amont ;
- « Loads dataset » pour le dataset lui-même ;
- « Uses dataset » pour l'aval.

L'auteur s'affiche « You » ou « Someone else ». C'est la seule vue qui relie l'historique des traitements au **lignage** d'un nœud.

### 6.3 Les autres vues

- **Compteur du menu Jobs** : nombre de jobs `PENDING`, `WAITING` ou `RUNNING`. Il est initialisé par un appel qui lit 100 processus, puis tenu à jour par SSE (`FE/core/services/running-jobs-badge.service.ts`).
- **Runs ML** : `RunProgressComponent` filtre `state$` par `jobId` ou `runId` et affiche le statut, avec l'arrêt anticipé quand il est disponible.
- **Runs planifiés** :
  - aucun statut « dernier run » sur la planification ;
  - l'historique passe par `process_groups`, puis par les processus liés via `session_id` ;
  - un e-mail part en fin de run.
- **Rapport d'activité** (administrateur d'organisation) : `GET /api/v1/reports/user-activity`, un export texte des jobs et de leurs erreurs.
- **Purge** : `POST /api/v1/processes` supprime l'historique plus vieux que N jours. C'est la seule politique de rétention.

### 6.4 Ce qui n'existait pas

- **Un run de flow** comme objet : identifiant, périmètre, version du flow, statut final, durée réelle.
- **Une photo de l'état des nœuds par run** : on ne peut pas revoir le flow « tel qu'il était » après tel run.
- **Une vue chronologique** des jobs d'un run, de type Gantt, ou une lecture « pas à pas » sur le graphe.
- **Une progression mesurée.** La route `/progress` de `papai-ml` renvoie `"progress": 0.42` en dur (`PML/engine/api/endpoints/management.py:37`). La seule progression réelle est un texte de 150 caractères, visible en direct seulement.

---

## 7. Annulation, jobs zombies et journaux

**Annulation.** Elle passe par `POST /api/v1/processes/{processId}/cancel` (`ProcessApplication.scala:453-469`).
- Seuls les jobs `WAITING` ou `RUNNING` sont visés.
  - Spark : `PUT …/statements/cancel` ;
  - Python : `POST /kill/{jobId}`, qui révoque la tâche Celery et tue les sous-processus ;
  - `core` : seul le SFTP peut être interrompu.
- `processes.cancelled_at` est posé tout de suite. **Le statut du job, lui, ne change qu'au retour du moteur.**
- Fermer la session d'un projet annule ses processus.
- Depuis le panneau du flow, le frontend retrouve le processus à annuler en cherchant **le premier job de la liste** qui porte l'identifiant de l'étape (`FEP/shared/src/services/flow-container-execution.service.ts:130`). C'est fragile si plusieurs runs touchent la même étape.

**Jobs zombies.** Il existe trois mécanismes :
- **Dans `core`** (`CORE/infrastructure/cron/CleanUpZombieJobs.scala`) :
  - Il tourne toutes les 5 minutes et relit l'état de **tous** les jobs Spark et Python non terminés.
  - Un état introuvable met le job en `ERROR`, avec un message générique.
  - Il écrit **directement en base**, sans événement SSE ni mise à jour du nœud. L'écran reste « en cours » jusqu'au rechargement.
  - **(inférence)** Les jobs encore en file (`WAITING`, pas encore soumis) n'ont pas d'état côté moteur. Ils peuvent donc être passés en erreur au bout de 5 minutes. Comme `ERROR` est terminal, leur passage ultérieur à `RUNNING` sera refusé.
- **Dans `spark-service`** (`SSB/shared/batchsyncersvc/BatchSyncerSvc.scala:27-71`) :
  - Il tue les lots dont le driver ne s'est pas enregistré dans les 300 s, ou qui n'envoient plus de battement (intervalle 60 s, délai 120 s).
  - Ces valeurs sont **codées en dur**, alors que `DEPLOYMENT.md` documente des variables d'environnement.
  - L'arrêt est renvoyé à `core` comme **`cancelled`**.
- **Débogage manuel** : `GET /api/v1/processes/{id}/debug-status` resynchronise un processus depuis les moteurs.

Ni reprise automatique, ni délai maximal côté `core`.

**Journaux.**
- `jobs.logs` ne garde que **le texte d'erreur** : le message Spark sans la pile, ou la trace Python.
- Les messages de progression et les journaux complets Python restent dans `papai-ml`, tronqués à 50 000 caractères.
- La pile Spark et les journaux du driver restent dans la base de `spark-service`, et aucune API ne les expose **(inférence)**.

---

## 8. Limites constatées, à ne pas reproduire

| # | Constat | Effet visible | Confiance |
|---|---|---|---|
| 1 | Pas de rejeu SSE : lecture à partir de « maintenant », rétention d'une minute ; repli sur un seul nœud | une reconnexion fait perdre des transitions ; l'écran reste faux jusqu'au rechargement | code |
| 2 | `running()` réécrit `startedAt` à chaque ping, et les horodatages du moteur sont ignorés | début et durée faux pour les jobs Python, qui pingent souvent | code |
| 3 | Chaque ping `RUNNING` remet l'opération à `pending` et ses sorties à « inexistantes » | l'état persisté clignote ; le client compense (§5.2) | code |
| 4 | Le nettoyeur de zombies écrit sans événement ni mise à jour du nœud | nœud bloqué « en cours » alors que le job est en erreur | code |
| 5 | `killed` (délai dépassé, driver muet) est renvoyé comme `cancelled` | une panne ressemble à une annulation par l'utilisateur | code |
| 6 | Aucune progression mesurée (`0.42` en dur) | anneau de progression inutilisé sur le flow | code |
| 7 | Huit vocabulaires de statuts, et une couche de normalisation côté client | chaque nouveau type de job demande d'enrichir les correspondances du frontend | code |
| 8 | Pas d'entité run de flow, flow non versionné, lien cron ↔ processus implicite | historique impossible à rejouer ; pas de « dernier run » sur une planification | code |
| 9 | Seul le texte d'erreur est conservé | aucune trace a posteriori de la progression d'un job réussi | code |
| 10 | Le runner séquentiel continue après un échec, et une instruction Spark en échec n'arrête pas son lot | tâches lancées sur des entrées manquantes | code |
| 11 | Conséquence du n° 10 : un run planifié se termine `Finished` | e-mail de succès malgré des tâches en échec | inférence |
| 12 | Le nettoyeur peut passer en erreur des jobs encore en file | run long avec de fausses erreurs, puis transitions refusées | inférence |
| 13 | La soumission d'un lot réécrit la ligne du processus, `cancelled_at` compris (`SparkApplication.scala:599-618`) | une annulation faite entre deux tâches peut être perdue | inférence |
| 14 | Le compteur de processus en cours de `getMappedProcesses` utilise `count++` en post-incrément et vaut toujours 0 (`FE/core/services/jobs.service.ts:47`) | sans effet : le badge du menu utilise un autre calcul | code |

---

## 9. Comparaison avec Agentium, et ce qu'on en retient

### 9.1 Ce qu'Agentium a déjà

| Sujet | papAI | Agentium (`demo/agentic`, 47e289da) |
|---|---|---|
| Unité suivie | job sur une étape, regroupé en processus | **Run** (`backend/app/models/run.py`) avec `checkpoints` par nœud, plus **`compute_runs`** pour le calcul (`backend/app/models/compute_run.py`, migration 128) |
| Version du flow | aucune : un flow mutable par projet | `flow_snapshot`, `flow_version_id` et `flow_sha256` sur chaque Run |
| Temps réel | SSE par projet, sans rejeu, jeton dans l'URL | SSE **par run** : `GET /api/v1/runs/{id}/stream`. Il rejoue d'abord les checkpoints persistés, puis envoie un `snapshot`, puis le direct (`backend/app/api/v1/endpoints/runs.py:1575-1590`). Le jeton passe en en-tête, via `fetch` (`frontend-ng/src/app/core/run-stream.service.ts`). |
| Événements de nœud | à déduire des types de job | `run_start`, `node_start`, `node_end`, `hitl_pause`, `hitl_resume`, `run_end` |
| Calcul long | statut, plus un message de 150 caractères | `status`, `stage`, `progress` (JSON), `attempt`, bail (`lease_expires_at`), échéance (`deadline_at`), `cancel_requested`, `outcome_unknown` |
| Coût | crédits par job (SaaS) | `cost_internal`, `provider_cost_usd`, `core_hours` et `cost_usd` par calcul |

### 9.2 Ce qu'il faut retenir pour le suivi des flows DataOps

1. **Un seul vocabulaire d'états, de bout en bout.**
   - Il doit être typé et partagé par le moteur, l'API, le flux et l'écran.
   - Il doit distinguer **inconnu**, **délai dépassé** et **annulé**. Le défaut n° 5 de papAI vient de leur confusion.
2. **L'état d'un nœud est une projection des événements d'un run versionné.** Ce n'est pas un champ du flow réécrit à chaque ping (défaut n° 3). L'état « courant » affiché sur le flow est celui du dernier run sur la version courante.
3. **Les horodatages viennent du moteur et ne s'écrivent qu'une fois.** `started_at` ne bouge plus après la première écriture (défaut n° 2).
4. **Une progression mesurée, ou rien.**
   - Afficher une étape (`stage`) et un message persisté, plutôt qu'un pourcentage inventé.
   - Afficher un anneau seulement si le moteur fournit un ratio réel, par exemple des lignes ou des partitions traitées.
5. **Tout changement d'état émet un événement**, y compris ceux du nettoyeur et des bails expirés. Le flux garde le rejeu qu'Agentium a déjà (défauts n° 1 et 4).
6. **La politique en cas d'échec est explicite et visible dans le run** : arrêter, continuer, ou ignorer telle branche. Un run « terminé avec erreurs » n'est jamais présenté comme un succès (défauts n° 10 et 11).
7. **La timeline est une vue du run, lisible depuis le flow.**
   - Une frise des nœuds, qui montre l'attente, l'exécution, la durée et le coût.
   - Un rejeu de l'état du graphe à un instant donné, possible grâce à `flow_snapshot` et aux checkpoints.
   - La propagation **« périmé » vers l'aval** par le lignage, absente de papAI. Elle se rattache au `needs_requalification` du plan DataOps.
8. **Garder ce que papAI faisait bien.**
   - Créer tous les jobs du run dès le lancement, pour voir d'emblée ce qui va tourner.
   - Rattraper les runs en cours au chargement, pour voir les runs des collègues.
   - L'activité amont, propre et aval d'un dataset.
   - Le lien profond vers un job.
   - Le bandeau de synthèse : statut, réussis sur total, temps et coût.
