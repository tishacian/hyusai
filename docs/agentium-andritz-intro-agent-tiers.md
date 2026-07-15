# Agentium & le cas Andritz — introduction pour un agent tiers

_But de ce document : donner à un agent (humain ou IA) qui découvre le dépôt une
vue d'ensemble exacte et actionnable d'**Agentium** et de son utilisation pour le
client **Andritz**, avec des pointeurs vers les docs de référence pour approfondir._

Dépôt : `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag` — branche de
travail `demo/agentic`.

---

## 1. Ce qu'est Agentium (en une page)

Agentium est un **système d'exploitation pour systèmes intelligents** : on déclare
un **objectif**, on le relie à des **capabilities** et des **skills**, et le
runtime produit des **décisions** mesurées, gouvernées et optimisées. La couche
RAG s'appelle **OmniRAG**.

Point essentiel pour comprendre le cas Andritz :

> La plateforme est **générique et multi-tenant par workspace**. **Andritz n'est
> pas du code sur mesure** : c'est un *slug de workspace + de la config + des
> données + des contrats de catalogue partagés*. Les anciens fallbacks fondés
> sur le slug sont une dette de compatibilité en cours de suppression, pas un
> mécanisme d'extension à reproduire.

Entités canoniques (Postgres) : `System`, `Capability`, `Skill`, `Context`,
`ControlPolicy`, `AdaptivePolicy`, `Run`, `Decision`, `Impact`.

Stack :
- **Backend** : FastAPI, `backend/app/api/v1/*`, services dans `backend/app/services/*`.
- **Frontend** : Angular 20 zoneless, `frontend-ng/src/app/*`.
- **Données** : Postgres (migrations Alembic), Qdrant (vecteurs dense + sparse,
  collections scoping `{workspace_slug}__{collection_name}`).
- **Voix** : STT/TTS via `voice_runtime.py` / `voice_session_gateway.py`
  (cascade + realtime LiveKit gated).

Doc de vérité produit complet : [`mental-model.md`](./mental-model.md).

---

## 2. Deux lignées métier, cinq Systems actifs, trois applications

Les travaux Andritz sont historiquement organisés autour de deux **lignées
métier** — Capture de connaissance et Recherche transverse. Elles ne doivent
pas être confondues avec l'inventaire runtime : le workspace possède cinq
`System` actifs distincts et expose trois applications métier aux utilisateurs.
Synthèse de réutilisation :
[`pih/AGENTIUM-PIH-reuse-from-andritz.md`](./pih/AGENTIUM-PIH-reuse-from-andritz.md).

| System actif | Variant / rôle |
| --- | --- |
| `Andritz Workspace Chat` | `chat_transverse_v1`, recherche canonique de `/chat` |
| `Andritz Chat Agentic` | `chat_agentic_thinking_v1`, délégation des intentions agentiques |
| `Andritz Expert Knowledge Capture System` | `expert_knowledge_capture`, capture et publication |
| `Client360 PDR` | `client360_pdr`, application Client360 |
| `News Lab` | `intelligence`, veille et recherche transverse |

Les deux Systems Chat sont complémentaires : le premier reste le point
d'entrée canonique et délègue au second lorsque la configuration agentique le
demande. Ils ne doivent ni être fusionnés ni être dédupliqués.

### Système A — Capture de connaissance experte ("Le Fil")

Chaîne fermée : **ancrage du contexte → analyse des lacunes → plan d'interview →
session voix/texte avec évaluation par tour → oracle qualité ancré RAG →
structuration → revue humaine (accepter/amender/rejeter) → publication →
ré-indexation dans la KB → journal d'audit append-only**.

- Backend : `backend/app/services/knowledge_capture.py` (moteur),
  `capture_knowledge_oracle.py` (scoring de lacunes + détection de contradictions),
  `capture_report_templates.py` (templates de fiche), `voice_session_gateway.py`.
- API : `backend/app/api/v1/endpoints/knowledge_capture.py` (`/api/v1/knowledge-capture/*`).
- Frontend : `frontend-ng/src/app/features/knowledge/capture-fil/*` (expérience
  "Le Fil" / "La Scène" : dashboard → plan → session live + transcript +
  pièces jointes marquées → finalize → revue → publish).
- Boucle fermée : `publish_proposal_to_knowledge` →
  `DocumentService.ingest_document(..., source_type="expert_fiche")` → faits
  structurés dans `KnowledgeDocumentFact` / `KnowledgeTableFact`. Les fiches
  publiées vont par défaut dans la **collection transverse** du chat recherche
  et sont **pinnées** comme les corrections expertes.

Spécs & décisions : [`expert-knowledge-capture.md`](./expert-knowledge-capture.md),
[`adr/0001-refonte-capture-le-fil.md`](./adr/0001-refonte-capture-le-fil.md),
catalogue A/B [`capture-le-fil-ab-test-catalog.md`](./capture-le-fil-ab-test-catalog.md).

### Système B — Chat / RAG transverse (OmniRAG)

Assistant métier de **consultation documentaire** sur une grande KB. Ce n'est
pas une interface de moteur de recherche : il répond au fait, puis cite.

Pipeline de réponse (orchestrateur `backend/app/services/rag/context.py::retrieve_rag_context`) :
indexation → storage Qdrant → résolution de profil → requête augmentée par
l'historique → guides + policy → **planification de corpus / inférence de scope /
gate de décomposition** → sélection de mode (dense vs hybride) → retrieval
multi-source (dense + BM25/sparse) → sous-requêtes comparatives → **fusion RRF** →
dédup → rerank policy + required-terms → **cross-encoder** → seuil de similarité →
**MMR** → compression contextuelle → contexte parent → faits table/document →
**decision trace** → génération à budget déterministe → **citations ancrées**.

- API + UI : `backend/app/api/v1/endpoints/chat.py` (`POST /chat/stream`, SSE) +
  `frontend-ng/src/app/features/chat/*` + `core/sse.service.ts`. Contrat de
  citation : `[1..N]` ↔ `sources[n-1]` (≤ 8 citables, ≤ 3 passages/doc).
- Planner grande KB : `backend/app/services/rag/corpus_planner.py`,
  `project_inventory.py`, `source_facets.py`.

Note de profil opératoire Andritz (à lire absolument avant de toucher au chat) :
[`andritz-chat-transverse-profile-note.md`](./andritz-chat-transverse-profile-note.md).

---

## 3. Spécificités Andritz : le modèle métier et la donnée

### 3.1 Modèle métier projet

- Les références `XXX123` (ex. `AKK200`, `BHX100`, `BBA120`, `COL100`) sont des
  **références projet stables** — un agencement de machines dans une ligne, **pas
  une machine unique**. Les 3 lettres = premier client historique ; le nombre =
  position/phase dans la chaîne. La référence ne change pas si la ligne est revendue.
- Les machines/équipements ne sont identifiés que lorsqu'ils sont **nommés** dans
  les notices : carde, TMS, TCF, EXCELLE, injector, pump, damper, sensor, jetlace…
- **Termes à protéger contre le rewriting** (ne jamais reformuler/traduire) :
  `COL100`, `BHX100`, `BBA120`, `AKK200`, `KD724`, `PRJ2S`, `TMS`, `TCF`,
  `EXCELLE`, `carde`. Remplacer `carde` par `carte` détruit la requête.

### 3.2 Collections & scope

- Scope principal : `andritz-spl-knowledge-experiment`.
- Collections : `andritz-notices-techniques-spl-pilot` (notices SPL, principale),
  `andritz-manuals-bba120-pilot`, `andritz-non-wovens-france-excel-pilot`,
  `andritz-non-wovens-pilot-archive`.
- Profils : navigation `business_end_user` (mini-shell métier à trois
  applications : `/chat` — Recherche, `/client360` — Client360 PDR et
  `/knowledge/capture` — Capture de connaissances, dans cet ordre), assistant
  `andritz_spl_advisor`, réponse `industrial_answer_profile_v1`
  (`backend/app/services/industrial_answer_profile.py`).

### 3.3 Flux d'ingestion (SFTP → index)

`Fichier déposé (SFTP/portail)` → ligne `deposit_files` `status='received'` →
**promotion manuelle** vers une collection → `status='promoted'` → extraction +
chunking + embeddings → points Qdrant → faits dans `knowledge_document_facts` /
`knowledge_table_facts`.

Pièges connus (voir [`andritz-data-indexing-context-2026-06-02.md`](./andritz-data-indexing-context-2026-06-02.md)) :
- `document_names` peut lister des docs **absents de Qdrant** : toujours vérifier
  Qdrant, pas seulement les métadonnées (cas `Manual_ASY100.zip`).
- Beaucoup de données carde/BHX100 sont encore en `received` (non exploitables).
- Les pages HTML de navigation (`menu`, `index`) doivent être **dépriorisées**
  comme preuve mais rester indexables si elles portent du contenu.

### 3.4 Règles de réponse du chat transverse (résumé)

Commencer par le fait, citer numériquement, **ne jamais exposer la mécanique**
(`chunk`, `score`, `retrieval`, `RAG`, `Qdrant`, ranking, confiance). Consolider
les faits multi-documents. Nommer explicitement les **trous documentaires** au
lieu d'inventer. Réserver les listes aux inventaires/comparaisons/pièces.

```text
La pompe utilisée pour le projet AKK200 est une Uraca KD724, associée au groupe
haute pression PHP. [1]
```

Chantier de vigilance ouvert : le **scoping du retrieval** peut filtrer trop tôt
sur les menus/sommaires et exclure les sections techniques (diagnostic AKK200).

---

## 4. Flow Builder & déclencheurs (travaux récents)

Le Flow Builder orchestre les systèmes en nœuds/arêtes. Trois évolutions
récentes ont fait des sources/inputs des nœuds de premier ordre (ADR :
[`adr-flow-source-nodes.md`](./adr-flow-source-nodes.md)) :

- **Phase 1** — nœuds `asset` (collections) et déclencheurs `source.sftp_arrival`
  déclaratifs (pass-through), projetés dans le manifest.
- **Phase 2** — les nœuds de retrieval résolvent la collection depuis le nœud
  `asset` connecté via `inputs_map` (flag `flow_asset_binding_authoritative`),
  avec sync de l'allowlist membrane.
- **Phase 3** — `event_driven_automation` : `source.sftp_arrival` peut déclencher
  des runs, **en dry-run par défaut** (flag `enable_event_triggers`), avec dédup,
  rate-limit et circuit-breaker.

**Invariant de gouvernance** (non négociable) : la promotion SFTP reste
**explicite** (pas d'auto-ingestion), et tout effet de bord passe par un HITL. Un
type de déclencheur ne sert qu'à un type d'effet.

---

## 5. Ops / déploiement (VM démo)

| Élément | Valeur |
| --- | --- |
| URL app | `https://agentium.papai.ai` |
| SSH | alias `omnirag-demo` |
| Repo VM | `/home/ubuntu/omnirag` |
| Services applicatifs | `agentium-backend`, `agentium-frontend`, `agentium-worker-cpu` |
| Dépôt sécurisé | `/data/secure_deposit/{deposit_files.object_key}` |
| Branche | `demo/agentic` |
| Santé | `curl -fsS https://agentium.papai.ai/api/v1/health` |
| Déploiement | `scripts/deploy-vm.sh`, branche et SHA complet obligatoires |

Les migrations ne sont pas appliquées automatiquement par le script. Une
révision Alembic impose le rollout en deux temps : construction du candidat,
quiescence de l'API, migration avec l'image candidate, vérification du head,
puis activation. Ne pas lancer un `alembic upgrade head` ad hoc pendant que
l'ancien backend sert encore du trafic. Le déroulé et le rollback de référence
sont ceux du
[`Lot 5 — cleanup & governance`](./agentium-navigation-lot-5-cleanup-governance.md#commandes-opératoires).

Ne pas supposer que les fichiers SFTP sont dans Git : ils vivent dans le dépôt
sécurisé de la VM, indexés dans Postgres/Qdrant.

---

## 6. Carte des documents de vérité

| Besoin | Document |
| --- | --- |
| Vision produit complète | [`mental-model.md`](./mental-model.md) |
| Réutilisation des briques (vue systèmes A+B) | [`pih/AGENTIUM-PIH-reuse-from-andritz.md`](./pih/AGENTIUM-PIH-reuse-from-andritz.md) |
| Chat transverse Andritz (profils, style, retrieval) | [`andritz-chat-transverse-profile-note.md`](./andritz-chat-transverse-profile-note.md) |
| Contexte data & indexation Andritz | [`andritz-data-indexing-context-2026-06-02.md`](./andritz-data-indexing-context-2026-06-02.md) |
| Knowledge Guide notices SPL | [`andritz-notices-techniques-spl-knowledge-guide.md`](./andritz-notices-techniques-spl-knowledge-guide.md) |
| Capture de connaissance (spéc & ADR) | [`expert-knowledge-capture.md`](./expert-knowledge-capture.md), [`adr/0001-refonte-capture-le-fil.md`](./adr/0001-refonte-capture-le-fil.md) |
| Flow Builder — nœuds source/asset & triggers | [`adr-flow-source-nodes.md`](./adr-flow-source-nodes.md) |
| Politique de déploiement dev | [`dev-deploy-policy.md`](./dev-deploy-policy.md) |
| Rollout VM épinglé au SHA, migration et rollback DB | [`agentium-navigation-lot-5-cleanup-governance.md`](./agentium-navigation-lot-5-cleanup-governance.md#commandes-opératoires) |
| Carte production / démo | [`production-demo-map.md`](./production-demo-map.md) |

---

## 7. Réflexes pour un agent qui reprend

1. Andritz = **config + données**, pas du code sur mesure. Chercher d'abord le
   levier config/policy/données avant d'écrire de la logique.
2. Avant de toucher au chat : lire la note de profil transverse. Le **style de
   réponse** (`industrial_answer_profile.py`) et le **retrieval**
   (`corpus_planner.py`) sont deux chantiers distincts.
3. **Protéger les termes exacts** (codes projet, pièces) contre tout rewriting.
4. Vérifier l'état réel de la donnée dans **Qdrant** (pas seulement Postgres)
   avant de conclure qu'une question est censée trouver une réponse.
5. Toute modif de schéma ⇒ rollout quiescé et épinglé au SHA ; ne jamais migrer
   la base après avoir exposé un backend qui attend déjà le nouveau schéma.
6. Respecter l'**invariant de gouvernance** des déclencheurs (SFTP explicite,
   HITL pour les effets de bord, dry-run par défaut).
