# Plan Git de transition Agentium A/B — 22 juillet 2026

Ce document décrit la transition révisée depuis le runtime réellement actif
`154fd98822439747846cd941dce1bf8191f379b2`. Il complète le
[runbook de déploiement sûr](./agentium-safe-vm-deployment.md) ; il ne donne
aucune autorisation de commit, push ou déploiement.

Il s'agit d'un plan de construction, pas de l'état d'une release publiée. La
présence locale du hardening et de ses tests ne signifie pas qu'une branche A a
été créée, commitée, poussée, déployée ou attestée. Chacune de ces opérations
requiert un GO distinct. Tant que les gates externes listés plus bas ne sont pas
levés, le statut de promotion est `NO-GO`.

Le registre d'autorités de preuve versionné contient actuellement uniquement
le producteur `protected_runner`. Le preflight transactionnel A exige les trois
producteurs réels et
s'arrête donc avant toute mutation. Il est interdit de générer des clés de
convenance ou de les injecter par option opérateur : leurs clés publiques
doivent être ajoutées par un changement Git revu avant de construire le SHA A.

## Pourquoi deux branches réelles

`origin/demo/agentic` contient déjà les commits Lots 7–9 à `955daada`, tandis
que la production a reçu les patchs sans migration sur
`hotfix/andritz-export` à `154fd988`. Une Release A créée depuis
`demo/agentic` embarquerait donc implicitement les migrations et le code métier
que la phase d'adoption de sûreté doit justement exclure.

La séparation A/B doit exister dans l'historique Git, pas seulement dans le
runbook :

```text
a8c790ad
  ├─ 955daada  Lots 7–9 + export FSE               <- origin/demo/agentic
  └─ 154fd988  hotfix Client360/FSE, runtime live
       └─ A1 startup non mutatif et gates
            └─ A2 attestations et transaction      <- Release A dédiée

Release B = merge contrôlé de Release A dans demo/agentic réconciliée avec
le hotfix, puis migrations 065–076 et backfills explicitement validés.
```

## Worktrees persistants

Ne pas utiliser `/tmp`. Conserver le checkout utilisateur actuel intact et
créer, seulement après autorisation, deux worktrees frères persistants :

- `.../papAI/omnirag-release-a-from-hotfix` pour la Release A ;
- `.../papAI/omnirag-demo-agentic-release-a` pour la Release B.

Avant toute promotion, `git fetch origin` doit confirmer simultanément
`origin/hotfix/andritz-export=154fd988...` et
`origin/demo/agentic=955daada...`. Toute autre valeur impose de refaire
l'audit de base et la réconciliation.

Les worktrees sont persistants et séparés du checkout utilisateur chargé.
Les anciennes inscriptions sous `/private/tmp` restent hors de la transaction
de release.

Le fallback direct retenu impose ensuite une séquence stricte, sans miroir
GitLab et sans PR comme source d'autorité :

1. construire, revoir et pousser **A seulement** sur la branche dédiée
   `codex/release-a-from-hotfix`, descendante exacte de `154fd988` ;
2. laisser cette branche exactement sur le SHA A pendant tout
   `preflight -> prepare -> apply -> reboot -> resume -> arm-sftp-canary ->
   record-sftp-active -> record-sftp-final -> finalize -> completed` ;
3. construire B comme descendant de A, de `origin/demo/agentic` et du hotfix ;
4. pousser B en fast-forward de `origin/demo/agentic`, puis déployer son SHA
   exact avec la transaction Release B.

Pousser ou déplacer la branche A pendant une reprise A est interdit.
`origin/demo/agentic` n'est jamais réécrit ni forcé.

La branche A est créée directement depuis `154fd988`. Il est interdit de
cherry-pick aveuglément un commit de hardening fabriqué sur `570b7239`.
L'audit trouve deux chevauchements d'ascendance et un troisième chevauchement
sémantique dans le canari live. Ils sont donc portés manuellement :

- `config.py` reçoit `import os`, `Literal`, `startup_reconciliation`,
  `_settings_env_file()` et l'instanciation `Settings(_env_file=...)`, qui
  forment ensemble le contrat d'environnement runtime immuable ; les champs
  `authorization_v2_*` restent exclusivement en B ;
- `agentium.env.example` reçoit uniquement le delta de sécurité non commité
  (identités de services, clés séparées et chemins `/dev/sdb`/`/dev/sdc`) ; les
  trois variables `AUTHORIZATION_V2_*` du HEAD Lots 7–9 restent en B ;
- `09-live-workspace-contract.spec.ts` repart du blob `154fd988` et reçoit les
  preuves A liées au SHA, aux UUID/slugs exacts, au mode content-free, au dry-run
  Client360 et à l'isolation inter-tenant. Il conserve strictement trois liens,
  trois surfaces et cinq Systems Andritz. La quatrième surface FSE, les six
  Systems, l'API Workspace Apps et les identifiants d'app restent en B.

Le profil de manifeste v6 contrôle ces frontières en plus de la revue du patch
exact. Il refuse les variables `AUTHORIZATION_V2_*` dans l'exemple d'environnement,
les structures FSE/Workspace Apps dans le canari 09, les nouvelles routes Python
quel que soit le nom du router et toute revue applicative qui omet un contrôle
obligatoire. Les deux tests de conformité/provenance nécessaires au nouveau
rollback sont admis comme preuves A. `config/agentium/product-compliance.v1.json`
doit aussi entrer dans A parce que `deploy-vm.sh` exécute le checker, mais
uniquement par remplacement structurel de l'unique claim rollback format 2 par
son équivalent format 3. Le manifeste compare l'arbre JSON complet au live et
refuse tout autre écart ; les quelque 1 500 lignes de claims Lots 7–9 restent
donc en B.

Tous les autres chemins A proviennent du hardening revu et sont appliqués au
SHA live `154fd988`. Ils peuvent être portés depuis
leurs octets courants après contrôle de l'inventaire exact, jamais par copie
globale du checkout.

## Commits de la Release A

Les commits utilisent exclusivement `git add -- <liste explicite>`. `git add
.`, `git add -A` et `git add -u` sont interdits dans les deux worktrees de
release.

### A1 — startup non mutatif et fermeture des ingress

Périmètre attendu :

- garde `STARTUP_RECONCILIATION=disabled`, settings en lecture sans création ;
- unité systemd backend sur `127.0.0.1`, adoption réversible sous gate fermé ;
- gate Nginx persistant, barrières SFTP/LiveKit/backend systemd et restart
  policies fail-closed ;
- tests strictement liés à ces mécaniques.

### A2 — stockage, environnement figé et transaction

Périmètre attendu :

- orchestrateur SHA-bound et primitive interne `deploy-vm.sh` ;
- générateur/vérificateur du manifeste privé Release A ; `create` puis
  `verify` sont obligatoires et lient le diff exact depuis le SHA live fixe à
  une policy fail-closed ; un reçu de vérification déjà présent est toujours
  confronté à une nouvelle vérification sémantique du Git, du manifeste et de
  la review, et n'est jamais accepté sur son seul mode ou son propre contenu ;
- vérificateur d'attestation Release A figé comme trust root ; son blob doit
  rester identique dans B, qui ne peut pas modifier son propre gate ;
- bundle d'environnement privé, atomique et réutilisé sur
  `prepare/apply/resume/arm-sftp-canary/record-sftp-active/
  record-sftp-final/finalize/rollback` ;
- liaison byte-for-byte des six preuves de préconditions avant toute mutation,
  puis manifeste fermé des 37 références finales avant ouverture : 23
  artefacts canoniques du journal et 14 triplets externes
  `artefact + provenance + signature` ; les reçus seuls ne remplacent jamais
  les artefacts qu'ils référencent ;
- registre d'autorités chargé exclusivement depuis le SHA Git revu, figé et
  rehashé par la transaction ; le preflight refuse tout registre incomplet,
  toute réutilisation de clé entre classes de producteurs et toute clé ou
  signature hors du profil RSA approuvé ; aucune substitution opérateur ;
- daemon Docker forcé sur le socket local et Engine ID figé dans le journal ;
- reçu OCI candidat après build, puis reçu OCI runtime lié aux IDs exacts des
  images/conteneurs, à leur santé et au `build-info` réellement servi avant
  toute ouverture ; le reçu de transaction A v3 rehash les huit reçus liés,
  dont le runtime OCI, le runtime SFTP prêt et le ledger PostgreSQL SFTP ;
- au preflight B, rehash du reçu OCI candidat référencé par le reçu runtime A,
  validation de sa chronologie et confrontation des IDs d'images attestés aux
  conteneurs A réellement actifs et à leurs `build-info` ;
- identité du backend systemd liée au SHA dans le bundle v3 et vérifiée par le
  `build-info` réellement servi, y compris après reprise et rollback ;
- journal transactionnel à schéma fermé, transitions monotones, récupération
  `recovering_pre_migration` et intention `rollback_closing` persistée avant
  mutation ;
- journal porté exclusivement par `/dev/sdb`, répertoires privés ouverts sans
  suivre de lien, verrou principal sur le FD du répertoire vérifié et verrou
  secondaire B compatible runner ; les FDs restent hérités pendant le re-exec
  de l'orchestrateur figé ;
- fermeture crash-safe dans cet ordre : restart policies durables `no` et
  unités writers désactivées, gate HTTP persistant, barrières ingress,
  drainage et arrêt, puis `closing_intent` fsyncé ;
- ouverture crash-safe : reçu et phase terminale fsyncés sous guards, puis
  ouverture physique ; les restart policies et guards ne sont restaurés/retirés
  qu'après cette phase, et un marqueur final rend la reprise après reboot ou
  SIGKILL idempotente ;
- dumps PostgreSQL publiés uniquement avec checksum et marqueur `.ready`, puis
  revalidés avant migration, reprise ou restauration ;
- inventaire PostgreSQL v2 constant-space, à deux accumulateurs SHA-256 par
  table, détails bornés au Run/SkillInvocations du ledger et agrégats de
  navigation par workspace ;
- preuve Qdrant exhaustive et content-free de tous les IDs, payloads et
  vecteurs, ainsi que preuves MinIO/ObjectStore, FAISS et Secure Deposit ;
- preuve SFTP positive et jetable sous gate externe : identité exacte du
  processus, de l'image et de `StartedAt`, authentification password-only avec
  host key Ed25519 épinglée, `getcwd()` et `stat('.')` seulement, révocation,
  refus de la même credential après révocation, ledger PostgreSQL exact et zéro
  `DepositFile` ;
- audit global des bindings qui bloque tout lien
  `ExpertCaptureSession -> System` entre workspaces ;
- canaris Showcase, Andritz, Sentinel et Octocity ;
- overlays Compose fermé/ouvert et exemples de configuration sans secret ;
- tests de contrat et runbooks associés.

Le diff `154fd988..A_SHA` doit rester limité aux familles suivantes :

- `scripts/agentium_*`, `scripts/audit_*`, `scripts/deploy-agentium-safe.sh`,
  `scripts/deploy-vm.sh`, `scripts/run-agentium-safe-canaries.sh` ;
- `backend/scripts/audit_*` et leurs tests ;
- les seuls fichiers backend de startup/settings/LiveKit nécessaires au mode
  non mutatif ;
- `deploy/agentium-backend.service`, son installateur et les configs Nginx ;
- `docker/compose.agentium*.yml` et les fichiers `*.env.example` ;
- les tests Playwright de non-régression, les documents `docs/ops` et
  `docs/dev-deploy-policy.md`.

Les familles suivantes sont interdites dans A :

- `backend/alembic/versions/**` ;
- seeds, backfills et bootstrap métier ;
- `backend/app/services/system_catalog_bindings.py` et
  `backend/app/services/workspace_blueprints.py` ;
- composants produit sous `frontend-ng/src/app/**` ;
- assets, captures, rendus et supports de démo ;
- tout `.env`, secret, clé privée, dump ou attestation produite sur la VM.

Le gate de diff est exécutable et obligatoire. Après création du commit A, dans
le worktree A propre, créer puis vérifier son manifeste dans un répertoire privé
hors dépôt :

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
# Après revue des patches exacts, renseigner approval, reviewer, review_ticket,
# classification et hardening_controls dans le draft privé.
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

Le manifeste v2 refuse toute ascendance différente, tout rename/delete, lien
symbolique, mode ou path non autorisé, ainsi que les migrations, seeds,
backfills, composants produit et artefacts privés. Il publie un inventaire
content-free exact des blobs et digests de patches. Les fichiers applicatifs
autorisés restent soumis à un contrôle sémantique fail-closed et à des controls
de hardening bornés par path dans la policy de revue. Sa sortie `passed` ne
dispense pas d'exécuter les tests de sûreté depuis le worktree A. A n'est
poussée vers une branche de revue qu'après ces contrôles ; elle n'est jamais
poussée de force sur `demo/agentic`.

Au premier preflight de B, le manifeste et sa revue privés sont fournis avec
leurs SHA-256 de fichiers explicites, avant l'attestation opérationnelle A. Le
safe deploy les copie atomiquement hors dépôt, exige que le helper manifeste ait
le même blob dans A active et B candidate, inscrit leurs digests et celui du
reçu dans les métadonnées v5, puis rejoue ce gate avant chaque transition de
phase. L'attestation opérationnelle ne remplace jamais ce contrôle de code.

## Construction de la Release B

Après push fast-forward, déploiement et attestation `completed` de A, créer B
depuis le SHA A et rejouer exactement, dans l'ordre :

1. `e4436102` — checkpoint Lots 7–9 ;
2. `cf750a01` — tenant lineage et seed reconciliation ;
3. `b937bfb3` — graphe audité et boucle de valeur ;
4. `eab2f234` — lifecycle Workspace Apps ;
5. `570b7239` — preuves de conformité ;
6. un commit B6 atomique pour les corrections post-audit restantes.

Les conflits sont résolus en conservant à la fois le contrat A (startup non
mutatif, bundle d'environnement, gates et attestations) et les ajouts métier B.
Le résultat peut être préparé sur une branche de revue locale, mais sa livraison
sur `demo/agentic` reste un fast-forward depuis A ; aucun rebase du distant ni
push forcé n'est autorisé.

Sur le chemin aller, Release B ne construit, ne remplace et ne recrée jamais
`agentium-sftp`. Elle épingle l'ID d'image SFTP validé et attesté en Release A,
arrête ce conteneur sous gate puis le redémarre sur le même ID. Lors d'un
rollback explicite, le conteneur peut être recréé, mais seulement depuis cet ID
exact via l'override rollback v3 ; le bind `/dev/sdc` ne change pas. Avant sa
réouverture, une preuve fraîche relie la frontière fermée, le runtime A, le
même serveur/host key, le port publié loopback, l'inventaire auth inchangé et
le montage encore read-only. Toute évolution SFTP reste un lot séparé, avec
rollback dédié et canari positif d'authentification et d'ouverture du
subsystem ; un banner ou un échange `none` ne suffit pas.

Le preflight B exige en outre exactement un journal A canonique en phase
`completed`, correspondant au SHA A actif et au même Engine ID Docker. Il
rehash les huit reçus liés par le reçu de transaction A v3 : vérification de
l'attestation, preuves finales, vérification du manifeste, préconditions,
preuves de préconditions, runtime OCI, runtime SFTP prêt et ledger PostgreSQL
SFTP. Il rehash aussi le registre d'autorités A, le manifeste de liaison et
chaque triplet externe gelé, puis rejoue le vérificateur A figé. Enfin, il
rehash le reçu OCI candidat transitivement lié et confronte ses IDs aux images
des conteneurs A actifs. La seule possession du JSON d'attestation A ne permet
pas de sauter le déploiement A.

## Topologie de données figée pendant A/B

- `/dev/sda1` reste le filesystem de PostgreSQL, de l'état Keycloak stocké
  dans PostgreSQL, de RabbitMQ et du bind FAISS historique ;
- `/dev/sdb`, monté sur `/srv/agentium-data`, reste le filesystem de Qdrant,
  MinIO et de l'ObjectStore ;
- `/dev/sdc`, monté sur
  `/home/ubuntu/omnirag/backend/data/secure_deposit`, reste le filesystem du
  Secure Deposit servi par SFTP.

Aucune Release A ou B ne migre ces données. Le gate exige exactement trois
sauvegardes fournisseur ou hors VM distinctes et restaurées : une pour
`/dev/sda1`, une pour `/dev/sdb` et une pour `/dev/sdc`.

## Gates de promotion

Release A n'est acquise qu'après :

- exactement trois sauvegardes fournisseur/hors VM restaurées, pour
  `/dev/sda1`, `/dev/sdb` et `/dev/sdc` ;
- marge d'au moins 40 Gio sur `/` sans suppression de volume/image active ;
- versioning du bucket MinIO effectif ;
- clés Qdrant admin et lecture seule distinctes ;
- backend systemd loopback et gate persistant après reboot ;
- preuve positive SFTP avec un principal canari jetable et borné ; aucune
  exception n'est acceptée et la preuve banner/transport sans
  credential ne dépasse jamais `runner_verified` ;
- audit tenant sans dérive ; la référence actuellement observée d'une session
  du workspace `test` vers un System Andritz doit être qualifiée et corrigée
  par décision opérateur auditée, jamais par seed/reconcile automatique ;
- dump/checksum/`.ready` revalidés, inventaires inchangés et smoke des quatre
  workspaces ;
- manifeste Release A créé puis vérifié sur le SHA exact avec la policy
  fail-closed embarquée.

Release B reste `NO-GO` tant qu'un seul de ces points manque. Une fois A
attestée, B suit la transaction fermée du runbook ; elle ne réutilise jamais le
chemin quotidien `git pull && docker compose up`.

## Blockers externes au code

Les éléments suivants ne peuvent pas être promus par un test local et restent
cumulativement bloquants :

- obtenir et tester exactement trois sauvegardes fournisseur ou hors VM, une
  pour `/dev/sda1`, une pour `/dev/sdb` et une pour `/dev/sdc` ;
- libérer la racine jusqu'au seuil de 40 Gio sans toucher aux volumes, images
  actives ni tags de rollback ;
- activer et attester le versioning du bucket MinIO existant ;
- provisionner les clés Qdrant admin/lecture seule et les identités S3 à moindre
  privilège ;
- adopter Nginx/systemd/gates, puis prouver leur comportement après reboot ;
- qualifier la dérive tenant `test -> Andritz` sans mutation implicite ;
- fournir un canari SFTP positif jetable ;
- créer et vérifier le manifeste de diff Release A sur le SHA exact ;
- exécuter et conserver l'attestation Release A sur le SHA exact.

Aucun contournement d'un de ces points, abaissement de seuil ou validation
manuelle d'un JSON isolé ne transforme la Release A ou B en GO.
