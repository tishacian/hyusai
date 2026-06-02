# LiveKit Conversation Stack Plan - Agentium

Objectif : ajouter LiveKit comme transport temps reel pour la gestion de
conversation Agentium, en particulier Knowledge Capture et le chat voix, sans
remplacer la logique metier existante (`VoiceSessionGateway`,
`VoiceRuntimeProvider`, `VoiceTandemOracle`, `process_conversation_step`).

Repo LiveKit inspecte : `/Users/thib/Developer/PAPAI/livekit`.

## 0. Etat inspecte

Ce plan s'appuie sur une lecture croisee du serveur LiveKit local et de la
stack Agentium actuelle.

Sources LiveKit verifiees :

- `/Users/thib/Developer/PAPAI/livekit/go.mod` : module Go
  `github.com/livekit/livekit-server`, pas une dependance Python/Angular.
- `/Users/thib/Developer/PAPAI/livekit/Dockerfile` : build du binaire
  `livekit-server` depuis `./cmd/server`, puis entree container
  `/livekit-server`.
- `/Users/thib/Developer/PAPAI/livekit/README.md` : separation explicite entre
  serveur OSS, Docker image, Client SDKs, Server SDKs et Agents SDKs.
- `/Users/thib/Developer/PAPAI/livekit/config-sample.yaml` : ports `7880`,
  range UDP `50000-60000`, ICE/TCP `7881`, Redis optionnel, webhooks et
  configuration audio.
- `/Users/thib/Developer/PAPAI/livekit/pkg/service/roomservice.go` et
  `roommanager.go` : API RoomService, notamment `CreateRoom`, participants,
  metadata et `SendData`.
- `/Users/thib/Developer/PAPAI/livekit/pkg/rtc/room.go` : diffusion des data
  packets, destinations par identity et deduplication par nonce.
- `/Users/thib/Developer/PAPAI/livekit/pkg/agent/worker.go` et `client.go` :
  protocole Agents, jobs room/publisher/participant et permissions par defaut
  incluant publish/subscribe/data.

Sources Agentium verifiees :

- `docs/dev-deploy-policy.md` : deploiement par commit/push, pull/reset sur VM
  et Docker, sans `scp`/`rsync`, sans toucher `agentium-sftp`.
- `docs/voice-v2v-structural-plan.md` : contrat provider-neutral des events
  voix (`session.start`, `audio.frame`, `text.partial`, `oracle.delta`,
  `conversation.step`, `runtime.metric`, etc.).
- `backend/app/services/voice_session_gateway.py` : gateway WebSocket actuel,
  endpointing, partial STT, oracle et `process_conversation_step`.
- `backend/app/services/voice_runtime.py` et `backend/app/core/config.py` :
  providers voix, fallback `cascade_openai`, transport actuel `backend_ws`.
- `frontend-ng/src/app/core/voice-session.service.ts` et
  `voice-loop-controller.service.ts` : boucle micro actuelle, events WS,
  endpointing et barge-in cote navigateur.
- `frontend-ng/package.json` : `livekit-client` est ajoute et charge
  dynamiquement par `LiveKitConversationService`.
- `backend/pyproject.toml` : pas de SDK Python LiveKit ajoute pour P0/P1 ; le
  backend genere les JWT avec PyJWT et appelle les APIs HTTP/Twirp LiveKit.
- `docker/compose.agentium.yml` et `deploy/nginx/agentium-container-backend.conf`
  : services Docker, profils `infra`/`sftp`, port backend `8001` sur la VM et
  proxy WebSocket existant pour `/api/v1/voice/sessions/`.

## 1. Decision d'architecture

La premiere vague ne doit pas forker le serveur LiveKit. Le code LiveKit local
montre deja les primitives necessaires :

- serveur WebRTC/SFU avec audio, video et data ;
- JWT et RoomService pour creer rooms, participants et permissions ;
- `SendData` RoomService, qui diffuse des `DataPacket_User` avec `Topic`,
  `DestinationIdentities` et `Nonce` ;
- webhooks de cycle de vie room/participant/track ;
- audio level / speaker detection ;
- protocole Agents pour lancer des participants backend.

Agentium doit donc consommer LiveKit comme infrastructure conversationnelle, pas
comme moteur metier. La source de verite conversation reste Agentium :

```text
Frontend Agentium
  -> LiveKit room audio/data
  -> Agentium LiveKit Agent participant
  -> VoiceSessionGateway / VoiceRuntimeProvider / TandemOracle
  -> Knowledge Capture + Chat events + audit
  -> LiveKit data/audio back to the room
```

## 1 bis. Diagnostic d'integration

Question tranchee : LiveKit n'est pas a integrer par cherry-pick de code serveur
dans Agentium. Le repo local est utile pour comprendre les primitives et, si
necessaire, construire une image serveur, mais pas comme framework applicatif a
importer dans notre backend Python ou notre frontend Angular.

| Option | Diagnostic | Decision Agentium |
| --- | --- | --- |
| Framework importable dans Agentium | Non pour le repo `livekit-server` : c'est un module Go qui produit un binaire serveur. Il peut etre importe par du Go, mais Agentium est Python/Angular et ne doit pas embarquer les packages internes `pkg/rtc`, `pkg/service`, `pkg/agent`. | Ne pas importer le repo serveur Go. |
| Service Docker dans la stack | Oui : c'est le mode naturel pour le media server LiveKit. Le Dockerfile local construit `/livekit-server`, et le README reference l'image Docker officielle. | Ajouter `agentium-livekit` au compose, profil `realtime`, avec une image taguee/pinnee. |
| SDK frontend | Oui : le README reference le SDK JavaScript/TypeScript. | `livekit-client` est ajoute cote Angular et charge a la demande par `LiveKitConversationService`. |
| SDK backend/server | Oui pour les primitives serveur, mais P0/P1 n'impose pas un SDK Python dedie. | Le backend genere les JWT avec PyJWT et appelle RoomService via HTTP/Twirp ; ajouter un SDK Python seulement si le besoin depasse ce contrat. |
| SDK Agents / participant backend | Oui, mais a choisir prudemment. LiveKit Agents est l'ecosysteme naturel pour des participants backend programmables. | P0 sidecar simple avec SDK client/RTC ; P2 migration vers protocole Agents si utile. |
| Cherry-pick de code LiveKit | Mauvaise option : risque de divergence, dette Go, couplage fort, securite/media difficiles a maintenir. | Interdit hors patch upstream tres cible. |
| Clone du repo LiveKit sur la VM | Non necessaire pour P0/P1. La VM de demo doit rester un checkout Agentium aligne sur `origin/demo/agentic`; LiveKit est lance via image Docker officielle ou image pinnee. | Ne pas cloner `/home/ubuntu/livekit` par defaut. Cloner seulement pour debug serveur avance ou fork explicite. |
| Inspiration architecture/design | Oui : lire le repo pour comprendre data packets, room metadata, webhooks, workers, permissions et audio levels. | Continuer a s'en servir comme reference de design. |

Synthese : LiveKit entre dans Agentium comme **service Docker + SDKs**. Le code
du repo `/Users/thib/Developer/PAPAI/livekit` reste une **reference
d'architecture et de verification**, pas une source a copier ni un checkout a
repliquer sur la VM.

## 2. Pourquoi LiveKit dans Agentium

Le WebSocket actuel `/api/v1/voice/sessions/{session_id}` est bon pour le
protocole metier, mais il oblige Agentium a transporter lui-meme l'audio encode
en base64. LiveKit apporte :

- une vraie session media full-duplex WebRTC ;
- une gestion propre des participants, reconnexions, permissions et data
  channels ;
- un chemin naturel pour l'audio assistant en track, pas en `audio.out` base64 ;
- les webhooks de presence pour audit et nettoyage ;
- une rampe vers agents backend et egress sans recoder un SFU.

Le contrat Agentium existant reste utile. Les events provider-neutral
`text.partial`, `text.final`, `conversation.step`, `oracle.delta`,
`oracle.commit`, `runtime.metric`, `barge_in`, `prompt.next` deviennent le
payload data-channel transporte par LiveKit.

## 3. Stack cible

### Services Docker

Ajouter dans `docker/compose.agentium.yml` :

| Service | Role | Profil |
| --- | --- | --- |
| `agentium-livekit` | Serveur LiveKit WebRTC/SFU | `realtime` |
| `agentium-livekit-agent` | Participant backend qui relie room LiveKit et Agentium | `realtime` |

Ne pas utiliser le profil `infra` pour les deploiements applicatifs. Ne pas
toucher `agentium-sftp`.

P0 peut demarrer LiveKit en standalone sans Redis. P2/P3 ajoutera Redis si on
veut multi-node ou haute dispo. LiveKit supporte Redis pour le mode distribue,
mais ce n'est pas un prerequis pour une VM demo mono-noeud.

### Ports et reseau

LiveKit a besoin de :

- TCP `7880` pour API/WebSocket RTC, derriere TLS/Nginx ;
- UDP range media, par defaut `50000-60000` ;
- TCP `7881` optionnel pour ICE/TCP ;
- TURN/TLS si les reseaux clients bloquent UDP.

Proposition VM :

```text
livekit.agentium.papai.ai  -> Nginx TLS -> 127.0.0.1:7880
UDP 50000-60000            -> host -> agentium-livekit
TCP 7881                   -> host -> agentium-livekit, si ICE/TCP active
```

Garder `/api/v1/voice/sessions/` proxie vers le backend comme fallback WS
Agentium. LiveKit est un domaine ou chemin separe, pas un remplacement de l'API.

## 4. Configuration

### Env backend Agentium

Ajouter dans `docker/example.env` pour la documentation publique, et dans le
fichier VM gitignore `docker/env/agentium.vm.env` lors du deploiement :

```text
LIVEKIT_ENABLED=false
LIVEKIT_URL=wss://livekit.agentium.papai.ai
LIVEKIT_INTERNAL_URL=http://agentium-livekit:7880
LIVEKIT_API_KEY=<key>
LIVEKIT_API_SECRET=<secret>
LIVEKIT_KEYS=<key>: <secret>
LIVEKIT_DEFAULT_ROOM_TTL_SECONDS=3600
LIVEKIT_AGENT_IDENTITY_PREFIX=agentium-agent
LIVEKIT_AGENT_CONNECT_ATTEMPTS=6
LIVEKIT_AGENT_CONNECT_RETRY_MS=500
LIVEKIT_AGENT_CONNECT_MAX_RETRY_MS=3000
LIVEKIT_WEBHOOK_API_KEY=<same key by default>
LIVEKIT_WEBHOOK_API_SECRET=<same secret by default>
```

Ne pas commiter les secrets LiveKit. Le backend lit le fichier VM via
`AGENTIUM_ENV_FILE=./env/agentium.vm.env`, relatif a `docker/`. Pour
`agentium-livekit`, Compose interpole `LIVEKIT_KEYS` depuis l'environnement du
shell ; il faut donc exporter les variables LiveKit depuis `env/agentium.vm.env`
avant les commandes Docker du profil `realtime`. Ne pas sourcer tout le fichier :
certains champs peuvent contenir des espaces non quotes. Si une cle webhook
dediee est utilisee, elle doit etre presente dans `LIVEKIT_KEYS`, car LiveKit
exige que `webhook.api_key` corresponde a une cle configuree. Le backend doit
recevoir le secret correspondant via `LIVEKIT_WEBHOOK_API_SECRET` ; par defaut,
il reutilise `LIVEKIT_API_SECRET`.

### Config LiveKit

Fichier ajoute : `docker/livekit/agentium-livekit.yaml`.

```yaml
port: 7880
rtc:
  port_range_start: 50000
  port_range_end: 60000
  tcp_port: 7881
  use_external_ip: true
webhook:
  api_key: __LIVEKIT_WEBHOOK_API_KEY__
  urls:
    - http://agentium-backend:8000/api/v1/livekit/webhooks
room:
  auto_create: false
  empty_timeout: 60
  departure_timeout: 20
audio:
  active_level: 30
  min_percentile: 40
  update_interval: 500
```

Les secrets ne sont pas dans ce fichier. Le compose injecte seulement
`LIVEKIT_KEYS` et `LIVEKIT_WEBHOOK_API_KEY` dans `agentium-livekit`, puis
remplace le placeholder `__LIVEKIT_WEBHOOK_API_KEY__` au demarrage du conteneur
avant d'appeler `/livekit-server --config`. La cle webhook doit exister dans
`LIVEKIT_KEYS`; garder la meme cle que `LIVEKIT_API_KEY` est le chemin le plus
simple pour la demo.

Le service `agentium-livekit-agent` ne depend pas d'un endpoint HTTP LiveKit
interprete comme healthcheck : le serveur expose un protocole RTC/Twirp et les
endpoints exacts peuvent varier selon l'image. Pour absorber le decalage de
demarrage Docker, le sidecar retente `room.connect()` au moment du dispatch via
`LIVEKIT_AGENT_CONNECT_ATTEMPTS`, `LIVEKIT_AGENT_CONNECT_RETRY_MS` et
`LIVEKIT_AGENT_CONNECT_MAX_RETRY_MS`, puis nettoie la session si LiveKit reste
injoignable.
Si `LIVEKIT_WEBHOOK_API_KEY` est dediee, ajouter aussi son secret cote backend
avec `LIVEKIT_WEBHOOK_API_SECRET`.

Note runtime : `LIVEKIT_URL` est l'URL publique exposee au navigateur
(`wss://...`). Le sidecar `agentium-livekit-agent` ne l'utilise pas pour joindre
la room ; le backend lui transmet une URL derivee de `LIVEKIT_INTERNAL_URL`
convertie en WebSocket (`http://agentium-livekit:7880` -> `ws://agentium-livekit:7880`).
Cela evite de dependre du DNS/TLS public depuis le reseau Docker interne.

## 5. Contrat backend Agentium

### Endpoints a ajouter

```http
GET  /api/v1/livekit/config
POST /api/v1/livekit/rooms
POST /api/v1/livekit/token
POST /api/v1/livekit/webhooks
POST /api/v1/livekit/sessions/{session_id}/agent/dispatch
```

`/config` :

- expose `enabled`, `url`, codecs recommandes, feature flags ;
- jamais l'API secret.

`/rooms` :

- cree ou retrouve une room LiveKit liee a `workspace_id`, `session_id`,
  `surface=knowledge_capture|chat`, `mode=conversation_only|chat_voice` ;
- pose metadata room JSON avec `agentium_session_id`, `workspace_id`,
  `surface`, `created_by_user_id`.

`/token` :

- genere un JWT LiveKit pour le participant navigateur ;
- permissions minimales :
  - `roomJoin=true`,
  - `canPublish=true` pour micro,
  - `canSubscribe=true` pour audio assistant,
  - `canPublishData=true`,
  - room exacte seulement ;
- identity stable : `user:<user_id>:<short_session_id>`.

`/webhooks` :

- valide signature LiveKit ;
- persiste presence/lifecycle dans audit et metrics ;
- ne doit pas servir de source de transcription.

`/agent/dispatch` :

- declenche le participant backend Agentium si pas deja present ;
- P0 peut le faire via notre propre sidecar ;
- P2 pourra utiliser le protocole Agents LiveKit si on veut deleguer au
  dispatcher natif.

### Modele de donnees

P0 sans migration obligatoire :

- `ExpertCaptureSession.metrics.livekit` pour room, participants, joins/leaves,
  latency et fallback ;
- `ExpertCaptureSession.transcript[]` continue de porter les segments ;
- `ExpertCaptureEvent` si present continue l'append-only.

P1/P2 migration optionnelle :

```text
conversation_sessions
  id
  workspace_id
  surface
  domain_session_id
  livekit_room_name
  livekit_room_sid
  status
  created_by_user_id
  started_at
  ended_at
  metadata

conversation_events
  id
  conversation_session_id
  type
  participant_identity
  livekit_event_id
  payload
  created_at
```

La migration n'est utile que si le chat voix et Knowledge Capture partagent
durablement la meme couche.

## 6. Agentium LiveKit Agent

Le service `agentium-livekit-agent` est la piece centrale. Il rejoint la room
comme participant cache et fait le pont :

```text
LiveKit audio track utilisateur
  -> STT / VoiceRuntimeProvider
  -> VoiceSessionGateway-compatible event stream
  -> Knowledge Capture / Chat engine
  -> TTS / assistant audio track
  -> LiveKit room

LiveKit data channel
  -> control events: barge_in, endpoint, command, pause/resume
  -> Agentium event envelope
  -> LiveKit data channel back to UI
```

### Deux options d'implementation

Option A - Sidecar Python/Node Agentium :

- plus rapide pour P0/P1 ;
- utilise les SDK LiveKit client/server ;
- appelle directement les services Agentium ou le WebSocket interne ;
- ne modifie pas le serveur LiveKit.

Option B - LiveKit Agents natif :

- plus propre si on adopte pleinement l'ecosysteme Agents ;
- le serveur LiveKit peut dispatcher les jobs room/participant ;
- necessite un worker conforme au protocole Agents.

Decision P0 : Option A. Garder Option B pour P2 quand les metriques et le flux
produit sont stabilises.

Etat implementation Phase 0 : le premier shim agent data-only est porte par le
backend Agentium via `RoomService.SendData`, expose par
`POST /api/v1/livekit/sessions/{session_id}/agent/dispatch`. Il garantit la room
et publie `session.ready`, `runtime.metric` et, en test, `text.partial` sur les
topics LiveKit. Phase 0 est conservee comme fallback si le sidecar n'est pas
joignable.

Etat implementation Phase 1 partielle : `agentium-livekit-agent` rejoint la room
comme participant cache, observe les tracks audio LiveKit, maintient un WebSocket
interne court-lived vers `VoiceSessionGateway`, relaie les events backend vers le
data channel LiveKit, bufferise le PCM entrant puis l'envoie au gateway sous
forme WAV au moment de `audio.endpoint`. Le gateway Agentium reste donc la source
de verite pour STT, correction transcript, oracle, `conversation.step`,
`prompt.next` et `audio.out`. Le buffer audio est remis a zero sur
`loop.start`, `loop.armed` et `barge_in` pour eviter de transmettre du pre-roll
ou des restes du tour precedent. Le frame WAV complet envoye par le sidecar porte
`incremental_transcription=false` afin que le gateway ne lance pas une STT
incrementale juste avant la STT finale d'endpoint. Un `audio.endpoint` LiveKit
sans audio bufferise publie une metrique mais n'est pas transmis au gateway, afin
d'eviter les erreurs `empty_audio` non actionnables.

Etat observabilite webhooks : `POST /api/v1/livekit/webhooks` valide le bearer
LiveKit, extrait la metadata de room Agentium et met a jour
`ExpertCaptureSession.metrics.livekit` avec compteurs d'evenements, room,
participants, tracks et derniers evenements bornes. Les webhooks non rattaches a
une session Agentium restent acceptes mais non enregistres.

Etat integration UI : `KnowledgeCaptureComponent` sait maintenant ouvrir une
connexion LiveKit via `LiveKitConversationService` lorsque la session ou les
settings workspace demandent explicitement le transport `livekit`. Sinon, la
voie historique `VoiceSessionService` / `backend_ws` reste le fallback par
defaut. En Knowledge Capture, le frontend exige `mode=voice_gateway_bridge`
apres dispatch ; sinon il ferme la room LiveKit et revient automatiquement au
WebSocket historique. Le mode LiveKit signale `audio_bridge=voice_gateway_ready`
quand le sidecar est relie au gateway, `media_observer_ready` si seul
l'observateur media est disponible, et `pending` en fallback data-only.
Quand l'utilisateur met en pause la conversation pendant un tour en cours, l'UI
differe `loop.stop` et la fermeture du transport jusqu'au retour de
`conversation.step` : l'`audio.endpoint` final part donc avant l'arret de la
boucle, ce qui preserve la generation de la proposition/carte finale du tour.

## 7. Mapping des events

Utiliser `DataPacket_User.Topic` pour garder les envelopes Agentium intactes.

| LiveKit topic | Direction | Payload |
| --- | --- | --- |
| `agentium.voice.event` | agent -> clients | `VoiceSessionEvent` existant |
| `agentium.voice.control` | client -> agent | `barge_in`, `audio.endpoint`, `loop.pause`, `loop.stop` |
| `agentium.voice.metric` | agent -> clients/backend | `runtime.metric`, stats LiveKit |
| `agentium.chat.event` | agent -> clients | chat voix hors capture |

Ne pas mapper P0 sur un format LiveKit natif de transcription si cela oblige a
perdre le contrat Agentium. On pourra publier en double plus tard si l'UI
LiveKit native en beneficie.

### Conversion minimale

```json
{
  "id": "evt-...",
  "session_id": "capture-session-id",
  "type": "text.partial",
  "ts_ms": 1710000000000,
  "sequence": 12,
  "payload": {
    "turn_id": "turn-1",
    "text": "je regle la vitesse...",
    "provider": "livekit_agent",
    "transport": "livekit"
  }
}
```

## 8. Frontend

### Dependencies

Ajouter `livekit-client` dans `frontend-ng`.

### Services

Ajouter :

```text
frontend-ng/src/app/core/livekit-conversation.service.ts
```

Responsabilites :

- recuperer `/api/v1/livekit/config` ;
- creer/retrouver room + token ;
- connecter LiveKit Room ;
- publier micro ;
- souscrire audio agent ;
- envoyer/recevoir data packets ;
- exposer un stream compatible `VoiceSessionEvent`.

`VoiceSessionService` reste le fallback `backend_ws`.

### Knowledge Capture

Dans `knowledge-capture.component.ts` :

- si `voice_runtime.default_mode === realtime` et `LIVEKIT_ENABLED`, utiliser
  LiveKit ;
- sinon garder `VoiceSessionService` backend WS ;
- UI identique : transcript partial/final, oracle, questions ouvertes,
  conversation.step, metrics ;
- bouton stop doit couper micro, data channel et TTS/agent audio.

## 9. Barge-in et endpointing

LiveKit donne les tracks et speaker updates, mais la decision metier reste
Agentium.

P0 :

- endpointing frontend existant via `VoiceLoopController` ;
- barge-in client : quand l'utilisateur reparle pendant l'audio assistant,
  envoyer `agentium.voice.control {type: "barge_in"}` ;
- l'agent coupe son audio track/TTS et marque `barge_in`.

P1 :

- utiliser audio-level/speaker detection LiveKit pour detecter parole pendant
  audio assistant ;
- publier `barge_in.detected` puis `barge_in.accepted` ;
- auditer l'interruption dans les events capture.

Etat implementation P2 : le chemin de controle `barge_in` est maintenant
observable sur les deux jambes. Le sidecar publie `runtime.metric` /
`livekit_barge_in_audio_reset` avec le nombre de bytes et frames audio jetes
avant reset, puis transmet `barge_in` au `VoiceSessionGateway`. Le gateway remet
a zero l'etat STT partiel, persiste un audit `voice.barge_in` et publie
`runtime.metric` / `barge_in` avant l'ACK `barge_in accepted`.

## 10. Fallbacks

Tout deploiement LiveKit doit garder les chemins existants :

| Echec | Fallback |
| --- | --- |
| LiveKit disabled | `backend_ws` VoiceSessionGateway |
| Token/room creation fails | afficher erreur + bouton "Conversation classique" |
| Agent participant absent | room reste connectee, mais UI repasse backend WS |
| WebRTC blocked | backend WS ou OpenAI Realtime direct selon config |
| STT/TTS provider fails | `cascade_openai` fallback deja defini |

Le fallback doit etre visible dans `runtime.metric` et dans les metrics de
session.

## 11. Deploiement VM

Respect strict du mode operatoire Agentium :

- code livre par commit + push sur `origin/demo/agentic` ;
- VM alignee par `git fetch` + `git reset --hard origin/demo/agentic` ;
- rebuild Docker depuis `/home/ubuntu/omnirag/docker` ;
- ne pas cloner le repo LiveKit sur la VM en routine : le compose doit utiliser
  une image `livekit/livekit-server:<version>` ou une image Agentium pinnee ;
- ne jamais `scp`/`rsync` de code applicatif ;
- ne pas toucher `agentium-sftp`.
- ne pas lancer `--profile infra` en deploiement courant.

Premiere vague Docker :

```bash
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD=$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' env/agentium.vm.env | cut -d= -f2-)
export LIVEKIT_API_KEY="$(grep -E '^LIVEKIT_API_KEY=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_API_SECRET="$(grep -E '^LIVEKIT_API_SECRET=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_WEBHOOK_API_KEY="$(grep -E '^LIVEKIT_WEBHOOK_API_KEY=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_KEYS="$(grep -E '^LIVEKIT_KEYS=' env/agentium.vm.env | cut -d= -f2-)"
test -n "$LIVEKIT_WEBHOOK_API_KEY" || export LIVEKIT_WEBHOOK_API_KEY="$LIVEKIT_API_KEY"
test -n "$LIVEKIT_KEYS" || export LIVEKIT_KEYS="$LIVEKIT_API_KEY: $LIVEKIT_API_SECRET"
docker compose -f compose.agentium.yml --profile realtime up -d agentium-livekit
docker compose -f compose.agentium.yml --profile realtime build agentium-backend agentium-frontend agentium-livekit-agent
docker compose -f compose.agentium.yml --profile realtime up -d agentium-backend agentium-frontend agentium-livekit-agent
```

Ouvrir les ports UDP uniquement apres validation Nginx/TLS et firewall.

Checks :

```bash
curl -fsS http://127.0.0.1:7880/
docker exec agentium-backend python -c "from app.services.livekit_service import LiveKitService; c=LiveKitService().public_config(); print(c['enabled'], c['url'])"
docker logs --tail=100 agentium-livekit
docker logs --tail=100 agentium-livekit-agent
docker inspect -f "{{.State.Health.Status}}" agentium-backend
docker inspect -f "{{.State.Health.Status}}" agentium-frontend
docker ps | grep agentium-sftp  # doit rester untouched
```

Metriques P2 a verifier dans les data-channel/logs applicatifs :

- `livekit_agent_dispatched` avec `sidecar_status`, `audio_bridge`,
  `connect_attempts` et `fallback_reason` ;
- `session.ready` avec `connect_attempts` et `voice_gateway_connected` ;
- `livekit_agent_joined` quand le participant cache est connecte ;
- `time_to_first_text` et `time_to_first_audio` par tour ;
- `livekit_barge_in_audio_reset` puis `barge_in` quand l'expert coupe l'IA.

Rollback si LiveKit bloque l'atelier :

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD=$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' env/agentium.vm.env | cut -d= -f2-)
# LIVEKIT_ENABLED=false dans docker/env/agentium.vm.env ou transport workspace=backend_ws.
docker compose -f compose.agentium.yml up -d agentium-backend agentium-frontend
docker compose -f compose.agentium.yml --profile realtime stop agentium-livekit-agent agentium-livekit
```

Ce rollback ne touche pas `agentium-sftp`, ne lance pas `--profile infra` et
ramene Knowledge Capture sur le WebSocket backend historique.

## 12. Phasage propose

### Phase 0 - Spike local verifiable

Objectif : prouver que le frontend rejoint une room LiveKit et recoit des data
events Agentium.

Travaux :

- ajouter config/env `LIVEKIT_*` ;
- ajouter `agentium-livekit` en compose profile `realtime` ;
- ajouter endpoints `/api/v1/livekit/config`, `/rooms`, `/token` ;
- ajouter `LiveKitConversationService` frontend ;
- test local avec un agent mock qui envoie `text.partial` et `runtime.metric`
  sur data channel.

Definition de sortie :

- room creee depuis Agentium ;
- token JWT scoping workspace/session ;
- participant navigateur rejoint ;
- data event `agentium.voice.event` affiche dans UI ou logs ;
- fallback backend WS intact.

### Phase 1 - Conversation Capture LiveKit

Objectif : remplacer le transport audio base64 par LiveKit pour Knowledge
Capture conversation-only.

Travaux :

- agent sidecar rejoint la room ;
- agent souscrit au micro utilisateur ;
- agent envoie audio vers provider STT ou gateway interne ;
- agent renvoie `text.partial`, `text.final`, `conversation.step`,
  `oracle.delta`, `runtime.metric` via data channel ;
- TTS sort comme audio track LiveKit ou fallback `audio.out` si necessaire.

Definition de sortie :

- une capture libre peut produire transcript + conversation.step via LiveKit ;
- les tests existants du gateway backend WS restent verts ;
- un test e2e mock LiveKit couvre join -> partial -> final -> stop.

Etat validation P1 hors Docker : `livekit-agent/src/agent.test.mjs` contient un
test de pont complet mocke. Il lance le sidecar avec une room LiveKit factice et
un WebSocket gateway factice, observe une track audio, envoie un
`audio.endpoint`, verifie le flush PCM -> WAV vers `VoiceSessionGateway`, puis
controle le relais data-channel de `text.partial`, `text.final` et
`conversation.step` jusqu'a la fermeture `session.close`.

### Phase 2 - Barge-in, audit et production VM

Objectif : rendre la conversation utilisable en atelier expert.

Travaux :

- barge-in detecte et audite ;
- webhooks LiveKit valides et persistants ;
- metrics session : connect time, first text, final text, first audio, fallback ;
- Nginx + firewall + health checks ;
- observabilite et runbook.

Definition de sortie :

- interruption audio sans perte du tour : couverte par le defer stop UI, le
  flush `audio.endpoint` avant fermeture et le reset audio `barge_in` audite ;
- session metrics visibles : dispatch, join, first text/audio, fallback et
  barge-in publies en `runtime.metric` ;
- deploiement VM avec SFTP intact : documente dans `docs/dev-deploy-policy.md` ;
- rollback vers backend WS documente.

### Phase 3 - Agents natifs et scale

Objectif : industrialiser si LiveKit devient le transport principal.

Travaux :

- adopter protocole LiveKit Agents pour dispatcher les workers ;
- Redis LiveKit pour multi-node ;
- TURN/TLS robuste ;
- egress/recording seulement si gouvernance audio l'autorise ;
- table `conversation_sessions` si besoin multi-surface.

Etat implementation P3 guardrails :

- `agentium-livekit-redis` existe sous profil separe `realtime-scale`. Il n'est
  jamais lance par la procedure applicative standard.
- Le serveur LiveKit injecte un bloc `redis:` dans son YAML uniquement si
  `LIVEKIT_REDIS_ADDRESS` est present. Adresse vide = single-node.
- `/api/v1/livekit/config` expose un statut non secret :
  `scale.mode`, `scale.redis_configured`, `turn.mode`, `agents.mode` et
  `governance`.
- `LIVEKIT_EGRESS_ENABLED=false` et
  `LIVEKIT_RECORDING_ALLOWED_WORKSPACE_SLUGS=` restent les valeurs par defaut ;
  il n'y a pas de retention audio brute par defaut.

Reference LiveKit : le mode distribue requiert Redis comme store partage et bus
de messages ; sans bloc `redis:`, LiveKit reste en single-node.

Decision Agents natifs :

- garder `agents.mode=sidecar_http_bridge` tant que Knowledge Capture est le
  seul flux voix critique ;
- passer a `native_agents_planned` seulement si l'on a besoin de dispatcher
  plusieurs workers backend, d'autoscaling ou d'une queue LiveKit Agents native ;
- ne pas cherry-pick le repo serveur Go LiveKit : l'integration reste
  service Docker + SDKs.

Definition de sortie P3 readiness :

- compose valide en `--profile realtime` sans Redis ;
- compose valide en `--profile realtime --profile realtime-scale` avec Redis ;
- `public_config()['scale']` indique le mode attendu sans exposer l'adresse ou
  le secret Redis ;
- aucune activation egress/recording sans workspace allowlist explicite ;
- `agentium-sftp` reste hors scope du deploiement realtime.

## 13. Tests et gates

Backend :

- unit token JWT : room exacte, permissions minimales, TTL ;
- unit webhook signature ;
- unit room metadata serialization ;
- unit event mapper `VoiceSessionEvent <-> DataPacket_User`;
- integration mock LiveKit client si possible.

Frontend :

- service LiveKit : token fetch, connect, data event parse, disconnect ;
- Knowledge Capture : fallback backend WS si LiveKit disabled ;
- UI stop/pause/barge-in ne laisse pas micro actif.

Runtime :

- health `agentium-livekit`;
- agent reconnect room ;
- no raw audio retention by default ;
- metrics emitted for every turn.
- sidecar Node tests: URL du gateway interne, routage topics, conversion PCM
  LiveKit -> WAV 16-bit, decoding WebSocket payloads et healthcheck HTTP
  testable sans importer le runtime RTC LiveKit. Le contrat `/dispatch` invalide
  est teste pour verifier une erreur structuree sans creation de session, et un
  echec `room.connect()` LiveKit nettoie la session en attente. Le flush audio
  nominal est teste : buffer PCM -> `audio.frame` WAV
  `incremental_transcription=false` -> `audio.endpoint`.

Deploy :

- `agentium-backend` healthy ;
- `agentium-frontend` healthy ;
- `agentium-livekit` reachable ;
- `agentium-livekit-agent` running ;
- `agentium-sftp` unchanged.

## 14. Risques

| Risque | Mitigation |
| --- | --- |
| UDP/firewall WebRTC bloque | fallback backend WS + TURN/TCP planifie |
| Complexite agent sidecar | P0 data-only mock avant audio |
| Latence STT toujours provider-bound | garder oracle partial + mesurer chaque phase |
| Perte de gouvernance si audio natif prend le dessus | transcript final Agentium reste source de verite |
| Secrets LiveKit exposes | backend seul genere tokens, TTL court, room scoped |
| Derive vs repo LiveKit local | pas de fork P0, image/version pinnee |

## 15. Etat courant et prochaine validation

Etat courant implemente :

1. Settings backend `LIVEKIT_*`.
2. Service backend `livekit_service.py` pour room, token, webhooks, sidecar et
   bridge interne vers `VoiceSessionGateway`.
3. Endpoints `/api/v1/livekit/*`.
4. Compose `agentium-livekit` + `agentium-livekit-agent` en profil `realtime`.
5. `LiveKitConversationService` Angular avec micro LiveKit, data-channel et
   fallback WebSocket.
6. Sidecar Node `agentium-livekit-agent` avec buffer PCM, flush WAV a
   l'endpoint et relai gateway.
7. Tests unitaires service, API, frontend TypeScript et sidecar Node.

Validation restante avant de dire que le plan est termine :

- builder les images Docker avec le daemon disponible ;
- lancer `--profile realtime` sans toucher `agentium-sftp` ;
- tester le parcours Knowledge Capture dans le navigateur avec LiveKit actif ;
- confirmer que `audio_bridge=voice_gateway_ready`, puis qu'un endpoint vocal
  produit transcript + `conversation.step` via le gateway Agentium.
