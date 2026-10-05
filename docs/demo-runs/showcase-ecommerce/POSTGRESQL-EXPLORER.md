# PostgreSQL : exploration et préparation DataOps

Livraison sur `demo/agentic`, QA du 2 octobre 2026 (Europe/Paris).

La carte PostgreSQL ouvre désormais `/connectors/postgresql`. Le parcours
utilise la connexion enregistrée du workspace : configuration, test réel,
découverte des schémas et tables accessibles, choix des colonnes, aperçu puis
création d'un dataset natif versionné. Un setup enregistré reste distinct d'une
connexion vérifiée ; le catalogue Resources ne compte pas ce setup comme une
connexion active mesurée.

## Comportement des données

- L'aperçu lit jusqu'à 25 lignes dans PostgreSQL. Il indique la date de lecture
  et la présence éventuelle de lignes supplémentaires.
- L'import relit toute la table pour les colonnes sélectionnées dans une
  transaction PostgreSQL en lecture seule. Il ne réutilise pas les lignes de
  l'aperçu. Une empreinte vérifie l'identité de la connexion et le schéma avant
  la lecture.
- Le dataset est enregistré dans le stockage natif Parquet et les métadonnées
  de DataOps, avec profil de colonnes et version. Sa provenance expose la base,
  le schéma, la table, les colonnes, la date de capture et une empreinte SHA-256.
  Le dataset reste lisible après modification de la table source.
- Les imports sont limités à **10 000 lignes et 16 Mio**. Un dépassement refuse
  l'import complet ; aucun dataset partiel n'est présenté comme réussi.
  L'explorateur accepte au plus 500 tables et 128 colonnes par table.
- Les tables ordinaires et les tables partitionnées parentes sont proposées.
  Les vues, tables étrangères, tables système et types non pris en charge sont
  exclus. Les droits du compte PostgreSQL filtrent le catalogue.
- Les décimaux, JSON, UUID, heures et intervalles sont préservés en texte,
  explicitement signalé dans la sélection de colonnes. Les entiers int64 restent
  numériques dans Parquet et sont affichés sans arrondi dans les aperçus.
- Les requêtes sont composées avec des identifiants cités et des paramètres ;
  cette page ne reçoit aucun SQL libre. Toutes les lectures utilisent une
  transaction en lecture seule, des délais et des limites de volume.
  PostgreSQL calcule un cumul de taille dans l'ordre de lecture : dès qu'une
  ligne franchit la limite, le serveur renvoie un indicateur et des valeurs
  NULL, jamais les cellules volumineuses. Les lignes arrivent par lots de 500,
  et le lecteur vérifie ensuite le volume total de la réponse. La requête ne
  dépend d'aucune fonction récente : elle fonctionne aussi avant PostgreSQL 12.
- Un import lit d'abord la source, puis verrouille brièvement le workspace en
  `FOR NO KEY UPDATE` pour attribuer la version : les runs, messages et
  journaux du workspace continuent de s'écrire pendant la lecture.
- Un échec s'affiche dans l'étape concernée, à côté de l'action, avec un bouton
  Réessayer. Une requête refusée après connexion (`PG_QUERY_FAILED`, 502) se
  distingue d'un serveur injoignable (`PG_UNAVAILABLE`, 503). L'interface et
  l'API affichent le code SQLSTATE standard ; les journaux du backend notent
  l'étape, la classe d'erreur et ce code, jamais le message du pilote.
- Seuls les administrateurs du workspace peuvent utiliser les identifiants
  enregistrés pour explorer, tester ou importer. Aucun mot de passe n'est
  retourné dans une réponse, un dataset ou sa provenance.
- Une relance du même import réutilise son identifiant et sa version. Une
  nouvelle demande d'import crée une nouvelle version du nom choisi.

Les datasets produits sont utilisables par les transformations natives et les
consommateurs de datasets du Flow Builder. La QA exécute une transformation SQL
native à partir d'un import PostgreSQL réel et vérifie sa filiation. Le Flow
métier des réclamations reste sur son lecteur SQL en direct et ses preuves
documentaires ; cette livraison n'y ajoute pas de modèle entraîné. Le ROI de
la démo dépend toujours de l'expérimentation mesurée documentée dans
[LIVE-QA-2026-10-02.md](./LIVE-QA-2026-10-02.md).

## Activation par l'opérateur

Déployer le frontend et le backend du même commit, après synchronisation du
miroir Bitbucket de `demo/agentic`, selon le
[runbook VM sûr](../../ops/agentium-safe-vm-deployment.md). Le SHA exact de la
livraison est communiqué avec le commit poussé. Cette extension n'ajoute ni
migration SQL ni dépendance runtime. Conserver la connexion Showcase existante
avec `luma_claims_reader` et son mot de passe enregistré.

Recette après déploiement sur `https://agentium.papai.ai` :

1. Sélectionner **Showcase**, ouvrir **Connecteurs → PostgreSQL → Explorer
   PostgreSQL**. Vérifier que la page dédiée s'affiche et que le compte enregistré
   est conservé. Laisser le champ mot de passe vide si la configuration est
   enregistrée à nouveau.
2. Cliquer **Tester la connexion**, puis **Explorer les tables**. Le catalogue
   doit venir de `GET /api/v1/connectors/postgresql/catalog` et afficher les tables
   réellement accessibles au lecteur.
3. Choisir `showcase_ecommerce`, puis `claims`. Vérifier les colonnes, sélectionner
   celles à préparer, puis **Afficher l'aperçu**.
4. Nommer le dataset `Luma — Réclamations PostgreSQL`, puis **Créer le dataset**.
   Le nombre de lignes enregistré doit correspondre à la lecture complète de la
   table à cet instant, même si l'aperçu en montre moins.
5. Ouvrir le dataset, consulter **Aperçu**, **Colonnes** et **Filiation**. Vérifier
   la source PostgreSQL, la table et la date de capture. Le dataset peut ensuite
   être sélectionné comme entrée dans une transformation DataOps.

Les appels d'exploration et d'import doivent répondre 403 pour un membre sans
droits d'administration, avant toute connexion à PostgreSQL. Un changement de
workspace pendant une lecture doit effacer le parcours et ignorer la réponse
tardive de l'ancien workspace.

## Vérifications de livraison

- PostgreSQL **16.2 local isolé**, compte SELECT : catalogues, droits, types,
  lecture seule effective, précision des décimaux/JSON/int64, changement de
  schéma, snapshot persistant et consommation par une transformation SQL native.
- Backend : **131 tests passants** couvrant le nouvel explorateur, les connecteurs
  génériques, datasets, transformations et lecteur métier des réclamations.
- Frontend : compilation production, **1 891 tests unitaires passants** et gardes
  i18n/chrome/liens ; le contrôle de conformité produit passe également.
- Navigateur local avec API simulée : **9 parcours PostgreSQL**, dont français
  sombre, français mobile clair, anglais clair, droits, édition sans remplacement
  du mot de passe, limites, relance d'import et réponse tardive après changement
  de workspace. Axe ne détecte aucune violation sur la nouvelle page.
  Les **5 parcours de régression** du studio réclamations sont également vérifiés.
- La QA navigateur capture les étapes connexion, aperçu et dataset dans le
  répertoire de résultats Playwright. Ces images utilisent des données fictives
  et ne constituent pas une preuve de déploiement sur Agentium.

Le test PostgreSQL réel est activé explicitement avec
`RUN_POSTGRESQL_BROWSER_INTEGRATION=1` contre une instance de test locale nommée
`agentium_pg_browser_test` sur `127.0.0.1:55432`. Il ne contacte pas la base de démo.
La QA visuelle utilise `E2E_BASE_URL=http://127.0.0.1:4238`,
`E2E_CHROME_V2_MOCKED=1` et les specs `29-postgresql-connector-mocked.spec.ts` et
`28-claims-studio-mocked.spec.ts`.

La validation du nouveau parcours sur le domaine Agentium reste à effectuer
après le déploiement opérateur.

Le pré-commit passe sur les fichiers livrés, avec le hook de mise à jour
automatique des versions d'outils désactivé pour conserver la configuration
revue du dépôt. Le pré-commit global a également été exécuté dans un checkout
isolé : il relève des anomalies préexistantes de droits d'exécution, de fins de
fichier, de whitespace et de YAML (`docker/livekit/agentium-livekit.yaml`),
ainsi que l'absence de `shellcheck`/`shfmt` dans le cloud. Le hook de mise à jour
propose aussi une nouvelle version de Ruff. Ces changements extérieurs à cette
livraison n'ont pas été reportés dans `demo/agentic`.
