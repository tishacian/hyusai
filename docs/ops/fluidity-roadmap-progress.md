# Fluidité — état de livraison

Image en production : `3fd6fb26243c869a67fe150d4e4ccc6aaef98a0e` (`revision_verified: true`).
Rollback image : `ae35157bf8a6`.

Ces pourcentages sont des estimations de complétude par critère de sortie, pas une mesure automatique. Les portes automation-first ne ferment pas F1–F6.

## Portes automation-first

- Porte 0 — environ 80 %. Le run SPARK-365 `8591bc37` sur `d4a75119` n’a pas produit de minutes. Sur `5eabc862`, un nouveau brouillon Trigger → Agent → Output (`0c7393e2`, run `b8d02ddb`, skill `workspace_llm_v1`) a produit des minutes. Le compte est encore le builder, pas un process owner. La porte reste ouverte.
- Porte 1 — fermée sur les noms visibles. Sur `ae35157b`, Run et Publish (ou Application une fois publié) portent le même nom accessible. Workbench, Server draft et Test draft sont absents.
- Porte 2 — fermée sur le scope défini. Retrieval cité, écriture SAP scellée, pause humaine, file de décision.
- Boucle d’édition — environ 90 %. Lecture, patch lié au hash, read-back et test de brouillon sont en ligne.
- Porte 3 — environ 80 %. Work et Hypervisor montrent l’automation publiée. La convention de valeur et l’écart mesuré sont encore absents, et l’interface le dit.

## F1–F6

- F1 — environ 90 %. Contexte System/Run/SkillInvocation, épingle, persistance, reprise et chat redimensionnable sont là. La recette utilisateur complète manque.
- F2 — environ 40 %. Le parcours de préparation est visible sur le Flow et nomme modèle, fournisseur, source, indexation, droits et exécutant. Un contrôle non fait reste « non effectué » et n’est pas prêt. Le fournisseur du workspace, les droits de l’appelant et l’exécutant ne sont pas encore contrôlés.
- F3 — environ 45 %. BRD, brouillon, gouvernance et exécution existent. La boucle résultat, réserve, correction relue et comparaison sans perte d’objet n’est pas close.
- F4 — environ 40 %. Le job Work d’une automation existe. Il manque la table générique ligne métier, version de dataset, Run, preuve.
- F5 — environ 40 %. Les graphiques et le portefeuille automation existent. Il manque le contrat graphique figé et le chemin point, dossier, Run.
- F6 — environ 30 %. Work et le paquet de run existent. La même permission et la même preuve sur Work, conversation et API ne sont pas qualifiées.

## Trace connue

Le 22 septembre 2026 à 11:09:30Z, pendant les lectures Hypervisor du canari Showcase, le backend a journalisé `Task exception was never retrieved` : `httpx2.AsyncClient.aclose` lève `RuntimeError: Event loop is closed`. La pile reste dans `httpx2` / `httpcore2` / `anyio`. Aucune frame applicative. Les requêtes autour restent en 200, et les conteneurs restent healthy. Ce n’est pas un zéro exception sur la fenêtre. Le correctif n’est pas identifié sans un client applicatif à fermer.
