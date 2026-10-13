# Politique de développement & déploiement — Agentium / OmniRAG

> But : un **chemin unique et reproductible** pour développer en local, livrer via
> git, et déployer sur la VM `omnirag-demo` via Docker. Cette note existe pour
> éviter le workflow accidenté qu'on a subi (rsync de fichiers non commités,
> arbre git sale, rebuild à partir d'une copie périmée, VM désynchronisée de
> `origin`).
>
> Pour toute opération de production, la référence exécutable unique est
> `scripts/agentium-vm-deploy.sh` (§6). La chaîne safe de la Release A
> (`deploy-agentium-safe.sh`, `deploy-vm.sh`, unité systemd `agentium-backend`)
> est retirée depuis le 12/10/2026 ; son journal est archivé dans
> `docs/archive/2026/ops/agentium-safe-vm-deployment.md`. Le runbook historique
> `docs/agentium-dockerization-runbook.md` reste une source d'architecture, pas
> une procédure opérateur. Cette note couvre le cycle **quotidien** code →
> commit → deploy une fois la Release A attestée.
>
> Cette politique ne constitue pas un GO : elle **n'autorise aucun commit,
> push ou déploiement**. Chacune de ces mutations requiert une demande
> explicite séparée, portant sur le SHA et la release concernés.

---

## 0. Principe directeur

**`origin/demo/agentic` est l'unique source de vérité.** Tout ce qui tourne sur la
VM doit correspondre à un commit poussé. Le code arrive sur la VM **par `git`**,
jamais par `rsync`, `scp`, ou édition directe.

```
local (branche)  ──commit──>  origin/demo/agentic  ──agentium-vm-build.sh──>  images <sha12>  ──agentium-vm-deploy.sh up──>  conteneurs
```

Si tu ne peux pas répondre à « quel commit tourne sur la VM ? » avec un SHA, le
déploiement est cassé.

Le premier passage depuis le runtime historique suit deux releases : une
Release A limitée aux protections d'infrastructure, puis une Release B pour les
migrations et le code métier. La VM contrôlée le 22 juillet 2026 est encore en
**NO-GO** : racine sous le seuil, bucket `agentium-artifacts` non versionné,
Qdrant sans séparation de clés, gate persistant non adopté, sauvegarde hors VM
de `/dev/sda1`, `/dev/sdb` et `/dev/sdc` non attestée, preuve SFTP
non authentifiée et dérive persistée d'une session du workspace `test` vers un
System Andritz. La procédure quotidienne ci-dessous ne devient exécutable
qu'après l'attestation de la Release A décrite dans le
[runbook VM sûr](archive/2026/ops/agentium-safe-vm-deployment.md). La construction des
deux historiques isolés est détaillée dans le
[plan Git A/B](./ops/agentium-release-a-b-git-plan-2026-07-22.md).

Le registre Git des autorités de preuve Release A est en outre volontairement
vide à ce stade. Le preflight exige, avant toute mutation, une vraie clé
publique revue pour chacun de `backup_provider`, `protected_runner` et
`release_a_host_collector`. Aucune clé fournie par l'opérateur ni aucun digest
auto-déclaré ne peut remplacer ce gate ; tant que le registre n'est pas
complété par review Git, Release A reste `NO-GO`.

Les deux exécuteurs forcent Docker sur le socket local
`unix:///var/run/docker.sock`. A fige son Engine ID, et B exige le journal A
canonique en phase `completed` sur ce même Engine avant son premier preflight.

Dans le fallback direct actuel, `demo/agentic` avance uniquement par deux
fast-forwards : d'abord vers A, qui doit rester le HEAD distant jusqu'au reçu
`completed`, puis vers B. Il est interdit de pousser B pendant `apply`, le
reboot, `resume` ou `finalize` de A. Le checkout local utilisateur, actuellement
divergent et sale, n'est utilisé ni comme worktree A/B ni comme source de build.

---

## 1. Travailler en local

### Prérequis
- Docker Desktop lancé.
- Python (backend) et Node (frontend-ng) pour itérer hors conteneur.
- `backend/.env` local (jamais commité — voir `.gitignore`).

### Boucle de dev
1. Pars d'une branche à jour :
   ```bash
   git checkout demo/agentic
   git pull --ff-only origin demo/agentic
   ```
   Pour une feature isolée : `git checkout -b feat/<sujet>` puis PR vers `demo/agentic`.
2. Backend :
   ```bash
   cd backend && uvicorn app.main:app --reload
   pytest app/tests/...        # cible les tests liés à ta zone
   ```
3. Frontend :
   ```bash
   cd frontend-ng && npm run start     # dev server
   npm run build                       # vérifie que le bundle prod compile
   ```
4. Pré-commit : `pre-commit run --all-files` (la config existe à la racine).

### Règles locales
- **Aucun secret dans le repo** : `.env`, `docker/env/*.vm.env`, clés. Ils sont
  gitignorés — garde-les ainsi.
- **Pas d'instrumentation debug commitée** (ex. `fetch('/api/v1/voice/debug-trace'…)`,
  logs `kc.prefetch` verbeux). Si tu en ajoutes pour diagnostiquer, retire-les
  **avant** le commit de livraison.
- Ne laisse pas traîner un arbre sale : `git status` doit être propre avant de
  changer de tâche.

---

## 2. Livrer via Git (commit + push)

Le déploiement **commence** par un commit propre poussé sur `origin`.
Les commandes suivantes sont une checklist à utiliser après un GO explicite ;
leur présence dans ce document n'autorise pas leur exécution.

```bash
# 1. Vérifier l'arbre sans prétendre qu'un contrôle de noms détecte les secrets
git status -sb
git diff --stat

# 2. Stager une liste fermée, revue fichier par fichier
git add -- path/to/first-file path/to/second-file

# 3. Revoir exactement l'index et son contenu
git diff --cached --check
git diff --cached --name-status
git diff --cached --stat
git diff --cached

# 4. Commit conventionnel (feat/fix/chore/docs + scope)
git commit -m "feat(scope): description courte de l'intention"

# 5. Pousser
git push origin demo/agentic
```

Avant le commit de production, exécuter également le scanner de secrets approuvé
par le dépôt sur **l'index**. Un grep sur les noms de fichiers ne constitue
jamais une preuve d'absence de secret. Si le scanner n'est pas disponible, le
commit reste en attente ; il n'est pas contourné par une revue partielle du
working tree.

### Style de commit
Conventional commits, en suivant l'historique du repo :
`fix(rag): …`, `feat(capture): …`, `fix(ui): …`, `docs: …`.
Message qui explique **le pourquoi**, pas seulement le quoi.

### Règles git
- **Ne jamais** `git push --force` sur `demo/agentic` / `main`.
- **Ne jamais** `git commit` sans qu'on te l'ait demandé explicitement.
- `git reset --hard` est réservé aux **cibles de déploiement** (la VM), pas à ton
  poste de dev, et uniquement vers un commit déjà poussé (voir §3).
- Pas de `rsync`/`scp` de code vers la VM. Jamais. C'est la cause racine du bazar.

---

## 3. Déployer sur la VM via Docker

La VM `omnirag-demo` est aussi le **nœud de build** : les images sont construites
sur place et taguées en local (`agentium-backend:local`, `agentium-frontend:local`,
`agentium-worker:local`). Pas de registry externe.

### Coordonnées canoniques
| Élément | Valeur |
|---|---|
| Hôte SSH | `omnirag-demo` |
| Worktree de build | `/srv/agentium-data/worktrees/demo-agentic` (root, fast-forward uniquement) |
| Lanceur | `scripts/agentium-vm-deploy.sh`, exécuté en root |
| Fichiers compose | `docker/compose.agentium.yml`, `$D/compose.agentium.opened.yml`, `docker/compose.agentium.vm-runtime.yml` (+ overlays opt-in) |
| Bundle d'env figé `D` | `AGENTIUM_RUNTIME_ENV_DIR`, par défaut `/srv/agentium-data/runtime-env/2026-10-12` |
| Journal des déploiements | `/srv/agentium-data/deployments/journal.tsv` |

> Les secrets ne vivent que dans `$D/runtime-env/` (root, 0600). Un nouveau
> bundle se dérive d'un ancien (`agentium_runtime_env_bundle.py
> derive-vm-bundle`) ; l'ancien n'est jamais modifié et reste la cible de
> rollback.

### Topologie de stockage à conserver

La transition A/B n'est pas une migration de stockage :

- PostgreSQL, l'état Keycloak persisté dans PostgreSQL et RabbitMQ restent sur
  le filesystem racine `/dev/sda1` ;
- Qdrant, MinIO, l'ObjectStore et, depuis la phase 4b (12/10), l'index FAISS
  (`/srv/agentium-data/faiss_db`) restent sous `/srv/agentium-data`, monté sur
  `/dev/sdb` ;
- le Secure Deposit SFTP est monté depuis la phase 4b sur
  `/srv/agentium-secure-deposit` (`/dev/sdc`, par UUID dans fstab).

Le GO Release A exige exactement trois sauvegardes fournisseur ou hors VM,
distinctes et restaurées : une pour chacun de `/dev/sda1`, `/dev/sdb` et
`/dev/sdc`. Un dump ou inventaire conservé sur l'un de ces mêmes disques ne
remplace pas cette preuve.

### Procédure standard (chemin unique)

1. Pousser le commit sur `origin/demo/agentic`.
2. Sur la VM, en `ubuntu`, `scripts/agentium-vm-build.sh <sha40>` dans sa
   version au `<sha40>` (`docs/agentium-release-process.md` §3) : verrou,
   fetch puis `merge --ff-only` du worktree de build par `sudo -n` (jamais de
   reset), les sept images `agentium-*:<sha12>` sidecar LiveKit compris, le
   label de révision de chacune, puis les budgets de taille
   (`scripts/agentium-image-budget.sh`, sidecar requis). Il remplace
   `/tmp/deploy-reorg.sh`, non versionné, laissé sur la VM et plus utilisé.
3. `AGENTIUM_IMAGE_TAG=<sha12> agentium-vm-deploy.sh storage-check`.
4. Si `backend/alembic` a changé : `migrate`. Le lanceur fait d'abord un
   `pg_dump -Fc` vérifié par `pg_restore --list`, publié avec un marqueur
   `.ready` (digest, taille) sous `/srv/agentium-data/deployments/<run-id>/` ;
   sans dump, pas de migration.
5. Vérifier qu'aucun Run n'est actif, puis `up`. `up` attend que
   `/api/v1/build-info` du backend annonce la révision du tag avec
   `revision_verified=true`, sinon il échoue en indiquant le tag précédent.
6. Si le tag du sidecar change : 0 room LiveKit et 0 session sidecar, puis
   `livekit-up`.
7. `catalog-check`, puis la vérification post-déploiement du §4.

Avec `AGENTIUM_GATE=1`, `migrate` et `up` ferment le gate de maintenance public
pendant la mutation ; un échec le laisse fermé et
`AGENTIUM_IMAGE_TAG=<sha12> agentium-vm-deploy.sh gate-exit <run-id>` le rouvre. Chaque `migrate` et `up`
ajoute une ligne au journal TSV (`journal` l'affiche) ; sa colonne
`previous_tag` est la cible de rollback : `AGENTIUM_IMAGE_TAG=<previous_tag> up`,
plus la restauration du dump si une migration irréversible est passée.

### Ne touche pas à l'infra par accident
- N'utilise **pas** le profil `infra` (`--profile infra`) en déploiement courant :
  il recrée Postgres / Keycloak / Qdrant.
- Ne recrée `agentium-kc` qu'avec `agentium-vm-deploy.sh keycloak-up` (Compose
  du worktree, `127.0.0.1`, healthcheck, `unless-stopped`) ; jamais par
  `docker run`.
- Ne recrée `agentium-livekit` / `agentium-livekit-agent` qu'avec
  `agentium-vm-deploy.sh livekit-up`, hors session active ; jamais par
  `docker run`.
- Ne recrée `agentium-sftp` qu'avec `agentium-vm-deploy.sh sftp-up`, hors
  upload en cours : son image reste celle épinglée par digest dans
  `compose.agentium.vm-runtime.yml`, et `up` ne la touche pas.
- Toute modification SFTP est un lot séparé avec rollback propre et canari
  positif prouvant le login **et** l'ouverture du subsystem avant exposition.
  Le banner loopback ou la méthode `none` ne suffisent jamais à remplacer
  l'image Release A.
- Ne contourne jamais le gate maintenance pour lancer un Compose manuel.

### Cas realtime LiveKit

LiveKit reste un déploiement applicatif, pas un déploiement `infra`, mais il a
une contrainte supplémentaire : le serveur `agentium-livekit` ne lit pas tout le
fichier backend `AGENTIUM_ENV_FILE`. Compose doit recevoir explicitement les
clés LiveKit dans l'environnement du shell, sinon le serveur média peut démarrer
avec les clés de démo pendant que le backend utilise les vraies clés VM.
Si `LIVEKIT_WEBHOOK_API_KEY` est dédiée, elle doit être présente dans
`LIVEKIT_KEYS` et le backend doit recevoir son secret via
`LIVEKIT_WEBHOOK_API_SECRET`. Le fichier
`docker/livekit/agentium-livekit.yaml` contient seulement un placeholder
`__LIVEKIT_WEBHOOK_API_KEY__` ; le compose le remplace au démarrage du conteneur
avec `LIVEKIT_WEBHOOK_API_KEY` avant de lancer `/livekit-server`.
La plage UDP demo par defaut est courte (`50000-50100`) pour eviter un blocage
Docker lors du publish de milliers de ports sur la VM. Elargir vers
`50000-60000` seulement lors d'un vrai cutover WebRTC production avec firewall
et monitoring prets.
Sur la VM demo mono-domaine, l'ingress public LiveKit peut rester sur
`wss://agentium.papai.ai/livekit` via Nginx, qui strippe le prefixe `/livekit/`
vers `127.0.0.1:7880`. Le sous-domaine `livekit.agentium.papai.ai` n'est pas
obligatoire tant que le certificat/DNS dedie n'existe pas.

En production, `agentium-livekit` et son sidecar `agentium-livekit-agent` ne
sont recréés que par `agentium-vm-deploy.sh livekit-up` : Compose du worktree,
bundle gelé (les clés `LIVEKIT_*` et `OPENAI_API_KEY` viennent de
`compose.effective.env`), `--wait`, et seuls les services dont la config rendue
a changé. Le sidecar est construit depuis `livekit-agent/` au tag `<sha12>`
par `scripts/agentium-vm-build.sh`, avec les autres images. Recréer coupe les sessions en cours :
vérifier avant `active_sessions: 0` sur le `/healthz` du sidecar et 0 run actif.
Dans une transaction Release A, l'orchestrateur capture leur image, leur état,
leurs ports et leur restart policy, ferme l'ingress UDP/TCP, draine les
participants, puis restaure exactement cet état après validation.

Ne pas sourcer tout `env/agentium.vm.env` : certains champs peuvent contenir des
espaces non quotés et les secrets ne doivent pas apparaître dans l'historique du
shell.

Checks realtime minimum :

```bash
docker compose -f compose.agentium.yml --profile realtime ps agentium-livekit agentium-livekit-agent agentium-backend agentium-frontend
docker inspect -f "{{.State.Health.Status}}" agentium-livekit-agent
docker inspect -f "{{.State.Health.Status}}" agentium-backend
docker exec agentium-backend python -c "from app.services.livekit_service import LiveKitService; c=LiveKitService().public_config(); print(c['enabled'], c['url'])"
curl -fsS http://127.0.0.1:${AGENTIUM_FRONTEND_HOST_PORT:-8081}/healthz
docker logs --tail=80 agentium-livekit-agent
docker logs --tail=80 agentium-livekit
docker ps --format '{{.Names}}\t{{.Status}}' | grep agentium-sftp
```

La session Knowledge Capture doit emettre au moins ces metriques data-channel :
`livekit_agent_dispatched`, `session_started`, `livekit_agent_joined`,
`time_to_first_text`, puis `livekit_barge_in_audio_reset` et `barge_in` si
l'expert coupe l'IA. Le champ `connect_attempts` sur
`livekit_agent_dispatched`/`session.ready` permet de diagnostiquer une latence de
connexion LiveKit sans ouvrir les logs Node.

Le rollback realtime passe lui aussi par le même `deployment-id`. Il ne lance
pas `--profile infra`, ne recrée pas Postgres/Qdrant/Keycloak et ne touche pas
au contenu SFTP. Après la frontière durable `opened`, on utilise un correctif
forward ou un feature flag ; on ne restaure jamais silencieusement une base qui
a pu recevoir de nouvelles écritures.

### Cas realtime-scale LiveKit / Redis

Le profil `realtime-scale` est reserve au moment ou LiveKit doit tourner en
multi-node ou ou l'on veut valider explicitement la couche Redis LiveKit. Il
n'est pas requis pour la VM demo single-node. Son activation est une release
complète et passe par l'orchestrateur ; aucune commande Compose ad hoc n'est
autorisée sur la VM live.

Ce profil ne doit pas etre ajoute a la commande de deploiement courant tant que
le besoin multi-node n'est pas etabli. Si `LIVEKIT_REDIS_ADDRESS` est vide, le
serveur LiveKit reste en single-node. L'egress/recording reste bloque par
defaut (`LIVEKIT_EGRESS_ENABLED=false`) ; l'autorisation par workspace doit etre
documentee avant tout enregistrement audio.

---

## 4. Vérification post-déploiement (obligatoire)

Un déploiement n'est « fini » que si ces checks passent.

```bash
# Santé
ssh omnirag-demo 'docker inspect -f "{{.State.Health.Status}}" agentium-backend'   # -> healthy
ssh omnirag-demo 'curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:${AGENTIUM_BACKEND_HOST_PORT:-8001}/health/live'  # -> 200

# Le code qui TOURNE = le commit attendu (pas seulement le checkout hôte).
# Le JSON doit porter le SHA complet attendu et revision_verified=true.
ssh omnirag-demo 'curl -fsS http://127.0.0.1:${AGENTIUM_BACKEND_HOST_PORT:-8001}/api/v1/build-info'

# Frontend servi
ssh omnirag-demo 'curl -fsSI http://localhost:8081/ | head -1'
```

> Piège vécu : l'image peut être rebuild à partir d'un arbre périmé. Toujours
> vérifier un **marqueur du changement dans le conteneur qui tourne**, pas
> seulement le SHA du checkout hôte.

### Checklist de clôture
- [ ] `git status` local propre, commit poussé sur `origin/demo/agentic`.
- [ ] VM : `git rev-parse HEAD` == `origin/demo/agentic`.
- [ ] `agentium-backend` healthy, `/health/live` = 200.
- [ ] `build-info` backend et frontend liés au SHA attendu ; pour le backend,
  `revision_verified=true`.
- [ ] IDs OCI backend/frontend/worker exactement égaux à la provenance canari ;
  l'override privé est figé dès le build et toutes les recréations
  backend/frontend/worker/P4 l'utilisent par ID, pas le seul tag mutable ; le
  rollback applique le même contrat aux images précédentes et à SFTP.
- [ ] Aucune instrumentation debug résiduelle (`grep -c debug-trace` == 0).
- [ ] Trois sauvegardes hors VM restaurables attestées exactement pour
  `/dev/sda1`, `/dev/sdb` et `/dev/sdc` ; topologie de stockage inchangée.
- [ ] Runner sûr terminé : System 360 Showcase, six gardes Andritz dont un seul
  Chat contrôlé, Sentinel et Octocity séparés, puis inventaire PostgreSQL v2
  constant-space lié au ledger, Qdrant, MinIO, FAISS et Secure Deposit validés.
- [ ] Audit global des bindings sans `ExpertCaptureSession -> System` entre
  workspaces ; la dérive `test -> Andritz` n'a pas été masquée par un seed.
- [ ] Preuve SFTP correctement qualifiée : le banner loopback sous gate externe
  est `runner_verified`, pas une preuve de login/subsystem ; un canari positif
  jetable est obligatoire avant la promotion. Le rollback possède en plus son
  propre reçu frais de continuité (runtime précédent, même image/host key,
  port publié, inventaire auth inchangé et `/dev/sdc` encore read-only).

---

## 5. Anti-patterns (ce qu'on ne refait plus)

| Anti-pattern | Pourquoi c'est cassé | À la place |
|---|---|---|
| `rsync`/`scp` de fichiers vers la VM | Aucune traçabilité, dérive silencieuse vs `origin` | Orchestrateur épinglé au SHA poussé |
| Rebuild VM sans aligner git d'abord | Image construite depuis un arbre périmé (régressions ré-introduites) | §3 étape 1 **avant** le build |
| Laisser la VM en arbre sale / non commité | « quel code tourne ? » sans réponse | La VM ne contient que du code de `origin` |
| Oublier `AGENTIUM_ENV_FILE` | Backend démarre sur `agentium.env.example` → auth Postgres échoue | Toujours exporter `./env/agentium.vm.env` depuis `docker/` |
| Commiter secrets / instrumentation debug | Fuite + bruit en prod | `.gitignore` + nettoyage avant commit |
| Vérifier seulement le SHA du checkout hôte | L'image ou le processus systemd en cours peut différer du checkout | Vérifier les `build-info` backend/frontend et `revision_verified=true` |
| `docker compose up` à la main sur la VM | Ni contrôle de stockage, ni dump, ni vérification build-info, ni journal | Toujours passer par `agentium-vm-deploy.sh` |
| Prendre le banner SFTP pour un test métier | Aucun credential ni subsystem SFTP n'a été utilisé | Conserver le plafond `runner_verified` et utiliser un principal canari jetable pour la preuve positive |
| Réparer une dérive tenant par seed/reconcile | Mutation non bornée des données Andritz | Qualifier, sauvegarder et corriger par décision opérateur auditée |

---

## 6. Lanceur de déploiement unique

`scripts/agentium-vm-deploy.sh` est l'unique entrée opérateur. Il arrive sur la
VM par git (worktree de build), jamais par `scp`, et s'exécute en root avec un
environnement nettoyé (`env -i`) : aucune variable ambiante ne peut rediriger
Compose ou le stockage.

Avant toute mutation (`migrate`, `up`, `catalog-apply`, `sftp-up`, `keycloak-up`, `livekit-up`), il refuse un
stockage qui a quitté ses disques : `/srv/agentium-data` doit être le point de
montage de `/dev/sdb` et chaque magasin un dossier réel dessus, le dépôt
sécurisé le point de montage de `/dev/sdc`, les volumes MinIO/Qdrant les binds
attendus, et les conteneurs en cours leurs montages contractuels. Il n'appelle
jamais `docker volume prune` ni un seed, et le profil `infra` seulement via
`keycloak-up`, pour le seul service `agentium-kc`.

Les garde-fous repris de la chaîne safe sont le dump vérifié avant `migrate`, le
gate de maintenance optionnel, la preuve `build-info` après `up` et le journal
TSV (§3). Les preuves Release A (manifeste de diff, attestations, canaris SFTP)
restent l'historique de la Release A : l'exécuteur
`deploy-agentium-release-a-safe.sh` relit ses aides au SHA Release A, pas au
HEAD, et le profil `_ALLOWED_PATHS` v7 n'a pas changé.

> Audit de dérive à la demande (sans déployer) :
> ```bash
> ssh omnirag-demo 'sudo tail -5 /srv/agentium-data/deployments/journal.tsv; docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"'
> ```
