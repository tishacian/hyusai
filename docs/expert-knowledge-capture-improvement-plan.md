# Expert Knowledge Capture — improvement plan

<!-- markdownlint-disable MD013 -->

Plan d'amélioration conséquent du MVP `Expert Knowledge Capture`, centré sur la
traçabilité de la captation vocale, la transcription proche du live, les
amendements HITL, la robustesse STT/TTS et la gestion des interruptions pendant
que l'IA parle.

Document source MVP : `docs/expert-knowledge-capture.md`.

## Objectif

Faire évoluer la Phase 0 actuelle :

```text
plan déterministe -> réponse expert texte/audio -> évaluation -> proposition reviewée
```

vers une boucle de captation auditée :

```text
session vocale live-ish
  -> segments audio horodatés
  -> transcription incrémentale
  -> amendements humains versionnés
  -> interruptions/barges-in comprises
  -> synthèse structurée
  -> proposition de connaissance avec preuves et corrections
  -> revue humaine
  -> ingestion contrôlée
```

Le principe produit : **la transcription n'est pas une vérité brute**. C'est un
artefact de travail amendable, traçable et relié à la proposition finale.

## Problèmes à résoudre

1. **Traçabilité insuffisante de la captation**
   - Aujourd'hui, le transcript est stocké comme liste JSON simple.
   - On ne distingue pas clairement audio source, texte STT, correction humaine,
     relance IA, interruption et version finale.

2. **Transcription trop batch**
   - `MediaRecorder` envoie un blob après stop.
   - Pour une session réelle, l'opérateur doit voir apparaître le texte pendant
     l'entretien, avec un délai faible.

3. **HITL transcript non formalisé**
   - La revue porte sur la proposition finale, pas sur chaque segment de
     transcription.
   - Une correction humaine doit être historisée et utilisée par le raisonnement
     aval.

4. **TTS non pilotable finement**
   - Le TTS peut parler trop longtemps.
   - L'utilisateur doit pouvoir interrompre l'IA, compléter, corriger, puis
     reprendre sans perdre le contexte.

5. **Interruption non comprise sémantiquement**
   - Si l'expert coupe l'IA, le système doit savoir si c'est :
     - une correction du transcript ;
     - un complément de réponse ;
     - un rejet de la relance ;
     - une demande de reformulation ;
     - un changement de sujet.

## Architecture cible

```text
Frontend capture session
  | audio chunks + control events
  v
Voice Session API
  | creates capture_event rows
  | stores audio chunks in storage
  v
STT runtime
  | partial/final transcript segments
  v
Transcript ledger
  | raw text
  | amended text
  | confidence
  | speaker
  | timestamps
  | provenance
  v
Knowledge Capture Engine
  | interprets expert turns + interruptions
  | evaluates sufficiency
  | emits next prompt / correction request
  v
TTS runtime
  | cancellable speech segments
  | barge-in aware
  v
Proposal builder
  | uses amended transcript as source of truth
  | preserves raw STT as evidence
```

## Data model improvements

### 1. `expert_capture_events`

Ajouter une table événementielle append-only.

Champs proposés :

```text
id
workspace_id
session_id
event_type
speaker
sequence
question_id
audio_ref
text_raw
text_amended
confidence
language
source
status
parent_event_id
metadata
started_at
ended_at
created_at
created_by
```

`event_type` :

- `audio_chunk_received`
- `stt_partial`
- `stt_final`
- `transcript_amended`
- `expert_turn_finalized`
- `ai_prompt_started`
- `ai_prompt_interrupted`
- `ai_prompt_completed`
- `barge_in_detected`
- `correction_interpreted`
- `proposal_generated`
- `proposal_reviewed`

`source` :

- `voice_stt`
- `operator_edit`
- `expert_live`
- `system_tts`
- `capture_engine`

### 2. Transcript segment state

Ajouter un état par segment :

- `draft`: reçu en STT partiel.
- `final_stt`: STT finalisé mais pas validé.
- `amended`: corrigé par l'humain.
- `accepted`: validé pour synthèse.
- `excluded`: ignoré explicitement.

La synthèse finale doit utiliser :

```text
text_amended if present else text_raw
```

et garder la provenance :

```json
{
  "source_event_id": "...",
  "raw_text": "...",
  "amended_text": "...",
  "amended_by": "...",
  "amended_at": "..."
}
```

### 3. Relation avec `ExpertCaptureSession`

Garder les champs JSON actuels pour compatibilité et démo rapide, mais les
considérer comme vues matérialisées :

- `transcript`: snapshot lisible.
- `evaluations`: résultats des tours.
- `captured_facts`: faits extraits depuis les segments acceptés.

La source de vérité devient `expert_capture_events`.

## API improvements

### Session voice lifecycle

Ajouter :

```http
POST /api/v1/knowledge-capture/sessions/{id}/voice/start
POST /api/v1/knowledge-capture/sessions/{id}/voice/chunks
POST /api/v1/knowledge-capture/sessions/{id}/voice/stop
GET  /api/v1/knowledge-capture/sessions/{id}/events
GET  /api/v1/knowledge-capture/sessions/{id}/events/stream
```

`voice/chunks` accepte :

- audio chunk;
- sequence number;
- client timestamp;
- active question id;
- optional `interrupting_event_id` si l'expert parle pendant le TTS.

### Transcript HITL

Ajouter :

```http
PATCH /api/v1/knowledge-capture/sessions/{id}/events/{event_id}/amend
POST  /api/v1/knowledge-capture/sessions/{id}/turns/finalize
POST  /api/v1/knowledge-capture/sessions/{id}/transcript/accept
POST  /api/v1/knowledge-capture/sessions/{id}/transcript/exclude
```

Exemple `amend` :

```json
{
  "text_amended": "Le symptôme apparaît surtout après changement de rouleau.",
  "reason": "STT misunderstood technical phrase",
  "actor": "operator@datategy.local"
}
```

### TTS control

Ajouter :

```http
POST /api/v1/knowledge-capture/sessions/{id}/tts/speak
POST /api/v1/knowledge-capture/sessions/{id}/tts/stop
POST /api/v1/knowledge-capture/sessions/{id}/interruptions
```

`interruptions` :

```json
{
  "interrupted_event_id": "ai_prompt_event_id",
  "audio_event_id": "expert_audio_event_id",
  "transcript": "Non, je veux corriger ce point...",
  "mode": "auto"
}
```

Réponse :

```json
{
  "interpretation": "correction",
  "target_event_id": "previous_expert_turn",
  "patch": {
    "operation": "append_correction",
    "text": "..."
  },
  "next_prompt": "Merci, je corrige. Pouvez-vous préciser la condition ?"
}
```

## Frontend improvements

### Capture console

Remplacer l'UI actuelle simple par une console en 4 zones :

1. **Plan d'entretien**
   - question active;
   - gaps ciblés;
   - statut de couverture.

2. **Live transcript**
   - segments partiels en gris;
   - segments final STT;
   - segments amendés;
   - badges `raw`, `amended`, `accepted`, `excluded`;
   - timestamps et speaker.

3. **Voice controls**
   - `Record`;
   - `Pause`;
   - `Stop`;
   - `Interrupt AI`;
   - `Resume prompt`;
   - niveau micro;
   - état STT/TTS.

4. **Synthesis panel**
   - faits capturés;
   - questions ouvertes;
   - contradictions;
   - proposition markdown;
   - diff raw vs amended.

### Transcription proche du live

Implémentation pragmatique :

- `MediaRecorder.start(timeslice=1000)` pour envoyer un chunk toutes les 1s.
- Afficher immédiatement un segment `audio_chunk_received`.
- Envoyer les chunks au backend.
- Le backend renvoie des events `stt_partial` ou `stt_final`.
- Le frontend met à jour le transcript sans attendre la fin de session.

Fallback :

- Si STT streaming indisponible, faire du chunked batch toutes les 3-5s.
- Marquer l'état comme `near-live`, pas `realtime`.

### Amendement HITL

UX attendue :

- clic sur un segment;
- édition inline;
- bouton `Apply correction`;
- affichage du diff;
- l'ancienne version reste visible dans un panneau `Evidence`.

Actions rapides :

- `Mark as correction`;
- `Append to previous answer`;
- `Split segment`;
- `Merge with previous`;
- `Exclude from synthesis`;
- `Accept segment`.

### Barge-in / interruption

Pendant que l'IA parle :

- bouton visible `Interrupt`;
- appui clavier possible (`Space` ou bouton micro);
- arrêt immédiat de l'audio côté navigateur;
- envoi d'un event `ai_prompt_interrupted`;
- démarrage d'un enregistrement expert;
- à réception de la transcription, le système interprète l'intention.

Modes d'interruption proposés :

- `Correction`: corrige ce que l'expert a dit avant.
- `Complement`: ajoute un détail.
- `Reject prompt`: l'expert conteste la relance.
- `Ask clarification`: l'expert demande une reformulation.
- `Change topic`: bascule vers une autre question/gap.

Le mode peut être auto-détecté puis amendé par l'opérateur.

## Backend voice robustness

### STT

Robustesse attendue :

- accepter `webm`, `mp3`, `wav`, `m4a`;
- conserver `content_type`, `duration_ms`, `bytes`;
- retry contrôlé sur erreur réseau/transient;
- fallback `gpt-4o-mini-transcribe` -> `whisper-1`;
- validation taille/durée;
- message explicite si clé OpenAI absente.

Ajouter :

- `audio_ref` persistant vers storage;
- `stt_model`;
- `stt_latency_ms`;
- `stt_confidence` si disponible;
- `stt_error` structuré.

### TTS

Robustesse attendue :

- découper les prompts IA en segments courts;
- permettre stop entre deux segments;
- ne pas lancer un prompt TTS de 4096 caractères en un bloc;
- fallback modèle TTS;
- journaliser chaque segment parlé.

Ajouter un `TtsPlaybackPlan` :

```json
{
  "prompt_event_id": "...",
  "segments": [
    {"id": "seg-1", "text": "...", "status": "queued"},
    {"id": "seg-2", "text": "...", "status": "queued"}
  ]
}
```

Le frontend lit segment par segment. Une interruption stoppe le plan restant.

## Interruption interpretation engine

Ajouter un service :

```text
backend/app/services/knowledge_capture/interruption.py
```

Entrées :

- question active;
- dernier prompt IA;
- dernier segment expert;
- transcription de l'interruption;
- transcript amendé courant;
- gaps ouverts;
- statut couverture.

Sortie :

```json
{
  "intent": "correction | complement | reject_prompt | clarification_request | topic_shift",
  "confidence": 0.0,
  "target_event_id": "...",
  "applied_patch": {},
  "requires_human_confirmation": true,
  "next_prompt": "..."
}
```

Phase 1 :

- heuristiques déterministes;
- marqueurs de correction :
  - "non", "je corrige", "ce n'est pas", "plutôt", "en fait";
- marqueurs de complément :
  - "j'ajoute", "aussi", "en plus", "autre point";
- marqueurs clarification :
  - "répète", "reformule", "je n'ai pas compris".

Phase 2 :

- LLM/RAG pour interprétation;
- toujours avec confirmation humaine si confidence faible ou correction d'un
  fait critique.

## Proposal and synthesis changes

La proposition finale doit inclure :

1. **Captured facts**
   - texte final;
   - source segments;
   - raw/amended provenance.

2. **Corrections applied**
   - ancienne transcription;
   - correction;
   - auteur;
   - raison.

3. **Interrupted prompts**
   - prompt IA interrompu;
   - raison interprétée;
   - suite donnée.

4. **Open questions**
   - questions non couvertes;
   - segments avec faible confiance;
   - contradictions.

5. **Audit summary**
   - nombre de segments;
   - taux d'amendement;
   - temps de parole expert / IA;
   - modèles STT/TTS utilisés;
   - erreurs/fallbacks.

## MVP milestones

### M1 — Transcript ledger

Objectif : rendre la captation auditée.

Livrables :

- table `expert_capture_events`;
- API list events;
- `append_turn` écrit aussi des events;
- proposal inclut source event ids;
- tests service.

Critère de sortie :

- une session peut être reconstruite depuis les events.

### M2 — HITL transcript amendment

Objectif : rendre la transcription amendable.

Livrables :

- endpoint `PATCH /events/{id}/amend`;
- édition inline UI;
- diff raw/amended;
- synthèse utilise `text_amended`;
- tests amendement -> proposal.

Critère de sortie :

- une correction humaine apparaît dans la proposition et remplace la version STT.

### M3 — Near-live transcription

Objectif : ne plus attendre `stop recording`.

Livrables :

- `MediaRecorder` timeslice;
- endpoint audio chunks;
- events `stt_partial` / `stt_final`;
- UI live transcript;
- fallback batch chunked.

Critère de sortie :

- l'opérateur voit le transcript évoluer pendant l'entretien.

### M4 — TTS segmented and cancellable

Objectif : arrêter proprement l'IA.

Livrables :

- découpage TTS en segments;
- event `ai_prompt_started/completed`;
- bouton stop/interrupt;
- arrêt local immédiat de l'audio;
- events persistés.

Critère de sortie :

- l'utilisateur interrompt l'IA sans casser la session.

### M5 — Barge-in interpretation

Objectif : comprendre le complément/correctif après interruption.

Livrables :

- endpoint `/interruptions`;
- service `interpret_interruption`;
- modes correction/complement/reject/clarification/topic_shift;
- UI confirmation si confidence faible;
- patch transcript/facts.

Critère de sortie :

- une interruption "non, je corrige..." modifie le bon segment ou ajoute une
  correction traçable.

### M6 — Accepted proposal -> knowledge ingestion

Objectif : boucler la valeur RAG.

Livrables :

- à `accepted`, créer un artifact markdown;
- passer par storage;
- déclencher ingestion document/knowledge;
- lier document id dans la proposition;
- recherche RAG retrouve le contenu capturé.

Critère de sortie :

- une connaissance captée oralement, amendée et acceptée devient citée dans une
  réponse RAG.

## Priorité recommandée

Ordre pragmatique :

1. M1 Transcript ledger
2. M2 HITL amendment
3. M4 TTS cancellable
4. M5 Barge-in interpretation
5. M3 Near-live transcription
6. M6 Ingestion

Raison :

- M1/M2 sécurisent la gouvernance et la valeur métier.
- M4/M5 améliorent fortement l'expérience vocale sans exiger un vrai STT
  streaming.
- M3 peut commencer en chunked near-live avant un provider realtime.
- M6 dépend de la storage layer et du choix Celery/worker.

## Tests à ajouter

Backend :

- create session -> events are written.
- amend segment -> proposal uses amended text.
- exclude segment -> proposal omits it.
- interrupted prompt -> interruption event persisted.
- correction interruption -> target segment patched.
- TTS plan stop -> remaining segments cancelled.
- STT failure -> event status `failed`, session still usable.

Frontend :

- live transcript renders partial and final segments.
- inline amend updates segment.
- interrupt button stops current audio.
- correction after interrupt shows confirmation.
- proposal preview includes amendments.

E2E :

- plan session;
- simulate audio chunk transcript;
- amend one segment;
- interrupt AI prompt;
- add correction;
- create proposal;
- accept;
- verify audit summary.

## Product guardrails

- Never silently overwrite raw transcript.
- Never ingest unreviewed captured knowledge.
- Always separate expert words, STT output, operator amendments and AI
  interpretation.
- If interruption confidence is low, ask for human confirmation.
- Keep voice realtime as an optimization, not as the governance foundation.

