# Pilote TabICL local — contrat technique P5

La famille `tabular_foundation` est **expérimentale et désactivée par défaut**.
Elle réutilise les jobs ML, les files `ml_deep`/`ml_deep_rpc`, les artefacts
ObjectStore/MinIO, MLflow et les grants Hugging Face de Hyusai. La preuve de
valeur appartient au lot P6 ; les petits jeux de qualification ci-dessous ne
justifient aucune adoption métier.

## Runtime et format du pilote

- TabICL **2.2.0**, torch **2.14.0+cpu**, CPU fixé, quatre threads maximum.
  Fit et reconstruction respectent aussi le plafond `OMP_NUM_THREADS` du worker
  (un thread en son absence), même si l'export provient d'un worker plus large.
  Le profil d'artefact est désormais `tabicl-json-safetensors-v2`. Les exports
  pilotes `v1` embarquent leur ancien code de reconstruction et sont refusés
  avant chargement par le lecteur courant (`ML_ARTIFACT_UNVERIFIED`). Ils doivent
  être régénérés avec ce producteur ; changer seulement leur manifeste ne
  constitue pas une migration. L'ancien environnement peut être conservé pour
  reproduire les smokes historiques, sans leur accorder l'admission courante.
- Un estimateur d'ensemble ; deux profils déclarés : sans cache ou cache en
  mémoire. Aucun cache interne n'est sérialisé. Aucun fine-tuning, tuning libre,
  cross-validation automatique, explication SHAP ou intervalle de prédiction.
  La régression est **refusée avec ou sans cache** à l'entrée du service :
  la parité après export/rechargement a échoué pour les deux profils dans le
  développement P6. Le cache ne constitue pas un correctif démontré. Le refus
  HTTP409 porte le code `ML_TABICL_PROFILE_UNQUALIFIED`, raison `reload_parity`.
  Il couvre entraînement, jobs en attente, promotion, publication comme Skill
  et prédiction sur un ancien modèle résident, qui est alors évincé du cache.
  L'interface annonce ces modèles non appelables. Les profils de classification
  restent expérimentaux ; leurs règles d'admission ne changent pas.
- Jusqu'à 10 000 lignes et 100 variables numériques/catégorielles ; un holdout
  tracé. Les poids sont figés, le contexte d'apprentissage reste sensible.
- Le loader interne `_load_model` de TabICL est remplacé par un adaptateur épinglé
  à 2.2.0, qui construit l'architecture validée et charge les seuls safetensors.
  Toute évolution de TabICL exige une nouvelle qualification.
- L'export contient un contexte JSON borné, les paramètres, l'ordre des classes,
  les versions exactes, les poids et une façade MLflow issue du code contrôlé.
  Le lecteur vérifie d'abord le contrat d'intégrité ancré dans la ligne du modèle.
  Le rechargement reconstruit le prétraitement et le cache à partir du contexte.
- `TabICL.save/load` et son pickle d'estimateur ne sont jamais utilisés. La
  conversion initiale `.ckpt` utilise `torch.load(weights_only=True)` uniquement
  après vérification du SHA-256 officiel épinglé. L'importeur général continue
  de refuser les `.ckpt`.

Référence des poids : `jingang/TabICL`, révision immuable
`4dcd344ece2c00be9e831fdd35bed57b5ad83e19`.

| Tâche | Checkpoint | SHA-256 source |
| --- | --- | --- |
| Classification | `tabicl-classifier-v2-20260212.ckpt` | `bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0` |
| Régression | `tabicl-regressor-v2-20260212.ckpt` | `0db9cb538f114e79026bf08f45f41ad8dd7ad2de2aaca9a5ca8cd3bd9748ae7a` |

## Provisionnement séparé de l'inférence

L'opérateur acquiert explicitement le checkpoint dans un environnement autorisé.
La [notice amont intégrale et sa provenance épinglée](../backend/app/resources/tabicl/README.md)
sont conservées dans le dépôt. Depuis sa racine, avec le runtime `ml-deep` qualifié :

```bash
python backend/scripts/convert_tabicl_checkpoint.py \
  /staging/classification.ckpt /staging/classification \
  --task classification

python backend/scripts/package_tabicl_bundle.py \
  /staging/classification /staging/tabicl-classification.tar \
  --workspace-id WORKSPACE_UUID \
  --signing-key-file /secrets/bundle-exporter.pem \
  --key-id exporter-configure \
  --license-file backend/app/resources/tabicl/LICENSE
```

Le packager exige les octets de cette notice complète et ajoute `license.json`
aux fichiers inventoriés et signés. L'import existant, la copie privée du worker
et l'export autonome transportent ainsi la notice avec les poids dans le même
ObjectStore. La notice Apache-2.0 du module forecast distribué par TabICL est
également conservée, bien que ce module ne soit pas utilisé par le pilote.

Un ancien bundle sans `license.json` ne peut plus être activé ni servir à un
nouvel entraînement (`HF_TABICL_LICENSE_REQUIRED`). Recréer le bundle depuis les
poids convertis avec la notice, importer puis activer le nouvel artefact : ne pas
modifier en place un manifeste signé. Une notice modifiée ou incomplète est
refusée avec `HF_TABICL_LICENSE_INVALID`.

La clé publique doit déjà appartenir aux exporteurs approuvés du dispositif
`HF_BUNDLE_TRUST_KEYS_JSON`. Aucun secret ou grant n'est créé par ces commandes.
Le bundle reçoit une identité dérivée `hyusai-converted/tabicl-v2-classification`
et une révision calculée à partir de la conversion et des octets. Le manifeste
conserve séparément dépôt, révision et empreinte du checkpoint source : les
safetensors convertis ne sont pas présentés comme des fichiers téléchargés de
l'amont.

Importer ensuite le `.tar` par le parcours **offline import existant** du
workspace. Ce parcours vérifie signature, destinataire, licence, quotas et
empreintes ; il écrit dans l'ObjectStore existant avant d'accorder le grant.
Préparer le cache du worker puis demander l'activation avec
`usage=tabular_foundation`, `runtime=ml`. Le probe effectue réellement fit et
prédiction CPU sur des données artificielles locales.

L'algorithme `tabicl_v2` devient utilisable seulement si
`ML_TABICL_ENABLED=true`, que le workspace appartient à `ML_TABICL_WORKSPACES`,
que le runtime est disponible et qu'un artefact activé est autorisé. Les requêtes
sélectionnent son UUID `artifact_id`, jamais un chemin libre ou une URL. Choisir
le checkpoint correspondant à la tâche ; le harness refuse toute divergence.

Une prédiction revalide le grant et les flags du pilote, y compris lorsque le
modèle est déjà en cache. Une révocation refuse la requête et évince la copie
résidente. Le modèle n'est pas promu automatiquement et n'est pas choisi comme
champion de repli. Promotion et exposition métier restent soumises aux gates
existantes et à la décision P6.

## Vérification reproductible

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 \
python backend/scripts/qualify_tabicl_offline.py /staging/tabicl-weights \
  --report /staging/tabicl-offline-proof.json
```

Le répertoire doit contenir `classification.ckpt`, `regression.ckpt` et les deux
répertoires convertis `classification/`, `regression/`. Sous Linux, le script
installe un filtre seccomp qui refuse les appels de connexion/envoi réseau et
vérifie le refus `EPERM` avant tout fit. Il compare l'adaptateur à l'estimateur
amont, exporte le contexte, supprime la copie de provisionnement et recharge
uniquement l'export ; tolérance `rtol=atol=1e-6`. Un environnement sans seccomp ne
reçoit pas de preuve offline positive.

La [preuve locale conservée](evidence/probabl-tabicl-offline.json) contient les
versions, les deux parités et les pics mémoire observés sous blocage seccomp.
Cette vérification réduite ne qualifie pas tous les profils : le
[diagnostic de parité P6](evidence/probabl-tabicl-parity-diagnostic.json) conserve
l'échec ultérieur de régression sans cache, jusqu'à `3,6621e-4` d'écart absolu
et 59 violations sur 120 sorties au seuil inchangé `rtol=atol=1e-6`.
Les contrôles excluent une mutation des données ou des sorties ; la cause
numérique interne précise reste non isolée. Des reproductions indépendantes
peuvent passer, ce qui ne retire pas les échecs. Le développement P6 suivant a
aussi refusé la parité de `linear-regression-demo/dev-1` avec cache ; cet échec
justifie le retrait de toute régression du produit, sans interrompre les mesures
du protocole gelé. Aucun final réservé n'a servi au diagnostic. Le profil
d'artefact `v2` garantit le contrat de lecture et le plafond CPU ; il n'atteste
pas la parité numérique d'un modèle ni son admission produit.

Les tests `test_tabicl_pilot.py` couvrent aussi le défaut désactivé, le refus des
configurations arbitraires et des poids altérés, l'absence de contournement des
grants, leur révocation sur cache chaud, et l'admission signée vers le stockage
existant. Les vrais roundtrips du harness et de MLflow ont été exécutés pour les
deux tâches. La taille des jeux smoke et leurs timings ne caractérisent ni la
frugalité du pilote complet ni les performances d'un serveur cible.
