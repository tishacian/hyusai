# Agentium Chat UI/UX, SSE, Sources et Backend

Note de navigation pour un developpeur qui doit refaire, extraire ou comprendre le chat Agentium sur la branche `demo/agentic`.

## 1. Vue mentale

Le chat Agentium est une surface transverse. Cela veut dire qu'il n'est pas seulement une page `/chat` : il existe aussi en panneau global depuis toute l'application, en plein ecran workspace, et en mode `drop-and-ask`.

```txt
Utilisateur
  |
  | ouvre chat depuis title bar / commande / route
  v
Angular UI
  ChatOverlayComponent
    -> ChatWorkspaceComponent
      -> ChatPanelComponent
        -> SseService.stream()
          POST /api/v1/chat/stream
            -> FastAPI chat.py
              -> Orchestrator
                -> OmniRAGAgent
                  -> retrieve_rag_context()
                  -> prompt LLM avec sources [1..N]
                  -> stream texte + steps + sources
```

## 2. Points d'entree frontend

### Shell global

Le chat transverse est monte dans le shell Angular :

- `frontend-ng/src/app/features/layout/shell.component.ts`

A lire autour de :

```txt
<app-command-palette>
<app-panel-host>
<app-chat-overlay>
<app-assistant-draft-drawer>
```

### Bouton chat dans la title bar

Fichier :

- `frontend-ng/src/app/features/layout/title-bar.component.ts`

Role :

- affiche l'icone `message-square`
- ouvre ou ferme le panneau chat
- utilise `ChatOverlayService`
- raccourci mental UX : le chat est toujours disponible

### Command palette

Fichier :

- `frontend-ng/src/app/features/layout/command-palette.component.ts`

Commandes chat :

```txt
chat.ask      -> mode quick
chat.system   -> mode system
chat.drop     -> mode drop
```

La palette appelle :

```ts
this.chatOverlay.open({ mode: 'quick' | 'system' | 'drop' })
```

### Service d'ouverture transverse

Fichier :

- `frontend-ng/src/app/features/chat/chat-overlay.service.ts`

Contrat UI minimal :

```ts
open({
  mode?: 'quick' | 'system' | 'drop',
  systemId?: string | null,
  contextId?: string | null,
  assistantProfile?: string | null,
  initialPrompt?: string | null,
  autoStartVoiceLoop?: boolean,
})
```

Ce service ne fait pas de backend. Il garde seulement l'etat du panneau : ouvert, mode, system/context/profile initial.

### Panneau overlay

Fichier :

- `frontend-ng/src/app/features/chat/chat-overlay.component.ts`

Role :

- monte un `ck-panel`
- insere `ChatWorkspaceComponent`
- passe `inline=true`
- permet d'ouvrir la version plein ecran `/workspace/:slug/chat`

## 3. Surface chat frontend

### ChatWorkspaceComponent

Fichier principal :

- `frontend-ng/src/app/features/chat/chat-workspace.component.ts`

Role :

- gere le layout general
- gere le selecteur de System
- gere le mode `drop-and-ask`
- gere l'upload de fichiers
- cree ou met a jour un Context ephemere
- transmet `systemId` et `contextId` au `ChatPanelComponent`

Modes :

```txt
quick
  Question workspace rapide.

system
  Conversation scopee sur un System.

drop
  Upload de fichiers, creation d'un Context temporaire,
  puis questions sourcees sur ces documents.
```

Flux drop-and-ask :

```txt
Drop files
  -> POST /api/v1/documents/upload-batch
  -> collection_name = documents
  -> createContext(ephemeral=true, ttl_hours=24)
  -> context.environment_state.collection = documents
  -> ChatPanel recoit contextId
```

### ChatPanelComponent

Fichier central :

- `frontend-ng/src/app/features/chat/chat-panel.component.ts`

C'est le composant a lire en priorite pour refaire l'UX chat. Il contient :

- types locaux `DecisionStep`, `Source`, `ChatMessage`, `AssistantProfile`, etc.
- historique des conversations
- composer
- controles RAG
- reception SSE
- rendu Markdown
- rendu citations
- panneau Sources
- deep search async
- feedback / evaluation
- voice integration

## 4. Contrats frontend utiles

Les interfaces importantes sont declarees localement dans :

- `frontend-ng/src/app/features/chat/chat-panel.component.ts`

DTO a recuperer :

```ts
interface DecisionStep {
  id: string;
  type?: string;
  title?: string;
  description?: string;
  status?: 'pending' | 'active' | 'completed' | 'warning' | 'error';
  duration?: number;
  metrics?: Record<string, unknown>;
}

interface Source {
  id?: string;
  document_id?: string;
  title?: string;
  filename?: string;
  snippet?: string;
  content?: string;
  text?: string;
  score?: number;
  collection?: string;
  collection_name?: string;
  page?: number;
  url?: string;
  metadata?: Record<string, unknown>;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  decisionSteps?: DecisionStep[];
  sources?: Source[];
  retrievalInfo?: RetrievalInfo | null;
  runId?: string | null;
}
```

Le payload envoye a `/api/v1/chat/stream` est construit dans `sendMessage`.

Champs importants :

```txt
query
ui_locale
response_language
agent_id
session_id
context_id
context_mode
stream
include_reasoning
include_sources
temperature
max_tokens
top_k
candidate_pool_k
synthesis_k
source_display_k
latency_profile
similarity_threshold
rag_pipeline_mode
rag_mode_override
prompt_type
knowledge_scope
assistant_profile
grounding_mode
system_prompt
agent_preferences.model_preferences
```

## 5. SSE frontend

Fichier :

- `frontend-ng/src/app/core/sse.service.ts`

Important : le chat n'utilise pas `EventSource`.

Raison :

```txt
EventSource
  - GET seulement
  - headers custom compliques
  - pas de body JSON

fetch streaming
  + POST possible
  + Authorization possible
  + X-Workspace-Slug possible
  + body JSON possible
```

Le service lit le flux HTTP :

```txt
fetch(url, { method: 'POST', headers, body })
  -> response.body.getReader()
  -> decode TextDecoder
  -> split frames by "\n\n"
  -> parse "data: <json>"
  -> emit SseChunk
```

Contrat `SseChunk` :

```ts
interface SseChunk {
  chunk_type?: 'text' | 'decision_step' | 'error' | 'eval_pending' | string;
  content?: string;
  decision_step?: unknown;
  sources?: unknown;
  reasoning_trace?: unknown;
  is_final?: boolean;
  run_id?: string;
  type?: 'done';
}
```

Fin du stream :

```txt
data: [DONE]
```

Le service transforme cela en :

```ts
{ type: 'done' }
```

## 6. Reception SSE dans le ChatPanel

Dans `chat-panel.component.ts`, le flux est traite ainsi :

```txt
chunk_type=session
  -> stocke chatSessionId

chunk_type=text
  -> append content dans buffer
  -> met a jour streamBuffer

chunk_type=decision_step
  -> upsert dans liveSteps

chunk_type=retrieval
  -> met a jour retrievalInfo
  -> detecte deep_queued

chunk_type=action_result
  -> dispatch events calendar/action/visual

chunk_type=map_command
  -> window.dispatchEvent('agentium:map-command')

chunk_type=action_effect
  -> AssistantEffectsService

chunk_type=eval_pending
  -> startEvalPolling(run_id)

type=done
  -> cree le message assistant final
  -> attache sources, steps, runId, retrievalInfo
```

Schema :

```txt
SSE chunks
  |
  +-- text -----------> buffer visible
  +-- decision_step --> reasoning trail
  +-- retrieval ------> chips RAG / deep status
  +-- sources --------> panneau Sources final
  +-- eval_pending ---> polling auto-eval
  +-- done -----------> commit ChatMessage
```

## 7. Backend chat

Endpoint principal :

- `backend/app/api/v1/endpoints/chat.py`

DTO backend :

```py
class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_preferences: Optional[Dict[str, Any]] = None
    stream: bool = True
    include_reasoning: bool = True
    include_sources: bool = True
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.3
    top_k: Optional[int] = None
    candidate_pool_k: Optional[int] = None
    synthesis_k: Optional[int] = None
    source_display_k: Optional[int] = None
    latency_profile: Optional[Literal["fast", "balanced", "deep"]] = None
    retrieval_profile: Optional[str] = None
    deep_retrieval: Optional[bool] = None
    retrieval_filters: Optional[Dict[str, Any]] = None
    rag_pipeline_mode: Optional[str] = None
    rag_mode_override: Optional[str] = None
    prompt_type: Optional[str] = None
    knowledge_scope: Optional[str] = None
    context_id: Optional[str] = None
    context_mode: Optional[str] = None
    assistant_profile: Optional[str] = None
    source_policy: Optional[Dict[str, Any]] = None
    grounding_mode: Optional[Literal["strict", "balanced"]] = None
    parent_message_id: Optional[str] = None
    previous_answer: Optional[str] = None
    ui_locale: Optional[Literal["fr", "en"]] = None
    response_language: Optional[Literal["fr", "en"]] = None
```

Endpoint streaming :

```py
@router.post("/stream")
async def chat_stream(...)
```

Format SSE backend :

```py
def _sse_data(payload: Any) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"

def _sse_done() -> str:
    return "data: [DONE]\n\n"
```

Pipeline backend simplifie :

```txt
chat_stream()
  -> _apply_workspace_chat_flow_defaults()
  -> _ensure_chat_session()
  -> _resolve_chat_context()
  -> _apply_context_to_chat_request()
  -> validate query
  -> canonical answer shortcut?
  -> registry/transverse action shortcut?
  -> resolve_grounding_policy()
  -> load conversation history
  -> orchestrator.process_request()
  -> yield SSE chunks
  -> persist Message assistant
  -> queue auto deep retrieval if needed
  -> persist Run
  -> yield eval_pending
  -> yield [DONE]
```

## 8. Sessions, Context et Run ledger

Session chat :

```txt
_ensure_chat_session()
  - verifie workspace_id
  - verifie user_id
  - reutilise la session recente si meme signature
  - sinon cree ChatSession
```

Context :

```txt
_apply_context_to_chat_request()
  - ajoute context_id
  - ajoute context.data_refs
  - lit environment_state.collection
  - lit environment_state.knowledge_scope
```

Run :

Chaque reponse chat reussie est persistee comme un `Run`, pas seulement comme message. C'est ce qui permet :

- observabilite
- evaluation automatique
- qualite / hallucination checks
- replay partiel
- rattachement system/capability

## 9. Orchestration

Fichier :

- `backend/app/agents/orchestrator.py`

Schema :

```txt
orchestrator.process_request()
  |
  +-- QueryRewriter
  |     -> decision_step query_rewrite active/completed
  |
  +-- Router
  |     -> selection agent(s)
  |
  +-- Agent RAG
        -> emits retrieval/text/decision_step/error
```

Agent principal :

- `backend/app/agents/procurement_agent.py`

Classe :

```py
class OmniRAGAgent(BaseAgent)
```

## 10. Profils, modes RAG et scopes

Fichier cle :

- `backend/app/services/rag/context.py`

Fonction de profile :

```py
get_retrieval_profile(request)
```

Elle transforme les champs UI/backend en politique concrete :

```txt
knowledge_scope
context_collection
context_mode
latency_profile
retrieval_profile
rag_pipeline_mode
top_k
candidate_pool_k
synthesis_k
source_display_k
retrieval_filters
```

Modes utilisateur :

```txt
auto
  Laisse workspace/scope/planner choisir.

naive
  Recherche vectorielle simple.

hybrid
  Sparse + dense.

hah
  Hierarchical Answer Harvesting.

chah
  Composite HAH.
```

Profils latence :

```txt
fast
  top_k max 8
  source_display_k max 8
  synthesis_k max 12
  candidate_pool_k max 20

balanced
  top_k max 12
  source_display_k max 24
  synthesis_k max 24
  candidate_pool_k max 80

deep
  top_k max 24
  source_display_k max 24
  synthesis_k max 48
  candidate_pool_k max 200
```

Session docs :

```txt
context_mode=replace
  -> si context_collection existe et pas de knowledge_scope,
     recherche seulement le contexte selectionne.

context_mode=combine
  -> ajoute la collection du Context aux collections du knowledge_scope.
```

## 11. Retrieval effectif

Fonction :

```py
retrieve_rag_context(request)
```

Fichier :

- `backend/app/services/rag/context.py`

Pipeline simplifie :

```txt
retrieve_rag_context()
  -> get_retrieval_profile()
  -> retrieve knowledge guides
  -> apply source_policy
  -> plan_corpus()
  -> resolve retrieval mode
  -> retrieve_for_mode()
  -> dedupe chunks/metadatas
  -> policy rerank
  -> required terms filter
  -> optional cross-encoder rerank
  -> similarity threshold
  -> diversity / MMR
  -> compression to synthesis_k
  -> append parent context
  -> prepend table/document analysis evidence
  -> prepend guide context
  -> return chunks, scores, metadatas, metrics
```

Retour attendu :

```py
{
  "chunks": list[str],
  "scores": list[float],
  "metadatas": list[dict],
  "pipeline": str,
  "label": str,
  "reason": str,
  "detail": str,
  "metrics": dict,
}
```

## 12. Citations sources

Fichier :

- `backend/app/agents/procurement_agent.py`

Principe fondamental :

```txt
Contexte LLM
  [1] Doc A
      extrait...
  [2] Doc B
      extrait...

Payload backend
  sources[0] = Doc A
  sources[1] = Doc B

Frontend
  texte "... [1]"
    -> bouton citation 1
    -> scroll vers sources[0]
```

Fonctions a reprendre :

```py
_select_citation_entries()
_source_entry_from()
_assemble_context_and_sources()
OmniRAGAgent._gate_sources()
```

Regles backend :

```txt
Knowledge Guide
  -> contexte advisory
  -> pas dans les citations numerotees

Doublons
  -> dedupe par document + locator

Synthetic analysis evidence
  -> remplace par vrai passage si disponible

source_display_k
  -> limite les sources visibles

follow-up/meta turn
  -> pas de panneau sources

model cite [n]
  -> garder la liste complete pour ne pas casser l'alignement

model ne cite rien
  -> cacher les sources sauf requete de decouverte documentaire
```

Structure source envoyee au front :

```json
{
  "id": "chunk-0",
  "type": "document",
  "title": "manual.pdf",
  "snippet": "extrait visible",
  "relevance_score": 0.82,
  "document_id": "...",
  "filename": "manual.pdf",
  "page": 4,
  "collection": "documents",
  "collection_name": "documents",
  "keywords": ["..."],
  "author": "...",
  "num_pages": 12
}
```

## 13. Rendu citation frontend

Fichier :

- `frontend-ng/src/app/features/chat/chat-panel.component.ts`

Fonctions :

```ts
renderAnswer()
renderMarkdownAnswer()
inlineMarkdownTokens()
isValidCitationForSources()
missingCitations()
citedIndices()
gotoSourceTarget()
resolveSourceReferenceIndex()
```

Le front reconnait :

```txt
[1]
[1, 2]
[1][2][3]
[filename.pdf] si resolvable vers une source
```

Rendu :

```txt
citation valide
  -> bouton bleu cliquable
  -> title avec source title + locator
  -> ouvre panneau Sources
  -> scroll + highlight

citation invalide
  -> chip gris
  -> warning "model referenced [n] but source unavailable"
```

## 14. Deep Search asynchrone

But :

```txt
Ne pas bloquer le chat rapide.
Si le retrieval rapide est insuffisant, timeout ou trop dense,
creer un job deep retrieval qui continue cote backend.
```

Backend :

- `backend/app/api/v1/endpoints/chat.py`
- endpoint `POST /chat/deep-retrieval-jobs`
- helper `_queue_auto_deep_retrieval_job()`

Frontend :

- `chat-panel.component.ts`
- detecte `chunk_type=retrieval` avec `phase=deep_queued`
- stocke `deepJobId`, `deepPollUrl`, `deepStatus`, `deepProgress`
- affiche placeholder
- poll le job
- peut promouvoir la reponse deep quand terminee

Schema :

```txt
Fast chat stream
  -> retrieval says deep_retrieval_recommended
  -> backend queues WorkspaceJob
  -> SSE chunk phase=deep_queued
  -> UI shows "Deep queued/running"
  -> frontend polls job
  -> deep answer + deep sources arrive later
```

## 15. Instructions LLM pour inference

Fichier :

- `backend/app/agents/procurement_agent.py`

Prompts a lire :

```py
SYSTEM_PROMPT
BALANCED_GROUNDING_APPENDIX
_build_rag_user_prompt()
_build_followup_user_prompt()
```

Contrat LLM principal :

```txt
Tu as acces a une knowledge base curate.
Reponds avec le contexte recupere.
Si le contexte contient des infos pertinentes, cite-les.
Si le contexte est absent ou non pertinent, dis-le clairement.
N'invente pas de sources.
Utilise les citations numeriques [number].
N'utilise pas des references brutes comme [menu.html].
Commence par une synthese concise.
Ajoute les preuves/citations utiles ensuite.
Si les preuves sont trop faibles ou contradictoires, dis-le.
```

Mode strict :

```txt
Answer using the context above.
Cite sources by their [number] when relevant.
If the context is not relevant or missing, say so clearly rather than guessing.
```

Mode balanced :

```txt
Utiliser les sources workspace en priorite.
Si aucune source n'existe et que la demande est generale/conseil/redaction,
autoriser une reponse de connaissance generale.
Mais si la question porte sur documents, chiffres, etat courant, actions,
agenda ou faits workspace, ne pas inventer.
```

Follow-up :

```txt
Si l'utilisateur dit "resume", "detaille", "plus court", etc.,
ne relance pas forcement retrieval.
Reponds a partir de la reponse precedente.
N'invente pas de nouveaux marqueurs [1].
```

## 16. Actions transverses

Certains messages chat ne partent pas au RAG. Ils resolvent une action transverse :

- agenda
- action plan
- visual intelligence
- map command
- effets UI

Fichiers :

- `backend/app/services/actions/registry.py`
- `backend/app/services/actions/executor.py`
- `backend/app/api/v1/endpoints/actions.py`

Principe :

```txt
query utilisateur
  -> resolve_action(surface="chat")
  -> action directe ou proposition
  -> chunk action_result / map_command / action_effect
  -> UI dispatch event
```

## 17. SSE Runs a ne pas confondre

Il existe une autre famille SSE pour les Runs :

- `frontend-ng/src/app/core/run-stream.service.ts`
- `backend/app/api/v1/endpoints/runs.py`
- `backend/app/services/run_engine/events.py`

Difference :

```txt
Chat SSE
  POST /api/v1/chat/stream
  data: JSON
  data: [DONE]

Run SSE
  GET /api/v1/runs/{id}/stream
  event: node_start
  data: JSON
```

Ne pas melanger les deux clients.

## 18. Ordre de lecture recommande

Pour refaire le chat sans se perdre :

```txt
1. frontend-ng/src/app/features/chat/chat-panel.component.ts
   Comprendre le contrat UI et le SSE.

2. frontend-ng/src/app/core/sse.service.ts
   Comprendre le streaming client.

3. frontend-ng/src/app/features/chat/chat-workspace.component.ts
   Comprendre quick/system/drop/context.

4. backend/app/api/v1/endpoints/chat.py
   Comprendre DTO, session, SSE, persistance.

5. backend/app/agents/orchestrator.py
   Comprendre query rewrite + routing.

6. backend/app/agents/procurement_agent.py
   Comprendre RAG, prompts, citations.

7. backend/app/services/rag/context.py
   Comprendre profiles, modes, budgets, retrieval.

8. backend/app/services/chat_grounding.py
   Comprendre strict/balanced.

9. backend/app/services/actions/registry.py
   Comprendre actions transverses.
```

## 19. Checklist de reimplementation

Pour refaire un chat compatible :

```txt
[ ] UI accepte quick/system/drop
[ ] UI sait envoyer context_id/context_mode
[ ] UI sait envoyer knowledge_scope/assistant_profile/grounding_mode
[ ] Client SSE utilise fetch streaming POST
[ ] Client parse data: JSON et data: [DONE]
[ ] UI gere text chunks incrementaux
[ ] UI gere decision_step
[ ] UI gere retrieval metadata
[ ] UI attache sources au message final
[ ] UI transforme [n] en bouton citation
[ ] UI affiche warning si citation sans source
[ ] UI affiche panneau Sources avec snippet/page/collection
[ ] Backend cree/verifie ChatSession
[ ] Backend applique Context vers retrieval
[ ] Backend resout grounding policy
[ ] Backend stream chunks text/retrieval/decision_step
[ ] Backend preserve sources[n-1] pour citation [n]
[ ] Backend persiste Message et Run
[ ] Backend renvoie eval_pending
[ ] Backend sait creer deep retrieval async
[ ] UI poll deep retrieval job
```

