# Vérification des extensions tabulaires — Lot 2

Les sous-lots 2b à 2f ajoutent les intervalles de régression, la calibration et
le seuil de classification, la recherche Optuna, les explications et le choix
d'encodeur de texte. Ils partent tous de `demo/agentic` à `19b2d488` (2a intégré),
sans migration et avec les nouveaux traitements désactivés par défaut.

Chaque branche reste livrable seule. `verify/ml-lot2-combined` rassemble leurs
changements et les résolutions de chevauchement pour vérifier leur coexistence.
Cette vérification ne fusionne rien dans `demo/agentic` et ne déploie rien.

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

La vérification assemblée a passé :

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
explicitement. Ces raccordements sont couverts par les tests de la branche de
vérification ; ils doivent être conservés lors des futures intégrations.

Le test de catalogue des wrappers `openai_llm_v1` / `azure_openai_llm_v1`, déjà
rouge avant ce lot, est hors des suites ci-dessus et n'a pas été modifié.

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
faire après le déploiement par l'utilisateur. Chaque fusion dans `demo/agentic`
reste soumise à son accord explicite.
