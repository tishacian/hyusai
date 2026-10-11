# Smoke runbook SENTINEL-CI · lundi 25 mai 2026

**Cible** : démo Vice Premier Ministre · `https://agentium.papai.ai/hypervisor/mission-room/cockpit`
**Workspace** : `sentinel-ci` · profil assistant `vigie_executive`
**Compte** : `thibaud.ishacian@datategy.net`
**Fenêtre** : 08h30 → 09h00 (H-1h démo). Lecture 3 min, exécution 25 min.
**Pré-requis Ops** : `git push origin demo/agentic` puis redéploy backend + frontend, puis `./scripts/predemo_reset.sh`.

---

## Section A — Smoke visuel navigateur (15 min)

Chrome incognito · fenêtre 1920 × 1080 · audio activé · profil neuf.
Ouvrir l'URL, login, sélectionner workspace `sentinel-ci`, puis cocher dans l'ordre :

| # | Bloc cockpit | Contrôle visuel | OK |
|---|---|---|---|
| 1 | Login + workspace | Bandeau workspace `sentinel-ci`, header date « Lundi 25 Mai 2026 » | ☐ |
| 2 | `vp_status_bar` | Chip 0 = « Zone Nord · Tendue », ton critique, **pulse visible** | ☐ |
| 3 | Agenda du jour | ≥ 6 items datés `2026-05-25` (et non avril 2026 ; aucun item « QA wiring ») | ☐ |
| 4 | Presse hero | Article CI en tête : Napié drone center / Abidjan.net / SENTINEL-CI · **pas Mali / Iran / Ebola** | ☐ |
| 5 | Carte CI overlay vessels | 16 pins navires en couche absolue **au-dessus** du canvas MapLibre (un seul plan visuel, pas un panneau séparé) | ☐ |
| 6 | Halo MV Atlantic Trader | Pin violet pulsant (`mmsi 627012345`) parmi les 16 ; clic ouvre vignette webcam APM Apapa Gate-1 (drawer plein écran avec JPG vivante) | ☐ |
| 7 | Toggle Zoom Abidjan / Vue pays | Bouton avec **`aria-pressed`** qui change d'état · animation fluide · les 16 pins se redistribuent sur la bbox Vridi puis pays | ☐ |
| 8 | Macro indicators sparklines | Cacao + anacarde + brent + spread + réserves + tension + opinion + port Abidjan TEU (label, valeur, source non vide) | ☐ |
| 9 | Sky cockpit / typo | Tons `--sentinel-*`, lisible à 2,5 m, pas de débordement texte ni de gradient title | ☐ |
| 10 | Pas d'erreur console | DevTools Console : 0 erreur 4xx/5xx réseau (HEAD `/webcams/proxy?source_id=apm-apapa-gate-1` doit répondre 200) | ☐ |

**Items 1–6 : bloquants démo.** Items 7–10 : dégradables.

---

## Section B — Smoke vocal AYA (10 min)

Onglet chat du cockpit ouvert · voice ON · sortie sur enceinte salle ou casque.
Dire **textuellement** chaque prompt, vérifier l'action déclenchée + le payload.

| # | Prompt à dire | Action attendue | Vérification UI / SSE | OK |
|---|---|---|---|---|
| 1 | « **AYA** » (seul) | `aya.acknowledge_presence` | Réponse courte « Je suis là, Monsieur le Vice Premier Ministre, à votre écoute. » · pas de fallback RAG · pas de drawer | ☐ |
| 2 | « **AYA, donne-moi le brief** » | `aya.priority_summary` ou `aya.focus_zone_with_project` ou `aya.explain_why` | Narrative **Centre International Formation Drones — Napié** · 0 occurrence Konaté · cargo MV Atlantic Trader cité | ☐ |
| 3 | « **pv douanes** » | `aya.show_customs_record` | Drawer PV douanes du **18 mai** · pas la fiche navire · citations OCR p.2 | ☐ |
| 4 | « **résume Préfet Nawa** » | `aya.summarize_last_exchanges` (skill `summarize_long_document_v1`) | Drawer document_preview rapport Préfet Nawa (≈ 70 p.) · synthèse cacao / diversification / infrastructures | ☐ |
| 5 | « **génère le rapport complet** » | `aya.draft_strategic_report` | Drawer `rapport_complet` · `download_url` valide · GET → PDF 200 OK | ☐ |
| 6 | « **ouvre la prochaine réunion** » | `aya.open_next_meeting` | Bascule meeting live mode · navigate `/meetings/evt-prefet-nawa` · highlight correct | ☐ |

**Plan B si une action tombe en RAG** : reformuler avec la forme canonique du `docs/sentinel-ci-presenter-cheatsheet.md`. Mots pivots : « ordre du jour », « PV douanes », « rapport préfet », « diversification cacao », « décide option ».

---

## Section C — Rouge / Vert / Décision

| Bloc | Items rouges (FAIL bloquant) | Items orange (FAIL dégradable) | Décision |
|---|---|---|---|
| A. Visuel | 1, 2, 3, 4, 5, 6 | 7, 8, 9, 10 | |
| B. Vocal | 1, 3, 5, 6 | 2, 4 (les drills causaux ont des fallbacks PV / RAG) | |

**Règle** : ≥ 1 rouge → `No-go` (basculer sur la trame chat dégradée, prévenir Vice Premier Ministre). Tous verts ou seulement orange → `Go`. À la moindre incertitude sur l'overlay vessels (item 5/6) ou la chaîne PV douanes (B-3) → `Dégradé` : on présente sans la carte, on enchaîne S2 directement.

| Décision finale | ☐ Go | ☐ Dégradé | ☐ No-go |
|---|---|---|---|

---

## Section D — État pré-deploy mesuré dimanche 24 mai 2026 — 12h29 (UTC+2)

Sortie automatique de `scripts/smoke_predeploy_probe.py` exécuté contre `https://agentium.papai.ai`. **Disclaimer** : les FAIL ci-dessous marqués `POST-DEPLOY=oui` sont **attendus** tant que le backend prod n'a pas été redéployé sur HEAD `demo/agentic` (`d452e001`). Ils doivent **tous passer** après `git push origin demo/agentic` + redéploiement + `./scripts/predemo_reset.sh`. Si l'un d'entre eux reste FAIL post-deploy → bloquant.

### D.1 — Vocal (résolveur via `POST /api/v1/actions/resolve`)

| # | PASS | Prompt | Attendu | Obtenu | Conf. | Post-deploy ? |
|---|---|---|---|---|---|---|
| 1 | FAIL | AYA | `aya.acknowledge_presence` | `(no_match)` | 0.00 | **oui** |
| 2 | PASS | AYA, donne-moi le brief | `aya.priority_summary` | `aya.priority_summary` | 0.85 | non |
| 3 | FAIL | pv douanes | `aya.show_customs_record` | `(no_match)` | 0.00 | **oui** |
| 4 | FAIL | résume Préfet Nawa | `aya.summarize_last_exchanges` | `(no_match)` | 0.00 | **oui** |
| 5 | PASS | génère le rapport complet | `aya.draft_strategic_report` | `aya.draft_strategic_report` | 1.04 | non |
| 6 | PASS | ouvre la prochaine réunion | `aya.open_next_meeting` | `aya.open_next_meeting` | 0.89 | non |

Voice **3 / 6 PASS** ; hors-redeploy **3 / 3** (100 % de ce qui doit déjà marcher fonctionne).

### D.2 — API non-régression

| PASS | Check | Attendu | Obtenu | Post-deploy ? |
|---|---|---|---|---|
| PASS | `cockpit.date_label` | `Lundi 25 Mai 2026` | `Lundi 25 Mai 2026` | non |
| PASS | `vp_status_bar[0].key` | `zone-nord-tension` | `zone-nord-tension` | non |
| PASS | `vp_status_bar[0].pulse` | `True` | `True` | non |
| FAIL | `vp_status_bar[0].id` (alias analytics) | non-null | `null` | **oui** |
| FAIL | `press_preview[0]` CI-first | geo=CI ou Napié/Abidjan | `Mali / Kidal "toujours en guerre"` | **oui** |
| FAIL | `agenda_day.events` 4 premières dates = 25/05 | `2026-05-25 × 4` | `2026-04-15 × 4` | **oui** |
| PASS | `maritime/vessels` count | `16` | `16` | non |
| PASS | MV Atlantic Trader · `linked_cargo_id` | `cargo-abidjan-supply-001` | `cargo-abidjan-supply-001` | non |
| PASS | MV Atlantic Trader · `recommended_webcam_source_id` | `apm-apapa-gate-1` | `apm-apapa-gate-1` | non |
| PASS | `GET /webcams/proxy?source_id=apm-apapa-gate-1` | `200 image/*` | `200 image/jpeg` | non |
| FAIL | `HEAD /webcams/proxy?source_id=apm-apapa-gate-1` | `200` | `404` | **oui** |
| FAIL | manifest `aya.acknowledge_presence` présent | `True` | `False` | **oui** |
| PASS | `/calendar/events` sur `2026-05-25` | `≥ 6` | `6` | non |
| PASS | `/calendar/events` sur `2026-05-26` | `≥ 2` | `2` | non |

API **9 / 14 PASS** ; hors-redeploy **9 / 9** (aucune régression sur ce qui était déjà PASS dans le QA Vague 2).

### D.3 — Synthèse

- **12 / 20 PASS au total (60 %)**, **12 / 12 PASS hors redeploy** : la non-régression est verte. Tous les FAIL sont strictement liés à des phrases ou polishs accumulés dans les 5 commits non-déployés (`11745daf` → `09188fa6` → `d1490f18` → `4c0208e1` → `d452e001`).
- Action Ops bloquante avant 08h30 lundi : `git push origin demo/agentic` + redéploy backend + frontend + `./scripts/predemo_reset.sh`. Sans ça, **8 contrôles cassent**, dont 4 démo-bloquants (A-3 agenda, A-4 presse, B-1 wake-word, B-3 PV douanes).
- Re-jouer ce probe (`python3 scripts/smoke_predeploy_probe.py`) **après redéploy** : le décompte attendu est 20/20 PASS. Tout FAIL résiduel = bloquant lundi matin.

---

## Annexe — Quick start probe pré-deploy

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL='<operator-email>' \
AGENTIUM_PASSWORD='<from-secret-manager>' \
WORKSPACE_SLUG=sentinel-ci \
python3 scripts/smoke_predeploy_probe.py
```

Lecture seule (login + 6 résolutions + 14 GET / HEAD), aucune mutation. Exit code 0 si ≥ 50 % PASS, 1 sinon.
