# Exécution et observabilité en production — bilan du 15 octobre 2026

L'opérateur rapporte la mise en production de `4a404d61`, avec journal,
supervision, admission, échéances, annulation et réconciliation ouverts pour
tous les workspaces. Ce bilan consigne son compte rendu ; aucune connexion à
la VM, lecture de `build-info`, vérification de santé ou opération de déploiement
n'a été effectuée dans cette session documentaire. Aucun nouveau bundle brut
de preuves VM n'est joint.

## Révisions et provenance des constats

| Objet | État au compte rendu | Origine du constat |
|---|---|---|
| Production | `4a404d61c8f80a9027d8ea9ababc9c30b112f8c0` | Rapport opérateur, avec vérification de `build-info` rapportée ; non relue sur la VM ici |
| `demo/agentic` et `develop` | `4a404d61` | Références Git de la livraison |
| `main` | `05809a8d` | Référence Git de la livraison |

Une référence Git vérifiée établit l'état du dépôt, pas celui des processus en
production. Les validations locales du
[rapport d'implémentation](../agentium-execution-observability-implementation.md)
restent attachées à leur code et à leurs conditions d'exécution historiques.
L'opérateur précise que l'observabilité a été fusionnée au-dessus des arbres
d'explication ML déjà présents sur `demo/agentic`, sans les écraser. Le correctif
d'exploitation décrit ci-dessous part de cette révision fusionnée.

## Fonctionnalités et contrôles rapportés

| Domaine | Observation de l'opérateur | Limite de la conclusion |
|---|---|---|
| Révision et santé | `build-info` confirme la révision ; accueil, health, disponibilité, Keycloak et LiveKit répondent 200 | Disponibilité rapportée au contrôle ; aucune nouvelle sonde VM ici |
| Sauvegarde et migrations | Migrations 133 et 134 effectuées après sauvegarde du plan de données | N'atteste pas une restauration exécutée ni un downgrade compatible avec les nouvelles écritures |
| Configuration et services de contrôle | Options d'exécution ouvertes ; worker et scheduler en service sur la file `control` | État rapporté, sans inspection locale de leurs environnements, images, files ou processus |
| Portée | Journal, supervision, admission, échéances, annulation et réconciliation ouverts pour tous les workspaces | Les droits natifs, quotas et contrôleurs des travaux restent applicables ; ce n'est pas une certification de chaque parcours |
| API d'activités | Accessible, liste vide avant de nouveaux travaux | Accessibilité de la lecture ; aucun cycle complet soumission, événement, annulation ou livraison ainsi démontré |
| Temporal | Désactivé | Le candidat natif local ne devient pas le moteur de production |

L'ouverture globale dépasse le canari Showcase de la recette initiale. Elle ne
fabrique pas l'historique des anciens travaux : un éventuel backfill conserve
sa sémantique d'instantané. Une liste d'activités vide ne signifie ni que le
journal a été testé sur un nouveau travail, ni qu'aucun travail historique
n'existe. La réussite technique, l'acceptation humaine et le reçu de livraison
restent des états distincts.

## Limite du script déployé et correctif préparé

À la révision `4a404d61`, `scripts/agentium-vm-deploy.sh` ne charge pas l'overlay
`docker/compose.agentium.execution.yml` et sa commande `up` ne sélectionne ni
`agentium-worker-control` ni `agentium-scheduler-control`. L'existence de cet
overlay et la déclaration de services actifs ne suffisent donc pas à garantir
que le chemin normal de déploiement les recréera avec le tag et l'environnement
de la prochaine release. Le contrôle de `build-info` du backend ne vérifie pas
à lui seul ces deux services.

Le raccordement est implémenté sur `codex/control-worker-deploy`, issue de
`4a404d61`. Le mode automatique sélectionne les deux services si les options
effectives le demandent ou si un des conteneurs existe encore, même arrêté.
Leurs options doivent correspondre à celles du backend. `up` les recrée avec
l'image worker de la release et vérifie image, révision, commandes, processus
du scheduler et réponse ciblée du worker avant de rouvrir la maintenance.
Les détails et les modes explicites figurent dans la
[recette d'exploitation](../agentium-execution-operations.md#capacité-de-contrôle-séparée).

**Ce correctif n'est pas déployé par le présent bilan.** Sa validation locale
est consignée dans le [relevé de tests](../evidence/control-worker-deploy-2026-10-15/validation.json).
Il ne faut pas arrêter le contrôle sans tenir compte des intentions, demandes
et réservations à drainer, ni démarrer un second scheduler pour le même périmètre.

## Qualification et suites encore ouvertes

- La comparaison Temporal/LangGraph/moteur existant à corpus identique n'a pas
  été réalisée. Les essais locaux de mécanismes ne constituent pas cette
  comparaison ; Temporal reste désactivé.
- La certification du catalogue de connecteurs reste ouverte. Son ouverture
  fonctionnelle ne rend aucun profil automatiquement Vérifié ou Certifié.
- Les états DataOps et connecteurs du compte rendu précédent sont conservés ;
  cette activation d'observabilité ne les modifie ni ne les requalifie. Voir le
  [bilan DataOps du 14 octobre](dataops-production-2026-10-14.md) et
  l'[état des connecteurs](../agentium-connectors-implementation.md).
- L'API vide ne ferme pas les recettes de nouveau travail réel, droits des trois
  profils, reprise SSE, admission sous charge, annulation effective, échéance,
  réconciliation et résultat métier. Les objectifs p95, consommations mesurées,
  budgets des images de cette release et reçu de livraison sur la VM restent
  à documenter par leurs preuves propres.

La [recette d'exploitation](../agentium-execution-operations.md) reste la
procédure de contrôle et de drainage. Aucun plan historique ni dossier de
preuves locales n'est réécrit pour transformer cette déclaration d'activation
en qualification complète.
