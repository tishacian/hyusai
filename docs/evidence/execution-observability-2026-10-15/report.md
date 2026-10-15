# Qualification locale des runtimes facultatifs

Ce rapport est un instantané historique des candidats A/B, établi avant le raccord du candidat C natif. Ses verdicts et l’absence de port natif décrivent ce corpus A/B ; ils ne constituent pas un verdict sur les travaux C ultérieurs. Le supplément [contrôle, transport et scaffolds](control-and-scaffold/report.md) conserve leurs vérifications distinctes.

Les deux candidats ont exécuté les deux compositions demandées avec un port de qualification déterministe : agent → données → agent → revue → livraison, et données → agent → juge → revue → livraison. Ce port effectue de petites requêtes PostgreSQL et journalise des effets idempotents de test. Il ne soumet aucun Skill natif, n'appelle aucun fournisseur et ne publie aucun DeliveryReceipt de production.

## Résultats bornés

- LangGraph 1.2.15 avec langgraph-checkpoint-postgres 3.2.0 : cinq scénarios passent, avec PostgreSQL réel, reconstruction du graphe/checkpointer, attente humaine, panne avant effet, panne après effet et révocation avant reprise.
- Temporal SDK 1.34.0, temporalio-langgraph 0.1.0, serveur réel 1.32.0 via CLI 1.9.1 : six scénarios passent. Les deux compositions reprennent après reconstruction du worker ; la recette hôte redémarre aussi le serveur pendant l'attente humaine. Les autres cas couvrent révocation, annulation, budget de test et redelivery/identité stable. Aucune Activity Temporal n'est en cours pendant l'attente humaine.
- Le graphe Temporal utilise des Activities par étape et un InMemorySaver. L'historique Temporal constitue l'autorité durable ; aucun deuxième checkpointer PostgreSQL ne pilote ce graphe. Le candidat LangGraph autonome utilise son checkpointer PostgreSQL.
- Une image dédiée, séparée des images et requirements principaux, exécute le même corpus mécanique sous 512 MiB / 1 CPU, utilisateur 1000, racine en lecture seule, capabilities supprimées. Cette recette image ne redémarre pas le serveur : ce cas est couvert par la recette hôte. Taille et méthode exactes figurent dans image-metadata.json ; il ne s'agit ni d'une mesure VM ni d'une certification du budget des images principales.

Les durées et RSS sont celles de ce petit corpus local. Elles ne constituent ni un SLA, ni un benchmark de DataOps/ML, ni une mesure de la consommation totale serveur + PostgreSQL + client.

## Verdicts

- **Candidat LangGraph autonome : NO-GO production.** Son raccord au dispatch durable et à la récupération native n'est pas qualifié. Les composants natifs existants peuvent servir à ce raccord ; cette qualification ne démontre pas la nécessité d'un nouveau scheduler.
- **Candidat Temporal + LangGraph : NO-GO production.** L'intégration officielle utilisée est en Public Preview ; le corpus complet des effets, interruptions, contraintes IAM et ressources natives reste à qualifier.
- **O5 : ouvert / NO-GO.** Aucun port de soumission natif idempotent n'est livré. L'API Protocol est typée ; l'absence d'adaptateur échoue fermée. Les lectures natives Run/Recipe/Compute/ML vérifient workspace, parent Run, acteur actif et contrat/version/digest gelés ; elles n'inventent pas de succès.
- **Comparaison A/B/C : NON FAITE à corpus identique.** Les 138 tests historiques du moteur natif cités par le parent ne sont pas une exécution comparative de ce corpus et ne prouvent aucune supériorité A ou B.

## Traçabilité

manifest.json contient commandes, contexte local, empreintes des sources et des preuves. mechanics-final.json/log correspond à la recette hôte avec redémarrage du serveur ; mechanics-image.json/log correspond à la recette dans l'image dédiée. dependencies-lock.json garde les versions, URLs publiques et empreintes de distributions installées (projection bornée du rapport pip, dont l’empreinte originale est conservée) ; le wheelhouse hors dépôt permet le build sans résolution réseau. temporal-version.log confirme les versions CLI/serveur. Les scénarios injectent volontairement des erreurs ; leurs traces ne contiennent que les fixtures jetables.

Le port de qualification, les fichiers SQLite du serveur de test et les identifiants PostgreSQL employés sont exclusivement locaux et jetables. Ils ne donnent aucun accès de production. Le conteneur PostgreSQL partagé avec les autres tests est conservé ; la suppression des schémas générés est vérifiée à la fin de chaque recette.

## Vérifications supplémentaires

Les trois fichiers PostgreSQL dédiés (foundation, execution_control et revue) passent ensemble : **11 tests, aucun skip, 28,96 s**. Le test de chaîne tabulaire exécute réellement les migrations sur PostgreSQL 17.11 via psql et Alembic : **27 tests, aucun skip, 351,89 s**, dont upgrade de 134, comparaison ORM et downgrade/re-upgrade. Seules les révisions hors plan tabulaire 121 et 133 sont estampillées ; le garde AST vérifie que cette sélection ne saute pas de mutation tabulaire.

Le contrôle officiel `scripts/agentium_compliance.py --check` passe : **16/22 claims vérifiés statiquement**, sans attestation runner ou déploiement. Il ne vaut pas qualification de production. Commandes, résultats et empreintes complémentaires figurent dans `validation.json` et `manifest.json`.
