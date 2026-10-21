# Lots 1 et 8a — état d’implémentation et preuves

Date : 21 octobre 2026. Branche locale : `feat/uiux-plan-completion`.
Aucun déploiement, commit ni appel à un fournisseur réel n’a été effectué pour ce lot.

## Lot 1 : finition mesurée

Les corrections reconstruites des composants partagés sont intégrées : cadre de page des connecteurs, géométrie des boutons Work et glyphes, disposition du wizard, table des applications et garde du plancher typographique de 12 px. La suite `e2e/tests/72-finish-geometry-mocked.spec.ts` contient les mesures de géométrie et les matrices d’accessibilité. Le lot 8a supprime également les tailles sous 12 px de SFTP, MCP, RPA, SharePoint, du tiroir générique et du portail invité.

`check:ui-chrome` a passé pendant cette implémentation. Son budget doit être resserré sur l’état final partagé, sans relever de valeur. Les 20 PNG historiques manquants ne sont pas recréés : des captures actuelles ne constitueraient pas une preuve de l’état historique « avant ». Le README historique `docs/ops/ui-finish-lot-1-2026-10-20/README.md` est un compte rendu reconstruit, pas une recette répétée dans cette session.

**Non validé dans cette session :** captures finales clair/sombre, mesures 1470×776, 320 px, zoom 200 %, focus/hover/désactivé et revue visuelle. La validation navigateur commune et les captures de l’état final sont à centraliser après le build final.

## Lot 8a : comportement livré

- Une matrice commune décrit configurer, tester, importer, planifier, écrire et révoquer ; les actions absentes de l’API sont indiquées comme non prises en charge. Les profils de Connexions utilisent leurs capacités déclarées. PostgreSQL historique indique l’import et aucune écriture dans la base source ; les écritures de Connexions conservent le contrat du lot 2a.
- Les contrôles distinguent configuration enregistrée, authentification et accès à la ressource. Une réponse vide ne constitue pas un succès. Un refus S3 403 laisse l’authentification indéterminée : il ne prouve pas l’existence du compartiment ni la validité des identifiants.
- RPA : test par lecture `GET /jobs`, correspondances de tâches lisibles avant usage, absence de découverte automatique expliquée, retrait local explicite sans interrompre les tâches déjà démarrées. Les réponses de test ne recopient pas le corps du fournisseur. Les adresses de base nouvellement enregistrées refusent les identifiants ou paramètres intégrés à l’URL.
- MCP et HANA : tests d’accès distinguant les causes, retrait MCP expliqué, traitement des écritures incertaines. Les aperçus MCP existants restent limités aux candidats de lecture reconnus par l’API ; la qualification actuelle repose notamment sur le nom des outils et ne certifie pas le comportement d’un serveur externe.
- SharePoint : test de lecture du dossier sans téléchargement ni suppression, accès OAuth/session, oubli explicite et résultat des écritures, suivi distinct téléchargement/indexation par fichier. Un reçu conserve au plus 500 fichiers et indique explicitement la troncature. La migration `144_sharepoint_file_outcomes`, après `143_task_executions`, ajoute la colonne JSON nullable ; elle n’a pas été appliquée à une base de production.
- Dépôt invité : chaque fichier reçoit son statut et son motif de refus, indépendamment de l’échec d’un autre fichier. La réception indique l’attente de promotion. Un délai dépassé reste incertain et les fichiers sélectionnés ne sont pas renvoyés automatiquement.
- SFTP : texte du parcours et des actions disponible FR/EN, inspections avant quarantaine conservées, conséquences de rotation/révocation explicites. La rotation invalide l’ancien mot de passe pour les nouvelles connexions ; les sessions existantes restent valides jusqu’à expiration, sauf révocation de l’accès. Une mutation incertaine bloque son rejeu ; la révocation reste disponible pour fermer un accès dont le mot de passe aurait changé sans réponse reçue.
- S3 : test réel `head_bucket`, sans liste ni envoi d’objet ; export, surveillance et déclenchement présentés séparément. Les surveillances renvoient au journal du système via `/systems/:id/flow?tab=triggers`. Les opérations avancées passent par Connexions, dont la configuration est distincte du tiroir générique.
- HANA, MCP, RPA, SFTP et SharePoint purgent leurs données/secrets à la transition de workspace et écartent les réponses tardives. Le garde partagé `guardWorkspaceRequest` annule la livraison d’un ancien contexte sans émettre de valeur de remplacement ; une erreur du contexte courant reste une erreur.

## Vérifications effectivement exécutées

- **100 tests services backend réussis** : `test_generic_connectors.py`, `test_mcp_connector.py`, `test_mcp_oauth.py`, `test_hana_security.py`, `test_hana_preview.py`, `test_connector_resource_checks.py`, `test_rpa_bridge_connector.py`, `test_sharepoint_file_receipt.py`.
- **5 suites ciblées frontend réussies après stabilisation finale** : matrice/contrôles, reçu invité, tiroir générique, HANA et RPA. Commande : `FLOW_UNIT_FILTER=rpa-connector,hana-connector,generic-connector-drawer,connector-capabilities,deposit-receipt node scripts/run-unit.mjs`. Les tests RPA couvrent notamment l’écriture 504 sans double envoi et le rejet d’une réponse tardive. Le tiroir générique couvre également la conservation du secret saisi après résultat incertain. Le test du garde partagé vérifie que l’erreur courante n’est jamais remplacée par une liste vide.
- `check:i18n` a passé : parité FR/EN et règles lexicales. Un doublon concurrent dans `experience.dict.ts` bloquait alors le typecheck global ; il ne constituait pas un diagnostic de ces connecteurs. Le build/typecheck final partagé reste la référence.
- `check:ui-chrome` a passé. Les quatre anciens `catchError(... EMPTY)` ajoutés pour annuler les requêtes périmées ont été remplacés par le garde partagé explicite ; aucun budget de repli n’a été relevé pour les autoriser. Dernier contrôle local : `check:fallbacks` **133/147**, réussi. `git diff --check` sur les fichiers du lot est également propre.

## Validations non achevées / limites

- Les tests API `test_hana_rpa_admin_api.py` et `test_generic_connectors_api.py` n’ont pas achevé leur exécution dans le bac à sable. Le processus bloqué a été arrêté ; les 100 tests services ci-dessus sont une exécution séparée réussie. Ne pas annoncer les tests API comme validés.
- La nouvelle suite `e2e/tests/76-connector-deposit-receipts-mocked.spec.ts` décrit deux fichiers, dont un refusé, FR/EN et 320 px. Elle **n’a pas produit de résultat validé** : le serveur local a d’abord échoué avec `listen EPERM`, puis la commande nécessitant le réseau local a été annulée. Ne pas compter ces deux scénarios comme réussis.
- Les fournisseurs réels (identifiants bons/mauvais, droits limités, OAuth/session, révocation effective, export immuable et livraisons S3) n’ont pas été exercés. La recette avec trois responsables de données et un invité, les captures et le taux de reprise demandé par le plan restent à mesurer sur une pile de recette.
- La migration SharePoint et les contrats externes doivent être validés sur cette pile. La troncature à 500 fichiers est annoncée, sans pagination de détail supplémentaire dans cette version.
