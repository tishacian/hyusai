# Connecteur Hugging Face — spec

Statut : implémentation Agentium livrée, recette d'environnement restante.
Les arbitrages du §11 et les contrats ci-dessous restent la référence.
Le [guide d'exploitation](huggingface-operations.md) détaille les parcours
livrés, le déploiement et les limites vérifiées. La prise en charge du protocole
HF-4 par le service externe des nœuds LLM reste à vérifier et, si nécessaire,
à compléter ; les critères de recette du §12 conditionnent la validation de
chaque lot sur la VM.

La [note de reprise HF-4](agentium-huggingface-hf4-handoff.md) rassemble les
travaux à effectuer par un agent ayant accès au service des nœuds LLM.

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

Les invariants actuels restent vrais : les processus qui exécutent les modèles
sont hors ligne vis-à-vis du Hub, les poids leur sont montés en lecture seule et
chaque chargement revérifie les empreintes. Sur les nœuds LLM, le téléchargement
est réalisé par un agent de préparation distinct du processus d'inférence (§5.1).

## 3. Concepts

**Connexion Hugging Face.** Un endpoint (`https://huggingface.co` par défaut,
ou un miroir / Hub d'entreprise) et un jeton optionnel, chiffré, jamais relu.
Le jeton ouvre les dépôts privés et les dépôts à accès restreint (gated). Une
connexion plateforme sert à tous les workspaces ; un workspace peut poser la
sienne pour ses dépôts privés.

La configuration plateforme est un stockage distinct des réglages de
workspace existants. La résolution de connexion est explicite : connexion du
workspace si présente, sinon connexion plateforme. Un échec d'autorisation
avec le jeton du workspace ne déclenche pas de repli vers le jeton plateforme.

**Artefact.** Une sélection de fichiers d'un dépôt Hugging Face figé à un
commit, matérialisée dans le magasin Agentium :

```
artifact_id, hub_endpoint, kind (model | dataset), repo_id,
revision (sha 40 hex), requested_ref (ex. main),
format (safetensors | gguf | onnx | parquet), variant, selection_digest,
files {chemin: {size_bytes, sha256, upstream_hash: {algorithm, value}}},
total_bytes, license, license_class,
gated, private, pipeline_tag, library, imported_at,
status (pending | fetching | ready | failed | revoked)
```

Le contenu et la provenance d'un artefact sont immuables ; son statut décrit
son cycle de vie. L'identité comprend l'endpoint normalisé, le type de dépôt,
le `repo_id`, le commit et la sélection. `selection_digest` est le SHA-256
d'une représentation canonique du format, de la variante et de la liste triée
des chemins avec leurs empreintes source à ce commit. Deux quantifications
GGUF, ou deux sélections de fichiers, produisent des artefacts distincts même
au même commit. Une nouvelle révision produit également un nouvel artefact ;
l'ancien reste chargeable tant qu'il est autorisé et non révoqué.

Pour un dataset, la sélection inclut aussi les paramètres et versions de
transformation du §5.4. Sa matérialisation durable est le résultat tabulaire
figé ; le manifeste distingue les fichiers source du résultat conservé.

**Stocké une fois, autorisé par workspace.** Dans un même endpoint et type de
dépôt, les octets sont rangés par `repo_id@revision/fichier` : deux artefacts
peuvent partager un fichier sans partager leur manifeste. Un modèle importé
par trois workspaces n'occupe la place qu'une fois. Un workspace y accède par
une **autorisation** (`workspace_id, artifact_id, granted_by, granted_at,
revoked_at, license_accepted_by, license_accepted_at, license_digest,
policy_version`). La preuve de licence conserve son texte ou une copie
immuable, son empreinte et la révision concernée.
Il voit les artefacts qu'il a importés et le **catalogue plateforme**, publié
par un admin plateforme (par exemple Chronos, MiniLM, les rerankers).

Le partage des octets ne donne jamais l'accès. Pour un dépôt privé ou gated,
chaque workspace prouve son accès avec son propre jeton avant de recevoir
l'autorisation. Si la sélection exacte existe déjà, les contrôles d'accès,
de licence et de quota du workspace sont refaits, pas le téléchargement.
Une nouvelle sélection réutilise les fichiers déjà vérifiés et ne télécharge
que les fichiers manquants. L'acceptation de licence se fait par workspace.

**Usage.** Le lien entre un artefact autorisé et ce qui l'exécute : une route
LLM, une collection RAG, une famille ML. Un usage ne voit qu'un `artifact_id`,
jamais un chemin, une clé d'objet ni un jeton.

## 4. Parcours

### 4.1 Parcourir

Depuis Ressources → Connecteurs → Hugging Face, l'utilisateur recherche un
modèle ou un dataset. Agentium interroge l'API du Hub côté serveur et affiche,
pour chaque dépôt : tâche (`pipeline_tag`), bibliothèque, licence et sa classe
(§8), statut gated, taille par format et statut de sécurité du Hub. Il voit
aussi les usages candidats : « utilisable comme LLM », « comme embedding »,
« comme reranker », « dans la famille Chronos ».

La compatibilité préliminaire est calculée à partir des métadonnées et de la
liste des fichiers, avant tout téléchargement. La mise en service d'un usage
exige ensuite la validation de son adaptateur : architecture, fichiers requis,
version du runtime et essai minimal de chargement/inférence (§5).

### 4.2 Importer

L'utilisateur choisit une révision (une branche ou un tag, résolu
immédiatement en sha) et un format quand le dépôt en propose plusieurs, par
exemple une quantification GGUF précise. L'import devient un job :

1. **Résolution.** `ref → sha`. La liste des fichiers, leurs tailles et leurs
   empreintes source viennent de l'API du Hub, à ce sha. L'algorithme est
   conservé avec l'empreinte : `git-blob-sha1` pour un fichier Git ordinaire,
   `sha256` pour un objet LFS. Une empreinte manquante ou non prise en charge
   bloque l'import ; un ETag n'est pas supposé être un SHA-256.
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
   Les quotas et la place temporaire sont réservés atomiquement avant le
   téléchargement. La taille réellement transférée reste contrôlée.
5. **Téléchargement.** Dans Agentium, seul `hub-fetch` télécharge les fichiers
   du Hub (§6). Il les transfère vers une zone temporaire MinIO en multipart.
   Pour chaque fichier, il vérifie l'empreinte source : SHA-256 des octets pour
   LFS, ou SHA-1 du blob Git, avec son en-tête `blob <taille>\0`, pour Git.
   Il calcule aussi le SHA-256 de tous les fichiers, indépendamment du mode
   de stockage amont ; c'est cette empreinte que les runtimes vérifieront.
6. **Publication.** Les fichiers vérifiés sont publiés sans écrasement dans
   le magasin partagé, puis le manifeste propre à l'artefact est écrit en
   dernier. Pour un dataset, seuls le résultat tabulaire et son manifeste
   sont publiés durablement (§5.4) ; ses sources restent temporaires et ne
   rejoignent pas `hub/blobs`. Le registre passe à `ready` après cette
   publication et les contrôles d'autorisation. Un lecteur exige le statut `ready` et
   un manifeste complet. Une interruption entre MinIO et la base est reprise
   par réconciliation, sans rendre visible un import incomplet.

Le manifeste v2 décrit un artefact et les empreintes SHA-256 de sa sélection,
avec les champs de provenance du §3. Il ne se réduit pas à l'ajout de champs
au manifeste global v1 du lot 6a ; leur coexistence est décrite au §5.3.

Un import est un job idempotent. Une contrainte d'unicité sur l'identité de
sélection évite deux publications concurrentes ; chaque demande conserve son
contrôle de droits. Une reprise retrouve la même sélection et les fichiers
déjà vérifiés. Échec, annulation et expiration d'un job abandonné libèrent ses
réservations et nettoient ses multipart/fichiers temporaires, sans supprimer
les fichiers publiés qu'un autre artefact référence.

Chaque import, refus, acceptation de licence et révocation est un événement
d'audit.

### 4.3 Utiliser

L'artefact `ready` et autorisé apparaît dans les sélecteurs des usages
candidats, avec l'état de validation de l'adaptateur (§5). Une demande
d'activation locale déclenche la matérialisation dans le cache (§6), puis la
validation ; l'usage devient disponible seulement après réussite.

Deux opérations distinctes s'appliquent dès HF-2 :

- **Retrait d'autorisation** (`revoke_grant`). L'admin du workspace retire
  uniquement l'accès de son workspace. Ses usages deviennent indisponibles ;
  ceux des autres workspaces restent actifs et le statut global de l'artefact
  ne change pas.
- **Révocation globale** (`revoke_artifact`). Seul l'admin plateforme peut
  passer l'artefact à `revoked`, avec une raison. Tous ses usages deviennent
  indisponibles, y compris ceux du catalogue plateforme.

Les droits et le statut sont revérifiés avant une exécution, un déploiement ou
l'émission d'une URL présignée, pas seulement à l'import. Une révocation
bloque les nouvelles exécutions concernées ; les exécutions déjà engagées sont
annulées lorsque le runtime le permet, sinon drainées avec un état visible.
Une URL déjà émise reste utilisable jusqu'à son expiration : sa durée maximale
fait partie du contrat des nœuds (§5.1).

La purge physique respecte les références au niveau des fichiers partagés,
du catalogue et des datasets dérivés, ainsi que les baux des runtimes qui les
utilisent encore. Elle n'efface jamais un fichier nécessaire à un autre
artefact. Un retrait de grant ne déclenche aucune suppression tant qu'une
autre autorisation ou un usage autorisé le retient. Le nettoyage des imports
incomplets est livré en HF-2 ; la purge complète et les preuves de suppression
sont livrées en HF-5.

### 4.4 Sans accès Internet

Pour un client isolé, le même artefact s'importe en déposant un bundle
(fichiers et manifeste) produit sur une machine connectée. Les vérifications
de contenu, de compatibilité et de licence restent identiques.

Pour les dépôts privés ou gated, le contrôle Hub du §3 est fait lors de
l'export avec le jeton du workspace cible. Le bundle porte une attestation
signée par un exportateur de confiance, liée à ce workspace, à l'artefact, à
la preuve de licence et à une échéance. L'installation isolée vérifie cette
signature avec une clé de confiance préconfigurée, la portée et la validité
avant de créer le grant ; une preuve absente ou expirée bloque l'import.
L'acceptation de licence du workspace cible reste requise. Cette délégation
atteste le contrôle à l'export, pas l'état courant du Hub inaccessible.

## 5. Adaptateurs d'usage

### 5.1 LLM open weights

Le portail LLM sait déjà déclarer un nœud de service compatible OpenAI. Il
gagne une action : **déployer un artefact sur un nœud**.

- L'agent de préparation du nœud reçoit la référence `artifact_id` et le
  manifeste. Il vérifie le SHA-256 de chaque fichier contre ce manifeste,
  quelle que soit la source, avant de monter les poids en lecture seule dans
  le runtime. Le processus d'inférence ne télécharge rien.
- **Source des poids.** Pour un dépôt public, cet agent tire directement du
  Hub, au sha et avec la sélection exacte du manifeste. Il passe par MinIO,
  avec des URL présignées et temporaires, dans trois cas :
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

**Contrat des nœuds.** `model_plane/serving_nodes.py` est un client du service
externe `omnirag-llm-portal`. HF-4 nécessite donc une version de ce service qui
annonce la prise en charge des artefacts, les formats/architectures et les
capacités matérielles. Avant implémentation du lot, l'API et sa version minimale
sont fixées des deux côtés : requête idempotente par déploiement, états
préparation/vérification/démarrage/prêt/échec, remontée des erreurs et reprise,
arrêt ou drainage, et durée maximale/renouvellement des URL présignées après
revalidation des droits. Un nœud incompatible refuse le déploiement avant
transfert. La synchronisation des routes et la provenance conservent
`artifact_id`, commit, variante et version du runtime. La recette inclut un
nœud réel ; la VM sans GPU ne suffit pas à valider un déploiement vLLM.

**Fournisseur HF Inference.** Indépendamment de l'import, la connexion permet
d'ajouter `huggingface` aux fournisseurs du portail, via son routeur compatible
OpenAI. Le modèle est appelé à distance avec le jeton de la connexion, sans
téléchargement. Il obéit aux mêmes règles de routage, de coût et de
`allowed_models` que les autres fournisseurs cloud, et à la politique de
licences du §8.

La classification, le refus et l'acceptation tracée des licences sont livrés
dès HF-1, sans attendre le registre d'artefacts. Le fournisseur enregistre le
modèle demandé et le modèle/fournisseur effectivement servi lorsque l'API le
retourne ; il ne promet pas une révision de poids figée pour cette inférence
distante.

### 5.2 RAG

- **Embeddings.** Un artefact compatible sentence-transformers devient
  sélectionnable comme modèle d'embedding d'une collection. Changer le modèle
  d'une collection existante impose une réindexation, annoncée avec son coût ;
  les vecteurs d'un modèle ne sont jamais mélangés à ceux d'un autre.
  Chaque génération d'index enregistre `artifact_id`, dimension et paramètres
  d'embedding. La reconstruction écrit une nouvelle génération et la bascule
  est atomique après validation ; un échec conserve l'ancienne génération si
  son artefact est encore autorisé. Une même dimension ne rend pas deux
  modèles interchangeables.
- **Rerankers.** Un artefact cross-encoder en ONNX est chargé par le chemin ONNX
  actuel. En safetensors, il passe par le chemin torch, sur un worker qui
  l'a installé.
- **Compatibilité.** Les adaptateurs valident les versions de bibliothèque,
  les fichiers requis et le contrat d'inférence. Le chemin ONNX actuel attend
  notamment `onnx/model.onnx`, `tokenizer.json` et une sortie `logits` scalaire
  passée par une sigmoid ; le seul tag cross-encoder ne suffit pas. Un essai
  de chargement et de score précède l'activation.
- Les modèles cuits dans l'image restent les défauts. Le repli vers un autre
  reranker est explicite et tracé. Aucun repli silencieux d'embedding n'est
  autorisé pour un index existant : si son modèle est absent ou révoqué, la
  recherche vectorielle concernée devient indisponible jusqu'à restauration
  ou reconstruction.

### 5.3 ML

`MODEL_SPECS` cesse d'être une liste fermée d'identifiants. Il devient une règle
par type d'usage :

- `forecasting` : architecture Chronos reconnue, safetensors ;
- `embedding` : sentence-transformers, safetensors.

Le manifeste version 2 remplace le provisionnement manuel du lot 6a. Les
workers `ml_deep` lisent le cache local en lecture seule, comme ils lisent
aujourd'hui `/data/models`.

Cette ouverture concerne aussi la résolution, les descriptors, les heartbeats
et les jobs, qui doivent transporter `artifact_id` et la provenance du runtime.
La matrice de compatibilité énumère les architectures et versions de
bibliothèque supportées, les fichiers requis et les poids shardés acceptés.
Le harness actuel ne copie que `config.json` et `model.safetensors` : une
architecture reconnue ne suffit pas à déclarer toutes ses variantes compatibles.

**Migration.** Le lecteur v1 et les modèles provisionnés restent disponibles
pendant HF-3a. Le lecteur v2 par artefact est ajouté explicitement ; les deux
schémas ne sont pas confondus. Les modèles historiques sont importés et
vérifiés, puis chaque usage migre vers son `artifact_id`. Le provisionnement
manuel n'est retiré qu'après migration des références et recette des jobs ;
le retour au lecteur v1 reste possible pour les usages non migrés.

### 5.4 Datasets

Un artefact dataset s'importe comme dataset tabulaire par `register_frame`,
avec `source="huggingface"` et la provenance `hf://repo@sha/config/split` :

- l'utilisateur choisit la config, le split et, si besoin, les colonnes et un
  plafond de lignes ;
- la lecture passe par les fichiers Parquet du dépôt, ou par la conversion
  Parquet que le Hub publie (`refs/convert/parquet`), jamais par un script de
  chargement ;
- les fichiers bruts sont temporaires : le résultat est le Parquet du dataset
  tabulaire, déjà stocké dans MinIO. Sa référence interne et son SHA-256 sont
  conservés dans `dataset_result` du manifeste ; les fichiers source et leurs
  empreintes restent décrits séparément. L'artefact n'est `ready` qu'après
  persistance de ce résultat et de son manifeste.

**Révisions.** `source_revision` désigne le commit du dépôt demandé. Pour des
Parquet natifs, c'est aussi la `revision` des fichiers lus. Pour une conversion,
`parquet_revision` est le commit résolu de `refs/convert/parquet`, utilisé
comme `revision` des fichiers ; sa correspondance avec `source_revision` doit
être vérifiée et conservée. Une URL de branche mobile n'est jamais enregistrée
comme référence de téléchargement figée. Si le Hub ne permet pas d'établir la
correspondance pour le commit demandé, l'import échoue avec
`HF_DATASET_REVISION_UNVERIFIED` ; il ne prend pas silencieusement la dernière
conversion. Le détail de ce fonctionnement est décrit dans la
[documentation Parquet du Hub](https://huggingface.co/docs/dataset-viewer/en/parquet).

**Sélection et rejeu.** Le manifeste et `selection_digest` incluent les
révisions source/conversion, la config, le split, la liste ordonnée des shards,
les colonnes dans leur ordre, la limite de lignes et la version de la
transformation. « N premières lignes » suit cet ordre de shards puis leur
ordre physique, sans échantillonnage implicite. La lecture applique les bornes
avant matérialisation complète : projection, plafond de lignes et de colonnes,
limites de téléchargement et de mémoire. `register_frame`, qui reçoit une
frame en mémoire, ne constitue pas à lui seul ce contrôle.

Le bloc de Flow `hf_dataset_import_v1` fige cet ensemble et référence le
résultat conservé. Son rejeu, sous autorisation valide, réutilise ce résultat
immuable vérifié ; il ne dépend pas d'un nouveau téléchargement ou d'une
nouvelle conversion du Hub. Les sorties par workspace gardent les ACL du
stockage tabulaire. Le résultat retenu par l'artefact ne peut pas être purgé
par la seule suppression d'une de ces sorties. Si ce résultat manque ou a été
révoqué, le rejeu échoue explicitement. Un changement de sélection ou de
transformation crée un nouvel artefact.

## 6. Stockage et runtime

**Magasin : MinIO.** Les fichiers des modèles sont stockés sous
`hub/blobs/{endpoint_id}/{kind}/{owner}/{repo}/{sha}/{chemin}`. `endpoint_id`
identifie l'endpoint normalisé ; `kind` évite de confondre un modèle et un
dataset de même nom. Les manifestes sont stockés séparément sous
`hub/artifacts/{artifact_id}/manifest.json` et référencent les seuls fichiers
de leur sélection. Une clé publiée n'est jamais écrasée. MinIO
sert aussi les URL présignées des nœuds LLM (§5.1) et prépare Agentium à
tourner sur plusieurs machines.

**Cache local.** Les runtimes lisent des fichiers locaux, souvent en mmap
(safetensors, GGUF). Chaque artefact utilisé localement est donc matérialisé
dans `/srv/agentium-data/hub-cache/{artifact_id}/` :

- `hub-fetch` copie depuis MinIO, revérifie chaque SHA-256 contre le manifeste
  et publie atomiquement ;
- les runtimes (`ml_deep`, workers RAG) montent ce cache **en lecture seule**
  et ne parlent jamais au Hub ; ils gardent `HF_HUB_OFFLINE=1` ;
- le cache est borné (§7) et évincé du moins récemment utilisé, sauf les
  artefacts qu'un usage actif référence ou qu'un runtime utilise sous bail ;
  l'admission réserve la place de la copie temporaire et de la publication.
  Si toutes les entrées sont retenues, le nouvel usage reste indisponible avec
  `HF_CACHE_FULL`, sans dépasser la borne ni évincer un modèle en cours ;
- une copie absente du cache est rematérialisée depuis MinIO, jamais depuis le
  Hub.

**Worker `hub-fetch`.** Image légère (`huggingface_hub` et client S3, sans
torch), queue `hub_fetch`. C'est le seul composant Agentium qui télécharge les
fichiers des dépôts du Hub. Il a une identité MinIO dédiée, limitée en écriture
au préfixe `hub/`, et il est le seul à écrire dans le cache. Les runtimes lisent
`hub/` avec une identité en lecture seule quand ils en ont besoin.

La conversion tabulaire s'exécute sur le worker dataset, à partir des fichiers
déjà acquis ; elle utilise l'identité de stockage tabulaire existante pour
`register_frame`. Elle ne nécessite ni torch dans `hub-fetch`, ni jeton Hub
dans le worker dataset. Les fichiers temporaires restent disponibles jusqu'à
publication du résultat, puis sont nettoyés par leur propriétaire.

**Réseau.** Les appels serveur de recherche, métadonnées et contrôle d'accès
sont autorisés vers l'API du Hub ; HF Inference utilise son routeur distant.
Les transferts de poids dans Agentium passent par `hub-fetch`, ceux d'un nœud
LLM public par son agent de préparation (§5.1). Les processus d'inférence et
les workers ML/RAG restent sans accès au Hub. Les endpoints autorisés et leurs
redirections de téléchargement sont validés ; aucun jeton n'est transmis à
un hôte non autorisé.

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

Le quota de modèles d'un workspace compte l'union des fichiers de ses
artefacts autorisés, même si leurs octets sont partagés avec un autre
workspace ; le quota plateforme les compte une seule fois. Les réservations
des imports en cours participent à ces calculs et sont prises dans la même
transaction que l'admission du job. Une réutilisation ne réserve que les
octets nouveaux à chaque niveau. Les résultats tabulaires conservent leur
comptabilité existante ; leurs sources temporaires participent à la
réservation d'espace disque et à la limite de téléchargement de 256 Mo.

Les octets téléchargés, les multipart en cours, les sorties dataset et les
copies de cache temporaires sont inclus dans le contrôle d'espace libre du
disque commun. Une marge de fonctionnement configurée est réservée aux autres
services. L'alerte d'occupation ne remplace pas le refus d'admission lorsque
cette marge ou un quota serait dépassé. Les limites sont aussi contrôlées
pendant le transfert et la lecture Parquet, pas seulement sur les métadonnées.

**Capacité de la VM de démo.** MinIO et le cache sont sur le même disque de
données : 492 Go, dont 242 Go libres le 9 octobre 2026, avec 152 Go déjà
occupés par MinIO. Le quota plateforme et le cache pleins consomment 190 Go et
laissent environ 50 Go, avant les réservations temporaires. Une alerte à 80 %
d'occupation et le contrôle d'admission sont nécessaires dès HF-2 ; la marge
est revalidée avant HF-3a. L'extension du disque est à prévoir avant que les
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
  Dès HF-1, une preuve d'acceptation indépendante des artefacts peut être
  liée au workspace, au modèle, à la révision/empreinte du texte de licence
  et à la version de politique. L'absence de cette preuve bloque un appel
  soumis à acceptation.
- **Application.** La classe enregistrée à l'import est une trace de la
  décision initiale. La politique effective plateforme/workspace est
  réévaluée à l'octroi d'accès et avant un nouvel usage, y compris via le
  catalogue. Un durcissement ne laisse pas un ancien grant contourner la
  règle ; le contenu immuable de l'artefact n'est pas modifié.
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
| Importer un modèle, accepter une licence, déployer un LLM, retirer un grant du workspace | Admin du workspace |
| Révoquer globalement un artefact, y compris hors catalogue | Admin plateforme |

Un dépôt gated n'est importable que si le jeton a déjà reçu l'accès sur le Hub.

## 10. Erreurs nommées

`HF_UNCONFIGURED`, `HF_AUTH_REQUIRED`, `HF_GATED`, `HF_NOT_FOUND`,
`HF_REVISION_UNRESOLVED`, `HF_UNSAFE_FORMAT`, `HF_REMOTE_CODE_REQUIRED`,
`HF_LICENSE_BLOCKED`, `HF_LICENSE_ACCEPTANCE_REQUIRED`, `HF_TOO_LARGE`,
`HF_QUOTA_EXCEEDED`, `HF_CHECKSUM_MISMATCH`, `HF_INCOMPATIBLE_USAGE`,
`HF_ARTIFACT_REVOKED`, `HF_ACCESS_REVOKED`, `HF_CHECKSUM_UNAVAILABLE`,
`HF_DATASET_REVISION_UNVERIFIED`, `HF_DATASET_RESULT_MISSING`, `HF_CACHE_FULL`,
`HF_NODE_INCOMPATIBLE`.

## 11. Arbitrages validés

1. **Partage.** Octets stockés une fois par `repo@sha` dans le périmètre d'un
   endpoint et d'un type de dépôt, avec des manifestes distincts par sélection.
   Visibilité par workspace par autorisation, plus un catalogue plateforme.
   L'accès aux dépôts privés et gated est prouvé par workspace (§3).
2. **Magasin.** MinIO, avec un cache local en lecture seule pour les runtimes,
   alimenté par `hub-fetch` (§6).
3. **Bornes.** 20 Go par modèle, 50 Go par workspace, 150 Go pour la
   plateforme, 40 Go de cache, datasets alignés sur l'upload (§7).
4. **Nœuds LLM.** Le Hub par défaut via l'agent de préparation, avec
   vérification du manifeste ; MinIO pour les dépôts privés ou gated, les
   nœuds isolés et les révisions disparues (§5.1). L'inférence reste hors ligne.
5. **Licences.** Trois classes au niveau plateforme, que chaque workspace peut
   seulement resserrer (§8).

## 12. Découpage et recette

| Lot | Contenu | Valeur |
|---|---|---|
| HF-1 | Connexion, test, recherche, fournisseur HF Inference ; politique de licences effective par workspace, acceptations et exceptions tracées, contrôle avant appel | Modèles HF utilisables à distance dans le portail |
| HF-2 | Registre, sélections immuables et manifeste v2, autorisations, révocation logique, worker `hub-fetch`, MinIO, fichiers et empreintes, réservations de quotas, reprise et nettoyage des imports échoués ; datasets et bloc de Flow | Imports vérifiés, partage isolé par workspace et datasets rejouables |
| HF-3a | Cache local commun, adaptateur ML, règles de compatibilité par famille ; migration des manifestes et des références du lot 6a | Modèles ML importés sans provisionnement manuel, avec continuité des usages existants |
| HF-3b | Adaptateurs RAG, générations d'index liées à l'artefact d'embedding, réindexation et bascule atomique ; rerankers ONNX et torch | Choix des modèles RAG sans mélange de vecteurs |
| HF-4 | API des nœuds pour déployer, suivre et arrêter un artefact ; contrôle des capacités, vérification du manifeste, sources Hub et MinIO, URL présignées | LLM importés servis sur les nœuds du portail |
| HF-5 | Import par bundle hors ligne, purge complète des objets et copies locales ou distantes après libération par les runtimes | Clients isolés et fin du cycle de vie physique |

HF-2 livre le manifeste v2 nécessaire à tout import. HF-3a livre le cache
commun à ML et RAG ; HF-3b ajoute la gestion des index. La révocation logique
et le refus des nouveaux usages sont disponibles dès HF-2 ; HF-5 complète la
purge physique des artefacts déjà utilisés.

Chaque lot se recette sur la VM de démo avec des dépôts publics, gated et
refusés par la politique, selon les parcours qu'il livre. Les cas suivants
conditionnent leur validation :

- **HF-1 :** un appel distant est refusé pour une licence bloquée ou une
  acceptation manquante. Le même modèle peut être autorisé dans un workspace
  et refusé dans un autre dont la politique est plus stricte ; le contrôle
  s'applique aussi à un appel direct de l'API du portail.
- **HF-2 :** importer Q4 puis Q8 au même commit produit deux sélections
  immuables prêtes avec des manifestes distincts, sans dupliquer leurs fichiers
  communs. Révoquer
  l'autorisation de A laisse celle de B utilisable. Un modèle contenant des
  fichiers non-LFS passe les contrôles ; une empreinte incorrecte interdit
  `ready`. Deux imports concurrents respectent les quotas réservés ; un arrêt
  avant publication du manifeste ne rend aucun artefact partiel accessible,
  et la reprise ou le nettoyage libère les réservations et objets temporaires.
  Un dataset à une révision historique utilise la conversion correspondante
  figée, ou échoue explicitement : il ne lit jamais silencieusement la
  conversion courante. Son rejeu retrouve le résultat conservé et vérifie son
  empreinte, même si la conversion amont change ; projection et limite de
  lignes restent figées.
- **HF-3a :** un modèle du lot 6a reste chargeable pendant la migration ; ses
  usages existants retrouvent le même modèle après migration. Un artefact
  autorisé se charge hors ligne depuis le cache vérifié ; une famille ou une
  architecture incompatible est refusée avant exécution.
- **HF-3b :** pendant une réindexation, les requêtes utilisent le modèle et la
  génération d'index encore actifs. Une interruption conserve cette paire tant
  que l'artefact reste autorisé ; une réussite bascule ensemble modèle et index.
  L'indisponibilité du modèle
  d'embedding ne provoque aucun repli silencieux vers un autre espace
  vectoriel.
- **HF-4 :** un déploiement public passe par le Hub, un déploiement gated ou
  isolé par MinIO sans transmettre le jeton HF au nœud. Une empreinte erronée
  ou une capacité insuffisante bloque le démarrage. Une relance de la même
  demande ne crée pas de déploiement concurrent ; l'état et l'arrêt sont
  observables, notamment lors d'une révocation.
- **HF-5 :** un bundle valide s'importe sans accès au Hub ; une modification
  de fichier est détectée. Un bundle gated exige l'attestation valide pour le
  workspace cible ; une preuve expirée ou destinée à un autre workspace est
  refusée. La purge attend la libération des fichiers ouverts
  et préserve les objets encore référencés par un autre artefact autorisé.

Dès HF-2, l'alerte disque et le contrôle d'admission du §7 doivent être actifs ;
leur marge est revalidée avant HF-3a. Avant HF-4, fixer le contrat d'API des
nœuds, son authentification et l'accès à MinIO par réseau
privé ou proxy dédié ; les URL présignées doivent être joignables depuis les
nœuds concernés.
