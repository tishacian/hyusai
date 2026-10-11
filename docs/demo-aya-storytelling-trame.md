# Trame storytelling — Démo SENTINEL-CI / AYA (S1 + S2)

**Durée totale** : ~12 minutes (5 min S1 + 2 min transition + 7 min S2)  
**Date simulée** : lundi 25 mai 2026, 10h30 (Abidjan)  
**Interlocuteur** : Vice Premier Ministre de la République
**Assistant** : AYA — cockpit souverain, mode **advisory-only**

> Toute action à effet de bord (email, écriture agenda, décision loggée) passe par une
> **proposition confirmable** puis une **validation Cabinet**. AYA ne décide pas à la place
> de l'exécutif.

---

## Introduction — « La matinée commence » (~1 min)

### Mise en scène

Le Vice Premier Ministre ouvre **SENTINEL-CI** le matin du 25 mai. AYA a déjà consolidé la nuit : signaux presse,
agenda du jour, tension territoriale, indicateurs macro et dossiers en attente d'arbitrage.

**Écran d'ouverture** : Cockpit Mission Room (`/hypervisor/mission-room/cockpit`).

**Ce que le public voit immédiatement :**

- La **barre de statut** : chip **Zone Nord · Tendue** en tête (pulse discret)
- Les **3 KPI macro** (chômage, inflation, PIB) avec sparklines ~12 ans — source Banque mondiale
- La **bannière AYA** : directive du matin (« Prioriser la tension Nord avant le Conseil de 15h »)
- La **carte + strip d'arbitrages** : lecture terrain en un coup d'œil
- **Une alerte presse hero** : signal open intelligence du jour

**Phrase d'ouverture suggérée (Vice Premier Ministre ou présentateur) :**

> « AYA, c'est lundi matin. Qu'est-ce qui demande mon attention en priorité ? »

AYA peut répondre par synthèse vocale ou chat ; le cockpit reste la **surface de vérité visuelle**.

### Scope fonctionnel couvert — Introduction

| Domaine | Capacité démontrée |
|---------|-------------------|
| **Cockpit exécutif** | Mission Room 5 blocs : status, macro, AYA, terrain, presse |
| **Indicateurs macro** | KPI temps-réel CI (Banque mondiale + fallback baseline) |
| **Open Intelligence** | Alerte presse hero sourcée |
| **Cartographie territoriale** | Zones tendu / surveillance / stable |
| **Voice / Chat** | Session loop AYA, partials sans side-effect |
| **Chrome SENTINEL-CI** | Design souverain Agentium, navigation 5 items |

---

## Partie 1 — Scénario Nord : « Comprendre pour agir » (~5 min)

### Arc narratif

La tension Nord n'est pas un incident isolé. AYA doit **démontrer la profondeur causale** :
de la carte à la preuve documentaire, jusqu'à une **action proposée** (email de dérogation douanière).

Le fil rouge est un **projet public réel** : le [Centre International de Formation aux Métiers des Drones à Napié](https://news.abidjan.net/articles/743173/cote-divoire-lancement-des-travaux-de-construction-du-centre-international-de-formation-aux-metiers-des-drones-a-napie) (région Poro, 100 M USD, Aerostar Dynamics × CEPICI, « Côte d'Ivoire Innovation 2030 »). En mai 2026, le chantier accuse ~120 jours de retard : les composants drones importés sont bloqués au port d'Abidjan.

### Trame pas-à-pas

| # | Moment | Prompt Vice Premier Ministre | Ce qu'AYA fait | Ce qu'on montre |
|---|--------|-----------|----------------|-----------------|
| 1 | **Accroche** | « Pourquoi la situation Nord est-elle tendue ? » | Drill causal niveau 1 | Navigation **Stratégie**, focus zone Nord + projet Napié |
| 2 | **Profondeur** | « Et pourquoi ce projet est en retard ? » | Drill causal niveau 2 | Evidence graph : lien projet → cargo |
| 3 | **Maritime** | « Pourquoi cette cargaison est-elle bloquée ? » | Drill + proposition | Focus **MV Atlantic Trader** (composants Aerostar Dynamics) ; proposition « Voir le PV douanes ? » |
| 4 | **Preuve** | « Oui » | Ouverture document | Drawer **document_preview** : PV douanes 18/05, page 2 surlignée (OCR) |
| 5 | **Action** | « Oui, prépare la dérogation » | Brouillon email | Drawer email `customs_derogation` : distingue cargo drones ≠ lot non conforme, cite Abidjan.net + PV |
| 6 | **Garde-fou** | *(présentateur)* | — | Bandeau **advisory-only** : « Proposition Cabinet — aucun envoi automatique » |

**Phrase de clôture S1 :**

> « En cinq minutes, AYA est passée du signal territorial à la preuve douanière, avec une
> proposition d'action sourcée — sans exécuter à ma place. »

### Chaîne causale (à montrer si on ouvre le graphe)

```
Zone Nord (tendue)
  ← retard Centre Drones Napié (120 j)
    ← cargo MV Atlantic Trader bloqué à Vridi
      ← PV douanes 18/05 (effet collatéral)
        → email dérogation proposé
```

### Scope fonctionnel couvert — Scénario 1

| Domaine | Capacité démontrée |
|---------|-------------------|
| **Evidence graph** | Relations `caused_by`, drill « pourquoi → pourquoi », trace API |
| **Intelligence territoriale** | Carte zones, focus projet, highlight causal |
| **Open Intelligence / projets** | Article Abidjan.net indexé (`sentinel-ci-projects`) |
| **Intelligence maritime** | Cargo seedé (IMO/MMSI), panel maritime, webcam port (fallback démo) |
| **Document Intelligence + OCR** | PV douanes PDF, collection `sentinel-ci-customs-records`, citation page |
| **Actions AYA** | `explain_why`, `show_customs_record`, `draft_customs_email` |
| **Assistant drawer** | Mode `document_preview` (iframe PDF + passages cités) + mode email |
| **Audit & SSE** | Événements `action.aya.*`, effets UI `action_effect` en streaming |
| **Knowledge Guides** | Interprétation Mission Room, pas substitution aux preuves brutes |

---

## Transition — « L'agenda reprend le fil » (~2 min)

### Mise en scène

Le Nord est qualifié ; l'exécutif bascule sur **la séquence du jour**. L'**agenda institutionnel**
sert de pivot narratif : même cockpit, autre temporalité — passage du **réactif** (crise Nord)
au **proactif** (préparation réunion territoriale).

**Écran** : navigation **Agenda** (`/hypervisor/mission-room/agenda`).

**Prompt de transition suggéré :**

> « AYA, quel est mon prochain rendez-vous ? »

AYA répond : **Rencontre Préfet de la région de Nawa**, 11h00 à Soubré — suite au rapport
préfectoral du 10 mai (cacao, infrastructures, diversification).

**Ce qu'on montre pendant la transition :**

- La **timeline** : événements du 25 mai (Conseil restreint 08h30, Préfet Nawa 11h, point presse 11h45…)
- Le **panneau détail** de l'événement Nawa : participants, contexte, lien vers le rapport
- Le **fil narratif** : « Le Nord était urgent ce matin ; l'Ouest demande une décision structurante
  avant midi. »

**Phrase de transition (présentateur) :**

> « SENTINEL-CI ne se limite pas à la gestion de crise. L'agenda relie chaque signal à une
> décision planifiée. Passons à la préparation de la rencontre Nawa. »

### Scope fonctionnel couvert — Transition

| Domaine | Capacité démontrée |
|---------|-------------------|
| **Agenda institutionnel** | Calendrier workspace, événements seedés, priorisation « prochain RDV » |
| **Navigation AYA** | `open_next_meeting`, effet navigate + highlight event |
| **Continuité cockpit → agenda** | Même workspace, même date démo, changement de vue fluide |
| **Contexte documentaire** | Lien event ↔ rapport préfet (`context_ref`) |

---

## Partie 2 — Scénario Nawa : « Préparer, arbitrer, mémoriser » (~7 min)

### Arc narratif

Le Vice Premier Ministre se prépare à rencontrer le Préfet de Nawa. Enjeu : **diversification cacao** et
transformation locale — un dossier de fond, pas une urgence presse. AYA doit **lire un corpus
dense**, **proposer des options sourcées**, **enrichir l'ODJ**, **tenir la réunion en live**
et **logger la décision** pour la retrouver plus tard.

### Trame pas-à-pas

| # | Moment | Prompt Vice Premier Ministre | Ce qu'AYA fait | Ce qu'on montre |
|---|--------|-----------|----------------|-----------------|
| 1 | **Synthèse** | « Résumé du rapport préfet » | RAG sur rapport ~70p | Synthèse structurée + proposition « Préconisations cacao ? » |
| 2 | **Options** | « Oui » | Recommandations sourcées | 3 options (transformation, coopérative, PPP) — guide anacarde, Banque mondiale, EUDR |
| 3 | **Livrable** | « Génère le rapport complet » | PDF stratégique | Drawer rapport + URL signée ObjectStore |
| 4 | **ODJ** | « Ajoute le point cacao à l'ordre du jour » | Patch agenda (confirm) | Drawer `calendar_agenda_patch` — validation requise |
| 5 | **Validation** | « Oui, valide » | Écriture agenda | ODJ mis à jour, badge « Ajouté par AYA », historique versionné |
| 6 | **Live** | « Démarre la réunion » | Mode meeting | Route `/agenda/meeting/evt-prefet-nawa` — chrono, ODJ vertical |
| 7 | **Arbitrage** | « Décide option B » | Log décision | Modal rationale → POST décision → registre |
| 8 | **Mémoire** | « Qu'avons-nous décidé la dernière fois ? » | Recall RAG | Panneau **Décisions**, audit persistant |

**Phrase de clôture S2 :**

> « De la lecture d'un rapport de 70 pages à la décision loggée en réunion — AYA a accompagné
> tout le cycle, avec traçabilité et validation à chaque étape d'écriture. »

### Scope fonctionnel couvert — Scénario 2

| Domaine | Capacité démontrée |
|---------|-------------------|
| **Document Intelligence** | Rapport Préfet Nawa (`sentinel-ci-ministerial-briefs`), synthèse RAG |
| **Knowledge Guides** | Guide diversification anacarde, recommandations groundées |
| **Génération documentaire** | PDF WeasyPrint ~70p, CLI `build_sentinel_reports`, endpoint `/reports/generate` |
| **Agenda éditable** | PATCH `metadata.agenda_items`, historique, badges source (AYA / Vice Premier Ministre / brief) |
| **Meeting live** | `vp-meeting` : ODJ, options A/B/C, chrono, modal décision |
| **Registre décisions** | Model `MeetingDecision`, API `/meetings/{id}/decisions`, decisions-log |
| **Mémoire institutionnelle** | `recall_past_decisions`, RAG sur décisions passées |
| **Actions AYA** | `summarize_last_exchanges`, `recommend_cacao`, `draft_strategic_report`, `update_meeting_agenda`, `start_meeting`, `log_decision` |
| **Confirmation policy** | Side-effects agenda = proposition → validation explicite |

---

## Conclusion — « Un cockpit, deux temporalités » (~1 min)

### Message de clôture

SENTINEL-CI / AYA illustre **deux postures complémentaires** de l'assistance exécutive :

1. **Réactive (S1)** — Comprendre vite, drill causal, preuve documentaire, action proposée
2. **Proactive (S2)** — Préparer une réunion, arbitrer sur options sourcées, mémoriser les décisions

Les deux scénarios partagent la même architecture : **sources citées**, **navigation cockpit**,
**drawer de validation**, **audit traçable**, **mode advisory-only**.

**Écran de clôture suggéré** : panneau **Décisions** ou retour **Cockpit** avec bannière AYA
actualisée (« Nord qualifié · Nawa arbitré · Prochaine échéance : Conseil 15h »).

**Phrase finale (présentateur) :**

> « AYA ne remplace pas l'exécutif. Elle accélère la lecture du réel, relie les signaux aux
> preuves, et prépare les arbitrages — toujours sous contrôle du Cabinet. »

### Scope fonctionnel couvert — Conclusion

| Domaine | Capacité démontrée |
|---------|-------------------|
| **Traçabilité** | Audit logs `action.aya.*`, `meeting.decision.logged`, `report.strategic.generated` |
| **Persistance** | Décisions et agenda survivent au redémarrage (workspace-scoped) |
| **Gouvernance** | Advisory-only, confirmation avant écriture, distinction preuve / guide |
| **Plateforme Agentium** | Action pack `sentinel_ci_aya_v1` isolé, héritage transverse sans pollution Andritz |

---

## Récapitulatif — Scope global de la démo

| Bloc | Durée | Message clé | Fonctionnalités Sentinel-CI |
|------|-------|-------------|----------------------------|
| **Introduction** | ~1 min | « Une matinée consolidée » | Cockpit, macro KPI, presse, carte, voice |
| **S1 — Nord** | ~5 min | « Comprendre pour agir » | Evidence graph, maritime, OCR/PV, email proposé |
| **Transition agenda** | ~2 min | « Du réactif au proactif » | Calendrier, prochain RDV, continuité narrative |
| **S2 — Nawa** | ~7 min | « Préparer, arbitrer, mémoriser » | RAG rapport, recommandations, ODJ, meeting live, décisions |
| **Conclusion** | ~1 min | « Advisory, sourcé, traçable » | Audit, persistance, gouvernance |

---

## Annexes

- Runbook opérationnel (pré-flight, plan B, tests) : [`demo-aya-runbook.md`](./demo-aya-runbook.md)
- Handoff plateforme Agentium : [`sentinel-ci-agentium-transverse-handoff-2026-05-23.md`](./sentinel-ci-agentium-transverse-handoff-2026-05-23.md)
- Source projet Napié : [Abidjan.net, 16 juillet 2025](https://news.abidjan.net/articles/743173/cote-divoire-lancement-des-travaux-de-construction-du-centre-international-de-formation-aux-metiers-des-drones-a-napie)
- Workspace démo : `sentinel-ci` · Date : `2026-05-25` · Login : `?workspace=sentinel-ci`
