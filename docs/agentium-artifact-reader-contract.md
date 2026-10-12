# Contrat de lecture des modèles Agentium

Le contrat `contract_version: 1` est produit après l'export MLflow complet et
conservé dans `MLModel.metrics_json.artifact` par le service d'apprentissage.
Cette ligne autorisée constitue l'ancre de confiance. Un manifeste récupéré
avec ses propres fichiers ne peut pas accorder de droits de désérialisation.
MinIO/ObjectStore conserve les octets ; aucun registre supplémentaire n'est créé.

Le lecteur contrôle, avant `mlflow.pyfunc.load_model` :

- namespace exact du workspace et du modèle, inventaire complet et chemins
  relatifs canoniques, absence de liens symboliques ;
- au plus 2 048 fichiers et un plafond **total** de
  `ML_TRAIN_ARTIFACT_LIMIT_MB` (512 Mio par défaut), également utilisé pour la
  taille décompressée de l'archive skops ; au plus 100 000 entrées internes et
  16 Mio de répertoire ZIP, contrôlés avant son allocation complète ;
- taille déclarée avant copie, copie réellement bornée en flux, puis tailles et
  SHA-256 de tous les fichiers, dont `MLmodel` et les métadonnées de préparation ;
- famille, format, profil de confiance et versions effectives de lecture ;
- pour skops, égalité entre les types du modèle, ceux du manifeste et ceux
  déclarés par MLflow, puis inclusion dans une liste **côté lecteur** de noms
  précis qualifiés. L'appartenance à un préfixe comme `numpy.` ne suffit pas.

L'identité du cache de serving inclut le contrat complet : une modification
administrative des métadonnées invalide la copie déjà chargée.

Le profil fondation tabulaire courant est `tabicl-json-safetensors-v2` : il
qualifie le code embarqué de reconstruction qui respecte le plafond de threads
du lecteur. Les exports pilotes `v1` sont refusés avant chargement et doivent
être régénérés ; leurs versions de dépendances identiques ne suffisent pas.

| Famille | Format | Portée du contrôle |
| --- | --- | --- |
| Tabulaire classique / clustering | skops | Inventaire, intégrité, versions, types autorisés et archive bornée. |
| Embeddings texte | cloudpickle | Exception existante : code exécutable ; intégrité, versions et provenance du producteur, dans le runtime `ml-deep`. |
| Prévision classique | skops / joblib | Exception joblib existante documentée, dans le runtime `ml-ts` ; manifeste désormais complet, incluant le code pyfunc et les métadonnées. |
| Fondation temporelle | JSON / safetensors | Inventaire complet, versions et code pyfunc ancré dans le manifeste. |
| Fondation tabulaire | JSON / safetensors | Contrat commun avant le chargeur dédié ; aucun fallback pickle/skops implicite. |

Une empreinte ne rend pas cloudpickle ou joblib inoffensifs. Les modèles doivent
provenir du producteur Agentium autorisé, pas d'un téléversement de code arbitraire.

## Versions et modèles historiques

La politique initiale exige l'égalité des versions enregistrées : Python
majeure/mineure et versions exactes des dépendances de la famille. Le changement
de version provoque `ML_ARTIFACT_RUNTIME_MISMATCH`, avec versions producteur et
lecteur. Des roundtrips réussis dans chaque runtime ne suffisent pas à autoriser
une lecture entre tous les runtimes. Une extension de cette politique nécessite
une matrice de compatibilité explicite sur les combinaisons effectivement
supportées ; elle ne doit jamais découler du simple succès de l'import Python.

Un modèle historique sans contrat v1 provoque
`ML_ARTIFACT_LEGACY_UNSUPPORTED` **avant copie et désérialisation**. Sa ligne n'est
ni réécrite ni marquée comme corrompue ; ses octets ne sont pas modifiés et aucun
manifeste n'est fabriqué après coup. Il faut conserver son déploiement producteur
pour le servir ou demander explicitement un nouvel entraînement. Le nouveau
lecteur ne sait pas router automatiquement un modèle vers une ancienne image.
Ce refus et la conservation de l'ancienne image doivent être pris en compte
avant une activation VM ; le rollback reste celui du déploiement existant.

## Qualification reproductible

`backend/app/tests/services/test_ml_artifact_contract.py` réalise des exports et
chargements MLflow/skops réels : classification et régression, encodages
`auto`/`string`/`minhash`, calibration/seuil et clustering. Il vérifie aussi les
refus de modification, de types non autorisés, de version, de chemins, de liens
et de volumes, sans appeler un désérialiseur sur le bundle refusé.

Exécuter le fichier dans le runtime producteur courant puis dans le candidat
(skrub 0.11.0 / skops 0.16.0). En parallèle, utiliser des `--basetemp` distincts
pour éviter que la rétention pytest d'un processus supprime les fichiers d'un
autre. Compléter avec les suites serving tabulaire, clustering et forecasting.

Résultat local du 11 octobre 2026 : **27 tests passent dans chacun des deux
runtimes**, plus un test dédié vérifiant que le serving refuse une altération
avant d'appeler MLflow. La lecture croisée de huit exports produits avec skops
0.14.0 / skrub 0.10.1 dans skops 0.16.0 / skrub 0.11.0 **refuse six modèles**
HistGradientBoosting (classification/régression × trois encodeurs) : le nouveau
lecteur exige de déclarer explicitement `TreePredictor`, absent de la liste
MLflow produite par 0.14.0. Les deux autres cas (calibration/seuil et clustering)
conservent leurs prédictions. Ce résultat interdit d'affirmer une compatibilité
générale ou d'élargir silencieusement la confiance des anciens modèles.
Les nouveaux exports 0.16.0 déclarent ce type et sont qualifiés par le profil
précis du lecteur. [Preuve résumée](archive/2026/evidence/probabl-skops-compatibility.json).

Les contrôles complémentaires couvrent les cinq fréquences forecasting publiées
(`h`, `D`, `W`, `MS`, `QS`), les dépendances pyfunc sortant du bundle, le namespace
inter-workspace et l'allocation du répertoire ZIP. La régression serving
(clustering, forecasting, prédiction tabulaire) a donné 132 succès et une ancienne
assertion à adapter : le test d'artefact absent utilisait une URI d'un autre
workspace, désormais refusée plus tôt. Le test corrigé supprime les objets dans
son namespace autorisé ; il passe, ainsi que le test dédié au refus inter-workspace.
