# Agentium Lot 7 — graphe objet et autorisation progressive

Ce document décrit le contrat de livraison du Lot 7. Il ne constitue pas une
preuve de déploiement : les états de conformité restent calculés depuis
`config/agentium/product-compliance.v1.json` et les attestations vérifiées.

## Niveaux de preuve

Les niveaux sont monotones et ne se déduisent jamais les uns des autres :

| Niveau | Signification |
|---|---|
| `declared` | Le contrat est décrit, sans preuve statique complète. |
| `static_verified` | Les fichiers et littéraux exigés par le manifeste sont présents. Cela ne prouve pas que les tests ont été exécutés. |
| `runner_verified` | Tous les runners requis ont produit des artefacts liés au SHA dans un job authentifié. |
| `deployed_verified` | Le même SHA est attesté sur l’environnement cible après les preuves runner. |
| `behavior_verified` | Le canari authentifié a réussi sur ce SHA et cet environnement. |
| `user_validated` | Un protocole versionné sans coaching a atteint ses seuils auprès d’utilisateurs représentatifs. |

La matrice publiée dans le dépôt ne calcule que l’état statique. Le collecteur
authentifié accepte séparément les preuves runner, environnement,
comportementales et utilisateur. Une attestation utilisateur ne peut promouvoir
un claim que si ce même claim est déjà `behavior_verified` et si les seuils
ci-dessous sont recalculés par le collecteur ; son libellé `passed` n’est jamais
cru seul.

P4 est un prérequis déjà clos. Les opérations ci-dessous commencent après P4
et ne le rouvrent pas.

## Portée

Le Lot 7 étend les quatre perspectives objet, dans cet ordre :

1. `Capability` ;
2. `Run` ;
3. `SkillInvocation`.

`Skill` reste le composant de conception du catalogue. `SkillInvocation` est
une exécution réelle, identifiée sous son `Run`. Les deux objets ne partagent
ni route canonique, ni identité, ni projection.

Les routes de perspective sont :

- `GET /api/v1/capabilities/{capability_id}/perspective` ;
- `GET /api/v1/runs/{run_id}/perspective` ;
- `GET /api/v1/runs/{run_id}/invocations/{invocation_id}/perspective`.

Elles acceptent uniquement `lens=build|operate|steer|govern` et une fenêtre
`7d`, `30d` ou `90d`. Chaque réponse conserve une identité et un header
invariants entre les lenses, expose quatre facettes stables et qualifie toute
donnée absente par un état explicite. Une projection ne fabrique ni mesure, ni
permission.

## Gates et ordre de déploiement

Les trois flags sont indépendants :

- `capability_360_projection_v1` ;
- `run_360_projection_v1` ;
- `skill_invocation_360_projection_v1`.

Un flag seul n'active jamais une projection. Le runtime exige aussi le résumé
d'attestation ordonné `_lot7_projection_gate_v1`, écrit atomiquement par le
service de rollout et préservé hors des PATCH génériques et des Blueprints.
Un état absent, mal formé ou non contigu échoue fermé. Les flags sont désactivés
par défaut. Le rollout découvre le canari depuis le marqueur
persisté `settings.experience.system_360_canary = "v1"`, jamais depuis un nom,
un slug ou un identifiant fixé dans le code. L'activation est volontairement
en deux phases afin de ne pas demander une preuve impossible à produire gate
off :

1. `stage` ouvre uniquement la projection suivante pendant au plus 30 minutes,
   avec un `lease_id`, le SHA runtime exact et le sujet découvert ;
2. le canari authentifié lit ce gate serveur et atteste le même lease et le
   même SHA ;
3. `finalize` remplace atomiquement la probation par une activation vérifiée ;
4. `deactivate` annule aussi bien la queue vérifiée qu'une probation expirée.

Le runtime refuse une probation expirée ou exécutée sur un autre SHA. Une
probation ne peut exister qu'en queue du préfixe ordonné. Le rollout refuse :

- un `workspace_id` absent ou inactif ;
- zéro ou plusieurs Systems marqués dans le workspace explicitement ciblé ;
- une Capability hors du workspace ;
- l’absence des prérequis Lot 6 `cockpit_router_axes_v4` et
  `system_360_projection_v1` ;
- une activation hors ordre ;
- une finalisation sans preuve liée au workspace, à la Capability, au System,
  à la projection, au `lease_id` et à la révision testée ;
- une finalisation appliquée sans observation pilote structurée, réalisée sans
  coaching dans le même lease et liée exactement aux mêmes identifiants ;
- une finalisation appliquée hors d’un runner GitLab OIDC protégé et lié au
  SHA déployé ;
- une preuve vieille de plus de 24 heures ou datée dans le futur ;
- une divergence entre le flag, le gate Workspace et l’historique d’attestation.

Le rollback désactive les gates dans l’ordre inverse : SkillInvocation, Run,
puis Capability. Les données et versions restent en place.

### Procédure opératoire des projections

Toutes les commandes backend ci-dessous s’exécutent depuis `backend/`. La
révision cible doit être le SHA Git complet réellement construit et servi par
le backend et le frontend.

1. Vérifier l’état et simuler le prochain stage :

   ```bash
   python -m scripts.rollout_lot7_projections status \
     --workspace-id "$WORKSPACE_ID"
   python -m scripts.rollout_lot7_projections stage capability \
     --workspace-id "$WORKSPACE_ID"
   ```

2. Ouvrir la probation pour 30 minutes au maximum :

   ```bash
   python -m scripts.rollout_lot7_projections stage capability \
     --workspace-id "$WORKSPACE_ID" \
     --apply --actor "$ACTOR"
   ```

3. Pendant le lease, lancer le canari depuis `frontend-ng/` avec des secrets
   fournis uniquement par l’environnement :

   ```bash
   E2E_LOT7_CANARY=1 \
   E2E_LOT7_PROJECTION=capability \
   E2E_LOT7_WORKSPACE_ID="$WORKSPACE_ID" \
   E2E_EXPECTED_SHA="$TARGET_SHA" \
   E2E_USERNAME="$E2E_USERNAME" \
   E2E_PASSWORD="$E2E_PASSWORD" \
   E2E_ENVIRONMENT="$TARGET_ENVIRONMENT" \
   E2E_LOT7_EVIDENCE=e2e/results/lot7-capability-evidence.json \
   npx playwright test e2e/tests/12-lot7-object-graph-canary.spec.ts \
     --project=chromium
   ```

   Le canari déclenche lui-même un Run après `staged_at`, attend son succès et
   atteste exactement cet ID. L'entrée par défaut est générique ; un flow qui
   exige un contrat d'entrée particulier peut recevoir un objet JSON via
   `E2E_LOT7_RUN_INPUT_JSON`, sans valeur métier fixée dans le test. Un Run
   échoué, annulé, en HITL ou exécuté par un autre SHA invalide la preuve.

4. Dans le même lease, recueillir une observation pilote sans coaching. Le
   document JSON est strict : profil parmi `builder|operator|decision_owner|
   governor|transverse`, sujet exact (`workspace_id`, `capability_id`,
   `system_id`, projection, SHA et `lease_id`), heure d’observation et exactement
   quatre résultats `build|operate|steer|govern`. Chaque résultat porte
   `success=true`, un temps strictement positif et inférieur ou égal à 60 s,
   une confiance entre 4 et 5 et `critical_confusion=false`. Exemple de forme :

   ```json
   {
     "schema_version": 1,
     "kind": "lot7_projection_pilot_observation",
     "subject": {
       "workspace_id": "<immutable workspace id>",
       "system_id": "<discovered system id>",
       "capability_id": "<discovered capability id>",
       "projection": "capability",
       "revision": "<40-character deployed SHA>",
       "lease_id": "<active probation lease id>"
     },
     "observed_at": "<ISO-8601 timestamp with timezone>",
     "participant": {
       "id": "opaque-stable-participant-id",
       "profile": "operator"
     },
     "uncoached": true,
     "questions": [
       {"lens": "build", "success": true, "duration_seconds": 42, "confidence": 4, "critical_confusion": false},
       {"lens": "operate", "success": true, "duration_seconds": 38, "confidence": 4, "critical_confusion": false},
       {"lens": "steer", "success": true, "duration_seconds": 51, "confidence": 4, "critical_confusion": false},
       {"lens": "govern", "success": true, "duration_seconds": 47, "confidence": 5, "critical_confusion": false}
     ]
   }
   ```

5. Vérifier la finalisation en dry-run, puis l’appliquer dans le job protégé
   qui possède le token OIDC. Les deux commandes lisent le même fichier pilote :

   ```bash
   python -m scripts.rollout_lot7_projections finalize capability \
     --workspace-id "$WORKSPACE_ID" \
     --evidence ../frontend-ng/e2e/results/lot7-capability-evidence.json \
     --pilot-observation "$PILOT_OBSERVATION"

   python -m scripts.rollout_lot7_projections finalize capability \
     --workspace-id "$WORKSPACE_ID" \
     --evidence ../frontend-ng/e2e/results/lot7-capability-evidence.json \
     --pilot-observation "$PILOT_OBSERVATION" \
     --oidc-token-env AGENTIUM_ATTESTATION_ID_TOKEN \
     --oidc-audience "$CI_SERVER_URL" \
     --apply --actor "$ACTOR"
   ```

6. Refaire exactement la séquence avec `run`, puis `skill_invocation`. Le
   statut doit montrer un préfixe contigu et `complete=true` seulement après
   les trois preuves liées au runner, au SHA courant et au canari.

Le champ `complete` est l’état interne de ce rollout ; il ne remplace pas le
rapport de conformité authentifié, qui exige aussi ses propres artefacts de
runner, d’environnement et de comportement.

Le document pilote brut n’est pas copié dans les settings. Son identifiant
participant opaque est haché ; la finalisation persiste l’adresse du document,
ce `participant_ref`, un résumé non sensible et l’ID d’un événement AuditLog
transactionnel lié au runner protégé. `status` revalide cet événement avant de
déclarer `pilot_observed`. Une finalisation sans token OIDC reste possible en
dry-run pour prévisualiser le résultat, mais `--apply` la refuse : une
probation ne devient donc jamais une activation finale `operator_validated`
non authentifiée.

La preuve projections utilise le schéma v2. Elle ne contient plus cinq
booléens auto-déclarés : elle embarque un manifeste source canonique référencé
par SHA-256, les empreintes API et UI d'un fact réellement rendu pour chaque
lens, la version exacte du flow et le ledger complet des invocations. Un petit
artefact JUnit content-addressé est décodé et reparsé par le rollout ; ses
compteurs doivent annoncer au moins un test, sans failure, error ni skip, et
ses propriétés doivent correspondre au SHA, au workspace, aux objets, à la
projection et au `lease_id`. Lorsqu'un token OIDC est fourni, les propriétés
`CI_PROJECT_ID`, `CI_PIPELINE_ID` et `CI_JOB_ID` de l'artefact doivent aussi
correspondre au runner authentifié. Le serveur revalide ensuite ces références contre
les lignes Run, SystemVersion et SkillInvocation avant toute finalisation.

En cas d’échec ou de lease expiré, retirer d’abord la queue concernée. Pour un
rollback complet :

```bash
python -m scripts.rollout_lot7_projections deactivate skill_invocation \
  --workspace-id "$WORKSPACE_ID"
python -m scripts.rollout_lot7_projections deactivate skill_invocation \
  --workspace-id "$WORKSPACE_ID" \
  --apply --actor "$ACTOR"
python -m scripts.rollout_lot7_projections deactivate run \
  --workspace-id "$WORKSPACE_ID" \
  --apply --actor "$ACTOR"
python -m scripts.rollout_lot7_projections deactivate capability \
  --workspace-id "$WORKSPACE_ID" \
  --apply --actor "$ACTOR"
python -m scripts.rollout_lot7_projections status \
  --workspace-id "$WORKSPACE_ID"
```

Chaque `deactivate` est à exécuter d’abord sans `--apply` pour vérifier le
sujet et l’effet attendu.

## Cache et changement de workspace

Le frontend précharge les quatre lenses. La clé de cache comprend l’epoch du
workspace, son slug courant, l'epoch du principal authentifié, le type d’objet,
les identifiants parents, la lens et la fenêtre. Logout, session invalidée ou
changement de sujet invalident cet epoch même si le workspace ne change pas.
Les quatre réponses sont validées ensemble avant toute écriture
en cache : schéma, identité, header, snapshot, parent Run et workspace doivent
être cohérents. Le cache a une durée de vie et une taille bornées, est vidé
atomiquement lors du changement de workspace et une réponse d’un epoch
précédent est rejetée. Deux chargements concurrents identiques partagent une
seule requête ; un refresh forcé plus récent gagne toujours et une réponse
supersédée ne peut pas repeupler le cache. Les `snapshot_id` fingerprintent les
valeurs exposées par les quatre perspectives, y compris décisions, audits et
policies. Une divergence inter-lens déclenche un unique rejeu complet puis
échoue explicitement si l'état continue de changer.

Une `SkillInvocation` nouvelle conserve une preuve d’exécution immuable :
identité/version/provider/certification du Skill réellement résolu et empreintes
SHA-256 des contrats. Elle ne copie ni schéma brut, ni configuration
d’exécution, ni credential. Les lignes historiques restent explicitement
inconnues. Le booléen tri-état `cost_measured` distingue un vrai coût nul d’une
absence de mesure.

## Autorisation v2

Le decision plane compare une décision legacy et une décision candidate pour
chaque frontière explicite. Les modes ont la sémantique suivante :

- `compat` : la décision legacy reste effective ;
- `shadow` : la décision legacy reste effective et toute divergence est
  auditée sans attribut sensible ;
- `enforce` : la décision candidate devient autoritaire.

Le backfill est idempotent, ciblé par identifiant immutable de workspace ou
famille canonique, et ne remplace jamais les extensions de politique propres au
workspace. Les actions couvertes comprennent les lectures objet, l’exécution
du moteur, l’envoi de mail, l’approbation, la publication et l’administration.

`enforce` ne peut pas élargir une garde structurelle. Le HITL du System Agentic
managed reste admin/owner avant toute résolution `run.approve` : la policy v2
peut ensuite restreindre cette population, mais un reviewer ne peut pas devenir
approbateur de ce System par simple promotion du manifeste.

L’incohérence reviewer de Knowledge Capture est traitée comme une politique
candidate séparée. Le manifeste historique reste inchangé en `compat` et en
`shadow`. Une promotion en `enforce` n’est possible qu’après observation des
différences et backfill explicite du workspace.

La promotion `shadow → enforce` est ciblée par identifiant immuable de
workspace et par liste exacte d’actions. Elle exige une preuve de moins de
24 heures, liée à un SHA Git complet, deux contrats JUnit content-addressés
ayant chacun au moins un test réellement exécuté, des
observations réellement non nulles et zéro divergence inexpliquée. Une
divergence intentionnelle n’est jamais « expliquée » par le collecteur seul :
elle exige une review persistée par un administrateur de policy authentifié. La source
d’observation est un manifeste des événements `iam.shadow.evaluation`, lié à
la fenêtre, au workspace et aux actions puis référencé par `sha256:<64 hex>`.
Chaque événement persiste `details.action` sous la clé canonique complète
`resource_kind.action` ; les actions courtes internes au resolver ne sont
jamais un contrat du collecteur.
Le collecteur refuse les compteurs déséquilibrés, les observations absentes et
toute divergence non revue. Il ne classe jamais lui-même une divergence comme
« expliquée ».

Pour une divergence intentionnelle, exécuter d’abord le collecteur sans review
afin d’obtenir le `source_manifest`, son `source_ref` et les IDs exacts des
observations en écart. Un administrateur du workspace envoie ensuite ce
manifeste complet à
`POST /api/v1/iam/authorization-v2/mismatch-reviews`, avec des entrées
`{action, observation_ids, reason_code, reason}`. Le serveur reconstruit la
source exhaustive depuis `AuditLog`, lie l’identité du reviewer, refuse une
couverture partielle et persiste un document content-addressé. L’`audit_id`
retourné est alors fourni au collecteur avec `--mismatch-review-id`. Le
promoteur recharge cette même review depuis le ledger et revalide toutes les
lignes source, y compris lorsque le manifeste déclare zéro mismatch ; une
review libre, modifiée ou seulement présente dans un fichier est rejetée.

L’application de la promotion exige en plus un token OIDC GitLab vérifié sur
une ref protégée. L’issuer, le projet, le pipeline, le job, la ref et le SHA
sont persistés sous forme d’attestation réduite ; le SHA du runner doit être
exactement celui de la promotion et l’issuer doit correspondre à l’ancre de
confiance serveur. Le projet GitLab numérique et la ref doivent également
correspondre aux ancres de déploiement ; un identifiant de projet vide bloque
volontairement tout `enforce`. Un déploiement direct depuis la VM peut activer le shadow,
mais ne peut donc pas produire un `enforce` valide. Une clé qui n’appartient
pas au contrat de rollout est refusée. Le retour `enforce → shadow` doit
reprendre le groupe d’attestation complet ; il est atomique, exige un acteur et
un motif, retire l’attestation active et conserve un historique ainsi qu’un
audit. Une réparation restrictive explicite reste disponible si l’état
persisté a dérivé.

### Préflight Client360 obligatoire

Le code Client360 échoue fermé si son unique System actif et sa Capability
canonique ne peuvent pas être résolus. Avant toute mise à jour contenant ces
frontières d’autorisation, exécuter le préflight en lecture seule depuis
`backend/` avec le SHA exact ciblé :

```bash
python -m scripts.preflight_client360_authority \
  --runtime-revision "$TARGET_SHA"
```

La cohorte est l’union des workspaces actifs de famille Andritz, des
installations déclarant la surface Client360, des membres possédant un
entitlement Client360 et des éventuels `--workspace-id` explicites. Le script
n’accepte ni slug ni nom comme autorité. Le gate est vert uniquement si
`summary.blocked == 0`, si chaque ligne a `ready=true` et si le SHA runtime est
un SHA Git complet. Le code de sortie `2` bloque l’opération. L’option
`--allow-unbound-runtime` sert seulement à une inspection locale et ne produit
pas une preuve de rollout.

Conserver comme artefact le rapport JSON, notamment `workspace_id`,
`system_id`, `capability_id`, `candidate_config_sha256`, `authority_sha256` et
`runtime_revision`. Rejouer ce préflight si la configuration IAM change, même
si son numéro de version n’a pas changé.

### Séquence opérationnelle de l’autorisation v2

1. Préparer le shadow sans mutation, puis l’appliquer par workspace immuable
   ou famille canonique :

   ```bash
   python -m scripts.backfill_authorization_v2 \
     --workspace-id "$WORKSPACE_ID"
   python -m scripts.backfill_authorization_v2 \
     --workspace-id "$WORKSPACE_ID" \
     --apply --actor "$ACTOR"
   ```

   `--family andritz` est autorisé pour le backfill shadow ; il ne doit jamais
   servir à une promotion `enforce`, qui exige un `workspace_id` exact et une
   liste exacte d’actions.

2. Vérifier l’état du groupe d’actions :

   ```bash
   python -m scripts.rollout_authorization_v2 status \
     --workspace-id "$WORKSPACE_ID" \
     --action system.read \
     --action system.engine.run \
     --action mail_draft.mail.send
   ```

3. Après une fenêtre shadow réelle, collecter les observations et les deux
   JUnit dans le job protégé :

   ```bash
   python -m scripts.collect_authorization_v2_shadow \
     --workspace-id "$WORKSPACE_ID" \
     --action system.read \
     --action system.engine.run \
     --action mail_draft.mail.send \
     --revision "$TARGET_SHA" \
     --window-started-at "$WINDOW_STARTED_AT" \
     --window-ended-at "$WINDOW_ENDED_AT" \
     --validated-by "$ACTOR" \
     --environment "$TARGET_ENVIRONMENT" \
     --legacy-junit "$LEGACY_JUNIT" \
     --candidate-junit "$CANDIDATE_JUNIT" \
     --oidc-token-env AGENTIUM_GITLAB_ID_TOKEN \
     --oidc-audience "$CI_SERVER_URL" \
     --output "$AUTH_EVIDENCE"
   ```

   Le collecteur bloque toute action sans observation, tout JUnit sans test
   exécuté, toute divergence non revue ou toute incohérence de compteur. Si une
   review serveur a été créée, rejouer exactement cette commande avec
   `--mismatch-review-id "$MISMATCH_REVIEW_AUDIT_ID"` avant de promouvoir.

4. Simuler, puis promouvoir atomiquement le même groupe :

   ```bash
   python -m scripts.rollout_authorization_v2 promote \
     --workspace-id "$WORKSPACE_ID" \
     --action system.read \
     --action system.engine.run \
     --action mail_draft.mail.send \
     --revision "$TARGET_SHA" \
     --evidence "$AUTH_EVIDENCE"

   python -m scripts.rollout_authorization_v2 promote \
     --workspace-id "$WORKSPACE_ID" \
     --action system.read \
     --action system.engine.run \
     --action mail_draft.mail.send \
     --revision "$TARGET_SHA" \
     --evidence "$AUTH_EVIDENCE" \
     --oidc-token-env AGENTIUM_ATTESTATION_ID_TOKEN \
     --oidc-audience "$CI_SERVER_URL" \
     --apply --actor "$ACTOR"
   ```

   Un workflow direct sur VM peut préparer et observer le shadow, mais ne peut
   pas produire une promotion `enforce` valide sans l’identité OIDC protégée.

5. Pour revenir en shadow, redonner exactement le groupe attesté et sa
   révision. Simuler avant d’appliquer :

   ```bash
   python -m scripts.rollout_authorization_v2 demote \
     --workspace-id "$WORKSPACE_ID" \
     --action system.read \
     --action system.engine.run \
     --action mail_draft.mail.send \
     --revision "$TARGET_SHA" \
     --actor "$ACTOR" --reason "$ROLLBACK_REASON"

   python -m scripts.rollout_authorization_v2 demote \
     --workspace-id "$WORKSPACE_ID" \
     --action system.read \
     --action system.engine.run \
     --action mail_draft.mail.send \
     --revision "$TARGET_SHA" \
     --apply --actor "$ACTOR" --reason "$ROLLBACK_REASON"
   ```

   `--repair-drift` est réservé à une réparation restrictive explicitement
   auditée ; ce n’est pas un raccourci de rollout.

## Shadow Membrane Andritz

Andritz ne passe pas en `enforce` dans ce lot. La préparation shadow :

- découvre les workspaces par famille canonique et les bindings par provenance
  de Membrane, sans branche de slug ;
- clone la policy source en MembraneSpec v2 `shadow` ;
- conserve la policy source et les SystemVersions historiques ;
- crée une nouvelle transition de version avec uniquement des références et
  empreintes positives, sans secrets ;
- est dry-run par défaut, idempotente et auditée lors de l’application.

La préparation est en outre interdite tant que le `status` DB autoritaire du
rollout Showcase Lot 6 ne retourne pas `ready=true`. Le dry-run expose ce
prérequis séparément de `ready`, qui décrit la seule cohérence structurelle de
la cohorte Andritz, et en donne une adresse SHA-256. L’application réévalue le
prérequis dans la même transaction puis en persiste la référence dans le
marqueur et l’audit. Le CLI retourne `2` si `ready=false` **ou** si
`prerequisite.ready=false`.

Le rollback dédié redécouvre uniquement le marqueur créé par ce rollout. Il ne
dépend jamais de l’état Showcase, afin qu’une restauration ne puisse pas être
bloquée par la dégradation d’un prérequis forward-only. Il
vérifie les deux policies, leurs empreintes et la SystemVersion de transition,
refuse toute ambiguïté ou dérive, puis rétablit atomiquement la policy source.
Il ajoute une nouvelle SystemVersion de configuration et un audit ; il ne
modifie ou ne supprime ni la policy shadow, ni les versions historiques. Le
rollback est lui aussi dry-run par défaut (`--rollback`, puis
`--rollback --apply --actor ...`).

La procédure complète, depuis `backend/`, est :

```bash
# Préflight de préparation, sans mutation.
python -m scripts.prepare_andritz_membrane_shadow

# Application seulement si ready=true, blockers=[] et prerequisite.ready=true.
python -m scripts.prepare_andritz_membrane_shadow \
  --apply --actor "$ACTOR"

# Préflight du rollback, limité aux marqueurs créés par ce rollout.
python -m scripts.prepare_andritz_membrane_shadow --rollback

# Restauration append-only de la policy source.
python -m scripts.prepare_andritz_membrane_shadow \
  --rollback --apply --actor "$ACTOR"
```

Chaque application refait la découverte sous les verrous exacts et bloque si
le sujet, le binding, le contrat ou la SystemVersion a dérivé depuis le
préflight. Un code de sortie `2` interdit de poursuivre. La préparation shadow
n’est pas, à elle seule, une preuve de non-régression Andritz : les gardes
métier, le golden retrieval et le shell à trois applications doivent encore
être rejoués, ainsi que Sentinel et Octocity séparément.

Les valves coût, tokens et latence portent une couverture de mesure explicite.
En v2 `enforce`, un budget configuré sans mesure complète produit
`*_measurement_unavailable` et bloque la publication ; `shadow` observe la
même divergence sans changer l'expérience et `compat` conserve la décision
historique. Un zéro n'est conforme que lorsqu'il a été explicitement rapporté.
Les descendants subflow appartiennent au ledger du parent ; un enfant sans
ledger crée un gap, jamais un coût ou un volume de tokens nul implicite.

## Validation utilisateur et promotion de conformité

Pendant la probation de chaque projection, au moins une observation pilote
sans coaching doit couvrir les quatre questions Build, Operate, Steer et
Govern en 60 secondes au plus chacune, avec quatre succès, une confiance d’au
moins 4/5 pour chaque réponse et zéro confusion critique. Le document porte un
profil canonique et les identifiants exacts du SHA, du lease, du workspace, de
la Capability, du System et de la projection. Cette observation pilote est un
gate produit content-addressé, mais elle ne suffit pas à produire
`user_validated`.

L’attestation formelle `kind=user_validation` doit être liée au même SHA, au
même job protégé et au même ensemble de claims que les preuves précédentes.
Son objet `study` respecte ce contrat minimal :

```json
{
  "participant_count": 5,
  "profiles": [
    "builder",
    "operator",
    "decision_owner",
    "governor",
    "transverse"
  ],
  "successes_per_question": {
    "build": 4,
    "operate": 4,
    "steer": 4,
    "govern": 4
  },
  "confidence_mean": 4.0,
  "critical_identity_or_lens_confusions": 0
}
```

Les cinq profils sont obligatoires, il faut au moins cinq participants, au
moins quatre succès pour chacune des quatre questions, une confiance moyenne
au moins égale à 4/5 et zéro confusion critique d’identité ou de lens. Le
collecteur recalcule ces seuils et refuse tout contournement par un simple
`result=passed`.

Le rapport formel se construit dans le job protégé en ajoutant l’artefact
utilisateur à la chaîne déjà complète :

```bash
python3 scripts/agentium_trusted_compliance.py \
  --static-report "$STATIC_REPORT" \
  --runner-attestation "$RUNNER_ATTESTATION" \
  --deployment-attestation "$DEPLOYMENT_ATTESTATION" \
  --behavior-attestation "$BEHAVIOR_ATTESTATION" \
  --user-attestation "$USER_ATTESTATION" \
  --output "$TRUSTED_COMPLIANCE_REPORT"
```

Sans les quatre niveaux précédents pour le claim concerné, l’attestation
utilisateur ne le promeut pas.

## Gates de sortie

Le Lot 7 n’est déclarable terminé qu’après :

- conformité statique régénérée et contrôle
  `python3 scripts/agentium_compliance.py --check` vert ;
- préflight Client360 lié au SHA cible avec `summary.blocked == 0` ;
- tests backend des quatre projections, de l’isolation workspace et des
  décisions `compat|shadow|enforce` ;
- tests frontend du cache par epoch, des routes Run/SkillInvocation et du
  comportement gate-off ;
- build frontend de production sous Node 22 ;
- preuve comportementale authentifiée sur la révision réellement déployée ;
- activation séquentielle Showcase ;
- campagne utilisateur sans coaching couvrant les cinq profils et les seuils
  formels, après la preuve comportementale ;
- si la préparation shadow Andritz est appliquée, gardes métier, golden
  retrieval et shell à trois applications rejoués avant de poursuivre ;
- non-régression Sentinel et Octocity vérifiée séparément, branding et action
  packs compris.
