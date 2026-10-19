# Luma : recette UX du modèle et reprise Work

Recette sur `d95ba09f`, le 19 octobre 2026. Les observations ci-dessous portent
sur les écrans réellement ouverts et les réponses de leurs API. Les éléments
de design proposés ne sont pas présentés comme déjà livrés.

## Parcours réellement vérifié

| Étape | Résultat | Limite |
| --- | --- | --- |
| Réentraînement SLA | V5 prête en 37,5 s, métriques et artefact persistés | Trois doublons de contenu train/test signalés par l'évaluation |
| Play | Prédiction v5 et explication contrefactuelle visibles | Entrées techniques et classes 0/1 encore exposées |
| Contrefactuel | Recherche aboutie sur `case_documents` | Sensibilité du modèle, pas recommandation de modifier les faits |
| Mise en service | Action de la fiche réussie, champion v5 relu en API | Ne met pas automatiquement à jour les versions épinglées des Flows |
| Publication composée | Flow v5, bindings, triage et Work release 4 alignés | Le brouillon Flow conserve ses modifications non publiées |
| Analyse après feedback | 64/64 échantillons, 48 réponses correctes, 75 % | Corpus synthétique équilibré, une requête batch et non 64 enquêtes |
| Surveillance | Mesure native du scheduler enregistrée en 6,53 s, Flow consultable ; cadence quotidienne rétablie | Proposition refusée avec `ML_SPEC_INVALID` ; validation humaine non atteinte. Challenger v2 legacy : shadow indisponible |
| Activités | Entraînement réussi dans le journal et la série horaire | La durée technique ne devient pas un gain humain ni un coût financier |
| Work / file | Application publiée et bindings résolus | PostgreSQL refuse la connexion TLS : aucun dossier chargé |

## Ce qui fonctionne dans la présentation

La fiche sépare l'état d'entraînement, la possibilité d'appeler la version et
son rôle de version sélectionnée. Les actions principales sont compactes. Le
Play affiche la version réellement servie et explique pourquoi le contrefactuel
est utilisé à la place de TreeSHAP. Le rapport « En production » indique le
nombre de lignes utilisées et précise que l'erreur est calculée sur la réponse
conservée, sans refaire la prédiction.

## Corrections de design à prioriser

| Priorité | Observation | Règle de conception et correction générique |
| --- | --- | --- |
| P1 | Le KPI AUC vert domine ; la réserve train/test apparaît sous le premier écran. La description synthétique enregistrée n'est pas rendue. | Mettre la population, la nature des données et les réserves de validation au contact des KPI. La couleur ne doit pas signifier « validé » sans critère explicite. |
| P1 | Le rappel/F1 en tête correspondent au seuil 50 %, alors qu'un seuil 48,7 % est sélectionné plus bas. | Identifier le seuil de chaque mesure, ou présenter les KPI correspondant au réglage servi. Relier score, version et comportement. |
| P1 | Les arbres affichent `paid_amount ≤ 0.404` ou `case_documents ≤ -0.249`, issus de l'espace transformé. | Revenir aux unités d'origine uniquement si la conversion est fiable. Sinon signaler l'espace transformé et réserver les règles à un détail technique. Ne pas donner à ces valeurs l'apparence d'une règle métier. |
| P1 | Work affiche seulement « dossiers indisponibles » alors que le connecteur connaît une cause TLS précise. | Partager le diagnostic fermé entre les lecteurs ; donner une explication et une reprise utile. Réserver la configuration aux utilisateurs autorisés. |
| P1 | Le Run de surveillance est terminé, mais sa proposition est refusée et la validation humaine n'a pas eu lieu. | Distinguer la réussite de la mesure, la décision de proposer et l'issue de la qualification. Rendre le motif du refus visible avant le détail technique du Run. |
| P2 | Les noms de colonnes, classes 0/1 et classes Python de préparation restent très présents. | Prévoir des libellés métier configurables et des listes sémantiques d'étapes lisibles. Conserver les identifiants dans les détails. |
| P2 | Les deltas `+0.004` côtoient des pourcentages ; des zéros signés sont colorés. | Utiliser des points de pourcentage quand pertinent, supprimer le zéro signé et qualifier la comparabilité des partitions avant de suggérer un progrès. |
| P2 | Results accumule préparation, calibration, production, arbres, effets, équité et courbes. | Un résumé « qualité, limites, qualification » doit précéder des sections de preuve repliables. Le lecteur ne doit pas reconstruire seul le verdict. |

Le texte DOM concatène les transformations, tandis que la capture les espace
visuellement : ce défaut concerne la sémantique et le vocabulaire, pas un collage
visuel démontré. Aucun ROI financier n'est affiché dans ces captures de modèle.
Le risque de lecture concerne surtout la provenance des données et la portée
des scores.

## Reprise de la recette métier

Le correctif de diagnostic est préparé et testé dans le dépôt ; il n'est pas
encore déployé lors de cette recette. Il partage les codes fermés avec le
connecteur, propose un bouton Réessayer compact et n'affiche le lien de
configuration que si le serveur accorde `can_configure`. Un consommateur reçoit
une indication pour contacter l'administrateur. Les réponses tardives d'un
autre workspace ou dossier ne remplacent pas le diagnostic courant.

Les sept scénarios ciblés Playwright et quatre tests du normaliseur d'erreur
passent, ainsi que TypeScript et le contrôle du chrome. Les captures desktop
(1 440 px) et mobile (390 px) ont été relues : pas de débordement horizontal ni
de violation Axe dans les états TLS testés. Les 65 tests backend ciblés passent.
Le message brut du pilote reste masqué et la politique TLS reste inchangée.

Après rétablissement PostgreSQL, reprendre depuis Work : file → préparation et
scoring → dossier et sources → enquête agentique → décision humaine → reçu
simulé → activité et Impact. Le présent rapport ne valide pas encore cette
nouvelle exécution complète. Les hypothèses financières convenues restent
séparées des mesures techniques et du corpus de qualification.
