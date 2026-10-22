# Qualité, campagnes et usage IA — livraison du 22 octobre 2026

Cette livraison ajoute des fonctions produit partagées par tous les workspaces. Luma les consomme par configuration. Elle ne crée ni carte Luma imposée, ni résultat de qualité, ni économie réalisée.

## Parcours produit

- **Run → Résultat / Exécution / Qualité / Usage et coûts**. Les vues Qualité lisent les évaluations conservées et réautorisent leurs preuves. Un échec technique du Judge reste « non évalué ». Le contrôle embarqué, la revue humaine et la qualification statistique sont distincts.
- **Observabilité → Qualité → Suivi / Tests / Revue humaine**. Éditer des cas et des assertions sans JSON, examiner le préflight, comparer les versions, puis retrouver les Runs et les preuves. L'absence d'assertion ne vaut pas réussite. La revue de calibration est aveugle et impose des annotateurs indépendants.
- **Observabilité → Usage et coûts**. Filtrer la période, le système, la population et le fournisseur ; examiner jetons, sous-totaux tarifés, couverture, appels et réservations. Les devises ne sont pas additionnées. Les montants calculés ne sont pas des factures.
- **Impact → Personnaliser**. Ajouter « Qualité des traitements » et « Usage IA et dépenses », choisir la population métier/essais/toutes, le système et l'ordre des blocs, puis enregistrer la vue. Aucune vue sauvegardée n'est modifiée automatiquement.

Le détail historique ne déclenche aucun appel LLM. Les campagnes sont informatives : elles ne publient pas un Flow, ne valident pas une décision humaine et n'ajoutent pas de verrou de publication.

## Déploiement

1. Sauvegarder la base et les volumes. Suspendre les nouveaux lancements et laisser finir/arrêter proprement les écrivains selon le runbook de déploiement existant.
2. Appliquer Alembic jusqu'à **`146_model_usage_budgets`**. `145_evaluation_isolation` ajoute la provenance des campagnes aux Runs, datasets, préparations et prédictions. `146` crée le journal d'appels, les tarifs versionnés, les politiques et réservations budgétaires. Aucun historique d'appels fournisseur n'est reconstruit.
3. Recréer l'API, le frontend et tous les processus qui peuvent appeler un modèle : workers CPU, DataOps, ingestion/recherche, runner de connecteurs, ainsi que les autres workers déployés sur cette image. Drainer les sessions LiveKit existantes et recréer l'agent LiveKit avant d'attester le déploiement. Recréer beat/scheduler selon la procédure habituelle. `AGENTIUM_IMAGE_REVISION` doit être le SHA Git complet effectivement servi, en minuscules.
4. Vérifier readiness et lecture des nouvelles routes avec le compte workspace autorisé. Aucun plafond n'est activé par la migration. La comptabilité commence avec les appels instrumentés après cette livraison.
5. Conserver les options déjà actives. Les alertes externes, l'import, la rétention, les webhooks et les plannings restent sous leur configuration existante.

Ne pas rejouer l'installation Luma. Relever et comparer avant/après la révision du brouillon, le hash publié, les bindings, le champion et le shadow. Les nouveaux tests possèdent leur propre provenance ; ils ne doivent pas alimenter la file métier, les jeux de données Work ou la surveillance du modèle servi.

## Activation explicite des budgets

Les limites suivent le mois calendaire dans le fuseau choisi (`UTC` par défaut), au niveau workspace et application racine. La première période commence à l'activation : elle ne reprend pas les appels antérieurs. Le fuseau devient immuable après cette activation. La consommation des sous-Runs est imputée à leur application racine ; les appels autonomes sans application identifiée relèvent du seul plafond workspace. Les deux limites applicables sont vérifiées simultanément ; modifier, désactiver puis réactiver une limite ne remet pas le compteur à zéro. La consommation continue d'être suivie pendant une pause.

1. Déclarer les tarifs du fournisseur et du **nom exact du modèle demandé** dans Usage → Tarifs. Saisir entrée/sortie par million, devise, et les tarifs de cache applicables. Une nouvelle version ne revalorise pas les appels historiques. Utiliser les tarifs contractuels, sans inventer un taux de change.
2. Vérifier l'ensemble des processus. Un administrateur du workspace déclare ensuite le déploiement via `POST /api/v1/observability/usage/readiness/attest`, avec `revision`, `components` (`api`, `cpu_worker`, `dataops_worker`, `connector_runner`, `livekit_agent`) tous au même SHA et `all_workers_recreated: true`, `livekit_sessions_drained: true`. Cette trace est une **attestation opérateur**, pas une découverte automatique de la flotte. `GET /api/v1/observability/usage/readiness` expose cette base et les transports qualifiés.
3. Dans Usage → Budgets, choisir workspace/application, fuseau, plafonds de jetons et/ou montants par devise. Enregistrer désactivé pour revue, puis activer explicitement. Aucun montant par défaut n'est fourni par le produit.
4. Sur un périmètre de recette, vérifier un appel admis puis un appel refusé avant envoi. Vérifier que les essais QA et les embeddings sont eux aussi comptés et que le refus apparaît dans le journal. Ne pas épuiser volontairement le budget de l'activité métier.

Les écritures de tarifs, budgets et attestations sont réservées aux administrateurs du workspace. Pour automatiser la configuration, `POST /api/v1/observability/usage/budgets` attend `scope: "workspace"` ou `"system"` (avec `system_id`), `enabled`, `timezone`, `max_tokens` et/ou `currency_limits`, ainsi que `expected_revision` : `0` à la création, puis la révision lue dans `GET /budgets`. Les montants sont des chaînes décimales indexées par devise, sans conversion. Une révision dépassée est refusée ; relire la politique avant modification.

La réservation précède chaque tentative fournisseur et partage la transaction des garde-fous natifs applicables. Les SDK ne doivent pas réessayer invisiblement sous une réservation. Tout plafond actif exige un transport et des bornes qualifiés. Un plafond monétaire exige aussi un tarif enregistré et une limite pour sa devise ; un plafond portant uniquement sur les jetons peut fonctionner sans tarif, avec un coût affiché inconnu. Le plafond porte sur les tarifs enregistrés et les bornes d'admission ; il ne garantit pas une facture fournisseur comprenant des éléments non représentés par ces tarifs. Si le tarif distingue le cache mais que le fournisseur ne rapporte pas ce détail, le coût reste inconnu et sa réservation reste engagée.

Les nouvelles sessions LiveKit et OpenAI Realtime sont refusées lorsqu’un plafond workspace ou application est actif : leur transport LLM continu n’a pas de borne qualifiée. Les sessions préexistantes doivent être drainées avant l’attestation. Les services audio STT/TTS seuls restent hors du suivi et du budget LLM ; ils ne sont pas présentés comme une dépense incluse.

Un envoi dont l'issue reste inconnue conserve sa réservation. Un rafraîchissement, une relance ou une pause de budget ne l'efface pas. Le journal montre les appels concernés ; ne pas libérer une réservation sans preuve fournisseur. Une mise à jour du SHA invalide l'attestation précédente : réattester après contrôle de la flotte avant de reprendre les appels sous plafond.

Cette livraison ne propose pas d'interface ni d'API administrateur de libération manuelle ou d'import de facture. Des mesures tardives peuvent compléter un appel via le service de règlement interne. Un dépassement de la réservation met la politique en état `reconciliation_required` et bloque les nouvelles admissions ; il ne se résout pas en augmentant simplement le plafond. Une reprise après pause est également refusée si des appels non mesurés n'ont aucune enveloppe conservée.

Les lectures respectent les droits sur les Runs, systèmes et jobs. Le détail des jobs d'ingestion `WorkerJob` et les consommations partagées des budgets sont actuellement réservés aux administrateurs. Les projections Usage sont limitées à 20 000 appels visibles : lorsque `coverage.complete` vaut `false`, leurs sous-totaux sont incomplets. Les séries sont regroupées en UTC, même si le budget suit un autre fuseau. Un filtre `run_id` consulte l'historique conservé de ce Run indépendamment de la fenêtre ; `run_scope: "tree"` inclut ses sous-Runs autorisés, sans double comptage.

## Recette attendue après mise en service

1. Ouvrir un ancien Run avec plusieurs évaluations : vérifier les états séparés, les preuves exactes et les révocations. Les anciens compteurs absents restent inconnus.
2. Exécuter un nouveau dossier puis un nouveau contrôle ; retrouver leurs appels, jetons, cache/raisonnement lorsque rapportés, tarif et liens de provenance. Aucun double comptage entre Run parent et sous-Runs.
3. Créer une suite et examiner son préflight. Les effets non qualifiés sont refusés avant lancement. Une campagne admissible s'arrête à la frontière humaine ; aucun remboursement ou envoi métier n'est exécuté.
4. Comparer l'activité métier et la population QA. Les datasets et prédictions QA demeurent consultables dans le contexte de test, sans être promus en données opérationnelles.
5. Ajouter les deux blocs génériques à une vue Impact de recette. Vérifier sa période, ses populations, ses liens et la conservation des autres vues.
6. Faire réaliser les annotations et arbitrages par les personnes habilitées. Les cas exportés depuis un résultat déjà examiné sont **dev-only**, pas un nouveau holdout indépendant.

L'exécution en service des campagnes, la facturation fournisseur et les annotations humaines ne peuvent pas être validées par les tests locaux. Le rapport de livraison doit distinguer ces étapes des tests automatisés et de la recette navigateur sur réponses contrôlées.
