# SENTINEL-CI — Guide pas-à-pas démo VP (25 mai 2026)

**Durée** : ~13 min (S1 5 min + transition 1 min + S2 7 min)  
**URL** : `https://agentium.papai.ai/hypervisor/mission-room/cockpit?workspace=sentinel-ci`  
**Profil** : `vigie_executive`  
**Règle d'or** : chaque demande à AYA commence par un **verbe d'action** ou « **AYA, …** ». Ne jamais dire « OK » seul.

---

## TL;DR — lancer S1 webcam + PDF en 30 secondes

1. Cockpit ouvert → cliquer **Zone Nord · Tendue** (chip rouge) → carte recentrée Nord.
2. Dire **« AYA, montre le cargo Atlantic Trader. »** → vignette webcam APM Apapa + proposition PV.
3. Dire **« AYA, ouvre le PV douanes. »** → drawer PDF page 2 surlignée.
4. Plan B sans voix : cliquer **Port Vridi · webcam demo** (légende carte cockpit) ou **APM Apapa Gate #1** (FLUX TERRAIN).

---

## Où sont les webcams

| Chemin | Action UI | Phrase AYA (canonique) | Résultat attendu |
|--------|-----------|------------------------|------------------|
| **1. Via AYA** | Bulle AYA ou micro | `AYA, montre le cargo Atlantic Trader.` | Panel maritime + événement `assistant-show-webcam` → source `apm-apapa-gate-1` |
| **2. Via FLUX TERRAIN** | Carte → mode live → panneau **Flux terrain** (bas) | `AYA, montre la situation au port.` | Bascule mode maritime ; webcam APM dans la grille ; sidebar : **APM Apapa Gate #1 · Port Vridi (demo)** en tête avec badge **Port Vridi · cargo demo** |
| **3. Via click cargo carte** | Cockpit → carte preview → clic pin violet **MV Atlantic Trader** | *(optionnel)* même phrase S1.4 | Vignette webcam sous la carte + navigation `/strategie?mode=live&panel=maritime&vessel=627012345` |

**Plan B webcam** : bouton **Port Vridi · webcam demo** dans la légende carte cockpit (sans AYA).

---

## Où sont les PDF

| Document | Phrase AYA | Drawer / UI attendu | Plan B clic |
|----------|------------|---------------------|-------------|
| **PV douanes 18 mai** | `AYA, ouvre le PV douanes.` | Drawer `document_preview` · target `proces-verbal-douanes-non-conformite-2026-05-18` · page 2 OCR surlignée · bouton télécharger | Après S1.4, accepter la proposition « Voir le PV ? » |
| **Rapport Préfet Nawa (~70 p.)** | `AYA, résume le rapport Préfet Nawa.` | Synthèse inline chat + proposition préconisations cacao (pas de PDF complet ici) | Agenda → événement Nawa 11h → lien contexte |
| **Rapport stratégique cacao** | `AYA, génère le rapport complet.` | Drawer PDF ~12 p. · URL signée · bouton **Télécharger** | — |

---

## S1 — Nord : « Comprendre pour agir » (5 min)

| Minute | Étape | Phrase AYA | Action UI principale | Chemin clic alternatif | Plan B |
|--------|-------|------------|----------------------|------------------------|--------|
| 0:00 | **S1.1** Brief | `AYA, c'est lundi matin. Qu'est-ce qui demande mon attention ?` | Cockpit auto-charge (5 blocs : posture, KPI, directive, carte, arbitrages) | sidebar **Cockpit** (URL : `/hypervisor/mission-room/cockpit`) — la vue **EST** le brief | AYA only pour la version vocale ; l'écran est lisible seul |
| 0:30 | **S1.2** Pourquoi Nord tendue | `AYA, pourquoi la situation Nord est-elle tendue ?` | Navigation Carte · focus Korhogo/Poro · highlight Napié | cockpit → **chip Zone Nord · Tendue** (chip rouge) → carte recentrée | Clic **Ouvrir le dossier Zone Nord** (bannière AYA) |
| 1:30 | **S1.3** Focus zone Nord + Napié | `AYA, focus sur la zone Nord et le projet Napié.` | Recadrage carte + surbrillance projet drones | cockpit → bouton **Brief opérationnel · Projet sensible Nord** → strategie?focus=zone-nord&highlight=proj-drone-centre-napie | Clic chip Zone Nord à nouveau |
| 2:30 | **S1.4** Cargo Atlantic Trader | `AYA, montre le cargo Atlantic Trader.` | Vignette webcam APM Apapa + proposition PV | cockpit/strategie → **clic pin MV Atlantic Trader** sur carte preview **ou** bouton **Port Vridi · webcam demo** (légende carte) | FLUX TERRAIN → **APM Apapa Gate #1** en tête (carte live) |
| 3:30 | **S1.5** PV douanes | `AYA, ouvre le PV douanes.` | Drawer PDF PV 18/05 · page 2 · citations OCR | strategie panel maritime → **clic chip PV douanes 18 mai** sous la fiche cargo (drawer document_preview, page 2) | Variante voix `pv douanes` ou accepter la proposition `propose-customs-pdf-show` |
| 4:30 | **S1.6** Courrier dédouanement | `AYA, rédige le courrier de dédouanement pour Atlantic Trader.` | Drawer email `customs_derogation` advisory | drawer PV → **bouton « Préparer email dérogation »** (proposal `propose-customs-derogation`) | — |

**Phrase de clôture S1** : « En cinq minutes, AYA est passée du signal territorial à la preuve douanière, avec une proposition d'action sourcée — sans exécuter à ma place. »

---

## Transition — Agenda (1 min)

| Minute | Étape | Phrase AYA | Action UI principale | Chemin clic alternatif | Plan B |
|--------|-------|------------|----------------------|------------------------|--------|
| 5:00 | **T.1** Prochain rendez-vous | `AYA, quel est mon prochain rendez-vous ?` | Navigation Agenda · highlight Préfet Nawa 11h | sidebar **Agenda** → carte **Préfet Nawa · 11:00 Soubré** dans la timeline | Clic manuel événement `evt-prefet-nawa` |

---

## S2 — Nawa / cacao (7 min)

| Minute | Étape | Phrase AYA | Action UI principale | Chemin clic alternatif | Plan B |
|--------|-------|------------|----------------------|------------------------|--------|
| 6:00 | **S2.1** Résumé Nawa | `AYA, résume le rapport Préfet Nawa.` | Synthèse inline + proposition préconisations | agenda → event Nawa → bouton **« Synthèse AYA »** (chip Synthese AYA dans agenda-timeline-panel) | `AYA, donne-moi le résumé du rapport préfet.` |
| 7:00 | **S2.2** Préconisations cacao | `AYA, donne-moi des préconisations sur le cacao.` | 3 options chiffrées (transformation, coop, PPP) | **AYA only** — les préconisations sont générées par le skill `generate_recommendations_v1` ; pas d'équivalent clic dans la démo (planifié post-démo : tuile « Préconisations cacao » sur la fiche event) | `recommandations cacao` |
| 8:00 | **S2.3** Rapport stratégique | `AYA, génère le rapport complet.` | Drawer PDF ~12 p. · URL signée | **AYA only** — la génération PDF passe par le skill `draft_strategic_report` ; pas de bouton équivalent (planifié : action « Générer rapport » dans `/decisions?focus=package-cacao-diversification`) | `génère le rapport stratégique` |
| 9:00 | **S2.4** Ajout point cacao ODJ | `AYA, ajoute le point cacao à l'ordre du jour.` | Drawer `calendar_agenda_patch` · pending staged | **agenda → event Préfet Nawa → form « Proposer un point ODJ » (champ titre + bouton « Proposer modification »)** dans la fiche meeting (`/agenda/meeting/evt-prefet-nawa`) ; ou directement **`+ Point` dans l'ODJ** pour patch immédiat (sans staging) | Dire **cacao** explicitement |
| 10:00 | **S2.5** Validation patch | `Oui, valide.` | Patch appliqué · badge « Ajouté par AYA » | **Bannière orange « Modification ODJ proposée · AYA » → bouton « Valider modification »** sur la fiche event (agenda detail panel) **ou** sur la page meeting (`/agenda/meeting/evt-prefet-nawa`) | Redire S2.4 si rien staged |
| 11:00 | **S2.6** Démarrer réunion | `AYA, démarre la réunion.` | Route `/agenda/meeting/evt-prefet-nawa` + `current_meeting` set | agenda → event Préfet Nawa → bouton **« Démarrer la réunion »** (POST `/meetings/{event_id}/start` puis navigation) | Naviguer manuellement vers `/hypervisor/mission-room/agenda/meeting/evt-prefet-nawa` |
| 12:00 | **S2.7** Décide option B | `AYA, décide option B.` | Décision loggée · registre | meeting view → **clic point ODJ « Cacao »** → **clic carte « Option B »** → **bouton « Décider »** → modal → **« Logger la décision »** (POST `/meetings/{event_id}/decisions`) | `valide l'option B` |
| 13:00 | **S2.8** Décisions passées | `AYA, qu'avons-nous décidé la dernière fois ?` | Panneau décisions · top entrée Nawa | sidebar **Arbitrages** → bloc **« Arbitrages loggés en mode meeting »** (liste décisions, source `/meetings`) ou meeting view → décisions inline | — |

> **Légende statut** : « AYA only » = pas de chemin clic équivalent en démo ; tout le reste est désormais accessible 100 % au clavier/souris (multi-clic OK).

---

## Tableau avant / après — interactions cockpit

| Élément UI | Avant (prod ce matin) | Après (fix local) |
|------------|----------------------|-------------------|
| Hero presse Napié | Navigation `/presse` sans drawer | Clic → **drawer article** immédiat |
| Chip Zone Nord | Drill-down générique carte | Clic → `/strategie?zone=zone-nord&layers=threat,press,maritime-traffic` |
| Clic MV Atlantic Trader (carte preview) | Bloqué par wrapper bouton carte | Clic → vignette webcam + navigation maritime live |
| **Ouvrir le dossier Zone Nord** | Allait vers Décisions/brief | Clic → carte Nord + prompt AYA explain_why |
| Sujet arbitrer Presse / Nord | Navigation seule | Presse → drawer article · Nord → dossier Zone Nord |
| FLUX TERRAIN sidebar | 17 webcams Abidjan.net seulement | **APM Apapa Gate #1** en tête + badge demo |
| Légende carte cockpit | Pas d'entrée port | Bouton **Port Vridi · webcam demo** |

---

## Routes à vérifier avant la démo

| Route | Attendu |
|-------|---------|
| `/hypervisor/mission-room/cockpit` | Cockpit 5 blocs · chips cliquables |
| `/hypervisor/mission-room/strategie` | Carte full · FLUX TERRAIN · AIS |
| `/hypervisor/mission-room/presse` | Liste articles · drawer |
| `/hypervisor/mission-room/agenda` | Timeline 25 mai · Nawa 11h |

---

## Audit voix vs clic — état au 25 mai 2026

Récap couverture clic pour chaque action AYA mappée dans le walkthrough :

| ID | Action AYA | Effet produit | Clic équivalent (résumé) | État |
|----|------------|---------------|--------------------------|------|
| S1.1 | `aya.priority_summary` | Lecture cockpit + 3 priorités | Cockpit auto-charge | OK (la vue est le brief) |
| S1.2 | `aya.explain_why` (Nord) | Drill causal + carte Nord | Chip **Zone Nord · Tendue** | OK |
| S1.3 | `aya.focus_zone_with_project` | Carte Nord + Napié | Bouton **Brief opérationnel · Projet sensible Nord** | OK |
| S1.4 | `aya.show_vessel_evidence` | Webcam APM Apapa + propose PV | Pin MV Atlantic Trader / **Port Vridi · webcam demo** | OK |
| S1.5 | `aya.show_customs_record` | Drawer PDF PV page 2 | Chip PV douanes (panel maritime) | OK |
| S1.6 | `aya.draft_customs_email` | Drawer email customs | Bouton « Préparer email dérogation » (drawer PV) | OK |
| T.1  | `aya.open_next_meeting` | Agenda Nawa highlight | Sidebar Agenda → carte Nawa | OK |
| S2.1 | `aya.summarize_last_exchanges` | Synthèse Nawa | Bouton **« Synthèse AYA »** sur agenda | OK |
| S2.2 | `aya.recommend_cacao` | 3 options chiffrées | — | **AYA only** |
| S2.3 | `aya.draft_strategic_report` | Drawer PDF stratégique | — | **AYA only** |
| S2.4 | `aya.update_meeting_agenda` | Pending agenda patch | Form **« Proposer un point ODJ »** (meeting view) ou **`+ Point`** ODJ direct | OK (fix 25/05) |
| S2.5 | `aya.confirm_agenda_patch` | Patch appliqué | Bannière orange **« Valider modification »** (agenda detail + meeting view) | OK (fix 25/05) |
| S2.6 | `aya.start_meeting` | Set current_meeting + navigate | Bouton **« Démarrer la réunion »** (POST `/meetings/{id}/start`) | OK (fix 25/05) |
| S2.7 | `aya.log_decision` | Décision persistée | Click ODJ → option → **« Décider »** → modal | OK |
| S2.8 | `aya.recall_past_decisions` | Liste décisions passées | Sidebar Arbitrages → bloc « Arbitrages loggés en mode meeting » | OK |

Endpoints REST « clic » exposés en complément du flow voix :

- `POST /api/v1/meetings/{event_id}/start` — clic « Démarrer la réunion » (set `current_meeting`)
- `POST /api/v1/meetings/{event_id}/agenda-patch` — clic « Proposer modification » (stage pending)
- `POST /api/v1/meetings/{event_id}/agenda-patch/confirm` — clic « Valider modification » (apply pending)
- `GET  /api/v1/meetings/{event_id}/agenda-patch` — état pending (utilisé par la bannière)
- `POST /api/v1/meetings/{event_id}/decisions` — clic « Logger la décision » (existant)

Cockpit → arbitrages : les 3 cartes droite ne plongent plus directement dans un dossier. Un clic sur une carte ouvre désormais `/decisions?highlight=<card-id>` (vue liste + détail), depuis laquelle l'utilisateur peut explicitement cliquer **« Voir l'article » / « Ouvrir le dossier Zone Nord » / « Arbitrer les options »**.

---

## Scénario 3 — Posture sécuritaire dual-axis (S3.1 → S3.6)

S3 s'enchaîne après S2.7 (Décision Option B) et prépare le Conseil Défense restreint de 15h00.

| ID | Phrase | Réponse attendue | Effet UI |
|----|--------|------------------|----------|
| S3.1 | `AYA, montre-moi la posture sécuritaire du jour.` | Posture en vigilance intérieure et élevée sur l'axe Sahel ; rumeur Nord démentie ; lecture Conseil 15h00 prête. | Cockpit : bloc « Posture sécuritaire » mis en avant (Intérieur vigilance / Extérieur Sahel élevée + pastille 15h00 Conseil Défense restreint). |
| S3.2 | `AYA, montre la pulsation sociale à Abidjan.` | 18 signaux publics sur la séquence du jour : canaux vérifiés, citoyens pseudonymisés et rumeurs suivies. | Veille sociale : feed 18 tweets, filtres, tri engagement et export CSV advisory. |
| S3.3 | `AYA, d'où vient la rumeur frontière Nord ?` | Tweet 11h42 → Telegram 12h08 → blog 12h48 → démenti FANCI 13h46 → Préfecture Nord 13h52. | Zoom Nord, couche frontière, timeline rumeur et proposition « Rédiger un communiqué ». |
| S3.4 | `AYA, montre les mouvements de troupes au Sahel.` | Snapshot ADS-B advisory : 10 traces publiques, aucune confirmation opérationnelle ni donnée classifiée. | Security Monitor : traces ADS-B advisory, zones de surveillance et bases CEDEAO. |
| S3.5 | `AYA, montre le drill de réputation 2 positifs 1 critique.` | Score 72/100 ; deux lectures favorables, une critique budget défense à surveiller. | Réputation : score 72/100, 3 cartes (Jeune Afrique + Fraternité Matin + L'Inter). |
| S3.6 | `AYA, prépare un communiqué de sécurité sur la rumeur Nord.` | Brouillon cabinet citant FANCI, Préfecture Nord et coordination CEDEAO ; validation humaine obligatoire. | Drawer brouillon communiqué, validation advisory requise. |

Routes : `/hypervisor/mission-room/cockpit` (S3.1, retour S3.6), `/hypervisor/mission-room/securite/monitor` (S3.4), `/hypervisor/mission-room/reputation` (S3.5), `/hypervisor/mission-room/veille-sociale` (S3.2).

Plan B clic : voir `docs/sentinel-ci-demo-trame-s3-presenter-card-2026-05-25.docx`.

Garde-fous démo-safe :

- ADS-B = snapshot advisory only, callsigns + types validés à la main.
- Comptes citoyens : pseudonymes `@citoyen_***` ; rumeur : `@rumeur_***`. Les 5 comptes officiels sont des comptes institutionnels publics (Présidence CI, FANCI, RFI Sahel, Jeune Afrique, Préfecture Nord).
- Critique réputation = article L'Inter déjà publié et seedé en S1 (`attention-inter-budget`).
- Brief Sahel = synthèse OSINT publique style ACLED, aucune claim renseignement militaire.

---

## Références

- Cheat-sheet phrases canoniques : [`sentinel-ci-presenter-cheatsheet.md`](./sentinel-ci-presenter-cheatsheet.md)
- Trame narrative : [`demo-aya-storytelling-trame.md`](./demo-aya-storytelling-trame.md)
- QA post-deploy S1 : [`sentinel-ci-qa-postdeploy-s1-2026-05-24.md`](./sentinel-ci-qa-postdeploy-s1-2026-05-24.md)
