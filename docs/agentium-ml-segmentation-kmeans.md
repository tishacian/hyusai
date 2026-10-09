# Segmentation numérique KMeans

La tâche `clustering` regroupe les lignes d’un dataset selon les variables
numériques choisies, sans cible ni étiquettes. Elle appartient à la famille
`clustering`, utilise le worker général et répond dans l’API, comme le tabulaire
classique. Elle n’ajoute ni dépendance, ni image, ni migration.

## Contrat du premier lot

- Algorithme `kmeans`, de 2 à 20 groupes (5 par défaut), de 50 à 500 itérations
  (300 par défaut). Dix initialisations, graine de la configuration ML existante.
- Sélection explicite de 1 à 50 variables de type entier ou décimal. Les plafonds
  globaux du déploiement restent applicables s’ils sont plus bas.
- De `max(ml_train_min_rows, 2 × nombre de groupes)` à 50 000 lignes. Le nombre de
  profils distincts après imputation doit permettre de former tous les groupes.
- Imputation par la médiane puis standardisation dans la pipeline exportée.
  Les colonnes entièrement vides, les valeurs infinies et les variables non
  numériques sont refusées. Les variables constantes et les lignes entièrement
  imputées sont signalées dans les résultats.
- Toutes les lignes ajustent le modèle final. Aucune cible, aucun split de test,
  aucune calibration ou optimisation automatique n’est utilisée. Pour préserver
  les clients communs existants, la valeur par défaut `test_size=0.25` est tolérée
  à l’entrée mais le modèle conserve `test_size=0` et `cross_validation=0`.
  Un autre split explicite est refusé.

Les distances donnent le même poids initial aux variables standardisées. Choisir
plusieurs variables fortement corrélées peut donc surpondérer un même phénomène.
Un identifiant numérique n’est généralement pas une variable de segmentation
pertinente : le choix des variables reste explicite dans le Studio et le Flow.

## Ce que les résultats mesurent

`metrics.clustering` publie les paramètres de lecture suivants :

| Champ | Signification |
|---|---|
| `clusters` | Identifiant, effectif et part de chaque groupe |
| `clusters[].features` | Moyenne, médiane, écart-type et valeurs manquantes, par variable |
| `overall_mean`, `standardized_difference` | Moyenne globale et écart du groupe à celle-ci en unités d’écart-type global |
| `silhouette` | Séparation et cohésion dans l’espace standardisé, sur au plus 2 000 lignes |
| `stability` | Accord ajusté de Rand avec le modèle final après trois ajustements sur des sous-échantillons distincts de 80 % |
| `warnings` | Variables constantes, lignes entièrement imputées, budget d’itérations atteint ou mesure de stabilité partielle |

Les profils sont calculés sur les valeurs observées, dans les unités d’origine ;
les valeurs imputées n’entrent pas dans leurs moyennes ou médianes. Les effectifs
incluent toutes les lignes affectées à un groupe.

Chaque ajustement de stabilité recalcule son imputation et sa standardisation
uniquement sur son sous-échantillon. Les affectations sont comparées sur un même
échantillon fixe, plafonné à 2 000 lignes. L’indice de Rand ajusté ignore les
permutations des identifiants de groupe. Si un sous-échantillon ne permet pas de
retrouver le nombre demandé de groupes, la moyenne de stabilité est indisponible
et le motif est conservé.

La silhouette et la stabilité sont des diagnostics internes, **pas une précision
prédictive mesurée sur un jeu de test**. Une segmentation stable peut rester peu
utile au métier. Aucun seuil universel « bon/mauvais » n’est attribué à ces scores.
Les groupes sont locaux à une version : le groupe 0 d’une version n’est pas
nécessairement le groupe 0 de la suivante.

## Entraînement, service et export

Le formulaire partagé entre Studio et Flow expose la tâche avant la cible, puis
présente le choix des variables numériques et les réglages KMeans. Le plan et
l’entraînement acceptent `target=""`. Les options supervisées ne sont pas
transportées dans cette demande.

La pipeline contient exclusivement les classes sklearn natives `SimpleImputer`,
`StandardScaler` et `KMeans`. MLflow la sérialise en skops, avec les dépendances
épinglées et une signature de doubles acceptant les valeurs manquantes. Chaque
fichier du bundle est empreinté ; le service vérifie l’inventaire complet et les
SHA-256 avant chargement. L’export s’utilise via `mlflow.pyfunc.load_model`, sans
module Agentium ni accès réseau.

Les prédictions et le scoring de dataset réutilisent les contrats de lignes
existants. Une réponse donne un identifiant de groupe, sans probabilité ni
« confiance ». Le scoring produit un nouveau dataset avec sa lignée. Les clés
API et la publication en Skill restent les mécanismes ordinaires de service.

Les retours de vérité terrain, la comparaison supervisée skore, le scoring
fantôme et le réentraînement planifié ne sont pas proposés pour cette famille.
Un nouvel entraînement manuel reste possible. HDBSCAN, les variables
catégorielles/texte, la recherche automatique de K et le nommage LLM des groupes
ne font pas partie de ce lot.

## Qualification et livraison

Les tests réels couvrent les groupes séparables avec valeurs manquantes, la
stabilité après changement d’unité, le recalcul du prétraitement dans chaque
sous-échantillon, les données inutilisables, les plafonds d’échantillonnage et le
rechargement autonome de l’export après suppression du répertoire source.

Le cas Nawa agrège 14 jours de données horaires en une ligne par cellule pour
72 cellules : moyenne des utilisateurs actifs, du PRB, du débit, de la latence,
du taux de coupure et de l’énergie. Cette agrégation est un choix explicite du
jeu de qualification ; l’entraînement ne l’effectue pas automatiquement.
Les mesures observées sont consignées dans
`docs/reports/ml-segmentation-kmeans-qualification.json`. Elles qualifient un
générateur de démonstration et ne constituent pas une validation métier.

Résultat Nawa : trois groupes de **46, 20 et 6 cellules**, silhouette **0,731**
et ARI **1,0** pour les trois sous-échantillons. Les identifiants numériques ne
nomment pas automatiquement ces groupes et ne remplacent pas leur interprétation.

La recette locale valide :

- 13 tests réels du harness et de l’export ;
- 66 contrôles plateforme/API, dont le cycle réel d’entraînement, le rechargement
  après vidage du cache, le scoring de dataset et la publication ;
- 253 contrôles de régression ML, complétés par le rejeu réussi des trois attentes
  historiques actualisées pour reconnaître la nouvelle tâche ;
- 9 contrôles croisés du catalogue et des traductions ;
- 158 tests unitaires frontend et 29 parcours Playwright sur le bundle de
  production, dont 8 scénarios de segmentation FR/EN et les régressions texte,
  embeddings et prévision ;
- compilation Angular, i18n, contrôles UI/navigation et revue backend/frontend.

`build:prod` a été exécuté une seule fois, avec succès. Les derniers ajouts de
libellés du catalogue et la reconnaissance de l’erreur de service
`ML_RUNTIME_MISSING` ont ensuite été vérifiés par la compilation Angular, les
tests unitaires et le contrat croisé du catalogue, sans nouveau build production.
Les avertissements Angular/CSS/budgets et CommonJS préexistants restent présents.

La livraison reconstruit les images applicatives et le frontend sur une même
révision, en conservant les profils déjà actifs. Pour la VM actuelle, garder
`AGENTIUM_ML_TS=1 AGENTIUM_ML_DEEP=1`. Alembic reste à `122_ml_families`.
Le catalogue doit être contrôlé puis réconcilié si sa description d’entraînement
a changé. Le déploiement s’effectue depuis le dépôt de référence Bitbucket.
