# Reprise ciblée d’une campagne de qualification

Une reprise crée **un nouveau Run canonique** pour un seul côté d’un cas. La mesure initiale, son échec, les autres cas et les totaux de la comparaison restent conservés. Les nouvelles preuves figurent dans une section séparée ; elles ne sélectionnent jamais automatiquement le meilleur essai.

## API

`POST /api/v1/evaluation/campaigns/{campaign_id}/retries`

```json
{
  "result_key": "delivery_contradiction-RC-5001:0",
  "side": "candidate",
  "source_run_id": "<dernier Run de ce côté>",
  "request_key": "<clé stable pour cette intention de reprise>",
  "reason": "Dépendance rétablie"
}
```

La réponse `201` reprend la représentation complète du GET campagne. Chaque côté expose `can_retry`, `retry_blocked_reason`, `retry_source_run_id` et `attempts`. Chaque tentative conserve son identifiant, son numéro, le Run initial, le Run source, le nouveau Run, le job, l’auteur, la date et le motif. Son `status` est le statut canonique du nouveau Run, et son résultat/coût concerne uniquement ce Run. `retry_pending` maintient le polling des reprises même si la comparaison initiale est terminée.

Réutiliser exactement la même clé et le même corps après une réponse HTTP perdue : le serveur retrouve la même tentative avant de contrôler l’état désormais modifié. Un corps différent avec la même clé donne `EVALUATION_RETRY_REQUEST_CHANGED` (409). Une nouvelle intention nécessite une nouvelle clé et le dernier `retry_source_run_id`.

## Conditions et limites

- Campagne `qualified_prefix` uniquement ; dernier Run `failed` ou `cancelled`, verdict `failed` ou `unevaluated`, aucune invocation encore en attente ou en cours. Un arrêt de qualification à la validation humaine n’est pas un échec à relancer. Un Run terminé avec une assertion négative n’est pas couvert par cette action.
- Les droits workspace, System/Flow Workbench et la lisibilité des Runs de la campagne sont contrôlés à la demande puis à l’exécution. La campagne peut être encore en cours sur d’autres cas.
- Le nouveau Run reprend les entrées, le Flow, le contrat d’exécution, le profil qualifié et les références de modèles figés. Le brouillon utilisateur n’est ni relu pour exécuter ni modifié. Un corpus modifié, un modèle remplacé ou une source invalide bloque la reprise.
- La liaison campagne et un identifiant de tentative distinct conservent le trafic d’évaluation et séparent ses datasets des données métier et des essais précédents. Le parcours s’arrête toujours à la frontière humaine, avant toute action métier. Les données de sources externes peuvent néanmoins évoluer ; leurs preuves appartiennent au nouveau Run.
- Maximum 20 reprises par côté et répétition. Aucune migration, aucun nouveau drapeau et aucun déblocage du rerun HTTP générique des Runs Workbench.

Autres refus 409 : `EVALUATION_RETRY_SOURCE_CHANGED`, `EVALUATION_RETRY_SOURCE_INVALID`, `EVALUATION_RETRY_CORPUS_CHANGED`, `EVALUATION_RETRY_NOT_ELIGIBLE` avec `reason` parmi `qualified_prefix_required`, `attempt_active`, `not_failed_terminal`, `retry_limit_reached`. Une ressource invisible renvoie 404. Le serveur reste l’autorité sur l’éligibilité : le client utilise `can_retry`.

## Concurrence et exploitation

L’admission sérialise brièvement la campagne avec un verrou `FOR NO KEY UPDATE`, compatible avec les lectures de clés étrangères. Le job existant de type `evaluation_campaign` porte `retry_run_id` et ne distribue que ce Run. Une prise exclusive persistée du job empêche deux livraisons de réinitialiser le même parcours. Aucune transaction ni aucun verrou campagne/job ne reste ouvert pendant l’exécution canonique.

Un échec de distribution clôt uniquement le nouveau Run non démarré. Après un crash de worker, un job déjà `running` n’est **pas redistribué automatiquement** : examiner le job, le Run et les invocations ; s’assurer qu’aucune exécution ne subsiste avant une clôture opérateur explicite. Il n’existe pas de récupération automatique des jobs de reprise interrompus dans cette livraison. Aucun état en cours n’est supposé échoué sur la seule base d’un délai.

La remise en service nécessite API et worker CPU sur la même livraison, ainsi que le correctif des transactions Judge. Ne pas rejouer la campagne entière pour reprendre un seul essai. La recette automatisée couvre l’idempotence, les droits, l’isolation, la source figée, la conservation des résultats et la concurrence sur PostgreSQL ; elle ne constitue pas une qualification métier en production.
