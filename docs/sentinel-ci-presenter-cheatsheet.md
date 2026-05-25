% SENTINEL-CI — Cheat-sheet présentateur AYA
% Démo Vice-Président — Lundi 25 mai 2026, 09h00
% Source de vérité : trame démo VP validée en QA

## En-tête

- **Objectif** : garder des phrases copy-paste, stables en salle, qui ouvrent les bons écrans sans improvisation.
- **URL** : `https://agentium.papai.ai/hypervisor/mission-room/cockpit` — **workspace** `sentinel-ci` — **profil** `vigie_executive` — **compte** `thibaud.ishacian@datategy.net`.
- **Pré-requis prod** : build du matin déployé avant passage VP, avec scénario port, Nawa et S3 chargés.
- **Règles d'or** :
  1. Démarrer chaque demande par un **verbe d'action** (« pourquoi », « montre », « rédige », « démarre », « décide », « résume ») ou par « **AYA, …** ».
  2. **Ne jamais** ouvrir une phrase nouvelle par un filler poli isolé (« OK… », « OK très bien… », « D'accord… »). Si filler, **enchaîner immédiatement** sur le verbe (« OK, montre la situation au port »).
  3. Si AYA répond hors-sujet ou en RAG long : recommencer avec la **forme canonique** du tableau (colonne « Prompt principal »).

## Wake-word

| Code | Prompt | Effet |
|---|---|---|
| W.1 | `AYA` | `aya.acknowledge_presence` — « Je suis là, Monsieur le Vice-Président, à votre écoute. » |
| W.2 | `AYA, <suite>` | wake-word retiré avant scoring ; la suite est routée normalement. |

## Tableau S1 — Drill causal Nord

| Étape | Prompt principal | Variante OK | Effet attendu |
|---|---|---|---|
| S1.1 | `AYA, pourquoi la situation Nord est-elle tendue ?` | `pourquoi le Nord est-il tendu` / `pourquoi nord tendu` | `aya.explain_why` — narrative Napié / Aerostar / Vridi / 120 j. |
| S1.2 | `AYA, ouvre le PV douanes.` | `montre le PV douanes` / `voir le PV des douanes` / `pv douanes` | `aya.show_customs_record` — drawer document_preview, PV 18 mai, page 2. |
| S1.3 | `AYA, focus sur la zone Nord et le projet Napié.` | `zoom sur la région Nord` / `projet sensible Nord` | `aya.focus_zone_with_project` — carte recadrée sur Korhogo/Poro + highlight projet drones. |
| S1.4 | `AYA, montre le cargo Atlantic Trader.` | `montre le navire MV Atlantic Trader` / `explique le cargo Atlantic Trader` / `voir flux entrée port` | `aya.show_vessel_evidence` — panel maritime, AIS pin, webcam APM Apapa, propose PV. |
| S1.5 | `AYA, montre la situation au port.` | `situation au port` / `ouvre la vue port` / `état du port Abidjan` | `aya.show_maritime_traffic` — vue port Abidjan (map + panel maritime + cargo). |
| S1.6 | `AYA, rédige le courrier de dédouanement pour Atlantic Trader.` | `rédige le mail dédouanement` / `email dérogation Atlantic Trader` | `aya.draft_customs_email` — drawer email pré-rédigé, recipient DGD Abidjan. |

## Tableau Transition

| Étape | Prompt principal | Variante OK | Effet attendu |
|---|---|---|---|
| T.1 | `AYA, quel est mon prochain rendez-vous ?` | `prochain rdv` / `prochaine réunion` / `next meeting` | `aya.open_next_meeting` — navigate agenda, highlight `evt-prefet-nawa` (11h00, Soubre). |

## Tableau S2 — Préfet Nawa (cacao)

| Étape | Prompt principal | Variante OK | Effet attendu |
|---|---|---|---|
| S2.1 | `AYA, donne-moi le résumé du rapport préfet.` | `résume-moi le rapport du préfet` / `derniers échanges` | `aya.summarize_last_exchanges` — synthèse Nawa/Soubre + propose préconisations cacao. |
| S2.2 | `AYA, résume le rapport Préfet Nawa.` | `résume Préfet Nawa` / `résume Nawa` | `aya.summarize_last_exchanges` — même handler, déclenche skill `summarize_long_document_v1` (long doc). |
| S2.3 | `AYA, donne-moi des préconisations sur le cacao.` | `recommandations cacao` / `diversification cacao` | `aya.recommend_cacao` — 3 leviers chiffrés (transformation 4,2 Mds FCFA, coop, PPP). |
| S2.4 | `AYA, génère le rapport complet.` | `prépare le rapport complet` / `génère le rapport stratégique` | `aya.draft_strategic_report` — drawer PDF (12 p.), audit `report.strategic.generated`. |
| S2.5 | `AYA, ajoute le point cacao à l'ordre du jour.` | `mets à jour l'ordre du jour` / `patch l'agenda` | `aya.update_meeting_agenda` — **dire « cacao »**. Proposition d'ordre du jour affichée, attend confirmation. |
| S2.6 | `Oui, valide.` | `valide la mise à jour de l'ordre du jour` / `applique l'ordre du jour` | `voice.confirm_yes` → résout `aya.confirm_agenda_patch` via awaiting bucket. ODJ patché. |
| S2.7 | `AYA, démarre la réunion.` | `commence la réunion` / `lance la réunion` / `on y va` | `aya.start_meeting` — navigate `/agenda/meeting/{id}`, set `current_meeting`. |
| S2.8 | `AYA, décide option B.` | `valide l'option B` / `choisis l'option B` / `j'arbitre option B` | `aya.log_decision` — décision option B persistée (diversification anacarde). |
| S2.9 | `AYA, qu'avons-nous décidé la dernière fois ?` | `rappelle-moi nos décisions` / `décisions passées` | `aya.recall_past_decisions` — top-5 décisions, nouvelle en tête. |

## Tableau S3 — Posture sécuritaire dual-axis

Le scénario s'enchaîne après S2.7 (Décision Option B) et se joue avant le Conseil Défense restreint de 15h00. Tous les signaux sont demo-safe : ADS-B advisory only, handles citoyens pseudonymisés (`@citoyen_***` / `@rumeur_***`), critique réputation = article L'Inter déjà publié (S1).

| Étape | Phrase principale | Variante de secours | Effet attendu |
|---|---|---|---|
| S3.1 | `AYA, montre-moi la posture sécuritaire du jour.` | `montre la posture sécuritaire` / `posture sécurité dual-axis` | Cockpit : bloc « Posture sécuritaire » mis en avant (Intérieur vigilance / Extérieur Sahel élevée + pastille 15h00 Conseil Défense). |
| S3.2 | `AYA, montre la pulsation sociale à Abidjan.` | `pulsation sociale Abidjan` / `montre les tweets du jour` | Vue Veille sociale : 18 signaux publics, canaux vérifiés, citoyens pseudonymisés et rumeurs suivies. |
| S3.3 | `AYA, d'où vient la rumeur frontière Nord ?` | `trace la rumeur frontière Nord` / `chaîne OSINT rumeur Nord` | Zoom Nord, couche frontière, timeline tweet 11h42 → Telegram 12h08 → blog 12h48 → FANCI 13h46 → Préfecture 13h52. |
| S3.4 | `AYA, montre les mouvements de troupes au Sahel.` | `snapshot ADS-B Sahel` / `montre l'activité aérienne Sahel` | Security Monitor : traces ADS-B advisory, zones de surveillance et bases CEDEAO, sans confirmation opérationnelle. |
| S3.5 | `AYA, montre le drill de réputation 2 positifs 1 critique.` | `drill réputation` / `montre le détail réputation` | Vue Réputation : score 72/100, deux lectures favorables, une critique L'Inter sur le budget défense. |
| S3.6 | `AYA, prépare un communiqué de sécurité sur la rumeur Nord.` | `rédige le communiqué démentant la rumeur Nord` | Drawer brouillon communiqué : FANCI + Préfecture Nord + coordination CEDEAO, validation humaine obligatoire. |

Plan B clic par étape : voir `docs/sentinel-ci-demo-trame-s3-presenter-card-2026-05-25.docx`.

## À ne PAS dire (bloc rouge)

- `OK` seul / `très bien` seul / `D'accord` seul → peut être interprété comme une validation. **Toujours enchaîner sur un verbe.**
- Ultra-courts ambigus (`le rapport`, `la décision`, `option B` seul, `cacao` à sec hors S2.3, `Préfet` seul, `Napié` seul) → `no_match` puis fallback RAG long.
- Anglicismes hors pack (`forecast cocoa`, `show port view`, `show me the cargo`, `what's happening up north`) → `no_match`. Anglicismes **couverts** : `morning briefing`, `next meeting`, `start meeting`, `customs report`, `draft a customs email`, `why is the north tense`, `cacao diversification recommendations`, `show the port situation`.
- `M. le Vice Président` / `M. le Vice-Président` → désormais **toujours** dire et écrire **« Monsieur le Vice-Président »** (TTS sinon prononce « M » comme la lettre).
- `AYA, explique le cargo Atlantic Trader` → en cas de doute, préférer la forme canonique S1.4 (`montre le cargo Atlantic Trader`).

## Plan B vocal

- **Réponse longue/hésitante sans `action_effect` UI** (drawer ou map ne bouge pas) : fallback RAG silencieux. Recommencer avec la phrase canonique du tableau, en insistant sur le **mot pivot** (`pourquoi nord`, `PV douanes`, `ordre du jour`, `diversification cacao`, `décide option`, `situation au port`).
- **AYA prononce mal un nom** (Napié, Nawa, Aerostar, Atlantic Trader) : continuer naturellement, **ne pas relancer** — pas d'impact sur la suite des matches.
- **Confirm `Oui, valide` ne déclenche rien** : vérifier qu'une proposition est bien visible à l'écran. Sinon, redire la commande qui propose (S2.5).
- **Filler poli involontaire au début** (`OK…`) : ajouter immédiatement un verbe.

## Annexe

- **Référence technique interne** : phrases AYA déclarées dans `backend/app/services/actions/registry.py`.
- **Baselines de confiance** : `docs/sentinel-ci-qa-postdeploy-s1-2026-05-24.md` (6 PASS / 1 WARN), `docs/sentinel-ci-qa-postdeploy-s2-2026-05-24.md` (9 PASS / 1 WARN).
- **Dernier audit cheat-sheet** : 25 mai 2026, 00h20 (réécriture concise pré-démo).
