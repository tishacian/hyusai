# HF-4 — note de reprise pour un agent ayant accès aux nœuds LLM

État au 10 octobre 2026 : **protocole implémenté dans `omnirag-llm-portal` et
recette réelle passée sur aigrid-vm**, à l'exception de trois points listés
dans [Résultat de la reprise](#résultat-de-la-reprise-9-10-octobre-2026).
HF-4 n'est pas encore marqué terminé dans la roadmap.
Les sections suivantes décrivent la demande initiale, rédigée lorsque le dépôt
`omnirag-llm-portal` n'était pas accessible.

## Point de départ et blocage

Le commit `8ab77d7f25fe6afdc0825f15eaf983dbf4c837b0`, intégré sur
`demo/agentic`, fournit le client Agentium, les API, l'interface, les contrôles
de droits et les tests de contrat HF-4.
Il ne contient pas l'implémentation du service externe des nœuds.

Le dépôt `omnirag-llm-portal` n'était pas accessible lors de la rédaction de
cette note. Aucun code serveur HF-4 ni déploiement de nœud n'a été effectué
lors de cette reprise.

Reprendre sur la dernière version de `demo/agentic` en préservant les commits
ultérieurs ; l'intégration se fait directement sur cette branche, sans PR.
Lire les instructions et l'architecture du service externe avant de le
modifier, et confirmer sa branche cible.

## Sources à lire

| Source | Rôle |
| --- | --- |
| [Roadmap, §5.1 et §12](agentium-huggingface-connector.md) | Périmètre et critères de recette HF-4 |
| [Protocole des nœuds v1](huggingface-node-protocol.md) | Contrat HTTP, capacités, états, sources et purge |
| [Client des artefacts](../backend/app/services/huggingface/nodes.py) | Payloads exacts, empreinte, idempotence et validation des réponses |
| [API de cycle de vie](../backend/app/api/v1/endpoints/huggingface_lifecycle.py) | Autorisations, usages, suivi, arrêt et renouvellement des URL |
| [Client des nœuds](../backend/app/services/model_plane/serving_nodes.py) | Configuration, authentification du portail et inventaire |
| [Enregistrement des modèles](../backend/app/services/model_plane/registration.py) | Construction des routes d'inférence et provenance |
| [Inférence des artefacts](../backend/app/services/huggingface/inference.py) | Revérification des droits et de la route à chaque appel |
| [Projection des fournisseurs](../backend/app/services/model_plane/providers.py) | Visibilité des modèles par workspace |
| [Tests des nœuds](../backend/app/tests/services/test_huggingface_nodes.py) | Tests de contrat déjà disponibles côté Agentium |
| [Guide d'exploitation](huggingface-operations.md) | MinIO, identités, réseau, limites de validation |

## Implémentation attendue côté service externe

Réutiliser son authentification, son gestionnaire d'instances et ses mécanismes
de réservation existants. Le client envoie le jeton de contrôle du nœud via
`Authorization: Bearer` et `X-LLM-Portal-Token`. Aucun jeton Hugging Face ne doit
être transmis au nœud. Authentifier chaque endpoint ci-dessous.

| Méthode et chemin sous `/api/v1/artifacts` | Comportement attendu |
| --- | --- |
| `GET /capabilities` | Version 1 du protocole, manifeste v2, runtimes réellement disponibles, architectures, contexte et mémoire ; refus avant transfert si incompatibles |
| `PUT /deployments/{id}` | Réservation atomique, enregistrement durable et préparation asynchrone du déploiement idempotent |
| `GET /deployments/{id}` | État, progression et erreur typée ; identité du déploiement et de l'artefact toujours présentes |
| `POST /deployments/{id}/stop` | Corps `{"drain":true}` ; annulation de la préparation ou refus des nouvelles requêtes et attente des requêtes actives |
| `PUT /deployments/{id}/sources` | Renouvellement des sources autorisées sans changer l'identité ni le manifeste ; reprise après expiration ou source Hub indisponible |
| `DELETE /deployments/{id}` | Suppression des copies libérées ; reçu explicite `state: "stopped", copies_deleted: true` pour terminer la purge HF-5 |

États acceptés : `preparing`, `verifying`, `starting`, `ready`, `failed`,
`draining`, `stopped`. Une réponse doit renvoyer les bons `deployment_id` et
`artifact_id`. Un HTTP 404 ou un nœud injoignable n'est pas une preuve de purge.

Le payload exact est construit par `nodes.deploy_artifact`. Son empreinte lie
workspace, nœud, SHA-256 du manifeste, architecture, contexte, mémoire,
moteur et version du runtime. La sérialisation canonique utilise
`sort_keys=True`, `separators=(',', ':')`, `ensure_ascii=False`, puis UTF-8.
Traiter `deployment_id` comme un identifiant opaque : l'API Agentium peut
fournir un ID dont le calcul diffère de l'empreinte par défaut de `nodes.py`.
Le serveur compare les champs immuables, sans exiger que l'ID soit leur hash.
Les URL temporaires sont exclues de cette identité. Rejouer une même demande
retourne le même déploiement ; réutiliser son ID avec une identité différente
doit échouer en 409.

La préparation télécharge exclusivement la sélection exacte : Hub public au
commit figé, ou URL MinIO présignées pour les dépôts privés/gated, les nœuds
isolés et les révisions disparues. Respecter une expiration maximale de
300 secondes, borner les redirections et leur destination, vérifier taille
et SHA-256 de chaque fichier, puis publier le dossier de façon atomique.
Refuser chemins sortants, liens symboliques, fichiers manquants ou non prévus.
Ne pas journaliser les URL signées et ne pas charger de code distant.

Démarrer vLLM pour les safetensors ou llama.cpp pour le GGUF uniquement lorsque
le runtime annonce cette capacité. Les poids sont montés en lecture seule ;
l'inférence utilise `HF_HUB_OFFLINE=1` et `TRANSFORMERS_OFFLINE=1`, avec une
isolation réseau effective. Ces variables seules ne coupent pas le réseau.
Vérifier le modèle servi et sa santé avant `ready`.

Persister les transitions et réservations pour réconcilier processus et
déploiements après redémarrage. Ne libérer les ressources qu'après avoir
confirmé l'arrêt des lecteurs ; préserver les fichiers partagés encore utilisés.

## Deux points d'interopérabilité à traiter

**Transport d'inférence.** `registration._openai_base_url` construit actuellement
une URL `scheme://hôte-du-nœud:port/v1` et l'enregistrement utilise la clé
`local`. `ArtifactInferenceClient._authorization` reconstruit cette URL pour
la vérifier. Ce contrat ne prend pas encore en charge un proxy d'inférence
authentifié par déploiement. Si l'isolation du service impose un tel proxy,
adapter ces deux chemins ensemble, ses credentials et les tests. Ne pas
supposer que le schéma HTTPS du contrôle s'applique aussi au port du runtime,
ni accepter une URL arbitraire de l'inventaire sans contrôle de destination.
Conserver la vérification des droits à chaque appel, y compris en streaming.

**Inventaire.** Le service doit exposer `artifact_id`, `workspace_id`,
`deployment_id`, `repo_id`, `revision`, `variant` et `runtime_version` au premier
niveau des instances, en plus des champs usuels provider/modèle/état/port et
de `provenance`. `providers.scoped_serving_providers` ne récupère pas ces champs
depuis `provenance`, contrairement à une partie du registre.

## Recette avant de déclarer HF-4 terminé

1. Refuser tout appel non authentifié et toute capacité insuffisante avant
   téléchargement. Deux déploiements concurrents doivent respecter les
   réservations de mémoire et de disque.
2. Vérifier rejeu idempotent, conflit 409, reprise après crash et renouvellement
   d'URL expirée sans créer un deuxième déploiement.
3. Importer un dépôt public depuis son commit exact et un dépôt gated via
   MinIO ; vérifier l'absence de jeton HF sur le nœud et dans les traces.
4. Injecter corruption, taille incorrecte, fichier manquant, traversée de
   chemin et redirection interdite : aucun runtime ne doit démarrer.
5. Exécuter une inférence réelle après préparation, sans accès sortant au Hub,
   avec les poids en lecture seule et une provenance conforme dans Agentium.
6. Révoquer le grant : aucun nouvel appel ni renouvellement d'URL ; le suivi
   et l'arrêt restent possibles. Drainer un stream actif avant `stopped`.
7. Purger après libération, préserver les références partagées et vérifier le
   reçu de suppression, y compris lors d'un deuxième appel DELETE.
8. Tester le client Agentium contre le vrai serveur HTTP, puis effectuer la
   recette sur le nœud cible. Les doubles de runtime ne qualifient pas le GPU.

Les tests existants côté client sont un point de départ, pas une preuve que
le serveur existe. La livraison Agentium initiale avait 690 tests backend et
2 084 tests frontend réussis ; aucun déploiement GPU réel n'a été validé.
La qualification MinIO réelle reste aussi à faire : l'environnement précédent
ne pouvait pas télécharger ses images de test. Consigner séparément tests
locaux, tests d'interopérabilité et recette réelle, avec commits et versions
des deux services. Ne marquer HF-4 terminé dans la roadmap qu'après cette recette.

## Résultat de la reprise (9-10 octobre 2026)

### Versions

| Service | Branche | Commits |
| --- | --- | --- |
| `omnirag-llm-portal` | `initial_version` | `101132a` protocole v1 et runtimes isolés ; `7b49050` tunnel SSH sortant |
| Agentium | `demo/agentic` | `e20910d2` inférence par le relais authentifié du nœud ; `23f9d3b9`, `aefb83e0`, `75edb545`, `a3bbbf69`, `f5773fff` correctifs trouvés pendant la recette |

Runtimes du nœud : vLLM 0.12.0 (GPU) et llama.cpp `b10524` (CPU). Agentium
déployé sur la VM de démo en `f5773fff`, avec l'overlay Hugging Face.

### Points d'interopérabilité

- **Transport d'inférence.** Le nœud expose un relais authentifié par
  déploiement, `/api/v1/artifacts/deployments/{id}/v1`, protégé par son jeton
  de contrôle. Agentium construit et revérifie cette route
  (`registration.route_base_url`) ; les runtimes restent sur un réseau Docker
  interne sans port publié.
- **Inventaire.** Les instances d'artefact exposent `artifact_id`,
  `workspace_id`, `deployment_id`, `repo_id`, `revision`, `variant` et
  `runtime_version` au premier niveau, en plus de `provenance`.

### Tests locaux

- Portail : 20 tests du protocole (`tests/test_artifacts.py`).
- Agentium : tests des nœuds, du registre, du cycle de vie, des acquisitions et
  du plan de modèles, complétés par les régressions des correctifs ci-dessous.

### Interopérabilité : client Agentium contre le vrai serveur

Exécutée depuis un poste avec tunnel vers le nœud :

- llama.cpp CPU, 22/22 : refus non authentifiés et capacités insuffisantes,
  empreinte, taille, fichier manquant, traversée de chemin et redirection
  interdite sans démarrage, rejeu idempotent et 409, inférence réelle, poids
  en lecture seule, réseau interne seul, mode hors ligne, aucun jeton HF,
  aucune sortie réseau, drain, arrêt et reçu de purge rejouable ;
- vLLM GPU, 14/14 : même cycle ; la mémoire GPU revient à son niveau initial ;
- résilience, 7/7 : redémarrage du portail pendant la préparation, runtime prêt
  conservé après redémarrage, drain d'un stream actif avant `stopped`.

### Recette réelle de bout en bout

Exécutée dans le conteneur API d'Agentium sur la VM, à travers les routes
`/api/v1/huggingface` : base, MinIO, worker `hub-fetch` et nœud réels ; seule
l'identité Keycloak d'un administrateur est injectée. Le nœud est joint par le
tunnel décrit dans le [guide d'exploitation](huggingface-operations.md#nœud-joint-par-tunnel-ssh)
et annonce `hub_network_access: false` : les poids transitent par MinIO.

| Parcours | Résultat |
| --- | --- |
| Qwen2.5-0.5B-Instruct, safetensors, vLLM GPU | 13/18 au premier passage : import, MinIO, déploiement, renouvellement d'URL, inférence « Paris », refus après révocation corrects ; drain et purge en échec (clé du jeton de nœud absente de `hub-fetch`, corrigé en `f5773fff`) ; purge relancée ensuite, 5/5 |
| Qwen2.5-0.5B-Instruct GGUF, llama.cpp CPU | 18/18 : import par `hub-fetch` au commit figé, poids sous `hub/blobs`, transfert MinIO par le tunnel avec renouvellement d'URL pendant la préparation, route via le relais, inférence par le runtime de modèles, révocation du grant (inférence et renouvellement refusés en `HF_ACCESS_REVOKED`), drain automatique jusqu'à `stopped`, révocation plateforme, purge des objets MinIO et de la copie du nœud confirmée |

Correctifs issus de la recette : politique MinIO `hub-fetch` installable,
nom du conteneur `agentium-hub-fetch` contrôlé par le guard de stockage,
métadonnées Hub gzip décodées une seule fois, hôtes CDN régionaux
`*.cdn.hf.co`, et journal structuré dans `workspace_config`.

### Restant avant de marquer HF-4 terminé

1. Dépôt gated via MinIO : demande un jeton Hugging Face propre au workspace.
2. Expiration effective d'une URL signée pendant un transfert, puis reprise
   par renouvellement : seul le renouvellement pendant la préparation a été
   exercé.
3. Deux déploiements concurrents sur le nœud réel : l'admission sous verrou
   n'est couverte que par les tests du portail.
