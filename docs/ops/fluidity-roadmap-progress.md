# Fluidité — état de livraison

Image en production : `26928471cb9f1163c1d24170da04dfd2f8b0a55e` (`revision_verified: true`).
Rollback image : `3f2b300fa0e8`.

Ces pourcentages sont des estimations de complétude par critère de sortie, pas une mesure automatique. Les portes automation-first ne ferment pas F1–F6.

## Portes automation-first

- Porte 0 — environ 80 %. Le run SPARK-365 `8591bc37` sur `d4a75119` n’a pas produit de minutes. Sur `5eabc862`, un nouveau brouillon Trigger → Agent → Output (`0c7393e2`, run `b8d02ddb`, skill `workspace_llm_v1`) a produit des minutes. Le compte est encore le builder, pas un process owner. La porte reste ouverte.
- Porte 1 — fermée sur les noms visibles. Sur `ae35157b`, Run et Publish (ou Application une fois publié) portent le même nom accessible. Workbench, Server draft et Test draft sont absents.
- Porte 2 — fermée sur le scope défini. Retrieval cité, écriture SAP scellée, pause humaine, file de décision.
- Boucle d’édition — environ 90 %. Lecture, patch lié au hash, read-back et test de brouillon sont en ligne.
- Porte 3 — le produit est en place. Work et Hypervisor montrent l’automation publiée. L’absence de convention et d’écart reste affichée tant qu’aucun tarif métier n’est déclaré. Ce manque n’est pas une vague de développement.

## F1–F6

- F1 — environ 90 %. Contexte System/Run/SkillInvocation, épingle, persistance, reprise et chat redimensionnable sont là. La recette utilisateur complète manque.
- F2 — environ 60 %. Sur `ab96ff7c`, l’automation `0c7393e2` dit pas prêt. Le modèle, le fournisseur nommé par le routage (`openai`) et la source sont prêts, l’indexation est sans objet, et les droits de l’appelant sont prêts. L’exécutant reste « contrôle non effectué » : aucun battement de cœur du worker n’existe à lire. F2 n’est pas close.
- F3 — la boucle est en ligne sur `b14fe69d`. Sur l’automation `0c7393e2` : réserve « VAT is still open », relecture trigger / agent / output, correction confirmée sur ce hash, comparaison avec le résultat suivant `b63de11e` en gardant le même objet. L’import SPARK-089 complet n’est pas cette preuve.
- F4 — la table est en ligne sur `76a7e9db`. Chaque version de dataset reste une ligne, avec preuve présente ou absente. Sur Nawa, « Subscriber base — cleaned » garde la version 6 et la version 7. Aucune de ces lignes n’attendait une personne.
- F5 — le graphique figé est en ligne sur `3f2b300f`. Le point « Subscriber base — cleaned · 6 » n’a pas de résultat. Le point version 7 ouvre le dossier et le résultat completed.
- F6 — Work, la conversation et l’API disent la même preuve sur `26928471`. Pour l’automation publiée `df04a96a`, les trois surfaces la voient présente. L’écriture reste scellée et non appelée. La convention et l’écart restent absents.

## Trace connue

Le 22 septembre 2026 à 11:09:30Z, pendant les lectures Hypervisor du canari Showcase, le backend a journalisé `Task exception was never retrieved` : `httpx2.AsyncClient.aclose` lève `RuntimeError: Event loop is closed`. La pile reste dans `httpx2` / `httpcore2` / `anyio`. Aucune frame applicative. Les requêtes autour restent en 200, et les conteneurs restent healthy. Ce n’est pas un zéro exception sur la fenêtre. Le correctif n’est pas identifié sans un client applicatif à fermer.
