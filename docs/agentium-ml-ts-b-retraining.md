# Séries temporelles B — Surveillance et réentraînement approuvé

Une version prête de prévision peut utiliser le Flow de surveillance du lot 5.
L’administrateur associe d’abord les réels, puis active la fréquence et, s’il le
souhaite, les propositions de réentraînement. Le Flow mesure la couverture
observée et conserve un snapshot. Une alerte sur le champion peut produire une
proposition, sans lancer d’entraînement avant la décision humaine.

## Données examinées et entraînées

La proposition fige la mesure, l’association choisie, la version et l’empreinte
des réels, ainsi que celles de l’historique initial. Son nouveau dataset réunit
l’historique initial et les observations passées supplémentaires. Les valeurs
contradictoires et les covariables manquantes sont refusées. Les horizons,
retards, covariables, options et réglages du modèle source sont conservés.
Le modèle de prévision valide cet historique avec ses propres règles de longueur,
fréquence et backtest, sans convertir les données en régression aléatoire.

La porte HITL existante montre la couverture figée, les erreurs, les séries,
le nombre de nouvelles observations et l’historique qui sera entraîné. Elle
réutilise les droits canoniques de l’exécution. Un lecteur voit la preuve sans
pouvoir approuver. Un refus, une expiration ou une acceptation automatique
ne permettent pas le fit.

À l’approbation, puis avant le fit, le serveur vérifie les versions et octets
des deux sources et du dataset figé. Une nouvelle version suivie ultérieurement
ne modifie pas une proposition déjà créée. Changer l’association explicite ou
les octets d’une source invalide cette proposition.

L’entraînement rejoint la file de la famille `forecasting` et son worker
`ml-ts`. La récupération existante conserve ses baux et sa prise en charge
unique du fit. Le résultat est un challenger ; une promotion explicite reste
nécessaire. La suppression du modèle surveillé arrête sa planification en
conservant les preuves et l’historique.

## Livraison et qualification

Intégrer après TS-A. Aucune migration ni dépendance supplémentaire. Reconstruire
backend, worker, ml-ts et frontend depuis Bitbucket, redémarrer le beat et
réconcilier le catalogue pour actualiser les descriptions des deux Skills.

- 63 tests backend ciblés passent avant la recette du fit réel.
- Les 12 scénarios TS finaux passent : historique figé, modifications des sources,
  suivi des nouvelles versions, déduplication, arrêt du cron, gate réel et fit
  skforecast/MLflow après approbation humaine. Refus et approbation automatique
  n’entraînent aucun modèle.
- Ce fit révèle et couvre un défaut ancien : une cible nommée `value` entrait
  en collision avec une colonne temporaire du backtest. Celle-ci est désormais
  choisie sans collision, indépendamment du nom de cible ou de série.
- 16 parcours navigateur passent : 12 régressions tabulaires et quatre parcours
  de revue des prévisions FR/EN, approbation, lecture seule et refus.
- La revue indépendante ne relève aucun blocage de provenance, droits ou routage.
