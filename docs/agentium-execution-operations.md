# Recette et exploitation du contrôle d'exécution

Ce document prépare une livraison ; il ne constate aucune modification de la
VM. Base de développement : `demo/agentic`, `0b63fcec`. Le plan de référence est
[O0–O7](agentium-execution-observability-plan.md). Les résultats locaux et les
portes encore ouvertes sont consignés dans le rapport d'implémentation.

## Préparation de la release

1. Figer le SHA candidat et vérifier les tests sur ce contenu. Sauvegarder la
   base et les objets selon le processus de release existant ; ne pas élargir
   le dump aux préfixes complets des workspaces.
2. Répéter les migrations 133 et 134 sur une copie PostgreSQL jetable issue du
   schéma déployé. Les tests locaux d'upgrade/downgrade de ces migrations ne
   prouvent pas que tout l'historique Alembic depuis une base vide fonctionne.
3. Construire les images ordinaires avec les options de release et mesurer
   `.Size` avec `agentium-image-budget.sh`. Les dépendances des runtimes
   expérimentaux restent dans leur image séparée. Aucun plafond des images
   existantes n'est relevé par ce chantier.
4. Vérifier les migrations avant de lancer les nouvelles images, même avec les
   options désactivées : les modèles ORM comprennent les nouvelles colonnes.

## Lecture et historique

Les trois options suivantes sont désactivées par défaut :

```dotenv
ACTIVITY_OBSERVABILITY_ENABLED=false
EXECUTION_CONTROL_ENABLED=false
EXECUTION_DURABLE_DISPATCH_ENABLED=false
EXECUTION_CANARY_WORKSPACES=showcase
```

La première active le journal et ses vues. Les suivantes contrôlent les
nouvelles soumissions/admissions du périmètre canari. La liste accepte des slugs
ou identifiants séparés par des virgules. `*` est une extension explicite à tous
les workspaces ; une liste vide n'en autorise aucun. L'admission déjà enregistrée
ne change pas de contrôleur quand cette configuration change.

Le backfill est paginé et peut reprendre après une interruption. Depuis
`backend`, dans l'environnement applicatif du candidat :

```sh
PYTHONPATH=. python scripts/execution_operations.py backfill run --limit 200
PYTHONPATH=. python scripts/execution_operations.py backfill run --limit 200 --after-id IDENTIFIANT_RETOURNE
```

Continuer avec le `next_id` retourné jusqu'à `null`. Répéter pour
`skill_invocation`, `recipe_execution`, `compute_run`, `ml_training`,
`workspace_job`, `service_window` et `delivery_receipt`. Chaque page est une
transaction ; la rejouer est sans effet supplémentaire. Les relevés historiques
portent `snapshot_only` et ne fabriquent pas une chronologie passée.

Les écritures métier ORM/Core produisent les transitions dans leur transaction.
Une modification SQL brut hors de l'application doit faire l'objet d'une
réconciliation explicite. Aucune capture CDC PostgreSQL n'est revendiquée.

## Capacité de contrôle séparée

Compose dispose de l'overlay `docker/compose.agentium.execution.yml`, profil
`execution-control`. Helm utilise `executionControl.enabled`. Ces composants
réutilisent l'image worker : un worker dédié à `control`, un scheduler distinct.
Le chart refuse d'activer les options sans cette capacité et interdit cette
file sur le worker général. Il n'y a aucun calcul DataOps dans ces processus.

Les valeurs initiales du chart (worker 512 Mio/1 CPU ; scheduler 256 Mio/0,5 CPU)
sont des bornes à qualifier sur la VM, pas une consommation mesurée. Les tâches
de contrôle sont courtes et ne doivent pas attendre la fin d'un calcul enfant.
Ne jamais démarrer deux schedulers pour le même contrôle.

Le pool `control` doit rester vivant pendant le drainage, y compris après la
fermeture des admissions. Fermer une option n'efface ni les soumissions durables
ni les demandes d'annulation déjà acceptées. En cas de panne RabbitMQ, les
intentions restent en base ; la reprise de publication réutilise leur identité.
La confirmation du broker ne prouve pas le succès du travail.

Avant d'ouvrir le canari, fixer les plafonds globaux et workspace d'exécution
en conservant de la capacité pour l'API, PostgreSQL, le broker et le contrôle.
L'admission compte les CPU/mémoires demandés ; elle ne transforme pas cette
allocation en CPU effectivement consommé. Les limites du workspace peuvent
réduire les plafonds opérateur. Les calculs interactifs gardent une réserve.
Les Runs du moteur historique utilisent leur file d'orchestration existante,
pas le quota de calcul de leurs enfants.

## Recette Showcase déléguée

La VM est le seul banc existant et n'est pas accessible depuis cet environnement.
Un opérateur doit conserver les résultats suivants, liés au SHA candidat :

| Preuve | Recette | Statut avant exécution sur la VM |
|---|---|---|
| Migration et retour arrière compatible | Copie de la base déployée, upgrade, refus de downgrade destructeur | NON EXÉCUTÉ |
| Images | Construction réelle et budgets via le script de release | NON EXÉCUTÉ |
| Trois profils | Responsable System, administrateur workspace, administrateur plateforme | NON EXÉCUTÉ |
| Reprise SSE | Couper/reprendre, révoquer un droit sur un flux ouvert | NON EXÉCUTÉ |
| Calcul réel | Préparation, SQL, scoring avec modèle/schéma compatibles et entraînement autorisé | NON EXÉCUTÉ |
| Admission | Saturer le canari, observer attente puis reprise sans effet doublé | NON EXÉCUTÉ |
| Contrôle | Annuler pendant calcul et publication, constater la fin native | NON EXÉCUTÉ |
| Résultat métier | Qualification, décision d'acceptation, reçu de livraison | NON EXÉCUTÉ |
| Charge | Accusé durable p95, transition visible p95, CPU/RAM/cgroup/disque/journal | NON EXÉCUTÉ |

Les pannes de broker, redémarrages forcés et destructions de workers se qualifient
sur des services/queues de recette isolés ; ne pas arrêter les services de
production pour jouer le corpus de pannes.

Le scénario navigateur `60-activity-observability-canary.spec.ts` est opt-in et
complète cette recette. Le scénario `59-activity-observability-mocked.spec.ts`
teste le navigateur avec des réponses contrôlées ; il ne certifie pas le broker,
PostgreSQL, l'IAM de la VM ou une annulation réelle.

## Perte de worker et réconciliation

```sh
PYTHONPATH=. python scripts/execution_operations.py status
```

Un bail expiré interdit une publication tardive. Si l'arrêt du processus n'est
pas établi, sa réservation reste retenue et son usage mesuré reste inconnu.
Le propriétaire qui confirme ensuite son arrêt peut solder cette réservation.
Sinon l'opérateur doit vérifier l'arrêt réel sur l'hôte et conserver une preuve
sans secret. L'outil suivant exige cette attestation explicite :

```sh
PYTHONPATH=. python scripts/execution_operations.py reconcile-stopped RESERVATION_UUID \
  --operator IDENTITE_OPERATEUR --evidence PREUVE_LOCALE \
  --confirm-process-stopped
```

L'outil garde l'identité de l'opérateur et l'empreinte de la preuve. Il ne rejoue
aucun effet, ne transforme pas un résultat perdu en réussite, et ne prétend pas
mesurer a posteriori le CPU. Une écriture externe au résultat inconnu reste
soumise à sa réconciliation métier propre.

## Fermeture du canari et suites

Fermer les nouvelles admissions, laisser le contrôle et les anciens workers
drainer leurs enregistrements, puis vérifier qu'il ne reste aucun propriétaire
actif sur la révision à retirer. Ne pas supprimer le journal, les intentions ou
les réservations pour faire disparaître une alerte. Un downgrade avec preuves
ou exécutions contrôlées est refusé. Ne pas revenir à `ad10dbc2` : des données
Delta ont déjà été créées en production selon le compte rendu fourni.

Temporal/LangGraph ne sont pas activés par cet overlay. Le remplacement du
runtime des Flows reste soumis au verdict de qualification ; aucun Run en vol
n'est transféré. Le candidat Temporal natif possède une
[image et un overlay séparés](agentium-temporal-native-handover.md) et son propre
flag d'admission, désactivé par défaut. Kubernetes éphémère, Spark,
Kafka, nouvel usage de Redis et narration gardent leur
[handover](agentium-execution-deferred-handover.md).
