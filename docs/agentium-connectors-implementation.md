# D7 — État du développement et limites de qualification

14 octobre 2026. Complément au [plan connecteurs](agentium-dataops-connectors.md),
sans remplacement de ses critères de recette ni du plan DataOps d’origine.
Le développement continue sur autorisation de l’utilisateur malgré l’absence de
banc accessible ici. La [procédure de certification déléguée](agentium-connectors-certification-handoff.md)
est destinée à l’opérateur disposant de la VM. Elle n’a pas été exécutée sur cette VM.

**Aucun nouveau profil n’est déclaré Vérifié ou Certifié par cette livraison.**
Les capacités YAML décrivent des opérations développées ; elles ne constituent
pas une preuve de compatibilité avec toutes les versions du fournisseur.
Les doubles HTTP/DBAPI, fichiers locaux et migrations PostgreSQL ci-dessous
ne remplacent pas les campagnes externes du plan. C0 et CH restent ouverts.

## Lots et points de reprise

| Lot | Développement présent | Recette externe encore nécessaire |
|---|---|---|
| C0 | Garde réseau SQL/HTTP, exceptions administrées et révocables, preuves immuables, image dédiée, deux files, kit réel et campagne nocturne opt-in | Observation puis `enforce` en production ; image construite et mesurée ; campagne complète acceptée |
| C1 | Connexions multiples, profils, grants, secrets utilisateur, délégations de versions publiées, OAuth, page Connexions, migration PG/HANA explicite et registre partagé DataOps | PG vérifié, migration des configurations réelles et compatibilité de la release ; aucune qualification HANA |
| C2 | Lectures bornées/partitionnées/incrémentales, append/overwrite/upsert natifs PG/MySQL/MariaDB/SQL Server/Oracle ; contrats d’écriture, aperçu préalable, reçus et rapprochement | TLS/authentification de chaque moteur, import PG 10 M avec mutations, écritures 1 M et injections de pannes |
| C3 | S3/compatibles, Azure Blob/ADLS, GCS : import, exports immuables ou Delta, pointeur conditionnel, surveillance Flow, filiation et requalification | MinIO/Azurite/GCS, authentifications réelles, concurrence et révocation pendant transfert, débit |
| C4 | API SQL Snowflake et BigQuery, lectures et écritures approuvées, identités stables, script/timer de campagne isolée | Comptes réels, budgets des comptes, kit et premier canari sur VM |
| C5 | Catalogue MCP officiel, OAuth personnel PKCE/DCR, délégation/révocation, import OpenAPI autonome, outils filtrés ; Skills lecture et demande d’écriture | Installation et consentements réels, contraintes de tenant, renouvellement/révocation et reçus des éditeurs |
| C6 | Redshift lecture/append/upsert ; Databricks SQL ; Unity Catalog/Delta Sharing ; Iceberg REST ; Synapse SQL-auth ; SharePoint/OneDrive/HTTP | Campagnes fournisseur ; restrictions de formats et de pilotes ci-dessous |
| C7 | MongoDB, Elasticsearch/OpenSearch et Cassandra ; conservation JSON, aplatissement choisi, token ranges/PIT, écritures Mongo/search approuvées | Serveurs réels, topologie/TLS, permissions, transactions Mongo, résultats partiels de bulk et défaillances |
| CH | Mode démo explicite conservé, TLS strict et écritures fermées | En attente d’une instance HANA réelle, conformément au choix utilisateur |

## Contrats de fonctionnement

- Le processus API ne charge pas les pilotes optionnels et ne fait pas les imports
  de données. Celery transporte uniquement l’identifiant d’un `ComputeRun`.
  Un enfant supervisé reçoit les secrets juste avant exécution, avec échéance
  absolue, limite mémoire, annulation et garde réseau. Le parent revalide les
  droits, révisions et secrets pendant le calcul et avant publication.
- Une ligne de calcul porte bail, placement local, workspace, origine Flow,
  coûts et quota. L’attente compte dans l’échéance. Un calcul lancé et perdu
  n’est jamais rejoué automatiquement. Le pont DataOps rejoint ce registre
  lorsque le framework connecteurs est activé ; il ne soumet pas un second job.
- Le coût monétaire reste `null` tant que les tarifs opérateur ne sont pas
  configurés. Les heures-cœur mesurent la durée occupée multipliée par les cœurs
  attribués ; elles ne sont pas un compteur de cycles CPU.
- Chaque écriture approuve le hash d’un contrat exact : connexion/révision,
  paramètres, version et empreinte des données, cible. Une prévisualisation
  réussie du même contrat est exigée côté serveur avant approbation. Pour les
  outils externes, ce contrôle valide le contrat et le schéma : il ne simule pas
  les effets du fournisseur. Les comptages estimés sont signalés comme tels.
- L’intention passe à `sent` avant toute mutation possible. Une réponse perdue
  donne `unknown`, bloque la cible et ouvre une décision durable. Un rapprochement
  exige un reçu natif correspondant pour conclure `applied`. Pour MCP/OpenAPI,
  une réponse synchrone positive vaut succès déclaré du fournisseur ; elle ne
  fournit pas un reçu natif permettant de rapprocher une réponse perdue.
  Un administrateur peut abandonner
  explicitement l’incertitude ; cet abandon ne prouve pas l’absence d’écriture
  et ne rejoue jamais l’opération initiale.
- Le Skill de lecture renvoie un identifiant de calcul et une opération `status`
  aux agents. Dans un Flow, il attend la publication et expose le dataset sous
  `result.dataset.dataset_id`. Le Skill de demande d’écriture prépare le contrat
  et son aperçu ; l’approbation et l’envoi restent dans la page Connexions.
- Le filigrane incrémental est le couple watermark/clé et n’avance qu’avec la
  publication du dataset. Le contrôle de révision rejette les lecteurs concurrents
  devenus obsolètes. Le recouvrement déduplique les clés. Les suppressions de la
  source ne constituent pas un CDC et ne sont pas propagées implicitement.
- `require_consistency` refuse une importation qui offrirait une cohérence plus
  faible. PG utilise une transaction en lecture seule `REPEATABLE READ` ; les
  autres SQL n’annoncent pas le même snapshot. Les imports objet figent la liste
  et les ETags/générations. Une empreinte faible ou absente ne promet pas de snapshot.
- Un export Parquet écrit sous `v=<operation_id>/`, puis son manifeste et enfin
  `_LATEST.json` sous condition. Le lecteur suit ce manifeste et vérifie ses
  empreintes. Delta publie son log natif avec création exclusive. Aucun chemin
  d’export ne supprime les versions historiques. Chaque publication Parquet est
  une version complète ; son contrat refuse `mode`. `append`/`overwrite` sont
  des modes d’écriture Delta, pas une fusion implicite des versions Parquet.
  Un export Parquet vide est refusé avant tout accès distant : ce lecteur ne
  peut pas encore publier un flux vide en conservant son schéma.

## Limites explicites de la première implémentation

Ces limites ne ferment pas les critères plus larges du plan.

1. **Bornes locales.** Imports : 3 M lignes par défaut, jusqu’à 10 M sur demande,
   1 Gio par import et 10 000 objets. Les plafonds de certains formats/aperçus sont
   plus faibles. Le worker requiert 4 Gio de scratch libres ; le chart réserve
   un volume disque de 20 Gio. Un dépassement échoue avec un code fermé.
2. **SQL cloud.** Les écritures Snowflake/BigQuery/Databricks utilisent leurs API
   SQL gardées, avec un maximum de 4 000 lignes et 1 Mio de SQL inline. Au-delà,
   `CONNECTOR_CLOUD_STAGING_REQUIRED` refuse l’opération : le transport bulk vers
   un stage fournisseur reste à développer/qualifier. Les résultats temporels
   dont le format dépend de la session conservent le texte exact du fournisseur.
3. **SQL natif.** Les tables cibles et `_agentium_operations` doivent exister.
   Aucune création DDL implicite ; overwrite fait un `DELETE` transactionnel.
   MySQL/MariaDB exigent InnoDB pour les données et le marqueur. Les comptes
   doivent disposer des seules permissions prévues pour le parcours choisi.
   L’upsert ligne par ligne n’est pas encore une garantie de débit à 1 M lignes.
4. **Redshift.** Append/upsert seulement, avec verrou explicite du registre puis
   de la cible avant lecture et mutation. La clé primaire n’est pas supposée
   contraignante : doublons et cardinalités sont vérifiés dans la transaction.
   Overwrite reste refusé. Cette implémentation exige la qualification du
   protocole sur Redshift réel avant de promettre sa compatibilité.
5. **Synapse/Fabric.** C6 retient Synapse via SQL-auth et `python-tds`, sans ODBC.
   Ce pilote ne fournit pas l’authentification Entra requise par Fabric : aucun
   profil Fabric exécutable n’est affiché. S-C4 reste ouvert pour Entra ; les
   différences SQL/transactions Synapse restent à qualifier sur un compte réel.
6. **Lakehouse.** Delta refuse les deletion vectors, le column mapping et les
   checkpoints v2/sidecars non pris en charge. Iceberg lit les schémas primitifs
   et refuse les delete files au lieu de réintroduire leurs lignes ; écriture
   limitée aux tables v2 existantes, non partitionnées, à schéma primitif.
   UUID, schéma et snapshot attendus sont liés au contrat puis au CAS REST.
   Les snapshots 64 bits sont conservés comme chaînes décimales dans l’UI.
   Aucun `VACUUM`, retrait de snapshot ou effacement distant n’est fourni.
7. **NoSQL.** Les documents JSON d’origine sont conservés comme chaînes pour
   préserver absence/null et types BSON représentables ; l’aplatissement est
   explicite. Les filtres Mongo/search sont limités aux opérateurs implémentés.
   Mongo nécessite transactions et collection de marqueurs précréée. Un bulk
   search partiel reste incertain ; aucun rollback fictif n’est annoncé.
   Cassandra reste en lecture seule.
8. **Outils.** Les outils tiers n’acquièrent jamais un badge natif. Un outil MCP
   d’écriture est fermé tant qu’un administrateur n’a pas sélectionné l’opération
   et approuvé le contrat. L’absence de protocole de reçu laisse un résultat perdu
   inconnu. OpenAPI n’accepte aucune référence distante ; les méthodes/origines
   non sélectionnées sont refusées.
9. **Certification.** Le kit exécute les cas réels fournis dans sa configuration.
   Une suite spécialisée non disponible est `skipped`, code de sortie 2. Il ne
   transforme jamais ce résultat en réussite. Les scénarios de fautes, sécurité,
   filiation/révocation et les gros volumes restent à compléter sur le banc.
   Les exceptions privées exportées doivent être revérifiées par l’opérateur
   avant campagne ; le kit autonome ne lit pas la révocation en base en continu.
10. **Identité serveur non observable.** MongoDB relève `buildInfo.version`,
    Elasticsearch/OpenSearch `GET /.version.number` et Cassandra
    `system.local.release_version` lors du test réel ; les permissions nécessaires
    restent à vérifier sur le banc. Sans cette valeur, aucune identité positive
    n’est produite. Les adaptateurs S3/compatibles, Azure Blob/ADLS, GCS,
    HTTP/SharePoint/OneDrive, Delta Sharing, Unity Catalog, Iceberg REST et BigQuery ne
    disposent pas encore d’une version serveur observable dans leur test.
    Ils peuvent exécuter leurs opérations développées, mais leur qualification
    est bloquée par le contrat actuel `ComponentIdentity.server_version`, même
    sur un banc complet. Ni l’opérateur ni la configuration ne peuvent fabriquer
    cette valeur. Une extension explicite du contrat aux identités de protocole
    ou d’API réellement observées reste à définir ; un numéro d’API demandé,
    un ETag ou un snapshot de table ne vaut pas version du serveur.
    BigQuery confirme sa connexion par un vrai `SELECT 1` ; la chaîne constante
    « Google BigQuery SQL API v2 » n’est pas une version serveur et n’est plus
    produite. Une observation marquée `version_kind=api` ou `protocol` est refusée.

## Pilotes et spikes

Les [mesures des roues](evidence/d7-connector-wheels.json) donnent **13,27 Mio**
d’archives et **44,29 Mio** décompressés pour quinze distributions résolues,
dont certaines sont déjà dans la base. Ce ne sont ni la taille Docker finale
ni son surcoût. L’image dédiée utilise la base worker de la même révision et un
venv séparé ; les Dockerfiles API/worker général et leurs budgets ne changent pas.
Le plafond de l’image connecteur reste à décider sur une mesure réelle `.Size`.

| Spike | Résultat de développement / suite nécessaire |
|---|---|
| S-C1 | Transport HTTP signé et gardé retenu pour maîtriser DNS, redirections et CAS ; renouvellement pendant de longues sessions, ADLS et débit à qualifier |
| S-C2 | Versions/licences/roues consignées, imports locaux vérifiés ; image finale et plafond en attente VM |
| S-C3 | Catalogue officiel initial + PKCE, DCR et révocation développés ; consentements/tenant réels en attente |
| S-C4 | SQL-auth Synapse sans ODBC ; Entra/Fabric non livré |
| S-C5 | dlt/PyAirbyte non intégrés. Étude optionnelle après C4 ; aucune dépendance ajoutée ni promesse de couverture longue traîne |
| S-C6 | Comptes cloud et budgets à fournir par l’opérateur ; aucun compte créé ici |
| S-C7 | Transaction PG `REPEATABLE READ` éprouvée sur PostgreSQL 17.11 jetable avec insertion concurrente (fabrique de connexion injectée, sans qualification TLS/transport) ; qualification multi-moteur restante |
| S-C8 | CH en attente, aucun HANA réel disponible |

## Migrations, activation et retour arrière

Les migrations 127–132 créent les connexions, grants/délégations, calculs,
preuves/exceptions réseau, états OAuth, intentions d’écriture et checkpoints/watches.
Le [rejeu PostgreSQL 17.11](evidence/d7-postgresql-migrations.json) part du schéma
ORM du prédécesseur `4417bc4f`, estampillé 126 : upgrade jusqu’à 132, comparaison
des colonnes, refus de downgrade avec checkpoint, puis aller-retour à vide.
Ce n’est pas un rejeu de l’historique depuis une base vide ; le blocage historique
à 013 n’est pas résolu par ce test.

La commande `python -m app.cli.migrate_connections --dry-run` examine les
configurations legacy sans déchiffrer les secrets. `--apply` est une action
d’exploitation distincte, transactionnelle par workspace, qui conserve les
anciennes pages/configurations pendant la release de compatibilité.

`CONNECTOR_FRAMEWORK_ENABLED` reste faux par défaut. Le Compose et le chart
connecteurs sont opt-in ; le timer de certification n’est ni installé ni activé.
Activer le framework force la garde réseau en `enforce`, y compris si un ancien
réglage indique encore `report`. L’observation et les exceptions nécessaires
doivent donc précéder cette activation ; les nouveaux parcours ne peuvent pas
utiliser la fenêtre d’observation pour atteindre une adresse privée non approuvée.
Aucun secret réel, aucune exception réseau de production et aucun changement
de configuration de la VM ne sont inclus. Les downgrades refusent de détruire
les nouveaux enregistrements : après usage, un retour aux anciennes images
demande une procédure d’exploitation et une sauvegarde compatible.

Les résultats de validation du commit livré sont consignés dans la PR. La
procédure déléguée distingue les tests de développement des preuves requises
pour ouvrir chaque lot et chaque niveau du catalogue.
