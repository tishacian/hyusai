# Fluidité — état de livraison

Image en production : `0dd15330570dd2c1755a17282426af75ce2b4fc8` (`revision_verified: true`).
Rollback image : `c629f5af5237`.

Ces pourcentages sont des estimations de complétude par critère de sortie, pas une mesure automatique. Les portes automation-first ne ferment pas F1–F6.

## Portes automation-first

- Porte 0 — environ 80 %. Le run SPARK-365 `8591bc37` sur `d4a75119` n’a pas produit de minutes. Sur `5eabc862`, un nouveau brouillon Trigger → Agent → Output (`0c7393e2`, run `b8d02ddb`, skill `workspace_llm_v1`) a produit des minutes. Le compte est encore le builder, pas un process owner. La porte reste ouverte.
- Porte 1 — fermée sur les noms visibles. Sur `ae35157b`, Run et Publish (ou Application une fois publié) portent le même nom accessible. Workbench, Server draft et Test draft sont absents.
- Porte 2 — fermée sur le scope défini. Retrieval cité, écriture SAP scellée, pause humaine, file de décision.
- Boucle d’édition — environ 90 %. Lecture, patch lié au hash, read-back et test de brouillon sont en ligne.
- Porte 3 — le produit est en place. Work et Hypervisor montrent l’automation publiée. L’absence de convention et d’écart reste affichée tant qu’aucun tarif métier n’est déclaré. Ce manque n’est pas une vague de développement.

## F1–F6

- F1 — l’objet épinglé survit au rechargement et au départ de la page. Sur `0dd15330`, le système `df04a96a` reste ouvert dans la conversation après un hard reload puis après `/systems`, avec Unpin et la même preuve présente.
- F2 — le panneau dit Prêt sur `c629f5af`, automation `0c7393e2`. Modèle, fournisseur `openai`, source, droits et exécutant sont prêts. L’indexation est sans objet. L’exécutant est prêt parce que deux workers Celery ont répondu.
- F3 — la boucle est en ligne sur `b14fe69d`. Sur l’automation `0c7393e2` : réserve « VAT is still open », relecture trigger / agent / output, correction confirmée sur ce hash, comparaison avec le résultat suivant `b63de11e` en gardant le même objet. L’import SPARK-089 complet n’est pas cette preuve.
- F4 — sur l’image `0dd15330`, la table garde les anciennes versions. « Subscriber base — cleaned » a toujours la version 6, preuve absente, et la version 7, preuve présente. Une version ajoutée, « Published minutes awaiting a person » version 1, dit preuve présente et en attente d’une personne. Le point du graphique ouvre ce dossier et le résultat `hitl_pending`.
- F5 — le graphique figé est en ligne sur `3f2b300f`. Le point « Subscriber base — cleaned · 6 » n’a pas de résultat. Le point version 7 ouvre le dossier et le résultat completed.
- F6 — Work, la conversation et l’API disent la même preuve sur `26928471`. Pour l’automation publiée `df04a96a`, les trois surfaces la voient présente. L’écriture reste scellée et non appelée. La convention et l’écart restent absents.

## Trace connue

Le 22 septembre 2026 à 11:09:30Z, pendant les lectures Hypervisor du canari Showcase, le backend a journalisé `Task exception was never retrieved` : `httpx2.AsyncClient.aclose` lève `RuntimeError: Event loop is closed`. La pile reste dans `httpx2` / `httpcore2` / `anyio`. Aucune frame applicative. Les requêtes autour restent en 200, et les conteneurs restent healthy. Ce n’est pas un zéro exception sur la fenêtre. Le correctif n’est pas identifié sans un client applicatif à fermer.
