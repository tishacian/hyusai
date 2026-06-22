# Jeu de questions/réponses — Démo Chat base de connaissances ANDRITZ (build du 22/06/2026)

**Date de vérification :** 22/06/2026 — **VM :** `omnirag-demo` (conteneur `agentium-backend`)
**Image exécutée :** `agentium-backend:local` buildée `2026-06-22T10:42:51Z` (≈ commit `4b8171b`) — code **figé dans l'image** (seuls `object_store` / `secure_deposit` / `faiss_db` sont bind-montés).
**Workspace :** `andritz` (`0cce0bee-7e86-485d-95b1-672e82f16600`)
**Scope par défaut confirmé :** `andritz-spl-knowledge-experiment` = **« Contexte Andritz SPL »** → collections `andritz-notices-techniques-spl-pilot` (+ `andritz-manuals-bba120-pilot`, `andritz-non-wovens-france-excel-pilot`, et `andritz-expert-fiche` quand l'intent « document facts » l'élargit). `scope_confidence` 0,85–0,94.
**Profil :** `balanced` partout (jamais `deep`).

> ⚠️ **Différence majeure avec le jeu du 15/06 (`demo-andritz-qa-set-2026-06-15.md`).** Entre le 15/06 et aujourd'hui, la **stack answer-profiling** est passée en prod (~17-18 juin). Sur les 12 questions « valeurs sûres » du 15/06, **plusieurs ont régressé** sur le build courant (voir §3). Ce document remplace le 15/06 pour la démo du 22/06.

> **Réponses VÉRIFIÉES EN LIVE** via le vrai chemin du chat en conteneur (`_apply_workspace_chat_flow_defaults` → answer_profile/scope/budget → `orchestrator.process_request` → collecte `_collect_chat_chunk` → post-filtre `apply_answer_policy_to_text`), workspace andritz, profil balanced, **chaque requête jouée 2×**. Les réponses ci-dessous sont *réelles*, pas idéalisées.

---

## 1. Récapitulatif — uniquement les valeurs sûres du 22/06

| Ordre | Question (abrégé) | Capacité | Profil | Langue | Latence (run chaud) |
|---|---|---|---|---|---|
| 1 | AKK200 — largeur/vitesse (FR) | Spec lookup | precise_fact | FR | ~11 s |
| 2 | Qualiscan QMS-12 — function (EN) | Multilingue (EN) | precise_fact | EN | ~9 s |
| 3 | Nettoyage des cartouches d'injecteurs (FR) | Procédure | precise_fact | FR | ~17 s |
| 4 | Description carde ACJ200 (FR) | Scope projet / synthèse | precise_fact\* | FR | ~19 s |

**Ordre conseillé pour la démo :** **1 (ouverture FR) → 2 (multilingue EN) → 3 (procédure) → 4 (synthèse carde).**

\* Q4 route `precise_fact` via `default_answer_profile` (la regex `project_summary` ne matche pas « Décris … composants ») mais le modèle produit quand même une synthèse complète : rendu démo bon.

> ℹ️ Latences mesurées sur un run « chaud » partageant le CPU avec le serveur (cross-encoder souvent en budget `timeout` → repli sur fusion dense+sparse) ; le serveur live préchargé est comparable ou plus rapide. Ce repli de rerank n'affecte pas les verdicts (Q1 réussit avec `xenc=timeout`).

---

## 2. Questions retenues (détail, réponses réelles)

### ⭐ 1 — AKK200 largeur/vitesse (FR) — `precise_fact` — ~11 s
- **Question :** « Quelle est la largeur de travail et la vitesse de production du système AKK200 Nonwoven ? »
- **Réponse réelle (verbatim) :** « Largeur de travail : 0,3 m. Vitesse de production : 10 à 20 m/min. [2] »
- **Sources :** panneau de 6 sources AKK200 ; citation `[2]` = `AKK200 … section_II/II.2.html` (« Technische Spezifikation und Leistungsparameter »).
- **Pourquoi propre :** la plus courte et exacte du lot, valeur+unité, 1 citation, 0 repli, 0 jargon, identique aux 2 runs. **Idéale pour ouvrir.**
- ⚠️ **Ne fonctionne de façon fiable que dans cette formulation FR exacte** (les variantes DE et EN du même fait retombent en repli — voir §3 et §4).

### ⭐ 2 — Qualiscan QMS-12 (EN) — `precise_fact` — ~9 s
- **Question :** « What is the Qualiscan QMS-12 system used for and how does it work? »
- **Réponse réelle (excerpt) :** « The Qualiscan QMS-12 is a traversing, modular quality control system used to measure, log, and continuously control in-process parameters across the full web width… basis weight, coating weight, moisture, and thickness for paper, films, nonwovens, textiles, rubber, metal foils… multiple measuring sensors mounted on traversing frames (measuring bridges) with one or more computers; components are networked via standard Ethernet. [3] »
- **Sources :** notices `QMS-12_Qualiscan` (en_GB) — `[3]`, `[5]`.
- **Pourquoi propre :** anglais respecté, ancré, marqueurs numériques propres, 0 repli/jargon/hedge, stable. Bonne vitrine **multilingue (EN)**.

### ⭐ 3 — Nettoyage cartouches injecteurs (FR) — `precise_fact` — ~17 s
- **Question :** « Comment dois-je nettoyer les cartouches d'injecteurs ? »
- **Réponse réelle (excerpt) :** « Immerger la cartouche dans le bac de nettoyage pendant 24 heures… Terminer avec la buse rotative et le nettoyeur haute pression… Toujours nettoyer de l'intérieur vers l'extérieur ; ne jamais de l'extérieur vers l'intérieur… injecteur arrêté (P = 0 bar). Références : notice "INJECTOR" standard 160 et 250 b [3]… »
- **Sources :** `notice injecteur standard 160 et 250 b.PDF` (`[1]`–`[4]`).
- **Pourquoi propre :** procédure correcte (bac + solution, trempage 24 h, sens intérieur→extérieur, P = 0 bar), ancrée, stable.

### 4 — Description carde ACJ200 (FR) — `precise_fact` (default) — ~19 s
- **Question :** « Décris la carde ACJ200 et ses principaux composants. »
- **Réponse réelle (excerpt) :** « La carde ACJ200 (Carde 69200, réf. 133349662/133349666) est une carde KREMPEL composée de trois zones principales — entrée, zone du grand tambour/transferts, sortie… Entrée : bâti, demi-lunes, table d'alimentation, faux-fonds, rouleaux d'entrée… [6, p.33-66] ; Avant-train/transferts… [6, p.79-161] ; Grand Tambour… [3];[6, p.164-206] ; Sortie carde… »
- **Sources :** `TTN20770J/TTN21131J … Carde 133349662-666 ACJ200` + spare parts list (`[1,2,3,5,6]`).
- **Pourquoi propre :** synthèse structurée riche, ancrée, stable sur 2 runs, 0 repli/jargon/hedge.

---

## 3. 🚫 À ÉVITER en démo (régressions vs 15/06 — constaté le 22/06)

| Question | Pourquoi l'éviter aujourd'hui |
|---|---|
| **AKK200 en allemand** (« Wie groß sind die Arbeitsbreite… ») | Repli absence + **répond en français** (le contrat de langue ne supporte que fr/en). |
| **CU250S-2 — rôle/configuration** | **Garde-fou `retrieval-exact-match-guardrail`** : run1 hedge « analyse générale à valider » + fuite jargon `vectoriel` ; run2 absence. Régression nette, même sous scope SPL. |
| **Etachrom — pièces de rechange** | Plus de liste DIN 24296 ; absence + hedge « analyse générale à valider » (retrouve « Etachrom BC », pas « Etachrom B »). |
| **Graisse palier D.60 — quantité** | Rend « 50 g » générique « à défaut d'indication » au lieu du **40 g (1er) / 20 g (2-3)** spécifique D.60 attendu. |
| **QMS-12 en allemand** (« Wozu dient… ») | Contenu ancré correct **mais répond en français** (DE hors contrat). |
| **Toute question en allemand** | Réponse rendue en **français** (contrat `response_language` = fr/en uniquement). |
| **Profil `deep`** | Scan ledger ~65 s → 0 passage → repli. Rester en `balanced`. |

> ⚠️ **Mi-figue (fond bon, forme imparfaite) :** ACJ200 risques résiduels (contenu SERVO X correct mais **ouverture hédgée**) et QMS-12 FR (contenu bon mais **citations non-numériques parasites** `[Qualiscan, 6, en_GB]`). À ne pas présenter comme « parfaites ».

---

## 4. Constats systémiques (issus de la vérif live du 22/06)

1. **Langue.** Le contrat `response_language` ne supporte que `fr`/`en`. Toute requête **allemande** est détectée « ni FR ni EN » → défaut **français**. La vitrine multilingue FR/EN/DE du 15/06 n'est donc plus tenue côté DE.
2. **Non-déterminisme / sensibilité à la formulation.** Le fait largeur/vitesse AKK200 n'est ramené de façon fiable que par la **formulation FR exacte** (Q1) ; le DE et l'EN retombent sur des pages nav/cover ou notices moteur → repli absence.
3. **Garde-fou exact-match + hedge.** CU250S-2 et Etachrom déclenchent le garde-fou exact-match / le repli « analyse générale à valider » apparu avec la stack answer-profiling — alors qu'ils étaient ⭐ le 15/06.

> Ces trois régressions (CU250S-2, Etachrom, graisse D.60) font l'objet d'une investigation/correction dédiée.

---

## Note méthodologique

- **Candidats testés :** 11 requêtes (9 du jeu 15/06 + 2 wins `precise_fact` de l'ère profilée 18-19 juin), chacune **2 runs**. **4 retenues** (✅ PASS), 4 écartées (❌ FAIL), 3 partielles (⚠️ contenu bon / forme imparfaite ou langue).
- **Comment vérifié :** vrai chemin du chat en conteneur (`process_request` + génération + post-filtre `apply_answer_policy_to_text`), aucune écriture (pas de session/run persistés).
- **Critère de rétention :** bon profil, réponse ancrée citant des documents réels (marqueurs `[n]`), valeur+unité+condition correcte, langue respectée, 0 repli / 0 garde-fou / 0 jargon plateforme / 0 hedge, **stable sur les 2 runs**.
