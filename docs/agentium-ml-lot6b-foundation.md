# Lot 6b — Prévisions zero-shot locales

Le catalogue propose `chronos_zero_shot`, tâche `forecasting`, famille
`forecasting_deep`. La famille et l'algorithme sont indisponibles sans worker
`ml-deep` actif et sans modèle local vérifié. Aucun schéma SQL ne change.

## Modèle et contrat

- `autogluon/chronos-2-small`, Apache-2.0, révision immuable
  `ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a`.
- `config.json` : SHA256 `f2780468adc8b16322aa0b6e28b26476c9401ecf64ab53292b6d2b0d3f423722`.
- `model.safetensors` : 111 749 048 octets, SHA256
  `492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd`.
- Provisionnement sous `/data/models` avec le manifeste du lot 6a ; aucun
  téléchargement au fit ni à l'inférence. Torch CPU, `chronos-forecasting==2.3.2`,
  `skforecast==0.25.0` ; torch et transformers gardent les pins communs.

Une série ou un panel de 32 séries au maximum, sur la même grille temporelle.
Contexte borné aux 512 dernières observations, horizon de 1 à 64 pas, 1 à 5
fenêtres de backtest. Les identifiants de série ambigus, dates invalides,
doublons, valeurs infinies et grilles incompatibles sont refusés. Les dates
sont normalisées en UTC. Les trous sont refusés, sauf remplissage explicite
par zéro. L'interpolation, les covariables, le calendrier, les lags,
l'optimisation et les réglages d'estimateur ne sont pas proposés.

Les intervalles proviennent des quantiles natifs du modèle ; le niveau proposé
va de 50 % à 98 %. La couverture observée est affichée sans garantie de
calibration. Il n'y a ni apprentissage des poids ni explication de variables
inventée. La surveillance des observations utilise le parcours des prévisions
existant ; le réentraînement planifié des familles deep reste refusé.

## Évaluation et export

Chaque origine reçoit uniquement son préfixe historique. Les horizons de test
sont exclus du contexte de la prévision correspondante. Le naïf saisonnier
répète la dernière saison connue, même si l'horizon dépasse cette saison. Le
MASE conserve la définition du catalogue : erreur divisée par la variation
absolue à un pas, mesurée ici sur le préfixe initial uniquement.

`ForecasterFoundation` clone son estimateur et perd le pipeline préchargé passé
au constructeur : le pipeline local doit donc être attaché après ce clone.
Le harness pilote les fenêtres temporelles explicitement, sans clonage ultérieur.

L'export MLflow contient le contexte en JSON, les poids en safetensors,
`meta.json` et le pyfunc autonome `ml_foundation_pyfunc.py`. Il ne contient aucun
pickle de torch. Tous les fichiers, y compris `MLmodel` et les dépendances, sont
empreintés et vérifiés avant chargement par Agentium. L'export se recharge avec
`mlflow.pyfunc.load_model` sans imports applicatifs et sans accès réseau. Le
chargeur vérifie aussi les empreintes des poids inclus. Les paramètres MLflow
`horizon` et `interval_level` gardent les mêmes bornes.

## Qualification

Tests : causalité des préfixes, naïf au-delà d'une saison, refus des données,
Nawa single et panel réels, invariance de chaque tenseur du modèle, export
indépendant hors ligne, sélection de série et altération d'artefacts.

La qualification Nawa utilise le générateur existant : 21 jours horaires,
une cellule, trois horizons de 24 heures. Sur les mêmes données et fenêtres :

| Modèle | MAE | Couverture observée à 80 % |
| --- | ---: | ---: |
| Naïf saisonnier | 3,3167 | — |
| Gradient boosting existant, réglages par défaut | 2,9061 | 79,17 % |
| Chronos-2-small zero-shot | 2,5901 | 72,22 % |

Ces mesures sont une qualification reproductible du générateur de démonstration,
pas une garantie de gain sur de futures données. Les intervalles Chronos sont
ici plus étroits et leur couverture plus faible.

Pour exécuter la qualification locale : définir `ML_DEEP_TEST_MODEL_DIR` vers
le snapshot provisionné et lancer `test_ml_foundation_harness.py` ainsi que
`test_ml_foundation_validation.py` dans l'environnement deep. Aucun test ne
récupère des poids sur Internet.
