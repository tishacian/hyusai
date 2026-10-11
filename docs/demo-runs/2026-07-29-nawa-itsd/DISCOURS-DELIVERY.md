# Discours — process de delivery & offre technique
## Service Help Desk PIH · à partir de l'offre v8 + Price Schedule v6 + templates méthodo

À dire après la démo produit (NAWA WE / Agentium), quand on bascule sur le *comment on livre*.
Durée indicative : **6–8 minutes**. Les montants restent au niveau de principe sauf si on ouvre le Price Schedule.

---

## Catch phrases (EN) — à planter dans le discours

**Headline (la phrase à retenir)**
> Progressive go-live from October. No cutover risk.

**Ouverture**
> This is not a big bang — it's a controlled ramp.
> We don't switch off the desk. We add capability wave by wave.
> No weekend cutover. No single-shot migration. No all-or-nothing.

**Architecture / coexistence**
> ManageEngine stays the system of record. Agentium sits on top.
> We extend ITSM — we don't replace it.
> Intelligence above the desk, not instead of the desk.

**Vagues / rollout**
> From October: foundation first, then waves into production.
> High volume, low risk first — prove value, then scale.
> Privileged use cases come later — with stronger gates, not faster shortcuts.
> Every wave earns the right to the next one.
> Stoppable at every wave. Nothing locked in beyond what we've proven.

**Quality / factory**
> Not 39 rebuilds — ~10 reusable patterns.
> No use case goes live without a quality gate.
> Buildable. Governable. Testable. — then production.
> Parallel run before privileged write. Always.

**Méthodo (BR → TOM → QA)**
> Business Requirements say *why*. The Operating Model says *how*. The Acceptance Record says *go*.
> Requirements → operating model → signed acceptance — then production.
> If it isn't in the golden set, it isn't ready.

**Commercial**
> Staged commitment: you buy the pilot, then you buy the results.
> Engage wave by wave — on measured outcomes, not promises.
> No per-employee licence. Cost follows value, not headcount.
> If you stop after the pilot, that's the only amount due.

**Clôture**
> Progressive. Controlled. Stoppable. — that's the delivery model.
> Production without cutover — that's the promise.

---

### 1. L'idée centrale (30 s)

Ce qu'on vient de montrer n'est pas un big-bang.

On ne remplace pas ManageEngine, on ne coupe pas le desk un week-end, et on ne livre pas les 39 use cases d'un coup.

**Le principe : mise en production progressive et maîtrisée, vague par vague, à partir d'octobre — sans risque de cutover.**

Chaque vague met en prod un lot de services, derrière des portes qualité. Si une vague s'arrête, le desk continue exactement comme avant. Ce n'est pas une bascule : c'est une montée en charge contrôlée.

---

### 2. Pourquoi ce modèle (45 s)

PIH, c'est environ 12 200 utilisateurs, 145+ sociétés, 25 pays, ~5 800 tickets / mois — plus le volume déjà absorbé par les 39 automatisations.

Sur ce périmètre, un cutover unique est le vrai risque : trop de connecteurs, trop de règles d'identité, trop de canaux, trop de populations.

Donc on sépare deux choses :

- **ManageEngine reste le système de record** — tickets, SLA, approvals, reporting.
- **Agentium est la couche d'orchestration et d'agents** — conversation, automation gouvernée, évaluation, audit, replay.

On déploie l'intelligence *au-dessus* de l'ITSM, pas à la place. Les opérations existantes ne sont jamais interrompues.

---

### 3. Le calendrier en vagues (2 min)

Calendrier indicatif — dates confirmées à la signature. Lecture pour un démarrage autour d'octobre :

| Vague | Timing indicatif | Ce qu'on met en prod | Porte de sortie |
| --- | --- | --- | --- |
| **Phase 0 — Foundation** | semaines 1–6 | environnements, modèle de sécurité, ManageEngine + Entra + Teams, ingestion knowledge, golden sets | architecture validée, connecteurs smoke-testés |
| **Wave 1 — Pilot** | mois 2–3 | un exemplaire de chacun des **4 patterns fondateurs** qui couvrent les 39 use cases, sur une population représentative limitée | deflection mesurée vs baseline, UAT signée, hypercare ≥ 30 jours |
| **Wave 2 — Core rollout** | mois 3–6 | migration des 39, écritures privilégiées sous mandates, connecteurs restants | quality gate **par use case**, parallel-run, PV de recette |
| **Wave 3 — Scale & proactive** | mois 6–8 | multi-entité / multi-pays, RCA & tendances étendus | KPI cockpit réconcilié avec le run ledger, autonomie ops PIH |

**Les 4 patterns du pilot** (ce qu'on prouve avant d'industrialiser) :

1. deflection conversationnelle live ;
2. opérations proactives & RCA sur l'historique ServiceDesk Plus ;
3. identity & access lifecycle en parallel-run / simulate ;
4. un flux d'approbation orchestré de bout en bout.

Principe de priorisation : **volume élevé + risque bas d'abord** pour montrer de la valeur vite ; les use cases sensibles (identité, onboarding/offboarding, mailbox, VPN/AVD, firewall) viennent ensuite, avec HITL renforcé et audit.

Après chaque vague : **hypercare** — on ne mesure pas seulement le go-live technique, on mesure l'adoption et la fiabilité opérationnelle.

---

### 4. Comment chaque use case est fabriqué — la factory (1 min)

Ce n'est pas 39 projets. C'est une **factory** : le même cycle, répétable, pour chaque service.

Lifecycle : design détaillé → spécification → mapping connecteurs → validation sécurité → build → tests unitaires → intégration → UAT → préparation déploiement → **mise en prod** → monitoring → stabilisation → documentation.

Les 39 se décomposent en ~**10 patterns réutilisables** sur le Flow Builder. Wave après wave, le coût unitaire baisse : on *author* une seconde instance d'un pattern, on ne *rebuild* pas.

Et rien ne part en prod sans **quality gates** prédéfinis : exigences validées, tests verts, sécurité approuvée, procédures écrites, équipes formées, rollback prêt, monitoring prêt.

---

### 5. La méthodo documentaire — BR → TOM → QA (1 min 30)

Le process n'est pas improvisé. On le porte avec trois livrables méthodo — les mêmes qu'on utilise sur les autres programmes Agentium, alignés ISO/IEC 42001 et 12792 :

**1. Business Requirements** — le *pourquoi* et le *quoi*.
Persona, As-Is → To-Be, outcomes, règles métier, garde-fous (« never do this »), KPIs, hors-périmètre. Chaque exigence se mappe à une Capability / Skill Agentium et à un cas golden.

**2. Target Operating Model** — le *comment on opère*.
Canaux, value streams humain+agent, RACI, autonomie vs HITL, gouvernance (mandates, audit, quality gates), SLAs, rôle du CoE / Academy, roadmap de transition. C'est ce qui évite de livrer une techno sans modèle d'exploitation.

**3. QA Acceptance Record (PV de recette)** — le *droit d'aller en prod*.
Entry criteria, portes de qualification (scope, branches, RAG, replay, sécurité, mandates, connecteurs…), golden set, registre de défauts, décision signée : Accept / Accept with reservations / Reject.

La traceabilité est volontairement fermée :

> outcome métier → exigence → règle / décision → élément TOM → System Agentium → cas golden QA.

C'est ce qui rend chaque vague **buildable, governable and testable** — et c'est ce qui permet de dire non au cutover.

---

### 6. L'offre commerciale suit le même rythme (1 min)

Trois principes, alignés sur le Price Schedule v6 :

1. **Pas de licence par employé** — le coût ne suit pas les 12 200 users, il suit la valeur livrée.
2. **Engagement étagé** — à la signature, seul l'engagement initial est engagé (~USD 10k) : Phase 0-lite + pilot Wave 1. Les vagues suivantes sont pré-prixées et engagées **vague par vague, sur les résultats mesurés**. Si PIH s'arrête après le pilot, c'est le seul montant dû.
3. **Run plat et prévisible** — Option 1 IT : USD 25k / an · Option 2 IT + Employee Services (recommandée) : USD 80k / an. Ops du quotidien internalisées chez PIH via Datategy Academy ; infra sous contrôle PIH.

Build complet indicatif sur ~8 mois : ~50k (Option 1) / ~60k (Option 2). TCO 3 ans Option 2 conçu pour rester sous le spend conversationnel IT+HR actuel.

Ce n'est possible que parce que le build est porté par le **CoE AI & Data** (factory), sous oversight architecture / QA Paris, avec un effet pattern + delivery assistée par l'IA — pas un rabais.

---

### 7. Phrase de clôture (15 s)

En résumé : **octobre, on démarre la fondation ; dès la Wave 1, on met en production un premier lot prouvé ; ensuite on élargit vague par vague, use case par use case, avec BR, TOM et PV de recette à chaque porte.**

Pas de cutover. Pas de big-bang. Une mise en prod progressive, maîtrisée, et stoppable à chaque vague.

---

## Si on te challenge

| Question | Réponse courte |
| --- | --- |
| *Et si le pilot échoue ?* | On s'arrête. Seul l'engagement initial est dû. ManageEngine n'a jamais été remplacé. |
| *Pourquoi pas tout livrer en 3 mois ?* | Parce que les use cases privilégiés (identité, firewall, VPN) exigent parallel-run, mandates et HITL — les livrer trop tôt, c'est importer le risque qu'on veut éviter. |
| *Qui opère après ?* | PIH, formé via Academy. Datategy reste en editor support (run). AgentOps managé en option. |
| *Qui écrit les prochains use cases ?* | PIH, sur le Flow Builder, après handover — coût marginal. Pair-authoring possible dès Wave 2. |
| *Où est le PV ?* | Template QA Acceptance : gates ★ must-pass, golden set, signatures Business + IT + Governance + Delivery. |
| *Cutover ManageEngine ?* | Jamais. ManageEngine reste le système de record. On ajoute une couche, on ne bascule pas. |

## Ce qu'il ne faut pas faire dans ce discours

- Annoncer des dates calendaires fermes (septembre / novembre / Q2) comme contractualisées — elles sont **illustratives**, confirmées à la signature.
- Sortir le détail jour/rôle du Price Schedule sauf si on ouvre l'annexe.
- Laisser entendre qu'Agentium remplace ManageEngine.
- Promettre les 39 en prod dès le pilot — le pilot prouve **4 patterns**, pas 39 services.
