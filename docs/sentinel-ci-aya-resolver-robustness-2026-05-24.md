# QA résolveur AYA — robustesse linguistique (2026-05-24)

Mission : sonder le résolveur d'actions du pack `sentinel_ci_aya_v1` sur
`https://agentium.papai.ai` (workspace `sentinel-ci`, profil
`vigie_executive`) avec 8 intentions × 6 variantes = 48 requêtes
chat-stream. Strictement read-only côté plateforme : toutes les
intentions probées sont `direct_safe` ou `confirm`-with-preview, aucun
`update_meeting_agenda` / `log_decision` / `confirm_agenda_patch` n'a
été émis. Score `confidence` non exposé sur SSE → colonne « Score »
N/A. Statut : `✓` = action attendue, `⚠` = autre action match, `✗` =
fallback RAG (aucune action).

## Synthèse exécutive

- **26/48 ✓ (54 %)**, 2/48 ⚠ (4 %), 20/48 ✗ (42 %). Aucune sentinelle
  négative (Konaté/Burkina) n'apparaît : pas de pollution
  cross-narrative observée.
- **Anglicismes en chute libre : 1/8** (seul `cacao` passe car le
  substring matche le pack FR). « morning briefing », « next meeting »,
  « start meeting », « customs report », « customs email », « why is
  the north tense » → tous fallback RAG, parfois en anglais (briefing
  anglais part sur Mali/Sambe, hors cockpit).
- **Ultra-courts (3-4 mots) : 3/8** seulement. « voir PV », « quoi
  maintenant », « résume Préfet », « préco cacao », « email
  dérogation », « start meeting » sont tous ratés.
- **Conflit déterministe `show_vessel_evidence` vs
  `show_customs_record` / `draft_customs_email`** : dès qu'on
  mentionne « Atlantic Trader » (même avec « PV » ou « courrier »
  dans la query), le résolveur capte d'abord la phrase navire et
  ignore l'intention douanes. 2/2 cas atterrissent sur le navire.
- **Forme orale familière (« c'est quoi qui cloche… », « on
  prépare… », « on commence… ») : 2/8** seulement. Les amorces
  conversationnelles sans verbe d'action déclaratif ne sont pas
  couvertes par les phrases actuelles.

## Tableau par intention

### Intention 1 — Briefing matinal (`aya.priority_summary`) — 4/6 ✓

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `donne-moi le cockpit 60 secondes` | `aya.priority_summary` | N/A | napi, atlantic trader | ✓ |
| orale · `c'est quoi mes priorités du jour` | `aya.priority_summary` | N/A | napi, atlantic trader | ✓ |
| stt_bruite · `quoi faire ce matin` | `aya.priority_summary` | N/A | napi, atlantic trader | ✓ |
| ultra_court · `priorités du jour` | `aya.priority_summary` | N/A | napi, atlantic trader | ✓ |
| nom_propre · `résume-moi ce qui touche Napié ce matin` | — | — | napi, napié | ✗ |
| anglicisme · `give me my morning briefing` | — | — | (réponse EN hors cockpit) | ✗ |

### Intention 2 — Drill causal Zone Nord (`aya.explain_why`) — 4/6 ✓

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `pourquoi la situation Nord est-elle tendue` | `aya.explain_why` | N/A | aerostar, napi, napié | ✓ |
| orale · `c'est quoi qui cloche dans le Nord` | — | — | (RAG fallback générique) | ✗ |
| stt_bruite · `pourquoi le nord est tendu` | `aya.explain_why` | N/A | aerostar, napi, napié | ✓ |
| ultra_court · `pourquoi Nord tendu` | `aya.explain_why` | N/A | aerostar, napi, napié | ✓ |
| nom_propre · `qu'est-ce qui se passe à Napié` | `aya.explain_why` | N/A | aerostar, atlantic trader, napi, napié, pv | ✓ |
| anglicisme · `why is the north situation tense` | — | — | (RAG fallback EN) | ✗ |

### Intention 3 — Voir le PV douanes (`aya.show_customs_record`) — 3/6 ✓ +1 ⚠

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `ouvre le PV douanes` | `aya.show_customs_record` | N/A | atlantic trader, pv | ✓ |
| orale · `c'est quoi le PV des douanes` | `aya.show_customs_record` | N/A | atlantic trader, pv | ✓ |
| stt_bruite · `montre le pv douanes` | `aya.show_customs_record` | N/A | atlantic trader, pv | ✓ |
| ultra_court · `voir PV` | — | — | pv (RAG fallback) | ✗ |
| nom_propre · `le PV du 18 mai sur Atlantic Trader` | `aya.show_vessel_evidence` | N/A | atlantic trader, pv | ⚠ |
| anglicisme · `show me the customs report` | — | — | (RAG fallback EN) | ✗ |

### Intention 4 — Préparer email dérogation (`aya.propose_customs_email` ou `aya.draft_customs_email`) — 2/6 ✓ +1 ⚠

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `propose un mail dédouanement` | `aya.propose_customs_email` | N/A | — | ✓ |
| orale · `on prépare un email aux douanes` | — | — | (RAG fallback) | ✗ |
| stt_bruite · `mail douanes` | `aya.propose_customs_email` | N/A | — | ✓ |
| ultra_court · `email dérogation` | — | — | (RAG fallback) | ✗ |
| nom_propre · `rédige un courrier de dédouanement pour Atlantic Trader` | `aya.show_vessel_evidence` | N/A | atlantic trader, pv | ⚠ |
| anglicisme · `draft a customs clearance email` | — | — | (RAG fallback EN) | ✗ |

### Intention 5 — Prochain rendez-vous (`aya.open_next_meeting`) — 4/6 ✓

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `quel est mon prochain rdv` | `aya.open_next_meeting` | N/A | nawa | ✓ |
| orale · `c'est quoi mon prochain rendez-vous` | `aya.open_next_meeting` | N/A | nawa | ✓ |
| stt_bruite · `prochain rdv` | `aya.open_next_meeting` | N/A | nawa | ✓ |
| ultra_court · `quoi maintenant` | — | — | (RAG fallback) | ✗ |
| nom_propre · `mon prochain RDV avec le Préfet Nawa` | `aya.open_next_meeting` | N/A | nawa | ✓ |
| anglicisme · `what's my next meeting` | — | — | (RAG fallback EN) | ✗ |

### Intention 6 — Résumé rapport préfet (`aya.summarize_last_exchanges`) — 3/6 ✓

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `résumé du rapport préfet` | `aya.summarize_last_exchanges` | N/A | nawa, cacao | ✓ |
| orale · `résume-moi le rapport du préfet` | `aya.summarize_last_exchanges` | N/A | nawa, cacao | ✓ |
| stt_bruite · `rapport prefet nawa` | `aya.summarize_last_exchanges` | N/A | nawa, cacao | ✓ |
| ultra_court · `résume Préfet` | — | — | préfet (RAG fallback) | ✗ |
| nom_propre · `résume Préfet Nawa` | — | — | nawa, préfet (RAG fallback) | ✗ |
| anglicisme · `summarize the prefect's report` | — | — | (RAG fallback EN) | ✗ |

### Intention 7 — Recommandations cacao (`aya.recommend_cacao`) — 3/6 ✓

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `donne-moi des préconisations sur le cacao` | `aya.recommend_cacao` | N/A | cacao | ✓ |
| orale · `t'as des idées pour diversifier le cacao` | — | — | cacao (RAG fallback) | ✗ |
| stt_bruite · `preco cacao` | — | — | (RAG fallback prix cacao) | ✗ |
| ultra_court · `préco cacao` | — | — | cacao (RAG fallback) | ✗ |
| nom_propre · `options de diversification cacao` | `aya.recommend_cacao` | N/A | cacao | ✓ |
| anglicisme · `cacao diversification recommendations` | `aya.recommend_cacao` | N/A | cacao | ✓ |

### Intention 8 — Démarrer la réunion (`aya.start_meeting`) — 3/6 ✓

| Variante | Action match | Score | Sentinelles | Statut |
|---|---|---|---|---|
| trame · `démarre la réunion` | `aya.start_meeting` | N/A | nawa | ✓ |
| orale · `on commence le meeting` | — | — | (RAG fallback) | ✗ |
| stt_bruite · `demarre la reunion` | `aya.start_meeting` | N/A | nawa | ✓ |
| ultra_court · `start meeting` | — | — | (RAG fallback EN) | ✗ |
| nom_propre · `lance la réunion avec le Préfet` | `aya.start_meeting` | N/A | nawa | ✓ |
| anglicisme · `start the meeting` | — | — | (RAG fallback EN) | ✗ |

## ✓ Statut 2026-05-24 18:00

Les **5 lacunes prioritaires** listées ci-dessous sont traitées en local sur
la branche `demo/agentic` (pas pushé) :

- ✓ **Anglicismes critiques** : `morning briefing`, `daily briefing`,
  `give me the briefing`, `next meeting`, `what's my next meeting`,
  `start meeting`, `start the meeting`, `kick off the meeting`,
  `show me the customs report`, `show the customs pv`,
  `customs clearance email`, `draft a customs email`, `why north`,
  `why is the north tense`, `why is the situation tense` ajoutés au pack.
- ✓ **Ultra-courts ≤ 4 mots** : `voir pv`, `voir le pv`, `pv douanes`,
  `quoi maintenant`, `et après`, `résume préfet`, `résume nawa`,
  `résume préfet nawa`, `résume rapport`, `preco cacao`, `préco cacao`,
  `diversifier cacao`, `diversifier le cacao`, `email dérogation`,
  `mail dérogation`, `on commence`, `c'est parti`, `on y va`, `go meeting`
  ajoutés au pack.
- ✓ **Tie-breaker `show_vessel_evidence` ↔ douanes** : (a) retrait du seul
  alias `atlantic trader` du pack vessel ; (b) ajout d'un tie-breaker dans
  `resolver.resolve_action` — si la requête contient un verbe douanes
  (`pv`, `procès-verbal`, `dédouanement`, `dérogation`, `courrier`,
  `email`, `mail`, `douanes`, `customs`) **et** que le top-score est
  `aya.show_vessel_evidence`, on bascule vers `aya.show_customs_record` /
  `aya.draft_customs_email` si match.
- ✓ **Forme orale familière** : `c'est quoi qui cloche au Nord`,
  `qu'est-ce qui cloche au nord`, `qu'est-ce qui ne va pas dans le nord`,
  `c'est quoi le souci au nord`, `on prépare un email aux douanes`,
  `on prépare un mail douanes`, `on commence le meeting`,
  `on commence la réunion`, `on y va` ajoutés.
- ✓ **Détours par nom propre seul** : `résume préfet`, `résume préfet nawa`,
  `résume nawa`, `résumé nawa`, `point matinal napié`,
  `qu'est-ce qui touche napié` ajoutés.
- ✓ **Reconnaissance du nom AYA** (point 1 de la mission) :
  - Nouveau manifest `aya.acknowledge_presence` (direct-safe) qui répond
    « Je suis là, M. le Vice Premier Ministre, à votre écoute. » et émet
    l'effet UI `assistant-acknowledge`.
  - `_strip_wake_word` dans `resolver` : « AYA, … », « …, AYA », « pourquoi
    AYA situation au nord » sont normalisés AVANT le scoring de manifest,
    et matchent les mêmes actions que la query sans wake-word.

Couverture par `test_actions_resolver.py::test_resolver_matches_demo_scenario_phrases` :
chaque phrase ajoutée a un cas paramétré qui passe en local
(`102 passed in 6.11s`).

## Top 5 lacunes prioritaires (phrases à ajouter)

1. **Anglicismes critiques manquants partout sauf cacao.** Ajouter au
   minimum un alias EN par action high-traffic :
   - `aya.priority_summary` : `morning briefing`, `daily briefing`,
     `give me the briefing`
   - `aya.open_next_meeting` : `next meeting`, `whats my next meeting`,
     `what's my next meeting`
   - `aya.start_meeting` : `start meeting`, `start the meeting`,
     `kick off the meeting`
   - `aya.show_customs_record` : `customs report`, `show the customs pv`
   - `aya.draft_customs_email` / `propose_customs_email` :
     `draft a customs email`, `customs clearance email`
   - `aya.explain_why` : `why north`, `why is the north tense`,
     `why is the situation tense`

2. **Ultra-courts (3-4 mots) inexistants pour 5 intentions sur 8.**
   Compléter les `phrases` :
   - `aya.show_customs_record` : `voir pv`, `voir le pv`, `pv douanes`
   - `aya.open_next_meeting` : `quoi maintenant`, `what's next`,
     `et après`
   - `aya.summarize_last_exchanges` : `résume préfet`,
     `résume rapport`, `résumé préfet nawa`, `résumé nawa`
   - `aya.recommend_cacao` : `préco cacao`, `preco cacao`,
     `diversifier cacao`, `diversifier le cacao`
   - `aya.start_meeting` : `start meeting`, `on commence`, `c'est parti`
   - `aya.draft_customs_email` : `email dérogation`, `email derogation`,
     `mail dérogation`

3. **Conflit `show_vessel_evidence` ↔ `show_customs_record` /
   `draft_customs_email`.** Les phrases actuelles `atlantic trader` /
   `mv atlantic trader` sur le navire absorbent les requêtes douanes
   qui mentionnent l'Atlantic Trader. Soit (a) retirer le seul nom
   propre `atlantic trader` du pack navire et garder uniquement les
   phrases verbe+navire (`montre le navire`, `voir le cargo`), soit
   (b) introduire une règle de priorité : si la query contient
   `pv` / `procès-verbal` / `dédouanement` / `courrier` / `email`,
   alors les actions `aya.show_customs_record` /
   `aya.draft_customs_email` doivent gagner sur `aya.show_vessel_evidence`.

4. **Forme orale familière (« c'est quoi qui cloche », « on prépare »,
   « on commence ») non couverte.** Ajouter des aliases
   conversationnels sans verbe d'action déclaratif :
   - `aya.explain_why` : `qu'est-ce qui cloche au nord`,
     `qu'est-ce qui ne va pas dans le nord`, `c'est quoi le souci au
     nord`
   - `aya.propose_customs_email` : `on prépare un email aux douanes`,
     `on prépare un mail douanes`, `il faut un courrier douanes`
   - `aya.start_meeting` : `on commence le meeting`,
     `on commence la réunion`, `on y va` (avec garde de contexte
     `current_meeting`)

5. **Détours par nom propre seul.** « résume-moi ce qui touche Napié »
   ne déclenche pas `aya.priority_summary` (manque l'ancrage
   « priorités » / « cockpit »), et « résume Préfet Nawa » /
   « résume Préfet » ratent `aya.summarize_last_exchanges` (le pack ne
   contient que `rapport prefet nawa`, pas la forme verbale courte).
   Ajouter :
   - `aya.priority_summary` : `qu'est-ce qui touche napié`,
     `point matinal napié`
   - `aya.summarize_last_exchanges` : `résume préfet`,
     `résume préfet nawa`, `résume le préfet`, `résume nawa`,
     `résumé nawa`

## Top 3 recommandations

1. **Ouvrir un layer anglicisme systématique** au pack
   `sentinel_ci_aya_v1` : un alias EN par action `direct_safe` à fort
   trafic (briefing, next meeting, start meeting, customs report,
   customs email, why north). Justification : 7/8 anglicismes
   tombent en RAG fallback aujourd'hui ; certains génèrent du contenu
   anglais hors-narratif (Mali/Timbuktu Institute) au lieu du cockpit
   Sentinel-CI, ce qui casse la promesse exec en mode bilingue.

2. **Compléter le pack avec une couche « ultra-court 3-4 mots » par
   action.** Chaque intention `direct_safe` doit avoir au moins une
   phrase ≤ 4 mots dans son pack. Aujourd'hui les phrases longues
   dominent (« donne-moi des préconisations sur le cacao »,
   « quel est mon prochain rdv ») ; les utilisateurs voice/STT
   abrégent systématiquement et tombent dans le no_match.

3. **Désambiguïser le cluster maritime/douanes par règle de priorité
   ou retrait du nom propre seul.** Le résolveur classe aujourd'hui
   par phrase la plus longue qui matche, et `atlantic trader` capte
   tout. Soit on retire l'alias bare-noun du pack navire, soit on
   ajoute un tie-breaker simple côté resolver : si la requête
   contient un verbe douanes (`pv`, `procès-verbal`, `dédouanement`,
   `courrier`, `email`, `mail`), `show_customs_record` /
   `draft_customs_email` priment sur `show_vessel_evidence`.
