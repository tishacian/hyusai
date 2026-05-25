# Trame présentateur — Carte minimale (25 mai 2026)

> **À lire mot pour mot.** Chaque phrase est vérifiée déterministe contre le pack
> `sentinel_ci_aya_v1` (HEAD `6335d460`, cf. QA `deck-phrases-resolve.json` du 25/05 12:36 — 12 PASS / 2 PARTIAL / 0 FAIL).
>
> Si AYA ne réagit pas en **2 secondes**, taper la phrase **mot pour mot** dans le **Quick Panel** (Cmd/Ctrl+K) — même résolveur, même intent.
> Ne **jamais** ouvrir une phrase par un filler poli isolé (« OK… », « D'accord… ») — risque de matcher `voice.confirm_yes`. Toujours enchaîner sur le verbe.

| # | Phrase à dire à AYA (verbatim) | Intent matché | Conf | Réponse AYA (vocal résumé + effet UI) | OK |
|---|---|---|---|---|---|
| **S1.1** | `AYA, c'est lundi matin. Qu'est-ce qui demande mon attention ?` | `aya.explain_why` | 0.875 | « Monsieur le Vice-Président, [chaîne causale Nord — Napié / Aerostar / Vridi / 120 j] ». Navigation **Stratégie** + focus zone-nord + highlight `proj-drone-centre-napie`. | ☐ |
| **S1.3** | `AYA, pourquoi la situation Nord est-elle tendue ?` | `aya.explain_why` | 1.06 | Drill causal niveau 1 (zone-Nord ← Napié). Navigation `/strategie?focus=zone-nord`, highlight projet drones. Si drill se prolonge sur le cargo, vignette webcam APM Apapa + proposition « Voir le PV douanes lié ? ». | ☐ |
| **S1.4** | `AYA, ouvre le PV douanes.` | `aya.show_customs_record` | 1.04 | « Page 2 du PV douanes du 18 mai : la non-conformité vise un autre cargo, MV Atlantic Trader bloqué par effet collatéral. ». Drawer **document_preview** PV PDF page 2 (OCR surligné) + proposition « Préparer email dérogation ? ». | ☐ |
| **S1.5** | `AYA, montre le cargo Atlantic Trader.` | `aya.show_vessel_evidence` | 0.905 | « MV Atlantic Trader (IMO 9876543) en attente de dédouanement à Vridi. Voir le PV douanes lié ? ». Navigation `/strategie?mode=live&panel=maritime&vessel=mv-atlantic-trader`, AIS pin highlight `cargo-abidjan-supply-001`, vignette webcam APM Apapa, proposition `propose-customs-pdf-show`. | ☐ |
| **S1.6** | `AYA, montre la situation au port.` | `aya.show_maritime_traffic` | 1.055 | « Trafic maritime à destination d'Abidjan : [résumé cargo Nord] ». Map Stratégie en mode live + panel maritime + webcam APM Apapa + cargo seedé. Proposition « Préparer un courrier de priorisation dédouanement ? ». | ☐ |
| **S1.7** | `AYA, rédige le courrier de dédouanement pour Atlantic Trader.` | `aya.draft_customs_email` | 0.94 | « Brouillon prêt : *[sujet email]*. Validation advisory requise. ». Drawer **email** `customs_derogation` (target `cargo-abidjan-supply-001`, recipient DGD Abidjan, refs projet + cargo + PV). | ☐ |
| **T.1** | `AYA, quel est mon prochain rendez-vous ?` | `aya.open_next_meeting` | 0.92 | « Prochain rendez-vous : **Rencontre Préfet Nawa** à 11:00 — Soubré. ». Navigation `/agenda` + highlight `evt-prefet-nawa`. | ☐ |
| **S2.1** | `AYA, donne-moi le résumé du rapport préfet.` | `aya.summarize_last_exchanges` | 0.92 | Synthèse markdown rapport Préfet Nawa (cacao / diversification / infrastructures, citations RAG). Inline chat. Proposition « Préconisations cacao ? ». | ☐ |
| **S2.2** | `AYA, donne-moi des préconisations sur le cacao.` | `aya.recommend_cacao` | 1.06 | « Préconisations cacao (chiffrage indicatif) : 1) transformation 4,2 Mds FCFA · 2) coopérative · 3) PPP » avec confiance %. Navigation `/decisions?focus=package-cacao-diversification`. Proposition rapport stratégique. | ☐ |
| **S2.3** | `AYA, génère le rapport complet.` | `aya.draft_strategic_report` | 1.04 | « Rapport de diversification cacao généré ([n] pages) — prêt pour validation advisory. ». Drawer **document_preview** rapport stratégique (~12 p.) + URL signée ObjectStore. | ☐ |
| **S2.4** | `AYA, ajoute le point cacao à l'ordre du jour.` | `aya.update_meeting_agenda` | 0.92 | « Je propose d'ajouter **point cacao** à l'ordre du jour de **Rencontre Préfet Nawa**. Validation advisory requise. ». Drawer **calendar_agenda_patch** + bannière orange « Modification ODJ proposée · AYA » (pending staged). | ☐ |
| **S2.5** | `Oui, valide.` | `voice.confirm_yes` → `aya.confirm_agenda_patch` (awaiting bucket) | 0.875 | « Ordre du jour mis à jour pour **Rencontre Préfet Nawa** : 1 point ajouté avec traçabilité advisory. ». PATCH calendar event appliqué, bannière retirée, badge « Ajouté par AYA », highlight agenda. | ☐ |
| **S2.6** | `AYA, démarre la réunion.` | `aya.start_meeting` | 1.025 | « Je démarre la réunion **Rencontre Préfet Nawa**. Mode meeting live — chaque arbitrage sera loggé. ». Navigation `/agenda/meeting/evt-prefet-nawa`, `current_meeting` set, ODJ vertical + chrono. | ☐ |
| **S2.7** | `AYA, décide option B.` | `aya.log_decision` | 0.89 | « Décision loggée : option B — Diversification anacarde, alignement Banque mondiale, EUDR. ». POST `/meetings/{id}/decisions`, navigation `/agenda/meeting/{id}?decision={id}`, registre arbitrages à jour. | ☐ |

## Avant de monter sur scène

- **URL prod** : `https://agentium.papai.ai/hypervisor/mission-room/cockpit?workspace=sentinel-ci`
- **Profil** : `vigie_executive` · **Compte** : `thibaud.ishacian@datategy.net`
- **Hard reload obligatoire** (Cmd+Shift+R / Ctrl+Shift+R) avant la démo pour vider tout `awaiting` / `current_meeting` résiduel.
- **Bouton « Parler à AYA »** : barre AYA en bas de cockpit ou icône micro dans le drawer assistant. Si la voix échoue → fallback **Quick Panel** (Cmd/Ctrl+K) avec la phrase verbatim de la colonne 2.
- **Tip prod requis** : `6335d460` (durcissement confirm + `aya.show_maritime_traffic` + Monsieur TTS).

## Plan B vocal (1 ligne)

Si AYA part en RAG long ou n'a pas de `action_effect` UI : **redire la phrase canonique** en insistant sur le mot pivot (`pourquoi nord`, `PV douanes`, `cargo Atlantic Trader`, `situation au port`, `dédouanement`, `prochain rendez-vous`, `résumé rapport`, `préconisations cacao`, `rapport complet`, `ordre du jour`, `valide`, `démarre la réunion`, `décide option B`).

## Références

- Pack résolveur : `backend/app/services/actions/registry.py` (lignes 274-1041, pack `sentinel_ci_aya_v1`).
- Cheat-sheet phrases : [`sentinel-ci-presenter-cheatsheet.md`](./sentinel-ci-presenter-cheatsheet.md)
- Trame narrative : [`demo-aya-storytelling-trame.md`](./demo-aya-storytelling-trame.md)
- Walkthrough pas-à-pas : [`sentinel-ci-demo-walkthrough-2026-05-25.md`](./sentinel-ci-demo-walkthrough-2026-05-25.md)
- QA résolveur (source des intents/conf) : `docs/status-screenshots/2026-05-25-qa-trame-v2/deck-phrases-resolve.json`
