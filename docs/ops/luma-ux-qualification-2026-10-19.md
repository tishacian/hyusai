# Luma : recette UX du modèle et reprise Work

Recette sur `d95ba09f`, complétée après déploiement de `945013ac` et `718c99bf` le 19 octobre
2026. Les observations ci-dessous portent
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
| Surveillance | Après `945013ac`, mesure native réussie et proposition créée ; Flow arrêté sur validation humaine, cadence quotidienne rétablie | Proposition non approuvée ; challenger v2 legacy : shadow indisponible |
| Activités | Entraînement réussi dans le journal et la série horaire | La durée technique ne devient pas un gain humain ni un coût financier |
| Work / file | Après `718c99bf` et choix explicite sans chiffrement, trois dossiers et leurs sources chargés ; 23 dossiers préparés et scorés | Réexamen RC-1042 arrêté à la validation humaine, aucune nouvelle action exécutée |

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
| P1 | L'approbation du réentraînement présente UUID, empreinte et JSON avant les actions ; le bouton Approuver apparaît vers 1 510 px dans une fenêtre de 1 000 px. | Présenter d'abord le modèle, les populations utilisées, le changement proposé et son effet. Replier les preuves techniques et conserver un accès clair aux actions, sans masquer la portée de l'approbation. |
| P2 | Les noms de colonnes, classes 0/1 et classes Python de préparation restent très présents. | Prévoir des libellés métier configurables et des listes sémantiques d'étapes lisibles. Conserver les identifiants dans les détails. |
| P2 | Les deltas `+0.004` côtoient des pourcentages ; des zéros signés sont colorés. | Utiliser des points de pourcentage quand pertinent, supprimer le zéro signé et qualifier la comparabilité des partitions avant de suggérer un progrès. |
| P2 | Results accumule préparation, calibration, production, arbres, effets, équité et courbes. | Un résumé « qualité, limites, qualification » doit précéder des sections de preuve repliables. Le lecteur ne doit pas reconstruire seul le verdict. |
| P2 | Les champs numériques du monitoring sont moins hauts et moins délimités que les sélecteurs voisins. | Unifier hauteur, bordure et focus pour que tous les champs éditables soient identifiables. |
| P2 | Le suivi indique une fréquence active sans afficher immédiatement la dernière mesure et la prochaine échéance. | Présenter ces deux repères avec leur fuseau dans le résumé de planification. |
| P2 | L'historique et le contexte affichent « Prédictions : 3 / Issues réelles : 64 ». | Distinguer appels et lignes : trois appels ont servi 66 lignes, dont 64 annotées. Ne pas laisser entendre qu'une même unité est utilisée. |

Le texte DOM concatène les transformations, tandis que la capture les espace
visuellement : ce défaut concerne la sémantique et le vocabulaire, pas un collage
visuel démontré. Aucun ROI financier n'est affiché dans ces captures de modèle.
Le risque de lecture concerne surtout la provenance des données et la portée
des scores.

## Reprise de la recette métier

Le correctif de diagnostic, préparé et testé lors de la première recette, est
confirmé en service sur `945013ac`. Il partage les codes fermés avec le
connecteur, propose un bouton Réessayer compact et n'affiche le lien de
configuration que si le serveur accorde `can_configure`. Un consommateur reçoit
une indication pour contacter l'administrateur. Les réponses tardives d'un
autre workspace ou dossier ne remplacent pas le diagnostic courant.

Les sept scénarios ciblés Playwright et quatre tests du normaliseur d'erreur
passent, ainsi que TypeScript et le contrôle du chrome. Les captures desktop
(1 440 px) et mobile (390 px) ont été relues : pas de débordement horizontal ni
de violation Axe dans les états TLS testés. Les 65 tests backend ciblés passent.
Le message brut du pilote reste masqué et la politique TLS reste inchangée.

La nouvelle recette live confirme une carte Work cohérente avec le chrome,
des actions compactes et une disposition lisible à 390 px. Le diagnostic est
visible en français et en anglais ; « connexion chiffrée (TLS) » serait un
libellé plus explicite pour le SAV. La recette live utilise un administrateur :
le cas consommateur demeure couvert par les tests d'interface.

Après `945013ac`, la fiche modèle expose « Validation humaine attendue » et
le lien vers le Run `3c758903-0f2b-4923-81e3-138e61f626e1`. Le bouton Approuver
est disponible mais n'a pas été activé. Le contexte est consultable ; sa densité
technique reste excessive pour une décision courante, et la question générée
reste en anglais dans l'interface française. Les deux observations P1 initiales
sur Work et la proposition refusée sont corrigées fonctionnellement ; les
autres recommandations de design ne sont pas présentées comme livrées.

La lecture du Flow exécuté et ses états sont vérifiés par API et navigateur.
Le navigateur de recette utilise un relais HTTP local : son message de
reconnexion ne permet pas de conclure sur le transport SSE en accès direct.
Le suivi temps réel n'est donc pas qualifié par cette capture.

Après rétablissement PostgreSQL, reprendre depuis Work : file → préparation et
scoring → dossier et sources → enquête agentique → décision humaine → reçu
simulé → activité et Impact. Le présent rapport ne valide pas encore cette
nouvelle exécution complète. Les hypothèses financières convenues restent
séparées des mesures techniques et du corpus de qualification.

## Recette après rétablissement PostgreSQL sur `718c99bf`

Le propriétaire du workspace a le droit de modifier la connexion, contrairement
au compte opérateur signalé lors du déploiement. La fiche PostgreSQL montre le
mode enregistré, le test réussi et un aperçu réel de 23 lignes. Le parcours Work
affiche maintenant les liens vers les datasets préparé/scoré, le modèle v5 et
le Flow Luma. Les priorités sont visibles dans la file puis recalculées sur le
dossier lors de l'enquête.
Le panneau du bordereau s'ouvre depuis le dossier et retrouve son passage cité
(réponse 200), avec page et collection : le code postal 75012 du transporteur
est consultable face au 75011 de la commande.

Le réexamen RC-1042 arrive à la validation humaine, avec huit étapes métier
terminées et une proposition motivée. Les captures desktop de 1 440 px et mobile
de 390 px ont été relues ; aucun débordement horizontal. Sur mobile, la décision
précède le détail du dossier et le parcours technique descend en bas de page.
Le résumé de décision reste accessible, mais les preuves demandent davantage
de défilement.

Deux observations précises :

- Après un test PostgreSQL réussi, le message « Configuration enregistrée. La
  connexion reste à tester » coexistait avec « Connexion vérifiée ». Le correctif
  générique efface ce message dès le début du test. Les deux scénarios existants
  FR/desktop et EN/mobile passent avec l'assertion de disparition ; ce petit
  correctif frontend est livré après `718c99bf` et reste à déployer.
- Le réexamen présente la nouvelle proposition à côté d'« Action enregistrée »,
  qui concerne le reçu historique du 2 octobre. La date et l'explication sont
  présentes, mais la hiérarchie laisse une ambiguïté. Pour un prochain ajustement
  générique, identifier explicitement l'action antérieure et distinguer son
  historique de la décision en cours. Aucun deuxième reçu n'a été créé ici.

Le Run d'enquête reste en attente d'approbation. Cette recette valide la reprise
des données et le parcours composé jusqu'à la décision, pas une action métier
supplémentaire ni un gain financier mesuré.

La vue Flow exécuté confirme les étapes réussies et le gate en attente. Elle
reste trop dense en valeurs « Indisponible » ; deux liens exposent les clés
`observability.activities.link.invocation` et `observability.activities.link.activity`
au lieu de libellés traduits. Le message de reconnexion SSE provient du même
relais de recette mentionné plus haut et ne qualifie pas le transport direct.
