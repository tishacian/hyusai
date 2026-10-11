# Catalogue de test A/B — Capture « Le Fil » vs v0

> But : qualifier **en asynchrone** la nouvelle expérience de capture de connaissances
> (**Le Fil**, `capture_experience='fil'`) face à l'expérience historique (**v0**), pour
> décider du **go / no-go** et détecter d'éventuelles régressions.
>
> Chaque scénario se joue **deux fois** (A = Le Fil, B = v0) quand un équivalent existe,
> puis on note le verdict de A et la **préférence A/B**.

| Champ | Valeur |
|---|---|
| Commit déployé | `e37fd363` (sur `2672d332`) |
| Environnement | `omnirag-demo` — tenant **Andritz** |
| Flag | `capture_experience` : `fil` activé sur Andritz (défaut code `v0`) |
| Route | `/knowledge/capture` |
| Date de qualif | _à remplir_ |
| Qualifieur | _à remplir_ |

---

## 1. Accès & bascule A/B

- **A (Le Fil)** : `/knowledge/capture?exp=fil`
- **B (v0)** : `/knowledge/capture?exp=v0`
- Sur Andritz, **sans paramètre** l'URL rend déjà **Le Fil** (flag tenant).
- Après changement de flag/tenant : **hard refresh** (Cmd/Ctrl+Shift+R) ou re-login pour recharger `workspace.settings`.
- Le `?exp=` est prioritaire sur le localStorage, lui-même prioritaire sur le réglage tenant — pratique pour alterner A/B dans deux onglets.
- Pour repartir « propre » : vider la clé `agentium.capture_experience` du localStorage.

> Astuce async : ouvrir **deux onglets** côte à côte (`?exp=fil` et `?exp=v0`) et rejouer le même scénario.

---

## 2. Protocole de qualification

1. Préparer le **jeu de données de test** (voir §3) — identique pour A et B.
2. Pour chaque cas : exécuter les **étapes** sur A, puis sur B (si équivalent existe).
3. Renseigner le **verdict A**, la **préférence A/B**, la **sévérité** d'un éventuel défaut, et un **commentaire**.
4. Capturer une **preuve** (screenshot / courte capture vidéo / id de session) en cas de réserve ou KO.
5. Reporter chaque ligne dans la **matrice de synthèse** (§16).

### Grille de notation

| Dimension | Échelle |
|---|---|
| **Verdict A (Le Fil)** | `OK` · `Réserve` · `KO` |
| **Préférence A/B** | `A>B` (Le Fil mieux) · `A≈B` · `A<B` (v0 mieux) · `N/A` (pas d'équivalent v0) |
| **Fluidité / UX** | `1` (frustrant) → `5` (excellent) |
| **Sévérité défaut** | `bloquant` · `majeur` · `mineur` · `cosmétique` · `—` |

### Critère de go/no-go (proposé)

- **Go** : 0 KO bloquant/majeur sur G1–G8, préférence globale `A≥B`, esthétique DS-C jugée `≥` v0.
- **No-go** : ≥1 KO bloquant, ou régression majeure sur capture vocale / rapport / provenance.

---

## 3. Pré-requis & jeu de données

- Compte **Andritz** avec accès Capture de connaissances ; navigateur récent (Chrome/Edge), **micro autorisé**, pièce calme.
- Documents de test (les mêmes pour A et B) :
  - 1 **PDF** multi-pages (≥ 5 pages).
  - 1 **PPTX / DOCX** (conversion Office → PDF côté serveur).
  - 1 **image** (PNG/JPG).
- Un **script de parole** court (~10 tours) incluant volontairement des **mentions déictiques** : « *sur cette page…* », « *ce document montre…* », « *comme on le voit ici…* ».
- Au moins **une session déjà terminée/publiée** sur le tenant pour tester la reprise/relecture.

---

## 4. G0 — Accès & bascule du flag

### A0.1 — Bascule `?exp=fil` / `?exp=v0`
- **Objectif** : la même route rend bien l'une ou l'autre expérience selon le paramètre.
- **Étapes** : ouvrir `/knowledge/capture?exp=fil`, puis `?exp=v0`.
- **Attendu** : A affiche le shell cockpit « Le Fil » ; B affiche le monolithe v0 ; pas d'erreur console.
- **Critères** : bascule fiable, pas de flash d'écran cassé.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Sév : ___ · Notes : ___

### A0.2 — Défaut tenant Andritz = Le Fil
- **Étapes** : ouvrir `/knowledge/capture` **sans** paramètre (localStorage vidé), hard refresh.
- **Attendu** : Le Fil s'affiche par défaut (réglage tenant).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : N/A · Notes : ___

### A0.3 — Non-régression autres tenants
- **Étapes** : sur un tenant **non-Andritz**, ouvrir `/knowledge/capture` sans paramètre.
- **Attendu** : v0 par défaut (flag non activé ailleurs).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Sév : ___ · Notes : ___

---

## 5. G1 — Capture vocale temps réel

### A1.1 — Démarrage & premier texte (time-to-first-text)
- **Étapes** : démarrer la capture, parler une phrase.
- **Attendu** : connexion rapide, transcription du **premier tour** affichée en quelques secondes.
- **Critères** : latence de 1er texte ressentie ≤ v0, indicateur d'état clair.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A1.2 — Transcription continue fluide
- **Étapes** : enchaîner 5–6 tours de parole sans pause longue.
- **Attendu** : flux continu, **pas de blocage**, **pas de doublons**, **pas de gros bloc qui arrive après les questions**.
- **Critères** : régression connue (blocages/GIL) **non reproduite**.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Sév : ___ · Notes : ___

### A1.3 — Fin de tour automatique (VAD silence)
- **Étapes** : parler puis se taire ~1,5 s.
- **Attendu** : tour committé automatiquement ; pas de coupure trop sensible en milieu de phrase.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A1.4 — Pause / reprise du micro
- **Étapes** : mettre en pause, reprendre, reparler.
- **Attendu** : l'audio reprend (micro ré-activé), la transcription repart.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

### A1.5 — Barge-in (couper l'IA) *(si applicable)*
- **Étapes** : pendant un retour audio IA, reprendre la parole.
- **Attendu** : l'IA s'efface au profit de l'expert (reset audio).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

---

## 6. G2 — Canal texte (composer) & mix voix/texte

### A2.1 — Saisie au composer
- **Étapes** : saisir un message, `Enter` pour envoyer, `Shift+Enter` pour saut de ligne.
- **Attendu** : `Enter` envoie, `Shift+Enter` insère un retour ; indicateur de niveau (VU) cohérent.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A2.2 — Mix voix + texte sans écrasement (deux canaux append-only)
- **Étapes** : alterner un tour parlé, un tour tapé, un tour parlé.
- **Attendu** : la transcription voix **n'écrase jamais** le texte tapé ; deux canaux distincts, **append-only**.
- **Critères** : cœur du design D3 — aucune perte de saisie.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Sév : ___ · Notes : ___

### A2.3 — Option « couper le micro pendant la frappe » (configurable, défaut OFF)
- **Étapes** : vérifier le défaut OFF (parler reste possible en tapant), puis activer l'option et taper.
- **Attendu** : OFF par défaut ; une fois activée, le micro se coupe pendant la frappe et reprend ensuite.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : N/A · Notes : ___

---

## 7. G3 — Le Fil (timeline)

### A3.1 — Ordre & auto-scroll
- **Étapes** : produire un mix `speak | note | anchor`.
- **Attendu** : ordre chronologique correct, **auto-scroll** vers le dernier événement, typage visuel clair des entrées.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A3.2 — Reprise d'une session **en cours**
- **Étapes** : quitter puis rouvrir une session active.
- **Attendu** : le Fil **se réhydrate** (timeline + ancres) puis continue en live.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

### A3.3 — Reprise d'une session **terminée** → rapport non vide *(régression corrigée — HIGH)*
- **Étapes** : depuis le dashboard, rouvrir une session `completed/published/archived` → surface Review ; puis « Revoir l'instant capté ».
- **Attendu** : le rapport et le Fil **ne sont pas vides** (hydratation via `GET /feed`).
- **Critères** : vérifie le fix du finding HIGH.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Sév : ___ · Notes : ___

---

## 8. G4 — La Scène & documents

### A4.1 — Upload de pièces jointes
- **Étapes** : ajouter PDF, PPTX/DOCX et image à la session.
- **Attendu** : upload OK, aperçu disponible (Office converti en PDF), pas de blocage de la séance (indexation différée).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A4.2 — Vue « en scène » + pellicule
- **Étapes** : afficher une vue (page/slide/image) en scène ; épingler plusieurs vues.
- **Attendu** : une vue principale en scène, **pellicule** des vues épinglées, navigation fluide.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A4.3 — Multi-pin
- **Étapes** : épingler 2–3 vues actives, les associer à des tours.
- **Attendu** : multi-épinglage stable, association au bon tour.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

---

## 9. G5 — Pointage & ancres

### A5.1 — Mention déictique → ancre fantôme auto-confirmée
- **Étapes** : afficher une vue, dire « sur cette page… ».
- **Attendu** : une **ancre fantôme** apparaît (pending, respiration), **countdown ~4,2 s** puis auto-confirmation.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : N/A · UX : _/5 · Notes : ___

### A5.2 — Confirmation manuelle avant countdown
- **Étapes** : cliquer « Confirmer » sur l'ancre fantôme.
- **Attendu** : passe à `confirmed` immédiatement (pas d'appel backend superflu).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Notes : ___

### A5.3 — Relier (rebind) à une autre vue *(régression corrigée — locators)*
- **Étapes** : sur une ancre, « Relier » vers une **autre page/slide/image** en scène.
- **Attendu** : l'ancre pointe la **nouvelle vue** ; **aucun locator périmé** (l'ancienne page/slide/image ne subsiste pas).
- **Critères** : vérifie le fix « stale locators ».
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Sév : ___ · Notes : ___

### A5.4 — Écarter (discard) *(régression corrigée — compteur)*
- **Étapes** : écarter une ancre, puis ouvrir le triage / la liste documents.
- **Attendu** : l'ancre écartée **n'apparaît pas** dans le rapport, **n'est pas indexée**, et **n'est plus comptée** dans `referenced_views_count`.
- **Critères** : vérifie le fix « discarded counted ».
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Sév : ___ · Notes : ___

### A5.5 — Faible confiance (lowconf)
- **Étapes** : provoquer une mention ambiguë (≥ 2 vues candidates).
- **Attendu** : ancre **lowconf** (ambre, confiance < 0,7), action de désambiguïsation proposée.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : N/A · Notes : ___

### A5.6 — Échec réseau sur action d'ancre → rollback *(régression corrigée)*
- **Étapes** : couper le réseau, tenter confirm/discard sur une ancre, observer, puis rétablir.
- **Attendu** : la pastille **revient à son état précédent** (pas d'état optimiste figé) + message d'erreur.
- **Critères** : vérifie le fix « optimistic rollback ».
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Sév : ___ · Notes : ___

---

## 10. G6 — Oracle (assistance non bloquante)

### A6.1 — Informations issues de la base de connaissances
- **Étapes** : aborder un sujet couvert par la KB.
- **Attendu** : suggestions/infos KB pertinentes, **sans figer** la capture.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A6.2 — Questions de relance
- **Étapes** : laisser l'oracle proposer des relances ; garder / ignorer.
- **Attendu** : relances utiles, calmes, **non bloquantes** ; keep/ignore fonctionnent.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

---

## 11. G7 — Triage de fin de capture (share_level)

### A7.1 — Modale segmentée, défaut `excerpt`
- **Étapes** : terminer la capture → modale de triage.
- **Attendu** : choix par document `full | excerpt | none`, **défaut `excerpt`**, lisible et segmenté.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : N/A · UX : _/5 · Notes : ___

### A7.2 — Raisons pré-déduites
- **Attendu** : raisons/justifications pré-remplies cohérentes avec l'usage en séance.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Notes : ___

### A7.3 — Confirmation explicite pour `none`
- **Étapes** : passer un document à `none`.
- **Attendu** : confirmation demandée ; rappel que les **vues ancrées restent dans le rapport** (provenance préservée), seule l'indexation KB est retenue.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Notes : ___

---

## 12. G8 — Rapport & provenance

### A8.1 — Fin de rédaction & passage à l'onglet rapport *(ancien bug)*
- **Étapes** : lancer la finalisation, observer les loaders du pop-up.
- **Attendu** : **fin de process bien détectée**, **passage automatique** à l'onglet rapport après les loaders (pas de blocage/timeout fantôme).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Sév : ___ · Notes : ___

### A8.2 — Marqueurs de sources cliquables
- **Attendu** : marqueurs de provenance dans le rapport, cliquables, ouvrant l'inspecteur.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A8.3 — Vue pointée surlignée
- **Attendu** : la vue source s'affiche avec **surlignage** de la zone (document-preview + highlight).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

### A8.4 — « Revoir l'instant capté » (bidirectionnel)
- **Étapes** : depuis une source du rapport, revenir à l'instant du Fil, et inversement.
- **Attendu** : navigation **bidirectionnelle** correcte vers le bon événement.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

### A8.5 — Bandeau d'indexation en arrière-plan (non bloquant)
- **Étapes** : observer le rapport juste après finalisation.
- **Attendu** : **bandeau** d'indexation background visible, **non bloquant** (le rapport est consultable pendant l'indexation), mise à jour d'état via WS.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : N/A · Notes : ___

---

## 13. G9 — Design System cockpit (DS-C)

### A9.1 — Knowledge Base re-skin
- **Attendu** : `knowledge-base` en cockpit (`.ck-surface`/`--ck-*`), comportement identique à avant.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A9.2 — Knowledge View re-skin
- **Attendu** : `knowledge-view` cockpit, fonctionnalités préservées.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A9.3 — Embedding Map re-skin
- **Attendu** : `embedding-map` cockpit, rendu/interaction OK.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · UX : _/5 · Notes : ___

### A9.4 — Cohérence visuelle globale
- **Attendu** : Le Fil + écrans knowledge jugés **plus modernes / cohérents** que v0.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · **Préf : ___** · UX : _/5 · Notes : ___

---

## 14. G10 — Robustesse & cas limites

### A10.1 — Perte réseau / reconnexion WS
- **Étapes** : couper/rétablir le réseau pendant une capture.
- **Attendu** : état « reconnecting » clair, reprise sans perte du Fil déjà capté.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Sév : ___ · Notes : ___

### A10.2 — Session longue
- **Étapes** : capture prolongée (≥ 15 min, nombreux tours/ancres).
- **Attendu** : pas de freeze, pas de dérive mémoire perceptible, ordre du Fil stable (tiebreak `sequence`).
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Sév : ___ · Notes : ___

### A10.3 — Publication du rapport
- **Étapes** : publier depuis la surface Publish.
- **Attendu** : publication OK, retour cohérent vers Review.
- **Résultat** — Verdict A : ☐OK ☐Réserve ☐KO · Préf : ___ · Notes : ___

---

## 15. Régressions ciblées (revue post-déploiement)

Rappel des 6 correctifs à re-vérifier en priorité :

| Réf | Finding (sévérité) | Cas de test |
|---|---|---|
| R1 | Reprise session terminée → rapport vide (HIGH) | **A3.3** |
| R2 | Revisit sans hydratation (MED) | **A3.3 / A8.4** |
| R3 | Rebind laisse des locators périmés (MED) | **A5.3** |
| R4 | Ancres `discarded` encore comptées (MED) | **A5.4** |
| R5 | Statut d'ancre optimiste non annulé sur échec (MED) | **A5.6** |
| R6 | Tri du Fil par `ts_ms` seul, perte d'ordre (LOW) | **A10.2** |

---

## 16. Matrice de synthèse (à remplir)

| ID | Scénario | Verdict A | Préf A/B | UX /5 | Sévérité | Preuve | Notes |
|---|---|---|---|---|---|---|---|
| A0.1 | Bascule exp= | | | | | | |
| A0.2 | Défaut Andritz=fil | | N/A | | | | |
| A0.3 | Défaut autres=v0 | | N/A | | | | |
| A1.1 | 1er texte | | | | | | |
| A1.2 | Flux continu | | | | | | |
| A1.3 | Fin de tour VAD | | | | | | |
| A1.4 | Pause/reprise | | | | | | |
| A1.5 | Barge-in | | | | | | |
| A2.1 | Composer | | | | | | |
| A2.2 | Mix voix/texte | | | | | | |
| A2.3 | Mute pendant frappe | | N/A | | | | |
| A3.1 | Ordre + auto-scroll | | | | | | |
| A3.2 | Reprise en cours | | | | | | |
| A3.3 | Reprise terminée (R1/R2) | | | | | | |
| A4.1 | Upload PJ | | | | | | |
| A4.2 | Scène + pellicule | | | | | | |
| A4.3 | Multi-pin | | | | | | |
| A5.1 | Ancre fantôme | | N/A | | | | |
| A5.2 | Confirm manuel | | | | | | |
| A5.3 | Rebind (R3) | | | | | | |
| A5.4 | Discard (R4) | | | | | | |
| A5.5 | Lowconf | | N/A | | | | |
| A5.6 | Rollback échec (R5) | | | | | | |
| A6.1 | Oracle KB | | | | | | |
| A6.2 | Relances | | | | | | |
| A7.1 | Triage défaut excerpt | | N/A | | | | |
| A7.2 | Raisons pré-déduites | | | | | | |
| A7.3 | Confirmation none | | | | | | |
| A8.1 | Fin rédaction → rapport | | | | | | |
| A8.2 | Marqueurs sources | | | | | | |
| A8.3 | Vue surlignée | | | | | | |
| A8.4 | Revoir l'instant | | | | | | |
| A8.5 | Bandeau indexation | | N/A | | | | |
| A9.1 | DS-C knowledge-base | | | | | | |
| A9.2 | DS-C knowledge-view | | | | | | |
| A9.3 | DS-C embedding-map | | | | | | |
| A9.4 | Cohérence visuelle | | | | | | |
| A10.1 | Perte réseau | | | | | | |
| A10.2 | Session longue (R6) | | | | | | |
| A10.3 | Publication | | | | | | |

### Verdict global

- **KO bloquants/majeurs** : _nombre_ → _liste IDs_
- **Préférence globale** : ☐ A>B ☐ A≈B ☐ A<B
- **Esthétique DS-C vs v0** : ☐ mieux ☐ équivalent ☐ moins bien
- **Décision** : ☐ **Go** ☐ **Go avec réserves** ☐ **No-go**
- **Commentaire de synthèse** : ___
