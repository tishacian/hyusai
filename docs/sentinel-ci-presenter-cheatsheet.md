% SENTINEL-CI — Cheat-sheet présentateur AYA
% Démo Vice-Président
% Lundi 25 mai 2026

## Cadre

- **Objectif** : rester en permanence dans le pack résolveur déterministe `sentinel_ci_aya_v1` afin que chaque prompt déclenche l'action attendue plutôt que de retomber en RAG générique, et préserver la cohérence narrative Napié (Centre Drones, cargo MV Atlantic Trader, PV douanes du 18 mai, Préfet Nawa, cacao).
- **URL** : `https://agentium.papai.ai/hypervisor/mission-room/cockpit`
- **Workspace** : `sentinel-ci` (header `X-Workspace-Slug: sentinel-ci`).
- **Profil assistant** : `vigie_executive`.
- **Seuil résolveur** : `min_confidence = 0.78` (cf. `resolve_action` dans `backend/app/services/actions/registry.py`).
- **Règles d'or** : (1) toujours préfixer la phrase par « AYA, … » (ou la finir par « , AYA ») pour activer le wake-word ; (2) préférer la forme officielle ci-dessous ; (3) si la première tentative tombe en RAG, reformuler avec un des mots-clés sentinelles indiqués dans la colonne « Mot pivot ».

## Wake-word

- « **AYA** » seul → réponse `aya.acknowledge_presence` : « Je suis là, M. le Vice Président, à votre écoute. » Utile pour ouvrir la séquence sans poser de question.
- « **AYA, …** » en tête, ou « …, AYA » en fin de phrase → le mot `aya` est retiré (`_strip_wake_word`) avant scoring : la query est traitée comme la phrase sans wake-word.
- Variantes acceptées par le pack acknowledge : `aya tu m'entends`, `aya tu es là`, `aya présente`, `aya écoute`, `ok aya`, `hey aya`.

## Séquence 1 — drill causal Nord (5 min)

| Étape | Prompt recommandé (à dire littéralement) | Action ciblée | Variantes acceptables | À éviter |
|---|---|---|---|---|
| Ouverture drill | « AYA, pourquoi la situation Nord est-elle tendue ? » | `aya.explain_why` | « pourquoi le Nord est tendu », « quelle est la situation au Nord », « pourquoi Nord tendu » (ultra-court) | « c'est quoi qui cloche dans le Nord » sans mot pivot (oral familier non couvert sans `nord`) ; « why is the north tense » côté EN (couvert mais peut être lu en anglais) |
| Drill projet | « Et pourquoi ce projet est-il en retard ? » | `aya.explain_why` (suite chaîne causale) | « pourquoi ce projet est en retard », « pourquoi le projet Centre Drones » | « il bloque pourquoi » (sans verbe « pourquoi » + sujet) |
| Drill cargaison | « Pourquoi cette cargaison est-elle bloquée ? » | `aya.explain_why` → `next_focus = customs-record` | « pourquoi cette cargaison est bloquée », « pourquoi MV Atlantic Trader bloqué » | « ça coince où » (RAG fallback) |
| Voir PV douanes | « AYA, ouvre le PV douanes. » | `aya.show_customs_record` | « montre le PV douanes », « voir le PV des douanes », « le PV du 18 mai sur Atlantic Trader » (tie-breaker actif) | « voir PV » seul si le contexte chat est vide (l'ultra-court est couvert mais préférer la forme verbale) ; « show me the customs report » côté EN (couvert mais préfère le FR pour la suite des citations) |
| Préparer dérogation | « Oui, prépare la dérogation. » (réponse à la proposition) puis si nécessaire « AYA, rédige le courrier de dédouanement pour Atlantic Trader. » | `aya.draft_customs_email` (le « oui » applique la proposition `aya.propose_customs_email`) | « rédige le mail dédouanement », « email dérogation », « courrier dédouanement Atlantic Trader » | « on prépare un email » sans `douanes` (couvert via `propose_customs_email` uniquement, pas `draft_*`) |

**Plan B vocal si fallback RAG sur le drill Nord** : reformuler avec « AYA, **pourquoi le Nord est-il tendu** ? » (forme la plus courte qui matche). Si la cargaison ne déclenche pas, repasser par « pourquoi cette cargaison est bloquée » (avec « est bloquée » en clair).

## Transition agenda

| Prompt recommandé | Action ciblée | Variantes acceptables | À éviter |
|---|---|---|---|
| « AYA, quel est mon prochain rendez-vous ? » | `aya.open_next_meeting` | « prochain rdv », « c'est quoi mon prochain rendez-vous », « mon prochain RDV avec le Préfet Nawa », « next meeting » | « quoi maintenant » seul (couvert mais ambigu en démo) ; « what's my next meeting » côté EN (couvert, mais préférer le FR pour rester sur le narratif Nawa) |

> Note : il n'existe pas d'action dédiée `aya.open_calendar` dans le pack v1 ; la vue agenda complète s'ouvre via la nav (item « Agenda »). Voir backlog post-démo 4.x pour l'ajout éventuel d'une intent `aya.open_calendar`.

## Séquence 2 — Préfet Nawa (7 min)

| Étape | Prompt recommandé | Action ciblée | Confirmation | Variantes acceptables | À éviter |
|---|---|---|---|---|---|
| Résumer rapport préfet | « AYA, donne-moi le résumé du rapport préfet. » | `aya.summarize_last_exchanges` | non (`direct_safe`) | « résume-moi le rapport du préfet », « rapport préfet Nawa », « résume Préfet Nawa », « résume Nawa » | « résume Préfet » trop court reste tangent ; « summarize the prefect's report » couvert mais bascule en EN |
| Préconisations cacao | « AYA, donne-moi des préconisations sur le cacao. » | `aya.recommend_cacao` | non (`direct_safe`) | « recommandations cacao », « options de diversification cacao », « préco cacao » | « t'as des idées pour diversifier le cacao » (forme orale, couvert via alias mais préférer la forme verbale) ; « cacao » seul (trop ambigu) |
| Générer rapport complet | « AYA, génère le rapport complet. » | `aya.draft_strategic_report` | non | « le rapport complet », « prépare le rapport complet », « génère le rapport stratégique » | « rapport » seul (RAG fallback) |
| Patch agenda Conseil | « AYA, ajoute le point cacao à l'ordre du jour. » | `aya.update_meeting_agenda` | **OUI** (`confirm`) | « ajoute à l'ordre du jour », « mets à jour l'ordre du jour », « propose cet arbitrage au Préfet » | omettre « ordre du jour » → tombe en RAG |
| Confirmation patch | « Oui, valide. » | `aya.confirm_agenda_patch` (`direct_safe`) | n/a (résolveur applique) | « valide la mise à jour de l'ordre du jour », « applique l'ordre du jour », « patch agenda » | un simple « ok » sans contexte de proposition (le système ne consomme la confirmation que si une proposition est en attente) |
| Démarrer la réunion | « AYA, démarre la réunion. » | `aya.start_meeting` | non | « démarre la réunion », « lance la réunion », « ouvre le meeting », « lance la réunion avec le Préfet » | « on commence » seul si aucun meeting en contexte ; « start meeting » côté EN (couvert) |
| Arbitrer décision | « AYA, décide option B. » | `aya.log_decision` | **OUI** (`confirm`) | « valide l'option B », « choisis l'option B », « j'arbitre option B », « décide option B » | « option B » seul (RAG fallback) |
| Recall décisions passées | « AYA, qu'avons-nous décidé la dernière fois ? » | `aya.recall_past_decisions` | non | « rappelle-moi nos décisions », « décisions passées », « qu'avons-nous décidé » | « on a décidé quoi » (forme orale non couverte) |

**Plan B vocal si fallback RAG sur S2** :

- Pour le résumé du rapport : reformuler avec **« résume-moi le rapport du préfet »** (forme verbale complète).
- Pour préconisations cacao : insister sur le mot **« diversification cacao »** ou **« recommandations cacao »**.
- Pour `update_meeting_agenda` : toujours inclure le segment **« à l'ordre du jour »**.
- Pour `log_decision` : préfixer par **« décide »** ou **« valide l'option »** explicitement (un nom d'option seul, comme « B », ne déclenche pas l'action).

## Tableau de bord récap (à garder sous les yeux)

| Étape démo | Action manifest | Prompt à dire | Confirmation oui/non |
|---|---|---|---|
| Wake-word | `aya.acknowledge_presence` | « AYA » | non |
| Briefing prio (option ouverture) | `aya.priority_summary` | « AYA, donne-moi le cockpit 60 secondes. » | non |
| Drill Nord | `aya.explain_why` | « AYA, pourquoi la situation Nord est-elle tendue ? » | non |
| Voir PV | `aya.show_customs_record` | « AYA, ouvre le PV douanes. » | non |
| Proposer dérogation | `aya.propose_customs_email` | « AYA, propose un mail dédouanement. » | non |
| Rédiger courrier | `aya.draft_customs_email` | « AYA, rédige le courrier de dédouanement pour Atlantic Trader. » | non |
| Prochain RDV | `aya.open_next_meeting` | « AYA, quel est mon prochain rendez-vous ? » | non |
| Résumé Nawa | `aya.summarize_last_exchanges` | « AYA, donne-moi le résumé du rapport préfet. » | non |
| Préco cacao | `aya.recommend_cacao` | « AYA, donne-moi des préconisations sur le cacao. » | non |
| Rapport complet | `aya.draft_strategic_report` | « AYA, génère le rapport complet. » | non |
| Patch agenda | `aya.update_meeting_agenda` | « AYA, ajoute le point cacao à l'ordre du jour. » | **OUI** |
| Confirmation patch | `aya.confirm_agenda_patch` | « Oui, valide. » | n/a |
| Démarrer réunion | `aya.start_meeting` | « AYA, démarre la réunion. » | non |
| Arbitrer décision | `aya.log_decision` | « AYA, décide option B. » | **OUI** |
| Recall décisions | `aya.recall_past_decisions` | « AYA, qu'avons-nous décidé la dernière fois ? » | non |

## À éviter en démo (formes encore fragiles)

D'après le rapport de robustesse résolveur du 24 mai 2026 (`docs/sentinel-ci-aya-resolver-robustness-2026-05-24.md`), les formes suivantes restent risquées même après le durcissement Vague 3 :

- **Anglicismes sans alias FR** : « give me my morning briefing » est couvert, mais d'autres anglicismes spontanés (« show me the cargo », « what's happening up north ») ne le sont pas. En cas d'anglicisme, viser un anglicisme déjà inscrit au pack (`morning briefing`, `next meeting`, `start meeting`, `customs report`, `draft a customs email`, `why is the north tense`, `cacao diversification recommendations`).
- **Ultra-courts ≤ 3 mots qui sortent du pack** : « voir cargo », « préco », « rapport », « décision » → fallback RAG. Préférer les formes verbales recommandées ci-dessus.
- **Formes orales familières non listées** : « on se la fait », « vas-y », « bon, allez ». Le pack couvre « on y va », « on commence », « c'est parti » seulement pour `aya.start_meeting`.
- **Nom propre seul** : « Préfet », « Napié » seul ne déclenche pas le drill. Toujours coller un verbe (« résume Préfet », « pourquoi Napié »).
- **MV Atlantic Trader sans verbe douanes** : « montre Atlantic Trader » → bascule sur `aya.show_vessel_evidence` (intentionnel). Pour rester sur le PV, dire explicitement « PV Atlantic Trader » ou « courrier dédouanement Atlantic Trader » (le tie-breaker FR vessel↔douanes route vers `show_customs_record` / `draft_customs_email`).

## Plan B vocal général (résolveur tombe en RAG)

1. Reformule en utilisant **le mot pivot** du tableau ci-dessus (par ex. : « ordre du jour », « PV douanes », « rapport préfet », « diversification cacao », « décide option »).
2. Si toujours en RAG : reprends la **forme officielle** (colonne « Prompt à dire »).
3. En dernier recours : actionne le bouton équivalent dans le cockpit (chip status bar, drawer ouvert) — toutes les actions du tableau récap sont aussi exposées en `ui` surface.

