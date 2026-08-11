# Assistant engine — frozen contracts

The conversational assistant engine lives in `backend/app/services/assistant/`. It is a
tool-calling turn loop shared by every surface: the text UI calls it over HTTP, the LiveKit
voice gateway calls it in-process. It contains **no reference to any tenant**; a workspace
configures it through `workspace.settings.assistant`.

This document freezes the two contracts other surfaces build against. Both are covered by
tests: `backend/app/tests/api/test_assistant_turns_api.py` pins the HTTP shape,
`backend/app/tests/services/test_assistant_engine.py` pins the internal one.

- [1. HTTP contract](#1-http-contract--post-apiv1assistantturns)
- [2. Internal call contract](#2-internal-call-contract--voice-and-any-in-process-surface)
- [3. Voice event names](#3-voice-event-names)
- [4. Workspace configuration](#4-workspace-configuration--workspacesettingsassistant)
- [5. Tools](#5-tools)
- [6. Authorization guarantee](#6-authorization-guarantee)

---

## 1. HTTP contract — `POST /api/v1/assistant/turns`

Authenticated and workspace-scoped through the standard dependencies
(`get_current_user`, `get_current_workspace`), exactly like `/api/v1/chat`. One request =
one assistant turn, which may internally call several tools.

### Request body

`Content-Type: application/json`. Unknown fields are **rejected** (`extra="forbid"` → 422).

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `text` | `string` | yes | The user utterance. 1–8000 chars. |
| `session_id` | `string \| null` | no | Conversation thread to continue (max 64 chars). Omit or `null` to open a new thread. |
| `surface` | `string` | no | Default `"text"`. Free-form (max 32 chars); `"voice"` additionally shapes the prompt for speech. |
| `session_context` | `object` | no | Context owned by the calling surface. Default `{}`. See below. |

`session_context` is passed to the engine verbatim. Two keys are meaningful today:

- `service_catalog`: `array<object>` — the service catalogue asset owned by the front
  (`assets/nawa/itsd-use-cases.json`). Each entry must carry a `slug` (or `id`, which is
  normalized to `slug`). It is **not** inlined in the prompt; only its size is announced,
  and the model reaches it through the `list_services` / `preview_service` tools. Capped
  at 40 entries.
- any scalar (`string`/`number`/`boolean`) key, e.g. `route_hint`: rendered into the
  system prompt as an advisory hint. This is where a client-side classifier such as
  `routeIntake` belongs — as a hint, never as a gate.

```json
{
  "text": "je n'arrive plus à me connecter, mon mot de passe ne marche pas",
  "session_id": "3f6b1c22-9d1e-4b3f-9a41-6c2f0b7a1d55",
  "surface": "text",
  "session_context": {
    "route_hint": "password_reset",
    "service_catalog": [
      { "slug": "password-reset", "title": "Réinitialisation de mot de passe", "category": "identity" },
      { "slug": "vpn-access", "title": "Accès VPN", "category": "network" }
    ]
  }
}
```

### Response `200`

The body has **exactly** these eleven keys.

| Field | Type | Notes |
| --- | --- | --- |
| `session_id` | `string` | Thread id. Authoritative: store it and send it back on the next turn. |
| `message_id` | `string` | Id of the persisted assistant message (uuid4). |
| `answer` | `string` | The text to render or speak. May be `""` only if the model returned nothing. |
| `citations` | `array<Citation>` | Deduplicated across every retrieval tool call, renumbered from 1. `[]` when no retrieval happened. |
| `tool_calls` | `array<ToolCall>` | Chronological. Empty when the model answered directly. |
| `model` | `string` | Model actually used, e.g. `"gpt-5"`. |
| `surface` | `string` | Echo of the request `surface`. |
| `tool_turns` | `integer` | Number of loop iterations that requested tools (≠ number of tool calls). |
| `finish_reason` | `string \| null` | Provider reason, or `"tool_turn_limit"` when the tool budget was exhausted. |
| `usage` | `object` | `{prompt_tokens, completion_tokens, total_tokens}`, values may be `null`. |
| `config` | `object` | `{configured: boolean, knowledge_scope: string\|null, allowed_tools: string[]}` — the effective workspace configuration, sorted. |

`Citation`:

| Field | Type |
| --- | --- |
| `index` | `integer` (1-based) |
| `id` | `string \| null` (chunk id) |
| `title` | `string` |
| `filename` | `string` |
| `document_id` | `string \| null` |
| `collection` | `string \| null` |
| `page` | `integer \| string \| null` |

`ToolCall` — **exactly** these seven keys:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `string` | Provider tool-call id. |
| `name` | `string` | Tool name, e.g. `"search_knowledge"`. |
| `arguments` | `object` | Parsed arguments; `{}` when the model emitted invalid JSON. |
| `ok` | `boolean` | Whether the tool succeeded. |
| `error` | `string \| null` | Stable error code when `ok` is `false`, `null` otherwise. |
| `result` | `object` | Full tool result (see §5). Always contains `ok`. |
| `duration_ms` | `integer` | Wall-clock duration of the tool. |

```json
{
  "session_id": "3f6b1c22-9d1e-4b3f-9a41-6c2f0b7a1d55",
  "message_id": "b0a4e1de-6c8f-4a2b-9d0e-53f1c9a7b234",
  "answer": "Je peux lancer la réinitialisation de votre mot de passe. Confirmez-vous ?",
  "citations": [
    {
      "index": 1,
      "id": "chunk-9",
      "title": "itsd-password-reset.md",
      "filename": "itsd-password-reset.md",
      "document_id": "doc-9",
      "collection": "itsd-knowledge",
      "page": 2
    }
  ],
  "tool_calls": [
    {
      "id": "call_a1",
      "name": "search_knowledge",
      "arguments": { "query": "réinitialisation mot de passe" },
      "ok": true,
      "error": null,
      "result": {
        "ok": true,
        "query": "réinitialisation mot de passe",
        "knowledge_scope": "itsd",
        "collections": ["itsd-knowledge"],
        "passages": [
          {
            "index": 1,
            "snippet": "Pour réinitialiser un mot de passe, ouvrez un ticket ITSD…",
            "score": 0.81,
            "citation": { "index": 1, "id": "chunk-9", "title": "itsd-password-reset.md", "filename": "itsd-password-reset.md", "document_id": "doc-9", "collection": "itsd-knowledge", "page": 2 }
          }
        ],
        "citations": [{ "index": 1, "id": "chunk-9", "title": "itsd-password-reset.md", "filename": "itsd-password-reset.md", "document_id": "doc-9", "collection": "itsd-knowledge", "page": 2 }]
      },
      "duration_ms": 412
    }
  ],
  "model": "gpt-5",
  "surface": "text",
  "tool_turns": 1,
  "finish_reason": "stop",
  "usage": { "prompt_tokens": 1841, "completion_tokens": 96, "total_tokens": 1937 },
  "config": {
    "configured": true,
    "knowledge_scope": "itsd",
    "allowed_tools": ["get_run_status", "list_services", "list_systems", "preview_service", "search_knowledge"]
  }
}
```

### Error responses

Every engine error returns `{"detail": {"code": <string>, "message": <string>}}` with a
**stable** `code`. A tool refusal is *not* an error: it comes back `200` inside
`tool_calls[].result`, because the conversation must survive it.

| Status | `detail.code` | When |
| --- | --- | --- |
| 400 | `assistant_input_invalid` | `text` empty after trimming (guards the internal contract; the HTTP layer normally catches it as 422 first). |
| 404 | `assistant_session_not_found` | `session_id` unknown, archived, or owned by another workspace/user. |
| 422 | *(FastAPI validation body)* | Missing/empty `text`, unknown field, oversized value. |
| 502 | `assistant_model_failed` | The provider call raised (timeout, 5xx, quota). |
| 503 | `assistant_unavailable` | The configured provider does not support tool calling, or its credentials are missing. |

---

## 2. Internal call contract — voice and any in-process surface

The voice path **must not** go through HTTP. It calls one coroutine.

```python
from app.services.assistant import answer_assistant_turn

result = await answer_assistant_turn(
    db,                                  # sqlalchemy Session (positional)
    user=user,                           # app.models.user.User
    workspace=workspace,                 # app.models.workspace.Workspace
    text="je n'arrive plus à me connecter",
    session_id=None,                     # str | None
    external_session_ref=state.session_id,  # str | None
    surface="voice",                     # SURFACE_TEXT | SURFACE_VOICE | any str
    session_context={"route_hint": "password_reset"},  # Mapping | None
)
```

Signature, verbatim:

```python
async def answer_assistant_turn(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    text: str,
    session_id: str | None = None,
    external_session_ref: str | None = None,
    surface: str = SURFACE_TEXT,
    session_context: Mapping[str, Any] | None = None,
) -> AssistantTurnResult
```

`SURFACE_TEXT == "text"` and `SURFACE_VOICE == "voice"` are exported from
`app.services.assistant`.

### Session thread resolution — three rules

1. `session_id` given → must resolve to an **active** thread of this workspace *and* this
   user, otherwise `AssistantSessionNotFoundError`.
2. `session_id` omitted and `external_session_ref` given → reuses the thread previously
   opened for that reference, creating it on first use. This exists for voice: pass the
   LiveKit/voice session id and you get one continuous conversation without adding a field
   to `VoiceSessionState`. (Implementation: stored in `sessions.context_signature` as
   `assistant:<ref>`, which cannot collide with the classic chat signature hash.)
3. Neither given → a brand new thread. The engine never glues a turn onto an unrelated
   thread; it does not use, and does not touch, `chat._ensure_chat_session`.

Either way, `result.session_id` is authoritative.

### Return value

`AssistantTurnResult` (dataclass) with these attributes:

| Attribute | Type |
| --- | --- |
| `session_id` | `str` |
| `message_id` | `str` |
| `answer` | `str` |
| `citations` | `list[dict]` (the `Citation` shape of §1) |
| `tool_calls` | `list[ToolCallRecord]` |
| `model` | `str` |
| `surface` | `str` |
| `tool_turns` | `int` |
| `finish_reason` | `str \| None` |
| `usage` | `dict` |
| `config` | `dict` |

`ToolCallRecord` is a dataclass with `id`, `name`, `arguments`, `ok`, `error`, `result`,
`duration_ms` and `as_payload()`.

`result.as_payload()` returns **exactly the JSON body of §1** — so the voice gateway emits
the same object the HTTP surface serves, and the front can share one renderer:

```python
await self._send_framed(websocket, state, "assistant.answer", result.as_payload())
```

Verbatim, but framed: the payload is larger than one LiveKit data packet, so it leaves in
ordered slices the frontend rejoins before any surface sees it (§3.0).

### Exceptions

All inherit `AssistantEngineError` and carry `.code` and `.status_code`, so a surface
translates without re-deriving a mapping.

| Class | `code` | `status_code` |
| --- | --- | --- |
| `AssistantInputInvalidError` | `assistant_input_invalid` | 400 |
| `AssistantSessionNotFoundError` | `assistant_session_not_found` | 404 |
| `AssistantModelFailedError` | `assistant_model_failed` | 502 |
| `AssistantUnavailableError` | `assistant_unavailable` | 503 |

A tool refusal never raises; it lands in `result.tool_calls[].result` with `ok: false`.

### Side effects the caller must expect

- The turn persists a `user` and an `assistant` `Message` row on the thread and commits.
  Do not persist the transcript again on top of it.
- `start_system_run` / `answer_hitl_gate` dispatch the run engine on a worker thread and
  return immediately. The turn does not wait for the run.

---

## 3. Voice event names

Per the plan, unchanged:

- **`assistant.answer`** — new event carrying `result.as_payload()` (the §1 body).
- **`audio.out`** — existing event, reused as-is for the spoken audio (already emitted by
  `_send_prompt_audio`).

No other event name is introduced by the engine. The two events below belong to the
gateway, not to the engine, and are what a voice surface must get right to reach it. Both
are covered by `backend/app/tests/services/test_voice_assistant_mode.py`.

### 3.0 Both of them travel framed

A LiveKit reliable data packet is capped at 15 KiB and the sidecar republishes every
gateway event as exactly one packet — it never splits or repackages anything. Both events
above exceed that on their own: one `list_services` result over the shipped 39-service
catalogue serializes to 13 098 bytes, and the ≤ 600 characters `_send_prompt_audio`
synthesizes are hundreds of kilobytes of base64 MP3. So they leave in **ordered frames**,
in the same shape the inbound `assistant.context` of §3.2 arrives in:

| Field | Type | Notes |
| --- | --- | --- |
| `seq` | `integer` | 0-based frame index. `0` starts a new payload and discards any partial one. |
| `total` | `integer` | Number of frames. |
| `payload_json` | `string` | This frame's slice of the payload's JSON. |

```json
{ "type": "audio.out", "payload": { "seq": 0, "total": 41, "payload_json": "{\"turn_id\":\"turn-1\",…" } }
```

Four properties, and the first two are the ones a client gets wrong:

- **A payload that would fit in one packet is framed too** (`seq: 0, total: 1`). One shape
  means rejoining is the path every answer takes, not a branch first exercised by a demo.
- **Rejoining belongs at the transport, not in a surface.** The frontend does it in
  `VoiceEventReassembler`, used by both `LiveKitConversationConnection` and
  `VoiceSessionConnection`, so a subscriber receives the whole event of §1 and no surface —
  `audio.out` is shared with Knowledge Capture — knows framing exists.
- The cut is on **UTF-8 bytes** (6 KiB of payload per frame), never on characters, and
  never inside a character. The frame is well under 15 KiB because the slice is re-escaped
  as a JSON string inside it, so a packet is larger than the payload it carries.
- A gap means the push was interrupted and the payload is dropped, exactly as inbound: both
  lanes deliver reliably and in order, so a plain append is safe and a gap is not a
  reordering to repair.

The budget is verified in bytes, not asserted on shape:
`test_voice_assistant_mode.py::test_the_answer_and_its_audio_fit_the_livekit_packet_ceiling`
weighs every packet the gateway emits for a real-size turn, and
`livekit-agent/src/agent.test.mjs` weighs what `publishData` is actually handed — a whole
`audio.out` measured over the ceiling, the framed one under it, and the frames rejoining
into the identical payload.

> The lasting fix for the audio half is a LiveKit **audio track** instead of the data
> channel. It would replace the `audio.out` event, not this framing, and it needs a
> publisher inside the sidecar container — deliberately separate work.

### 3.1 Turning the assistant on — `session.start`

The gateway routes a committed utterance to the engine when, and only when,
`state.mode == "assistant"`. That field comes from the `session.start` payload:

```json
{ "type": "session.start", "payload": { "mode": "assistant", "surface": "nawa_assistant" } }
```

`surface` isolates the room and its metadata; it is **never** read as a mode. A room opened
on the assistant surface with the default `conversation_only` mode transcribes and answers
nothing.

The mode crosses `POST /livekit/token`, `POST /livekit/sessions/{id}/agent/dispatch` and the
sidecar before it reaches the gateway, so the gateway echoes it back on
`runtime.metric` / `metric: "session_started"` as `mode`. A surface reads that echo rather
than assuming the room it asked for is the room it got.

### 3.2 Handing over the session context — `assistant.context`

The only **inbound** event of the assistant lane, and the voice equivalent of the
`session_context` field of §1: a surface pushes the context it owns — typically a service
catalogue living in a front asset the server cannot see — once, right after the room opens.
The gateway keeps it on the connection and passes it **verbatim** as `session_context` to
every `answer_assistant_turn()` of that session. The gateway reads none of it.

It is framed, because a LiveKit reliable data packet is capped at 15 KiB and a catalogue is
larger:

| Field | Type | Notes |
| --- | --- | --- |
| `seq` | `integer` | 0-based frame index. `0` starts a new push and discards any partial one. |
| `total` | `integer` | Number of frames, 1–16. |
| `context_json` | `string` | This frame's slice of `JSON.stringify(context)`. |

```json
{ "type": "assistant.context", "payload": { "seq": 0, "total": 2, "context_json": "{\"service_catalog\":[…" } }
```

A one-frame context is framed too (`seq: 0, total: 1`): one shape, one code path. Both lanes
deliver reliably and in order — LiveKit's reliable data channel, and the direct WebSocket —
so reassembly is a plain append and a gap is treated as an interrupted push.

The gateway answers on the same event name, and **never** with `session.error`: a malformed
context must not take a live call down.

| `status` | When | Other fields |
| --- | --- | --- |
| `pending` | Frame accepted, more expected | `received`, `total` |
| `ok` | Reassembled and stored | `received`, `total`, `keys`, `service_catalog` (entry count) |
| `invalid` | Push dropped | `reason`, `has_context` (whether an earlier context survives) |

`reason` is one of `context_frame_invalid`, `context_frame_out_of_order`,
`context_too_large` (more than 262 144 characters accumulated), `context_unparseable` (not
JSON, or not an object).

Two properties matter more than the shape:

- **A turn spoken before the context lands is answered anyway**, with no `session_context`.
  It is a poorer turn — `list_services` finds nothing — never a refused one.
- **The 40-entry cap stays in the engine** (`MAX_SERVICES`, §1). The gateway bounds bytes,
  not semantics, so a surface that sends more is trimmed in exactly one place. The NAWA
  front caps at the same 40 before framing.

### 3.3 A failed turn is not a lost room — `session.error`

The gateway reports a failed turn on `session.error` and **keeps the session open**: it
sends the code and returns without touching the socket, and the next utterance is answered
normally. It also reports on `session.error` the failures that did end the room. A surface
must tell the two apart, **by the code**, never by the message — which is prose, is
server-side French, and for a provider failure would name a provider.

| Recoverable — the room stays | Codes |
| --- | --- |
| The engine, on one utterance | `assistant_error`, `assistant_model_failed`, `assistant_unavailable`, `assistant_input_invalid`, `assistant_session_not_found` |
| Synthesis, after `assistant.answer` already shipped | `synthesize_failed`, `voice_provider_error`, `provider_unavailable`, `provider_not_allowed`, `provider_capability_unsupported` |
| One audio segment | `transcribe_failed`, `realtime_stt_error`, `realtime_stt_connect_failed`, `empty_audio`, `missing_audio`, `invalid_audio`, `livekit_audio_buffer_overflow` |
| One unreadable frame | `unknown_event`, `invalid_livekit_event` |

Everything else is terminal, and so is `session.close`: authentication and authorisation
(`unauthorized`, `forbidden` — the gateway closes the socket right after sending them), and
the relay between room and gateway (`livekit_voice_gateway_*`, `livekit_audio_stream_failed`,
`transport_error`). An unknown code is treated as terminal: giving up a live room costs one
reconnection, while holding a dead one makes every later press do nothing.

Treating a recoverable failure as terminal is not a cosmetic mistake. The surface stops
listening to a room that is still connected with the microphone open, so barge-in no longer
reaches the gateway and the next press opens a *second* room beside the first.

---

## 4. Workspace configuration — `workspace.settings.assistant`

The engine reads this block and nothing else. Every field is optional; unknown tool names
are dropped rather than failing the turn; out-of-range numbers are clamped.

```json
{
  "assistant": {
    "persona": "You are the NAWA IT service desk assistant…",
    "knowledge_scope": "itsd",
    "allowed_tools": [
      "search_knowledge",
      "list_systems",
      "get_run_status",
      "list_services",
      "preview_service"
    ],
    "provider": "openai",
    "model": "gpt-5",
    "max_tool_turns": 4,
    "history_turns": 12,
    "top_k": 8,
    "latency_profile": "balanced",
    "locale": "en"
  }
}
```

| Key | Type | Default | Bounds |
| --- | --- | --- | --- |
| `persona` | `string` | neutral built-in persona | ≤ 8000 chars |
| `knowledge_scope` | `string` | the workspace default Knowledge Scope | must exist in `settings.knowledge_scopes`, else falls back |
| `allowed_tools` | `string[]` | `["search_knowledge", "list_systems", "get_run_status", "list_services", "preview_service"]` | unknown names dropped; `[]` disables all tools; a non-list is treated as *not configured* |
| `provider` | `string` | `settings.default_provider` (`openai`) | `openai` only; anything else → 503 (see below) |
| `model` | `string` | `settings.default_model` (`gpt-5`) | ≤ 120 chars |
| `max_tool_turns` | `integer` | 4 | 1–8 |
| `history_turns` | `integer` | 12 | 0–50 |
| `top_k` | `integer` | 8 | 1–25 |
| `latency_profile` | `string` | `balanced` | `fast` / `balanced` / `deep` |
| `locale` | `string` | none | ≤ 12 chars; when set, the model is told to always answer in it |

**`openai` is the only provider, and `azure_openai` is refused by name.** Tool calling
exists in exactly one client here, and that client hard-codes `https://api.openai.com/v1`
and `OPENAI_API_KEY`. Accepting `azure_openai` would honour the label while calling the
public API, so it raises `assistant_unavailable` with a sentence saying that Azure is not
implemented — a 503 on the HTTP lane, a recoverable `session.error` on the voice lane. A
workspace that wants the public API says `openai`.

**The default allowlist is read-only on purpose.** `start_system_run` and
`answer_hitl_gate` require an explicit opt-in, so a workspace nobody configured can never
be driven into an execution by a model.

### 4.1 NAWA stays read-only, and the requester still gets the reset

`nawa` does **not** opt in. Both mutating tools stay off its allowlist, so the model
neither starts a run nor answers an approval gate. The reason is not that the tools are
unsafe in themselves — they cross the same authorization as the HTTP routes — but that this
deployment's IAM runs in observation mode, where the run authorization returns "allowed"
whatever it is asked. In that configuration the allowlist is the only thing between a
sentence and an execution, and a sentence is attacker-controlled input.

Read-only must not become "nothing can be done from here", which would be a regression on
the scripted assistant that reset a password from the conversation. So the execution moved
one step out, onto the person:

1. the turn recognises the service — `preview_service` returning a `live` entry with a
   route, or the `route_hint` naming one — and the front marks the turn as executable
   (`EngineTurn.action`, `frontend-ng/src/app/features/nawa/nawa-engine.ts`);
2. the screen offers the launch the service desk surface already uses:
   `NawaItsdService.launchTyped`, with the case built from the System's own prompt
   templates, `expected_flow_sha256` pinned, the run trace and the supervisor gate
   unchanged. **A person presses it.** There is no second execution path;
3. the two identity proofs are typed in the box attached to that button, not into the
   conversation. On the typed lane they never reach the engine at all. Spoken, the gateway
   has already transcribed the utterance by the time the surface sees it, so on that lane
   the proofs do pass through the engine; the surface still fills the box from what was
   heard, so the press is the same, and `redactSecrets` keeps the code off the screen.

The persona has to describe exactly that, or the answer and the screen contradict each
other. The reference NAWA configuration is `knowledge_scope: "itsd"` over the
`itsd-knowledge` collection, `locale: "en"` — the library, the catalogue and the surface
are all English, and a locale the library does not speak produces answers whose own
citations disagree with them — the five read-only tools above, and this persona:

> You are the NAWA IT service desk assistant. You serve the person who is asking, in
> English, in plain words, and you never name the software you run on.
>
> For a question about the rules, search the published library and answer from what it
> says, with the passage cited. If nothing supports an answer, say so and say what is
> missing — never fill the gap yourself.
>
> For a request, use the service catalogue. Say which service it belongs to and what the
> desk's own procedure is for it. For a service that is not yet automated here, be clear
> that the desk carries it out by hand today.
>
> One service runs in this workspace: Password Reset. You do not start it — you cannot, and
> you must not claim otherwise. What you do is prepare it: confirm it can be run here, say
> that identity is verified against the HR record and the registered authenticator before
> any password changes, and tell the requester that a button on screen starts it when they
> press it, with a box next to it for their staff number and current 6-digit code. Never
> repeat a code back, and never say a request has been sent, started or completed — the
> screen reports the run, from the run.
>
> You never invent a service, a document, a ticket, an identifier or a person. When a tool
> returns nothing usable, say that plainly and ask for what is missing.

---

## 5. Tools

All results are `{"ok": true, …}` or
`{"ok": false, "error": "<stable_code>", "message": "<human sentence>", …}`.

| Tool | Mutating | Authorization crossed | Arguments |
| --- | --- | --- | --- |
| `search_knowledge` | no | workspace-scoped retrieval | `query` *(required)*, `top_k` |
| `list_systems` | no | `system.read` | — |
| `get_run_status` | no | `run.read` | `run_id` *(required)* |
| `start_system_run` | **yes** | `system.engine.run` via `enforce_system_engine_run` | `system_id` *(required)*, `input`, `expected_flow_sha256` |
| `answer_hitl_gate` | **yes** | `system.engine.run` **and** `run.approve` | `run_id` *(required)*, `decision` (`accept`\|`reject`, required), `note` |
| `list_services` | no | session context only | `query` |
| `preview_service` | no | session context only | `slug` *(required)* |

Result payloads (success):

- `search_knowledge` → `query`, `knowledge_scope`, `collections`, `passages[]`
  (`index`, `snippet` ≤ 1200 chars, `score`, `citation`), `citations[]`.
- `list_systems` → `systems[]` (`system_id`, `name`, `objective`, `status`,
  `capability_id`, `runnable`, `flow_sha256`). Up to 25 rows, sorted by name.
  `flow_sha256` is `null` and `runnable` is `false` when the System has no published Flow.
- `get_run_status` → `run_id`, `system_id`, `status`, `trigger`, `error`, `started_at`,
  `completed_at`, `output`, `awaiting_gate` (`null`, or `{node_id, prompt, decision_id}`).
- `start_system_run` → `run_id`, `system_id`, `status`, `flow_sha256`.
- `answer_hitl_gate` → `run_id`, `decision_id`, `decision_status`, `applied`.
- `list_services` → `services[]` (`slug`, `title`, `category`, `summary`).
- `preview_service` → `service` (the full catalogue entry).

`expected_flow_sha256` mirrors `POST /systems/{id}/runs`: the digest the model read from
`list_systems`. When omitted, the engine resolves the currently published digest itself and
`create_published_ingress_run` revalidates it under its own row lock — so the precondition
is never simply skipped.

Stable error codes: `query_required`, `run_id_required`, `system_id_required`,
`slug_required`, `decision_invalid`, `run_not_found`, `system_not_found`,
`service_not_found`, `run_forbidden`, `run_rejected`, `flow_not_publishable`,
`flow_publication_required`, `gate_not_pending`, `gate_corrupt`,
`gate_system_unavailable`, `gate_forbidden`, `gate_requires_admin`,
`gate_plane_unsupported`, `gate_decision_missing`, `gate_transition_invalid`,
`tool_not_available`, `tool_forbidden`, `tool_failed`, `arguments_unparseable`.

---

## 6. Authorization guarantee

A model that can start a Run is an escalation surface, so the guarantee is structural, not
a convention. The first line of it is the allowlist of §4 — `nawa` does not opt in, so on
that workspace no sentence reaches either mutating tool at all. What follows is what holds
for a workspace that does:

- Every tool crosses **the same authorization as its HTTP endpoint**, with the identity of
  the authenticated caller. There is no privileged path.
- `start_system_run` and `answer_hitl_gate` call
  `app.services.system_engine_authorization.enforce_system_engine_run` — the canonical
  non-HTTP execution boundary, the same one the agentic chat adapter uses — with
  `source="assistant_engine"`, **before** anything reaches the run engine.
- `app/services/assistant/tools.py` must not import `app.api`. Delegating to an endpoint
  would move the boundary out of reach of the analysis below.
- `backend/app/tests/services/test_assistant_authorization_inventory.py` parses the tool
  module as an AST, follows intra-module calls transitively, and **fails** if any tool can
  reach a run engine entrypoint (`schedule_run`, `resume_run_dag`,
  `create_published_ingress_run`, `accept_decision`, `reject_decision`, …) without calling
  `enforce_system_engine_run` first, or if the boundary is crossed after it. The checker
  is itself exercised against deliberately violating sources, and the `mutating` flag of
  each registered tool is asserted to match what the code actually reaches.

Known, deliberate limitations of `answer_hitl_gate`: it drives only the ordinary
in-process gate. A delegated subflow or durable Celery gate carries deadline and lease
semantics owned by the operator console, so the tool refuses with
`gate_plane_unsupported` instead of half-implementing them. Likewise `start_system_run`
refuses with `flow_publication_required` on a workspace that opted out of Flow publication.
Both are fail-closed refusals, never a widened boundary.
