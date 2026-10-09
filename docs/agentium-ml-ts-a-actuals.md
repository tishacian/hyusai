# Séries temporelles A — Prévisions face aux valeurs réalisées

La carte d’un modèle de prévision dispose d’un suivi distinct de son backtest.
Un administrateur associe un dataset de réels de son workspace. L’association
est fixée à une version, ou suit les nouvelles versions prêtes de la même lignée
si l’administrateur coche cette option. Le modèle conserve les noms de colonnes
(date, cible et séries) de sa spécification.

`POST /ml-models/{id}/monitoring/actuals` reçoit `dataset_id` et `follow_latest`.
`GET /ml-models/{id}/monitoring` ajoute `forecast_actuals` : provenance, métriques
globales, par série et par pas d’horizon, anomalies et limites de la mesure.
L’association est enregistrée dans `params_json.mlops.forecast_actuals` ; aucune
migration n’est nécessaire. Les droits de lecture et d’administration existants
s’appliquent. La carte affiche les erreurs codées et attend la réponse serveur
avant d’annoncer une association enregistrée.

## Mesure

Une observation est identifiée par sa série et son instant UTC. Une prévision
n’est admissible que si son appel a été émis avant cet instant, désormais passé.
La première prévision admissible conservée pour chaque série, instant et pas
d’horizon compte une fois. Les appels après l’échéance, les points encore futurs
et les répétitions sont comptés séparément. Une date sans fuseau signifie UTC.
Les cibles non numériques ou non finies, les doublons et les identifiants de
série ambigus sont refusés.

La MAE, la RMSE et la sMAPE décrivent les points appariés. La couverture et la
largeur moyenne portent sur les intervalles dont le niveau demandé est connu.
Ce niveau et le pas d’horizon sont désormais journalisés pour les appels API
et Flow. Les anciens appels sans niveau connu contribuent aux erreurs uniquement.
Un réalisé hors intervalle apparaît dans l’aperçu des anomalies.

Le signal de couverture commence à 20 intervalles évalués : surveillance à
10 points sous la couverture nominale moyenne, alerte à 20 points. Il n’est pas
comparé à un score de backtest obtenu sur d’autres lignes.

La fenêtre conserve au plus 400 appels, 64 points par appel et 200 groupes ;
l’aperçu montre 40 anomalies. Les grands panels peuvent donc être partiellement
représentés et la carte l’indique. Les fichiers sont limités à 100 000 lignes,
32 MiB stockés et 128 MiB décompressés selon leurs métadonnées Parquet. Les
imports scientifiques restent hors du chargement des routes API.

## Réentraînement et livraison

Le service fournit un snapshot liant modèle, version du dataset, empreinte du
fichier et fenêtre des prévisions. La construction d’un historique fusionne les
observations passées avec le train initial, conserve toutes les covariables et
refuse les conflits. Le volet B utilisera cet historique pour une proposition
soumise à approbation humaine.

Livrer depuis Bitbucket sur la VM habituelle après synchronisation. Reconstruire
backend, workers ML concernés et frontend ; aucune nouvelle dépendance. Les
anciens modèles restent utilisables. Émettre une prévision avant son échéance,
associer ensuite les réels et vérifier ses erreurs, sa couverture et sa série.

## Qualification frontend

- 89 tests ciblés passent, dont autorisation, double soumission, changement de
  modèle/workspace, refus serveur et présentation des métriques.
- Quatre parcours navigateur FR/EN passent : association, suivi des versions,
  erreurs/intervalle/anomalies, lecture seule et refus serveur.
- Compilation Angular sans émission, i18n, contrôles UI et navigation passent.
- Le build production unique passe ; les avertissements Angular, CSS, budget
  initial et dagre préexistants restent présents.
- 110 tests backend de régression passent, puis 34 tests spécifiques finaux
  (24 service, 10 API) : droits, isolation, dates, empreintes, fichiers corrompus,
  journal API et historiques single/panel/multivariés.
