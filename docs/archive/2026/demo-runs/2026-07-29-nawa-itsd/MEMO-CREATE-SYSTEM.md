# Parcours clics — créer un System (use case) from scratch

Vérifié sur le produit : `/systems/new` (form canvas) → `/systems/:id/flow`
(Flow builder). Workspace de démo : **Nawa**. Les Capabilities sont un
catalogue existant — le builder **exige** d'en choisir une ; il n'y a pas
aujourd'hui de « New capability » dans l'UI.

Deux chemins. Le **A** est celui à montrer (factory / industrialisé).
Le **B** est le brouillon libre (scratchpad → promote).

---

## Catch phrases (EN)

> Name it. Bind a capability. Every gate green — then create.
> Form first for the contract. Flow second for the behaviour.
> A System is not a chatbot — it's a governed executable.

---

## Chemin A — Form canvas → Flow (recommandé)

### 0. Prérequis (30 s)

1. Workspace pastille = **Nawa**
2. Scope sidebar = **BUILD**
3. (Optionnel) Knowledge : une collection déjà ingérée si tu veux du RAG
   (`/knowledge`). Sinon tu peux créer sans collection.

### 1. Entrée

| Clic | Où |
| --- | --- |
| Sidebar **BUILD** → **Systems** | `/systems` |
| **New system** (ou « Create your first system ») | `/systems/new` |

Tu arrives sur le canvas à 6 sections. Chaque section a un badge
`READY` / `PENDING`. Le bouton **CREATE SYSTEM** ne s'active que quand
toutes les gates sont vertes.

Gates **bloquantes** (les seules) :
- **Objective** → un nom non vide
- **Capability** → une capability sélectionnée

Skills / Context / Policy sont toujours « READY » (optionnels pour créer).

### 2. Objective

| Champ | Exemple démo |
| --- | --- |
| **Name** | `Shared Mailbox Creation` |
| **Objective** | `Create a shared mailbox after dual approval, then notify the requester.` |

→ la section passe **READY**.

### 3. Capability

Clique une carte Capability dans la liste (ex. une capability IT / automation
déjà au catalogue).

Effets auto :
- le **Name** se préremplit si tu l'avais laissé vide
- **Skills** se remplissent avec les skills bundlés de la capability
- les levers Policy (coût / confiance) peuvent s'ajuster

→ Capability **READY**.

> Si aucune capability ne colle : prends la plus proche et dis
> *« Capability is the value unit; the Flow is where we specialise the use case. »*

### 4. Skills (lecture, pas bloquant)

Vérifie le résumé : `N bundled · X stub · Y unbound`.

- **BOUND** = exécutable
- **STUB** = placeholder (ne crash pas la création, mais la run échouera sur ce nœud)
- Apps / connectors liés : lien **Manage apps** si un connecteur manque

Ne bloque pas **CREATE SYSTEM**.

### 5. Context (optionnel)

| Champ | Choix démo |
| --- | --- |
| Collections | coche une KB ITSD si tu veux du RAG |
| Pipeline | `OmniRAG` / `Hybrid` / `Direct LLM` |
| Reuse context | laisser vide = un Context neuf est créé au launch |

Sans collection : le System se crée quand même (pas de RAG).

### 6. Policy (optionnel — à montrer 20 s)

| Levier | Sens |
| --- | --- |
| Execution mode | `Real-time` (chat/API) · `Event-driven` · `Human-augmented`… |
| Max cost / latency / confidence | garde-fous runtime |
| Require citations | ON si RAG |
| Enable audit | ON |

### 7. Launch

1. Aside droite : **GATES 6 / 6**
2. Bouton vert **CREATE SYSTEM**
3. Toast : `"… is live"` → navigation vers `/systems/:id`

### 8. Author le use case dans le Flow

| Clic | Où |
| --- | --- |
| Sur la fiche System → **Flow** / ou depuis la file WE : **Flow Builder** | `/systems/:id/flow` |

Sur le canvas :

1. **FIT** / **ARRANGE** pour lire le graphe généré depuis le form
   (souvent Trigger → Retrieve → Generate → Output — squelette)
2. Remplace / étends : ajoute Decision, HITL (policy), Connector, Compliance
3. Clique un nœud → panneau droit **CONFIGURED** (skill, ports, params)
4. **SAVE**
5. **Versions** pour figer un snapshot
6. **Simulate** (client-side) pour un dry walk
7. **Execute** pour un vrai run (besoin System persisté — OK ici)
8. Puis **Runs** / **Open the full trace** / **Rerun**

> Phrase : *Form first for the contract. Flow second for the behaviour.*

### Raccourci : Switch to Flow avant CREATE

Si name + capability sont prêts, **Switch to Flow** :
- crée/sauve le draft System
- ouvre directement `/systems/:id/flow`
- utile si tu veux skipper le polish Policy et passer au graphe

---

## Chemin B — Scratchpad → TO SYSTEM

Pour un graphe libre sans passer par le form.

| Clic | Où |
| --- | --- |
| BUILD → **Flow builder** (ou `/orchestration`) | scratchpad |
| Composer le DAG (Trigger → … → Output) | canvas |
| **SAVE** (brouillon local scratchpad) | |
| **TO SYSTEM** | crée un System (`Promoted from scratchpad flow`) |
| Puis Execute / Versions / Runs | bound au System |

Limite : sur le scratchpad, **Execute** et **Versions** sont désactivés
tant que tu n'as pas promu (*promote first*).

---

## Séquence parlée « use case from scratch » (~4 min)

1. **Systems → New system** — *Name it. Bind a capability.*
2. Remplir Objective + Capability → gates green
3. Montrer Context (KB) + Policy (cost / HITL mode) en 20 s
4. **CREATE SYSTEM**
5. **Flow** — étendre le squelette, ouvrir un nœud, **SAVE**
6. **Execute** → ouvrir le run → **Rerun**
7. Catch : *A System is not a chatbot — it's a governed executable.*

---

## Ce qu'il ne faut pas faire en démo live

- Créer un System sur un **autre** workspace (Andritz / Aya) — isolation client
- Promettre « New capability from this screen » — pas dans l'UI aujourd'hui
- **Execute** sur le scratchpad sans **TO SYSTEM**
- Laisser un System de test nommé n'importe comment sur Nawa sans le retirer /
  le retirer après (*Systems → …*) si ce n'est pas le Password Reset
- S'éterniser sur la checklist « 49 warnings » du Flow Password Reset existant
  (sujet différent — voir MEMO-CLICS §3 bis)

---

## Mapping méthodo delivery ↔ clics produit

| Livrable méthodo | Où ça se matérialise dans l'UI |
| --- | --- |
| Business Requirements | Objective + Capability (+ objective text) |
| Target Operating Model | Policy (execution mode, HITL, audit) + Skills/apps |
| QA Acceptance / golden | Flow Simulate → Execute → Runs / Rerun + golden hors écran |
| Use case in a wave | Un System (+ flow versionné) promu vague par vague |

---

## From a blank canvas → Shared Mailbox Creation

Procédure client (classeur) — 6 étapes à matérialiser :

1. Requester submits creation request (name, purpose, members, approvals)
2. IT verifies Line Manager **and** IT Approver authorisation
3. Create shared mailbox in mail system
4. Assign members / permissions
5. Configure aliases if required
6. Confirm active + notify requester

### 1. Ouvrir un canvas vraiment vierge

| Clic | Effet |
| --- | --- |
| Sidebar **BUILD** → **Flow builder** | `/orchestration` — scratchpad |
| Si tu vois encore Objective → Retrieve → Generate → Output | c'est le **starter** par défaut (4 nœuds), pas un blanc |
| Toolbar → icône **clear / trash** (Clear) | `store.clear()` → canvas vide |

Workspace = **Nawa**. Ne touche pas Password Reset.

### 2. Poser le squelette (drag depuis la palette)

Palette = **SKILLS** (haut) + **PRIMITIVES** (bas).

Ordre de pose, de gauche à droite :

| # | Palette | Label à donner (double-clic / inspector) | Rôle métier |
| --- | --- | --- | --- |
| 1 | Primitive **Trigger** | `Inbound request` | Étape 1 — intake |
| 2 | Skill **Azure OpenAI** (BOUND) | `Classify & extract fields` | parse name, purpose, members |
| 3 | Primitive **Decision** | `Line Manager approved?` | 1ʳᵉ porte dual-approval |
| 4 | Primitive **Decision** | `IT Approver approved?` | 2ᵉ porte |
| 5 | Skill bound le plus proche d'une action directory / **ou** Azure OpenAI en mode « draft action » | `Create shared mailbox` | Étape 3 — **simulé en démo** (pas de connecteur M365 dédié bound aujourd'hui) |
| 6 | Skill **Audit Log** (BOUND) | `Write audit ledger` | preuve d'action |
| 7 | Skill Azure OpenAI | `Notify requester` | message de clôture |
| 8 | Primitive **Output** | `Ticket closed` | sink happy path |
| 9 | Primitive **Output** | `Rejected` | sink si Decision = no |

Relie les ports dans l'ordre. Branches **no** des Decision → `Rejected`.

**FIT** puis **ARRANGE** pour lisibilité.

### 3. Configurer chaque nœud (panneau droit)

Pour chaque nœud cliqué :

1. **Label** + description métier (copie la procédure, pas le jargon technique)
2. Sur les Decision : branches `yes` / `no` — condition sur un champ d'entrée
   (ex. `line_manager_approved == true`) tant que tu n'as pas de nœud HITL
3. Sur Azure OpenAI : prompt d'extraction / de notification
4. Sur Audit Log : ce qui est ledgered (mailbox name, members, approvers)

> HITL « pause run » (comme Password Reset) n'est **pas** une tuile de la
> palette primitives aujourd'hui. En canvas from-scratch, les **Decision**
> jouent les portes ; le pattern `policy` / `hitl_pending` se réplique depuis
> un flow existant (Password Reset) ou arrive via le form **Human-augmented**.
> En démo : *« Dual approval is two gates — in production they pause the run
> for Line Manager then IT Approver. »*

### 4. Promouvoir en System

| Clic | |
| --- | --- |
| **SAVE** | brouillon scratchpad |
| **TO SYSTEM** | crée le System |
| Nommer | `Shared Mailbox Creation` |
| Objective | `Create a shared mailbox after dual approval, assign members, notify requester.` |

Tu quittes le scratchpad : **Execute** et **Versions** deviennent disponibles.

### 5. Jouer

1. **Simulate** — walk client-side des branches
2. **Execute** — vrai run (les nœuds LLM appellent le runtime ; la création mailbox reste dry-run / simulée tant qu'il n'y a pas de connecteur M365)
3. **Runs** → ouvrir la trace → **Rerun**

### Catch phrases

> Blank canvas. Same procedure as the workbook — six steps, two gates.
> Dual approval before any mailbox write.
> Promote when the graph tells the story — then Execute.

### Ce que tu ne peux pas prétendre from-scratch aujourd'hui

- Un connecteur **Exchange / M365 shared mailbox** bound comme `rpa_dispatch` du Password Reset — la création réelle reste **simulée** ou stub
- Un nœud HITL pause en un clic depuis la palette (utiliser Decision, ou dupliquer le pattern Password Reset)
- Brancher automatiquement le catalogue WE (`shared-mailbox-creation`) — ça, c'est entitlement / app NAWA, pas le Flow builder

### Variante plus rapide (si le scratchpad gêne)

1. `/systems/new` → Name `Shared Mailbox Creation` + Capability
2. **Switch to Flow** (crée le System + ouvre le graphe form-généré)
3. **Clear** le squelette Retrieve/Generate si tu veux repartir de zéro
4. Reposer le DAG ci-dessus, **SAVE**, **Execute**
