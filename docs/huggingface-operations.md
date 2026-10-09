# Exploitation du connecteur Hugging Face

Cette livraison implémente le connecteur dans Agentium. La recette sur la VM,
avec ses identités MinIO et ses nœuds GPU, reste une étape de déploiement.
Le service externe `omnirag-llm-portal` doit implémenter le
[protocole d'artefacts v1](huggingface-node-protocol.md) pour servir les LLM
importés. Agentium refuse les nœuds incompatibles avant tout transfert.

## Périmètre livré

| Lot | Parcours dans ce dépôt | Vérification externe restante |
| --- | --- | --- |
| HF-1 | Connexion chiffrée, recherche, licences, fournisseur HF Inference, contrôle par workspace à chaque appel | Jeton gated autorisé et appel facturé HF Inference |
| HF-2 | Registre et manifestes v2, import asynchrone, empreintes, quotas réservés, reprise, révocation, dataset et Flow | IAM MinIO et transferts sur la VM |
| HF-3a | Cache vérifié, activation avec chargement et inférence réels, adaptateurs ML, maintien des manifestes v1 | Image `ml-deep` qualifiée et modèle Chronos sur la VM |
| HF-3b | Embeddings par collection, réindexation et bascule atomique, rerankers ONNX/torch | Réindexation Qdrant sur les collections de démo |
| HF-4 | Déploiement idempotent, capacités, provenance, renouvellement des URL, état et arrêt | Implémentation du protocole et recette vLLM/llama.cpp dans le service externe |
| HF-5 | Bundles signés, import sans Hub, consentement hors ligne, purge après libération | Clés Ed25519, suppression des versions MinIO, libération des copies sur les nœuds |

Les datasets doivent fournir des fichiers Parquet dans le commit demandé.
Une conversion `refs/convert/parquet` sans preuve de correspondance au commit
source est refusée avec `HF_DATASET_REVISION_UNVERIFIED`. Le résultat projeté
est conservé et vérifié lors du rejeu, indépendamment de l'output dataset initial.

Les adaptateurs locaux prennent en charge Chronos2 pour le forecasting,
Sentence Transformers pour les architectures standard Bert, Roberta,
XLMRoberta et DistilBert, et les rerankers à un seul logit en ONNX ou torch.
L'activation exécute un véritable test d'inférence dans le runtime sélectionné.
Les scripts distants et `trust_remote_code` sont interdits. Les autres
architectures restent importables pour les usages compatibles, sans être
annoncées comme exécutables par un adaptateur local.

## Déploiement

L'overlay explicite `docker/compose.agentium.huggingface.yml` ajoute le worker
`agentium-hub-fetch`, la queue `hub_fetch`, le cache et le spool de bundles.
Il active `INSTALL_HF_RAG=1` dans les images API et CPU. Les workers ML gardent
le profil `ml-deep` existant. L'image de téléchargement ne contient ni torch,
ni moteur d'inférence, ni moteur tabulaire.

Créer sur le disque de données, avec l'UID/GID configuré pour Agentium :

```text
/srv/agentium-data/hub-cache
/srv/agentium-data/hub-bundles
/srv/agentium-data/hf-bundle-keys
```

Les binds refusent de créer automatiquement ces répertoires. Le cache est
accessible en écriture uniquement à `hub-fetch`, et en lecture seule à l'API,
au worker CPU et aux deux workers `ml-deep`. Le spool est partagé en écriture
par l'API, le worker CPU et `hub-fetch`. Il contient des bundles privés :
réserver ses permissions au compte de service et le placer sur le disque
de données. Les leases empêchent l'éviction ou la purge de fichiers ouverts.

Définir dans l'environnement Compose privé :

```text
AGENTIUM_HUGGINGFACE=1
AGENTIUM_HUB_ENV_FILE=/chemin/prive/huggingface-worker.env
AGENTIUM_HUB_CACHE_PATH=/srv/agentium-data/hub-cache
AGENTIUM_HUB_BUNDLES_PATH=/srv/agentium-data/hub-bundles
AGENTIUM_HF_BUNDLE_KEYS_PATH=/srv/agentium-data/hf-bundle-keys
```

Partir de `docker/env/huggingface-worker.env.example` pour le fichier du
worker ; le conserver hors Git avec des permissions `0600`. Fournir la base,
le broker, l'endpoint/bucket MinIO, la clé Fernet identique à celle de l'API
et une identité S3 dédiée. `AGENTIUM_ENV_FILE` reste l'environnement applicatif
habituel ; il ne doit jamais contenir les secrets du writer Hub.

Le lanceur VM ajoute l'overlay lorsque `AGENTIUM_HUGGINGFACE=1`. Pour un
environnement de développement, ajouter explicitement l'overlay et
`--profile huggingface` aux commandes Compose existantes. Conserver les
overlays de stockage et la séquence de migration du déploiement existant.
La migration Alembic `123_huggingface_connector` ajoute le registre et les
références des collections, sans réécrire les modèles du lot 6a.

La migration d'un modèle entraîné du lot 6a est explicite : importer et activer
l'artefact identique, puis appeler
`POST /huggingface/artifacts/{id}/migrate-legacy` avec `{"model_id":"..."}`.
Le worker ML compare la provenance enregistrée à l'entraînement, le modèle
v1 provisionné et l'inventaire SHA-256 complet de l'artefact. Il refuse toute
différence de dépôt, commit ou fichiers. Le mapping vérifié soumet ensuite
les prédictions aux droits de l'artefact, sans réécrire le modèle entraîné
ni sa provenance originale. Les modèles non migrés conservent leur parcours v1.
Pour les entraînements suivants, sélectionner explicitement `spec.artifact_id`
dans la configuration ; les anciens programmes de réentraînement ne sont pas
réécrits automatiquement.

Un seul Beat doit être actif. Il envoie toutes les minutes la récupération
des imports, activations et opérations de bundles. Ne pas lancer un second
Beat dans `hub-fetch`. Les erreurs d'envoi au broker laissent une intention
durable, visible dans les jobs, que cette récupération peut relancer.

## Identités et stockage

Les objets persistants suivent ces préfixes :

```text
hub/blobs/{endpoint_hash}/{kind}/{repo}/{commit}/{path}
hub/artifacts/{artifact_id}/manifest.json
hub/tmp/{job_id}/...
workspaces/{workspace_id}/tabular/hub-artifacts/{artifact_id}/result.parquet
```

| Processus | Identité et droits nécessaires |
| --- | --- |
| API | Identité `HF_S3_*` de lecture pour signer les téléchargements ; aucune écriture dans `hub/blobs/` |
| `hub-fetch` | Identité `HF_S3_*` dédiée : lecture, publication conditionnelle et multipart dans `hub/`, nettoyage des temporaires, suppression physique autorisée par le registre |
| Worker CPU | Identité tabulaire existante pour les résultats et leur rejeu ; lecture des sources `hub/tmp/`, publication des manifestes sous `hub/artifacts/` |
| Purge des résultats retenus | Identité optionnelle `HF_TABULAR_DELETE_ACCESS_KEY` / `HF_TABULAR_DELETE_SECRET_KEY`, limitée aux clés `workspaces/*/tabular/hub-artifacts/*` |

Sur un bucket versionné, supprimer un objet requiert aussi la suppression de
ses versions et delete markers : prévoir `ListBucketVersions` et
`DeleteObjectVersion` dans le périmètre de purge. Une identité applicative
append-only ne suffit pas. Ne pas lui accorder des droits administrateur pour
contourner un refus. Les modèles partagés et les usages actifs empêchent la
purge ; un nœud injoignable n'est jamais considéré comme libéré.

Le script `scripts/agentium_hf_storage_policies.py --bucket NOM --role ROLE`
génère les politiques `hub-fetch`, `hub-read`, `application` et `tabular-purge`
sans modifier MinIO. Remplacer la politique applicative historique trop large :
ajouter seulement une politique restrictive ne retire pas ses anciens droits.

Prévoir la sauvegarde du préfixe `hub/`, des résultats retenus et de la base.
Le script historique `agentium-data-plane-dump.sh` ne sauvegarde pas encore
les nouveaux objets `hub/`. Le cache est reconstructible à partir des objets
vérifiés ; il ne remplace pas cette sauvegarde.

Les URL présignées expirent en cinq minutes au maximum. L'endpoint S3 utilisé
pour leur signature doit être joignable depuis les nœuds via réseau privé ou
proxy dédié, avec le même hôte que dans la signature. Les secrets HF restent
dans Agentium. Les dépôts privés et gated nécessitent un jeton propre au
workspace : le jeton plateforme ne sert pas de preuve d'accès pour eux.

L'endpoint Hub officiel est autorisé par défaut. Ajouter les éventuels Hubs
d'entreprise à `HF_ALLOWED_ENDPOINTS` dans l'API et les workers concernés.
Seuls des endpoints HTTPS explicitement autorisés peuvent recevoir un jeton.
Les runtimes utilisent les fichiers locaux avec `HF_HUB_OFFLINE=1` et
`TRANSFORMERS_OFFLINE=1`. Les clients de métadonnées explicites de l'API et le
worker d'acquisition ont toujours besoin de leur accès réseau au Hub.

## Bundles hors ligne

Tous les bundles sont signés avec Ed25519, y compris les dépôts publics.
La signature couvre le manifeste, la licence, le workspace cible et une
expiration. Cette signature empêche de transformer un dépôt gated en dépôt
public en modifiant ses métadonnées.

Configurer `HF_BUNDLE_SIGNING_KEY_PATH` sous `/run/hf-bundle-keys/` et
`HF_BUNDLE_SIGNING_KEY_ID` sur les workers exportateurs. La clé privée montée
en lecture seule n'entre ni en base ni dans l'image. Configurer
`HF_BUNDLE_TRUST_KEYS_JSON`, mapping identifiant vers clé publique PEM ou
base64, sur l'API et les workers importateurs. L'API ne nécessite pas la clé
privée.

L'export gated vérifie l'accès actuel du workspace cible avant de signer.
L'import vérifie la signature, la cible, l'expiration et chaque empreinte sans
accéder au Hub. Si la licence requiert un consentement, le job expose son
texte signé et attend l'acceptation de l'administrateur du workspace avant
de reprendre. L'upload utilise un corps `application/x-tar`, borné et streamé.

## Quotas et incidents

Les valeurs initiales sont 20 Gio par modèle, 50 Gio par workspace, 150 Gio
pour les modèles de la plateforme, 40 Gio de cache, et les limites tabulaires
de 256 Mio, cinq millions de lignes et 512 colonnes. Un admin plateforme
peut ajuster les limites via `/huggingface/platform/limits`. L'admission
réserve les téléchargements en cours et la place temporaire, sous verrou de
base ; elle conserve au moins 10 Gio de marge disque par défaut.

Un import échoué peut conserver des octets partagés déjà vérifiés. Sa place
reste comptée jusqu'à la purge. Ne pas supprimer manuellement les objets
`hub/blobs/` ou les dossiers du cache. Utiliser révocation puis purge et
consulter les usages bloquants. Une révocation de workspace laisse les
autres grants valides ; une révocation globale refuse tous les nouveaux usages.

Pour une réindexation RAG, les requêtes gardent la paire modèle/index active
jusqu'à la validation complète de la nouvelle génération. Un échec ou une
annulation libère la génération en préparation. Si le modèle actif est
révoqué ou indisponible, la requête échoue explicitement, sans fabriquer des
vecteurs avec un autre modèle.

## Validation

Les tests du connecteur résident sous `backend/app/tests/services/test_huggingface_*`,
`test_hf_embedding_generation.py` et les tests API correspondants. Ils
couvrent les refus d'accès, les licences, les checksums LFS et Git, les leases,
la reprise, le rejeu des datasets, les générations RAG, les signatures et la
purge. Les probes locaux emploient de petits modèles ONNX et Sentence
Transformers exécutés hors ligne. La migration et le rendu Compose ont des
tests dédiés sous `backend/app/tests/infra/`.

Ces tests ne valent pas recette GPU ou IAM sur la VM. Exécuter les scénarios
public/gated/refusés et les critères de la
[roadmap](agentium-huggingface-connector.md#12-découpage-et-recette) avant
d'annoncer chaque lot opérationnel dans cet environnement.

Le test `backend/app/tests/services/test_huggingface_minio_integration.py`
qualifie les écritures conditionnelles, l'abandon multipart, la suppression
de toutes les versions et les refus IAM sur un MinIO Docker éphémère avec
des identités synthétiques. Il est désactivé par défaut ; l'activer avec
`RUN_HF_MINIO_INTEGRATION=1` après avoir chargé les images MinIO et `mc`.
Les variables `HF_MINIO_TEST_IMAGE` et `HF_MINIO_TEST_MC_IMAGE` permettent
de sélectionner des miroirs qualifiés. Cette recette réelle n'a pas pu être
exécutée dans l'environnement de développement : les images n'y étaient
pas disponibles et les registres consultés en ont refusé le téléchargement.
Les tests unitaires de ces comportements passent ; le tag MinIO de
production reste inchangé.
