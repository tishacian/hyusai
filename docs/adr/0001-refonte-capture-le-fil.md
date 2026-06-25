# ADR 0001 — Refonte de la capture multimodale « Le Fil »

- **Statut** : Accepté
- **Date** : 2026-06-25
- **Portée** : écran de captation de connaissance (`knowledge-capture`), pointage déictique, indexation, rapport
- **Contexte source** : analyse du handoff design `docs/design_handoff_pointage_le_fil/` et de la v0 « omni-composer + focus tray » déjà déployée
- **Plan associé** : `fluid_capture_text_and_pins_2fde9b03.plan.md`

---

## Contexte

La v0 de la capture (composer unifié + focus tray + indexation paresseuse + toast de
référence) est en production derrière la branche `demo/agentic`. Un handoff design
(« Le Fil ») propose une refonte où la capture devient une **timeline d'événements
horodatés** (parole / note / pièce montrée / ancre déictique), avec :

- **« La Scène »** : une seule vue « en scène » à la fois pour le pointage, les autres
  pièces épinglées en pellicule ;
- **Pointage « fantôme auto-confirmé » (hybride)** : à la détection d'une phrase déictique,
  une ancre `pending` apparaît, se confirme seule après 4200 ms, reste corrigeable inline
  (Confirmer / Relier… / ✕), sans modale ni toast éphémère.

Cette note fige les décisions prises pour cadrer l'implémentation. Elle complète (et
diverge sur un point, cf. D5) le handoff design, qui reste la référence visuelle hifi.

---

## Décisions

### D0 — Conserver la v0 derrière un flag pendant la bascule — **Acté**

On garde la v0 comme repli et base de comparaison A/B derrière un flag d'expérience
(`captureExperience`). La v0 reste en `brand-*` (legacy), vouée à la suppression une fois
« Le Fil » validé. La seule « couture » visuelle est v0 ↔ reste, transitoire et assumée
(elle n'apparaît qu'au basculement du flag).

### D1 — Réconciliation event / tour — **Acté : Option C (hybride formalisé), par étapes A → C**

Le handoff modélise la capture comme un flux d'**events** (`speak | note | anchor`), alors
que notre back persiste des **tours** (`append_turn`) avec faits, sources et questions oracle.

Options étudiées :
- **A — Tour = source de vérité** : les events ne sont qu'une projection d'affichage.
  Simple, mais perd la granularité fine (ancres intra-tour, notes interstitielles).
- **B — Event = source de vérité** : on réécrit la persistance autour d'un journal d'events.
  Le plus fidèle au handoff, mais réécriture lourde et risquée du back existant.
- **C — Hybride formalisé (retenu)** : le **tour reste l'unité de persistance/rapport**, et
  les events sont une **couche journalisée** (déjà amorcée avec `capture_view_referenced`)
  qui se **réconcilie** vers les tours. On formalise le mapping event→tour plutôt que de
  remplacer l'un par l'autre.

**Décision** : Option C, déployée **par étapes A → C** (on part de l'existant orienté tour,
on enrichit progressivement la couche event jusqu'au modèle hybride cible).

### D2 — Score de confiance & ancre `lowconf` — **Acté : version simple en Phase 1, kind-matching en V2**

Le handoff veut un état `lowconf` (confiance < 0.7) à bordure ambre quand l'association
déictique est ambiguë (ex. plusieurs vues à l'écran).

**Décision** :
- **Phase 1** : score de confiance **déterministe et simple** — p. ex. dérivé du nombre de
  vues en scène au moment de la mention (1 vue → confiance haute ; ≥ 2 → `lowconf`). Pas de
  modèle, pas de NLP avancé.
- **V2** : affiner avec un **kind-matching** (cohérence entre le type de déictique employé —
  « cette page », « cette image », « ce tableau » — et la nature de la vue active) pour
  désambiguïser plus finement.

### D3 — Édition du transcript & mix voix/texte — **Acté**

Le Fil doit rester **inaliénable** (append-only), or un mix d'entrées voix + texte risque de
faire que la transcription « écrase » le texte tapé.

**Décision** :
- **Option 1 (retenue, structurelle)** : **deux canaux append-only** distincts (parole et
  écrit) sur le même Fil ; aucun event n'en écrase un autre.
- **Option 2 (confort, configurable)** : possibilité de **couper le micro pendant la frappe**
  — **réglage configurable, défaut OFF** (le micro continue de capter par défaut).
- **Édition du transcript en séance : hors-scope Phase 1.**

### D4 — Périmètre design system — **Acté : DS-C maintenant (tout knowledge en cockpit)**

Clarification de cadrage : `Tailwind` est la *technique* (le look `brand-*`/`t-card` actuel
est déjà fait en Tailwind) ; `cockpit --ck-*` est le *design system* (tokens + composants
`shared/cockpit/*`). La vraie comparaison est **langage visuel cockpit `--ck-*`** vs
**langage `brand-*`/`t-card`**. Le cockpit est jugé nettement plus travaillé et intentionnel
(signaux sémantiques, glows, bi-température Studio/Cockpit, mono, grille ambiante, états
riches), et le handoff est **dessiné nativement en `--ck-*`**.

Options :
- **DS-A** : re-skinner « Le Fil » en `brand-*`. Écarté : re-mapper chaque `--ck-*` (certains,
  glows/ambient-grid, sans équivalent) = plus de travail, moins fidèle.
- **DS-B** : construire « Le Fil » nativement en cockpit, reste de knowledge en `brand-*`
  (couture temporaire).
- **DS-C (retenu)** : migrer **toute la section knowledge** en cockpit `--ck-*`.

**Décision** : **DS-C maintenant**. Comme « Le Fil » est une réécriture et que le handoff est
déjà en `--ck-*`, on construit la capture nativement en cockpit, puis on migre les écrans
voisins. Pas de couture permanente.

Périmètre de migration `brand-*`/`t-card` → cockpit `--ck-*` :

| Écran | Fichier | Action |
|---|---|---|
| Capture « Le Fil » | `features/knowledge/knowledge-capture.component.ts` | réécrit nativement en cockpit |
| Base de connaissances | `features/knowledge/knowledge-base.component.ts` | re-skin cockpit |
| Vue / détail | `features/knowledge/knowledge-view.component.ts` | re-skin cockpit |
| Embedding map | `features/knowledge/embedding-map.component.ts` | re-skin cockpit |
| Rapport / proposal | (rendu dans capture/view) | re-skin cockpit |

**Ordre recommandé** : (1) « Le Fil » en cockpit d'abord (écran le plus complexe, valide les
patterns) ; (2) ripple sur `knowledge-base`, `knowledge-view`, `embedding-map`, rapport.
La v0 reste en `brand-*` (non re-skinnée, legacy).

### D5 — Niveaux de partage au triage de fin — **Acté : `share_level {full, excerpt, none}`, défaut `excerpt`**

Constat technique vérifié dans le code : les sources du rapport se construisent à partir des
`document_refs` **journalisés** sur les faits/tours (`_document_sources_from_facts`,
`backend/app/services/knowledge_capture.py`) + l'**original stocké**, **pas** depuis la
collection indexée. Il faut distinguer **deux types de sources** dans le rapport :

- **Provenance d'une vue pointée (l'ancre)** → vient des events `capture_view_referenced` /
  `document_refs` + l'original stocké (preview surlignée). **Indépendant de l'indexation.**
- **Citations issues du retrieval (`retrieval_refs`)** → viennent de la collection indexée (RAG).

**Décision** : niveaux de partage à **3 états**, **défaut `excerpt`** :
- **`excerpt` (défaut)** — n'indexe **que les vues pointées/journalisées** (comportement déjà
  implémenté par le batch de fin). Un doc jamais pointé n'a aucune vue → `excerpt` n'indexe
  rien pour lui (= équivalent `none` de fait) jusqu'à passage manuel en `full`.
- **`full`** — ingère **tout le document** en plus (opt-in explicite).
- **`none`** — n'indexe rien, **mais conserve l'original stocké et les events journalisés**.

**Règle d'or à graver** : `none` ne supprime **jamais** l'original ni le ledger d'events. En
conséquence, **les anchors du rapport sont préservés même en `none`** ; seul le **retrieval
KB** (recherche future, grounding RAG) est retiré — ce qui est l'intention même de `none`.
L'UI confirme, pour un doc déjà pointé passé en `none` : « restera citable dans le rapport,
mais absent de la recherche KB ».

> Divergence assumée avec le handoff §5.3 : le handoff pré-déduit « pointé ≥ 1× → Entier ».
> On retient **défaut `excerpt`** (lazy : on n'indexe que ce qui a été montré, `full` opt-in).

---

## Impacts d'implémentation (synthèse)

**Backend** :
- `status` + `confidence` sur l'event `capture_view_referenced` (D1, D2).
- `share_level {full, excerpt, none}` (remplace le booléen `full_share`), défaut `excerpt` (D5).
- Segmentation event/tour formalisée, modèle hybride C (D1).
- Exclusion des vues `discarded` du batch d'indexation de fin (D1/D5).

**Frontend** :
- « Le Fil » + « La Scène » + ancres « fantôme auto-confirmé » en cockpit `--ck-*` (D4).
- Deux canaux append-only voix/texte ; mute-micro pendant frappe configurable, défaut OFF (D3).
- Flag `captureExperience` (v0 `brand-*` ↔ Le Fil cockpit) (D0).
- Score de confiance simple + état `lowconf` ; pas d'édition de transcript en séance (D2, D3).
- Re-skin cockpit des autres écrans knowledge (D4).

---

## Conséquences

- **Positif** : charge cognitive minimale en capture, provenance robuste et découplée de
  l'indexation, direction visuelle unifiée (cockpit), bascule réversible via flag.
- **Coût** : DS-C ajoute du travail front (re-skin de plusieurs écrans) ; couture v0 ↔ cockpit
  transitoire jusqu'à suppression de la v0.
- **À suivre** : V2 du kind-matching de confiance (D2) ; suppression de la v0 et du flag une
  fois « Le Fil » validé.

---

## Rollout (activation du flag)

L'expérience « Le Fil » est livrée **derrière le flag `capture_experience`, défaut `'v0'`** :
aucun utilisateur existant n'est impacté tant qu'on ne bascule rien. La route reste stable
(`/knowledge/capture`) ; le wrapper `CaptureRouterComponent` choisit la surface selon le flag.
Ordre de résolution (le plus prioritaire gagne), implémenté dans
`frontend-ng/src/app/core/capture-experience.service.ts` :

1. **Par session / test (override URL)** : `?exp=fil` (ou `?exp=v0`) sur l'URL — A/B ponctuel
   sans rien persister.
2. **Par utilisateur (test / pilote)** : `localStorage['agentium.capture_experience'] = 'fil'`
   (mirroir du pattern `VoiceCaptureMode`). Effacer la clé pour revenir au défaut.
3. **Par tenant (déploiement)** : `workspace.settings['capture_experience'] = 'fil'`
   (même mécanisme que `navigation_profile`) — bascule tout le workspace.
4. **Défaut** : `'v0'`.

**Procédure recommandée** : valider d'abord en `?exp=fil` / localStorage sur un compte pilote,
puis activer `workspace.settings.capture_experience='fil'` pour les tenants pilotes, enfin
généraliser. La bascule est **réversible** (repasser la valeur à `'v0'` ou retirer le réglage).

**Suppression de la v0 différée** : le monolithe v0 (`knowledge-capture.component.ts`, gelé en
`brand-*`) et le flag lui-même ne sont **supprimés qu'après validation** de « Le Fil » sur les
tenants pilotes (cf. D0). Aucune suppression n'est faite dans cette phase.

---

## Références

- Handoff design : `docs/design_handoff_pointage_le_fil/README.md` (et `src/sim.jsx` pour la
  logique d'ancre : `HYBRID_CONFIRM = 4200ms`, statuts `pending|confirmed|lowconf|discarded`).
- Plan d'implémentation : `fluid_capture_text_and_pins_2fde9b03.plan.md`.
- Code clé : `backend/app/services/knowledge_capture.py`
  (`_document_sources_from_facts`, `register_capture_documents`, `run_capture_finalize_index`).
