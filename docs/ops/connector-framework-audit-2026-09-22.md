# Note — catalogue de connecteurs et framework de création

22 septembre 2026. Compilation de l'audit Sim (VM NAWA, v0.8.26), n8n (clone local `n8n-nodes-base` 2.40.0, commit `32aa4629`), Dataiku DSS, DuckDB, Databricks Delta, et de ce qu'Agentium a déjà dans `backend/app/services/connectors/`.

But : Agentium comme framework qui offre un catalogue natif riche **et** un chemin court pour qu'un utilisateur crée le connecteur qui manque. Cette note ne réécrit pas la roadmap F1–F6. Elle fixe le contrat que cette roadmap devra respecter.

## 1. Ce qu'on a mesuré

| Produit | Ce qui a été lu | Catalogue |
|---|---|---|
| Sim / NAWA | VM NAWA, images pinées v0.8.26, base `simstudio` | ~314 blocs sur GitHub `main`. Sur la VM : une app OAuth Google, credentials Gmail, Sheets, bot Slack, clés OpenRouter. Blocs réellement posés : `gmail_v2`, `google_sheets_v2`, `slack`, `mothership`. |
| n8n | clone local du dépôt n8n | 308 dossiers de nœuds dans `nodes-base`, 458 credentials (118 OAuth2, 332 clés ou schémas propres), 1 238 fichiers de test dans `nodes-base`. Slack : v1 à v2.7, ~12 300 lignes hors tests. |
| Dataiku DSS | Documentation DSS 14/15 | Connexion SQL nommée **et** JDBC libre : JAR, URL `jdbc:`, dialecte. Lecture souvent possible, écriture rarement sans travail. |
| DuckDB | Documentation des extensions | `ATTACH` Postgres et MySQL (lecture et écriture, mode `READ_ONLY`). Extension Delta : lecture, append, time travel. Pas de driver JAR. |
| Databricks | Delta + Lakehouse Federation | Delta est un format de table. Federation est un catalogue de lecture vers des bases externes, pas un JDBC d'écriture. |
| Agentium | Code `demo/agentic` | MCP (contrat SAP à outils nommés, écritures allow-listées), HANA (SQL lecture, Fernet), SharePoint OTP, RPA, skill `polars_transform_v1`, Parquet dans MinIO, Postgres applicatif. |

## 2. Verdict d'audit

Les catalogues Sim et n8n sont déjà écrits. Activer une tuile qui existe n'est pas du développement : c'est une app OAuth ou une clé, plus l'URL publique de callback. La différence est ailleurs.

**n8n gagne la profondeur d'un connecteur.** Credential réutilisable, nœud versionné (ressource × opération), `continueOnFail` dans 260 fichiers de nœud, erreurs typées, tests à côté de l'opération. Un workflow ancien charge encore Slack v1. L'échappatoire si la tuile manque : nœud HTTP, nœud Code, paquet community. La licence fair-code interdit d'en faire le produit revendu.

**Sim gagne l'embarquement dans NAWA.** Apache 2.0, image déjà en production, un bloc par app, OAuth central (une app Google couvre Gmail, Drive, Sheets). Le graphe ne stocke qu'un identifiant de credential. Monter de version, c'est changer l'image entière. Une tuile absente se bricole avec le bloc API ou Function. Un vrai connecteur nouveau, c'est une modification de cette image. 56 tests colocalisés aux blocs sur `main`, contre 1 238 fichiers dans `nodes-base`. Ce n'est pas toute la suite Sim. C'est le signal collé au catalogue.

**Aucun des deux n'a de JDBC.** n8n parle `pg`, `mysql2`, `mssql`, `oracledb`, `snowflake-sdk`, un nœud par moteur. Sim a les blocs `postgresql`, `mysql`, `mssql`, `mongodb`, `snowflake`, `clickhouse`, `databricks`, `google_bigquery`. Le SQL brut est générique **dans un dialecte déjà supporté**. Oracle, HANA, DB2 hors liste demandent un processus Java à côté.

**MCP est le client générique des deux.** n8n : MCP Client, MCP Client Tool, MCP Server Trigger, registry, transports HTTP streamable et SSE, auth de « aucune » à OAuth2. Sim : bloc MCP (lister / exécuter), serveurs déclarés dans le workspace, `streamable-http`, et Sim peut servir `/api/mcp`. Un serveur JDBC-MCP se branche sur les deux sans modifier leur code. Ce n'est pas une fonction de leur catalogue.

**Dataiku est le seul cadre JDBC générique** parmi les plateformes comparées. On dépose un JAR, on donne `jdbc:…`. La doc prévient : hors liste, la lecture marche souvent, l'écriture rarement. Delta n'est pas ce cadre. DuckDB est le portail SQL le plus proche de ce qu'Agentium sait déjà faire (Parquet, fichiers, Postgres, MySQL en attach).

## 3. Ce qu'Agentium a déjà, et qu'il ne faut pas reconstruire

Le plan données n'est pas un trou.

- **Tabulaire.** `polars_transform_v1` soumet une exécution, le worker `agentium.tabular_polars_execute` lance Polars. Les datasets vivent en Parquet sous MinIO (`workspaces/…/tabular/datasets/…/data.parquet`). Postgres reste le registre, pas le fichier.
- **SAP en lecture SQL.** `connectors/hana` : config workspace, mot de passe Fernet (`HANA_CONNECTOR_FERNET_KEY`), SQL borné aux requêtes `SELECT` / `WITH`, timeout court, repli démo explicite.
- **SAP en outils.** `connectors/mcp` : serveurs dans `workspace.settings`, transports SSE et streamable HTTP, auth bearer / OAuth client-credentials / inherit. Le contrat PR→PO est une liste fermée (`list_approved_prs`, `check_budget`, `create_po`, …). Les écritures (`reject_pr`, `create_po`, `handle_rejection`) passent par une seule porte (`write.py`) : allow-list, preview distincte de l'appel, `isError` du transport ignoré au profit du payload SAP, rollback si le commit échoue. `mcp_call_v1` existe, mais les skills nommées sont la voie canvas.
- **Même enveloppe ailleurs.** SharePoint OTP et RPA réutilisent le chiffrement de secret. Ce n'est pas encore un registre unique, mais le motif est là.

Ce qui manque n'est pas un moteur de données. C'est la **forme produit** : un catalogue que l'on parcourt, et un gabarit pour ajouter un connecteur sans ouvrir `contract.py`.

## 4. Le framework cible

Deux vitesses, un seul objet.

L'objet s'appelle une **connexion**. Elle a un nom, un moteur, un secret chiffré, un mode (lecture ou écriture), et un contrat d'opérations. Un bloc ou une skill ne voit qu'un identifiant. Le secret ne traverse ni le graphe, ni le chat, ni le Parquet.

### 4.1 Catalogue natif

Court, et tenu. Pas 300 tuiles le jour un.

| Famille | Natif | Pourquoi celui-là |
|---|---|---|
| Fichiers analytiques | MinIO / S3 + Parquet + Delta en lecture via DuckDB | Déjà le plan tabulaire. Delta se lit, il ne remplace pas Postgres. |
| SQL opérationnel | Postgres, MySQL, SQL Server | Drivers natifs. Une connexion, pas trois blocs. |
| SQL analytique multi-sources | DuckDB `ATTACH` (Postgres, MySQL, Parquet, Delta), `READ_ONLY` par défaut | Un SELECT, plusieurs sources, sans JAR. |
| ERP | SAP : HANA lecture + MCP outils nommés | Déjà le différenciateur. On l'expose comme connexion, pas comme sept skills orphelines. |
| Productivité PIH | Un OAuth Microsoft (Graph : mail, fichiers, listes) quand le besoin est là | Une app, plusieurs opérations. On ne clone pas les 458 credentials n8n. |
| Longue traîne | MCP générique, puis JDBC-MCP si le driver n'existe qu'en Java | Oracle, DB2, un SAP hors contrat. |

Chaque natif a : un test d'opération lecture, un test qui refuse l'écriture sans porte, une fixture, et une version de contrat. On copie à n8n la **version du nœud** (Slack v1 reste chargeable) et le test à côté de l'opération. On ne copie pas le volume.

### 4.2 Créer un connecteur sans fork

Trois gabarits, du plus sûr au plus libre. L'utilisateur n'en voit qu'un à la fois.

**Gabarit A — MCP.** Il colle l'URL, choisit le transport (déjà `http_sse` ou `streamable_http`), pose le secret (bearer ou OAuth, déjà dans `ALLOWED_AUTH_MODES`). Agentium liste les outils (plafond déjà à 80). Il coche ceux qui sont des lectures et ceux qui sont des écritures. Les écritures naissent verrouillées : preview, décideur, timeout qui n'est pas un succès. C'est `write.py` généralisé, plus le contrat PR→PO codé en dur. Temps visé : moins d'une heure, sans Python.

**Gabarit B — SQL.** Il choisit Postgres, MySQL, SQL Server, HANA ou DuckDB. Il donne l'hôte et le secret. La lecture est un SELECT borné (lignes, temps), comme HANA le fait déjà. L'écriture est un second verbe, même porte que SAP. Pas de JDBC dans le process Python. Si le moteur n'est pas dans la liste, le gabarit A pointe vers un serveur JDBC-MCP qu'on opère nous, pas l'utilisateur.

**Gabarit C — table.** Pour un fichier ou un export : schéma, Parquet dans MinIO, skill Polars. Le connecteur « créé » est un dataset, pas une API. C'est le chemin le plus court pour un classeur PIH.

Le code libre (`mcp_call_v1` sans liste, SQL arbitraire, Polars arbitraire) reste une capability d'ingénieur, pas le bouton du process owner.

### 4.3 Contrat unique d'une opération

Toute opération, native ou créée, expose la même fiche.

- **Nom stable** et version (`sap_create_po_v1`). Une nouvelle version n'écrase pas l'ancienne.
- **Effet** : `read`, `preview`, ou `write`. `preview` ne peut pas devenir `write` selon le texte des paramètres. C'est déjà la règle MCP/SAP.
- **Entrée / sortie** schématisées. Le Flow mappe des champs, il ne devine pas un JSON.
- **Borne** : lignes, octets, durée. HANA a `DEFAULT_MAX_ROWS = 200`. On généralise.
- **Secret** : identifiant seulement. Fernet déjà utilisé pour HANA, SharePoint, RPA. Un seul coffre, pas trois enveloppes.
- **Preuve** : l'appel, le hash du contrat, l'identité si c'est une écriture, le fait que le transport a menti ou non. SAP ignore déjà le flag `isError` du MCP et lit le payload. Cette méfiance devient le défaut de tout write.
- **Échec** : une erreur nommée (`mcp_unconfigured`, outil inconnu, SQL refusé), pas un stack dans le chat.

### 4.4 Ce qu'on ne construit pas

- Le catalogue n8n (308 apps) ni la palette Sim (314 blocs). On documente l'échappatoire MCP le jour où l'app manque.
- Un driver JDBC dans le backend Python.
- Delta comme base opérationnelle. Delta est une source DuckDB ou un export. Postgres et le Parquet MinIO restent la vérité.
- Dataiku comme dépendance. On retient l'idée (connexion + dialecte + « l'écriture n'est pas gratuite »), pas le produit.
- Un second moteur à côté de Sim si Sim reste le builder NAWA. Les connexions Agentium se branchent comme outils MCP que Sim sait déjà consommer, ou comme skills du Flow Agentium. Un seul coffre de secrets.

## 5. Recommandations, dans l'ordre

1. **Nommer le registre.** Une page Connexions : SAP (MCP + HANA), MinIO/Parquet, Postgres. Les skills actuelles deviennent des opérations de ces connexions. Rien de nouveau côté protocole.
2. **Généraliser la porte d'écriture.** Sortir l'allow-list PR→PO du cas particulier vers le gabarit A : toute opération cochée `write` passe par preview, décideur, et réconciliation. `mcp_call_v1` sans coche reste refusé pour un rôle métier.
3. **Un bloc SQL à connexions**, pas un bloc par moteur. Postgres d'abord (déjà là), HANA ensuite (déjà là, le déclarer dans le même registre), MySQL / SQL Server si un BRD le demande. DuckDB en lecture sur le Parquet MinIO et, en `READ_ONLY`, sur Postgres.
4. **Gabarit MCP en UI**, sur le service qui existe. URL, auth, liste d'outils, coche lecture/écriture, test de lecture. Le contrat codé à la main reste pour SAP, qui est le natif de référence.
5. **Version et test obligatoires** pour chaque natif, à la manière n8n, sur cinq connexions pas sur cent. Une opération sans test de refus d'écriture ne sort pas.
6. **JDBC seulement comme sidecar MCP** le jour où un moteur absent bloque un projet (Oracle, DB2). Ce n'est pas le framework par défaut : Dataiku montre que l'écriture JDBC « générique » ment.
7. **Ne pas importer le catalogue Sim ni n8n.** Si NAWA powered by Sim reste le builder, les tuiles Sim (Gmail, Sheets) s'allument par OAuth, une app à la fois. Agentium ne les réécrit pas. Il possède SAP, le tabulaire, et le gabarit « je crée le connecteur ».

## 6. Lien avec la roadmap F#, sans la réécrire

Les portes automation-first restent le chemin du premier run (Trigger, Agent, Output, Run du brouillon). Cette note dit ce que la porte 2 y pose :

- le natif SAP et le natif table ne sont pas des cérémonies avant le run ;
- ils apparaissent comme opérations d'une connexion, après le premier succès, avec l'écriture fermée ;
- le framework « créer son connecteur » est le gabarit A (MCP) puis B (SQL), pas un nouveau System à remplir.

Le détail F1–F6 (compagnon, diagnostic, SPARK-089, ligne de table, graphiques, interfaces) se reprend ensuite. Le contrat ci-dessus est la contrainte : une ligne de table ou un graphique qui lit une base passe par une connexion versionnée, pas par un secret dans le nœud.

## 7. Licences pour un usage dans Agentium

Ce n'est pas un avis d'avocat. C'est la lecture des textes au 22 septembre 2026, pour un produit que Datategy livre à des clients (NAWA, PIH), pas pour un usage interne seulement.

| Composant | Licence lue | Dans Agentium vendu à un client |
|---|---|---|
| Sim (dépôt `simstudioai/sim`) | Apache 2.0 | Oui. Usage, modification, revente. Garder les notices, dire ce qui a été modifié. Le Chat hébergé sim.ai (`COPILOT_API_KEY`) est un service à part, pas une condition du code Apache. |
| n8n, tronc `master` hors `.ee` | Sustainable Use License 1.0 | Non, si Agentium est fourni à un client. Usage interne Datategy ou don non commercial seulement. Licence non cessible, non sous-licenciable. |
| Fichiers n8n `.ee.` | n8n Enterprise License | Non sans contrat Enterprise. Même la production interne est réservée aux titulaires. Copie et test de développement seulement. |
| Delta Lake, delta-rs | Apache 2.0 | Oui. |
| Unity Catalog open source (`unitycatalog/unitycatalog`) | Apache 2.0 | Oui, pour le serveur et l'API ouverts. |
| Unity Catalog Databricks (federation, gouvernance hébergée) | Contrat Databricks | Non « libre ». C'est un service. |
| DuckDB | MIT (Stichting DuckDB Foundation) | Oui, y compris revente. Garder le copyright. |
| Polars | MIT | Oui. Déjà dans le worker tabulaire. |
| Format Parquet, Iceberg | Apache 2.0 | Oui. |
| SDK MCP Python | MIT (Anthropic) | Oui. Le protocole ne remplace pas la licence du serveur qu'on appelle. |
| Client `minio-py` | Apache 2.0 | Oui. |
| Serveur MinIO | AGPL 3.0 | Pas libre d'embarquer. Le livrer dans la stack client, ou le modifier et l'exposer en réseau, oblige à fournir le source correspondant. Parler S3 à un stockage du client, ou à un serveur qu'on n'a pas modifié et qu'on ne distribue pas, reste le chemin prudent. |
| PostgreSQL | Licence PostgreSQL (permissive) | Oui. |

Conséquence pour le framework de connecteurs : on peut s'appuyer sur Sim, DuckDB, Polars, Delta, le Unity Catalog ouvert et le SDK MCP. On ne copie pas le catalogue n8n dans Agentium. On ne livre pas le binaire MinIO comme partie du produit.
