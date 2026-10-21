# Lots 2b et 3 — implémentation et validation

État au 21 octobre 2026 : changements dans le workspace, sans commit, push ni déploiement. La validation navigateur locale n'est pas acquise. La compilation de production et les vérifications globales sont centralisées dans le bilan d'intégration.

## Lot 2b — lectures honnêtes

- Sécurité du compte : une lecture MFA absente, mal formée, refusée ou indisponible affiche un état inconnu. Les commandes activer/désactiver ne sont accessibles qu'après lecture réussie.
- Sessions : une panne affiche l'erreur et Réessayer ; seule une réponse 200 vide donne un état vide.
- Récupération du mot de passe : les comptes connus/inconnus conservent la même réponse neutre lors d'une réussite. Les échecs Keycloak de recherche ou d'envoi produisent un 502 ; le formulaire reste disponible et permet de réessayer sans annoncer un envoi réussi.
- Politiques de contrôle/adaptatives, résumés des boucles, historique des conversations et réglages du workspace : états de lecture explicites. Les compteurs ne remplacent pas une erreur par zéro. Le filtre auteurs de l'historique a également un état d'erreur et une reprise.
- Les méthodes canoniques migrées pour les politiques, les écritures migrées et la simulation Impact propagent les erreurs par défaut. Une décision humaine sans identifiant attendu est refusée avant la requête.
- `check:fallbacks` inventorie par AST les replis `catchError`, `.catch(() => …)` et **tous** les appels `fallbackUnless`. Budget par fichier et empreintes, justification des nouvelles exceptions et comparaison avec le budget de la base empêchent une remontée.

Le même inventaire trouve **145** replis à `7e5652d5` et **126** après l’intégration finale, soit **19 de moins (13,1 %)**. `docs/compliance/fallback-budget.v1.json` conserve le SHA et le compte initial. La baisse ne résulte pas du déplacement de `catchError` vers le helper de compatibilité. Les annulations de réponses d'un ancien workspace ne fabriquent aucune valeur et ne masquent aucune erreur du workspace courant.

La CI construit le frontend, transmet son `dist/agentium/browser` au job Playwright puis exécute les fichiers `*-mocked.spec.ts`. `playwright.mocked.config.ts` impose une origine HTTP loopback, interdit une origine distante et active les fixtures locales. Une erreur navigateur fait échouer le job ; aucun compte de production n'est nécessaire. Ce nouveau job n'a pas encore été exécuté dans GitLab dans cette session.

## Lot 3 — repères et accès

- La reconstruction intégrée conserve la normalisation de destination après reconnexion, l'exclusion des routes `/auth/*`, les noms distincts Applications métier / Modules du workspace / Extensions et le paramètre `since` du catalogue de navigation.
- La palette lit les listes en mode strict et ajoute les applications réellement accessibles renvoyées par `/work`, avec l'identité publiée. Elle distingue une panne, une absence de résultats et un résultat masqué par le filtre de type ; chaque résultat d'objet indique son type et son workspace. Les réponses tardives d'un ancien workspace sont rejetées.
- L'étape de recherche serveur est implémentée et documentée dans `docs/adr/0005-navigation-search.md`. `/navigation/search` renvoie uniquement les métadonnées des collections/documents accessibles et des connexions du workspace. Le filtrage des droits précède la limite et `has_more`. Aucune configuration de connexion, référence de secret ou contenu de document n'est exposé. Les destinations appliquent le filtre du document et la sélection de la connexion.
- `DataService` épingle l'en-tête du workspace et vérifie son époque à chaque retour de liste, téléversement, détail, aperçu, réindexation et suppression. Un changement de workspace remet son cache à zéro ; une ancienne réponse ne termine pas le chargement du nouveau workspace.
- Work place les applications avant les indicateurs et la file. La file est nommée comme partagée par l'équipe et limitée par les droits. Le dossier et le filtre sont mémorisés par workspace pour le retour, avec lecture fraîche de l'état serveur et restauration du focus.
- La palette boucle la tabulation sur ses contrôles et rend le focus à l'élément d'origine à Échap. Le pied du rail possède un nom accessible, une étape de tabulation et un focus visible. Les liens feuille acceptent `tab`, notamment pour les journaux de déclencheurs.

## Preuves exécutées

| Vérification | Résultat réellement observé |
|---|---|
| `account-read-state.spec.ts` | 11 tests réussis : MFA, sessions, reset, reprise |
| `workspace-scoped-services.spec.ts` | 8 tests réussis, dont réponses liste et upload A→B |
| `command-palette.component.spec.ts` | 8 tests réussis, dont panne, application publiée, filtre, réponse serveur A→B |
| `conversations.component.spec.ts` | 4 tests réussis, dont panne→reprise vide |
| `navigation.catalog.spec.ts` | 26 tests réussis, dont transmission du tab de feuille |
| `canonical-api-errors.spec.ts` | 5 tests réussis : 21 méthodes × 4 statuts, décision sans id sans POST |
| `scripts/check-fallbacks.spec.mjs` | 3 tests réussis : AST, nouvelle exception injustifiée, budget qui ne peut augmenter |
| `check:fallbacks` | Budget final 126 ; baisse enregistrée par `--update`, sans relever un fichier |
| Pytest `test_auth_recovery_availability.py` + `test_navigation_search.py` | 9 tests réussis : neutralité, indisponibilité Keycloak, droits, isolation de workspace, absence de secrets, échappement des jokers |
| TypeScript `tsc --noEmit -p tsconfig.app.json` | Réussi lors de la vérification ciblée ; le build global reste la référence finale |
| `check:i18n` et `check:ui-chrome` | Réussis lors de la vérification ciblée ; libellés ajoutés en FR et EN |

Les tests TypeScript ont été bundlés avec esbuild et exécutés directement avec Node afin de lire le nombre de sous-tests, pas seulement le nombre de fichiers du runner.

## Vérifications encore nécessaires

`82-navigation-reads-mocked.spec.ts` contient 6 scénarios FR/EN couvrant MFA inconnu, sessions indisponibles puis reprise, récupération en panne puis réussite, recherche récupérable, filtre d'application et retour du focus. `26-work-home-mocked.spec.ts` vérifie aussi l'ordre applications/file et le retour au dossier.

**Ces scénarios navigateur ne sont pas déclarés passants.** La tentative du 21 octobre a échoué avant le premier test sur `listen EPERM: 127.0.0.1:4331`. L'appel demandant le réseau additionnel a été interrompu ; aucun serveur n'est resté démarré par ce lot. Le lancement est à reprendre avec le build final dans l'environnement de validation autorisé.

La recette du plan avec trois collaborateurs pour les états de sécurité, et cinq personnes pour les tâches de navigation, n'a pas été réalisée. Les tests automatisés ne remplacent pas cette recette. La preuve complète du retour depuis les écrans qualité avec période, System et filtres reste à couvrir par le parcours navigateur d'intégration.
