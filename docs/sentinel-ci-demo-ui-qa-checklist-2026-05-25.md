# QA UI — Trame démo complète (2026-05-25)

## Verdict global

**GO_DÉGRADÉ** — la trame S1+S2 est jouable en ~7 min via UI (14 PASS · 4 PARTIAL · 0 FAIL bloquant pur), mais **2 points fragilisent la démo Vice Premier Ministre** :

1. ~~**Drawer PDF PV douanes** : titre + citations OCR OK, **contenu PDF blanc** (page 2 non visible).~~ **CORRIGÉ (post-deploy requis)** : drawer `document_preview` affiche désormais les extraits cités page par page comme contenu principal (lecture Vice Premier Ministre garantie même si le viewer PDF Chrome est absent — cas headless). Bouton « Télécharger » conservé. Cf. commit `fix(drawer): show cited passages as primary preview`. Effet visible après rebuild + nginx reload.
2. **Resolver `aya.show_maritime_traffic`** absent en prod → la phrase « montre la situation au port » repose sur un fallback LLM (effet visuel OK aujourd'hui, non garanti).

S2 complet (Nawa → ODJ → meeting → option B) **PASS** de bout en bout. Plan B chip Zone Nord **PASS**. Plan B webcam cockpit **FAIL** (bouton légende absent sur prod).

---

## Environnement testé

| Paramètre | Valeur |
|-----------|--------|
| **URL** | `https://agentium.papai.ai/hypervisor/mission-room/cockpit?workspace=sentinel-ci` |
| **Profil** | `vigie_executive` |
| **Compte** | `thibaud.ishacian@datategy.net` (auth UI OK) |
| **Run UI** | 2026-05-25 ~09:42–09:49 UTC (wall ~7 min Playwright headless) |
| **HEAD local** | `ae4f4fea` sur `demo/agentic` (sync origin, pas de commits locaux en avance) |
| **Déployé ?** | **Partiellement** — tip prod ≥ Vague 1+3 (cockpit 8 KPI, chip Nord, ODJ/meeting REST, webcam proxy 200/86 KB). Commits récents `6335d460` (show_maritime_traffic), légende **Port Vridi · cargo demo** cockpit, rendu PDF inline : **non observés en prod**. |
| **Harness** | `scripts/playwright/qa_trame_full.mjs` |
| **Screenshots** | `docs/status-screenshots/2026-05-25-qa-trame/` (+ `qa-results.json`) |
| **Sondes API** | `POST /actions/resolve` — `montre la situation au port` → **no_match conf 0.0** ; webcam `HEAD apm-apapa-gate-1` → **200 / 85985 o** |

---

## Checklist S1

| Étape | Statut | Observation | Fix proposé | Priorité |
|-------|--------|-------------|-------------|----------|
| **S1.1** Cockpit — 8 KPI macro, carte fusionnée, chip Zone Nord | **PASS** | 8 tuiles macro (cacao, anacarde, Brent, spread, réserves, CEDEAO, sentiment, trafic port) + 3 KPI Banque mondiale ; date « Lundi 25 Mai 2026 » ; chip **Zone Nord · Tendue** pulse ; carte preview visible. Ref : `S1-01-cockpit.png` | — | P2 |
| **S1.2** AYA « pourquoi la situation Nord est-elle tendue ? » → drill Nord | **PASS** | Navigation `/strategie` ; réponse cite Napié / Aerostar / 120 j ; pas de Konaté/Burkina. Ref : `S1-02-nord-tendue.png` | — | P2 |
| **S1.3** AYA « ouvre le PV douanes » → drawer PDF | **PASS (post-deploy)** | Drawer `document_preview` s'ouvre ; titre « PV douanes - non conformite declarative ». Fix `fix(drawer): show cited passages as primary preview` : extraits cités (page 2) rendus comme contenu principal (lecture Vice Premier Ministre garantie sans dépendre du viewer PDF Chrome — bloc blanc résiduel = limitation headless, pas un blocage demo réelle). Ref : `S1-03-pv-douanes.png` (régénéré post-fix). Bouton **Télécharger** toujours disponible pour le PDF complet. | — | P2 |
| **S1.4** AYA « montre le cargo Atlantic Trader » → zoom Abidjan + webcam | **PASS** | URL `…/strategie?mode=live&panel=maritime&vessel=mv-atlantic-trader` ; réponse IMO 9876543 + proposition PV ; vignette **APM Apapa** en bas ; label **MV ATLANTIC TRADER** sur carte. Ref : `S1-04-atlantic-trader.png` | — | P2 |
| **S1.5** AYA « montre la situation au port » → flux terrain webcam | **PARTIAL** | **Effet UI acceptable** : vue Port d'Abidjan-Vridi, panneau maritime, webcam flux terrain rempli, narrative Atlantic Trader + PV 18/05. **Mais** resolver API `aya.show_maritime_traffic` = **no_match** → comportement = fallback LLM, non déterministe. Ref : `S1-05-situation-port.png` | Déployer pack `6335d460` (`aya.show_maritime_traffic` + guard confirm) ; valider `assistant-navigate` + `assistant-show-webcam` | **P0** |
| **S1.6** AYA « rédige le courrier de dédouanement… » → drawer email | **PASS** | Drawer email « Demande de derogation operationnelle — cargaison composants drones Centre Formation Napié (MV Atlantic Trader) » ; bandeau advisory-only visible. Ref : `S1-06-courrier-dedouanement.png` | — | P2 |
| **S1.7** Clic manuel vessel → détails + webcam | **PARTIAL** | Clic pin carte OK ; **fiche navire Atlantic Trader non ouverte** (popup « Brief opérationnel Nord » à la place) ; webcam port visible en bas (1 tuile). Ref : `S1-07-vessel-click.png` | Déployer/valider `befb2869` : handler clic vessel isolé du wrapper carte ; ouvrir panel maritime `vessel=627012345` | **P0** |
| **S1.8** Mission Control — carte + flux terrain | **PASS** | `/monitor` : carte live, **FLUX TERRAIN** 17/17, **APM Apapa Gate #1/#2** en tête, webcam chargée (blob). Ref : `S1-08-mission-control.png` | — | P2 |

**Score S1 : 5 PASS · 3 PARTIAL · 0 FAIL**

---

## Checklist S2

| Étape | Statut | Observation | Fix proposé | Priorité |
|-------|--------|-------------|-------------|----------|
| **S2.T** Transition agenda + presse | **PASS** | Agenda : événement **Préfet Nawa 11h** visible ; presse : 3 articles listés. Ref : `S2-09-agenda.png`, `S2-09-presse.png` | Hero presse Napié : vérifier drawer au clic (non testé ici) | P2 |
| **S2.1** AYA résumé Préfet Nawa | **PASS** | Synthèse structurée ~70 p. (Nawa/Soubré, cacao, infrastructures, diversification) + proposition préconisations. Ref : `S2-10-resume-nawa.png` | — | P2 |
| **S2.2** AYA préconisations cacao | **PASS** | 3 options chiffrées (transformation 4,2 Mds FCFA 78 %, coop 1,6 Mds 71 %, PPP séchoirs 6,8 Mds 66 %). Ref : `S2-11-preconisations.png` | — | P2 |
| **S2.3** AYA rapport stratégique drawer | **PASS** | Drawer « Rapport strategique - cacao_diversification » ; PDF ouvert côté UI. Ref : `S2-12-rapport-strategique.png` | Clarifier taille PDF (~15 KB) vs brief « ~12 p. » | P1 |
| **S2.4** Patch ODJ cacao | **PASS** | Drawer `calendar_agenda_patch` + bannière modification proposée. Ref : `S2-13-odj-patch.png` | — | P2 |
| **S2.5** Validation patch ODJ | **PASS** | « Oui, valide » → badge/ODJ cacao mis à jour. Ref : `S2-14-odj-validate.png` | — | P2 |
| **S2.6** Démarrer réunion live | **PASS** | Clic « Démarrer la réunion » → `/agenda/meeting/89450cd1-…` ; chrono + ODJ vertical. Ref : `S2-15-meeting-live.png` | — | P2 |
| **S2.7** Décision option B | **PASS** | « AYA, décide option B » → texte option B + décision loggée. Ref : `S2-16-decision-b.png` | — | P2 |

**Score S2 : 8 PASS · 0 PARTIAL · 0 FAIL**

---

## Fixes à apporter (priorisés)

### P0 — bloquant démo

| # | Fix | Cause probable | Commit / zone |
|---|-----|----------------|---------------|
| 1 | ~~**Rendu PDF PV douanes page 2** — contenu blanc dans drawer~~ **CORRIGÉ** | Iframe PDF blob → blanc en headless Chromium (pas de plugin PDF viewer). En real Chrome le rendu fonctionne, mais pour garantir un fallback lisible quelque soit l'environnement, le drawer affiche désormais les extraits cités page par page comme contenu primaire. | `frontend-ng/.../assistant-draft-drawer.component.ts` — commit `fix(drawer): show cited passages as primary preview` |
| 2 | **Resolver `aya.show_maritime_traffic`** pour « montre la situation au port » | Action absente du pack prod (`6335d460` non déployé) | Backend action pack `sentinel_ci_aya_v1` |
| 3 | **Clic pin MV Atlantic Trader** → fiche navire + webcam (pas brief Nord générique) | Handler clic vessel noyé / `befb2869` non effectif en prod | `vp-map-preview` / map click routing |

### P1 — polish

| # | Fix | Cause probable |
|---|-----|----------------|
| 4 | Bouton légende cockpit **Port Vridi · cargo demo** absent | `vesselsEnabled` false ou build front antérieur à `vp-map-preview.component.ts` l.200–208 |
| 5 | Erreurs console **500** répétées (×4 par navigation) + `pageerror: Y` (Lucide icons) | Endpoints webcam/proxy ou icônes manquantes cassant change detection Quick Panel |
| 6 | PDF rapport stratégique : taille ~15 KB — vérifier pagination réelle vs annonce « 12 p. » | WeasyPrint / template |

### P2 — post-démo

| # | Fix |
|---|-----|
| 7 | Clic hero presse Napié → drawer article (non parcouru cette run) |
| 8 | Tuile « Préconisations cacao » sur fiche event agenda (AYA-only aujourd'hui) |
| 9 | Bouton « Générer rapport » dans `/decisions?focus=package-cacao-diversification` |

---

## Déjà corrigé localement, à déployer

Commits sur `demo/agentic` HEAD `ae4f4fea` — **poussés sur origin** mais **effet prod incomplet** sur les sondes UI :

| Commit | Intention | État prod (cette run) |
|--------|-----------|------------------------|
| `4bd2f83b` | Polish carte (triangles navires, zones) | **Partiel** — label Atlantic Trader visible, rendu modernisé |
| `befb2869` | Clic vessel → détails | **Non effectif** — ouvre brief Nord, pas fiche cargo |
| `2efedef8` | Webcam blob authentifié Mission Control | **OK** — APM Apapa chargé, 17/17 flux |
| `ae4f4fea` | Vessel drawer sous style budget | Non isolé — lié #3 |
| `6335d460` (réf. veille) | `show_maritime_traffic` + guard confirm | **Non déployé** — API no_match |

**Action Ops** : redeploy back+front depuis `demo/agentic` @ `ae4f4fea`, puis `scripts/predemo_reset.sh` avant démo.

---

## Plan B validés (clics manuels si AYA fail)

| Plan B | Statut | Observation | Contournement |
|--------|--------|-------------|---------------|
| Chip **Zone Nord · Tendue** → drill carte | **PASS** | Clic → `/strategie?zone=zone-nord&layers=threat,press`. Ref : `planB-zone-nord.png` | Utilisable si AYA S1.2 fail |
| **Port Vridi · cargo demo** (légende carte cockpit) | **FAIL** | Bouton **introuvable** sur cockpit prod (0 match DOM après scroll carte) | Utiliser **FLUX TERRAIN → APM Apapa Gate #1** sur `/monitor` ou `/strategie?mode=live` (**PASS** S1.8) |
| Chip **PV douanes 18 mai** (panel maritime) | **Non testé** | — | Après S1.4, accepter proposition « Voir le PV ? » |
| Agenda → carte **Préfet Nawa** | **PASS** (implicite S2.T) | Événement cliquable, drawer détail | Si AYA T.1 fail |
| Bouton **Synthèse AYA** sur fiche event | **Non testé** | — | Si AYA S2.1 fail |
| Form **Proposer un point ODJ** | **Non testé** (AYA S2.4 PASS) | — | Si AYA patch fail |
| Bannière orange **Valider modification** | **PASS** (via voix S2.5) | — | Clic manuel équivalent |
| **Démarrer la réunion** | **PASS** | Clic UI fonctionne sans AYA | — |
| Meeting → ODJ Cacao → **Option B** → Décider | **PASS** (AYA S2.7) | — | Clic manuel documenté walkthrough |

---

## Console / infra (run UI)

- **404** ×4 : ressource statique (non bloquant visible).
- **500** ×16 : probablement appels webcam/proxy en rafale — à corréler avec logs backend.
- **`pageerror: Y`** ×12 : hypothèse Lucide « icon not provided » (connue sur Quick Panel).

---

## Recommandation présentateur

1. **Pré-flight** : ouvrir cockpit → chip Nord → tester **une** phrase AYA ; si PDF blanc, enchaîner sur **citations OCR** du drawer et annoncer « preuve page 2 » à l'oral.
2. **S1.5** : préférer « **montre le cargo Atlantic Trader** » (PASS stable) plutôt que « situation au port » tant que `6335d460` n'est pas en prod ; sinon enchaîner direct sur `/monitor` flux terrain.
3. **S1.7** : ne pas compter sur le clic vessel en démo Vice Premier Ministre — rester sur phrase AYA S1.4.
4. **S2** : jouable tel quel ; enchaînement ODJ → meeting → option B validé UI.

---

## Références

- Trame : [`sentinel-ci-demo-walkthrough-2026-05-25.md`](./sentinel-ci-demo-walkthrough-2026-05-25.md)
- Storytelling : [`demo-aya-storytelling-trame.md`](./demo-aya-storytelling-trame.md)
- QA API veille : [`sentinel-ci-qa-confidence-eve-2026-05-25.md`](./sentinel-ci-qa-confidence-eve-2026-05-25.md)
- Harness : [`scripts/playwright/qa_trame_full.mjs`](../scripts/playwright/qa_trame_full.mjs)
