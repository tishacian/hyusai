# Agentium — Hyperviseur, décision et industrialisation de l'IA

> Briefing pour qui prépare, présente ou pilote Agentium auprès d’un
> **C-level**, d’un **métier** ou d’un **décideur opérationnel**.
>
> Ce n’est pas le contrat d’implémentation. Les sources normatives restent
> [`mental-model.md`](./mental-model.md) et
> [`agentium-reference.md`](./agentium-reference.md). La preuve d’adoption
> utilisateur est dans
> [`agentium-adoption-roadmap.md`](./agentium-adoption-roadmap.md) — aujourd’hui
> **implémentée, opt-in, non acceptée**.
>
> Deck de présentation :
> [`deck-agentium-decision-adoption.md`](./deck-agentium-decision-adoption.md).

---

## 1. Ce qu’Agentium change dans la décision d’entreprise

Les plateformes « agent builder » s’arrêtent au composer : un prompt, un
outil, une démo. Elles ne disent pas **quel objectif métier** est servi, **ce
qui s’est réellement passé**, **qui a tranché**, ni **si l’organisation
s’améliore**.

Agentium industrialise des **Systems** — des systèmes intelligents liés à des
capacités métier, exécutés sous politiques, avec une preuve canonique.

La règle produit (mental model §0.0) :

- Une **application métier** et une **conversation** sont deux façons
  première classe d’utiliser et de contrôler un System publié.
- **Work** sert la tâche. **Cockpit** expose la construction, l’opération,
  l’amélioration, l’impact et l’administration.
- Le succès est un **résultat vérifiable**, puis une **amélioration
  opérationnelle ou économique**. Le débit et la latence expliquent la santé
  d’exécution ; ils ne prouvent pas un gain métier.
- Une valeur déclarée, une projection, une mesure opérationnelle et un
  impact économique attesté restent **distincts**. Une heure gagnée ou un
  euro économisé exigent une baseline, des unités comparables et une preuve
  attribuable. Un Run terminé ne suffit pas.

Chaîne canonique :

```text
System → Run → Evaluation → Decision → Action
```

| Maillon | Rôle pour la stratégie |
|---|---|
| **System** | Intention industrialisée : objectif, graphe, contexte, politiques. |
| **Run** | Une exécution traçable (coût, latence, contexte, provenance). |
| **Evaluation** | Score et dimensions — la qualité n’est pas un ressenti. |
| **Decision** | Proposition humaine ou machine : revue, recommandation, scénario de valeur. |
| **Action** | Acceptation, rejet, replay, promotion d’une réponse canonique, ou enactment gouverné. |

L’Hyperviseur est la **vue portefeuille** de cette chaîne. Il n’est pas
l’endroit où l’on « appuie sur un bouton magique » pour changer le runtime.

---

## 2. Observer, consommer, monitorer, décider

Quatre verbes, quatre contrats. Les mélanger est la principale erreur de
démo auprès d’un COMEX.

| Verbe | Question | Surface | Ce que la personne emporte |
|---|---|---|---|
| **Observer** | Qu’est-ce que le portefeuille a rendu ? Sur quelle preuve ? | `/hypervisor` (rail **Impact** si l’expérience d’adoption est active) | Un registre : mesuré / déclaré / absent. Pas un zéro inventé. |
| **Consommer** | Quelle tâche dois-je finir maintenant ? | `/work`, `/work/:slug`, Studio (ex. `/work/pr-to-po`) | Un résultat vérifiable, des citations, un gate humain si la politique l’exige. |
| **Monitorer** | Qu’est-ce qui tourne, attend, dérive ? | `/runs`, `/observability`, `/steering/review-queue`, Diagnostics | Santé d’exécution et files d’attente — explicitement **pas** le succès métier. |
| **Décider** | Qu’est-ce qui attend une signature, et où ça s’enacte ? | Feed `/hypervisor` (signal) · gates Work/Studio · boucle de valeur **Steer** | Un état de `Decision` + un audit. Le modèle ne peut pas signer à sa place. |

`Work ↔ Cockpit` est un lien **RBAC**, pas un interrupteur de thème. Les
identifiants, l’audit et les deep links sont partagés.

Mots interdits à l’écran et dans un brief : **Desk**, **Board**,
**workflow** / **pipeline** (dire **Flow**), **job** (dire **Run**),
**HITL** comme libellé (dire **approbation humaine**).

---

## 3. L’Hyperviseur

### 3.1 Une phrase

L’Hyperviseur est le **grand livre du portefeuille IA** : ce que les Systems
ont exécuté, ce que cela a coûté, ce qui est déclaré comme valeur, ce qui
manque, et **ce qui attend une signature**.

Route unique : `/hypervisor`. Le composant (v1 ou v2) dépend du flag
workspace `settings.features.hypervisor_v2`. Absent ou `false` → v1.

Avec l’expérience d’adoption, le rail Cockpit relabelle cette zone
**Impact** (FR). L’identifiant de navigation reste `hypervisor`. Renommer
l’onglet **n’établit pas** un outcome économique.

### 3.2 Deux lectures, un même objet `Decision`

| | **v1 — Bilan de valeur** | **v2 — Grand Livre** (flag `hypervisor_v2`) |
|---|---|---|
| Promesse UI | « Valeur nette générée » — coût, valeur estimée, ROI, signaux, recommandations SCAN | « Ce que le portefeuille a rendu » — encre = mesuré, teal = déclaré |
| Strates | Hero + KPI + capacités + signaux + reco + décisions | **Comprendre → Détailler → Décider** |
| Vues | Une page, période WTD/MTD/QTD/30j/90j | Direction (heures, 90j) · Operations (runs, 30j) · Conformité (runs, 90j) |
| Boucle de valeur portefeuille | Oui — agrégat en lecture (`GET /hypervisor/value-loop`) | Non — le v2 est un registre instrumenté, pas le même tableau de bord |
| Décider | Accepter / Rejeter | Accepter / Rejeter |

Les deux versions **acceptent et rejettent** une `Decision` proposée. Aucune
des deux **n’enacte** un changement de policy via « Appliquer » : l’API
répond `LEGACY_DECISION_ACTUATOR_DISABLED` et renvoie vers la boucle de
valeur d’un System. C’est volontaire, pas un bug de démo.

Phrase à dire : *« Valider ici enregistre un signal de décision. Modifier le
comportement d’un System passe par Steer : Simuler → Approuver → Agir →
Mesurer. »*

### 3.3 Ce que le C-level doit lire (et ce qu’il ne doit pas)

**À lire**

- La légende v2 : *encre = mesuré · teal = déclaré · une donnée absente n’est
  pas un zéro*.
- Le héros : heures rendues, runs exécutés, ou valeur **déclarée** — le
  libellé le dit.
- Les **bases de valeur** : une base est signée, datée, versionnée. Sans
  base, le produit montre l’unité native.
- Le feed **Décisions** : *Ce qui attend une signature*.
- En v1 seulement : le bandeau *Une simulation n’est pas une mesure* sur
  l’agrégat de boucle de valeur.

**À ne pas lire comme une vérité financière**

- La « valeur nette » v1 = `valeur estimée − coût` sur les Runs visibles.
  Le chrome le qualifie de **modèle de ROI des capacités**.
- Un ROI affiché quand le coût est quasi nul : le backend le **supprime**
  (seuil ~0,01) et plafonne l’affichage.
- Un zéro géométrique sur un graphique v2 : remplissage de calendrier, pas
  une mesure.

### 3.4 Mission Room n’est pas l’Hyperviseur

`/hypervisor/mission-room/*` est une **application de workspace** immersive
(Sentinel-CI, Octocity, ou provider générique). Briefing ministériel, carte,
veille, arbitrages de cabinet. Même préfixe d’URL, **autre contrat**. Ne pas
les présenter comme le grand livre du portefeuille.

---

## 4. Où une décision devient une action

Trois plans, à ne pas fusionner.

```text
Portefeuille          System                    Application
/hypervisor           /systems/:id?lens=steer   /work/:slug  (Studio)
accept / reject       Simulate → Approve        gate humain
= signal              → Act → Measure           = approbation
                      = enactment borné         requise
```

### 4.1 Signal portefeuille

`POST /hypervisor/decisions/{id}/accept|reject` fait passer
`proposed → accepted | rejected`. Un `kind=review_required` peut nourrir le
feedback d’évaluation. Un `scenario_id` (boucle de valeur) **refuse** ce
chemin : il doit passer par l’orchestrateur de valeur.

### 4.2 Enactment — boucle de valeur (Lot 8)

Contrat : `Outcome → Decision → Simulate → Approve → Act → Measure`.

- Porte par **System**, dans Steer — pas par le portefeuille.
- Gate : `features.value_loop_v1` **et** activation du System (canari
  `settings.experience.value_loop_canary = "v1"` pendant le déploiement).
- Premier actionneur, volontairement borné :
  `control_policy.guardrails.patch.v1`, seulement si le System le déclare et
  si la Membrane v2 en `enforce` l’autorise. Sinon : `not_configured`.
- Baseline = Run terminé à provenance serveur `runtime_auto`. Un seed, un
  canari ou une valeur opérateur est **refusé** comme baseline.
- `simulation_is_measurement: false` partout. Une mesure ne clôt le
  scénario que sur un Run post-action réellement observé.
- Détail : [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md).

`/steering` (page historique) garde le CRUD de politiques. L’aperçu
« leviers / what-if » y est **éteint**. `POST /hypervisor/what-if` et
`POST /control-plane/simulate` répondent `not_configured` et pointent vers
`/systems/{id}/value-loop`. Ne pas promettre un impact preview universel
(< 300 ms) : c’est **planifié**, le composant n’est pas branché.

### 4.3 Approbation humaine dans Work

Dans une application publiée (Studio), un gate est une **décision humaine
explicite**. Le modèle ne peut pas accepter à la place de la personne
(`POST /assistant/decisions` exige l’action UI et l’id observé). La file
`/steering/review-queue` traite les revues d’évaluation. Ces actes ont une
provenance humaine dans l’audit.

---

## 5. Industrialiser l’IA : ce que ça change pour la stratégie

Industrialiser, dans Agentium, n’est pas « mettre un LLM en production ».
C’est faire tenir **cinq disciplines** sur le même objet `System`.

| Discipline | Ce que le COMEX obtient | Où le voir |
|---|---|---|
| **Alignement** | Chaque System sert une Capability, pas un prompt orphelin | `/capabilities`, `/systems`, Work |
| **Publication** | Ce que le métier consomme est une **Experience** liée à une version publiée | `/create/apps` → `/work/:slug` |
| **Preuve** | Chaque réponse a un Run, un coût éventuel, un contexte, une lignée | `/runs/:id`, conversation « Preuves de l’action » |
| **Gouvernance** | Politiques, IAM, audit, Membrane — jamais « prompt only » | `/governance/audit`, `/governance/access` |
| **Allocation** | On arbitrage ce qu’on finance, ce qu’on resserre, ce qu’on arrête, **sur preuve** | `/hypervisor` + boucle de valeur du System |

Conséquence stratégique :

1. **Le portefeuille devient un objet de management**, pas une collection de
   PoC. On peut dire *combien de Systems ont une base de valeur*, *lesquels
   n’ont que des runs*, *lesquels attendent une signature*.
2. **La conversation n’est pas un canal parallèle.** Elle réutilise les
   mêmes contrats, permissions et gates. Elle peut lancer une action
   autorisée ; elle ne crée pas un droit.
3. **L’économie n’est pas un badge chrome.** Les cinq métriques
   d’**objectif opérationnel** (adoption) ne sont pas un ROI attesté. La
   boucle de valeur porte les mesures économiques. L’écart « heures / argent
   économisés » (O5) reste un **trou d’acceptation** documenté.
4. **Le risque d’autonomie est borné.** Un actionneur unique, une Membrane
   en enforce, un humain sur les gates. On industrialise le contrôle autant
   que l’exécution.

La maturité visée (mental model §37), **sans UX adaptative automatique**
aujourd’hui :

```text
Construire → Exécuter → Mesurer → Optimiser → Allouer
```

Règle : *l’adoption commence par l’exécution ; le passage à l’échelle
exige l’économie.* On ne force pas un C-level à un bilan s’il n’y a pas
encore de Runs, et on ne vend pas un bilan s’il n’y a que des Runs.

---

## 6. Capacité d’adoption

### 6.1 État réel

| Élément | État |
|---|---|
| Expérience d’adoption | Code livré derrière `settings.features.adoption_experience_v1` (**off** par défaut) |
| Work / Experiences | `experience_v1` — contrat Work/runtime ; « intégré » ≠ accepté en production |
| Guides EN/FR | `/help/{start,sources,systems,runs,value}` |
| Parcours NorthForge | `/work/getting-started` — 4 étapes, Showcase + collection notices requise |
| Compagnon de conversation | Overlay Work + Cockpit, scope bound, le modèle ne signe pas |
| Objectifs opérationnels | 5 métriques bornées sur le System — pas un ROI |
| Sessions d’utilisabilité | **Non tenues** (cible : 5 métier + 5 développeurs) |
| Seuil NorthForge | 4/5 métier finissent **seuls en 10 minutes** — non mesuré |
| Retrait du flag | Séquence sponsor (pilote → défaut → retrait) — **non signée** |

L’adoption n’est **pas une édition permanente**. C’est un contrôle de
déploiement. Le récit à tenir : *« le chemin métier existe ; il n’est pas
encore le défaut de tous les workspaces, et nous n’avons pas encore la
feuille d’acceptation. »*

### 6.2 Trois couches de « persona » — ne pas les confondre

| Couche | Valeurs | Ce qu’elle change | Ce qu’elle ne change pas |
|---|---|---|---|
| **Rôle IAM** | Droits workspace | Ce que la personne *peut* faire | — |
| **Mode workspace** | `builder` / `operator` / `executive` (+ `demo`, `portfolio` provisionnés) | Densité Cockpit, home, divulgation éco/technique | Les droits |
| **Préférence membre** (adoption) | Construction / Utilisation / Pilotage de la valeur | Ton des guides `<ck-help>` | Mode, rôle, entitlements |

Le mode `demo` masque fournisseurs et modèles (présentation sûre).
`portfolio` est persisté, volontairement absent du sélecteur UI.

Personas de récit (deck produit) — utiles pour une histoire, **pas** des
comptes :

| Persona | Entrée | Job |
|---|---|---|
| Sarah — CAIO | `/hypervisor` | Arbitrer le portefeuille |
| Mehdi — Steward | `/steering` puis Steer d’un System | Enveloppe et politiques |
| Alex — Builder | `/create`, `/systems/new` | Composer un System |
| Claire — Analyste | Work d’abord ; Cockpit `/runs` en forage | Consommer et tracer |
| Léo — Curateur | `/knowledge` | Préparer les sources |
| Nadia — Gouvernance | `/governance/audit` | Conformité |

Claire ne « vit » pas dans `/systems/:id`. Le métier consomme dans
**Work**. Le chat Cockpit est le chemin opérateur.

### 6.3 Courbe d’apprentissage

Trois paliers **déclarés**, pas encore un coach automatique (§38 planifié).

```text
1. Exécuter une tâche          Work / Studio
2. Relier le résultat à un Run  Citations, /runs, compagnon
3. Relier le Run à une décision Impact + gates + (si activé) boucle de valeur
```

| Profil | Premiers 15 minutes | Première semaine |
|---|---|---|
| **C-level observateur** | `/work` → une app publiée → `/hypervisor` (Impact) → lire mesuré/déclaré/absent → `/help/value` | Revue 30j/90j, couverture des bases de valeur, décisions en attente, un passage audit. **Pas** d’« heures économisées € » sans baseline Lot 8. |
| **Métier consommateur** | `/work` → question → ouvrir la citation → (optionnel) NorthForge. Persona **Utilisation**. | Quotidien Work ; file `/steering/review-queue` si assigné ; deep link Run seulement pour forer. *Terminé ≠ réponse validée.* |
| **Décideur** | Un gate Studio **ou** une décision Hyperviseur (signal) **avant** d’ouvrir Steer | Inbox : gates + revue + feed Impact. Un scénario `Simuler → Mesurer` seulement si `value_loop_v1` est actif sur **ce** System. |

Cible d’acceptation métier (non mesurée) : premier résultat vérifiable
**seul, en dix minutes**, sur l’exemple NorthForge.

Cible builder (référence, pas une promesse client) : adapter l’exercice
« Operational Analysis » (Flow → System dédié → app publiée) en une
session ; le run interne a déjà dépassé le budget 120 min.

### 6.4 Ce que « capable d’adoption » veut dire — et ne veut pas dire

**Veut dire**

- Un métier peut entrer par **Work**, sans jargon moteur.
- Un C-level peut ouvrir **Impact** et distinguer preuve, hypothèse et
  trou.
- Un décideur a un endroit **explicite** pour signer, distinct de
  l’exécution du modèle.
- Les guides et le compagnon existent en FR/EN.
- Le chrome refuse de fabriquer un total financier de substitution.

**Ne veut pas dire**

- « Tout le monde est autonome le premier jour » — non mesuré.
- « NorthForge certifie » — les étapes visitées ne certifient rien.
- « Le flag adoption = produit mature » — le flag est un robinet.
- « Impact = ROI » — le renommage n’établit pas l’outcome.

---

## 7. Contrat d’honnêteté — phrases à tenir / à interdire

| Tenir | Interdire |
|---|---|
| *Une donnée absente n’est pas un zéro.* | Afficher ou raconter un 0 € / 0 h là où l’état est `not_measured` / `not_configured`. |
| *Une simulation n’est pas une mesure.* | « On a simulé, donc on a gagné. » |
| *Accepter dans l’Hyperviseur enregistre un signal.* | « L’Hyperviseur applique tout seul la policy. » |
| *La boucle de valeur vit sur un System, derrière un flag.* | « Tous les workspaces ferment la boucle. » |
| *Le what-if portefeuille est retiré.* | « Bougez le levier, le ROI se met à jour en live. » |
| *Mission Room est une app de workspace.* | « Mission Room = le grand livre. » |
| *Adoption opt-in, sessions non tenues.* | « L’adoption est validée par les utilisateurs. » |
| *Conformité générée = état dépôt, pas preuve de prod.* | Lire le tableau lots du mental model comme une attestation client. |

États de fait partagés : `available` · `not_measured` · `not_configured` ·
`restricted` · `unavailable`.

---

## 8. Parcours de présentation recommandé

Hard-reload (Cmd+Shift+R) avant toute parole. Un onglet périmé produit des
422 nues et un message « cet onglet a été ouvert avant une mise à jour ».

1. **Work** — une application publiée, une question, une citation. *Consommer.*
2. **Run** — deep link. *Monitorer : voici la preuve, pas le gain.*
3. **Hyperviseur / Impact** — légende mesuré/déclaré, une décision en
   attente. *Observer, puis décider (signal).*
4. **Steer d’un System** (seulement si `value_loop_v1` est réellement
   actif) — *Simuler n’est pas mesurer.* Sinon, s’arrêter et le dire.
5. **`/help/value`** — refermer sur la distinction coût observé / valeur
   déclarée / impact attesté.

Pour un client NAWA, le Studio PR→PO (`/work/pr-to-po?workspace=nawa&lang=en`)
se présente depuis le playbook opérateur, pas depuis l’UI :
[`ops/nawa-pr-to-po-live-demo-playbook.md`](./ops/nawa-pr-to-po-live-demo-playbook.md).

---

## 9. Cartographie des sources

| Document | Usage |
|---|---|
| [`mental-model.md`](./mental-model.md) | Vision, entités, maturité, limites |
| [`agentium-reference.md`](./agentium-reference.md) | Lexique, surfaces, Work / Cockpit / Studio |
| [`agentium-adoption-roadmap.md`](./agentium-adoption-roadmap.md) | Flag, lots, protocole d’acceptation |
| [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md) | Enactment Simulate → Measure |
| [`hypervisor-v2-chart-grammar.md`](./hypervisor-v2-chart-grammar.md) | Grammaire visuelle v2, vues, fact-states |
| [`deck-product-review.md`](./deck-product-review.md) | Deck mental model (équipe produit) |
| [`deck-agentium-decision-adoption.md`](./deck-agentium-decision-adoption.md) | Deck C-level / métier (ce briefing) |
| [`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md) | Script Hyperviseur v1 (SCAN) |

Copy écran à réutiliser tel quel : `frontend-ng/src/app/core/i18n/hypervisor.dict.ts`,
`experience.dict.ts`, `backend/app/content/help_content.yaml`.
