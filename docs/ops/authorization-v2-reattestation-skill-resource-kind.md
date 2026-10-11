# Ré-attestation authorization-v2 — ajout du `resource_kind` `skill`

Date : 2026-08-08

Cette note couvre une seule mutation : la déclaration du `resource_kind`
`skill` (`read`, `admin`) dans `agentium_object_actions`
(`backend/app/services/iam/manifest.py`). Elle ne vaut pas preuve de
déploiement et n'autorise ni migration ni mutation de VM à elle seule.

## Ce que la mutation change

`candidate_config_sha256()` sérialise le registre `MANIFESTS` complet. Ajouter
deux `PermissionRule` déplace donc le digest de **toutes** les workspaces, quelle
que soit leur politique. C'est l'effet attendu : le digest existe précisément
pour qu'un changement de politique invalide les preuves qui portaient sur
l'ancienne.

Pour la forme de politique de référence (`config=None`) :

| | digest |
|---|---|
| avant | `7885d0fe7d0aa1e4d82536b9d2d878bcfa7baca1335ff8426796a89c02548a22` |
| après | `0d17b4c7481cc2b829c1882852ef67a640b670094925d80ed31bc5af16b03959` |

Ces deux valeurs ne servent qu'à vérifier que le digest a bougé. Le digest réel
d'une workspace dépend aussi de ses `policy_version`, `default_mode` et
`role_flags` ; il se calcule workspace par workspace avec la sonde ci-dessous.

La mémoïsation est inchangée : `_candidate_config_sha256` reste `lru_cache`d sur
la sérialisation `{policy_version, default_mode, role_flags}` et `MANIFESTS`
reste un registre statique du module. Un agrégat continue de hacher une fois par
politique distincte, pas une fois par ressource.

## Conséquence runtime sur une action déjà en `enforce`

Chaîne exacte, sans intervention :

1. `resolve_mode()` voit une clé exacte `enforce` et appelle
   `enforcement_attestation_errors(..., require_runtime_revision=True,
   require_server_receipt=True)` ;
2. `decision_plane.py:440` compare le `candidate_config_sha256` stocké dans
   l'attestation au digest runtime ; ils diffèrent désormais, ce qui produit
   `attestation candidate config differs from runtime policy` ;
3. `resolve_mode()` retourne `INVALID_ENFORCE`, jamais un repli silencieux ;
4. `resolve_candidate_permission()` force `effective_allowed = False` avec le
   motif `authorization_enforcement_attestation_invalid`.

L'action **refuse en fail-closed**. `shadow_review.py:239` applique la même
comparaison côté collecte de preuves : une fenêtre shadow ouverte avant la
mutation ne peut pas servir à promouvoir après.

Une action en `compat` ou en `shadow` n'est pas affectée : le digest n'entre
dans la décision que par la validation d'attestation, qui n'est atteinte que
depuis une déclaration `enforce` exacte.

## Portée mesurée

Aucune base de données n'était accessible depuis le poste de développement
(pas d'accès VM, port 5432 fermé en local). La portée est donc établie par le
code, puis à confirmer par la sonde ci-dessous avant le déploiement.

Trois verrous indépendants doivent tous être ouverts pour qu'une action soit
réellement en `enforce` aujourd'hui :

1. **La workspace doit porter une politique v2 avec une clé exacte `enforce`.**
   `build_authorization_v2_backfill()` écrit `default_mode: compat` et un
   `modes` entièrement en `shadow` ; seul `rollout_authorization_v2 promote
   --apply` peut écrire `enforce`. Une workspace sans clé `authorization_v2`
   dans `capability_overrides` résout tout en `compat`.
2. **L'héritage est impossible.** Une entrée `*.*` ou `skill.*` en `enforce`
   est rétrogradée en `shadow` par `resolve_mode()` : seule la clé exacte
   promue par le gate porte une autorité runtime.
3. **`settings.agentium_image_revision` doit être un SHA Git exact.** La valeur
   par défaut est `development`, que `GIT_SHA_RE` rejette ; toute attestation
   est alors déjà invalide, indépendamment du digest. Symétriquement,
   `authorization_v2_trusted_project_id` vaut `""` par défaut, ce qui bloque
   toute promotion (`trusted runner project is not the configured trust
   anchor`).

Autrement dit, sur un déploiement où ces deux réglages n'ont pas été renseignés,
`enforce` n'est pas atteignable et la portée de cette mutation est nulle.
L'hypothèse « andritz résout tout en `compat` faute de clé `authorization_v2` »
est cohérente avec le code mais **n'a pas pu être vérifiée en base** ; elle doit
l'être avec la sonde avant la fenêtre.

### Sonde à exécuter avant le déploiement

Depuis `backend/`, sur l'environnement cible, en lecture seule :

```bash
python - <<'PY'
from app.db.base import SessionLocal
from app.models.workspace import Workspace, WorkspaceIAMConfig
from app.services.iam.decision_plane import (
    ATTESTATIONS_KEY,
    AuthorizationMode,
    candidate_config_sha256,
    resolve_mode,
)

with SessionLocal() as db:
    for config, slug in db.query(WorkspaceIAMConfig, Workspace.slug).join(
        Workspace, Workspace.id == WorkspaceIAMConfig.workspace_id
    ):
        policy = (config.capability_overrides or {}).get("authorization_v2") or {}
        for key, declared in sorted((policy.get("modes") or {}).items()):
            if declared != AuthorizationMode.ENFORCE.value or "." not in key:
                continue
            kind, action = key.split(".", 1)
            effective = resolve_mode(config, resource_kind=kind, action=action, db=db)
            attested = ((policy.get(ATTESTATIONS_KEY) or {}).get(key) or {}).get(
                "candidate_config_sha256"
            )
            print(
                slug,
                key,
                effective.value,
                "digest_match" if attested == candidate_config_sha256(config) else "digest_drift",
            )
PY
```

Aucune ligne en sortie signifie portée nulle : aucune action n'est déclarée
`enforce`, il n'y a rien à ré-attester et le déploiement peut se faire sans
étape supplémentaire. Chaque ligne imprimée est une action à traiter.

Une ligne déjà en `invalid_enforce` **avant** la mutation signale une dérive
préexistante (révision d'image ou ancre de confiance non renseignée) ; elle doit
être traitée pour elle-même et non imputée à ce changement.

## Procédure de ré-attestation, dans la même fenêtre

À exécuter par workspace, pour chaque groupe d'attestation imprimé par la sonde.
Le groupe est indivisible : `--action` doit reprendre exactement la liste
`actions` de l'attestation stockée, sinon la démotion est refusée.

```bash
export WORKSPACE_ID=...          # id exact, jamais un slug ni --family
export TARGET_SHA=...            # SHA déployé, identique à agentium_image_revision
export ACTOR=...                 # opérateur nommé
export GROUP="--action system.read --action system.engine.run"  # groupe exact
```

1. **Constater** l'état, avant et après le déploiement de l'image :

   ```bash
   python -m scripts.rollout_authorization_v2 status --workspace-id "$WORKSPACE_ID"
   ```

   Après déploiement, chaque action du groupe porte
   `drift: ["attestation candidate config differs from runtime policy"]` et
   `effective_mode: invalid_enforce`.

2. **Redescendre le groupe en shadow.** C'est l'étape qui rouvre l'action :
   tant que l'attestation périmée est stockée, `promote` refuse de s'exécuter
   (`authorization enforce state is unattested or drifted`). Le groupe reste
   cohérent après un simple déplacement de digest, donc `--repair-drift` n'est
   **pas** nécessaire et ne doit pas être utilisé ici.

   ```bash
   python -m scripts.rollout_authorization_v2 demote \
     --workspace-id "$WORKSPACE_ID" $GROUP \
     --revision "$TARGET_SHA" \
     --actor "$ACTOR" --reason "manifest change: skill resource kind"

   python -m scripts.rollout_authorization_v2 demote \
     --workspace-id "$WORKSPACE_ID" $GROUP \
     --revision "$TARGET_SHA" \
     --apply --actor "$ACTOR" --reason "manifest change: skill resource kind"
   ```

3. **Observer une fenêtre shadow réelle sur le nouveau digest**, puis collecter
   les preuves. La fenêtre doit être postérieure au déploiement : le collecteur
   lie l'observation au digest runtime et refuse une fenêtre ouverte sur
   l'ancien.

4. **Re-promouvoir** le même groupe, avec l'identité OIDC protégée.

Les commandes exactes des étapes 3 et 4 (`collect_authorization_v2_shadow`,
`rollout_authorization_v2 promote`) ne sont pas dupliquées ici : elles sont
normatives dans
[`docs/agentium-lot7-object-graph-authorization.md`](../agentium-lot7-object-graph-authorization.md),
section « Procédure ». Les rejouer telles quelles avec `$TARGET_SHA`.

Conséquence de planification : la ré-attestation **ne tient pas** dans une
fenêtre de déploiement courte si une action est réellement en `enforce`, parce
que l'étape 3 exige du trafic réel observé. La séquence exécutable en fenêtre
est donc étapes 1 et 2 ; le groupe reste en `shadow` (non bloquant, autorité
legacy) jusqu'à la promotion suivante. Si la sonde ne retourne rien, la question
ne se pose pas.

## Ce qui reste avant que `skill.*` puisse être appliqué

`skill.read` et `skill.admin` sont déclarés au manifeste — c'est le prérequis
pour que `resolve_candidate_permission()` accepte le couple au lieu de lever
`Unknown candidate permission` — mais ils ne figurent pas dans
`build_authorization_v2_backfill()`. Ils résolvent donc en `compat` et
`rollout_authorization_v2` refuse de les promouvoir
(`_require_governed_actions`). Avant la tranche CRUD Skill scopée workspace, il
faudra ajouter `skill.read` et `skill.admin` au document de rollout dans
`backend/app/services/iam/decision_plane.py`, puis rejouer le backfill shadow.
Cet ajout ne déplace pas le digest : `modes` est délibérément exclu de
`candidate_config_sha256`.
