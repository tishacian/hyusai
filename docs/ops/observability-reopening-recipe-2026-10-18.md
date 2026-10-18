# Observabilité : recette après déploiement de la PR #16

## État vérifié, options fermées

Le 18 octobre 2026 à 12:52 UTC, les deux `build-info` répondent avec
`bb33ceba5250e69aa4c59109f91f981f5095d446`, révision vérifiée. Health et
readiness répondent 200. GitHub porte cette révision sur `demo/agentic` et
`develop` ; `main`, à `e35a93d869b8c9a77c78500b1a3421a05fe3f1d1`, a le même
arbre. La PR #16 est fusionnée.

Les trois vrais comptes confirment le journal ouvert et les options séries
et Flow fermées. À 12:53 UTC, l'API de liste accepte
`status=pending,running,waiting` et exclut le Run en échec, pour chaque compte.
Une union contenant un statut invalide donne 422. La population active est
vide : cela ne qualifie pas le rendu d'un Run actif ni ses transitions.

[Relevé HTTP](../evidence/observability-live-2026-10-18/deployed-fix-http-check.json).
Les budgets d'images, la tête Alembic `138_activity_measures`, Bitbucket et
la recréation LiveKit proviennent du compte rendu opérateur. Ils ne sont pas
remesurés ici. Aucun accès SSH n'est disponible dans cet environnement.

La [recette précédente](observability-live-acceptance-2026-10-18.md) conserve
ses observations historiques. Le présent suivi ne déclare pas la livraison
qualifiée et ne change aucune option de production.

Le canari Qualité 66 a ensuite réussi sur cette révision, options fermées :
nuage et matrice vers le même Run et sa preuve, retour et rechargement,
clavier, 1440 et 390 px, radar et historique. Aucun appel métier en écriture
n'a été tenté. Les dix captures restent privées ; le
[relevé de recette](../evidence/observability-live-2026-10-18/deployed-quality-live.json)
ne contient que les identifiants et résultats. Ce parcours documentaire ne
possède pas de lien vers une invocation Skill ; ce lien n'est pas qualifié.

## Trois comptes, trois contrôles distincts

Le canari 67 accepte maintenant `E2E_OBSERVABILITY_PROFILE`, avec vérification
effective de `/auth/me` et des scopes, sans changement de rôle :

| Valeur | Rôle plateforme | Membership Showcase | Scopes |
| --- | --- | --- | --- |
| `owner` (défaut) | `user` | `owner` | workspace, system |
| `restricted` | `user` | `member` | workspace, system |
| `platform_admin` | `admin` | `member` | workspace, system, platform |

Les deux comptes dédiés ont le template `workspace_contributor`. Il n'existe
pas de rôle isolé à un seul System. `E2E_OBSERVABILITY_SYSTEM_ID` permet de
rejouer avec un filtre System réel : tuiles, listes paginées, séries et URL
emploient alors le même identifiant. Ce filtre ne prouve pas une isolation
par System.

Chaque principal compare ses séries à sa propre liste exhaustive autorisée.
Les séries de l'administrateur restent celles de Showcase. L'écran de portée
plateforme présente un agrégat `/platform-overview`, sans séries temporelles ;
son autorisation doit être contrôlée séparément (403 hors admin, 200 admin).

## Réouverture coordonnée sur la VM

L'opérateur doit pouvoir rétablir les deux options à `false` pendant toute la
recette. Sauvegarder le fichier effectif, avec permissions restreintes :
`/srv/agentium-data/runtime-env/2026-10-12/runtime-env/source-001.env`.
Y remplacer les deux valeurs, sans doublon et sans surcharge dans un overlay :

```dotenv
ACTIVITY_SERIES_ENABLED=true
EXECUTION_VIEW_ENABLED=true
```

Conserver les images actuellement en service, les huit workers et les profils
actifs. L'exemple ci-dessous correspond à la révision vérifiée ; si la
production a changé, relever ses images et ses profils avant de l'adapter.
Reprendre le plafond qualifié du runner de la dernière release dans
`AGENTIUM_IMAGE_BUDGET_MB_CONNECTOR_RUNNER`. Son image est lue sur le conteneur
actuel : ne pas réutiliser le digest du repli sur `12cdac72`. Le script exige
que le label de révision du runner soit identique à celui du backend.

```bash
export AGENTIUM_RUNTIME_ENV_DIR=/srv/agentium-data/runtime-env/2026-10-12
export AGENTIUM_IMAGE_TAG=bb33ceba5250 AGENTIUM_BACKEND_WORKERS=8
export AGENTIUM_ML_TS=1 AGENTIUM_ML_DEEP=1 AGENTIUM_HUGGINGFACE=1
export AGENTIUM_OPENBAO=1 AGENTIUM_CONNECTORS=1 AGENTIUM_EXECUTION_CONTROL=auto
export AGENTIUM_CONNECTOR_RUNNER_IMAGE="$(docker inspect --type container --format '{{.Config.Image}}' agentium-worker-connectors)"
: "${AGENTIUM_IMAGE_BUDGET_MB_CONNECTOR_RUNNER:?Reprendre le plafond qualifié de la dernière release}"
export AGENTIUM_IMAGE_BUDGET_MB_CONNECTOR_RUNNER
/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh storage-check
/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh up
```

Ne pas appeler `migrate`, reconstruire les images ou relancer LiveKit pour
cette ouverture. Vérifier les deux révisions, health/readiness, les options
effectives du backend et du contrôle, puis `/activities/features` authentifié.
Conserver la migration 138, le journal, l'admission et le contrôle d'exécution.
Si la recette échoue, remettre les deux valeurs à `false` et rejouer
`storage-check`, puis `up` avec les mêmes paramètres ; confirmer la fermeture
par l'API. Ne pas revenir aux anciennes images.

## Exécution depuis l'environnement de recette

Injecter les secrets du compte choisi dans `E2E_USERNAME` et `E2E_PASSWORD`.
Ne pas les inscrire dans les commandes versionnées, preuves ou traces.
Définir `E2E_BASE_URL=https://agentium.papai.ai`,
`E2E_SHOWCASE_WORKSPACE_SLUG=agentium-showcase` et le SHA complet réellement
déployé dans `E2E_EXPECTED_REVISION`. Depuis `frontend-ng`, pour chacun des
trois comptes, avec un répertoire de résultats distinct et privé :

```bash
E2E_OBSERVABILITY_PROFILE=restricted \
npx --no-install playwright test \
  --config=playwright.observability-live.config.ts \
  67-observability-series-release-canary.spec.ts \
  --output=/tmp/observability-recipe-restricted
```

Remplacer `restricted` par `owner` ou `platform_admin`, et injecter les
identifiants correspondants. Le canari exige les deux options ouvertes,
un corpus réel non vide, la parité liste/séries, les liens des quatre tuiles,
le filtre après rechargement et les graphiques sur 1440 et 390 px.
L'absence de données ne devient pas une réussite par substitution.

Le canari 66 reste exécutable options fermées en le sélectionnant seul avec
`E2E_EXPECT_ACTIVITY_SERIES=false` et `E2E_EXPECT_EXECUTION_VIEW=false`.
Après ouverture, passer ces attentes à `true`. Pour le canari 68, fournir
`E2E_FLOW_RUN_IDS` avec des identifiants de Runs existants et autorisés :
`519ce4f9-583e-4d70-a4b7-c3229d1749d8,666a0219-36a5-4dc2-871d-a92fe44575f2`.

## Contrôles encore nécessaires au-delà des canaris

- Exécuter deux parcours composites dédiés à la recette et suivre leurs
  passages, tentatives et attentes réels, dont un Run actif non vide.
- Couper la connexion pendant une transition puis reconnecter : vérifier le
  curseur, le rattrapage, l'absence de doublons et l'état terminal. Le canari
  68 ne prouve qu'un handshake SSE et un heartbeat sur un Run historique.
- Publier une nouvelle version d'un Flow de recette et vérifier que son
  ancien Run conserve le graphe et l'empreinte enregistrés. Deux historiques
  de versions différentes ne suffisent pas à tester cette opération.
- Retirer le membership du seul compte restreint pendant que ses graphiques
  et son Flow sont ouverts. Vérifier la purge, les réponses refusées et
  l'absence de réapparition après réponse tardive ou reconnexion. Restaurer
  dans un `finally` son rôle, ses labels et ses habilitations capturés avant
  le retrait, en utilisant le compte propriétaire ; ne pas toucher à celui-ci.
- Vérifier séparément les refus natifs sur les jobs masqués et l'agrégat
  plateforme. Ne pas assimiler ces contrôles à un rôle exclusif System.

Consigner les résultats et limites par profil, avec révision et options
avant/après. Conserver les captures contenant des données hors du dépôt.
Les canaris seuls ne ferment pas ces contrôles manquants.
