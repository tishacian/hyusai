# Flow Builder P0 — handoff commit et livraison `demo/agentic`

Date : 2026-08-07

Cette note fige l'état de reprise. Elle n'autorise pas, à elle seule, l'avancement de
`demo/agentic`, une migration de base ou une mutation de la VM de production.

## État Git sécurisé

- Branche source : `codex/flow-builder-p0-safety`.
- Baseline distante vérifiée : `origin/demo/agentic` à
  `b0b8f45209c0bb895764653b4ecf78b3d7cc10b3`.
- Fondations Flow à intégrer :
  - `282bc686` — garde des écritures destructives ;
  - `df8fd31d` — runtime/publication et migrations 077–080 ;
  - `875bfa36` — workflow Draft/Publish du Builder.
- Commit backend de cette tranche :
  `39843407` (`feat(flow): govern local workbench preview execution`).
- Commit frontend de cette tranche : le commit contenant cette note, résolvable avec
  `git log -1 --format=%H -- docs/ops/flow-builder-p0-delivery-handoff-2026-08-07.md`.
- `99750826` est patch-équivalent à `b0b8f452` et ne doit jamais être rejoué.

## Barrières P0 livrées

### Exécution Workbench

- feature flag `flow_workbench_v1` strictement égal à `true`, absent/faux donc fermé ;
- contrôle doublé à l'API et dans le service transactionnel ;
- plancher global admin ou workspace admin/owner avant la décision IAM existante ;
- viewer refusé en compat, shadow et enforce ;
- refus prouvé sans création de Run ni dispatch sur preview, node et golden set.

Le flag doit rester désactivé par défaut en production. Son premier canari doit utiliser
un Skill sans effet externe. Avant une ouverture aux Skills à effets réels, traiter
l'idempotence des requêtes et la reprise du dispatch actuellement basé sur
`BackgroundTasks`.

### Suppression de nœud

- supprimer un nœud retire uniquement ce nœud et ses edges incidents ;
- aucune route n'est synthétisée pour un Skill, un contrôle Governance ou une task ;
- undo restaure exactement le nœud, ses edges et la sélection ;
- redo réapplique la même suppression fail-closed ;
- les edges directs préexistants et non incidents restent inchangés.

## Validations exécutées

- Backend post-correctif : 68 tests Workbench/Retrieval/DAG passants.
- Backend avant correction : 325 tests ciblés publication/runtime/RAG/migrations passants.
- Ruff : nouveaux fichiers backend et tests propres.
- Frontend post-correctif : 178 tests Flow ciblés passants, dont les 18 tests
  FlowStore.
- TypeScript `--noEmit` : passant.
- Build Angular production post-correctif : passant ; avertissements de budgets existants,
  Flow Builder chargé en lazy chunk d'environ 771 Ko.
- Contrat Playwright local exécuté avant le correctif : passant.
- `git diff --check` : passant.
- `python3 scripts/agentium_compliance.py --check` : passant.

La suite frontend complète reste à rejouer après récupération d'espace local ou dans un
environnement jetable. Le contrôle Ruff global remonte de la dette historique dans les
grands fichiers préexistants ; aucune réécriture mécanique globale ne doit être mêlée à
ce patch.

## Fichiers explicitement exclus

Ne pas inclure dans les commits ou l'intégration Flow :

- `docs/demo-runs/2026-07-29-nawa-itsd/COMPILATION-NAWA-WE.md` ;
- les fichiers non suivis sous `docs/pih/` ;
- les scripts et previews non suivis sous `docs/render/`.

Cette note est le seul nouveau fichier `docs/**` intentionnel de la tranche.

## Intégration ultérieure dans `demo/agentic`

Créer un worktree propre depuis le SHA distant encore vérifié, puis cherry-pick dans cet
ordre :

1. `282bc686`
2. `df8fd31d`
3. `875bfa36`
4. `39843407`
5. le commit contenant cette note

Ne pas cherry-pick `99750826`. Rejouer tous les gates sur l'arbre intégré. Avancer
`demo/agentic` uniquement en fast-forward si sa tête distante n'a pas changé.

## Déploiement différé

La production est encore à Alembic 076 ; le candidat introduit 077–080, dont la mutation
du graphe Andritz par 078. Ce premier rollout doit utiliser la voie orchestrée sûre :

1. construire uniquement backend, worker et frontend, liés au même SHA complet ;
2. créer un dump PostgreSQL frais et réussir sa restauration isolée ;
3. fermer l'ingress et drainer les writers avant migration ;
4. conserver le gate fermé entre migration, activation et canaris ;
5. vérifier `storage-check`, build-info, refus non-admin, absence de mutation
   Draft/Published, scope Retrieval exact et canaris métier ;
6. rouvrir uniquement après attestation liée au déploiement.

Ne reconstruire ni recréer PostgreSQL, RabbitMQ, Qdrant, MinIO, SFTP, P4 ou LiveKit.
Après migration, un simple retour d'image ou un downgrade Alembic aveugle n'est pas un
rollback : restaurer le dump frais sous writers fermés ou appliquer un roll-forward.

## Reçu à compléter à la reprise

Complété le 07/08/2026 après déploiement. Détail complet dans
`docs/ops/agentium-safe-vm-deployment.md`, section « Flow Builder P0 (07/08) ».

- commit frontend : `9b0a116a25e46b9303d850a518cc992ab78359e4`
  (`feat(flow): complete operator workbench authoring UX`), qui porte cette note ;
- SHA intégré candidat : `9b0a116a25e46b9303d850a518cc992ab78359e4`, cinq commits
  au-dessus de `b0b8f452` (`73f94877`, `aab6b5a6`, `c09c49e9`, `c055493c`,
  `9b0a116a`) ;
- SHA final `demo/agentic` : `9b0a116a25e46b9303d850a518cc992ab78359e4`, avancé en
  fast-forward depuis `b0b8f452` par bundle Git poussé depuis la VM ;
- reçu dump/restauration :
  `/srv/agentium-data/flow-p0-deployments/2026-08-07-9b0a116a25e4/postgres-pre-migration.dump`,
  `sha256` `1c63327751f3ea2f5d7920600044edb3d056406a3d53180e5f79a9b9dc05269f`,
  448 212 403 octets, triplet `.sha256`/`.ready` publié ; restauration rejouée sur
  base jetable et migrations 077–080 menées jusqu'à `080_trigger_event_claims`
  avant toute mutation de production ;
- digests OCI candidat : backend
  `sha256:cbd828d527b0a7cfd2369397d21e669738907a67bdbaaafe038c661c33427fe6`,
  worker `sha256:48a441d24cbbc1bb78172704b204ece908bbbc96e41c3f33bf562659b3f41a14`,
  frontend `sha256:bf4fe6e76661aeb999bb27a599960c5da4491f1ad3024e8d47d09104237d0414`,
  double tag `9b0a116a25e4` + `demo-agentic` ;
- canaris et attestation : `run-iteration-canaries.sh` 6/6 vertes sur le SHA
  déployé (gate léger, non signé). L'attestation signée 7 tokens reste à produire
  au prochain jalon.

Le drapeau `flow_workbench_v1` est resté absent de tous les workspaces : la
tranche est déployée mais fermée.

La migration 078 a effectivement muté le graphe Andritz — elle ne s'est pas
abstenue. Une seule arête ajoutée (`decision.verdict --[strong]--> join.answer`),
23 nœuds inchangés, 30 → 31 arêtes, nouvelle version immuable #20 et pointeur
publié réémis, l'ancienne version restant intacte.
