# Intégration du plan UI/UX — 21 octobre 2026

**Bilan avant déploiement : candidat implémenté, recette complète non acquise.** Ce dossier conserve les preuves obtenues avant la livraison. La version a depuis été déployée par l'utilisateur ; les contrôles en service et corrections suivants figurent dans la [recette après déploiement](../uiux-recette-2026-10-21.md). Aucun de ces bilans ne certifie à lui seul les 58 stories.

## Révision et périmètre

- Checkout : `feat/uiux-plan-completion`, HEAD `d3517a15` (lot 2a reconstruit). Ce bilan a été établi avant le commit ; la livraison Git a ensuite été autorisée par l’utilisateur. Le commit qui contient ce rapport identifie le candidat publié. `files.sha256` identifie le contenu des fichiers modifiés/ajoutés hors ce dossier ; le HEAD seul ne représente donc pas le candidat.
- Référence produit du plan : `7e5652d5`. Le plan PDF fourni couvre les lots 1, 2a, 2b, 3, 4, 5, 6, 7, 8a, 8b, 8c et 9.
- Les sept contributions reconstruites ont été intégrées : 2a comme base, puis les différences des lots 1, 3, 4, 6, 7 et 8b. Le conflit de la page des applications conserve la présentation du lot 1 et la reprise du wizard du lot 4.
- Les ajouts de cette session complètent les autres lots et corrigent les défauts trouvés pendant l'intégration. La validation ci-dessous précède le commit et le push. Aucun déploiement, migration de base réelle ou action auprès des fournisseurs n'a été effectué.
- `RESULTAT.md`, le rapport UX détaillé et la matrice source des stories n'étaient pas disponibles. L'identité des 23 SHA annoncée dans le récit de reconstruction n'a pas été auditée à nouveau ; le dernier script 8b fait partie du WIP intégré, sans preuve qu'il avait tourné sur le Mac. Les captures PNG du lot 1 ne sont pas reconstituées.

## Couverture

| Lots | Implémentation locale | Recette |
| --- | --- | --- |
| [1 et 8a](lots-1-8a.md) | Finition, cadres de page, capacités/tests de connecteurs, reçus par fichier, écritures incertaines, isolation workspace | Tests ciblés passés ; captures, navigateur et fournisseurs réels non validés |
| [2a](lot-2a.md) | États partagés, décision avec reçu exact, erreurs canoniques, rôle confirmé, création de System sans succès inventé | Tests unitaires passés ; décisions réelles à trois comptes et concurrence non rejouées |
| [2b et 3](lots-2b-3.md) | Lectures honnêtes, garde CI, recherche et droits serveur, navigation et caches scoped | Tests ciblés passés ; parcours navigateur et panel non réalisés |
| [4 et 5](lots-4-5.md) | Départ vierge, wizard repris, Flow publié en lecture, Judge guidé, conflits, rollback, journal des livraisons acceptées | Tests unitaires passés ; test 71, Luma et scénario créateur sur pile réelle non exécutés |
| [6](lot-6.md) | Provenance exacte, erreurs connaissance, fraîcheur, callable, effectifs qualité, préparation et imports | Tests ciblés passés ; recette CSV, PostgreSQL et import réel non exécutés |
| [7](lot-7.md) | Impact, secrets, missions durables, Services, reçus cycle de vie et audit | Tests ciblés passés ; migration/Celery/PostgreSQL concurrents et parcours navigateur non validés |
| [8b et 8c](lots-8b-8c.md) | Imports partiels, aide, capture relue, veille, mail Client 360 et versions applicatives | Tests ciblés passés ; scénarios navigateur et fournisseurs non validés |
| [9](lot-9-recette.md) | Protocole, seuils et exclusions documentés | **Non exécuté** : second corpus, accessibilité globale, premier regard et panel humain |

Le registre complet des doublons/livraisons ignorées et le rejeu des déclencheurs constituent le chantier séparé explicitement prévu au lot 5. La première version lit les livraisons acceptées existantes. La note de conception est dans `docs/design/trigger-delivery-registry.md`.

## Vérifications d'intégration

Les résultats définitifs et commandes figurent dans `validation.txt`. Les rapports par lot détaillent les tests ciblés ; leurs nombres ne doivent pas être additionnés aux suites globales, car il existe des recouvrements.

- Contrôles i18n, navigation, chrome et budget de replis exécutés. Le garde i18n refuse désormais aussi les clés d'objet dupliquées, avant qu'une traduction puisse être écrasée silencieusement.
- Le budget de replis diminue de **145 à 126** à inventaire comparable, helpers compris. Le budget visuel est abaissé à **1 921** occurrences existantes autorisées ; ce nombre n'est pas un résultat axe ni une affirmation de conformité visuelle.
- La compilation `build:prod:offline` conserve les optimisations JavaScript/CSS et les budgets de production. Le téléchargement des polices est désactivé uniquement dans cette configuration. Le build standard a échoué sur l'accès à Google Fonts interdit dans le sandbox ; sa réussite n'est pas revendiquée.
- Backend : 32 tests ciblés d'intégration locale passent, dont navigation/droits, récupération de compte, missions, cycle de vie, références audit, reçus SharePoint et cadence. Des services externes sont simulés. Une tentative plus large incluant les anciens tests HTTP TestClient s'est bloquée et a été arrêtée après 60 secondes ; elle n'est pas comptée comme réussite.
- Alembic présente une seule tête `144_sharepoint_file_outcomes`. Cela vérifie le graphe, **pas** l'application des migrations sur une base. Les migrations 142, 143 et 144 et le worker/beat nécessitent une validation sur la pile de recette.
- Aucun scénario Playwright de cette session n'est marqué passé. Le serveur local a été refusé par le sandbox (`listen EPERM`), puis les appels avec permission réseau sont restés en attente et ont été interrompus. La présence de scénarios et du job CI n'est pas une preuve de leur exécution.

## Conditions restantes pour annoncer « terminé »

1. Exécuter le build standard et les scénarios navigateur, notamment Luma et le test 71, sur une pile autorisée correspondant au candidat.
2. Vérifier migrations, concurrence PostgreSQL, redémarrage/reprise du worker Celery et les fournisseurs réellement raccordés ; les limites précises sont dans les bilans par lot.
3. Rejouer les trois scénarios avec un second corpus et les droits réels. Mesurer clavier, 320 px, thèmes/langues et axe, puis réaliser les séances du lot 9 aux seuils du plan.
4. Rapprocher les résultats de la matrice source des 58 stories : chaque story recettée ou exclusion explicite, mesures avant/après réellement observées.

Le code est disponible pour revue locale. Le commit et le push sur `feat/uiux-plan-completion` ont été explicitement demandés par l’utilisateur après lecture de ces résultats partiels. Le déploiement reste à sa charge ; les validations absentes ne deviennent pas acquises par la publication Git.
