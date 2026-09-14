---
marp: true
theme: default
paginate: true
class: lead
title: "Agentium — Décision, Hyperviseur et adoption"
author: "Équipe Agentium"
description: "Comment Agentium industrialise l’IA pour observer, consommer, monitorer et décider"
---

# Agentium

**Décision, Hyperviseur et adoption**

Comment la plateforme aide un COMEX et un métier à **observer**, **consommer**, **monitorer** et **décider** — sans inventer un zéro.

<br>

*Branche `demo/agentic` · `agentium.papai.ai`*
*Note de fond : [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md)*

---

## Le problème que le COMEX connaît

Les PoC IA s’accumulent.

- Un prompt, une démo, **pas d’objectif métier** industrialisé.
- Personne ne peut dire **quel commit / quel System** a produit la réponse.
- « On a économisé » sans **baseline**, sans unité, sans responsable.
- Soit l’humain est hors boucle, soit il est noyé dans le jargon moteur.

> On ne manque pas de modèles. On manque d’un **système de management** de l’IA.

---

## Ce qu’Agentium est

Un **système d’exploitation pour Systems intelligents**.

Pas un agent builder.

Une équipe crée, orchestre, **consomme**, pilote et industrialise des Systems alignés sur des **capacités métier**.

Une **application** et une **conversation** sont deux interfaces première classe.
Même contrats. Mêmes droits. Mêmes preuves. **Le modèle ne signe pas.**

---

## La chaîne — une seule

```text
System → Run → Evaluation → Decision → Action
```

| Mot | Dire ça |
|---|---|
| **System** | L’intention industrialisée |
| **Run** | L’exécution prouvée |
| **Decision** | Ce qui attend une signature |
| **Work** | Là où le métier consomme |
| **Cockpit** | Là où l’on construit, suit, améliore, impacte, administre |
| **Studio** | La surface humaine d’une application publiée |
| **Hyperviseur / Impact** | Le grand livre du portefeuille |

Ne pas dire : Desk, Board, workflow, pipeline, job, HITL.

---

## Quatre verbes, quatre contrats

| | Question | Où |
|---|---|---|
| **Observer** | Qu’a rendu le portefeuille, sur quelle preuve ? | `/hypervisor` |
| **Consommer** | Quelle tâche dois-je finir ? | `/work` · Studio |
| **Monitorer** | Qu’est-ce qui tourne, attend, dérive ? | `/runs` · file de revue · Diagnostics |
| **Décider** | Qu’est-ce qui attend une signature — et où ça s’applique ? | Feed Impact · gates Work · **Steer** |

Mélanger les quatre est la principale erreur de démo.

---

## Industrialiser = cinq disciplines

1. **Alignement** — un System sert une Capability, pas un prompt orphelin.
2. **Publication** — le métier consomme une Experience **versionnée**.
3. **Preuve** — chaque réponse a un Run (coût, contexte, lignée).
4. **Gouvernance** — politiques, IAM, audit. Jamais « prompt only ».
5. **Allocation** — on finance, on resserre, on arrête **sur preuve**.

```text
Construire → Exécuter → Mesurer → Optimiser → Allouer
```

*L’adoption commence par l’exécution. Le passage à l’échelle exige l’économie.*

---

## L’Hyperviseur en une phrase

**Le grand livre du portefeuille IA.**

Ce qui a été exécuté. Ce que cela a coûté. Ce qui est **déclaré** comme valeur.
Ce qui **manque**. Ce qui **attend une signature**.

Route : `/hypervisor`
Rail adoption : **Impact** — le nom n’établit pas l’outcome.

---

## Deux lectures, un même objet Decision

| v1 Bilan de valeur | v2 Grand Livre (`hypervisor_v2`) |
|---|---|
| Valeur nette estimée, ROI, SCAN | *Ce que le portefeuille a rendu* |
| + agrégat de boucle de valeur | Comprendre → Détailler → Décider |
| | Direction · Operations · Conformité |

Les deux : **Accepter / Rejeter = signal**.
Aucun des deux : **Appliquer une policy**.

> *« Valider ici enregistre une décision. Modifier un System passe par Steer. »*

---

## Légende à laisser à l’écran

**encre = mesuré · teal = déclaré**

Une donnée absente **n’est pas un zéro**.

Une base de valeur est **signée, datée, versionnée**.
Sans base : unité native (runs, heures), pas un euro fabriqué.

Un Run terminé ≠ une réponse validée ≠ un gain économique.

Diagnostics (débit, latence) = santé technique.
Ils ne remplacent **jamais** l’objectif métier.

---

## Où la décision devient une action

```text
Portefeuille                 System                      Application
/hypervisor                  Steer                       Studio
accept / reject              Simuler → Approuver         gate humain
signal                       → Agir → Mesurer            approbation
                             enactment borné             requise
```

Premier actionneur : un patch de *guardrails*, si le System le déclare
et si la Membrane l’autorise. Sinon : **non configuré**.

**Une simulation n’est pas une mesure.**

---

## Ce qu’on ne promet pas

- L’Hyperviseur n’applique pas tout seul une policy.
- Le what-if portefeuille / leviers live est **retiré**.
- Mission Room (`/hypervisor/mission-room`) est une **app de workspace**, pas le grand livre.
- Le tableau de conformité du dépôt n’est pas une attestation client.
- « Heures ou euros économisés » sans baseline Lot 8 = trou d’acceptation (O5).

---

## Courbe d’apprentissage

```text
1. Finir une tâche              Work / Studio
2. Relier le résultat à un Run  Citation · /runs · compagnon
3. Relier le Run à une décision Impact · gates · Steer
```

Trois couches — ne pas les confondre :

| Couche | Change |
|---|---|
| **IAM** | Ce que je *peux* |
| **Mode workspace** | Densité de l’écran (`builder` / `operator` / `executive`) |
| **Préférence membre** | Ton des guides — pas les droits |

---

## C-level — 15 minutes

1. Une application **Work** — voir que le métier a une porte.
2. **Impact** — lire la légende, pas le plus grand chiffre.
3. Une **décision** en attente — *ce qui attend une signature*.
4. **`/help/value`** — coût observé / valeur déclarée / impact attesté.

**Semaine 1 :** revue 30j/90j, couverture des bases, file de décisions, un passage audit.

Ne pas attendre un total « € économisés » sur le chrome.

---

## Métier — 15 minutes

1. `/work` — chercher l’application, pas le System.
2. Poser la question métier. **Ouvrir la citation.**
3. (Optionnel) NorthForge : `/work/getting-started` — quatre étapes, exemple fictif.
4. Si un gate apparaît : **Accepter / Refuser** — pas le modèle.

*Terminé ≠ réponse validée.*

Cible d’acceptation (pas encore mesurée) : **seul, en dix minutes**, un résultat vérifiable.

---

## Décideur — 15 minutes

1. Un gate **Studio** ou la file de revue — lire avant de signer.
2. Le feed **Impact** — signal, pas enactment.
3. Si — et seulement si — la boucle de valeur est active sur **ce** System :
   **Simuler → Approuver → Agir → Mesurer**.

Le modèle ne peut pas accepter un gate.
Une décision périmée est refusée.

---

## Capacité d’adoption — état

| | |
|---|---|
| Chemin métier Work + guides FR/EN | **Livré**, flag `adoption_experience_v1` **off** |
| Compagnon de conversation | **Livré** — ne signe pas |
| Objectifs opérationnels (5 métriques) | **Livré** — ce n’est pas un ROI |
| NorthForge 4 étapes | **Livré** sur Showcase |
| 10 sessions d’utilisabilité | **Non tenues** |
| Flag par défaut / retrait | **Non signé** |

Dire : *le chemin existe ; ce n’est pas encore le défaut ; nous n’avons pas encore la feuille d’acceptation.*

---

## Personas de récit (pas des comptes)

| | Entre par | Job |
|---|---|---|
| **Sarah** CAIO | Impact | Allouer |
| **Claire** métier | Work | Consommer |
| **Mehdi** steward | Steer | Encadrer |
| **Alex** builder | Créer | Composer |
| **Nadia** gouvernance | Audit | Contrôler |

Claire ne vit pas dans le Cockpit.
Sarah ne « clique pas Appliquer » sur le portefeuille.

---

## Démo — cinq temps

Hard-reload avant de parler.

1. **Work** — une question, une citation. *Consommer.*
2. **Run** — la preuve. *Monitorer.*
3. **Impact** — légende + une signature en attente. *Observer / décider.*
4. **Steer** — seulement si le flag valeur est vraiment on. Sinon, le dire.
5. **`/help/value`** — refermer sur l’honnêteté.

NAWA PR→PO : playbook opérateur, pas l’improvisation UI.

---

## Phrase de clôture

Agentium ne vend pas un copilote de plus.

Il donne à l’entreprise un **portefeuille de Systems** :
consommable par le métier, **observable** sans zéro inventé,
**monitoré** sans confondre santé technique et succès,
**décidé** par un humain — et industrialisé sous preuve.

---

## Pour aller plus loin

- Note : [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md)
- Lexique : [`agentium-reference.md`](./agentium-reference.md)
- Adoption (contrat) : [`agentium-adoption-roadmap.md`](./agentium-adoption-roadmap.md)
- Boucle de valeur : [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md)
- Grammaire Hyperviseur v2 : [`hypervisor-v2-chart-grammar.md`](./hypervisor-v2-chart-grammar.md)
