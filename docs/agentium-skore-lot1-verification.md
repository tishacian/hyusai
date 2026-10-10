# Skore 0.27 — qualification du lot 1

Date : 10 octobre 2026. Base : `demo/agentic` à
`7e41de642c6254b3b88f508cb37be79ff5844fed`.
Branche de travail : `feat/skore-027-lot1`.
Voir la [roadmap](agentium-skore-integration-roadmap.md).

## Changement livré

- Plage Skore `>=0.27,<0.28`, version qualifiée `0.27.0` dans les contraintes
  app et Giskard. Les couches ml-ts/ml-deep héritent des contraintes app.
- Adaptateur commun `backend/app/resources/ml_skore_adapter.py`, sans I/O,
  utilisé par le harness autonome et la comparaison. Le forecasting hérite
  de cet adaptateur via son diagnostic de régresseur à un pas.
- Lecture explicite des noms machine, index plats, moyennes et écarts types ;
  rejet des colonnes ambiguës ; valeurs non finies restituées en `null`.
- `default_score`, ajouté par Skore 0.27, est exclu du contrat Hyusai. Les
  métriques nommées, arrondis, précision des comparaisons et MAPE en pourcentage
  conservent leur comportement précédent.
- Script reproductible de qualification avec six rapports synthétiques :
  deux binaires, un multiclasse, une régression et deux validations croisées.
  La comparaison est reconstruite à partir des rapports binaires.

Aucun changement de stockage : les octets restent dans l'ObjectStore/MinIO
existant, avec les références MLflow existantes. Aucun Project Skore, Hub,
registre ou serveur supplémentaire. Le script de qualification utilise
uniquement des fichiers temporaires de test ; il ne contacte pas ces services.

## Résultats locaux

Python 3.12.14, Linux ; dépendances app contraintes, puis extensions ml-ts
contraintes. Le passage 0.25 → 0.27 n'a remplacé que Skore. `uv pip check`
confirme la compatibilité des 218 paquets installés après ajout ml-ts.

| Vérification | Résultat |
| --- | --- |
| Référence 0.25, entraînement/comparaison hors tests lents | 66 réussis, 18 désélectionnés |
| Nouvel adaptateur testé en 0.25 | 11 réussis |
| Suite principale 0.27 : entraînement, comparaison, calibration/seuils, registre, adaptateur, options combinées, contraintes | 156 réussis, 1 échec de chargement intermédiaire (1 358 s), requalifié ci-dessous |
| Reprise des 11 tests de l'adaptateur sur le code final, dans un processus neuf | 11 réussis (8 s), y compris le cas en échec dans le premier lancement |
| Adaptateur final 0.27 + contrats sources/contexte des images | 30 réussis |
| Forecasting réel : diagnostic Skore recursive/direct, absence de diagnostic ETS, relecture du rapport | 1 réussi (158 s) |
| Comparaison API après exclusion de `default_score`, y compris entraînements réels | 8 réussis (261 s) |
| Métriques des nouveaux entraînements 0.27 comparées à la référence 0.25 | Réussite ; mêmes clés et valeurs, tolérance absolue `1e-6`, relative `1e-8` |
| Six états 0.25 relus en 0.25, puis comparaison | Réussite, `.fit()` interdit pendant la relecture |
| Six nouveaux états 0.27 relus en 0.27, puis comparaison | Réussite, `.fit()` interdit pendant la relecture |
| États 0.25 relus directement en 0.27 | **Incompatible**, voir ci-dessous |
| Ruff, règles d'import du dépôt sur les cinq fichiers Python modifiés/ajoutés | Réussite |
| Hooks pre-commit applicables aux fichiers modifiés | Réussite ; exceptions d'exécution détaillées ci-dessous |
| Gitleaks 8.30.1 sur le diff indexé, sortie masquée | Aucune fuite détectée |
| Contrat statique Agentium | Réussite, 16/22 assertions vérifiées statiquement ; attestations runner séparées |

Le premier lancement long a importé l'adaptateur avant la correction de
`default_score`. Plus tard, le harness chargé par chemin a lu le fichier
corrigé : l'assertion d'égalité entre ces deux chargements voyait donc une clé
`default_score` supplémentaire dans l'ancien module en mémoire, et huit autres
valeurs identiques. Le rejeu des 11 tests dans un processus neuf passe sur le
code final, tout comme les 8 tests de comparaison API rejoués après correction.
Il s'agit d'une qualification par suite et reprises ciblées, pas d'un lancement
unique intégralement vert. Aucun test n'a été retiré ou rendu moins exigeant.

Les cinq fichiers Python sont formatés avec Ruff 0.15.10. Les deux fichiers
existants ont été normalisés pour satisfaire le hook du dépôt ; leurs arbres
syntaxiques avant/après formatage sont identiques. Ces changements de mise en
forme n'ajoutent pas de comportement à la migration.

Le hook Go de Gitleaks ne pouvait pas s'installer avec le `go` de cet
environnement. Le même Gitleaks 8.30.1 a donc été exécuté séparément depuis son
binaire officiel, après vérification SHA-256, avec `git --pre-commit --redact
--staged`. Les autres hooks ont tourné avec
`SKIP=gitleaks,yamlfmt,pre-commit-update` : aucun YAML n'est modifié et la mise
à jour des versions des hooks n'appartient pas à ce lot.

## Limite des anciens rapports et règle de livraison

`joblib.load()` d'un état 0.25 échoue sous 0.27 avec :

```text
ModuleNotFoundError: No module named 'skore._utils._skrub'
```

Le dictionnaire `to_dict()` contient lui-même des objets Python dépendant de
modules internes. Ce format ne garantit pas une portabilité interversions.
La preuve de relecture couvre les six cas synthétiques décrits ci-dessus,
pas tous les artefacts de production.

Les anciens états sont conservés, sans réécriture ni shim sur les modules
privés de Skore. Ils se relisent avec le runtime 0.25 compatible, en récupérant
les mêmes octets depuis l'ObjectStore existant. La version Skore est déjà
enregistrée dans les métadonnées et les tags MLflow. Aucun lecteur de rapports
persistés n'est actuellement exposé par l'application ; la comparaison relit
les modèles et reconstruit les rapports.

**Avant livraison :** conserver et identifier l'image 0.25 et ses contraintes
pour cette relecture ; qualifier les nouvelles images API/worker/ml-ts/ml-deep
ensemble et leur procédure de retour. L'environnement 0.25 reconstruit ici
ne constitue pas une attestation de conservation d'image en production.
Un futur lecteur doit sélectionner le runtime compatible ou signaler une
incompatibilité, sans réentraînement automatique et sans prétendre que le
rapport n'existe pas. Les modèles servis et les états de rapport sont des
artefacts distincts.

## Reproduire la qualification de sérialisation

Depuis `backend/`, avec deux interpréteurs : `PY025` pour Skore 0.25.0 et
`PY027` pour Skore 0.27.0. Utiliser Python 3.12 et les mêmes pins numpy,
scipy, pandas, scikit-learn, skrub et joblib. Les anciennes contraintes sont
récupérables au commit de base via `git show <base>:backend/constraints-demo-app.txt`.
Les chemins de sortie doivent être neufs. Charger uniquement les fichiers
produits par le script dans un environnement de confiance.

```bash
"$PY025" scripts/qualify_skore_upgrade.py write /tmp/hyusai-skore-proof-025
"$PY025" scripts/qualify_skore_upgrade.py verify /tmp/hyusai-skore-proof-025
"$PY027" scripts/qualify_skore_upgrade.py fresh /tmp/hyusai-skore-proof-025
"$PY027" scripts/qualify_skore_upgrade.py write /tmp/hyusai-skore-proof-027
"$PY027" scripts/qualify_skore_upgrade.py verify /tmp/hyusai-skore-proof-027
# Doit échouer sur l'incompatibilité documentée, pas être ignoré dans un gate :
"$PY027" scripts/qualify_skore_upgrade.py verify /tmp/hyusai-skore-proof-025
```

Les temps d'exécution sont exclus des comparaisons numériques. Les nouveaux
entraînements sont également vérifiés contre la référence ; le seul fait de
relire un cache ne prouve pas que la version candidate calcule les mêmes valeurs.

Pour les tests applicatifs, installer `requirements.txt` avec
`constraints-demo-app.txt`, puis `requirements_ml_ts.txt` avec les contraintes
app et ml-ts, ainsi que pytest, pytest-asyncio et pytest-mock. Depuis `backend/` :

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
"$PY027" -m pytest -q \
  app/tests/services/test_ml_training.py \
  app/tests/services/test_ml_comparison.py \
  app/tests/services/test_ml_calibration.py \
  app/tests/services/test_ml_registry.py \
  app/tests/services/test_ml_skore_adapter.py \
  app/tests/services/test_ml_lot2_combined.py \
  app/tests/infra/test_demo_dependency_constraints.py
"$PY027" -m pytest -q \
  app/tests/services/test_ml_forecast_harness.py::test_the_regressor_is_diagnosed_one_step_ahead_by_skore
"$PY027" -m pytest -q \
  app/tests/services/test_ml_skore_adapter.py \
  app/tests/infra/test_source_tree_reaches_the_repo.py \
  app/tests/infra/test_python_image_context.py
```

Les tests de registre utilisent les doubles ObjectStore existants et un registre
MLflow de test local. Ils vérifient notamment que le run référence le rapport
déjà stocké, séparément du modèle servi ; ils ne prouvent pas la connectivité
aux services de production.

## Périmètre non qualifié ici

Pas de build Docker, de déploiement, de test contre un MinIO/MLflow de production,
ni d'exécution des modèles profonds. La cohérence statique des contraintes ne
remplace pas la qualification des images. Les corrections de F1 macro, la
classe positive, les partitions persistées et les checks restent les lots
suivants ; ce lot ne change pas silencieusement leur sémantique.
