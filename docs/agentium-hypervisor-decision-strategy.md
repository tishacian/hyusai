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
> User stories (format papAI, objets Agentium) :
> [`agentium-hypervisor-user-stories.md`](./agentium-hypervisor-user-stories.md),
> MVP COMEX [`agentium-hypervisor-mvp-comex.md`](./agentium-hypervisor-mvp-comex.md).
>
> Deck de présentation :
> [`deck-agentium-decision-adoption.md`](./deck-agentium-decision-adoption.md).
>
> Pack Office (régénérer avec
> `python3 docs/render/build_hypervisor_decision_pack.py`) :
> [`agentium-hypervisor-decision-strategy.fr.docx`](./agentium-hypervisor-decision-strategy.fr.docx),
> [`deck-agentium-decision-adoption.fr.pptx`](./deck-agentium-decision-adoption.fr.pptx).
> English twins:
> [`agentium-hypervisor-decision-strategy.en.md`](./agentium-hypervisor-decision-strategy.en.md),
> [`agentium-hypervisor-decision-strategy.en.docx`](./agentium-hypervisor-decision-strategy.en.docx),
> [`deck-agentium-decision-adoption.en.pptx`](./deck-agentium-decision-adoption.en.pptx).

Comment lire : le glossaire et les §1–3 suffisent pour un COMEX. Les
routes, interrupteurs et extraits d’API sont des notes pour qui prépare
une démo ou implémente — on peut les sauter.

---

## 0. Dix mots

| Mot | Sens courant |
|---|---|
| **System** | Un système d’IA industrialisé : un objectif métier, des règles, une façon de s’exécuter. Pas un chat. |
| **Run** | Une exécution tracée. Terminé ≠ réponse validée ≠ argent gagné. |
| **Work** | Là où le métier fait le travail, dans une application publiée. |
| **Studio** | L’écran de cette application : suivre, et approuver quand on le demande. |
| **Cockpit** | Là où l’on construit, suit, améliore et administre les Systems. |
| **Hyperviseur / Impact** | Le **grand livre** du portefeuille : ce qui a déjà tourné. Ce n’est pas la salle d’opération. |
| **Décision** | Un avis humain (accepter / refuser). Dans l’Hyperviseur, cela **enregistre** l’avis. Cela n’applique pas le changement. |
| **Steer** (Piloter) | L’écran d’**un** System où l’on peut, si c’est ouvert, simuler puis appliquer un changement, puis mesurer. |
| **Base de valeur** | Une convention signée (« ce type de résultat vaut X heures ou Y € »). C’est **déclaré**, pas comptable. |
| **Mesuré / déclaré / absent** | Trois qualités d’un chiffre. Absent **n’est pas** un zéro. |

Mots à éviter à l’écran : Desk, Board, workflow, pipeline, job, « HITL ».
On dit **Flow**, **Run**, **approbation humaine**.

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
| **Action** | Accepter, refuser, rejouer, promouvoir une réponse de référence, ou appliquer un changement encadré. |

L’Hyperviseur est la **vue portefeuille** de cette chaîne. Il n’est pas
l’endroit où l’on « appuie sur un bouton magique » pour changer le runtime.

---

## 2. Observer, consommer, monitorer, décider

Quatre verbes, quatre contrats. Les mélanger est la principale erreur de
démo auprès d’un COMEX.

| Verbe | Question | Où | Ce que la personne emporte |
|---|---|---|---|
| **Observer** | Qu’est-ce que le portefeuille a rendu ? Sur quelle preuve ? | Hyperviseur / Impact | Un registre : mesuré / déclaré / absent. Pas un zéro inventé. |
| **Consommer** | Quelle tâche dois-je finir maintenant ? | Work, Studio (l’application publiée) | Un résultat vérifiable, des sources ouvertes, une **approbation humaine** si la règle l’exige. |
| **Monitorer** | Qu’est-ce qui tourne, attend, dérive ? | Exécutions, file de revue, Diagnostics | Santé d’exécution et files d’attente — explicitement **pas** le succès métier. |
| **Décider** | Qu’est-ce qui attend une signature, et où le changement s’applique ? | File de l’Hyperviseur (avis) · approbation dans l’application · **Steer** (appliquer) | Un avis enregistré + une trace. Le modèle ne peut pas signer à sa place. |

On passe de Work au Cockpit selon les **droits**, pas selon un bouton
« mode ». Les identifiants, le journal et les liens profonds sont
partagés.

*Côté technique :* Hyperviseur = `/hypervisor` (le menu peut dire
**Impact** si le parcours d’accueil est allumé). Work = `/work`. File de
revue = `/steering/review-queue`.

---

## 3. L’Hyperviseur

### 3.1 Une phrase

L’Hyperviseur est le **grand livre du portefeuille IA** : ce que les Systems
ont exécuté, ce que cela a coûté, ce qui est déclaré comme valeur, ce qui
manque, et **ce qui attend une signature**.

Deux lectures possibles de la même page : un **bilan de valeur** (ancienne
vue) ou un **grand livre** (nouvelle vue). Le menu peut dire **Impact**.
Changer le nom de l’onglet **n’établit pas** un résultat économique.

*Côté technique :* route unique `/hypervisor`. La nouvelle vue s’allume
avec l’interrupteur d’espace `hypervisor_v2`.

### 3.2 Deux lectures, un même avis à signer

| | **Ancienne vue — Bilan de valeur** | **Nouvelle vue — Grand livre** |
|---|---|---|
| Promesse à l’écran | « Valeur nette générée » — coût, valeur estimée, ROI, signaux, recommandations | « Ce que le portefeuille a rendu » — encre = mesuré, teal = déclaré |
| Comment on lit | Une page de chiffres + signaux + décisions | **Comprendre → Détailler → Décider** |
| Fenêtres | Une page, période au choix (semaine / mois / 30 j / 90 j) | Direction (heures, 90 j) · Opérations (exécutions, 30 j) · Conformité (exécutions, 90 j) |
| Résumé de boucle de valeur | Oui — un agrégat en lecture seule | Non — le grand livre n’est pas le même tableau |
| Décider | Accepter / Refuser | Accepter / Refuser |

Les deux vues **enregistrent un avis** (accepter / refuser). Aucune des
deux **n’applique** un changement de règle via « Appliquer » : c’est
refusé volontairement, et l’écran renvoie vers le pilotage d’un System.
Ce n’est pas un bug de démo.

Phrase à dire : *« Valider ici enregistre un avis. Modifier un System
passe par son écran de pilotage : Simuler → Approuver → Appliquer →
Mesurer. »*

*Côté technique :* l’ancien chemin d’application répond un refus explicite
(`LEGACY_DECISION_ACTUATOR_DISABLED`).

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

**Mission Room** est une **application d’espace** immersive (briefing type
gouvernement / ville). Même famille d’adresse que l’Hyperviseur, **autre
contrat**. Ne pas la présenter comme le grand livre du portefeuille.

---

## 4. Où une décision devient une action

Trois plans, à ne pas fusionner.

```text
Portefeuille                 Un System                    L’application
Hyperviseur / Impact         Écran de pilotage (Steer)    Studio
accepter / refuser           Simuler → Approuver          approbation humaine
= un avis                    → Appliquer → Mesurer        = obligatoire
                             = changement borné
```

### 4.1 Un avis sur le portefeuille

Accepter ou refuser dans l’Hyperviseur fait passer la proposition à
*acceptée* ou *refusée*. Cela nourrit parfois une revue qualité. Un
scénario de **changement de règle** refuse ce chemin : il doit passer par
le pilotage du System.

*Côté technique :* `POST /hypervisor/decisions/{id}/accept|reject`.

### 4.2 Appliquer un changement — boucle de valeur

Contrat visible : **Résultat → Décision → Simuler → Approuver → Appliquer
→ Mesurer**.

- Sur **un** System, dans Steer — pas sur tout le portefeuille.
- Ouvert seulement si l’interrupteur « boucle de valeur » est allumé **et**
  que ce System est choisi pour l’essai.
- Premier changement autorisé, volontairement étroit : un ajustement de
  garde-fous, seulement si le System le déclare et si le contrôle
  d’exécution l’autorise. Sinon : *non configuré*.
- Le point de départ est une vraie exécution enregistrée par le serveur.
  Un exemple, un essai ou un chiffre saisi à la main est **refusé**.
- *Une simulation n’est pas une mesure.* On ne clôt que si une exécution
  **après** le changement a été observée.
- Détail : [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md).

L’ancien écran de politiques existe encore. L’aperçu « leviers / et si »
y est **éteint**. Ne pas promettre un aperçu d’impact universel en direct :
c’est **planifié**, pas branché.

*Côté technique :* interrupteurs `value_loop_v1` + canari System ;
actionneur `control_policy.guardrails.patch.v1` ; what-if
`not_configured`.

### 4.3 Approbation humaine dans l’application

Dans une application publiée (Studio), une demande d’approbation est une
**décision humaine explicite**. Le modèle ne peut pas cliquer à la place
de la personne. Une file de revue traite les contrôles qualité. Ces actes
ont une provenance humaine dans le journal.

---

## 5. Industrialiser l’IA : ce que ça change pour la stratégie

Industrialiser, dans Agentium, n’est pas « mettre un LLM en production ».
C’est faire tenir **cinq disciplines** sur le même objet `System`.

| Discipline | Ce que le COMEX obtient | Où le voir |
|---|---|---|
| **Alignement** | Chaque System sert une capacité métier, pas un prompt orphelin | Capacités, Systems, Work |
| **Publication** | Ce que le métier utilise est une **application** liée à une version publiée | Créer une app → Work |
| **Preuve** | Chaque réponse a une exécution, un coût éventuel, un contexte, une lignée | Fiche d’exécution, conversation « Preuves de l’action » |
| **Gouvernance** | Règles, droits d’accès, journal, contrôle d’exécution — jamais « prompt only » | Audit, accès |
| **Allocation** | On arbitre ce qu’on finance, ce qu’on resserre, ce qu’on arrête, **sur preuve** | Hyperviseur + pilotage du System |

Conséquence stratégique :

1. **Le portefeuille devient un objet de management**, pas une collection de
   PoC. On peut dire *combien de Systems ont une base de valeur*, *lesquels
   n’ont que des runs*, *lesquels attendent une signature*.
2. **La conversation n’est pas un canal parallèle.** Elle réutilise les
   mêmes règles, droits et approbations. Elle peut lancer une action
   autorisée ; elle ne crée pas un droit.
3. **L’économie n’est pas un badge décoratif.** Les cinq indicateurs
   d’**objectif opérationnel** ne sont pas un ROI attesté. La boucle de
   valeur porte les mesures économiques. « Heures / argent économisés »
   reste un **trou** : on ne l’a pas encore prouvé.
4. **Le risque d’autonomie est borné.** Un seul type de changement
   autorisé, un contrôle d’exécution, un humain sur les approbations. On
   industrialise le contrôle autant que l’exécution.

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
| Parcours d’accueil métier | Code livré, **éteint par défaut** — pas encore validé auprès des utilisateurs |
| Work / applications | Le métier peut travailler dans une application publiée ; « intégré » ≠ accepté en production |
| Guides EN/FR | Démarrer, sources, Systems, exécutions, valeur |
| Exemple guidé (NorthForge) | Quatre étapes, sur l’espace de démonstration, collection d’exemples requise |
| Compagnon de conversation | Présent dans Work et le Cockpit, même périmètre que l’écran, le modèle ne signe pas |
| Objectifs opérationnels | 5 indicateurs bornés sur le System — pas un ROI |
| Sessions d’utilisabilité | **Non tenues** (cible : 5 métier + 5 développeurs) |
| Seuil NorthForge | 4/5 métier finissent **seuls en 10 minutes** — non mesuré |
| Passage en défaut / retrait | Séquence sponsor (essai → défaut → retrait) — **non signée** |

L’adoption n’est **pas une édition permanente**. C’est un contrôle de
déploiement. Le récit à tenir : *« le chemin métier existe ; il n’est pas
encore le défaut de tous les workspaces, et nous n’avons pas encore la
feuille d’acceptation. »*

### 6.2 Trois couches de « persona » — ne pas les confondre

| Couche | Valeurs | Ce qu’elle change | Ce qu’elle ne change pas |
|---|---|---|---|
| **Droits d’accès** | Droits dans l’espace | Ce que la personne *peut* faire | — |
| **Mode de l’espace** | Construire / Opérer / Diriger (+ démo, portefeuille) | Densité de l’écran, accueil, ce qui est dit en économique ou technique | Les droits |
| **Préférence membre** (accueil) | Construction / Utilisation / Pilotage de la valeur | Ton des guides | Mode, rôle, droits |

Le mode démo masque fournisseurs et modèles (présentation sûre). Le mode
portefeuille existe en coulisse, volontairement absent du sélecteur.

Personas de récit (deck produit) — utiles pour une histoire, **pas** des
comptes :

| Persona | Entre par | Job |
|---|---|---|
| Sarah — direction IA | Hyperviseur / Impact | Arbitrer le portefeuille |
| Mehdi — pilote | Pilotage d’un System | Encadrer les règles |
| Alex — concepteur | Créer | Composer un System |
| Claire — métier | Work d’abord ; Cockpit seulement pour forer une exécution | Utiliser et tracer |
| Léo — curateur | Connaissances | Préparer les sources |
| Nadia — conformité | Journal d’audit | Contrôler |

Claire ne « vit » pas dans la fiche technique d’un System. Le métier
travaille dans **Work**. Le chat du Cockpit est le chemin opérateur.

### 6.3 Courbe d’apprentissage

Trois paliers **déclarés**, pas encore un coach automatique (§38 planifié).

```text
1. Exécuter une tâche          Work / Studio
2. Relier le résultat à un Run  Citations, /runs, compagnon
3. Relier le Run à une décision Impact + gates + (si activé) boucle de valeur
```

| Profil | Premiers 15 minutes | Première semaine |
|---|---|---|
| **C-level observateur** | Work → une application publiée → Impact → lire mesuré / déclaré / absent → aide valeur | Revue 30 j / 90 j, couverture des conventions de valeur, avis en attente, un passage audit. **Pas** d’« heures économisées € » sans une mesure après changement. |
| **Métier** | Work → question → ouvrir la source → (optionnel) exemple guidé. Préférence **Utilisation**. | Quotidien Work ; file de revue si on lui a assigné ; ouvrir une exécution seulement pour forer. *Terminé ≠ réponse validée.* |
| **Décideur** | Une approbation dans l’application **ou** un avis Hyperviseur **avant** d’ouvrir le pilotage | Boîte : approbations + revue + file Impact. Un scénario *Simuler → Mesurer* seulement si la boucle de valeur est ouverte sur **ce** System. |

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
- « Le parcours d’accueil = produit mature » — c’est un robinet, éteint par défaut.
- « Impact = ROI » — le renommage n’établit pas l’outcome.

---

## 7. Contrat d’honnêteté — phrases à tenir / à interdire

| Tenir | Interdire |
|---|---|
| *Une donnée absente n’est pas un zéro.* | Afficher ou raconter un 0 € / 0 h là où l’état est `not_measured` / `not_configured`. |
| *Une simulation n’est pas une mesure.* | « On a simulé, donc on a gagné. » |
| *Accepter dans l’Hyperviseur enregistre un avis.* | « L’Hyperviseur applique tout seul la règle. » |
| *La boucle de valeur vit sur un System, si elle est ouverte.* | « Tous les espaces ferment la boucle. » |
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

1. **Work** — une application publiée, une question, une source ouverte. *Consommer.*
2. **Une exécution** — le lien profond. *Monitorer : voici la preuve, pas le gain.*
3. **Hyperviseur / Impact** — légende mesuré / déclaré, une décision en
   attente. *Observer, puis donner un avis.*
4. **Pilotage d’un System** (seulement si la boucle de valeur est vraiment
   ouverte) — *Simuler n’est pas mesurer.* Sinon, s’arrêter et le dire.
5. **Aide valeur** — refermer sur la distinction coût observé / valeur
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
