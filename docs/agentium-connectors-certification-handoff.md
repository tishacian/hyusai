# Relais opérateur — certification des connecteurs sur la VM

## Statut et portée

Cette procédure prépare une campagne sur `omnirag-demo`, depuis un environnement qui dispose **déjà** de l’accès à la VM. Elle ne prouve aucun accès SSH depuis l’environnement de développement. Les commandes ci-dessous sont à exécuter par l’opérateur ; elles n’ont pas été exécutées sur la VM pour rédiger ce document.

Le [plan connecteurs](agentium-dataops-connectors.md) reste la référence. **C0 reste ouvert** : il faut encore la preuve du mode réseau `enforce` réellement déployé, un banc en service, un bundle réel et la qualification de l’image. **CH attend une instance HANA réelle**. Showcase en démo explicite, avec TLS strict conservé, ne qualifie pas HANA. C1 à C7 peuvent être développés sans fermer ces gates ; les profils restent non vérifiés tant que leurs preuves ne sont pas acceptées.

Ce relais ne fusionne rien, ne migre aucune base applicative, ne démarre aucun service Compose et ne change ni les conteneurs de production, ni leurs variables, ni leurs plafonds. Le canary déployé et l’activation de `enforce` en production relèvent d’une décision de livraison séparée. La présence d’un timer dans le dépôt ne l’installe pas.

## 1. Préparer un espace de banc distinct

Préconditions : Bash, Git, Python 3, client Docker et accès au daemon ; checkout propre de la révision à qualifier ; espace disque confirmé pour les couches de construction, caches et rapports. Le groupe Docker donne un pouvoir d’administration sur l’hôte : utiliser le compte opérateur prévu à cet effet.

Choisir les chemins autorisés localement, sans réutiliser le worktree de livraison ni un volume de données de production :

```bash
REPO=/chemin/vers/checkout-candidat
BENCH=/srv/agentium-bench
cd "$REPO"
test -z "$(git status --porcelain)"
REV=$(git rev-parse HEAD)
TAG="bench-${REV:0:12}"
umask 077
install -d -m 700 "$BENCH/private/fixtures" "$BENCH/reports"
docker version
docker info --format 'root={{.DockerRootDir}} driver={{.Driver}}'
docker system df
df -h "$BENCH"
```

Relever également l’espace libre du `DockerRootDir` affiché. Arrêter si la construction risque de remplir ce volume. Ne pas lancer `docker system prune`, supprimer un cache partagé ou retirer une image de production pour faire de la place.

Préparer un compte fournisseur et des tables ou préfixes **jetables**, avec les droits minimaux. La procédure ne crée pas de serveur de base, de bucket ni de conteneur fournisseur. Le réseau de banc doit être approuvé localement, distinct des réseaux applicatifs ; sa création n’expose aucun port :

```bash
CONNECTOR_CERT_NETWORK=agentium-connector-bench
docker network create --driver bridge \
  --label io.agentium.purpose=connector-certification \
  "$CONNECTOR_CERT_NETWORK"
```

Si ce réseau existe déjà, l’inspecter et réutiliser celui qui porte ce label ; ne pas recréer ni modifier un réseau existant. Vérifier qu’aucun conteneur métier n’y est raccordé. Le bridge permet les sorties nécessaires aux services cloud ; il ne fournit pas à lui seul une autorisation d’accès aux réseaux privés. La garde applicative reste en `enforce` et TLS reste strict.

## 2. Construire les images candidates sans démarrer le worker

Le runner hérite **du worker construit depuis la même révision**, puis ajoute ses pilotes dans `/opt/agentium-connectors`. Construire ce worker à côté avec les options de la release ; ne pas réutiliser le worker de production d’une autre révision. La base Python ci-dessous est celle du script de release à la rédaction ; si sa référence change, prendre celle approuvée dans `scripts/agentium-vm-build.sh` de la révision candidate.

```bash
PYTHON_BASE_IMAGE=python:3.12-slim@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe
WORKER_IMAGE="agentium-worker:$TAG"
RUNNER_TAG="agentium-connector-runner:$TAG"
docker build -f docker/Dockerfile.agentium-worker \
  --build-arg PYTHON_BASE_IMAGE="$PYTHON_BASE_IMAGE" \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  --build-arg USER_UID=1000 --build-arg USER_GID=1000 \
  --build-arg INSTALL_HF_RAG=1 --build-arg INSTALL_GISKARD_RAGET=true \
  --build-arg AGENTIUM_IMAGE_REVISION="$REV" \
  -t "$WORKER_IMAGE" .
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$WORKER_IMAGE")" = "$REV"
docker build -f docker/Dockerfile.agentium-connector-runner \
  --build-arg WORKER_BASE_IMAGE="$WORKER_IMAGE" \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  --build-arg AGENTIUM_IMAGE_REVISION="$REV" \
  -t "$RUNNER_TAG" .
AGENTIUM_CONNECTOR_RUNNER_IMAGE=$(docker image inspect --format '{{.Id}}' "$RUNNER_TAG")
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$AGENTIUM_CONNECTOR_RUNNER_IMAGE")" = "$REV"
```

L’ID local `sha256:…` est immuable et accepté par le script de banc : aucun push n’est nécessaire. Une référence déjà présente `registre/image@sha256:…` convient aussi. Ne pas confondre le digest de manifeste d’un registre avec l’ID Docker local : garder **la même référence immuable** pour l’exécution, `runner_image_sha256` et l’assemblage des preuves. Le script refuse une configuration dont le SHA ou la révision ne correspond pas à la référence choisie.

Les Dockerfiles excluent les fichiers d’environnement et secrets de leur contexte. Ne placer aucune configuration privée dans le checkout. Le runner accepte, si l’environnement de construction l’exige, un certificat public par `--secret id=connector_ca,src=/chemin/ca.pem` ; ne pas désactiver TLS et ne pas utiliser un secret comme argument de build. Les dépendances sont figées dans `requirements_connectors_*.txt`, `constraints-demo-app.txt` et `constraints-connectors.txt`.

## 3. Mesurer avant toute décision de plafond

La métrique de release est **`docker image inspect .Size` en octets**, convertie en Mio par division par 1 048 576. Relever Docker, driver de stockage, référence immuable et révision avec chaque mesure :

```bash
docker image inspect --format 'image={{.Id}} bytes={{.Size}} platform={{.Os}}/{{.Architecture}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' \
  "$WORKER_IMAGE" "$AGENTIUM_CONNECTOR_RUNNER_IMAGE" \
  > "$BENCH/reports/image-sizes-$TAG.txt"
docker image history --no-trunc --format '{{.Size}}\t{{.CreatedBy}}' \
  "$AGENTIUM_CONNECTOR_RUNNER_IMAGE" \
  > "$BENCH/reports/image-layers-$TAG.txt"
```

Le spike de dépendances a relevé **13,27 Mio de roues téléchargées et 44,29 Mio de contenu décompressé**. Ces chiffres ne sont **pas une taille d’image Docker** : ils ne mesurent ni le worker de base, ni les couches finales, ni leur comptabilité sur le daemon VM. Ils ne justifient aucun nouveau plafond.

Les plafonds existants restent : backend **1 480 Mio**, worker **1 850 Mio**, frontend **40 Mio**, ml-ts **1 240 Mio**, livekit-agent **110 Mio**. Aucun plafond du runner connecteurs n’est attribué avant sa mesure et la décision S-C2. Les anciennes mesures de `6dcb0d48` ne qualifient pas cette nouvelle image.

Le script suivant garde le contrôle fermé si le plafond du runner est absent. Les images backend/frontend du même tag sont nécessaires au succès du contrôle global ; ne pas les remplacer par des alias des images de production. Cette procédure ne construit que worker et runner, donc une image obligatoire manquante garde aussi le contrôle global en échec.

```bash
export AGENTIUM_CONNECTOR_RUNNER_IMAGE
AGENTIUM_IMAGE_BUDGET_MB_BACKEND=1480 \
AGENTIUM_IMAGE_BUDGET_MB_WORKER=1850 \
AGENTIUM_IMAGE_BUDGET_MB_FRONTEND=40 \
AGENTIUM_IMAGE_BUDGET_MB_ML_TS=1240 \
AGENTIUM_IMAGE_BUDGET_MB_LIVEKIT_AGENT=110 \
AGENTIUM_IMAGE_REQUIRE_CONNECTOR_RUNNER=1 \
  scripts/agentium-image-budget.sh "$TAG" \
  > "$BENCH/reports/image-budget-$TAG.txt"
```

Conserver le code de sortie et tous les motifs d’échec. Après décision explicite, l’opérateur peut fournir le plafond **approuvé** dans `AGENTIUM_IMAGE_BUDGET_MB_CONNECTOR_RUNNER` et rejouer le contrôle avec le jeu d’images complet de cette révision. Ne pas calculer automatiquement « taille mesurée + marge » dans cette procédure, ni modifier un plafond pour obtenir un code 0.

## 4. Configuration privée et jeu attendu

Les fichiers `private/*.json` doivent appartenir au compte qui lance le banc, être réguliers, sans lien symbolique, mode **0600**, et faire moins de 64 Kio. Les Parquet attendus vont dans `private/fixtures/`. Les deux répertoires privés et rapports doivent être distincts et ne pas s’imbriquer. Un exemple local, à compléter sans afficher les secrets dans le terminal :

```bash
python3 - "$BENCH/private/postgresql.json" "$REV" "${AGENTIUM_CONNECTOR_RUNNER_IMAGE##*sha256:}" <<'PY'
import json, os, sys
config = {
    "profile_key": "postgresql",
    "values": {"host": "banc.exemple.fr", "port": 5432,
               "database": "agentium_bench", "username": "bench_reader"},
    "credentials": {"password": "A_RENSEIGNER_LOCALEMENT"},
    "source_revision": sys.argv[2], "runner_image_sha256": sys.argv[3],
    "environment": "test_account", "environment_id": "omnirag-demo-banc-isole",
    "source": "real", "timeout_s": 30, "allow_writes": False,
    "read": {
        "parameters": {"schema": "agentium_bench", "table": "source_types"},
        "golden_parquet": "/bench/config/fixtures/source_types.parquet",
        "partition_column": "partition_key",
        "incremental": {"watermark_column": "modified", "key_column": "id",
                        "type": "integer", "overlap": 1}
    }
}
fd = os.open(sys.argv[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as handle:
    json.dump(config, handle, indent=2)
PY
```

`golden_parquet` désigne le chemin **dans le conteneur**, pas celui de l’hôte. Construire le golden indépendamment de l’adaptateur testé, avec types précis, nulls, Unicode, dates et binaire. La recette partitionnée exige des NULL et des valeurs négatives dans une colonne entière. La recette incrémentale exige plusieurs lignes partageant un watermark, distinguées par une clé stable. Les limites du kit sont 5 000 lignes/32 Mio par import, 5 000 lignes/16 Mio par golden et 300 secondes par appel. Les benchmarks de 3 ou 10 millions de lignes sont des campagnes séparées, pas une option à relever dans ce kit.

Pour S3/Azure/GCS, reprendre les paramètres et secrets du profil livré et un préfixe jetable immuable ; le golden doit correspondre exactement à ce jeu. La présence d’un profil ne prouve pas que toutes ses suites spécialisées sont automatisées.

Pour un hôte privé, `network_grants` peut contenir un **export d’exception déjà approuvée** :

```json
{"exception_id":"UUID_DE_L_EXCEPTION_APPROUVEE","cidr":"10.22.33.0/24","ports":[5432],"expires_at":"ECHEANCE_ISO_8601_AVEC_FUSEAU"}
```

Placer ces objets dans une liste `network_grants` du fichier privé. Les placeholders sont volontairement invalides. Vérifier ID, périmètre, ports, échéance et absence de révocation dans le journal d’administration avant chaque campagne. Seuls RFC1918 /24 ou plus précis et ULA /64 ou plus précis passent ; ni loopback, ni link-local, ni CIDR général. Une échéance est obligatoire, au plus 90 jours ; le kit la revalide à chaque appel. **Le kit autonome ne consulte pas la base de production : une révocation après export impose l’arrêt par l’opérateur.** Il ne crée aucune exception. Seuls les IDs sont consignés dans les métadonnées. Ce mécanisme opérateur n’est pas une autorisation fournie par un workspace via l’API.

## 5. Exécuter le batch explicite

```bash
export AGENTIUM_CONNECTOR_RUNNER_IMAGE CONNECTOR_CERT_NETWORK
export CONNECTOR_CERT_CONFIG_DIR="$BENCH/private"
export CONNECTOR_CERT_REPORT_DIR="$BENCH/reports"
bash scripts/agentium-connector-certification.sh
```

Le script utilise l’image locale sans pull, un conteneur éphémère par configuration, 1 CPU, 2 Gio de mémoire, filesystem en lecture seule, aucun privilège Linux, un `/tmp` de 512 Mio et aucun port publié. Il ne monte ni socket Docker ni environnement applicatif ni volume de production. Le répertoire des configurations est monté en lecture seule ; les rapports sont écrits avec l’UID opérateur. Le conteneur du banc est supprimé à la fin ou à l’interruption.

Chaque exécution crée un répertoire neuf avec `metadata.json`, `reports.json` et `reports/NN-suite.json` en mode 0600. Le code **2** signifie échec, suite requise non exécutée, identité incomplète ou précondition invalide ; ce n’est pas une certification partielle. Le kit n’écrit ni contenu de ligne ni message fournisseur brut. Les comptes de test doivent rester bornés et jetables même lorsque `allow_writes` est activé.

La [notice du kit](../backend/app/tests/connectors/kit/README.md) décrit les fixtures d’écriture. Elle exige un état initial, un fichier d’entrée et un état final attendus, une cible distincte de la source de lecture, puis vérifie le reçu. Pas de mutation de source métier, ni nettoyage destructeur, ni rejeu automatique après réponse perdue.

## 6. Produire les preuves manquantes, puis assembler

Lister les suites requises depuis **la même image**, sans connexion à une source :

```bash
docker run --rm --pull=never --network none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,noexec,nosuid,size=536870912 \
  --workdir /app/backend --entrypoint python \
  "$AGENTIUM_CONNECTOR_RUNNER_IMAGE" -m app.cli.connector_evidence --plan postgresql
```

Le kit générique ne remplace pas les recettes suivantes. Une suite sans exécution réelle reste `skipped`, même si un test unitaire équivalent passe :

| Preuve | Travail à déléguer sur cible jetable |
| --- | --- |
| Réseau et sécurité | DNS mixte/rebinding, mauvaise origine, redirections, certificat invalide et SNI ; constater que la cible interdite ne reçoit aucun secret. |
| Révocation | Import actif puis révocation du membre, OAuth/secret ou exception ; arrêt et absence de publication du dataset. |
| Résilience | Attente dépassant l’échéance, worker perdu, bail expiré et annulation ; états durables et aucun rejeu d’écriture. |
| Filiation | Import réel publié dans un workspace de banc, droits puis réutilisation Flow ; contrôle de la source et de la révision. |
| Aperçu et approbation | Intention, aperçu distant sans mutation, comptes observables ou estimations explicités, approbation du digest exact. |
| Lecture seule | Connexion applicative en lecture seule et compte fournisseur sans droit d’écriture ; mutation refusée, état inchangé. |
| Réponse perdue | Couper la réponse après commit ; état `unknown`, rapprochement par marqueur/job/log sans nouvel envoi. |
| Objets et watch | Export natif, lecture de retour, collision CAS, réponse perdue et changement réel détecté. |
| Cohérence et options | Mutation concurrente pour la garantie annoncée ; refus effectif des capacités absentes, partitions NULL et tuple incrémental. |

Les recettes doivent produire des `ProofReport` valides et garder leurs preuves opérateur séparées, sans inventer un rapport `passed`. Les bundles unitaires ne sont pas importables comme attestation de banc. Les outils MCP/OpenAPI restent `third_party` ; une démo HANA n’est jamais une source HANA réelle.

**Blocage d’identité à ne pas contourner.** Le contrat actuel exige une version serveur
réellement observée. Le test MongoDB interroge `buildInfo.version`, celui de
Elasticsearch/OpenSearch lit `GET /.version.number` et Cassandra interroge
`system.local.release_version` ; vérifier les permissions de ces lectures.
S3/compatibles, Azure Blob/ADLS, GCS, HTTP/SharePoint/OneDrive et les catalogues
Delta Sharing/Unity Catalog/Iceberg REST et BigQuery n’émettent pas encore cette identité.
BigQuery vérifie la connexion avec `SELECT 1`, sans déclarer de version serveur.
Leurs recettes peuvent produire des diagnostics, mais aucun bundle qualifiant
ne peut être assemblé avec `identity=null`. Ne pas remplir la version à la main,
depuis la configuration, un ETag, un snapshot ou le numéro d’API demandé.
Une identité de protocole/API observable devra faire l’objet d’une extension
explicite du contrat de preuve ; le banc ne peut pas lever ce manque de code.

Choisir le répertoire de campagne effectivement terminé, puis assembler. Les métadonnées, packages, profil, kit et source révisée doivent correspondre ; une identité nulle ou une suite absente est refusée. Des suites explicitement échouées ou ignorées peuvent produire un bundle de diagnostic, avec code 2 ; elles ne donnent pas `verified`.

```bash
CAMPAIGN=postgresql_HORODATAGE_A_REMPLACER
docker run --rm --pull=never --network none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,noexec,nosuid,size=536870912 \
  --mount "type=bind,src=$BENCH/reports/$CAMPAIGN,dst=/proof" \
  --workdir /app/backend --entrypoint python \
  "$AGENTIUM_CONNECTOR_RUNNER_IMAGE" -c '
import json, sys
from app.cli.connector_evidence import main
m = json.load(open("/proof/metadata.json"))
sys.exit(main(["--identity-file", "/proof/metadata.json", "--reports-dir", "/proof/reports",
    "--revision", m["source_revision"], "--environment", m["environment"],
    "--environment-id", m["environment_id"], "--completed-at", m["completed_at"],
    "--kind", "suite", "--output", "/proof/bundle.json"]))'
```

`bundle.json` est créé sans écraser un fichier existant. Archiver sa référence, son digest, la révision et la mesure d’image. Le digest garantit l’intégrité des octets, pas l’authenticité du producteur.

## 7. Acceptation administrative et automatisation distinctes

L’acceptation appartient à un **administrateur de plateforme** qui vérifie l’opérateur producteur, les fixtures et les preuves. Sur une instance où le framework est déjà autorisé, l’API est `POST /api/v1/connector-governance/evidence`, corps `{producer, bundle, reports}`. Le JSON de l’assembleur contient déjà `bundle` et `reports` ; ajouter l’identité réelle du producteur. Utiliser l’authentification administrative existante sans mettre son token dans l’historique shell. Ne pas activer le framework sur la production pour contourner un 404 de cette API.

Une preuve acceptée n’active aucune capacité et ne suffit pas seule au badge : il faut une observation `test` actuelle avec l’identité exacte. La suite réelle complète peut donner `verified`. `certified` demande en plus le canary et la révocation de l’environnement déployé, récents et acceptés. Une nouvelle version de profil, pilote, image, kit ou serveur requiert une requalification. Une preuve peut être révoquée par l’administration via `DELETE /api/v1/connector-governance/evidence/{digest}`.

Les unités `ops/systemd/agentium-connector-certification.{service,timer}` sont des **modèles non installés**. Le service attend le compte `agentium-bench`, `/etc/agentium/connector-certification.env`, le script à `/opt/agentium/scripts/agentium-connector-certification.sh` et des rapports dans `/srv/agentium-bench/reports`. Son fichier d’environnement ne contient que les quatre références non secrètes suivantes ; les credentials restent dans les JSON 0600 :

```ini
AGENTIUM_CONNECTOR_RUNNER_IMAGE=sha256:SHA_LOCAL_64_HEXA
CONNECTOR_CERT_CONFIG_DIR=/srv/agentium-bench/private
CONNECTOR_CERT_REPORT_DIR=/srv/agentium-bench/reports
CONNECTOR_CERT_NETWORK=agentium-connector-bench
```

Faire concorder le propriétaire des configurations avec `User=agentium-bench`. Le timer proposé est quotidien à 02:30 UTC avec jusqu’à 30 minutes de décalage, sans rattrapage des exécutions manquées ; le service est limité à deux heures. **Ne pas installer ni activer ces unités dans cette campagne manuelle.** Leur mise en service demande une décision opérateur séparée sur le compte, l’horaire, la charge et la notification d’échec. Les recettes d’écriture à état initial fixe nécessitent un réarmement explicite des fixtures ; elles ne doivent pas être répétées aveuglément par le timer.

À remettre : révision/image exactes, mesures `.Size` et verdicts de budgets, rapports complets, preuves des scénarios spécialisés, IDs des exceptions utilisées, diagnostics fermés et décisions d’acceptation. Si une preuve manque, le profil garde son niveau actuel ; C0 et CH gardent leurs conditions de clôture.
