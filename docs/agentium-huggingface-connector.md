# Connecteur Hugging Face — spec

Statut : proposition. Les arbitrages du §11 sont validés ; la spec est à
relire avant implémentation.

## 1. Objectif

Hugging Face devient une source de premier rang pour Agentium, sur deux objets :

- **les modèles**, quel que soit leur usage : LLM open weights, embeddings et
  rerankers du RAG, modèles des familles ML profondes, et tout usage futur ;
- **les datasets**, importés comme datasets tabulaires Agentium.

Le connecteur ne dépend d'aucun usage. Il produit des **artefacts figés et
vérifiés**. Chaque usage (LLM, RAG, ML) les consomme par un adaptateur. Ajouter
un usage ne change ni le connecteur ni le magasin.

## 2. Ce qui existe

| Brique | Aujourd'hui | Ce que la spec en fait |
|---|---|---|
| Registre `connectors/generic` | Config par workspace, secrets Fernet en écriture seule, test de connexion | Accueille la connexion `huggingface` |
| Portail LLM (`model_plane`) | Routes nommées, fournisseurs cloud, nœuds de service vLLM / llama.cpp / Ollama exposant `/v1` | Reçoit les LLM open weights importés et le fournisseur HF Inference |
| RAG | Rerankers ONNX figés par `rag_models.lock.json` et cuits dans l'image ; embeddings OpenAI ou sentence-transformers | Peut choisir un artefact importé, avec réindexation explicite |
| ML deep (lot 6a) | `MODEL_SPECS` fermé à deux modèles, manifeste écrit à la main par l'opérateur | Le manifeste est produit par l'import ; la liste fermée devient une règle par type |
| Datasets tabulaires | Upload, Postgres, `register_frame`, Parquet dans MinIO | Gagnent la source `huggingface` |
| Object store | MinIO, identifiants séparés par rôle | Devient le magasin des modèles |

Les invariants actuels restent vrais : les runtimes qui exécutent les modèles
sont hors ligne vis-à-vis du Hub, les poids leur sont montés en lecture seule et
chaque chargement revérifie les empreintes.

## 3. Concepts

**Connexion Hugging Face.** Un endpoint (`https://huggingface.co` par défaut,
ou un miroir / Hub d'entreprise) et un jeton optionnel, chiffré, jamais relu.
Le jeton ouvre les dépôts privés et les dépôts à accès restreint (gated). Une
connexion plateforme sert à tous les workspaces ; un workspace peut poser la
sienne pour ses dépôts privés.

**Artefact.** Un dépôt Hugging Face figé à un commit, matérialisé dans le
magasin Agentium :

```
artifact_id, kind (model | dataset), repo_id, revision (sha 40 hex),
requested_ref (ex. main), files {chemin: sha256}, total_bytes,
format (safetensors | gguf | onnx | parquet), license, license_class,
gated, private, pipeline_tag, library, imported_at,
status (pending | fetching | ready | failed | revoked)
```

Un artefact est immuable. Suivre une nouvelle révision crée un nouvel
artefact ; l'ancien reste chargeable tant qu'un usage le référence.

**Stocké une fois, autorisé par workspace.** Les octets sont rangés par
`repo_id@revision` : un modèle importé par trois workspaces n'occupe la place
qu'une fois. Un workspace y accède par une **autorisation**
(`workspace_id, artifact_id, granted_by, license_accepted_by, license_accepted_at`).
Il voit les artefacts qu'il a importés et le **catalogue plateforme**, publié
par un admin plateforme (par exemple Chronos, MiniLM, les rerankers).

Le partage des octets ne donne jamais l'accès. Pour un dépôt privé ou gated,
chaque workspace prouve son accès avec son propre jeton avant de recevoir
l'autorisation. Si l'artefact existe déjà, seul ce contrôle d'accès est refait,
pas le téléchargement. L'acceptation de licence se fait par workspace.

**Usage.** Le lien entre un artefact autorisé et ce qui l'exécute : une route
LLM, une collection RAG, une famille ML. Un usage ne voit qu'un `artifact_id`,
jamais un chemin, une clé d'objet ni un jeton.

## 4. Parcours

### 4.1 Parcourir

Depuis Ressources → Connecteurs → Hugging Face, l'utilisateur recherche un
modèle ou un dataset. Agentium interroge l'API du Hub côté serveur et affiche,
pour chaque dépôt : tâche (`pipeline_tag`), bibliothèque, licence et sa classe
(§8), statut gated, taille par format et statut de sécurité du Hub. Il voit
aussi les usages compatibles : « utilisable comme LLM », « comme embedding »,
« comme reranker », « dans la famille Chronos ».

La compatibilité est calculée à partir des métadonnées et de la liste des
fichiers, avant tout téléchargement.

### 4.2 Importer

L'utilisateur choisit une révision (une branche ou un tag, résolu
immédiatement en sha) et un format quand le dépôt en propose plusieurs, par
exemple une quantification GGUF précise. L'import devient un job :

1. **Résolution.** `ref → sha`. La liste des fichiers et leurs empreintes LFS
   viennent de l'API du Hub, à ce sha.
2. **Licence.** La classe de licence (§8) est appliquée : import direct,
   acceptation explicite requise, ou refus.
3. **Politique de fichiers.** On ne retient que des fichiers de données :
   - poids `*.safetensors`, `*.gguf`, `*.onnx`, et leurs index ;
   - configurations et tokenizers (`*.json`, `tokenizer.model`, `*.spm`,
     `*.txt` de vocabulaire) ;
   - modules sentence-transformers ;
   - pour un dataset, les fichiers Parquet.

   Sont refusés : `*.bin`, `*.pt`, `*.pth`, `*.pkl`, `*.ckpt`, tout `*.py`, et
   tout dépôt qui exige `trust_remote_code`. Un dépôt sans format sûr est
   refusé avec une erreur nommée (`HF_UNSAFE_FORMAT`), pas importé à moitié.
4. **Bornes.** Les bornes du §7 portent sur les fichiers retenus, pas sur le
   dépôt entier : un dépôt GGUF contient souvent une dizaine de quantifications.
   Le dépassement est refusé avant le téléchargement.
5. **Téléchargement.** Seul le worker `hub-fetch` a un accès réseau sortant
   vers le Hub. Il envoie chaque fichier dans MinIO en multipart, calcule son
   SHA-256 pendant le transfert et le compare à l'empreinte LFS du Hub.
6. **Manifeste.** Écrit en dernier, dans le même format que le lot 6a en
   version 2 : il ajoute `repo_id`, `kind`, `format` et `license`. Sa présence
   marque l'artefact `ready` ; un import interrompu n'a pas de manifeste et
   n'est jamais lu.

Chaque import, refus, acceptation de licence et révocation est un événement
d'audit.

### 4.3 Utiliser

L'artefact `ready` apparaît dans les sélecteurs des usages compatibles (§5).
Activer un usage local déclenche sa matérialisation dans le cache (§6).

Un administrateur peut **révoquer** un artefact : les usages qui le
référencent passent indisponibles avec une raison lisible, puis les objets
MinIO et les copies en cache sont supprimés une fois qu'aucun runtime ne les a
ouverts. Retirer une autorisation de workspace ne supprime les octets que si
plus aucun workspace ni le catalogue plateforme ne les référence.

### 4.4 Sans accès Internet

Pour un client isolé, le même artefact s'importe en déposant un bundle
(fichiers et manifeste) produit sur une machine connectée. Les vérifications
sont identiques, seule la source change.

## 5. Adaptateurs d'usage

### 5.1 LLM open weights

Le portail LLM sait déjà déclarer un nœud de service compatible OpenAI. Il
gagne une action : **déployer un artefact sur un nœud**.

- Le nœud reçoit la référence `artifact_id` et le manifeste. Il vérifie le
  SHA-256 de chaque fichier contre ce manifeste, quelle que soit la source.
- **Source des poids.** Pour un dépôt public, le nœud tire directement du Hub,
  au sha du manifeste. Il passe par MinIO, avec des URL présignées et
  temporaires, dans trois cas :
  - un dépôt privé ou gated, pour que le jeton Hugging Face ne quitte jamais
    Agentium ;
  - un nœud sans accès Internet ;
  - une révision supprimée ou devenue gated sur le Hub après l'import.
- Le nœud lance le runtime adapté au format : vLLM pour safetensors,
  llama.cpp pour GGUF. La route du portail enregistre le nom servi, le
  `repo_id@sha` et la quantification. La provenance d'un appel LLM inclut
  l'artefact.
- Agentium ne sert pas de GPU lui-même ; la VM de démo n'en a pas. Le
  dimensionnement (mémoire GPU, contexte, quantification) est vérifié contre la
  capacité déclarée du nœud avant le déploiement.

**Fournisseur HF Inference.** Indépendamment de l'import, la connexion permet
d'ajouter `huggingface` aux fournisseurs du portail, via son routeur compatible
OpenAI. Le modèle est appelé à distance avec le jeton de la connexion, sans
téléchargement. Il obéit aux mêmes règles de routage, de coût et de
`allowed_models` que les autres fournisseurs cloud, et à la politique de
licences du §8.

### 5.2 RAG

- **Embeddings.** Un artefact compatible sentence-transformers devient
  sélectionnable comme modèle d'embedding d'une collection. Changer le modèle
  d'une collection existante impose une réindexation, annoncée avec son coût ;
  les vecteurs d'un modèle ne sont jamais mélangés à ceux d'un autre.
- **Rerankers.** Un artefact cross-encoder en ONNX est chargé par le chemin ONNX
  actuel. En safetensors, il passe par le chemin torch, sur un worker qui
  l'a installé.
- Les modèles cuits dans l'image restent le défaut et le repli.

### 5.3 ML

`MODEL_SPECS` cesse d'être une liste fermée d'identifiants. Il devient une règle
par type d'usage :

- `forecasting` : architecture Chronos reconnue, safetensors ;
- `embedding` : sentence-transformers, safetensors.

Le manifeste version 2 remplace le provisionnement manuel du lot 6a. Les
workers `ml_deep` lisent le cache local en lecture seule, comme ils lisent
aujourd'hui `/data/models`.

### 5.4 Datasets

Un artefact dataset s'importe comme dataset tabulaire par `register_frame`,
avec `source="huggingface"` et la provenance `hf://repo@sha/config/split` :

- l'utilisateur choisit la config, le split et, si besoin, les colonnes et un
  plafond de lignes ;
- la lecture passe par les fichiers Parquet du dépôt, ou par la conversion
  Parquet que le Hub publie (`refs/convert/parquet`), jamais par un script de
  chargement ;
- les fichiers bruts sont temporaires : le résultat est le Parquet du dataset
  tabulaire, déjà stocké dans MinIO. L'artefact garde la provenance et le
  manifeste.

Le même import existe comme bloc de Flow (`hf_dataset_import_v1`). Il est figé
sur un sha, donc rejouable à l'identique.

## 6. Stockage et runtime

**Magasin : MinIO.** Les modèles sont stockés sous
`hub/models/{owner}/{repo}/{sha}/`, avec le manifeste à côté des fichiers. Une
clé d'objet ne change jamais : un nouveau sha est un nouveau préfixe. MinIO
sert aussi les URL présignées des nœuds LLM (§5.1) et prépare Agentium à
tourner sur plusieurs machines.

**Cache local.** Les runtimes lisent des fichiers locaux, souvent en mmap
(safetensors, GGUF). Chaque artefact utilisé localement est donc matérialisé
dans `/srv/agentium-data/hub-cache/{sha}/` :

- `hub-fetch` copie depuis MinIO, revérifie chaque SHA-256 contre le manifeste
  et publie atomiquement ;
- les runtimes (`ml_deep`, workers RAG) montent ce cache **en lecture seule**
  et ne parlent jamais au Hub ; ils gardent `HF_HUB_OFFLINE=1` ;
- le cache est borné (§7) et évincé du moins récemment utilisé, sauf les
  artefacts qu'un usage actif référence ;
- une copie absente du cache est rematérialisée depuis MinIO, jamais depuis le
  Hub.

**Worker `hub-fetch`.** Image légère (`huggingface_hub` et client S3, sans
torch), queue `hub_fetch`. C'est le seul composant avec un accès sortant vers
le Hub. Il a une identité MinIO dédiée, limitée en écriture au préfixe `hub/`,
et il est le seul à écrire dans le cache. Les runtimes lisent `hub/` avec une
identité en lecture seule quand ils en ont besoin.

**Registre.** Tables `hub_artifacts`, `hub_artifact_grants` et
`hub_artifact_usages`, dans le même schéma que les datasets.

**Contrat de stockage VM.** Le cache est ajouté au contrat comme
`ml-deep-models` l'a été : chemin protégé sur le disque de données, montage en
lecture seule pour les runtimes, écriture réservée à `hub-fetch`.

## 7. Bornes par défaut

| Borne | Défaut | Repère |
|---|---|---|
| Taille d'un modèle (fichiers retenus) | 20 Go ; un admin plateforme peut monter à 80 Go | Un modèle 8B en bf16 fait environ 16 Go, un 32B en GGUF Q4 environ 20 Go ; un 70B en Q4 (environ 42 Go) est une décision explicite |
| Quota par workspace | 50 Go | Deux ou trois LLM moyens, plus les embeddings |
| Quota plateforme (MinIO) | 150 Go | Octets dédupliqués, comptés une fois |
| Cache local | 40 Go | Modèles exécutés sur la VM : RAG et ML, pas les LLM des nœuds |
| Imports simultanés | 1 par workspace, 2 pour la plateforme | Bande passante de la VM |
| Dataset : octets téléchargés | 256 Mo | Même valeur que l'upload (`tabular_upload_max_bytes`) |
| Dataset : lignes | 5 M au maximum, avec l'option « N premières lignes » | Même valeur que `tabular_transform_max_rows` ; l'entraînement ML plafonne déjà à 2 M |
| Dataset : colonnes | 512 | Même valeur que `tabular_max_columns` |

Toutes les bornes sont des réglages de plateforme.

**Capacité de la VM de démo.** MinIO et le cache sont sur le même disque de
données : 492 Go, dont 242 Go libres le 9 octobre 2026, avec 152 Go déjà
occupés par MinIO. Le quota plateforme et le cache pleins consomment 190 Go et
laissent environ 50 Go. Une alerte à 80 % d'occupation du disque est
nécessaire avant HF-3, et l'extension du disque est à prévoir avant que les
quotas soient atteints.

## 8. Licences

La politique est définie au niveau plateforme, à partir du tag de licence du
dépôt, en trois classes :

| Classe | Licences | Effet |
|---|---|---|
| Autorisée | `apache-2.0`, `mit`, `bsd-2-clause`, `bsd-3-clause`, `cc-by-4.0`, `cc0-1.0` | Import direct |
| Acceptation tracée | Licences communautaires à conditions (`llama3.*`, `gemma`, `openrail`, `openrail++`, `creativeml-openrail-m`), `cc-by-sa-4.0`, `other` | Un admin du workspace lit le texte de licence et l'accepte ; l'acceptation est enregistrée (qui, quand, licence à quel sha) |
| Bloquée | Non commerciales et recherche (`cc-by-nc-*`), licence absente ou `unknown` | Refus ; seul un admin plateforme débloque, au cas par cas, avec trace |

- **Par client, on resserre seulement.** Un workspace peut déplacer une licence
  vers une classe plus stricte (une banque n'autorise qu'`apache-2.0` et `mit`,
  par exemple), jamais vers une classe plus souple.
- **Datasets.** Même règle. Un dataset non commercial n'entraîne pas un modèle
  servi à un client.
- **HF Inference.** La classe s'applique aussi aux modèles appelés à distance.
- **Limite.** Le tag de licence est déclaré par l'auteur du dépôt. La politique
  filtre ; elle ne remplace pas une revue juridique des licences
  personnalisées, en particulier `other`.

## 9. Droits

| Action | Rôle |
|---|---|
| Configurer la connexion plateforme, publier au catalogue plateforme, régler les bornes et la politique de licences | Admin plateforme |
| Configurer une connexion de workspace, resserrer la politique de licences | Admin du workspace |
| Parcourir | Tout membre ayant accès aux ressources |
| Importer un dataset | Éditeur du workspace |
| Importer un modèle, accepter une licence, déployer un LLM, révoquer | Admin du workspace ; admin plateforme pour les artefacts du catalogue |

Un dépôt gated n'est importable que si le jeton a déjà reçu l'accès sur le Hub.

## 10. Erreurs nommées

`HF_UNCONFIGURED`, `HF_AUTH_REQUIRED`, `HF_GATED`, `HF_NOT_FOUND`,
`HF_REVISION_UNRESOLVED`, `HF_UNSAFE_FORMAT`, `HF_REMOTE_CODE_REQUIRED`,
`HF_LICENSE_BLOCKED`, `HF_LICENSE_ACCEPTANCE_REQUIRED`, `HF_TOO_LARGE`,
`HF_QUOTA_EXCEEDED`, `HF_CHECKSUM_MISMATCH`, `HF_INCOMPATIBLE_USAGE`,
`HF_ARTIFACT_REVOKED`.

## 11. Arbitrages validés

1. **Partage.** Octets stockés une fois par `repo@sha`, visibilité par
   workspace par autorisation, plus un catalogue plateforme. L'accès aux dépôts
   privés et gated est prouvé par workspace (§3).
2. **Magasin.** MinIO, avec un cache local en lecture seule pour les runtimes,
   alimenté par `hub-fetch` (§6).
3. **Bornes.** 20 Go par modèle, 50 Go par workspace, 150 Go pour la
   plateforme, 40 Go de cache, datasets alignés sur l'upload (§7).
4. **Nœuds LLM.** Le Hub par défaut avec vérification du manifeste ; MinIO
   pour les dépôts privés ou gated, les nœuds isolés et les révisions
   disparues (§5.1).
5. **Licences.** Trois classes au niveau plateforme, que chaque workspace peut
   seulement resserrer (§8).

## 12. Découpage

| Lot | Contenu | Valeur |
|---|---|---|
| HF-1 | Connexion, test de connexion, recherche dans le Hub avec classe de licence, fournisseur HF Inference dans le portail | LLM open weights utilisables à distance tout de suite |
| HF-2 | Registre d'artefacts et autorisations, worker `hub-fetch`, politique de fichiers et de licences, magasin MinIO, import de datasets et bloc de Flow | Datasets Hugging Face dans les modèles et les Flows |
| HF-3 | Cache local, usages RAG et ML, manifeste version 2, fin du provisionnement manuel du lot 6a | Embeddings, rerankers et modèles profonds au choix |
| HF-4 | Déploiement d'un artefact LLM sur un nœud du portail, URL présignées MinIO | LLM open weights servis sur notre infrastructure |
| HF-5 | Import par bundle hors ligne, révocation et purge | Clients isolés, cycle de vie complet |

Chaque lot se recette sur la VM de démo, avec un vrai dépôt public, un dépôt
gated et un dépôt refusé par la politique de licences.

HF-4 suppose que les nœuds du portail atteignent MinIO pour les URL
présignées. L'exposition de MinIO aux nœuds (réseau privé ou proxy dédié) est
à fixer avec l'hébergement des nœuds, avant ce lot.
