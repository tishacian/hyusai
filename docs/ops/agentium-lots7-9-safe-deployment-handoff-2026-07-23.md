# Handoff — déploiement sûr Agentium Lots 7–9

Date de référence : 23 juillet 2026.

## Objectif final

Obtenir un unique état aligné :

- dépôt local propre ;
- `origin/demo/agentic` sur le SHA candidat validé ;
- checkout VM sur `demo/agentic` au même SHA ;
- backend, frontend, worker CPU et maintenance construits depuis ce SHA ;
- services sains ;
- migrations et backfills terminés ;
- données PostgreSQL, Qdrant, MinIO/ObjectStore, FAISS et Secure Deposit SFTP
  préservées ;
- Andritz, Showcase, Sentinel et Octocity validés séparément ;
- sept preuves Carakai liées au SHA réellement déployé.

Ce document n’autorise ni push, ni correction de donnée, ni déploiement.

## État Git figé

### Production observée

- branche VM : `hotfix/andritz-export` ;
- SHA live : `154fd98822439747846cd941dce1bf8191f379b2` ;
- `origin/hotfix/andritz-export` : même SHA ;
- backend et frontend `build-info` : même SHA, `revision_verified=true` ;
- Alembic : `064_run_dispatch_outbox`.

### Release A — adoption de sûreté

- worktree :
  `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag-release-a-from-hotfix`
- branche : `codex/release-a-from-hotfix`
- HEAD propre : `4d3fc58d`
- ascendance :
  - `154fd988` — baseline production et patchs Client360/FSE ;
  - `ecbe72cb` — A1, startup non mutatif et fermeture des ingress ;
  - `8a6224e6` — orchestrateur Carakai et producteurs signés ;
  - `4d3fc58d` — A2, transaction data-safe et attestations.

Release A ne contient aucune migration Alembic Lots 7–9.

Validation locale sur cette reconstruction :

- 638 tests Release A passés ;
- 1 test sauté ;
- `git diff --check` propre.

### Release B — Lots 7–9 et hotfix réconciliés

- worktree :
  `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag-demo-agentic-release-a`
- branche : `codex/demo-agentic-release-a-integration`
- checkpoint fonctionnel : `38c3fd81b621f4e911feb2503eec9894ca786d8a`
- base : `origin/demo/agentic=955daada` ;
- sept commits hotfix Client360 portés avec `-x` ;
- `09c7488c` non rejoué car l’export FSE est déjà dans `955daada` ;
- `70035e94` non rejoué car il supprimerait la frontière IAM Lots 7–9 ;
- correctif d’intégration `38c3fd81` :
  - lecture fiche : `system:read` ;
  - enrichissement IA : `system:engine.run` ;
  - purge et annulation par epoch workspace ;
  - contrat `next_due` aligné.

Validations :

- 127 tests backend Client360/FSE/IAM passés ;
- 398 tests frontend passés avec Node 22 ;
- aucune collection, seed, promotion ou donnée externe modifiée.

Important : `38c3fd81` ne descend pas encore de Release A. Il s’agit d’un
candidat fonctionnel, pas du SHA Release B final.

### Runner Carakai

- checkout source figé : `72b8ed50c2db08a74b920a6ad67c43177f5eceea` ;
- Node 22.23.1, Playwright 1.59.1, AsyncSSH 2.23.0 ;
- utilisateur sans sudo ni Docker ;
- sandbox systemd : 2 CPU, 6 Gio, réseau limité à l’IP production ;
- clé publique `protected_runner` vérifiée ;
- aucun credential, job ou canari actif.

Carakai est prêt pour une acceptance. Il n’est pas encore éligible à une
preuve formelle Release A.

## Baseline data à ne pas altérer

| Surface | Baseline |
|---|---|
| PostgreSQL, RabbitMQ, Keycloak, FAISS | `/dev/sda1` |
| Qdrant, MinIO, ObjectStore, snapshots | `/dev/sdb`, monté sur `/srv/agentium-data` |
| Secure Deposit SFTP | `/dev/sdc`, monté sous `backend/data/secure_deposit` |
| `/dev/sdb` | environ 279 Gio libres |
| `/dev/sdc` | environ 382 Gio libres |
| Secure Deposit | 45 424 fichiers logiques PostgreSQL |
| SFTP | image `sha256:22cd79c…`, conteneur `18f52288…`, host key ED25519 `SHA256:zm4vcBu3WcD6WFDLHBN1+dhEK/t0412S2FC2N59cr54` |

Ne jamais exécuter `docker volume prune`. Deux volumes non attachés peuvent
contenir des historiques :

- `qdrant_data`, environ 43 Gio ;
- `agentium_minio`, environ 158 Gio.

Baseline métier :

- Andritz : 6 Systems actifs, 5 membres et 4 entitlements par membre
  (`chat`, `client360-pdr`, `knowledge-capture`, `fse-reports`) ;
- 30 collections Andritz ;
- SPL : 109 798 documents / 1 570 607 chunks ;
- Client360 : 8 documents / 6 233 chunks ;
- Sentinel : 20 Systems et 10 collections prêtes ;
- Octocity : 7 Systems et 7 collections prêtes.

Une collection metadata Octocity vide porte encore le nom
`sentinel-ci-visual-intelligence`. C’est une dérive préexistante à attester,
jamais à supprimer implicitement.

## NO-GO actuels

1. `/` possède environ 16 Gio libres ; le gate en exige 40. Le cache builder
   annonce environ 38,83 Gio récupérables. Un nettoyage exige un GO séparé et
   ne doit viser ni volume, ni image active.
2. Registre d’autorités : `1/3`.
   - présent : `protected_runner` ;
   - manquants : `backup_provider`, `release_a_host_collector`.
   Ne jamais générer de fausses autorités de convenance.
3. Les preuves de sauvegarde et de restauration distinctes pour `/dev/sda1`,
   `/dev/sdb` et `/dev/sdc` ne sont pas encore réunies.
4. Une `ExpertCaptureSession` du workspace `test` référence un System Andritz.
   Le gate tenant échouera. La correction doit être un plan/apply auditée,
   bornée à ces bindings, sans supprimer la session, son Run, son Context ou
   ses événements.
5. Release A n’est pas poussée, installée ni attestée.
6. Le producteur SFTP strict et le principal navigateur non personnel ne sont
   pas encore disponibles ; les preuves Carakai actuelles seraient seulement
   `acceptance`, `formal_release_eligible=false`.

## Séquence de reprise obligatoire

### 1. Revalider les références

Exiger :

- `origin/hotfix/andritz-export=154fd988...` ;
- `origin/demo/agentic=955daada...` ;
- les deux worktrees ci-dessus propres aux SHAs documentés.

Tout changement impose de refaire merge-tree et les tests affectés.

### 2. Fermer les gates externes

- attester trois sauvegardes restaurables distinctes ;
- ajouter dans Git les deux vraies clés publiques manquantes ;
- préparer le bundle runtime privé hors dépôt ;
- libérer l’espace racine uniquement par le cache builder, après GO ;
- corriger la dérive tenant via une opération auditée indépendante ;
- capturer la collection metadata Octocity vide comme baseline acceptée.

### 3. Pousser et exécuter Release A

Pousser `codex/release-a-from-hotfix` sans déplacer `demo/agentic`.

Le manifeste Release A est lié à la baseline fixe `154fd988`. La branche
dédiée doit rester exactement sur son SHA pendant :

`preflight → prepare → apply → resume → arm-sftp-canary → record-sftp-active
→ record-sftp-final → finalize → completed`.

Release A ne lance aucune migration 065–076.

### 4. Construire le SHA Release B final

Depuis le candidat `38c3fd81`, merger Release A avec `--no-ff`. Le résultat
doit descendre de :

- `origin/demo/agentic` ;
- `154fd988` ;
- `4d3fc58d`.

Résolutions à auditer :

- `client360.py` : conserver endpoints hotfix et IAM/action plane Lots 7–9 ;
- `knowledge_capture.py` : conserver IAM et export FSE ;
- `config.py` : conserver `AUTHORIZATION_V2_*`, startup non mutatif et dotenv
  figé ;
- `product-compliance.v1.json` : conserver tous les claims Lots 7–9 et le
  rollback format 3 ;
- `agentium.env.example` : conserver IAM v2 et les identités/chemins Release A ;
- `client360_pdr.py`, `api.service.ts` et tests frontend : revue sémantique.

Ne lancer aucun seed, backfill, script de promotion ou synchronisation de
collection pendant ce merge.

### 5. Valider Release B hors production

- suites backend Lots 7–9, P4, Client360, FSE, entitlements et blueprints ;
- suite frontend et build production Node 22 ;
- simulation Alembic `064→076` sur restauration PostgreSQL ;
- dry-run des backfills Workspace Apps ;
- gardes Andritz et golden retrieval ;
- Showcase System 360 ;
- Sentinel et Octocity séparés ;
- `git diff --check`, conformité et provenance.

### 6. Promouvoir `demo/agentic`

Seulement après Release A `completed` :

- pousser le SHA B en fast-forward de `origin/demo/agentic` ;
- basculer explicitement la branche VM, car `deploy-vm.sh` ne change pas de
  branche implicitement ;
- exécuter la transaction Release B avec dump quiescé, migration `064→076`,
  backfills dry-run/apply et inventaires avant/après ;
- ne jamais reconstruire ou déplacer le stockage SFTP.

### 7. Attester et conclure

- backend, frontend, worker et maintenance : même SHA et labels OCI ;
- VM HEAD et `origin/demo/agentic` : même SHA ;
- sept preuves Carakai signées et revalidées ;
- PostgreSQL/Qdrant/SFTP/MinIO/FAISS comparés ;
- services sains ;
- rollback v3 complet présent sous `/srv/agentium-data`.

## Rollback

Baseline applicative avant Release A : `154fd988...`.

Les anciens fichiers TSV format 2, notamment `955daada...tsv`, ne constituent
pas le rollback de cette transaction et ne doivent pas être supprimés
aveuglément. Release A puis Release B doivent chacune produire leur journal
canonique et leur reçu terminal.

## Prompt de reprise pour Cursor

> Reprendre le déploiement sûr Agentium Lots 7–9 depuis ce handoff. Ne toucher
> ni au worktree principal sale, ni à la production avant fermeture des NO-GO.
> Vérifier d’abord les SHAs et la propreté des deux worktrees. Release A
> `4d3fc58d` descend du live `154fd988`; candidat fonctionnel B `38c3fd81`
> descend de `origin/demo/agentic` et contient les patchs hotfix, mais doit
> encore merger Release A. Ne jamais lancer seed, promote, sync de collection,
> `docker volume prune`, migration ou restart sans gate et autorisation
> explicite. L’objectif final est local + `origin/demo/agentic` + VM sur un
> unique SHA B, services sains, migrations/backfills validés et données
> PostgreSQL/Qdrant/SFTP/MinIO/FAISS inchangées hors deltas autorisés.
