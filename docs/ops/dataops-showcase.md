# Exploitation DataOps et Showcase

**État de production au 14 octobre 2026 :** l'opérateur rapporte `0e401afc`,
avec préparation DataOps, écriture Delta, contrats et scoring en flux ouverts
globalement. Une sonde Delta d'une ligne a réussi dans `default` ; le scoring
en flux n'a pas encore été exercé. Voir le
[bilan de production](dataops-production-2026-10-14.md), notamment la contrainte
de retour arrière après écriture Delta et l'activation HANA Showcase restante.
Les indications Helm ci-dessous décrivent le profil et ses défauts ; elles ne
remplacent pas cet état effectif de la VM.

Le lot actif prépare le scoring nominal de 2 millions de lignes et le scoring
haut volume de 3 millions. Narration/jugement de 500 unités reste un brouillon
différé à la demande de l’utilisateur, avec `narration_enabled=false`. Gemini via
OpenRouter sera raccordé et qualifié lors d’un lot ultérieur.
Le seed ne produit ni Run de démonstration, ni décision humaine, ni chiffre de
qualité. Les versions sources, modèles, configuration du juge et responsable
doivent exister réellement dans le workspace.

## Worker et stockage

Le chart Helm sépare `agentium-worker-dataops` du worker CPU/recettes : queue
`dataops`, concurrence 1, Beat désactivé, limites 4 GiB et 2 CPU. Le sous-processus
DataOps est limité à 3 GiB pour laisser de la place au parent ; DuckDB dispose
de 1 GiB, 2 threads et 4 GiB de spill. Le scratch est un `emptyDir` disque de
8 GiB. Ce scratch est jetable, jamais le stockage canonique d'un dataset, modèle
ou asset. Le chart impose ObjectStore S3 partagé avec le backend et les workers.

Le worker général ne consomme plus `dataops`. Un override réintroduisant cette
queue fait échouer le rendu Helm. Le worker dédié est présent par défaut, mais
les features DataOps et les contrats ne sont pas activés implicitement. Le profil
`ops/helm/agentium/values-dataops-showcase.yaml` active explicitement les flags de
préparation/Delta/scoring et le watchdog ; les contrats restent activés par
workspace après la préparation des services.

Valider le rendu puis appliquer le processus de release habituel :

```bash
helm template agentium ops/helm/agentium \
  -f ops/helm/agentium/values-dataops-showcase.yaml > /tmp/agentium-dataops.yaml
```

Le rendu et ses tests ne prouvent pas un déploiement. Les limites ne constituent
pas non plus une mesure de débit. Contrôler dans le cluster les OOM, le spill,
l'espace éphémère et les consommateurs de queues avant d'augmenter les réplicas.
Le dataset et son journal Delta restent immuables après publication ; leur
sauvegarde doit inclure les parts, `_delta_log`, les manifests A1 et les lignes SQL
qui les référencent. Ne restaurer aucune de ces références avec des octets d'une
autre version.

## Seed sans résultats inventés

Le workspace doit déjà porter `settings.showcase_seed=true`. Un slug semblable
ne suffit pas. Le responsable doit être un User actif, membre administrateur réel.
Les quatre Skills canoniques doivent être disponibles dans le catalogue.

Depuis `backend`, préparer les brouillons :

```bash
python -m scripts.seed_dataops_showcase \
  --workspace-slug agentium-showcase --owner-user-id "$OWNER_USER_ID"
```

Cette commande crée des Capabilities possédées par le workspace, des Systems,
leurs vrais graphes en `SystemFlowDraft` et des contrats non publiés. Sans
configuration complète, aucun `SystemVersion` publié n'est inventé. Rejouer la
commande conserve les mêmes contrats quand leurs termes sont identiques et
respecte les brouillons modifiés par un opérateur.

Après configuration, la publication est explicite :

```bash
python -m scripts.seed_dataops_showcase \
  --workspace-slug agentium-showcase --owner-user-id "$OWNER_USER_ID" \
  --dataset-id "$DATASET_2M_ID" --high-dataset-id "$DATASET_3M_ID" \
  --model-id "$MODEL_ID" --model-version "$MODEL_VERSION" \
  --starts-on 2026-10-14 --timezone Europe/Paris --deadline 17:00 \
  --publish-services
```

Les noms d'IDs ci-dessus désignent des objets à fournir, pas des valeurs de
démonstration. Les trois prérequis sont évalués séparément : un service incomplet
reste en brouillon et le JSON retourné expose ses codes de blocage. Scoring
vérifie le nombre de lignes annoncé par le dataset prêt, les features et la
version native du modèle. Le seed enregistre les octets de la source dans A1 et une qualification technique
d’intégrité, jamais une qualification métier ou une approbation humaine.
Le contrat sélectionne la source par sa clé logique, la fige à chaque fenêtre
et transmet son identifiant natif. Le graphe exécute réellement `data_prep_v1`
en conservant toutes les colonnes sources, puis `ml_batch_score_v1`, avec version
du modèle figée.

### Narration : recette future, inactive

Le service narration conserve le code de blocage `NARRATION_DEFERRED` tant que
le flag de rollout reste fermé. La suite décrit sa reprise future.

La narration exige un asset source de 500 unités, un endpoint autorisé et sa
révision, une configuration `TypedEvaluationInput` valide et un profil A1
`typed_calibration_profile` actuellement qualifié. Les empreintes de rubrique
doivent correspondre. `--judge-config` fournit une vraie configuration de test
(questions, rubrique, tarif, budget, preuves de test) ; le bridge remplace les
preuves par celles effectivement produites par la narration à l'exécution.
Le budget doit autoriser au moins 500 appels pour `batch_mode=per_unit`.
Le budget cumulé du service est configuré par `--service-budget fichier.json`
(`max_attempts`, `max_cost`, `max_tokens`, `max_seconds`). Sans ce paramètre,
il vaut 2 tentatives, 10 USD, 100 000 tokens et 900 secondes. Si le budget du juge
dépasse cette enveloppe, le service reste en brouillon. Prévoir aussi la part de
la narration ; ce plafond ne garantit pas que 500 unités tiendront dans le délai.

Chaque unité source possède une entrée `evidence` avec le même identifiant et
les champs documentaires réellement applicables : `document_family`, `source`,
`language`, `task`. Ne déclarer `j2450_translation` que pour une véritable
comparaison de traduction. Les images demandent également une route vision A1
qualifiée, fournie par `--vision-route`. L'absence de ces preuves ne peut pas être
réparée en ajoutant une confiance arbitraire.

Le graphe narration relie `narration_run_v1` à `evaluate_v2` via l'asset gouverné.
La sortie est un nouveau candidat avec rapport de jugement. La livraison Work
demande toujours une revue humaine explicite portant sur les empreintes vues.
Le seed n'approuve jamais un candidat et ne crée aucun reçu. Une publication
réussie du Flow reste distincte d'une réussite du moteur externe, à qualifier
selon [le protocole gateway](narration-gateway.md).

## Benchmark de volume

La CLI emploie les vrais services d'ingestion, préparation et scoring ainsi qu'un
modèle natif prêt. Le choix d'une entrée réelle ou synthétique est obligatoire :

```bash
python -m scripts.benchmark_dataops_showcase \
  --workspace-id "$WORKSPACE_ID" --owner-user-id "$OWNER_USER_ID" \
  --model-id "$MODEL_ID" --model-version "$MODEL_VERSION" \
  --synthetic-input --rows 3000000 --varied-inputs --extra-columns 28 \
  --report /var/lib/agentium/benchmarks/dataops-3m.json
```

`--synthetic-input` seul répète en batches bornés les exemples d'entrée enregistrés
avec le modèle. `--varied-inputs` produit des valeurs déterministes dans les plages
numériques de ces exemples, indépendamment du découpage des batches. Les champs
catégoriels réutilisent leurs valeurs enregistrées. `--extra-columns 28` ajoute
un identifiant unique de ligne et 27 valeurs numériques variées, conservées par
la préparation puis le scoring. Les parts Delta gardent leur taille cible normale
de 128 MiB. Ce scénario exerce réellement l'IO de plusieurs parts ; les données
répétées seules se compressent trop pour cela.

Le rapport et la lineage signalent cette construction ; il ne s'agit pas de
trois millions de clients indépendants ni d'une qualification métier. Pour une
base réelle, remplacer ces flags par `--dataset-id` ; le dataset
doit être prêt et porter exactement le nombre de lignes demandé. La CLI refuse
les combinaisons ambiguës. Elle ne crée ni modèle factice ni reçu Work.

Le rapport contient durées des trois phases, cardinalités entrée/préparation/
sortie, nombre de colonnes et de parts Delta, empreintes et mesures mémoire.
Le fichier annexe `.progress.json` garde la dernière phase commencée, utile
lors d'une interruption avant la production du rapport final. L'échantillonnage
RSS utilise les liens PPid de `/proc` toutes les 50 ms ; `sampled_scope` précise
la portée observable. Les pics noyau du parent et des enfants sont rapportés
séparément via `getrusage` et ne doivent pas être additionnés comme s'ils étaient
simultanés. Les buffers caches/noyau hors RSS ne sont pas comptés. Un rapport
local n'est pas une mesure de cgroup 4 GiB en production.

La CLI active les options eager/Delta/streaming seulement dans son processus et
restaure les valeurs ensuite. Elle écrit de vrais datasets et jobs dans le
workspace choisi : utiliser un workspace de benchmark possédé par le responsable,
conserver le rapport et appliquer la politique normale de rétention. Les tests
utilisent une base SQLite et un ObjectStore isolés.

### Mesure locale du 13 octobre 2026

Le cas de test a entraîné un modèle natif avec le harness ML de production, puis
exécuté l'ingestion, la préparation et le scoring réels sur 3 millions de lignes
synthétiques variées, avec 4 features et 28 colonnes supplémentaires. Les
batches contenaient au plus 65 536 lignes ; les colonnes supplémentaires sont
restées présentes jusqu'à la sortie.

| Phase | Durée | Lignes | Colonnes | Parts Delta | Octets Parquet |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ingestion | 59,08 s | 3 000 000 | 32 | 6 | 782 811 016 |
| Préparation | 73,77 s | 3 000 000 | 32 | 6 | 782 811 038 |
| Scoring | 138,36 s | 3 000 000 | 35 | 6 | 788 548 852 |

Le pipeline a duré 271,26 secondes, avec zéro ligne exclue. Le pic RSS visible de
l'arbre de processus était de 3 492 511 744 octets, soit 3,25 GiB. Un superviseur
séparé, échantillonnant toutes les 200 ms, aurait arrêté le processus au-delà
de 4 GiB de RSS ou de 900 secondes ; aucun de ces seuils n'a été atteint.
La durée totale de pytest, comprenant l'entraînement du modèle et les fixtures,
était de 309,10 secondes. Ces résultats sont consignés dans
`dataops-benchmark-3m-varied.json` et son rapport `.supervision.json` produits
pendant la session. Il s'agit d'une mesure locale avec ObjectStore sur disque,
pas d'une preuve de limite cgroup, de quota 2 CPU, de débit S3 ou de qualité métier.

Une première exécution de ce scénario a été interrompue par manque de mémoire
pendant la préparation. Elle a révélé un readahead Arrow échappant au budget
DuckDB ; le résultat ci-dessus a été obtenu après passage des scans au stockage
natif de DuckDB avec spill et réduction du readahead. Un premier cas répétitif,
beaucoup plus compressible, était insuffisant pour révéler ce problème.

Pour reproduire le test d'intégration complet dans l'environnement de développement :

```bash
AGENTIUM_VOLUME_BENCHMARK_ROWS=3000000 \
AGENTIUM_VOLUME_BENCHMARK_EXTRA_COLUMNS=28 \
AGENTIUM_VOLUME_BENCHMARK_VARIED=1 \
AGENTIUM_VOLUME_BENCHMARK_REPORT=/tmp/dataops-benchmark-3m-varied.json \
python -m pytest app/tests/scripts/test_dataops_showcase.py::test_benchmark_uses_real_preparation_and_native_model -q
```

Ce test seul n'installe pas de superviseur mémoire : lancer la mesure dans le
worker isolé prévu pour vérifier les limites de déploiement.

## Watchdog indépendant du scheduler

Un arrêt de Beat ne doit pas faire disparaître une obligation sans Run. Le script
suivant exécute un seul passage, matérialise les fenêtres dues et crée les incidents
canoniques dédupliqués, sans dispatcher de Run :

```bash
python -m scripts.dataops_watchdog --probe-queue \
  --state-file /var/lib/agentium/monitoring/dataops-watchdog.json
```

Lancer ce passage depuis un timer système ou le CronJob Helm indépendant, jamais
comme deuxième scheduler applicatif. `--probe-queue` attend au plus trois secondes
les réponses Celery et signale l'absence d'un consommateur `dataops`. Les incidents
restent internes et affectés au responsable du contrat ; le script n'envoie ni
email ni message. Des incidents déjà ouverts conservent un état `attention`, même
si le passage n'a créé aucun nouvel incident.

Un observateur séparé doit détecter l'arrêt du watchdog lui-même :

```bash
python -m scripts.dataops_watchdog --check-state \
  --state-file /var/lib/agentium/monitoring/dataops-watchdog.json --max-age-seconds 900
```

Codes de sortie : 0 sain, 1 attention, 2 état absent/périmé ou échec. Le fichier
est remplacé atomiquement. Pour le CronJob, surveiller aussi son dernier passage
réussi et ses Jobs en échec via le monitoring Kubernetes ; le CronJob ne prétend
pas vérifier sa propre disponibilité. La résolution des incidents reste une
action opérateur, et n'est pas déduite de l'absence de nouvelles erreurs.
