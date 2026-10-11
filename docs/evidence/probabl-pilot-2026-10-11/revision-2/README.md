# Qualification technique du pilote — révision 2

Le protocole v2 conserve les jeux, partitions et seuils de v1. Avant ce nouveau
développement, les neuf cas de régression sans cache ont été déclarés non qualifiés
à cause des échecs de parité diagnostiqués. Ils ne sont ni exécutés ni sélectionnables.
La correction du plafond de threads est incluse dans le code gelé (empreinte
`a91abd4c57c0cac31bb03a487e86376088080b55f3627e7c9ef8181ac48e6029`, identique aux six fichiers livrés).

Développement : **97 évalués**, **2 échecs**, **9 exclus**, sur 108 cas annoncés.
Final indépendant : **12 évalués**, **0 échecs** sur 12 prévus.

Échecs de développement conservés : linear-regression-demo/dev-1/tabicl_cache ; friedman-mixed-demo/dev-2/tabicl_cache.
Ces refus de parité export/rechargement empêchent les tâches concernées d’ouvrir leur réserve finale.

Sur **4 comparaisons finales complètes** (2 tâches non évaluées au final),
**0** satisfont tous les seuils techniques de gain de qualité et de coût ;
**0** satisfont les seuils de frugalité CPU, stockage et non-infériorité.
Ces seuils ne constituent ni une validation de production ni une preuve de valeur métier.
Le pilote reste expérimental ; aucune activation globale ne découle de ce rapport.
Indépendamment des seuils par tâche, **toute régression TabICL est refusée côté produit**,
y compris avec cache, après son échec de parité en développement. La classification reste
réservée au pilote manuel. Une éventuelle éligibilité statistique ne lève pas cette restriction.

| Tâche | Gain et IC 95% apparié | Rapport de coût CPU projeté | Seuil qualité | Seuil frugalité |
| --- | --- | ---: | --- | --- |
| breast-cancer | 0.96 [0.00, 2.94] points F1 | 3.56× | non | non |
| iris-multiclass | 0.00 [0.00, 0.00] points F1 | 3.02× | non | non |
| delivery-late-imbalanced-demo | -6.66 [-19.13, 0.40] points F1 | 2.52× | non | non |
| linear-regression-demo | non évalué | — | non évalué | non évalué |
| friedman-mixed-demo | non évalué | — | non évalué | non évalué |
| delivery-cost-mixed-demo | 2.58 [-1.52, 6.42] % réduction MAE | 6.65× | non | non |

Tous les challengers sélectionnés utilisent le cache. Les baselines sélectionnées
sont linéaires, sauf le gradient boosting pour les retards. Un rapport de coût
supérieur à 1 signifie que le challenger consomme davantage de CPU.

| Tâche | Métrique | Baseline | TabICL cache | Lignes finales |
| --- | --- | ---: | ---: | ---: |
| breast-cancer | F1 macro ↑ | 0.97158 | 0.98115 | 114 |
| iris-multiclass | F1 macro ↑ | 0.96658 | 0.96658 | 30 |
| delivery-late-imbalanced-demo | F1 macro ↑ | 0.54978 | 0.48320 | 200 |
| delivery-cost-mixed-demo | MAE ↓ | 1.89031 | 1.84152 | 200 |

Le coût projeté inclut le processus, ses descendants, la sélection/entraînement,
le premier appel, l’export local, l’éviction/rechargement et 100 requêtes de 100 lignes.
Il exclut le chemin API/MLflow/ObjectStore et le second passage de classification
`predict_proba`. Le cache système n’est pas purgé ; aucun p95, SLA ou coût énergétique
n’est qualifié. Les IC95% sont individuels par tâche, sans garantie simultanée sur le corpus.

CPU développement + final mesuré : **2552.41 s**.
Réserves antérieures, distinctes des mesures : **8071.14 s**.
Total imputé : **10623.55 s / 43200 s** ;
restant : **32576.45 s**.

- `development-frozen-protocol.json` et `final-frozen-protocol.json` : gels, poids, versions, partitions et exclusions.
- `development-results.json` et `final-results.json` : chaque cas, y compris erreurs/exclusions, mesures et prédictions finales nécessaires à la reproduction statistique.
- `decision.json` : décision automatique suivant les seuils préenregistrés, sans moyenne de métriques hétérogènes.
- `accounting.json` : consommation et réserves explicites.
- `source-artifacts.json` : SHA256 et tailles des rapports source complets.
- `interpretation-limits.json` et `environment-inventory.json` : portée et environnement.

Traces d'exécution retirées et identifiants normalisés après la campagne, selon
les règles décrites dans le [README parent](../README.md).

Les labels et scores finaux ne doivent pas alimenter la proposition ou le réglage de modèles.
Ces fichiers de preuve n’ajoutent aucun stockage opérationnel à MinIO/ObjectStore et MLflow.
