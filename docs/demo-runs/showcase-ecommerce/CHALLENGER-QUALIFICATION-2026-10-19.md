# Luma — qualification du challenger RandomForest, 19 octobre 2026

La version 6 est entraînée, appelable et produit une véritable explication
TreeSHAP sur le déploiement `718c99bf7e9e07fb689ff0bcd4a1ffd90fca2ece`.
La version 5 reste le champion servi. La qualification ne modifie ni le Flow,
ni Work, ni la proposition de réentraînement en attente d'approbation humaine.

## Modèle et contrat d'entrée

| Élément | Valeur |
| --- | --- |
| Nom | Luma — Risque de résolution >72h |
| Slug / version | `luma-risque-de-resolution-72h` / **6** |
| ID challenger | `6d9c2eee-60b9-4995-afb5-6dc9c148de6c` |
| ID champion v5 | `2e71ce6f-800f-4d02-b59e-498e40fe48eb` |
| Famille / tâche | `tabular` / `classification` |
| Algorithme | `random_forest`, 200 arbres, profondeur maximale 8, minimum 5 observations par feuille |
| Dataset | `e1141f15-820e-46e5-87f8-9c6f3dc9a430`, version 2 ; 4 573 lignes synthétiques |
| Cible / classe positive | `resolution_over_72h` / `1` |
| Entraînement terminé | 19/10/2026 à 14:50:27 UTC ; durée enregistrée 46,366 s |
| État | `ready`, `serving.callable=true`, `is_champion=false` |
| Référence de runtime | 256 lignes du test final ; capture automatique terminée |

Les six entrées restent `claim_reason`, `paid_amount`, `shipment_status`,
`already_refunded`, `case_documents` et `item_quantity`. Le champ `language`
reste un auxiliaire d'analyse par groupe et ne devient pas une entrée du
modèle. Le jeu de données et le contrat d'entrée sont identiques à ceux de v5.

La calibration est désactivée explicitement ; le seuil est choisi par Youden,
le réglage automatique est désactivé et le pack d'explication est demandé.
La partition est un holdout aléatoire de 25 %, avec graine 42, et la validation
croisée utilise trois plis. Le modèle linéaire calibré v5 ne devient pas
compatible avec TreeSHAP : cette capacité est démontrée sur le challenger RF.

## Comparaison sur le même test final

`GET /api/v1/ml-models/6d9c2eee-60b9-4995-afb5-6dc9c148de6c/comparison?against=2e71ce6f-800f-4d02-b59e-498e40fe48eb`
répond **200**. La comparaison est vérifiée et utilise l'intersection des
observations enregistrées comme non vues à l'entraînement : **1 141 lignes**,
stratégie `recorded_unseen_intersection`, rôle `final_test`, aucun avertissement.
Les trois observations du test initial présentant un chevauchement de doublons
ne sont donc pas comptées dans cette comparaison.

| Mesure | Champion v5, linéaire | Challenger v6, RF |
| --- | ---: | ---: |
| Exactitude | 0,7371 | 0,7327 |
| Précision | 0,6895 | 0,6730 |
| Rappel | 0,7386 | 0,7703 |
| ROC AUC | 0,8205 | 0,8112 |
| Log loss, plus faible préférable | 0,5100 | 0,5249 |
| Score de Brier, plus faible préférable | 0,1716 | 0,1770 |

Le challenger augmente le rappel au seuil retenu, avec une précision, une AUC
et des scores probabilistes moins favorables. Ces résultats ne justifient pas
une promotion automatique. Ils permettent de montrer une comparaison et un
arbitrage réels, sur un corpus synthétique. Ils ne démontrent ni une qualité
commerciale en production ni une économie financière.

## TreeSHAP effectivement exécuté

Dans Play, ouvrir **v6** et lancer une prédiction sur une observation ;
l'explication est sélectionnée automatiquement. La qualification ci-dessous
utilise l'API avec `explain_method: "shap"`, qui refuse une explication de
substitution. Le contrat API qualifié est :

```json
{
  "inputs": [{
    "claim_reason": "delivery_disputed",
    "paid_amount": 364.99,
    "shipment_status": "in_transit",
    "already_refunded": 0,
    "case_documents": 3,
    "item_quantity": 1
  }],
  "version": 6,
  "explain": true,
  "explain_method": "shap",
  "store": true
}
```

Envoyer à
`POST /api/v1/ml-models/6d9c2eee-60b9-4995-afb5-6dc9c148de6c/predict`.
Le paramètre `version` est nécessaire : sans version épinglée, la route de
prédiction suit le champion de la lignée.

Le premier appel explicite a renvoyé **409**, `ML_EXPLAIN_UNAVAILABLE`, raison
`timeout`. Ce refus est conservé dans les preuves. Le deuxième appel a répondu
**200** à 14:52:03 UTC, avec `method=tree_shap`, estimateur
`RandomForestClassifier`, classe `1`, et espace de sortie `probability`.
Il n'utilise pas une explication de substitution.

| Contribution | Variation de probabilité |
| --- | ---: |
| Valeur de base | 0,442232 |
| Motif du dossier | +0,224897 |
| Statut de livraison | +0,119631 |
| Montant payé | +0,089527 |
| Déjà remboursé | +0,044625 |
| Documents du dossier | −0,016255 |
| Quantité | −0,005680 |
| **Probabilité résultante** | **0,898977** |

La somme base + contributions a été vérifiée contre la probabilité renvoyée ;
`additivity_gap=0`. Les six champs attendus sont présents. L'explication prend
94,6 ms dans cette réponse ; ce temps technique n'est pas du temps humain
économisé. La prédiction conservée porte l'identifiant
`a1e166b5-c8b4-4382-92d7-27deb2dab6b5`.

## Shadow : blocage actuel et reprise après déploiement

Le shadow reste désactivé. Le déploiement en service choisit le challenger
par son classement dans le registre avant de vérifier son caractère appelable.
Il retient ainsi l'ancienne v2, `0c93ef17-3241-43bd-93dc-cc0d9c5524e1`, qui
présente une AUC enregistrée supérieure mais un artefact legacy non accepté.
La readiness renvoie `can_enable=false`, `ML_ARTIFACT_LEGACY_UNSUPPORTED`.
L'entraînement de v6 ne change pas ce classement et ne débloque donc pas le
shadow à lui seul.

Le correctif générique de sélection des candidats shadow admissibles doit
être déployé avant la qualification de cette partie. Il ne doit modifier ni
le classement général du registre, ni le champion, ni les métriques des
anciennes versions. Après déploiement :

1. Vérifier que la readiness shadow désigne v6 et explicite les exclusions
   des versions legacy.
2. Activer un échantillonnage borné sur v5, envoyer un petit lot de prédictions
   v5 conservées et attendre la fin effective des jobs shadow.
3. Vérifier la paire v5/v6, les lignes comparées, les refus éventuels et les
   latences avant de fixer la configuration de suivi souhaitée.
4. Présenter l'accord entre versions et le surcoût d'exécution ; sans résultats
   métier connus sur ces observations, ne pas annoncer une précision supérieure.

À la fin de cette qualification, le champion servi est toujours v5. La
configuration shadow est inchangée : désactivée, échantillonnage mémorisé 10 %,
délai maximal 15 s ; aucun job shadow n'a été créé. La proposition de
réentraînement existante reste soumise à la décision humaine.

Les requêtes, réponses et assertions détaillées sont conservées hors dépôt
dans `/workspace/scratch/luma-four-lots-2026-10-19/challenger/`. Aucun jeton ni
mot de passe n'est enregistré dans ces preuves ou cette note.
