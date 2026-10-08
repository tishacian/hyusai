# Vérification des extensions tabulaires — Lot 2

Les sous-lots 2b à 2f ajoutent les intervalles de régression, la calibration et
le seuil de classification, la recherche Optuna, les explications et le choix
d'encodeur de texte. Ils partent tous de `demo/agentic` à `19b2d488` (2a intégré),
sans migration et avec les nouveaux traitements désactivés par défaut.

Chaque branche reste livrable seule. La première qualification a été menée sur
`verify/ml-lot2-combined`. Après la demande explicite de revue et de fusion de
l’utilisateur, les changements ont été assemblés dans l’ordre **2b → 2c → 2d →
2e → 2f**, avec une fusion `--no-ff` par sous-lot, pour intégrer `demo/agentic`.
Aucun déploiement n’est effectué par ces fusions.

## Qualification initiale des branches

| Lot | Branche indépendante | Révision vérifiée | Unités frontend | Infrastructure |
|---|---|---|---:|---:|
| 2b | `feat/ml-lot2-b-intervals` | `826f9c46` | 1 982 | 919 |
| 2c | `feat/ml-lot2-c-calibration` | `88aac662` | 1 982 | 919 |
| 2d | `feat/ml-lot2-d-tuning` | `35dbef72` | 1 982 | 920 |
| 2e | `feat/ml-lot2-e-explainability` | `685b1004` | 1 984 | 919 |
| 2f | `feat/ml-lot2-f-text` | `6bf50acb` | 1 980 | 919 |

Chaque lot a passé ses tests backend ciblés, i18n, parcours navigateur mockés
FR/sombre et EN/clair, et un unique `build:prod`. Les suites d'infrastructure
comportent chacune 36 cas ignorés, liés aux contrôles externes.

## Coexistence des options

La première vérification assemblée a passé :

- 348 tests ML/API/datasets existants, avec 18 tests marqués lents exclus de cette
  passe générale ; les nouveaux harness réels ont été exécutés séparément ;
- 920 tests d'infrastructure, 36 ignorés ;
- 1 994 unités frontend, le contrôle i18n et la compilation Angular des templates ;
- 29 parcours navigateur mockés couvrant les lots 2a à 2f ;
- trois entraînements conjoints avec sauvegarde et rechargement MLflow :
  régression MinHash + Optuna + intervalles + explications ; classification
  MinHash + Optuna + calibration + seuil + explications ; régression
  StringEncoder avec graine 0 + Optuna + intervalles + explications ;
- deux validations de spec complète lors d'un changement de cible : les options
  partagées restent présentes et celles incompatibles avec la tâche sont retirées.

Le test conjoint recalcule le score initial de validation croisée avec l'encodeur
choisi et vérifie son égalité avec l'essai initial Optuna. Il contrôle aussi que
les colonnes d'équité restent hors des variables prédictives, que les groupes
couvrent les lignes de test et que le résumé d'explications respecte ses limites.

Les résolutions communes réunissent les neuf champs du catalogue, les cartes
Evidence et les traductions. Le choix d'encodeur s'applique dans `_make_pipeline`,
utilisé à la fois par les essais et le fit final. La graine 0 est conservée
explicitement. Ces raccordements sont conservés dans les fusions ordonnées et
couverts par les tests d’intégration.

Le test de catalogue des wrappers `openai_llm_v1` / `azure_openai_llm_v1`, déjà
rouge avant ce lot, est hors des suites ci-dessus et n'a pas été modifié.

## Revue avant fusion — 8 octobre 2026

La revue indépendante a conduit aux corrections suivantes, poussées sur les
branches concernées avant leur intégration :

- **2c, `4d65c63a`** : une classe entièrement absente du sous-ensemble de
  calibration compte désormais comme ayant zéro exemple. Le modèle conserve
  alors son entraînement complet au lieu d’échouer à la calibration.
- **2d, `a698ecbb`** : l’objectif de recherche est déterminé par les classes
  non manquantes du train effectif, même si le profil contient des valeurs nulles
  ou NaN. L’encodeur automatique utilise la graine de la recherche dans les
  essais et dans le modèle final ; son comportement hors tuning reste inchangé.
- **2e, `32b79fb3`** : les PDP numériques respectent l’espacement réel des
  valeurs sur un axe linéaire. Les groupes d’équité gèrent aussi les types
  pandas nullables issus de Parquet.

Aucun autre défaut bloquant n’a été relevé dans 2b ou 2f, ni dans la relecture
des résolutions de fusion. Les fusions gardent les neuf champs du catalogue,
les cartes Evidence et les traductions FR/EN. Un quatrième entraînement conjoint
couvre l’encodeur automatique avec Optuna, intervalles et explications, avec
recalcul du score initial et rechargement de l’artefact MLflow.

La vérification finale aligne également les guillemets des clés du dictionnaire
sur le format existant, sans changer les clés ni les libellés, afin de conserver
le contrôle backend du contrat catalogue/traductions.

Sur l’assemblage final, les contrôles passent :

- **303 tests backend** des extensions, familles, API, prédictions et registre,
  incluant les quatre entraînements conjoints réels ;
- **126 tests complémentaires** d’entraînement, comparaison, monitoring,
  datasets et contrat de traduction ; 18 tests lents restent exclus de cette
  passe complémentaire ;
- **920 tests d’infrastructure**, 36 ignorés ;
- **1 996 unités frontend**, contrôle i18n et compilation Angular des templates ;
- **29 parcours navigateur mockés** des lots 2a à 2f, en FR/sombre et EN/clair ;
- contrôle des différences Git et recherche de secrets sans anomalie.

Les builds de production déjà réalisés une fois par sous-lot n’ont pas été
relancés pendant cette revue. Aucun changement de schéma ni migration n’est ajouté.

## Qualification avant déploiement

2d déplace les versions Optuna 5.0.0 / colorlog 6.12.0 déjà qualifiées dans ml-ts
vers les dépendances communes. L'API n'importe jamais Optuna. Les images backend
et worker doivent être reconstruites ensemble.

Leur budget de taille reste **non qualifié** : le moteur Docker local en `vfs`
a épuisé son espace lors de l'export d'une image construite avec une base mobile.
La taille provisoire backend de 2,61 Go dépassait le budget ; le worker n'a pas
été construit. Les budgets restent inchangés. Refaire la mesure avec la base
épinglée de la VM et analyser tout dépassement avant déploiement, comme détaillé
dans `docs/agentium-release-process.md`. Le contrôle de compatibilité des
214 paquets du venv commun est passé après alignement des versions.

2b enrichit le contrat des Skills publiées depuis un modèle avec intervalles ;
ce contrat suit la version promue via `refresh_published_skill`. Après un futur
déploiement, suivre le contrôle `catalog-check` puis `catalog-apply` si nécessaire.
Les essais réels sur la VM et les mesures de latence à froid/à chaud restent à
faire après le déploiement par l'utilisateur. L’accord de fusion des sous-lots
a été donné explicitement ; il ne constitue pas une demande de déploiement.
