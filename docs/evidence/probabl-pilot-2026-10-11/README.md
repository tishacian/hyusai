# Qualification technique du pilote Probabl — 11 octobre 2026

Ces preuves diagnostiques concernent un cycle **modèle direct**, sur deux jeux
publics UCI et quatre générateurs synthétiques. Elles ne qualifient ni un coût
API/MLflow/ObjectStore, ni un SLA, ni un gain métier ou énergétique.

La première campagne complète prévue a été interrompue avant le test final :
51 cas terminés, dont 48 évalués et trois refus de parité export/rechargement du
profil TabICL sans cache en régression. Les 57 autres cas ne sont pas évalués.
Le plafond de threads du runtime produit nécessitait également une correction,
incluse depuis dans la révision 2.
Ces résultats sont conservés et **ne permettent aucune décision d'adoption**.

La [qualification terminée sous protocole v2](revision-2/README.md) conserve ces
preuves et présente séparément ses exclusions, ses échecs et son test final.

L'empreinte agrégée du code de cette campagne sur les six fichiers du gel est
`8a0878cf988e99992e07520268bcd4ccf02d630749185a081925e0d5f8511d03`.
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

Les traces d'exécution (lignes de commande, chemins et piles d'appels) ont été
retirées après la campagne : seuls les résultats, mesures et messages d'erreur
sont publiés. Les identifiants de schéma et d'architecture ont été normalisés,
puis les empreintes du contrat, du code et des artefacts publiés recalculées en
conséquence. Les empreintes `source_results_sha256` désignent les rapports
complets bruts, non publiés.

Les rapports sont des preuves versionnées. Ils ne constituent pas un stockage
opérationnel supplémentaire : MinIO/ObjectStore et MLflow gardent leurs rôles.
