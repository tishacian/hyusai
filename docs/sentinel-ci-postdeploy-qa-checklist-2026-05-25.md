# SENTINEL-CI — Checklist QA post-deploy (S1 + S2 + S3)

**Durée estimée** : ~20 min (gate automatisé ~15 min + manuel présentateur ~5 min)  
**Cible** : `https://agentium.papai.ai` · workspace **`sentinel-ci`** · profil **`vigie_executive`**  
**Branche déployée** : `demo/agentic`  
**Seuil cible** : **100 % readiness** — 0 FAIL · 0 PARTIAL · console propre

---

## Pré-requis

| Variable | Valeur |
|----------|--------|
| `AGENTIUM_HOST` | `https://agentium.papai.ai` |
| `AGENTIUM_EMAIL` | `thibaud.ishacian@datategy.net` |
| `AGENTIUM_PASSWORD` | *(compte démo — voir vault / ops runbook)* |
| `WORKSPACE_SLUG` | `sentinel-ci` |
| `QA_GATE_DIR` | `docs/status-screenshots/YYYY-MM-DD-qa-gate` *(auto)* |

**URL cockpit** :  
`https://agentium.papai.ai/hypervisor/mission-room/cockpit?workspace=sentinel-ci`

---

## 0. Gate unique — readiness 100 % (recommandé)

Exécuter **< 2 h avant la VP** avec reset workspace :

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL=thibaud.ishacian@datategy.net \
AGENTIUM_PASSWORD='***' \
WORKSPACE_SLUG=sentinel-ci \
./scripts/qa_demo_gate.sh --with-reset
```

Sans reset (vérif rapide post-deploy) :

```bash
./scripts/qa_demo_gate.sh
```

| Étape gate | Seuil 100 % | Artefact |
|------------|-------------|----------|
| 0 `predemo_reset.sh` *(option `--with-reset`)* | demo_time 25/05 10:30 · ODJ non patché · evt-prefet-nawa 11h | log inline |
| 1 smoke probe prod | **26/26 PASS** | `qa-gate/smoke-probe.log` |
| 2 resolver S3 local | **12/12 PASS** | `qa-gate/s3-resolver.log` |
| 3 deck phrases resolve | **14/14 PASS** · 0 PARTIAL | `qa-gate/deck-phrases-resolve.json` |
| 4 Playwright S1+S2 | **0 FAIL · 0 PARTIAL** | `qa-gate/qa-trame-results.json` |
| 5 Playwright S3+V21 | **0 FAIL** | `qa-gate/qa-s3-results.json` |
| Console QA | **0×500 · 0 pageerror** | champs `consoleErrors` JSON |
| **Exit code** | **`0`** | `qa-gate/gate-summary.json` |

Options :

- `--with-reset` — enchaîne `scripts/predemo_reset.sh` en étape 0 (état démo propre).
- `--skip-playwright` — smoke + resolver + deck seulement (~2 min).

---

## 1. Commandes individuelles (debug / CI partiel)

### 1.1 Resolver S3 local (code, sans réseau)

```bash
cd backend
PYTHONPATH=$(pwd) python3 ../scripts/test_s3_resolver.py
```

| Attendu | Seuil |
|---------|-------|
| **12/12 PASS** | conf ≥ 0.85, action_id exacte |
| Exit code | `0` |

### 1.2 Smoke probe prod (API + resolver live)

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL=thibaud.ishacian@datategy.net \
AGENTIUM_PASSWORD='***' \
WORKSPACE_SLUG=sentinel-ci \
python3 scripts/smoke_predeploy_probe.py
```

| Bloc | Attendu |
|------|---------|
| Voice resolver | **12/12 PASS** |
| API non-régression | **14/14 PASS** |
| **Total** | **26/26 PASS (100 %)** |

> Le gate exige **26/26** ; le script smoke seul accepte ≥ 50 % (legacy).

### 1.3 Deck phrases resolve

```bash
QA_OUT=docs/status-screenshots/2026-05-25-qa-gate/deck-phrases-resolve.json \
python3 scripts/qa_deck_phrases_resolve.py
```

| Attendu | Seuil |
|---------|-------|
| **14/14 PASS** | 0 PARTIAL · 0 FAIL |

### 1.4 QA UI Playwright S1+S2

```bash
cd scripts/playwright
OUT_DIR=../../docs/status-screenshots/2026-05-25-qa-gate \
node qa_trame_full.mjs
```

| Attendu | Seuil 100 % |
|---------|-------------|
| Steps S1+S2 + Plan B | **0 FAIL · 0 PARTIAL** |
| Plan B chip Nord | **PASS** |
| Plan B Port Vridi légende | **PASS** |
| Console | **0×500 · 0 pageerror** |

### 1.5 QA UI Playwright S3

```bash
cd scripts/playwright
OUT_DIR=../../docs/status-screenshots/2026-05-25-qa-gate \
node qa_s3_security.mjs
```

| Attendu | Seuil 100 % |
|---------|-------------|
| V21 surfaces | **4/4 PASS** |
| S3.1–S3.6 | **0 FAIL** (critère DOM primaire) |
| S3.5 URL | contient `/reputation` *(info)* |

---

## 2. Structure artefacts gate

Dossier : **`docs/status-screenshots/YYYY-MM-DD-qa-gate/`**

| Fichier | Contenu |
|---------|---------|
| `gate-summary.json` | Verdict global `readiness_100: true/false` |
| `smoke-probe.log` | 26/26 smoke |
| `deck-phrases-resolve.json` | 14 phrases deck |
| `qa-trame-results.json` | S1+S2 + Plan B |
| `qa-s3-results.json` | S3.1–S3.6 + V21 |
| `S*.png` / `V21-*.png` | Captures Playwright |

---

## 3. Régression S1 smoke (inclus dans gate step 1)

| # | Check | Attendu |
|---|-------|---------|
| R1 | Cockpit démo-time + chip Nord | `date_label = "Lundi 25 Mai 2026"` · chip `zone-nord-tension` pulse |
| R2 | Resolver PV douanes | `aya.show_customs_record` conf ≥ 1.0 |
| R3 | Webcam port demo | `HEAD /webcams/proxy?source_id=apm-apapa-gate-1` → **200** |

Points S1 validés par gate Playwright (plus de GO dégradé) :

- « montre la situation au port » → `aya.show_maritime_traffic` **PASS**
- Clic pin MV Atlantic Trader → fiche navire + webcam **PASS**
- Légende **Port Vridi · cargo demo** → **PASS**

---

## 4. Checks manuels présentateur (~5 min)

Cocher après gate `exit 0` :

- [ ] **Hard reload** cockpit (`Cmd+Shift+R`)
- [ ] Workspace **SENTINEL-CI** sélectionné
- [ ] **Quick Panel** : `Cmd+J` → textarea visible · **0 pageerror console**
- [ ] **S1.4** : phrase Atlantic Trader → webcam APM (sans 500 console)
- [ ] **S2.T** : Agenda → **Préfet Nawa 11h**
- [ ] **S3.1** : posture sécuritaire dual-axis
- [ ] **S3.6** : brouillon communiqué advisory

Phrases : [`sentinel-ci-demo-walkthrough-2026-05-25.md`](./sentinel-ci-demo-walkthrough-2026-05-25.md)

---

## 5. Tableau Go / No-Go — seuil 100 %

| Critère | Seuil GO (100 %) | NO-GO |
|---------|------------------|-------|
| `qa_demo_gate.sh` | **exit 0** | exit 1 |
| Smoke probe | **26/26** | < 26/26 |
| S3 resolver local | **12/12** | < 12/12 |
| Deck resolve | **14/14 PASS** · 0 PARTIAL | any FAIL/PARTIAL |
| Trame S1+S2 UI | **0 FAIL · 0 PARTIAL** | any FAIL |
| S3 UI | **0 FAIL** | any FAIL |
| Plan B S1 (Nord + Vridi) | **2/2 PASS** | any FAIL |
| Console QA | **0×500 · 0 pageerror** | any 500/pageerror |
| predemo_reset | exécuté < 2 h VP (`--with-reset`) | workspace dirty |

### Verdict

| Scénario | Décision |
|----------|----------|
| Gate exit 0 + `readiness_100: true` | **GO 100 %** — trame S1+S2+S3 sans Plan B dégradé |
| Gate exit 0 mais console 500/pageerror | **NO-GO** — redeploy front (webcam blob + icônes Lucide) |
| Smoke < 26/26 ou login fail | **NO-GO** — redeploy + `predemo_reset.sh` |

---

## 6. Score de readiness cible

| Périmètre | Score cible | Gate step |
|-----------|-------------|-----------|
| S1 Nord / douanes / maritime | **100 %** | `qa_trame_full` + smoke |
| S2 Nawa / cacao | **100 %** | `qa_trame_full` |
| S3 Sécurité | **100 %** | `qa_s3_security` + smoke S3 |
| Ops / console | **100 %** | `predemo_reset` + consoleErrors |
| **Global S1+S2+S3** | **100 % GO** | `gate-summary.json` |

---

## 7. Ordre d'exécution rapide

| Min | Action |
|-----|--------|
| 0–15 | `./scripts/qa_demo_gate.sh --with-reset` |
| 15–20 | §4 checks manuels + relecture PNG gate |

---

## Références

- Walkthrough VP : [`sentinel-ci-demo-walkthrough-2026-05-25.md`](./sentinel-ci-demo-walkthrough-2026-05-25.md)
- QA UI S1+S2 détail : [`sentinel-ci-demo-ui-qa-checklist-2026-05-25.md`](./sentinel-ci-demo-ui-qa-checklist-2026-05-25.md)
- Ops deploy : [`sentinel-ci-ops-deploy-runbook-2026-05-25.md`](./sentinel-ci-ops-deploy-runbook-2026-05-25.md)
- Scripts : `scripts/qa_demo_gate.sh` · `scripts/predemo_reset.sh` · `scripts/smoke_predeploy_probe.py` · `scripts/playwright/qa_trame_full.mjs` · `scripts/playwright/qa_s3_security.mjs`
