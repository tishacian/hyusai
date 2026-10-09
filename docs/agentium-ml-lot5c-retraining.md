# Lot 5c — Surveillance planifiée et réentraînement approuvé

Une version tabulaire peut être surveillée toutes les heures, toutes les six
heures ou chaque jour, en UTC. La surveillance est désactivée par défaut.
Un administrateur du workspace peut également autoriser la création de
propositions de réentraînement. Cette option ne vaut jamais approbation d'un
entraînement ni promotion du modèle obtenu.

## Parcours

`POST /ml-models/{id}/monitoring/policy` accepte exclusivement :

```json
{"enabled": true, "propose_retraining": true, "interval_minutes": 60}
```

La configuration d'une version est conservée dans
`params_json.mlops.monitoring`. Elle crée un System dédié et son RunSchedule,
avec publication canonique du Flow lorsque celle-ci est active. Le cron existant
exécute la chaîne suivante :

1. `source.schedule` déclenche le Run.
2. `ml_monitor_model_v1` mesure la fenêtre de cette version et garde un snapshot.
3. Une branche conduit à la sortie si aucune proposition n'est nécessaire.
4. Sinon, un gate HITL `approve_model_retraining` présente la proposition.
5. Après approbation humaine, `ml_retrain_model_v1` crée un challenger et attend
   son entraînement dans le worker tabulaire.

Le gate expire après deux jours et rejette la proposition. Il utilise les
routes et droits HITL existants. Aucun second bouton d'approbation ni décision
Hypervisor générique ne confère le droit d'entraîner.

## Conditions et données

La proposition requiert un badge `alert`, un modèle explicitement champion et
au moins `max(40, ML_TRAIN_MIN_ROWS)` appels étiquetés admissibles parmi les
400 derniers appels de cette version. Chaque appel contribue uniquement sa
première ligne, celle à laquelle correspond le feedback. Les autres lignes
et les observations sans vérité terrain ne deviennent jamais des labels.
Les entrées sont celles du contrat de service effectif ; une colonne constante
retirée au fit initial ne bloque pas la collecte.

Le service produit un nouveau dataset de feedback, conserve les identifiants
des prédictions et fige son identité, sa version et le SHA-256 de ses octets
Parquet. La proposition contient les mesures de dérive qui l'ont déclenchée,
les paramètres, les options de famille, la cible et les variables.
Le coût d'inférence déclaré pour une distillation n'est pas reporté sur cet
entraînement de feedback. Les autres réglages sont repris depuis `spec_json`.
Le nouveau modèle conserve la lignée et reçoit une nouvelle version.

Une même fenêtre ne produit qu'une proposition ; une proposition active
bloque les suivantes pour ce modèle. Le contrôle du dataset et des paramètres
est répété après l'approbation et avant le fit. Une modification du Flow,
des données, du champion, de la politique ou des droits de son auteur invalide
l'autorisation. Une nouvelle décision forgée ne peut pas remplacer celle que
le serveur a liée à la proposition.

## Exécution et reprise

Les jobs `ml_monitoring` et `ml_retraining` sont réservés au serveur. Les routes
génériques de création et de transition de jobs les refusent.
Le modèle en attente et son lien à la proposition sont enregistrés dans une
transaction avant toute publication au broker. Une tâche de récupération
passe chaque minute. Un bail de publication de 60 secondes et un identifiant
de tâche déterministe permettent de reprendre une publication dont
l’acquittement a été perdu. Une prise en charge atomique distincte autorise
un seul fit : les livraisons en double restent sans effet. Après perte du
worker, le modèle est déclaré en échec à la limite d’entraînement plus
120 secondes ; le fit ne redémarre pas automatiquement. Les propositions
abandonnées sont clôturées, et l’annulation d’un Run interrompt son fit.
Les limites ordinaires de temps, mémoire et annulation du
worker ML s'appliquent.

La suppression d’un modèle désactive les planifications de son Flow de
surveillance dans la même transaction, avec verrouillage et rechargement
du modèle pour couvrir une activation concurrente. Le Flow, les exécutions
et les propositions restent disponibles pour l’historique.

Le modèle entraîné reste challenger, même si l'ancien champion disparaît.
Une promotion explicite et indépendante est nécessaire pour qu'il devienne
le modèle servi par défaut.

## Lecture et interface

`GET /ml-models/{id}/monitoring` ajoute `scheduled` : politique, droit de
configuration, historique et propositions avec leurs liens Run, dataset et
modèle. Les 100 dernières fenêtres distinctes sont conservées ; l'interface
reçoit au plus 20 snapshots et 20 propositions parmi les 40 derniers jobs.
Chaque proposition garde sa propre preuve de dérive après purge du snapshot.
Le lien de proposition ouvre la fiche d’exécution, qui présente le contexte
figé et les boutons HITL canoniques. Le champ `hitl.can_decide` est calculé
par le plan d’autorisation du serveur ; un lecteur voit le contexte sans
bouton de décision. Le POST revalide toujours les droits et la décision visée.
Les checkpoints de surveillance alimentent les signaux de l’Hypervisor avec
le nom du modèle, sa version et le niveau d'alerte.

Les métriques et rapports MLflow/skore existants du nouveau modèle restent
consultables depuis sa fiche. Aucune latence n'est convertie en coût monétaire.

## Livraison

- Fusionner dans l'ordre 5a, 5b, 5c.
- Aucune migration et aucune nouvelle dépendance.
- Reconstruire frontend, backend et worker ; redémarrer le beat.
- Exécuter le contrôle puis la réconciliation du catalogue pour publier
  `ml_monitor_model_v1` et `ml_retrain_model_v1` avant d'activer une politique.
- Le beat existant `agentium.scheduler_tick` déclenche les schedules ;
  `agentium.ml_retraining_recovery` reprend les intentions d'entraînement.
- La synchronisation et le déploiement se font depuis le dépôt Bitbucket.

## Qualification

Les tests couvrent le cron et le Flow publié, l'approbation par l'API HITL,
un fit MLflow réel, le refus et l'approbation automatique, la déduplication,
la conservation des options, les colonnes retirées au fit, le contrôle des
preuves et des droits, la séparation du champion et la protection des jobs.
- 234 tests backend combinés passent : entraînement ML, monitoring statistique,
  shadow, Flow de revue des labels, HITL et imports API.
- 13 scénarios dédiés vérifient les baux, livraisons concurrentes, annulation,
  perte de worker et absence de famine dans la récupération.
- Les derniers contrôles d’autorité couvrent aussi la modification réelle du
  Parquet et la disparition de ses octets ; aucun fit n’est alors autorisé.
- 33 tests catalogue/scheduler passent. La régression API passe 68 tests et
  retrouve uniquement le rouge préexistant des wrappers `openai_llm_v1` et
  `azure_openai_llm_v1`, sans entrée de catalogue.
- 25 tests supplémentaires du parcours de lecture et de décision HITL passent,
  dont lecture seule et expiration du gate.
- 181 tests frontend ciblés et 12 parcours navigateur FR/EN passent, dont
  proposition → fiche d’exécution → approbation, lecture seule, expiration,
  contexte figé et réponse POST d’accusé distincte du Run complet.
- Compilation Angular, i18n, contrôles UI et navigation passent.
- Le build production unique de cette branche passe. Les avertissements
  Angular, CSS, budget initial et dagre déjà présents restent sans changement.
- La revue d’intégration valide 64 tests ciblés backend : suppression et arrêt
  du cron, conservation de l’historique, isolation entre modèles et espaces,
  activation après lecture du modèle, parcours de réentraînement, récupération,
  API, scheduler et imports. Le frontend reste identique au build déjà qualifié.
