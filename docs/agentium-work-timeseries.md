# Work : historique, prévision et incertitude

Le composant certifié `chart` possède un type `timeseries`, configuré dans
Studio : sélectionner le graphique, **Contenu → Type de graphique → Historique
et prévision**. Choisir les colonnes date, prévision, observation, bornes basse et
haute, série et unité. Les champs observation, bornes et série sont facultatifs ;
laisser leur mapping vide si la colonne n’existe pas. Les deux bornes doivent être
configurées ensemble.

Deux sources sont disponibles :

- **Résultat lié (lignes)** : choisir la sortie d’une action ou d’un binding dans
  l’onglet Action, puis le chemin d’un tableau de lignes ou d’un objet `{rows}`.
- **Dataset produit par une exécution** : choisir l’action productrice de la même
  page et le chemin `dataset_id` dans son résultat. Le serveur résout lui-même la
  référence enregistrée dans le Run ; le navigateur ne fournit aucun dataset ID.

Le chart reprend `ck-forecast-chart` du Model Center. Les observations et
prévisions partagent une échelle, les valeurs absentes restent des trous, et une
bande est dessinée uniquement lorsque ses deux bornes sont valides. Une liste
sélectionne la série ; une table dépliable donne les valeurs accessibles. Une vue
partielle signale toute troncature, ligne invalide, date dupliquée ou intervalle
invalide. Aucun point manquant n’est remplacé par zéro.

## Configuration d’un graphique sur dataset

```json
{
  "type": "chart",
  "id": "demand-chart",
  "props": {
    "title": "Charge prévue",
    "kind": "timeseries",
    "datasetSource": {
      "source": "run-output",
      "componentId": "forecast-action",
      "selector": "dataset_id"
    },
    "mapping": {
      "time": "ds", "value": "forecast", "actual": "actual",
      "lower": "lower", "upper": "upper", "series": "channel"
    },
    "unit": "dossiers",
    "maxRows": 1000
  }
}
```

`forecast-action` doit être une action ou un composant de requête publié dans
la même page. Le chart utilise une seule source : `datasetSource` exclut
`dataBinding` et `queryBinding` sur ce chart. L’éditeur retire l’ancienne source
lors du changement. Les brouillons incomplets peuvent être enregistrés ; le
ready-check bloque leur publication avec la configuration à corriger.

Pour réunir historique et futur, le Flow doit produire un dataset contenant les
lignes observées (`actual`, prévision nulle) et prévues (`forecast`, observation
nulle). Des observations reçues après la prévision peuvent partager leur date.
Le chart n’infère ni actuals, ni associations de prévisions, ni métrique métier.
Le suivi des actuals et les preuves de backtest restent dans Model Center.

## Accès et limites

`GET /work/{slug}/datasets/{page_id}/{component_id}?run_id=…` utilise les mêmes
gardes d’accès à Work et sa release publiée, puis vérifie :

1. workspace et droit `run.read` ;
2. identité de l’application, release courante, binding, System, page et action ;
3. Run terminé ;
4. référence de dataset extraite du résultat, dataset prêt et créé par ce Run ;
5. colonnes explicitement autorisées par la configuration publiée.

Les références provenant d’une autre application, release, workspace ou d’un
autre Run sont refusées. Un upload indépendant ou un dataset simplement cité
par l’agent ne devient pas lisible via ce bloc.

La projection lit au plus **1 000 lignes et 8 colonnes** en Parquet. Les objets
distants utilisent des lectures seekable/range ; aucun téléchargement intégral
n’est nécessaire. Les premières lignes sont sélectionnées dans l’ordre du
fichier ; le producteur doit donc borner et ordonner son dataset de restitution.
Le rendu se limite à 12 séries. Ce bloc est une vue bornée, pas un explorateur
analytique de millions de lignes.

La réponse expose version et nom du dataset, Run, dates de production et modèle
résolu depuis la lineage du dataset dans le même workspace. Le graphique montre
la fraîcheur et fournit des liens vers le dataset et le modèle. Les résultats
précédents sont retirés dès qu’une nouvelle exécution démarre.

## Vérifications

- `backend/app/tests/services/test_work_datasets.py` : accès croisés, provenance,
  autorisations, release/action, configuration, projections bornées locales et
  distantes, route et ready-check.
- `frontend-ng/src/app/features/experience/runtime/timeseries.spec.ts` : alignement
  temporel, gaps, intervalles, doublons, mappings, limites de lignes/séries.
- Les tests du runtime et du Studio conservent barres/anneaux et bindings existants.


### Recette navigateur locale du 9 octobre 2026

`e2e/tests/33-work-ml-blocks-mocked.spec.ts` exécute les composants réels Angular
avec API isolées sur HTTP localhost, Chromium et `ignoreHTTPSErrors: false`.
Huit scénarios passent : desktop sombre FR, desktop clair EN, mobile clair FR
(390 px), refus du dataset, dataset vide, mauvaise version de modèle, données
partielles et configuration Studio persistée puis rechargée. Le score est lu
depuis l’invocation du node configuré, distincte du résultat final du Run.

Le parcours clavier déclenche l’action, ouvre/ferme la table et conserve la
navigation entre pages. Axe ne relève aucune violation sur le runtime dans les
trois variantes visuelles. Les captures ont été inspectées : bande d’incertitude,
axes espacés, sources, champs Studio, focus visible et absence de débordement.
Les commandes ont une largeur intrinsèque (155 × 32 px pour le libellé testé) ;
les actions de l’en-tête Work reviennent à la ligne sur mobile.

Cette recette ne remplace pas un essai du déploiement avec ses données réelles.
Les contrôles d’autorisation du serveur sont couverts séparément par les tests
backend ; les scénarios navigateur vérifient leur restitution, sans prétendre
prouver l’autorisation à partir d’une réponse simulée.
