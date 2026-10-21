# Recette missions — 21 octobre 2026

Recette locale sur `feat/uiux-recette`, issue de `34244ab7`. PostgreSQL 16.2
jetable, accessible uniquement par socket Unix local, base
`test_mission_execution_recette`. Aucun accès ni changement aux données de
production ou Luma. Les schémas de test sont créés par les modèles ORM ; cette
recette ne valide pas l'application des migrations sur une base existante.

## Défauts reproduits et corrections

1. **Reprise concurrente avec une écriture du worker : deadlock PostgreSQL.**
   La reprise verrouillait `Task`, puis `TaskExecution`, alors que le checkpoint
   et la récupération procédaient dans l'ordre inverse. Deux tests utilisant
   des connexions indépendantes et des barrières sur les requêtes SQL
   reproduisent `psycopg2.errors.DeadlockDetected`. La reprise verrouille
   désormais la tentative avant son parent, comme les workers. Les refus de
   reprise d'une tentative encore active ou déjà terminée restent explicites.
2. **Nouvelle mission : erreur avant le premier appel au modèle.**
   Le processus Celery réel a révélé un `KeyError('"title"')` dans
   `PLAN_PROMPT.format(...)` : les accolades de l'exemple JSON n'étaient pas
   échappées. Elles sont désormais échappées et la nouvelle régression vérifie
   le prompt effectivement transmis au modèle, avec un objectif contenant
   lui-même des accolades.

Ces corrections n'ajoutent aucune migration ni modification de données.

## Preuves obtenues

| Vérification | Résultat | Preuve locale |
| --- | --- | --- |
| PostgreSQL avant correction, après correction de la fixture d'ID | 3 réussis, 2 deadlocks reproduits | `/tmp/hyusai-recette/mission-pg-before-2.log` |
| PostgreSQL après correction de l'ordre des verrous | **5 réussis**, 9,33 s | `/tmp/hyusai-recette/mission-pg-after.log` |
| Régression du prompt avant correction | 1 échec reproduit, `KeyError` | `/tmp/hyusai-recette/mission-plan-before.log` |
| Cycle de vie et planification, SQLite, après les deux corrections | **9 réussis**, 3,45 s | `/tmp/hyusai-recette/mission-sqlite-final.log` |
| Premier essai de processus Celery | Échec sur le prompt, corrigé ensuite | `/tmp/hyusai-recette/mission-celery.log` |
| Processus Celery après correction du prompt | **1 réussi**, 18,95 s | `/tmp/hyusai-recette/mission-celery-after.log` |
| Même scénario, première distribution par un vrai processus beat à 30 s | **1 réussi**, 39,69 s | `/tmp/hyusai-recette/mission-celery-beat.log` |

Les cinq cas PostgreSQL couvrent deux lancements simultanés (une tentative,
un conflit), deux livraisons simultanées (un seul worker acquiert le bail), deux
récupérations concurrentes (une seule invalidation), le refus d'une écriture
de l'ancien worker après reprise et la reprise chevauchant un checkpoint ou
une récupération. Les livrables et étapes confirmées sont vérifiés en base.

Les contrôles Ruff ciblés (`I,F401,E402,UP006`), le formatage des cinq fichiers
Python concernés et `git diff --check` passent.

## Processus Celery et limites

Le test `test_mission_execution_celery_process.py` lance de vrais processus
Celery `solo` avec un transport filesystem temporaire. Il conserve les tâches
de production, le dispatch, le moteur de mission, les baux, les checkpoints et
la reprise. Seules les réponses du modèle sont déterministes ; le bail est
ramené à deux secondes dans le worker de test.

La distribution initiale vient d'un vrai processus beat conservant uniquement
l'entrée de production `mission-recovery-30s`, sans modifier son intervalle de
30 secondes. Le journal montre son démarrage à 16:31:52,216 UTC et l'émission
de `agentium.recover_missions` à 16:32:22,233 UTC. Aucun appel manuel ne
déclenche cette première distribution. Aucun autre job périodique n'est activé.
Beat est arrêté dès que le worker atteint la seconde étape.

Le scénario interrompt ensuite le worker par `SIGKILL` après une première étape
confirmée, exécute la tâche de récupération, exige une reprise explicite, puis
vérifie qu'une nouvelle récupération rediffuse la demande et que les livraisons
dupliquées ne refont pas le travail. **Ce scénario passe.** Les journaux du
second worker montrent une exécution `finished`, puis deux livraisons refusées
avec `already_claimed`. Le journal des appels modèle contient exactement
`pause:plan`, `pause:evidence`, `pause:report`, `finish:report` : la première
étape confirmée et la planification ne sont pas répétées après reprise.
Les journaux des deux workers, du transport et des appels modèle sont conservés
dans `/tmp/hyusai-recette/mission-celery-process/test_worker_kill_preserves_che0`.

Ce périmètre valide la première échéance réelle à 30 secondes en environnement
isolé. Il ne valide pas RabbitMQ, sa redélivrance après perte de worker, la
topologie Celery/beat de production, les fournisseurs réels ou la concurrence
avec les autres services de production. Aucun résultat de ces validations
n'est revendiqué.

## Rejouer en environnement isolé

Utiliser une base PostgreSQL jetable dont le nom commence par `test_`, avec
`PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1` et `DATABASE_URL` pointant sur cette
base. Le fixture de pytest efface les tables qu'il utilise ; ne jamais pointer
ces commandes sur une base de production ou Luma.

```sh
cd backend
pytest -v app/tests/integration/test_mission_execution_postgresql.py
RUN_MISSION_CELERY_INTEGRATION=1 CELERY_BROKER_URL=filesystem:// \
  CELERY_RESULT_BACKEND=cache+memory:// \
  pytest -vs app/tests/integration/test_mission_execution_celery_process.py
pytest -q app/tests/services/test_mission_execution.py
```

Les processus Celery sont arrêtés dans le `finally` du test. Le cluster
PostgreSQL temporaire doit être arrêté à la fin de la recette locale.
