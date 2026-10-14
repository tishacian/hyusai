# Complément D7 — Catalogue de connecteurs certifiés

> **Statut** : proposé le 14 octobre 2026, sur `origin/demo/agentic` (`0e401afc`).
> **Rattachement** : complète le lot D7 du [plan DataOps](agentium-dataops-plan.md), ainsi que ses §29.4 (Unity Catalog, Delta Sharing, Databricks SQL) et §30 (Iceberg). Le plan d'origine n'est pas modifié. Les [amendements](agentium-dataops-amendments.md) pointent vers ce document.
> **Règles** : celles de l'annexe D du plan. Une branche par PR depuis `origin/demo/agentic`, poussée avec une refspec explicite, et chaque fusion attend l'accord explicite de l'utilisateur.
>
> Ce document ne vaut ni implémentation ni recette. Un connecteur n'est « certifié » que lorsque ses preuves existent (§8).

---

## 0. Lecture rapide

| Lot | Objectif | Dépend de | PR prévues |
|---|---|---|---|
| **C0** | Prérequis : garde réseau commune en mode blocage, catalogue affiché honnête, squelettes de l'image des pilotes et du kit de certification | — | 2 |
| **C1** | Socle D7.1 à D7.3 : table `connections`, profils déclaratifs, page Connexions. Migration de PostgreSQL et HANA | C0 | 3 |
| **C2** | Bases relationnelles, vague 1 : MySQL, MariaDB, SQL Server, Oracle, en lecture puis en écriture | C1 | 2 |
| **C3** | Nouvelle famille stockage objet : S3, compatibles S3 dont MinIO, Azure Blob et ADLS, Google Cloud Storage | C1 | 2 |
| **C4** | Entrepôts cloud, vague 1 : Snowflake et BigQuery, avec leurs comptes de certification | C1 | 2 |
| **C5** | Catalogue des outils : serveurs MCP officiels, OAuth utilisateur, import OpenAPI | C0 | 3 |
| **C6** | Vague 2 : Redshift, Databricks SQL, Unity Catalog, Delta Sharing, Iceberg REST, Synapse ou Fabric, SharePoint et OneDrive, fichiers HTTP | C2, C3, C4 | 4 |
| **C7** | Vague 3 : MongoDB, Elasticsearch ou OpenSearch, Cassandra | C1 | 3 |

**Ordre** : C0, puis C1. Ensuite C2, C3 et C4 peuvent avancer en parallèle, dans la limite de deux ou trois agents. C5 peut démarrer dès C0, car il ne dépend pas du socle des bases. C6 et C7 viennent après.

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
| SAP HANA (`services/connectors/hana/`) | Durci par S0 : écritures réservées aux administrateurs autorisés, mot de passe global supprimé, TLS strict, codes fermés. La garde réseau (`network_policy.py`) ne couvre que HANA et reste en mode `report` par défaut |
| MCP (`services/connectors/mcp/`) | Plusieurs serveurs HTTP par workspace, lecture, aperçu, écritures scellées. Authentification `none`, `bearer`, `oauth_client_credentials` ou `inherit`. **Aucun flux OAuth utilisateur** (code d'autorisation), qu'exigent la plupart des serveurs MCP distants des éditeurs. Chaque serveur s'ajoute à la main par son URL |
| SharePoint (`services/connectors/sharepoint_otp/`) | Ingestion documentaire vers Knowledge |
| Registre de secrets (`services/secrets/registry.py`) | Disponible, avec OpenBao en option. Les connecteurs, le Hub et les nœuds de service y résolvent déjà leurs secrets |
| Actifs gouvernés (`services/governed_assets.py`) | Versions pour `dataset`, `model`, `document_set` et `reference`, filiation, requalification propagée aux descendants |
| SFTP et dépôt sécurisé | Référence de solidité, voir ci-dessous |
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

C'est ce niveau qui définit le badge « Certifié » (§8).

---

## 3. Décisions

| # | Décision | Choix retenu | Raison |
|---|---|---|---|
| C-1 | Deux catalogues | **Données** : profils natifs certifiés. **Outils** : serveurs MCP officiels, import OpenAPI, nœud REST | On ne code pas mille intégrations SaaS à la main. On code en profondeur ce qui porte la donnée |
| C-2 | Niveaux de preuve | **Certifié**, **Vérifié**, **Tiers**. Le badge est calculé à partir des preuves, jamais déclaré | Un chiffre crédible face à un acheteur. Règle d'honnêteté du modèle mental |
| C-3 | Statut `available` | Supprimé pour toute fiche sans preuve. Une fiche sans connecteur est masquée ou marquée « sur demande » | Les fiches actuelles sans backend affaiblissent tout le catalogue |
| C-4 | Stockage objet | Nouvelle famille `object_store` dans D7.3 | SQLAlchemy ne couvre ni le listage, ni les formats de fichiers, ni l'arrivée de fichiers |
| C-5 | NoSQL | Trois familles courtes : `document` (MongoDB), `search` (Elasticsearch, OpenSearch), `wide_column` (Cassandra) | Un adaptateur par famille, comme le veut D7.3, même quand la famille ne compte qu'un ou deux moteurs |
| C-6 | Pilotes | Une image et une file dédiées : worker `agentium-worker-connectors`, file `connectors`. L'API n'importe aucun pilote | Le backend n'a plus que 68 Mio de marge et le worker 85 Mio. Les pilotes Oracle, Snowflake, BigQuery ou Databricks n'y tiennent pas |
| C-7 | Garde réseau | Une garde commune à tous les connecteurs, tirée de `hana/network_policy.py`, en mode `enforce` avant tout nouveau profil | Chaque profil accepte un hôte fourni par l'utilisateur. La surface SSRF grandit avec le catalogue |
| C-8 | Connexion et actifs | Un import produit une version d'actif gouverné, avec filiation, empreinte de la source et fraîcheur | C'est ce qui distingue Agentium : une connexion devient une source gouvernée, pas seulement un appel d'API |
| C-9 | MCP | Un catalogue choisi de serveurs **officiels**, publiés par les éditeurs. Flux OAuth utilisateur ajouté. Outils filtrés par liste blanche, écritures scellées par défaut | Largeur immédiate, avec la gouvernance existante |
| C-10 | OpenAPI | Une spécification importée devient des outils typés. Lecture seule par défaut | Couvre la longue traîne des API documentées, comme le nœud HTTP de n8n, avec des contrats |
| C-11 | Longue traîne des sources | Spike dlt contre PyAirbyte, sans engagement | Possible relais pour des centaines de sources, si licences et taille d'image le permettent |
| C-12 | Communication | On publie « N sources certifiées, M vérifiées, K outils tiers », calculés depuis les preuves | Pas de course au chiffre brut |

**Inchangé** : D7.1 à D7.6, la décision D-18 (pas de JDBC dans le processus Python), les règles d'écriture de D7.4, les §29.4 et §30.

---

## 4. Catalogue des données : couverture par vague

Le pilote indiqué est un candidat. Sa licence et sa taille dans l'image se confirment au spike S-C2 (qui prolonge S-D7-3).

| Profil | Famille | Pilote candidat | Lecture | Écriture | Banc de test | Vague |
|---|---|---|---|---|---|---|
| `postgresql` | `sqlalchemy` / `adbc` | psycopg2, ADBC PostgreSQL | Oui | append, overwrite, upsert | Conteneur | 1 (migration) |
| `mysql`, `mariadb` | `sqlalchemy` | pymysql | Oui | idem | Conteneurs | 1 |
| `sqlserver` | `sqlalchemy` | pymssql | Oui | idem | Conteneur | 1 |
| `oracle` | `sqlalchemy` | oracledb, mode thin | Oui | idem | Conteneur Oracle Free | 1 |
| `sap_hana` | `sqlalchemy` | hdbcli, sqlalchemy-hana | Oui | idem, derrière S0 | Instance Showcase | 1 (migration) |
| `snowflake` | `sqlalchemy` / `adbc` | snowflake-connector-python | Oui, Arrow | idem, `MERGE` | Compte de test | 1 |
| `bigquery` | `sqlalchemy` | google-cloud-bigquery, API Storage | Oui, Arrow | idem, `MERGE` | Projet de test | 1 |
| `s3` | `object_store` | pyarrow.fs ou obstore (S-C1) | Oui | Écriture de fichiers | Bucket AWS de test, MinIO | 1 |
| `s3_compatible` | `object_store` | idem, endpoint et style de chemin | Oui | idem | MinIO | 1 |
| `azure_blob` | `object_store` | idem, ADLS Gen2 compris | Oui | idem | Azurite, compte de test | 1 |
| `gcs` | `object_store` | idem | Oui | idem | Faux serveur GCS, projet de test | 1 |
| `redshift` | `sqlalchemy` / `adbc` | redshift_connector ou ADBC | Oui | idem | Compte de test | 2 |
| `databricks_sql` | `sqlalchemy` | databricks-sql-connector | Oui | `MERGE` | Espace Databricks de test | 2 (§29.4) |
| `unity_catalog` | `uc_rest` | httpx, deltalake | Oui | Plus tard | Conteneur UC OSS, Databricks | 2 (§29.4) |
| `delta_sharing` | `delta_sharing` | delta-sharing | Oui | — | Serveur de référence en conteneur | 2 (§29.4) |
| `iceberg_rest` | `iceberg_rest` | pyiceberg | Oui | append, overwrite, upsert | Conteneur de catalogue REST | 2 (§30, I1) |
| `synapse`, `fabric_warehouse` | `sqlalchemy` | à trancher (S-C4) | Oui | `MERGE` | Compte de test | 2 |
| `sharepoint_files`, `onedrive` | `object_store` | client Graph existant | Oui | Plus tard | Tenant de test | 2 |
| `http_files` | `object_store` | httpx | Oui | — | Serveur local | 2 |
| `mongodb` | `document` | pymongo | Oui | insert, upsert par clé | Conteneur | 3 |
| `elasticsearch`, `opensearch` | `search` | clients officiels | Oui | Indexation en masse | Conteneurs | 3 |
| `cassandra` | `wide_column` | cassandra-driver | Oui, par plages de jetons | Plus tard | Conteneur | 3 |

**Hors de ce complément, à la demande** : IBM DB2, Teradata, ClickHouse, MotherDuck, Kafka et les flux continus.

**Parité** : après la vague 1, Agentium couvre les bases et le stockage objet de papAI. Après la vague 3, il couvre l'ensemble de papAI, plus les lakehouses et Databricks.

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
| `list` | Listage paginé sous un préfixe autorisé, avec taille, date et empreinte (ETag ou équivalent) |
| `preview` | Lecture bornée de Parquet, CSV, TSV, JSON, NDJSON, XLSX, plus détection d'une table Delta ou Iceberg |
| `import` | Un fichier, un motif ou un préfixe devient une version de dataset en parts, avec options de schéma et d'union par nom de colonnes |
| `export` | Un dataset s'écrit en Parquet, CSV ou Delta sous un **nouveau** préfixe. L'écrasement d'un préfixe existant exige une confirmation explicite |
| `watch` | Interrogation périodique d'un préfixe. Un fichier nouveau ou modifié déclenche un Flow. Pas de bus d'événements en v1 |

**Règles**
- Aucune suppression d'objet en v1.
- Lecture seule par défaut. L'export exige une connexion `read_write`, activée par un administrateur.
- Plafonds de taille par fichier et par import.
- L'empreinte de chaque objet lu est conservée dans la filiation. Une empreinte qui change propose une requalification des actifs descendants (`mark_for_requalification`), sans l'appliquer d'office.
- Tout passe par le runner connecteur, en flux, sans charger un fichier entier en mémoire.

---

## 6. Familles NoSQL

| Famille | Moteurs | Lecture | Écriture | Garde-fous |
|---|---|---|---|---|
| `document` | MongoDB | Collections, inférence de schéma sur échantillon, filtre JSON validé, aplatissement configurable | insert, upsert par clé | Opérateurs `$where`, `$function` et `$accumulator` refusés |
| `search` | Elasticsearch, OpenSearch | Index, mapping, requête DSL validée, export par point-in-time ou scroll | Indexation en masse | Scripts refusés, taille de page bornée |
| `wide_column` | Cassandra | Keyspaces et tables, lecture partitionnée par plages de jetons | Plus tard | Pas de `ALLOW FILTERING` sans accord explicite |

---

## 7. Catalogue des outils

### 7.1 Serveurs MCP officiels

- **Catalogue choisi** : fichier versionné `backend/app/resources/connectors/mcp_catalog.yaml`. Chaque entrée donne l'éditeur, l'URL officielle, le mode d'authentification, la liste blanche d'outils par défaut, les outils d'écriture scellés et une note sur la localisation des données.
- **N'y entrent que des serveurs publiés par l'éditeur lui-même**, par exemple GitHub, Atlassian ou Notion. La liste exacte se fixe au spike S-C3.
- **OAuth utilisateur** : ajouter le flux par code d'autorisation avec PKCE, et l'enregistrement dynamique de client quand le serveur le permet. Les jetons et leur renouvellement passent par le registre de secrets.
- **Écritures** : scellées par défaut, sur le modèle de `connectors/mcp/write.py`. Elles s'ouvrent outil par outil, avec approbation humaine si la politique l'exige.
- **Niveau** : un serveur MCP tiers reste « Tiers ». Il ne devient jamais « Certifié », même s'il fonctionne.

### 7.2 Import OpenAPI

- Une spécification OpenAPI, fournie par URL ou par fichier, est validée puis listée par opération.
- L'administrateur choisit les opérations exposées. Chacune devient un outil typé, avec son schéma d'entrée et de sortie.
- Les `GET` sont en lecture. Les autres méthodes exigent une connexion `read_write` et, si la politique l'exige, une approbation humaine.
- Secrets dans le registre, garde réseau sur l'hôte, plafonds de taille de réponse et de débit.

### 7.3 Fiches SaaS existantes

Teams, Outlook, Dynamics 365, Telegram, WhatsApp, SMTP et MQTT suivent chacune l'une de trois voies, tranchées en C0 :
1. connecteur natif à certifier ;
2. renvoi vers le serveur MCP officiel de l'éditeur ;
3. masquage, ou mention « sur demande ».

### 7.4 Outils exposés aux agents

Chaque connexion de données expose aussi des outils typés à l'agent : lister, prévisualiser, interroger en lecture. Ils obéissent aux mêmes droits, à la même garde et au même audit que dans le Flow.

---

## 8. Niveaux de preuve et kit de certification

### 8.1 Les trois niveaux

| Niveau | Conditions | Réévaluation |
|---|---|---|
| **Certifié** | Toute la suite du kit au vert sur conteneur ou compte de test, **et** canari positif sur l'environnement déployé contre une vraie instance, **et** révocation d'identifiant testée | Le badge retombe à « Vérifié » si le dernier canari a plus de `connector_certification_max_age_days` jours, ou si la version du profil ou du pilote change |
| **Vérifié** | Toute la suite du kit au vert sur conteneur ou compte de test | Retombe à « Non vérifié » si la suite échoue ou si le pilote change sans nouvelle exécution |
| **Tiers** | Serveur MCP ou API importée, soumis aux politiques d'Agentium, sans garantie de fonctionnement | — |

Le catalogue lit le niveau depuis les preuves enregistrées, avec leur révision et leur date. Aucune fiche ne déclare son niveau à la main.

### 8.2 Le kit commun

Le kit vit sous `backend/app/tests/connectors/kit/` et se paramètre par profil. Ajouter un profil sans code doit suffire à le faire passer (critère D7.6).

| Suite | Contenu |
|---|---|
| Contrat | Validation du profil, génération du formulaire, liste blanche des options |
| Connexion | Diagnostic par étapes : DNS, réseau, TLS, authentification, droits. Un code fermé par étape |
| Introspection | Schémas, tables ou préfixes, colonnes, types |
| Lecture | Matrice des types, valeurs nulles, Unicode, grandes valeurs, lecture partitionnée, reprise incrémentale par filigrane |
| Écriture | append, overwrite et upsert avec des comptes exacts, essai à blanc, refus sur une connexion en lecture seule |
| Sécurité | Adresses privées, link-local et de métadonnées refusées, rebinding DNS, échec TLS, aucun texte de pilote dans les erreurs, aucun secret dans les journaux ni les manifestes |
| Révocation | Identifiant tourné ou révoqué : code fermé, pas de tempête de reprises |
| Résilience | Délai dépassé, annulation, coupure réseau en pleine lecture : aucun dataset partiel publié |
| Filiation | Un import produit une version d'actif, avec l'empreinte de la source |

### 8.3 Où le kit tourne

- **Vérifié** : jobs GitLab CI avec conteneurs de service. PostgreSQL, MySQL, MariaDB, SQL Server, Oracle Free, MinIO, Azurite, faux serveur GCS, MongoDB, Elasticsearch, OpenSearch, Cassandra, Unity Catalog OSS, serveur Delta Sharing de référence, catalogue Iceberg REST.
- **Comptes de test cloud** : Snowflake, BigQuery, Redshift, Databricks, Synapse ou Fabric, AWS S3, Azure et GCS. Job nocturne, schémas et buckets dédiés, purge en fin d'exécution. **Ligne de budget et propriétaire des comptes à désigner** (S-C6).
- **Certifié** : canari depuis l'environnement déployé, sur le modèle du canari positif SFTP, écritures dans un espace de test dédié.

---

## 9. Interface

- **Une seule page Connexions** : recherche, catégories, logos, badge de niveau avec lien vers sa preuve, état en direct de chaque connexion.
- **Création** : formulaire généré depuis le profil, secrets saisis une fois puis stockés dans le registre.
- **Test** : diagnostic affiché étape par étape, avec le code de chaque échec.
- **Explorateur** : schémas, tables, préfixes ou index, puis aperçu.
- **Import** : produit un dataset versionné, visible dans Data avec sa filiation. Il peut devenir une entrée gouvernée d'un contrat de service, avec sa fraîcheur.
- **Écriture** : essai à blanc obligatoire, puis approbation si la politique l'exige.
- **Trois usages d'une même connexion** : nœuds de lecture et d'écriture dans le Flow, import dans Data, outil pour un agent.
- Sobriété Tokens v2 : les logos et le badge portent l'information, pas de décor ajouté.

---

## 10. Sécurité

- **Garde réseau commune** (C0) : résolution, refus des adresses privées, de bouclage, link-local et de métadonnées sauf réseau autorisé, connexion à l'IP résolue, ports attendus par profil. Mode `report` une release, puis `enforce`.
- **Registre de secrets obligatoire** (D7.1) : pas de connexion sans registre.
- **Écriture verrouillée à la naissance** : connexion `read` par défaut, passage en `read_write` par un administrateur.
- **Codes fermés** : jamais le texte du pilote.
- **Pilotes isolés** : seuls le worker et le runner connecteur les chargent.
- **Audit** : `connection.created`, `connection.tested`, `connection.used`, `connection.write_previewed`, `connection.write_applied`, `connection.revoked`.

---

## 11. Image, file et budget

- **Image** `agentium-connector-runner` : base du worker, plus une couche de pilotes. Sa taille est mesurée par `scripts/agentium-image-budget.sh`, avec un plafond fixé après le spike S-C2.
- **File** `connectors`, consommée seulement par `agentium-worker-connectors`. Elle est déclarée dans Compose, le chart Helm, `agentium-vm-deploy.sh`, le bundle d'environnement et `check-k8s-scaffold.sh`, selon la règle D.4 du plan.
- **Test et aperçu depuis l'interface** : tâches courtes sur cette file, avec un délai bref. L'API ne charge aucun pilote.
- **À éviter** : les bibliothèques système ODBC, sauf si le spike S-C4 les rend inévitables pour Synapse ou Fabric.

---

## 12. Lots détaillés

### C0 — Prérequis (2 PR)

1. **Garde réseau commune** : extraire `hana/network_policy.py` vers `services/connectors/network_policy.py`, l'appliquer à PostgreSQL et MCP, en mode `report`, puis `enforce` à la release suivante.
2. **Catalogue honnête** : retirer le statut `available` des fiches sans connecteur, trancher la voie de chaque fiche SaaS (§7.3), poser le calcul du niveau à partir des preuves, et créer les squelettes du kit, de l'image et de la file.

**Critères** : aucune fiche affichée sans connecteur ni mention explicite. La garde refuse une adresse de métadonnées sur PostgreSQL et sur MCP.

### C1 — Socle (3 PR)

Table `connections` et commande de reprise (D7.1), profils déclaratifs et famille `sqlalchemy` (D7.2, D7.3), page Connexions, migration de PostgreSQL et HANA.

**Critères** : PostgreSQL et HANA passent le kit et rejoignent le niveau « Vérifié ». Les anciennes pages spécifiques restent lisibles pendant une release.

### C2 — Bases relationnelles, vague 1 (2 PR)

MySQL, MariaDB, SQL Server, Oracle, d'abord en lecture, puis en écriture.

**Critères** : les quatre profils sont « Vérifiés ». Import partitionné de 10 millions de lignes depuis PostgreSQL, upsert d'un million de lignes vers PostgreSQL et SQL Server avec des comptes exacts (critères D7.6).

### C3 — Stockage objet (2 PR)

Famille `object_store`, profils `s3`, `s3_compatible`, `azure_blob` et `gcs`, puis `watch` et `export`.

**Critères** : les quatre profils sont « Vérifiés » sur MinIO, Azurite et le faux serveur GCS. Un fichier modifié propose une requalification des actifs descendants.

### C4 — Entrepôts cloud, vague 1 (2 PR)

Snowflake et BigQuery, puis le job nocturne sur comptes de test.

**Critères** : les deux profils sont « Vérifiés » sur compte de test. Le premier profil « Certifié » est obtenu par canari depuis la VM.

### C5 — Catalogue des outils (3 PR)

1. OAuth utilisateur pour MCP et catalogue `mcp_catalog.yaml`.
2. Import OpenAPI.
3. Outils exposés aux agents pour les connexions de données.

**Critères** : un serveur MCP officiel s'installe et s'autorise en moins de trois minutes, sans saisie d'URL. Une écriture MCP reste scellée tant qu'un administrateur ne l'ouvre pas. Une opération OpenAPI non choisie est refusée.

### C6 — Vague 2 (4 PR)

Redshift et Databricks SQL, puis Unity Catalog et Delta Sharing, puis Iceberg REST, puis Synapse ou Fabric, fichiers SharePoint, OneDrive et HTTP.

### C7 — Vague 3 (3 PR)

MongoDB, puis Elasticsearch et OpenSearch, puis Cassandra.

---

## 13. Critères de réussite globaux

- **Chaque profil affiché** porte un niveau calculé depuis une preuve datée.
- **Ajouter un profil** de la famille `sqlalchemy` ou `object_store` sans code fait passer le kit.
- **Après C4**, au moins onze sources de données sont « Vérifiées » ou « Certifiées » : PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, SAP HANA, Snowflake, BigQuery, S3, Azure Blob et GCS.
- **Après C7**, la couverture de papAI est atteinte et dépassée par les lakehouses et Databricks.
- **Aucun secret** n'apparaît dans un journal, un manifeste ou une erreur.
- **Aucune adresse interne** n'est joignable par un profil en mode `enforce`.

---

## 14. Spikes

| Spike | Question | Lot |
|---|---|---|
| S-C1 | pyarrow.fs, obstore ou fsspec pour le stockage objet : couverture d'ADLS hiérarchique, renouvellement des identifiants, débit, taille | C3 |
| S-C2 | Taille et licence de chaque pilote, prolongement de S-D7-3 | C0 |
| S-C3 | OAuth des serveurs MCP officiels : enregistrement, portées, renouvellement, contraintes de tenant, liste initiale des éditeurs | C5 |
| S-C4 | Authentification Entra ID pour Synapse et Fabric sans bibliothèque ODBC | C6 |
| S-C5 | dlt contre PyAirbyte pour la longue traîne : licences, taille, exécution isolée, qualité des sources | Après C4 |
| S-C6 | Coût et propriété des comptes de test cloud, rotation de leurs identifiants | C4 |

---

## 15. Risques

| Risque | Mitigation |
|---|---|
| Un catalogue large mais fragile | Kit commun, badge calculé et périmé après un délai, canari pour « Certifié » |
| Des images trop lourdes | Image et file dédiées, budget mesuré par pilote |
| Une surface SSRF multipliée | Garde commune en `enforce` avant tout nouveau profil |
| Le coût des comptes cloud | Spike S-C6, purge systématique, budget explicite |
| Des serveurs MCP tiers qui changent | Version épinglée, tests de contrat, niveau « Tiers » seulement |
| Une dispersion loin des parcours de référence | Vagues ordonnées par la parité papAI et les demandes réelles. Les deux parcours de référence restent prioritaires dans les arbitrages |

---

## Annexe A — Codes d'erreur additionnels

Ils complètent l'annexe B du plan.

| Code | Cas |
|---|---|
| `CONNECTOR_DNS_FAILED`, `CONNECTOR_NETWORK_UNREACHABLE` | Étapes du diagnostic de connexion |
| `CONNECTOR_BUCKET_NOT_FOUND`, `CONNECTOR_PREFIX_FORBIDDEN` | Conteneur absent, préfixe hors du périmètre autorisé |
| `CONNECTOR_OBJECT_TOO_LARGE`, `CONNECTOR_FORMAT_UNSUPPORTED` | Fichier trop gros, format non pris en charge |
| `CONNECTOR_EXPORT_PREFIX_EXISTS` | Export vers un préfixe existant sans confirmation |
| `CONNECTOR_NOSQL_OPERATOR_FORBIDDEN` | Opérateur ou script refusé dans une requête NoSQL |
| `CONNECTOR_OAUTH_CONSENT_REQUIRED`, `CONNECTOR_OAUTH_TOKEN_EXPIRED` | Autorisation utilisateur absente ou expirée |
| `CONNECTOR_TOOL_NOT_ALLOWED` | Outil MCP ou opération OpenAPI hors liste blanche |
| `CONNECTOR_OPENAPI_INVALID` | Spécification invalide ou non prise en charge |
| `CONNECTOR_CREDENTIAL_REVOKED` | Identifiant révoqué ou tourné |

## Annexe B — Réglages additionnels

- `celery_connectors_queue` ;
- `connector_object_max_mb`, `connector_import_max_files` ;
- `connector_watch_interval_s` ;
- `connector_network_policy_mode` (`report` puis `enforce`) ;
- `connector_certification_max_age_days` (30 par défaut) ;
- `connector_mcp_catalog_enabled`, `connector_openapi_import_enabled`.

## Annexe C — Sources publiques consultées le 14 octobre 2026

- [Documentation de Sim](https://docs.sim.ai/) et [outils de Sim](https://docs.sim.ai/tools)
- [Nombre d'intégrations de n8n en 2026, mpiresolutions](https://mpiresolutions.com/blog/how-many-integrations-does-n8n-have/)
- [Présentation de n8n, Techjack Solutions](https://techjacksolutions.com/ai-tools/n8n/what-is-n8n/)
- [Revue de n8n, Hackceleration](https://hackceleration.com/?p=493414)
- [Dataiku, connexion aux données](https://doc.dataiku.com/dss/latest/connecting/index.html) et [version 12](https://doc.dataiku.com/dss/12/connecting/index.html)

La couverture de papAI provient du code de `papai-latest` (`spark-service`, `core`, `frontend`), consulté le même jour.
