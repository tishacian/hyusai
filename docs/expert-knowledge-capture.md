# Expert Knowledge Capture — documentation produit et technique

Ce document décrit **l’ensemble du livrable** « capture de connaissance experte » sur Agentium / omnirag : modèle mental, données persistées, API, skills, voix, UI, navigation, tests et évolutions prévues.

---

## 1. Objectif produit

Permettre à un workspace de :

1. **Contextualiser** une session à partir d’un **Context** (portée knowledge, ACLs, contraintes métier, références).
2. **Identifier** des **écarts de connaissance** (gaps) à clarifier avec un expert.
3. **Préparer de façon asynchrone** un **plan d’entretien** avec durée cible (ex. 20 minutes) et questions ordonnées.
4. **Mener une session guidée** avec **voix** (enregistrement → transcription → évaluation synchrone → relances / question suivante).
5. **Produire une proposition de mise à jour** de la base de connaissance, **soumise à revue humaine** avant ingestion.

L’implémentation actuelle est une **Phase 0** : logique déterministe et robuste pour démo, extensible vers LLM/RAG sans changer les contrats API principaux.

### Parcours pilote (Andritz / Eric UX)

- **Capture libre** (`plan_mode=free_conversation`) : pas de plan ni de couverture ; conversation vocale directe après préparation (titre + domaine + durée optionnelle).
- **Construire un plan** (`plan_build`) : co-construction par tours de dialogue (`POST …/plan/dialogue-turn`) puis finalisation (`POST …/plan/finalize`) — le mode `ai_plan` instantané est réservé aux rôles reviewer/admin.
- **Préparation pilote** : le contexte workspace est lié automatiquement ; pas de choix collection visible en mode démo.
- **Qualité** : backlog métier (`GET …/quality-backlog`) — imprécisions, contradictions, questions ouvertes ; action **Reporter** sans bloquer la session.
- **Clôture** : pause/reprise, export Markdown, publication Knowledge après `review_decide` + `trigger_ingestion`.

---

## 2. Modèle mental Agentium

| Concept | Rôle |
| ------- | ---- |
| **Capability** `expert_knowledge_capture` | Promesse métier : préserver le raisonnement tacite et structurer une proposition reviewable. |
| **Skills** | Primitives versionnées invoquées par le runtime ou exposées au Flow builder. |
| **Context** | Ancre la session : collections, `data_refs` / `memory_refs`, etc. |
| **System / Flow** | Peut orchestrer les mêmes skills dans un graphe (voir registre et bindings). |
| **Knowledge** | Cible finale : proposition markdown + métadonnées ; ingestion réelle après validation opérationnelle. |

La page `/knowledge/capture` matérialise ce fil : **Capability → System (runtime guidé) → Context → Knowledge (proposition reviewée)**.

---

## 3. Capability et skills (registre)

**Fichier canonique :** `backend/app/services/skills_registry/seed.py`

### 3.1 Capability

- **Slug :** `expert_knowledge_capture`
- **Skills associés :**  
  `knowledge_gap_analysis_v1`, `expert_interview_plan_v1`, `voice_transcribe_v1`, `expert_answer_evaluator_v1`, `capture_structuring_v1`, `voice_tts_v1`, `audit_log_v1`

### 3.2 Skills dédiés à la capture

| Slug | Rôle |
| ---- | ---- |
| `knowledge_gap_analysis_v1` | Produit une liste de gaps priorisés à partir de l’objectif, du profil expert et du snapshot de contexte. |
| `expert_interview_plan_v1` | Construit le plan (agenda, questions, critères de complétude, métriques de succès). |
| `expert_answer_evaluator_v1` | Évalue une réponse (score, verdict, follow-up). |
| `capture_structuring_v1` | Structure le payload de proposition (facts, questions ouvertes, markdown d’ingestion). |
| `voice_transcribe_v1` | STT (runtime voix). |
| `voice_tts_v1` | TTS (runtime voix). |
| `audit_log_v1` | Traçabilité (composante gouvernance). |

**Bindings :** `backend/app/services/skills_registry/wrappers.py` — les quatre skills « knowledge capture » pointent vers `app.services.knowledge_capture` ; la voix pointe vers `app.services.voice_runtime`.

---

## 4. Couche métier backend

**Fichier :** `backend/app/services/knowledge_capture.py`

### 4.1 Gaps (`build_knowledge_gaps`)

- Part d’un catalogue de templates (`decision_rationale`, `exception_handling`, `signals_and_symptoms`, etc.).
- Ajuste les priorités selon des mots-clés dans l’objectif / le profil / les références du contexte.
- **Phase 0 :** entièrement déterministe (pas d’appel LLM obligatoire).

### 4.2 Plan d’entretien (`build_interview_plan`)

- Dérive le nombre de questions et le temps par question à partir de `duration_minutes` et des gaps sélectionnés.
- Questions en français orientées entretien expert (exceptions, signaux, provenance, validation…).

### 4.3 Évaluation synchrone (`evaluate_expert_answer`)

- Heuristiques sur la réponse : longueur, marqueurs de raisonnement, exemple, source, incertitude, contradiction.
- **Verdicts :** `sufficient`, `partial`, `needs_precision`, `contradiction_or_update`.
- Produit un **follow-up** adapté si le verdict n’est pas `sufficient`.

### 4.4 Cycle de session

- **`create_capture_plan`** : charge le `Context` si `context_id` est fourni, calcule gaps + plan, crée `ExpertCaptureSession` en statut `planned`, enregistre un `Run` + `SkillInvocation` (plan).
- **`start_session`** : passage `planned` → `active` (optionnel côté API dédiée).
- **`append_turn`** : ajoute au transcript ; si `speaker == expert`, évalue, met à jour `captured_facts`, calcule `next_prompt` / question suivante, métriques (`coverage`, etc.), enregistre un run « turn ».
- **`create_update_proposal`** : `structure_capture_payload`, persiste `KnowledgeUpdateProposal`, marque la session `completed`, run « structuring ».
- **`review_proposal`** : `accepted` | `rejected` | `changes_requested`.

### 4.5 Traçabilité

`_record_capture_run` crée des enregistrements `Run` et `SkillInvocation` pour corréler les phases avec la capability seedée.

---

## 5. Persistance (ORM + migration)

**Modèles :** `backend/app/models/expert_capture.py`

- **`expert_capture_sessions`** : workspace, capability, context, system, run, titre, objectif, profil, durée, `voice_runtime`, statut, JSON (`plan`, `knowledge_gaps`, `transcript`, `evaluations`, `captured_facts`, `metrics`), horodatage.
- **`knowledge_update_proposals`** : lien session, statut de revue, JSON `proposal`, notes, reviewer, dates.

**Migration Alembic :** `backend/alembic/versions/021_expert_capture.py` (révision `021_expert_capture`).

Après déploiement : `alembic upgrade head` sur l’environnement cible.

---

## 6. API REST

**Préfixe :** `/api/v1/knowledge-capture`  
**Fichier :** `backend/app/api/v1/endpoints/knowledge_capture.py`  
**Enregistrement :** `backend/app/api/v1/router.py` (`include_router(..., prefix="/knowledge-capture")`)

Authentification : workspace courant via `get_current_workspace` (comme le reste de l’API métier).

| Méthode | Chemin | Description |
| ------- | ------ | ----------- |
| GET | `/voice-runtimes` | Liste des fournisseurs voix disponibles (métadonnées). |
| POST | `/plans` | Crée une session + plan (body : objectif, titre optionnel, profil, durée, `context_id`, `system_id`, `knowledge_refs`, `voice_runtime`). |
| GET | `/sessions` | Liste des sessions du workspace (`?status=`, `?limit=`). |
| GET | `/sessions/{id}` | Détail session sérialisé. |
| POST | `/sessions/{id}/start` | Démarre explicitement (active). |
| POST | `/sessions/{id}/turns` | Ajoute un tour (`speaker`, `text`, `question_id`, `audio_ref` optionnel). Réponse : session + évaluation + `next_prompt`. |
| POST | `/sessions/{id}/proposal` | Génère la proposition de mise à jour knowledge. |
| GET | `/proposals` | Liste des propositions. |
| PATCH | `/proposals/{id}/review` | Revue (`status`, `reviewer`, `review_notes`). |

### 6.1 Format de la proposition (`structure_capture_payload`)

Champs utiles dans `proposal` JSON :

- `captured_facts`, `open_questions`, `transcript`
- `recommended_ingestion` : `title`, `content` (markdown), `metadata` (`source: expert_capture_session`, `session_id`, `voice_runtime`)
- `review.required` et justification

L’ingestion automatique dans Qdrant / pipelines documentaires peut s’brancher sur ce contrat en aval de la revue.

---

## 7. Voix (Phase 0 : cascade OpenAI)

**Fichier :** `backend/app/services/voice_runtime.py`

- **`VoiceRuntimeProvider`** : interface commune `transcribe`, `create_speech`, `synthesize_bytes`.
- **`CascadeVoiceRuntime`** (`slug: cascade`) : OpenAI (`OPENAI_TRANSCRIBE_MODEL`, `OPENAI_TTS_MODEL` via env, défauts documentés dans le module).
- **`RealtimeVoiceRuntime`** : emplacement pour futur fournisseur type full-duplex / GPU (Moshi-like), sans casser les appelants.

**Endpoints HTTP voix** (chat et capture côté client) : `backend/app/api/v1/endpoints/voice.py` — s’appuient sur le provider cascade.

**Côté skills :** `voice_transcribe_v1` / `voice_tts_v1` dans `wrappers.py` délèguent au même runtime.

---

## 8. Frontend Angular

### 8.1 Route et module

- **Route :** `/knowledge/capture`  
- **Fichiers :**  
  - `frontend-ng/src/app/features/knowledge/knowledge.routes.ts`  
  - `frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts`

### 8.2 Client API

**Fichier :** `frontend-ng/src/app/core/api.service.ts`

Méthodes : `listVoiceRuntimes`, `createCapturePlan`, `listCaptureSessions`, `startCaptureSession`, `addCaptureTurn`, `createCaptureProposal`, `reviewCaptureProposal` — toutes sur le préfixe `/knowledge-capture/...`.

### 8.3 Comportement UI

- Sélection **Context** (liste `/contexts`), défaut : premier contexte avec collection ou `data_refs`, sinon premier de la liste — **aucun workspace codé en dur**.
- Query param **`?contextId=`** pour ouvrir directement sur un contexte.
- **Prepare capture plan** → affiche plan, métriques, liens navigation (Capabilities, Systems, Contexts, Knowledge).
- **Interview plan** : clic sur une question → **TTS** via `synthesizeSpeech`.
- **Expert answer** : saisie manuelle ou **MediaRecorder** → `transcribeAudio` → **Evaluate answer** → affichage verdict / next prompt / TTS auto sur la relance.
- **Create proposal** → prévisualisation markdown ; **Accept proposal** → PATCH review.

**Zoom context :** `ZoomContextService` mis à jour lors du plan et du changement de contexte pour breadcrumb / mini-rail (libellés lisibles).

### 8.4 Points d’entrée navigation

- Page Knowledge : liens « Expert capture » vers `/knowledge/capture` (`knowledge-base.component.ts`).
- **Command palette** : entrée `palette.view.expert_capture` → même route (`command-palette.component.ts`).

### 8.5 i18n

**Fichiers :** `frontend-ng/src/app/core/i18n/<domaine>.dict.ts` (les clés `capture.*` vivent dans `capture.dict.ts`), fusionnés par `frontend-ng/src/app/core/i18n.dict.ts`. Convention : `frontend-ng/src/app/core/i18n/CONVENTION.md`.

Clés notables : `nav.capture`, `nav.review`, `palette.view.expert_capture`, `palette.view.expert_capture.hint` (FR + EN, dans `chrome.dict.ts`).

**Guard :** `frontend-ng/scripts/check-i18n.mjs` + script npm `check:i18n` (parité FR/EN, couverture nav, chaînes en dur, lexique).

---

## 9. Flow builder (orchestration visuelle)

Les mêmes skills peuvent être assemblés dans un **System** (`CanonicalFlow` / Drawflow). Pour une démo complète :

- Lier chaque nœud `task` au **skill_id** ou **`skill_slug`** attendu par l’inspecteur.
- Renseigner **input/output maps** et prompts **HITL** si présents.

Des améliorations UX du Flow builder (toolbar, terminal, inspector, auto-fit, messages si skill non lié) facilitent la configuration de systèmes « Expert Knowledge Capture » sans logique Andritz spécifique dans le code.

---

## 10. Tests automatisés

**Fichier :** `backend/app/tests/services/test_knowledge_capture.py`

- Vérifie le seed et le statut **bound** des skills voix + capture.
- Scénario bout-en-bout : plan → tour expert → proposition → revue `accepted`.

Exécution typique : `cd backend && poetry run pytest app/tests/services/test_knowledge_capture.py -q`

---

## 11. Variables d’environnement et prérequis

- **OpenAI** : clé configurée côté backend pour STT/TTS cascade (`settings.openai_api_key`).
- Modèles surchargeables : `OPENAI_TRANSCRIBE_MODEL`, `OPENAI_TTS_MODEL` (voir `voice_runtime.py`).

Sans clé, la transcription / synthèse échouent avec erreur explicite côté API voix.

---

## 12. Déploiement sur la VM (après commit et push depuis la machine locale)

Ce guide décrit le flux **standard** une fois le code **commité et poussé** sur le dépôt distant : tu mets à jour la VM, les dépendances Python, les migrations, le build Angular, puis tu redémarres le backend. Les chemins ci-dessous correspondent à la config **systemd** du repo (`deploy/agentium-backend.service`) et à Nginx (`deploy/nginx/agentium.conf` : racine statique `/var/www/agentium`).

Pour le détail historique (smokes, variables d’environnement, topologies alternatives `/srv/agentium/…`), voir aussi [`vm-deploy-chat-runbook.md`](./vm-deploy-chat-runbook.md) et [`operator-deploy-vague-d.md`](./operator-deploy-vague-d.md).

### 12.1 Prérequis côté feature Knowledge Capture

- Migration Alembic **`021_expert_capture`** : elle est appliquée par `alembic upgrade head` après `git pull` (une fois le fichier présent sur la branche déployée).
- **Seed** capabilities/skills : doit avoir été exécuté sur la base cible (procédure d’init habituelle du projet) pour que `expert_knowledge_capture` et les skills voix/capture existent.

### 12.2 Étape 0 — Local

1. Sur ta machine : tests / typecheck optionnels (`poetry run pytest`, `npx tsc --noEmit`).
2. Commit, puis push vers la branche déployée sur `origin` (souvent `main` ou `demo/agentic` selon l’équipe).

```bash
git push origin <ta-branche>
```

### 12.3 Étape 1 — Connexion SSH et mise à jour du code

Remplace `<user>` et l’hôte par ceux de ton environnement (ex. `ubuntu@agentium.papai.ai`).

```bash
ssh <user>@agentium.papai.ai

cd /home/ubuntu/omnirag
git fetch origin
git checkout <branche-déployée>
git pull --ff-only origin <branche-déployée>
```

Si la VM a des modifications locales : `git stash`, `pull`, puis `stash pop` ; éviter les fichiers non suivis qui bloquent le checkout.

### 12.4 Étape 2 — Backend (venv, deps, migrations)

Le service systemd utilise **`/home/ubuntu/omnirag/venv`** et **`WorkingDirectory=/home/ubuntu/omnirag/backend`**. Utilise le même venv pour `pip` et `alembic`.

```bash
source /home/ubuntu/omnirag/venv/bin/activate
pip install -q -r /home/ubuntu/omnirag/backend/requirements.txt

cd /home/ubuntu/omnirag/backend
alembic -c alembic.ini upgrade head
deactivate
```

**Ordre important :** `git pull` puis `upgrade head` avant de tester des routes qui dépendent de nouvelles tables/colonnes.

### 12.5 Étape 3 — Frontend (build + publication des statiques)

Le projet Angular s’appelle **`agentium`** dans `angular.json` ; la sortie production est **`frontend-ng/dist/agentium/browser/`**.

**Option A — Build sur la VM** (recommandé si Node local &lt; 22 ou pour reproduire l’environnement cible) :

```bash
cd /home/ubuntu/omnirag/frontend-ng
npm ci
npx ng build -c production
sudo rsync -a --delete dist/agentium/browser/ /var/www/agentium/
```

**Option B — Build sur le laptop puis rsync** (Node ≥ 22 aligné avec le projet) :

```bash
# Sur la machine locale, à la racine du repo
cd frontend-ng
npm ci
npx ng build -c production

rsync -az --delete dist/agentium/browser/ \
  <user>@agentium.papai.ai:/tmp/agentium-browser-stage/
```

Puis sur la VM :

```bash
sudo rsync -a --delete /tmp/agentium-browser-stage/ /var/www/agentium/
```

Un redémarrage backend n’est pas toujours nécessaire si seuls les assets JS/CSS changent ; en cas de doute (routes, `index.html`), redémarrer ne nuit pas.

### 12.6 Étape 4 — Redémarrage du backend

```bash
sudo systemctl restart agentium-backend
sudo systemctl status agentium-backend --no-pager
```

Les logs applicatifs sont configurés vers `/home/ubuntu/omnirag/uvicorn.log` (voir l’unité systemd).

### 12.7 Vérifications rapides

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://agentium.papai.ai/
curl -sS -o /dev/null -w "%{http_code}\n" https://agentium.papai.ai/openapi.json
```

Contrôle métier optionnel : ouvrir `/knowledge/capture` (authentifié), créer un plan, vérifier transcription/TTS si la clé OpenAI est présente dans `backend/.env` sur la VM.

### 12.8 Pièges fréquents

| Problème | Piste |
| -------- | ----- |
| Erreur SQL / colonne manquante | Oublie de `alembic upgrade head` après pull, ou mauvais venv. |
| Ancien frontend | Mauvais dossier rsync : vérifier `dist/agentium/browser/`. |
| 503 voix | `OPENAI_API_KEY` absent ou invalide dans `/home/ubuntu/omnirag/backend/.env`. |
| Chemins différents sur une autre machine | Lire `deploy/agentium-backend.service` sur la branche déployée ; adapter `cd` et venv. |

---

## 13. Limites connues (Phase 0) et évolution

| Sujet | État | Piste |
| ----- | ---- | ----- |
| Gaps / plan / évaluation | Heuristiques déterministes | Brancher LLM + RAG sur le même schéma JSON. |
| Voix | Cascade STT/TTS | `RealtimeVoiceRuntime` + infra GPU si besoin produit. |
| Ingestion | Proposition + markdown | Job post-revue vers `document_ingestion_v1` ou équivalent. |
| `system_id` | Optionnel à la création du plan | Renseigner via API ou extension UI pour lier une session à un System précis. |

---

## 14. Index des fichiers principaux

| Zone | Fichiers |
| ---- | -------- |
| API | `backend/app/api/v1/endpoints/knowledge_capture.py`, `router.py` |
| Métier | `backend/app/services/knowledge_capture.py` |
| Voix | `backend/app/services/voice_runtime.py`, `endpoints/voice.py` |
| Modèles | `backend/app/models/expert_capture.py` |
| Migration | `backend/alembic/versions/021_expert_capture.py` |
| Registre | `seed.py`, `wrappers.py` |
| UI | `knowledge-capture.component.ts`, `knowledge.routes.ts`, `api.service.ts` |
| Tests | `backend/app/tests/services/test_knowledge_capture.py` |

---

*Document aligné sur l’état du dépôt omnirag au moment de sa rédaction. Pour toute évolution de contrat API, mettre à jour ce fichier et les tests associés.*
