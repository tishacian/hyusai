# DataOps D3 — lecture, export et purge des versions

Ce document décrit l'implémentation et son exploitation. Il ne remplace pas les
critères D3 du plan. Le writer Delta reste derrière `DATAOPS_WRITE_DELTA_ENABLED`
et doit rester désactivé tant que le déploiement n'a pas reçu tous les lecteurs.
Aucun déploiement n'est effectué par cette qualification locale.

## Contrat de fichiers

Une version historique conserve sa clé `data.parquet` et son SHA256 des octets.
Une nouvelle version Delta possède un seul commit, `_delta_log/00000000000000000000.json`.
Son identité est le SHA256 exact de ce fichier, pas un hash du dossier ou une
recomposition des partitions. Le journal est l'autorité des fichiers actifs ;
un fichier Parquet absent du journal est ignoré. Les protocoles acceptés sont
reader 1 / writer 2, sans column mapping, deletion vectors ou partitions Hive.
Un deuxième commit, un `remove`, une traversée de chemin ou une entrée dupliquée
provoque un refus. Le journal est limité à 16 MiB.

Les nouvelles empreintes utilisent commit0. `dataset_digest_matches` accepte
également l'ancien composite journal+hashes pour terminer une exécution DataOps
déjà enregistrée. Les références A1 historiques utilisent leur identité native
(version, clé, schéma, cardinalité), qui reste inchangée. Les SHA des anciens
Parquet utilisés par revue de labels, enrichissement et réentraînement sont
conservés.

| Lecteur | Interface D3 |
| --- | --- |
| Tabular `read_frame`, `read_rows`, `read_page` | liste des fichiers actifs, sans fusion préalable |
| SQL / enrichissement | `views[].paths`, empreinte de version |
| Polars / dbt | liste par entrée, anciens manifestes avec chaîne toujours acceptés |
| ML tabulaire, clustering, forecasting, foundation et TabICL | `data_paths`, repli de lecture des anciens `data_path` |
| Comparaison, prédiction et forecast serving / monitoring | helpers communs ou Parquet multi-fichiers |
| Labels LLM, revue, réentraînement | copie bornée des parts et empreinte stable |
| Work charts | projection Arrow Delta ; lecture distante par plages préservée pour legacy |
| Scoring streaming | scanner Arrow sans réencodage ni copie complète préalable |
| Sauvegarde | fichiers cités dans commit0 et manifestes A1, selon le plan de sauvegarde borné |

`dataset_files` retourne les clés actives. `materialize_dataset` retourne une
liste de `Path`, contrôle les tailles et les SHA enregistrés. `open_dataset_arrow`
retourne un dataset Arrow paresseux, local ou S3, après validation du journal ;
une projection ne télécharge pas toutes les parts pour recalculer leurs SHA.
L'ancien `materialize` reste disponible pour les Parquet historiques et refuse
Delta : aucun appel interne ne reconsolide désormais Delta en Parquet.

## Production et publication

Le runner SQL écrit des parts Parquet par sortie avec rotation autour de
`DATAOPS_PART_MAX_MB`, puis delta-rs produit un unique commit0. `PartWriter`
appelle l'API native `convert_to_deltalake` sur son répertoire local privé :
Rust lit les footers, construit les actions et statistiques et commite les
fichiers existants sans réencoder leurs octets. Les sorties vides utilisent
`DeltaTable.create` et gardent un fichier vide de profil hors journal. Le writer
partagé et le runner utilisent la même primitive. Les timestamps Arrow sont
normalisés en UTC avec une précision microseconde au writer Delta ; ceux sans
fuseau sont interprétés UTC. Cela évite `timestamp_ntz` et `timestamp_nanos`,
incompatibles avec le protocole retenu. Le cast est sûr : une valeur portant
des nanosecondes non représentables est refusée avant publication, jamais
tronquée silencieusement. Les autres dates restent typées.

Le profil utilise DuckDB avec mémoire, spill et temps bornés et un seul thread
pour que les groupes de grandes valeurs puissent déborder sur disque. Il compte
exactement les valeurs distinctes par `GROUP BY`, sans approximation. Ses
agrégats fixes lisent les parts Parquet natives, sans recopier la table entière ;
seul le runner de SQL utilisateur matérialise ses entrées avant scellement.
L'aperçu conserve l'ordre des parts avec un scan Arrow borné. Le runner
profile dans son processus supervisé ; les autres producteurs appellent un
sous-processus supervisé. Il conserve cardinalité, nulls, distincts, statistiques
numériques, histogramme, top valeurs et aperçu. Les tailles, schémas Parquet et
cardinalités réelles sont confrontés au journal avant publication. Chaque
sortie garde un sample Parquet limité et son SHA. Ce sample est un sous-ensemble
uniforme des indices de lignes réels, avec graine 42 (`reservoir_seeded`). Les
cellules sélectionnées sont copiées par `take`, avec un plafond de 8 MiB décodés.
Si la sélection dépasse ce plafond, elle est réduite uniformément puis relue ;
on ne conserve jamais seulement les premières lignes qui rentrent.

Les parts sont envoyées avant le commit, qui utilise `If-None-Match: *` en S3.
Le client ne remplace jamais ce PUT conditionnel par un GET suivi d'un PUT.
La génération manuelle des actions JSON, écart D-21 de la première implémentation,
est remplacée par ce commit natif. Cela suit le chemin « écrire les parts puis
commiter » prévu au §29.3 du plan ; l'encodage des parts reste assuré par PyArrow.
Le journal n'est ni reconstruit ni modifié après delta-rs. Les répertoires déjà
remplis, fichiers étrangers et liens de fichiers sont refusés avant conversion ;
les fichiers actifs doivent ensuite être exactement ceux du writer. Les chemins
sont canoniques et l'ordre des parts du journal est repris par le profil et le
réservoir pour assurer des reprises déterministes. Aucun append, retry vers
commit1 ou checkpoint n'est autorisé. Les lecteurs historiques restent compatibles.
Les sorties d'une préparation sont rendues `ready` dans une même transaction
SQL. Un échec laisse toutes les sorties non publiées, même si les premières
parts ou un commit sont déjà présents ; ces objets attendent une purge dédiée.

## Téléchargement et purge

`GET /api/v1/datasets/{id}/download?format=parquet|csv` exige l'accès au workspace
et une version prête. La réponse encode et émet des lots successifs, sans fichier
consolidé sur disque. Le Parquet exporté est portable ; ses octets réencodés ne
constituent pas l'identité historique du dataset.

La retraite logique ne supprime plus les fichiers, même avec le backend local.
Elle refuse un ingest actif et une référence A1 native ou objet qui conserve cette
version. `POST /api/v1/datasets/{id}/purge` exige un administrateur du workspace,
refuse une version prête non retirée et crée une intention durable
`tabular_dataset_purge`. Les requêtes répétées retournent le même job ; l'API
générique des jobs ne peut ni créer ni piloter cette autorité.

L'opérateur exécute `backend/scripts/purge_tabular_dataset.py --job-id <id>` dans
un environnement séparé. Le programme exige `HF_TABULAR_PURGE_ACCESS_KEY` et
`HF_TABULAR_PURGE_SECRET_KEY` pour S3, distincts de l'identité applicative ; ces
secrets restent interdits dans l'environnement commun API/workers. La politique
`tabular-purge` générée par `scripts/agentium_hf_storage_policies.py` autorise les
versions des préfixes `tabular/datasets/*` et `tabular/hub-artifacts/*`, sans droit
sur les knowledge collections. Le programme ne reçoit jamais de préfixe libre.
Il recontrôle workspace, auteur admin, état, version et références A1 sous verrou,
puis supprime les versions S3 et delete markers et finalise le même job.

Le bootstrap Helm active le versioning du bucket et applique Get/Put avec refus
explicite de DeleteObject/DeleteObjectVersion à l'identité applicative. Il
n'installe pas automatiquement de secret de purge. L'application de ces règles
à un cluster existant reste une opération de déploiement séparée.

Deux usages documentaires de `delete_prefix` subsistent hors D3 : récupération
BM25 des campagnes notices et suppression des collections documentaires. Ils ne
reçoivent aucun droit supplémentaire du rôle tabular-purge. La suppression locale
des modèles ML et les identités spécialisées du Hub restent également distinctes.

## Qualification locale reproductible

Les tests `test_dataops_multipart.py` et `test_datasets_api.py` couvrent les parts
réelles, le journal, les empreintes, les harnesses, le streaming, le tenant et A1.
`test_dataops_minio.py` requiert explicitement `D3_MINIO_SESSION`, répertoire privé
d'un MinIO local jetable avec comptes application et purge séparés. Il exerce
les PUT conditionnels concurrents et les refus IAM, sans remplacer S3 par un mock.
Le benchmark `backend/scripts/benchmark_dataops_storage.py` écrit plus de 3 GiB
de données synthétiques, vérifie les téléchargements par SHA et peut lancer le
profil réel avec `--profile` ; il ne crée aucune donnée métier ni approbation.

Le répertoire de MinIO et `TMPDIR` du benchmark doivent être sur un disque réel.
Dans l'environnement cloud de qualification, `/tmp` est un tmpfs : les octets
stockés y consomment la mémoire du cgroup. Les tentatives interrompues sur ce
montage restent des échecs de laboratoire et ne sont pas des mesures de débit
qualifiées. Les rapports conservés indiquent le montage, les budgets, la version
et le SHA du binaire, le nombre de parts, les octets et les limites effectivement
rencontrées. La qualification d'une VM, d'un MinIO distant, du débit réseau réel
et d'une migration de bucket de production reste extérieure à ces tests locaux.

Une première mesure du 13 octobre 2026, conservée comme historique, a terminé sur **3 248 348 018 octets,
25 parts et 790 528 lignes** : lecture lazy, exclusion d'un orphan, téléchargement
vérifié par SHA et profil exact, en 100 s. Le superviseur a observé 1 789 MiB de
RSS pour l'arbre client/profil, sans déclencher ses limites 4 GiB / 900 s.
MinIO avait son propre cgroup 512 MiB / 1 CPU. Le client n'était pas placé dans
un cgroup 4 GiB / 2 CPU ; il s'agit d'une mesure de stockage synthétique locale.

Cette mesure utilisait encore le journal manuel et précédait la correction du sample `head` vers le réservoir uniforme.
Une série de 38 tests ciblés couvre ensuite cette correction, sa borne 8 MiB,
les doublons/NULL, les lecteurs affectés et quatre tests MinIO réels. Ils ne
constituent pas une seconde mesure de volume avec le réservoir final. Les deux
refus du profil avant son passage mono-thread sont également conservés.
Les preuves et limites sont centralisées dans
[`d3-validation.json`](evidence/dataops-completion-2026-10-13/d3-validation.json).
Ce premier laboratoire, ses données et ses credentials privés ont été supprimés.

La qualification finale avec **delta-rs 1.6.6 et le réservoir seedé** a ensuite
réussi sur les mêmes 3 248 348 018 octets, 25 parts et 790 528 lignes en
**84,679 s**. Le commit natif est une opération `CONVERT`, version 0 seule.
Le réservoir contient 1 250 lignes (5 175 351 octets), produit en 6,355 s ;
les SHA des 25 parts téléchargées et le profil exact sont vérifiés. Les
**47 tests ciblés** passent, dont quatre contre MinIO réel et les contrôles
de statistiques natives, de sorties vides, d'abandon, de fichiers étrangers,
de conservation des octets Parquet et d'atomicité des sorties multiples.

Cette exécution finale place le client dans un **vrai cgroup 4 GiB / 2 CPU**,
avec swap désactivé ; MinIO reste à 512 MiB / 1 CPU. Le pic comptable du cgroup
client, qui inclut le cache de fichiers, est de 4 297 986 048 octets
(4 098,88 MiB). `memory.events` rapporte 32 177 événements `max`, aucun `oom`
ni `oom_kill` : le plafond a été atteint sans OOM ni arrêt du traitement.
Ce compteur n'est pas une mesure du RSS des processus.
Les rapports `d3-native-minio-volume*.json`, les logs et les empreintes des
sources sont conservés dans le même répertoire de preuves. Les deux conteneurs,
leurs données temporaires, les binaires et credentials de ce second laboratoire
ont été supprimés après la mesure. Aucune VM ni production n'a été modifiée.
