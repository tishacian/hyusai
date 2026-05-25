% SENTINEL-CI — Cheat-sheet présentateur AYA
% Démo Vice-Président — Lundi 25 mai 2026, 09h00
% Source de vérité : pack résolveur `sentinel_ci_aya_v1` à HEAD `6335d460`

## En-tête

- **Objectif** : rester dans le pack déterministe pour neutraliser l'hallucination — chaque prompt ci-dessous est garanti copy-paste (vérifié contre le code à HEAD `6335d460` et les QA post-deploy S1/S2 du 24 mai).
- **URL** : `https://agentium.papai.ai/hypervisor/mission-room/cockpit` — **workspace** `sentinel-ci` — **profil** `vigie_executive` — **compte** `thibaud.ishacian@datategy.net`.
- **Tip prod requis** : `6335d460` (durcissement confirm + `aya.show_maritime_traffic`). À déployer **avant 09h00**. Sans ce tip, S1.5 plante et tout filler poli matche le yes-stub.
- **Règles d'or** :
  1. Démarrer chaque demande par un **verbe d'action** (« pourquoi », « montre », « rédige », « démarre », « décide », « résume ») ou par « **AYA, …** ».
  2. **Ne jamais** ouvrir une phrase nouvelle par un filler poli isolé (« OK… », « OK très bien… », « D'accord… ») — risque de matcher `voice.confirm_yes`. Si filler, **enchaîner immédiatement** sur le verbe (« OK, montre la situation au port » — la longueur > 4 tokens désactive le guard confirm).
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
| S1.5 | `AYA, montre la situation au port.` (NOUVEAU `6335d460`) | `situation au port` / `ouvre la vue port` / `état du port Abidjan` | `aya.show_maritime_traffic` — vue port Abidjan (map + panel maritime + cargo). |
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
| S2.5 | `AYA, ajoute le point cacao à l'ordre du jour.` | `mets à jour l'ordre du jour` / `patch l'agenda` | `aya.update_meeting_agenda` — **dire « cacao »** (sujet hardcodé en prod ; commit `e40432b2` paramétrable pas encore déployé). Stage `pending_agenda_patch`, attend confirmation. |
| S2.6 | `Oui, valide.` | `valide la mise à jour de l'ordre du jour` / `applique l'ordre du jour` | `voice.confirm_yes` → résout `aya.confirm_agenda_patch` via awaiting bucket. ODJ patché. |
| S2.7 | `AYA, démarre la réunion.` | `commence la réunion` / `lance la réunion` / `on y va` | `aya.start_meeting` — navigate `/agenda/meeting/{id}`, set `current_meeting`. |
| S2.8 | `AYA, décide option B.` | `valide l'option B` / `choisis l'option B` / `j'arbitre option B` | `aya.log_decision` — décision option B persistée (diversification anacarde). |
| S2.9 | `AYA, qu'avons-nous décidé la dernière fois ?` | `rappelle-moi nos décisions` / `décisions passées` | `aya.recall_past_decisions` — top-5 décisions, nouvelle en tête. |

## Tableau S3 — Posture sécuritaire dual-axis

Pack additionnel `sentinel_ci_aya_security_v1` (activé via `workspace.settings.actions.enabled_packs`). Le scénario s'enchaîne après S2.7 (Décision Option B). Tous les signaux sont demo-safe : ADS-B advisory only, handles citoyens pseudonymisés (`@citoyen_***` / `@rumeur_***`), critique réputation = article L'Inter déjà publié (S1).

| Étape | Prompt principal | Variante OK | Effet attendu |
|---|---|---|---|
| S3.1 | `AYA, montre-moi la posture sécuritaire du jour.` | `montre la posture sécuritaire` / `posture sécuritaire intérieur extérieur` / `posture sécurité dual-axis` / `show security posture` | `aya.show_security_posture` — cockpit, bloc « Posture sécuritaire » mis en avant (Intérieur vigilance / Extérieur Sahel élevée + pastille 15h00 Conseil Défense). |
| S3.2 | `AYA, montre la pulsation sociale à Abidjan.` | `pulsation sociale Abidjan` / `montre les tweets du jour` / `snapshot Twitter Abidjan` / `show social pulse` | `aya.show_social_pulse` — couche carte `social-geo` activée + drawer liste tweets (officiels / citoyens / rumeur). |
| S3.3 | `AYA, d'où vient la rumeur frontière Nord ?` | `trace la rumeur frontière Nord` / `chaîne OSINT rumeur Nord` / `qui a lancé la rumeur Bouna` / `trace rumor origin` | `aya.trace_rumor_origin` — zoom carte Nord, couche `border-tension`, drawer chaîne tweet → telegram → blog → démentis + proposition « Rédiger un communiqué ». |
| S3.4 | `AYA, montre les mouvements de troupes au Sahel.` | `snapshot ADS-B Sahel` / `montre l'activité aérienne Sahel` / `troupes Bamako Ouaga Niamey` / `show troops movement` | `aya.show_troops_movement` — couches `military-air` + `border-tension` actives, drawer ADS-B advisory only. |
| S3.5 | `AYA, montre le drill de réputation 2 positifs 1 critique.` | `drill réputation` / `réputation 2 positifs 1 critique` / `montre le détail réputation` / `show reputation drill` | `aya.show_reputation_drill` — vue Réputation, score 72/100, 3 cartes (Jeune Afrique, Fraternité Matin, L'Inter). |
| S3.6 | `AYA, prépare un communiqué de sécurité sur la rumeur Nord.` | `rédige le communiqué démentant la rumeur Nord` / `prépare un communiqué FANCI sur la frontière` / `draft security communique` | `aya.draft_security_communique` — drawer brouillon communiqué (skill `draft_response_email_v1`), validation advisory. |

Plan B clic par étape : voir `docs/sentinel-ci-demo-trame-s3-presenter-card-2026-05-25.docx`.

## À ne PAS dire (bloc rouge)

- `OK` seul / `très bien` seul / `D'accord` seul → matche `voice.confirm_yes` (le guard `6335d460` désamorce les fillers > 4 tokens, mais un filler isolé reste piégeux). **Toujours enchaîner sur un verbe.**
- Ultra-courts ambigus (`le rapport`, `la décision`, `option B` seul, `cacao` à sec hors S2.3, `Préfet` seul, `Napié` seul) → `no_match` puis fallback RAG long.
- Anglicismes hors pack (`forecast cocoa`, `show port view`, `show me the cargo`, `what's happening up north`) → `no_match`. Anglicismes **couverts** : `morning briefing`, `next meeting`, `start meeting`, `customs report`, `draft a customs email`, `why is the north tense`, `cacao diversification recommendations`, `show the port situation`.
- `M. le Vice Président` / `M. le Vice-Président` → désormais **toujours** dire et écrire **« Monsieur le Vice-Président »** (TTS sinon prononce « M » comme la lettre).
- `AYA, explique le cargo Atlantic Trader` → couvert par `6335d460` (`explique le cargo atlantic trader`), mais en cas de doute préférer la forme canonique S1.4 (`montre le cargo Atlantic Trader`).

## Plan B vocal

- **Réponse longue/hésitante sans `action_effect` UI** (drawer ou map ne bouge pas) : fallback RAG silencieux. Recommencer avec la phrase canonique du tableau, en insistant sur le **mot pivot** (`pourquoi nord`, `PV douanes`, `ordre du jour`, `diversification cacao`, `décide option`, `situation au port`).
- **AYA prononce mal un nom** (Napié, Nawa, Aerostar, Atlantic Trader) : continuer naturellement, **ne pas relancer** — pas d'impact sur la suite des matches.
- **Confirm `Oui, valide` ne déclenche rien** : vérifier qu'une proposition est bien staged (drawer `assistant-propose` visible). Sinon, redire la commande qui propose (S2.5).
- **Filler poli involontaire au début** (`OK…`) : ajouter immédiatement un verbe — le guard > 4 tokens désactive le match confirm.

## Annexe

- **Pack résolveur** : `sentinel_ci_aya_v1` dans `backend/app/services/actions/registry.py` (lignes 274-1041).
- **Tip prod requis** : `6335d460` — *Fix demo-eve bugs: confirm-stub guard, zone-nord focus, panel snap-open, "Monsieur" TTS*.
- **Baselines de confiance** : `docs/sentinel-ci-qa-postdeploy-s1-2026-05-24.md` (6 PASS / 1 WARN), `docs/sentinel-ci-qa-postdeploy-s2-2026-05-24.md` (9 PASS / 1 WARN).
- **Seuil résolveur** : `min_confidence = 0.78` ; guard confirm : `_CONFIRM_MAX_TOKENS = 4`.
- **Dernier audit cheat-sheet** : 25 mai 2026, 00h20 (réécriture concise pré-démo, alignée HEAD `6335d460`).
