# User stories : Hyperviseur Agentium

> Ce document transmet les spécifications de l’Hyperviseur. Il reprend le
> format papAI (`En tant que / je veux / afin de`, critères, priorités)
> avec le vocabulaire Agentium, **lisible sans connaître le produit**.
>
> Comment lire : le §0 et le glossaire suffisent pour un COMEX. Les epics
> sont le contrat produit. La ligne *Côté technique* est pour l’équipe
> qui implémente — on peut la sauter.
>
> Statut : **Livré** (déjà dans le produit) · **Partiel** (existe, à
> compléter) · **Spécifié** (écrit, pas encore fait).
>
> Vue COMEX courte : [`agentium-hypervisor-mvp-comex.md`](./agentium-hypervisor-mvp-comex.md).
> Note de fond : [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md).
> English : [`agentium-hypervisor-user-stories.en.md`](./agentium-hypervisor-user-stories.en.md).
> Word : [`agentium-hypervisor-user-stories.fr.docx`](./agentium-hypervisor-user-stories.fr.docx).

---

## Glossaire — dix mots

| Mot | Sens courant |
|---|---|
| **Portefeuille** | L’ensemble des systèmes d’IA de l’organisation, dans un espace de travail. |
| **System** | Un système d’IA industrialisé : un objectif métier, des règles, une façon de s’exécuter. Pas un simple chat. |
| **Run** | Une exécution tracée : ce qui s’est passé, à quel coût éventuel, sur quelles sources. Un Run **terminé** n’est ni une réponse validée ni un gain d’argent. |
| **Work** | L’espace des applications métier. On y fait le travail, sans jargon moteur. |
| **Studio** | L’écran d’une application publiée : on suit l’exécution et on approuve quand c’est demandé. |
| **Cockpit** | L’espace où l’on construit, suit, améliore et administre les Systems. |
| **Hyperviseur** (aussi appelé **Impact**) | Le grand livre du portefeuille : ce qui a tourné, ce que ça a coûté, ce qui est déclaré comme valeur, ce qui manque, ce qui attend une signature. |
| **Décision** | Une proposition qui attend un humain : accepter ou refuser. Dans l’Hyperviseur, cela **enregistre un avis**. Cela ne change pas tout seul le System. |
| **Steer** (Piloter) | L’écran d’un System où l’on peut, si c’est ouvert, simuler puis appliquer un changement de règle, puis le mesurer. |
| **Base de valeur** | Une convention signée (« un résultat de ce type vaut X heures ou Y € »). C’est une **déclaration**, pas une mesure comptable. |

Trois qualités d’un chiffre, à ne jamais mélanger :

- **Mesuré** — observé sur de vraies exécutions (coût, nombre de Runs…).
- **Déclaré** — hypothèse ou convention (base de valeur, estimation).
- **Absent** — on n’a pas la donnée. **Ce n’est pas un zéro.**

Mots à éviter à l’écran : Desk, Board, workflow, pipeline, job. On dit
**Flow**, **Run**, **approbation humaine**.

---

## 0. L’histoire en une phrase

En tant que dirigeant, je veux voir d’un coup d’œil ce que nos systèmes
d’IA ont vraiment fait, faire utiliser les applications par les métiers,
suivre les exécutions sans les prendre pour un succès business, et
décider moi-même — donner un avis dans l’Hyperviseur, approuver dans une
application, ou (si c’est ouvert) appliquer un changement de règle sur
**un** System — afin de piloter l’IA comme le reste de l’entreprise,
**sans chiffre inventé** et **sans laisser le modèle signer à ma place**.

---

## 1. Vue d’ensemble

### 1.1 Le problème

Sans grand livre, le COMEX ne sait pas ce que l’IA a réellement produit.
Les équipes n’ont pas de chemin officiel pour remonter une preuve. On
retombe sur des e-mails, des réunions, ou un « ROI » affiché qui fabrique
un 0 € là où l’on n’a rien mesuré.

### 1.2 Ce que l’Hyperviseur apporte

| On peut… | En pratique |
|---|---|
| Lire le grand livre | Voir les exécutions, les coûts mesurés, la valeur déclarée, et ce qui manque |
| Donner un cap | Fixer un objectif opérationnel simple sur un System (volume, délai, validations, coût) |
| Faire remonter le terrain | Les applications publiées et chaque exécution laissent une trace |
| Décider | Accepter ou refuser ce qui attend une signature — **avis enregistré**, pas changement automatique |
| Appliquer un changement | Uniquement depuis l’écran de pilotage d’**un** System : simuler, approuver, appliquer, mesurer |
| Parler au portefeuille | Un compagnon de conversation, avec les mêmes droits que l’écran ; il ne signe pas |
| Contrôler | Qui voit, qui décide, qui applique ; tout est journalisé |

### 1.3 Qui fait quoi

| Persona | Job | Où |
|---|---|---|
| Dirigeant | Voir le portefeuille, signer les avis, arbitrer | Hyperviseur |
| Pilote | Encadrer un System, appliquer un changement de règle s’il est ouvert | Écran de pilotage du System |
| Concepteur | Construire et publier un System ou une application | Cockpit, création |
| Métier | Utiliser l’application, ouvrir les sources, approuver si demandé | Work, Studio |
| Conformité | Vérifier qui a fait quoi | Journal d’audit, accès |

Work et Cockpit ne sont pas deux thèmes visuels : on passe de l’un à
l’autre selon les **droits**, pas selon un bouton « mode ».

### 1.4 Ce qui s’allume ou s’éteint

Agentium n’a pas d’offre « Standard / PRO ». On ouvre des capacités par
espace de travail :

| Interrupteur (nom interne) | Effet visible |
|---|---|
| Applications métier | Work et applications publiées |
| Parcours d’adoption | Accueil métier, menu « Impact », guides, compagnon — **éteint par défaut**, pas encore validé auprès des utilisateurs |
| Grand livre v2 | Nouvelle lecture (mesuré / déclaré) ; sinon l’ancien bilan de valeur |
| Boucle de valeur | Sur **un** System choisi : simuler puis appliquer un changement |

### 1.5 Si vous venez de papAI

| On disait | On dit maintenant | À ne plus promettre |
|---|---|---|
| Suite, Workflow | System, rattaché à une capacité physique métier | « KPI de la Suite » |
| App Hyperviseur | Page Hyperviseur / Impact dans le Cockpit | « première App système » |
| Objectif en euros | Objectif opérationnel (5 indicateurs) + base de valeur **déclarée** | Le grand chiffre à l’écran = vérité financière |
| Directive à acquitter | Décision + approbation dans l’application +, si ouvert, changement de règle | Circuit d’acquittement papAI |
| Proposition / alerte / insight | Une décision (recommandation, revue, scénario de valeur) | Six formulaires distincts |
| Agent stratégique qui agit | Compagnon qui **lit** et explique | Envoyer une directive depuis le chat |
| Santé des AI Services | Santé **technique** des exécutions | « Vert » = succès métier |
| Pipeline de KPI à 4 étapes | Publier une application + exécuter + tracer | Créer une métrique technique depuis l’Hyperviseur |
| Banner PRO | Interrupteurs d’espace de travail | Édition payante |

---

## 2. Epic 1 — Lire le grand livre

### US-AHYP-100 : Voir ce que le portefeuille a rendu

**Statut : Partiel** · **P0**

En tant que dirigeant, je veux voir, sur la période choisie, ce qui a
vraiment tourné et sur quelle preuve, afin de juger l’impact **sans
prendre un trou pour un zéro**.

Critères d’acceptation :

- [ ] L’Hyperviseur montre les exécutions, les résultats, le coût et la
      valeur, chacun avec un état clair : disponible, non mesuré, non
      configuré, accès restreint, indisponible
- [ ] Une donnée manquante n’apparaît **pas** comme 0 € ou 0 h
- [ ] Ancienne vue : le grand chiffre « valeur nette » est annoncé comme
      un **modèle estimé** (valeur déclarée moins coût), pas un compte
      audité
- [ ] Nouvelle vue : légende *encre = mesuré · teal = déclaré* ; on
      comprend, on détaille, on décide
- [ ] On peut cliquer une ligne pour voir le System ou ses exécutions
- [ ] Un « ROI » n’apparaît pas si le coût est quasi nul

*Côté technique :* page Hyperviseur ; états de fait partagés ; v2 derrière
l’interrupteur Grand livre.

### US-AHYP-101 : Choisir la période

**Statut : Livré** · **P0**

En tant que dirigeant, je veux choisir 30 jours, 90 jours ou une période
équivalente, afin de comparer sans changer de sujet.

Critères d’acceptation :

- [ ] Le choix est visible en haut de l’Hyperviseur
- [ ] Tout l’écran se recalcule (chiffres, liste, décisions, graphiques)
- [ ] Nouvelle vue : Direction = 90 jours / heures ; Opérations = 30 jours
      / exécutions ; Conformité = 90 jours / exécutions

### US-AHYP-102 : Voir les bases de valeur

**Statut : Livré** · **P0**

En tant que dirigeant, je veux savoir quelles capacités ont une convention
de valeur signée, datée, versionnée, afin de séparer ce qui est **déclaré**
de ce qui n’existe qu’en nombre d’exécutions ou d’heures.

Critères d’acceptation :

- [ ] La liste des bases est visible, avec un statut : déclarée, mesurée,
      ou aucune
- [ ] Sans base : on reste en unité simple (exécutions, heures), pas
      d’euro inventé
- [ ] Une base déclarée n’est **pas** une économie prouvée

### US-AHYP-103 : Ne pas raconter la même histoire sur les deux vues

**Statut : Livré** · **P1**

En tant que pilote, je veux que l’ancienne et la nouvelle vue restent
honnêtes, afin de ne pas promettre un « résumé de boucle de valeur » là
où il n’est pas affiché.

Critères d’acceptation :

- [ ] Sans nouvelle vue : bilan + résumé portefeuille, avec la phrase
      *Une simulation n’est pas une mesure*
- [ ] Avec nouvelle vue : grand livre ; pas ce résumé-là

---

## 3. Epic 2 — Donner un cap (objectifs)

### US-AHYP-200 : Fixer un objectif opérationnel

**Statut : Livré** · **P0**

En tant que dirigeant ou responsable, je veux poser un objectif simple
sur un System (indicateur, cible, 1 à 90 jours, responsable, point de
comparaison), afin de donner un cap **sans parler d’euros économisés**.

Critères d’acceptation :

- [ ] Uniquement cinq indicateurs : volume d’exécutions terminées, durée
      moyenne, attentes humaines, taux de validation humaine, coût mesuré
- [ ] Seul un responsable habilité peut l’écrire
- [ ] L’écran le montre, et dit *Non mesuré* ou *Impact économique non
      attesté ici* quand c’est le cas
- [ ] Ce n’est **pas** un objectif financier, ni « heures / argent
      économisés »

### US-AHYP-201 : Voir si on tient l’objectif

**Statut : Partiel** · **P0**

En tant que dirigeant, je veux voir l’écart entre le réel et la cible,
afin de savoir si le System est dans les clous.

Critères d’acceptation :

- [ ] Réel vs cible, dans l’unité de l’indicateur
- [ ] « Zéro exécution mesuré » n’est pas la même chose que « on n’a pas
      la donnée »
- [ ] Pas de pastille « dans les temps » économique juste parce qu’un
      Run est terminé

### US-AHYP-202 : Modifier ou retirer l’objectif

**Statut : Livré** · **P1**

En tant que responsable, je veux changer la cible, les dates, ou retirer
l’objectif. Le journal garde la trace.

### US-AHYP-203 : Voir les Systems sans cap ni convention

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux voir les Systems qui n’ont ni objectif ni
base de valeur, afin de relancer les responsables plutôt que d’afficher
un portefeuille « à 0 € ».

---

## 4. Epic 3 — Décider (avis dans l’Hyperviseur)

### US-AHYP-300 : Voir ce qui attend une signature

**Statut : Livré** · **P0**

En tant que dirigeant, je veux la liste de ce qui est proposé et pas
encore tranché, afin de savoir où je dois me prononcer.

Critères d’acceptation :

- [ ] File filtrable : recommandations, revues, scénarios de valeur
- [ ] Chaque carte : titre, pourquoi, impact **estimé**, objet concerné,
      dates
- [ ] Si la file est vide : *le portefeuille n’attend pas de signature*

### US-AHYP-301 : Accepter ou refuser — un avis, pas un interrupteur

**Statut : Livré** · **P0**

En tant que dirigeant, je veux accepter ou refuser une proposition, afin
qu’un **avis** soit enregistré et traçable.

Critères d’acceptation :

- [ ] Accepté ou refusé, avec la personne et l’heure quand l’écran l’exige
- [ ] Un scénario de changement de règle **ne se tranche pas ici** : on
      va sur l’écran de pilotage du System
- [ ] L’écran **n’offre pas** « Appliquer à tout le portefeuille »
- [ ] Tenter d’appliquer depuis l’Hyperviseur est **refusé** (voulu)

Phrase à dire : *Valider ici enregistre un avis. Changer un System se
fait depuis son écran de pilotage.*

### US-AHYP-302 : Demander une analyse de recommandations

**Statut : Livré** · **P1**

En tant que dirigeant, je veux lancer une analyse et voir les
recommandations, afin de nourrir la file **sans les prendre pour des
chiffres mesurés**.

### US-AHYP-303 : Approuver dans l’application métier

**Statut : Livré** · **P0**

En tant que métier, je veux accepter ou refuser une demande
d’approbation dans l’application, afin que l’exécution attende un humain.

Critères d’acceptation :

- [ ] Le modèle **ne peut pas** cliquer à ma place
- [ ] Une demande trop vieille est refusée
- [ ] Une file de revues existe pour les contrôles qualité
- [ ] Le journal note qui a signé

---

## 5. Epic 4 — Appliquer un changement (un System à la fois)

### US-AHYP-400 : Changer une règle depuis le pilotage, pas depuis le grand livre

**Statut : Livré (essai limité)** · **P0**

En tant que pilote, je veux, sur **un** System : partir d’un résultat,
proposer, **simuler**, faire approuver, **appliquer**, puis **mesurer** —
afin de changer une règle de façon limitée et prouvée.

Critères d’acceptation :

- [ ] Ouvert seulement si l’interrupteur « boucle de valeur » est allumé
      **et** que ce System est choisi pour l’essai
- [ ] On le fait sur l’écran de pilotage du System, **pas** dans
      l’Hyperviseur
- [ ] Un seul type de changement pour l’instant (garde-fous de politique),
      et seulement si la sécurité l’autorise ; sinon : *non configuré*
- [ ] La référence de départ est une vraie exécution enregistrée par le
      serveur — pas un exemple, pas un chiffre saisi à la main
- [ ] *Une simulation n’est pas une mesure*
- [ ] On ne clôt que si une exécution **après** le changement a été
      observée

### US-AHYP-401 : Lire un résumé portefeuille sans crier victoire

**Statut : Livré (ancienne vue seulement)** · **P1**

En tant que dirigeant, je veux voir, sur l’ancienne vue, l’écart observé,
les risques et les scénarios, afin d’ouvrir le bon System — **pas** pour
dire « on a simulé, donc on a gagné ».

---

## 6. Epic 5 — Faire remonter le terrain

### US-AHYP-500 : Publier une application métier

**Statut : Livré** · **P0**

En tant que concepteur, je veux publier une application liée à une
version figée d’un System, afin que le métier travaille dans Work, sans
ouvrir le moteur.

Critères d’acceptation :

- [ ] Brouillon → version publiée (on ne la réécrit pas) → mise en service
      (pilote ou en service)
- [ ] Le métier entre par Work, pas par la fiche technique du System

### US-AHYP-501 : Laisser une preuve à chaque exécution

**Statut : Livré** · **P0**

En tant que métier ou concepteur, je veux qu’une exécution laisse une
trace (coût éventuel, sources, historique), afin que le grand livre ait
de quoi parler.

Critères d’acceptation :

- [ ] On peut ouvrir la trace depuis Work, le compagnon ou l’Hyperviseur
- [ ] *Terminé ≠ réponse validée ≠ argent gagné*
- [ ] Débit et latence restent dans un tiroir « santé technique »

### US-AHYP-502 : Déclarer une convention de valeur

**Statut : Livré** · **P1**

En tant que pilote, je veux déclarer « un résultat de ce type vaut X
heures ou Y € », avec mon nom, afin que le grand livre convertisse **sans
inventer une mesure**.

### US-AHYP-503 : Voir les Systems silencieux

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux que l’absence d’exécutions récentes
apparaisse comme un **trou**, pas comme une belle performance à zéro.

---

## 7. Epic 6 — Parler au portefeuille (compagnon)

### US-AHYP-600 : Poser une question en français (ou en anglais)

**Statut : Partiel** · **P1**

En tant que dirigeant ou métier, je veux interroger les Systems auxquels
j’ai droit, afin de comprendre sans cliquer partout — **avec les mêmes
droits qu’à l’écran**.

Critères d’acceptation :

- [ ] Le compagnon est là dans Work et dans le Cockpit
- [ ] Je choisis jusqu’à dix Systems ; si je n’en choisis aucun, on
      explore, on ne lance rien
- [ ] Il peut inspecter un System, comparer des exécutions, lire les
      indicateurs opérationnels
- [ ] Il s’appuie sur les mêmes règles que les boutons de l’écran
- [ ] Quand un System a tourné : sources et preuves visibles
- [ ] Des guides existent : démarrer, sources, Systems, exécutions, valeur

### US-AHYP-601 : Empêcher le modèle de signer

**Statut : Livré** · **P0**

En tant que conformité, je veux qu’aucun tour de conversation n’accepte
une approbation à la place d’un humain.

### US-AHYP-602 : Voir le périmètre avant de parler

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux voir *à quoi* le compagnon a accès
(Systems, espace, lecture seule ou non), afin de ne pas le prendre pour
un oracle. Envoyer une directive ou inventer une prévision depuis le
chat : **hors contrat**.

---

## 8. Epic 7 — Ce qui demande de l’attention

### US-AHYP-700 : Une file d’attention unique

**Statut : Partiel** · **P1**

En tant que dirigeant, je veux au même endroit : avis en attente,
objectifs hors délai, Systems sans convention, risques sur un changement
de règle — afin de réagir. Un voyant technique « en panne » n’est **pas**
un échec métier.

### US-AHYP-701 : Une tendance honnête

**Statut : Partiel** · **P2**

En tant que dirigeant, je veux voir l’évolution jour après jour. Une
projection « mois futur » ou un « et si on bougeait le levier » sur tout
le portefeuille **n’est pas livré**. Tant qu’on n’a pas de preuve, on ne
dessine pas de barre en pointillés.

### US-AHYP-702 : Exporter un dossier pour le COMEX

**Statut : Spécifié** · **P2**

En tant que dirigeant, je veux un export de la période (PDF ou tableur) :
registre, bases, décisions, et la mention mesuré / déclaré / absent.
**Pas encore fait.**

---

## 9. Epic 8 — Qui a le droit, et la trace

### US-AHYP-800 : Séparer voir, décider, appliquer

**Statut : Livré** · **P0**

En tant qu’administrateur, je veux des droits distincts : lire
l’Hyperviseur, accepter ou refuser, écrire un objectif, appliquer un
changement, publier une application. Le « mode » de l’espace (construire,
utiliser, piloter) change **la densité de l’écran**, pas les droits.

### US-AHYP-801 : Tout tracer

**Statut : Livré** · **P0**

En tant que conformité, je veux dans le journal : avis, approbations
humaines, écriture d’objectif, étapes d’un changement de règle. Chaque
ligne : qui, quoi, sur quoi, quand. (Les progrès d’un parcours d’aide :
métadonnées seulement, pas le contenu des questions.)

### US-AHYP-802 : Ne pas confondre avec Mission Room

**Statut : Livré** · **P0**

En tant que produit, je veux qu’une salle de briefing immersive
(démonstrations type gouvernement / ville) reste **une application
d’espace**, afin de ne pas la vendre comme le grand livre.

---

## 10. Epic 9 — Honnêteté et première prise en main

### US-AHYP-900 : Interdire le zéro inventé

**Statut : Livré** · **P0**

En tant que produit, je veux qu’aucun total financier de substitution
n’apparaisse dans l’habillage de l’écran. « Heures ou euros économisés »
n’est **pas** encore un chiffre que l’on peut défendre.

### US-AHYP-901 : Commencer par une tâche métier

**Statut : Livré (parcours éteint par défaut)** · **P1**

En tant que métier, je veux un premier résultat vérifiable (exemple
guidé, quatre étapes, seul, en dix minutes — **cible pas encore
mesurée**) sans ouvrir le Cockpit. Le parcours d’accueil n’est **pas**
allumé partout ; les tests utilisateurs n’ont **pas** encore eu lieu.

---

## 11. On ne promet pas

- Appliquer un changement depuis l’Hyperviseur
- Un levier « et si » en direct sur tout le portefeuille
- Les directives papAI (urgent / stratégique, relance, escalade)
- Créer une métrique technique depuis l’Hyperviseur
- Une édition Standard / PRO
- Un export COMEX (écrit, pas construit)
- Des économies d’heures ou d’euros attestées
- Un partage entre espaces de travail
- Mission Room = Hyperviseur

---

## 12. Récapitulatif

**P0** indispensable en séance COMEX · **P1** souhaitable · **P2** plus tard.

| ID | Epic | Titre | P | Statut |
|---|---|---|---|---|
| US-AHYP-100 | Grand livre | Voir ce que le portefeuille a rendu | P0 | Partiel |
| US-AHYP-101 | Grand livre | Choisir la période | P0 | Livré |
| US-AHYP-102 | Grand livre | Voir les bases de valeur | P0 | Livré |
| US-AHYP-103 | Grand livre | Deux vues, deux récits honnêtes | P1 | Livré |
| US-AHYP-200 | Objectifs | Fixer un objectif opérationnel | P0 | Livré |
| US-AHYP-201 | Objectifs | Voir si on tient l’objectif | P0 | Partiel |
| US-AHYP-202 | Objectifs | Modifier ou retirer | P1 | Livré |
| US-AHYP-203 | Objectifs | Systems sans cap ni convention | P1 | Partiel |
| US-AHYP-300 | Décisions | Voir ce qui attend une signature | P0 | Livré |
| US-AHYP-301 | Décisions | Accepter ou refuser (avis) | P0 | Livré |
| US-AHYP-302 | Décisions | Demander des recommandations | P1 | Livré |
| US-AHYP-303 | Décisions | Approuver dans l’application | P0 | Livré |
| US-AHYP-400 | Changement | Simuler puis mesurer sur un System | P0 | Livré (essai limité) |
| US-AHYP-401 | Changement | Lire le résumé sans crier victoire | P1 | Livré |
| US-AHYP-500 | Terrain | Publier une application | P0 | Livré |
| US-AHYP-501 | Terrain | Laisser une preuve d’exécution | P0 | Livré |
| US-AHYP-502 | Terrain | Déclarer une convention de valeur | P1 | Livré |
| US-AHYP-503 | Terrain | Voir les Systems silencieux | P1 | Partiel |
| US-AHYP-600 | Compagnon | Poser une question | P1 | Partiel |
| US-AHYP-601 | Compagnon | Le modèle ne signe pas | P0 | Livré |
| US-AHYP-602 | Compagnon | Voir le périmètre | P1 | Partiel |
| US-AHYP-700 | Attention | Une file d’attention | P1 | Partiel |
| US-AHYP-701 | Attention | Une tendance honnête | P2 | Partiel |
| US-AHYP-702 | Attention | Export dossier COMEX | P2 | Spécifié |
| US-AHYP-800 | Droits | Séparer voir / décider / appliquer | P0 | Livré |
| US-AHYP-801 | Droits | Tout tracer | P0 | Livré |
| US-AHYP-802 | Droits | Mission Room n’est pas le grand livre | P0 | Livré |
| US-AHYP-900 | Honnêteté | Pas de zéro inventé | P0 | Livré |
| US-AHYP-901 | Prise en main | Commencer par une tâche métier | P1 | Livré (éteint par défaut) |
