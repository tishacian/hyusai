# Handoff — Capture multimodale « Le Fil » : pointage déictique & parcours

> Paquet de transfert pour implémentation dans le codebase **Angular + Tailwind** (cockpit Agentium).
> Décision validée : le pointage déictique utilise le mode **« fantôme auto-confirmé » (hybride)**.

---

## 1. Overview

Refonte UX/UI de l'écran de **captation de connaissance multimodale** (écrit + parlé + pièces jointes)
pour experts. Principe directeur : **charge cognitive minimale pendant la capture**, gros œuvre
(indexation) repoussé à la fin et non bloquant.

Parti pris central — **« Le Fil »** : la capture n'est pas une saisie mais une **timeline d'événements
horodatés**. Voix, écrit, pièce montrée et référence déictique sont quatre types d'événements sur un
seul fil. Cela remplace l'« omni-composer + focus tray » de la v0.

---

## 2. À propos des fichiers de design

Les fichiers de ce paquet sont des **références de design réalisées en HTML/React** — des prototypes
qui montrent l'apparence et le comportement *visés*, **pas du code de production à copier tel quel**.
La tâche est de **recréer ces écrans dans l'environnement existant du codebase** (Angular + Tailwind),
avec ses patterns, composants et tokens déjà en place. Le prototype est en React uniquement parce que
c'était le médium de maquettage ; **la cible reste Angular**.

Les tokens utilisés (`--ck-*`) **existent déjà** dans le design system Agentium (`cockpit-tokens.css`,
`cockpit-utilities.css`). Réutiliser ces tokens, ne pas réinventer de valeurs.

---

## 3. Fidélité

**Haute fidélité (hifi).** Couleurs, typographie, espacements, états et micro-interactions sont
définitifs. Recréer l'UI au pixel près en s'appuyant sur les tokens et utilitaires `--ck-*` existants.
La seule donnée « maquette » est le contenu de la séance simulée (étude géotechnique) — c'est un jeu de
démonstration, à remplacer par les vraies données runtime.

---

## 4. La décision validée — Pointage déictique « fantôme auto-confirmé » (hybride)

C'est le cœur du transfert. Quand l'expert prononce une phrase déictique (« cette page / cette image /
comme on le voit ici… ») **alors qu'une vue est « en scène »**, le système crée une **ancre** liée à
l'instant du transcript. Comportement retenu :

### Cycle de vie de l'ancre (statuts)
1. **`pending` (fantôme)** — créée dès la détection. Rendu : pastille à **bordure pointillée**,
   couleur `--ck-fg-3` (neutre), **animation de respiration** (`opacity 1 → .55`, 2 s, ease-in-out),
   accompagnée d'un bandeau d'action : `confirmation auto dans {N}s` + boutons **Confirmer** /
   **Relier…** / **✕**.
2. **Auto-confirmation** — après **4200 ms** sans action, l'ancre passe en `confirmed`.
3. **`confirmed`** — pastille pleine, fond `color-mix(--ck-signal-* 12%)`, bordure couleur de la pièce,
   icône `check`. C'est l'état final « validé ».
4. **`discarded`** — si l'expert clique ✕ : texte barré, `--ck-fg-5`, mention « pointage annulé »
   (réversible : reste dans le Fil, non supprimé).
5. **`lowconf` (incertain)** — si **confiance < 0.7** (ex. 2 vues à l'écran → déictique ambigu) :
   bordure pointillée **ambre** (`--ck-signal-warn`), mention `⚠ association incertaine · « {phrase} »`
   + boutons **Corriger** / **OK**. Jamais de fausse certitude.

### Correction in-situ (« Relier… »)
Toute ancre reste cliquable. **Relier…** déplie la liste des pièces actuellement en scène ; sélectionner
une pièce **re-lie** l'ancre (statut → `confirmed`, confiance → 1) sans casser le Fil ni recharger.

### Règle d'or
**Aucune modale bloquante.** Tout feedback est inline, réversible et non bloquant. Pas de toast éphémère
(la v0 utilisait un toast — abandonné car non navigable et spammable).

### Alternatives étudiées (NON retenues, à garder en option réglable)
- **Auto** : l'ancre se confirme instantanément, zéro action. Risque : faux positif silencieux.
- **Manuel** : l'expert doit poser un geste explicite (tap sur la pièce / raccourci) pour pointer.
  Fiable à 100 %, mais demande une micro-action à chaque fois.
- **Hybride (retenu)** : effort nul *sauf* si correction. Concilie les deux.

Garder les trois comme valeur de configuration (`pointingMode: 'auto' | 'manuel' | 'hybride'`),
**défaut = `hybride`**.

---

## 5. Écrans / Vues

### 5.1 Capture en direct  — *température « Studio » (chrome minimal)*
**But :** capter parole + écrit, montrer/pointer des pièces, sans piloter d'UI.
**Layout :** colonne pleine hauteur.
- **Barre de statut** (h ≈ 50px) : pastille live + libellé `CAPTURE`, titre de séance, horloge mono
  (`HH:MM:SS`, tabular-nums), phase courante ; à droite : badge `pointage · {mode}`, compteur `{n} réf.`,
  play/pause, rejouer, **« Terminer la capture »** (bouton primaire).
- **Grille 3 colonnes** : `58px | 1fr | 340px` (la 3ᵉ passe à `300px` si oracle off).
  1. **Spine temporelle** (58px) : icône micro + **VU-mètre animé** (5 barres, `mic-bar` 0.9 s), filet
     vertical à ticks, label vertical « LE FIL ».
  2. **Le Fil** (centre) : flux d'événements horodatés, **auto-scroll** vers le bas. Composer ancré en bas.
  3. **La Scène** (haut, ~56%) + **Oracle** (bas, ~44%).
- **Le Fil — types d'entrées :**
  - *Parole* : horloge (56px, mono, `--ck-fg-5`) + texte. **Provisoire** = `--ck-fg-3`, *italique*, curseur
    clignotant (`cur-blink` 1 s) ; **finalisé** = `--ck-fg-1`, normal. Taille selon densité :
    compact 15 / regular 17 / comfy 19 px ; `line-height: 1.62` ; `text-wrap: pretty`.
  - *Note écrite* : carte en retrait, `border-left 2px` (`--ck-signal-cool` si saisie utilisateur,
    `--ck-signal-violet` si système), icône `pen`, fond `--ck-tint-faint`.
  - *Ancre* : voir §4.
- **Composer** (modalité unique) : conteneur arrondi `--ck-radius-lg`, fond `--ck-bg-inset`. À gauche :
  icône micro + VU-mètre (voix captée en continu). Textarea auto-grow (placeholder « Écrire une note —
  s'insère dans le Fil · la voix est captée en continu »). Bouton **Insérer**.
  Raccourcis : **↵ = insérer**, **⇧↵ = nouvelle ligne**.
- **La Scène :** titre `LA SCÈNE · {n} pièce(s)`. Vue active **agrandie** avec badge **« EN SCÈNE »**
  (pastille + glow couleur pièce). En dessous : **pellicule** horizontale des autres pièces (vignettes
  84px, vue active mise en avant, autres `opacity .5`).
- **Oracle (« Pistes de l'oracle ») :** liste calme, **jamais modale**, libellé « non bloquant ». Chaque
  carte : tag mono + horodatage, question, boutons **Garder** (épingle, vire au violet) / **Ignorer**.

### 5.2 Pièces & pointage
**But :** expliquer le modèle multi-pièces + comparer les 3 approches de pointage.
- Démo « La Scène » : grande vue active + **pellicule verticale** (liste de lignes cliquables, badge
  « EN SCÈNE » sur l'active).
- 3 cartes côte à côte **Auto / Manuel / Hybride** (cf. §4), la carte hybride portant le badge
  **« RECO PAR DÉFAUT »** (`--ck-signal-pos`), avec mini-transcript illustrant le rendu de chaque mode.

### 5.3 Fin de séance — Triage  — *température « Cockpit »*
**But :** confirmer ce qui est partagé, **sans formulaire**.
- Le niveau de partage est **pré-déduit de l'usage** : pointé ≥ 1× → **Entier** ; épinglé mais jamais
  pointé → **Aucun** ; cliché isolé → **Extrait**.
- Liste de documents : vignette, nom (mono), raison déduite (ex. « Pointé 3× (coupe, essais, tassement) »),
  **segmenté Entier / Extrait / Aucun** (pré-sélectionné, modifiable). Ligne `Aucun` → `opacity .62`.
- Encart : « L'indexation lourde démarre en arrière-plan dès l'ouverture du rapport ».
- CTA **« Ouvrir le rapport »** + compteur de documents partagés.

### 5.4 Indexation en arrière-plan
**But :** rassurer sans bloquer. Le rapport est déjà ouvert et lisible.
- **Pouls global** : filet de progression 3px (`--ck-signal-violet`, glow), `{pct}%`.
- Liste de sources avec **états** : `Non indexé → Référencé → En file → Indexation… → Indexé`, une seule
  indexation active à la fois (file). Pastille d'état (live pendant `indexing`), barre de progression par
  source, libellé d'état coloré.
- Légende des états en bas.

### 5.5 Rapport — lecture + sources cliquables  — *température « Cockpit »*
**But :** lire le rapport publié, vérifier chaque affirmation à sa source.
- 2 panneaux : `1fr | 396px`.
- **Document** (gauche) : en-tête (titre, réf, **pouls d'indexation** « indexation 2/3 · sources
  cliquables au fil »). Corps en colonne `max-width 660px`, fond `.ck-ambient-grid`. Chaque affirmation
  sourcée porte un **marqueur** (`◇ {n}`, pastille couleur de la pièce) ; au clic, l'affirmation se
  **surligne** et l'inspecteur s'ouvre. Affirmation de synthèse non sourcée → mention `(synthèse)`.
- **Inspecteur de provenance** (droite) : **vue pointée agrandie** avec **zone surlignée** (cadre couleur
  pièce + libellé « ZONE POINTÉE » + scrim autour) ; méta (nom doc, page/cliché, objet, état d'index) ;
  bouton **« Revoir l'instant capté · dit à {HH:MM:SS} dans Le Fil »** → provenance **bidirectionnelle**.

### 5.6 Cas limites & états
4 cartes annotées : **Erreur de pointage** (re-liaison), **Déictique ambigu** (incertain explicite),
**Perte réseau** (capture locale + file de synchro + bandeau ambre non bloquant), **Reprise de séance**
(carte « Séance interrompue à {h} · reprendre / clôturer », Fil persistant).

---

## 6. Interactions & comportements

- **Streaming de la parole** : provisoire (italique, dim, curseur) → finalisé (~420 ms après le dernier mot).
- **Détection déictique → ancre** : cf. §4. Compte à rebours 4200 ms ; respiration 2 s.
- **Auto-scroll** du Fil à chaque nouvel événement (`scrollTop = scrollHeight`, **jamais** `scrollIntoView`).
- **VU-mètre micro** : actif tant que la capture tourne et que le réseau est présent.
- **Oracle** : ajout au fil de l'eau, épinglage/rejet, jamais bloquant.
- **Triage** : segmenté par ligne, réversible.
- **Indexation** : progression séquentielle (file), pouls global + par source.
- **Rapport** : clic marqueur → surlignage + inspecteur ; lien retour vers l'instant du transcript.
- **Perte réseau** (toggle de démo) : bandeau ambre, capture continue en local, rien n'est perdu.
- **Réduction de mouvement** : `@media (prefers-reduced-motion: reduce)` coupe toutes les animations.
- **Accessibilité** : navigation clavier complète (↵ / ⇧↵ dans le composer, `role=radiogroup` sur les
  segmentés, `role=button` + Enter/Espace sur les lignes cliquables), contraste AA (tokens `--ck-fg-4/5`
  calibrés), annonces non intrusives recommandées pour les ancres (aria-live polite).

---

## 7. State management (modèle runtime)

État de la séance de capture (cf. `sim.jsx`, hook `useSession`) :
- `feed: Array<Entry>` — timeline. `Entry = speak | note | anchor`.
  - `speak`  : `{ id, t, text, final }`
  - `note`   : `{ id, t, text, byUser }`
  - `anchor` : `{ id, t, viewId, confidence, status, phrase, ambiguousWith?, confirmAt? }`
    avec `status ∈ {pending, confirmed, lowconf, discarded}`.
- `scene: View[]` — pièces épinglées ; `activeView: viewId | null` — pièce « en scène ».
- `oracle: Array<{ id, q, tag, state }>` avec `state ∈ {open, pinned, dismissed}`.
- `phase: string`, `clock: ms`, `playing: bool`, `awaitingGesture` (mode manuel).
- Constantes : `HYBRID_CONFIRM = 4200ms`, `FINALIZE_DELAY = 420ms`.
- Config : `{ pointingMode, oracleOn, density, speed, theme }` (défauts : `hybride`, true, `regular`, 1.2×, sombre).

Transitions clés : détection déictique → push `anchor`(pending) ; tick horloge ≥ `confirmAt` → `confirmed` ;
action utilisateur → `confirmed` / `discarded` / re-lié.

---

## 8. Design tokens (tous existants dans Agentium `--ck-*`)

- **Surfaces :** `--ck-bg-void #05070a`, `--ck-bg-base #07090c`, `--ck-bg-panel #0c1014`,
  `--ck-bg-panel-hi #11161c`, `--ck-bg-inset #0a0d11`.
- **Strokes :** `--ck-stroke-1/2/3`, `--ck-stroke-hot`.
- **Texte :** `--ck-fg-1 #f2f5f8` → `--ck-fg-5 #606874`.
- **Signaux :** pos `#34d399`, neg `#ef5a6f`, warn `#f5b84a`, cool `#7dd3fc`, violet `#a78bfa`, ice `#e0f2fe`.
- **Glows :** `--ck-glow-cool/pos/violet/warn/neg`. **Ombres :** `--ck-shadow-panel/popover/card`.
- **Radii :** sm 4 / md 6 / lg 10 / xl 14.
- **Type :** `--ck-font-sans` (Inter Tight / Inter), `--ck-font-mono` (JetBrains Mono).
- **Motion :** `--ck-ease-out`, `--ck-ease-in-out`, `--ck-dur-fast 120 / med 240 / slow 520`.
- **Utilitaires :** `.ck-scroll`, `.ck-live-dot(.cool|.violet|.warn|.neg)`, `.ck-ambient-grid`, `.ck-label`.
- **Système bi-température :** *Studio* (capture : typo large, chrome atténué) vs *Cockpit* (triage /
  indexation / rapport : dense, tabular-nums, grille ambiante). Mêmes tokens, densité/échelle différentes.

---

## 9. Assets

- **Aucune image réelle.** Les pages/slides/clichés sont des **placeholders rayés** (hachures CSS +
  libellé monospace), à remplacer par le vrai rendu de document côté codebase.
- **Icônes** : jeu géométrique inline (micro, stylo, cible/pointage, doc, image, étincelle/oracle, calques,
  œil, livre…). Remplaçables par le jeu d'icônes maison.
- **Polices** : Inter Tight + JetBrains Mono (déjà bundlées dans Agentium `fonts/`). Le prototype les
  charge via Google Fonts en fallback — en prod, utiliser les fontes locales du DS.

---

## 10. Fichiers de ce paquet

- `Le Fil - Contre-proposition.html` — prototype autoportant complet (Doc + 6 écrans), ouvrable hors-ligne.
- `src/` — sources React commentées (référence de comportement, **pas** à porter telles quelles) :
  - `data.jsx` — données de la séance simulée (documents, vues, script, triage, rapport).
  - `sim.jsx` — moteur de séance + machine d'états des ancres (la logique de référence du §4 et §7).
  - `ui.jsx` — primitives (icônes, placeholders, boutons, pastilles).
  - `capture.jsx` — écran Capture + AnchorChip (rendu des 4 statuts).
  - `flows.jsx` — Triage, Indexation, Pièces & pointage, Cas limites.
  - `report.jsx` — Rapport + inspecteur de provenance.
  - `doc.jsx` — la spec narrative (analyse, flux, raisonnement, comparatif).
  - `app.jsx` — coquille + Tweaks (config runtime).

> Pour le détail de la logique du pointage (timings, statuts, transitions), `sim.jsx` fait foi.

### Captures d'écran (`screens/`)
Rendus hifi de référence (1× chacun) :
- `01-doc-spec.png` — la spec narrative (mode Doc).
- `02-capture.png` — **Capture en direct au moment clé** : ancre **fantôme** « Coupe stratigraphique »
  avec *confirmation auto dans 2s* + Confirmer / Relier… / ✕, Scène à 2 pièces. C'est le comportement validé.
- `03-pieces-pointage.png` — La Scène multi-pièces + comparatif Auto / Manuel / Hybride.
- `04-fin-triage.png` — Triage pré-déduit (Entier / Extrait / Aucun).
- `05-indexation.png` — Moteur d'indexation en arrière-plan (états + pouls).
- `06-rapport-sources.png` — Rapport, sources cliquables + inspecteur de provenance (zone pointée).
- `07-cas-limites.png` — Cas limites (erreur de pointage, déictique ambigu, perte réseau, reprise).
