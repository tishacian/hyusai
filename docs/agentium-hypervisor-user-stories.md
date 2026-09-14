# User stories : Hyperviseur Agentium

> Format repris des spécifications papAI (`USER_STORY_HYPERVISOR`,
> `MVP_HYPERVISOR_COMEX`) : macro-story, epics, `En tant que / je veux /
> afin de`, critères d’acceptation, données, priorités.
>
> Les objets changent. **Suite / Workflow / App / AI Service** deviennent
> **System / Capability / Experience / Run / Decision**. L’Hyperviseur
> n’est plus « une App papAI » : c’est le **grand livre du portefeuille**
> (`/hypervisor`, rail **Impact** si l’adoption est active).
>
> Légende statut : **Livré** (sur `demo/agentic`) · **Partiel** ·
> **Spécifié** (contrat, pas encore le comportement).
>
> Normatif : [`mental-model.md`](./mental-model.md),
> [`agentium-reference.md`](./agentium-reference.md),
> [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md).
> MVP COMEX : [`agentium-hypervisor-mvp-comex.md`](./agentium-hypervisor-mvp-comex.md).
> EN : [`agentium-hypervisor-user-stories.en.md`](./agentium-hypervisor-user-stories.en.md).
>
> Word : [`agentium-hypervisor-user-stories.fr.docx`](./agentium-hypervisor-user-stories.fr.docx).

---

## 0. Macro user story

En tant que dirigeant ou décideur, je veux piloter le portefeuille de
**Systems** Agentium depuis l’Hyperviseur : observer ce qui a été exécuté
et sur quelle preuve (mesuré / déclaré / absent), consommer les
applications publiées dans **Work**, monitorer les **Runs** sans les
confondre avec le succès métier, et décider — enregistrer un **signal**
dans l’Hyperviseur, signer un **gate humain** dans un Studio, ou enacter
une policy bornée via **Steer** (`Simuler → Approuver → Agir → Mesurer`) —
afin d’industrialiser l’IA comme un objet de management, **sans inventer
un zéro** et **sans que le modèle ne signe à ma place**.

---

## 1. Vue d’ensemble

### 1.1 Problème résolu

Sans l’Hyperviseur Agentium, le COMEX n’a pas de registre de ce que les
Systems ont réellement rendu. Les équipes n’ont pas de canal gouverné pour
faire remonter une preuve (Run, base de valeur, décision). La gouvernance
IA retombe sur des échanges informels, ou sur un « ROI » chrome qui
invente un zéro.

papAI traitait ça comme un flux **top-down / bottom-up** entre décideur et
builders, via Suites et Workflows. Agentium reprend le flux, sur d’autres
objets : le **bas** ce sont les Runs et les Experiences publiées ; le
**haut** ce sont les objectifs opérationnels, les Decisions et la boucle
de valeur.

### 1.2 Proposition de valeur

| Capacité | Description Agentium |
|---|---|
| Grand livre | Consolider Runs, coûts mesurés, valeur déclarée, états `not_measured` / `not_configured` |
| Objectifs top-down | Objectif opérationnel borné sur un System (`operational_objective`) |
| Remontées bottom-up | Runs, bases de valeur, Experiences Work, file de revue |
| Décisions | `proposed → accepted \| rejected` ; enactment **hors** Hyperviseur |
| Boucle de valeur | Steer : `Outcome → Decision → Simulate → Approve → Act → Measure` |
| Compagnon | Conversation première classe, mêmes droits, le modèle ne signe pas |
| Gouvernance | IAM, audit, Membrane ; jamais « prompt only » |

### 1.3 Personas

| Persona | Rôle Agentium | Surface |
|---|---|---|
| Dirigeant (Sarah) | Observer le portefeuille, signer les signaux, allouer | `/hypervisor` |
| Steward (Mehdi) | Encadrer, enacter via Steer | `/systems/:id?lens=steer` |
| Builder (Alex) | Composer et publier un System / une Experience | `/create`, `/systems/new` |
| Métier (Claire) | Consommer, citer, signer un gate | `/work`, Studio |
| Gouvernance (Nadia) | Audit, accès | `/governance/audit`, `/governance/access` |

`Work ↔ Cockpit` est un lien RBAC, pas un thème. Ne pas dire Desk, Board,
workflow, pipeline, job, HITL (dire **Flow**, **Run**, **approbation
humaine**).

### 1.4 Gating — flags, pas d’édition PRO

Agentium n’a pas le couple Standard / PRO de papAI. Le périmètre se
contrôle par flags workspace :

| Flag | Effet |
|---|---|
| `experience_v1` | Work / Experiences |
| `adoption_experience_v1` | Entrée métier, rail Impact, guides, compagnon — **off** par défaut, **non accepté** |
| `hypervisor_v2` | Grand Livre (sinon v1 bilan de valeur) |
| `value_loop_v1` + canari System | Enactment Simulate → Measure |

### 1.5 Correspondance papAI → Agentium

| papAI | Agentium | Ne pas reprendre tel quel |
|---|---|---|
| Suite / Workflow | System lié à une Capability | « KPI Suite » |
| App Hyperviseur | Surface Cockpit `/hypervisor` | « première App système NextJS » |
| Target chiffré € | `operational_objective` (5 métriques) + base de valeur **déclarée** | ROI chrome = vérité financière |
| Directive + acquittement | Decision + gate Studio + boucle de valeur | Workflow d’acquittement type papAI |
| Proposal / Alert / Insight | Decision (`recommendation`, `review_required`, `value_loop`) | Six types de formulaires |
| Agent stratégique + tools d’action | Compagnon (`inspect_system`, `compare_runs`, `read_operational_metrics`) | `send_directive()` depuis le chat |
| AI Service health | Diagnostics + Runs — santé **technique** | Score « Healthy » = succès métier |
| Pipeline KPI 4 étapes | Publication Experience + évaluation + Run | Custom Metric Python depuis l’Hyperviseur |
| Gating PRO banner | Flags workspace | Édition payante Standard/PRO |

---

## 2. Epic 1 — Grand livre (agrégation)

### US-AHYP-100 : Voir ce que le portefeuille a rendu

**Statut : Partiel** · **P0**

En tant que dirigeant, je veux voir, sur la période choisie, ce que le
portefeuille a exécuté et sur quelle preuve, afin d’évaluer l’impact sans
prendre un zéro inventé pour une mesure.

Critères d’acceptation :

- [ ] `/hypervisor` affiche Runs, outcomes, coût et valeur avec un
      fact-state explicite : `available` · `not_measured` ·
      `not_configured` · `restricted` · `unavailable`
- [ ] Une donnée absente n’est **pas** rendue comme 0 € / 0 h
- [ ] v1 : hero « valeur nette » qualifié de **modèle de ROI des
      capacités** (estimé − coût), pas d’attestation financière
- [ ] v2 (`hypervisor_v2`) : légende *encre = mesuré · teal = déclaré* ;
      strates Comprendre → Détailler → Décider
- [ ] La décomposition par System / Capability est cliquable vers le
      détail (Runs ou System)
- [ ] Le ROI affiché est **supprimé** si le coût est quasi nul, et plafonné

Données : `GET /hypervisor/balance-sheet`, `GET /hypervisor/series`,
`GET /hypervisor/value-bases`.

### US-AHYP-101 : Choisir la période d’observation

**Statut : Livré** · **P0**

En tant que dirigeant, je veux choisir la fenêtre (30 j, 90 j, WTD / MTD /
QTD selon la version), afin de comparer sans changer d’objet.

Critères d’acceptation :

- [ ] Le sélecteur est dans le chrome de `/hypervisor`
- [ ] Tous les blocs (hero, registre, décisions, séries) se recalculent
- [ ] v2 : vue Direction = 90 j / heures ; Operations = 30 j / runs ;
      Conformité = 90 j / runs

### US-AHYP-102 : Lire les bases de valeur

**Statut : Livré** · **P0**

En tant que dirigeant, je veux voir quelles Capabilities ont une base de
valeur signée, datée, versionnée, afin de savoir ce qui est déclaré et ce
qui n’a que l’unité native (runs, heures).

Critères d’acceptation :

- [ ] `GET /hypervisor/value-bases` liste les bases (`declared` |
      `measured` | `none`)
- [ ] Sans base : unité native, pas d’euro fabriqué
- [ ] Une base déclarée n’est **pas** une mesure Lot 8

### US-AHYP-103 : Distinguer v1 et v2 sans raconter la même histoire

**Statut : Livré** · **P1**

En tant que steward, je veux que le flag `hypervisor_v2` choisisse le
composant, afin de ne pas promettre le bandeau de boucle de valeur
portefeuille sur le Grand Livre.

Critères d’acceptation :

- [ ] Flag absent / false → v1 (bilan + agrégat `GET /hypervisor/value-loop`)
- [ ] Flag true → v2 (pas d’agrégat value-loop)
- [ ] v1 affiche *Une simulation n’est pas une mesure* sur l’agrégat

---

## 3. Epic 2 — Objectifs top-down

### US-AHYP-200 : Fixer un objectif opérationnel sur un System

**Statut : Livré** · **P0**

En tant que dirigeant ou owner, je veux fixer un objectif opérationnel
borné sur un System (métrique, cible, fenêtre 1–90 jours, owner,
référence de comparaison), afin de donner un cap **sans prétendre à un
ROI économique**.

Critères d’acceptation :

- [ ] Métriques autorisées uniquement :
      `completed_volume` · `mean_duration_ms` · `human_waits` ·
      `human_validation_rate` · `measured_cost_usd`
- [ ] Écriture protégée (admin System) ; un PATCH métier est refusé
- [ ] L’UI Impact / overview System affiche l’objectif et *Non mesuré* /
      *Impact économique non attesté ici* le cas échéant
- [ ] Ce n’est **pas** le Target € papAI, ni O5 (heures / argent
      économisés)

Données : `System.settings.operational_objective`
(`backend/app/schemas/operational_objective.py`).

### US-AHYP-201 : Voir la progression vers l’objectif

**Statut : Partiel** · **P0**

En tant que dirigeant, je veux voir l’écart entre la mesure opérationnelle
et la cible, afin de savoir si le System est dans la fenêtre.

Critères d’acceptation :

- [ ] Valeur observée vs cible, unité native de la métrique
- [ ] Un zéro mesuré (vrai 0 runs) ≠ `not_measured`
- [ ] Pas de badge « On track » économique dérivé d’un Run terminé

### US-AHYP-202 : Modifier ou retirer l’objectif

**Statut : Livré** · **P1**

En tant que owner, je veux changer la cible, la fenêtre ou retirer
l’objectif, afin d’ajuster le cap. L’audit conserve l’écriture.

### US-AHYP-203 : Voir les Systems sans objectif ni base

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux voir les Systems qui n’ont ni objectif
opérationnel ni base de valeur, afin de relancer les owners plutôt que
d’afficher un portefeuille « à 0 € ».

---

## 4. Epic 3 — Décisions (signal portefeuille)

### US-AHYP-300 : Voir ce qui attend une signature

**Statut : Livré** · **P0**

En tant que dirigeant, je veux la file des `Decision` `proposed`, afin de
savoir ce qui attend un humain.

Critères d’acceptation :

- [ ] `GET /hypervisor/decisions` paginé, filtrable par `kind` et `status`
- [ ] Carte : titre, justification, impact **estimé**, cible
      (System / Capability / Run), dates
- [ ] Copy v2 : *Ce qui attend une signature* ; file vide = *le
      portefeuille n’attend pas de signature*
- [ ] `kind` observés : `recommendation`, `review_required`, `value_loop`

### US-AHYP-301 : Accepter ou rejeter — signal seulement

**Statut : Livré** · **P0**

En tant que dirigeant, je veux accepter ou rejeter une Decision proposée,
afin d’enregistrer un **signal de décision** tracé.

Critères d’acceptation :

- [ ] `POST .../accept` : `proposed → accepted`
- [ ] `POST .../reject` : `proposed → rejected`
- [ ] Provenance humaine (`human_confirmed_by` / `at`) quand l’UI l’exige
- [ ] Une Decision liée à `scenario_id` **refuse** ce chemin (orchestrateur
      de valeur)
- [ ] L’UI **n’offre pas** « Appliquer » comme enactment portefeuille
- [ ] `POST .../apply` répond **409** `LEGACY_DECISION_ACTUATOR_DISABLED`

Phrase à tenir : *Valider ici enregistre un signal. Modifier un System
passe par Steer.*

### US-AHYP-302 : Scanner des recommandations

**Statut : Livré** · **P1**

En tant que dirigeant, je veux lancer SCAN (`POST /hypervisor/recommendations/generate`)
et voir les recommandations, afin de nourrir la file sans les prendre pour
des mesures.

### US-AHYP-303 : Signer un gate dans Work / Studio

**Statut : Livré** · **P0**

En tant que métier ou décideur opérationnel, je veux accepter ou refuser
un gate sur une application publiée (Studio), afin que l’exécution
attende un humain.

Critères d’acceptation :

- [ ] Le modèle **ne peut pas** accepter (`POST /assistant/decisions`
      exige l’action UI et l’id observé ; décision périmée → refus)
- [ ] File `/steering/review-queue` pour les revues d’évaluation
- [ ] Audit : provenance humaine

---

## 5. Epic 4 — Enactment (boucle de valeur)

### US-AHYP-400 : Enacter via Steer, pas via l’Hyperviseur

**Statut : Livré (canari)** · **P0**

En tant que steward, je veux exécuter
`Outcome → Decision → Simulate → Approve → Act → Measure` sur **un**
System, afin de changer une policy de façon bornée et prouvée.

Critères d’acceptation :

- [ ] Gate : `features.value_loop_v1` **et** activation System
      (`settings.experience.value_loop_canary = "v1"` en canari)
- [ ] Surface : `/systems/:id?lens=steer` — pas `/hypervisor`
- [ ] Actionneur unique : `control_policy.guardrails.patch.v1` + Membrane
      `enforce` ; sinon `not_configured`
- [ ] Baseline = Run `runtime_auto` ; seed / opérateur **refusés**
- [ ] `simulation_is_measurement: false`
- [ ] Une mesure ne clôt que sur un Run post-action observé

### US-AHYP-401 : Lire l’agrégat portefeuille sans le confondre avec une mesure

**Statut : Livré (v1 seulement)** · **P1**

En tant que dirigeant, je veux voir sur v1 le Δ observé, les risques et
les scénarios agrégés, afin de forer vers le System — pas pour raconter
« le portefeuille a simulé donc on a gagné ».

---

## 6. Epic 5 — Remontées bottom-up (Work, Runs, Knowledge)

### US-AHYP-500 : Publier une Experience consommable

**Statut : Livré** · **P0**

En tant que builder, je veux publier une Experience liée à une version de
System, afin que le métier consomme dans `/work/:slug` sans jargon moteur.

Critères d’acceptation :

- [ ] Cycle Experience : Draft → Release immuable → Deployment
      (Pilot | In service)
- [ ] Le métier entre par Work, pas par `/systems/:id`
- [ ] Flag `experience_v1`

### US-AHYP-501 : Faire remonter une preuve (Run)

**Statut : Livré** · **P0**

En tant que métier ou builder, je veux qu’une exécution produise un Run
(coût éventuel, contexte, lignée, provenance), afin que l’Hyperviseur ait
quelque chose à agréger.

Critères d’acceptation :

- [ ] Deep link `/runs/:id` depuis Work, compagnon, Hyperviseur
- [ ] *Terminé ≠ réponse validée ≠ gain économique*
- [ ] Diagnostics (débit, latence) restent derrière un disclosure
      « santé technique »

### US-AHYP-502 : Déclarer une base de valeur (bottom-up gouverné)

**Statut : Livré** · **P1**

En tant que steward, je veux déclarer une base (`value_per_unit`,
`hours_per_unit`, auteur, statut `declared`), afin que le Grand Livre
puisse convertir des outcomes **sans inventer une mesure**.

### US-AHYP-503 : Voir les Systems silencieux

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux voir l’absence de Runs récents comme un
trou, pas comme une performance nulle.

---

## 7. Epic 6 — Compagnon (ex-« agent stratégique »)

### US-AHYP-600 : Interroger le portefeuille en langage naturel

**Statut : Partiel** · **P1**

En tant que dirigeant ou métier, je veux poser une question scopée à des
Systems autorisés, afin d’inspecter sans naviguer — **avec les mêmes
droits que l’UI**.

Critères d’acceptation :

- [ ] Compagnon Work + Cockpit ; scope 0–10 `system_ids` ; scope vide =
      découverte, pas de lancement
- [ ] Tools lecture : `inspect_system`, `compare_runs`,
      `read_operational_metrics`
- [ ] Lancement / approbation = services canoniques, pas un orchestrateur
      parallèle
- [ ] Citations / preuves d’action quand un System a tourné
- [ ] Guides `/help/{start,sources,systems,runs,value}`

### US-AHYP-601 : Empêcher le modèle de signer

**Statut : Livré** · **P0**

En tant que gouvernance, je veux qu’aucun tour de modèle n’accepte un
gate, afin de garder la décision humaine.

### US-AHYP-602 : Avertir du périmètre

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux voir le scope (Systems, workspace, tools
disponibles ou non), afin de ne pas croire à un agent omniscient.
`send_directive` / `forecast_value` papAI sont **hors contrat**.

---

## 8. Epic 7 — Attention et tendances

### US-AHYP-700 : Voir ce qui demande une attention

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux agréger : décisions `proposed`, objectifs
hors fenêtre, Systems `not_configured`, risques de boucle de valeur — afin
de réagir. Pas un « AI Service Down » papAI pris pour un échec métier.

### US-AHYP-701 : Lire une tendance sans projection = mesure

**Statut : Partiel** · **P2**

En tant que dirigeant, je veux les séries v2 (rivières, cadran, Sankey)
jour par jour. Une projection ou un what-if portefeuille **n’est pas
livré** (`POST /hypervisor/what-if` → `not_configured`). Une barre en
pointillés « mois futur » papAI est **hors contrat** tant qu’elle n’a pas
de provenance.

### US-AHYP-702 : Exporter un rapport COMEX

**Statut : Spécifié** · **P2**

En tant que dirigeant, je veux exporter la période (PDF / CSV) : registre,
bases, décisions, disclaimer mesuré/déclaré/absent. **Pas livré.**

---

## 9. Epic 8 — Gouvernance

### US-AHYP-800 : Contrôler qui observe, qui décide, qui enacte

**Statut : Livré** · **P0**

En tant qu’admin, je veux séparer : lecture Hyperviseur · accept/reject ·
écriture d’objectif · Act Steer · publication Work. Le mode workspace
(`builder` / `operator` / `executive`) change la **densité**, pas les
droits IAM.

### US-AHYP-801 : Tracer

**Statut : Livré** · **P0**

En tant que gouvernance, je veux dans `/governance/audit` : accept/reject,
gates humains, progrès d’adoption (métadonnées seulement), écriture
d’objectif, étapes de boucle de valeur. Chaque entrée : acteur, action,
objet, timestamp.

### US-AHYP-802 : Isoler Mission Room

**Statut : Livré** · **P0**

En tant que produit, je veux que `/hypervisor/mission-room/*` reste une
**application de workspace** (Sentinel / Octocity / générique), afin de ne
pas la spécifier comme le grand livre.

---

## 10. Epic 9 — Honnêteté et adoption

### US-AHYP-900 : Refuser le zéro inventé

**Statut : Livré** · **P0**

En tant que produit, je veux que chrome et API refusent de fabriquer un
total financier de substitution. O5 (heures / argent économisés) reste un
**trou d’acceptation**.

### US-AHYP-901 : Entrer par Work

**Statut : Livré (flag off)** · **P1**

En tant que métier, je veux un premier résultat vérifiable (NorthForge,
4 étapes, 10 min seules — **cible non mesurée**) sans ouvrir le Cockpit.
`adoption_experience_v1` off par défaut ; 10 sessions **non tenues**.

---

## 11. Hors scope (repris et actualisé)

- Enactment portefeuille (« Appliquer » sur `/hypervisor`)
- What-if / leviers live / impact preview < 300 ms
- Directives papAI (types Urgent/Strategic, escalade, webhook Broadcast)
- Pipeline Custom Metric depuis l’Hyperviseur
- Gating Standard / PRO + banner upgrade
- LLMOps « AI Service » comme objet de santé métier
- Partage inter-workspace
- Favoris KPI (papAI US-HYP-802) — non spécifié Agentium
- Mission Room = Hyperviseur

---

## 12. Récapitulatif

Légende priorités : **P0** must COMEX · **P1** should · **P2** plus tard.

| ID | Epic | Titre | P | Statut |
|---|---|---|---|---|
| US-AHYP-100 | Grand livre | Voir ce que le portefeuille a rendu | P0 | Partiel |
| US-AHYP-101 | Grand livre | Choisir la période | P0 | Livré |
| US-AHYP-102 | Grand livre | Lire les bases de valeur | P0 | Livré |
| US-AHYP-103 | Grand livre | Distinguer v1 / v2 | P1 | Livré |
| US-AHYP-200 | Objectifs | Fixer un objectif opérationnel | P0 | Livré |
| US-AHYP-201 | Objectifs | Voir la progression | P0 | Partiel |
| US-AHYP-202 | Objectifs | Modifier / retirer | P1 | Livré |
| US-AHYP-203 | Objectifs | Systems sans objectif ni base | P1 | Partiel |
| US-AHYP-300 | Décisions | File des signatures | P0 | Livré |
| US-AHYP-301 | Décisions | Accept / reject = signal | P0 | Livré |
| US-AHYP-302 | Décisions | SCAN recommandations | P1 | Livré |
| US-AHYP-303 | Décisions | Gate Work / Studio | P0 | Livré |
| US-AHYP-400 | Enactment | Steer Simulate → Measure | P0 | Livré (canari) |
| US-AHYP-401 | Enactment | Agrégat v1 ≠ mesure | P1 | Livré |
| US-AHYP-500 | Bottom-up | Publier une Experience | P0 | Livré |
| US-AHYP-501 | Bottom-up | Preuve Run | P0 | Livré |
| US-AHYP-502 | Bottom-up | Déclarer une base | P1 | Livré |
| US-AHYP-503 | Bottom-up | Systems silencieux | P1 | Partiel |
| US-AHYP-600 | Compagnon | Question scopée | P1 | Partiel |
| US-AHYP-601 | Compagnon | Le modèle ne signe pas | P0 | Livré |
| US-AHYP-602 | Compagnon | Avertir du périmètre | P1 | Partiel |
| US-AHYP-700 | Attention | File d’attention | P1 | Partiel |
| US-AHYP-701 | Attention | Tendance sans fausse projection | P2 | Partiel |
| US-AHYP-702 | Attention | Export rapport COMEX | P2 | Spécifié |
| US-AHYP-800 | Gouvernance | IAM observe / décide / enacte | P0 | Livré |
| US-AHYP-801 | Gouvernance | Audit | P0 | Livré |
| US-AHYP-802 | Gouvernance | Mission Room isolée | P0 | Livré |
| US-AHYP-900 | Honnêteté | Pas de zéro inventé | P0 | Livré |
| US-AHYP-901 | Adoption | Entrée Work | P1 | Livré (flag off) |
