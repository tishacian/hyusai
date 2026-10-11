# QA UI prod — SENTINEL-CI — 2026-05-25

## Verdict global

**GO_DÉGRADÉ** — la trame VP est jouable en prod avec les Plans B documentés, mais ce n'est pas un **GO readiness 100 %** strict.

Raison : le gate automatisé avec reset a bien validé smoke, resolver, deck phrases, S1/S2 et console, mais a échoué une fois sur **S3.5 navigation `/reputation`**. Le rerun S3 isolé puis la trame unifiée S1+S2+S3 sont repassés à 100 %. En parallèle, la capture S1.7 montre que le clic pin Atlantic Trader n'expose pas systématiquement la fiche navire IMO/MMSI ; l'effet webcam/port est présent, mais le critère fiche navire reste partiel.

## Déploiement vérifié

| Élément | Statut | Preuve |
|---|---:|---|
| VM `/home/ubuntu/omnirag` | PASS | `demo/agentic` au tip `39618aa fix(sentinel): mark CI press preview region` |
| Docker backend | PASS | `agentium-backend` healthy |
| Docker frontend | PASS | `agentium-frontend` healthy |
| Workspace reset | PASS | `predemo_reset.sh --with-reset` via gate, agenda reseed 8/8 |

## Scores

| Scénario | PASS | PARTIAL | FAIL | Score |
|---|---:|---:|---:|---:|
| S1 | 7 | 1 | 0 | 94 % |
| S2 | 8 | 0 | 0 | 100 % |
| S3 | 6 | 0 | 0 | 100 % final, avec 1 flake gate |
| Plans B | 2 | 0 | 0 | 100 % |
| V21 | 4 | 0 | 0 | 100 % |
| **Global présentateur** | 27 | 1 | 0 | **98 %** |

## Gate automatisé

| Étape gate | Statut | Observation |
|---|---:|---|
| `predemo_reset` | PASS | demo time + agenda + warm reports OK |
| Smoke probe | PASS | `26/26` |
| S3 resolver local | PASS | `12/12` |
| Deck phrases resolve | PASS | `14/14 PASS`, `0 PARTIAL`, `0 FAIL` |
| `qa_trame_full.mjs` | PASS | `18P 0Pa 0F` après correction harness Plan B |
| Console trame | PASS | `console500=0`, `pageerror=0` |
| `qa_s3_security.mjs` | FAIL | `9P 0Pa 1F` sur S3.5 : drill visible mais URL restée `/securite/monitor` |
| Console S3 | PASS | `console500=0`, `pageerror=0` |

Artefacts principaux :
- `docs/status-screenshots/2026-05-25-qa-gate-prod/gate-summary.json`
- `docs/status-screenshots/2026-05-25-qa-gate-prod/qa-trame-full-results.json`
- `docs/status-screenshots/2026-05-25-qa-gate-prod/qa-s3-results.json`
- `docs/status-screenshots/2026-05-25-qa-gate-prod/qa-s3-results-rerun-pass.json`
- `docs/status-screenshots/2026-05-25-qa-gate-prod/qa-trame-full-s3-results.json`

## Tableau détaillé

| Étape | Statut | Observation | Fix proposé | Priorité | Screenshot |
|---|---:|---|---|---:|---|
| S1.1 | PASS | KPIs, carte, date et Zone Nord Tendue visibles | Aucun | P2 | `S1-01-cockpit.png` |
| S1.2 | PASS | Navigation stratégie, récit Napié/Aerostar visible | Aucun | P2 | `S1-02-nord-tendue.png` |
| S1.3 | PASS | Drawer PV douanes ouvert, titre et contenu lisibles ; iframe PDF headless non bloquante | Aucun | P2 | `S1-03-pv-douanes.png` |
| S1.4 | PASS | Atlantic Trader + webcam APM Apapa visibles | Aucun | P2 | `S1-04-atlantic-trader.png` |
| S1.5 | PASS | Situation port résolue en `aya.show_maritime_traffic`, panel maritime + webcam | Aucun | P2 | `S1-05-situation-port.png` |
| S1.6 | PASS | Drawer courrier dédouanement advisory ouvert | Aucun | P2 | `S1-06-courrier-dedouanement.png` |
| S1.7 | PARTIAL | Clic manuel produit webcam/port, mais pas fiche navire IMO/MMSI fiable | Corriger layer order/hit-test deck.gl vessel ou utiliser Plan B AYA | P0 | `S1-07-vessel-click.png` |
| S1.8 | PASS | Monitor : carte, flux terrain, APM Apapa, 17/17 | Aucun | P2 | `S1-08-mission-control.png` |
| S2.T | PASS | Agenda + presse, Préfet Nawa visible | Aucun | P2 | `S2-09-agenda.png` |
| S2.1 | PASS | Résumé Préfet Nawa visible | Aucun | P2 | `S2-10-resume-nawa.png` |
| S2.2 | PASS | 3 options cacao visibles | Aucun | P2 | `S2-11-preconisations.png` |
| S2.3 | PASS | Drawer rapport stratégique ouvert ; iframe PDF headless non bloquante | Aucun | P2 | `S2-12-rapport-strategique.png` |
| S2.4 | PASS | Patch ODJ cacao proposé | Aucun | P2 | `S2-13-odj-patch.png` |
| S2.5 | PASS | Validation ODJ cacao OK | Aucun | P2 | `S2-14-odj-validate.png` |
| S2.6 | PASS | Meeting live démarré + ODJ visible | Aucun | P2 | `S2-15-meeting-live.png` |
| S2.7 | PASS | Option B loggée | Aucun | P2 | `S2-16-decision-b.png` |
| V21 rail | PASS | Sécurité + Reputation visibles | Aucun | P2 | `V21-01-nav-rail.png` |
| V21 `/securite` | PASS | Shell sécurité agrégé visible | Aucun | P2 | `V21-02-securite-shell.png` |
| V21 monitor | PASS | Security Monitor + ADS-B baseline visible | Aucun | P2 | `V21-03-security-monitor.png` |
| V21 veille | PASS | Veille sociale + export advisory visible | Aucun | P2 | `V21-04-veille-sociale.png` |
| S3.1 | PASS | Bloc posture sécuritaire + Conseil 15h visible | Aucun | P2 | `S3.1-posture-securite.png` |
| S3.2 | PASS | Drawer pulsation sociale ouvert | Aucun | P2 | `S3.2-pulsation-sociale.png` |
| S3.3 | PASS | Timeline rumeur + démenti officiel visible | Aucun | P2 | `S3.3-rumeur-frontiere.png` |
| S3.4 | PASS | Drawer ADS-B Sahel advisory ouvert | Aucun | P2 | `S3.4-troupes-sahel.png` |
| S3.5 | PASS final / FAIL gate 1x | Rerun et trame unifiée naviguent vers `/reputation`; gate dédié a flaké une fois en restant sur `/securite/monitor` | Renforcer effet `assistant-navigate` ou fermeture drawer avant navigation | P1 | `S3.5-drill-reputation.png` |
| S3.6 | PASS | Drawer communiqué sécurité ouvert | Aucun | P2 | `S3.6-communique-securite.png` |

## Régressions vs run précédent

- **Amélioré** : Plan B Port Vridi passe quand il est testé comme action indépendante depuis le cockpit. Le premier FAIL venait du harness qui héritait de la route Zone Nord sans couche maritime.
- **À surveiller** : S3.5 a produit un FAIL isolé dans le gate dédié, puis PASS en rerun S3 et PASS dans la trame unifiée. Risque flake présentateur faible, mais réel.
- **Toujours fragile** : S1.7 clic pin vessel ne donne pas une fiche navire IMO/MMSI fiable. Le Plan B AYA `AYA, montre le cargo Atlantic Trader.` est stable.

## Console / infra

- `0` erreur HTTP 500 détectée.
- `0` `pageerror` détecté.
- 404 génériques observés dans la console headless : 11 côté trame, 3 côté S3, 14 côté unifié. Le harness ne capture pas l'URL de ressource ; pas de corrélation endpoint possible sans enrichir la sonde console.
- PDF iframe blanc en headless non considéré bloquant : les drawers exposent les titres et contenus/citations lisibles.

## Plan B validés

| Plan B | Statut | Note |
|---|---:|---|
| Chip Zone Nord | PASS | Clic vers `/strategie?zone=zone-nord&layers=threat,press` |
| Port Vridi · cargo demo | PASS | Depuis cockpit : bouton visible, clic ouvre vue maritime/webcam |
| S1.7 vessel | PASS comme alternative AYA | Utiliser `AYA, montre le cargo Atlantic Trader.` plutôt que le clic pin |
| S3.5 réputation | PASS comme alternative manuelle | Si AYA ne route pas, cliquer rail **Reputation** |

## Recommandation présentateur

- Jouer S1.7 avec la phrase AYA Atlantic Trader, pas avec le clic pin en live.
- Pour S3.5, garder le rail **Reputation** comme clic de secours immédiat.
- Utiliser Quick Panel texte `Cmd+J`; ne pas dépendre du STT en salle.

## Actions ops avant VP

1. Si l'objectif est **GO 100 % strict**, corriger puis redéployer le hit-test/layer order du clic vessel Atlantic Trader.
2. Stabiliser S3.5 : l'effet AYA doit fermer/neutraliser le drawer ADS-B puis naviguer explicitement vers `/hypervisor/mission-room/reputation`.
3. Relancer `qa_demo_gate.sh --with-reset` après ces deux corrections ; critère attendu : `readiness_100=true`, `0 FAIL`.

## Notes QA harness

Deux corrections locales de harness ont été appliquées pendant l'analyse, sans commit ni push :

- `scripts/qa_demo_gate.sh` : conversion de `QA_GATE_DIR` en chemin absolu avant d'appeler Playwright, pour éviter l'écriture sous `scripts/playwright/docs/...`.
- `scripts/playwright/qa_trame_full.mjs` : Plan B Port Vridi testé comme fallback indépendant depuis le cockpit ; S1.7 ne clique plus le bouton Port avant le pin vessel et reclassifie correctement l'absence de fiche navire.
