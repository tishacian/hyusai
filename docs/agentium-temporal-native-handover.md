# Candidat Temporal natif : image et lancement optionnels

Ce document concerne le candidat C natif, avec `temporalio==1.34.0` uniquement.
Les preuves A/B de `evidence/execution-observability-2026-10-15/report.md`
portent sur d'autres adaptateurs ; elles ne qualifient pas ce candidat. Les
fichiers ci-dessous préparent sa qualification. Ils n'activent ni une VM, ni un
workspace, ni un serveur Temporal.

## Image de même révision

`docker/Dockerfile.agentium-orchestration` part de l'image worker générale
déjà construite et qualifiée, référencée par son digest immuable. Il vérifie que
son `AGENTIUM_IMAGE_REVISION` hérité correspond au SHA complet attendu. Il ne
recopie pas les sources et ne remplace pas cette révision par une étiquette
arbitraire. Le SDK est ajouté dans `/opt/agentium-temporal`, un environnement
héritant des dépendances du worker, sous les contraintes de l'application. Les
requirements et images principaux restent inchangés.
`constraints-temporal.txt` fixe le SDK et ses deux ajouts hors contraintes
principales, `nexus-rpc` et `types-protobuf`, sans modifier la pile commune.

Exemple de construction après qualification de la base et sélection du SHA :

```sh
docker build -f docker/Dockerfile.agentium-orchestration \
  --build-arg WORKER_BASE_IMAGE="$QUALIFIED_WORKER_DIGEST" \
  --build-arg EXPECTED_WORKER_REVISION="$QUALIFIED_SOURCE_SHA" \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  -t "$ORCHESTRATION_CANDIDATE_TAG" .
```

Une CA publique nécessaire au proxy de construction peut être fournie par le
secret BuildKit `temporal_ca`. Aucun secret Temporal n'est un argument de build.
Avant lancement, vérifier les révisions des images API, worker et orchestration,
leur digest et les dépendances effectives. La taille et la mémoire du candidat
doivent être mesurées ; les mesures de l'image A/B ne s'y appliquent pas. Aucun
budget existant n'est relevé par ce fichier.

## Compose : deux processus, aucun serveur implicite

L'overlay `docker/compose.agentium.temporal.yml` impose une image qualifiée et
une adresse Temporal choisie explicitement. Il ne comporte aucun serveur de
développement. Les secrets d'accès restent dans le mécanisme d'environnement
opérationnel existant, jamais dans le YAML versionné.

`QUALIFIED_SOURCE_SHA` désigne le SHA complet de 40 caractères utilisé par
`EXPECTED_WORKER_REVISION`. `QUALIFIED_RELEASE_TAG` contient ses 12 premiers
caractères, conformément aux tags construits par `agentium-vm-build` ; c'est
ce tag de release que Compose utilise pour les images applicatives.

```sh
export AGENTIUM_ORCHESTRATION_IMAGE="$QUALIFIED_ORCHESTRATION_DIGEST"
export AGENTIUM_IMAGE_TAG="$QUALIFIED_RELEASE_TAG"
export EXECUTION_TEMPORAL_ADDRESS="$QUALIFIED_TEMPORAL_ADDRESS"
export EXECUTION_TEMPORAL_NAMESPACE=default
export EXECUTION_TEMPORAL_TASK_QUEUE=agentium-native-v1
export EXECUTION_TEMPORAL_TLS=true

docker compose -f docker/compose.agentium.yml \
  -f docker/compose.agentium.execution.yml \
  -f docker/compose.agentium.temporal.yml \
  --profile execution-control --profile execution-temporal config
```

La commande ci-dessus rend la configuration ; elle ne démarre rien. Après les
gates de qualification et l'autorisation de mise en service, les mêmes fichiers
et profils permettent de lancer les deux nouveaux services :

- `agentium-orchestration-starter` consomme exclusivement la file Celery
  `orchestration`, avec `app.workers.temporal_execution:app`, concurrence 1,
  pool `solo`, sans beat ni volumes d'artefacts.
- `agentium-orchestration-worker` exécute
  `python -m app.workers.temporal_execution worker`. Les étapes agentiques et
  juges accèdent aux mêmes objets, dépôt sécurisé en lecture seule, index FAISS
  et chemins de recettes que le worker natif. Les calculs enfants conservent
  leurs workers et leur autorité de ressources. Le registre de code vient de
  l'image ; les métadonnées et artefacts utilisent les mêmes services natifs.

Les deux dépendent du worker et du scheduler de contrôle existants. Ne pas
ajouter un second beat : la réconciliation doit être publiée par le scheduler
de contrôle vers `orchestration`. Les workers généraux ne doivent pas consommer
cette file. Le runtime suffixe la file Temporal par la révision du code : ne pas
remplacer les anciens consommateurs avant drainage ou migration explicitement
qualifiée de leurs workflows.

Le profil est un choix de déploiement ; `EXECUTION_TEMPORAL_ENABLED=false` reste
la valeur d'admission par défaut. Ouvrir de nouvelles soumissions exige le flag
et le périmètre `EXECUTION_CANARY_WORKSPACES` autorisé, ainsi que les autres
gates d'exécution applicables. Refermer ce flag empêche de nouveaux départs,
mais ne doit pas empêcher de redémarrer les processus pour drainer les commandes
et workflows déjà acceptés. L'overlay ne force donc jamais le flag à `true` et
ne conditionne pas le démarrage d'un consommateur au flag d'admission.

TLS est actif par défaut. L'adresse, le namespace, l'authentification et les
droits du serveur externe sont à qualifier avant toute activation. L'exemple
n'installe ni certificats, ni compte, ni accès réseau.

## Profil de composition et contrat de service

Le candidat ne remplace pas automatiquement le moteur d'un System. Son profil
`execution_profile.orchestration` doit être explicite et correspondre exactement
au Flow publié et à ses contrats figés. Exemple pour le premier parcours :

```json
{
  "max_runtime_s": 3600,
  "orchestration": {
    "engine": "temporal",
    "version": 1,
    "composition": "agent_data_agent",
    "role_nodes": {
      "agent_plan": "plan",
      "data_prepare": "prepare",
      "agent_explain": "explain",
      "review": "review",
      "delivery": "delivery"
    },
    "output_role": "data_prepare",
    "output_port": "out",
    "review": "service_delivery",
    "delivery": "service_receipt",
    "max_runtime_s": 3600,
    "poll_interval_s": 10
  }
}
```

Les valeurs de `role_nodes` sont les identifiants des nœuds du Flow. Le deuxième
profil, `data_agent_delivery`, remplace `agent_plan` par un rôle `judge` lié à
`evaluate_v2`, après `agent_explain`. Le rôle `data_prepare` accepte la préparation
ou le scoring en flux ; le scoring synchrone ne devient pas un calcul durable
par simple choix du profil. Les branches, boucles, `agent_loop` et sous-flows
restent sur leur moteur actuel. Un profil non représentable est refusé.

`output_role` désigne le résultat proposé à la revue de livraison. Pour un nœud
DataPrep à plusieurs sorties, `output_port` est obligatoire et doit nommer un
port de sa spécification publiée. Il est facultatif quand cette spécification
ne contient qu'une sortie. Le port est figé dans le digest du profil : la revue
et le reçu concernent exactement ce dataset. Le `from_port` de l'arête vers
l'agent règle séparément son entrée ; le candidat reprend la sélection canonique
du Flow, y compris la sortie unique implicite. Les autres Skills de sortie
n'acceptent pas `output_port`. Les recettes locales de sortie implicite et de
split avec port explicite vont jusqu'au reçu, dans les
[preuves du candidat C](evidence/execution-observability-2026-10-15/native-c/report.md).

Le System doit disposer d'un contrat de service publié : destination, propriétaire,
qualifications et politique d'approbation viennent de ce contrat. `service_tick`
crée la fenêtre, sa tentative et le Run publié, puis une seule intention Temporal
dans la même transaction. Le port exige ce lien avec une vraie fenêtre ; une
entrée manuelle dépourvue de fenêtre ne fournit aucune autorité de livraison.
L'échéance du candidat est bornée par celle de la fenêtre et par le profil.

L'opérateur examine le candidat dans la revue de livraison existante, avec sa
version et sa qualification. Le workflow observe cette décision persistée. Un
signal Temporal ou une approbation HITL générique ne vaut pas approbation de
livraison. Le reçu est publié par le service natif avec son bail et son fence.

L'historique Temporal ne contient que les références et les états nécessaires à
l'orchestration. Les entrées, sorties, secrets et preuves restent dans les
registres métier sous leurs droits. Une erreur après effet inconnu ferme la
tentative pour réconciliation ; elle ne provoque pas une seconde invocation.

## Handover Kubernetes

Le chart actuel n'ajoute pas ces Deployments automatiquement. Pour une future
intégration, conserver deux Deployments distincts utilisant le **même digest
d'image d'orchestration** : starter Celery et worker Temporal, avec les commandes
ci-dessus, les mêmes ConfigMap/Secret que l'application et un compte autorisé
sur le namespace Temporal. Garder `executionControl.enabled=true` et son unique
beat ; router la réconciliation vers la file dédiée, sans scheduler additionnel.

Le starter n'a besoin que de `/tmp` ; le worker doit retrouver les volumes
d'actifs natifs. Conserver `readOnlyRootFilesystem`, `no-new-privileges`, les
capabilities supprimées et des ressources bornées. Les valeurs proposées dans
Compose (starter 512 MiB / 1 CPU, worker 2 GiB / 1 CPU) sont des limites de
protection à mesurer, pas une capacité validée ni un changement des budgets
existants. Ne pas configurer de HPA ou retirer une révision encore propriétaire
de workflows sans qualification de leur reprise et du drainage.

La validation de schéma Compose et du garde de révision ne remplace pas les
preuves natives : reprise du worker et du serveur, redelivery sans effet
dupliqué, annulation, attente humaine, révocation, quotas, publication et
réconciliation doivent être établies par la recette du candidat C.
