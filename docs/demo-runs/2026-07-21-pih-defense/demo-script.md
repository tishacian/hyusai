# PIH Defense — Live Platform Walkthrough (21 juillet 2026, 15h30)

Déroulé opérateur pour les ~25 minutes de démo live, aligné sur la slide
« Walkthrough storyline » du deck (`Datategy-PIH-Defense-Deck.pptx`, section 03)
et ses cinq proof points. Environnement : `https://agentium.papai.ai`,
workspace **agentium-showcase**, SHA `c760db66c95fe0f`.

Le moment fort est le **live build** : on ajoute ensemble un nœud SAP HANA au
flow existant, on voit la réponse changer, puis on rejoue le run à l'identique.
Ce parcours exact (nœud ajouté au format palette + rebind du contexte + rerun)
a été validé moteur de bout en bout sur la VM aujourd'hui
(runs `403e95f1` et `5c0707c5`, verdict `stockout_ok / answer_ok / rerun_ok`).

---

## T-15 min — pré-checks (5 min)

1. `ssh omnirag-demo` → backend healthy :
   `docker inspect --format '{{.State.Health.Status}}' agentium-backend`
2. Run de contrôle du flow baseline (ne pas le faire pendant la démo) :
   `docker exec -w /app/backend agentium-backend python -m scripts.seed_hana_demo_flow --skip-connector --run`
   → attendu : `Flow chain validated: sap_hana_query_v1 → llm_rag_answer_v1`,
   `row_count=15`, `source=hana_live`.
3. Onglets ouverts à l'avance :
   - Agentium, workspace **agentium-showcase**, Flow Builder sur
     **SAP HANA Maintenance Copilot** ;
   - Hypervisor du showcase ;
   - SAP HANA Database Explorer (SQL console, instance BTP `agentium-demo`) ;
   - page **Models & Providers**.
4. Copier les deux snippets (SQL + question, ci-dessous) dans un pense-bête.
5. Si l'instance HANA est injoignable le jour J : le skill bascule tout seul
   sur le dataset embarqué et marque `source: demo_dataset` — la démo continue,
   le dire simplement (« resilient by design »).

---

## Déroulé minuté (~25 min)

### 1 · Steer — Hypervisor (2 min)

Portefeuille de capabilities : valeur nette, coût, ROI, confiance.

> “This is how a CIO steers an agent estate: every capability carries its net
> value, cost and confidence — not a dashboard bolted on, the operating view.”

### 2 · Run baseline — le flow SAP HANA existant (3 min)

Flow Builder → **SAP HANA Maintenance Copilot** : Trigger → *Open maintenance
orders (HANA)* → *Open orders synthesis* → Result. Montrer dans le Node
Inspector que le SQL et la question sont des paramètres éditables. **Execute**.

- Terminal : `[RUN]` scheduled → `[LLM]` streaming → `[RESULT]` réponse finale.
- La réponse liste les ordres de maintenance ouverts/released (15 lignes
  remontées en live du SAP HANA Cloud de PIH-like données hydro).

> “The SQL you see is live against SAP HANA Cloud — this is the S/4HANA access
> pattern from our RFI response, running, not mocked.”

### 3 · Live build — on ajoute un nœud ensemble (7 min) ← moment clé

But affiché : « procurement wants to know which spare parts are below minimum
stock ». On l'ajoute en direct :

1. **Palette → drag “SAP HANA Query”** sur le canvas.
   Renommer le label : `Spare parts below minimum (HANA)`.
2. **Node Inspector → sql** (coller) :

   ```sql
   SELECT PART_ID, EQUIPMENT_ID, DESCRIPTION, QTY_ON_HAND, QTY_MIN, LEAD_TIME_DAYS
   FROM DEMO_SPARE_PARTS
   WHERE QTY_ON_HAND < QTY_MIN
   ORDER BY QTY_ON_HAND ASC, LEAD_TIME_DAYS DESC
   ```

3. **Câbler** : Trigger → nouveau nœud, puis nouveau nœud → *Open orders
   synthesis*.
4. Inspector du nœud *Open orders synthesis* :
   - **context** : re-binder via le picker sur `Spare parts below minimum
     (HANA) · context` ;
   - **query** (coller) :
     `Which spare parts are below minimum stock, and what should procurement
     reorder first given the lead times?`
5. **Save** puis **Execute**.

Résultat attendu : réponse totalement différente — 8 pièces sous le minimum,
priorisées par rupture (qty 0) et lead time (kit runner blade 90 jours, HV
bushing 60 jours…), avec citations vers les lignes HANA.

> “We just changed what this agent does — no code, no redeploy. The node we
> dropped is a governed, typed skill; the SQL is a parameter, and the run
> engine chains it in a strict dataflow contract.”

**Plan B** (si le picker de contexte est capricieux en live) : garder le
binding contexte d'origine, ne faire que l'ajout du nœud + Execute. Le nouveau
nœud s'exécute et se voit dans le terminal et le run detail (8 lignes, source
`hana_live`) — l'impact est démontré ; enchaîner sur le replay.

### 4 · Run & replay — la boîte noire (4 min)

Ouvrir le **Run detail** du run qu'on vient de lancer :

- ledger d'invocations : le SQL en entrée, les 8 lignes en sortie,
  latence et coût par appel — *proof point 5 (cost visible per action)* ;
- checkpoints `node_start` / `node_end` — la trace complète ;
- **Re-run** : nouveau run avec `parent_run_id` vers l'original, même
  `flow_snapshot`, mêmes inputs → chaîne identique — *proof point 2
  (replay is real)*.

> “Same snapshot, same inputs, full lineage to the parent run — this is the
> capability behind certified execution in our compliance response.”

### 5 · Evaluate & Govern (5 min)

- Evaluation : golden sets / gates — *proof point 4 (evaluation gates
  production)*.
- Governance : mandates, permissions, audit ledger — *proof point 3
  (governance is structural)* ; montrer un blocage hors-scope si le temps.

### 6 · La preuve côté SAP + Models & Providers (2 min)

- Onglet SAP DBX, exécuter :
  `SELECT COUNT(*) FROM DEMO_SPARE_PARTS WHERE QTY_ON_HAND < QTY_MIN;` → 8.
  Les données vivent bien côté SAP, Agentium les consomme en live.
- Page **Models & Providers** : OpenAI actif, Ollama local, Azure OpenAI /
  OpenRouter configurables — le model routing multi-provider de la réponse
  RFI (D14), gouverné au niveau workspace.

> “Everything you saw runs on the same build you get access to today — that's
> proof point 1: nothing here is slideware.”

---

## Mapping deck → démo

| Proof point (deck 3.2) | Où dans la démo |
|---|---|
| 1 · Nothing is slideware | Tout le parcours + accès SaaS PIH (section 04 du deck) |
| 2 · Replay is real | Étape 4 — Re-run avec lineage |
| 3 · Governance is structural | Étape 5 — mandates & audit ledger |
| 4 · Evaluation gates production | Étape 5 — golden sets |
| 5 · Cost visible per action | Étape 4 — ledger d'invocations |

## Preuves moteur (aujourd'hui, VM)

- Ajout de nœud au format exact de la palette (inputs_map vide + params
  inspector) : commit `6ac087f0` — les params `config.params` sont mergés en
  défauts du payload strict.
- Sortie de run déterministe via le sink : commit `c760db66`.
- Script rejouable : `backend/scripts/validate_node_add_demo.py`
  (crée un System temporaire, exécute run + rerun, nettoie tout).
