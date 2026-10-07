# Hyperviseur Agentium — MVP COMEX

> Une page pour un COMEX ou une direction produit. On peut la lire
> **sans connaître Agentium**. Les détails et les critères sont dans
> [`agentium-hypervisor-user-stories.md`](./agentium-hypervisor-user-stories.md).
>
> Note de fond : [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md).
> EN : [`agentium-hypervisor-mvp-comex.en.md`](./agentium-hypervisor-mvp-comex.en.md).
> Word : [`agentium-hypervisor-mvp-comex.fr.docx`](./agentium-hypervisor-mvp-comex.fr.docx).

---

## Glossaire express

| Mot | Sens |
|---|---|
| **System** | Un système d’IA industrialisé (objectif, règles, exécution). |
| **Run** | Une exécution tracée. Terminé ≠ validé ≠ argent gagné. |
| **Hyperviseur / Impact** | Le **grand livre** du portefeuille : le passé, pas la salle d’opération. |
| **Décision** | Un avis humain (accepter / refuser). Cela n’applique pas le changement. |
| **Steer** | L’écran où l’on **applique** un changement sur **un** System, après simulation et approbation. |
| **Mesuré / déclaré / absent** | Trois qualités d’un chiffre. Absent **n’est pas** zéro. |

---

## Vision en une phrase

L’Hyperviseur est le **grand livre** des Systems d’IA de l’organisation :
un dirigeant voit ce qui a vraiment tourné et sur quelle preuve, le
métier utilise les applications publiées, chaque exécution laisse une
trace, un humain décide — donner un avis, approuver dans une application,
ou (si c’est ouvert) appliquer un changement de règle sur **un** System —
**sans chiffre inventé** et **sans laisser le modèle signer**.

---

## 1. Ce que le MVP montre aujourd’hui

Chez papAI, six briques étaient à construire *avant* l’Hyperviseur. Chez
Agentium elles existent déjà, sous d’autres noms. On ne les reconstruît
pas.

| papAI disait | Agentium montre | Ce que le COMEX emporte |
|---|---|---|
| Tableau KPI / ROI | Page Hyperviseur / Impact | Un registre honnête : mesuré, déclaré, absent — **pas** un ROI audité |
| Objectifs descendants | Objectif opérationnel sur un System | Cinq indicateurs simples, 1 à 90 jours — **pas** des euros économisés |
| Métriques remontantes | Applications + exécutions + conventions de valeur | Une preuve d’exécution, pas un formulaire « publier un KPI » |
| Assistant IA | Compagnon de conversation | Il **lit** et explique ; il n’envoie pas d’ordre |
| Catalogue / base documentaire | Connaissances + applications publiées | Sources citées depuis le travail |
| Socle App | Work (métier) + Cockpit (construire / suivre) | Deux espaces, selon les **droits** |
| Gouvernance | Droits d’accès + journal | Qui voit, qui donne un avis, qui applique |

**À montrer en séance** (recharger la page avant de parler) :

1. **Work** — une question, une source ouverte. *Le métier travaille.*
2. **Une exécution** — la preuve. *On suit : ce n’est pas le gain.*
3. **Hyperviseur / Impact** — la légende mesuré / déclaré, une décision en attente. *On observe, on donne un avis.*
4. **Pilotage d’un System** — seulement si la boucle de valeur est vraiment ouverte. Sinon, le dire.
5. **Aide valeur** — coût observé / valeur déclarée / impact attesté.

Stories P0 de la séance : US-AHYP-100, 101, 102, 200, 300, 301, 303, 400
(si ouvert), 500, 501, 601, 800, 801, 900.

---

## 2. Déjà là — pas un chantier préalable

| # | papAI | Déjà chez Agentium | Attention COMEX |
|---|---|---|---|
| 1 | Catalogue | Connaissances + publication d’application | Une mauvaise source reste une mauvaise source |
| 2 | Centre documentaire | Collections, citations dans le travail | La fraîcheur = ce qui a vraiment été ingéré |
| 3 | Socle App | Work et Cockpit | L’Hyperviseur n’est pas « la première application système » |
| 4 | Flux de KPI | Exécutions + objectif + convention de valeur + décision | C’est **toujours** la brique critique — et c’est le grand livre, pas une API à part |
| 5 | Agent RAG | Compagnon en lecture | Le modèle ne signe pas |
| 6 | Gouvernance | Droits, journal, contrôle d’exécution | Déjà obligatoire |

Ordre de **démonstration**, plus de construction :

```text
Droits et journal  →  System publié + application métier  →  exécutions
     →  Hyperviseur (grand livre + avis)
     →  (option) compagnon
     →  (option, essai limité) appliquer un changement sur un System
```

---

## 3. User stories MVP (table COMEX)

### A — Lire le grand livre

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| A1 (US-AHYP-100) | Dirigeant | Voir exécutions, coût, valeur, avec l’état de la preuve | Juger l’impact sans zéro inventé |
| A2 (US-AHYP-101) | Dirigeant | Choisir 30 jours / 90 jours | Comparer |
| A3 (US-AHYP-102) | Dirigeant | Voir les conventions de valeur | Séparer le déclaré de l’unité simple |
| A4 (US-AHYP-201) | Dirigeant | Voir l’écart à l’objectif | Repérer un System hors cadre |

### B — Donner un cap

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| B1 (US-AHYP-200) | Dirigeant | Fixer un objectif opérationnel borné | Donner un cap sans parler d’argent économisé |
| B2 (US-AHYP-202) | Responsable | Modifier ou retirer | Ajuster |
| B3 (US-AHYP-203) | Dirigeant | Voir les Systems sans objectif ni convention | Relancer, pas afficher 0 € |

### C — Faire remonter le terrain

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| C1 (US-AHYP-500) | Concepteur | Publier une application | Rendre le travail consommable |
| C2 (US-AHYP-501) | Métier | Produire une exécution citée | Remonter une preuve |
| C3 (US-AHYP-503) | Dirigeant | Voir le silence (pas d’exécutions) | Distinguer un trou d’un zéro mesuré |

### D — Décider

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| D1 (US-AHYP-300) | Dirigeant | Voir ce qui attend une signature | Prioriser |
| D2 (US-AHYP-301) | Dirigeant | Accepter / refuser (avis) | Tracer **sans** appliquer |
| D3 (US-AHYP-303) | Métier | Approuver dans l’application | Garder l’humain dans la boucle |
| D4 (US-AHYP-400) | Pilote | Simuler puis mesurer sur un System | Appliquer **si** l’essai est ouvert |

### E — Compagnon (périmètre MVP)

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| E1 (US-AHYP-600) | Dirigeant | Poser une question dans mon périmètre | Comprendre sans tout cliquer |
| E2 (US-AHYP-601) | Conformité | Que le modèle ne signe pas | Séparer la parole de la décision |
| E3 (US-AHYP-602) | Dirigeant | Voir le périmètre | Limiter fuite et sur-promesse |

### F — Droits et trace

| ID | En tant que… | Je veux… | Afin de… |
|---|---|---|---|
| F1 (US-AHYP-800) | Admin | Séparer voir / donner un avis / appliquer | Respecter les rôles |
| F2 (US-AHYP-801) | Admin | Tout tracer | Conformité |

---

## 4. Si quelque chose manque

| Si absent | Stories touchées | Gravité |
|---|---|---|
| Aucune exécution / aucune application | A1, C1, C2 — grand livre vide | Maximale — même risque qu’un Hyperviseur « coquille » |
| Pas de convention de valeur | A1 en euros, A3 | Haute — rester en unité simple (exécutions, heures) |
| Pas de droits / pas de journal | D2, D3, F1, F2 | Fondation |
| Boucle de valeur éteinte | D4 | Normal : dire « non ouvert », ne pas improviser « Appliquer » |
| Compagnon éteint | E1 | L’écran Hyperviseur reste utilisable |
| Parcours d’accueil éteint | Entrée métier par défaut | Le chemin Work existe ; ce n’est pas l’accueil de tous |

---

## 5. Risques à nommer en séance

| Risque | Impact | Ce qu’on dit / ce qu’on fait |
|---|---|---|
| Raconter la « valeur nette » comme un P&L | Décision COMEX sur une estimation | *Modèle estimé, pas un compte audité* |
| Fuite via le compagnon | Il voit trop | Même périmètre que l’écran ; lecture seule ; il ne signe pas |
| « Appliquer » depuis le grand livre | Fausse industrialisation | Refusé volontairement ; on passe par le pilotage d’un System |
| « L’adoption est validée » | Sur-promesse | Le parcours existe, il est éteint par défaut, les tests utilisateurs n’ont pas eu lieu |
| Confondre avec Mission Room | On vend une démo immersive pour le grand livre | Autre contrat, même famille d’URL |
| « Et si » / projection | Une simulation vendue comme une mesure | Non livré sur le portefeuille ; *une simulation n’est pas une mesure* |

---

## 6. Ce que le MVP ne fait pas

- Appliquer un changement depuis l’Hyperviseur
- Un levier « et si » en direct sur tout le portefeuille
- Les directives papAI (types, relance, escalade)
- Créer une métrique technique depuis l’Hyperviseur
- Une édition Standard / PRO
- Un export PDF / tableur COMEX (écrit, pas construit)
- Des heures ou euros économisés attestés
- Un partage entre espaces de travail
- Mission Room comme preuve du portefeuille
