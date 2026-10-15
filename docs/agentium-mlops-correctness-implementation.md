# M2 — Justesse MLOps, 15 octobre 2026

Lot initialement développé depuis `47e289da`, puis rebasé sur M1 `e74de787`. Le plan historique
reste inchangé. Ce lot ne déploie rien et n'ajoute aucune dépendance.

## Contrats livrés

- Le feedback désigne un échantillon conservé par un `sample_id` calculé côté
  serveur. Un appel de plusieurs lignes exige ce choix explicite ; aucun label
  de lot n'est propagé implicitement. Les anciens labels d'appels unitaires
  restent exploitables, les anciens labels de lots ambigus sont exclus.
- `original_plus_feedback` devient le mode par défaut, avec dédoublonnage,
  plafond de proportion, fenêtre temporelle facultative et contrôle des classes.
  `feedback_only` et `latest_dataset_version` sont explicites. Le plafond borne
  la composition du dataset ; il ne prétend pas appliquer des poids au modèle.
- Les trois modes conservent le test final enregistré du modèle source. Les
  observations du test, même réétiquetées, sont exclues de l'entraînement. Le
  dataset, les sources et leur version/digest, la partition et les exclusions
  sont figés dans les preuves puis revérifiés à l'approbation et à l'entraînement.
  Un ancien modèle sans partition vérifiable est refusé, sans inventer un test.
  Les sources dépassant les plafonds de lignes/octets sont refusées sans troncature.
- La dérive de concept couvre MAE/RMSE en régression et accuracy/F1 macro en
  multiclasse. La référence des scores est enregistrée sur le test d'entraînement ;
  les anciens modèles indiquent explicitement le repli sur la fenêtre précédente.
  Le badge des prévisions utilise les réels et reste absent sans mesure disponible.
- Chaque exécution planifiée produit son instantané, avec reprise idempotente de
  la même exécution. Monitor affiche les séries PSI, p-valeurs et concept, ainsi
  que la politique et la population figée du réentraînement. Les points absents
  ne deviennent pas des zéros.

La dérive multivariée optionnelle n'est pas implémentée. Le test synthétique
montre l'avantage du mélange sur un feedback biaisé et un test identique ; il ne
garantit aucune amélioration sur les données réelles.

## Assemblage avec M1 et M3

La migration 136 suit 135 et l'ordre de purge inclut `ml_prediction_feedback`.
L'API transmet `sample_id` et fournit le GET de métadonnées des échantillons,
avec contrôle du workspace, de la lignée et des permissions M1. Aucune entrée
brute n'est renvoyée par cette route.

L'approbation et le rejet du réentraînement sont audités via M1 dans la
transaction native, y compris le chemin de rejet qui termine le Run en échec.
La preuve de décision évite un audit doublé lors d'une reprise. Les tests du
Flow réel vérifient ces audits. Le downgrade 136 refuse de détruire des labels
conservés ; le test valide ce refus puis le downgrade d'une table vide.

La fenêtre de feedback est préchargée par lot : 80 prédictions et trois
parcours des labels coûtent deux SELECT. Une correction suivie d'un commit
est visible à la fenêtre suivante ; aucun cache applicatif persistant ne
masque le nouveau label. Les labels d'un autre workspace sont exclus.

M3 raccorde ensuite `ml_alerts.monitor_transition` à la création d'un nouvel
instantané, dans sa transaction, avec `source_id=snapshot.id`.

## Validation

Preuves légères et empreintes :
[`docs/evidence/mlops-correctness-2026-10-15/manifest.json`](evidence/mlops-correctness-2026-10-15/manifest.json).
Résultats : 133 tests backend, 2265 tests unitaires frontend, 6 E2E ciblés
FR/dark et EN/light ; TypeScript, i18n, navigation et build de production passent.
Les E2E doublent le backend ; ils ne valident donc pas les routes M1 à assembler.
La migration est vérifiée sur SQLite dans ce lot ; la chaîne PostgreSQL relève
de l'assemblage. Le guard `ui-chrome` échoue sur un état préexistant inchangé :
`src/styles.scss` compte 7 halos pour un budget de 6. Le budget n'est pas relevé.

Depuis `backend`, Python/pytest du venv partagé :

```bash
/workspace/hyusai/.venv/bin/python -m pytest \
  app/tests/services/test_mlops_correctness.py \
  app/tests/services/test_ml_retraining.py \
  app/tests/services/test_ml_retraining_recovery.py \
  app/tests/services/test_tabular_monitoring.py \
  app/tests/services/test_forecast_monitoring.py \
  app/tests/api/test_ml_retraining_api.py \
  app/tests/services/test_ml_training.py::test_the_harness_writes_the_evidence_the_model_card_reads \
  app/tests/services/test_ml_training.py::test_the_harness_regresses_a_continuous_target_with_a_scaled_pipeline \
  -q -p no:cacheprovider -W ignore
```

Depuis `frontend-ng`, Node `v24.19.0`, npm `11.9.0` :

```bash
TMPDIR=/workspace/mlops-m2-evidence/tmp GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run test:unit
node_modules/.bin/tsc --noEmit -p tsconfig.app.json
npm run check:i18n
npm run check:nav-links
npm run check:ui-chrome
TMPDIR=/workspace/mlops-m2-evidence/tmp GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run build:prod
PORT=4312 node e2e/serve-dist.mjs
# Dans un second processus, serveur arrêté ensuite :
E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4312 node_modules/.bin/playwright test \
  e2e/tests/44-models-retraining-mocked.spec.ts \
  e2e/tests/33-models-tabular-extensions-mocked.spec.ts \
  --project=chromium --grep 'configure with empty|history curve|regression feedback' --reporter=list
```

Ruff ciblé passe ; l'exception `F811` concerne les fixtures importées des tests
existants. Aucun test global de l'assemblage M1+M2+M3 n'est revendiqué ici.

Complément d’assemblage : 96 tests ciblés passent après préchargement du
feedback, et cinq tests vérifient le Flow réel/audit ainsi que le feedback
par ligne à travers HTTP. La chaîne PostgreSQL complète 135–137 est vérifiée
avec M3 ; aucune qualification de la VM n’est revendiquée.
