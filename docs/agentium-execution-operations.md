# Recette et exploitation du contrôle d'exécution

Cette procédure a été préparée depuis `demo/agentic`, `0b63fcec`, avec le plan
[O0–O7](agentium-execution-observability-plan.md). Elle conserve les contrôles de
release et de recette ; sa mise à jour ne réalise aucune opération sur la VM.
Les résultats locaux historiques sont consignés dans le
[rapport d'implémentation](agentium-execution-observability-implementation.md).

Le [plan Opérations, Activités et suivi du Flow](agentium-operations-activities-flow-plan.md)
ajoute une recette de conservation des écrans et de continuité des jobs. Ses
lots sont planifiés, pas livrés par cette mise à jour documentaire. Leur future
recette devra notamment vérifier Opérations et Activités séparément, ainsi que
le nuage de points, la matrice des preuves et leurs liens dans Qualité.

## État déclaré au 15 octobre 2026

Le [bilan de production](ops/execution-observability-production-2026-10-15.md)
rapporte `4a404d61` avec journal, supervision, admission, échéances, annulation
et réconciliation ouverts pour tous les workspaces. L'API d'activités est
accessible et vide avant de nouveaux travaux. La révision lue dans `build-info`,
la santé, la sauvegarde, les migrations, les options effectives et les services
de contrôle sont rapportés par l'opérateur, sans vérification VM indépendante
ici. Ces références de dépôt ne prouvent pas à elles seules les états de la VM.

L'activation globale remplace le périmètre initial Showcase pour cet état
déclaré ; les valeurs par défaut et exemples de canari ci-dessous restent des
réglages de préparation, pas un relevé des variables de production. Temporal
reste désactivé. La comparaison des moteurs et la certification du catalogue
restent ouvertes, et les activations DataOps/connecteurs sont inchangées.

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

Les trois options suivantes sont désactivées par défaut dans le code ; cet
exemple ne décrit pas l'activation globale rapportée en production :

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

**Limite de la révision déclarée en production (`4a404d61`) :** le script
`scripts/agentium-vm-deploy.sh` n'intègre pas cet overlay et sa commande `up`
ne recrée pas les services `agentium-worker-control` et
`agentium-scheduler-control`. Leur état actif rapporté ne garantit pas leur
prise en charge lors de la release suivante. Le correctif est préparé sur
`codex/control-worker-deploy`, sans déploiement à ce stade.

Avec ce correctif, `AGENTIUM_EXECUTION_CONTROL=auto` est le mode par défaut.
Il rend le backend avec l'environnement figé, puis sélectionne l'overlay et les
deux services si une des options `ACTIVITY_OBSERVABILITY_ENABLED`,
`EXECUTION_CONTROL_ENABLED`, `EXECUTION_DURABLE_DISPATCH_ENABLED` ou
`EXECUTION_TEMPORAL_ENABLED` est active, ou si un des conteneurs existe encore
(y compris arrêté). `images`, `ps`, `storage-check` et `up` utilisent cette
sélection. Fermer les options conserve donc la capacité nécessaire au drainage.

Le mode `1` prépare cette capacité avant l'ouverture des options. Le mode `0`
est refusé si une option l'exige ou si un des conteneurs existe. Son retrait
définitif demande de fermer les admissions, vérifier le drainage puis retirer
explicitement les conteneurs ; changer le mode ne les supprime pas.

Les deux services utilisent l'image worker du tag demandé et le même
`AGENTIUM_ENV_FILE` figé que le backend, sans volume d'artefacts ni AppRole
OpenBao supplémentaire. Les quatre options doivent être identiques dans les
trois services ; un override propre au backend qui les fait diverger bloque
le script avant toute mutation. Placer ces options dans l'environnement
applicatif commun du bundle figé.

Après `build-info`, `up` contrôle les identifiants d'image, les révisions,
les commandes et l'isolation de la file, vérifie le PID du scheduler puis
adresse un ping Celery au seul worker de contrôle. Un échec conserve la
maintenance fermée lorsqu'elle est activée (`AGENTIUM_GATE=1`). Ces contrôles
établissent la présence des processus attendus ; la recette d'un travail réel
et de son journal reste nécessaire.

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

## Recette d'exploitation déléguée

La recette initiale était limitée à Showcase ; la portée de production est
désormais globale selon le compte rendu. Les parcours doivent donc rester
isolés dans un workspace de recette avec leurs autorisations natives, sans
assimiler l'ouverture globale à leur validation. Cette session ne réalise
aucun contrôle VM. Un opérateur doit conserver les résultats suivants, liés
au SHA réellement testé :

| Preuve | Recette | Preuve de qualification VM disponible dans ce dossier |
|---|---|---|
| Migration et retour arrière compatible | Copie de la base déployée, upgrade, refus de downgrade destructeur | Sauvegarde et migrations de production rapportées ; recette de restauration/retour compatible non attestée |
| Images | Construction réelle et budgets via le script de release | Non attestée pour cette release par un relevé joint |
| Trois profils | Responsable System, administrateur workspace, administrateur plateforme | Non attestée ; API accessible et vide seulement rapportée |
| Reprise SSE | Couper/reprendre, révoquer un droit sur un flux ouvert | Non attestée |
| Calcul réel | Préparation, SQL, scoring avec modèle/schéma compatibles et entraînement autorisé | Nouveau parcours avec journal non attesté |
| Admission | Saturer le workspace de recette, observer attente puis reprise sans effet doublé | Non attestée |
| Contrôle | Annuler pendant calcul et publication, constater la fin native | Services actifs rapportés ; parcours non attesté |
| Résultat métier | Qualification, décision d'acceptation, reçu de livraison | Non attestée |
| Charge | Accusé durable p95, transition visible p95, CPU/RAM/cgroup/disque/journal | Non attestée |

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
