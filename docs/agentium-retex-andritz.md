# Retex ANDRITZ — ce que le premier grand client a appris à la plateforme

- **Date** : 2026-09-23
- **Pour qui** : ingénieurs qui travaillent sur la récupération, l'indexation ou le multi-locataire sans avoir vécu le projet ANDRITZ
- **Voir aussi** : [ADR 0002 — nomenclature projet par client](adr/0002-nomenclature-projet-par-client.md)

---

## Pourquoi cette page

ANDRITZ a façonné une grande partie du code de récupération, et une partie de
ce code a longtemps agi pour tous les locataires. Le client est aujourd'hui peu
actif, mais son workspace, ses index, ses applications et ses systèmes doivent
rester pérennes.

La règle de cette page : **on garde les problèmes découverts, pas les
solutions codées pour un client**. Les expressions régulières, les listes de
vocabulaire et les seuils ANDRITZ restent dans le code, derrière le stamp de
famille. Ce qui voyage vers le client suivant, c'est ce qu'on a compris en les
écrivant.

---

## Ce que le corpus a enseigné

### La contamination inter-projets est un vrai mode de panne

Sur un corpus organisé par affaire, la pire réponse n'est pas l'absence de
réponse : c'est une réponse correcte sur le mauvais projet. Un utilisateur qui
interroge le projet A et reçoit un extrait du projet B ne s'en aperçoit pas.

Ce qu'on en retient pour tout client organisé par affaire :

- le cloisonnement doit être **dur**, par filtre sur le moteur vectoriel, pas
  seulement par bonus de classement ;
- mais un filtre dur sur un identifiant que la base ne contient pas vide le
  résultat. Le planificateur n'émet donc un filtre que pour des codes
  **effectivement indexés** parmi les lignes retenues ;
- le rejet des sources d'un autre projet a un mode ombre qui trace sans
  bloquer. Un nouveau client doit commencer par là.

La capacité est générique (`reject_cross_project_sources`). La façon de
reconnaître un identifiant de projet ne l'est pas.

### La prose fabrique des identifiants

Une grammaire d'identifiants appliquée au texte libre trouve des codes là où il
n'y en a pas. L'incident fondateur : « à remplacer tous les 16 000 heures » a
produit le code projet inventé `LES16`, qui a ensuite empoisonné le tour de
conversation suivant par la mémoire conversationnelle.

Pour toute grammaire d'identifiants future :

- des **gardes négatives** sur les tournures de la langue, pas seulement des
  motifs positifs ;
- un rejet explicite des **unités de mesure** qui suivent un nombre : rpm, mm,
  kg, bar, V, heures, °C ;
- un nombre nu n'est un identifiant que si le contexte le dit, par un verbe
  comme « résume » ou « compare », ou par une appartenance exacte à un
  référentiel connu ;
- un faux identifiant coûte plus cher qu'un identifiant manqué, parce qu'il
  entre dans la mémoire du tour suivant.

### Comparer par sous-chaîne est un piège

La détection de « question sur le workspace » comparait des termes par
sous-chaîne. Des codes de série de trois lettres se déclenchaient donc à
l'intérieur de mots ordinaires, « ara » dans « caractère », « ava » dans
« avancement », pour tous les locataires, et faisaient basculer la réponse en
mode strict.

Toute liste de vocabulaire qui décide d'un comportement doit être comparée **par
mot**, ou rester propre au locataire qui l'a écrite.

### Un vocabulaire n'a qu'un producteur

La famille documentaire (liste de pièces détachées, manuel d'exploitation,
procédure de maintenance…) influence le classement. Mais trois vocabulaires
s'étaient accumulés chez les consommateurs, et plusieurs valeurs sur lesquelles
le code aiguillait n'avaient **jamais** été produites, ni dans le code actuel ni
dans l'historique. Elles donnaient l'illusion d'un réglage.

La règle retenue : le producteur fait foi, un consommateur n'aiguille que sur
des valeurs effectivement émises, et une valeur sans producteur est supprimée,
pas généralisée.

### Personne n'a mesuré ce que valent ces métadonnées

Il n'existe aucune ablation. Le lot de référence ANDRITZ est un contrat de
non-régression, pas une mesure avec et sans. On ne sait donc pas combien la
référence projet ou la famille documentaire rapportent en qualité de
récupération.

À faire avant d'écrire le moindre pack de règles pour un second client : une
ablation sur un corpus vivant. Elle ne peut pas tourner sans infrastructure,
parce que le lot de référence évalue un contexte déjà constitué et n'appelle
pas la récupération.

### Un gros corpus change les seuils

Sur la collection des notices, environ 99 000 sources et 1,49 million de
fragments, le planificateur profond chargeait tout le registre pour inférer la
portée. Ce balayage prenait de 55 à 120 secondes, alors que la récupération
vectorielle elle-même tenait sous la seconde, et les requêtes larges
expiraient avec zéro passage.

La leçon est générique : **au-delà d'une taille de registre, le planificateur
ne doit plus balayer, il doit cibler**. Le sondage de taille ne lit que les
colonnes indexées.

### Les inventaires exhaustifs ont besoin d'un plancher de rappel

Une question du type « quels projets utilisent telle pompe » demande
l'exhaustivité, pas les cinq meilleurs extraits. Le moteur ajoute une passe de
rappel dédiée aux listes de pièces détachées pour ne pas en manquer.

Le besoin est générique ; l'implémentation actuelle est nommée d'après une
famille ANDRITZ et s'exécute encore pour tous les locataires, sans effet utile
hors de ce corpus. C'est un résidu connu.

---

## Ce que la plateforme a enseigné

### Le slug ne porte jamais de sens

Un slug est modifiable et arbitraire. Seul le stamp `settings.family` décide
qu'un workspace est ANDRITZ. Déduire une spécialisation d'un nom, c'est
exactement ce qui avait fait fuir le client dans tout le code. La doctrine est
écrite dans `backend/app/services/workspace_features.py`.

### Un classifieur doit respecter la politique qu'on lui passe

Le classifieur d'intention renvoyait un profil industriel quelle que soit la
politique fournie. Un workspace neutre, correctement amorcé avec la politique
neutre, partait donc quand même en inventaire exhaustif et en récupération
profonde. Passer une politique à une fonction qui l'ignore ne neutralise rien.
Le test à garder en tête : *la sortie est-elle un profil que la politique
offre ?*

### Une variable de contexte ne traverse pas n'importe quoi

Le schéma de nomenclature est porté par une variable de contexte liée à chaque
point d'entrée. Trois comportements de plateforme ont été vérifiés :

| Situation | Liaison visible en aval |
| --- | --- |
| Dépendance FastAPI **synchrone** à `yield` | non : posée et libérée dans deux threads différents |
| Dépendance FastAPI **asynchrone** à `yield` | oui |
| Générateur de réponse en streaming, FastAPI 0.135 | oui |
| Tâche Celery | non : il faut relier dans la tâche |

Là où le workspace est déjà sous la main, un **argument explicite** vaut mieux
qu'une variable de contexte : il ne peut pas se perdre en route.

### Un défaut fermé doit être observable

Sans schéma lié, la grammaire ANDRITZ se désactive, ce qui protège les autres
locataires. Mais un oubli de liaison sur le workspace ANDRITZ éteignait alors
silencieusement son cloisonnement, sans erreur. On avait déplacé la panne d'un
tiers bruyant vers le client principal, discret.

D'où deux outils :

- un **compteur d'appels sans liaison**, qui distingue « ce locataire n'est pas
  ANDRITZ » de « personne n'a lié de schéma ici ». Il a immédiatement servi : il
  a séparé en une exécution des fixtures non estampillées de vrais points
  d'entrée manquants ;
- l'**audit** `backend/scripts/audit_project_scheme_stamps.py`, qui compare par
  workspace les codes projet déjà présents dans le registre et la capacité du
  locataire à en produire. À lancer après toute restauration.

### Une sélection de tests ciblée ment par omission

Le verrou de la grammaire a été validé par une sélection de 169 tests. Trois
séries de tests qu'elle ne couvrait pas étaient cassées : deux sont apparues en
lançant des suites voisines, la dernière seulement en comparant la suite
complète à la base. Le compteur n'en a découvert aucune, il en a donné la cause
à chaque fois. Pour tout changement qui touche un comportement transverse,
**comparer la suite complète contre la base**, pas seulement une sélection.

### Les données d'un client n'ont rien à faire dans le code

Deux noms de personnes réelles figuraient comme libellés dans un gabarit de
rapport. Un nom se périme le jour où la personne change de poste, et il n'a
rien à faire dans un dépôt de code source. Il reste dans un commit
d'historique ; le retirer demanderait de réécrire des branches partagées.

---

## Ce qui reste propre à ANDRITZ, et doit rester intact

Rien de ceci ne doit être généralisé, et rien ne doit être supprimé tant que le
workspace existe :

- la grammaire d'identifiants SPL et Needlepunch, et la série machine ;
- les facettes de familles documentaires par défaut ;
- le vocabulaire de grounding du client ;
- la politique de réponse industrielle, que la famille `andritz` reçoit parce
  qu'elle fait partie des familles industrielles ;
- les packs d'actions, le déploiement agentique et le système de rapports
  d'intervention, déjà gardés par la famille.

Un second client industriel reçoit son **propre** pack de règles derrière une
garde par famille. Le seuil auquel on repasse à un schéma déclaratif est fixé
par l'ADR 0002 : au troisième pack écrit à la main.
