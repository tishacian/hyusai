# Politique de développement & déploiement — Agentium / OmniRAG

> But : un **chemin unique et reproductible** pour développer en local, livrer via
> git, et déployer sur la VM `omnirag-demo` via Docker. Cette note existe pour
> éviter le workflow accidenté qu'on a subi (rsync de fichiers non commités,
> arbre git sale, rebuild à partir d'une copie périmée, VM désynchronisée de
> `origin`).
>
> Pour toute opération de production, y compris cutover Nginx, protection
> MinIO/Qdrant, adoption SFTP ou migration de stockage, la référence exécutable
> unique est `docs/ops/agentium-safe-vm-deployment.md`. Le runbook historique
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
local (branche)  ──commit──>  origin/demo/agentic  ──git fetch+reset──>  VM  ──docker build+up──>  conteneurs
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
[runbook VM sûr](./ops/agentium-safe-vm-deployment.md). La construction des
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
| Dossier de déploiement | `/home/ubuntu/omnirag` (checkout git) |
| Dossier compose | `/home/ubuntu/omnirag/docker` |
| Fichier compose | `compose.agentium.yml` |
| Env conteneurs | `docker/env/agentium.vm.env` (gitignored, **jamais** dans un commit) |
| `AGENTIUM_ENV_FILE` | `./env/agentium.vm.env` — **relatif au dossier `docker/`** |

> Piège vécu : `AGENTIUM_ENV_FILE=./env/agentium.vm.env` est relatif à `docker/`,
> donc le fichier est `docker/env/agentium.vm.env`, pas `env/` à la racine.
> Sans le bon env file, le backend démarre avec `agentium.env.example` et échoue
> sur l'auth Postgres.

### Topologie de stockage à conserver

La transition A/B n'est pas une migration de stockage :

- PostgreSQL, l'état Keycloak persisté dans PostgreSQL, RabbitMQ et le bind
  FAISS historique restent sur le filesystem racine `/dev/sda1` ;
- Qdrant, MinIO et l'ObjectStore restent sous `/srv/agentium-data`, monté sur
  `/dev/sdb` ;
- le Secure Deposit SFTP reste sous
  `/home/ubuntu/omnirag/backend/data/secure_deposit`, monté sur `/dev/sdc`.

Le GO Release A exige exactement trois sauvegardes fournisseur ou hors VM,
distinctes et restaurées : une pour chacun de `/dev/sda1`, `/dev/sdb` et
`/dev/sdc`. Un dump ou inventaire conservé sur l'un de ces mêmes disques ne
remplace pas cette preuve.

### Procédure standard (chemin unique)

L'orchestrateur est propriétaire du fetch/reset épinglé, du build, de la
quiescence backend/worker/SFTP, des dumps, des migrations, des attestations et
du rollback. Il s'arrête en `validation_pending`, puis suit exactement
`sftp_canary_pending -> sftp_canary_active_recorded -> sftp_canary_recorded ->
opening_forward -> completed` via `arm-sftp-canary`, `record-sftp-active`,
`record-sftp-final` et `finalize`. `resume` ne fournit aucune preuve et ne
rouvre aucun writer : il réconcilie seulement une transaction interrompue. Le
control plane backend/Keycloak utilisé pour créer et révoquer le principal
jetable reste non public et est arrêté avant les snapshots SFTP. La procédure
complète — y compris les quatre identités de workspace explicites, le dry-run
du backfill, les deux reprises et le rollback — est documentée uniquement dans
[`ops/agentium-safe-vm-deployment.md`](./ops/agentium-safe-vm-deployment.md).

Ne recopier ici aucune commande abrégée : omettre les identités canaris ou le
digest du dry-run transforme une transaction vérifiable en procédure ambiguë.

`scripts/deploy-vm.sh --build-only/--activate-only` reste une primitive interne.
Il ne constitue plus, seul, une transaction de production sûre et ne doit
jamais être invoqué directement par l'opérateur.

Le protocole sûr journalise une transaction monotone. Les états, métadonnées et
artefacts privés sont publiés atomiquement ; les dumps ne sont utilisables
qu'avec leur checksum et leur marqueur `.ready`. Une reprise pré-migration passe
par `recovering_pre_migration`, et un rollback persiste `rollback_closing` avant
sa première mutation. Une reprise qui rencontre cette intention refuse de
repartir vers l'avant.

La fermeture suit un ordre crash-safe non interchangeable : restart policies
durables `no` et unités writers désactivées, gate HTTP persistant, barrières
ingress IPv4/IPv6, drainage et arrêt des writers, puis seulement
`closing_intent` publié et fsyncé. Ainsi, un reboot après `closing_intent` ne
peut pas faire repartir un writer automatiquement.

Une reprise après la frontière publique applique le même niveau d'exclusion :
elle reclôt les ingress, draine les sessions existantes, quiesce SFTP et
Keycloak, arrête backend/worker/P4/LiveKit, exige RabbitMQ vide et PostgreSQL
sans connexion applicative, puis seulement remonte le Secure Deposit en lecture
seule. Un remount forcé pendant un upload ou un Run est interdit.

### Ne touche pas à l'infra par accident
- N'utilise **pas** le profil `infra` (`--profile infra`) en déploiement courant :
  il recrée Postgres / Keycloak / Qdrant.
- Ne redémarre/recrée **jamais** `agentium-sftp` manuellement. L'orchestrateur
  le pause, vérifie les descripteurs d'upload et conserve l'ID d'image validé
  en Release A. Release B ne construit ni ne recrée SFTP ; elle redémarre
  exactement cette image après ses preuves sous gate. Seul le rollback
  transactionnel peut recréer le conteneur, depuis l'ID exact de l'override v3,
  sans toucher au bind `/dev/sdc`, puis après une nouvelle preuve fermée et une
  preuve du port publié loopback par le runtime précédent.
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

LiveKit n'est jamais construit, recréé ou arrêté par une commande Compose
isolée en production. L'orchestrateur capture son image, son état, ses ports et
sa restart policy, ferme l'ingress UDP/TCP, draine les participants, puis
restaure exactement cet état après validation. Toute modification de clés,
plage UDP ou profil `realtime` fait partie du SHA et de la transaction complète.

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
| Invoquer `deploy-vm.sh` directement | Build/activation sans journal, quiescence, inventaires ni rollback transactionnel | Toujours passer par l'orchestrateur sûr après GO explicite |
| Prendre le banner SFTP pour un test métier | Aucun credential ni subsystem SFTP n'a été utilisé | Conserver le plafond `runner_verified` et utiliser un principal canari jetable pour la preuve positive |
| Réparer une dérive tenant par seed/reconcile | Mutation non bornée des données Andritz | Qualifier, sauvegarder et corriger par décision opérateur auditée |

---

## 6. Orchestrateur de déploiement unique

`scripts/deploy-agentium-safe.sh` est l'unique entrée opérateur. Il compose les
primitives de build et d'activation avec les protections données et le gate de
validation. Il arrive sur la VM par git, jamais par `scp`.

La livraison locale suit le §2 uniquement après une autorisation explicite et
avec une liste de fichiers stageés contrôlée. Ne pas transformer ce runbook en
commande chaînée commit/push.

La commande VM complète n'est pas répétée ici : elle exige quatre identités de
workspace, un `deployment-id`, puis le digest du dry-run Workspace Apps. Utiliser
la séquence copiée depuis le runbook opératoire, jamais une version abrégée.
Le premier `preflight` exige d'abord les chemins privés et SHA-256 explicites du
manifeste Release A et de sa policy de revue, puis ceux de l'attestation
opérationnelle Release A. Les deux gates sont indépendants : l'attestation ne
remplace pas le manifeste. Les phases suivantes utilisent exclusivement les
copies figées et revalident leurs reçus liés au SHA précédent.

Avant le push, le déploiement et l'attestation de la Release A, le worktree A
propre doit avoir produit un `review-template`, fait renseigner cette revue
sémantique, exécuté `seal-review`, puis créé et vérifié son manifeste privé avec
`create` et `verify`. Ce manifeste lie le SHA live fixe, le SHA A, les blobs et
digests exacts du diff et l'empreinte de la policy fail-closed ; une liste
`git diff` relue informellement ne le remplace pas. Les commandes complètes sont celles du
[plan Git A/B](./ops/agentium-release-a-b-git-plan-2026-07-22.md) et le fichier
reste hors dépôt.

L'orchestrateur refuse une VM sale, une branche distante différente, un gate
Nginx absent, un montage déplacé, un espace disque insuffisant, un upload SFTP
ouvert, une dérive de binding entre tenants et un artefact de validation
déclaratif/non relié aux snapshots. Son inventaire PostgreSQL v2 traite toutes
les lignes en espace constant, borne les artefacts et ne sérialise que les
empreintes des lignes contrôlées par le ledger. Il n'appelle jamais
`docker volume prune`, un seed ou le profil `infra`.

> Audit de dérive à la demande (sans déployer) :
> ```bash
> ssh omnirag-demo 'cd /home/ubuntu/omnirag && git status --short --branch && docker ps --format "table {{.Names}}\t{{.Status}}"'
> ```

Il n'existe volontairement aucune procédure manuelle « équivalente » : débrayer
la quiescence, les attestations ou l'état de rollback change le niveau de sûreté
et exige un runbook d'incident distinct.
