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

| Minute | Où cliquer (UI) | Quoi dire à AYA | Ce qui doit se passer à l'écran | Plan B si rien |
|--------|-----------------|-----------------|----------------------------------|----------------|
| 0:00 | Ouvrir **Cockpit** (sidebar) | `AYA, c'est lundi matin. Qu'est-ce qui demande mon attention ?` | Chips posture, KPI macro, directive AYA orange, carte + arbitrages | Lire la directive affichée sans voix |
| 0:30 | Chip **Zone Nord · Tendue** (pulse rouge) | `AYA, pourquoi la situation Nord est-elle tendue ?` | Navigation **Carte** · focus Korhogo/Poro · highlight projet Napié | Clic **Ouvrir le dossier Zone Nord** (bannière AYA) |
| 1:30 | *(reste sur carte ou cockpit)* | `AYA, focus sur la zone Nord et le projet Napié.` | Recadrage carte + surbrillance projet drones | Clic chip Zone Nord à nouveau |
| 2:30 | Clic pin **MV Atlantic Trader** sur carte preview **ou** bouton **Port Vridi · webcam demo** | `AYA, montre le cargo Atlantic Trader.` | Vignette webcam APM Apapa · proposition « Voir le PV douanes ? » | FLUX TERRAIN → **APM Apapa Gate #1** en tête de liste |
| 3:30 | Accepter proposition ou dire directement | `AYA, ouvre le PV douanes.` | Drawer PDF PV 18/05 · page 2 · citations OCR | Variante : `pv douanes` |
| 4:30 | Drawer email (après PV) | `AYA, rédige le courrier de dédouanement pour Atlantic Trader.` | Drawer email `customs_derogation` · bandeau advisory-only | — |

**Phrase de clôture S1** : « En cinq minutes, AYA est passée du signal territorial à la preuve douanière, avec une proposition d'action sourcée — sans exécuter à ma place. »

---

## Transition — Agenda (1 min)

| Minute | Où cliquer (UI) | Quoi dire à AYA | Ce qui doit se passer à l'écran | Plan B si rien |
|--------|-----------------|-----------------|----------------------------------|----------------|
| 5:00 | Sidebar **Agenda** | `AYA, quel est mon prochain rendez-vous ?` | Highlight **Préfet Nawa** · 11h00 Soubré · lien rapport | Clic manuel événement `evt-prefet-nawa` |

---

## S2 — Nawa / cacao (7 min)

| Minute | Où cliquer (UI) | Quoi dire à AYA | Ce qui doit se passer à l'écran | Plan B si rien |
|--------|-----------------|-----------------|----------------------------------|----------------|
| 6:00 | Agenda · panneau Nawa | `AYA, résume le rapport Préfet Nawa.` | Synthèse structurée · proposition préconisations | `AYA, donne-moi le résumé du rapport préfet.` |
| 7:00 | Bulle AYA | `AYA, donne-moi des préconisations sur le cacao.` | 3 options chiffrées (transformation, coop, PPP) | `recommandations cacao` |
| 8:00 | — | `AYA, génère le rapport complet.` | Drawer PDF stratégique · téléchargement | `génère le rapport stratégique` |
| 9:00 | — | `AYA, ajoute le point cacao à l'ordre du jour.` | Drawer `calendar_agenda_patch` · attente confirmation | Dire **cacao** explicitement |
| 10:00 | Bouton valider drawer | `Oui, valide.` | ODJ patché · badge « Ajouté par AYA » | Redire S2.5 si rien staged |
| 11:00 | — | `AYA, démarre la réunion.` | Route `/agenda/meeting/evt-prefet-nawa` · chrono · ODJ | Sidebar Agenda → Démarrer |
| 12:00 | Modal décision | `AYA, décide option B.` | Décision loggée · registre | `valide l'option B` |
| 13:00 | Sidebar **Arbitrages** ou chat | `AYA, qu'avons-nous décidé la dernière fois ?` | Panneau décisions · top entrée Nawa | — |

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

## Références

- Cheat-sheet phrases canoniques : [`sentinel-ci-presenter-cheatsheet.md`](./sentinel-ci-presenter-cheatsheet.md)
- Trame narrative : [`demo-aya-storytelling-trame.md`](./demo-aya-storytelling-trame.md)
- QA post-deploy S1 : [`sentinel-ci-qa-postdeploy-s1-2026-05-24.md`](./sentinel-ci-qa-postdeploy-s1-2026-05-24.md)
