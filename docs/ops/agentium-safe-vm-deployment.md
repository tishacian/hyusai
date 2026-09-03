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

## Gel de la démo NAWA — ouvert le 02/09/2026 (réalignement post-audit)

Périmètre gelé : le chemin `Studio -> SAP` de la démo PR→PO
(`/work/pr-to-po`, flow `pr_to_po_flow`, serveurs MCP `sap`/`hikma`/`bapi_po`,
porte d'écriture `connectors/mcp/write.py`). Commit de référence servi sur la
VM à l'ouverture : `988ee5c7ec2c1ab2a16e6d42831518d51ed6b39a`.

Pendant le gel : aucune nouvelle fonctionnalité sur ce chemin, aucun
changement de contrat d'écriture SAP hors du chantier H0+H1 du plan de
réalignement (une seule porte d'écriture, un seul runtime PR→PO côté serveur).
Le Studio reste servi tel quel jusqu'au déploiement H1.

Contrat de non-régression : `frontend-ng/e2e/tests/18-nawa-agent-studio-canary.spec.ts`
(redirect `/desk`, run → gate → décision, verdict d'écriture serveur, zéro
`invoke` MCP depuis le navigateur, dialogue d'écriture dans le chat). Il est
figé en H0 ; H1 doit le passer **sans le modifier**.

Critères de sortie du gel :

| Critère | Preuve attendue |
|---|---|
| Une seule porte d'écriture | tout `tools/call` non-lecture (HTTP `invoke`, run-engine, `mcp_call_v1`) passe par `mcp_write` — tests `test_mcp_write.py`, `test_mcp_call_skill.py` verts |
| Un seul runtime PR→PO | `pr-to-po-desk.ts` / `PrToPoBoardComponent` supprimés ; le Studio ne fait ni lecture ni écriture SAP ; `rg BAPI_ frontend-ng/src` ne renvoie que des noms d'outils du rail |
| Contrat e2e | spec 18 verte sur la VM au SHA déployé, mode par défaut (garde-fou create off) puis `E2E_NAWA_STUDIO_WRITE=1` si un PO réel est accepté |
| Journal | entrée d'itération H0+H1 avec build-info, gates, QA, rollback |

Fin du gel : à la validation de l'itération H0+H1 ci-dessous. H2, H3, H4
partent ensuite en PRs séparées, hors gel.

**Gel levé le 03/09/2026** sur l'itération « Réalignement H0+H1 » servie sur
`1134a61d` (branche de PR `cursor/realign-h0-h1-5b89` → `demo/agentic`) : les
quatre critères ci-dessus sont tenus, preuves dans l'entrée d'itération en fin
de journal. Le contrat e2e a été passé sans modification de ses assertions ;
seules deux retouches d'outillage y ont été faites (option vidéo, ouverture du
`<details>` du transcript avant lecture).

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

## Record d'exploitation — voie dérogée « Option B » (28/07) et atterrissage Release B (30/07)

Le 28/07/2026, la réouverture post-Release A a été conduite en voie dérogée
(« Option B ») : ouverture manuelle du gate sans attestation protected-runner
complète, pour tenir l'échéance démo (4 apps andritz + chat sourcé à 9h).
Fonctionnellement et techniquement le résultat est identique à la voie
officielle ; seules les attestations diffèrent. Dette embarquée : specs canary
figées (3 surfaces, anciens sélecteurs), runner `run-agentium-safe-canaries.sh`
épinglant les anciens noms de tests, volume sda OVH en attente chez OVH.

Le 30/07/2026 (~01:07-01:18 UTC), la Release B (lots 7-9) a été atterrie sur
l'état de production nawa par merge (`release/b-landing`, SHA `22b271c1`, tag
`agentium-release-b-20260730-22b271c1`, `demo/agentic` fast-forwardée) dans une
fenêtre dérogée outillée : gate fermée (503 externe / loopback 127.0.0.2
disponible), dump PG frais checksummé, état primaire/jumeau nawa consigné
(primaire actif), `alembic upgrade head` one-off (12 migrations
065_system_version_config → 076), recréation des trois conteneurs applicatifs,
contrôles DB (chat nawa préservé, `platform_brand` intact, flow 29 nœuds +
jumeau 29 nœuds) et smoke non-auth, puis réouverture. Record complet :
`/srv/agentium-data/release-b-deployments/release-b-2026-07-30/LANDING-RECORD.md`
sur la VM.

La dette de specs canary est soldée dans cette même version : specs défigées
(4 surfaces andritz, sélecteur workspace par `data-testid`, breadcrumb
System360, inventaire workspaces réel) et runner aligné — elles constituent la
nouvelle baseline pour une régularisation attestée post-B. Décision actée :
politiques `restart: unless-stopped` restaurées sur les services applicatifs
(survie au reboot VM).

### Régularisation attestée post-B (30/07 14:40 UTC) — soldée

La voie officielle carakai protected-runner a produit un reçu
`acceptance` **passed** (7 tokens signés) contre le déploiement live
`f51db0a1` (`revision_verified: true`), avec
`formal_release_eligible: false` et principal `operator_personal_admin`
(régularisation, pas promotion formal-release). Source tooling :
`754ff75f` (`release/b-attestation-tooling`). Evidence privée :
`/srv/agentium-data/release-b-deployments/release-b-2026-07-30/attestation/`
et record :
`/srv/agentium-data/release-b-deployments/release-b-2026-07-30/LANDING-RECORD.md`.

Mitigations ops sans changement d'image (SHA préservé) : workers uvicorn
3→8 (`/root/release-b-workers.yml`), fontconfig sur carakai, brand AYA
`sentinel-ci` réparé en base. Backlog non bloquant : N+1 `/api/v1/skills`,
alias root SFTP `"/."`, volume OVH sda.

## Réalignement sur `demo/agentic` (30/07) — boucle d'itération courte

Après la régularisation attestée, la production est réalignée sur la branche
`demo/agentic` : le worktree de build bascule sur la branche et est renommé
`/srv/agentium-data/worktrees/demo-agentic`, les trois images applicatives
sont reconstruites au tip avec double tag `demo-agentic` (mouvant) et
`<sha12>` (immuable, adressable en rollback), puis une nouvelle attestation
`acceptance` (7 tokens) conserve `tested_sha == live_sha`. Les anciennes
images `:release-b` sont conservées comme point de rollback vers `f51db0a1`.

### `/home/ubuntu/omnirag` reste l'ancre de montage — ne pas supprimer

Le basculement du build vers `/srv/agentium-data/worktrees/demo-agentic` ne
retire **pas** le checkout live `/home/ubuntu/omnirag` (le `LIVE_REPO`
historique). Il remplit deux rôles que le worktree de build ne reprend pas :

- **Ancre de montage des données runtime.** Plusieurs bind mounts Docker
  pointent en dur sous ce chemin, indépendamment du worktree de build :
  `backend/faiss_db` (FAISS legacy sur `/dev/sda1`) et
  `backend/data/secure_deposit` (Secure Deposit SFTP sur `/dev/sdc`). Les
  recréer ailleurs casserait ces montages et déplacerait silencieusement les
  données hors de leur filesystem attendu (cf. « Données à préserver »).
- **Source du clone `--no-hardlinks`.** Les worktrees de release sont créés
  par `git clone --no-hardlinks /home/ubuntu/omnirag …` : le checkout live
  sert de référentiel objet local, et sa propreté (`git status` vierge) est
  une précondition vérifiée par le preflight identitaire.

Conséquence opérationnelle : on peut mettre à jour, fetcher ou rebaser
`/home/ubuntu/omnirag`, mais on ne le supprime ni ne le déplace tant que ces
bind mounts et ce rôle de source de clone n'ont pas été migrés de façon
explicite et revue.

Le chemin de déploiement est désormais versionné (il remplace les overlays
`/root/release-b-{images,restart,workers}.yml` et le script ad-hoc
`/root/release-b-deploy.sh`) :

- `scripts/agentium-vm-deploy.sh` — même forme d'invocation (env figé +
  overlay `opened` + overlay runtime), mais tags et workers passent par
  l'environnement : `AGENTIUM_IMAGE_TAG` (`<sha12>` ou `demo-agentic`,
  obligatoire, validé) et `AGENTIUM_BACKEND_WORKERS` (défaut 8).
  Sous-commandes `images`, `storage-check`, `migrate`, `up`, `ps` ; `up`
  reste `--no-build --no-deps` sur les cinq services applicatifs uniquement
  (backend, worker CPU, frontend, maintenance P4 et beat).
  `migrate` et `up` exécutent obligatoirement `storage-check` avant toute
  mutation. Le gateway Compose repart d'un environnement vide et ne propage
  que les contrôles applicatifs allowlistés ; `DOCKER_HOST`, `COMPOSE_*` et
  les variables de sélection de stockage héritées du shell sont ignorés. Tous
  les appels Docker sont en outre épinglés explicitement sur le socket local
  `unix:///var/run/docker.sock`, indépendamment du contexte Docker utilisateur.
- `docker/compose.agentium.vm-runtime.yml` — overlay unique portant ce que
  le compose de base ne paramètre pas : `restart: unless-stopped` sur les
  quatre services applicatifs, et épinglage par digest d'`agentium-sftp`
  (`sha256:22cd79c6…`) et `agentium-p4-maintenance` (`sha256:54d942c3…`),
  les deux services à ne jamais recréer. Il fixe aussi, sans interpolation,
  MinIO sur `agentium_minio_block`, Qdrant sur `agentium_qdrant_block` et les
  snapshots sur `/srv/agentium-data/qdrant-snapshots`.
- `docker/compose.agentium.local-storage.yml` — opt-in local/dev explicite
  vers `agentium_minio` et `qdrant_data`. Cet overlay est interdit sur VM ; le
  Compose de base échoue par défaut si les volumes block-backed n'existent pas.

Le gate `storage-check` est strictement non mutant. Il exige les quatre
valeurs canoniques dans le bundle figé, valide le rendu Compose en mémoire,
confirme que `/srv/agentium-data` est exactement le mountpoint `/dev/sdb`,
rejette les symlinks et mounts imbriqués sous les trois chemins protégés,
inspecte les options `local`/`bind` ainsi que les mountpoints `_data` actifs
des deux volumes externes, puis confirme que les conteneurs MinIO et Qdrant
actifs montent ces mêmes identités. Une valeur absente ou différente, un
volume manquant, un mauvais bind, un chemin ne résolvant pas directement sur
`/dev/sdb`, un `/dev/sdb` absent ou un conteneur stateful arrêté bloque
`migrate` et `up`.
Le gate ne lance ni `create`, ni `run`, ni `up` et ne recrée aucun service
stateful.

- `scripts/run-iteration-canaries.sh` — gate léger par itération, exécuté
  sur carakai en root : specs `11-system360-canary`,
  `12-protected-runner-canaries`, `16-experience-work-canary` et
  `17-experience-studio-canary` contre le SHA déployé, sans orchestrateur
  ni signature. Les identifiants sont lus depuis
  `/root/.attestation-username` / `/root/.attestation-password` (root-only)
  en mémoire, jamais écrits sur disque — corrige le `E2E_PASSWORD` en clair
  de `/tmp/rb-job/job.env`. Le script active explicitement les canaries
  Experience avec `E2E_EXPERIENCE_CANARY=1`; leurs prérequis manquants font
  échouer le gate au lieu d'être assimilés à une réussite. Le checkout
  Carakai doit être root-owned, propre, détaché sur le même SHA 40 caractères
  que `build-info`, et porter un `.agentium-source-sha` root-owned identique.
  Le symlink `frontend-ng/node_modules` doit viser le runtime gelé dont le
  `package-lock.json` a le digest attendu par l'orchestrateur. Pour ce candidat,
  ce runtime doit inclure `@axe-core/playwright`; un checkout ou un lock périmé
  échoue volontairement avant tout test.

Boucle d'itération cible :

1. commit sur `demo/agentic` ;
2. `git pull --ff-only` dans le worktree ;
3. rebuild des services touchés, tag `<sha12>` ;
4. `agentium-vm-deploy.sh storage-check` (facultatif comme affichage autonome,
   obligatoire et rejoué automatiquement par les étapes mutantes) ;
5. créer et vérifier le dump PostgreSQL pré-bascule ;
6. `AGENTIUM_IMAGE_TAG=<sha12> agentium-vm-deploy.sh migrate`, puis vérifier
   que `alembic current` rend exactement la tête attendue ;
7. `AGENTIUM_IMAGE_TAG=<sha12> agentium-vm-deploy.sh up` ;
8. mettre le checkout et les dépendances gelées Carakai sur ce SHA/lock exact,
   puis `run-iteration-canaries.sh <sha40>` (gate léger, non signé) ;
9. aux jalons seulement : attestation signée 7 tokens
   (`scripts/agentium_protected_runner_orchestrator.py`, voie carakai).

Rollback à toute itération : `AGENTIUM_IMAGE_TAG=<sha12 précédent>` puis
`up`. Les migrations `093`/`094` sont additives et restent en place lors d'un
rollback vers l'image précédente compatible ; ne pas exécuter de downgrade automatique.
Le dump vérifié reste le recours si une restauration de données est nécessaire.

## Dette technique résorbée (31/07) — déployée sur `b0ce840a` / `97e3f182`

Trois items du backlog post-B traités, chacun en petit commit sur
`demo/agentic`, poussé via bundle (accès Bitbucket local indisponible),
rebuildé au tip et déployé par la boucle d'itération :

- **N+1 `/api/v1/skills`** (`e943a22d`). `readable_runs` et
  `readable_skill_invocations_for_runs` ré-émettaient une requête
  `WorkspaceMember` et une requête `WorkspaceIAMConfig` par ligne, et
  `resolve_mode` re-validait le reçu de promotion contre `audit_logs` par
  ressource en mode `enforce`. Le membership, la config et le verdict de mode
  sont désormais préchargés une fois par lot. Mesuré en prod sur `andritz`
  (1333 runs / 4496 invocations) : agrégation ~19.7s → ~2.5s (~8×). Test de
  non-régression : le compte de SELECT reste constant quand le lot croît.
- **Alias racine SFTP** (`20f09784`). `_normalise_virtual_path` ne réduisait
  pas les segments `.`/`..`, donc `stat(".")` (envoyé par asyncssh en `/./`)
  n'était pas reconnu comme racine → `SFTPNoSuchFile` ; le canary d'acceptance
  devait faire `stat("/")` pour contourner. Résolution des segments contre la
  racine virtuelle (avec clamp de `..`), 52 tests. L'image `agentium-sftp` a
  été repinée du digest Release A `22cd79c6` vers le digest `b0ce840a`
  (`af7ef7a7`) et recréée ; l'acceptance SFTP end-to-end passe désormais sans
  contournement.
- **Ancre `/home/ubuntu/omnirag`** (`b0ce840a`). Rôle de montage documenté
  dans cette section.

L'attestation SFTP signée référence toujours l'ancien SHA (`ea80e656`) : à
régulariser au prochain jalon attesté, comme fait pour le backend. Gate
d'itération `run-iteration-canaries.sh` : 6/6 specs vertes sur `b0ce840a`.

## Flow Builder P0 (07/08) — déployé sur `9b0a116a`

Tranche Flow Builder P0 (cinq commits `73f94877`, `aab6b5a6`, `c09c49e9`,
`c055493c`, `9b0a116a`) atterrie sur `demo/agentic` puis déployée par la boucle
d'itération courte. Première itération de cette boucle qui embarque des
migrations : elle a donc été précédée d'un dump checksummé et d'une répétition
complète sur copie restaurée.

### Atterrissage

`origin/demo/agentic` avancée en fast-forward de `b0b8f452` vers
`9b0a116a25e46b9303d850a518cc992ab78359e4`, par bundle Git (accès Bitbucket
local toujours indisponible, même voie que le 31/07) : `git bundle create` local
borné `b0b8f452..`, `git bundle verify` des deux côtés, `git fetch` du bundle
dans `/home/ubuntu/omnirag`, puis push depuis la VM. Aucun `--force`. Le
checkout live et le worktree de build sont tous deux à ce SHA, porcelain vide.

### Images

Rebuild des trois seuls services applicatifs depuis
`/srv/agentium-data/worktrees/demo-agentic`, `AGENTIUM_IMAGE_REVISION` en 40-hex
complet, `PIP_INDEX_URL` explicite, `USER_UID/GID` 1000. Double tag habituel
`9b0a116a25e4` (immuable) + `demo-agentic` (mouvant) :

| Service | ID OCI |
|---|---|
| `agentium-backend` | `sha256:cbd828d527b0a7cfd2369397d21e669738907a67bdbaaafe038c661c33427fe6` |
| `agentium-worker` | `sha256:48a441d24cbbc1bb78172704b204ece908bbbc96e41c3f33bf562659b3f41a14` |
| `agentium-frontend` | `sha256:bf4fe6e76661aeb999bb27a599960c5da4491f1ad3024e8d47d09104237d0414` |

Le rebuild est obligatoire : la tranche ajoute la dépendance backend
`jsonschema` (4.26.0 résolue dans les images backend et worker). Les images
`b0ce840ab020` sont conservées intactes comme point de rollback.

### Dump avant migration

Triplet publié sur `/dev/sdb`, en `0600` sous un répertoire `0700` :

- `/srv/agentium-data/flow-p0-deployments/2026-08-07-9b0a116a25e4/postgres-pre-migration.dump`
- `sha256` `1c63327751f3ea2f5d7920600044edb3d056406a3d53180e5f79a9b9dc05269f`
- `bytes` `448212403`, 1178 entrées TOC, relu par `pg_restore --list`
- marqueur `.ready` au format documenté (`format`/`sha256`/`bytes` tabulés)

C'est le seul rollback réel de la base. Un retour d'image ou un downgrade
Alembic aveugle n'en est pas un.

### Répétition sur copie restaurée

Base jetable `agentium_flowp0_rehearsal` créée dans le conteneur `agentium-pg`
existant, restaurée avec `pg_restore --exit-on-error` (163 tables, Alembic 076),
puis `alembic upgrade head` avec l'image candidate pointée exclusivement sur
cette base. Elle atteint `080_trigger_event_claims`, l'effet de 078 est constaté,
puis la base est supprimée. La base live est restée à 076 pendant toute la
répétition.

### Effet réel de la migration 078

Sur les données de production, la migration **a bien muté** le graphe Andritz :
elle ne s'est pas abstenue. Le graphe live hachait exactement l'ancien contrat
épinglé (`6780628580346fb9…`), le seul workspace porteur du marqueur 059 étant
`andritz` (System `874211ee`, `system_type=chat_agentic`,
`flow_revision=056_andritz_chat_asset_binding`).

La mutation est minimale et identique en répétition et en production
(`flow_sha256` résultant `d17d9f8ba63682dd…` dans les deux cas) :

- une seule arête ajoutée, `decision.verdict --[strong]--> join.answer` ;
- 23 nœuds inchangés, 30 → 31 arêtes, aucune suppression ;
- contrat `6780628580346fb9…` → `55611adbfba88483…` ;
- `state.graph_changed=true`, `state.draft_upgraded=true` ;
- nouvelle version immuable #20 (`created_by=migration-078`,
  `release_kind=migration`), pointeur publié `2206fc61…` → `d433a466…`,
  l'ancienne version #19 restant intacte ;
- `systems.settings.flow_revision` et le marqueur de rollout workspace passent
  à `078_andritz_decision_contract` ;
- exactement 1 System sur 104 porte la clé d'état 078.

La 077 a par ailleurs backfillé 104 Drafts et 104 pointeurs publiés
(`system_versions` 138 → 226, dont 87 insertions 077 et 1 insertion 078). La
080 crée `trigger_event_claims`, vide.

### Vérifications

- `/api/v1/build-info` backend et frontend : `revision` = SHA 40-hex complet,
  `revision_verified: true` ;
- Alembic `080_trigger_event_claims` ;
- `storage-check` vert avant et après, en autonome et dans `migrate`/`up` ;
- seuls backend, worker et frontend recréés ; `agentium-sftp`
  (`eddce4dfca79`, `sha256:af7ef7a7…`) et `agentium-p4-maintenance`
  (`e60e2745b3a1`, `sha256:54d942c3…`) conservent conteneur, digest épinglé et
  `StartedAt` ; PostgreSQL, RabbitMQ, Qdrant, MinIO, Keycloak et LiveKit
  intouchés ;
- drapeau `flow_workbench_v1` absent de tous les workspaces : la tranche reste
  fermée en production, conformément au handoff ;
- `run-iteration-canaries.sh` : 6/6 vertes sur le SHA déployé.

Le premier passage des canaris a signalé un échec `cross_terms_absent` sur
Sentinel, non reproduit au second passage (6/6). Cause qualifiée et **antérieure
à cette tranche** : `vp-macro-indicators.component.ts` (inchangé ici, introduit
le 30/06) initialise ses signaux avec `SOVEREIGN_FALLBACK`, dont les libellés
portent `Octocity market cache` et `Meridian harbor cache`, et conserve ce repli
via `catchError`. Tant que l'agrégat macro n'a pas répondu — typiquement juste
après un redémarrage du backend — ces termes d'un autre tenant sont présents
dans le DOM de n'importe quel workspace. Les lignes
`workspace_macro_indicators` de `sentinel-ci` sont elles correctes. À traiter :
le repli ne doit pas porter de marque tenant.

### Dette relevée, non traitée dans cette fenêtre

`/api/v1/skills` sur `andritz` répond en ~9,6 s de façon stable (4 mesures),
contre ~0,1–0,3 s sur les autres workspaces et ~2,5 s documentés après
l'optimisation N+1 du 31/07, à volume quasi identique (1335 Runs / 4500
SkillInvocations contre 1333 / 4496). Le changement `run_access.py` de cette
tranche est écarté : `is_workbench_run` ne matche aucun Run existant
(`execution_surface` NULL sur les 1335) et `has_private_chat_admin_access`
court-circuite sur un principal admin. La cause reste à établir ; l'endpoint
répond correctement en HTTP 200.

### Rollback

- images : `AGENTIUM_IMAGE_TAG=b0ce840ab020` puis `up` (les trois images
  précédentes sont conservées) ;
- base : restaurer le triplet ci-dessus sous writers fermés. La base étant déjà
  en 080, un simple retour d'image laisserait un runtime `b0ce840a` sur un
  schéma 080 — dégradé, jamais un rollback.

Cette fenêtre a délibérément suivi la boucle d'itération courte, sans fermeture
d'ingress ni drainage des writers, là où la note de handoff recommandait la voie
orchestrée. Le dump et la répétition compensent le risque base ; le risque de
contention pendant le backfill 077 a été assumé.

## Correctifs jumelés (07/08, soir) — déployé sur `5c1f8838`

Deux correctifs indépendants batchés délibérément pour que les trois images
atterrissent sur un seul SHA : `b229b4a6` (frontend, déjà sur `origin`) retire
les libellés de repli marqués tenant de `vp-macro-indicators.component.ts` ;
`5c1f8838` (backend) corrige la latence de `/api/v1/skills` sur `andritz`.

Contrairement à la fenêtre Flow Builder P0, cette tranche ne porte **ni
migration ni changement de dépendance** : c'est un pur échange de trois images.
Les étapes dump et répétition du 07/08 n'ont donc pas lieu d'être, et le
rollback redevient intégral (voir plus bas).

### Atterrissage

`origin/demo/agentic` avancée en fast-forward de
`b229b4a6a844143e662dede33de2b7e0600f56a5` vers
`5c1f8838ac665706dfeecd79cc35ff63f55bb51a`, par bundle Git (accès Bitbucket
local toujours indisponible, même voie que les 31/07 et 07/08) : bundle borné
`b229b4a6..`, 4522 octets, `sha256`
`46e6dc39f8622da09f38b27029a603105f3c44fed6b89ea64fafc9962d961a61` identique
des deux côtés, `git bundle verify` local et sur la VM, `git fetch` du bundle
dans `/home/ubuntu/omnirag`, puis push depuis la VM. Un seul commit transféré,
descendance de `b229b4a6` vérifiée avant push. Aucun `--force`. Le checkout
live et le worktree de build sont tous deux à ce SHA, porcelain vide.

Avant d'avancer `/home/ubuntu/omnirag`, il a été vérifié que le delta
`9b0a116a..5c1f8838` ne touche aucun des fichiers montés en bind dans des
conteneurs vivants (`docker/livekit/agentium-livekit.yaml`,
`backend/keycloak/realm-export.json`, `backend/keycloak/themes/agentium`) : ces
montages exposent le checkout en direct, un `checkout` les réécrirait sous les
conteneurs en cours. Les ancres `backend/faiss_db` (`/dev/sda1`) et
`backend/data/secure_deposit` (`/dev/sdc`) sont restées en place.

### Images

Rebuild des trois seuls services applicatifs depuis
`/srv/agentium-data/worktrees/demo-agentic`, `AGENTIUM_IMAGE_REVISION` en 40-hex
complet, `PIP_INDEX_URL` explicite, `USER_UID/GID` 1000. Double tag habituel
`5c1f8838ac66` (immuable) + `demo-agentic` (mouvant) :

| Service | ID OCI |
|---|---|
| `agentium-backend` | `sha256:e77c1fc802b4ac7aa205e0c330d57fbaed0bb9b8119ba289cb5da708f77ba5cb` |
| `agentium-worker` | `sha256:84daf3d477e5bb9239c029e799db266d66b28dc2d5a42ae11eeac122b022d459` |
| `agentium-frontend` | `sha256:5e4c3525a238a6d37d0e374869326536d1647544a5a4a6a89bf1009063b1488a` |

Les trois portent le label `org.opencontainers.image.revision` en 40-hex
complet, et les deux tags pointent bien le même ID. Les images `9b0a116a25e4`
sont conservées intactes comme point de rollback. À noter : l'environnement
figé `compose.effective.env` porte `AGENTIUM_IMAGE_TAG=local` ; le tag doit
être passé par l'environnement du shell, qui l'emporte sur `--env-file`.

### Vérifications

- `/api/v1/build-info` backend et `build-info.json` frontend : `revision` =
  `5c1f8838ac665706dfeecd79cc35ff63f55bb51a`, `revision_verified: true` ;
- Alembic reste à `080_trigger_event_claims`, avant **et** après : aucune
  commande `migrate` n'a été exécutée dans cette fenêtre ;
- `storage-check` vert en autonome et rejoué dans `up` ;
- seuls backend, worker et frontend recréés ; `agentium-sftp`
  (`eddce4dfca79`, `sha256:af7ef7a7…`) et `agentium-p4-maintenance`
  (`e60e2745b3a1`, `sha256:54d942c3…`) conservent conteneur, digest épinglé et
  `StartedAt` (`2026-08-07T07:01:36Z` / `07:01:37Z`) ; PostgreSQL, RabbitMQ,
  Qdrant, MinIO, Keycloak et LiveKit intouchés (mêmes IDs et mêmes `StartedAt`
  relevés avant et après) ;
- drapeau `flow_workbench_v1` absent des 17 workspaces : la tranche Flow
  Builder reste fermée en production ;
- logs backend et worker sans `error`/`traceback` après recréation, worker
  Celery `ready` et reconnecté à RabbitMQ.

### Latence `/api/v1/skills` mesurée en production

Mesures depuis carakai contre `https://agentium.papai.ai`, même principal et
même méthode avant et après (4 appels avant, 5 après) :

| Workspace | Avant (`9b0a116a25e4`) | Après (`5c1f8838ac66`) |
|---|---|---|
| `andritz` | 10,03 – 10,86 s | 2,87 – 3,25 s |
| `agentium-showcase` (témoin) | 0,25 – 0,45 s | 0,14 – 0,17 s |
| `sentinel-ci` (témoin) | 0,18 – 0,31 s | 0,13 – 0,15 s |

Soit ~10,5 s → ~3,0 s sur `andritz` (~3,5×), sans régression sur les témoins,
qui s'améliorent eux aussi légèrement. Mesuré en direct sur la boucle locale
(`127.0.0.1:8001`, sans TLS ni nginx) : ~2,89 s — l'écart réseau n'est que de
~0,15 s. Le chiffre côté serveur est donc ~2,9 s, un peu au-dessus des 2,57 s
du banc pré-commit ; même ordre de grandeur, l'écart n'a pas été instruit.

Sortie **octet pour octet identique** avant/après sur les trois workspaces
(`sha256` des trois charges utiles inchangés, respectivement
`0340c1cd…`, `826666f1…`, `dc0da599…`) : l'optimisation ne change pas le
contrat de l'endpoint.

### Canaris

`run-iteration-canaries.sh` sur carakai en root contre le SHA déployé :
**6/6 vertes au premier passage**, pas de reprise.

Le checkout source revu du runner protégé est resté à `b0ce840a` (comme lors
du passage du 07/08). C'est délibéré et c'est ici une propriété utile :
l'assertion `cross_terms_absent` qu'il porte est la regex inline d'origine
(`/Octocity|\bOCTAVE\b|\bAsteria\b|\bMeridian\b/i`), écrite **avant** le
correctif. Le vert obtenu atteste donc du comportement du runtime, pas d'une
assertion réajustée.

### Dette `cross_terms_absent` (lignes 1161-1170) — résorbée

Le correctif `b229b4a6` supprime le repli marqué tenant. Preuve déterministe,
indépendante du caractère intermittent du canari : les libellés
`Octocity market cache` et `Meridian harbor cache` sont présents dans le bundle
de l'image `9b0a116a25e4` (`chunk-IUV35RMM.js`) et **totalement absents** du
bundle servi par l'image déployée. Les occurrences résiduelles d'`Octocity` et
de `Meridian` dans le nouveau bundle sont toutes gardées derrière
`isOctocityMode` : elles ne peuvent pas s'afficher dans le workspace d'un autre
tenant, y compris avant réponse de l'agrégat macro.

`b229b4a6` refactore par ailleurs l'assertion des canaris en
`findSentinelForbiddenPresentationTerms`, sémantiquement identique à la regex
inline précédente (mêmes quatre termes, même insensibilité à la casse, mêmes
limites de mots) ; elle renvoie en plus le terme fautif au lieu d'un booléen.
Cette liste partagée n'entrera en vigueur sur le runner qu'au prochain
rafraîchissement du checkout revu.

### Rollback

- images : `AGENTIUM_IMAGE_TAG=9b0a116a25e4` puis `up` (les trois images
  précédentes sont conservées) ;
- base : **rien à défaire**. Aucune migration, aucun changement de dépendance
  dans cette tranche ; la base reste en `080_trigger_event_claims` quel que
  soit le sens du basculement. Contrairement à la fenêtre du 07/08, où un
  retour d'image aurait laissé un runtime ancien sur un schéma 080, ce rollback
  est intégral et réellement réversible.

## Publication Flow par défaut (081/082) — ordre obligatoire, déployé le 10/08

> **Historique.** Cette section a été écrite avant exécution et décrivait alors
> la prochaine fenêtre. Elle a été jouée le 10/08 : voir *Fenêtre exécutée le
> 10/08* en fin de document pour les observables réels. La production sert
> `f8c0758bf938414f1be2da4874eb0fdda00edd2c` et la base est en
> `084_decision_condition_repair`. Ce qui suit reste utile pour le raisonnement
> — pourquoi l'ordre est contraignant, où sont les signatures d'échec — mais ses
> chiffres sont ceux d'une prévision, pas d'une mesure.

La tranche `714bac2c` fait de `flow_publication_v1` un **défaut de code** et non
plus un drapeau par workspace : `workspace_features.graduated_feature_enabled`
renvoie `True` en l'absence de la clé, et seul un `false` explicitement stocké
dans `settings.features` constitue un opt-out. Aucun workspace n'ayant jamais
porté cette clé, la bascule est **totale et simultanée sur les 17 workspaces**
au moment où les images candidates prennent le trafic.

Ce n'est pas un simple changement de posture : cela déplace l'autorité
d'exécution du miroir `systems.flow_definition` vers le pointeur immuable
`systems.published_flow_version_id`. Or 16 de ces pointeurs ne portent
aujourd'hui aucun contrat d'exécution (mesure du 08/08, voir « Périmètre réel »).

### Pourquoi l'ordre est contraignant

Un contrat d'exécution se compile depuis les Skills du workspace, qui sont des
données catalogue mutables. Alembic ne doit pas les atteindre : les trois
migrations qui ont écrit des baselines de publication posent donc
délibérément `execution_contract = NULL`.

| Migration | Écriture | `execution_contract` |
|---|---|---|
| `077_flow_publication_v1` | 104 pointeurs publiés, 104 Drafts, 87 versions insérées, 17 versions historiques réutilisées | `NULL` (insertions) ; colonne créée nullable, donc `NULL` aussi sur les réutilisées |
| `078_andritz_decision_contract` | 1 version insérée, pointeur Andritz redirigé | `NULL` |
| `081_flow_publication_baseline` | baselines des Systems créés après 077 par la voie legacy | `NULL` |

Côté runtime, `flow_publication.published_run_evidence` refuse d'exécuter une
version publiée sans contrat immuable valide et lève
`PUBLISHED_EXECUTION_CONTRACT_MISSING`. Elle ne recompile jamais à la volée :
ce serait faire dépendre un Run de lignes Skill mutables, exactement ce que le
pointeur immuable existe pour empêcher.

Le seul chemin supporté pour matérialiser un contrat est un Publish explicite,
qui appende une version portant le contrat figé même à graphe inchangé.
`backend/scripts/backfill_flow_publication_contracts.py` réalise ce Publish sur
tout le parc, par `flow_publication.publish_draft` — il n'écrit pas la colonne
en direct.

L'ordre est donc strictement : **`migrate` (081, 082) → backfill des contrats →
`up` (bascule des images)**.

Propriété utile : entre `migrate` et `up`, le trafic est encore servi par
`5c1f8838`, où `flow_publication_v1` est un drapeau opt-in absent partout. La
voie legacy reste donc active et il n'y a **pas de fenêtre d'indisponibilité**
entre la migration et le backfill. Cette fenêtre n'exige ni fermeture d'ingress
ni drainage des writers, à condition de respecter l'ordre ci-dessus.

Corollaire d'outillage : le backfill doit s'exécuter **depuis l'image
candidate**, en one-off, comme l'`alembic upgrade head` du 07/08. Lancé depuis
l'image live, `flow_publication_enabled` renvoie `False` partout et le script
saute les 17 workspaces en les déclarant hors périmètre.

### Périmètre réel — mesuré le 08/08 sur la base de production

Cette section affirmait un périmètre **exhaustif** (« le parc entier est
concerné », 104 Systems sur 104), par déduction des compteurs du 07/08. Les
requêtes ci-dessous ont été rejouées en lecture seule sur la base live : cette
déduction est fausse, le périmètre est borné.

| Mesure | Requête | Valeur |
|---|---|---|
| Systems au total | — | 104 |
| Inertes une fois le drapeau actif (sans pointeur, ou version publiée à `execution_contract` NULL) | 2 | **16** |
| Version publiée sans `flow_sha256` | 4 | **16** |
| Inertes **et** réparables par le backfill tel qu'écrit avant le 08/08 | — | **0** |
| Volume propre à la 081 | 3 | 0 |
| Dérive du miroir legacy | 5 | 0 |
| Opt-out explicite `flow_publication_v1` | 1 | 0 |

Les deux ensembles de 16 sont **le même ensemble**, vérifié par jointure. C'est
la signature exacte des baselines réutilisées par la 077 : elle a repris un
snapshot historique comme pointeur publié sans lui écrire de `flow_sha256`, donc
ces versions n'ont ni contrat ni empreinte. Les 88 autres Systems portent déjà
un contrat valide sur leur pointeur publié — par quel chemin, cette mesure ne
l'établit pas, et cela ne change rien à la conduite de la fenêtre. Ce constat
contredit l'arithmétique du 07/08 (87 insertions à contrat NULL) : ces chiffres
sont une vérité de mesure, pas un acquis, et se **re-mesurent juste avant le
GO**.

Les 16 ont tous un Draft présent. Répartition :

| Workspace | Systems | Nature |
|---|---|---|
| `agentium-showcase` | 7 | démo interne |
| `andritz` | 2 | client (Expert Knowledge Capture et sa variante) |
| `nawa` | 3 | client (Password Reset, Scratchpad flow, Shared mailbox creation) |
| `personal-253f4c1c` | 4 | débris e2e (`e2e-debug-*`, `e2e-hitl-*`) |

Les quatre Systems `personal-253f4c1c` sont des résidus de tests e2e : le
périmètre opérationnellement significatif est donc de **12 Systems**, dont 5
client-facing chez `andritz` et `nawa`. Ce n'est ni le parc entier, ni un risque
théorique.

La 081 ne touche que les Systems créés après la 077 par la voie legacy — ceux
dépourvus de pointeur **ou** de Draft. Elle passe explicitement les autres, et
son volume mesuré est **nul** : ce n'est pas elle qui crée le risque, c'est la
bascule du drapeau.

Les requêtes se rejouent en lecture seule juste avant le GO, sur la base live :

```sql
-- 1. Opt-out explicites. Attendu : aucune ligne avec une valeur non nulle.
SELECT id, slug, settings->'features'->>'flow_publication_v1' AS opt_out
FROM workspaces WHERE deleted_at IS NULL ORDER BY slug;

-- 2. Périmètre : Systems inexécutables une fois le drapeau actif.
SELECT w.slug, count(*) AS systems
FROM systems s
JOIN workspaces w ON w.id = s.workspace_id
LEFT JOIN system_versions v ON v.id = s.published_flow_version_id
WHERE s.published_flow_version_id IS NULL OR v.execution_contract IS NULL
GROUP BY w.slug ORDER BY 2 DESC;

-- 3. Volume propre à la 081 (Systems sans pointeur ou sans Draft).
SELECT count(*) FROM systems s
LEFT JOIN system_flow_drafts d ON d.system_id = s.id
WHERE s.published_flow_version_id IS NULL OR d.system_id IS NULL;

-- 4. Baselines 077 réutilisées, sans `flow_sha256`. Mesuré : 16.
SELECT count(*) FROM systems s
JOIN system_versions v ON v.id = s.published_flow_version_id
WHERE v.flow_sha256 IS NULL;

-- 5. Dérive du miroir legacy depuis la 077/078 (indicatif, égalité jsonb).
SELECT count(*) FROM systems s
JOIN system_versions v ON v.id = s.published_flow_version_id
WHERE s.flow_definition::jsonb IS DISTINCT FROM v.flow_definition::jsonb;

-- 6. Les périmètres 2 et 4 doivent coïncider (attendu, et mesuré : 0).
SELECT count(*) FROM systems s
LEFT JOIN system_versions v ON v.id = s.published_flow_version_id
WHERE (s.published_flow_version_id IS NULL OR v.execution_contract IS NULL)
      IS DISTINCT FROM (v.flow_sha256 IS NULL);
```

La requête 2 donne le nombre de Systems qui basculeraient en échec si `up`
précédait le backfill. La requête 4 était présentée ici comme un angle mort du
script ; depuis le correctif décrit plus bas, elle mesure au contraire le cœur du
périmètre **réparable**. La 5 dénombre la seule catégorie que le script ne répare
pas, et elle est à 0 aujourd'hui. La 5 est indicative : l'égalité `jsonb`
normalise les nombres là où le hachage canonique conserve leur représentation ;
le dry-run reste l'autorité. La 6 est le contrôle qui a permis d'établir que les
16 inertes et les 16 sans empreinte sont le même ensemble ; si elle cesse d'être
nulle, les deux catégories ont divergé et le périmètre doit être requalifié avant
le GO.

### Jeu de migrations en attente

| Révision | Objet | Nature |
|---|---|---|
| `081_flow_publication_baseline` | baselines de publication manquantes | data-only, idempotente, ne touche jamais `systems.flow_definition` |
| `082_skill_category` | colonne `category` du catalogue Skill + backfill figé | expand + data |

`083` est **déjà pris** par le travail en cours sur le CRUD Skill scopé
workspace : ne pas réattribuer ce numéro à un correctif de cette fenêtre.

Un identifiant de révision ne peut pas dépasser **32 caractères** :
`alembic_version.version_num` est un `character varying(32)` et Alembic n'expose
aucune option pour l'élargir. Au-delà, l'`UPDATE` du tampon échoue en
`StringDataRightTruncation` après que la migration a déjà écrit ses données. Le
nom de fichier peut rester long et descriptif, seul l'identifiant est contraint.

### Séquence

Les étapes 1 à 3 reprennent la fenêtre du 07/08 : cette tranche embarque des
migrations, donc dump checksummé et répétition sur copie restaurée sont
obligatoires.

```bash
CANDIDATE_TAG='<sha12-candidat>'
DEPLOY='/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh'
REPORTS='/srv/agentium-data/flow-publication-deployments/<date>-<sha12>'

# 1. Rebuild des trois services applicatifs, double tag <sha12> + demo-agentic.
# 2. Triplet dump/checksum/.ready sur /dev/sdb, puis répétition
#    `alembic upgrade head` sur base jetable restaurée (doit atteindre 082).
# 3. Gate stockage.
AGENTIUM_IMAGE_TAG="$CANDIDATE_TAG" "$DEPLOY" storage-check

# 4. Migrations 081 puis 082. Les images applicatives restent en 5c1f8838 :
#    le trafic continue de passer par la voie legacy.
AGENTIUM_IMAGE_TAG="$CANDIDATE_TAG" "$DEPLOY" migrate

# 5. Backfill des contrats, one-off sur l'IMAGE CANDIDATE contre la base live.
#    Dry-run par défaut : aucune écriture, la session est rollbackée.
#    `--report` écrit dans le conteneur : monter "$REPORTS" en bind.
python -m scripts.backfill_flow_publication_contracts \
  --report /report/contracts-dry-run.json

# 6. Après relecture du rapport uniquement.
python -m scripts.backfill_flow_publication_contracts --apply \
  --actor 'system:flow-contract-backfill' \
  --report /report/contracts-apply.json

# 7. Bascule des images, puis canaris.
AGENTIUM_IMAGE_TAG="$CANDIDATE_TAG" "$DEPLOY" up
/srv/agentium-data/worktrees/demo-agentic/scripts/run-iteration-canaries.sh
```

Contrôles entre étapes :

- **après 4** : révision Alembic à `082_skill_category` ; requête 2 ci-dessus
  rejouée — elle doit être stable ou avoir augmenté du seul volume de la 081 ;
  backend live toujours en `5c1f8838` et trafic nominal (la 081 est invisible
  du code legacy) ;
- **après 5** : code de sortie **0** exigé — le dry-run sort en 1 si le plan
  contient déjà un `apply_risk` (`summary.at_risk`), justement pour qu'un plan
  entièrement vert ne se lise pas comme une garantie. Lire la partition de
  `summary.publish` : `publish_initial` sont les versions sans contrat,
  `publish_republication` celles dont le contrat gelé n'est plus celui que
  produit le compilateur courant — c'est le volume qu'une passe précédente
  déclarait `already_pinned`, et il doit être attendu, pas découvert ici.
  `summary.already_pinned` couvre le reste du parc ; y relire les
  `contract_freshness: unverified`. Lire les `skipped` un par un. Un `reason`
  valant `no published pointer` ou `no server draft` signifie que la 081 n'a pas
  été appliquée : **ne pas continuer**. Un `draft differs from the published
  version` désigne maintenant un Draft réellement édité, jamais une baseline 077
  réutilisée. Lire enfin `report["limits"]` : il énumère ce que ce plan n'a pas
  pu vérifier ;
- **après 6** : code de sortie **0** exigé — le script sort en 1 dès un seul
  `failed`, y compris un `not_repaired` (Publish accepté mais version toujours
  inexécutable). `summary.published + summary.skipped + summary.already_pinned`
  doit égaler `summary.systems`, et les requêtes 2 **et** 4 doivent être
  retombées au nombre de `skipped`. Chaque publication est committée
  individuellement : une reprise se fait en relançant simplement le script, les
  Systems déjà traités ressortant en `already_pinned` ;
- **après 7** : `/api/v1/build-info` sur le SHA complet avec
  `revision_verified: true`, canaris 6/6, puis surveillance des Runs rejetés
  (voir signature ci-dessous) pendant 60 minutes.

Ne jamais exécuter l'étape 7 avant que l'étape 6 soit sortie en 0. C'est le
seul invariant réellement contraignant de cette fenêtre.

### Signature d'échec si l'ordre est violé

Si `up` précède le backfill, la bascule est immédiate et silencieuse côté
image : les conteneurs démarrent sainement, `build-info` est vert, les canaris
d'infrastructure passent. La panne n'apparaît qu'au premier Run.

`published_run_evidence` lève `PUBLISHED_EXECUTION_CONTRACT_MISSING` — « The
published version has no valid immutable execution contract; publish the server
draft before running it » — sur **toutes** les surfaces de dispatch, chacune la
présentant différemment :

| Surface | Chemin | Présentation |
|---|---|---|
| Scheduler | `run_engine/scheduler.py` | Run non créé, `FlowIngressError` journalisée |
| Triggers | `run_engine/triggers.py` | verdict `rejected`, `reason: published_execution_contract_missing`, avant même la gouvernance |
| Chat Agentic | `chat_agentic_runtime.py` | échec de dispatch sur la voie ingress publiée |
| Exécution manuelle | `POST` System / `flow_runner` | erreur HTTP 409, code `PUBLISHED_EXECUTION_CONTRACT_MISSING` |
| Ingress publiés | `api/v1/endpoints/flow_ingresses.py` | idem 409 |
| Subflows | `run_engine/dag.py` | Run enfant refusé, Run parent en erreur |

Deux traits rendent le diagnostic trompeur : le scheduler et les triggers
**ne remontent pas d'erreur HTTP**, ils refusent proprement, ce qui produit une
disparition d'exécutions plutôt qu'un pic de 5xx ; et le test de Draft
(`create_draft_test_run`) continue de fonctionner, puisqu'il compile son
contrat à la volée sans passer par le pointeur publié. Un opérateur peut donc
vérifier un Flow avec succès dans l'éditeur pendant que toutes ses exécutions
publiées sont refusées, et conclure à tort que le moteur va bien.

Deux codes voisins peuvent apparaître et **ne se traitent pas de la même
façon** : `PUBLISHED_FLOW_VERSION_HASH_MISSING` (version publiée sans
`flow_sha256` exact) et `PUBLISHED_FLOW_MIRROR_DRIFT`
(`systems.flow_definition` ne reflète plus sa version publiée). Le backfill
répare le premier quand le contrat manque aussi — c'est le cas des 16 Systems du
périmètre, dont le Publish écrit à la fois le contrat et l'empreinte. Il ne
répare ni le second, ni une empreinte absente sous un contrat déjà valide, cas
auquel Publish répond par un no-op.

### Reprise après violation de l'ordre

Aucune restauration de base n'est nécessaire et aucune n'est souhaitable : la
donnée n'est pas corrompue, il lui manque un contrat.

1. Rejouer immédiatement l'étape 6 depuis l'image candidate — désormais celle
   qui tourne — en `--apply`. C'est la reprise nominale ; elle est idempotente
   et rétablit le service au fur et à mesure des commits, System par System.
2. Si le backfill ne peut pas être lancé tout de suite et que l'indisponibilité
   n'est pas tenable, revenir aux images précédentes :
   `AGENTIUM_IMAGE_TAG=5c1f8838ac66` puis `up`. La base reste en 082, ce qui est
   un runtime dégradé et non un rollback — mais `5c1f8838` ignore les colonnes
   ajoutées et retrouve la voie legacy, donc le trafic repart. Relancer ensuite
   la séquence dans l'ordre.
3. Ne **pas** contourner en posant `flow_publication_v1: false` sur les
   workspaces. C'est l'opt-out documenté, mais il restaure la posture
   destructive où une écriture d'éditeur atterrit directement sur le graphe
   exécutable live, et il faudra de toute façon le retirer.
4. Ne **pas** tenter un `alembic downgrade`. La 077 refuse déjà de descendre en
   présence de données produit, et la 081 ne supprime que les lignes qu'elle a
   elle-même écrites : un downgrade n'enlève pas les contrats manquants, il
   enlève les baselines.

### Classement du backfill — un défaut corrigé, une catégorie toujours non réparée

Le script est conservateur par conception : il ne promeut jamais un Draft qui a
divergé de sa version publiée, parce que publier du travail d'éditeur non revu
est exactement ce que la séparation Draft/Publish existe pour empêcher. Cette
prudence était correcte ; sa mise en œuvre ne l'était pas.

**Baselines 077 réutilisées — le défaut, corrigé.** Quand la 077 a trouvé un
snapshot historique exactement égal au miroir legacy, elle a réutilisé cette
ligne comme pointeur publié **sans lui écrire de `flow_sha256`** — la colonne
venait d'être créée. Le Draft, lui, a bien reçu le digest. Le script comparait
`draft.flow_sha256` à `version.flow_sha256` : `<digest>` contre `NULL`, donc
« différent », donc `skipped` avec le motif `draft differs from the published
version; publish it by hand`. Or une empreinte absente signifie *inconnue*, pas
*différente* : le Draft était identique. **Les 16 Systems du périmètre mesuré
sont exactement ceux-là**, et le script tel qu'écrit n'en réparait aucun. Un
dry-run vert aurait été rapporté alors que rien n'aurait été corrigé.

Le classement compare désormais le digest du Draft à l'empreinte **recalculée
depuis le JSON immuable de la version publiée**, jamais à la colonne nullable.
C'est la même autorité que le runtime : `published_run_evidence` refuse déjà une
version dont `flow_sha256` ne vaut pas le hachage canonique de son payload. La
protection est intacte — un Draft réellement en avance donne un digest différent
de l'empreinte recalculée et reste `skipped` — et les 16 basculent en `publish`.
Le service n'a pas été modifié : il avait raison, c'est le script qui lisait le
mauvais côté de l'égalité. Tests dans
`backend/app/tests/services/test_backfill_flow_publication_contracts.py`.

Deux cas voisins sont désormais classés explicitement plutôt que confondus avec
un Draft édité : une empreinte stockée qui **contredit** son propre payload
(`flow_sha256_drift`) est `skipped`, parce que `publish_draft` refuse cette
version et qu'aucun Publish ne peut la réparer ; une empreinte absente sous un
contrat déjà valide reçoit un `apply_risk`, parce que Publish y répondrait par un
no-op qui laisserait l'empreinte manquante en place. Aucun des deux n'existe en
production au 08/08.

**Contrat gelé mais périmé — le même défaut une troisième fois, corrigé le
09/08.** Le classement reposait encore sur une présence : une colonne
`execution_contract` non nulle et structurellement valide valait `already_pinned`.
Or le contrat vacant du témoin du 08/08 (`{"nodes": {}, "outputs": [],
"ingresses": []}`) satisfait les deux barrières runtime et refuse pourtant les
cinq adaptateurs. Le gel étant le principe même de la publication, le
compilateur corrigé n'atteint jamais ces lignes : « basculer l'image » ne suffit
pas, il faut une **re-publication**.

Le classement recompile donc le payload publié avec le compilateur courant et
compare le `contract_sha256` obtenu à celui gelé. C'est exactement le test que
`publish_draft` applique déjà pour décider s'il est un no-op, ce qui rend la
passe idempotente par construction : une seconde exécution recompile le même
digest et ne publie rien. Nouveau défaut `execution_contract_stale`, nouveau
champ `publication_kind` par System (`initial` / `republication`) et deux
compteurs qui partitionnent `publish` : `summary.publish_initial` et
`summary.publish_republication`. Un opérateur doit voir que cette passe touche
des lignes que la précédente déclarait saines.

Conséquence sur le dry-run : il **compile** désormais, donc il n'est plus aveugle
aux échecs de compilation — ils ressortent en `apply_risk` portant le code exact
du compilateur. Un System dont le contrat ne recompile pas reste `already_pinned`
mais porte `contract_freshness: unverified` : sa péremption est inconnue, pas
absente. Ce que le dry-run ne voit toujours pas, c'est un diagnostic DAG bloquant
(`publish_draft` valide le graphe avant de compiler) ; `report["limits"]` le dit.

Mesuré le 09/08 sur `agentium_reh_108bbfce`, contrats d'avant correctif restaurés
depuis `estate-and-contracts-BEFORE-fix.json` (état identique, deux scripts) :

| Script | `already_pinned` | `publish` | dont `republication` | `at_risk` | sortie |
|---|---|---|---|---|---|
| avant (`61eab738`) | 49 | 40 | — | 0 | 0 |
| après | 10 | 79 | **39** | 3 | 1 |

`--apply` publie les 39 ; la seconde exécution consécutive rapporte
`publish_republication: 0`, `published: 0`, et `system_versions` reste à 314
lignes. Les 40 `initial` échouent comme avant (conditions Decision invalides) :
c'est le défaut voisin, non traité ici. Les 3 `at_risk` sont
`SKILL_NOT_BOUND_TO_SYSTEM`, `ADAPTIVE_POLICY_SCOPE_MISMATCH` et
`FLOW_OUTPUT_SINK_REQUIRED` — trois refus d'`--apply` que l'ancien dry-run ne
pouvait pas annoncer.

**Miroir legacy en avance — toujours non réparé.** Tout System dont le graphe a
été édité par la voie legacy depuis la 077/078 a un `systems.flow_definition` en
avance sur sa version publiée. `publish_draft` lève
`PUBLISHED_FLOW_MIRROR_DRIFT` à l'application, compte `failed` et fait sortir le
script en 1. C'est le bon comportement : publier le Draft 077 y reviendrait à
annuler l'édition. Le dry-run classait ces Systems `publish` sans réserve ; il
émet maintenant un `apply_risk` porteur du code exact, compté dans
`summary.at_risk`, et sort en 1. La requête 5 les pré-dénombre — **0 en
production au 08/08**, donc ce chemin n'est pas exercé dans cette fenêtre. Ces
Systems se traitent un par un, en connaissance du graphe attendu.

Conséquence pratique inchangée : **le dry-run est un plan, pas une garantie**. Il
ne compile aucun contrat et n'appelle jamais `publish_draft`, donc il ne peut pas
prédire un échec de compilation (Skill retirée du catalogue, binding catalogue
invalide, diagnostic DAG bloquant), et il décrit l'état de la base à l'instant de
la lecture. Un dry-run entièrement en `publish` n'exclut pas un `--apply`
partiellement `failed`. Le rapport porte désormais ces limites dans
`report["limits"]` au lieu de les laisser implicites, et `--apply` vérifie après
chaque Publish que la version pointée est réellement exécutable : un Publish
accepté qui laisse le System inerte ressort en `not_repaired` et compte `failed`.

Le script a maintenant des tests automatisés, ce qui n'était pas le cas quand ce
runbook a été écrit. Cela ne dispense pas d'une **lecture humaine des deux
rapports** : les compteurs prouvent le classement, pas la pertinence métier de
publier ces 16 Systems dans cette fenêtre.

**Ce qui reste non vérifié.** Le correctif a été validé par tests sur les formes
de lignes exactes relevées en production, et depuis le 09/08 sur la copie de
répétition, jamais contre la base de production : personne n'a encore exécuté le
dry-run depuis l'image candidate contre la base live. Restent donc à constater
dans la fenêtre, avant tout `--apply` : la partition exacte de `summary.publish`
entre `publish_initial` et `publish_republication` ; les `apply_risk` qui
apparaissent ; et que la compilation de contrat aboutit, ce qu'aucun test hors
production ne peut établir puisque le contrat se compile depuis le catalogue
Skill live. L'étape 5 est le premier moment où ces trois points deviennent
observables sur les lignes réelles.

Deux réserves sur les mesures SQL elles-mêmes, qui peuvent faire dépasser 16 :
la requête 2 ne voit pas une empreinte stockée **non nulle** qui contredirait son
propre payload, alors que le runtime refuse cette version
(`PUBLISHED_FLOW_VERSION_HASH_MISSING`) ; et la requête 5 compare en `jsonb`, ce
qui normalise les nombres là où le hachage canonique conserve leur
représentation. Le dry-run recalcule le hachage canonique des deux côtés, donc
lui seul dénombre l'ensemble inerte réel et la dérive réelle. S'il rapporte plus
de 16 `publish`, c'est la mesure SQL qui était optimiste, pas le script qui
s'emballe.

### Le backfill est bloqué par les conditions Decision, pas par le compilateur

Mesuré le 09/08 sur `agentium_reh_108bbfce`, 89 Systems dans la cohorte. Après
avoir remis les 39 contrats publiés dans leur forme pré-correctif :

| | ancien script | script corrigé |
|---|---|---|
| `already_pinned` | 49 | 10 |
| `publish` | 40 | 79 |
| dont `publish_initial` | — | 40 |
| dont `publish_republication` | — | **39** |
| `at_risk` | 0 | **3** |

Les 39 contrats vides que l'ancien script déclarait `already_pinned` sont bien
republiés, et un second `--apply` consécutif retombe à `already_pinned: 49`,
`publish_republication: 0`, `published: 0` — idempotent.

**Mais 40 des 89 Systems ne se publient pas du tout**, et cela n'a rien à voir
avec le correctif d'ingress ni avec le classement : ce sont les 40
`publish_initial`, qui échouent identiquement sous l'ancien script. La
répartition des diagnostics bloquants, relevée sur la copie de répétition :

| Diagnostic | Systems |
|---|---|
| `decision_condition_invalid` | 36 |
| `decision_branch_unwired` | 2 |
| `flow_output_sink_required` | 1 |
| `ADAPTIVE_POLICY_SCOPE_MISMATCH` (au compile, pas au validate) | 1 |

`decision_condition_invalid` est exactement le défaut que la migration
`084_decision_condition_repair` répare — de la prose laissée par les seeds dans
les conditions stockées. **La fenêtre de déploiement ne peut donc pas se
terminer sur le seul correctif d'ingress : sans `084`, 36 Systems restent
non publiables et donc non dispatchables.** Les trois autres sont des défauts
d'auteur réels, pas de dialecte : `Contract Risk Copilot` n'a aucun nœud puits
(ses nœuds sont tous `task`, il ne s'agit pas d'un `type: "sink"` mal lu), et
`Shared mailbox creation` déclare `config.skill_slug` correctement mais son
`system.skill_ids` est **vide** — le compilateur lit le binding, c'est le
System qui ne possède pas la Skill.

Les 3 `at_risk` du dry-run corrigé ont prédit exactement trois de ces échecs,
avec le même code qu'à l'`--apply` : le dry-run compile désormais le contrat,
là où l'ancien annonçait `at_risk: 0` et laissait l'opérateur les découvrir en
cours d'écriture.

### Un Run accepté aboutit — mesuré le 09/08, pas déduit

Le correctif d'ingress du 08/08 faisait *accepter* un Run par 45 Systems ; que
ce Run *aboutisse* restait le risque ouvert, parce que les graphes legacy le
sont bien au-delà de leur entrée : ils écrivent `skill_slug` à plat au lieu du
binding imbriqué, et orthographient les puits `type: "sink"`, non reconnu comme
sortie. `backend/scripts/rehearse_published_ingress_run.py` crée un vrai Run par
`flow_ingress.create_published_ingress_run` puis l'exécute par
`run_engine.schedule_run` — les deux appels exacts que fait la surface de
dispatch manuel — et rapporte le statut terminal, les invocations et tous les
checkpoints. Il exécute les Skills pour de bon : copie de répétition uniquement.

Quatre Runs sur `agentium_reh_108bbfce`, depuis l'image candidate :

| System | Mode | Ingress | Statut terminal |
|---|---|---|---|
| `News Lab` (`smoke-dfbfc7`) | `sequential_legacy` | `manual` | **completed** |
| `Evidence Graph` (`sentinel-ci`) | `sequential_legacy` | `manual` | **completed** |
| `Password Reset` (`nawa`) | `dag_overlay` | `manual` | **completed** |
| `Andritz Chat Agentic` (`andritz`) | `dag_overlay` | `chat` | **completed** |

Le dialecte ne mord pas une seconde fois, et la raison est structurelle.
`resolve_flow_execution` n'envoie un Flow au marcheur DAG que si
`schema_version >= 2` **et** qu'au moins un nœud porte un `kind` de contrôle ;
un `type: "source"` sans `kind` ne compte pas. Un graphe purement legacy tombe
donc toujours sur le marcheur **séquentiel**, qui exécute `system.skill_ids` et
ne lit pas le graphe. Rejoué avec cette règle exacte sur les 99 graphes non
vides des 104 Systems de l'export d'évidence : 56 en marcheur DAG, 43 en
séquentiel, et **zéro intersection** entre les deux — les 42 graphes à
`type: "sink"` legacy, les 42 à `type: "source"` legacy et les 20 à
`skill_slug` à plat sont tous séquentiels. La tolérance étroite de
`flow_node_kind` n'a donc pas à être élargie, et l'élargir aux puits changerait
les contrats gelés de ces 42 Systems sans qu'aucun marcheur les lise.

Ce que cela coûte, en revanche, doit être dit : pour ces graphes le contrat
compile `nodes: {}` et `outputs: []`, et `run_contracts.validate_node_output` /
`validate_sink_output` retournent `None` quand le nœud est absent du contrat. La
publication n'y ajoute donc **aucune** validation d'exécution au-delà du payload
d'ingress — le Run est identique à ce que produit la voie legacy. Le bénéfice de
la publication pour ces Systems est la barrière d'ingress, pas le contrat.

Deux réserves honnêtes sur ces mesures :

- le `chat` a échoué deux fois avant d'aboutir, sur
  `membrane_valve_breach:max_latency_ms` (valve à 45 000 ms, `semantic_search_v1`
  à 27–35 s). Ce n'est pas une régression de la publication : l'historique du
  même System dans la copie de répétition compte **253 `completed` et 90
  `failed`, dont 90 sur exactement ce code**. Un Run de chat sur quatre franchit
  déjà cette valve aujourd'hui ;
- `News Lab` et `Evidence Graph` n'ont **aucun Run historique** : ce sont des
  Systems de démonstration semés. Les « 44 ingress manuels » gagnés par le
  correctif sont donc en majorité du contenu de démonstration, pas du trafic.
  Sur `Evidence Graph`, trois invocations sur quatre échouent en interne
  (`'query'` absent, `audit_log_v1 requires an event_type`) sans faire échouer le
  Run : c'est le comportement du marcheur séquentiel, antérieur et indépendant
  de la publication, mais un `completed` de ce System ne prouve rien de plus que
  la traversée.

Le harnais a tourné avec `docker/env/agentium.env`, qui porte la clé Qdrant en
lecture seule et non celle du conteneur backend : les écritures Qdrant du
Skill d'ingestion de `News Lab` sont sorties en `403 Forbidden`. Volontaire — un
Run de répétition ne doit pas écrire dans le Qdrant de production — mais cela
borne la mesure : elle prouve la traversée et le statut terminal, pas la qualité
des effets de bord.

### Régression opérateur — deux scripts fermés par conception

Deux scripts opérateur refusent d'écrire tant que `flow_publication_v1` est
actif. C'était une garde correcte sous drapeau opt-in ; sous défaut de code
elle devient un refus permanent. Leur portage était hors périmètre de la
tranche `714bac2c`.

| Script | Garde | Portée du refus |
|---|---|---|
| `scripts/rollout_system360_canary.py` | `discover_target` / `_discover_bootstrap_candidate`, sous `lock=True` | l'unique workspace marqué `settings.showcase_seed`, et **uniquement en `--apply`** |
| `scripts/backfill_flow_v3_variables.py` | `require_legacy_flow_authority`, appelée par workspace | tout workspace de la cohorte, et **uniquement en `--apply`** |

Précisions qui changent le diagnostic en incident :

- les deux scripts restent **pleinement utilisables en dry-run**, et
  `rollout_system360_canary status` reste opérationnel : seules les mutations
  sont fermées ;
- la fermeture de `rollout_system360_canary` ne vise pas « tous les
  workspaces » : la découverte ne retient qu'un seul workspace, celui portant
  le marqueur showcase. Le rollout canari Lot 6 est donc inexécutable en
  écriture, mais l'impact est borné à ce workspace ;
- `version_service.rollback_to_version` porte la même garde et lève
  `ChainVersionError` : tout appelant legacy de rollback de version est
  concerné, y compris la sous-commande `rollback` du canari.

**Il n'existe aucune option CLI d'opt-out.** Ni `--force`, ni `--allow-…`. Le
seul contournement est de stocker `settings.features.flow_publication_v1 =
false` sur le workspace visé, de dérouler l'opération legacy, puis de retirer la
clé — en acceptant que, pendant ce laps, une écriture d'éditeur atterrisse
directement sur le graphe exécutable live de ce workspace. Une telle
dérogation doit être tracée, bornée dans le temps et refermée dans la même
fenêtre.

Ne pas découvrir ce point pendant un incident : si le rollout Lot 6 doit
avancer après cette fenêtre, la décision entre porter les scripts sur la voie
Publish et poser un opt-out temporaire se prend **avant** le GO.

## Bascule `flow_publication_v1` — procédure exécutable, mesurée en combiné le 09/08

Cette section remplace la *Séquence* de la section « Publication Flow par défaut
(081/082) » pour tout ce qui concerne l'ordre, les points de contrôle et le
retour arrière. Elle est écrite depuis une répétition complète, en une seule
passe, sur une copie fraîche du dump de production — la mesure combinée qui
manquait. Chaque nombre ci-dessous a été observé, aucun n'est déduit.

Répétition de référence : base jetable `agentium_reh_f8c0758b`, restaurée depuis
`…/2026-08-08-108bbfcea7b5/postgres-pre-migration.dump` (sha256 vérifié,
révision de départ `080_trigger_event_claims`), image candidate
`agentium-backend:f8c0758bf938`. Rapports sous
`/srv/agentium-data/candidate-out/taskc/reports/`.

### Accès à la VM — ce que ce document ne disait pas

Ce runbook nomme `carakai` une dizaine de fois sans jamais dire que **ce n'est
pas la VM applicative**. `carakai` (`79.137.18.231`) est l'hôte du runner
protégé et des canaris ; il ne porte ni `/srv/agentium-data`, ni checkout
omnirag. Deux agents y ont cherché la base.

| Rôle | Hôte SSH | Adresse |
|---|---|---|
| VM applicative Agentium (PostgreSQL, images, worktrees, `/srv/agentium-data`) | `omnirag-demo` | `217.182.104.99` = `agentium.papai.ai` |
| Runner protégé, canaris d'itération, attestations | `carakai` | `79.137.18.231` |

Tout ce qui suit s'exécute sur `omnirag-demo`, en `sudo` : les worktrees et le
répertoire de déploiement appartiennent à `root`.

### Périmètre réel de la fenêtre, mesuré en combiné

Cohorte : 89 Systems, dans les 17 workspaces non supprimés (les 15 Systems
restants sur 104 vivent dans deux workspaces en suppression douce).

| Observable | Valeur mesurée |
|---|---|
| `alembic upgrade head` depuis `080` | atteint `084_decision_condition_repair`, **tête unique**, sortie 0 |
| Lignes réparées par `084` | 130 (41 `systems`, 41 `system_flow_drafts`, 48 `system_versions`), 41 Systems distincts |
| Dry run du backfill | `publish 89` (tous `initial`), `already_pinned 0`, `at_risk 3`, sortie **1** — voir le décalage post-remédiation ci-dessous |
| `--apply` | **`published 85`, `failed 4`**, sortie **1** — voir le décalage post-remédiation ci-dessous |
| `--apply` consécutif | `already_pinned 85`, `published 0`, `publish_republication 0` — **idempotent** |
| Systems dispatchables après backfill | 77 / 89 |
| Refus restants | `FLOW_INGRESS_SYSTEM_INACTIVE` 8, `PUBLISHED_EXECUTION_CONTRACT_MISSING` 4 |
| Accepteraient un Run, par adaptateur | `manual 59`, `chat 16`, `event 1` |
| Contrats publiés mais sans ingress | 2 dispatchables (4 tous statuts confondus) |

**`chat: 20` et `chat: 16` sont tous les deux vrais et ne disent pas la même
chose.** 20 contrats publiés *contiennent* un ingress `chat` ; 16 seulement
*accepteraient un Run*. Les 4 manquants sont des Systems `retired`, que
`assert_dispatchable` refuse en `FLOW_INGRESS_SYSTEM_INACTIVE`. Le chiffre à
présenter à une fenêtre est **16** : c'est celui qui décrit du trafic possible.
Compter les ingress compilés est exactement l'erreur de mesure que ce dossier
enregistre depuis trois nuits — la présence d'une valeur pour la réalité qu'elle
représente.

Les 4 échecs de publication sont les défauts d'auteur déjà inventoriés
(`Tender Response Analyst`, `Contract Risk Copilot`, `Shared mailbox creation`,
`Translation Suite`). Ils ne sont pas mécaniques et ne se réparent pas dans une
fenêtre de déploiement.

### Décalage post-remédiation — les chiffres attendus ont bougé de un

La fenêtre du 10/08 s'est arrêtée en étape 2 sur un cinquième échec non
sanctionné : `SAP HANA Maintenance Copilot` (`b4e4cc03`, `agentium-showcase`),
refusé en `PUBLISHED_FLOW_MIRROR_DRIFT`. Cause : une édition d'auteur du 09/08
08h27 (faycal.benaissa@datategy.net) déplaçant un nœud sur le canevas. La voie
legacy a empilé les versions #15 et #16 sans jamais déplacer le pointeur publié.
`canonical_flow_sha256` hachant `position`, le graphe hache différemment et
`publish_draft` refuse.

**Remédié en production le 10/08 06h32 UTC**, version #17,
`created_by=operator:flow-mirror-drift-remediation`, `flow_sha256 cf2b2e99…`,
`contract_sha256 5ceebd1b…`. Les coordonnées de l'auteur sont préservées, la
dérive est levée, et le compte de dérive sur tout l'estate est **0**. Un Run
legacy réel a été joué avant et après l'écriture, tous deux `completed` avec un
`flow_sha256` identique.

**Conséquence sur les chiffres attendus : ce System est déjà publié, donc les
étapes 5 et 6 décalent de un.** Ce n'est pas une divergence.

| Étape | Documenté ci-dessus | Attendu après remédiation |
|---|---|---|
| 5 dry run | `publish 89` (tous `initial`), `already_pinned 0` | `publish 88` (`publish_initial 87`, `publish_republication 1`), `already_pinned 1` |
| 6 apply | `published 85`, `failed 4` | **`published 84`, `already_pinned 1`, `failed 4`** — somme 89 |
| 7 | `dispatchable 77`, `manual 59, chat 16, event 1` | **inchangé** |

#### Deux pièges que cette remédiation a mis au jour

**Le chemin produit ne peut pas réparer une dérive.** `publish_draft` et
`reconcile_system_flow` passent tous deux par `_assert_published_mirror`, et
aucune fonction exposée ne réconcilie un miroir dérivé : on ne peut pas publier
tant qu'il y a dérive, et publier est ce qui la lèverait. La remédiation a donc
exigé une écriture du miroir en transaction, entre un `restore_draft` et un
`publish_draft`, jamais observable comme état committé.

**« Publier » sur un brouillon en retard détruit l'édition du miroir.** Le
brouillon de ce System portait encore les anciennes coordonnées. `publish_draft`
publie le brouillon *puis* écrase le miroir avec : une publication naïve aurait
effacé le déplacement en rapportant un succès. D'où le `restore_draft(#16)`
préalable, qui charge l'instantané enregistré de l'auteur.

**Le contrôle de dérive ne se périme pas moins vite qu'une journée.** Le rejouer
sur la copie restaurée à l'ouverture de chaque fenêtre. Le compte à reproduire
est **0**. Au-dessus de zéro, examiner *en quoi consiste* la dérive avant toute
décision : celle du 10/08 était cosmétique, c'est un fait sur ce jour-là et non
une règle. Une dérive portant sur autre chose que `position` arrête la fenêtre.
Le comparateur est dans
`/srv/agentium-data/window-2026-08-10/remedy_live.py` et se pointe sur n'importe
quel System.

### Le backfill sort en 1 et c'est l'état nominal

La *Séquence* du 08/08 exige « **après 6 : code de sortie 0** » et interdit
l'étape 7 tant qu'il n'est pas obtenu. **Sur cet estate, ce 0 est
inatteignable** : le script sort en 1 dès un seul `failed`, et 4 Systems
échouent à chaque passe, définitivement. Un opérateur qui applique la consigne
littéralement ne bascule jamais.

La condition d'arrêt correcte n'est pas le code de sortie mais la composition du
rapport :

- `summary.published + summary.already_pinned + summary.skipped + summary.failed`
  doit égaler `summary.systems` (89) ;
- `summary.failed` doit valoir **exactement 4**, et les quatre `system_id`
  doivent être ceux de la liste ci-dessus. Un cinquième échec, ou un échec sur
  un autre Système, arrête la fenêtre ;
- `summary.skipped` doit valoir **0**. Un `skipped` portant
  `no published pointer` ou `no server draft` signifie que `081` n'a pas été
  appliquée : ne pas continuer.

### Séquence

```bash
# Sur omnirag-demo, en sudo.
CAND=f8c0758bf938                       # <sha12> du candidat, immuable
DEPLOY=/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh
REPORTS=/srv/agentium-data/flow-publication-deployments/$(date +%F)-$CAND
WORKTREE=/srv/agentium-data/worktrees/candidate-$CAND

# 1. Construire les trois images au SHA candidat, tag <sha12> UNIQUEMENT.
#    Ne pas déplacer `demo-agentic` : c'est le point de rollback, et il doit
#    continuer de désigner 5c1f8838 jusqu'à l'étape 8.
#    Les quatre build-args sont tous obligatoires : sans PIP_INDEX_URL le build
#    meurt à l'étape 4 du Dockerfile sur « PIP_INDEX_URL is required ».
cd "$WORKTREE"
for svc in backend worker frontend; do
  docker build -f docker/Dockerfile.agentium-$svc \
    --build-arg AGENTIUM_IMAGE_REVISION=<sha40> \
    --build-arg PIP_INDEX_URL=https://pypi.org/simple \
    --build-arg USER_UID=1000 \
    --build-arg USER_GID=1000 \
    -t agentium-$svc:$CAND .
done

# 2. Dump quiescé + checksum + marqueur .ready sur /dev/sdb, puis répétition
#    complète (étapes 4 à 7) sur une base jetable restaurée. Obligatoire :
#    cette tranche mute des graphes stockés, pas seulement du schéma.
sha256sum -c "$REPORTS/postgres-pre-migration.dump.sha256"

# 3. Gate stockage.
AGENTIUM_IMAGE_TAG="$CAND" "$DEPLOY" storage-check

# 4. Migrations 081 → 084. Les images servies restent en 5c1f8838 ; le trafic
#    continue de passer par la voie legacy, qui lit le drapeau par son absence.
AGENTIUM_IMAGE_TAG="$CAND" "$DEPLOY" migrate

# 5. Backfill, dry run. Sortie 1 attendue si at_risk > 0 : lire le rapport.
python -m scripts.backfill_flow_publication_contracts \
  --report /report/contracts-dry-run.json

# 6. Backfill, apply. Après relecture du rapport de l'étape 5 uniquement.
python -m scripts.backfill_flow_publication_contracts --apply \
  --actor 'system:flow-contract-backfill' \
  --report /report/contracts-apply.json

# 7. Vérification d'exécution, avant toute bascule d'image.
python -m scripts.measure_flow_dispatch_readiness \
  --report /report/readiness-post-apply.json

# 8. Bascule des images, puis canaris.
AGENTIUM_IMAGE_TAG="$CAND" "$DEPLOY" up
/srv/agentium-data/worktrees/demo-agentic/scripts/run-iteration-canaries.sh
```

Les étapes 5 à 7 tournent en one-off sur l'**image candidate**, contre la base
live, avec `"$REPORTS"` monté en bind sur `/report`.

### Point de contrôle après chaque étape

| Étape | Observable qui autorise la suite | Ce qui arrête la fenêtre |
|---|---|---|
| 3 | `storage-check` sort en 0 | tout écart de montage |
| 4 | `alembic current` = `084_decision_condition_repair`, **une seule ligne** dans `alembic_version` ; `flow_decision_condition_repairs` existe et compte **130 lignes / 41 Systems** ; le backend live répond toujours en `5c1f8838` et le trafic est nominal | ledger vide ou partiel : `084` n'a pas vu les graphes attendus |
| 5 | `summary.systems` = 89 ; `summary.skipped` = 0 ; `summary.already_pinned` = 1 (SAP HANA, remédié le 10/08) ; `summary.at_risk` = 3 et les trois codes sont `SKILL_NOT_BOUND_TO_SYSTEM`, `ADAPTIVE_POLICY_SCOPE_MISMATCH`, `FLOW_OUTPUT_SINK_REQUIRED` ; lire `report["limits"]` | un `skipped` en `no published pointer` (081 absente) ; un `at_risk` inattendu ; tout `PUBLISHED_FLOW_MIRROR_DRIFT`, qui signale une **nouvelle** dérive apparue depuis la remédiation |
| 6 | `published` = 84, `already_pinned` = 1, `failed` = 4 et **les quatre identifiants attendus** ; la somme des catégories vaut 89 (85 / 0 / 4 avant la remédiation du 10/08) | un cinquième échec, ou un échec sur un autre System |
| 7 | `dispatchable` = 77 ; `would_accept_a_run_by_kind` = `manual 59, chat 16, event 1` ; `blocked_by_code` ne contient que `FLOW_INGRESS_SYSTEM_INACTIVE: 8` et `PUBLISHED_EXECUTION_CONTRACT_MISSING: 4` | toute occurrence de `PUBLISHED_FLOW_MIRROR_DRIFT` : voir *Downgrade de 084* |
| 8 | `/api/v1/build-info` sur le SHA complet, `revision_verified: true`, canaris 6/6, puis 60 minutes de surveillance des Runs rejetés | — |

L'étape 7 est le seul contrôle qui distingue « publié » de « exécutable ». Ne
pas la sauter : le 08/08, une publication réussie masquait 43 contrats vides.

### Où est le point de non-retour, et où il n'est pas

**Le retour arrière par les images reste disponible du début à la fin, et la
base n'a pas besoin d'être restaurée.** Vérifié, pas supposé, avec `084`
appliquée — c'était le doute ouvert, puisque `084` réécrit du contenu de graphe
et pas seulement du schéma.

Mesuré en exécutant l'image `5c1f8838` contre la base migrée en `084` et déjà
backfillée :

- les 41 Systems réparés, **170 conditions Decision** : `condition.validate`
  et `condition.evaluate` de l'ancienne image les acceptent toutes.
  **0 échec de parsing, 0 échec d'évaluation** (63 `True`, 107 `False`) ;
- l'ancien `dag_validator.validate_flow` ne produit **aucun diagnostic
  bloquant** sur les 41 graphes réparés ;
- deux Runs legacy réels (`Agentium Workspace Chat` / Showcase,
  `NAWA Workspace Chat` / Nawa), créés et exécutés par la branche drapeau-éteint
  de `POST /systems/{id}/run`, terminent en **`completed`**, les deux Decisions
  réparées résolvant `matched` ;
- l'ORM de l'ancienne image lit sans erreur le schéma `082`/`083`/`084`, y
  compris la table ledger qu'elle ne connaît pas.

La raison est structurelle et vaut mieux que la mesure seule :
`run_engine/condition.py` est **identique** entre `5c1f8838` et `f8c0758b` à une
addition près (`references()`, un helper non appelé par l'évaluateur). La
grammaire qui lit les conditions réparées est la même des deux côtés. Et le
drapeau `flow_publication_v1` est **absent** des 17 workspaces, donc l'ancienne
image repart intégralement sur la voie legacy.

**Une réserve, sans impact sur le service.** Depuis l'ancienne image, toute
invocation Alembic échoue contre une base en `084` :
`Can't locate revision identified by '084_decision_condition_repair'`, sortie
255. Le point d'entrée du backend n'appelle pas Alembic, donc le service
démarre et sert normalement ; mais après un rollback d'images, **ne pas lancer
`agentium-vm-deploy.sh migrate`** — il échouera. C'est bénin tant que personne
ne le tente.

**Le vrai point de non-retour est le downgrade de `084` après le backfill, pas
la bascule d'image.** Voir ci-dessous.

### Downgrade de `084` : ce qu'il restaure, et pourquoi il ne faut pas le jouer après le backfill

`084.downgrade()` recopie les octets d'origine de `flow_definition` et de
`flow_sha256` depuis le ledger vers `systems`, `system_flow_drafts` et
`system_versions`, puis supprime la table ledger. Il **ne touche jamais
`execution_contract`**.

Conséquence, mesurée en jouant réellement le downgrade sur la copie après un
`--apply` complet :

| | avant downgrade | après downgrade |
|---|---|---|
| contrats publiés (objets) | 85 | **85, inchangés** |
| dérive miroir | 0 | **36** |
| Systems dispatchables | 77 | **47** |
| accepteraient un Run `chat` | 16 | **1** |
| accepteraient un Run `manual` | 59 | 44 |
| nouveau code de refus | — | **`PUBLISHED_FLOW_MIRROR_DRIFT` : 30** |

Le mécanisme : le backfill écrit des versions publiées portant le graphe
*réparé*, versions que le ledger de `084` ne connaît pas puisqu'elles n'existaient
pas au moment de l'upgrade. Le downgrade ramène le miroir `systems.flow_definition`
à la prose, la version publiée reste réparée, et les deux ne concordent plus.
Le backfill **ne répare pas** `PUBLISHED_FLOW_MIRROR_DRIFT` : c'est écrit plus
haut dans ce document, et cela reste vrai ici.

Donc :

- **avant** tout `--apply`, le downgrade de `084` est propre et réversible ;
- **après** un `--apply`, il est destructeur et laisse l'estate plus abîmé
  qu'avant la fenêtre. Ne pas le jouer.

**Récupération si le downgrade a été joué par erreur** — mesurée, elle est
simple : rejouer `alembic upgrade head`. Réappliquer `084` réécrit le miroir
dans sa forme réparée, qui reconcorde avec les contrats déjà publiés, et
l'estate revient à 77 dispatchables / `chat 16` / `manual 59` **sans backfill**.
Un `--apply` lancé ensuite rapporte `already_pinned 85`, `published 0` : il n'y
a rien à republier.

### Si le backfill est interrompu en cours d'`--apply`

Mesuré en tuant le conteneur en plein vol :

- **les publications déjà faites sont conservées.** Chaque System est committé
  individuellement ; la coupure a laissé 28 contrats écrits et valides ;
- **aucun rapport n'est écrit.** Le fichier `--report` n'est produit qu'à la
  toute fin. Une exécution interrompue ne laisse donc *aucun* artefact : tous
  les points de contrôle de l'étape 6 sont indisponibles, et l'état ne peut se
  lire que dans la base ou au rapport de la passe suivante ;
- **la reprise est le simple relancement de la même commande.** Aucune option,
  aucun nettoyage. La passe suivante a rapporté `already_pinned 28`,
  `published 57` — soit les 85 attendus — et l'état final est identique à celui
  d'une passe non interrompue : 77 dispatchables, `chat 16`, `manual 59`.

Ne pas restaurer la base : la donnée n'est pas corrompue, il lui manque des
contrats. Ne pas non plus downgrader `084` (section précédente).

### Preuve d'exécution bout-en-bout

Cinq Runs réels depuis l'image candidate sur la copie, créés par
`flow_ingress.create_published_ingress_run` puis exécutés par
`run_engine.schedule_run` — les deux appels exacts du dispatch manuel.

| System | Mode | Ingress | Statut terminal |
|---|---|---|---|
| `Evidence Graph` (sentinel-ci) | `sequential_legacy` | `manual` | **completed** |
| `Password Reset` (nawa) | `dag_overlay` | `manual` | **completed** |
| `News Lab` (Default) | `sequential_legacy` | `manual` | **completed** |
| `Agentium Workspace Chat` (showcase) — **réparé par `084`** | `dag_overlay` | `chat` | **completed** |
| `Andritz Chat Agentic` (andritz) | `dag_overlay` | `chat` | échec puis **completed** |

Le Run du chat Andritz a échoué une fois en
`membrane_valve_breach:max_latency_ms` avant d'aboutir au second essai. Ce n'est
pas une régression de la publication : environ un Run de chat sur quatre
franchit déjà cette valve, sur le même code, depuis longtemps. Le compter comme
tel.

Le quatrième est le plus informatif : ce System n'était **pas publiable avant
`084`**, et son Run traverse les deux Decisions réparées (`router.fast_exit`,
`runtime.deep_router`), toutes deux résolues en `matched`.

**Précision sur la branche choisie.** Le handoff annonçait que chaque Decision
réparée retomberait sur son `default_branch`. L'observable dit autre chose de la
même chose : la réparation écrit `True` sur la branche de repli, donc le moteur
la voit *matcher* et journalise `decision_resolution: matched`, pas un repli.
Le résultat fonctionnel est bien celui attendu, mais un opérateur qui cherche
`default` dans les checkpoints ne trouvera rien.

### Bornes de cette répétition

- Les Runs ont tourné avec la clé Qdrant en lecture seule et un object store
  local jetable, pour qu'aucune écriture de répétition n'atteigne la production.
  La mesure prouve la traversée et le statut terminal, **pas** la qualité des
  effets de bord : plusieurs invocations échouent en interne
  (`audit_log_v1 requires an event_type`, `'answer'`) sans faire échouer le Run,
  comportement du marcheur antérieur et indépendant de la publication.
- `dispatch-readiness` lit vert-et-vide pour un workspace sans surface déclarée.
  Le chiffre qui fait foi reste celui de `measure_flow_dispatch_readiness`, qui
  rejoue la barrière d'ingress System par System.
- Les 59 ingress `manual` gagnés sont majoritairement du contenu de
  démonstration, pas du trafic.

## Fenêtre exécutée le 10/08 — déployé sur `f8c0758b`, estate publié

Fenêtre ouverte sans trafic, à la demande, et menée d'un trait de 06h44 à 07h15
UTC. Les huit étapes ont été jouées dans l'ordre et **chaque point de contrôle a
rendu le chiffre attendu**, y compris le décalage de un dû à la remédiation SAP
HANA. Aucune étape n'a demandé d'arbitrage.

### Ce qui est servi, et ce qui ne l'est pas

| | Valeur |
|---|---|
| Images servies | `agentium-{backend,worker,frontend}:f8c0758bf938` |
| Révision bakée, `revision_verified` | `f8c0758bf938414f1be2da4874eb0fdda00edd2c`, `true` |
| Tête de `demo/agentic` | `5ca80901e48f` |
| Base | `084_decision_condition_repair`, ligne unique |
| Point de rollback images | `agentium-*:5c1f8838ac66`, conservés |
| Point de rollback base | dump du 10/08 ci-dessous |

**La tête de branche est deux commits devant l'image, et c'est voulu.**
`f8c0758b..5ca80901` ne touche que `docs/ops/` — vérifié par
`git diff --name-only | grep -v '^docs/'`, qui rend le vide. L'image répétée en
combiné la veille a été conservée plutôt que reconstruite au head : rebâtir
aurait échangé un artefact éprouvé contre une résolution de dépendances neuve,
sans rien gagner. L'alias `agentium-*:demo-agentic` a été déplacé sur la ligne
déployée après les canaris.

### Deux choses que le runbook ne disait pas, et qui ont coûté du temps

**Seul le backend avait été construit au SHA candidat.** La répétition combinée
du 09/08 n'avait besoin que de lui. `worker` et `frontend` manquaient à
l'ouverture de la fenêtre : sans eux, l'étape 8 aurait basculé un backend neuf
contre un frontend de trois jours. Construire les deux prend six minutes avec le
cache chaud. **Contrôler la présence des trois tags avant l'étape 2.**

**`node` n'est pas sur le `PATH` de root sur `carakai`.** Le binaire vit sous
`/opt/agentium-protected-runner/node-current/bin` ; sans lui, le shim Playwright
meurt en `/usr/bin/env: 'node': No such file or directory`, code 127, en deux
secondes. Et le checkout du runner pointait sur `/tmp/omnirag-attestation.bundle`,
disparu depuis : il a fallu lui réexpédier un bundle incrémental depuis le poste
de développement pour qu'il connaisse le SHA déployé. Préambule correct :

```bash
export PATH=/opt/agentium-protected-runner/node-current/bin:$PATH
git -C /opt/agentium-protected-runner/repos/omnirag fetch <bundle> \
    'refs/heads/<branche>:refs/remotes/bundle/head'
git -C /opt/agentium-protected-runner/repos/omnirag checkout --detach <sha40>
```

### Observables, étape par étape

| Étape | Observé | Attendu |
|---|---|---|
| 2 dump | `448723924` o, sha256 `6585433a22ae…`, 1201 entrées TOC, triplet `.sha256`/`.ready` en `0600` | triplet complet |
| 2 dérive | **0** sur tout l'estate | 0 |
| 3 stockage | sortie 0 | 0 |
| 4 migration | `083` → `084`, ligne unique ; ledger **130** lignes (`systems` 41, `system_flow_drafts` 41, `system_versions` 48), **41** Systems, **465** conditions réécrites | 130 / 41 |
| 5 dry run | `systems` 89, `publish` 88 (`initial` 87, `republication` 1), `already_pinned` **1**, `at_risk` 3, `skipped` 0 | conforme au décalage post-remédiation |
| 6 apply | `published` **84**, `already_pinned` **1**, `failed` **4**, `skipped` 0, somme **89** | 84 / 1 / 4 |
| 7 readiness | `dispatchable` **77**, `manual 59 / chat 16 / event 1`, blocages `FLOW_INGRESS_SYSTEM_INACTIVE` 8 et `PUBLISHED_EXECUTION_CONTRACT_MISSING` 4 | identique |
| 8 bascule | `build-info` sur le SHA complet, `revision_verified: true`, frontend en 200, **canaris 6/6** en 1,0 min | 6/6 |

Les quatre échecs sont nominativement ceux inventoriés :
`Tender Response Analyst`, `Contract Risk Copilot`, `Translation Suite`
(showcase) et `Shared mailbox creation` (nawa).

La base était déjà en `083` depuis la fenêtre du 08/08, donc l'étape 4 n'a
appliqué que `084`. L'état d'arrivée est celui de la répétition, qui partait de
`080`.

### Après bascule

- Dérive miroir re-mesurée : **0**. Le nouveau chemin n'en a pas créé.
- `measure_flow_dispatch_readiness` rejouée sous l'image servie : chiffres
  identiques à l'étape 7.
- **0 opt-out et 0 opt-in explicites** sur les 15 workspaces actifs : tous
  tournent sur le défaut publié, aucun n'a été épinglé à la main.
- **104 Systems sur 104** portent un pointeur publié.
- Aucun `traceback`, `error` ni `exception` dans les journaux backend et worker.

### L'ancre et le worktree de déploiement ont été avancés

`/home/ubuntu/omnirag` était détachée sur `522632e0` ; elle suit désormais
`demo/agentic` et pointe sur `5ca80901`. Le worktree
`/srv/agentium-data/worktrees/demo-agentic` a suivi.

**Ce contrôle est obligatoire avant de la déplacer.** L'ancre ne monte pas que
des répertoires de données : trois chemins **suivis par git** sont montés dans
des conteneurs vivants —
`docker/livekit/agentium-livekit.yaml` (livekit),
`backend/keycloak/realm-export.json` et `backend/keycloak/themes/agentium` (kc).
Un `checkout` qui les modifierait changerait la configuration sous des
conteneurs qui ne redémarrent pas. Ici le diff sur ces trois chemins est vide,
et leurs `mtime` sont restés à leurs dates d'origine après la bascule : le
checkout ne les a pas réécrits. **Rejouer ce diff avant chaque déplacement de
l'ancre.**

### Ce que cette fenêtre ne prouve pas

Aucun Run n'a été exécuté en production. `rehearse_published_ingress_run.py`
s'interdit lui-même la production — il exécute les Skills pour de vrai — et la
fenêtre a respecté cette borne. La preuve d'acceptation du dispatch est le
replay read-only de la barrière par `measure_flow_dispatch_readiness` ; la preuve
d'aboutissement reste celle des cinq Runs de la répétition combinée, sur une
copie du même code et des mêmes données. La surveillance de 60 minutes des Runs
rejetés prévue au point de contrôle 8 n'a rien à observer sur une fenêtre sans
trafic : **elle reste due au premier usage réel.**

## Itération du 10/08 — déployée sur `78f56ed4`, isolation client360

Itération courte, frontend seul, sans migration : boucle en six pas, pas de
fenêtre lourde.

### Ce qu'un contrôle d'intégration a trouvé

Question posée : les lots 7-9 et les tranches Flow Builder sont-ils bien tous
sur `demo/agentic` ? Un test d'ascendance dit oui pour toutes les branches sauf
quelques-unes ; il ment, parce que **l'intégration s'est faite par cherry-pick
et que les SHA changent**. Le contrôle qui répond vraiment est
`git cherry -v origin/demo/agentic <branche>`, qui compare les patches, doublé
d'un `comm` sur les listes de fichiers.

Résultat sur `codex/demo-agentic-release-a-integration` : sept des neuf commits
atterris sous d'autres SHA, et **un absent** —
`38c3fd81 fix(client360): preserve IAM and workspace isolation`. Son mécanisme
d'époque était bien passé, mais pas ses points d'appel : `fetchCustomerFiche` et
`loadCustomerSummary` écrivaient leur réponse sans vérifier l'époque, et
`resetWorkspaceActions` laissait affichées les données du tenant précédent.
Changer de workspace pendant le chargement d'une fiche affichait le client de A
dans B.

**Règle à retenir : après une intégration par cherry-pick, vérifier par
`git cherry` et par diff de contenu, jamais par `merge-base --is-ancestor`.**

### Périmètre réparé, plus large que le commit manquant

L'audit du composant entier a trouvé la même faille dans onze autres méthodes,
antérieures à ce correctif : chat, réglages SMTP, prompt mail, brouillons,
envois, impact et campagnes écrivaient tous des données de tenant sans contrôle
d'époque ni en-tête de scope. **25 appels réseau, 13 méthodes** désormais
épinglés, et `resetWorkspaceActions` purge l'état tenant à la bascule.

Un test de contrat (`client360-page.component.spec.ts`) parcourt la source du
composant et échoue si un futur appel réseau arrive sans garde ou sans son
en-tête de scope. Le test de comportement a été **prouvé rouge sans le
correctif** avant d'être accepté vert.

Les trois tests backend du commit manquant n'ont **délibérément pas** été
portés : ils attendaient `read` / `customer_detail` sur `/customers/{id}`, alors
que la route exige aujourd'hui `engine.run`. Les porter les aurait fait échouer,
ou aurait poussé à affaiblir l'endpoint.
`test_client360_authorization_inventory.py` couvre déjà la propriété par AST sur
**toutes** les routes et épingle le couple `system` / `engine.run`.

### Observables

| Pas | Observé |
|---|---|
| Gates locaux | 702 tests unitaires frontend, `tsc -p tsconfig.app.json` propre, inventaire backend 2/2 |
| Push | `demo/agentic` en fast-forward `d5d11c6b` → `78f56ed4` |
| Ancre + worktree | avancés sur `78f56ed4` ; inodes `faiss_db` (2049:2665446) et `secure_deposit` (2080:2) inchangés |
| Diff des trois chemins suivis | **vide**, `mtime` d'origine, livekit et keycloak jamais redémarrés |
| Build | trois images au tag `78f56ed46084` (backend et worker inchangés en source, rebuildés pour que `AGENTIUM_IMAGE_REVISION` reste vrai) |
| `storage-check` | sortie 0 |
| `up` | trois conteneurs recréés, `build-info` sur le SHA complet, `revision_verified: true` |
| Canaris | **6/6** en 56 s, premier passage |

Rollback disponible : `AGENTIUM_IMAGE_TAG=f8c0758bf938` puis `up`. Aucune
migration dans cette itération, donc le retour arrière est symétrique — c'est la
différence avec la fenêtre du matin.

### Le piège du re-tag, à ne pas prendre

Seul le frontend avait changé. Re-taguer `agentium-backend:f8c0758bf938` en
`78f56ed46084` aurait économisé un build, mais `AGENTIUM_IMAGE_REVISION` est
cuit dans l'image : `/api/v1/build-info` aurait annoncé `f8c0758b` sous un tag
`78f56ed4`, et `revision_verified` serait tombé, avec lui le gate canari.
**Rebuilder les trois, même quand un seul service change.**

### Ce que cette itération ne prouve pas

La fuite corrigée est une course : elle demande de changer de workspace pendant
un appel en vol. Aucun test ne la reproduit contre la production — le test de
comportement la simule avec un `HttpClient` factice, et le test de contrat est
statique. Rien n'a été observé sur du trafic réel, pour la même raison qu'au
matin : il n'y en avait pas.

## Ménage du 10/08 — et le worktree qu'il ne fallait pas prendre pour un résidu

### `/srv/agentium-data/worktrees/release-a` n'est pas un reliquat

Il porte le nom d'une release close et ressemble à s'y méprendre à un candidat
oublié. **Deux conteneurs vivants montent depuis ce chemin :**
`agentium-p4-maintenance` et `qdrant`. Le supprimer aurait cassé la maintenance
P4 et le store vectoriel, trois jours d'uptime chacun.

Contrôle obligatoire avant de retirer un worktree de la VM :

```bash
for c in $(docker ps --format '{{.Names}}'); do
  docker inspect "$c" | grep -q "/srv/agentium-data/worktrees/<nom>" && echo "$c MONTE"
done
```

Seuls `candidate-dcc36f97899f`, `candidate-f8c0758b` et
`candidate-ingress-6604d957` étaient réellement sans montage : 1,7 Gio retirés.
Restent `demo-agentic` (déploiement) et `release-a` (**infrastructure vivante,
ne pas supprimer**).

### Cache builder, et rien d'autre

`docker builder prune --filter 'until=24h'` : **6,27 Gio** récupérés, cache
ramené de 42,8 à 36,5 Gio. Ni image ni volume touchés, conformément à la règle
posée en tête de ce document. Les « 49 Gio réclamables » annoncés sur les
volumes locaux restent le piège à ne pas prendre. Après ménage :
`storage-check` en 0, douze conteneurs sains, `build-info` inchangé, frontend en
200.

### Le poste est enfin *sur* `demo/agentic`

Il poussait dessus depuis `codex/flow-builder-p0-integration`, sans upstream,
avec un refspec explicite à chaque fois — et la branche locale `demo/agentic`
traînait **33 commits en arrière**. Un `git checkout demo/agentic` y aurait
ramené l'état du 6 août. Worktree principal basculé, upstream configuré.

Vingt-deux branches locales retirées : dix-sept joignables depuis
`demo/agentic`, cinq reprises par cherry-pick. Les deux qui n'existaient **que**
sur ce poste ont été archivées en tags poussés avant suppression —
`archive/release-a-hardening-2026-07-23` et
`archive/demo-agentic-release-a-integration-2026-07-27`. Le handoff Lots 7-9,
seule copie sur la branche supprimée, a été remis dans `docs/ops/`.

Quatre branches anciennes et réellement non fusionnées ont été conservées :
`feat/create-vector-store-api`, `Omnirag-react-reasoning-trace`, `doc/cir`,
`backup/capture-pre-rebase-20260624`.

### Supprimer une branche locale ne la fait pas disparaître du sélecteur

Cursor liste les branches distantes à côté des locales. `codex/release-a-from-hotfix`
a continué de s'afficher après le ménage local parce qu'elle vivait toujours sur
`origin` — ni cache périmé ni référence de suivi obsolète, la branche était bien
sur le serveur. Le ménage local et le ménage distant sont deux gestes séparés, et
le second est visible par toute l'équipe.

Neuf branches `codex/*` retirées d'`origin` le 10/08, toutes vérifiées
entièrement joignables depuis `demo/agentic` juste avant suppression, et toutes
archivées en tags poussés d'abord (`archive/codex-<nom>-<date>`), présence sur le
serveur contrôlée avant le `--delete`. Le distant passe de 33 à 24 branches.

Trois exclusions délibérées. `main` et `develop` sont techniquement redondantes
mais conventionnelles et de longue vie — `main` est probablement la branche par
défaut du dépôt. `codex/flow-builder-p0-safety` porte un patch sans équivalent
exact au sens de `git cherry` (son contenu a atterri sous un autre SHA), gardée
par prudence.

Les quinze branches distantes réellement non fusionnées — `feat/qdrant`,
`feat/keycloak`, `feat/metadata-indexing`, `Justicia/multi-modal--pipeline`,
`llmaas` et les autres — sont toutes antérieures à mai et sans rapport avec
Agentium. Ne pas les prendre pour du résidu.

### Quatre pièges en avançant l'ancre d'un commit documentaire

**Le worktree de déploiement n'est pas un clone indépendant.**
`/srv/agentium-data/worktrees/demo-agentic` est un worktree *lié* du clone
`release-a`, enregistré sous le nom hérité `release-b`, et son répertoire
d'administration appartient à `root`. Une raison de plus de ne jamais supprimer
`release-a` : cela emporterait aussi l'administration du worktree de
déploiement.

**`sudo -u ubuntu` échoue dessus**, sur `cannot lock ref 'ORIG_HEAD'`. L'ancre
se manipule en `ubuntu`, ce worktree en `root` — les deux commandes ne sont pas
interchangeables.

**Son `origin/*` lui est propre.** Un `merge --ff-only origin/demo/agentic`
répond « Already up to date » alors que le worktree est en retard, parce que la
référence de suivi du clone `release-a` n'a pas bougé. Toujours `fetch` puis
fusionner `FETCH_HEAD` :

```bash
sudo git -C /srv/agentium-data/worktrees/demo-agentic fetch origin demo/agentic
sudo git -C /srv/agentium-data/worktrees/demo-agentic merge --ff-only FETCH_HEAD
```

**`build-info` ne répond qu'en HTTPS.** Le backend n'est pas publié sur le
`:8000` de l'hôte et nginx en clair renvoie 404 sur ce chemin. La sonde correcte
est `curl -sk https://localhost/api/v1/build-info`.

**`--filter health=healthy` renvoie 9 sur 12 à l'état normal.** Trois conteneurs
n'ont pas de healthcheck déclaré — `agentium-livekit`,
`agentium-p4-maintenance`, `agentium-worker-cpu`. Ils sont debout, pas malades.
Le « douze conteneurs sains » écrit plus haut était une formulation relâchée.

## Itération du 10/08 (après-midi) — déployée sur `7619f0be`, skills de réconciliation PO/facture

Boucle courte, sans migration : quatre skills cœur déterministes pour la démo
NAWA de réconciliation PO/facture — `spreadsheet_table_extract_v1`,
`invoice_document_extract_v1`, `line_items_reconcile_v1`,
`reconciliation_report_v1` — plus un helper de résolution de fichiers et leurs
tests à fixtures. Le diff (`1807bf1e..7619f0be`, 7 fichiers, +1380) ne touche
que `backend/app/services` et `backend/app/tests` ; le contrôle des trois
chemins montés rend le vide, `mtime` d'origine conservés après l'avance de
l'ancre, inodes `faiss_db` (2049:2665446) et `secure_deposit` (2080:2)
inchangés.

### Observables

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `1807bf1e` → `7619f0be`, accès Bitbucket local direct (pas de bundle côté poste) |
| Build | trois images au tag `7619f0be51f5`, label 40-hex vérifié sur les trois ; ~7,7 min cache chaud |
| Dump | `postgres-pre-switch.dump`, **449349951** o, sha256 `91702ae9e799…`, **1204** entrées TOC, triplet `.sha256`/`.ready` en `0600` sous `/srv/agentium-data/recon-skills-deployments/2026-08-10-7619f0be51f5` (`0700`) |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | seuls backend, worker-cpu et frontend recréés ; `build-info` sur le SHA complet, `revision_verified: true` |
| Alembic | `084_decision_condition_repair` avant **et** après — aucune migration dans cette tranche |
| Logs | aucun `traceback`/`error`/`exception` backend au démarrage |
| Skills | les 4 slugs présents dans `skills` avec leurs catégories (`Analysis` ×2, `Decision Support`, `Governance`), `is_seeded='Y'` — via le seed one-off ci-dessous |
| Canaris | **6/6** en 57,4 s, premier passage |
| Ancre + worktree | avancés sur `7619f0be`, alias `demo-agentic` déplacé sur la ligne déployée après les canaris |

Rollback disponible : `AGENTIUM_IMAGE_TAG=78f56ed46084` puis `up`. Base
intouchée par la tranche, retour symétrique.

Le commit qui porte cette section avance ensuite la tête de branche, l'ancre
et le worktree d'un commit documentaire au-dessus de `7619f0be` : les images
servies restent en `7619f0be` et c'est l'état attendu, le delta ne touchant
que `docs/ops/`.

### Le seed de démarrage ne tourne pas en production — le plan supposait le contraire

Cette tranche partait de « le seed se réconcilie au démarrage du backend,
aucune migration ». C'est vrai du code, faux de la configuration servie :
`startup_reconciliation = "disabled"` est épinglé par le manifeste Release A,
et `app/main.py` garde **tous** ses seeds derrière ce drapeau. Après la
bascule, le backend a démarré proprement en journalisant
`Database startup reconciliation disabled`, et la table `skills` ne portait
aucun des quatre slugs.

Remède joué, conforme au précédent des one-off sur image candidate :
`seed_skills_and_capabilities(db)` exécuté une fois dans le conteneur backend
servi (fonction idempotente, upsert par `slug`, commit interne). Rapport :
`skills_added 10, skills_updated 79, capabilities_added 0,
capabilities_updated 25`.

**Dix ajoutés, pas quatre.** Le seed n'avait tourné dans aucune fenêtre depuis
que le drapeau est posé : six entrées de `SEED_SKILLS` de tranches antérieures
(`briefing_priorities_v1`, `causal_drill_v1`, `draft_email_v1`,
`generate_recommendations_v1`, `schedule_meeting_v1`,
`summarize_long_document_v1`) attendaient en silence. Ce sont des lignes de
catalogue globales (`workspace_id NULL`), inertes tant qu'aucun workspace ne
les active — l'arriéré est soldé, pas un incident.

**Règle à retenir : toute tranche qui s'appuie sur « seedé au démarrage » doit
prévoir le one-off en production.** Le démarrage ne seede rien tant que
`startup_reconciliation` reste `disabled`, ce qui est son état nominal.

### Le bundle du runner, encore

Même piège qu'au matin, variante : `/tmp/omnirag-attestation.bundle` existait
cette fois sur carakai, mais périmé — le fetch « réussit » sans apprendre le
SHA candidat. Bundle incrémental `78f56ed4..demo/agentic` réexpédié depuis le
poste (sha256 `cb31e328…` identique des deux côtés), fetch, checkout détaché
sur `7619f0be`, préambule `PATH` node inchangé. Un `fetch origin` qui sort en 0
sur ce dépôt ne prouve rien : vérifier `cat-file -e <sha40>` avant de lancer
les canaris.

### Ce que cette itération ne prouve pas

Aucun Run n'a exercé les quatre skills en production : la preuve fonctionnelle
est celle des tests à fixtures (extraction exacte des deux fichiers d'exemple,
les 2 écarts attendus trouvés, rapport stable). L'exposition catalogue par
workspace (`enabled_skills`), la configuration NAWA et le System de démo
restent à faire — c'est l'étape suivante du plan, hors fenêtre.

## Répétition du 10/08 (midi) — System NAWA publié, deux boucles opérationnelles manquantes

La configuration NAWA, le System « PO vs Invoice Reconciliation » (v3 publiée,
sha `d3b03ec6…`) et les trois chemins d'ingress (manuel, `deposit.promoted`,
cron) ont été répétés de bout en bout — détails, chiffres et check-list dans
`docs/demo-runs/2026-08-10-nawa-po-invoice-recon/DEMO-SCRIPT.md`. Deux pièges
d'infrastructure découverts en chemin, à connaître au-delà de cette démo.

### Le conteneur `agentium-p4-maintenance` sert une image ancienne — et son rôle est OFF par défaut

Les runs déclenchés par événement ne s'exécutent pas tout seuls : le trigger
écrit un Run `pending` plus une ligne `run_dispatch_outbox`, et c'est la boucle
P4 (`app.workers.p4_maintenance`) qui publie vers Celery. Sur cette VM,
`ENABLE_P4_MAINTENANCE` n'est posé nulle part → la boucle idle (« P4
maintenance disabled ») et tout run événementiel reste `pending` pour toujours.

Pire : le conteneur dédié est resté épinglé sur une image du 27/07 (révision
`07f54a68`, antérieure au type d'événement `trigger_run`). Y lancer la boucle
marque les dispatches `dead` avec « invalid dispatch envelope ». Une ligne
outbox (`b64ae1ff…`) a été repassée `dead` → `pending` en SQL direct (écriture
documentée), puis publiée proprement une fois la boucle relancée **dans
`agentium-worker-cpu`** (image `7619f0be`, alignée backend) :

```bash
sudo docker exec -d -e ENABLE_P4_MAINTENANCE=true agentium-worker-cpu \
  python -m app.workers.p4_maintenance
```

### Aucun processus Celery beat — le cron `scheduler_tick` ne tire jamais

`celery_app.conf.beat_schedule` déclare `agentium.scheduler_tick` toutes les
60 s, mais seul un *worker* tourne : personne n'émet les ticks, donc les
`run_schedules` n'ont jamais tiré sur cette VM. Lancé pareil, dans le worker :

```bash
sudo docker exec -d agentium-worker-cpu python -m celery \
  -A app.workers.celery_app:celery_app beat --loglevel info \
  --schedule /tmp/celerybeat-schedule
```

**Les deux boucles sont des `docker exec` : un restart du conteneur worker les
tue.** À relancer avant toute démo (check-list du script), et à intégrer à la
prochaine fenêtre de déploiement comme services compose durables (env
`ENABLE_P4_MAINTENANCE=true` + image du conteneur p4 réalignée, service beat).

## Itération du 10/08 (fin d'après-midi) — déployée sur `59723514`, parseur d'en-tête de facture

Boucle courte, sans migration, un seul commit de code
(`c56a352d..59723514`, 2 fichiers, +165/−8, `backend/app/services` +
`backend/app/tests` uniquement) : le parseur d'en-tête de
`invoice_document_extract_v1` tolère désormais la mise en page fusionnée de
pdfplumber. Le texte pdfplumber réel a été capturé **avant** le correctif via
`docker exec` sur l'image servie (pdfplumber 0.11.10) et committé en fixture de
test paramétrée à côté du texte PyPDF2 — le comportement colonnes-fusionnées
est épinglé localement sans ajouter pdfplumber aux dépendances. 41 tests
verts (réconciliation + gardes skills-registry), ruff propre sur les fichiers
touchés.

### Observables

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `c56a352d` → `59723514` |
| Worktree | `fetch origin demo/agentic` + `merge --ff-only FETCH_HEAD` en root, les trois chemins montés suivis intouchés |
| Build | trois images au tag `59723514e0d3`, label 40-hex vérifié sur les trois, ~8 min cache chaud |
| Dump | `postgres-pre-switch.dump`, **449429808** o, sha256 `b3b8dcf4a2c8…`, **1204** entrées TOC, triplet `.sha256`/`.ready` en `0600` sous `/srv/agentium-data/recon-skills-deployments/2026-08-10-59723514e0d3` (`0700`) |
| `storage-check` | sortie 0 |
| `up` | backend, worker-cpu, frontend recréés ; `build-info` sur le SHA complet, `revision_verified: true` ; alembic `084` avant et après |
| Logs | aucun `traceback`/`error`/`exception` backend ni worker après bascule |
| Boucles | draineur P4 + celery beat morts avec le restart du worker (attendu), relancés à l'identique (`docker exec -d`, env `ENABLE_P4_MAINTENANCE=true`), `ps aux` de contrôle avant/après |
| Canaris | **6/6** en 54,7 s, premier passage — bundle incrémental `7619f0be..demo/agentic` requis sur carakai (sha256 identique des deux côtés), `cat-file -e` vérifié avant les canaris |
| Ancre + worktree | avancés sur `59723514` puis sur le commit documentaire ; inodes `faiss_db` (2049:2665446) et `secure_deposit` (2080:2) inchangés |
| Seed | aucun changement de seed dans la tranche ; les 4 slugs réconciliation toujours `is_seeded='Y'` (vérifié, pas supposé) |

Rollback disponible : `AGENTIUM_IMAGE_TAG=7619f0be51f5` puis `up`. Base
intouchée, retour symétrique.

### System NAWA republié en v4, hors fenêtre — le PDF pilote le filtre Excel

Dans la foulée, le System « PO vs Invoice Reconciliation » a été republié v4
par la voie produit en conteneur (`save_draft` → `validate_flow` →
`publish_draft`, acteur `thibaud.ishacian@datategy.net`) : le nœud facture
publie `po_reference` dans le namespace déclaré `po_filter` via `outputs_map`
(`{"po_reference": "po_filter.PO Number"}`) et le nœud registre lie `filters`
à ce namespace entier — le mécanisme de composition d'objet est celui que
`recon_report` utilisait déjà. `invoice_meta` réalimente les deux nœuds de
rapport, le rapprochement lit `po_reference` depuis la facture, et le
contournement `settings.recon.po_filters` est retiré des settings.

Validateur : **zéro issue**. La publication a exigé
`breaking_change_intent="acknowledged"` (ajouts de contrat sur trois nœuds +
`variable_namespaces`) — attendu pour un System actif. Version v4
`9fc3cd0e-2e9a-427b-ae44-4bf301d924e5`, flow sha `1ab05703…`.

Re-répétition : un dispatch manuel réel (`POST
/systems/{id}/ingresses/source.manual/runs`, identifiants e2e de carakai), run
`3184a53c-0d63-49f1-a280-22aa9247eac8` **completed** en 0,7 s. Les cinq champs
d'en-tête sortent remplis en production (INV-8834, 14 July 2026, PO-2026-0451,
13 August 2026, Al Fanar Industrial Supplies W.L.L.), mêmes chiffres (2 flags,
−10.00 %, +4.29 %, 9 950 vs 9 860, Needs Review), la ligne d'identité facture
est revenue dans le rapport, et **0** `execution_contract_violation` — le run
v3 équivalent en portait exactement 1 (`/due_date`, observe).

Le commit qui porte cette section avance la tête de branche, l'ancre et le
worktree d'un commit documentaire au-dessus de `59723514` : les images servies
restent en `59723514` et c'est l'état attendu, le delta ne touchant que
`docs/`.

## Durcissement du 10/08 (après-midi) — boucles P4 et beat durables, déployé compose-only sur `23a8528f`

Fenêtre sans rebuild d'image : les deux boucles opérationnelles lancées en
`docker exec` le matin (draineur d'outbox P4 + Celery beat, tuées par tout
restart du worker) deviennent des services compose durables. Images servies
inchangées en `59723514`, `revision_verified: true` avant et après.

### Le piège du draineur à image ancienne, consigné

`agentium-p4-maintenance` datait du déploiement Release A du 28/07 : image du
27/07 (révision `07f54a68`, **antérieure au type d'outbox `trigger_run`**),
`restart: no` (posture opened jamais corrigée puisque jamais recréé), et
`ENABLE_P4_MAINTENANCE` posé nulle part — sa boucle principale idlait
(« P4 maintenance disabled »). Y lancer une boucle activée marque les
dispatches des types récents `dead` (« invalid dispatch envelope »,
`PermanentDispatchError` sur type inconnu) : c'est l'incident `b64ae1ff…` du
matin. **Règle : le draineur doit toujours servir l'image alignée sur le
backend.** L'épinglage de digest du vm-runtime, pensé « ne jamais recréer »,
était précisément ce qui figeait le conteneur sur l'image piégée. Le worktree
`release-a` reste par ailleurs de l'infrastructure vivante (administration du
worktree de déploiement) : ne pas le supprimer.

### Nouvelle topologie durable

- `agentium-p4-maintenance` : dé-épinglé dans
  `docker/compose.agentium.vm-runtime.yml`, suit `AGENTIUM_IMAGE_TAG` comme
  backend/worker, `ENABLE_P4_MAINTENANCE: "true"` posé par l'overlay (littéral,
  l'overlay reste sans interpolation), `restart: unless-stopped`. Montages
  inchangés (les binds applicatifs du compose de base ; les « montages
  release-a » du conteneur historique étaient en réalité l'association aux
  fichiers compose du projet, pas des binds).
- `agentium-beat` : nouveau service du compose de base, image worker, commande
  `celery … beat`, `restart: unless-stopped`, derrière un **profil `beat`** —
  un `up` local nu ne le démarre pas (le worker local garde son beat embarqué
  `CELERY_BEAT=1`), le lanceur VM le nomme explicitement (ce qui active le
  profil) tandis que le worker VM reste `AGENTIUM_CELERY_BEAT=0` : exactement
  **un beat par environnement, jamais deux**.
- `scripts/agentium-vm-deploy.sh up` recrée désormais cinq services :
  backend, worker-cpu, frontend, p4-maintenance, beat. Le contrat
  `test_safe_vm_deploy_contract.py` (compte des `AGENTIUM_DISABLE_DOTENV`)
  passe de 5 à 6 services Python ; les 162 tests infra sont verts.

### Bascule et preuves

- `up --dry-run` d'abord : backend/worker/frontend `Running` (non recréés),
  beat `Created`, p4 `Recreated` — aucun autre conteneur touché ; contrôle des
  chemins montés avant l'avance de l'ancre (delta `1bf45513..23a8528f` :
  compose, lanceur, un test — aucun fichier bind-monté), inodes
  `faiss_db`/`secure_deposit` inchangés.
- Ordre de bascule dicté par la sémantique des claims : beat exec tué **avant**
  le `up` (un tick raté se rattrape, `next_fire_at` reste dû ; jamais deux
  beats), draineur exec laissé vivant **pendant** la recréation et tué après
  (claims `FOR UPDATE SKIP LOCKED` + jetons de lease + task ids déterministes :
  un double-drain bref est sans effet).
- Durabilité : `docker restart` des trois conteneurs → les trois reviennent
  seuls (p4 « started » après SIGTERM propre, beat repart, worker `ready`).
- Bout en bout : `next_fire_at` de la planification NAWA reculé d'une minute
  en SQL, le tick beat suivant tire le run `0efe69b3-6dc3-4448-819a-e38a80113474`
  — completed en 0,9 s, verdict **Needs Review**, 2 flags, `PO-2026-0451` —
  et `next_fire_at` **revient tout seul** sur `2026-08-11 07:00` (croniter) :
  la cadence quotidienne n'a pas eu à être restaurée à la main.
- Outbox : 2 `published`, **0** `pending`/`leased`/`dead` avant et après.
- Canaris : **6/6** en 56,9 s, premier passage (le SHA `59723514` était déjà
  dans le checkout du runner, `cat-file -e` vérifié en root — le contrôle en
  `ubuntu` échoue sur « dubious ownership », c'est attendu).

### Nouveau compte nominal : **13 conteneurs**

12 + `agentium-beat`. Quatre sans healthcheck (« Up » est leur état sain) :
`agentium-worker-cpu`, `agentium-p4-maintenance`, `agentium-livekit` et
désormais `agentium-beat`. `--filter health=healthy` renvoie 9 sur 13 à l'état
normal.

Rollback : `AGENTIUM_IMAGE_TAG` précédent puis `up` reste valable pour les
images ; pour la topologie, un `git revert 23a8528f` + avance du worktree +
`up` suffit (compose-only). Le commit documentaire qui porte cette section
avance ensuite tête de branche, ancre et worktree ; les images servies restent
en `59723514`.

## Itération du 10/08 (soir) — déployée sur `8fc41597`, QA Flow Builder et capacité `document_reconciliation`

Boucle courte, sans migration, quatre commits par tranche au-dessus de
`7b7d69a2` : la fiche System dit ce que le run engine exécute et la navigation
garde le graphe (`67f7c22a`), la création de Skill depuis l'UI sur les
exécuteurs que le serveur vérifie (`f673e428`), la séparation auteur/opérateur
du Flow Builder avec les deux correctifs d'intégrité backend — plancher de coût
et plafond d'affichage du ROI, capacité `document_reconciliation` au seed
(`05deb3ef`) — puis la mise à jour du contrat d'authoring e2e (`8fc41597`).
Le delta ne touche que `backend/app/{api,services,tests}`, `frontend-ng/src`,
`frontend-ng/scripts` et `frontend-ng/e2e` ; aucun fichier bind-monté, inodes
des chemins montés inchangés.

### Portails locaux

| Portail | Commande | Observé |
|---|---|---|
| Types | `npx tsc -p tsconfig.app.json --noEmit` | sortie 0 |
| Unitaires | `node scripts/run-unit.mjs` | **743/743** en 4,7 s (3 specs ajoutées) |
| AOT | `npx ng build --configuration development` | bundle complet en 17,0 s, un seul `NG8107` préexistant dans `vp-map-preview.component.ts` (fichier non touché) |
| Backend ciblé | `pytest` sur systems/flow (publication, ingress, workbench, safety, validate, perspective), hypervisor, authoring de Skills, surface catalogue, visibilité/couverture, seed, réconciliation, exécuteurs vérifiés | **180 passed** |
| Backend infra | `pytest app/tests/infra` | **863 passed** (contrat de conformité inclus) |
| Ruff | fichiers backend touchés | jeu de violations **identique** à `HEAD` (dette `UP006`/`UP007`/`I001` préexistante, rien de neuf) |

### Compatibilité des canaris — une seule spec réellement périmée

Quatorze contrôles de la barre d'outils passent derrière deux disclosures
(`Operate`, `More actions`) : ils sortent du DOM et de l'arbre d'accessibilité
au chargement. Cinq vignettes majuscules du workbench disparaissent au profit
d'une ligne d'état et d'une disclosure « What this run touches ».

- `e2e/tests/16-flow-builder-authoring-contract.spec.ts` (**+17**, seule spec
  éditée) : la spec vérifie d'abord qu'« Execute on backend » est **absent** de
  l'arbre et qu'« Operate » s'annonce `aria-expanded="false"`, puis ouvre la
  disclosure et poursuit le parcours. L'intention préservée est
  « le contrôle reste atteignable » — la présence par défaut est remplacée par
  une assertion de portée, pas assouplie. Côté workbench, la garantie de
  sécurité est ré-pointée sur les phrases qui la portent désormais : la ligne
  d'état est exigée sur « Nothing is saved or published », et « Autosave stays
  paused » est attesté **caché** puis **visible** après clic sur « What this
  run touches ». Aucune assertion de sécurité supprimée, aucune transformée en
  contrôle souple.
- `09-live-workspace-contract`, `11-system360-canary`,
  `12-protected-runner-canaries`, `scripts/playwright/**` : **aucune édition
  nécessaire** après relecture des chaînes et des sélecteurs. Le canari de
  termes interdits (`findSentinelForbiddenPresentationTerms`) est intact.
- Une adaptation a été faite **côté produit plutôt que côté canari** : la
  signature de chrome invariant de `11` tolère mal un eyebrow qui changerait de
  façon asynchrone. `system-view.component.ts` porte donc `flowChromeActive`,
  qui n'expose « Systems · Flow » que lorsque la projection `system_360_canary`
  est inactive — le canari garde son assertion, la fiche garde sa vérité.
- `core/zoom-context.service.ts` : le typeguard lit `candidate['workspace_slug']`
  en notation crochets, comme le reste du dépôt, sinon l'inventaire
  `WorkspaceSlugBranch` de `agentium_compliance` déclare une branche non
  inventoriée. Le contrat de conformité redevient vert sans toucher à
  l'inventaire.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `7b7d69a2` → `8fc41597`, accès direct depuis le poste (pas de bundle vers l'origine) |
| Ancre + worktree | `sudo -u ubuntu git fetch` puis checkout sur `8fc41597`, arbre propre hors résidus connus |
| Build | **trois** images au tag `8fc41597486d` (backend, worker, frontend), label `org.opencontainers.image.revision` 40-hex vérifié sur les trois |
| Dump | `postgres-pre-switch.dump`, **449485592** o, sha256 `a11f96865552…`, **1204** entrées TOC, triplet `.sha256`/`.ready` sous `/srv/agentium-data/qa-flow-deployments/2026-08-10-8fc41597486d` en `0600` |
| `up` | cinq services recréés (backend, worker-cpu, frontend, p4-maintenance, beat) à 16:01:52Z, `RestartCount=0` sur les trois principaux |
| `build-info` | `revision: 8fc41597486dc78d52b1d79dd3ff0e5d8ff02530`, `revision_verified: true` (HTTPS seulement) |
| Alembic | `084_decision_condition_repair` avant **et** après — aucune migration dans ce programme |
| Conteneurs | **13**, `--filter health=healthy` = **9** (les quatre sans healthcheck sont sains en « Up ») |
| Logs | **0** réponse 5xx, **0** ligne `ERROR`, **0** `Traceback` sur toute la vie du conteneur backend ; histogramme `200`×404, `404`×7, `401`×2 |
| Snapshot post-bascule | `postgres-post-switch.dump`, 449501891 o, sha256 `d0a0244e00aa…`, rangé à côté du dump pré-bascule |
| Canaris carakai | **6/6** en 57,1 s, premier passage, sur les specs **telles que mises à jour** |

Rollback disponible : `AGENTIUM_IMAGE_TAG=59723514e0d3` puis `up`. La base ne
porte qu'un ajout de ligne de catalogue (ci-dessous), retour symétrique.

### Re-seed en production — une capacité ajoutée, rien de dupliqué

`startup_reconciliation` reste `disabled` : le one-off est obligatoire, comme
consigné l'après-midi. `seed_skills_and_capabilities(db)` joué dans le
conteneur backend servi.

| Table | Avant | Après |
|---|---|---|
| `capabilities` | **36** | **37** (`document_reconciliation`, `tier=universal`, `workspace_id NULL`, `is_seeded='Y'`, créée à 16:03:40Z) |
| `skills` | **89** | **89** — `skills_added 0` |

Les dix lignes `skills` créées le 10/08 datent de **09:46**, fenêtre du matin :
cette tranche n'en ajoute aucune. Les cinq `skill_ids` de la capacité résolvent
exactement `spreadsheet_table_extract_v1`, `invoice_document_extract_v1`,
`line_items_reconcile_v1`, `reconciliation_report_v1`, `audit_log_v1`.
Idempotence prouvée par un second passage : `skills_added 0, skills_updated 89,
capabilities_added 0, capabilities_updated 26`, compteurs inchangés,
**zéro slug en double** dans `capabilities` comme dans `skills`.

Effet catalogue mesuré : dans NAWA le bloc `visibility` des cinq skills nomme
`document_reconciliation` dans `capabilities` tout en gardant
`reason: enabled_override` — l'override du workspace précède la capacité, c'est
la précédence attendue. Dans `andritz`, `test` et `agentium-showcase`, qui n'ont
pas d'override, la raison devient `reason: capability` : le portage par capacité
est bien la voie qui les rend visibles, plus un patch NAWA.

### Vérification API post-bascule

| Contrôle | Observé |
|---|---|
| `GET /systems` (NAWA) | **7** Systems, **7/7** porteurs des trois clés `published_*` |
| `GET /systems/fe4ab7e5…` | `published_flow_version_id: 9fc3cd0e-2e9a-427b-ae44-4bf301d924e5`, `published_at: 2026-08-10T12:36:19`, `published_by: thibaud.ishacian@datategy.net` |
| `GET /skills/executors` | `200`, `editable: true`, deux kinds (`prompt_template`, `registry_call`) |
| `GET /hypervisor/balance-sheet` | **13** libellés `High-yield outcome · ROI > 1000%`, **0** pourcentage à quatre chiffres ; le champ machine `roi` garde son ratio brut (max 63,0 sur 3 signaux, 2 au-dessus de 10) — le plafond est **d'affichage**, pas de donnée |
| `GET /systems/dispatch-readiness` | Système de réconciliation `ready: true`, deux surfaces prêtes (planification quotidienne `next_fire_at 2026-08-11T07:00`, événement `deposit.promoted`) |

### Pièges rencontrés, et leur résolution

- **Checkout du runner périmé.** `/opt/agentium-protected-runner/repos/omnirag`
  était resté en `59723514`. Bundle incrémental `59723514..demo/agentic`
  (96132 o, sha256 `fc23da62fb94…` identique des deux côtés), `fetch` du
  bundle, `cat-file -e 8fc41597…` **avant** de lancer les canaris, checkout
  détaché. `node` toujours hors du `PATH` de root : préambule
  `/opt/agentium-protected-runner/node-current/bin`.
- **Le dump pré-bascule est à quatre niveaux de profondeur.** Un
  `find /srv/agentium-data -maxdepth 3 -name '*.dump'` ne le voit pas et
  « prouve » son absence : il vit sous
  `/srv/agentium-data/<programme>-deployments/<date>-<tag>/`. Contrôler le
  répertoire de fenêtre, pas la racine.
- **`POST /auth/login` renvoie `token`, pas `access_token`.** Un script de
  vérification qui lit `.access_token` obtient une chaîne vide et enchaîne des
  401 muets.
- **`GET /systems` renvoie `{"systems": [...]}`.** Lire `.items` ou traiter la
  réponse comme un tableau donne « 0 System » sur un workspace qui en a sept.
- **`capabilities.skill_ids` stocke des ids, pas des slugs.** Chercher le
  porteur d'un slug par `like '%slug%'` sur cette colonne rend systématiquement
  vide ; passer par `skills.id`, ou lire le bloc `visibility.capabilities` de
  l'API qui fait déjà la résolution.

### Ce que cette fenêtre prouve, et ce qu'elle ne prouve pas

Elle prouve le contrat serveur : les champs de publication sortent de l'API, le
catalogue d'exécuteurs répond avec son drapeau `editable`, les libellés de ROI
sont bornés, la capacité de réconciliation porte ses cinq skills sans doublon,
le System de démo reste dispatchable, et les canaris protégés passent sur les
specs mises à jour au SHA déployé.

Elle ne prouve rien de l'UI : les portails locaux et les canaris couvrent le
contrat d'authoring et le chrome invariant, pas les quatre tranches de surface
(fiche System pilotée par le Flow, dialogue de création de Skill, barre
d'outils dédoublée, ligne d'état du workbench) — la relecture navigateur est
faite hors fenêtre par le coordinateur. Aucun Run réel n'a été lancé sur le
System de réconciliation : la preuve est la **disponibilité de dispatch**, pas
une exécution de bout en bout de plus.

## Itération du 10/08 (nuit) — déployée sur `8fbf440b`, plafond de rendement sur les trois surfaces restantes

Le plafond posé le soir même ne couvrait que les **libellés du fil de signaux**,
côté backend. Trois surfaces continuaient d'imprimer les ratios en toutes
lettres : le bandeau du bilan (`ROI 6277%`, `EFFICIENCY 992.40`), la ligne
`Workspace Assistant` du tableau CAPABILITIES (`ROI 6382%`,
`EFFICIENCY 1001.18`) et la carte Outcome des runs (`EFFICIENCY 1303293%` sur
des runs à 1,50 $ pour un coût de 0,0001 $). Itération courte, frontend seul,
sans migration : le seuil et les deux formes de rendu passent dans
`frontend-ng/src/app/shared/cockpit/yield-format.ts`, consommé par
`hypervisor.component.ts` et `run-outcome-card.component.ts`, avec le miroir de
`MAX_SIGNAL_ROI_RATIO` écrit dans le module pour que backend et frontend ne
divergent pas en silence.

**Correctif d'affichage seulement, par décision.** `_compute_efficiency`
(`backend/app/services/outcome/derive.py`) et la colonne `efficiency` sont
intouchées : y poser un plancher de coût changerait la sémantique des runs déjà
enregistrés et de toute agrégation en aval. Le delta ne touche que
`frontend-ng/{src,scripts}` ; aucun fichier bind-monté, diff vide sur les trois
chemins suivis montés dans des conteneurs vivants, inodes `faiss_db`
(2049:2665446) et `secure_deposit` (2080:2) inchangés après l'avance de l'ancre.

### Portails locaux

| Portail | Commande | Observé |
|---|---|---|
| Types | `npx tsc -p tsconfig.app.json --noEmit` | sortie 0 |
| Unitaires | `node scripts/run-unit.mjs` | **747/747** en 51,0 s (743 avant, 4 tests ajoutés par `yield-format.spec.ts`) |
| AOT | `npx ng build --configuration development` | bundle complet en 61,9 s, un seul `NG8107` préexistant dans `vp-map-preview.component.ts` (fichier non touché) |
| Backend | aucun — **aucun fichier backend touché** |

Aucun canari n'a été édité : la recherche de `EFFICIENCY`, `ROI` et d'un
pourcentage attendu dans `e2e/tests/**` et `scripts/playwright/**` ne rend
aucune assertion sur ces chaînes. `12-protected-runner-canaries` visite bien
`/hypervisor`, mais n'y assert que la présence de l'extension Mission Room et
son profil.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `59b0c8f3` → `8fbf440b`, accès Bitbucket direct depuis le poste |
| Ancre + worktree | `/home/ubuntu/omnirag` en `merge --ff-only` sur `8fbf440b`, worktree de build détaché sur le même SHA ; `mtime` d'origine conservés sur `agentium-livekit.yaml` (02/06) et `realm-export.json` (23/04) |
| Build | **trois** images au tag `8fbf440b827b`, label `org.opencontainers.image.revision` 40-hex vérifié sur les trois (~8 min cache chaud) |
| Dump | `postgres-pre-switch.dump`, **449618012** o, sha256 `5c39966041805b55…`, **1204** entrées TOC, triplet `.sha256`/`.ready` en `0600` sous `/srv/agentium-data/yield-cap-deployments/2026-08-10-8fbf440b827b` (`0700`), `sha256sum -c` **OK** |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services recréés (backend, worker-cpu, frontend, p4-maintenance, beat), `RestartCount=0` sur les trois principaux |
| `build-info` | `revision: 8fbf440b827b50359279f129ca3f0c448f917671`, `revision_verified: true` (HTTPS) |
| Alembic | `084_decision_condition_repair` avant **et** après — aucune migration dans cette itération |
| Conteneurs | **13**, `--filter health=healthy` = **9** (les quatre sans healthcheck sont sains en « Up ») |
| Logs | **0** `ERROR`, **0** `Traceback`, **0** réponse 5xx côté backend ; histogramme `200`×325, `404`×1 |
| Canaris carakai | **6/6** en 57,3 s, premier passage, contre le SHA déployé |
| Alias | `demo-agentic` déplacé sur la ligne déployée après les canaris ; images `8fc41597486d` conservées |

Rollback disponible : `AGENTIUM_IMAGE_TAG=8fc41597486d` puis `up`. Base
intouchée, retour symétrique.

### Vérification API post-bascule — le fil garde ses ratios bruts

C'est la preuve que le correctif est bien d'affichage et pas de donnée.

| Contrôle | Observé |
|---|---|
| `GET /hypervisor/balance-sheet` (NAWA) | `portfolio.roi` **62.772004…**, `portfolio.avg_efficiency` **992.4015…** — ratios bruts intacts, pour 165,195 $ de valeur et 2,5904 $ de coût |
| Même appel, ligne `Workspace Assistant` | `roi` **63.0191…**, `avg_efficiency` **1001.1838…** — bruts eux aussi |
| Libellés de signaux | 13 `High-yield outcome · ROI > 1000%`, déjà bornés par le backend depuis `05deb3ef` |
| `GET /runs?system_id=fe4ab7e5…` | 6 runs, `efficiency` brut **13032.927**, **13394.329**, **13983.431**, **12008.121**, **13741.933** sur `value 1.5` / `cost 0.0001` ; un run `failed` sans outcome |

Rendu correspondant après bascule : `> 1000%` partout où un ratio dépasse 10 en
pourcentage, `> 10.00` pour l'index d'efficacité du hypervisor, `—` pour le run
en échec. En deçà du plafond, rien ne change.

### Trois pièges, tous dans l'outillage de fenêtre

- **Compter les entrées TOC demande le client de la même famille.**
  `docker run --rm postgres:16 pg_restore --list` sur le dump rend **0** entrée
  sans échouer bruyamment, et `docker exec -i agentium-pg pg_restore --list
  /dev/stdin` en rend 0 aussi (le flux n'est pas seekable). Le contrôle qui
  répond : monter le répertoire de fenêtre dans un conteneur jetable bâti sur
  **l'image de `agentium-pg` elle-même**
  (`docker run --rm --entrypoint pg_restore -v "$D":/d:ro "$(docker inspect -f
  '{{.Image}}' agentium-pg)" --list /d/<dump>`). 1204 entrées, comme les
  fenêtres précédentes.
- **Un glob sur le répertoire de dump échoue silencieusement.** Le répertoire
  est en `0700 root` : `sudo chmod 0600 "$D"/*.dump.*` est expansé par le shell
  **non privilégié** avant `sudo`, ne matche rien, et `chmod` se plaint d'un
  chemin littéral inexistant alors que les fichiers sont bien là. Passer par
  `sudo sh -c '…'` pour que l'expansion se fasse en root.
- **`POST /auth/login` attend `email`, pas `username`.** Le champ `username`
  sort en `422 {"loc":["body","email"],"type":"missing"}`. À rapprocher du piège
  déjà consigné sur la clé de réponse (`token`, pas `access_token`) : les deux
  bouts du contrat de login sont contre-intuitifs.

### Ce que cette fenêtre prouve, et ce qu'elle ne prouve pas

Elle prouve que le fil n'a pas bougé : les quatre champs machine relus après
bascule portent exactement les ratios bruts d'avant, et les libellés backend
restent bornés. Elle prouve que le SHA déployé passe les canaris protégés.

Elle ne prouve rien du rendu : aucun canari n'assert sur `ROI` ni `EFFICIENCY`,
et le portail qui couvre le changement est un test unitaire sur le module de
formatage, pas une lecture de page. La relecture navigateur des trois surfaces
est faite hors fenêtre par le coordinateur.

### Dette relevée, non traitée

`_compute_efficiency` n'a d'autre garde-fou que `cost <= 0`. Les runs futurs
continueront donc d'écrire des ratios à cinq chiffres en base dès qu'une skill
est tarifée sous le centime. Le backend a choisi le plancher `MIN_SIGNAL_COST`
pour ses signaux ; poser le même plancher dans le calcul stocké est un
arbitrage ouvert, **volontairement non pris ici** parce qu'il changerait la
sémantique des runs déjà enregistrés et de toute agrégation en aval.

## Itération du 11/08 (matin) — déployée sur `6b65eaf1`, moteur d'assistant conversationnel NAWA

L'assistant NAWA était un script : intentions codées en dur, une phrase par
branche, rien à répondre hors du chemin prévu. Le moteur qui le remplace
(`backend/app/services/assistant/`, endpoint `POST /api/v1/assistant/turns`,
mode assistant dans la passerelle vocale, front NAWA rebranché, tramage sortant
LiveKit) ne sait rien du tenant : persona, scope de connaissance, allowlist
d'outils et modèle sont résolus depuis `workspace.settings.assistant`.

**Ni migration Alembic ni dépendance nouvelle.** `alembic current` rend
`084_decision_condition_repair` avant **et** après la bascule. Le schéma ne
bouge pas, donc le retour arrière est symétrique : redéployer les images
précédentes suffit, sans restauration de base.

### Portails locaux

| Portail | Commande | Observé |
|---|---|---|
| Backend | `backend/.venv/bin/python -m pytest app/tests --ignore=app/tests/integration` | **4957/4957** en 376,5 s, 0 échec |
| Types | `npx tsc -p tsconfig.app.json --noEmit` | sortie 0 |
| Unitaires front | `node scripts/run-unit.mjs` | **817/817** en 9,5 s |
| Sidecar | `npm test` dans `livekit-agent/` | **29/29** en 0,8 s |

`app/tests/integration/` est exclu : ses 18 échecs viennent d'un Qdrant absent
en local et préexistent à cette fenêtre.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `eb2b77f3` → `6b65eaf1`, accès Bitbucket direct depuis le poste (pas de bundle) |
| Ancre + worktree | `/home/ubuntu/omnirag` en `merge --ff-only` sur `6b65eaf1`, worktree de build détaché sur le même SHA, `git status` vierge des deux côtés |
| Build | **trois** images au tag `6b65eaf1ba23`, label `org.opencontainers.image.revision` 40-hex vérifié sur les trois (~7,7 min) |
| Dump | `postgres-pre-switch.dump`, **449847639** o, sha256 `43b26efd3a0497e2…`, **1204** entrées TOC, triplet `.sha256`/`.ready` en `0600` sous `/srv/agentium-data/assistant-engine-deployments/2026-08-11-6b65eaf1ba23` (`0700`), `sha256sum -c` **OK** |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services recréés (backend, worker-cpu, frontend, p4-maintenance, beat), `RestartCount=0` sur tous |
| `build-info` | `revision: 6b65eaf1ba234d7f793086e2ed7386d63a3d1c4c`, `revision_verified: true` (HTTPS) |
| Alembic | `084_decision_condition_repair` avant **et** après |
| Conteneurs | **13**, `--filter health=healthy` = **9** — compte nominal inchangé |
| Sidecar | `agentium-livekit-agent` **non reconstruit et non recréé** : `Up 4 days`, `healthy`, `RestartCount=0`, 0 erreur sur 30 min. Le tramage est émis par la passerelle backend ; le sidecar relaie ce qu'on lui donne |
| Logs | **0** `ERROR`, **0** `Traceback`, **0** réponse 5xx ; histogramme `200`×132, `401`×1 (la sonde non authentifiée de la fenêtre) |
| Canaris carakai | **6/6 vertes** au premier passage, en reprise le 11/08 à 08h04 UTC |
| Alias | `demo-agentic` déplacé sur `6b65eaf1ba23` après les canaris |

### Les canaris, joués en reprise

Le premier essai de la fenêtre a conclu que `carakai` (`79.137.18.231`) était
injoignable **au niveau TCP** sur le port 22, depuis le poste comme depuis
`omnirag-demo`. La panne était transitoire : deux heures plus tard `nc -vz`
aboutit et `ssh carakai` ouvre une session sans rien changer à la
configuration. Retenir de cet épisode qu'un `nc` qui expire ne prouve rien de
durable, et qu'il vaut de réessayer avant de conclure — pas d'écarter le gate.

Reprise contre le SHA effectivement servi (`build-info` relu en HTTPS,
`revision_verified: true` avant lancement) :

```bash
ssh carakai
sudo -n env PATH=/opt/agentium-protected-runner/node-v22.23.1-linux-x64/bin:$PATH \
  /opt/agentium-protected-runner/repos/omnirag/scripts/run-iteration-canaries.sh \
  6b65eaf1ba234d7f793086e2ed7386d63a3d1c4c
```

`node` n'est **pas** dans le `PATH` de root sur carakai et ne vit pas à un
chemin standard : il est sous `/opt/agentium-protected-runner/node-v22.23.1-linux-x64/bin`.
Le `PATH` doit être épinglé explicitement, comme pour les autres exécutants.

**6/6 vertes en 57,1 s**, pas de reprise : projections System 360, routes
applicatives et Client360 à blanc, isolation de marque Sentinel et Octocity,
configuration LiveKit sans jeton, micro non accordé alors que Capture reste
accessible.

Le checkout source revu du runner est resté à `8fbf440b` — l'état où la fenêtre
précédente l'avait laissé. C'est ici une propriété utile plutôt qu'un retard :
les assertions sont antérieures au moteur d'assistant, donc le vert atteste
d'une non-régression des surfaces existantes et non d'un test écrit avec le
code qu'il contrôle.

### L'alias, déplacé après le gate

Les trois `demo-agentic` pointaient sur `8fbf440b827b` ; ils pointent désormais
sur les images `6b65eaf1ba23` (`docker tag` des trois dépôts applicatifs).
L'opération ne redémarre rien : les cinq conteneurs applicatifs sont épinglés
sur le tag immuable, et leur `Status` est inchangé après coup. Le point de
rollback reste `AGENTIUM_IMAGE_TAG=8fbf440b827b`, adressable par son tag
immuable indépendamment de l'alias.

### Configuration du workspace `nawa` — la clé de scope du contrat est fausse

`docs/ops/assistant-engine-contract.md` §4 et §4.1 écrivent tous deux
`"knowledge_scope": "itsd"`. **La clé réelle en production est
`itsd-knowledge`**, relue dans `settings.knowledge_scopes` avant écriture :

```json
{ "key": "itsd-knowledge", "label": "IT Service Desk knowledge",
  "is_default": true, "collection_slugs": ["itsd-knowledge"] }
```

`"itsd"` n'aurait pas échoué : `select_scope` serait retombé sur le scope par
défaut, qui *est* celui-là. Ça aurait donc marché — par accident. La
configuration aurait affirmé un scope inexistant et le contrôle de scope
n'aurait rien prouvé. C'est le piège de cette famille de réglages : **une clé
inexistante est silencieuse quand le défaut est le bon.** Le contrôle qui répond
est un prédicat sur la base, pas une relecture du bloc écrit :

```sql
SELECT settings::jsonb -> 'knowledge_scopes'
    @> jsonb_build_array(jsonb_build_object('key', settings::jsonb#>>'{assistant,knowledge_scope}'))
  FROM workspaces WHERE slug='nawa';   -- doit rendre t
```

Bloc posé, idempotent (`jsonb_set`, rejeu à `md5(settings)` identique :
`d3c606fe86cf90c4a3e2b3feec2ef478` avant et après) :

| Clé | Valeur | Pourquoi |
|---|---|---|
| `knowledge_scope` | `itsd-knowledge` | la clé réelle ; le contrat, qui écrivait `itsd`, a depuis été corrigé en `5db3038f` |
| `locale` | `en` | la bibliothèque, le catalogue et la surface sont en anglais ; une locale que la bibliothèque ne parle pas produit des réponses que leurs propres citations contredisent |
| `allowed_tools` | les **cinq** en lecture seule | `start_system_run` et `answer_hitl_gate` restent hors allowlist |
| `persona` | §4.1 du contrat, **recopiée**, 1307 caractères | extraite du fichier par script, pas retapée |
| `provider` / `model` | `openai` / `gpt-5` | `azure_openai` est refusé par nom |
| `max_tool_turns` / `history_turns` / `top_k` / `latency_profile` | 4 / 12 / 8 / `balanced` | valeurs de référence du contrat |

L'IAM de ce déploiement tourne en mode observation : l'autorisation de run répond
« autorisé » quoi qu'on lui demande. L'allowlist est donc la seule chose entre
une phrase et une exécution, et une phrase est une entrée contrôlée par
l'attaquant. `nawa` n'opte pas. L'exécution passe par le bouton à l'écran,
chemin `NawaItsdService.launchTyped`.

Les neuf autres clés de `settings` sont intactes (`demo_safe`, `catalog`,
`family`, `features`, `knowledge_scopes`, `navigation_profile`,
`platform_brand`, `presentation`, `_migration_065_nawa_itsd_state`).

**État antérieur sauvegardé** dans `nawa-settings-before.json` (1144 o, sha256
`fd9a3fc192f7a9ab…`, `0600`), à côté du dump, dans le répertoire de fenêtre.

### Validation texte — quatre tours réels contre la production

Jouée par le contrat interne §2 (`answer_assistant_turn`) dans le conteneur
`agentium-backend` déployé, contre la base et le Qdrant live. **Pourquoi pas la
voie HTTP :** les deux membres de `nawa` s'authentifient par Keycloak et n'ont
pas de `password_hash` local ; obtenir un jeton aurait demandé de créer ou de
muter un identifiant sur le workspace client le plus sensible, ce qui n'était
pas dans le mandat. La voie HTTP est vérifiée séparément — la route existe et
rend **401** sans jeton — et le corps servi est exactement `result.as_payload()`,
dont les onze clés sont assertées à chaque tour.

| Contrôle | Preuve |
|---|---|
| Politique citée, bon scope | T1 « What does the service desk policy say about MFA for remote access? » → `search_knowledge` en 11 837 ms, `knowledge_scope: "itsd-knowledge"`, `collections: ["itsd-knowledge"]`, 8 passages, **4 citations** (`multi-factor-authentication.md`, `remote-access-and-vpn.md`, `password-and-account-policy.md`, `service-desk-priorities-and-targets.md`) ; la réponse cite le texte entre guillemets |
| Service nommé, lancement proposé, rien déclenché | T2 « I lost my password » → « This is handled by the **Password Reset** service… **I can't start it for you** ». Outils appelés : `list_services`, `preview_service` (`status: live`) — **jamais** `start_system_run`. `count(runs)` du workspace : **125 avant, 125 après**, delta **0** |
| Aucun nom de fournisseur à l'écran | 13 motifs cherchés (`openai`, `gpt`, `chatgpt`, `anthropic`, `claude`, `azure`, `mistral`, `gemini`, `llama`, `o3`, `o4`, `language model`, `llm`) sur les quatre réponses : **0 occurrence**. Le champ `model` du payload vaut bien `gpt-5`, mais aucune surface NAWA ne le lit — vérifié par recherche : `AUCUNE LECTURE DU CHAMP model`. `_demo_safe(workspace)` est vrai par `settings.demo_safe` **et** `presentation.hide_provider_details` |
| Fil continu, nouvelle conversation distincte | T1/T2/T3 partagent `a388a6cd-68f6-4361-b865-306a5b40efb5` ; T4 sans `session_id` ouvre `9483b9ab-b43e-4634-9255-c97773aff5b3`. T3 « What do I need to have ready **before I press it**? » n'a pas d'antécédent dans son propre tour et résout pourtant Password Reset : la continuité est référentielle, pas seulement un identifiant reconduit |
| Rien au-delà de la persona | Anglais sur les quatre tours ; identité annoncée comme vérifiée contre le dossier RH et l'authentificateur enregistré ; bouton et champ décrits ; aucun code répété ; jamais « envoyé », « démarré » ou « terminé » |

Les deux fils créés par la validation ont été **archivés et effacés en doux**
(`status='archived'`, `archived_at`, `deleted_at`) : aucun fil actif du jour ne
subsiste dans `nawa`.

### Voix — configurée, cohérente, volontairement fermée

**Rien n'a été ouvert, et rien n'était à fermer.** Le défaut de `mode` est
`conversation_only`, qui « transcrit et ne répond rien » (§3.1), et la recherche
`mode: 'assistant'` dans `frontend-ng/src` hors specs ne rend **aucune**
occurrence : aucune surface ne demande le mode assistant. La lane est construite
de bout en bout côté serveur et transport — passerelle, moteur, tramage,
`VoiceEventReassembler` sur `LiveKitConversationConnection` *et*
`VoiceSessionConnection` — mais aucun écran ne l'appelle.

Reste à faire pour un essai en salle réelle :

1. **La capability** : passer `mode: "assistant"` et `surface: "nawa_assistant"`
   au `session.start`. Le mode traverse `POST /livekit/token`,
   `POST /livekit/sessions/{id}/agent/dispatch` et le sidecar ; la passerelle le
   renvoie en écho sur `runtime.metric` / `metric: "session_started"`. **Lire
   l'écho**, ne pas supposer que la salle obtenue est celle demandée.
2. **L'écran** : `nawa-assistant.component.ts` (route `/nawa/itsd`). Il n'utilise
   aujourd'hui que `VoiceTtsPlaybackService` pour la restitution locale ; il
   n'ouvre pas de salle en mode assistant.
3. **Le réglage** : pousser `assistant.context` une fois la salle ouverte, tramé
   (`seq`/`total`/`context_json`), avec les 39 entrées du catalogue plafonnées à
   40. Un tour parlé avant l'arrivée du contexte est répondu quand même, en moins
   bien — jamais refusé.
4. **Le tri des erreurs** : distinguer récupérable et terminal **par le code**,
   jamais par le message — qui est de la prose française côté serveur et qui,
   pour une panne fournisseur, nommerait un fournisseur. Traiter un récupérable
   comme terminal ouvre une *seconde* salle à côté de la première, micro ouvert.

### L'asymétrie du code à usage unique — à connaître avant une démo parlée

En **texte**, les deux preuves d'identité sont tapées dans le champ attaché au
bouton : le code ne quitte jamais le navigateur, il n'est pas envoyé au moteur.

À la **voix**, il ne peut pas en être ainsi : la passerelle a entendu et
transcrit l'énoncé, et a répondu au tour, **avant** que la surface puisse agir.
Sur cette lane les preuves transitent donc par le moteur. `redactSecrets` garde
le code hors de l'écran, et la pression sur le bouton est identique des deux
côtés — mais l'affichage masque, il n'empêche pas le transit. C'est un fait
assumé, pas un défaut à corriger dans la fenêtre, et il doit être connu avant
de montrer la voix.

### Rollback

```bash
# 1. Images précédentes. Base intouchée : le schéma n'a pas bougé.
DEPLOY=/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh
sudo env AGENTIUM_IMAGE_TAG=8fbf440b827b "$DEPLOY" up

# 2. Settings du workspace, depuis la sauvegarde de fenêtre.
D=/srv/agentium-data/assistant-engine-deployments/2026-08-11-6b65eaf1ba23
sudo docker cp "$D/nawa-settings-before.json" agentium-pg:/tmp/nawa-before.json
sudo docker exec -i agentium-pg psql -U agentium -d agentium -v ON_ERROR_STOP=1 <<'SQL'
\set before `cat /tmp/nawa-before.json`
UPDATE workspaces SET settings = :'before'::json WHERE slug = 'nawa';
SQL
sudo docker exec agentium-pg rm -f /tmp/nawa-before.json
```

**Pas de restauration de base.** Le dump de fenêtre est une assurance, pas une
étape du retour arrière : aucune migration n'a tourné. Retirer le seul bloc
`assistant` suffit d'ailleurs à rendre l'assistant neutre — son absence est une
configuration valide (persona neutre, scope par défaut, allowlist en lecture
seule), ce qui fait du réglage lui-même un point de retour indépendant des
images.

### Ce que cette fenêtre prouve, et ce qu'elle ne prouve pas

Elle prouve que le SHA déployé sert, que la configuration écrite désigne un
scope qui existe, et que quatre tours réels contre la production tiennent les
cinq contrôles texte — dont le seul qui compte vraiment pour la sûreté : le
modèle nomme le service, prépare le lancement, et **n'a créé aucun Run**.

Elle ne prouve rien de la voix : aucune salle n'a été ouverte en mode assistant.
Elle ne prouve rien du rendu navigateur : les tours sont passés par le contrat
interne, pas par un écran. Et elle ne porte pas le gate des canaris, `carakai`
étant injoignable.

### Dette relevée, non traitée

Le contrat `docs/ops/assistant-engine-contract.md` continue d'écrire
`"knowledge_scope": "itsd"` en §4 et en §4.1, alors que la production porte
`itsd-knowledge`. Le corriger touche un document gelé comme contrat ; l'écart
est consigné ici plutôt que patché en fenêtre.

## Itération du 12/08 — déployée sur `ec934d64`, polish UI/UX bilingue et sans jargon interne

Deux commits sur `demo/agentic` : `9ea4b4a9` (import BRD pour amorcer une skill,
rattachement à une capability) et `ec934d64` (dictionnaire scindé en onze
modules de domaine, thème tri-state partout, assistant de création de skill,
liste de contrôle du Flow Builder en langage clair). Le déclencheur était des
libellés livrés en français seulement, un mode clair partiel, et une création de
skill qui exigeait d'écrire du JSON à la main.

**Ni migration Alembic ni dépendance frontale nouvelle.** `alembic current` rend
`084_decision_condition_repair` avant **et** après la bascule, donc le retour
arrière est symétrique : redéployer les images précédentes suffit. Côté backend
la dépendance `python-docx` entre pour le parse `.docx`, ce qui impose de
reconstruire l'image plutôt que de recycler la précédente.

### Portails locaux

| Portail | Commande | Observé |
|---|---|---|
| Garde i18n | `npm run check:i18n` | sortie 0 — **2792** clés, 11 domaines, 20 règles de lexique |
| Garde chrome | `npm run check:ui-chrome` | sortie 0 — les deux violations de violet hérité de `connectors-page` et `resources-page` sont soldées |
| Types | `npx tsc -p tsconfig.app.json --noEmit` | sortie 0 |
| Unitaires front | `node scripts/run-unit.mjs` | **857/857** |
| Build AOT | `npm run build:prod` | réussi, seuls les avertissements de budget préexistants |
| QA navigateur | pilotes `e2e/qa-*.mjs` sur le build AOT servi par `serve-dist.mjs` | **134** captures relues en clair/sombre × FR/EN |

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `d650b72a` → `ec934d64`, accès Bitbucket direct depuis le poste |
| Ancre + worktree | `/home/ubuntu/omnirag` en `pull --ff-only`, worktree de build détaché sur le même SHA, `git status` vierge des deux côtés |
| Build | **trois** images au tag `ec934d64a889`, `AGENTIUM_IMAGE_REVISION` en 40-hex (~9,5 min) |
| Dump | **aucun** — la tranche ne mute ni schéma ni graphes stockés |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services recréés (backend, worker-cpu, frontend, p4-maintenance, beat), `RestartCount=0` sur tous |
| `build-info` | `revision: ec934d64a889ea02c2efa29dfb8affa5b42ed090`, `revision_verified: true` |
| Alembic | `084_decision_condition_repair` avant **et** après |
| Conteneurs | **13**, `--filter health=healthy` = **9** — compte nominal inchangé |
| Sidecar | `agentium-livekit-agent` non reconstruit et non recréé : `Up 5 days`, `healthy` |
| Logs | **0** `ERROR`, **0** `Traceback` sur le backend depuis la bascule |
| Canaris carakai | **6/6 vertes** au premier passage, artefacts `/tmp/iteration-canaries-20260812T140225Z.MK5cMy` |
| Alias | `demo-agentic` déplacé sur `ec934d64a889` après les canaris |

### Ce que la fenêtre a corrigé au passage, hors périmètre annoncé

Le build AOT était **déjà cassé** avant l'ouverture de la fenêtre :
`client360-page.component.ts` portait deux boucles `@for` sur des membres jamais
déclarés, absents de `HEAD` et introduits par une itération antérieure. Les deux
tableaux ont été reconstitués depuis les `<option>` d'origine. Un déploiement
tenté sans cette réparation aurait échoué au build, pas en production.

Le garde i18n ne sondait que les templates : le français en dur des littéraux
TypeScript lui échappait entièrement, ce qui explique que des libellés
monolingues aient pu être livrés sans alerte. La sonde couvre désormais les
deux, et la dette restante est cliquetée — un budget par fichier qui ne peut que
descendre, avec les vraies fixtures (verbatims de démonstration, table
d'anonymisation, miroir du contrat `capture_templates`) séparées de la dette
sous une catégorie explicite.

### Ce que cette fenêtre prouve, et ce qu'elle ne prouve pas

Elle prouve que le SHA déployé sert, que les deux thèmes se tiennent sur les
écrans touchés, et que le mot `advisory` a disparu de l'écran au profit de
« recommandation » pour le livrable consultatif et de « consultatif » pour une
donnée non contraignante — le lexique opposable le bannit désormais, donc la
rechute est bloquée à la garde.

Elle ne prouve rien des états denses : la QA navigateur tourne sur un stub d'API
et rend le chrome et les états vides, pas des listes peuplées ni la mission
room. La barre vocale n'a été vue qu'inactive, aucune session micro réelle n'a
été ouverte. Et aucun parcours authentifié contre la production n'a été rejoué
au-delà des six canaris.

### Dette relevée, non traitée

- **Dette i18n restante** : 11 entrées de ratchet côté template pour 66 lignes,
  et `knowledge-capture.component.ts` concentre à lui seul ~282 littéraux.
- **Trois défauts QA constatés, non corrigés faute d'arbitrage** : les libellés
  indicatifs de l'overlay de chat débordent et se coupent sur deux lignes dans
  les quatre cellules (arbitrage de largeur) ; la copie des catalogues
  `connectors` et `resources` reste anglaise en locale FR (antérieur à la
  fenêtre) ; l'écran de publication expose `source_type` en pleine phrase
  utilisateur.
- **Terminal d'exécution du Flow Builder** : il imprime encore la phrase brute
  de l'analyseur en anglais. C'est un journal, registre technique, mais il
  pourrait réutiliser la correspondance code → message écrite pour le bandeau.
- **Messages de `capture-engine`** : résolus au moment de l'événement puis
  stockés en signal, ils ne se retraduisent pas si l'utilisateur change de
  langue en cours de session.

## Itération du 12/08 (après-midi) — déployée sur `5b51f5fc`, dette de libellés monolingues soldée

Suite directe de `ec934d64`, par la boucle courte. Le ratchet de dette i18n
passe de **douze entrées à deux** : `knowledge-capture.component.ts` livrait à
lui seul 282 libellés en français uniquement, et le panneau de chat, Client360,
la base de connaissances et la moitié template de mission-room étaient dans le
même cas. Le dictionnaire passe de ~2 940 à **3 200 clés**, chacune dans les
deux langues — la contrainte de type `Record<keyof typeof X_FR, string>` rend la
parité vérifiable par `tsc`, pas seulement par la garde.

**Incrément purement frontend.** Ni migration, ni dépendance nouvelle :
`alembic current` rend `084_decision_condition_repair` avant et après. Les trois
images sont tout de même reconstruites, parce que le tag est commun aux cinq
services et que `build-info` doit refléter le SHA réellement déployé.

### Portails locaux

| Portail | Observé |
|---|---|
| `npm run check:i18n` | sortie 0 — **3 200** clés, 11 domaines, 172 templates, 206 fichiers de code, 20 règles de lexique |
| `npm run check:ui-chrome` | sortie 0 |
| Unitaires front | **857/857** |
| `tsc -p tsconfig.app.json --noEmit` | sortie 0 |
| Build AOT | réussi, seuls les avertissements préexistants |

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `4f61d0be` → `5b51f5fc` |
| Ancre + worktree | `pull --ff-only` sur l'ancre, worktree de build détaché sur le même SHA |
| Build | trois images au tag `5b51f5fc0e9b`, `AGENTIUM_IMAGE_REVISION` en 40-hex (~8 min) |
| Dump | **aucun** — ni schéma ni graphes stockés ne bougent |
| `storage-check` | sortie 0, rejoué dans `up` |
| `up` | cinq services recréés, `RestartCount=0` sur tous |
| `build-info` | `revision: 5b51f5fc0e9b7c1fda9aa207fdfd280fd3962504`, `revision_verified: true` |
| Alembic | `084_decision_condition_repair` avant **et** après |
| Conteneurs | **13**, sains **9** — compte nominal inchangé |
| Logs | **0** `ERROR`, **0** `Traceback` depuis la bascule |
| Canaris carakai | **6/6 vertes** au premier passage, artefacts `/tmp/iteration-canaries-20260812T160213Z.I0RAO6` |
| Alias | `demo-agentic` déplacé sur `5b51f5fc0e9b` après les canaris |

### Ce que la fenêtre apprend sur la dette elle-même

Une part importante du travail n'a pas été de traduire mais de **câbler** : tout
le bloc campagnes de Client360 existait déjà, écrit dans les deux langues, sans
aucun site d'appel. C'est le troisième incrément consécutif où ce motif
apparaît. Une clé écrite mais jamais lue ne déclenche aucune alerte — ni la
garde de parité, ni le typage ne voient l'absence d'appel — donc cette forme de
dette est invisible jusqu'à ce qu'on ouvre l'écran.

Deux littéraux de `knowledge-capture` sont reclassés en DATA plutôt qu'en dette :
`isRuntimeCapturePrompt()` teste `pour l'objectif` et `quelle décision experte`
dans des prompts produits par le backend, pour reconnaître une relance générée à
l'exécution. Ce sont des aiguilles de détection, jamais du texte affiché ; les
traduire casserait la reconnaissance, exactement comme pour la table
d'anonymisation de mission-room.

Une régression rencontrée en chemin mérite d'être notée : injecter
`I18nService` dans `SseService` cassait deux specs qui construisent un injecteur
isolé. L'injection est devenue optionnelle avec repli sur la clé, si bien que le
transport reste constructible hors racine — corrigé sans toucher à une seule
assertion.

### Termes internes retirés de l'écran

« V2V » devient « Assistant transversal, écrit et vocal » ; « oracle de
contexte » devient « repères de contexte » ; « Drill du sentiment » devient
« Détail du sentiment » ; « fallback HTTP » devient « mode de secours ». Les
noms `LiveKit` et `WebSocket` sortent des bascules de transport vocal au profit
de « pont temps réel » et « session vocale continue ».

Restent exposés, déjà listés dans l'allowlist de lexique : « HITL » en libellé
principal dans `capabilities`, `steering` et `system-builder`, et « ingress »
dans `flow-runner`.

### Dette relevée, non traitée

La paire mission-room est le seul DEBT restant : `mission-room.component.ts`
(73 littéraux) et `mission-control-monitor.component.ts` (31). Les deux mêlent,
dans le même corps de classe, du contenu de scénario semé — documents sécurité,
articles de presse, verbatims AYA, noms propres de zones et de personas — et de
la vraie chrome. Relever la chrome ligne à ligne laisserait ses voisines sans
accent (`Reputation`, `Presse`, `Explorer`) en dur juste à côté, invisibles aux
sondes. Le ratchet reste donc à sa valeur mesurée plutôt que déclaré DATA en
bloc : ce qu'il faut ici est un découpage fixture/chrome, pas un relevé.

## Itération du 12/08 (soir) — déployée sur `5facb2a7`, emblème de marque pour le thème clair

Première fenêtre depuis le 10/08 à embarquer une migration : **085
`nawa_brand_light_emblem`**, sur `084_decision_condition_repair`. Dump
checksummé pris avant, pas de répétition sur copie restaurée — la migration
n'ajoute qu'une clé au JSON `settings` d'un seul workspace, elle ne touche ni le
schéma ni des graphes stockés.

### Le défaut, et pourquoi il n'est pas une régression du thème

En mode clair, la barre de titre affichait le logo NAWA sur une plaque noire
arrondie. `nawa-logo.png` est en réalité un **JPEG sans canal alpha** : le noir
est dans les pixels, aucune règle CSS ne peut l'enlever. Un commentaire du code
l'avouait déjà — le rayon d'arrondi servait à « adoucir les coins opaques d'un
logo livré sans canal alpha ».

Les écrans métier `features/nawa/` géraient déjà les deux cas via
`NAWA_LOGO = { dark, light }`. La barre de titre, elle, ne lit qu'une URL unique
depuis `workspace.settings.platform_brand` et n'a jamais su choisir. Le défaut
était donc **latent depuis l'origine** ; le mode clair, déployé le 12/08 au
matin, l'a simplement rendu visible. Tant que le cockpit était toujours sombre,
la plaque noire se fondait dans le fond.

Un seul fichier ne peut pas servir les deux thèmes : la copie détourée porte une
encre gris-anthracite, illisible sur le fond sombre. Teinter par filtre CSS
abîmerait le W orange de la marque.

### Le correctif, générique et non spécifique à NAWA

`platform_brand` accepte désormais un `emblem_light` **optionnel**, que la barre
de titre utilise quand `ThemeService.resolved()` vaut `light`. Le champ ne
participe pas au contrôle de complétude : `label` et `emblem` restent seuls
obligatoires, et deux tests pinnent qu'`emblem_light` seul ne valide jamais une
marque. **Un tenant qui ne déclare pas de variante ne voit rien changer** — une
cellule de QA rejoue volontairement le défaut d'origine pour l'attester.

Le rayon d'arrondi est conditionné plutôt que supprimé : il ne disparaît que
pendant que la variante détourée est à l'écran, puisque c'est là qu'il n'y a
plus de coin opaque à adoucir et qu'arrondir rognerait le wordmark. En sombre,
NAWA garde le JPEG et son rayon.

Le **favicon n'est délibérément pas câblé**. L'onglet du navigateur suit le
thème de l'OS, pas la préférence tri-state de l'application : le brancher sur
`ThemeService` donnerait le mauvais résultat aussi souvent que le bon. À faire
un jour, ce serait sur `prefers-color-scheme`, et il faudrait rendre
`FaviconService` réactif — il ne se réveille aujourd'hui que sur la navigation.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `538a1f57` → `5facb2a7` |
| Build | trois images au tag `5facb2a7ef67`, revision 40-hex (~8 min) |
| Dump | `postgres-pre-085.dump`, **450466467** o, **1219** entrées TOC, triplet `.sha256`/`.ready` en `0600` sous `/srv/agentium-data/brand-emblem-deployments/2026-08-12-5facb2a7ef67` (`0700`), `sha256sum -c` **OK** |
| `storage-check` | sortie 0, rejoué dans `migrate` puis dans `up` |
| `migrate` | `084` → `085_nawa_brand_light_emblem` |
| Marque après migration | `emblem_light: /assets/nawa/nawa-logo-transparent.png` ajouté, les trois champs d'origine intacts |
| `up` | cinq services recréés, `RestartCount=0` sur tous |
| `build-info` | `revision: 5facb2a7ef67013e667e0bc39d5b49401ae9d146`, `revision_verified: true` |
| Alembic après bascule | `085_nawa_brand_light_emblem (head)` |
| Asset | `/assets/nawa/nawa-logo-transparent.png` servi en **200** |
| Conteneurs | **13**, sains **9** |
| Logs | **0** `ERROR`, **0** `Traceback` |
| Canaris carakai | **6/6 vertes** au premier passage, artefacts `/tmp/iteration-canaries-20260812T163225Z.m3qpHI` |
| Alias | `demo-agentic` déplacé sur `5facb2a7ef67` après les canaris |

### Deux pièges rencontrés, à retenir

**Les identifiants de workspace en production sont des UUID**, pas les
`workspace-nawa` des jeux d'essai. Une migration qui désignerait le workspace
par cet identifiant serait silencieusement sans effet. La 085 sélectionne par
`slug == "nawa"`, comme la 065 — vérifié avant de migrer, et la marque en base
correspondait exactement au littéral `PLATFORM_BRAND` de la 065, condition pour
qu'elle soit complétée.

**Entre `migrate` et `up`, `alembic current` échoue dans le conteneur backend
encore en vol** : il tourne sur l'image précédente, qui ne contient pas le
fichier de la 085, et ne sait donc pas résoudre la révision que la table de
version porte désormais. C'est attendu et bénin ; la révision se lit
normalement après la bascule. Ne pas le lire comme une migration ratée.

**`/tmp` n'est pas inscriptible sur la VM**, même via `sudo sh -c`. Un dump doit
être écrit directement dans son répertoire de fenêtre sous `/srv/agentium-data`.
Le rôle PostgreSQL est `agentium`, pas `postgres`.

## Itération du 13/08 (matin) — déployée sur `92b32ce4`, quatre correctifs pré-démo flow builder

Frontend uniquement, aucune migration, pas de dump. Les quatre correctifs
répondent aux plaintes de la passe QA du 11/08 avant la démo :

1. **Scratchpad silencieux** — `/orchestration` s'ouvre vide (le guide premier
   Flow remplace le gabarit Objective/Retrieve/Generate/Output qui levait deux
   avertissements de validation avant tout geste utilisateur).
2. **Barre auteur allégée** — la ligne auteur ne garde que la boucle d'édition ;
   zoom avant/arrière, Ranger et Vérifier passent sous « Plus ».
3. **Retour System unifié** — le lien verrouillé du system-builder mène à
   `/systems/:id/flow` au lieu de `/orchestration?systemId=…`.
4. **Contrat de sortie sans jargon** — le repli de l'inspecteur abandonne
   « fige le schéma catalogue » pour une formulation en langage clair (FR+EN).

Deux tests e2e ont dû suivre l'UI : `17-flow-palette-density` pré-sème
désormais son flow dans `localStorage` (il comptait sur le gabarit disparu), et
`16-flow-builder-authoring-contract` ouvre « Plus » avant de cliquer Vérifier.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `0da237b6` → `92b32ce4` |
| Build | trois images au tag `92b32ce4d067` |
| `storage-check` | sortie 0 |
| `up` | services recréés sans migration |
| `build-info` | `revision: 92b32ce4d06726dbaa0beedc275ecd69381a8d28`, `revision_verified: true` (revérifié le 13/08 à 08:30 UTC) |
| Canaris carakai | **6/6 vertes**, artefacts `/tmp/iteration-canaries-20260813T081120Z.W52OlZ` (`playwright-runtime.json` : `candidate_sha 92b32ce4…`, `result: passed`) |
| Alias | `demo-agentic` sur `92b32ce4d067` pour les trois images (ids identiques vérifiés) |

### Répétition navigateur sur la prod (13/08, 08:15–08:25 UTC)

Les trois actes de la démo ont été rejoués au navigateur sur
`https://agentium.papai.ai` : scratchpad vide, barre épurée + « Plus » complet,
retour Skills → System sans perte de contexte, copy de l'inspecteur adoucie,
wizard « + New skill » (4 étapes, 3 presets, aides BRD), et un test de brouillon
réel `{"collection_slug": "po-invoice-recon-demo"}` — run
`4648085f-bf68-44e4-85fa-70a81790604d` (surface `draft_test`) completed en ~1 s,
verdict Needs Review, audit `938e5860…`, 0 appel LLM. Le cron quotidien continue
de produire son run à 07:00 UTC (`951c838a…` le 13/08, `e5668f9e…` le 12/08).

Le script présentateur à jour est
`docs/demo-runs/2026-08-13-nawa-po-invoice-recon-v2/DEMO-SCRIPT.md`.

## Itération du 13/08 (midi) — déployée sur `0a3534f2`, vague de résorption i18n P0→P3

Quatre commits sur `demo/agentic` (`981c3b46` → `0a3534f2`), un par palier de la
QA visuelle bilingue du matin sur la prod. La dette anglaise-en-FR relevée sur
onze familles de surfaces est soldée : détail de run et chrome du chat (P0),
portail de dépôt, base de connaissances, shell du chat workspace et feed
hyperviseur (P1), Steer/contexts/suite Govern/workspace/compte/presets/missions
(P2), catalogues resources/connectors/apps, palette Flow, aria de l'aide et
résumé RSS backend (P3). Le dictionnaire passe à **5 219 clés sur 18 domaines**
(7 nouveaux : contexts, deposit, governance, knowledge, resources, settings,
tasks), parité FR/EN garantie par contrat de type + garde + spec de parité des
placeholders.

Décisions notables de la vague :

- **Feed hyperviseur** : les titres backend à motifs fixes (« Run failed · … »,
  « High-yield outcome · ROI … ») sont mappés motif→clé côté frontend avec
  interpolation ; tout titre non reconnu (raisons d'auto-éval, recommandations)
  s'affiche verbatim — la donnée reste de la donnée.
- **Surface-map Govern** : traduction au rendu par clé dérivée de l'id d'entrée,
  repli sur le catalogue de routes non modifié ; les entrées au wording banni
  (« jobs ») ou aux noms propres de tenant restent en repli assumé.
- **Chrome partagée sans propriétaire** : `run-outcome-card` (SKILL LEDGER,
  DECISION…), `ck-tabs` (More) et `ck-object-perspective` (états de facts,
  titres de lens) migrés vers `runs.outcome.*` et `common.perspective/tabs.*`.
  Les titres de lens FR utilisent une apposition neutre (« Comment cet objet
  ({name}) est construit ») : les libellés d'objet sont de genres mêlés.
- **Backend** : le résumé RSS de repli de `batch.py` perd son français sans
  accents servi dans les deux langues au profit d'un anglais propre.
- **Ratchet** : budget hardcodedText de `chat-knowledge-settings` resserré de
  7 à 4 — ne restent que les exemples de données FR que l'admin saisit.

### Portails locaux

| Portail | Observé |
|---|---|
| Garde i18n | sortie 0 — 5 219 clés, 18 domaines, 20 règles de lexique, aucune note de ratchet restante |
| Unitaires front | **863/863** (specs touchés dotés du provider `I18nService`, motif NG0201) |
| Build AOT | `npx ng build -c production` vert, seuls les warnings CommonJS préexistants |
| E2E palette | `16-flow-builder-authoring-contract` et `17-flow-palette-density` verts contre le build local (`E2E_BASE_URL=http://localhost:4200`) — obligatoires, la palette rend désormais ses descriptions traduites |

### Observables du déploiement

| Pas | Observé |
|---|---|
| Garde-fou | diff `92b32ce4..0a3534f2` **vide** sur `agentium-livekit.yaml`, `realm-export.json`, thème Keycloak |
| Push | `demo/agentic` en fast-forward `3c029d06` → `0a3534f2` |
| Ancre + worktree | `pull --ff-only` et `fetch` + `merge --ff-only FETCH_HEAD`, les deux sur `0a3534f2`, statut vierge |
| Build | trois images au tag `0a3534f2a14d` (~7,8 min), révision 40-hex vérifiée sur les trois |
| Dump | **aucun** — ni schéma ni graphes stockés ne changent (frontend + une chaîne backend) |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés, backend et frontend `healthy` |
| `build-info` | `revision: 0a3534f2a14d655a285ea8755b5b876e5dab317c`, `revision_verified: true` |
| Alembic | `085_nawa_brand_light_emblem` avant **et** après — aucune migration |
| Logs | 0 `error`/`traceback`/`exception` backend depuis la bascule |
| Canaris carakai | **6/6 vertes** en 57,8 s au premier passage, artefacts `/tmp/iteration-canaries-20260813T111445Z.IO043H` (`candidate_sha 0a3534f2…`, `result: passed`) |
| Alias | `demo-agentic` déplacé sur `0a3534f2a14d` pour les trois images (ids identiques vérifiés) ; rollback : `AGENTIUM_IMAGE_TAG=92b32ce4d067` |

Piège rejoué : l'`origin` du checkout carakai est un bundle `/tmp` périmé — le
`fetch` « réussit » sans apprendre le nouveau SHA, et le premier bundle
incrémental a échoué sur prérequis (`3c029d06` inconnu de carakai, le tip y
était `b0ce840a`). Bundle refait depuis `b0ce840a..demo/agentic`, sha256
identique des deux côtés, `cat-file -e` vérifié avant les canaris.

### Dette relevée, non traitée

- `hypervisor.col.capability` = « CAPACITÉ » en FR alors que le lexique impose
  « Capability » (la nouvelle clé `hypervisor.scope.capability` est conforme) —
  clé préexistante, à corriger dans une passe dédiée.
- Les mots bannis sous allowlist lexique restent à l'écran en attendant la
  passe flow-clarity : « catalog only » (apps), « Pipeline mode » (presets),
  « HITL » (capabilities, steering, system-*), « ingress » (flow-runner).
- `rpa_bridge` (connecteur et app) reste en repli brut : son wording tiers
  contient « jobs ».
- Le catalogue bilingue backend (`seed.py`, descriptions skills/capabilities)
  reste un choix produit ouvert — les descriptions de skills dynamiques
  s'affichent telles quelles dans la palette, par conception.

## Itération du 13/08 (après-midi) — déployée sur `664e68b7`, fiabilisation chat Client360

Un commit backend-only sur `demo/agentic` (`0a3534f2` → `664e68b7`), issu de la
QA de préparation de la démo Client360 andritz. Deux flakes bloquants pour une
démo corrigés dans `client360_chat.py` :

- **Résolution client non déterministe** : le vocabulaire envoyé au LLM de
  traduction NL ne contient pas les noms de clients ; quand le modèle omettait
  le filtre `customer`, son résultat (même vide) court-circuitait l'extraction
  déterministe qui, elle, trouvait le client dans les facettes. « audite
  Septona » échouait donc aléatoirement. L'extraction déterministe comble
  désormais toute facette omise par le LLM (le LLM garde la priorité sur ce
  qu'il a résolu).
- **Pont forecast jamais branché** : `_call_forecast_helper` sondait des noms
  de fonctions (`customer_forecast`, `forecast_customer`…) qui n'ont jamais
  existé dans `client360_forecast` — l'intent répondait « moteur forecast
  indisponible » depuis sa création. Il appelle désormais le vrai point
  d'entrée `customer_next_due` (signature keyword-only `customer_key`,
  normalisation via `normalize_customer_key`).

### Observables du déploiement

| Pas | Observé |
|---|---|
| Garde-fou | diff `0a3534f2..664e68b7` : 3 fichiers (`client360_chat.py`, son test, ce runbook) — rien sur livekit/realm/thème Keycloak |
| Ancre + worktree | `pull --ff-only` (ancre) et `fetch` + `merge --ff-only FETCH_HEAD` (worktree), les deux sur `664e68b7`, statuts vierges |
| Build | trois images au tag `664e68b760de` en 7 min 43 s, révision 40-hex vérifiée sur les trois |
| Dump | **aucun** — backend-only, ni schéma ni graphes stockés ne changent |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés (12:32:25Z), backend et frontend `healthy`, `agentium-sftp` intouché |
| `build-info` | `revision: 664e68b760dea9eed596edf6610c59eff94f001a`, `revision_verified: true` |
| Alembic | `085_nawa_brand_light_emblem` avant **et** après — aucune migration |
| Logs | 0 `error`/`traceback`/`exception` backend depuis la bascule, y compris pendant la QA |
| Canaris carakai | **6/6 vertes** en 56,7 s au premier passage, artefacts `/tmp/iteration-canaries-20260813T123653Z.bg7kvH` (`candidate_sha 664e68b7…`, `result: passed`) |
| Piège bundle | rejoué : carakai ne connaissait pas `664e68b7` — bundle incrémental `0a3534f2..demo/agentic`, sha256 identique des deux côtés, `cat-file -e` avant lancement |
| Alias | `demo-agentic` déplacé sur `664e68b760de` (ids identiques sur les trois) ; rollback : `AGENTIUM_IMAGE_TAG=0a3534f2a14d` puis `up` |

Vérification post-bascule sur le workspace `andritz`, trois processus
indépendants par requête : « audite Septona » → `customer_audit` stable (260
opportunités, 2,14 M€) ; « quelles pièces à prévoir chez Septona ? » →
`forecast` avec 2 échéances déterministes (plus jamais « indisponible ») ;
« hello » → `help`, 0 source. QA campagne : campagne « Relance échéances PDR —
S35 » créée (`c0faeb3e…`, ciblage `status=detected` + 5 clés clients), stats
374 opportunités / potentiel 2 316 421,78 € / expected_value 295 343,78 € avec
disclaimer ; brouillon témoin mono-opportunité `ai_assisted` (gpt-5,
`prompt_hash` présent, action de validation créée). Aucun envoi SMTP.

### Dette relevée, non traitée

- **Aucune opportunité ne porte d'email de contact** (`metadata.contact.email`
  vide sur les 402) : la génération de brouillons en lot sort à 0
  (`missing_contact_email: 374`). Le dédoublonnage fonctionne, mais l'onglet
  Campagnes ne peut pas produire de lot tant que les données sources n'ont pas
  d'emails — la voie mono-brouillon depuis la fiche opportunité reste la voie
  démontrable.
- **Clés clients dupliquées** (vestige de deux normalisations) : `septona s a`
  / `septona`, `karafiber tekstil` / `…sanayi ve ticaret`, etc. Conséquence
  cosmétique : `targeted_customers=5` pour 3 clients réels. Le chat agrège
  correctement ; à résorber par une passe de re-normalisation des
  `customer_key` persistés.
- La campagne S35 reste en `draft` avec 0 brouillon (bascule auto vers
  `active` au premier brouillon de lot).

## Itération du 13/08 (soir) — déployée sur `e678d21a`, page de connexion split-screen

Un commit frontend-only sur `demo/agentic` (`a86bd5c6` → `e678d21a`). La carte
centrée cède la place à un panneau instrument (orbe `ck-thinking-orb` vivant
dans des anneaux orbitaux, graphe générique Objectif → Restitution) et une
colonne d'accès. Formulaire, MFA et erreurs passent par i18n ; le contrat
`signin-experience` (profil Sentinel) reste hors dictionnaire.

Deux commits Client360 (`283fd586`, `ba3b224b`) ont atterri sur le tip après
le push de cette itération ; **ils ne sont pas dans les images servies**.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Garde-fou | diff `a86bd5c6..e678d21a` : 3 fichiers (`auth-shell`, `signin`, `chrome.dict`) — rien sur livekit/realm/thème Keycloak |
| Ancre + worktree | `pull --ff-only` et `fetch` + `merge --ff-only FETCH_HEAD`, les deux sur `e678d21a` au moment du build |
| Build | trois images au tag `e678d21aa76b` en ~8 min, révision 40-hex vérifiée sur les trois |
| Dump | **aucun** — frontend-only, ni schéma ni graphes stockés ne changent |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés, backend et frontend `healthy`, `agentium-sftp` intouché (Up 6 days) |
| `build-info` | `revision: e678d21aa76bffbb07a75d6e478eaaa311bd3992`, `revision_verified: true` |
| Alembic | `085_nawa_brand_light_emblem` avant **et** après — aucune migration |
| Logs | 0 `error`/`traceback`/`exception` backend depuis la bascule |
| Canaris carakai | **6/6 vertes** en 57,5 s au premier passage, artefacts `/tmp/iteration-canaries-20260813T152250Z.al600y` (`candidate_sha e678d21a…`, `result: passed`) |
| Piège bundle | rejoué : carakai ne connaissait pas `e678d21a` — bundle incrémental `664e68b7..demo/agentic` (sha256 `76c8fe8a…` identique des deux côtés), `cat-file -e` avant lancement. Le checkout runner reste à `8fbf440b` |
| Alias | `demo-agentic` déplacé sur `e678d21aa76b` (ids identiques sur les trois) ; rollback : `AGENTIUM_IMAGE_TAG=664e68b760de` puis `up` |

## Itération du 23/08 — déployée sur `6d15e521`, AgentLoop + Experience apps

GO deploy depuis un Cloud Agent. `origin/demo/agentic` avançait de
`491ca889` (live) à `6d15e521` : Experience no-code (`22ede41f`, migrations
`093` + `094`) puis AgentLoop L0–L5 (`decide_next_v1`, kind `agent_loop`,
HITL intra-loop, privilege tiers, steer, fan-out). Le premier `build:prod`
VM a échoué : `agent_loop_no_budget` / `agent_loop_allowlist` absents de
l'union `FlowValidationIssue` — corrigé par `6d15e521` avant le switch.

Canaris carakai joués le 23/08 contre le SHA live (clé acceptée). Le
checkout runner était à `8fbf440b`, origin = bundle `/tmp` périmé. Bundle
incrémental `8fbf440b..demo/agentic` (sha256
`bdc5dfc1d07c08d34ab4e589d060d550141ea19dc663da16f5faf3f017146a7c`
identique des deux côtés), `cat-file -e`, checkout détaché `6d15e521`,
marqueur `.agentium-source-sha` aligné. Dépendances gelées retargetées
`e2d45039…` → `a59bcb33…` (`npm ci` du lock du candidat, `@axe-core/playwright`
présent). Ancien tree `frontend-deps-e2d45039…` conservé.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `491ca889` → `6d15e521` (dont `3fadcc73` docs SSH + `6d15e521` union TS) |
| Ancre | `/home/ubuntu/omnirag` **intouchée** (`56a9c57b`) |
| Worktree | `fetch origin demo/agentic` + `merge --ff-only FETCH_HEAD` → `6d15e52151e003aafabf39fb6b602370d5a9da0a`, porcelain vide |
| Build | trois images au tag `6d15e52151e0`, label 40-hex identique sur backend / worker / frontend |
| Dump | `/srv/agentium-data/agentloop-deployments/2026-08-23-6d15e52151e0/pre-6d15e52151e0.dump` sha256 `8b1d56b44207c2ec3d4939ac699b574c5396ae7a3ef8eaf672eabcecaed96d04` |
| `migrate` | `092_experience_access_policy` → `093_experience_run_idempotency` → `094_experience_brand_history` |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés (07:17:19Z), backend et frontend `healthy` |
| `build-info` | `revision: 6d15e52151e003aafabf39fb6b602370d5a9da0a`, `revision_verified: true` (localhost Host + `https://agentium.papai.ai`) |
| Alembic | `094_experience_brand_history (head)` après bascule |
| Logs | 0 `traceback`/`exception` backend depuis la bascule ; `/` = 200 |
| Infra | `agentium-sftp`, LiveKit, pg, Keycloak, Qdrant, MinIO, RabbitMQ intouchés (Up 2 weeks) |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `400f1bdf452c`) |
| Canaris carakai | **5 passed / 3 failed** en 1,2 min, artefacts `/tmp/iteration-canaries-20260823T072846Z.CZra7M` (`playwright-runtime.json` : `candidate_sha 6d15e521…`, producer `result: passed`). Spec 12 (5) verte. Échecs : **11** rail `Build` absent sous `experience_v1` (le verbe ouvre Create), **16** `GET /work` = 0 Experience Pilot/In-service, **17** overflow title-bar à 320px (`415 > 321`). |
| Rollback | migration déjà appliquée : pas de restore dump. Images précédentes : `AGENTIUM_IMAGE_TAG=491ca889579b` puis `up` uniquement si on accepte un backend sans colonnes 093/094. Sinon fix-forward. |

## Itération du 23/08 — Builder AgentLoop UX sur `18eba715`

GO deploy depuis un Cloud Agent. Slice frontend-only : inspecteur AgentLoop
(enveloppe goal / allowlist / budget / privilege), porte humaine, starter
`Trigger → Agent loop → Human gate → Output`. Aucune migration Alembic.
`build:prod` local puis VM vert après `18eba715` (privilege fail-closed).

Canaris carakai : checkout runner était à `6d15e521`, origin = bundle
`/tmp` périmé. Bundle incrémental `6d15e521..demo/agentic` (sha256
`008eefdc30f31fb5ffd064e5de359e701659e07f7755a250f2f038c04f094e3a`
identique des deux côtés), `cat-file -e`, checkout détaché `18eba715`,
marqueur `.agentium-source-sha` aligné. `node_modules` symlink inchangé
(lock `a59bcb33…`).

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `8e4a8711` → `18eba715` (`d8ac82c8` inspector + `18eba715` type-gate privilege) |
| Ancre | `/home/ubuntu/omnirag` **intouchée** (`56a9c57b`) |
| Worktree | `fetch origin demo/agentic` + `merge --ff-only FETCH_HEAD` → `18eba7156650f325a29459f4bae2406a881adbed`, porcelain vide |
| Build | trois images au tag `18eba7156650`, label 40-hex identique sur backend / worker / frontend |
| Dump | aucun — pas de fichier sous `backend/alembic/versions/` dans le delta |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés, backend et frontend `healthy` |
| `build-info` | `revision: 18eba7156650f325a29459f4bae2406a881adbed`, `revision_verified: true` (localhost Host) |
| Logs | 0 `traceback`/`exception` backend depuis la bascule ; `/` = 200 |
| Infra | `agentium-sftp`, LiveKit, pg, Keycloak, Qdrant, MinIO, RabbitMQ intouchés (Up 2 weeks) |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `400f1bdf452c`) |
| Canaris carakai | **5 passed / 3 failed** en 1,2 min, artefacts `/tmp/iteration-canaries-20260823T081941Z.LUneEX` (`playwright-runtime.json` : `candidate_sha 18eba715…`, producer `result: passed`). Spec 12 (5) verte. Échecs inchangés vs `6d15e521` : **11** rail `Build` absent sous `experience_v1`, **16** `GET /work` = 0 Experience Pilot/In-service, **17** overflow title-bar à 320px (`415 > 321`). |
| Rollback | pas de migration : `AGENTIUM_IMAGE_TAG=6d15e52151e0` puis `up`. |

## Itération du 24/08 — Nœud « Recette Python » sur `4a1c2a49`

GO deploy depuis un Cloud Agent. `origin/demo/agentic` avançait de
`18eba715` (live) à `4a1c2a49` : plan d'exécution des recettes Python
(`6fbf1550` venvs content-addressed + tâches Celery + API, migration
`095_python_recipes`), tests (`30101df8`), atelier Flow Builder CodeMirror
(`005c8f70`), admission du store `/srv/agentium-data/recipe_envs` dans le
contrat de stockage (`fa688667`, montage **worker seul** `/data/recipe_envs`,
cible transitionnelle tolérée sur l'ancienne génération pendant la bascule),
puis trois correctifs trouvés par la boucle e2e sur la VM (ci-dessous).

Quatre générations d'images ont été construites et basculées dans la même
fenêtre — la boucle e2e a servi de découvreur de défauts :

1. `fa688667` (07:45, `migrate` 095 + `up`) : le setup e2e a échoué deux
   fois — la skill seedée `python_recipe_v1` était **non réclamée** par une
   capability, donc filtrée du catalogue (`skill_not_visible`, palette grisée,
   binding System refusé).
2. `af06849a` : capability universelle « Python Recipes » réclame la skill
   (seed + test épinglant la réclamation). Runs A/B verts ; l'annulation (Run C)
   a montré que l'enveloppe d'échec du walker rejouait le bloc `_recipe`
   (script complet, jusqu'à 200 Ko) dans `output_ref`.
3. `b5a6075a` : le walker retire `_recipe` des enveloppes d'échec de nœud
   task (`_passthrough_without_recipe` + test e2e DAG). Scénario e2e complet
   vert à 08:39.
4. `4a1c2a49` : attestation seulement — à 08:41 l'orchestrateur carakai a
   refusé **avant tout test** (« frontend dependency lock differs », dossiers
   artefacts vides) : `PACKAGE_LOCK_SHA256` ne connaissait pas le lock
   CodeMirror. Constante retargetée, rebuild/rebascule pour garder
   l'invariant checkout HEAD == SHA déployé.

Canaris carakai : checkout runner avancé `18eba715` → `4a1c2a49`,
dépendances gelées retargetées `a59bcb33…` → lock `95689c8c…` (`npm ci` du
lock candidat avec `codemirror` + `@codemirror/lang-python`), ancien tree
conservé.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `18eba715` → `4a1c2a49` (8 commits, dont le journal 23/08) |
| Ancre | `/home/ubuntu/omnirag` **intouchée** (`56a9c57b`) |
| Worktree | `4a1c2a493df67caa928a958e2a6d7c3ae913a5db`, porcelain vide |
| Build | quatre générations (`fa6886672f73`, `af06849a7ab4`, `b5a6075a0894`, `4a1c2a493df6`), label 40-hex identique sur backend / worker / frontend à chaque bascule |
| Dump | `/srv/agentium-data/recipe-deployments/2026-08-24-fa6886672f73/pre-fa6886672f73.dump` sha256 `a2e97e73028cd445d756eea43a807e07d4255865917e07f735389efc944a8557`, pris avant l'unique `migrate` |
| `migrate` | `094_experience_brand_history` → `095_python_recipes` (une seule fois, les rebascules suivantes étaient sans migration) ; `alembic current` = `095_python_recipes (head)` |
| `storage-check` | sortie 0 au tag final, autonome puis rejoué dans `up` — inclut le nouveau garde `recipe_envs` (bind `/dev/sdb`, UID 1000, env `AGENTIUM_RECIPE_ENVS_PATH`) |
| `up` | cinq services applicatifs recréés (dernière bascule 08:53:06Z), backend et frontend `healthy` |
| `build-info` | `revision: 4a1c2a493df67caa928a958e2a6d7c3ae913a5db`, `revision_verified: true` (`https://agentium.papai.ai`) ; `/` = 200 |
| Logs | 0 `traceback`/`exception` backend **et worker** depuis la bascule finale |
| Infra | `agentium-sftp`, LiveKit, pg, Keycloak, Qdrant, MinIO, RabbitMQ intouchés (Up 2 weeks) |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `400f1bdf452c`) |
| Canaris carakai | **5 passed / 3 failed** en 1,2 min, artefacts `/tmp/iteration-canaries-20260824T085353Z.49IYJ4` (`playwright-runtime.json` : `candidate_sha 4a1c2a49…`, `package_lock_sha256 95689c8c…`, producer `result: passed`). Spec 12 (5) verte, 5 artefacts `evidence/`. Échecs inchangés vs `18eba715` : **11** rail `Build` absent sous `experience_v1`, **16** `GET /work` = 0 Experience Pilot/In-service, **17** overflow title-bar à 320px (`415 > 321`). |
| Rollback | migration 095 additive appliquée : `AGENTIUM_IMAGE_TAG=18eba7156650` puis `up` si on accepte un backend sans `python_envs`/`recipe_executions` ; sinon fix-forward, dump vérifié en recours |

### Scénario e2e recette (driver API, Système `test`, node runs workbench)

Environnement `pandas` : fingerprint `92a4d755…`, 149 778 965 octets, lock
`pandas 3.0.5 / numpy 2.5.2 / python-dateutil 2.9.0.post0 / six 1.17.0`.

| Phase | Observé |
|---|---|
| Run A (1er run) | 21,3 s ; exécution `queued → env_building → running → succeeded` (build 16,98 s, téléchargements pip) ; sortie `pandas_version 3.0.5` ; run `completed` |
| Run B (réutilisation) | 4,1 s ; `running → succeeded`, **aucun** `env_building`, `use_count` 1 → 2 |
| Run C (annulation) | sleep 90 s, cancel API à ~1 s ; exécution `running → cancelled`, run `completed` avec enveloppe `{"seconds": 90, "_error": "recipe_execution_cancelled: cancel_requested", "_status": "failed"}` — **sans** `_recipe` (contrat continue-on-error du walker) |
| Éviction | `DELETE /python-envs/{id}` → row `evicted` + dispatch du sweep vers le worker (le backend ne monte pas le store) ; sweep `orphan_dirs_removed=1`, disque 157 Mio → 28 Mio (cache pip seul) |
| Run D (rebuild) | 18,0 s ; `env_building → running → succeeded`, build log « Using cached …whl » sur les quatre paquets (cache pip chaud, zéro re-téléchargement), même lock, `use_count` 5 |
| Atelier UI (live) | workshop CodeMirror ouvert depuis l'inspector, env `READY` (Python 3.12, 143 Mio, versions verrouillées), test isolé `QUEUED → … → SUCCEEDED` en ~11 s avec sortie JSON et stdout — enregistrement vidéo archivé côté agent |

## Itération du 24/08 (bis) — Polish QA recettes sur `f31eecad`

GO deploy depuis un Cloud Agent, suite directe de la QA du matin : les
quatre items de polish qualifiés non bloquants sont corrigés et livrés.
Cinq petits commits (`1b16cb0b` → `f31eecad`), aucune migration Alembic,
aucun changement de lock frontend (l'attestation `95689c8c…` reste valide).

- `1b16cb0b` — le `flow-schema-editor` partagé (inspector, atelier E/S,
  éditeur d'entrée) parle le dictionnaire : « Dériver des ports » /
  « Effacer » / « Déclaré — c'est ce que la publication fige. » (FR+EN,
  clés `flow.schema.*`) au lieu d'anglais en dur dans toutes les locales.
- `aae14a8a` — l'onglet Test de l'atelier ne montre plus le code machine
  (`cancel_requested`, `recipe_exit_1: …`) : `recipeExecutionReason()`
  projette l'inventaire complet des codes du superviseur sur des clés
  `flow.recipe.reason.*` + détail utile (dernière ligne stderr, erreur de
  build) en mono discret ; repli honnête pour un code inconnu. Spec de
  contrat sur tout l'inventaire.
- `20344b2a` — plus de « undefined » sur le canvas : libellé du nœud en
  repli `label → type → skill_slug → pastille de kind localisée`.
- `23815bbb` — le sweep purge les rows `pending` jamais construites que
  rien ne référence, passé `RECIPE_ENVS_PENDING_PURGE_HOURS` (défaut 24 h) ;
  `resolve` recrée une spec purgée à la demande ; rows référencées par une
  exécution conservées. Nouveau champ `purged_pending` dans le rapport.
- `f31eecad` — description seed de `python_recipe_v1` en texte brut (les
  backticks s'affichaient littéralement dans le catalogue).

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `4a1c2a49` → `f31eecad` (5 commits) |
| Ancre | `/home/ubuntu/omnirag` **intouchée** |
| Worktree | `f31eecad6e2af9482b2ec3380b26e2a87fdcc45c`, porcelain vide |
| Build | trois images au tag `f31eecad6e2a` en 8 min (13:02 → 13:10Z), label 40-hex identique backend / worker / frontend |
| Dump / `migrate` | aucun — pas de fichier sous `backend/alembic/versions/` dans le delta |
| `storage-check` | sortie 0, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés, backend et frontend `healthy` |
| `build-info` | `revision: f31eecad6e2af9482b2ec3380b26e2a87fdcc45c`, `revision_verified: true` (`https://agentium.papai.ai`) ; `/` = 200 |
| Activation | `RECIPE_EXECUTION_ENABLED=true` effectif dans backend **et** worker ; `RECIPE_ENVS_PATH=/data/recipe_envs` monté worker |
| Reseed | le seed ne tournant pas au boot, upsert rejoué one-off dans le backend (`seed_skills_and_capabilities` : 92 skills / 27 capabilities rafraîchies) — description sans backticks vérifiée en base |
| Sweep | déclenché one-off post-bascule : rapport avec la nouvelle clé `purged_pending=0` (l'unique row `pending` a ~2 h, dans la fenêtre 24 h — conservée, comportement voulu) |
| Logs | 0 `traceback`/`exception` backend et worker depuis la bascule |
| Infra | PostgreSQL, RabbitMQ, Qdrant, MinIO, Keycloak, LiveKit, SFTP intouchés |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Canaris carakai | checkout avancé par bundle incrémental (sha256 `d366b631…` identique des deux côtés), marqueur `.agentium-source-sha` aligné, lock inchangé. **5 passed / 3 failed** en 1,2 min, artefacts `/tmp/iteration-canaries-20260824T131546Z.J7KVQ6` (`playwright-runtime.json` : `candidate_sha f31eecad…`, `package_lock_sha256 95689c8c…`, producer `result: passed`). Échecs inchangés vs `4a1c2a49` : **11** rail `Build`, **16** `GET /work` vide, **17** overflow title-bar 320px |
| Vérif UI live | après hard-reload du bundle : nœud API sans label affiche `python_recipe_v1` (plus de « undefined ») ; onglet E/S en français (« DÉRIVER DES PORTS » / « EFFACER » grisé tant qu'aucun schéma n'est déclaré) ; essai annulé depuis l'atelier → « Annulée » + « Exécution annulée à la demande. », le code brut `cancel_requested` n'apparaît plus — vidéo archivée côté agent |
| Rollback | pas de migration : `AGENTIUM_IMAGE_TAG=4a1c2a493df6` puis `up` |

## Préparation du 25/08 — plan data/ML, **non déployée**, routine de dump étendue

Entrée de préparation et non de déploiement : la tranche data/ML
(datasets tabulaires, nœuds SQL / Polars / dbt, entraînement et service de
modèles, démo Nawa) est répétée en local mais **n'a pas été portée sur la VM**.
La VM reste à `095_python_recipes`, sans aucune des tables du plan
(`tabular_datasets`, `ml_models`, `ml_model_api_keys` : absentes, vérifié).
Ce qui suit est ce qui a été préparé et vérifié *contre* la VM, sans la modifier.

### La routine de dump du §5 n'était plus une sauvegarde

À partir de `096_tabular_data_plane`, Postgres cesse d'être l'état complet :
`tabular_datasets.storage_key` désigne un objet Parquet et `ml_models.model_uri`
un répertoire de modèle MLflow, tous deux dans le bucket MinIO. Restaurer le
`pg_dump` seul rend un registre d'URI pendantes — `/predict` répond
`ML_ARTIFACT_MISSING`, les aperçus de datasets échouent — c'est-à-dire la pire
sauvegarde, celle qui a l'air d'avoir marché.

`scripts/agentium-data-plane-dump.sh` prend les deux moitiés dans une seule
fenêtre, puis vérifie que chaque artefact que le registre nomme y est présent ;
`.ready` n'est écrit qu'après ce contrôle. Le périmètre vient du registre et non
d'un glob de chemins : seuls les préfixes `tabular/` et `ml/` des workspaces qui
possèdent réellement des datasets ou des modèles sont miroirés — jamais un
workspace entier, dont les collections de connaissance sont un ordre de grandeur
plus grosses et se reconstruisent depuis leurs sources.

### Il n'y a pas de base `mlflow` à créer

Le plan demandait de provisionner une base `mlflow`. Rien ne s'y connecterait :
MLflow est utilisé ici comme **format** d'artefact, pas comme service, et le
registre est la table `ml_models`. Les trois réglages `mlflow_*` de
`config.py` sont des jalons pour une phase ultérieure, lus par personne, et
l'entraînement force `MLFLOW_TRACKING_URI` vers un répertoire jetable du scratch
du run — donc un serveur configuré au niveau VM ne serait de toute façon pas
joignable depuis un fit. Décision et conséquences :
[`agentium-data-plane-provisioning.md`](agentium-data-plane-provisioning.md).

### Observables (contre la VM, sans la modifier)

| Pas | Observé |
|---|---|
| Tête Alembic VM | `095_python_recipes` ; la tranche apporte `096_tabular_data_plane` → `097_ml_training_plane`, chaînés dessus |
| Tables du plan | `tabular_datasets`, `ml_models`, `ml_model_api_keys` **absentes** — le plan n'est pas déployé |
| Bucket | `agentium-artifacts` (`OBJECT_STORE_BACKEND=s3`, endpoint `http://agentium-minio:9000`) ; aucun préfixe `tabular/` ni `ml/` sous `workspaces/` |
| Bases Postgres | `agentium` seule (+ `postgres`, `template0/1`) ; **aucune** base `mlflow`, et aucune variable `MLFLOW_*` dans l'environnement backend — état correct |
| `agentium-data-plane-dump.sh` | shellcheck 0 finding ; essai réel sur la VM : dump `pg_dump -Fc` de 433 Mo, sha256 revérifié `OK`, archive listable (`pg_restore -l` : 1276 entrées TOC), détection correcte du schéma pré-096 (mirroir sauté et annoncé), `MANIFEST.json` + `.ready` écrits. Fenêtre d'essai supprimée ensuite (disque revenu à 219 G / 268 G libres) |
| Moitié objets du script | vérifiée séparément contre de vrais octets MinIO : parse `mc du --json` (46 315 o), préfixe absent lu comme 0 (cas d'un workspace sans modèles), `mc mirror` → `docker cp` → 7 fichiers sortis, checksums par clé relative, contrôle d'existence positif sur une clé réelle |
| Fuite de secret | aucune : l'alias `mc` est assemblé **dans** le conteneur MinIO depuis son propre environnement, jamais sur la ligne de commande de l'hôte ni dans la fenêtre |
| Divergence de schéma connue | `070` a été réécrite (`NOT LIKE '% %'` → `replace(app_key, ' ', '')`) pour débloquer `create_all` sur Postgres neuf. Déjà appliquée sur la VM, donc la contrainte vive garde la forme `!~~ '% %'` : équivalente (et la regex frère exclut déjà l'espace), rien à réparer — noté pour qu'un diff futur se lise comme prévu |
| Attestation lock frontend | `PACKAGE_LOCK_SHA256 = cfded9c9…` = sha256 réel de `frontend-ng/package-lock.json`, alignée |
| Infra | PostgreSQL, RabbitMQ, Qdrant, MinIO, Keycloak, LiveKit, SFTP **intouchés** ; aucun conteneur recréé, aucune image construite, aucun tag déplacé |

### Ce qu'il reste pour déployer

Le chemin normal du process, avec le §5 remplacé par le §5b : dump des deux
moitiés, `migrate` (096 puis 097), `storage-check`, `up`, canaris carakai + e2e,
puis rejouer le runbook des sept temps sur la VM et remplacer sa section
« preuves de répétition » par les identifiants VM. `RECIPE_EXECUTION_ENABLED`
doit être actif côté backend **et** worker pour que les temps Polars et dbt
s'exécutent ; `WORKER_EAGER_MODE` reste éteint sur la VM, où un worker tourne.

## Itération du 25-26/08 — plan data/ML sur `fb62edba`, **déployée**

GO deploy depuis un Cloud Agent, dans la fenêtre ouverte par l'entrée de
préparation ci-dessus. `origin/demo/agentic` avançait de `f31eecad` (live) à
`fb62edba`, 57 commits : les sept phases du plan data/ML (datasets tabulaires,
nœuds SQL / Polars / dbt, entraînement scikit-learn avec registre MLflow,
service `/predict` à clé, démo Nawa) et les correctifs que la VM a trouvés.

**La conclusion « il n'y a pas de base `mlflow` à créer » de l'entrée de
préparation est renversée.** Elle était exacte quand elle a été écrite — MLflow
n'était alors qu'un format d'artefact — et la phase 5 a ajouté le registre
lui-même, dont le backend store *est* une base Postgres. Il y a donc bien une
base `mlflow` sur `agentium-pg`, sans serveur ni port : le client écrit dedans
et crée son schéma à la première connexion. Toujours pas de `MLFLOW_*` dans
l'environnement compose, le client étant configuré en code — et c'est cette
absence, pas une variable, qui est la précondition à vérifier.
[`agentium-data-plane-provisioning.md`](agentium-data-plane-provisioning.md)
porte l'état à jour.

Neuf générations d'images ont été construites et basculées dans la même fenêtre.
Sept l'ont été parce que la VM refusait ce qui passait en local, et c'est le
résultat le plus utile de la journée : la boucle e2e + runbook sur la machine
réelle a trouvé six défauts qu'aucune suite locale ne pouvait montrer.

1. `2bd4786d` (23 h 08, dump puis `migrate`) : `097` a échoué sur un
   `DuplicateColumn` — cinq colonnes de `097` avaient été écrites *aussi* dans
   `096`. Invisible en local, où la base part de zéro et où `create_all` couvre
   la dérive ; visible sur la seule base qui applique la chaîne pour de vrai.
   Corrigé dans `096`, plus un test qui parcourt la chaîne complète et attrape
   une colonne ajoutée deux fois (`test_tabular_migration.py`).
2. `52c2d5f1` → `5d54e2ec` : le nœud LLM du brief Nawa répondait « could not
   parse the JSON body ». Le nœud amont met un objet sous la clé `model` de son
   enveloppe, que le wrapper prenait pour un nom de modèle. `_model_name()`
   traverse les candidats non-textuels au lieu de les transmettre.
3. `d2e39cb8` — **le nœud dbt s'arrêtait sur la VM et nulle part ailleurs**
   (`cannot allocate memory for thread-local data: ABORT`, exit 127).
   `RLIMIT_AS` compte l'espace d'adressage *réservé* et glibc réserve une arène
   de 64 Mio par thread, jusqu'à huit par cœur : sur 16 cœurs les arènes seules
   mangent le budget de 3 Gio et le premier thread meurt dans l'allocateur avant
   le SQL du projet. `MALLOC_ARENA_MAX=2` est désormais épinglé pour tout enfant
   supervisé, donc un budget veut dire la même chose sur 4 et sur 16 cœurs. Le
   message rapporté était par-dessus le marché faux : le superviseur citait la
   dernière ligne de stderr, soit un avertissement de sémaphore fuité imprimé
   *après* l'ABORT. `harness_error_line` saute les lignes d'avertissement.
4. `8fd38055` — le client MLflow *étranger* ne chargeait pas depuis MinIO. La
   `source` d'une version est une URI `s3://` et le dépôt d'artefacts S3 de
   mlflow importe `boto3` par son nom ; `botocore`, que `s3fs` apporte pour nos
   propres lectures, ne suffit pas. En local l'object store rend des `file://` :
   l'étape censée prouver la portabilité était la seule jamais exercée là où
   elle compte.
5. `a61c1e6b` — `/predict` répondait `ML_ARTIFACT_UNLOADABLE` en citant
   `No module named 'torchvision'`. `skops.io` construit ses tables de types à
   l'import en interrogeant tout `sys.modules` ; dans le backend `transformers`
   y est déjà, son `__getattr__` paresseux importe le module d'un nom, et le
   balayage traverse des processeurs d'images qui supposent un `torchvision`
   absent. Le pair est installé depuis l'index CPU de PyTorch avec `torch`, et
   `preload_deserializer` déplace les dix secondes de balayage du premier
   `/predict` vers le démarrage.
6. `9ae74b9a` → `a52cb29a` — l'onglet Comparaison de la carte du modèle qui
   *sert* était vide, « rien à comparer », avec trois versions dans la lignée.
   Deux causes : la route de détail sérialisait les versions sans leurs scores,
   et le front comparait à la version *précédente*, ce qu'une v1 n'a pas. La
   route porte `include_scores`, et `comparisonPair` prend la version d'en
   dessous ou, à défaut, celle d'au-dessus, toujours rendue dans l'ordre.
7. `fb62edba` — le registre gardait ce que la plateforme avait supprimé :
   **quatre modèles enregistrés répondaient encore `@champion`** après que
   toutes leurs versions aient été supprimées. Le chemin de suppression
   nettoyait les alias qu'un survivant pouvait nommer, jamais la version
   elle-même, ni le conteneur avec sa dernière version. Un registre public qui
   liste des versions que le déploiement ne sait plus expliquer est exactement le
   mode de défaillance qu'un registre existe pour empêcher. `retire_version` et
   `forget_model` closent ça, et restent muets sur une panne : la ligne est
   l'enregistrement opérationnel, le miroir qui se taît ne retient pas une
   suppression.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `f31eecad` → `fb62edba` (57 commits). Cette entrée est poussée **après** la bascule, comme les précédentes : `build-info` restera donc un commit derrière la tête de branche jusqu'à la prochaine itération, qui l'emportera dans son delta |
| Ancre | `/home/ubuntu/omnirag` **intouchée** (`56a9c57b`) |
| Worktree | `/srv/agentium-data/worktrees/demo-agentic` = `fb62edba8886a9d78b8ea6e7e9c4721f9368eef3`, porcelain vide |
| Build | neuf générations (`2bd4786d8396`, `52c2d5f179b3`, `5d54e2ec4be8`, `d2e39cb8d19d`, `8fd380555e5b`, `a61c1e6b754c`, `9ae74b9a3879`, `a52cb29a0512`, `fb62edba8886`), label 40-hex identique backend / worker / frontend à chaque bascule |
| Dump | `/srv/agentium-data/data-ml-deployments/2026-08-25-2bd4786d8396/pre-2bd4786d8396.dump`, 453 440 634 o, sha256 `9eac734596fd220416843eb3718ae7b04456e412df6dd7c431b43b11acc92da2`, `.ready` écrit. `MANIFEST.json` porte `data_plane_deployed: false` et `object_files: 0` — correct : la fenêtre est prise **avant** `096`, il n'y a pas encore d'objet à mirorer, et le script le dit plutôt que d'écrire un miroir vide qui aurait l'air d'une sauvegarde |
| `migrate` | `095_python_recipes` → `096_tabular_data_plane` → `097_ml_training_plane` (une fois, après le correctif du `DuplicateColumn`) ; `alembic current` = `097_ml_training_plane (head)` aux huit bascules suivantes |
| Registre | database `mlflow` créée par `ensure_database()` à la première publication, propriétaire `agentium`, schéma migré par MLflow lui-même ; aucun `MLFLOW_*` dans l'environnement compose |
| `storage-check` | sortie 0 au tag final, autonome puis rejoué dans `up` |
| `up` | cinq services applicatifs recréés (05:29Z), backend et frontend `healthy` |
| `build-info` | `revision: fb62edba8886a9d78b8ea6e7e9c4721f9368eef3`, `revision_verified: true` en localhost Host **et** sur `https://agentium.papai.ai` ; `/` = 200 |
| Logs | 0 `traceback`/`exception` backend et worker depuis la bascule |
| Infra | PostgreSQL, RabbitMQ, Qdrant, MinIO, Keycloak, LiveKit, SFTP **intouchés** (Up 2 weeks) |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Canaris carakai | checkout avancé `8fd38055` → `fb62edba` par bundle incrémental (sha256 `7f5fc9d5f697ccca6587e7443065884e560c1327980a35fadb2c565ce6ac13f1` identique des deux côtés, `cat-file -e` positif), marqueur `.agentium-source-sha` réaligné — il était resté à `f31eecad`. **5 passed / 3 failed** en 1,2 min, `/tmp/iteration-canaries-20260826T053724Z.atoDsI` (`playwright-runtime.json` : `candidate_sha fb62edba…`, `package_lock_sha256 cfded9c9…`, producer `result: passed`), 5 artefacts `evidence/`. Échecs inchangés depuis `6d15e521` : **11** rail `Build` absent sous `experience_v1`, **16** `GET /work` sans Experience Pilot/In-service, **17** overflow title-bar à 320 px — aucun ne touche le plan data/ML |
| Attestation lock frontend | `PACKAGE_LOCK_SHA256 = cfded9c9…` = sha256 réel de `frontend-ng/package-lock.json` ; l'arbre `frontend-deps-cfded9c9…` était déjà installé, `npm ci` non rejoué |
| Rollback | `096` et `097` sont additives : `AGENTIUM_IMAGE_TAG=f31eecad6e2a` puis `up` rend un backend qui ignore les nouvelles tables (les pages Data et Models disparaissent, le reste sert). Le dump `2bd4786d8396` est le recours, à restaurer **avec** la moitié objets — un `pg_restore` seul rendrait un registre d'URI pendantes |

### Scénario e2e data/ML (driver API contre la VM vive, workspace `nawa`)

`scripts/e2e_data_ml_live.py --reproduce` exerce la tranche de bout en bout
contre l'URL publique, sans accès à la base ni au store : upload d'un CSV de
4 000 lignes, ingestion narrée, transform SQL, refus du garde SQL,
entraînement, re-entraînement à l'identique, comparaison sur un même split,
`/predict` à clé seule, portée de la clé, révocation, puis suppression de tout
ce qu'il a créé — dans un `finally`, pour qu'une passe rouge ne laisse pas ses
lignes sur la démo.

| Phase | Observé (à `fb62edba`) |
|---|---|
| `build-info` | `fb62edba…` `verified=True` avant tout le reste — un e2e contre l'ancienne image ne prouve rien |
| Ingestion | 4 000 lignes, 8 colonnes ; narration `reading` (les pas sont un vocabulaire et un ordre, pas un compte : un ingest de 4 000 lignes peut n'en montrer qu'un) |
| SQL | 15 groupes en 763,8 ms, catalogue 8 colonnes |
| Garde SQL | `DROP` refusé, `SQL_FORBIDDEN_KEYWORD` |
| Plan | classification sur `churn`, 7 features, `gradient_boosting` pris dans les 4 offerts par l'API (et non codé en dur) |
| Fit v1 | roc_auc 0,807505 ; narration `reading → scoring → saving` ; contrat de prédiction 6 champs |
| Reproductibilité | v2 roc_auc 0,807505, **identique** |
| Comparaison | 6 métriques sur un split unique de 1 000 lignes |
| `/predict` (clé seule) | 3 lignes en 192,9 ms, `served` v1, `cached: false` |
| Portée de la clé | la même clé est refusée par `/datasets` et par la route de détail du modèle |
| Révocation | la clé révoquée cesse de répondre immédiatement |
| Nettoyage | 2 modèles et 1 dataset supprimés ; **et le registre revient à un seul modèle enregistré** (`b337fdbf.churn-radar`, `champion` → 1, `challenger` → 2), ce qui est la vérification du correctif `fb62edba` en conditions réelles |

### État de la démo Nawa sur la VM

| Objet | Observé |
|---|---|
| Datasets | 7 `ready` : `base-clients-export-brut` 8 412 (upload) · `kpi-cellules-radio` 24 192 (upload) · `base-clients-nettoyee` v1 et v2 6 903 (transform, la v2 est le rejeu du Flow par-dessus l'état seedé — attendu) · `base-clients-features` 6 903 · `base-clients-scoree` 6 903 · `cellules-a-risque-7-jours` 72 (dbt) |
| Modèles | `Churn Radar` v1 `linear` **champion** · v2 et v3 `gradient_boosting`, toutes `ready` |
| Scores v1 | roc_auc 0,835206 · accuracy 0,836037 · balanced_accuracy 0,697737 · f1 0,548644 · precision 0,704918 · recall 0,449086 · log_loss 0,391460 · brier 0,122305 |
| Registre | `b337fdbf.churn-radar`, 3 versions, `source` en `s3://agentium-artifacts/workspaces/…/ml/models/<id>/model`, `champion` → v1 et `challenger` → v2 — la meilleure perdante, pas la plus récente |
| Nœud dbt | rejoué après le correctif d'arènes : le 7ᵉ dataset existe, 72 lignes |

## Itération du 26/08 — renommage anglais et re-vérification sur `4483dd1a`, **déployée**

GO deploy depuis un Cloud Agent. `origin/demo/agentic` avançait de `fb62edba`
(live) à `4483dd1a`, en trois bascules : la tranche anglaise et les correctifs
d'interface, puis deux défauts que seul le re-seed sur la VM a montrés. Aucune
migration dans le lot — `alembic current` était déjà `097_ml_training_plane` et
l'est resté aux trois bascules —, mais la fenêtre a quand même été prise, parce
que `--reset` supprime des lignes.

**Ce que la VM a trouvé, et que rien en local ne pouvait montrer.**

1. `2bf1006d` — **le re-seed a rendu `exit 0` sur une démo qui ouvrait au
   rouge.** Quatre des sept nœuds du Flow `Churn Radar` avaient échoué
   (`DATASET_NOT_FOUND`, puis les trois nœuds en aval faute d'entrée), il n'y
   avait ni table de features, ni base scorée, ni v3 — et le script imprimait
   « system ready: Churn Radar » puis « Nawa data demo ready ».

   Le graphe nomme son dataset d'entrée **par slug**. `--reset` retire les
   anciens slugs, `ensure_system` doit réécrire le graphe avec les nouveaux, et
   il ne pouvait pas : la réconciliation préserve un brouillon laissé ouvert
   dans le Builder, et un opérateur réel en avait un sur `Churn Radar`
   (`system_flow_drafts` r3, `thibaud.ishacian@datategy.net`). Préserver ce
   brouillon est la bonne règle ; exécuter le graphe précédent ensuite et
   appeler ça prêt ne l'est pas. `Radio Watch`, dont le brouillon était celui du
   seed et propre, s'est réconcilié et a tourné vert du premier coup — c'est le
   cas contre lequel le code avait été écrit.

   Trois correctifs : `--reset` jette les brouillons de ses **deux** Systems et
   d'aucun autre ; `ensure_system` compare le miroir que le moteur exécute au
   graphe qu'on lui a passé et nomme le porteur du brouillon quand ils
   diffèrent ; un run dont le walker dit `completed` avec un nœud `failed`
   n'est plus une démo seedée.
2. `4483dd1a` — **le contrôle de portabilité échouait avant de charger quoi que
   ce soit.** L'étape 5 du vérificateur (« un client MLflow standard, à qui on
   ne donne que l'URI du registre ») mourait en `NoCredentialsError`. La
   `source` d'une version est une URI `s3://`, le dépôt d'artefacts S3 de mlflow
   la lit avec boto3, et boto3 ne lit ses identifiants que dans
   l'environnement. Rien dans le déploiement ne les pose, parce que rien n'en a
   besoin : notre propre service télécharge le répertoire par la façade object
   store et passe un chemin local à `load_model`. La seule étape dont le but est
   d'être exercée contre MinIO était donc la seule qui ne pouvait pas l'être, et
   en local elle passait parce qu'un object store local rend des `file://` et
   n'appelle jamais boto3. Même piège que le `boto3` manquant de l'itération
   précédente, une couche plus loin.

   Exporter les trois variables S3 n'est pas une fissure dans la promesse, c'est
   la promesse : ce qu'il faut à un lecteur étranger, c'est la configuration S3
   avec laquelle n'importe quel MLflow parle à un object store, et zéro code
   Agentium. Sept artefacts descendent maintenant, signature à 20 colonnes lue
   dessus.

   Les attendus du vérificateur étaient par ailleurs restés ceux du générateur
   d'avant le renommage : cinq lignes criaient `DRIFT` contre un plan correct.

**Le sixième décimal du modèle linéaire appartient à la machine.** `lbfgs`
somme dans l'ordre qu'OpenBLAS choisit par CPU : v1 vaut 0,836617 sur le
Broadwell de la VM et 0,836610 sur les agents de build, tandis que la paire
boostée est identique au dernier chiffre des deux côtés. Accuracy, precision et
recall ne bougent pas — aucune ligne ne traverse le seuil —, donc seule la
métrique de rang reçoit une tolérance, et seulement pour le fit linéaire. La
note `PAPAI-MIRROR.md` §7 le dit maintenant, ce qui évite qu'un rebuild dans
papAI prenne un écart de 7e-6 pour une erreur de pipeline.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `fb62edba` → `d00e9150` → `2bf1006d` → `4483dd1a` |
| Ancre | `/home/ubuntu/omnirag` **intouchée** (`56a9c57b`) |
| Worktree | `/srv/agentium-data/worktrees/demo-agentic` = `4483dd1a34eb92e4edfbae7103f36120fba79697`, porcelain vide |
| Build | trois générations (`d00e9150cda3`, `2bf1006d5e0a`, `4483dd1a34eb`), label 40-hex identique backend / worker / frontend à chaque bascule |
| Dump | `/srv/agentium-data/data-plane-deployments/2026-08-26-d00e9150cda3` : Postgres 433 Mo, registre `mlflow` 132 ko (3 versions), 103 objets / 103 Mo sur `agentium-artifacts`, 3 états de rapport, `.ready` écrit. Pris **avant** le premier `--reset`, qui est la seule opération destructive du lot |
| `migrate` | aucune révision à appliquer ; `alembic current` = `097_ml_training_plane (head)` aux trois bascules |
| `storage-check` | sortie 0 aux trois bascules |
| `up` | cinq services applicatifs recréés à chaque fois, backend et frontend `healthy` |
| `build-info` | `revision: 4483dd1a34eb92e4edfbae7103f36120fba79697`, `revision_verified: true` en localhost Host **et** sur `https://agentium.papai.ai` ; `/` = 200 |
| Infra | PostgreSQL, RabbitMQ, Qdrant, MinIO, Keycloak, LiveKit, SFTP **intouchés** (Up 2 weeks) |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Canaris carakai | **non rejoués.** Le runner exige un candidat en phase `validation_pending` de `deploy-agentium-safe.sh`, dont le préflight demande le manifeste Release A privé et sa politique de revue ; ces artefacts ne sont pas dans la portée d'un Cloud Agent. Les trois échecs connus (rail `Build`, `GET /work`, overflow 320 px) portent sur Experience et ne touchent pas le plan data/ML |
| Rollback | `AGENTIUM_IMAGE_TAG=fb62edba8886` puis `up`. Aucune migration dans le lot, donc la bascule arrière est propre côté schéma ; le seed anglais reste en base et un backend `fb62edba` le sert sans s'en émouvoir (les slugs vivent en données, pas en code) |

### Re-vérification de bout en bout

| Contrôle | Observé (à `4483dd1a`) |
|---|---|
| `verify_nawa_data_ml_plane` | **72 lignes, toutes `ok`, aucun `DRIFT`** — y compris l'étape 5, verte pour la première fois contre MinIO |
| `e2e_data_ml_live --reproduce` | **E2E PASSED** contre l'URL publique, `--expect-sha` vérifié en premier. Ingestion 4 000 lignes, aperçu paginé lignes 3 995–4 000 lus dans le Parquet, SQL 15 groupes en 594,1 ms, `DROP` refusé, fit roc_auc 0,807505 puis **0,807505 à l'identique**, comparaison 6 métriques sur 1 000 lignes, `/predict` à clé seule 3 lignes en 185,9 ms, portée refusée sur `/datasets`, révocation immédiate, nettoyage complet |
| Démo Nawa | 7 datasets `ready`, 3 modèles, champion v1 non réassigné, Flow `Churn Radar` **7 nœuds sans échec** (clean 270 ms · features 3,2 s · train 46,2 s · score 12,8 s · brief 5,8 s), `Radio Watch` 3 nœuds, dbt 72 lignes |
| Scores | v1 `linear` 0,836617 **champion** · v2 `gradient_boosting` 0,864133 · v3 `gradient_boosting` 0,853761 |
| Registre | `b337fdbf.churn-radar`, 3 versions, `source` en `s3://agentium-artifacts/…`, `champion` → v1, `challenger` → v2 |
| Vidéo | 88 s, les sept temps du runbook, navigateur en `fr-FR` et `<html lang="en">` : onglet Comparaison rempli (v2 contre v3, sept métriques avec avant / après / delta), Playground répondant, aucun texte français à l'écran |

### Dette relevée, non traitée

- **Le numéro de version des datasets seedés monte à chaque `--reset`.** Les
  uploads sont en v2 et `subscriber-base-cleaned` en v2/v3, parce que la
  suppression est douce et que le compteur porte sur le slug. Rien de faux —
  c'est bien la deuxième fois que la table est écrite — mais le tableau du
  runbook a dû être réécrit et le sera encore au prochain re-seed. Une purge
  dure de la lignée du seed rendrait le compteur à 1 ; elle demande de retirer
  aussi les objets Parquet, ce qui n'a pas été fait ici.
- **La vidéo a été tournée avec un compte de test.** `nawa` n'a que ses deux
  membres réels, et les identifiants d'un opérateur ne sont pas dans la portée
  d'un Cloud Agent ; `bob@globex.test` a été ajouté membre le temps du tournage
  puis retiré (la table est revenue à ses deux lignes). Le nom dans le coin de
  l'écran n'est donc pas celui d'un présentateur.

## Itération du 26/08 (après-midi) — l'app métier, déployée sur `d220cf2a`

GO deploy depuis un Cloud Agent. `origin/demo/agentic` avance de `4483dd1a` à
`d220cf2a`. Aucune migration : `alembic current` rend `097_ml_training_plane`
avant et après. La fenêtre a quand même été prise, parce que le re-seed passe
par `--reset`, qui supprime des lignes.

La tranche répond à une question posée sur la démo : les Systems produisent des
datasets, des modèles et des runs, mais tout cela se lit dans des surfaces
faites pour celui qui les a construits — un canevas de Flow, un catalogue de
datasets, une fiche de modèle, un cURL. Le public à qui le travail s'adresse
n'avait nulle part où atterrir. Il y a maintenant une page `/work/retention-board`
lisible par un `workspace_viewer`, dont chaque chiffre est calculé au clic
depuis la base scorée réelle.

**Ce qu'il a fallu ajouter sous la page, et pourquoi ce ne sont pas des
rustines de démo.** Un nœud `python_recipe_v1` rend du JSON arbitraire mais ne
savait pas lire une table : le bac à sable n'a ni base ni object store, donc la
*référence* de dataset que tout nœud de transformation passe est précisément la
seule valeur qu'il ne peut pas ouvrir. Les nœuds SQL / Polars / dbt lisent des
tables mais n'émettent qu'une nouvelle version de table — cinq rafraîchissements
auraient laissé cinq copies des mêmes lignes sur la page Data. D'où deux
primitives : un pin `sources` sur le nœud recipe, identique à celui que les
trois autres portent déjà, et `system_run_read_v1`, qui lit le dernier run
terminé d'un autre System. La seconde est ce qui fait que le brief affiché est
*celui que le pipeline a écrit* et non une génération neuve qui répondrait à une
autre question sous le même titre.

**Ce que la VM et la première capture ont trouvé.**

1. **Le `Churn Desk` n'était pas seedé du tout.** `publish_and_mint` rend le
   Skill *à côté* de la clé d'API (`{"skill": {...}, "api_key_prefix": …}`), et
   l'appelant lisait `slug` sur l'enveloppe : toujours `None`, donc la branche
   qui construit le desk ne s'ouvrait jamais. Un seed complet imprimait
   « ready » de bout en bout sans le sixième temps. La lecture est maintenant
   une fonction nommée avec son test, et un champion qui ne publie aucun Skill
   appelable arrête le seed au lieu de le laisser passer.
2. **Le contrôle e2e échouait sur une VM saine, parce qu'elle est rapide.**
   L'assertion « l'ingestion narre » lisait `[]` : 4 000 lignes s'ingèrent en
   ~250 ms, les pas sont bien écrits et committés un par un, mais c'est plus
   court qu'un aller-retour HTTPS depuis l'extérieur — le premier poll trouve la
   ligne déjà `ready` et le champ vidé. Plus la machine est oisive, plus le test
   déclare le plan muet. `--rows` passe à 60 000, et ne rien voir se rapporte
   désormais autrement que ne voir que `queued` : l'un est un observateur trop
   lent, l'autre est le spinner muet que le contrôle existe pour attraper.
3. **La liste d'appels était tronquée en plein en-tête.** Sept colonnes sur une
   demi-rangée : un chargé de rétention voyait l'ancienneté d'un abonné mais ni
   son ARPU, ni sa probabilité, ni ce que son départ coûte — soit toutes les
   colonnes qui justifient la liste. Et l'exposition s'affichait `72314.04` :
   une tuile imprime ce qu'on lui donne, et les centimes sur un revenu mensuel
   sont du bruit. Le test d'arithmétique des rangées, ajouté au passage, a
   attrapé du premier coup une rangée de contrôle à moitié vide.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Push | `demo/agentic` en fast-forward `4483dd1a` → `d220cf2a` |
| Worktree | `/srv/agentium-data/worktrees/demo-agentic` = `d220cf2a045fdc4e6823622d7a660faf3261996a` |
| Build | trois images `d220cf2a045f` (backend, worker, frontend), label 40-hex identique |
| Dump | `/srv/agentium-data/flow-publication-deployments/2026-08-26-d220cf2a045f/postgres-pre-switch.dump`, sha256 relevé, pris **avant** le `--reset` |
| `storage-check` | sortie 0 |
| `migrate` | aucune révision à appliquer ; `alembic current` = `097_ml_training_plane` |
| `up` | cinq services applicatifs recréés, backend et frontend `healthy` |
| `build-info` | `revision: d220cf2a045fdc4e6823622d7a660faf3261996a`, `revision_verified: true` |
| Infra | PostgreSQL, RabbitMQ, Qdrant, MinIO, Keycloak, LiveKit, SFTP **intouchés** (Up 2 weeks) |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Rollback | `AGENTIUM_IMAGE_TAG=4483dd1a34eb` puis `up`. Aucune migration dans le lot ; le board resterait en base, servi par un backend qui refuse le type `chart` au *release* — les releases déjà figées ne sont pas revalidées, donc la page continue de s'afficher |

### Re-vérification de bout en bout

| Contrôle | Observé (à `d220cf2a`) |
|---|---|
| Seed rejoué avec `--reset` | 7 datasets, 3 modèles, **`Churn Desk` actif pour la première fois**, `Retention Board` actif, `experience_v1` posé par le seed |
| `Churn Radar` | run `completed`, 7 nœuds, aucun échec |
| `Churn Desk` | run `completed` ; `decide_next_v1` délibère 3 246 ms puis choisit `ws.b337fdbf….predict_churn_radar`, qui répond en 237 ms — `goal.status: complete`, `observations[0].ok: true`. La flèche « un modèle publié est un skill qu'un agent peut appeler » est vérifiée sur la VM, pas affirmée |
| `verify_nawa_data_ml_plane` | **toutes les lignes `ok`, aucun `DRIFT`**, étape 5 (client MLflow standard contre MinIO) comprise |
| `e2e_data_ml_live --reproduce` | **E2E PASSED** à `--rows 60000` : ingestion narrée, aperçu paginé lu dans le Parquet, SQL 15 groupes en 231,6 ms, `DROP` refusé, fit roc_auc 0,857888 puis **0,857888 à l'identique**, comparaison 6 métriques sur 15 000 lignes, `/predict` à clé seule 3 lignes en 134,6 ms, portée refusée, révocation immédiate, nettoyage complet |
| `/work/retention-board` | ouvert en `workspace_viewer` dans un navigateur : 16 blocs, chaque sélecteur lié résolu, **aucun vide**. 1 000 abonnés signalés, 72 314 MAD d'exposition, décile le plus risqué 77,4 % contre 22,2 % de base, `roc_auc` 0,836617, 20 lignes d'appel, `msisdn` en chaîne |

### Dette relevée

- **Le brief du pipeline invente ses chiffres, et le board les affiche à côté
  des chiffres mesurés.** `_azure_llm_v1` ne reçoit qu'un `prompt` : le nœud
  `task.brief` ne lui passe aucune ligne, et l'invite lui demande pourtant de
  « citer des chiffres ». Il annonce 1 200 abonnés et 360 000 MAD quand les
  tuiles voisines, calculées sur le même run, disent 1 000 et 72 314. Le défaut
  est antérieur à cette tranche ; le board est ce qui l'a rendu visible, en
  mettant l'invention à deux blocs de la mesure.
- **Le board observe et fait consulter, il ne fait pas encore agir.** Le seul
  contrôle est un rafraîchissement. Le `Churn Desk` répond exactement à la
  question suivante — faut-il appeler cet abonné — mais son entrée est le
  contrat fermé à vingt colonnes du modèle, alors qu'un formulaire de page ne
  peut offrir qu'un identifiant pris dans le tableau : il lui faut une ingress
  qui résolve l'abonné elle-même.
- **La sortie du desk n'est pas encore un verdict lisible.** Le run rend
  l'enveloppe de la boucle (`exit`, `observations`) et `summary` y est vide ; la
  boucle s'arrête dès que `done_when` est satisfait, donc le rédacteur de son
  catalogue n'est jamais appelé. Ce qu'un humain lirait n'existe pas encore.
- **`bob@globex.test` a de nouveau été ajouté membre** (`workspace_viewer`
  cette fois, ce qui est aussi le contrôle d'accès de la page) le temps des
  captures, et doit être retiré à la fin de la fenêtre.

## Itération du 26/08 (soir) — le graphique du board, déployée sur `64f53239`

GO deploy depuis un Cloud Agent, deux tranches successives : `dbfdf5f6` puis
`64f53239`. Aucune migration dans l'une ni dans l'autre. Une fenêtre a été
prise avant chaque `--reset` (`postgres-pre-switch.dump` et
`postgres-pre-reseed.dump`, sha256 relevés dans
`/srv/agentium-data/flow-publication-deployments/2026-08-26-dbfdf5f6fdec`).

La demande était de rendre les graphiques de l'app présentables. Le bloc
`chart` certifié dessinait ses barres avec `ck-bar-list`, le composant du plan
data : des règles de 5 px et du mono en 10,5 px, conçus pour classer vingt
importances de variables dans un panneau latéral. Le board de rétention est lu
à une autre distance — par quelqu'un qui décide de financer une campagne, et
souvent par-dessus une épaule — et à cette taille la même image se lit comme
une note de bas de page.

**Ce que la tranche change.** Les barres sont désormais le balisage du bloc :
14 px, un remplissage qui va du translucide au plein pour que la barre ait un
sens de lecture, une lueur qui la pose sur son rail, et un balayage décalé à
l'arrivée des données. La largeur est portée par l'élément et le balayage est
un `scaleX`, donc une barre est à sa place dès la première image même si
l'animation ne joue jamais — ce qui compte, parce que la règle globale
`prefers-reduced-motion` annule la durée mais pas le délai. Chaque barre porte
sa part du total, retirée dès qu'une valeur est négative et rendue `<1%`
sous le point, pour qu'une bande de trois abonnés ne se lise pas comme un zéro
mesuré. Le donut écrit son total dans le moyeu.

**La palette est optionnelle, et c'est le point.** `severity` parcourt
vert → ambre → rouge dans l'ordre où les lignes arrivent. C'est juste pour des
bandes de risque, faux pour des régions : un dégradé sur des catégories
rapporte un classement que personne n'a mesuré. Le défaut ne classe rien, et
le champ de l'atelier porte l'avertissement en libellé.

**Ce que la VM a trouvé.**

- **Le board ne reprend pas un document modifié par le seed sans `--reset`.**
  `ensure_board_experience` ne re-publie pas une page existante — c'est
  volontaire, sinon un re-seed écraserait le travail d'un opérateur. La
  première capture montrait donc les nouvelles barres avec l'ancienne palette.
  `--reset` est le chemin documenté pour un changement de copie seedée ; il a
  été rejoué et le seed est sorti vert (`SEED EXIT=0`, 7 datasets, 3 modèles).
- **L'interpolation en sRGB donnait une bande médiane olive.** Moyenner canal
  par canal entre le vert et l'ambre emprunte la corde la plus courte du cube,
  qui passe près de son centre : la couleur arrive désaturée et se lit comme un
  défaut de rendu entre deux barres nettes. Corrigé en interpolant en OkLCH, en
  parcourant le cercle des teintes par le court chemin. Le gris est traité à
  part : il a des coordonnées mais pas de teinte, et interpoler vers lui
  ferait dévier l'arc au hasard.
- **La page `/work` impose son thème clair.** Le chrome suit le thème de
  l'application, les tuiles du board non. La rampe s'affiche donc toujours dans
  ses valeurs claires, où l'ambre `#c27803` est volontairement sombre pour
  rester lisible en texte : la deuxième bande est un or foncé plutôt qu'un jaune
  vif. C'est le bon compromis sur un panneau presque blanc, où un jaune vif
  serait l'élément le plus faible de la page.

**Observables.** `#34d399 → #cac546 → #fc9841 → #ef5a6f` en thème sombre,
`#0e9f6e → #9f8a00 → #cf6510 → #d93a52` en clair. Board vivant :
4 549 (66 %) / 1 354 (20 %) / 732 (11 %) / 268 (4 %), soit les mêmes 6 903
lignes que les tuiles voisines. Barrières : 1 276 tests unitaires front,
`check:i18n` sur 6 862 clés, `build:prod`, 50 tests du seed.

**Dette laissée.**

- **Un bloc court à côté d'un bloc haut laisse un vide.** La grille étire les
  tuiles d'une même rangée ; sur la page catalogue, le graphique en barres est
  suivi d'un vide de la hauteur du donut. Le board n'en souffre pas — le
  graphique y voisine un encart de hauteur comparable — et corriger la
  répartition verticale toucherait tous les types de blocs, pas seulement le
  graphique.
- **Le donut n'a aucune surface seedée.** Il ne se photographie que sur la page
  catalogue de l'atelier. Le board n'en affiche pas, et lui en ajouter un serait
  une décision de produit, pas une amélioration de rendu.
- **`bob@globex.test` a été retiré de `nawa`** à la fin des captures ; la table
  est revenue à ses deux membres réels.

## Itération du 26/08 (nuit) — le panneau de preuves, déployée sur `2b995cdf`

GO deploy depuis un Cloud Agent, trois tranches successives : `46fc7ea3`
(les courbes, déployée dans la journée et non journalée jusqu'ici), puis
`efd0f5a1` et `2b995cdf`. Aucune migration dans aucune des trois. Une fenêtre a
été prise avant chaque bascule
(`/srv/agentium-data/flow-publication-deployments/2026-08-26-efd0f5a1c0c9` et
`…-2b995cdf0e08`).

La demande était l'effet « wow » sur les graphiques. Les courbes de la fiche
modèle l'avaient reçu — dégradé sous la ligne, ligne éclairée, balayage à
l'arrivée, réticule au pointeur. Le reste du panneau non, et une seule courbe
polie au milieu de quatre instruments plats est pire que cinq instruments
plats : le soin mis sur le ROC se lit comme un accident de rendu et non comme
la langue du panneau.

**Ce que la tranche change.** Les barres de la fiche reprennent exactement le
dessin du board : deux fois la couleur pour que la barre ait un sens, un anneau
et une lueur pour la poser sur son rail, un lustre, un balayage qui arrive dans
l'ordre du classement. Le décalage est arithmétique et non constant — un pas
fixe est juste pour un graphique d'équilibre à deux classes et vaut une seconde
et demie d'attente pour vingt importances — donc `staggerDelay` comprime le pas
pour que tout ensemble tienne dans un même budget. `VizBar` gagne une part
optionnelle : un effectif et son pourcentage cessent d'être une seule chaîne
mono que le lecteur doit séparer lui-même. La matrice imprime la part de ligne
que sa teinte encode déjà et se découvre en vagues le long de la diagonale ; une
cellule survolée est soulevée et jamais recolorée, puisque la teinte porte la
part. Le cadran du Playground reçoit une rampe, une lueur et une poignée.

**Le cadran mesure enfin le cercle que le navigateur dessine.** `A56,56` entre
deux extrémités distantes de 116 ne décrit aucun cercle ; SVG remonte les rayons
jusqu'à 58, et un cadran mesuré avec 56 s'arrête avant sa propre fin à 100 %.

**Ce que la VM a trouvé.**

- **La poignée du cadran n'était pas là où le DOM la disait.** Le remplissage et
  la poignée avaient la même durée et la même courbe, et arrivaient séparément :
  en milieu de course l'arc est passé au-dessus du cadran et le point est encore
  au départ. Les deux chiffres sont exacts, un test les tenait égaux, et le
  moteur de style confirme la poignée sur le rail à un rayon de 58 sur les 157
  images d'une course réelle mesurée sur la VM. Les pixels disent le contraire :
  `transform` est compositable, donc la rotation part au compositeur qui
  interpole une matrice, hors du fil principal et hors de pas avec un
  `stroke-dashoffset` qui est une propriété de peinture et n'en sort jamais. La
  poignée est devenue le motif de tirets du remplissage lui-même — même chemin,
  un tiret de 0,01 et un vide de tout le rail, décalé d'une période. Elle est sur
  l'arc par construction et non par accord.
- **`AGENTIUM_IMAGE_TAG` veut 12 hexadécimaux, pas 8.** Les trois images avaient
  été bâties sous un préfixe court et `storage-check` a refusé la bascule. Elles
  ont été re-taguées plutôt que rebâties ; le garde-fou a fait exactement son
  travail, avant la bascule et non après.
- **Le Dockerfile backend exige `PIP_INDEX_URL`** en argument de build, et un
  script de reprise écrit à la main l'avait perdu. Échec en quelques secondes,
  sur la première couche.
- **Une entrée d'animation ne se photographie pas deux fois.** Remonter le bloc
  en quittant l'onglet et en revenant rejoue l'arrivée, mais remet aussi la page
  en haut, et le panneau est sous la ligne de flottaison. Le scroll doit être
  redonné dans les premières images de la course.
- **Le Playground d'une version non servie propose une réponse qu'il n'obtiendra
  pas.** Le formulaire est construit sur le contrat de *sa* version — 29 champs
  pour la v3 — et la requête part vers le plan, qui sert la v1 et ses 20 champs :
  422. La première capture du cadran s'est perdue là.

**Observables.** Barrières : 1 311 tests unitaires front, `check:i18n` sur
6 862 clés, `build:prod`. `build-info` sur la VM :
`2b995cdf0e082016e01b7a4767f719e92b41fb12`, `revision_verified: true`. Matrice
de la v2 : 1 287 / 56 / 199 / 184, parts 95,8 % / 4,2 % / 52 % / 48 %. Équilibre
de la v1 : 5 373 (77,8 %) et 1 530 (22,2 %). Cadran : 0,9 % sur la ligne typique
seedée, 99,7 % après passage au profil à risque (tenure 2, 5 tickets, NPS 0),
répondu en 296 à 360 ms.

**Dette laissée.**

- **Le 422 du Playground sur une version non servie** est un vrai défaut d'usage,
  pas un défaut de rendu : la fiche offre un formulaire dont la réponse est
  refusée. Le corriger demande de décider ce que la page promet — servir la
  version affichée, ou dire qu'elle ne l'est pas — et ce n'est pas une décision
  de mise en forme.
- **L'arrivée des barres et de la matrice n'est pas filmée.** Elle est prouvée
  par le cadran, dont la course est photographiée image par image ; les deux
  autres arrivent une fois, hors champ, et les remettre en champ demanderait de
  déplacer le panneau plutôt que la caméra.
- **`bob@globex.test` a été retiré de `nawa`** à la fin des captures. Il y était
  encore au début de cette itération : le retrait noté à la tranche précédente
  avait bien été fait, puis le compte a été re-invité pour les captures des
  courbes sans que la ligne soit rejouée. La table est revenue à ses deux membres
  réels.

## Vérification du 26-27/08 — « prêts pour la démo ? », **rien de déployé**

Question posée : est-ce que tout est fini et déployé. Réponse courte : la démo
l'est, la suite backend ne l'était pas — elle ne finissait pas, et personne ne
s'en était aperçu parce qu'elle ne finissait pas *silencieusement*.

**Ce qui était déjà en place.** `demo/agentic` est à `411a1e4e`, poussé, arbre
propre. Les images de la VM tournent sur `2b995cdf` : deux commits d'écart, qui
sont un journal (`485b4c80`) et **une** ligne dans un fichier de test
(`411a1e4e`). Aucun code exécuté ne diffère, donc pas de bascule à refaire.
`verify_nawa_data_ml_plane` repasse les 51 lignes du runbook sur la base seedée
de la VM, zéro `DRIFT`, y compris les trois lignes de portabilité — un client
MLflow de série qui résout `champion`, et un skore de série qui rouvre l'état du
rapport. Les trois barrières front sont vertes : `check:i18n` sur 6 862 clés,
1 311 tests unitaires, `build:prod`.

**La suite backend ne terminait pas.** Lancée sur la VM puis en local, elle
s'arrêtait à 67 % pendant plus de quarante minutes à 0,02 % de CPU. Ce n'était
pas un blocage : py-spy montrait le thread principal endormi dans
`create_sqlalchemy_engine_with_retry` de MLflow, appelé depuis `clear_alias` ←
`sync_challenger` ← `run_training`. La ligne 344 de `mlflow/store/db/utils.py`
est le `time.sleep` du réessai, dix tentatives en `0.1 * (2**n - 1)` : environ
101 secondes de sommeil par client construit, pour chaque test qui entraîne.

**La cause est un nom, pas une panne.** `registry_uri()` *dérive* le registre au
lieu de le configurer : un `mlflow-registry.db` fixe à côté de la base
applicative. Le conftest nomme la base par processus
(`pytest_omnirag-{worker}-{pid}.db`) mais son frère dérivé retombe sur un seul
`/tmp/mlflow-registry.db`, ouvert par le processus pytest *et* par chaque
sous-processus du harnais d'entraînement. La contention ne fait échouer aucun
test : elle le fait dormir. C'est pour cela que la panne était invisible — un
test qui dort ne rougit pas, et `--timeout` ne l'attrapait pas non plus tant que
chaque test restait sous la borne.

La mesure qui l'isole tient en une variable : même test, même arbre, seul le
répertoire temporaire change, exécuté pendant qu'une autre suite tenait le
fichier partagé — `TMPDIR` privé, `1 passed in 3.39s` ; `/tmp` partagé, les 101
secondes de réessai. Le conftest nomme donc désormais le registre par processus,
pour la raison qui lui faisait déjà nommer la base par processus, et le supprime
au démontage de session.

**Observables.** Après le correctif la suite atteint sa propre ligne de résumé :
**21 échecs, 5 674 succès, 37 ignorés en 20 min 53 s**. Sans les tests
`integration`, que leur marqueur déclare dépendants de Qdrant sur localhost :
**3 échecs, 5 669 succès, 25 ignorés, 35 désélectionnés en 20 min 52 s** — soit
exactement les trois échecs qui ne sont pas d'environnement. Les deux tests qui
bloquaient passent ensemble en 28,74 s, deux ajustements réels compris, pendant
qu'un autre processus tenait l'ancien fichier partagé.

**Les 21 échecs sont antérieurs à la tranche graphique.** Ils ont été rejoués
tels quels sur `37215e10` (`46fc7ea3~1`), dans un worktree séparé : `diff` des
deux listes vide, ensembles identiques. Dix-huit sont sous `app/tests/integration/`
et réclament Qdrant sur localhost, ce que le marqueur `integration` annonce ;
localhost:6333 répond `000` ici. Restent trois échecs qui ne sont pas
d'environnement et qui méritent d'être nommés :

- `test_zip_member_source_is_bounded_and_traversal_is_rejected` attend
  `member_sha_mismatch` et reçoit `secure_deposit_source_content_changed` :
  c'est une garde extérieure qui parle avant celle que le test interroge.
- `test_secure_deposit_detects_replacement_with_restored_size_and_mtime` et
  `test_secure_deposit_manifest_digest_detects_equal_size_replacement` veulent
  deux empreintes de manifeste différentes après un remplacement de même taille
  et de même mtime, et obtiennent deux fois la même. L'un des deux est passé une
  fois sur deux exécutions : la ligne est sensible à la granularité des dates du
  système de fichiers.

**Dette laissée.**

- **Les trois échecs non liés à l'environnement ne sont pas corrigés.** Aucun ne
  touche le plan data/ML de la démo, et chacun demande une décision sur ce que
  le contrat promet — quelle garde doit parler la première, et sur quoi une
  empreinte de manifeste doit porter — et non un ajustement de test.
- **L'activation du board n'a jamais atterri.** Le commit `4dbc4efc` la porte
  avec douze tests rouges ; il n'est sur aucune branche et n'est pas dans
  `demo/agentic`. Le board reste consultable et non actionnable.
- **La suite complète coûte 21 minutes** même corrigée, et une part de ce prix
  est le même réessai vu d'un autre côté. Trois tests pointent *volontairement*
  le registre sur `postgresql://nobody:nothing@127.0.0.1:1/absent` pour prouver
  qu'une panne du registre ne fait pas échouer un entraînement ; py-spy les a
  retrouvés endormis dans `forget_model` et `publish`. Là le DSN est injoignable
  par intention, donc les 101 secondes sont le comportement attendu de MLflow et
  non une contention à corriger — mais elles achètent une assertion booléenne au
  prix d'une minute et demie chacune, et une borne de réessai passée à ces
  appels rendrait ce temps sans rien retirer à ce qu'ils démontrent.
## Itération du 27/08 — le Playground répond de sa propre version, déployée sur `29aa8981`

GO deploy depuis un Cloud Agent. Une seule tranche, `29aa8981`, sur la base de
`2b995cdf` plus les trois commits de l'isolation du registre pytest. Aucune
migration : la base était déjà à `097_ml_training_plane` et le reste à sa place.
Fenêtre prise avant la bascule
(`/srv/agentium-data/flow-publication-deployments/2026-08-27-29aa898159b5/postgres-pre-switch.dump`,
sha256 `47a88bf2…`).

**Le défaut, et pourquoi il visait le money shot.** Le Playground construit son
formulaire depuis `serving.fields`, et ce bloc est le contrat de la version
*affichée* — ses colonnes, ses bornes, ses catégories. L'appel dessous ne nommait
aucune version, donc `serving_version()` résolvait l'alias et c'est le champion
qui répondait. Juste pour une intégration, faux pour une carte : deux versions
d'une lignée ne sont pas tenues de partager une liste de colonnes, et la lignée
churn seedée ne la partage pas. Relevé sur la VM avant la bascule :

| version | champion | colonnes du contrat |
| --- | --- | --- |
| `churn-radar` v1 | oui | 20 |
| `churn-radar` v2 | non | 20 |
| `churn-radar` v3 | non | **29** |

Ouvrir la v3 et presser Prédire envoyait donc vingt-neuf champs à un modèle qui
en connaissait vingt : `422 ML_PREDICT_FIELD_UNKNOWN`,
`'arpu_per_month' is not an input of this model`. Le même défaut était dans le
cURL à côté, qui portait la ligne de la version affichée sans nommer de version.
La v2 s'en sortait par chance — même contrat que l'alias — mais répondait quand
même depuis la v1 en le laissant croire l'inverse.

**La règle retenue.** Une version qui n'est pas celle qui sert se nomme
elle-même ; la carte du champion reste sans épingle. C'est là que « l'alias
répond pour la lignée » est la démonstration et non une contradiction, et là que
le cURL doit garder la forme que prend `mlflow models serve`. Une seule lecture
(`pinnedVersion`) alimente le bouton et le snippet, donc la commande copiée
reproduit la réponse que la salle vient de voir apparaître ; la ligne à côté du
bouton annonce désormais la version qui *va* répondre plutôt qu'un champion que
l'épingle contourne. L'endpoint acceptait déjà `version` (`ge=1`, absent = « ce
qui sert ») et le client le transmettait déjà : seul l'appelant ne demandait
rien. Aucun changement d'API.

**Observables.**

| Contrôle | Résultat |
| --- | --- |
| Sonde au niveau route, avant bascule | v3, sa propre ligne d'exemple : sans version **422 `ML_PREDICT_FIELD_UNKNOWN`** ; avec `"version": 3` **200**, `served v3`, confiance 0,98977 |
| Suite backend complète | **21 échecs, 5 677 succès, 37 ignorés en 20 min 59 s** — soit exactement +3 succès (les trois tests ajoutés) et le **même** ensemble de 21 échecs qu'avant la tranche |
| `check:i18n` | OK, 6 862 clés sur 21 domaines |
| `test:unit` | **1 314 succès, 0 échec** |
| `build:prod` | propre |
| Plan seedé + épingle, après bascule | **19/19** : 7 datasets prêts, 5 avec parent de lignage, profils de colonnes, dataset scoré, trois versions aux AUC distincts (0,836617 / 0,864133 / 0,853761), un champion, une clé vivante, la skill publiée — et **les trois versions répondent quand leur carte les nomme**, la v3 restant refusée sans épingle |
| Capture UI | v3, même page, même ligne : épingle retirée en vol → refus rouge « A field that was sent is not part of the model's contract », épingle laissée passer → cadran à **1 %** puis **99,1 %** sur un profil à risque, `answered by v3`, cURL portant `"version": 3` |

La capture « avant » n'est pas un autre build : c'est celui-ci avec l'épingle
retirée de la requête en vol, ce qui est exactement l'appel que faisait l'ancien
client. Même page, même version, même ligne — seul le champ que cette révision
ajoute est enlevé.

**Trois frictions d'ops, notées pour la prochaine boucle.**

- **Le worktree est à root.** `git fetch` dans
  `/srv/agentium-data/worktrees/demo-agentic` écrit `FETCH_HEAD` sous
  `release-a/.git/worktrees/release-b/`, qui appartient à root : les verbes git
  du script de déploiement doivent passer par `sudo`.
- **Le gate de stockage aussi.** `runtime-env/` est `drwx------ root root`, donc
  `storage-check`, `migrate` et `up` s'exécutent en root (`sudo env AGENTIUM_IMAGE_TAG=…`).
- **`docker compose run` mange l'entrée standard.** Le script lancé par
  `ssh omnirag-demo "bash -s" < script` s'arrêtait *proprement* après `migrate` :
  le conteneur de migration avait consommé le reste du script depuis stdin. Il
  faut copier le script sur la VM et l'exécuter en tant que fichier.

**Deux observations sur la bascule elle-même.**

- **Le backend met une dizaine de minutes à devenir sain.** Aucune des deux
  images ne porte de cache HuggingFace, donc les huit workers téléchargent
  chacun `cross-encoder/ms-marco-MiniLM-L-6-v2` au démarrage. Pendant ce temps
  nginx rend 502 et le health check échoue (`FailingStreak` 47), puis tout passe
  au vert d'un coup. Ce n'est pas propre à cette tranche — mais un déploiement
  qui abandonne au bout de cinq minutes conclurait à tort.
- **Le compte de capture est refermé.** `bob@globex.test` a été membre
  `workspace_viewer` le temps des captures avec un mot de passe Keycloak jetable ;
  le credential a été **supprimé** (pas rotaté), les sessions révoquées, la
  membership retirée — `nawa` est revenu à ses deux membres réels. Les huit clés
  `pin-probe`/`pin-verify` mintées par les sondes ont été supprimées de la table :
  une clé révoquée reste visible par conception, ce qui est précisément pourquoi
  celles d'une vérification ne doivent pas rester. Seule `Nawa demo` subsiste.

**Note pour qui cherche l'admin Keycloak.** Le client public `core-service` ne
peut pas retirer de service account (`unauthorized_client`) ; c'est
`core-resource-server` — `settings.keycloak_resource_server_id`, avec le même
secret — qui ouvre l'API admin, exactement comme le fait `_get_admin_token()`
dans `auth.py`.

**Dette laissée.** Inchangée depuis la vérification du 26-27/08 : les trois
échecs backend non liés à l'environnement, et l'activation du board
(commit `4dbc4efc`, douze tests rouges, sur aucune branche).

## Itération du 27/08 — couverture MLOps A–D + QA, déployée sur `e5d3b8f2`

GO deploy depuis un Cloud Agent (« polish/QA puis on deploie »). Une pile
`cursor/mlops-coverage-34ca` / [PR #30](https://bitbucket.org/datategy-root/omnirag/pull-requests/30),
pas un merge dans `demo/agentic`. SHA servi
`e5d3b8f207088b9e6d05d071d07bdf4486d81a0a`. Migration `098_ml_predictions`
(additive). Fenêtre
`/srv/agentium-data/flow-publication-deployments/2026-08-27-e5d3b8f20708/`
(`postgres-pre-switch.dump` 456 057 029 o, sha256 `5c9df285ae58…`,
`sha256sum -c` OK).

**Ce que la revue a dû corriger avant la bascule.**

| Défaut | Effet | Correctif |
|---|---|---|
| `badges_for` ignorait le PSI features | Liste Stable, onglet Alerte | Pire des trois signaux, même calcul que `report()` |
| `score_dataset` journalisait `rows=[]` | PSI features aveugle sur le chemin Flow | Échantillon `head(_JOURNAL_ROW_CAP)` des colonnes du contrat |
| `pipeline_provenance` prenait l'ordre `SQL IN` | Mauvais upload en `parents[0]` | Marche `parent_ids` |
| Merge #20 : `_score_into` nommait `model` | NameError au journal du batch | `requested=` distinct de `served` |
| Trailing comma dans `i18n.t()` du tab Environnement | `ng build -c production` rouge sur la VM | Virgule retirée. Les unitaires ne compilent pas le template. |

**Séquence.** Fetch `cursor/mlops-coverage-34ca` dans le worktree root-owned,
images taguées `e5d3b8f20708` seulement (alias `demo-agentic` non déplacé),
dump, `storage-check`, `migrate`, `up`. Script copié et exécuté comme fichier.
Premier build frontend arrêté sur le trailing comma ; second SHA après
correctif.

**Observables après bascule.**

| Contrôle | Résultat |
|---|---|
| `GET /api/v1/build-info` | `e5d3b8f207088b9e6d05d071d07bdf4486d81a0a`, `revision_verified=true` |
| `alembic_version` | `098_ml_predictions` (une ligne) |
| `ml_predictions` | table créée, 0 ligne |
| Images | `agentium-{backend,worker,frontend}:e5d3b8f20708` |
| Frontend servi | `monitor-panel`, `monitor-badge`, `provenance-chain`, `pinned-environment` |
| Backend ciblé | 207 verts |
| `check:i18n` / unitaires / `build:prod` | 6911 clés, 1329 verts, prod local OK |
| Témoin `nawa` | non muté. Pas de `e2e_data_ml_live.py`. |

Rollback images : `AGENTIUM_IMAGE_TAG=29aa898159b5` puis `up`. Ne pas
downgrader `098`. Backend sain en ~2 min (MiniLM déjà en cache, contrairement
aux ~10 min du 27/08 matin).

## Itération du 30/08 — usine NAWA PR→PO, déployée sur `ea19a5b6`

GO land + deploy depuis un Cloud Agent. `origin/demo/agentic` était resté
sur `dc896dad` alors que la VM tournait `e5d3b8f2` (slice MLOps, jamais
atterrie). Le POC vivait 23 commits plus loin sur
`cursor/mcp-pr-to-po-5b89`. Rebase `--onto` le tip journalisé
`71691719` (descendant de `e5d3b8f2`), fast-forward
`dc896dad` → `ea19a5b6cbe26e6761bef8f5c07636b68a369630`. Aucune
migration dans ce slice (098 déjà live).

Le slice ajoute le connecteur MCP (Hikma S/4), le Système **PR to PO**,
l'application métier `pr-to-po` (`/work/pr-to-po`), le nœud recette
`tabulate`, et **Lancer un cycle** via
`POST /work/pr-to-po/bindings/procurement.pr_to_po.run/runs`.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit`, `build:prod` verts ; pytest ciblé 75 verts |
| Push | `demo/agentic` en fast-forward `dc896dad` → `ea19a5b6` (49 commits : 25 déjà live + journal MLOps + 23 POC) |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `ea19a5b6cbe26e6761bef8f5c07636b68a369630`, porcelain vide, fichiers `pr-to-po` présents |
| Build | trois images `agentium-{backend,worker,frontend}:ea19a5b6cbe2`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra (pg, Keycloak, Qdrant, MinIO, RabbitMQ, SFTP, LiveKit) intouchée |
| `build-info` | `revision: ea19a5b6cbe26e6761bef8f5c07636b68a369630`, `revision_verified: true` (backend et frontend) |
| Bundle | `pr-to-po` présent dans le JS servi ; `/` et `/work/pr-to-po` = 200 |
| Logs | 0 `traceback`/`exception` backend depuis la bascule |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Seed `nawa` | Système `28345b5a-0824-4f2b-a420-ebe0aa7cd34f`, Experience `de2264aa-9570-40ee-bdd7-70c30da2c0a2` slug `pr-to-po` r1, liaison `procurement.pr_to_po.run` ; flags `mcp_connector`, `experience_v1`, `flow_workbench_v1` |
| OAuth Hikma | URLs + client id posés, `secret_set=false` — la lecture live reste fermée jusqu'à saisie du secret dans Connexions |
| Canaris carakai | non rejoués dans cette fenêtre (hôte runner non invoqué) |
| Rollback | `AGENTIUM_IMAGE_TAG=e5d3b8f20708` puis `up` ; le seed `nawa` reste (fix-forward) |

## Itération du 31/08 — desk NAWA PR→PO (graphiques, ask, portail in-app), déployée sur `d203e6f8`

GO land + deploy depuis un Cloud Agent. `origin/demo/agentic` était sur
`935d2ccc` (journal docs de l'itération `ea19a5b6`) alors que les
conteneurs tournaient encore `ea19a5b6cbe26e6761bef8f5c07636b68a369630`.
Cinq commits frontend en fast-forward propre
(`935d2ccc` → `d203e6f87a478178c830d17d8f1588de4bbfb5e3`). Aucune
migration dans ce slice.

Le slice ajoute sur `/work/pr-to-po` : voix + graphiques (donut, barres
fournisseurs, couverture), ask déterministe, et le **portail usine**
embarqué (`app-chat-panel` compact, même Système `PR to PO`). L'URL
reste `/work/pr-to-po`. La station d'écriture reste **scellée**.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1355 verts), `build:prod` verts ; pas de pytest backend (slice frontend) |
| Push | `demo/agentic` en fast-forward `935d2ccc` → `d203e6f8` (5 commits) |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `d203e6f87a478178c830d17d8f1588de4bbfb5e3`, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:d203e6f87a47`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra (pg, Keycloak, Qdrant, MinIO, RabbitMQ, SFTP, LiveKit) intouchée |
| `build-info` | `revision: d203e6f87a478178c830d17d8f1588de4bbfb5e3`, `revision_verified: true` (backend et frontend) |
| Bundle | chaînes `Factory portal`, `Ask the factory`, `Live read` présentes dans le JS servi ; `/` et `/work/pr-to-po` = 200 |
| Logs | 0 `traceback`/`exception` backend depuis la bascule |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Smoke desk | lecture live nawa : PR 8 / inbox 2 / PO 8 / GR limité ; couverture 100 % ; ask « Can we write » → scellé ; « how many purchase orders » → 8 PO ; texte libre « explain this dossier to me » ouvre le portail **sans** quitter `/work/pr-to-po` ; rail d'historique `display:none` ; prompt cite le briefing + write sealed |
| Seed `nawa` | inchangé — Système `28345b5a-0824-4f2b-a420-ebe0aa7cd34f`, Experience `de2264aa-9570-40ee-bdd7-70c30da2c0a2` slug `pr-to-po` r1, liaison `procurement.pr_to_po.run` |
| Flags | `mcp_connector`, `experience_v1`, `flow_workbench_v1` déjà on ; `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre (hôte runner non invoqué) |
| Rollback | `AGENTIUM_IMAGE_TAG=ea19a5b6cbe2` puis `up` ; aucun schéma à reculer |

## Itération du 31/08 — justification PR live (`get_A_PurchaseRequisitionItem_by_key`), déployée sur `bc5810b3`

GO land + deploy depuis un Cloud Agent. `origin/demo/agentic` était déjà
sur `bc5810b3864313d4e44a75410ea175f1bc08af56` (land ff de
`e52b2696` : journal `d203e6f8` + deux commits justification). La VM
tournait encore `d203e6f87a478178c830d17d8f1588de4bbfb5e3`. Aucune
migration dans ce slice.

Le slice ajoute `POST /api/v1/mcp/servers/{id}/read` (lecture cléée,
outils write refusés) et le bouton desk **Read justification** /
**Lire la justification**. L'outil live
`get_A_PurchaseRequisitionItem_by_key` est appelé avec les clés
Fayçal (`PurchaseRequisition=2000276450`, item `10`, expand
`to_PurchaseReqnItemText`). Le texte sort de `NoteDescription` (pas
d'alias inventé). La preview keyless n'est pas assouplie. La station
d'écriture reste **scellée**. Le bouton ne démarre pas de Run.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1356 verts), `build:prod` verts ; pytest `test_mcp_read` + preview/call/fixture/nawa 39 verts (avant land) |
| Push | `demo/agentic` déjà à `bc5810b3` avant le switch VM |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `e52b2696` → `bc5810b3864313d4e44a75410ea175f1bc08af56` ff-only, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:bc5810b38643`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra (pg, Keycloak, Qdrant, MinIO, RabbitMQ, SFTP, LiveKit) intouchée |
| `build-info` | `revision: bc5810b3864313d4e44a75410ea175f1bc08af56`, `revision_verified: true` (backend et frontend) |
| Bundle | `Read justification`, `Lire la justification`, `get_A_PurchaseRequisitionItem_by_key` dans le JS servi ; `/` et `/work/pr-to-po` = 200 |
| Logs | 0 `traceback`/`exception` backend depuis la bascule |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `400f1bdf…`) |
| Smoke API | `POST /mcp/servers/sap/read` 200, `tool=get_A_PurchaseRequisitionItem_by_key`, `text=LORX  FURNITURE CLEANER  - 650 ML - GREEN` |
| Smoke desk | bouton **Read justification** poste les clés Fayçal ; fact dossier `justification` via l'outil live ; **Read selected requisition** offert (PR live ≠ `2000276450`) ; Write **SEALED** ; pas de Run |
| Seed `nawa` | inchangé — Système `28345b5a-0824-4f2b-a420-ebe0aa7cd34f`, Experience `de2264aa-9570-40ee-bdd7-70c30da2c0a2` slug `pr-to-po` r1, liaison `procurement.pr_to_po.run` |
| Flags | `mcp_connector`, `experience_v1`, `flow_workbench_v1` déjà on ; `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre (hôte runner non invoqué) |
| Rollback | `AGENTIUM_IMAGE_TAG=d203e6f87a47` puis `up` ; aucun schéma à reculer |

## Itération du 31/08 — alignement PDF lecture / écriture scellée, déployée sur `38c94289`

GO land + deploy depuis un Cloud Agent. `origin/demo/agentic` est passé
`9ea69594` → `38c94289675250d3061d69dddc4f79b7a1c2b8fb` (4 commits, ff
propre). La VM tournait `bc5810b3864313d4e44a75410ea175f1bc08af56`.
Aucune migration dans ce slice.

Le slice aligne le desk **Run the factory** et les skills nommées sur les
outils PIH QA (`get_A_PurchaseRequisitionItem`, `fi_Validate`,
`get_A_PurReqnAcctAssgmt`, `get_A_PurchaseOrderItem` + 5 headers). Les
écritures `post_A_PurchaseOrder` (serveur hikma, type NB) et
`fi_DiscardFromPurchasing` sont **composées** après `tools/list`, jamais
appelées. Budget `Type E` = fact seulement. `fi_EnableForPurchasing`
n’est pas utilisé. Preview `_by_key` inchangée. Station write **scellée**.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1359 verts), `build:prod` verts ; pytest MCP+nawa 46 verts |
| Push | `demo/agentic` en fast-forward `9ea69594` → `38c94289` (4 commits) |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `bc5810b3` → `38c94289675250d3061d69dddc4f79b7a1c2b8fb` ff-only, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:38c942896752`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra (pg, Keycloak, Qdrant, MinIO, RabbitMQ, SFTP, LiveKit) intouchée |
| `build-info` | `revision: 38c94289675250d3061d69dddc4f79b7a1c2b8fb`, `revision_verified: true` (backend et frontend) |
| Bundle | `get_A_PurchaseRequisitionItem`, `fi_Validate`, `get_A_PurReqnAcctAssgmt`, `IsClosed eq false`, `Funds center` / `Centre de fonds` ; aucun `post_A_PurchaseOrder` / `fi_Discard*` dans le JS servi |
| Logs | 0 `traceback`/`exception` backend depuis la bascule ; 0 `tools/call` write |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `400f1bdf…` / ids `d14cd3a9` / `f8a99caa` / `bc950852`) |
| Smoke API | `POST /mcp/servers/sap/read` items 200, `tool=get_A_PurchaseRequisitionItem`, 50 lignes, `__count` 65833, retenue `2000276449` « STICKER WHITE » `MaterialGroup=Z100001` ; `fi_Validate` 200 (0 ligne = pass) ; imputation 200 (0 ligne sur cette PR) ; hikma items 200, 50/200 ; writes `post_A` / `fi_Discard` / `fi_Enable` → 400 `not a read` |
| Seed `nawa` | relancé sans secret (encrypted conservé, `oauth_secret_set=true`) ; Système `28345b5a-0824-4f2b-a420-ebe0aa7cd34f`, Experience slug `pr-to-po` r1, liaison `procurement.pr_to_po.run` |
| DAG publié | **non remplacé** — brouillon opérateur `faycal.benaissa@datategy.net` rev 6 préservé (`operator_draft_preserved`). Les skills du cycle tournent quand même le nouveau code (reads live / writes compose-only). `inputs_map` publié reste `pr_type` seul. |
| Flags | `mcp_connector`, `experience_v1`, `flow_workbench_v1` déjà on ; `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre (hôte runner non invoqué) |
| Rollback | `AGENTIUM_IMAGE_TAG=bc5810b38643` puis `up` ; aucun schéma à reculer |

## Itération du 31/08 — desk quatre temps Fayçal, déployée sur `d46e6bf1`

GO land + deploy depuis un Cloud Agent, branche `demo/agentic` (pas de
branche `cursor/*`). `origin/demo/agentic` est passé `4c055e58` →
`d46e6bf1a12d51a55582b0c0192ae62a95b63bb6` (1 commit desk, ff propre).
Aucune migration. Le slice rend visibles les quatre preuves de démo :
lecture SAP MCP live, résumé de justification, POST hikma
`post_A_PurchaseOrder` type NB scellé, portail lecture seule get PR / get PO.

Playbook opérateur EN illustré :
`docs/ops/nawa-pr-to-po-live-demo-playbook.docx`.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1361 verts), `build:prod` verts |
| Push | `demo/agentic` en fast-forward `4c055e58` → `d46e6bf1` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `38c94289` → `d46e6bf1a12d51a55582b0c0192ae62a95b63bb6` ff-only, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:d46e6bf1a12d`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: d46e6bf1a12d51a55582b0c0192ae62a95b63bb6`, `revision_verified: true` |
| Bundle | `Success criteria`, `Compose the POST`, `Justification summary`, `post_A_PurchaseOrder` dans le JS servi |
| Logs | 0 `traceback`/`exception` backend depuis la bascule |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `d14cd3a9` / `f8a99caa` / `bc950852`) |
| Smoke API | `get_A_PurchaseRequisitionItem` 200 ; writes `post_A` / `fi_Discard` / `fi_Enable` → 400 `not a read` |
| Smoke desk | quatre beats Shown après Run the factory + Summarise ; POST sealed `called: false` type NB ; chips Ask + portail lecture seule |
| Seed / DAG | inchangés — Système `28345b5a-…`, liaison `procurement.pr_to_po.run` sur v2 `b9217063-…` |
| Flags | `mcp_connector`, `experience_v1`, `flow_workbench_v1` déjà on ; `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre |
| Rollback | `AGENTIUM_IMAGE_TAG=38c942896752` puis `up` ; aucun schéma à reculer |

## Itération du 31/08 — polish quatre temps + playbook, déployée sur `3eb72f95`

GO land + deploy depuis un Cloud Agent, branche `demo/agentic` (pas de
branche `cursor/*`). `origin/demo/agentic` est passé `d46e6bf1` →
`a05af224` (desk : un scroll, résumé auto, POST scellé) puis
`3eb72f95f6b6b778e039ea5cab215f0d19c6d47f` (playbook d46e + journal).
Aucune migration. Le desk joue les quatre preuves Fayçal sur une page.
Le playbook opérateur EN illustré
`docs/ops/nawa-pr-to-po-live-demo-playbook.docx` est réaligné sur ce SHA
(figures live4, rollback `d46e6bf1a12d`).

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | déjà verts sur `a05af224` (`check:i18n`, `check:ui-chrome`, `test:unit` 1361, `build:prod`) ; ce SHA docs ne les rejoue pas |
| Push | `demo/agentic` en fast-forward `d46e6bf1` → `3eb72f95` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `d46e6bf1` → `3eb72f95f6b6b778e039ea5cab215f0d19c6d47f` ff-only, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:3eb72f95f6b6`, label 40-hex identique ; conteneurs créés `2026-08-31T09:28:12Z` |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: 3eb72f95f6b6b778e039ea5cab215f0d19c6d47f`, `revision_verified: true` |
| Bundle | `Success criteria`, `Compose the POST`, `Justification summary`, `post_A_PurchaseOrder` dans le JS servi |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste `d14cd3a9` / `f8a99caa` / `bc950852`) |
| Smoke API | `get_A_PurchaseRequisitionItem` 200 (outil exact) ; `get_A_PurchaseRequisitionItem_by_key` 200 texte `STICKER WHITE` ; `fi_Validate` 200 ; `get_A_PurReqnAcctAssgmt` 200 (0 ligne sur cette PR) ; hikma `get_A_PurchaseOrder` / `get_A_PurchaseOrderItem` 200 ; writes `post_A` / `fi_Discard` / `fi_Enable` → 400 `not a read` |
| Smoke desk | quatre beats `done` après lecture live + résumé `azure_llm_v1` ; POST `hikma` `post_A_PurchaseOrder` `sealed: true` `called: false` type `NB` fournisseur `1000001737` PR `2000276449` ; chip *Can we write* = No ; portail *Read only. Answer with get PR and get PO tools.* |
| Seed / DAG | inchangés — Système `28345b5a-…`, liaison `procurement.pr_to_po.run` sur v2 `b9217063-…` ; seed **non** relancé |
| Flags | `mcp_connector`, `experience_v1`, `flow_workbench_v1` déjà on ; `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre |
| Rollback | `AGENTIUM_IMAGE_TAG=d46e6bf1a12d` puis `up` ; aucun schéma à reculer |

## Itération du 31/08 — bureau opérateur, déployée sur `cd40fe33`

GO land + deploy depuis un Cloud Agent, branche `demo/agentic`.
`origin/demo/agentic` est passé `73fb7e55` →
`cd40fe337285058120ec7236d587b1853ca72c42`. Aucune migration.
Le strip présentateur (critères de succès, pastilles 1–4, « succès de
cette démo ») quitte l’UI. Le bureau reste un poste de travail : KPI,
dossier, brouillon de commande scellé, questions. Les rappels Fayçal
restent dans `docs/ops/nawa-pr-to-po-live-demo-playbook.docx`.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1361 verts), `build:prod` verts |
| Push | `demo/agentic` en fast-forward `73fb7e55` → `cd40fe33` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `3eb72f95` → `cd40fe337285058120ec7236d587b1853ca72c42` ff-only, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:cd40fe337285`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: cd40fe337285058120ec7236d587b1853ca72c42`, `revision_verified: true` |
| Bundle | plus de `Success criteria` / `Compose the POST` / `success of this demo` dans le JS servi |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Smoke API | writes `post_A_PurchaseOrder` → 400 `not a read` |
| Smoke desk | pas de `.xp-desk-beats` ; KPI 50/2/5 ; Write **Sealed** ; résumé `azure_llm_v1` ; brouillon `hikma` `post_A_PurchaseOrder` `sealed: true` `called: false` type `NB` ; chip *Write status* = No |
| Seed / DAG | inchangés — seed **non** relancé |
| Flags | `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre |
| Rollback | `AGENTIUM_IMAGE_TAG=3eb72f95f6b6` puis `up` ; aucun schéma à reculer |

## Docs du 31/08 — playbook Fayçal réeligné sur le bureau opérateur

Pas de bascule VM. SHA live inchangé
`cd40fe337285058120ec7236d587b1853ca72c42`. Les rappels Fayçal ne sont plus
seulement le Word : trois fichiers à jour, calés sur les libellés EN du
bureau (plus de tuiles 1–4 / Success criteria / *Can we write*).

| Fichier | Usage |
|---|---|
| `docs/ops/nawa-pr-to-po-live-demo-playbook.md` | Handout EN (preuves, script, exemple live STICKER WHITE) |
| `docs/ops/nawa-pr-to-po-live-demo-presenter-fr.md` | Carte présentateur FR, une page |
| `docs/ops/nawa-pr-to-po-live-demo-playbook.docx` | Même contenu, illustré (figures `nawa-pr-to-po-playbook-figures/`) |
| `docs/ops/build-nawa-pr-to-po-playbook.py` | Régénération du Word |

Pointeur aussi dans `docs/agentium-release-process.md` §12.

## Itération du 31/08 — compose BAPI ZLPO scellé, déployée sur `34731192`

GO land + deploy depuis un Cloud Agent, branche `demo/agentic`.
`origin/demo/agentic` est passé `cd40fe33` →
`347311924faba4fc6686a05c3318cb5d2415fa2a`. Aucune migration.
Le bureau compose un package `bapi_po` / `BAPI_PO_CREATE1` type **ZLPO**
depuis les commandes les plus récentes de l’établissement (plus de
majorité groupe-matériel, plus de type NB, plus de TESTRUN). L’écriture
reste scellée : pas de `tools/call` live.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1364 verts), `build:prod` verts ; pytest MCP/flow scoped verts |
| Push | `demo/agentic` en fast-forward `cd40fe33` → `34731192` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `cd40fe33` → `347311924faba4fc6686a05c3318cb5d2415fa2a` ff-only, porcelain vide |
| Build | trois images `agentium-{backend,worker,frontend}:347311924fab`, label 40-hex identique |
| Dump / migrate | sautés — pas de nouvelle révision Alembic |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: 347311924faba4fc6686a05c3318cb5d2415fa2a`, `revision_verified: true` |
| Bundle | `BAPI_PO_CREATE1`, `bapi_po`, `ZLPO`, *plant supplier*, *Compiled brief* dans les chunks JS servis |
| Alias | tag mobile `demo-agentic` **non déplacé** (reste sur l’image `400f1bdf452c`) |
| Smoke API | `hikma` `post_A_PurchaseOrder` → 400 `not a read` ; `bapi_po` `/read` → 400 `mcp_unconfigured` (connecteur non attaché — le package compose le `server_id`, il n’appelle pas) |
| Smoke desk | hard-reload EN ; KPI 50/2/20/0 ; Write **Sealed** ; résumé `azure_llm_v1` ; brouillon `bapi_po` `BAPI_PO_CREATE1` `sealed: true` `called: false` `testrun: false` type **ZLPO** ; `PURCH_ORG` = `COMP_CODE` = `1000` ; fournisseur `1000000018` via commande la plus récente ; PR `2000276449` / `00020` PAPER BAG ; chip *Write status* = No |
| Seed / DAG | inchangés — seed **non** relancé |
| Flags | `sap_hana_connector` reste off |
| Canaris carakai | non rejoués dans cette fenêtre |
| Rollback | `AGENTIUM_IMAGE_TAG=cd40fe337285` puis `up` ; aucun schéma à reculer |
| Playbook | SHA / images / exemple live réelignés sur `34731192` (PAPER BAG, 50/2/20, BAPI ZLPO) |

## Itération du 31/08 — orbes de lecture, déployée sur `64178930`

GO desk : `ck-thinking-orb` sur **Run the factory** (`searching`, 20) et
**Start a cycle** (`working`, 20), plus le slot de première lecture (64).
Pas de reroute de layout. `origin/demo/agentic` `91b9a348` →
`6417893067f9e4b2f17bc1cd2d7dbf7da54acb9c`. Aucune migration.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1364 verts), `build:prod` verts |
| Push | `demo/agentic` en fast-forward `91b9a348` → `64178930` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `34731192` → `6417893067f9e4b2f17bc1cd2d7dbf7da54acb9c` ff-only |
| Build | trois images `agentium-{backend,worker,frontend}:6417893067f9` |
| Dump / migrate | sautés |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: 6417893067f9e4b2f17bc1cd2d7dbf7da54acb9c`, `revision_verified: true` |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Smoke desk | hard-reload ; bouton *The factory is reading SAP…* avec canvas orbe ; slot `.xp-desk-reading` orbe 64 ; après lecture : PAPER BAG / `1000000018` / Write **Sealed** / `BAPI_PO_CREATE1` |
| Seed / DAG | inchangés — seed **non** relancé |
| Flags | `sap_hana_connector` reste off |
| Canaris carakai | non rejoués |
| Rollback | `AGENTIUM_IMAGE_TAG=347311924fab` puis `up` ; aucun schéma à reculer |

## Itération du 01/09 — correctifs QA visuelle, déployée sur `97771958`

GO desk après QA visuelle : dates OData formatées `YYYY-MM-DD` dans les
tables, en-têtes courts (nom SAP brut en tooltip) pour supprimer le
rognage 1080p, prompt du portail réécrit sans noms d'outils d'écriture,
justification lue sur l'item **sélectionné** (repli étiqueté `item 10`
si la ligne n'a pas de texte). `origin/demo/agentic` `64178930` →
`97771958db08158197d562f851cdf34ef82de950`. Aucune migration.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1365 verts), `build:prod` verts |
| Push | `demo/agentic` en fast-forward `64178930` → `97771958` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | `64178930` → `97771958db08158197d562f851cdf34ef82de950` ff-only |
| Build | trois images `agentium-{backend,worker,frontend}:97771958db08` |
| Dump / migrate | sautés |
| `storage-check` | sortie 0 |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: 97771958db08158197d562f851cdf34ef82de950`, `revision_verified: true` |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Smoke desk | zéro `/Date(` à l'écran, 6 dates ISO ; zéro table rognée (`scrollWidth ≤ clientWidth`) ; en-têtes `PR / ITEM / ITEM TEXT / MATL GROUP / QTY` et `PO / TYPE / SUPPLIER / ORDERED / PURCH ORG` ; justification **PAPER BAG** via `get_A_PurchaseRequisitionItem_by_key · item 20` (cohérente avec la sélection, sans repli) ; prompt du portail sans `BAPI_*` ni `post_A_*` |
| Seed / DAG | inchangés — seed **non** relancé |
| Flags | `sap_hana_connector` reste off |
| Canaris carakai | non rejoués |
| Rollback | `AGENTIUM_IMAGE_TAG=6417893067f9` puis `up` ; aucun schéma à reculer |

## Itération du 01/09 — skin NAWA du portail + session vierge, déployée sur `301bb73d`

GO chatbot : le chat du portail prend la charte NAWA (bulles utilisateur
corail en dégradé, bulles assistant charbon chaud, bouton Ask corail,
liens Deep search corail / Correct sauge), orbes aux trois moments
(en-tête du portail, état vide, pilule de streaming, halo corail),
`freshSession` pour ouvrir le portail sur une conversation vierge, et
prompt du portail ré-ancré (outils de lecture + faits du desk) après
qu'une reformulation avait rendu les réponses évasives. Quatre commits
`97771958` → `301bb73dbee8f9b99e11e77c764d5476f7a07d0f`. Aucune migration.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n`, `check:ui-chrome`, `test:unit` (1366 verts), `build:prod` verts |
| Push | `demo/agentic` en fast-forward `97771958` → `301bb73d` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | ff-only jusqu'à `301bb73dbee8f9b99e11e77c764d5476f7a07d0f` |
| Build | images `agentium-{backend,worker,frontend}:301bb73dbee8` (itérations intermédiaires `dd2edd41`, `a3f89be9`, `e02c3773` également construites puis remplacées) |
| Dump / migrate | sautés |
| `storage-check` | sortie 0 à chaque bascule |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: 301bb73dbee8f9b99e11e77c764d5476f7a07d0f`, `revision_verified: true` |
| Alias | tag mobile `demo-agentic` **non déplacé** |
| Smoke chat | portail ouvert sur session vierge (0 bulle), orbe d'en-tête + orbe d'état vide + pilule orbe pendant le streaming ; Ask `rgb(232,84,58)` ; bulle utilisateur dégradé corail ; bulle assistant `rgb(29,29,29)` ; Deep search corail ; réponse ancrée « 50 requisitions, 20 orders, supplier 1000000018 » ; suivi « nothing written to SAP » ; aucun nom d'outil d'écriture dans les réponses |
| Seed / DAG | inchangés — seed **non** relancé |
| Flags | `sap_hana_connector` reste off |
| Canaris carakai | non rejoués |
| Rollback | `AGENTIUM_IMAGE_TAG=97771958db08` puis `up` ; aucun schéma à reculer |

## Itération du 01/09 — Agent Studio + écriture SAP réelle, déployée sur `c789d070`

GO SAP : le NAWA Agent Studio prend la racine `/work/pr-to-po` (Run flow /
Chat, rail d'outils MCP, nœuds dépliables avec appels verbatim, gate
d'approbation avec provenance par champ, guardrails côté client), le desk
reste sur `/work/pr-to-po/desk`. Nouveau chemin d'écriture backend
flag-gaté : `POST /mcp/servers/{id}/invoke` (allow-list `BAPI_PO_CREATE1`,
`BAPI_TRANSACTION_COMMIT`, `BAPI_TRANSACTION_ROLLBACK`, ban `TESTRUN`,
rollback automatique sur create échoué, audit systématique), serveurs
`bapi_po`/`bapi_pr` au seed, flag workspace `sap_write_unsealed` **on**
pour `nawa`. Commits `ad3be20e` → `c789d0703779c8de9b63ddab2ea9e42894dc3947`.

Trois défauts trouvés et corrigés en QA live, dans l'ordre :

1. `4c20a215` — le schéma live de `BAPI_PO_CREATE1` exige `POHEADER`/
   `POHEADERX` sous `import`, pas sous `tables` (502 `mcp_call_failed` en
   preuve) ; et un corps d'erreur HTTP sans clé `sealed` se lisait comme
   un succès scellé — corrigé dans `outcomeFromInvoke`.
2. `f54c62ad` — les PR à prix réel prennent les créneaux du gate en
   premier (SAP rejette un create à 0.00 : `06/215`), carte flaguée quand
   la demande ne porte aucun prix.
3. `c789d070` — cause racine du 0.00 : `PREVIEW_COL_CAP = 8` éjectait
   `PurchaseRequisitionPrice`, `OrderedQuantity`, `PurReqnItemCurrency`
   et `DeliveryDate` de la preview ; cap relevé à 18 et champs du contrat
   PR→PO ajoutés aux colonnes préférées, test de régression
   `test_pr_item_preview_keeps_the_fields_the_agent_posts_from`.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n` (7265 clés), `check:ui-chrome`, `test:unit` (1377 verts), `build:prod` verts |
| Pytest image | 55 verts dans `agentium-backend:c789d0703779` (`test_mcp_preview`, `test_mcp_read`, `test_mcp_fixture`, `test_mcp_write`, `test_mcp_oauth`, `test_mcp_call_skill`) |
| Push | `demo/agentic` en fast-forward `301bb73d` → `4c20a215` → `f54c62ad` → `c789d070` |
| Ancre | `/home/ubuntu/omnirag` intouchée |
| Worktree | ff-only jusqu'à `c789d0703779c8de9b63ddab2ea9e42894dc3947` |
| Build | images `agentium-{backend,worker,frontend}:c789d0703779` (`4c20a215959c` et `f54c62ad27c1` construites puis remplacées) |
| Dump / migrate | `migrate` sans schéma nouveau ; `storage-check` sortie 0 à chaque bascule |
| `up` | cinq services applicatifs recréés ; infra intouchée |
| `build-info` | `revision: c789d0703779c8de9b63ddab2ea9e42894dc3947`, `revision_verified: true` |
| Sealed (flag off) | vérifié avant activation : `invoke` renvoie `sealed: true, called: false`, aucun appel réseau |
| Écriture réelle | **PO `4500382538` créé et committé** (PR `2000276658`, 100 × 100.00 SYP, ZLPO, org 8675) via gate → `BAPI_PO_CREATE1` + `BAPI_TRANSACTION_COMMIT` ; relu et confirmé côté SAP par `get_A_PurchaseOrder` (CreatedByUser `SAP_MCP`) |
| Guardrail | toggle `BAPI_PO_CREATE1` off → « Blocked by the guardrail — no call was made », aucun appel réseau, transcript conservé |
| Smoke Studio | badge `SAP WRITE LIVE`, run flow jusqu'au gate (discard sauté volontairement), 3 propositions à prix réels avec provenance, chat répond, `/work/pr-to-po/desk` vivant |
| Seed | relancé pour attacher `bapi_po`/`bapi_pr` et poser `sap_write_unsealed` |
| Flags | `sap_write_unsealed` **on** pour `nawa` — désactivable instantanément en relançant le seed sans la variable |
| Canaris carakai | non rejoués |
| Rollback | `AGENTIUM_IMAGE_TAG=301bb73dbee8` puis `up` ; flag `sap_write_unsealed` à retirer du seed si retour arrière complet |

## Itération du 01/09 — écriture conversationnelle + prompt ancré, déployée sur `41a60d7f`

Demande SAP : l'écriture doit exister aussi dans le conversationnel, avec un
dialogue de confirmation vers l'humain **dans le fil**. Livré en un commit
`41a60d7f9e348e0f57f8934e37a8f632b9f1d74a` :

- **Prompt resserré.** Le chat classique ne peut pas appeler d'outils ; le
  Studio exécute donc lui-même les lectures SAP (réquisitions + historique
  PO par site) et injecte un fact-sheet en direct dans le prompt
  (`studioFactSheet`). Consigne explicite : répondre depuis ces faits,
  ne jamais annoncer une lecture « à faire plus tard » — le travers que la
  QA attrapait à chaque passe.
- **Dialogue d'écriture dans le fil.** La 5e chip devient « Créer la
  commande » (ordre du scénario de démo) : bulle utilisateur, bulle agent
  avec proposition + provenance + payload exact dépliable, boutons
  Confirmer / Annuler dans la conversation. La confirmation emprunte le
  même chemin gardé que le gate du Run flow (`guardrailBlocked` puis
  `POST /mcp/servers/bapi_po/invoke`, create puis commit) ; garde-fou
  coupé → bulle de refus « aucun appel émis », appel bloqué visible dans
  le déroulé du dialogue.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n` (7278 clés), `check:ui-chrome`, `test:unit` (1380 verts), `build:prod` verts |
| Push | `demo/agentic` en fast-forward `64d9fb67` → `41a60d7f` |
| Worktree | ff-only jusqu'à `41a60d7f9e348e0f57f8934e37a8f632b9f1d74a` |
| Build | images `agentium-{backend,worker,frontend}:41a60d7f9e34` |
| `storage-check` / `migrate` / `up` | sortie 0 ; cinq services applicatifs recréés (une bascule ratée sur un tag mal saisi `41a60d7f7f0b`, sans effet — reprise immédiate sur le bon tag) |
| `build-info` | `revision: 41a60d7f9e348e0f57f8934e37a8f632b9f1d74a`, `revision_verified: true` |
| Chat ancré | chip « Demandes ouvertes » → réponse listant les vraies PR (2000276630 « Testing Material » 8.00 ALL site 3540, …) avec fournisseurs/termes de l'historique ; aucune « lecture annoncée » |
| Garde-fou dans le fil | `BAPI_PO_CREATE1` off → Confirmer → bulle « aucun appel émis — rien n'a été écrit », zéro appel réseau |
| Écriture conversationnelle | ré-ouverture, Confirmer → **PO `4500382543` créé et validé** (PR 2000276630, 1000 KG × 8.00 ALL, ZLPO, org 3540) ; relu côté SAP (`CreatedByUser: SAP_MCP`) |
| Seed / flags | inchangés — `sap_write_unsealed` reste on pour `nawa` |
| Rollback | `AGENTIUM_IMAGE_TAG=c789d0703779` puis `up` |

## Itération du 01/09 (bis) — polish du chat Studio, déployée sur `988ee5c7`

Demande : « petits coups de polish sur le chat, orbs, zone de texte agréable,
bonne clarté de la conversation ». Deux commits, `4857b977` puis `988ee5c7`
(correction de libellé), déployés l'un après l'autre :

- **Clarté du fil.** Le prompt technique (fact-sheet SAP + consignes) ne
  transite plus par la bulle utilisateur : le chat-panel gagne une entrée
  `systemPrompt` envoyée sur le rôle système de la requête (`system_prompt`,
  déjà honoré côté backend), et le Studio n'affiche dans le fil que la
  question humaine. La zone de texte se pré-remplit donc avec la question
  nue, plus jamais avec le pavé d'instructions.
- **Orbs.** En-tête du portail chat avec orbe + titre « Conversation avec
  l'agent » et rappel « les écritures attendent toujours votre accord » ;
  avatar orbe accolé à la bulle agent du dialogue d'écriture (état `working`
  pendant le post).
- **Zone de texte.** Composer plus généreux (52 px min, padding 14/16,
  rayon 14 px, placeholder adouci), halo corail doux au focus à la place de
  l'anneau Tailwind brut, bouton micro aligné sur la même hauteur ; bulles à
  0.95 rem / interligne 1.55–1.65.
- **Libellé.** « 1 tool calls » → « Tool calls: 1 — full transcript »
  (idem FR), attrapé sur capture pendant la QA.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n` (7280 clés), `test:unit` (1381 verts, dont le nouveau contrat « la bulle ne porte que la question ») , `build:prod` verts |
| Push | `demo/agentic` en fast-forward `41a60d7f` → `4857b977` → `988ee5c7` |
| Worktree | ff-only jusqu'à `988ee5c7ec2c1ab2a16e6d42831518d51ed6b39a` |
| Build | images `agentium-{backend,worker,frontend}:4857b977a059` puis `:988ee5c7ec2c` (le second lot d'abord mal taggé `988ee5c7fc4a`, retaggé avant `up`, tag fautif supprimé) |
| `storage-check` / `up` | sortie 0 ; cinq services applicatifs recréés à chaque bascule |
| `build-info` | `revision: 988ee5c7ec2c…`, `revision_verified: true` |
| QA Playwright | pré-remplissage = question nue (68 caractères, zéro consigne) ; bulle utilisateur = question seule ; réponse ancrée (PR 2000276501/20, 2000276559/10, 2000276580/10) sans « lecture annoncée » ; orbe d'en-tête et avatar orbe du dialogue présents ; annulation → « Understood — nothing was written », aucune écriture émise |
| Écritures | aucune sur cette itération (dialogue testé jusqu'à l'annulation) ; le chemin gardé create+commit est inchangé depuis `41a60d7f` |
| Seed / flags | inchangés — `sap_write_unsealed` reste on pour `nawa` |
| Rollback | `AGENTIUM_IMAGE_TAG=41a60d7f9e34` puis `up` |

## Itération du 03/09 — réalignement H0+H1, déployée sur `1134a61d`

Chantier du plan de réalignement post-audit, sous gel (voir en tête de
journal). Branche `cursor/realign-h0-h1-5b89`, PR vers `demo/agentic` ; la VM
sert le SHA de la PR en attendant la fusion.

- **Une porte d'écriture (H0).** Tout `tools/call` non-lecture — HTTP
  `/mcp/servers/{id}/invoke`, skills nommés du run-engine, `mcp_call_v1` —
  passe par `connectors/mcp/write.py` : allow-list BAPI, interdiction de
  `TESTRUN`, flag `sap_write_unsealed`, garde-fous `disabled_tools`, rollback
  automatique d'un create sans commit, audit `mcp.write.invoked` pour chaque
  appel qui est parti. Nouvelle règle : **une écriture que personne n'a
  décidée reste scellée** (`reason: unattended`) même flag levé — expiration
  de porte (`system:gate_ttl`), tick planifié, branche automatique.
- **Un runtime PR→PO côté serveur (H1).** Le DAG `pr_to_po_flow` porte la
  sélection de PR (`select_next_pr` : PR avec prix réel d'abord, candidats
  exposés), la porte humaine enrichie (candidats, conditions de paiement,
  incoterms, `decided_by`) et les écritures `task.create_po` /
  `task.handle_rejection`. Le Studio est un client du `Run` : il démarre par
  le binding, suit `checkpoints` et `invocations`, décide par l'HITL
  canonique et n'appelle jamais un serveur MCP. `pr-to-po-desk.ts` et
  `PrToPoBoardComponent` supprimés, `/work/pr-to-po/desk` redirige.
- **Trouvé pendant le déploiement, corrigé sur la branche.**
  `task.audit` échouait à chaque tick depuis le 01/09 (« audit_log_v1
  requires an event_type ») : `config.params` n'atteint un skill qu'en mode
  strict, or les runs publiés marchent en `dag_overlay`. Le nœud mappe
  désormais ses propres params via l'espace `node` (test
  `test_audit_node_reaches_its_event_type_in_overlay_mode`, faux `audit`
  des tests DAG rendu exigeant). Et le seed rendait `system ready` alors que
  la réconciliation répondait `operator_draft_preserved` : la v2 du flow
  (31/08) était restée la version live parce qu'un brouillon opérateur
  (rev 8, retouches de canvas sans changement sémantique) tenait le System.
  Le seed imprime maintenant le statut, avertit et sort en 1 quand le flow
  n'est pas celui du fichier ; il reprend aussi les positions du canvas
  publié pour ne pas déranger la mise en page de l'opérateur.

### Observables du déploiement

| Pas | Observé |
|---|---|
| Gates | `check:i18n` (7165 clés, 22 règles lexique), `run-unit` 1360 verts ; pytest ciblé (`test_mcp_write`, `test_mcp_call_skill`, `test_nawa_pr_to_po_flow`, `test_mcp_read`, `test_mcp_fixture`) 65 verts sur la VM (image `test-realign`), puis 10/10 sur le flow après le correctif audit (3 échecs reproduits sans lui) |
| Worktree | `sudo git fetch origin cursor/realign-h0-h1-5b89 && checkout --detach` → `f12f8d74`, `b35319a4`, puis `1134a61d8613ae9a6b6c649d0c465d2963e07340` |
| Build | trois lots `agentium-{backend,worker,frontend}` : `:f12f8d745d16` (~35 min, cache pip froid), `:b35319a41473`, `:1134a61d8613` (~10 min avec cache) ; `AGENTIUM_IMAGE_REVISION` = SHA complet |
| Dumps pré-bascule | `flow-publication-deployments/2026-09-02-f12f8d745d16/` (sha256 `df007536…`) et `2026-09-03-1134a61d8613/` (sha256 `ba4a5b65…`), 462 Mo chacun |
| `storage-check` / `migrate` / `up` | sortie 0 ; aucune nouvelle révision Alembic ; cinq services recréés |
| `build-info` | backend et frontend `revision: 1134a61d8613…`, `revision_verified: true` |
| Flow live | v3 `5250e776`, sha `3b262625…`, publiée par l'opérateur via `PUT /systems/{id}/flow-draft` (rev 9) puis `POST /systems/{id}/flow/publish` ; positions du canvas conservées ; seed relancé → `flow reconciliation: published_no_op` |
| Portes de sonde | `782e6032` (garde-fou on) et `f3dff90e` (snapshot v2 sans `decided_by`) réglées par l'API HITL : `create_po` et `handle_rejection` sortis `sealed: true, called: false, reason: unattended` — preuve live de la règle avant même la v3 |
| Contrat e2e, mode par défaut | `18-nawa-agent-studio-canary.spec.ts` vert en 48 s : redirect `/desk`, run par binding, porte avec proposition, appels de lecture verbatim, décision HITL canonique, verdict `blocked`, audit `done`, chat annulé puis confirmé → refus garde-fou, **0 `invoke` MCP navigateur**, 0 porte laissée ouverte |
| Contrat e2e, `E2E_NAWA_STUDIO_WRITE=1` | vert en 58 s : verdict `posted`, **PO 4500382548** créée et validée (run `70bacd67`), chat toujours refusé garde-fou off, 0 `invoke` navigateur |
| Ledger | 4 lignes `procurement.pr_to_po` (une par run, nœud audit réparé) ; 2 lignes `mcp.write.invoked` (`BAPI_PO_CREATE1` « Local PO created under the number 4500382548 », `BAPI_TRANSACTION_COMMIT` ok, 933 ms) ; aucun `mcp.write.invoked` pour les écritures refusées — elles ne sont jamais parties |
| Runs planifiés | cinq portes `hitl_pending` du 02/09 (04:00→20:00, snapshot v2) restent ouvertes jusqu'à leur TTL d'un jour. Celle de 00:00 (`dc4ffbed`) a expiré à 00:01:50 sous le nouveau backend : `handle_rejection` sorti `sealed: true, called: false, reason: unattended` — la règle tient sur le chemin `system:gate_ttl` en conditions réelles (son nœud audit, snapshot v2, a échoué comme attendu). Le prochain tick (04:00) marche la v3 |
| Cosmétique noté | le walker émet `node_start` sur le nœud de la branche non prise avant son `node_end skipped` : le Studio affiche `Running` un cycle de polling sur « Discard on human rejection » après une approbation. Fidèle au serveur, hors périmètre H1 |
| Rollback | `AGENTIUM_IMAGE_TAG=988ee5c7ec2c` puis `up` ; flow : `POST /systems/{id}/flow-draft/restore/b9217063-…` puis publish |

