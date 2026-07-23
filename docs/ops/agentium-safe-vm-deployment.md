# Déploiement sûr Agentium sur la VM unique

Ce runbook est le chemin canonique tant que `demo/agentic` est synchronisée
directement sur la VM. GitLab n'est pas requis pour exécuter la transaction,
mais l'absence de job protégé limite la promotion des claims à
`runner_verified`. La VM et les canaris produisent une preuve exploitable ; ils
ne remplacent pas l'attestation indépendante d'un runner protégé.

Ce document décrit un protocole et ses gates ; il **n'autorise aucun commit,
push ou déploiement**. Une exécution requiert un GO opérateur distinct, donné
pour un SHA, un `deployment-id` et une fenêtre déterminés. Au 23 juillet 2026,
le verdict reste `NO-GO`.

## Verdict opérationnel au 23 juillet 2026

Le déploiement applicatif direct de l'état historique vers les Lots 7–9 est un
**NO-GO**. Ce n'est pas un doute fonctionnel sur ces lots : le runtime live ne
possède pas encore les primitives nécessaires pour rendre leur premier
déploiement transactionnel.

| Gate | État observé | Conséquence |
|---|---|---|
| Checkout live | propre, `hotfix/andritz-export` à `154fd988` | runtime backend/frontend/worker/P4 aligné ; ce constat n'autorise ni pull ni déploiement |
| Espace libre `/` | 16 Gio disponibles, seuil 40 Gio | preflight bloqué ; seul le cache builder inutilisé peut être purgé séparément |
| `/dev/sdb` | 279 Gio disponibles | capacité suffisante observée pour le journal et les artefacts, sans constituer une sauvegarde hors VM |
| `/dev/sdc` | 382 Gio disponibles | capacité suffisante observée pour Secure Deposit, sans autoriser de mutation ni de déplacement |
| Cache Docker builder | 38,83 Gio annoncés reclaimables | candidat unique au nettoyage opérateur ; aucun volume ni image active ne doit être purgé |
| MinIO | bucket `agentium-artifacts` existant non versionné | un overwrite/delete ne serait pas récupérable par l'orchestrateur |
| Qdrant | aucune paire de clés admin/lecture seule | impossible de prouver que les canaris ne peuvent pas écrire dans les 33 collections |
| Backend systemd | écoute toujours publiquement sur `0.0.0.0:8000` | chemin de contournement du gate Nginx |
| Gate maintenance | non adopté par le runtime historique | aucune fermeture persistante après reboot |
| Sauvegarde hors VM | non attestée par ce dépôt pour `/dev/sda1`, `/dev/sdb` et `/dev/sdc` | les inventaires protègent un rollout, pas la perte physique d'un disque ; les trois restaurations sont obligatoires |
| Autorité tenant | une `ExpertCaptureSession` du workspace `test` référence un System Andritz | gate de bindings bloqué ; aucune réparation ou seed automatique n'est autorisé |
| SFTP positif | producteur local et ledger DB durcis, mais aucun cycle réel n'a encore été exécuté sur la VM | code-ready seulement ; le gate exige encore authentification, subsystem, révocation et refus post-révocation live |
| Autorités de preuve | le registre Git revu contient `protected_runner`, soit `1/3` | le preflight A refuse avant toute mutation ; ajouter `backup_provider` et `release_a_host_collector` avec des clés réellement distinctes |
| Bundle runtime privé | `agentium.env` et `qdrant.agentium.env` absents, clé Qdrant applicative invalide, `backend/.env` en `0644` | la capture v3 refuse ces sources ; préparer hors checkout un miroir `0700` dont chaque fichier est `0400/0600`, avec clés Qdrant admin/lecture seule distinctes |

La dérive tenant a été qualifiée sans lire de contenu métier : la session
est `planned`, appartient à `test`, pointe vers un Run et un Context `test`,
contient cinq événements et aucune proposition, mais référence un System
Andritz et une Capability devenue introuvable. La correction conservatrice
serait de retirer uniquement ces deux bindings invalides en conservant la
session, le Run, le Context et les événements. Elle exige toutefois une décision
opérateur tracée et un plan/apply lié à l'identité exacte de la ligne ; le
déploiement ne l'exécute jamais implicitement.

Le rapport d'audit v2 reste content-free : pour au plus 100 anomalies, il
publie uniquement les identifiants de liaison, les relations de workspace,
l'état de rattachement Run/System et les compteurs d'événements/propositions.
Il ne lit ni titre, ni objectif, ni transcript, ni proposition. Le compteur
global reste exhaustif et un booléen signale toute troncature des détails.

La transition est donc scindée en deux releases distinctes :

1. **Release A — adoption de sûreté**, construite depuis le SHA live
   `154fd988` sur une branche dédiée.
   Elle n'embarque ni migration métier, ni seed, ni Lots 7–9. Elle installe les
   gates, borne le backend à la boucle locale, active et vérifie la protection
   MinIO, introduit les clés Qdrant séparées et ferme les chemins de déploiement
   directs.
2. **Release B — déploiement fonctionnel**, rebased sur la Release A. Elle seule
   applique les migrations 065–076, le backfill Workspace Apps et les Lots 7–9
   via la transaction décrite plus bas.

Un unique SHA mélangeant l'adoption de sûreté et les migrations métier est
interdit : si l'adoption échoue, le runtime historique doit rester intact ; si
la Release B échoue, les primitives de rollback doivent déjà être actives et
éprouvées.

La construction des deux historiques depuis le SHA live, dans des worktrees
persistants et sans embarquer les fichiers utilisateur, est détaillée dans le
[plan Git A/B daté](./agentium-release-a-b-git-plan-2026-07-22.md).

## Contrat

- La source est un SHA complet déjà poussé sur `origin/demo/agentic`.
- `git pull`, `--force`, `git clean`, les hotfix in-container et les seeds sont
  interdits.
- Le trafic public d'écriture, les producteurs externes, l'ancien backend, le
  scheduler, P4 et LiveKit restent gelés pendant la migration et les canaris.
  Pour les contrôles applicatifs authentifiés hors cycle SFTP, le
  backend/frontend candidats et un seul worker candidat peuvent être actifs,
  avec Celery Beat forcé à `0` et RabbitMQ vide avant et après. Pendant la
  création et la révocation du principal SFTP jetable, seuls le backend
  candidat et Keycloak sont temporairement démarrés comme control plane
  applicatif, tous deux sans exposition publique et accessibles uniquement par
  la boucle locale ou les réseaux Docker privés ; frontend, workers CPU/P4,
  Beat et LiveKit restent arrêtés. Ce control plane est arrêté avant les
  snapshots PostgreSQL SFTP. Keycloak est revalidé contre l'ID exact du
  conteneur, l'ID, le digest normalisé et la référence exacte de l'image, sa
  commande, son healthcheck, ses labels, sa configuration exacte vérifiée par
  empreinte, ses montages exacts en lecture seule, son unique réseau privé
  partagé avec PostgreSQL et ses publications de ports exclusivement loopback.
  Un port seulement déclaré dans `ExposedPorts`, mais absent des bindings hôte,
  est admis : il ne constitue pas une publication. Tout binding hôte
  supplémentaire ou non-loopback est refusé. La première exécution ne reçoit
  aucun objectif de durée : on réserve 60 à 90 minutes et on privilégie un
  service fermé à une réouverture sans preuve.
- Une activation s'arrête en `validation_pending`, puis traverse obligatoirement
  `sftp_canary_pending`, `sftp_canary_active_recorded` et
  `sftp_canary_recorded`. Elle ne rouvre les writers qu'après validation du
  cycle SFTP complet et d'une attestation liée au même déploiement.
- Les secrets candidats sont fournis par un miroir privé préparé hors du
  checkout live, du worktree candidat et du journal de déploiement. Le miroir
  reproduit uniquement `docker/env/*.env` et `backend/.env`, avec des fichiers
  `0400` ou `0600`; aucune valeur secrète n'est passée en argument ni héritée
  depuis le shell. Le bundle runtime v3 est privé (`0700` pour son répertoire,
  `0600` pour ses fichiers), publié atomiquement, puis devient l'unique source
  de `prepare`, `apply`, `resume`, `finalize` et `rollback`. Sous maintenance,
  ses fichiers sont aussi publiés atomiquement aux emplacements canoniques de
  la VM afin que la Release B relise exactement le contrat adopté.
- Le bundle systemd v3 reçoit une unique `AGENTIUM_IMAGE_REVISION` possédée par
  l'orchestrateur. L'adoption, chaque reprise et le rollback attendent que
  `/api/v1/build-info` serve ce SHA avec `revision_verified=true`; vérifier le
  checkout ou le répertoire courant du processus ne suffit pas.
- Les exécutants A, B, `deploy-vm.sh` et le runner canari épinglent leur `PATH`
  système et neutralisent les variables d'injection Git/Python. A, B et le
  runner refusent en outre un interpréteur avec optimisation active, afin
  qu'aucun contrôle Python ne puisse disparaître sous `PYTHONOPTIMIZE`.

## Données à préserver

| Surface | Emplacement | Règle |
|---|---|---|
| PostgreSQL, état Keycloak et RabbitMQ | volumes Docker actuellement sur `/dev/sda1` ; Keycloak persiste dans PostgreSQL | aucune migration de stockage pendant A/B ; dump PostgreSQL quiescé sur `/dev/sdb`, marqueur de publication durable, rehearsal de restauration, inventaire v2 borné de toutes les lignes métier et files RabbitMQ vides |
| Qdrant, MinIO, ObjectStore et snapshots | volumes/binds sous `/srv/agentium-data` (`/dev/sdb`) | aucun volume/bind recréé ou déplacé ; A peut uniquement recréer les conteneurs Qdrant/MinIO sur les mêmes images et identités de stockage pour adopter l'authentification/versioning, sous contrat pré-mutation et gate fermé |
| Secure Deposit SFTP | `/home/ubuntu/omnirag/backend/data/secure_deposit` (`/dev/sdc`) | nouvelles connexions bloquées en IPv4/IPv6, sessions drainées, fichiers ouverts audités, filesystem remonté en lecture seule et manifeste privé avant/après |
| FAISS legacy | `/home/ubuntu/omnirag/backend/faiss_db` sur `/dev/sda1` | snapshot préalable, montage candidat en lecture seule et aucune migration destructive pendant le rollout |

Un `Mount.Source` Docker situé sous `/var/lib/docker/volumes` ne prouve pas que
la donnée réside sur le disque racine : Qdrant et MinIO utilisent des volumes
Docker `local` bindés vers `/srv/agentium-data`. Le preflight résout donc le
filesystem effectif de chaque destination avec `findmnt`/`stat`, puis exige :

- `agentium_qdrant_block` avec les options exactes
  `type=none,o=bind,device=/srv/agentium-data/qdrant` ;
- `agentium_minio_block` avec les options exactes
  `type=none,o=bind,device=/srv/agentium-data/minio` ;
- le bind snapshots Qdrant existant sous `/srv/agentium-data`, sans changement
  de source ;

- PostgreSQL, l'état Keycloak, RabbitMQ et FAISS sur le filesystem racine
  `/dev/sda1` attendu ;
- Qdrant (`storage` et `snapshots`), MinIO et l'ObjectStore sur `/dev/sdb` ;
- tous les montages Secure Deposit, y compris SFTP et les montages applicatifs
  en lecture seule, sur `/dev/sdc`.

Cette distribution est un invariant de la transition, pas une cible de
migration. La Release A comme la Release B refusent tout déplacement implicite
de PostgreSQL/Keycloak/RabbitMQ depuis la racine, des données
Qdrant/MinIO/ObjectStore depuis `/srv/agentium-data`, ou du Secure Deposit SFTP
depuis `/dev/sdc`.

L'inventaire PostgreSQL v2 parcourt toutes les lignes mais reste en espace
constant : chaque table est représentée par son compteur et deux sommes
commutatives SHA-256 séparées par domaine (clés primaires et état des lignes).
Il ne sérialise jamais les lignes ni leurs identifiants bruts. Les seuls détails
par ligne admis sont les empreintes du Run et des SkillInvocations désignés par
le ledger Chat privé ; les événements `navigation.resolved` sont agrégés par
workspace. La baseline n'est pas liée à un ledger ; les captures post-canari,
finale et juste avant ouverture le sont au même ledger et au même digest. La
comparaison refuse suppression ou modification d'une ligne préexistante et
n'autorise que les deltas explicitement contrôlés. Les tables Keycloak
volatiles sont listées une par une : aucun préfixe de table ou wildcard ne
constitue une exception. Chaque artefact reste borné à 16 Mio.

Les autres inventaires ne publient aucun nom de collection, clé d'objet ou chemin
Secure Deposit : les identifiants sont hachés. Ils couvrent le contenu complet
de l'ObjectStore, les versions MinIO via `ListObjectVersions` et, pour chaque
collection Qdrant, un scroll exhaustif et paginé de tous les IDs, payloads et
vecteurs avec `consistency=all`. Le flux canonique est haché sans publier ces
valeurs ; deux comptages exacts encadrent le parcours et toute pagination
incomplète, cyclique ou non ordonnée est refusée. Cette lecture peut être longue
sur les collections Andritz : elle n'est jamais remplacée par le seul compteur
de points. L'inventaire couvre aussi aliases, schémas et configuration, ainsi
qu'un manifeste structurel du Secure Deposit. Pour ce dernier, les 744 Gio ne
sont pas relus intégralement :
le manifeste structurel couvre chemins hachés, type, taille, inode, `mtime` et
`ctime`, puis le filesystem est protégé en lecture seule. Le contrôle
`quiesced -> activated` est strict : aucune
différence n'est acceptée. Le contrôle après canari est append-aware, mais il
n'autorise que l'unique artefact de provenance produit par le Chat Andritz
contrôlé, avec le même backend, la même clé hachée, la même taille et le même
SHA-256 que le ledger. Chaque testcase workspace porte aussi une propriété
JUnit `commit_sha`, égale au SHA backend et frontend observé. Une suppression,
une modification ou un ajout étranger
fait échouer la validation.

## Matrice de non-régression protégée

| Périmètre | Mutation autorisée pendant validation | Preuve exigée |
|---|---|---|
| Showcase | projections et un Run canari contrôlé | System découvert par marqueur, quatre lenses, identité/facettes/historique invariants |
| Andritz Chat Agentic | exactement une requête, un Run, ses SkillInvocations et un artefact de provenance | ledger content-free lié au SHA, au Run, aux invocations et à l'ajout ObjectStore/MinIO |
| Andritz Knowledge Capture et FSE | lecture uniquement | routes/APIs existantes, aucun ajout métier PostgreSQL/Qdrant/SFTP |
| Andritz Client360 | `dry_run` uniquement | classification admin et action sans effet externe |
| Sentinel-CI | aucune écriture métier | branding, action pack et shell Mission Room propres au workspace |
| Octocity Mission Room | aucune écriture métier | branding, action pack et absence de termes Sentinel |
| PostgreSQL | Run/SkillInvocations contrôlés et audits `navigation.resolved` des quatre workspaces | inventaire v2 constant-space avant, puis captures liées au ledger après canari, en final et à la frontière d'ouverture ; seules les tables Keycloak explicitement listées sont volatiles |
| Qdrant | aucune | collections, schémas, aliases et compteurs inchangés ; probes backend/worker rejetées en écriture |
| Secure Deposit SFTP | un lien jetable, quatre audits bornés et aucun `DepositFile` | connexion password-only, `getcwd`/`stat(.)` uniquement, `/dev/sdc` en lecture seule, révocation puis refus explicite ; aucun listing, transfert, delete, reconcile ni seed |
| MinIO/ObjectStore | unique provenance du Chat contrôlé | versioning MinIO actif, aucune suppression/modification/version étrangère |
| FAISS legacy | aucune | snapshot et montage candidat en lecture seule ; pas de conversion implicite vers Qdrant |

## Invariant crash/reboot

Une coupure de la session SSH ou un reboot ne doit jamais transformer une
indisponibilité en corruption :

- le répertoire d'état est fixé à
  `/srv/agentium-data/release-a-deployments`, privé et porté par `/dev/sdb` ;
  une surcharge vers la racine ou un autre filesystem est refusée avant tout
  `mkdir`, de sorte que le dump PostgreSQL ne peut pas remplir `/dev/sda1` ;
  les métadonnées, la phase, l'état runtime et l'état de rollback ont des
  schémas fermés, sont liés au SHA et aux quatre identités de workspace, puis
  publiés par `fsync -> replace -> fsync(parent)` ;
- les répertoires de transaction A et B sont créés en `0700` par des ouvertures
  `nofollow`, avec identité device/inode vérifiée avant toute écriture. Chaque
  exécution verrouille d'abord le descripteur du répertoire d'état ; B conserve
  en plus le fichier `.agentium-deploy.lock` en `0600` comme verrou secondaire
  compatible avec le runner canari. Les deux descripteurs survivent au re-exec
  de l'orchestrateur figé, sans fenêtre où une seconde transaction pourrait
  démarrer ;
- le marqueur HTTP vit sous `/var/lib/agentium`, et survit donc à un reboot ;
- l'ordre de fermeture est strict : appliquer les restart policies durables
  `no` et désactiver les unités writers, installer ensuite le gate HTTP
  persistant, poser les barrières IPv4/IPv6, drainer et arrêter les writers,
  puis seulement publier et fsyncer `closing_intent` ;
- ainsi, tout état qui contient `closing_intent` est déjà fermé et protégé contre le
  redémarrage automatique de SFTP, du backend, des workers et des autres
  writers ; un reboot antérieur à cette intention reste récupérable depuis
  l'état `prepared` ;
- chaque reprise réimpose les gates, draine les connexions déjà établies,
  quiesce SFTP et Keycloak, arrête et vérifie backend, worker, P4 et LiveKit,
  exige RabbitMQ vide et PostgreSQL sans connexion applicative, puis seulement
  remonte `/dev/sdc` en lecture seule ; elle ne croit jamais uniquement le
  fichier de phase ;
- le reçu terminal puis la phase `completed` sont fsyncés **avant** la première
  réouverture publique. Jusqu'à cette écriture, les unités systemd restent
  désactivées sous un drop-in `Restart=no`, les conteneurs restent en
  `restart=no`, et HTTP ainsi que les barrières writer restent fermés. Le
  retrait des guards et la restauration des restart policies n'interviennent
  qu'après le reçu et la phase terminale ;
- l'ouverture terminale du gate n'est autorisée qu'au helper candidat figé,
  auquel l'orchestrateur transmet le descripteur déjà verrouillé exclusivement
  du répertoire parent des transactions. Le helper vérifie qu'il s'agit de la
  même open-file description et refuse un FD absent, déverrouillé ou ouvert par
  un autre processus. Il exige aussi l'autorisation canonique privée de la
  direction concernée, liée au `deployment-id`, au SHA Release A, au purpose, à
  la phase terminale, au nom du reçu exact et à son SHA-256. Un appel direct du
  helper ou une autorisation copiée ne peut donc pas ouvrir le trafic ;
- un marqueur de réouverture réconciliée `format=2` est publié en dernier. Il
  lie direction, `deployment-id`, SHA Release A, phase terminale, digest du
  reçu et digest de l'autorisation terminale. S'il manque après SIGKILL ou
  reboot, ou si le gate physique a été refermé malgré sa présence, `resume`
  repart d'une fermeture durable, revalide le reçu, l'autorisation et le
  runtime, puis rejoue l'ouverture de façon idempotente ;
- la même frontière existe lors d'un rollback : reçu puis phase `rolled_back`
  précèdent l'ouverture physique et le retrait des guards. La base restaurée
  ne peut donc pas être restaurée une seconde fois après l'autorisation
  terminale ;
- en Release B, un bootstrap minimal lit `opening_forward` ou
  `rollback_opening` avant les validations sémantiques et avant le re-exec de
  l'orchestrateur figé. Il conserve toute règle firewall déjà posée, arrête
  SFTP en premier, applique `restart=no` et arrête les autres writers connus,
  arrête les unités systemd historiques, puis remonte `/dev/sdc` en lecture
  seule. Un échec IPv4/IPv6 partiel ne peut donc jamais rouvrir SFTP.

Le dump n'existe opérationnellement qu'avec son triplet
`postgres-<phase>.dump`, `.sha256` et `.ready`. Le marqueur `.ready`, publié en
dernier et de façon durable, lie le digest et la taille ; `resume`, migration et
rollback le revalident avant toute restauration. Un dump sans marqueur est une
publication interrompue, jamais une sauvegarde utilisable.

Les transitions sont monotones et vérifiées par une matrice fermée. Une erreur
avant migration persiste d'abord `recovering_pre_migration`, met en quarantaine
les artefacts incomplets, réimpose les barrières, puis ne revient à `prepared`
qu'après restauration complète de l'ancien runtime. Un rollback persiste
`rollback_closing` **avant** sa première mutation, passe par
`rollback_restoring`, puis marque durablement la frontière de réouverture. Un
`apply` ou `resume` qui rencontre une intention de rollback refuse de continuer
et exige la commande de rollback explicite avec le même `deployment-id`.

Le résultat privilégié d'un crash est donc un service encore fermé qui demande
une reprise explicite, jamais un writer revenu automatiquement sur une base ou
un filesystem dans un état intermédiaire.

## Preuve SFTP et limite d'assurance

La preuve SFTP est positive, non destructive et sans secret sérialisé. Pendant
la fermeture, les règles IPv4/IPv6 `INPUT` et `DOCKER-USER` bloquent les
interfaces externes mais laissent la boucle locale au runner protégé. L'ordre
est contraignant :

1. `arm-sftp-canary` démarre une seule fois le conteneur SFTP historique avec
   `restart=no`, ferme l'ingress, maintient `/dev/sdc` en lecture seule et émet
   `sftp-validation-runtime-ready.json`, lié à l'image, au conteneur, à
   `StartedAt`, à la host key et aux quatre règles firewall ;
2. le runner démarre temporairement le backend candidat et Keycloak, sans
   exposition publique, crée le lien jetable dans un workspace canari
   non-Andritz, puis arrête ce control plane ; frontend, workers CPU/P4, Beat
   et LiveKit restent arrêtés ;
3. le runner s'authentifie par mot de passe avec host key Ed25519 épinglée ;
   AsyncSSH ne charge ni agent ni clé par défaut ;
4. le subsystem SFTP exécute uniquement `getcwd()` et `stat('.')`. Listing,
   lecture, création, modification et suppression sont interdits ;
5. après vérification de l'arrêt du backend et de Keycloak et de l'absence de
   connexions applicatives à PostgreSQL, `record-sftp-active` fige le ledger
   privé et prouve exactement le lien actif, `deposit.link.created` et
   `deposit.sftp.auth.success` dans PostgreSQL ;
6. le runner redémarre le même control plane minimal uniquement pour révoquer
   le lien par l'API autorisée, puis l'arrête immédiatement ; la même credential
   doit alors échouer par `PermissionDenied` sans ouverture du subsystem ;
7. backend et Keycloak arrêtés, workers CPU/P4, Beat et LiveKit toujours
   arrêtés, `record-sftp-final` prouve le lien révoqué, les audits
   `deposit.link.revoked` et `deposit.sftp.auth.failed` avec motif
   `inactive_or_expired`, zéro session active et zéro `DepositFile` ;
8. l'artefact final autoportant relie les deux probes, le reçu runtime et le
   ledger DB. La finalisation refuse tout changement du conteneur, de l'image,
   de `StartedAt`, des lignes métier ou du montage avant l'ouverture.

Le mot de passe, les identifiants bruts du workspace et du lien, et le contenu
du dépôt ne quittent jamais les fichiers privés `0400/0600`. Les credentials
Andritz existants sont hors périmètre : seul un principal jetable est admis. La
preuve ne réalise volontairement aucun upload ou download ; elle prouve
authentification, autorisation de metadata minimale, ouverture/fermeture du
subsystem et révocation. Il n'existe aucun waiver SFTP accepté par le gate.

Toute perte de l'identité attestée après `arm-sftp-canary` — redémarrage du
processus ou de la VM, disparition du conteneur, ou divergence de `StartedAt`
— crée une invalidation immuable dans le journal privé. L'orchestrateur reclôt
alors HTTP et tous les ingress writers, désactive les redémarrages, arrête les
writers et remet `/dev/sdc` en lecture seule. Le reçu SFTP antérieur et toute
preuve Release B qui le référence deviennent impropres à l'ouverture, même si
l'image, la host key ou le banner sont inchangés. L'ancien principal jetable
doit être révoqué ou nettoyé sous fermeture, mais cette opération ne réhabilite
jamais son attestation.

Il n'existe aucun réarmement sur place : ni `resume`, ni rollback, ni une
nouvelle probe ne peuvent remplacer le `StartedAt` lié au même
`deployment-id`. Après qualification de l'invalidation, l'opérateur abandonne
la transaction et recommence le preflight, l'armement, l'authentification, la
révocation et les ledgers sous un **nouveau `deployment-id`**. Aucun fallback
in-process, simple banner ou attestation manuelle ne peut promouvoir la preuve
précédente.

Au contrôle en lecture seule du 23 juillet 2026, la topologie de stockage reste
conforme : `/` dispose de 12.13 GB, `/dev/sdb` de 298 GB et `/dev/sdc` de
410 GB. Le seuil de 40 Gio sur la racine bloque volontairement tout rollout
avant assainissement de capacité. `docker system df` annonce 38.77 GB de cache
builder reclaimable ; les volumes, les images actives et les tags immuables de
rollback ne doivent jamais être supprimés. Une purge du seul cache builder
reste une opération opérateur séparée, après vérification qu'aucun build n'est
en cours :

```bash
docker system df
docker builder prune --filter 'until=24h'
df -h /
```

Ne pas ajouter `--force` à cette commande : l'inventaire interactif fait partie
du contrôle humain. Rejouer le preflight après l'opération ; ne jamais abaisser
le seuil pour faire passer un déploiement.

Ne jamais exécuter `docker volume prune`, `docker system prune`, un profil
Compose `infra`, un reconcile Secure Deposit ou un reset de données pendant ce
workflow.

Ce mécanisme protège contre une mauvaise release, une migration ou une reprise
interrompue. Il ne constitue pas une sauvegarde après perte physique d'un
disque : le dump PostgreSQL est volontairement sur un autre filesystem que sa
base, mais les inventaires de `/dev/sda1`, `/dev/sdb` et `/dev/sdc` ne
dupliquent pas leurs données. Snapshots fournisseur et sauvegardes hors VM des
trois devices relèvent du plan de continuité, séparé de cette transaction.

## Release A — adoption initiale des protections

La Release A est un changement d'infrastructure à part entière, pas le
`preflight` de la Release B. Le script transactionnel refuse volontairement la
VM tant que cette adoption n'est pas terminée ; il ne doit pas être utilisé
pour contourner ses propres préconditions.

### Préparation hors interruption

- Créer une branche/worktree depuis le **SHA live exact**, contenant uniquement
  les primitives de sûreté. Les migrations 065–076, backfills, seeds et code
  métier des Lots 7–9 ne doivent pas apparaître dans son diff.
- Créer puis vérifier le manifeste privé du diff Release A avec
  `scripts/agentium_release_a_manifest.py`. Ce gate est obligatoire avant revue,
  push ou déploiement : il lie le SHA live fixe, le SHA A, chaque path, mode,
  blob Git et digest de patch, ainsi que l'empreinte de la policy embarquée.
  Une policy de revue sémantique privée et liée aux mêmes blobs est obligatoire ;
  une revue informelle de la liste de fichiers ne la remplace pas.
- Libérer au moins 40 Gio sur `/` avec une opération opérateur distincte. La
  seule candidate déjà identifiée est le cache Docker builder inutilisé ; ne
  jamais purger volumes, images actives ou tags de rollback.
- Obtenir trois sauvegardes fournisseur ou hors VM vérifiées et restaurées,
  exactement une pour `/dev/sda1`, une pour `/dev/sdb` et une pour `/dev/sdc`.
  Une copie locale des quelque 150 Gio MinIO sur `/srv` n'est pas
  une stratégie de reprise après perte du disque qui contient à la fois la
  source et la copie.
- Capturer les dumps PostgreSQL, inventaires Qdrant/MinIO/ObjectStore, le
  manifeste Secure Deposit et le snapshot FAISS avant toute mutation. Chaque
  dump doit avoir son checksum et son marqueur `.ready` durable avant d'être
  consommé ou déclaré restaurable.
- Générer hors logs une clé Qdrant admin et une clé lecture seule distinctes,
  ainsi que des credentials S3 séparés pour l'application et le canari. Les
  valeurs restent uniquement dans les secrets VM.
- Qualifier la dérive persistée déjà détectée : une `ExpertCaptureSession` du
  workspace `test` référence un System Andritz. La décision de correction doit
  être explicite, précédée d'une sauvegarde et auditée. Le déploiement ne la
  répare jamais et ne lance aucun seed ; tant que le compteur global n'est pas
  nul, l'audit d'autorité tenant échoue.

Le manifeste du diff est produit dans un répertoire privé, jamais dans le
dépôt. Le fichier de sortie doit ne pas exister avant `create` :

```bash
RELEASE_A_REPO='/chemin/absolu/omnirag-release-a-hardening'
RELEASE_A_SHA='<sha-complet-release-a>'
RELEASE_A_REVIEW_DRAFT='/chemin/prive/release-a-semantic-review.draft.json'
RELEASE_A_REVIEW='/chemin/prive/release-a-semantic-review.json'
RELEASE_A_MANIFEST='/chemin/prive/release-a-diff-manifest.json'

"$RELEASE_A_REPO/scripts/agentium_release_a_manifest.py" review-template \
  --repository "$RELEASE_A_REPO" \
  --release-a-sha "$RELEASE_A_SHA" \
  --output "$RELEASE_A_REVIEW_DRAFT"
# Un reviewer lit les patches exacts, renseigne approval=approved, reviewer,
# review_ticket, classification et hardening_controls dans le draft privé.
"$RELEASE_A_REPO/scripts/agentium_release_a_manifest.py" seal-review \
  --repository "$RELEASE_A_REPO" \
  --release-a-sha "$RELEASE_A_SHA" \
  --draft "$RELEASE_A_REVIEW_DRAFT" \
  --output "$RELEASE_A_REVIEW"
"$RELEASE_A_REPO/scripts/agentium_release_a_manifest.py" create \
  --repository "$RELEASE_A_REPO" \
  --release-a-sha "$RELEASE_A_SHA" \
  --review-policy "$RELEASE_A_REVIEW" \
  --output "$RELEASE_A_MANIFEST"
"$RELEASE_A_REPO/scripts/agentium_release_a_manifest.py" verify \
  --repository "$RELEASE_A_REPO" \
  --release-a-sha "$RELEASE_A_SHA" \
  --review-policy "$RELEASE_A_REVIEW" \
  --manifest "$RELEASE_A_MANIFEST"
```

Le résultat doit être `passed`. Toute divergence d'ascendance, path, statut,
mode, inventaire ou empreinte de policy maintient Release A en `NO-GO`.

### Fenêtre contrôlée

1. Installer le gate HTTP persistant, appliquer les restart policies durables
   `no` et désactiver les unités writers. Publier `closing_intent` seulement
   après ces protections reboot-safe, puis fermer les nouveaux transports
   SFTP/LiveKit par les barrières IPv4/IPv6 et drainer les connexions existantes.
2. Arrêter tous les writers applicatifs. Remonter `/dev/sdc` en lecture seule et
   vérifier qu'aucun descripteur d'upload ne reste ouvert.
3. Activer le versioning du bucket MinIO existant. Vérifier par API que le
   statut est `Enabled`, puis tester avec un objet de garde dédié que le compte
   canari ne peut ni supprimer une version, ni changer la configuration du
   bucket. Le versioning protège les futures versions ; il ne remplace pas la
   sauvegarde hors VM des objets déjà présents. Le bootstrap est rejouable
   uniquement dans ses quatre états atteignables par crash : absent, user créé,
   policy créée ou policy attachée. À chaque reprise, il réauthentifie le secret
   figé, exige un user enabled sans groupe ni policy supplémentaire, compare la
   policy exportée au contrat exact, puis confronte `MINIO_PROOF` à son contenu
   déterministe avant de poursuivre.
4. Redémarrer Qdrant sur les mêmes binds `/srv/agentium-data` avec les deux clés.
   Tester l'admin sur une collection de garde absente et prouver que la clé
   lecture seule reçoit `401/403` sur la même route d'écriture. Aucun snapshot,
   alias ou collection existante ne doit disparaître.
5. Installer le snippet Nginx de maintenance et l'unité backend canonique liée à
   `127.0.0.1:8000`. Vérifier qu'il n'existe plus aucun listener public direct
   sur 8000 et que le marqueur `/var/lib/agentium/deploy-maintenance` survit à
   un restart contrôlé.
6. Configurer backend/worker/canari avec les credentials de moindre privilège,
   les montages Secure Deposit et FAISS en lecture seule pendant validation,
   puis recapturer tous les inventaires.
7. Lier les trois images candidates à leurs IDs OCI dès le build, revalider les
   tags avant chaque activation, puis publier un reçu du runtime exact avec IDs
   de conteneur, IDs d'image, santé et `build-info` servi. Ne rouvrir qu'après
   égalité des inventaires, audit d'autorité tenant sans dérive et smoke
   authentifié séparé de Showcase, Andritz, Sentinel et Octocity. Un échec
   restaure les fichiers Nginx/systemd sauvegardés et maintient les writers
   fermés ; il ne déclenche jamais de seed ou de recréation de volume.

### Commandes de la transaction Release A

Ces commandes sont un gabarit, pas une autorisation d'exécution. Elles ne sont
utilisables qu'après le GO portant sur les deux SHA et le `deployment-id`.
`PRE_EVIDENCE` contient exactement les six fichiers dont les SHA-256 sont
référencés par les préconditions. Les 37 références finales ne sont plus une
liste déclarative de fichiers interchangeables : 23 sont résolues vers les
artefacts canoniques du journal A, et 14 preuves externes sont fournies dans
`FINAL_EVIDENCE` sous forme de triplets fermés `artefact + provenance JSON +
signature détachée`. Les répertoires sont `0700`, leurs fichiers `0400` ou
`0600`, et restent hors des deux worktrees et du journal.

Le preflight fige depuis le SHA Release A le registre revu
`config/agentium/release-a-evidence-authorities.v1.json`, puis exige trois
classes d'autorité complètes et distinctes (`backup_provider`,
`protected_runner`, `release_a_host_collector`). Il n'existe aucune option CLI
permettant à l'opérateur de substituer ce registre. Un registre incomplet
bloque donc le **preflight avant toute mutation**, même si son schéma JSON est
valide. Le fichier livre actuellement `protected_runner` seulement : le chemin
reste **NO-GO** tant que les clés publiques réelles de `backup_provider` et
`release_a_host_collector` n'ont pas été ajoutées par un changement Git revu.

```bash
LIVE_SHA='<sha-live-complet>'
RELEASE_A_SHA='<sha-release-a-complet>'
DEPLOYMENT_ID='<id-release-a-unique>'
LIVE_REPO='/home/ubuntu/omnirag'
CANDIDATE_REPO='/srv/agentium-data/worktrees/release-a'
PRIVATE_ENV='/srv/agentium-private/release-a-env'
PRECONDITIONS='/srv/agentium-private/release-a-preconditions.json'
PRE_EVIDENCE='/srv/agentium-private/release-a-precondition-evidence'
MANIFEST='/srv/agentium-private/release-a-diff-manifest.json'
REVIEW='/srv/agentium-private/release-a-semantic-review.json'

COMMON=(--live-repo "$LIVE_REPO" --candidate-repo "$CANDIDATE_REPO"
  --branch codex/release-a-from-hotfix \
  --live-sha "$LIVE_SHA" --release-a-sha "$RELEASE_A_SHA"
  --deployment-id "$DEPLOYMENT_ID")

"$CANDIDATE_REPO/scripts/deploy-agentium-release-a-safe.sh" preflight \
  "${COMMON[@]}" \
  --manifest "$MANIFEST" --manifest-sha256 "$(sha256sum "$MANIFEST" | awk '{print $1}')" \
  --review-policy "$REVIEW" --review-policy-sha256 "$(sha256sum "$REVIEW" | awk '{print $1}')" \
  --preconditions "$PRECONDITIONS" --preconditions-sha256 "$(sha256sum "$PRECONDITIONS" | awk '{print $1}')" \
  --preconditions-evidence-root "$PRE_EVIDENCE" \
  --runtime-env-source-root "$PRIVATE_ENV"

EXECUTOR="/srv/agentium-data/release-a-deployments/$DEPLOYMENT_ID/deploy-agentium-release-a-safe.sh"
"$EXECUTOR" prepare "${COMMON[@]}"
"$EXECUTOR" apply "${COMMON[@]}" --preconditions-evidence-root "$PRE_EVIDENCE"

# Reboot contrôlé pendant que les gates restent fermés, puis :
"$EXECUTOR" resume "${COMMON[@]}"

# Le runner protégé prépare hors logs le principal jetable, le mot de passe,
# known_hosts, le ledger privé et ses fichiers de preuve en 0400/0600.
"$EXECUTOR" arm-sftp-canary "${COMMON[@]}"

# Démarrer temporairement backend + Keycloak sans exposition publique, créer le
# lien jetable par l'API autorisée, puis les arrêter. Workers CPU/P4, Beat,
# frontend et LiveKit restent arrêtés. Exécuter ensuite `probe` sur loopback et
# vérifier l'absence de connexion applicative avant le snapshot actif.
SFTP_LEDGER='/srv/agentium-private/release-a-sftp-ledger.json'
"$EXECUTOR" record-sftp-active "${COMMON[@]}" \
  --sftp-canary-ledger "$SFTP_LEDGER" \
  --sftp-canary-ledger-sha256 "$(sha256sum "$SFTP_LEDGER" | awk '{print $1}')"

# Redémarrer backend + Keycloak uniquement pour révoquer le lien via l'API,
# puis les arrêter avant `verify-post-revoke` et le snapshot PostgreSQL final.
"$EXECUTOR" record-sftp-final "${COMMON[@]}"

# Le runner appelle enfin `finalize` du producteur SFTP avec le reçu runtime,
# le reçu ledger PostgreSQL et les deux preuves privées, puis signe le triplet
# externe `sftp-positive-auth` avant de construire l'attestation v4.

ATTESTATION='/srv/agentium-private/release-a-attestation.json'
FINAL_EVIDENCE='/srv/agentium-private/release-a-final-evidence'
"$EXECUTOR" finalize "${COMMON[@]}" \
  --attestation "$ATTESTATION" \
  --attestation-sha256 "$(sha256sum "$ATTESTATION" | awk '{print $1}')" \
  --final-evidence-root "$FINAL_EVIDENCE"
"$EXECUTOR" status "${COMMON[@]}"
```

Le dernier résultat attendu est `completed`. `origin/demo/agentic` doit rester
exactement sur `RELEASE_A_SHA` du premier `preflight` jusqu'à cet état. Les
appels Docker sont forcés sur `/var/run/docker.sock` et l'Engine ID capturé au
preflight est revalidé à chaque phase. Une interruption MinIO dans un état
atteignable est reprise idempotemment après revalidation complète ; une policy,
un groupe, un secret ou un état d'identité divergent reste fermé et exige une
qualification manuelle. De même, une collection de probe Qdrant ambiguë n'est ni
supprimée ni écrasée : le script garde les gates fermés.
Après l'intention d'adoption stateful, aucun rollback automatique n'est
autorisé ; la récupération reste fermée et suit les sauvegardes attestées.

Le premier preflight de B ne se contente pas de rejouer le validateur de
l'attestation A. Il retrouve exactement une transaction A canonique sous
`/srv/agentium-data/release-a-deployments`, exige sa phase `completed`, le même
SHA actif et le même Engine ID Docker, puis rehash les huit reçus référencés
par son reçu de transaction v3, dont le reçu OCI, le runtime-ready SFTP et le
ledger PostgreSQL. Il revalide aussi l'autorisation terminale canonique, le
marker d'ouverture `format=2` et leurs digests, puis le même
conteneur/image/`StartedAt`. Il refuse toute invalidation SFTP liée à A : une
preuve devenue stale ne peut jamais autoriser B. Une attestation copiée sans
transaction A achevée ne peut donc pas autoriser B.

### Gate de sortie Release A

La Release A n'est acquise que si un reboot contrôlé conserve le gate fermé,
Qdrant authentifié, le backend en loopback et les restart policies attendues,
puis si la réouverture contrôlée retrouve exactement les quatre workspaces et
les services SFTP/LiveKit historiques. Le cycle SFTP authentifié, révoqué et
journalisé est obligatoire, sans invalidation de son identité runtime. Tant que
ce bootstrap n'a pas son propre runbook exécuté, son attestation, une décision
sur la dérive tenant et cette preuve live, la Release B reste **NO-GO**.

L'attestation opérateur est un JSON privé, content-free et à schéma fermé,
contrôlé par `scripts/agentium_release_a_attestation.py`. Elle est liée au SHA
Release A réellement actif, au hostname de la VM et à sa propre empreinte. Elle
ne contient que des statuts, timestamps et SHA-256 pour : exactement trois
sauvegardes hors VM distinctes restaurées (`/dev/sda1`, `/dev/sdb` et
`/dev/sdc`), MinIO versionné et à
credentials séparés, Qdrant admin/lecture seule, reboot et loopback backend,
audit tenant à zéro, puis authentification et subsystem SFTP positifs. Le
smoke content-free couvre aussi Showcase, Andritz, Sentinel, Octocity et
LiveKit ; les comparaisons d'intégrité couvrent PostgreSQL, Qdrant, l'ObjectStore
MinIO, FAISS, Secure Deposit et RabbitMQ. Chaque restauration et comparaison
est liée à son artefact de preuve par SHA-256.
Le validateur refuse les champs supplémentaires, preuve périmée, fichier
symbolique/hardlinké, permissions autres que `0400/0600`, divergence de host,
waiver SFTP ou digest implicite. Son reçu vérifie la cohérence de l'attestation ;
il ne fabrique ni ne remplace les preuves opérateur externes qu'elle référence.
Le vérificateur lui-même appartient à la trust root Release A : son blob Git
doit être strictement identique dans la Release A active et la Release B
candidate. Une Release B qui modifie le gate chargé de l'autoriser est refusée.
Les préconditions et leurs preuves de restauration/capacité doivent dater de
moins de 24 heures ; cette borne n'est pas modifiable par l'environnement
opérateur. Leurs octets sont reliés au reçu du `preflight`, puis relus et
rehashés juste avant la première mutation de `apply`. S'ils expirent, changent
ou disparaissent, abandonner l'état `prepared` et utiliser un nouveau
`deployment-id`. L'attestation finale v4 et ses 37 références sont liées avant
`opening_forward` par un manifeste typé : 23 références pointent vers le
journal canonique et 14 vers des preuves externes dont la provenance est signée
par une clé approuvée. Les triplets externes vérifiés, le registre d'autorités
et le manifeste de liaison sont gelés dans le journal privé ; `resume`, la
réconciliation B et les reprises d'ouverture les rehashent et rejouent la
vérification cryptographique. Ils ne dépendent donc pas du maintien du
répertoire opérateur après l'intention irréversible.

## Transaction

Cette section ne s'exécute qu'après vérification du manifeste/review et
attestation opérationnelle de la Release A. Les quatre UUID
sont résolus en lecture seule juste avant la fenêtre, puis comparés aux slugs
attendus par le collecteur PostgreSQL ; ils ne sont pas sérialisés dans
`validation.json`.

```bash
LIVE_REPO=/home/ubuntu/omnirag
SHA='<sha-complet-poussé>'
DEPLOYMENT_ID="$(date -u +%Y%m%dT%H%M%SZ)-${SHA:0:12}"
LAUNCHER="/srv/agentium-data/deploy-launchers/${DEPLOYMENT_ID}-${SHA:0:12}"
RELEASE_A_ATTESTATION='/chemin/prive/release-a-attestation.json'
chmod 0600 "$RELEASE_A_ATTESTATION"
RELEASE_A_ATTESTATION_SHA256="$(sha256sum "$RELEASE_A_ATTESTATION" | awk '{print $1}')"
RELEASE_A_MANIFEST='/chemin/prive/release-a-diff-manifest.json'
RELEASE_A_REVIEW='/chemin/prive/release-a-semantic-review.json'
RELEASE_A_MANIFEST_SHA256="$(sha256sum "$RELEASE_A_MANIFEST" | awk '{print $1}')"
RELEASE_A_REVIEW_SHA256="$(sha256sum "$RELEASE_A_REVIEW" | awk '{print $1}')"

# Valeurs résolues et vérifiées séparément pour Showcase, Andritz,
# Sentinel-CI et Octocity Mission Room.
CANARY_IDS=(<uuid-showcase> <uuid-andritz> <uuid-sentinel> <uuid-octocity>)
COMMON=(--repo-dir "$LIVE_REPO" --branch demo/agentic --sha "$SHA"
  --deployment-id "$DEPLOYMENT_ID")
for id in "${CANARY_IDS[@]}"; do COMMON+=(--canary-workspace-id "$id"); done

git -C "$LIVE_REPO" fetch origin demo/agentic
test "$(git -C "$LIVE_REPO" rev-parse origin/demo/agentic)" = "$SHA"
git -C "$LIVE_REPO" worktree add --detach "$LAUNCHER" "$SHA"

"$LAUNCHER/scripts/deploy-agentium-safe.sh" preflight "${COMMON[@]}" \
  --release-a-manifest "$RELEASE_A_MANIFEST" \
  --release-a-manifest-sha256 "$RELEASE_A_MANIFEST_SHA256" \
  --release-a-review-policy "$RELEASE_A_REVIEW" \
  --release-a-review-policy-sha256 "$RELEASE_A_REVIEW_SHA256" \
  --release-a-attestation "$RELEASE_A_ATTESTATION" \
  --release-a-attestation-sha256 "$RELEASE_A_ATTESTATION_SHA256"

ORCHESTRATOR="/srv/agentium-data/deployments/$DEPLOYMENT_ID/deploy-agentium-safe.sh"
git -C "$LIVE_REPO" worktree remove "$LAUNCHER"

"$ORCHESTRATOR" prepare "${COMMON[@]}"
"$ORCHESTRATOR" apply "${COMMON[@]}"
```

`apply` s'arrête une première fois en `backfill_pending` et imprime le digest du
dry-run Workspace Apps. L'opérateur lit le rapport, vérifie qu'il ne touche que
les installations attendues et reprend avec ce digest exact :

```bash
ANALYSIS_SHA='<sha256-du-dry-run-relu>'
"$ORCHESTRATOR" resume "${COMMON[@]}" \
  --workspace-app-analysis-sha "$ANALYSIS_SHA"
```

Le premier appel copie atomiquement l'orchestrateur, les helpers, le manifeste,
sa policy de revue et l'attestation opérationnelle Release A dans le répertoire
privé du déploiement. Le helper de manifeste doit avoir exactement le même blob
dans la Release A active et la Release B candidate. Le gate de code est vérifié
avant l'attestation opérationnelle, puis tous les digests et les deux reçus sont
inscrits dans les métadonnées v5 et revérifiés avant chaque transition de phase ;
l'attestation ne peut jamais remplacer le manifeste. `prepare` construit dans un second worktree isolé
sur `/dev/sdb`, sans activer les images, capture la provenance et répète les
migrations puis le retour à la révision précédente sur une restauration
temporaire. `apply` ferme HTTP et les nouvelles connexions SFTP, attend la fin
des connexions existantes, audite les descripteurs ouverts, arrête les writers,
remonte `/dev/sdc` en lecture seule, crée puis publie durablement le triplet du
dump final, produit le dry-run, attend son approbation par digest, puis migre et
active le candidat. L'image SFTP n'appartient pas au candidat B : son ID Release
A est capturé et vérifié, le conteneur est seulement arrêté puis redémarré sur
ce même ID, sans build ni recréation. Il doit
terminer en `validation_pending`.

Immédiatement après le build, l'orchestrateur fige dans un override Compose
privé les IDs OCI exacts du backend, du frontend et du worker. La provenance
canari doit ensuite désigner exactement ces mêmes IDs (`sha256:...`) ; backend,
frontend, worker et P4 ne sont donc jamais recréés depuis le seul tag mutable,
y compris après crash. Après chaque recréation, l'orchestrateur compare l'ID du
conteneur à l'override puis, juste avant l'ouverture, revalide santé, labels OCI
et `build-info` backend/frontend. Le serveur PostgreSQL de rehearsal utilise de
même l'ID exact de l'image du PostgreSQL live, et jamais le tag mutable
`postgres:17`.

Les canaris sont ensuite exécutés avec les identifiants injectés par
l'environnement. Ils vérifient au minimum :

- SHA, labels OCI, build-info et révision Alembic ;
- System 360 Showcase ;
- les trois Apps Andritz et leurs quatre surfaces, Client360 en `dry_run`,
  Knowledge Capture/FSE en lecture et exactement un Chat contrôlé dont le Run,
  les SkillInvocations et l'artefact de provenance sont audités sans contenu ;
- Sentinel et Octocity séparément, puis dans les deux sens avec une réponse de
  l'ancien workspace retardée ;
- l'autorité de chaque binding System et l'absence globale de lien
  `ExpertCaptureSession -> System` entre workspaces ;
- égalité stricte de Qdrant et Secure Deposit, intégrité de tous les objets
  préexistants et correspondance de l'unique ajout de provenance autorisé.

Le runner ne reçoit les identifiants que dans son environnement de processus :

```bash
read -r E2E_USERNAME
read -rs E2E_PASSWORD
export E2E_USERNAME E2E_PASSWORD
"$LIVE_REPO/scripts/run-agentium-safe-canaries.sh" \
  --repo-dir "$LIVE_REPO" --branch demo/agentic \
  --sha "$SHA" --deployment-id "$DEPLOYMENT_ID"
unset E2E_USERNAME E2E_PASSWORD
```

Le runner produit les preuves privées mais ne décide pas la réouverture. Après
son succès, l'orchestrateur recapture PostgreSQL et Qdrant, recalcule toutes les
différences, construit lui-même `validation.json`, puis le vérifie une seconde
fois avant d'ouvrir :

```bash
"$ORCHESTRATOR" resume "${COMMON[@]}" \
  --workspace-app-analysis-sha "$ANALYSIS_SHA" \
  --validation-artifact \
  "/srv/agentium-data/deployments/$DEPLOYMENT_ID/validation.json"
```

`resume` recalcule les digests, vérifie l'âge et les permissions de la preuve,
vérifie que RabbitMQ est encore vide, que Qdrant est toujours en lecture seule,
et compare les inventaires PostgreSQL v2 : aucun état métier préexistant ne
change ; seuls le Run/les SkillInvocations liés au ledger et les agrégats de
navigation canoniques des quatre workspaces peuvent progresser. Il recapture
encore PostgreSQL à la frontière d'ouverture et refait la comparaison avant
tout writer. La phase durable `opening_forward` est écrite et fsyncée avant
le premier writer ou remount RW ; `opened`, puis `completed`, ne sont publiées
qu'après la réouverture prouvée. Le contrat Qdrant admin est attesté avant de
retirer le gate TCP/8000 ;
la preuve SSH loopback est, elle, produite alors que le gate SFTP externe est
encore fermé et `/dev/sdc` encore en lecture seule ; elle est liée à une
intention durable qui contient les SHA B et A/SFTP. Le Secure Deposit revient
ensuite en lecture-écriture, le gate SFTP est retiré et
P4/SFTP/LiveKit/scheduler retrouvent leur état antérieur avant l'ouverture HTTP.
Si le processus tombe pendant `opening_forward`, la reprise reclôt d'abord tous les
ingress, attend la fin des sessions existantes, arrête tous les writers et
vérifie RabbitMQ/PostgreSQL avant le remount lecture seule et la recréation du
backend, du frontend, du worker et de P4 par IDs OCI attestés. Le conteneur SFTP
attesté n'est jamais recréé : toute perte de son identité déclenche
l'invalidation immuable et abandonne ce `deployment-id`. Le même ordre
s'applique à l'intention durable
`rollback_opening` : les images
précédentes viennent d'un override privé dérivé de l'état rollback v3, puis le
runtime précédent doit encore présenter exactement le conteneur, l'image, la
host key et le `StartedAt` SFTP déjà attestés sur le réseau Docker et sur le
port publié loopback, avec inventaire d'authentification inchangé et
`/dev/sdc` toujours en lecture seule. Son reçu est lié à une intention durable
avant le remount RW et le retrait du gate SFTP. Backend, frontend, worker, P4
et SFTP sont revérifiés par ID exact avant l'ouverture HTTP ; une divergence
SFTP interdit cette ouverture et ne peut pas être réparée dans la transaction.
Une simple déclaration
JSON non reliée aux snapshots, aux JUnit, au SHA, aux images et au ledger n'est
pas acceptée.

## Arrêts et rollback

- Avant migration, une erreur entre en `recovering_pre_migration`, réimpose les
  barrières et ne rouvre le gate qu'après restauration complète et durable de
  l'état des services.
- Après le début de la migration, une erreur laisse tous les writers arrêtés.
  Aucun downgrade ou rollback image implicite n'est tenté.
- Tant que la phase `opened` n'a pas été atteinte, le rollback explicite
  persiste `rollback_closing`, revalide le triplet de dump quiescé, restaure la
  base une seule fois, vérifie l'ancienne révision Alembic, puis restaure
  exactement les images backend, frontend, worker et P4 enregistrées. Le
  rollback ne recrée ni ne redémarre le conteneur SFTP après son attestation :
  il exige le même conteneur, la même image et le même `StartedAt`. Une perte de
  cette identité persiste l'invalidation, maintient le plan d'exécution fermé
  et impose un nouveau `deployment-id` ; elle n'autorise aucun réarmement dans
  le rollback. Le bind Secure Deposit n'est jamais recréé, déplacé ni purgé.

```bash
"$ORCHESTRATOR" rollback "${COMMON[@]}" \
  --workspace-app-analysis-sha "$ANALYSIS_SHA" \
  --confirm-rollback "$DEPLOYMENT_ID"
```

Après réouverture aux utilisateurs, une restauration automatique PostgreSQL
est interdite car elle pourrait supprimer de nouvelles écritures. Désactiver
d'abord les feature flags concernés et préparer un correctif forward.

## Capacité et rétention

Le preflight impose :

- 40 Gio libres sur `/` ;
- 64 Gio libres sur `/srv/agentium-data` ;
- `max(64 Gio, 10 %)` sur le Secure Deposit ;
- 10 % d'inodes libres sur chaque filesystem.

Le déploiement ne nettoie rien automatiquement. Si la racine est sous le seuil,
purger uniquement le cache Docker builder inutilisé. Les anciens tags de
rollback peuvent ensuite être retirés explicitement en conservant le courant
et les deux derniers états vérifiés. Les volumes et les copies de données ne
sont jamais concernés.

Les artefacts qui permettent un rollback (`runtime-env`, dumps, images et état
de transaction) restent locaux pendant une fenêtre minimale de sept jours et
jusqu'à validation explicite de la release suivante. Leur purge est une action
opérateur distincte, après preuve de sauvegarde hors VM ; elle n'est jamais
automatique. Les reçus content-free, JUnit expurgés et digests peuvent être
conservés 90 jours. Les bundles d'environnement, dumps et attestations privées
ne sont jamais copiés dans le dépôt ni joints à un ticket.

## Clôture

Conserver sous `/srv/agentium-data/deployments/<deployment-id>` les dumps,
checksums, snapshots, comparaison, JUnit et attestation finale en permissions
privées. Surveiller pendant 60 minutes les HTTP 5xx, RabbitMQ, Runs échoués,
PostgreSQL, Qdrant et les erreurs SFTP.

Le déploiement reste interdit tant que l'un des points suivants n'est pas vert :

- Release A attestée séparément : MinIO versionné, credentials applicatif et
  canari bornés, Qdrant admin/lecture seule prouvés, gate persistant après reboot
  et backend systemd uniquement sur loopback ; l'ouverture terminale est liée
  au verrou orchestrateur hérité, à l'autorisation canonique et au marker
  `format=2` exacts ;
- manifeste de diff Release A créé puis vérifié avec le SHA A exact, le SHA
  live fixe et l'empreinte de policy attendue ;
- exactement trois sauvegardes fournisseur ou hors VM restaurables, une pour
  `/dev/sda1`, une pour `/dev/sdb` et une pour `/dev/sdc`, et preuve SFTP
  authentifiée avec un principal canari jetable, identité `StartedAt` inchangée
  et aucune invalidation ; la chaîne sans credential ou liée à une preuve stale
  reste au mieux `runner_verified` et ne peut pas ouvrir Release B ;
- SHA complet présent sur `origin/demo/agentic`, checkout et runtime initial
  alignés, VM propre et aucune dérive Nginx/systemd ;
- au moins 40 Gio libres sur `/`, donc assainissement préalable du cache builder
  actuellement nécessaire ;
- topologie exacte `/dev/sda1`, `/dev/sdb` et `/dev/sdc`, manifests complets et
  lisibles en privilège contrôlé ; PostgreSQL/Keycloak/RabbitMQ restent sur la
  racine, Qdrant/MinIO/ObjectStore sous `/srv/agentium-data`, et SFTP Secure
  Deposit sur `/dev/sdc` ;
- rehearsal aller/retour PostgreSQL réussi et images de rollback encore
  présentes par ID ; triplets dump/checksum/`.ready` revalidés ;
- canaris Showcase, Andritz, Sentinel et Octocity séparément verts et liés au
  même SHA ; Andritz prouve Chat Agentic, Knowledge Capture, Client360 et FSE,
  tandis que Sentinel et Octocity prouvent séparément branding et action packs ;
- audit global des bindings sans lien entre tenants ; la dérive actuellement
  observée du workspace `test` vers un System Andritz doit avoir fait l'objet
  d'une décision opérateur auditée et le compteur doit être revenu à zéro ;
- comparaison PostgreSQL v2 liée au ledger : seuls le Run et les
  SkillInvocations du Chat contrôlé et les agrégats de navigation des quatre
  workspaces ont progressé ; Qdrant est resté en lecture seule et `/dev/sdc`
  est resté structurellement identique ;
- validation finale toujours fraîche, writers encore gelés et gates toujours
  fermés juste avant `resume`.

Ces points sont des conditions cumulatives. La présence du code, de tests
locaux ou d'un rapport `passed` isolé ne vaut ni attestation Release A ni GO de
Release B.
