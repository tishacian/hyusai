# Lot 6a — runtime optionnel pour modèles locaux

Le profil Compose `ml-deep` ajoute une image et deux pools indépendants. Sans ce
profil, le déploiement, les modèles tabulaires et `ml-ts` gardent leur comportement.
Aucune migration : Alembic reste au head `122_ml_families`.

| Service | Queue | Concurrence par défaut | Mémoire |
| --- | --- | --- | --- |
| `agentium-worker-ml-deep` | `ml_deep` | 1 | 8 Gio |
| `agentium-worker-ml-deep-serve` | `ml_deep_rpc` | 1, pool threads | 4 Gio |

Le cache de modèles servis est limité à une entrée (`ML_PREDICT_CACHE_SIZE=1`)
pour éviter de multiplier les copies des poids dans le pool interactif.

Les deux services utilisent `app.workers.celery_ml`, n'exécutent pas beat et
annoncent `ML_RUNTIME=ml-deep`. Le TTL du heartbeat existant reste 180 secondes.
Le pool interactif ne reste donc pas derrière un entraînement dans sa queue.
Les familles clientes choisissent `celery_ml_deep_queue` et
`celery_ml_deep_serve_queue` ; le worker général ne consomme aucune de ces queues.

L'image conserve le préfixe commun aux images API, worker et `ml-ts`, puis ajoute
la pile `ml-ts`, torch et les providers. Les versions communes restent celles de
`constraints-demo-app.txt`. Les ajouts sont figés dans
`constraints-demo-ml-deep.txt` : Chronos 2.3.2, sentence-transformers 6.1.0,
accelerate 1.15.0 et einops 0.8.2. Torch 2.14.0+cpu vient exclusivement de
`TORCH_INDEX_URL`, par défaut `https://download.pytorch.org/whl/cpu`.
Ni le catalogue, ni l'API, ni l'import du worker ML ne chargent ces providers.
L'empreinte d'exécution conserve leurs versions sans les importer.

## Provisionnement explicite des poids

Les poids ne sont ni téléchargés au démarrage ni intégrés dans l'image.
L'opérateur monte `AGENTIUM_ML_DEEP_MODELS_PATH` en lecture seule dans
`/data/models`, sur les deux services. L'API n'a pas besoin de ce montage.
`HF_HUB_OFFLINE=1` et `TRANSFORMERS_OFFLINE=1` s'appliquent dans l'image et Compose.
Le cache HF temporaire ne constitue pas une source de modèles.

Deux identifiants sont autorisés ; aucun chemin ou identifiant distant fourni
par un utilisateur n'est accepté :

| Identifiant Agentium | Provider public | Révision qualifiée pour le spike |
| --- | --- | --- |
| `chronos-2-small` | `autogluon/chronos-2-small` | `ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a` |
| `multilingual-minilm` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` |

L'acquisition de ces snapshots publics se fait séparément, sur une machine de
préparation autorisée à accéder au provider, avec les révisions ci-dessus et
uniquement les fichiers nécessaires au chargement local. On transfère ensuite
les répertoires ordinaires dans le volume ; les symlinks vers un cache externe
ne sont pas admis. Le modèle de prévision nécessite `config.json` et
`model.safetensors` (environ 112 Mo) ; l'encodeur inclut ses poids, tokenizer et
configuration sentence-transformers (environ 486 Mo). Aucun package interne ni
modèle provenant d'une autre application n'est requis.

Le script suivant ne fait aucun accès réseau. Il enregistre les SHA-256 des
fichiers déjà présents, associe la révision et conserve les autres entrées :

```sh
python backend/scripts/provision_ml_deep_manifest.py \
  --models-dir /data/models --model-id chronos-2-small \
  --path chronos-2-small \
  --revision ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a

python backend/scripts/provision_ml_deep_manifest.py \
  --models-dir /data/models --model-id multilingual-minilm \
  --path multilingual-minilm \
  --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42
```

Il produit `/data/models/manifest.json` de version 1, avec pour chaque entrée
`kind`, `upstream_id`, `revision`, `path` relatif et `files` (chemin → SHA-256).
Le résolveur refuse les fichiers ajoutés ou absents, les empreintes modifiées,
les traversées de répertoire, les symlinks sortants et les révisions flottantes.
Chaque entraînement revérifie tous les octets. Le heartbeat peut réutiliser une
vérification tant que le manifeste et les métadonnées inode/taille/mtime/ctime de
l'inventaire ne changent pas.

Le heartbeat transmet seulement l'identité publique, la révision et l'empreinte
des bundles valides dans `packages_json.agentium_models`. Le catalogue ne lit
pas le disque des workers. Un modèle est indisponible si son bundle manque, si
un worker de sa queue ne l'annonce pas, si les workers annoncent des révisions
différentes ou si les battements expirent. Aucun chemin interne n'est exposé.
Les métadonnées de heartbeat ne remplacent jamais la vérification au fit.

## Activation et variante GPU

Après construction et provisionnement, l'opérateur ajoute `--profile ml-deep`
à sa commande Compose habituelle. Les services reprennent le tag et la révision
explicites du déploiement. Le profil reste désactivé tant que cette activation
n'a pas été demandée. La recette doit vérifier les deux heartbeats, l'identité
des bundles, un entraînement et un appel servi. Le poids final de l'image et ses
couches sont à mesurer pendant la qualification d'image ; ce document ne
présente pas de taille d'image construite localement.

Une variante CUDA doit être une image distincte, qualifiée séparément. Changer
uniquement `TORCH_INDEX_URL` ne suffit pas : le pin CPU commun ferait échouer
la résolution. La variante doit conserver toutes les versions applicatives,
remplacer seulement les builds `torch`/`torchvision` `+cpu` par les builds CUDA
correspondants dans son fichier de contraintes, puis appliquer ce fichier aux
installations spécifiques de son Dockerfile après le préfixe commun. Elle
sélectionne l'index PyTorch CUDA correspondant via `TORCH_INDEX_URL` et réserve
explicitement un GPU NVIDIA dans son overlay Compose (`capabilities: [gpu]`).
Elle exige NVIDIA Container Toolkit sur l'hôte, une vérification des contraintes,
les mêmes tests d'export/rechargement et une qualification mémoire/latence avant
activation. Les loaders livrés ici sont qualifiés sur CPU ; leur sélection du
device doit être qualifiée avec la variante CUDA. Aucune autre image ne reçoit
une dépendance ou une réservation GPU.

## Vérification du sous-lot

- Résolution et cache de provenance, altération de poids et inventaire,
  identité refusée, montage absent, battements périmés ou contradictoires.
- Imports de l'API et des métadonnées sans torch, transformers, Chronos ni
  sentence-transformers, même si ces packages sont installés.
- Contraintes additives, préfixes d'images communs, contexte Docker sans secrets.
- Résolution Compose du profil : queues séparées, poids montés en lecture seule.

Les capacités de prévision zéro-shot et d'encodage de texte sont livrées par les
sous-lots 6b et 6c. Les modèles temporels profonds entraînés restent sur demande.
