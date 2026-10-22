# Recette — observabilité, qualité et usage IA

Livraison produit générique du 22 octobre 2026, préparée depuis `aeec29e3a77bf1edc213db2c045ac04330c82961`.

## Ce qui est livré

- Un Run se consulte par Résultat, Exécution, Qualité et Usage et coûts. Les évaluations multiples conservent leur identité, leur état technique, leur verdict et leurs preuves autorisées. Work, Flow, Runner, perspectives et SSE appliquent aussi la révocation des preuves.
- Une suite se prépare avec des cas, assertions et contraintes de parcours lisibles. Le préflight précède les essais. Le parcours DataOps/ML/agent est isolé et s'arrête avant l'approbation humaine ; les tests ne produisent pas de remboursement métier.
- Giskard examine les réponses conservées, sans rappeler les outils métier. La revue humaine aveugle, l'arbitrage et le rapport de calibration demeurent distincts du Judge embarqué.
- Le journal IA conserve chaque tentative, son attribution et ses compteurs disponibles. Les tarifs sont versionnés ; les coûts calculés, devises séparées, ne représentent pas une facture. Une valeur absente demeure inconnue.
- Les plafonds workspace/application se réservent atomiquement avant envoi. Les appels concurrents, retries, sous-Runs et évaluations partagent les limites applicables. Une issue inconnue conserve son enveloppe.
- Impact propose deux blocs configurables, Qualité et Usage IA. Aucun écran ni carte spécifique Luma n'est imposé ; les vues sauvegardées restent intactes.

## Validation locale

- **77 tests unitaires frontend** : navigation exacte vers les preuves, sections du Run, blocs Impact, états de qualité, formulaires et calculs de présentation de l'usage.
- **23 tests navigateur Chromium** : français/anglais, thème sombre/clair, ordinateur/mobile, liens vers les preuves, accès révoqué, préparation des campagnes, revue aveugle, budgets explicites, vues Impact conservées. Les contrôles Axe inclus dans ces parcours passent.
- Compilation Angular de production et contrôles i18n, chrome UI et navigation réussis.
- **1 907 tests backend distincts validés sur 106 modules** : recette intégrée puis reprises ciblées des fixtures corrigées. Quatre tests MinIO explicitement optionnels restent non exécutés, faute de service MinIO dédié. Les tests PostgreSQL de concurrence, de migrations et de vue d’exécution passent.
- Ruff, formatage, contrat de conformité, hygiène Git et détection de secrets passent. Le hook de mise à jour automatique des versions d’outils a été écarté de cette livraison fonctionnelle ; les contrôles utilisent les versions déjà fixées dans le dépôt.

Deux corrections de préparation des tests ont été nécessaires : le scénario IAM respecte maintenant la confirmation de revue déjà requise par l’endpoint mail, et les imports de fixtures partagées sont explicites pour résister au nettoyage des imports inutilisés. Aucun endpoint métier n’a été changé pour contourner ces contrôles.

La sélection backend est conservée dans [backend-test-files.txt](backend-test-files.txt). Depuis `backend`, la relancer avec `python -m pytest -q -ra --tb=short $(cat ../docs/evidence/observability-quality-usage-2026-10-22/backend-test-files.txt)`. Les trois variables `MODEL_USAGE_POSTGRES_URL`, `DATASET_POSTGRES_URL` et `ACTIVITY_POSTGRES_URL` désignent une base PostgreSQL de test jetable, jamais la base de production. Configurer `SKB_DATA_DIRECTORY` et les caches ML vers un répertoire accessible en écriture.

Les tests navigateur utilisent des réponses API contrôlées, bloquent les accès externes et n'appellent aucun fournisseur. Les captures montrent ces données de test, **pas des mesures de Luma en service**. Les tests backend utilisent des doubles de fournisseurs ; les tests de transactions et migrations utilisent un PostgreSQL 16 jetable local.

## Captures

| Parcours | Capture |
| --- | --- |
| Contrôles et preuves | [Qualité](quality-fr.png) |
| Consommation et couverture | [Usage ordinateur](usage-fr-1440.png), [mobile](usage-en-390.png) |
| Limites explicites | [Budgets](budgets-fr-1440.png) |
| Attribution à une exécution | [Run](run-usage-fr.png) |
| Pilotage configurable | [Impact](impact-assurance-fr.png) |

## Mise en service et limites

Appliquer les migrations **145 et 146**, puis suivre le [runbook de livraison](../../ops/model-quality-usage-release-2026-10-22.md). L'activation des budgets requiert une attestation opérateur liée au SHA et des bornes/transport qualifiés. Les sessions vocales LLM et les requêtes multimodales non qualifiées sont refusées sous plafond ; STT/TTS restent hors budget LLM. Les réservations inconnues n'ont pas encore de parcours administrateur de résolution, et aucun import de facture n'est fourni.

Le [parcours de qualification Luma](../../ops/luma-agent-qa-campaigns.md) propose **12 cas × 2 versions × 2 répétitions = 48 Runs**, avec cas à relire. Six familles couvrent quatre scénarios métier ; elles ne constituent pas une campagne adversariale exhaustive. Les sources vivantes sont comparées par empreinte, sans garantie de rejeu immuable. Les références Giskard, annotations et arbitrages humains ne sont pas fabriqués. La création d'un nouveau corpus indépendant reste accessible par l'API existante ; le lecteur de revue ne prend pas en charge l'annotation d'images.

Aucune campagne Luma ni mesure fournisseur réelle n'a été produite par cette recette. Aucun brouillon utilisateur, Flow publié, champion, shadow ou vue enregistrée n'a été modifié en service. La qualification sur le déploiement cible reste à réaliser.
