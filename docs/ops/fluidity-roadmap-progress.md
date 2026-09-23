# Fluidité — état de livraison

Image en production : `1d27134c116b684a3a80c5aba6f6d25e7721f4f3` (`revision_verified: true`).
Rollback image : `61a1eb77d99a`.

Ces pourcentages sont des estimations de complétude par critère de sortie, pas une mesure automatique. Les portes automation-first ne ferment pas F1–F6.

## Portes automation-first

- Porte 0 — environ 80 %. Le run SPARK-365 `8591bc37` sur `d4a75119` n’a pas produit de minutes. Sur `5eabc862`, un nouveau brouillon Trigger → Agent → Output (`0c7393e2`, run `b8d02ddb`, skill `workspace_llm_v1`) a produit des minutes. Le compte connecté est `workspace_owner`. Nawa compte 3 `workspace_contributor` et 2 `workspace_admin`. Deux contributeurs sont `active` et ont déjà une connexion ; le troisième est `pending` et n’a jamais ouvert de session. `iam_enforced` est absent sur Nawa, et le moteur IAM global ne liste que `andritz`, donc un membre peut créer et lancer un System. La session ouverte n’est pas la leur. La porte reste ouverte.
- Porte 1 — fermée sur les noms visibles. Sur `ae35157b`, Run et Publish (ou Application une fois publié) portent le même nom accessible. Workbench, Server draft et Test draft sont absents.
- Porte 2 — fermée sur le scope défini. Retrieval cité, écriture SAP scellée, pause humaine, file de décision.
- Boucle d’édition — critère de sortie couvert sur `0c7393e2`. La relecture montre retrieve, approval, sap_write et l’arête `decided_by`. Le brouillon n’est pas publié. Sur `65b66219`, le run `498fff50` sans personne termine l’écriture `sap_create_po_v1` avec `sealed: true`, `called: false`, raison `unattended`, puis reste en pause sur l’approbation.
- Porte 3 — le produit est en place. Work et Hypervisor montrent l’automation publiée. L’absence de convention et d’écart reste affichée tant qu’aucun tarif métier n’est déclaré. Ce manque n’est pas une vague de développement.

## F1–F6

- F1 — l’objet épinglé survit au rechargement. Sur `65b66219`, le chat du système publié liste ce système dans son contexte, avec les autres systèmes et 16 conversations. Le thème passe de sombre à clair (`data-theme=light`) puis revient à sombre, stocké dans `agentium_theme`. La flèche gauche élargit le panneau de 560 à 592 px, stocké dans `agentium.chat-panel-width`. Un second onglet ouvert sur le run `8591bc37` lit les mêmes valeurs. L’usage répété au fil des jours n’est pas une preuve de session.
- F2 — fermée sur `1d27134c`, automation `0c7393e2`. Les six contrôles sont prêts : modèle `workspace_llm_v1`, fournisseur `openai`, source, indexation, droits, exécutant. L’indexation est prête parce que Nawa a déjà des chunks (`documents`, `itsd-knowledge`, `po-invoice-recon-demo`). L’exécutant est prêt parce que Celery a répondu. Le panneau dit Prêt.
- F3 — sur `61a1eb77`, le Flow de `SPARK-089 summary` (`cd696462`) affiche Réserve. La note « The proposed grade is still missing. » est enregistrée sur le run `95f2e6e5`, et l’adresse reste ce système. La relecture s’arrête : le brouillon contient `t_extract`, hors catalogue d’automation. Le document `e2d7e8ce` et les cinq cas « Human review required » restent la preuve d’import. La comparaison de `0c7393e2` reste une autre preuve.
- F4 — sur l’image `0dd15330`, la table garde les anciennes versions. « Subscriber base — cleaned » a toujours la version 6, preuve absente, et la version 7, preuve présente. Une version ajoutée, « Published minutes awaiting a person » version 1, dit preuve présente et en attente d’une personne. Le point du graphique ouvre ce dossier et le résultat `hitl_pending`.
- F5 — revu sur `65b66219`. Le point « Subscriber base — cleaned · 6 » dit « This point has no result. » Le point version 7 dit « Result: completed » (`01732a0d`).
- F6 — sur `65b66219`, Work, la page Flow et la conversation disent « Same proof: present. » pour `df04a96a`. Le pilote montre ce système et Unpin. L’API dit présente, scellée, non appelée, convention absente, écart absent, une source.

## Trace connue

Le 22 septembre 2026 à 11:09:30Z, pendant les lectures Hypervisor du canari Showcase, le backend a journalisé `Task exception was never retrieved` : `httpx2.AsyncClient.aclose` lève `RuntimeError: Event loop is closed`. La pile reste dans `httpx2` / `httpcore2` / `anyio`. Aucune frame applicative. Les requêtes autour restent en 200, et les conteneurs restent healthy. Ce n’est pas un zéro exception sur la fenêtre. Le correctif n’est pas identifié sans un client applicatif à fermer.
