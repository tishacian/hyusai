# Retro — Training session Agentium (29/07/2026, ~14:32 CEST)

Source: `Agentium - Training Session - 2026_07_29 14_32 CEST - Transcript.docx`  
Participants: **Thibaud Ishacian**, **MoFaycal** (~38 min)  
Objet: construire un System **Shared Mailbox Creation** from scratch après création via form gates.

---

## Ce qui s’est passé (chrono)

| Temps | Fait |
| --- | --- |
| Début | Gates verts → **CREATE SYSTEM** → landing System → **Flow builder** (template capability) |
| ~5′ | Clear canvas → from scratch ; lecture procédure Excel IT Ops (6 steps) |
| ~8–12′ | Pose **Trigger** + **Azure OpenAI** ; question MoFaycal: *how to configure trigger for user input?* |
| ~12–15′ | Prompt classify/extract ; débat **structured / pydantic** output entre nœuds |
| ~15′ | Pose **Decision** (LM approved / null mailbox) ; picker vide / pas de valeur |
| ~20′+ | Blocage UX → bascule Showcase (SAP) pour montrer un System qui tourne |
| ~30′ | Feedback produit MoFaycal: System = backend sans front ; chat standard par System |
| Fin | Accord itération Qatar ; MoFaycal teste sur **Showcase**, pas Nawa |

---

## Frictions vécues en live (= dette UX / produit)

### F1 — Trigger : pas de sélecteur d’entrée utilisateur
**Dit en session:** *« from the UI I miss one dropdown to select the input trigger »*  
MoFaycal: webhook / API / chat ?

**Réalité produit:** Trigger palette = entry reasoning (`input_ref` au run). Event triggers (webhook, schedule, SFTP) existent en code mais **ne s’offrent pas** sur le nœud Trigger plain. Execute envoie `{}`.

**Accepté en session:** label + description ; « ce sera webhook/API ou chat intégré ».  
**À escalader:** sélecteur Trigger kind + formulaire `input_ref` / schema sur Execute.

### F2 — Structured output LLM non garanti entre nœuds
**Dit:** output JSON demandé dans le prompt ; MoFaycal veut pydantic-safe ; Thibaud: *schema check between nodes not configured in the UI*.

**Accepté:** « OK for POC if it doesn’t break often ».  
**À escalader:** output schema / JSON mode sur skill LLM + validation port-to-port (fail before Decision).

### F3 — Decision : picker `In` = « — unbound — »
**Dit:** *« Why don’t I have value here from the… »*  
Cause: pas d’ancêtres / mismatch type (`goal` string vs `in` object) ; pas d’éditeur de `branches`/`condition` dans l’inspector.

**Accepté:** improvise / explique / change de System.  
**À escalader:** éditeur de branches ; picker compatible object|string ; binding nommé (`line_manager_approved`) comme Password Reset JSON.

### F4 — Pas de parcours « inbound request → voir le résultat » lisible
MoFaycal: *walk me through a system that already works… inbound request… interact with it*.  
Terminal d’exécution montré ; pas convaincant comme UX métier.

**Accepté:** Showcase SAP + terminal.  
**À escalader:** surface chat/run par System (voir F5).

### F5 — « Backend without frontend » (demande produit majeure)
MoFaycal: chaque System = workflow backend + **chatbot frontend** standard ; input + steps + résultat dans le chat ; apps hand-coded (NAWA) = exception temporaire.

Thibaud: *100%, bricks exist (workspace chat + system dropdown), need wiring ; goal = product feature*.

**Accepté pour la session:** promesse d’itération.  
**À escalader (P0 produit):** System Chat Runner — trigger + transcript + HITL + outcome dans un chat lié au System.

### F6 — Terminology
MoFaycal: évoluer « System » → workflow self-contained (backend + chat front).  
Note: aligner wording delivery / UI sans casser le modèle mental Capability/Skill/System.

---

## Décisions de session — custom vs plateforme

| Sujet | Laissé custom / workaround | Escalader en feature Agentium |
| --- | --- | --- |
| Intake Shared Mailbox | Prompt texte dans le nœud Azure OpenAI | Skill « classify & extract » + JSON schema |
| Dual approval | Decision sur flags JSON (fragile) | HITL palette + dual gate template |
| User input | `input_ref` API / app dédiée (NAWA) | Trigger UI + Execute payload form |
| Résultat | Terminal Flow / app Angular hand-coded | **Chat surface per System** |
| Connecteurs M365 mailbox | Simulation / stub | Connector catalogue Exchange/M365 |
| Validation inter-nœuds | Confiance prompt | Port schemas + fail closed |
| Template capability au create | Clear canvas manuellement | « Blank canvas » option at create |

---

## Ce qui a bien marché (à garder dans le pitch training)

- Form `/systems/new` → gates verts → CREATE → Flow : chemin compris
- Clear canvas + palette Skills/Primitives : mental model « from scratch »
- Versions / rollback mentionnés
- Procédure Excel → nœuds : bon storytelling factory
- Accès Showcase pour MoFaycal ; itération terrain Qatar

---

## Incident post-session — Password Reset cassé (29/07 ~15h)

**Symptôme (capture 14:57):** le Flow Password Reset n’avait plus que le
squelette 4 nœuds (Objective → Retrieve → Generate → Output), badges
`MANIFEST ONLY`, checklist `task_no_skill` ×2. Cause probable : Clear canvas /
Import du starter pendant le training, puis **SAVE** sur le System live.

**Rollback UI:** le panneau Versions existe et l’API marche
(`POST /systems/{id}/versions/{version_number}/rollback`). Pièges UX qui font
dire « ça ne marche pas » :
1. Rollback est **disabled sur la version courante** (premier item) — il faut
   cliquer une version **plus ancienne**.
2. Après le Clear+Save, les versions récentes **sont le squelette cassé**
   (v18–v19 = 4 nœuds). Rollback « d’un cran » reste cassé. Il faut remonter à
   une version **29 nœuds** (ex. v16) ou utiliser `primary_flow_snapshot`.
3. Restore effectué le 29/07 soir → **v22 = 29 nœuds / 3 LLM** (depuis v16).

**Delete single node:** pas de bouton poubelle sur le nœud. La poubelle toolbar
= **Clear all**. Suppression unitaire = touche **Delete / Backspace** (hors
champ texte). Gap UX confirmé — à escalader: bouton Delete sur nœud sélectionné.

| Bug | Sévérité | Escalade |
| --- | --- | --- |
| Clear/Save écrase le flow prod sans confirm forte | P0 | Confirm dialog « replace live flow » + soft-lock demo Systems |
| Rollback non évident / perçu cassé | P0 | Label « Restore this version » sur v-1… ; disable reason tooltip |
| Pas de delete single-node button | P1 | Bouton Delete dans inspector + toolbar contextuelle |
| Trash icon = clear all | P1 | Icône/label « Clear canvas » distinct de Delete |

---

## Actions recommandées (post-training)

**Pour MoFaycal (Showcase, pas Nawa)**  
1. Rejouer Password Reset / un System avec **Run + trace** avant Shared Mailbox  
2. Shared Mailbox v0 minimal: Trigger → LLM → Output (texte « request received ») — comme il l’a demandé pour le mental model  
3. Ensuite seulement Decision + flags

**Pour le produit (ordre suggéré)**  
1. **P0** Execute / Run panel: éditeur `input_ref` (JSON ou form)  
2. **P0** Trigger inspector: kind (manual | webhook | schedule | chat)  
3. **P0** Decision: branch editor + fix type filter on `In`  
4. **P1** LLM JSON schema / structured output  
5. **P1** System-bound chat runner (la demande structurante de MoFaycal)  
6. **P2** HITL in palette ; blank-canvas create option  

---

## Catch phrases (EN) issues de la session

> The form creates the contract. The canvas creates the behaviour.  
> Trigger is the door — user input arrives as `input_ref` at run time.  
> Every System should feel like an app: chat in, steps visible, result out.  
> Terminal is for builders. Chat is for operators.
