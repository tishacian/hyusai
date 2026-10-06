# Luma — DataOps, modèle et priorisation SAV

La file SAV utilise un modèle pour faire remonter les dossiers dont le profil
ressemble aux résolutions longues de l’historique. L’agent enquête ensuite dans
PostgreSQL et les documents pour proposer une action justifiée. Le score change
l’ordre de traitement ; les faits, la politique et l’approbation humaine
continuent à déterminer les remboursements.

## Ce qui est déjà présent dans Showcase

Vérifié sur `agentium.papai.ai`, workspace `agentium-showcase`, le 6 octobre
2026. Les datasets, l’entraînement et le scoring ci-dessous sont des objets
natifs créés et exécutés sur le site. Le raccordement au Flow principal et la
nouvelle carte Work nécessitent le déploiement et l’activation décrits plus bas.

| Objet | Référence native | Résultat vérifié |
|---|---|---|
| Historique CSV brut | [Dataset](https://agentium.papai.ai/data/00e991d8-9745-4847-9271-8b2ab0a9f9f8) | 1 236 lignes, 10 colonnes |
| Historique préparé | [Dataset](https://agentium.papai.ai/data/20301a42-ef4f-4982-b3e5-a503f9af7f2b) | 1 200 lignes, 8 colonnes |
| Entraînement | [Flow](https://agentium.papai.ai/systems/04aaadef-e8d7-4614-aea0-454d08652e15/flow) | Run `02322b02-0304-4c3f-a148-86dab7f65f00` terminé |
| Modèle | [Model](https://agentium.papai.ai/models/67ee9f56-0a79-4ad6-b550-a932fa0d6e78) | Régression logistique, v1, `ready`, champion |
| Variables opérationnelles | [Dataset](https://agentium.papai.ai/data/99e10700-2323-4da3-8fa7-07ec5c262990) | 23 dossiers, 7 colonnes |
| File scorée | [Dataset](https://agentium.papai.ai/data/d9f44db3-837a-414a-9a0d-f8d1f0d4fe56) | 23 dossiers, 10 colonnes, lignage vers le modèle v1 |
| Priorisation | [Flow](https://agentium.papai.ai/systems/7477fafa-574b-479f-aea3-b8a5ac1fb540/flow) | Run `de320e8f-0582-46a3-860b-e96b0956f2a8` terminé |

Six datasets supplémentaires proviennent des imports PostgreSQL en lecture
seule : `claims`, `orders`, `order_items`, `shipments`, `refunds` et
`document_refs`. Leur capture initiale date du 6 octobre à 20:26 UTC. Avec le
dataset documentaire déjà existant, Showcase contient maintenant onze datasets
`ready`. Ce premier scoring utilise ces captures datées ; l’activation remplace
ce chemin par une lecture PostgreSQL cohérente et fraîche à chaque recalcul.

## Intérêt et fonctionnement

**DataOps.** Le [générateur reproductible](fixtures/dataops/generate_history.py)
produit un historique synthétique indépendant des dossiers de démonstration.
Le [SQL de préparation](fixtures/dataops/prepare_history.sql) normalise les
catégories, convertit les types, retire 24 doublons et 12 issues invalides,
puis construit la cible `resolution_over_72h` à partir des dates d’ouverture et
de résolution. Les dates d’issue ne font pas partie des six variables du modèle.

**MLOps.** `ml_train_sklearn_v1` entraîne réellement un pipeline scikit-learn
sur 900 lignes, avec 300 lignes de test et trois plis de validation croisée.
Les métriques natives observées sont : AUC **0,858062**, exactitude **0,783333**,
F1 **0,756554**, score de Brier **0,151952** ; AUC de validation croisée
**0,852743 ± 0,004896**. Ce sont des résultats sur des données synthétiques,
pas une validation de production. L’artefact, les métriques, les versions et le
lignage sont consultables dans Model Center. Le serving est épinglé à la v1.

Les variables partagées par l’entraînement, le batch et l’enquête sont : motif,
montant payé, statut de livraison, remboursement antérieur, nombre de documents
du dossier et quantité d’articles. Les extractions sont limitées à la cohorte
configurée, sans SQL fourni par un agent, dans une transaction PostgreSQL
read-only. Les deux Skills ont des sorties distinctes : une liste de variables
pour un dossier, une référence de dataset pour la file complète.

Après activation, les chemins opérationnels sont :

```text
File : PostgreSQL → variables → SQL de contrôle → batch score v1 → dataset priorisé
Cas  : requête → variables PostgreSQL → predict v1 → agent → proposition → humain
```

Le Flow principal conserve ses entrées Document Center et PostgreSQL. Le score
et la version servie entrent dans le contexte de l’agent ; la décision financière
reste contrôlée par les outils existants. L’entraînement reste une opération
séparée, visible et versionnée ; il ne se répète pas pour chaque dossier.

Sur le premier batch réel, la probabilité de la classe positive vaut **82,19 %**
pour RC-1042, **16,32 %** pour RC-1043 et **1,10 %** pour RC-1044. Le litige
complexe remonte, tandis que le dossier déjà remboursé reste standard. Les
seuils de priorité 0,60 et 0,35 sont une convention explicite de démonstration.
Afficher `score_1`, jamais la confiance dans la classe prédite : pour RC-1044,
la confiance dans la classe « résolution courte » est proche de 99 %.

Les dossiers ont des dates fixes. Ce modèle reconnaît un **profil de traitement
long**, sans calculer une échéance actuelle ou un temps restant. Work l’indique
et propose un recalcul compact, les liens vers les datasets et le modèle, ainsi
qu’un accès direct au Flow builder. Un score absent, invalide ou âgé de plus
d’une heure est masqué ; la file retrouve son ordre d’origine. Une prédiction
fraîche du Run d’enquête peut remplacer le score batch dans le dossier ouvert,
uniquement si elle provient de la même version du modèle.

## Activation par l’opérateur

La démo Luma est déjà installée : ne pas rejouer les seeds PostgreSQL,
l’installateur original, l’ingestion documentaire ou l’entraînement ci-dessus.
Le code arrive par Git, depuis `origin/demo/agentic` et son miroir Bitbucket,
selon le [runbook VM sûr](../../ops/agentium-safe-vm-deployment.md). Vérifier
la révision du backend, du worker et du frontend avant l’activation. Aucun
nouveau schéma SQL n’est requis par cette extension.

Le [plan figé](fixtures/dataops/live_activation_plan.json) cible le Flow
principal v3, la release Work 2 et le Flow de scoring v1 constatés sur le site.
Depuis le checkout propre du code déployé, produire la revue sans mutation :

```bash
cat docs/demo-runs/showcase-ecommerce/fixtures/dataops/live_activation_plan.json |
  docker exec -i agentium-backend python -m scripts.activate_ecommerce_triage \
    --workspace agentium-showcase \
    --actor-user-id 06a2e190-ae2d-4365-b4f3-9952401f531d \
    > /tmp/luma-triage-review.json
```

Relire les graphes et leurs références. Les cibles revues le 6 octobre sont :

- Flow principal : 15 nodes, 16 edges,
  `68c103d15a97e342be6b5a6efd4a66f85952f5c41b408c03448fa70b9839443f`.
- Flow de scoring : 6 nodes, 5 edges,
  `445eec21706f85f5bb56926a8e98f19f710418f052a3025cf5cd2a02cd82dd56`.

Si l’état a changé, la commande refuse l’activation. Faire une nouvelle revue
du draft, des publications et de la release avant de modifier le plan ou les
empreintes ; ne pas contourner les contrôles de concurrence.

Appliquer ensuite exactement ces cibles :

```bash
cat docs/demo-runs/showcase-ecommerce/fixtures/dataops/live_activation_plan.json |
  docker exec -i agentium-backend python -m scripts.activate_ecommerce_triage \
    --workspace agentium-showcase \
    --actor-user-id 06a2e190-ae2d-4365-b4f3-9952401f531d \
    --apply \
    --expected-target-sha256 68c103d15a97e342be6b5a6efd4a66f85952f5c41b408c03448fa70b9839443f \
    --expected-scoring-target-sha256 445eec21706f85f5bb56926a8e98f19f710418f052a3025cf5cd2a02cd82dd56 \
    > /tmp/luma-triage-activation.json
```

L’activation publie les deux Flows, ajoute les bindings des Skills nécessaires
et crée la release Work reliée à la nouvelle publication du Flow principal,
dans une transaction native. Elle conserve les versions et releases antérieures
ainsi que les données. Conserver le reçu retourné et ses IDs de publication,
release et déploiement.

Ouvrir [Work Réclamations](https://agentium.papai.ai/work/reclamations/studio),
puis **Recalculer la file**. Ce bouton lance un vrai Run du nouveau scoring,
avec publication et empreinte attendues. Le premier dataset antérieur ne peut
pas servir de résultat au nouveau Flow. Vérifier le Run terminé, les 23 scores,
le nouveau dataset et son lignage avant la présentation.

## QA après activation et démonstration

1. Dans Data Center, ouvrir le CSV brut, l’historique préparé et leurs profils.
   Montrer les anomalies retirées et les liens vers le Run de préparation.
2. Dans Model Center, montrer la v1, ses métriques et son dataset d’entraînement.
   Le modèle est synthétique et la métrique n’est pas un ROI.
3. Depuis Work, ouvrir le Flow de priorisation et le node PostgreSQL : vérifier
   le drill-down vers les tables Luma, puis les nodes de préparation et scoring.
4. Recalculer la file et conserver le vrai Run. RC-1042 doit remonter avec son
   profil de traitement long ; les montants restent 420 €, 49,90 € et 89 €.
5. Enquêter sur un cas : la trace doit inclure construction des variables,
   prédiction v1, recherches documentaires et proposition. Vérifier les branches
   d’origine : litige de livraison, perte confirmée, remboursement déjà exécuté.
   Les paiements restent simulés et soumis à approbation humaine.
6. Vérifier clair/sombre, FR/EN, clavier et largeur mobile, ainsi que les liens
   Dataset → Model → Dataset scoré → Flow builder. Si les scores expirent,
   ils disparaissent et le recalcul reste disponible.

La QA locale passe : **140 tests backend**, **1 936 tests unitaires frontend**,
**11 scénarios navigateur**, compilation de production (inlining des polices
externes désactivé pour le réseau local). Les scénarios navigateur
utilisent des APIs simulées pour les nouveaux écrans ; ils ne remplacent pas la
vérification du raccordement déployé. Les vues natives de modèle, dataset scoré,
lignage et Flow ont été parcourues sur le site ; la carte Work a été inspectée
en clair, sombre et mobile, avec zéro violation Axe dans sa zone de priorisation.

Les hooks appliqués à l’index de livraison, le scan Gitleaks de cet index et les
contrôles du chrome, des traductions, des liens et de conformité passent. Le
contrôle `pre-commit --all-files`, exécuté sur une copie isolée avec l’historique
réel, reste en échec sur la dette existante du dépôt : imports/formatage et
template `docker/livekit/agentium-livekit.yaml`, avec `shellcheck` et `shfmt`
absents de cet environnement. Ces modifications globales ne sont pas livrées.
Le hook de mise à jour des dépendances de pré-commit est désactivé pour cette
livraison, qui conserve les versions des outils du dépôt.

## Mesure de valeur dans Impact

Le benchmark garde la convention **40 €/h, hypothèse de démonstration**. Ses
dix paires manuel/assisté ne sont pas encore mesurées. Les scores et les aides
automatiques restent masqués tant que la condition de session n’est pas connue,
puis pendant toute session manuelle. Une QA automatique ne produit pas de temps
humain ni de gain annoncé.

Le protocole existant mesure le traitement des dossiers, pas l’amélioration
d’un SLA sur une file réelle. Un gain de temps nécessite dix paires complètes
de qualité comparable ; une réduction des délais de résolution nécessiterait
une expérimentation distincte sur des arrivées et résolutions réelles.
La revue de coût doit inclure aussi préparation, entraînement et batch scoring,
avec une allocation explicite et ses preuves, en plus des coûts des enquêtes.
Leur présence dans le catalogue et les Runs ne garantit pas leur couverture
dans le ledger du benchmark. Sans coûts complets, le bénéfice net et le ROI
restent inconnus. Voir le [protocole opérateur](OPERATOR-RUNBOOK.md).
