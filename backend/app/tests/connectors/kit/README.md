# Banc de certification des connecteurs

Le kit exécute les adaptateurs livrés contre une source réelle. Il ne démarre aucun service, ne modifie pas les déploiements, et ne publie aucune certification. La VM de production est uniquement le lieu d'exécution disponible : préparer un compte et des tables ou préfixes jetables, sans utiliser une table métier comme cible.

Les tests `test_certification_contract.py` restent des tests unitaires. Ils ne constituent jamais une preuve de qualification. `test_live.py` est ignoré sans activation explicite.

## Préparation par l'opérateur du banc

1. Exécuter dans le runner connecteurs correspondant à la révision à qualifier. Relever le SHA de l'image avec Docker ; ne pas recopier un SHA d'une ancienne livraison. Utiliser les dépendances et profils effectivement installés dans ce runner.
2. Préparer une source SQL ou objet jetable avec une référence Parquet locale attendue. Inclure types numériques précis, nulls, Unicode, dates, booléens et binaire. Pour les partitions, inclure des valeurs négatives et NULL ; pour l'incrémental, au moins trois lignes dont deux partagent le watermark et possèdent des clés différentes.
3. Stocker la configuration ci-dessous dans un fichier privé, propriétaire courant, mode **0600**, hors du dépôt. Les mots de passe et tokens ne passent ni en argument de commande ni dans les rapports. La garde réseau est imposée en mode `enforce`, TLS reste vérifié. Le kit ne crée aucune exception réseau.
4. Pour un banc privé, exporter une exception **déjà approuvée par l’administration de plateforme** : renseigner `network_grants` dans ce même fichier 0600, avec `exception_id`, `cidr`, `ports` et `expires_at` ISO-8601 avec fuseau. Vérifier manuellement l’ID, la justification et la révocation dans le journal d’administration avant chaque campagne. Le kit standalone ne contacte pas la base de production et ne peut donc pas vérifier cette provenance ni observer une révocation ultérieure ; l’opérateur doit interrompre la campagne dans ce cas. Seuls RFC1918 /24 ou plus précis et ULA /64 ou plus précis sont autorisés, au maximum 32 ports et une échéance de 90 jours. Aucun CIDR général ni adresse loopback/link-local n’est accepté. Le contexte est limité à chaque appel du banc, TLS reste strict ; seuls les IDs d’exceptions figurent dans les rapports.
5. Choisir un répertoire de rapports neuf. Une sortie existante contenant des rapports est refusée pour empêcher de réutiliser des résultats d'une exécution précédente.

Exemple SQL à remplir localement ; les valeurs ci-dessous ne sont pas des identifiants utilisables :

```json
{
  "profile_key": "postgresql",
  "values": {"host": "banc.exemple.fr", "port": 5432, "database": "agentium_bench", "username": "bench_reader"},
  "credentials": {"password": "A_RENSEIGNER_LOCALEMENT"},
  "runner_image_sha256": "SHA_IMAGE_64_HEXA",
  "source_revision": "REVISION_40_HEXA",
  "environment": "test_account",
  "environment_id": "omnirag-demo-banc-isole",
  "source": "real",
  "timeout_s": 30,
  "allow_writes": false,
  "read": {
    "parameters": {"schema": "agentium_bench", "table": "source_types"},
    "golden_parquet": "/banc/source_types.parquet",
    "partition_column": "partition_key",
    "incremental": {"watermark_column": "modified", "key_column": "id", "type": "integer", "overlap": 1}
  }
}
```

Pour un profil objet, `values`/`credentials` suivent son YAML ; `read.parameters` contient `prefix` ou `key` et les limites acceptées par le profil. `golden_parquet` contient exactement les lignes du jeu d'objets immuable à lire. Le kit limite les imports à 5 000 lignes / 32 Mio, les golden à 5 000 lignes / 16 Mio, et les appels à 300 secondes maximum. Un benchmark de volume est une recette distincte.

## Exécution

Depuis `backend`, dans l'environnement runner préparé :

```sh
python -m app.tests.connectors.kit.live --config /banc/prive/connecteur.json --reports /banc/resultats/run-neuf
```

La commande affiche uniquement les noms de suites, statuts et codes fermés. Le code de sortie est **2** dès qu'une suite requise échoue, reste non exécutée, ou que l'identité effective est incomplète. Aucun détail brut d'exception fournisseur ou contenu de ligne n'est écrit.

Variante pytest, sans recopier l'environnement de la base de production :

```sh
AGENTIUM_CONNECTOR_KIT_CONFIG=/banc/prive/connecteur.json AGENTIUM_CONNECTOR_KIT_REPORTS=/banc/resultats/run-neuf-pytest python -m pytest -q app/tests/connectors/kit/test_live.py --tb=short
```

Les rapports sont `metadata.json`, une synthèse `reports.json` et un fichier `reports/NN-suite.json` par suite, tous en mode 0600. L'identité est observée à partir du vrai `test` du connecteur, des versions de packages chargés, du profil et du hash du kit livré ; une version serveur ne se configure pas à la main. Une identité nulle ne peut pas être assemblée en preuve.

L'assembleur `app.cli.connector_evidence` doit recevoir `metadata.json` comme identité et le sous-répertoire `reports`. Il vérifie l'ensemble exact des suites et leurs digests ; accepter la preuve reste une opération d'administration séparée. Un SHA prouve l'intégrité, pas l'origine du producteur.

## Écritures, toujours explicites

Par défaut aucune écriture n'est exécutée. Pour les activer, `allow_writes` doit être vrai et chaque entrée `writes.write_append`, `writes.write_overwrite` ou `writes.write_upsert` doit préciser :

```json
{
  "parameters": {"schema": "agentium_bench", "table": "cible_jetable_upsert", "keys": ["id"]},
  "input_parquet": "/banc/input.parquet",
  "before_parquet": "/banc/etat_initial.parquet",
  "after_parquet": "/banc/etat_attendu.parquet"
}
```

Le kit refuse une cible identique à la source de lecture, vérifie son état initial avant mutation, puis son état final et le reçu. Les tables restent en place pour examen ; aucun nettoyage destructeur ni nouvelle tentative automatique n'a lieu. Préparer manuellement la table de marqueurs avec `sql_write.marker_table_ddl` quand le profil l'exige. Les écritures cloud par SQL inline restent bornées à 4 000 lignes et 1 Mio de SQL ; au-delà, le connecteur refuse `CONNECTOR_CLOUD_STAGING_REQUIRED`.

## Suites qui exigent encore une recette spécialisée sur le banc

Le kit générique produit un résultat **skipped**, jamais un succès, lorsqu'il ne peut exercer le scénario. Cela empêche `verified` tant que ces preuves manquent.

| Suite | Recette déléguée à exécuter sur une cible de test isolée |
| --- | --- |
| `security` | DNS mixte et rebinding, IP privée sans exception, redirection vers une autre origine, certificat invalide et SNI ; vérifier l'absence de secret reçu par la destination interdite. |
| `revocation` | Import en cours, puis retrait du membre, révocation OAuth/secret et exception réseau ; vérifier l'arrêt et l'absence de dataset publié. |
| `resilience` | Perte du worker, échéance dans la file, bail expiré et annulation ; constater les états durables et l'absence de reprise d'une mutation lancée. |
| `lineage` | Depuis un vrai workspace du banc, publier un import, le réutiliser dans le Flow et vérifier source, révision, dataset et droits. |
| `write_dry_run` | Préparer une intention, exécuter l'aperçu distant, comparer les comptes, approuver le digest exact puis vérifier le reçu. |
| `write_read_only_refusal` | Appeler une écriture avec connexion en lecture seule et un compte fournisseur sans privilège d'écriture ; vérifier aucune modification. |
| `write_unknown_outcome` | Couper la réponse après commit, constater `unknown`, rapprocher par marqueur/job/log sans réémettre la mutation. |
| `export_files` / `watch` | Export vers préfixe jetable, lecture native, conflit CAS, réponse perdue et modification réelle détectée par watch. |
| `consistency:snapshot` / `per_partition` | Mutation concurrente contrôlée de la source ; vérifier exactement la garantie déclarée. |
| Refus des capacités imbriquées | Vérifier via l'API et le runner le refus des options partition/incrémental/création absentes du profil. |

Un profil MCP ou OpenAPI reste `third_party`. La démo HANA ne peut produire aucune qualification HANA. Le canary déployé et sa révocation réelle restent distincts de ces suites de compte de test ; ce kit n'effectue aucun déploiement.
