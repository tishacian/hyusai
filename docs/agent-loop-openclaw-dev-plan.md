# Plan de dev — AgentLoop (enveloppe déterministe, intérieur mou)

Date : 2026-08-22
Branche cible : `demo/agentic`
Statut : **contrat de plan** — pas une attestation, pas une autorisation de
déployer, pas une migration.

Ce document transforme le mapping OpenClaw → NAWA / PIH en un plan d'implémentation
**collé au runtime existant**. Il est la source de vérité des contrats L0–L5
tant qu'aucun ADR d'implémentation ne les reprend.

Formule produit à tenir :

> **Deterministic envelope, non-deterministic interior.**
> Le flow fixe *ce qui est permis, ce qui est commit, ce qui est évalué*.
> L'agent choisit *comment avancer dans l'enveloppe* jusqu'au goal.

Le « mou » = **quelle skill appeler ensuite**. Pas « écrire dans SAP comme il
veut ».

---

## 0. Invariants (non négociables)

1. OpenClaw n'est **pas** le modèle. Agentium reste une **boucle libre dans une
   enveloppe de capacités**. Pas de `exec` / shell, pas d'autonomie write par
   défaut, pas de skills community non reviewées, pas de `MEMORY.md` perso, pas
   de « l'agent fabrique ses skills » en prod.
2. Aucun nouveau kind ne remplace un kind qui marche. On **compose** :
   `task` = InvokeSkill, `hitl` = HumanGate, `fork`/`join` = FanOut/Join,
   Membrane = mandate.
3. Un nœud `loop` existant **n'est pas** un AgentLoop. `loop` répète **une**
   skill bornée. `agent_loop` choisit **la prochaine** skill dans une allowlist.
4. Tout write / side-effect class `write` traverse un gate (HITL ou
   `act_with_approval`). Le modèle ne voit jamais un tool qu'il n'a pas le
   droit d'appeler.
5. Pause = checkpoint + resume. Jamais restart. Autorité =
   `Run.checkpoints` + `Decision` existants (`resume_run_dag`).
6. Mesurer la propriété qui compte, pas son indice. Un contrat publié non
   nul ne prouve pas un dispatch. Un AgentLoop « qui tourne » ne prouve pas
   qu'un write a été gated. (Leçon `docs/ops/skills-program-handoff-2026-08-08.md`.)
7. Premier host : **NAWA Password Reset**, déjà porteur de LLM + Decision +
   HITL + audit. On ne greffe pas ça d'abord sur Finance close (pas de flow
   nommé) ni sur un graphe Andritz à 20 nœuds.

---

## 1. État actuel — ce qu'on récupère, ce qu'on n'invente pas

Inventaire runtime au 2026-08-22. Les chemins sont des ancres, pas une licence
à tout réécrire.

| Primitive voulue | Artefact actuel | Statut | Ancre |
|---|---|---|---|
| Trigger | `kind: source` (+ webhook / SFTP / schedule / deposit) | Existe | `flow.types.ts` `DEFAULT_PALETTE` |
| Goal | port `goal` sur Trigger ; pas d'objectif typé | Partiel | même palette, output `goal` |
| InvokeSkill | `kind: task` + `config.skill_slug` | Existe | `_execute_task_node` |
| Decide déterministe | `kind: decision` + DSL AST | Existe | `condition.py`, `_run_decision` |
| Decide JSON-schema | skills LLM (`chat_agentic_plan_v1`) | Partiel | `wrappers.py` — coerce + defaults sûrs |
| AgentLoop | **absent** | Manquant | — |
| Loop borné (1 skill) | `kind: loop` `max_iterations` | Existe | `_run_loop` |
| HumanGate + resume | `kind: hitl` + `hitl_pending` + `resume_run_dag` | Existe | `dag.py`, `POST /runs/{id}/hitl` |
| Mandate / allowlist | `MembraneSpec.capabilities.allowed_skills` + ControlPolicy | Partiel | `membrane/spec.py` |
| Privilege tiers | **absent** comme enum | Manquant | valves / outbound seulement |
| Side-effect class | trigger governance `ingestion` / `analysis` / `notification` | Partiel | `triggers.py` |
| FanOut / Join | `fork` / `join` | Existe | `_run_fork`, `_run_join` |
| Sub-agent | `subflow` + `allowed_delegations` | Existe | `subflow_orchestration.py` |
| Steering mid-run | inbox **seulement** si `hitl_pending` | Partiel | `inbox.py` |
| Budget tokens / $ / latence | `ValvesFacet` + `WalkerState.total_cost` | Partiel | pas de budget *turns* |
| Ledger / replay narratif | `Run.checkpoints` + `SkillInvocation` + `audit_log_v1` | Existe | pas de replay-from-ledger |
| Catalog compaction | palette Builder seulement | Manquant runtime | pas de `tool_search` |
| HITL dans la palette | **absent** (`hitl` artifact-authored) | Trou UX | `gen_nawa_password_reset_flow.py` L1780 |

Walker : Kahn + ticks parallèles dans `backend/app/services/run_engine/dag.py`.
`CONTROL_KINDS` aujourd'hui :

```text
decision, fork, join, retry, hitl, subflow, loop
```

(`execution_contract.py`)

**Conséquence produit :** le DAG « 20 nœuds » que Fayçal refuse est déjà notre
path Andritz Chat Agentic (`plan → route → retrieve → eval fan-out →
self-correct → HITL`). Le plan consiste à **replier l'intérieur** dans un
`agent_loop`, pas à ajouter encore des kinds décoratifs.

---

## 2. Mapping OpenClaw → primitives Agentium

| Concept OpenClaw | Primitive Agentium | Rôle | Action |
|---|---|---|---|
| `goal` | config `Goal` sur `agent_loop` (+ nœud Goal optionnel L1+) | objectif + `done_when` + budget + status | **nouveau contrat**, pas une table Day-1 |
| Agent loop | `kind: agent_loop` | boucle bornée think → gate → act → observe | **nouveau kind** (L1) |
| `llm-task` | skill `decide_next_v1` puis nœud `decision` mode `json_schema` | JSON figé `{next_skill, …}` | **nouvelle skill** (L0) puis mode Decision (L1) |
| Skill pack | `task` / `InvokeSkill` (alias UX seulement) | playbook catalogué | réutiliser |
| Tool | connector derrière une skill, jamais exposé au modèle | SAP read, ME ticket, Teams | durcir le catalogue, pas le walker |
| Tool policy | Membrane ∩ allowlist du loop ∩ privilege tier | filtre **avant** le prompt | étendre Membrane (L0/L3) |
| `ask_user` | `hitl` comme tool du loop | pause structurée + resume | promouvoir palette (L2) |
| Steering | run-control API | redirect mid-flight sans tuer | **après** L2 (L4) |
| Approval Lobster | HITL existant + ledger | side effects seulement après OK | réutiliser |
| Subagent / swarm | `fork` + `join` + workers `read` | parallèle borné, merge déterministe | **après** (L5) |
| `tool_search` | `skill_search_v1` sur mini-catalogue | compaction | L4, pas L0 |

DAG minimal crédible (celui demandé) :

```text
Trigger → Goal → AgentLoop(Decide ↔ Skills) → HumanGate? → Commit → Eval
```

Traduction **sans inventer 5 kinds** :

```text
source  →  agent_loop{goal, decide_next_v1, allowlist}
              ├─ task (skills allowlistées)
              └─ hitl (si needs_human / write)
         →  task:audit_log_v1
         →  task:eval_*  |  sink
```

`Commit` et `Eval` restent des **skills** (`audit_log_v1`, `response_eval_v1`,
`eval_radar_v1`). Les promouvoir en kinds ne change rien au contrat d'usine
et augmente la surface Builder — contraire au feedback Fayçal.

---

## 3. Spec 1 page — `decide_next_v1` + `agent_loop`

Les schémas ci-dessous sont **pinnés**. Changer ici d'abord, puis le code.

### 3.1 Skill `decide_next_v1` (cœur du mou contrôlé)

Pattern déjà prouvé : `chat_agentic_plan_v1` (JSON strict, coerce, defaults
fail-closed). On ne copie pas son schéma métier (action chat). On copie la
**discipline**.

**Input (runtime, jamais le prompt brut catalogue) :**

```json
{
  "goal": {
    "objective": "Reset the requester AD password under ITSD policy",
    "done_when": [
      "identity_verified OR human_approved",
      "reset_simulated OR reset_applied",
      "requester_notified"
    ],
    "status": "active"
  },
  "observations": [
    {"turn": 1, "skill": "nawa_classify_intent_v1", "ok": true, "summary": "password_reset"}
  ],
  "visible_skills": [
    {
      "slug": "nawa_classify_intent_v1",
      "purpose": "Classify ITSD intent",
      "side_effect_class": "read",
      "privilege_tier": "recommend"
    }
  ],
  "budget": {"turns_left": 4, "cost_left": 0.4, "deadline_ms_left": 20000}
}
```

`visible_skills` est **déjà filtré** (Membrane ∩ allowlist du loop ∩
privilege). Le modèle ne peut pas demander une skill absente de cette liste.

**Output figé :**

```json
{
  "next_skill": "nawa_assess_identity_v1",
  "rationale": "Intent is password_reset; identity evidence is still missing.",
  "confidence": 0.81,
  "needs_human": false,
  "human_prompt": null,
  "exit": null,
  "done": false
}
```

| Champ | Type | Règle |
|---|---|---|
| `next_skill` | `string \| null` | **Doit** ∈ `visible_skills`. Sinon coerce → `exit: "policy_block"` |
| `rationale` | `string` | max 400 chars, ledger |
| `confidence` | `number` | `[0, 1]`, défaut `0` |
| `needs_human` | `boolean` | si `true`, le loop **n'exécute pas** `next_skill` |
| `human_prompt` | `string \| null` | requis si `needs_human` |
| `exit` | `null \| "complete" \| "blocked" \| "ask_human" \| "budget" \| "policy_block"` | terminal du tour |
| `done` | `boolean` | `true` seulement si `done_when` est revendiqué ; le **spine** revérifie |

**Seuil :** si `confidence < loop.confidence_floor` (défaut `0.55`) →
`needs_human: true` **ou** fallback déterministe (Decision DSL déjà câblée).
Jamais « on tente le write quand même ».

**Fail-closed coerce** (même esprit que `_coerce_plan`) :

- JSON illisible → `{next_skill: null, exit: "blocked", confidence: 0, done: false}`
- skill hors allowlist → `policy_block`
- `needs_human` sans prompt → prompt synthétique depuis `rationale`
- `done: true` alors qu'un check `done_when` est faux → ignorer `done`, continuer

### 3.2 Nœud `agent_loop`

Kind nouveau, ajouté à `CONTROL_KINDS`. Ce n'est **pas** un alias de `loop`.

```ts
interface GoalSpec {
  objective: string;
  done_when: string[];          // golden checks / critères, pas un chemin
  status: 'active' | 'blocked' | 'needs_approval' | 'complete';
}

interface AgentLoopBudget {
  max_turns: number;            // obligatoire, défaut 6, max auteur 20
  max_cost?: number;            // $ run-local, en plus de ValvesFacet
  deadline_ms?: number;
}

interface AgentLoopNodeConfig {
  goal: GoalSpec;
  decide_skill: 'decide_next_v1';
  skill_allowlist: string[];    // 5–8 slugs, intersect Membrane
  confidence_floor: number;     // défaut 0.55
  budget: AgentLoopBudget;
  privilege_tier: 'recommend' | 'act' | 'act_with_approval';
  on_budget: 'exit' | 'ask_human';
}
```

**Sémantique d'un tour** (spine déterministe, cellule cognitive unique) :

```text
[spine]  load goal + observations + remaining budget
[cell]   decide_next_v1 → DecideOutput          ← seul choix modèle
[spine]  policy gate (allowlist ∩ membrane ∩ privilege ∩ side-effect)
[spine]  if needs_human or write-without-act → hitl pause (resume token)
[spine]  else execute next_skill via _execute_task_node
[spine]  observe + append checkpoint agent_loop_turn
[spine]  eval done_when  →  continue | ask_human | exit
```

Le spine est **replayable / diffable / ledger-friendly**. On ne rejoue pas les
tours passés au resume : on reprend `observations[]` depuis le checkpoint.

**Status Goal** (machine, pas du texte LLM) :

| Status | Qui l'écrit | Signification |
|---|---|---|
| `active` | spine au start | budget restant, pas bloqué |
| `needs_approval` | spine si `needs_human` ou write gated | run = `hitl_pending` |
| `blocked` | spine si `policy_block` / membrane breach | pas de write |
| `complete` | spine si **tous** les `done_when` passent | exit propre |

Le modèle peut *revendiquer* `done`. Seul le spine *accorde* `complete`.

### 3.3 Privilege tiers (L3, contrat figé dès L0 pour ne pas peindre dans le coin)

| Tier | Le loop peut | Writes |
|---|---|---|
| `recommend` | skills `side_effect_class: read` + drafts | jamais |
| `act` | read + writes already allowlistés | oui, ledger immédiat |
| `act_with_approval` | read libre ; write → HITL | seulement après accept |

Day-1 PIH / NAWA = `act_with_approval` sur tout write (SAP, AD, ITSM).
`act` n'est pas un défaut produit.

### 3.4 HumanGate comme tool, pas comme exception

`hitl` existant devient invocable **depuis le loop** :

- `needs_human: true` → même `_run_hitl` / Decision `proposed`
- kinds de prompt : `choice` (A/B), `validate_draft`, `missing_file`, `approve_write`
- resume = `POST /runs/{id}/hitl` actuel ; l'observation `human` est poussée
  dans `observations[]` ; le loop **reprend**, il ne restart pas

Pas de second protocole « resume token Lobster ». Le token **est**
`(run_id, decision_id, checkpoint.kind=hitl_pause)`.

---

## 4. Ce qu'on n'importe **pas**

| OpenClaw | Pourquoi non (PIH / Agentium) |
|---|---|
| `exec` / shell libre | surface d'attaque + non auditable métier |
| Autonomie write par défaut | SAP / ITSM / AD = approve-then-act |
| Skills community non reviewées | pas de CoE / pas de golden set |
| `MEMORY.md` perso illimité | fuite cross-BU / retention |
| « Build its own skills » en prod | OK lab CoE, interdit factory day-1 |
| 80 tools dans le prompt | inverse de l'allowlist ; C-level illisible |
| Renommer `task` → `InvokeSkill` en breaking | alias UX seulement, jamais un second kind |
| Étendre `loop` jusqu'à ce qu'il « choisisse » | deux sémantiques, un seul kind = dette sure |

---

## 5. Tranches — ordre ROI

Taille : S = un commit chirurgical, M = quelques fichiers + tests, L = moteur
+ contrat + un flow hôte. Pas de calendrier.

| # | Tranche | Taille | Dépend de | Host de preuve |
|---|---|---|---|---|
| **L0** | `decide_next_v1` + allowlist dans un flow existant | M | — | Password Reset (nœud task, DAG inchangé) |
| **L1** | `agent_loop` + budget turns/$ + exit explicite | L | L0 | Password Reset *variante* overlay, pas un rewrite prod |
| **L2** | HumanGate palette + `ask_user` *depuis* le loop (resume) | M | L1 | même host ; tests HITL déjà là |
| **L3** | Privilege tiers bindés Membrane / mandate | M | L0 (contrat), L1 (enforce) | Password Reset write simulé + 1 skill read |
| **L4** | Steering mid-run + `skill_search_v1` | L | L2 | cockpit ops / C-level POC |
| **L5** | Fan-out workers read-only + Join déterministe | M | L1 + `fork`/`join` | HR Barometer / multi-BU — **pas** day-1 |

L0 est livrable **sans** nouveau kind. C'est volontaire : on prouve le mou
contrôlé dans le walker actuel avant d'élargir `CONTROL_KINDS`.

---

### L0 — `decide_next_v1` + allowlist (sans nouveau kind)

**But.** Un nœud `task` appelle `decide_next_v1`. Une Decision DSL déjà câblée
branche sur `next_skill` / `needs_human` / `exit`. Le modèle ne voit que 5–8
skills.

**Toucher (cible, pas un dump) :**

- `backend/app/services/skills_registry/seed.py` — seed `decide_next_v1`
- `backend/app/services/skills_registry/wrappers.py` — wrapper + coerce
- `backend/app/services/membrane/enforcement.py` — visible catalog = intersection
- flow hôte : overlay **de démo** à côté de
  `backend/app/resources/flows/nawa_password_reset_v1.json`
  (ne pas casser le golden path artifact-authored)
- tests : `backend/app/tests/services/` nouveau
  `test_decide_next_v1.py` + reuse
  `test_nawa_password_reset_flow.py` comme non-régression

**Hors scope L0.** Nouveau kind, palette HITL, steering, fan-out, Finance close.

**Succès vérifiable.**

1. Prompt envoyé au modèle contient **uniquement** les slugs allowlistés.
   Test : skill hors liste absente du prompt **et** rejetée au coerce.
2. JSON cassé → `exit=blocked`, aucune skill métier invoquée.
3. `confidence < floor` → branche HITL existante (le flow password reset a déjà
   `hitl.identity_gate`).
4. Suite `test_nawa_password_reset_flow.py` verte sans modification de
   sémantique du path simulé.

**DAG L0 (minimal, overlay) :**

```text
source.request
  → task.decide_next_v1
  → decision.route          # DSL sur exit / needs_human / next_skill
       ├─ task.<chosen>     # un task par skill allowlistée (encore figé)
       └─ hitl.identity_gate
  → sink
```

Oui, L0 a encore N `task` en aval : le **choix** est mou, le **câblage** reste
un DAG. L1 supprime ces N nœuds.

---

### L1 — nœud `agent_loop` + budget + exit

**But.** Un seul nœud remplace la gerbe `decide → decision → N tasks`.
Le walker exécute la boucle interne. Le canvas redevient lisible.

**Toucher :**

- `execution_contract.py` — `agent_loop` ∈ `CONTROL_KINDS`
- `flow_node_kind.py` + `dag_validator.py` — allowlist 5–8, `max_turns` requis
- `dag.py` — `_run_agent_loop()` ; **réutilise** `_execute_task_node`,
  `_run_hitl`, checkpoints ; **n'appelle pas** `_run_loop`
- `flow-serializer.service.ts` — `NodeKind` + `AgentLoopNodeConfig`
- `flow.types.ts` — entrée palette **une** : `Agent loop`
- `flow_contracts.py` — figer `decide` schema + allowlist dans le contrat publié
- tests walker : nouveau module, plus une golden preview Workbench

**Contrat walker.**

- Serialise le nœud (comme `hitl` / `loop`) : pas de fan-out interne parallèle.
- Chaque tour écrit `checkpoints[]` `{kind: "agent_loop_turn", turn, decide, skill, cost}`.
- Budget : `turns >= max_turns` ou `total_cost >= max_cost` ou deadline →
  `on_budget` (`exit` | `ask_human`). Jamais un 7ᵉ tour « pour finir ».
- `done_when` évalué par le spine (predicates DSL `condition.py` **ou** checks
  nommés du host). Pas un « le modèle a dit done ».

**Succès vérifiable.**

1. Flow overlay Password Reset : canvas = `source → agent_loop → sink`
   (plus la gerbe N tasks).
2. 1 run complete ≤ `max_turns` ; 1 run forcé budget → `goal.status=blocked`
   ou HITL, **zéro** write.
3. Skill hors allowlist demandée par un stub modèle → `policy_block`,
   invocation métier absente de `SkillInvocation`.
4. Publication : contrat contient l'allowlist figée ; un PATCH du catalogue
   skill **ne** change **pas** un Run déjà piné (même discipline que
   `083a9ada` gel d'exécuteur).
5. `python` tests L1 + non-régression password reset + Ruff des fichiers
   nouveaux.

**Interdit L1.** Steering, `skill_search`, workers, rewrite du flow prod
NAWA seedé.

---

### L2 — HumanGate = tool du loop (resume, pas restart)

**But.** `ask_user` n'est plus une exception de graphe. Le loop s'arrête,
l'humain répond, le loop reprend avec la même `Run.id`.

**Toucher :**

- Palette : ajouter `hitl` dans `DEFAULT_PALETTE` (trou documenté depuis le
  générateur password reset).
- `HitlNodeConfig` : `prompt_kind: 'choice' | 'validate_draft' | 'missing_file' | 'approve_write'`
- `_run_agent_loop` : `needs_human` / `act_with_approval` + write → même pause
  que `_emit_hitl_pause`
- UI terminale déjà dans `flow-terminal.component.ts` — étendre les 3 kinds
  de prompt, pas une nouvelle page
- tests : étendre `test_nawa_password_reset_flow.py` + Playwright
  `e2e/tests/03-hitl-approve.spec.ts`

**Succès vérifiable.**

1. Run `hitl_pending` au milieu d'un `agent_loop` (tour 2/6) ; accept →
   tour 3 **sans** recréer le Run, observations 1–2 intactes.
2. Reject write → `goal.status=blocked`, pas d'appel connecteur.
3. HITL visible dans la palette Builder ; drop + publish compile.
4. TTL gate existant (`gate_ttl.py`) s'applique au HITL *intra-loop*.

---

### L3 — Privilege tiers bindés au mandate

**But.** Une seule enveloppe consultée **avant** le prompt. Plus de policy
éparpillée « un peu Membrane, un peu ControlPolicy, un peu trigger ».

**Toucher :**

- `CapabilityFacet` : `privilege_tier` + `side_effect_class` par skill
  (lecture depuis le seed catalogue, pas saisi à la main dans le loop)
- compilation d'un **Mandate view** (read-model) :
  Membrane ∩ ControlPolicy ∩ `agent_loop.skill_allowlist` ∩ tier
- enforcement dans le *gate du tour*, pas seulement en début de Run
- seed skills NAWA : classify/assess = `read`/`recommend` ; reset simulé =
  `write`/`act_with_approval`

**Pas de table `mandates` Day-1.** Le message PIH « signed mandate » est déjà
porté par ControlPolicy / Membrane. L3 **compile** cette enveloppe pour le
loop. Une table signée / révocation 1-clic est un lot gouvernance à part
(decks PIH) — ne pas le glisser ici.

**Succès vérifiable.**

1. Loop `privilege_tier=recommend` : `decide_next` ne reçoit **aucune** skill
   `write` dans `visible_skills` ; un stub qui les demande → `policy_block`.
2. `act_with_approval` + next write → HITL **avant** `_execute_task_node`.
3. Shadow vs enforce Membrane : shadow log + run continue ; enforce abort.
   Même sémantique qu'aujourd'hui, appliquée **au tour**.

---

### L4 — Steering + catalog compaction

**But.** Sensation OpenClaw sans restart : « arrête les writes, continue en
recommend-only » ; « change de BU, même goal » ; « escalade Finance ».

**Toucher :**

- étendre `inbox.py` aux Runs `running` **porteurs d'un `agent_loop`**
  (aujourd'hui : buffer seulement si `hitl_pending`)
- API `POST /runs/{id}/steer` :
  `{op: "set_tier"|"set_allowlist"|"inject_note"|"escalate", ...}`
- effet : prochain tour voit le Mandate view mis à jour ; **ne skip pas** un
  tool déjà `running` ; **ne rejoue pas** les tours passés
- skill `skill_search_v1` : query → ≤ 8 slugs **sous** le mandate ; le loop
  peut l'appeler comme n'importe quelle skill `read`

**Succès vérifiable.**

1. Steer `set_tier=recommend` mid-run : les tours suivants n'exécutent plus
   de write ; les writes déjà committed restent (ledger).
2. Steer n'ouvre **pas** de nouveau Run.
3. `skill_search_v1` hors mandate → 0 résultat, pas d'erreur modèle.

---

### L5 — Fan-out borné (après seulement)

**But.** 1 parent goal, N workers **read-only**, 1 collector déterministe.

Réutiliser `fork` / `join` (`strategy: all`) + `subflow` avec
`allowed_delegations`. Chaque worker peut porter un `agent_loop` en
`recommend`. Le Join **ne** décide **pas** : merge fixé (schema), auditable.

Host : HR Barometer / multi-BU Finance — **pas** Password Reset.

**Succès vérifiable.**

1. Worker qui tente un write → `policy_block` isolé, parent continue.
2. Join replay : mêmes N payloads → même objet fusionné (test snapshot).

---

## 6. Hosts — où greffer, où ne pas greffer

| Host | Pourquoi | Tranche |
|---|---|---|
| **NAWA Password Reset** `nawa_password_reset_v1.json` | Seul flow shipped avec LLM + Decision + HITL + write simulé + `audit_log_v1` + suite de tests | L0–L3 |
| PO–Invoice Reconciliation `po_invoice_reconciliation_v1.json` | DAG v3 linéaire, contrat publié, zéro control node — bon 2ᵉ host InvokeSkill / Goal | L1 overlay optionnel |
| Andritz Chat Agentic v3 | Proto-loop figé en 20 nœuds ; *cible de repli* une fois L1 stable, pas le premier patient | post-L2 |
| Finance close / SFTP staging | Infra trigger existe (`source.sftp_arrival`), **pas de flow nommé** | greenfield **après** L2 |

Password Reset reste le path prod artifact-authored tant qu'un overlay
AgentLoop n'a pas les mêmes goldens. Ne pas réécrire
`gen_nawa_password_reset_flow.py` en L0.

---

## 7. Décisions produit réservées (humain, pas agent)

1. **Rewrite vs overlay du System NAWA Password Reset.** Recommandation :
   overlay / System jumeau `nawa_password_reset_agent_loop_v1` jusqu'à parité
   de la scenario matrix. Toucher le seed prod = décision auteur.
2. **`act` en prod PIH.** Le contrat dit non par défaut. Un workspace lab CoE
   peut l'allumer explicitement.
3. **Nœud Goal séparé vs Goal-dans-le-loop.** L1 embarque Goal dans
   `AgentLoopNodeConfig`. Un nœud `goal` déclaratif (pass-through canvas) n'est
   justifié que si Fayçal veut le voir comme carte « objectif ≠ chemin ».
4. **Table Mandate signée / révocation 1-clic.** Hors de ce plan (gouvernance
   PIH / decks). L3 compile l'enveloppe déjà persistée.
5. **Andritz Chat Agentic collapse.** Politique : seulement après L2 + goldens
   password reset. Ce graphe est un actif de démo, pas un bac à sable.

---

## 8. Risques et anti-patterns

| Risque | Parade |
|---|---|
| « AgentLoop = `loop` + un if » | kinds séparés ; `_run_loop` inchangé |
| Le modèle invente un slug | coerce + gate spine ; test dédié |
| Write avant gate « pour gagner une latence » | `_execute_task_node` write seulement après gate du tour |
| Contrat publié vide (leçon 08/08) | tester `execution_contract.nodes.agent_loop.allowlist` **non vide** |
| Palette qui explose (anti-Fayçal) | **un** nœud `Agent loop` + HITL ; pas Goal/Commit/Eval/InvokeSkill |
| Steering qui tue le run | L4 skip les tools non démarrés, jamais les committed |
| Mémoire cross-BU | observations **bornées au Run** ; pas de MEMORY.md |
| L5 trop tôt | fan-out interdit tant que L2 n'a pas le resume intra-loop |

---

## 9. Tests — critère d'arrêt par tranche

Socle à ne pas casser :

- `backend/app/tests/services/test_nawa_password_reset_flow.py`
- tests DAG existants (`test_run_engine_dag_e2e.py` et voisins)
- Playwright `frontend-ng/e2e/tests/03-hitl-approve.spec.ts`
- `python3 scripts/agentium_compliance.py --check` sur les fichiers touchés

Goldens **nouveaux** (L1+) — 4 scénarios minimum, même esprit que la matrix
password reset :

1. Happy path recommend-only → `complete` sans HITL
2. Write demandé → HITL → accept → `complete` + audit
3. Write demandé → reject → `blocked`, zéro side-effect
4. Budget turns épuisé → `blocked` / `ask_human`, zéro write

Mesure : compter les `SkillInvocation` et les checkpoints `agent_loop_turn`,
pas « le run est green ».

---

## 10. Hors plan (rappel)

- Implémenter OpenClaw, Lobster, ou un second moteur à côté de `dag.py`
- Skills générées par l'agent en production
- Shell / code-interpreter
- Refactor opportuniste de `dag.py` hors `_run_agent_loop` et points
  d'extension listés
- Calendrier en jours / semaines — l'ordre L0→L5 **est** le plan

---

## 11. Message slide (Fayçal / Mounir) — 6 lignes

1. OpenClaw impressionne parce que **le prochain pas est libre**.
2. PIH n'achète ça que si **les effets de bord ne le sont pas**.
3. Agentium : *enveloppe déterministe, intérieur mou*.
4. Un nœud `Agent loop` remplace le DAG de 20 cases ; le ledger garde chaque tour.
5. Le modèle choisit une skill **parmi 5–8** déjà filtrées par le mandate.
6. Un write SAP / AD / ITSM = HumanGate + resume, jamais restart, jamais shell.

Ce fichier est le plan de dev. La spec exécutable de L0 est §3.1. La spec
exécutable de L1 est §3.2. Tout le reste attend que L0 soit vert.
