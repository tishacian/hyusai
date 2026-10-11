# Qualification technique du pilote Probabl — 11 octobre 2026

Ces preuves diagnostiques concernent un cycle **modèle direct**, sur deux jeux
publics UCI et quatre générateurs synthétiques. Elles ne qualifient ni un coût
API/MLflow/ObjectStore, ni un SLA, ni un gain métier ou énergétique.

La première campagne complète prévue a été interrompue avant le test final :
51 cas terminés, dont 48 évalués et trois refus de parité export/rechargement du
profil TabICL sans cache en régression. Les 57 autres cas ne sont pas évalués.
Le plafond de threads du runtime produit nécessite également une correction.
Ces résultats sont conservés et **ne permettent aucune décision d'adoption**.

Le code exact de cette campagne est conservé au commit `0cf5e01c` : son empreinte
agrégée sur les six fichiers du gel est
`259328f50a3c40c0bd380bd211090ad4d8e763af1760bd6e6dfd771b368a2537`.
Une qualification corrigée doit utiliser un nouveau gel et conserver ces preuves.

- `frozen-protocol.json` : protocole, jeux/licences, partitions, budgets, versions,
  poids et empreinte du code figés avant ces mesures.
- `diagnostic-development.json` : résultats bornés de chaque cas, erreurs,
  mesures CPU, mémoire, artefacts et latences ; empreintes des fichiers source
  complets conservés dans l'espace de qualification.
- `INTERRUPTED.json` : arrêt effectif, réserve finale fermée et comptabilité
  conservatrice du budget restant après les tentatives précédentes.
- `interpretation-limits.json` : limites d'interprétation et coûts non mesurés.
- `environment-inventory.json` : Python et dépendances de l'environnement.

Les rapports sont des preuves versionnées. Ils ne constituent pas un stockage
opérationnel supplémentaire : MinIO/ObjectStore et MLflow gardent leurs rôles.
