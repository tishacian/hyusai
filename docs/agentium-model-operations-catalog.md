# Model Operations : catalogue et activation

Les Skills `ml_monitor_model_v1` et `ml_retrain_model_v1` disposent de wrappers
et de contrats installés. Sans Capability porteuse, le catalogue les classe
`unclaimed` : la palette ne les propose pas et leur fiche répond 404.

La Capability universelle **Model Operations** (`model_operations`) les porte
pour les modèles tabulaires et les prévisions. Elle ne dépend d'aucun secteur,
client ou workspace et ne déclare ni coût forfaitaire ni valeur financière.
Les deux Skills conservent leur certification `beta`.

## Configuration utilisateur

1. Ouvrir **Model Center**, sélectionner la version prête d'un modèle compatible,
   puis **Monitoring**.
2. Configurer la fréquence de surveillance et l'émission éventuelle de
   propositions de réentraînement avec les droits d'administration requis.
3. Inspecter le Flow géré : surveillance, branchement, revue humaine,
   entraînement du challenger. Les fiches des deux Skills sont maintenant
   consultables dans le catalogue et depuis ce Flow.
4. Examiner une proposition dans le parcours HITL avant d'approuver son
   entraînement. La promotion du challenger reste une décision distincte.

La visibilité dans la palette n'autorise pas l'exécution arbitraire de ces
Skills. Ils exigent toujours la liaison modèle/politique/Run du Flow géré et,
pour le réentraînement, la proposition et la décision humaine correspondantes.
Ajouter seul un nœud depuis la palette ne configure pas une politique valide.

Les paramètres de curation restent prioritaires : `show_universal: false`
masque cette Capability ; `hidden_capabilities` et `hidden_skills` conservent
leurs effets. Un administrateur peut rendre uniquement **Model Operations**
visible via la curation du catalogue, sans ouvrir les autres Capabilities
universelles. La réconciliation ne modifie aucune de ces préférences et
n'accorde aucun droit d'administration ou d'approbation.

## Déploiement

Aucune migration ni nouvelle dépendance. Après livraison du backend, utiliser
le déploiement existant sur la VM :

```sh
agentium-vm-deploy.sh catalog-check
agentium-vm-deploy.sh catalog-apply
agentium-vm-deploy.sh catalog-check
```

Le premier contrôle peut sortir avec le code 3 et annoncer la Capability
`model_operations` manquante ainsi que les descriptions des deux Skills à
actualiser. Vérifier le rapport complet : la commande applique toutes les
différences du catalogue canonique, y compris celles d'autres évolutions
éventuellement non réconciliées. Le dernier contrôle doit annoncer `in_sync`.

La même opération, dans l'environnement backend configuré de l'installation,
est disponible avec `python -m app.cli.reconcile_catalog` puis `--apply`.
Les identifiants des Skills existants sont conservés. Une seconde application
n'écrit rien. Aucune politique de surveillance n'est activée par cette opération.

## Vérification après livraison

Dans un workspace autorisé à voir les Capabilities universelles :

- `GET /api/v1/skills?category=Models` contient les deux Skills avec
  `visibility.reason = capability` et `model_operations` comme porteur.
- Leurs fiches `GET /api/v1/skills/<slug>` répondent 200 et indiquent
  `runtime_status = bound`, `certification_level = beta`.
- La palette les classe dans **Models**, sous leur Capability.
- Un masquage explicite reste effectif ; ne pas le supprimer pour faire passer
  le contrôle. Inspecter la raison via `include_filtered=true`.

La disponibilité d'un moteur ML, les références statistiques, les observations
ou labels requis et les workers/beat restent des prérequis séparés. Ce contrôle
ne déclenche aucun entraînement et ne démontre aucune amélioration de modèle.

Tests ciblés : `app/tests/api/test_model_operations_catalog.py` et les suites
de réconciliation, visibilité et surface du catalogue.
