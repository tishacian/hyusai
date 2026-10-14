# Budget partagé d'une fenêtre de service

Une fenêtre possède un seul ledger `WorkspaceJob`, de type
`service_window_budget_v1`, partagé par narration et juge. Les réservations sont
cumulées entre étapes, workers et reprises de Runs. Une narration mesurée à 9
sur un plafond de 10 ne laisse que 1 disponible : une réservation du juge à 9
échoue avant l'appel du modèle.

Les limites du contrat versionné restent `max_cost`, `max_tokens`, `max_seconds`
et `max_attempts`. Un lot mixte peut déclarer des enveloppes d'étape :

```json
{
  "max_cost": 10,
  "max_tokens": 100000,
  "max_seconds": 3600,
  "max_attempts": 3,
  "stages": {
    "narration": {"max_cost": 6, "max_tokens": 70000, "max_seconds": 2400},
    "judge": {"max_cost": 4, "max_tokens": 30000, "max_seconds": 1200}
  }
}
```

Cet exemple illustre la répartition, pas un tarif ni un seuil métier recommandé.
La somme des enveloppes ne peut dépasser la fenêtre, sur aucune dimension.
Quand `stages` est renseigné, une étape non déclarée est refusée. Les plafonds
propres à l'adaptateur ou au modèle peuvent réduire ces enveloppes.

La narration réserve son maximum distant avant le premier POST. Le gateway
doit réellement appliquer les plafonds qu'il reçoit. Le juge réserve chaque
appel juste avant son envoi, à partir des bornes de prompt, sortie, images et
tarif figé. La fenêtre et sa tentative active sont résolues en base depuis le
Run : un `service_window_id` dans une entrée libre ne donne aucune autorité.
L'admission vérifie fence, lease, échéance et System, puis écrit sous verrou.

Une mesure terminale complète remplace la réserve. Une mesure intermédiaire
ne libère rien : un gateway encore actif pourrait consommer le reste de son
enveloppe. Une mesure inconnue conserve aussi la réserve entière. Un zéro
explicite est une mesure ; `null` ne devient jamais zéro. Si une mesure réelle
dépasse l'engagement, le ledger conserve la dépense et signale le dépassement.
Une hausse contradictoire après facture finale est conservée avec
`measurement_conflict=true` et interdit de nouvelles admissions.

Le compteur de narration et la clé d'idempotence du gateway sont liés à
`window_id + node_id`, pas au Run courant. Une reprise retrouve le même job
distant. Elle ne remet à zéro ni plafond, ni échéance, ni coût inconnu. Une
réponse tardive peut encore régler sa réservation originale ; le worker périmé
ne peut ni poursuivre, ni modifier les checkpoints hérités, ni annuler le job
partagé de la nouvelle tentative. Une réponse modèle ambiguë n'est jamais
relancée automatiquement comme si son premier appel était gratuit.

Si la narration est déjà complète, un nouveau Run réutilise les octets dans un
nouvel actif immuable. Son `producer.run_id` désigne le Run courant ; le parent,
`reused_from` et `original_measurement` conservent l'origine. La nouvelle dépense
vaut explicitement zéro, et la qualification du nouveau candidat vaut
`review_required`. Réutiliser le cache ne réutilise pas une décision humaine.

## Raccordement du moteur

`window_budget.reserve(ctx, stage, key, cost, tokens, seconds)` et
`window_budget.settle(reservation, cost=None, tokens=None, seconds=None)` possèdent
leurs transactions courtes. Seul le gateway avec sa clé distante stable utilise
`replayable=True`. Les paramètres nommés sont obligatoires pour les limites.
`guard_checkpoint(db, ctx)` verrouille la fenêtre jusqu'au commit du checkpoint.

`summary(db, workspace_id, window_id, run_id=...)` renvoie les mesures propres à
une tentative de Run ; sans `run_id`, il renvoie le cumul de la fenêtre :

- `engaged_*` : consommation conservatrice pour l'admission ;
- `reserved_*` : somme historique des réservations ;
- `known_*` : sous-total réellement connu, éventuellement partiel ;
- `measured_*` : total complet, sinon `null` ;
- `*_coverage` : `unavailable`, `partial` ou `measured` ;
- `over_budget` et `measurement_conflict` : raisons de refuser la livraison.

Ne pas additionner ces totaux au `Run.provider_cost_usd` : le juge y figure déjà.
Le moteur doit rapprocher les mesures par Run, puis vérifier les indicateurs
globaux de fenêtre avant livraison, notamment après une réponse tardive. La
durée totale du Run reste la mesure de temps de l'obligation de service ; les
réservations de temps par étape empêchent des appels simultanés ou successifs de
consommer chacun le plafond complet. Aucun double comptage Run + étapes.

Validation locale :

```bash
cd backend
../.venv/bin/python -m pytest -q app/tests/services/test_window_budget.py app/tests/services/test_narration.py app/tests/services/test_typed_judge.py app/tests/services/test_service_contracts.py
```
