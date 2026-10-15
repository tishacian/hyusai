# M2 — Justesse MLOps, 15 octobre 2026

Lot indépendant depuis `47e289da`, à assembler avec M1 et M3. Le plan historique
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

## Assemblage nécessaire avec les lots voisins

1. Migration `136_mlops_correctness` après `135_mlops_governance` : nouvelle table
   `ml_prediction_feedback`. Ajouter cette table avant `ml_predictions` dans
   l'ordre de purge des tests PostgreSQL et vérifier la chaîne 135–137.
2. L'API feedback doit transmettre `sample_id` à `attach_feedback`. Le GET
   `ml-models/{id}/predictions/{prediction_id}` doit appliquer les permissions M1,
   vérifier workspace et modèle, puis renvoyer `serialize_prediction` dans
   `{prediction: ...}`. Le client ne reçoit pas les données d'entrée.
3. M1 porte `input_storage_allowed` et les réglages de budget/seuils. Les entrées
   non conservées sont refusées par M2. Les valeurs par défaut locales permettent
   de qualifier ce lot indépendamment, sans ajouter de politique RBAC parallèle.
4. M1 doit journaliser strictement l'approbation/rejet dans la transaction native
   de décision via `ml_permissions.audit`. `settle_gate` est le point de liaison ;
   son rejet lève `ML_RETRAIN_REJECTED` après `flush`, donc l'audit doit être dans
   la transaction qui conserve effectivement la décision, pas dans un rollback.
   Aucun import facultatif silencieux du module M1 n'est ajouté par ce lot.
5. M3 peut appeler `ml_alerts.monitor_transition` après création d'un nouvel
   instantané dans la même transaction, avec `source_id=snapshot.id`. Les reprises
   de l'instantané existant ne doivent pas recréer une transition.

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
/workspace/omnirag/.venv/bin/python -m pytest \
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
