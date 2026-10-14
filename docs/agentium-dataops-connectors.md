# Complément D7 — Catalogue de connecteurs certifiés

> **Statut** : proposé le 14 octobre 2026 sur `origin/demo/agentic` (`0e401afc`). **Révision 1** du même jour, après la revue de `d3c2a9d3` : identités OAuth, garde réseau HTTP, écritures au résultat inconnu, cohérence des lectures incrémentales, règles de certification, files d'exécution et moyens de qualification. L'annexe D relie chaque point de la revue à sa correction.
> **Rattachement** : complète le lot D7 du [plan DataOps](agentium-dataops-plan.md), ainsi que ses §29.4 (Unity Catalog, Delta Sharing, Databricks SQL) et §30 (Iceberg). Le plan d'origine n'est pas modifié. Les [amendements](agentium-dataops-amendments.md) pointent vers ce document.
> **Règles** : celles de l'annexe D du plan. Une branche par PR depuis `origin/demo/agentic`, poussée avec une refspec explicite, et chaque fusion attend l'accord explicite de l'utilisateur.
>
> Ce document ne vaut ni implémentation ni recette. Un connecteur n'est « certifié » que lorsque ses preuves existent (§11).

---

## 0. Lecture rapide

| Lot | Objectif | Dépend de | PR prévues |
|---|---|---|---|
| **C0** | Prérequis : garde réseau commune aux connexions SQL et HTTP, **activée en `enforce` en production** ; banc de certification en service ; catalogue affiché honnête ; squelettes de l'image des pilotes, des deux files et du kit | — | 4 |
| **C1** | Socle D7.1 à D7.3 : table `connections`, profils déclaratifs avec capacités, page Connexions, registre local des calculs partagé avec DataOps. Migration de PostgreSQL, et de HANA sans qualification | C0 | 3 |
| **C2** | Bases relationnelles, vague 1 : MySQL, MariaDB, SQL Server, Oracle, en lecture puis en écriture | C1 | 2 |
| **C3** | Nouvelle famille stockage objet : S3, compatibles S3 dont MinIO, Azure Blob et ADLS, Google Cloud Storage | C1 | 2 |
| **C4** | Entrepôts cloud, vague 1 : Snowflake et BigQuery, avec leurs comptes de certification | C1 | 2 |
| **C5** | Catalogue des outils : autorisations utilisateur, serveurs MCP officiels, import OpenAPI | C0, C1 | 3 |
| **C6** | Vague 2 : Redshift, Databricks SQL, Unity Catalog, Delta Sharing, Iceberg REST, Synapse ou Fabric, SharePoint et OneDrive, fichiers HTTP | C2, C3, C4 | 4 |
| **C7** | Vague 3 : MongoDB, Elasticsearch ou OpenSearch, Cassandra | C1 | 3 |
| **CH** | Qualification de SAP HANA sur une instance réelle | Banc HANA réel | 1 |

**Ordre** : C0, puis C1. Ensuite C2, C3 et C4 peuvent avancer en parallèle, dans la limite de deux ou trois agents. C5 suit C1, qui livre le modèle de connexion et d'autorisation. C6 et C7 viennent après. CH n'a lieu que lorsqu'une instance HANA réelle est disponible.

**C0 n'est terminé** que lorsque la garde réseau tourne en mode `enforce` sur la production, preuve à l'appui, et que le banc de certification a produit au moins un bundle de preuves. Aucun nouveau profil n'est publié avant.

---

## 1. Pourquoi ce complément

**L'objection est commerciale et récurrente.** Agentium est comparé à des outils qui affichent un très grand catalogue :

| Outil | Ce qu'il revendique publiquement | Nature du catalogue |
|---|---|---|
| Sim | Plus de 1 000 intégrations natives selon sa documentation | Outils SaaS appelés par un agent |
| n8n | De 400 à plus de 1 000 intégrations selon le décompte retenu, plus un nœud HTTP générique | Outils SaaS et automatisation |
| Dataiku | Une trentaine de bases SQL et entrepôts, S3, Azure Blob, Google Cloud Storage, HDFS, FTP et SFTP, HTTP | Sources de données |
| papAI | PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, MongoDB, Cassandra, Elasticsearch, S3, MinIO, GCS, Azure Blob, SFTP, API | Sources de données, import et export |

Ces chiffres sont déclaratifs et se comptent différemment d'un éditeur à l'autre. Ils montrent surtout que **l'objection mélange deux catalogues** :

- **les outils** qu'un agent appelle, terrain de Sim et n8n ;
- **les sources de données** qu'on importe, prépare et alimente, terrain de papAI et Dataiku.

**La décision du 14 octobre.** Les analyses stratégiques conseillaient d'être sélectif sur les connecteurs génériques. L'utilisateur décide malgré tout de faire du catalogue une vitrine, avec une solidité comparable à celle du dépôt SFTP. Ce complément concilie les deux : **une largeur crédible**, obtenue par deux mécaniques distinctes, et un badge qui ne s'affiche que sur preuve.

---

## 2. Existant au 14 octobre (`0e401afc`)

| Élément | État |
|---|---|
| Catalogue affiché (`frontend-ng/src/app/features/resources/resources.catalog.ts`) | Une vingtaine de fiches. Statuts : 5 `active` (SFTP, SharePoint, API REST, calendrier institutionnel, flux visuels), 9 `available`, 3 `beta` (SAP HANA, MCP, pont RPA), 2 `coming-soon`. S3 est `available` sans connecteur dédié dans le code serveur |
| Modèle de connexion | Aucune table `connections`. La configuration vit dans `workspace.settings`, une instance par type |
| PostgreSQL (`services/connectors/generic/`) | psycopg2, `pg_catalog`, plafond de 10 000 lignes, exécution dans le processus web |
| SAP HANA (`services/connectors/hana/`) | Durci par S0 : écritures réservées aux administrateurs autorisés, mot de passe global supprimé, TLS strict, codes fermés. La garde réseau (`network_policy.py`) protège une connexion SQL sur TCP, ne couvre que HANA et reste en mode `report` par défaut. **Aucune instance HANA réelle n'est qualifiée** ; Showcase utilise un mode démo explicite |
| MCP (`services/connectors/mcp/`) | Plusieurs serveurs HTTP par workspace, lecture, aperçu, écritures scellées. Authentification `none`, `bearer`, `oauth_client_credentials` ou `inherit`, avec des secrets **rattachés au workspace**. Aucun flux OAuth utilisateur. Le client HTTP **suit les redirections** sans revalider chaque destination (`client.py`, `follow_redirects=True`). Chaque serveur s'ajoute à la main par son URL |
| Registre de secrets (`services/secrets/registry.py`) | Portées `platform`, `workspace` et `system`. **Aucune portée utilisateur**. OpenBao en option |
| Actifs gouvernés (`services/governed_assets.py`) | Versions pour `dataset`, `model`, `document_set` et `reference`, filiation, requalification propagée aux descendants |
| Contrats de service (`services/service_promises.py`) | Incidents attribués au responsable d'un System, revue humaine, reçus de livraison |
| Exécution locale | Worker `dataops` dédié. Le registre `compute_runs` est prévu en D4 avec les types `connector_read` et `connector_write`, mais n'existe pas encore |
| Intégration continue | Le [processus de release](agentium-release-process.md) indique qu'**aucune CI distante ne tourne** ; `.gitlab-ci.yml` est une configuration, pas un service actif. Les canaris tournent sur l'hôte du runner protégé |
| Plan D7 | Onze profils de bases et de lakehouse. **Aucun stockage objet, aucune base NoSQL**, donc pas de parité avec papAI |

**Ce qui rend SFTP solide.** Le dépôt sécurisé écrit toujours en zone d'attente, et seul un utilisateur autorisé promeut un fichier. Ses 178 tests couvrent :

| Fichier de test | Tests | Ce qu'ils prouvent |
|---|---:|---|
| `tests/services/test_secure_deposit.py` | 43 | Règles du service |
| `tests/api/test_secure_deposit_api.py` | 19 | Contrat HTTP et droits |
| `tests/services/test_secure_deposit_object_staging.py` | 13 | Zone d'attente dans l'ObjectStore |
| `tests/services/test_secure_deposit_workspace_flag.py` | 5 | Activation par workspace |
| `tests/scripts/test_audit_sftp_deploy_boundary.py` | 54 | Audit de la frontière réseau du déploiement |
| `tests/infra/test_agentium_release_a_sftp_positive_canary.py` | 30 | Canari positif sur l'environnement déployé |
| `tests/infra/test_agentium_protected_runner_sftp_acceptance.py` | 9 | Recette par le runner protégé |
| `tests/infra/test_agentium_release_a_sftp_identity_invalidation.py` | 5 | Invalidation d'une identité |

C'est ce niveau qui définit le badge « Certifié » (§11).

---

## 3. Décisions

| # | Décision | Choix retenu | Raison |
|---|---|---|---|
| C-1 | Deux catalogues | **Données** : profils natifs certifiés. **Outils** : serveurs MCP officiels, import OpenAPI, nœud REST | On ne code pas mille intégrations SaaS à la main. On code en profondeur ce qui porte la donnée |
| C-2 | Niveaux de preuve | **Certifié**, **Vérifié**, **Tiers**. Le badge est calculé à partir de preuves qui identifient chaque composant, jamais déclaré | Un chiffre crédible face à un acheteur. Règle d'honnêteté du modèle mental |
| C-3 | Statut `available` | Supprimé pour toute fiche sans preuve. Une fiche sans connecteur est masquée ou marquée « sur demande » | Les fiches actuelles sans backend affaiblissent tout le catalogue |
| C-4 | Stockage objet | Nouvelle famille `object_store` dans D7.3 | SQLAlchemy ne couvre ni le listage, ni les formats de fichiers, ni l'arrivée de fichiers |
| C-5 | NoSQL | Trois familles courtes : `document` (MongoDB), `search` (Elasticsearch, OpenSearch), `wide_column` (Cassandra) | Un adaptateur par famille, comme le veut D7.3, même quand la famille ne compte qu'un ou deux moteurs |
| C-6 | Pilotes et files | Une image dédiée et **deux files** : `connectors_interactive`, avec une capacité réservée aux opérations courtes, et `connectors` pour les imports, exports et écritures. L'API n'importe aucun pilote | Le backend n'a plus que 68 Mio de marge et le worker 85 Mio. Un diagnostic ne doit jamais attendre derrière un import massif |
| C-7 | Garde réseau | Une garde commune à **toutes les destinations** : hôtes SQL, points d'accès de stockage, serveurs MCP, points OAuth, serveurs OpenAPI, fichiers HTTP, et chaque étape de redirection. Activée en `enforce` avant tout nouveau profil | Chaque profil accepte une destination fournie par l'utilisateur. La surface SSRF grandit avec le catalogue |
| C-8 | Connexion et actifs | Un import produit une version d'actif gouverné, avec filiation, empreinte de la source, fraîcheur et niveau de cohérence | Une connexion devient une source gouvernée, pas seulement un appel d'API |
| C-9 | Autorisations | Une autorisation OAuth appartient à **un utilisateur, dans un workspace, pour une connexion**. Une exécution sans utilisateur n'utilise jamais une autorisation personnelle, sauf délégation explicite | Empêcher qu'un consentement serve à quelqu'un d'autre |
| C-10 | Écritures | Chaque écriture porte un **identifiant d'opération stable**. Un résultat perdu donne l'état « inconnu », suivi d'un rapprochement, jamais d'une reprise aveugle | Un append rejoué après une réponse perdue duplique les données |
| C-11 | Exports de fichiers | En v1, **préfixes immuables** et publication finale par manifeste et pointeur. Delta suit son propre contrat | Écraser un préfixe sans supprimer laisse d'anciens fichiers lisibles |
| C-12 | Lectures incrémentales | Chaque profil déclare la cohérence qu'il offre. Le filigrane avance seulement avec le commit de la version | Un simple contrôle du nombre de lignes masque trous et doublons |
| C-13 | Capacités | Chaque profil déclare ses capacités. Le kit teste celles-ci, et teste le refus des autres | Un profil en lecture seule ne peut pas satisfaire des critères d'écriture |
| C-14 | MCP et OpenAPI | Catalogue choisi de serveurs **officiels**, outils filtrés par liste blanche, écritures scellées par défaut. Spécification OpenAPI autonome | Largeur immédiate, avec la gouvernance existante |
| C-15 | Longue traîne des sources | Spike dlt contre PyAirbyte, sans engagement | Possible relais pour des centaines de sources, si licences et taille d'image le permettent |
| C-16 | Communication | On publie « N sources certifiées, M vérifiées, K outils tiers », calculés depuis les preuves | Pas de course au chiffre brut |

**Inchangé** : D7.1 à D7.6, la décision D-18 (pas de JDBC dans le processus Python), les règles d'écriture de D7.4, les §29.4 et §30.

---

## 4. Catalogue des données : couverture par vague

Le pilote indiqué est un candidat. Sa licence et sa taille dans l'image se confirment au spike S-C2 (qui prolonge S-D7-3). Les capacités suivent le format du §7.

| Profil | Famille | Pilote candidat | Capacités visées | Banc de test | Vague |
|---|---|---|---|---|---|
| `postgresql` | `sqlalchemy` / `adbc` | psycopg2, ADBC PostgreSQL | Lecture partitionnée, incrémentale, append, overwrite, upsert | Conteneur | 1 (migration) |
| `mysql`, `mariadb` | `sqlalchemy` | pymysql | idem | Conteneurs | 1 |
| `sqlserver` | `sqlalchemy` | pymssql | idem | Conteneur | 1 |
| `oracle` | `sqlalchemy` | oracledb, mode thin | idem | Conteneur Oracle Free | 1 |
| `sap_hana` | `sqlalchemy` | hdbcli, sqlalchemy-hana | idem, derrière S0 | **Instance réelle à obtenir** (lot CH) | 1 (migration), qualification en CH |
| `snowflake` | `sqlalchemy` / `adbc` | snowflake-connector-python | Lecture Arrow, append, overwrite, upsert par `MERGE` | Compte de test | 1 |
| `bigquery` | `sqlalchemy` | google-cloud-bigquery, API Storage | idem | Projet de test | 1 |
| `s3` | `object_store` | pyarrow.fs ou obstore (S-C1) | Listage, aperçu, import, export immuable, surveillance | Bucket AWS de test, MinIO | 1 |
| `s3_compatible` | `object_store` | idem, endpoint et style de chemin | idem | MinIO | 1 |
| `azure_blob` | `object_store` | idem, ADLS Gen2 compris | idem | Azurite, compte de test | 1 |
| `gcs` | `object_store` | idem | idem | Faux serveur GCS, projet de test | 1 |
| `redshift` | `sqlalchemy` / `adbc` | redshift_connector ou ADBC | Lecture, append, upsert | Compte de test | 2 |
| `databricks_sql` | `sqlalchemy` | databricks-sql-connector | Lecture, upsert par `MERGE` | Espace Databricks de test | 2 (§29.4) |
| `unity_catalog` | `uc_rest` | httpx, deltalake | Lecture | Conteneur UC OSS, Databricks | 2 (§29.4) |
| `delta_sharing` | `delta_sharing` | delta-sharing | Lecture | Serveur de référence en conteneur | 2 (§29.4) |
| `iceberg_rest` | `iceberg_rest` | pyiceberg | Lecture, append, overwrite, upsert | Conteneur de catalogue REST | 2 (§30, I1) |
| `synapse`, `fabric_warehouse` | `sqlalchemy` | à trancher (S-C4) | Lecture, upsert par `MERGE` | Compte de test | 2 |
| `sharepoint_files`, `onedrive` | `object_store` | client Graph existant | Listage, aperçu, import | Tenant de test | 2 |
| `http_files` | `object_store` | httpx | Aperçu, import | Serveur local | 2 |
| `mongodb` | `document` | pymongo | Lecture, insert, upsert par clé | Conteneur | 3 |
| `elasticsearch`, `opensearch` | `search` | clients officiels | Lecture, indexation en masse | Conteneurs | 3 |
| `cassandra` | `wide_column` | cassandra-driver | Lecture par plages de jetons | Conteneur | 3 |

**Hors de ce complément, à la demande** : IBM DB2, Teradata, ClickHouse, MotherDuck, Kafka et les flux continus.

**Parité** : après la vague 1, Agentium couvre les bases et le stockage objet de papAI, HANA restant non qualifié tant que CH n'a pas eu lieu. Après la vague 3, il couvre l'ensemble de papAI, plus les lakehouses et Databricks.

---

## 5. Famille `object_store`

**Paramètres du profil**
- `provider` : `s3`, `s3_compatible`, `azure_blob`, `gcs`, `sharepoint_files`, `onedrive`, `http_files` ;
- `bucket` ou conteneur, `prefix` racine autorisé, `region` ou `endpoint`, style de chemin pour les compatibles S3 ;
- authentification par fournisseur :
  - S3 : clé d'accès et secret, ou rôle assumé par STS ;
  - Azure : SAS, clé de compte ou principal de service ;
  - GCS : compte de service en `secret_file` ;
  - tout secret passe par le registre.
- TLS vérifié par défaut.

**Opérations**

| Opération | Comportement |
|---|---|
| `list` | Listage paginé sous un préfixe autorisé, avec taille, date et empreinte (ETag, génération ou équivalent) |
| `preview` | Lecture bornée de Parquet, CSV, TSV, JSON, NDJSON, XLSX, plus détection d'une table Delta ou Iceberg |
| `import` | Un fichier, un motif ou un préfixe devient une version de dataset en parts. L'ensemble des objets et leurs empreintes sont figés au départ (§9.1) |
| `export` | Écriture **immuable** décrite au §8.4. Aucun écrasement en place |
| `watch` | Interrogation périodique d'un préfixe. Un fichier nouveau ou modifié déclenche un Flow. Pas de bus d'événements en v1 |

**Règles**
- Aucune suppression d'objet en v1. La rétention des anciennes versions relève d'une politique ultérieure ou du client.
- Lecture seule par défaut. L'export exige une connexion `read_write`, activée par un administrateur.
- Plafonds de taille par fichier et par import.
- L'empreinte de chaque objet lu est conservée dans la filiation. Une empreinte qui change propose une requalification des actifs descendants (`mark_for_requalification`), sans l'appliquer d'office.
- Tout passe par le runner connecteur, en flux, sans charger un fichier entier en mémoire.

---

## 6. Familles NoSQL

| Famille | Moteurs | Lecture | Écriture | Garde-fous |
|---|---|---|---|---|
| `document` | MongoDB | Collections, inférence de schéma sur échantillon, filtre JSON validé, aplatissement configurable | insert, upsert par clé | Opérateurs `$where`, `$function` et `$accumulator` refusés |
| `search` | Elasticsearch, OpenSearch | Index, mapping, requête DSL validée, export par point-in-time | Indexation en masse avec identifiants de documents déterministes | Scripts refusés, taille de page bornée |
| `wide_column` | Cassandra | Keyspaces et tables, lecture par plages de jetons | Plus tard | Pas de `ALLOW FILTERING` sans accord explicite |

---

## 7. Capacités déclarées par profil

Chaque profil déclare ses capacités. L'interface n'offre que celles-ci, et le kit les teste toutes.

```yaml
capabilities:
  read: true
  read_partitioned: true
  read_incremental: true
  consistency: snapshot            # snapshot | per_partition | none (§9.1)
  write_append: true
  write_overwrite: true
  write_upsert: true
  create_table: true
  write_outcome_check: marker_table # marker_table | job_id | idempotency_key | conditional_put | none (§8.2)
  export_files: false
  watch: false
```

- **Une capacité absente est refusée** avec `CONNECTOR_OPERATION_UNSUPPORTED`, par l'API, par le Flow et par les outils d'agent. Le kit vérifie ce refus.
- Les capacités entrent dans l'empreinte du profil (§11.2) : les modifier impose une nouvelle qualification.

---

## 8. Écritures : identifiant d'opération et résultat inconnu

### 8.1 Cycle de vie d'une écriture

1. **Préparer** : l'opération reçoit un `operation_id` stable, enregistré avant tout envoi, avec la connexion, la cible, l'empreinte du dataset source et le mode d'écriture. Elle passe par le registre local des calculs (§12.2).
2. **Essai à blanc** : lignes à insérer et à mettre à jour. Approbation humaine si la politique l'exige.
3. **Envoyer** : l'état passe à `sent` avant l'appel au moteur.
4. **Conclure** :
   - réponse reçue et positive : `applied` ;
   - erreur certaine avant toute modification : `failed` ;
   - réponse perdue, délai dépassé ou coupure après l'envoi : **`unknown`**.
5. **Rapprocher** un état `unknown` selon la capacité `write_outcome_check` (§8.2) :
   - preuve d'application trouvée : `applied` ;
   - preuve d'absence certaine : nouvel envoi **avec le même `operation_id`** ;
   - indécidable : l'état reste `unknown`, un incident est attribué au responsable du System et une revue est ouverte. Aucune nouvelle écriture vers la même cible ne part tant que l'opération n'est pas tranchée.

**Aucune reprise automatique** n'a lieu sur un état `unknown` sans rapprochement.

### 8.2 Règles par capacité du moteur

| `write_outcome_check` | Moteurs visés | Mécanisme | Reprise |
|---|---|---|---|
| `marker_table` | PostgreSQL, MySQL InnoDB, SQL Server, Oracle, HANA, Snowflake | Les données et une ligne `operation_id` sont écrites dans la même transaction, dans une table technique `_agentium_operations` du schéma cible | Sûre après rapprochement |
| `job_id` | BigQuery | Identifiant de job déterministe dérivé de `operation_id` ; un job déjà existant est retrouvé, pas recréé | Sûre |
| `idempotency_key` | API OpenAPI ou MCP qui déclarent un en-tête d'idempotence | `Idempotency-Key` égal à `operation_id` | Sûre si le service l'honore, sinon `none` |
| `conditional_put` | Stockage objet | Écriture conditionnelle de l'objet de publication (§8.4) | Sûre |
| `none` | Tout autre cas | Aucun moyen de prouver l'application | `unknown` vers une revue humaine, jamais de reprise automatique |

- **Upsert** par clés : idempotent par nature, il reste soumis au rapprochement pour le comptage exact.
- **Overwrite** : `TRUNCATE` puis insertion dans une transaction, ou échange par renommage d'une table de staging. Il est rejouable avec le même `operation_id`.
- **Append** sans `marker_table` ni clé naturelle : autorisé seulement avec `write_outcome_check: none`, donc sans reprise automatique, et signalé comme tel dans l'interface.
- Créer `_agentium_operations` exige un droit de création une fois. Sans ce droit, le profil se déclare `none` pour l'append.

### 8.3 Recette des écritures

Pour chaque capacité déclarée, le kit coupe la réponse **après** l'envoi de la validation. Il vérifie l'état `unknown`, le rapprochement, l'absence de doublon par comparaison des clés et des empreintes, et l'incident attribué quand le rapprochement est impossible.

### 8.4 Exports vers le stockage objet en v1

- **Préfixes immuables** : chaque export écrit sous `<racine>/<nom>/v=<operation_id>/`. Les fichiers d'une version ne sont jamais réécrits.
- **Manifeste** : chaque version contient `manifest.json`, avec la liste exacte de ses fichiers, leurs tailles et empreintes, et l'empreinte du dataset source.
- **Publication** : un pointeur `<racine>/<nom>/_LATEST.json` désigne la version courante. Il est écrit en dernier, par **écriture conditionnelle** : `If-None-Match` ou `If-Match` selon le cas sur S3 et Azure, précondition de génération sur GCS. Un échec de condition signale une publication concurrente.
- **Lecteurs** : ils lisent le pointeur, puis le manifeste. Lister le préfixe ne fait pas foi. Un consommateur qui exige le contenu exact d'un dossier relève d'une version ultérieure.
- **Delta** : contrat distinct. delta-rs écrit la table sous un préfixe dédié. Un `overwrite` est un commit Delta logique, sans `VACUUM` lancé par Agentium. La sûreté des commits concurrents dépend du mécanisme d'écriture conditionnelle ou de verrou pris en charge par delta-rs sur le stockage cible : elle se qualifie au spike S-C1.
- **Iceberg** : contrat du §30, inchangé.

---

## 9. Lectures : cohérence et reprise incrémentale

### 9.1 Niveau de cohérence déclaré

| Niveau | Garantie | Moteurs pressentis, à confirmer au spike S-C7 |
|---|---|---|
| `snapshot` | Toutes les parts reflètent un même instant de la source | PostgreSQL : `REPEATABLE READ` et snapshot exporté entre connexions. SQL Server : isolation par snapshot si la base l'autorise. Oracle : requête `AS OF SCN`, dans la limite de la rétention d'annulation. Snowflake et BigQuery : voyage dans le temps. Elasticsearch et OpenSearch : point-in-time. Stockage objet : ensemble d'objets et empreintes figés au départ |
| `per_partition` | Chaque part est cohérente, l'ensemble ne l'est pas forcément | MySQL en lectures parallèles, faute de snapshot partagé sans verrou global. Cassandra |
| `none` | Aucune garantie | Moteurs ou comptes sans les mécanismes ci-dessus |

- Le niveau obtenu est inscrit dans la filiation de la version produite, et visible dans Data.
- Un import peut exiger `snapshot`. S'il ne l'obtient pas, il échoue avec `CONNECTOR_CONSISTENCY_UNAVAILABLE`, sans se dégrader en silence.
- Pour MySQL, le mode `snapshot` reste possible en lecture séquentielle sur une seule connexion.

### 9.2 Bornes des partitions

- Les bornes sont calculées **une fois au départ**, sur le snapshot quand il existe.
- Les intervalles sont semi-ouverts, `[a, b)`, sauf le dernier qui inclut le maximum relevé.
- Les valeurs `NULL` de la colonne de partition forment **une partition à part**.
- Une ligne insérée au-delà du maximum relevé n'entre pas dans cet import. Elle sera lue au suivant.

### 9.3 Filigrane incrémental

- La colonne de filigrane doit être **non nulle** et croissante : date de mise à jour ou séquence. Un profil le vérifie au premier import et refuse sinon (`CONNECTOR_WATERMARK_INVALID`).
- **Égalités** : le filigrane est le couple formé de la valeur et de la clé primaire. La reprise lit les couples strictement supérieurs au dernier couple validé.
- **Borne haute** : le maximum relevé au départ de l'import.
- **Retards** : une fenêtre de recouvrement configurable relit une marge en arrière, puis dédoublonne par clé. Elle couvre les horloges décalées et les transactions longues.
- **Suppressions** : non captées par ce mode, ce qui est signalé dans la filiation. La capture de changements est hors de ce complément.

### 9.4 Moment où le checkpoint devient définitif

- Le nouveau filigrane est enregistré **dans la même transaction** que le commit de la version de dataset.
- Un import échoué ou interrompu ne fait jamais avancer le filigrane.
- Une reprise repart du dernier checkpoint définitif, avec de nouvelles bornes.

### 9.5 Recette des lectures

- Insérer, modifier et supprimer des lignes dans la source **pendant** une lecture, puis interrompre et reprendre l'import.
- Comparer le résultat à la source au point de cohérence annoncé, **par ensemble de clés et par empreintes**, pas seulement par nombre de lignes.
- Vérifier qu'aucun trou ni doublon n'est masqué, et que le niveau de cohérence inscrit correspond à ce qui a été obtenu.

---

## 10. Catalogue des outils

### 10.1 Autorisations utilisateur

**Le modèle.** Une autorisation OAuth est un objet à part entière :

| Champ | Rôle |
|---|---|
| `owner_user_id`, `workspace_id`, `connection_id` | Le propriétaire, le workspace où elle a été accordée, le serveur ou l'API visé |
| `scopes` | Les portées accordées par le fournisseur |
| `token_refs` | Références vers une **nouvelle portée `user`** du registre de secrets, liée au couple utilisateur et workspace |
| `delegations[]` | Délégations explicites à un System (§10.2) |
| `granted_at`, `expires_at`, `revoked_at`, `revoked_by` | Cycle de vie |

**Les règles d'usage**
- **Exécution interactive** (Work, Studio, conversation, lancement manuel dans le Cockpit) : seule l'autorisation **de l'utilisateur qui agit** est utilisable. Sans elle : `CONNECTOR_OAUTH_CONSENT_REQUIRED`.
- **Exécution sans utilisateur** (fenêtre d'un contrat de service, déclencheur, planification, rejeu automatique) : jamais d'autorisation personnelle implicite. Elle utilise soit l'identité de service du workspace, configurée par un administrateur en OAuth client credentials ou en compte technique, soit une délégation explicite (§10.2). Sinon : `CONNECTOR_GRANT_REQUIRED`.
- **Aucun autre partage.** Un administrateur ne peut pas utiliser l'autorisation d'un membre.
- **Les outils d'agent** reçoivent une poignée d'exécution, jamais le jeton. Le jeton n'apparaît dans aucune entrée de Run, aucun manifeste, aucun journal.
- **Chaque appel** enregistre l'identité qui agit : utilisateur, identité de service ou délégation de tel utilisateur.

### 10.2 Délégation à un System

- Le propriétaire délègue son autorisation à **un System**, dans une version publiée précise.
- Un administrateur du workspace approuve la délégation. Elle est visible sur la page du System et sur la connexion.
- Elle expire, et une nouvelle version publiée du System exige une nouvelle délégation.

### 10.3 Révocation

Une autorisation est révoquée quand son propriétaire la retire, quand un administrateur la retire, quand le membre quitte le workspace ou quand le workspace est supprimé. Alors :
- ses jetons sont effacés du registre ;
- le point de révocation du fournisseur est appelé quand il existe ;
- ses délégations tombent ;
- un Run en cours échoue proprement au prochain appel.

### 10.4 Recette des autorisations

- Deux utilisateurs A et B sur la même connexion : B ne peut utiliser l'autorisation de A ni par l'API, ni par un Flow, ni par un agent, ni par un rejeu.
- Un Flow planifié sans délégation est refusé. Avec une délégation, il ne fonctionne que pour la version de System visée.
- Après révocation, l'appel suivant échoue. Retirer un membre révoque ses autorisations et leurs délégations.
- Les jetons de A et de B restent isolés dans le registre, et aucun jeton n'apparaît dans les journaux.

### 10.5 Serveurs MCP officiels

- **Catalogue choisi** : fichier versionné `backend/app/resources/connectors/mcp_catalog.yaml`. Chaque entrée donne l'éditeur, l'URL officielle, le mode d'authentification, la liste blanche d'outils par défaut, les outils d'écriture scellés et une note sur la localisation des données.
- **N'y entrent que des serveurs publiés par l'éditeur lui-même**, par exemple GitHub, Atlassian ou Notion. La liste exacte se fixe au spike S-C3.
- **OAuth** : flux par code d'autorisation avec PKCE, et enregistrement dynamique de client quand le serveur le permet, selon le modèle du §10.1.
- **Écritures** : scellées par défaut, sur le modèle de `connectors/mcp/write.py`. Elles s'ouvrent outil par outil, avec approbation humaine si la politique l'exige, et suivent le §8 quand le serveur déclare une idempotence.
- **Niveau** : un serveur MCP tiers reste « Tiers ». Il ne devient jamais « Certifié », même s'il fonctionne.

### 10.6 Import OpenAPI

- Une spécification OpenAPI, fournie par URL ou par fichier, est validée puis listée par opération.
- **Spécification autonome** : les références `$ref` externes sont refusées en v1. Une spécification découpée doit être assemblée avant l'import.
- **Serveurs** : les `servers` de la spécification doivent correspondre aux origines déclarées sur la connexion, validées par un administrateur.
- L'administrateur choisit les opérations exposées. Chacune devient un outil typé, avec son schéma d'entrée et de sortie.
- Les `GET` sont en lecture. Les autres méthodes exigent une connexion `read_write`, l'approbation humaine si la politique l'exige, et le cycle du §8.
- Plafonds de taille de réponse et de débit.

### 10.7 Fiches SaaS existantes

Teams, Outlook, Dynamics 365, Telegram, WhatsApp, SMTP et MQTT suivent chacune l'une de trois voies, tranchées en C0 :
1. connecteur natif à certifier ;
2. renvoi vers le serveur MCP officiel de l'éditeur ;
3. masquage, ou mention « sur demande ».

### 10.8 Outils exposés aux agents

Chaque connexion de données expose aussi des outils typés à l'agent : lister, prévisualiser, interroger en lecture. Ils obéissent aux mêmes droits, aux mêmes capacités, à la même garde et au même audit que dans le Flow.

---

## 11. Niveaux de preuve et kit de certification

### 11.1 Les trois niveaux

| Niveau | Conditions |
|---|---|
| **Vérifié** | Une preuve correspond **exactement** aux composants actuels (§11.2), et toutes les suites des capacités déclarées sont au vert sur conteneur ou compte de test |
| **Certifié** | Vérifié, **plus** un canari positif sur l'environnement déployé avec ces mêmes composants, datant de moins de `connector_certification_max_age_days` jours, **plus** un test de révocation d'identifiant réussi |
| **Tiers** | Serveur MCP ou API importée, soumis aux politiques d'Agentium, sans garantie de fonctionnement |

**Deux règles de déclassement, sans contradiction :**
- **Un composant change** (version du profil, capacités, pilote, image du runner ou version du kit) : aucune ancienne preuve ne s'applique. Le profil passe à « À requalifier » et perd les deux niveaux jusqu'à une nouvelle exécution du kit.
- **Le canari vieillit** au-delà du délai, sans changement de composant : « Certifié » redevient « Vérifié ».

### 11.2 Identité d'une preuve

Chaque bundle de preuves enregistre :
- la clé et la version du profil, et l'empreinte de ses capacités ;
- les paquets de pilotes et leurs versions exactes ;
- l'empreinte de l'image du runner connecteur ;
- la version du kit ;
- la version du moteur testé côté serveur ;
- l'environnement : conteneur, compte de test ou environnement déployé ;
- la date, le résultat de chaque suite et l'empreinte du bundle.

Le catalogue calcule le niveau en comparant ces identités aux composants déployés. Aucune fiche ne déclare son niveau à la main.

### 11.3 Le kit commun

Le kit vit sous `backend/app/tests/connectors/kit/`. Il se paramètre par profil **et par capacités**. Ajouter un profil sans code doit suffire à le faire passer (critère D7.6).

| Suite | Contenu |
|---|---|
| Contrat | Validation du profil, génération du formulaire, liste blanche des options, cohérence des capacités |
| Capacités absentes | Chaque opération non déclarée est refusée avec `CONNECTOR_OPERATION_UNSUPPORTED` |
| Connexion | Diagnostic par étapes : DNS, réseau, TLS, authentification, droits. Un code fermé par étape |
| Introspection | Schémas, tables ou préfixes, colonnes, types |
| Lecture | Matrice des types, valeurs nulles, Unicode, grandes valeurs, lecture partitionnée, cohérence et reprise incrémentale (§9.5) |
| Écriture | Pour les modes déclarés : comptes exacts, essai à blanc, refus sur une connexion en lecture seule, réponse perdue et rapprochement (§8.3) |
| Sécurité | Garde réseau du §13 sur la destination et sur les redirections, rebinding DNS, échec TLS, aucun texte de pilote dans les erreurs, aucun secret dans les journaux ni les manifestes |
| Révocation | Identifiant tourné ou révoqué : code fermé, pas de tempête de reprises |
| Résilience | Délai dépassé, annulation, coupure réseau en pleine lecture : aucun dataset partiel publié |
| Filiation | Un import produit une version d'actif, avec l'empreinte de la source et son niveau de cohérence |

### 11.4 Où le kit tourne

**Le banc doit d'abord exister.** Aucune CI distante ne tourne aujourd'hui. C0 met en service l'une de ces deux options, à trancher par l'utilisateur :
1. un runner GitLab actif, avec conteneurs de service ;
2. un hôte de banc dédié, ou l'hôte du runner protégé, qui exécute le kit par `docker compose` et produit des bundles de preuves avec empreintes, comme les preuves actuelles.

Ensuite :
- **Vérifié** : conteneurs PostgreSQL, MySQL, MariaDB, SQL Server, Oracle Free, MinIO, Azurite, faux serveur GCS, MongoDB, Elasticsearch, OpenSearch, Cassandra, Unity Catalog OSS, serveur Delta Sharing de référence, catalogue Iceberg REST.
- **Comptes de test cloud** : Snowflake, BigQuery, Redshift, Databricks, Synapse ou Fabric, AWS S3, Azure et GCS. Job nocturne, schémas et buckets dédiés, purge en fin d'exécution. **Ligne de budget et propriétaire des comptes à désigner** (S-C6).
- **Certifié** : canari depuis l'environnement déployé, sur le modèle du canari positif SFTP, écritures dans un espace de test dédié.
- **SAP HANA** : aucun conteneur ni démo ne qualifie HANA. Le lot CH attend une instance réelle (S-C8).

---

## 12. Exécution : files, échéances et registre local des calculs

### 12.1 Deux files

| File | Opérations | Capacité | Échéance |
|---|---|---|---|
| `connectors_interactive` | Test de connexion, introspection, aperçu, échange de jeton OAuth | **Réservée** : processus dédiés, jamais occupés par un import | Échéance absolue fixée par l'API, **attente en file comprise**. Une tâche non démarrée à l'échéance est abandonnée |
| `connectors` | Import, export, surveillance, écriture | Partagée, bornée par les quotas | Délai du nœud, comme DataOps |

- Si une opération courte expire avant de démarrer, l'API répond `CONNECTOR_BUSY`, et non « injoignable ». L'interface distingue ainsi une connexion saine d'un banc saturé.
- Les deux files sont déclarées dans Compose, le chart Helm, `agentium-vm-deploy.sh`, le bundle d'environnement et `check-k8s-scaffold.sh`, selon la règle D.4 du plan.

### 12.2 Registre local des calculs, partagé avec DataOps

- Les imports, exports et écritures sont des calculs du registre `compute_runs`, avec les types `connector_read` et `connector_write` déjà prévus au §12 du plan.
- Ce registre est un **prérequis commun** : il porte le bail, l'annulation, l'échéance, les quotas par workspace et les mesures de coût, pour le placement local. Il est livré **une seule fois**, en tête de C1, au service de DataOps et de D7.
- Les mesures alimentent le coût complet par résultat accepté et les seuils de passage à l'échelle.

---

## 13. Sécurité

### 13.1 Garde réseau commune

**Périmètre** : toute destination sortante d'un connecteur, soit les hôtes SQL, les points d'accès de stockage, les serveurs MCP, les points OAuth de découverte, d'autorisation, de jeton, de révocation et de clés, les serveurs OpenAPI, les fichiers HTTP, et **chaque étape d'une redirection**.

**Règles**
1. Résoudre le nom, puis refuser toute réponse qui contient une adresse privée, de bouclage, link-local ou de métadonnées, même mêlée à des adresses publiques.
2. **Se connecter à l'IP validée**, en conservant le nom pour SNI et la vérification du certificat. Cela protège contre le rebinding, en SQL comme en HTTP.
3. **Redirections désactivées par défaut.** Le client MCP actuel les suit (`follow_redirects=True`) : C0 change ce comportement. Un profil qui les autorise est limité à trois étapes, chacune revalidée par la garde. Un passage de HTTPS à HTTP est refusé.
4. **Secrets liés à leur origine** : schéma, hôte et port déclarés sur la connexion. Un en-tête `Authorization`, un cookie ou une clé d'API ne part jamais vers une autre origine, redirection comprise.
5. **OAuth** : les points de découverte et de jeton sont en HTTPS, passent par la garde, et l'émetteur annoncé doit correspondre à celui de la connexion.
6. **Ports attendus** par profil.

**Exceptions administrées** pour les installations clientes, où les bases vivent souvent sur un réseau privé :
- `connector_allowed_networks` reçoit des entrées précises : CIDR, ports, portée plateforme ou workspace, motif et date d'expiration ;
- seul un administrateur de la plateforme les crée, et chaque création est auditée ;
- les adresses de bouclage, link-local et de métadonnées, par exemple `169.254.169.254`, ne peuvent **jamais** faire l'objet d'une exception ;
- une exception « tout le réseau privé » est refusée.

**Activation** : mode `report` pendant une release, analyse de chaque refus constaté, puis mode `enforce`. **C0 n'est terminé qu'avec `enforce` actif en production**, prouvé par la configuration déployée et un refus observé sur une destination de test.

### 13.2 Autres règles

- **Registre de secrets obligatoire** (D7.1), avec la nouvelle portée `user` pour les autorisations (§10.1).
- **Écriture verrouillée à la naissance** : connexion `read` par défaut, passage en `read_write` par un administrateur.
- **Codes fermés** : jamais le texte du pilote.
- **Pilotes isolés** : seuls le worker et le runner connecteur les chargent.
- **Audit** : `connection.created`, `connection.tested`, `connection.used`, `connection.write_previewed`, `connection.write_applied`, `connection.write_unknown`, `connection.revoked`, `grant.created`, `grant.delegated`, `grant.revoked`, `network.exception_created`.

---

## 14. Image et budget

- **Image** `agentium-connector-runner` : base du worker, plus une couche de pilotes. Sa taille est mesurée par `scripts/agentium-image-budget.sh`, avec un plafond fixé après le spike S-C2.
- **À éviter** : les bibliothèques système ODBC, sauf si le spike S-C4 les rend inévitables pour Synapse ou Fabric.

---

## 15. Interface

- **Une seule page Connexions** : recherche, catégories, logos, badge de niveau avec lien vers sa preuve, état en direct de chaque connexion.
- **Création** : formulaire généré depuis le profil, secrets saisis une fois puis stockés dans le registre.
- **Test** : diagnostic affiché étape par étape, avec le code de chaque échec, et `CONNECTOR_BUSY` distinct d'une panne.
- **Explorateur** : schémas, tables, préfixes ou index, puis aperçu.
- **Import** : produit un dataset versionné, visible dans Data avec sa filiation et son niveau de cohérence. Il peut devenir une entrée gouvernée d'un contrat de service, avec sa fraîcheur.
- **Écriture** : essai à blanc obligatoire, approbation si la politique l'exige, et état `unknown` affiché tel quel avec son rapprochement.
- **Autorisations** : chaque utilisateur voit ses autorisations, ses délégations et leur usage. Un administrateur voit les délégations et les identités de service.
- **Trois usages d'une même connexion** : nœuds de lecture et d'écriture dans le Flow, import dans Data, outil pour un agent.
- Sobriété Tokens v2 : les logos et le badge portent l'information, pas de décor ajouté.

---

## 16. Lots détaillés

### C0 — Prérequis (4 PR)

1. **Garde réseau commune** pour SQL et HTTP (§13.1), en mode `report`. Elle s'applique à PostgreSQL, HANA et MCP. Le client MCP cesse de suivre les redirections par défaut.
2. **Exceptions administrées et passage en `enforce`**, après une release d'observation.
3. **Banc de certification** : option retenue au §11.4, squelette du kit paramétré par capacités, format des bundles de preuves.
4. **Catalogue honnête** : retrait du statut `available` sans preuve, voie de chaque fiche SaaS (§10.7), calcul du niveau depuis les preuves, squelettes de l'image et des deux files.

**Critères** : `enforce` actif en production, prouvé. Un bundle de preuves produit par le banc. Aucune fiche affichée sans connecteur ni mention explicite.

### C1 — Socle (3 PR)

1. **Registre local des calculs** partagé avec DataOps (§12.2), s'il n'existe pas encore.
2. Table `connections`, autorisations et portée `user` du registre (§10.1), commande de reprise (D7.1).
3. Profils déclaratifs avec capacités, famille `sqlalchemy`, page Connexions, migration de PostgreSQL et de HANA.

**Critères** :
- PostgreSQL passe le kit et devient « Vérifié ».
- **HANA migre sans qualification** : ses tests de non-régression reproduisent le comportement actuel, mode démo compris, et son niveau reste « Non qualifié » jusqu'au lot CH.
- Les anciennes pages spécifiques restent lisibles pendant une release.

### C2 — Bases relationnelles, vague 1 (2 PR)

MySQL, MariaDB, SQL Server, Oracle, d'abord en lecture, puis en écriture avec le cycle du §8.

**Critères** : les quatre profils sont « Vérifiés ». Import partitionné de 10 millions de lignes depuis PostgreSQL, avec source modifiée pendant la lecture et reprise après interruption. Upsert d'un million de lignes vers PostgreSQL et SQL Server avec des comptes exacts, réponse perdue comprise.

### C3 — Stockage objet (2 PR)

Famille `object_store`, profils `s3`, `s3_compatible`, `azure_blob` et `gcs`, puis `watch` et export immuable (§8.4).

**Critères** : les quatre profils sont « Vérifiés » sur MinIO, Azurite et le faux serveur GCS. Deux publications concurrentes d'un même export : une seule réussit. Un fichier modifié propose une requalification des actifs descendants.

### C4 — Entrepôts cloud, vague 1 (2 PR)

Snowflake et BigQuery, puis le job nocturne sur comptes de test.

**Critères** : les deux profils sont « Vérifiés » sur compte de test. Le premier profil « Certifié » est obtenu par canari depuis la VM.

### C5 — Catalogue des outils (3 PR)

1. Flux OAuth utilisateur, délégations et révocation (§10.1 à §10.4), puis catalogue `mcp_catalog.yaml`.
2. Import OpenAPI (§10.6).
3. Outils exposés aux agents pour les connexions de données (§10.8).

**Critères** : la recette du §10.4 passe en entier. Un serveur MCP officiel s'installe et s'autorise sans saisie d'URL. Une écriture MCP reste scellée tant qu'un administrateur ne l'ouvre pas. Une opération OpenAPI non choisie est refusée.

### C6 — Vague 2 (4 PR)

Redshift et Databricks SQL, puis Unity Catalog et Delta Sharing, puis Iceberg REST, puis Synapse ou Fabric, fichiers SharePoint, OneDrive et HTTP.

### C7 — Vague 3 (3 PR)

MongoDB, puis Elasticsearch et OpenSearch, puis Cassandra.

### CH — Qualification de SAP HANA (1 PR)

Exécution du kit et du canari sur une instance HANA réelle, une fois le spike S-C8 tranché. HANA devient alors « Vérifié », puis « Certifié ».

---

## 17. Critères de réussite globaux

- **Chaque profil affiché** porte un niveau calculé depuis une preuve dont l'identité correspond aux composants déployés.
- **Ajouter un profil** de la famille `sqlalchemy` ou `object_store` sans code fait passer le kit pour ses capacités déclarées.
- **Après C4**, au moins dix sources de données sont « Vérifiées » ou « Certifiées » : PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, Snowflake, BigQuery, S3, Azure Blob et GCS. HANA les rejoint après CH.
- **Après C7**, la couverture de papAI est atteinte et dépassée par les lakehouses et Databricks.
- **Aucune écriture** n'est rejouée sur un état `unknown` sans rapprochement.
- **Aucune autorisation** n'est utilisée par un autre que son propriétaire, hors délégation approuvée.
- **Aucun secret** n'apparaît dans un journal, un manifeste ou une erreur.
- **Aucune adresse interne** non autorisée n'est joignable, redirections comprises.

---

## 18. Spikes

| Spike | Question | Lot |
|---|---|---|
| S-C1 | pyarrow.fs, obstore ou fsspec pour le stockage objet : ADLS hiérarchique, renouvellement des identifiants, écriture conditionnelle par fournisseur, commits Delta concurrents, débit, taille | C3 |
| S-C2 | Taille et licence de chaque pilote, prolongement de S-D7-3 | C0 |
| S-C3 | OAuth des serveurs MCP officiels : enregistrement, portées, renouvellement, révocation, contraintes de tenant, liste initiale des éditeurs | C5 |
| S-C4 | Authentification Entra ID pour Synapse et Fabric sans bibliothèque ODBC | C6 |
| S-C5 | dlt contre PyAirbyte pour la longue traîne : licences, taille, exécution isolée, qualité des sources | Après C4 |
| S-C6 | Coût et propriété des comptes de test cloud, rotation de leurs identifiants | C4 |
| S-C7 | Cohérence réellement obtenue par moteur : snapshot exporté, isolation par snapshot, `AS OF SCN`, voyage dans le temps, point-in-time, et leurs prérequis côté client | C2 |
| S-C8 | Banc HANA réel : SAP HANA Cloud en essai ou HANA Express, licence, taille et hébergement | CH |

---

## 19. Risques

| Risque | Mitigation |
|---|---|
| Un catalogue large mais fragile | Kit par capacités, preuve liée aux composants, canari pour « Certifié » |
| Des images trop lourdes | Image dédiée, budget mesuré par pilote |
| Une surface SSRF multipliée | Garde commune en `enforce` sur toutes les destinations, redirections comprises, avant tout nouveau profil |
| Un consentement réutilisé par un autre utilisateur | Autorisations personnelles, délégation explicite et approuvée, recette à deux utilisateurs |
| Des écritures dupliquées | Identifiant d'opération, état `unknown`, rapprochement par capacité |
| Des imports incohérents masqués | Cohérence déclarée et inscrite, checkpoint lié au commit, recette par ensemble de clés |
| Des diagnostics bloqués par les imports | File interactive à capacité réservée, échéance incluant l'attente |
| Le coût des comptes cloud | Spike S-C6, purge systématique, budget explicite |
| Des serveurs MCP tiers qui changent | Version épinglée, tests de contrat, niveau « Tiers » seulement |
| Une dispersion loin des parcours de référence | Vagues ordonnées par la parité papAI et les demandes réelles. Les deux parcours de référence restent prioritaires dans les arbitrages |

---

## Annexe A — Codes d'erreur additionnels

Ils complètent l'annexe B du plan.

| Code | Cas |
|---|---|
| `CONNECTOR_DNS_FAILED`, `CONNECTOR_NETWORK_UNREACHABLE` | Étapes du diagnostic de connexion |
| `CONNECTOR_BUSY` | Opération courte non démarrée avant son échéance |
| `CONNECTOR_REDIRECT_DENIED` | Redirection refusée par la garde ou vers une autre origine |
| `CONNECTOR_OPERATION_UNSUPPORTED` | Opération absente des capacités du profil |
| `CONNECTOR_WRITE_OUTCOME_UNKNOWN` | Écriture envoyée dont le résultat n'a pas pu être établi |
| `CONNECTOR_CONSISTENCY_UNAVAILABLE` | Niveau de cohérence exigé non disponible |
| `CONNECTOR_WATERMARK_INVALID` | Colonne de filigrane nulle ou non croissante |
| `CONNECTOR_BUCKET_NOT_FOUND`, `CONNECTOR_PREFIX_FORBIDDEN` | Conteneur absent, préfixe hors du périmètre autorisé |
| `CONNECTOR_OBJECT_TOO_LARGE`, `CONNECTOR_FORMAT_UNSUPPORTED` | Fichier trop gros, format non pris en charge |
| `CONNECTOR_PUBLICATION_CONFLICT` | Publication concurrente détectée par l'écriture conditionnelle |
| `CONNECTOR_NOSQL_OPERATOR_FORBIDDEN` | Opérateur ou script refusé dans une requête NoSQL |
| `CONNECTOR_OAUTH_CONSENT_REQUIRED`, `CONNECTOR_OAUTH_TOKEN_EXPIRED` | Autorisation de l'utilisateur absente ou expirée |
| `CONNECTOR_GRANT_REQUIRED`, `CONNECTOR_GRANT_NOT_OWNED` | Exécution sans utilisateur ni délégation, autorisation d'un autre utilisateur |
| `CONNECTOR_TOOL_NOT_ALLOWED` | Outil MCP ou opération OpenAPI hors liste blanche |
| `CONNECTOR_OPENAPI_INVALID` | Spécification invalide, référence externe ou serveur non déclaré |
| `CONNECTOR_CREDENTIAL_REVOKED` | Identifiant révoqué ou tourné |

## Annexe B — Réglages additionnels

- `celery_connectors_queue`, `celery_connectors_interactive_queue`, `connectors_interactive_concurrency` ;
- `connector_interactive_deadline_s`, attente en file comprise ;
- `connector_object_max_mb`, `connector_import_max_files` ;
- `connector_watch_interval_s`, `connector_incremental_lookback_s` ;
- `connector_network_policy_mode` (`report` puis `enforce`), `connector_redirect_max_hops` (0 par défaut) ;
- `connector_certification_max_age_days` (30 par défaut) ;
- `connector_grant_delegation_max_days` ;
- `connector_mcp_catalog_enabled`, `connector_openapi_import_enabled`.

## Annexe C — Sources publiques consultées le 14 octobre 2026

- [Documentation de Sim](https://docs.sim.ai/) et [outils de Sim](https://docs.sim.ai/tools)
- [Nombre d'intégrations de n8n en 2026, mpiresolutions](https://mpiresolutions.com/blog/how-many-integrations-does-n8n-have/)
- [Présentation de n8n, Techjack Solutions](https://techjacksolutions.com/ai-tools/n8n/what-is-n8n/)
- [Revue de n8n, Hackceleration](https://hackceleration.com/?p=493414)
- [Dataiku, connexion aux données](https://doc.dataiku.com/dss/latest/connecting/index.html) et [version 12](https://doc.dataiku.com/dss/12/connecting/index.html)

La couverture de papAI provient du code de `papai-latest` (`spark-service`, `core`, `frontend`), consulté le même jour.

## Annexe D — Suivi de la revue de `d3c2a9d3`

| Point de la revue | Correction |
|---|---|
| 1. Propriétaire de l'autorisation OAuth | Modèle d'autorisation, portée `user` du registre, règles d'usage interactif et sans utilisateur, délégation à un System, révocation, recette à deux utilisateurs (§10.1 à §10.4, C-9) |
| 2. Garde réseau sur toutes les destinations HTTP | Périmètre étendu aux points OAuth, serveurs OpenAPI et redirections, IP validée en HTTP, secrets liés à l'origine, références OpenAPI externes refusées, exceptions administrées, C0 terminé seulement avec `enforce` en production (§13.1, §10.6, C-7) |
| 3. Écritures au résultat inconnu et préfixes écrasés | Identifiant d'opération, état `unknown`, rapprochement par capacité, recette de réponse perdue, préfixes immuables avec manifeste et pointeur conditionnel, contrat Delta distinct (§8, C-10, C-11) |
| 4. Cohérence de la reprise incrémentale | Niveau de cohérence déclaré, bornes figées, partition des `NULL`, filigrane à couple, fenêtre de recouvrement, checkpoint lié au commit, recette par ensemble de clés (§9, C-12) |
| 5. Règles de certification contradictoires et kit non paramétré | Identité complète d'une preuve, deux règles de déclassement distinctes, kit paramétré par capacités avec test des refus (§7, §11, C-13) |
| 6. Diagnostics bloqués derrière les imports | File interactive à capacité réservée, échéance incluant l'attente, `CONNECTOR_BUSY`, registre local des calculs mutualisé avec DataOps (§12, C-6) |
| 7. Moyens de qualification indisponibles | Migration de HANA dissociée de sa qualification, lot CH et spike S-C8, mise en service du banc comme critère de C0 (§11.4, §16) |
