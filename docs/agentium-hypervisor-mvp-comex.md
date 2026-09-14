# Hyperviseur Agentium, MVP COMEX : spécification exécutive

> Audience : COMEX, direction produit.
> Statut : traduction des concepts papAI (`MVP_HYPERVISOR_COMEX`) vers
> Agentium, **sans** reprendre le socle « 6 briques à construire avant
> l’App ». Ces briques existent déjà sous d’autres noms.
>
> User stories détaillées :
> [`agentium-hypervisor-user-stories.md`](./agentium-hypervisor-user-stories.md).
> Briefing : [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md).
> EN : [`agentium-hypervisor-mvp-comex.en.md`](./agentium-hypervisor-mvp-comex.en.md).
> Word : [`agentium-hypervisor-mvp-comex.fr.docx`](./agentium-hypervisor-mvp-comex.fr.docx).

---

## Vision en une phrase

L’Hyperviseur est le **grand livre** du portefeuille de Systems Agentium :
un dirigeant observe ce qui a été exécuté et sur quelle preuve, le métier
consomme des Experiences publiées, les Runs remontent une trace, un humain
décide (signal portefeuille, gate Studio, ou enactment Steer) — dans un
périmètre IAM + audit, **sans zéro inventé** et **sans que le modèle ne
signe**.

---

## 1. Ce que livre le MVP (aujourd’hui, `demo/agentic`)

| Brique papAI | Équivalent Agentium déjà là | Ce que le COMEX voit |
|---|---|---|
| Dashboard KPI / ROI | `/hypervisor` v1 ou v2 | Registre mesuré / déclaré / absent — pas un ROI audité |
| Objectifs top-down | `operational_objective` sur un System | Cinq métriques opérationnelles, 1–90 jours |
| Métriques bottom-up | Runs + bases de valeur + Work | Preuve d’exécution, pas un formulaire « publier un KPI » |
| Assistant IA | Compagnon de conversation | Lecture scopée ; **pas** `send_directive` |
| Catalog / KB | Knowledge + Experiences | Sources citées depuis Work |
| Socle App | Cockpit + Work (pas une App NextJS) | `/hypervisor` et `/work` |
| Gouvernance | IAM + `/governance/audit` | Qui observe, qui décide, qui enacte |

**P0 à montrer en séance (hard-reload) :**

1. Work — une question, une citation. *Consommer.*
2. Run — la preuve. *Monitorer : pas le gain.*
3. `/hypervisor` — légende + une Decision `proposed`. *Observer / signal.*
4. Steer **seulement** si `value_loop_v1` est réellement on. Sinon le dire.
5. `/help/value` — coût observé / valeur déclarée / impact attesté.

US MVP correspondantes : US-AHYP-100, 101, 102, 200, 300, 301, 303, 400
(si flag), 500, 501, 601, 800, 801, 900.

---

## 2. Les prérequis — déjà industrialisés, pas à reconstruire

Le document papAI listait 6 briques *avant* l’Hyperviseur. Chez Agentium
elles sont le runtime. On ne les re-spécifie pas comme un chantier
préalable.

| # | papAI | Agentium | Point d’attention COMEX |
|---|---|---|---|
| 1 | Catalog / promotion | Knowledge + publication Experience | Garbage in, garbage out inchangé |
| 2 | Document Center / KB | Collections, citations Work | Fraîcheur = ingestion réelle, pas une promesse chrome |
| 3 | Socle App | FastAPI + Angular, Work / Cockpit | L’Hyperviseur n’est pas « la première App système » |
| 4 | Flux KPI bidirectionnel | Runs + `operational_objective` + `value_basis` + Decision | C’est **toujours** la brique critique — mais elle est le ledger, pas une API KPI à part |
| 5 | Agent minimal RAG | Compagnon + tools lecture | Le modèle ne signe pas ; tools d’action papAI hors MVP |
| 6 | Gouvernance | IAM, audit, Membrane | Fondation déjà obligatoire |

Ordre de *démonstration*, plus de *construction* :

```text
IAM / audit  →  System publié + Work  →  Runs
     →  Hyperviseur (registre + décisions)
     →  (option) compagnon
     →  (option, canari) boucle de valeur Steer
```

---

## 3. User stories MVP (format COMEX)

### Epic A — Grand livre

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| A1 (US-AHYP-100) | Dirigeant | Voir Runs, coût, valeur avec fact-state | Évaluer l’impact sans zéro inventé |
| A2 (US-AHYP-101) | Dirigeant | Choisir 30 j / 90 j | Comparer |
| A3 (US-AHYP-102) | Dirigeant | Voir les bases de valeur | Séparer déclaré et unité native |
| A4 (US-AHYP-201) | Dirigeant | Voir l’écart à l’objectif opérationnel | Repérer un System hors fenêtre |

### Epic B — Objectifs top-down

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| B1 (US-AHYP-200) | Dirigeant | Fixer un objectif opérationnel borné | Donner un cap non économique |
| B2 (US-AHYP-202) | Owner | Modifier ou retirer | Ajuster |
| B3 (US-AHYP-203) | Dirigeant | Voir les Systems sans objectif ni base | Relancer, pas afficher 0 € |

### Epic C — Remontées bottom-up

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| C1 (US-AHYP-500) | Builder | Publier une Experience | Rendre le travail consommable |
| C2 (US-AHYP-501) | Métier | Produire un Run cité | Remonter une preuve |
| C3 (US-AHYP-503) | Dirigeant | Voir le silence (pas de Runs) | Distinguer trou et zéro mesuré |

### Epic D — Décider

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| D1 (US-AHYP-300) | Dirigeant | Voir ce qui attend une signature | Prioriser |
| D2 (US-AHYP-301) | Dirigeant | Accepter / rejeter (signal) | Tracer sans enacter |
| D3 (US-AHYP-303) | Métier | Signer un gate Studio | Garder l’humain dans la boucle |
| D4 (US-AHYP-400) | Steward | Simuler → Mesurer sur un System | Enacter si le canari est on |

### Epic E — Compagnon (périmètre MVP)

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| E1 (US-AHYP-600) | Dirigeant | Poser une question scopée | Inspecter sans naviguer |
| E2 (US-AHYP-601) | Gouvernance | Que le modèle ne signe pas | Séparer parole et décision |
| E3 (US-AHYP-602) | Dirigeant | Voir le périmètre | Limiter le risque de fuite / sur-promesse |

### Epic F — Gouvernance

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| F1 (US-AHYP-800) | Admin | Séparer lecture / signal / Act | Respecter les rôles |
| F2 (US-AHYP-801) | Admin | Tracer | Conformité |

---

## 4. Matrice de dépendance (lecture COMEX)

| Si absent | US cassées | Criticité |
|---|---|---|
| Aucun Run / aucune Experience | A1, C1, C2 — grand livre vide | Maximale — même risque qu’« Hyperviseur coquille » papAI |
| Pas de base de valeur | A1 en euros, A3 | Haute — le produit **doit** rester en unité native |
| IAM / audit | D2, D3, F1, F2 | Fondation |
| `value_loop_v1` off | D4 | Attendue : dire « non configuré », ne pas improviser Apply |
| Compagnon / tools off | E1 | L’Hyperviseur UI reste utilisable |
| `adoption_experience_v1` off | Entrée Work par défaut | Le chemin `/work` existe ; ce n’est pas le home |

---

## 5. Risques (actualisés)

| Risque | Impact | Mitigation |
|---|---|---|
| Raconter la valeur nette v1 comme un P&L | Décision COMEX sur un modèle estimé | Phrase obligatoire : *modèle de ROI des capacités* ; légende v2 |
| Fuite via le compagnon | Même risque papAI : le scope = les Systems autorisés | Scope explicite, tools lecture, pas d’action de signature |
| Apply portefeuille | Fausse industrialisation | 409 `LEGACY_DECISION_ACTUATOR_DISABLED` ; Steer seulement |
| Adoption « validée » | Overclaim | Flag off, 10 sessions non tenues — le dire |
| Mission Room | Confusion grand livre / app démo | Préfixe URL ≠ même contrat |
| What-if / projection | Simulation vendue comme mesure | Endpoints `not_configured` ; `simulation_is_measurement: false` |

---

## 6. Ce que le MVP ne fait pas

- Pas d’enactment depuis `/hypervisor`
- Pas de what-if / leviers live
- Pas de directives papAI (types, escalade, Broadcast)
- Pas de pipeline Custom Metric dans l’Hyperviseur
- Pas de gating Standard / PRO
- Pas d’export PDF/CSV COMEX (US-AHYP-702, P2)
- Pas d’O5 « heures / € économisés » attesté
- Pas de partage inter-workspace
- Pas de Mission Room comme preuve portefeuille
