# SENTINEL-CI — Instructions Ops · déploiement démo VP · 25 mai 2026

**Objectif** : prod `https://agentium.papai.ai` prête pour la démo à **09h00 Abidjan** (11h00 Paris).  
**Workspace** : `sentinel-ci` · **Branche** : `demo/agentic` · **Tip cible** : ≥ `9d0f8012` (+ commits locaux si pushés : `b9e8a414` Quick Panel, fix PDF drawer, etc.)

---

## 0. Pré-requis

- Accès SSH VM `omnirag-demo` (backend systemd + frontend nginx)
- Repo : `/home/ubuntu/omnirag` (ajuster si différent)
- Compte test : `thibaud.ishacian@datategy.net`

---

## 1. Pull & déploy (ordre strict)

```bash
cd /home/ubuntu/omnirag
git fetch origin
git checkout demo/agentic
git pull --ff-only origin demo/agentic
git log -1 --oneline   # vérifier tip ≥ 9d0f8012
```

### Backend

```bash
sudo ./deploy/install-backend-service.sh
sudo systemctl status agentium-backend agentium-worker-cpu --no-pager
```

### Frontend

```bash
cd frontend-ng
npm ci
npm run build:prod
# Copier dist vers nginx selon procédure interne, puis :
sudo systemctl reload nginx   # ou équivalent
```

**Vérif** : `curl -sI https://agentium.papai.ai/ | grep -i last-modified` — doit être **post-deploy** (aujourd’hui ~06:54 UTC minimum pour les fixes récents).

---

## 2. WeasyPrint — libs système + smoke test

Les PDFs Préfet Nawa et PV douanes sont des **stubs ~600 o** si WeasyPrint n’a jamais regénéré les fichiers.

```bash
/home/ubuntu/omnirag/venv/bin/python -c "from weasyprint import HTML; print('WeasyPrint OK')"
```

**Si échec** :

```bash
sudo apt-get update && sudo apt-get install -y \
  libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-dejavu-core

/home/ubuntu/omnirag/venv/bin/python -c "from weasyprint import HTML; print('WeasyPrint OK')"
```

---

## 3. Régénération PDFs (OBLIGATOIRE pour démo S1.2 / S2)

```bash
cd /home/ubuntu/omnirag/backend

# Rapport Préfet Nawa 70p → object store
/home/ubuntu/omnirag/venv/bin/python -m app.cli.build_sentinel_reports --force

# PV douanes 18 mai → fichier statique API (predemo_reset NE le fait PAS)
/home/ubuntu/omnirag/venv/bin/python ../scripts/generate_customs_pdf.py --force
```

**Vérif tailles** (doivent être >> 1 KB) :

```bash
ls -lh ../backend/app/resources/sentinel_ci_customs/*.pdf 2>/dev/null || true
# Préfet : vérifier via object store ou endpoint reports si exposé
```

Attendu : PV douanes **> 50 KB**, Préfet **> 500 KB**.

---

## 4. Reset état démo workspace

Depuis la VM **ou** poste local avec accès API prod :

```bash
cd /home/ubuntu/omnirag
./scripts/predemo_reset.sh
```

Ce script :
- PATCH `demo_time_context` → 25 mai 2026
- Reset `actions.last_focus`, `awaiting`, `current_meeting`, `pending_agenda_patch`
- Purge events debug agenda + reseed calendrier 25–26 mai
- Warm-up PDF cacao + admin reseed/rebuild

---

## 5. Smoke tests (GO / NO-GO)

```bash
cd /home/ubuntu/omnirag
python3 scripts/smoke_predeploy_probe.py
```

**Objectif : 20/20 PASS.**

Probes manuelles si doute :

```bash
# Login puis :
curl -s "https://agentium.papai.ai/api/v1/mission-room/macro-indicators?workspace=sentinel-ci" \
  -H "Authorization: Bearer $TOKEN" | jq '.sovereign_indicators | length'
# → doit retourner 8
```

Résolveur (3 prompts critiques) :

| Prompt | Action attendue |
|---|---|
| `AYA, pourquoi la situation Nord est-elle tendue ?` | `aya.explain_why` |
| `AYA, ouvre le PV douanes.` | `aya.show_customs_record` |
| `AYA, montre la situation au port.` | `aya.show_maritime_traffic` |

---

## 6. Vérif UI navigateur (5 min)

Ouvrir **fenêtre privée** (éviter cache SPA) :

1. `https://agentium.papai.ai/hypervisor/mission-room/cockpit` — workspace `sentinel-ci`
2. **8 KPIs souverains** visibles (cacao, anacarde, Brent, spread, BCEAO, CEDEAO, opinion, port Abidjan) — titre « Pouls économique souverain », **pas** « temps réel »
3. Clic **+ AYA** (Quick Panel) → panel s’ouvre (fix icons `b9e8a414`)
4. Taper `AYA, ouvre le PV douanes.` → **drawer document_preview** s’ouvre (fix PDF blob `assistant-draft-drawer`)
5. Carte : **16 navires** sur l’eau (deck.gl, pas sur la terre)
6. FLUX TERRAIN : **APM Apapa Gate #1** en tête de liste

---

## 7. Commits locaux à pousser AVANT deploy (si pas déjà fait)

Vérifier côté dev si ces commits sont sur `origin/demo/agentic` :

| Commit | Contenu |
|---|---|
| `b9e8a414` | Fix Quick Panel (icônes Lucide → drawers AYA) |
| Fix PDF drawer | `assistant-draft-drawer` blob fetch (si commit séparé) |
| `b83694e8` | Charts presse drawer |
| `cef22a4c` | Deck présentateur |

Si absents : demander push `git push origin demo/agentic` puis **refaire étape 1**.

---

## 8. Plan B si NO-GO partiel

| Symptôme | Contournement démo |
|---|---|
| Quick Panel ne s’ouvre pas | Chat plein écran ou **Plan B clic** (deck présentateur) |
| PDF iframe vide | Montrer **passages cités page 2** + bouton Télécharger |
| Rapport Nawa | **Résumé texte AYA** (pas PDF inline) — phrase : « AYA, résume le rapport Préfet Nawa. » |
| AYA répond mal | Utiliser phrases **exactes** cheatsheet (`docs/sentinel-ci-presenter-cheatsheet.md`) |

---

## 9. Contacts / docs

- Walkthrough : `docs/sentinel-ci-demo-walkthrough-2026-05-25.md`
- Cheatsheet prompts : `docs/sentinel-ci-presenter-cheatsheet.md`
- Deck présentateur : `docs/sentinel-ci-demo-presenter-deck-2026-05-25.pptx`

---

## Checklist finale (cocher)

- [ ] `git pull demo/agentic` OK
- [ ] Backend + worker healthy
- [ ] Frontend rebuild + nginx reload
- [ ] WeasyPrint smoke OK
- [ ] PDFs regénérés (--force)
- [ ] `predemo_reset.sh` joué
- [ ] Smoke 20/20
- [ ] UI privée : 8 KPIs + Quick Panel + drawer PV
- [ ] Signal GO envoyé à l’équipe démo

**Deadline hard : 08h30 Abidjan (10h30 Paris)** — marge 30 min avant VP.
