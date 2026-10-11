# Lot 8 — rollout sûr de la boucle de valeur

Le rollout du canari Lot 8 est piloté par
`backend/scripts/rollout_value_loop.py`. Il ne sélectionne jamais un workspace
ou un System par slug, nom ou identifiant codé en dur.

## Cible et invariants

- La cible normale porte `settings.experience.value_loop_canary = "v1"`.
- Lors du premier `prepare`, ce marqueur peut uniquement être dérivé de
  l'unique System actif portant `system_360_canary = "v1"` dans le workspace
  explicitement borné par `--workspace-id`.
- Zéro ou plusieurs marqueurs compatibles font échouer l'opération.
- Les commandes sont des dry-runs par défaut. Toute écriture exige `--apply`
  et un acteur non vide.
- `prepare` ne peut jamais activer `features.value_loop_v1`.

## Séquence opérateur

```bash
cd backend
python -m scripts.rollout_value_loop status --workspace-id "$WORKSPACE_ID"
python -m scripts.rollout_value_loop prepare \
  --workspace-id "$WORKSPACE_ID"
python -m scripts.rollout_value_loop prepare \
  --workspace-id "$WORKSPACE_ID" --apply --actor "$OPERATOR"
```

La préparation ajoute uniquement le contrat borné
`control_policy.guardrails.patch.v1` et son autorisation explicite dans la
facette `capabilities.allowed_actions` de la Membrane v2. Le changement de la
Membrane vers `enforce` reste une opération séparée. Il doit précéder le Run
comportemental lui-même : le runtime refuse aussi la simulation et l'action en
mode `compat` ou `shadow`, indépendamment du gate de rollout.

Après le passage explicite à `enforce`, ouvrir la fenêtre de preuve. Cette
commande active l'accès au seul System marqué pendant deux heures au maximum,
sur le SHA courant. Elle écrit un audit avec `claim_promoted = false` : ce
n'est ni une activation, ni une preuve comportementale.

```bash
python -m scripts.rollout_value_loop open-canary \
  --workspace-id "$WORKSPACE_ID"
python -m scripts.rollout_value_loop open-canary \
  --workspace-id "$WORKSPACE_ID" --apply --actor "$OPERATOR"
```

Le canari Playwright choisit une valeur bornée réellement différente de la
policy courante, l'applique, puis déclenche un vrai Run après l'action. Ce Run
doit porter le snapshot serveur exact du ControlPolicy effectivement exécuté.
Le canari relit ce ControlPolicy après l'action et effectue l'approbation depuis
l'interface Steer. La mesure doit ensuite référencer la simulation approuvée,
conserver son `forecast_delta` et une évaluation d'hypothèses dont la causalité
reste `not_established`.

À l'ouverture de la fenêtre, le rollout fige une racine content-addressée du
`ControlPolicy`. Chaque `Act` autorisé ajoute une transition append-only
`from → to` liée à l'action et au scénario. L'activation réutilise cette chaîne
et le gate exige que sa pointe soit exactement l'état courant de la policy.
Une écriture externe, une transition manquante ou une valeur modifiée sans
action referme donc le gate ; une actuation normale le garde ouvert.
Une valeur opérateur écrite par le canari lui-même ou un Run dont la provenance
ne correspond pas ne peut jamais devenir une mesure. Si aucun Run indépendant
ne satisfait le contrat, l'observation porte `not_promotable` et ne peut jamais
déclarer `behavior_verified`. Son JSON ne contient aucun identifiant de
workspace, System, Run ou record : uniquement leurs SHA-256.

Le collecteur local valide le format et produit volontairement un résultat
non promotable, sans identifiant brut :

```bash
python -m scripts.collect_value_loop_evidence \
  --mode local \
  --workspace-id "$WORKSPACE_ID" \
  --observation /path/to/lot8-observation.json \
  --junit /path/to/playwright-junit.xml \
  --output /path/to/lot8-local-collection.json
```

Le mode protégé est accepté seulement dans un job CI protégé dont l'identité
GitLab OIDC est vérifiée contre l'issuer, le projet et la ref configurés, et
dont `CI_COMMIT_SHA` est exactement le SHA du runtime. L'observation doit
provenir du même pipeline et du même job. Le collecteur résout les hashes via
la base serveur, vérifie la fenêtre, les cinq records, les audits, les reçus
idempotents, le vrai Run post-action et le digest du JUnit Playwright original,
puis écrit en mode `0600` le contrat d'activation v3. Il contient les objets
fermés `trusted_runner` et `source_junit`, ce dernier étant relié au
`source_junit_ref` du runner artifact canonique. Ce fichier protégé
contient les identifiants autoritaires et ne doit pas être publié comme artefact
Playwright.

```bash
python -m scripts.collect_value_loop_evidence \
  --mode protected \
  --validated-by "$CI_JOB_URL" \
  --workspace-id "$WORKSPACE_ID" \
  --observation /path/to/lot8-observation.json \
  --junit /path/to/playwright-junit.xml \
  --output /secure/lot8-activation-evidence.json
```

Activer ensuite avec le contrat collecté :

```bash
python -m scripts.rollout_value_loop activate \
  --workspace-id "$WORKSPACE_ID" --evidence /secure/lot8-activation-evidence.json
python -m scripts.rollout_value_loop activate \
  --workspace-id "$WORKSPACE_ID" --evidence /secure/lot8-activation-evidence.json \
  --apply --actor "$OPERATOR"
```

L'activation exige une preuve fraîche qui relie le workspace, le System et le
SHA exact aux cinq enregistrements persistés de la boucle. L'apply ne peut être
effectué que depuis le même job GitLab OIDC protégé que celui inscrit dans la
preuve ; un replay local ou depuis un autre pipeline/job est rejeté. Le JUnit
canonique embarqué et adressé par SHA-256, lui-même lié au digest du JUnit
Playwright original, doit prouver exactement : création, simulation,
approbation, action, mesure, idempotence, isolation tenant et séparation entre
simulation et mesure. Le script confronte ensuite les identifiants aux lignes
autoritaires, aux reçus idempotents et à l'état `measured` avant d'activer le
flag dans la même transaction que la preuve réduite et l'audit.

L'observation brute et son JUnit ne sont pas stockés dans les settings. Seuls
leurs digests, les identifiants de records résolus côté serveur, le SHA, les
résultats booléens et les métadonnées de validation non sensibles sont
conservés. L'activation ferme atomiquement la fenêtre de canari.

Le flag `features.value_loop_v1` appartient exclusivement à ce rollout : le
PATCH générique des settings Workspace ne peut ni l'activer ni le désactiver.
Le gate runtime confronte en plus la dernière activation réduite au System
canari unique et au SHA complet du runtime courant. Un nouveau déploiement sans
preuve correspondante referme donc automatiquement la boucle, même si le booléen
persisté était encore actif. Il confronte également le snapshot racine et la
chaîne des transitions autorisées au digest du `ControlPolicy` courant.

## Rollback

```bash
python -m scripts.rollout_value_loop deactivate \
  --workspace-id "$WORKSPACE_ID" --apply --actor "$OPERATOR"
```

Cette commande désactive `features.value_loop_v1` et ferme toute fenêtre de
canari. Elle conserve
le marqueur, la configuration de l'actuator, l'allow-list Membrane, les
scénarios, simulations, actions, mesures et preuves historiques. Les
migrations additives restent en place.

Le rollout est démontré statiquement et par tests locaux tant qu'aucune preuve
issue de l'environnement déployé n'a été acceptée ; cela ne vaut pas statut
`deployed_verified` ou `behavior_verified`.
