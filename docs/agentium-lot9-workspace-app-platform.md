# Agentium Lot 9 — Workspace App Platform

Ce document décrit la lifecycle autoritaire des Workspace Apps construite après
P4, System 360 et la boucle de valeur. Il ne transforme pas les observations
locales en preuve d’environnement : toute promotion reste liée au SHA, aux
artefacts runner et aux digests réellement activés.

## Manifeste versionné et adressé par contenu

Le registry backend compile des manifestes immuables. Une application est
sélectionnée par le triplet exact :

`app_id + version SemVer + manifest_digest SHA-256`

Le manifeste contient :

- identité, compatibilité Agentium/Blueprint/plateforme ;
- routes, surfaces et préfixes API ;
- namespace de branding ;
- action packs ;
- clés d’entitlement ;
- contrat de configuration fermé et valeurs par défaut ;
- prérequis de migration de plateforme et backfill applicatif explicite.

Pour les applications intégrées actuelles, ces prérequis sont maintenant
consommés comme une chaîne ordonnée et adressée par contenu. Les migrations de
plateforme `069` et `073` sont des préconditions vérifiées par un exécuteur
fermé ; le backfill initial appartient à la phase séparée `legacy_adoption`.
Chaque étape produit un reçu transactionnel. Le système ne prétend pas lancer
un runner arbitraire ni une migration métier opaque : un nouvel exécuteur doit
être codé, enregistré et testé avant qu'un manifeste puisse le référencer.

Le backend n’accepte jamais un manifeste arbitraire envoyé par un workspace.
Une configuration inconnue, incomplète, non canonique ou croisant les profils
Sentinel/Octocity échoue fermé.

Les clés d’entitlement ne sont plus une enum de schéma à étendre à chaque app.
Le fichier de migration additif `070_workspace_app_entitlement_registry`
(révision Alembic `070_app_entitlement_registry`) conserve les quatre clés
historiques et remplace leur liste DB par un format canonique. En
mode plateforme, une mutation de grants n’accepte toutefois que les clés des
manifestes effectivement installés dans le workspace ; gate off, le contrat
historique à quatre clés reste inchangé. Tout futur manifeste qui introduit
une clé hors de ce socle doit déclarer explicitement la dépendance de plateforme
`workspace_app_platform.entitlement_registry.070`.

Le lockfile versionné
`config/agentium/workspace-app-manifests.v1.json` contient le digest exact de
chaque couple `app_id@version` intégré. Il est vérifié au chargement du registry :
modifier le contenu d’une version publiée, ajouter une entrée non verrouillée ou
retirer une entrée bloque le démarrage et impose une nouvelle version SemVer.

Les références intégrées sont :

- `andritz.chat` ;
- `andritz.client360-pdr` ;
- `andritz.knowledge-capture` ;
- `mission-room.extension` ;
- `sentinel.mission-room` ;
- `octocity.mission-room`.

Andritz conserve exactement ses trois applications historiques. La surface FSE
Reports, sa route `/knowledge/interventions`, son entitlement `fse-reports` et
ses APIs existantes appartiennent au manifeste `andritz.knowledge-capture` ;
elles ne créent pas une quatrième application dans le shell.

Sentinel et Octocity possèdent des namespaces de branding, assistants et action
packs distincts. Aucun terme de l’un n’entre dans le manifeste de l’autre.
Le catalogue de gouvernance est filtré par famille et profil structurés du
workspace : le registry interne reste global, mais un admin ne voit que les
manifestes installables dans son propre contexte.

`mission-room.extension@1.2.0` est la première version générique qui déclare un
provider runtime. Il projette exclusivement les objets canoniques du workspace
(Systems, Runs, Decisions, audits et calendrier) et expose des états vides
explicites lorsque les données ne sont pas configurées ou mesurées. Son contrat
énumère les couples méthode/endpoint core autorisés. Le préfixe partagé ne lui
donne donc aucun accès aux routes spécialisées de Sentinel ou Octocity
(sécurité, satellite, documents, maritime et webcams). Les versions 1.0/1.1
restent installables mais provider-less ; une installation existante doit
passer par l’upgrade lifecycle explicite, jamais par une réécriture du backfill.
Les lectures core et les brouillons commitent leur audit avant de répondre ; un
échec de persistance rollback la session. Un brouillon reste toujours
`sent=false` et `requires_validation=true`.

## Lifecycle transactionnelle

Trois tables additives portent l’autorité :

- `workspace_app_installations` : état courant, version, digest, configuration
  et révision par workspace ;
- `workspace_app_operations` : reçus immuables et idempotents des transitions.
- `workspace_app_lifecycle_step_receipts` : résultat ordonné de chaque
  exécuteur fermé, digest de l'étape, preuve et sémantique de réversibilité.

Les opérations sont `install`, `upgrade`, `rollback` et `uninstall`. Le client
demande d’abord un plan en lecture seule, puis applique exactement son
`plan_sha256`. L’apply reprend un verrou tenant, reconstruit le plan, vérifie le
digest, revalide puis exécute chaque étape via le registry fermé, revendique une
clé d’idempotence locale au workspace et écrit installation, opération, reçus
d'étapes et audit dans la même transaction. Un échec d'exécuteur ou d'audit
annule l'ensemble ; aucun reçu partiel ne subsiste.

Un install normal contient uniquement les étapes du manifeste cible. Upgrade
et rollback ordonnent les étapes `source` puis `target`; uninstall consomme les
étapes `source`. Le plan et l'opération lient le `steps_sha256`. Chaque
transition déclare une compensation déterministe : rollback transactionnel
avant commit, puis opération inverse exacte après commit. Les migrations
additives persistantes déclarent explicitement qu'elles ne sont pas compensées
par une suppression de schéma.

Un rollback n’accepte qu’une version et une configuration déjà observées dans
l’historique de cette installation. Un uninstall doit reconnaître le digest
exact actuellement installé. Il n’existe aucun fallback vers une version
`latest` ni vers un document opaque.

La lifecycle vérifie également la famille et le profil structurels, les groupes
exclusifs, le chevauchement des routes et la compatibilité du shell. Mission
Room générique, Sentinel et Octocity se partagent le groupe exclusif
`mission-room.primary` et ne peuvent donc jamais coexister dans un workspace.

Cette lifecycle ne modifie ni `workspace.settings`, ni les entitlements des
membres. Ces deux contrats restent des frontières séparées.

Une activation runtime fige aussi la lifecycle. Tant que
`workspace_app_platform_v1=true`, tout nouveau plan ou apply
install/upgrade/rollback/uninstall échoue avec `runtime_authority_active` ; seul
le replay strictement idempotent d'un reçu existant reste permis puisqu'il ne
mute aucun état. La séquence opératoire obligatoire est :

`deactivate → lifecycle ou Blueprint → preflight → probation → finalize`

Cette séparation empêche une version, un digest ou une application ajoutée
après le canari de bénéficier silencieusement de l'autorité déjà activée.

## API de gouvernance

Les routes sont séparées de l’ancien endpoint `/workspaces/{slug}/apps` :

| Méthode | Route | Usage |
|---|---|---|
| `GET` | `/api/v1/governance/workspace-apps/manifests` | Registry autoritaire |
| `GET` | `/api/v1/governance/workspace-apps/installations` | État du workspace courant |
| `POST` | `/api/v1/governance/workspace-apps/plan` | Plan déterministe en lecture seule |
| `POST` | `/api/v1/governance/workspace-apps/apply` | Application du plan exact |

Elles sont réservées aux admins/owners du workspace. L’apply reprend le verrou
workspace avant de relire le membership, dérive l’acteur du sujet authentifié
et exige `Idempotency-Key`, digest de manifeste et digest de plan. Les erreurs
404/409/422 ont des codes stables sans révéler un autre tenant.

La surface frontend de Govern suit le même protocole plan/apply. Une clé
d’idempotence reste stable lors d’un retry et toute réponse d’un ancien epoch
workspace est rejetée. Le plan expose la phase, la chaîne et son digest ; la
réponse apply expose des reçus d'étapes expurgés de leurs identifiants internes.
L'API publique reste volontairement en phase `normal` : `legacy_adoption` est
réservée au CLI de backfill avec sélection explicite.

## Blueprint v2

`experience.contract_version = 2` transporte une section
`experience.workspace_apps` autoritaire et triée. Chaque installation contient
exactement :

- `app_id` ;
- `version` ;
- `manifest_digest` ;
- `config` canonique.

Les reçus d’opération et les entitlements sont exclus. L’import confronte chaque
entrée au registry compilé, planifie les install/upgrade/rollback/uninstall et
applique toutes les transitions dans la transaction globale du Blueprint. Un
conflit sur une application annule l’import entier.

La compatibilité des apps est calculée contre l’expérience prospective du
Blueprint, pas contre un état intermédiaire de la cible. À l’apply, la famille
et le profil validés sont établis sous le verrou workspace avant la lifecycle ;
une erreur ultérieure annule à la fois l’expérience et toutes les transitions
d’apps.

Un Blueprint v2 avec `experience.contract_version = 1` reste lisible et
préserve les installations de la cible. Cela permet de relire les exports
antérieurs sans leur donner une autorité qu’ils ne déclaraient pas.

Les Contexts et Systems portent chacun une clé Blueprint opaque et stable.
L’export transporte ces clés, les liaisons `context_key`/`system_key` dans les
deux sens et le `scope_key` des presets. À l’import, un nom hérité n’est adopté
que s’il désigne un objet unique ; toute ambiguïté est un conflit explicite.

## Backfill explicite

La migration Alembic `069_workspace_app_lifecycle` crée uniquement le schéma
initial. Elle ne déduit aucune installation et ne touche aucun entitlement.
La migration additive `073_workspace_app_steps`, chaînée exactement après
`072_value_measurement_eval`, ajoute la chaîne de reçus. Les opérations
antérieures sont étiquetées `legacy_unorchestrated` : aucune preuve d'étape
n'est reconstruite a posteriori.

Le fichier de migration additif `070_workspace_app_entitlement_registry`
(révision Alembic `070_app_entitlement_registry`) remplace l’ancienne
énumération SQL des quatre surfaces Andritz par une contrainte de format
canonique. Il ne crée ni ne réécrit aucun grant : les mutations restent
validées contre les `entitlement_keys` des manifestes effectivement installés
dans le workspace. Le downgrade refuse de rétablir l’ancien enum tant qu’un
grant défini par manifeste existe. Le compilateur refuse en outre toute clé
hors des quatre historiques si le manifeste ne déclare pas explicitement la
migration requise `workspace_app_platform.entitlement_registry.070`.

Le backfill applicatif exige une liste de `--workspace-id`; il n’existe pas de
mode global. La détection utilise `settings.family` et les marqueurs structurés
`mission_room.enabled/profile/assistant_profile_default`, jamais slug ou nom.
Son dry-run produit un rapport adressé par contenu. L'apply repasse par la phase
`legacy_adoption`; l'exécuteur de prérequis vérifie l'ID explicite du workspace,
le digest du rapport et le `plan_sha256` de chaque installation avant toute
mutation. Un plan normal n'inclut jamais cette étape de backfill.

Dry-run :

```bash
cd backend
python -m scripts.backfill_workspace_app_installations \
  --workspace-id "$WORKSPACE_ID"
```

Apply du rapport exact :

```bash
python -m scripts.backfill_workspace_app_installations \
  --workspace-id "$WORKSPACE_ID" \
  --apply \
  --expected-analysis-sha256 "$ANALYSIS_SHA256" \
  --actor "$OPERATOR"
```

Une installation existante mais différente bloque le backfill : elle doit
passer par la lifecycle normale. Le lot entier est transactionnel. Le champ
`runner` du manifeste identifie le CLI opérateur autorisé ; il n'est ni importé
ni exécuté dynamiquement par la lifecycle.

## Autorité runtime et activation

Le backfill et la lifecycle ne peuvent pas activer l’autorité runtime. Le seul
propriétaire de `features.workspace_app_platform_v1` est :

`backend/scripts/rollout_workspace_app_platform.py`

Tant que le flag n’est pas le booléen `true`, le shell et les APIs conservent le
comportement historique. Une fois activé, le bootstrap, les portes d’entrée des
apps, Mission Room et les action packs sont dérivés exclusivement des lignes
installées résolues par leur digest. Une famille, un profil, une route, un shell
ou un digest devenu incompatible échoue fermé ; il n’existe aucun retour aux
settings legacy.

Le statut et le bootstrap ciblent toujours un ID de workspace explicite. Le
bootstrap ajoute uniquement le marqueur structurel du canari, sous verrou, sur
un workspace dont l'autorité est désactivée et dont l'ensemble installé est
déjà non vide. Il ne peut jamais activer le runtime :

```bash
cd backend
python -m scripts.rollout_workspace_app_platform status \
  --workspace-id "$WORKSPACE_ID"

python -m scripts.rollout_workspace_app_platform bootstrap \
  --workspace-id "$WORKSPACE_ID"

python -m scripts.rollout_workspace_app_platform bootstrap \
  --workspace-id "$WORKSPACE_ID" \
  --apply --actor "$OPERATOR"
```

L'activation directe est interdite. Le protocole comporte deux preuves
distinctes et une probation bornée :

1. le canari preflight restaure et atteste l'ensemble installé exact pendant
   que le gate est encore OFF ;
2. le collecteur protégé lie son observation et le digest du JUnit Playwright
   original aux lignes autoritaires ;
3. `stage` ouvre une probation et active temporairement l'autorité ;
4. le canari post-activation confronte l'expérience réellement servie, les
   routes, les action packs, le changement de workspace et la référence de
   probation ;
5. un second collecteur protégé produit la preuve finale, puis `finalize`
   transforme la probation en activation durable.

Les preuves v2 contiennent `trusted_runner`, `source_junit`, `validated_by` et
un `observation_ref` adressé par contenu. Les writes `stage` et `finalize`
exigent le même runner GitLab OIDC protégé que celui ayant produit leur preuve :
issuer, projet, ref protégée, SHA, pipeline et job sont vérifiés. `finalize`
doit en outre être exécuté par le runner déjà inscrit lors du preflight/stage ;
preflight, probation et post-canary forment ainsi une seule chaîne de confiance.
Le digest du JUnit Playwright original est lié au runner artifact canonique ;
modifier l'un ou rejouer le JSON depuis un autre job échoue fermé.

Dry-run puis stage :

```bash
python -m scripts.rollout_workspace_app_platform stage \
  --workspace-id "$WORKSPACE_ID" \
  --evidence "$LOT9_PREFLIGHT_EVIDENCE"

python -m scripts.rollout_workspace_app_platform stage \
  --workspace-id "$WORKSPACE_ID" \
  --evidence "$LOT9_PREFLIGHT_EVIDENCE" \
  --apply --actor "$OPERATOR"
```

Finalisation après le canari post-activation :

```bash
python -m scripts.rollout_workspace_app_platform finalize \
  --workspace-id "$WORKSPACE_ID" \
  --evidence "$LOT9_POSTACTIVATION_EVIDENCE"

python -m scripts.rollout_workspace_app_platform finalize \
  --workspace-id "$WORKSPACE_ID" \
  --evidence "$LOT9_POSTACTIVATION_EVIDENCE" \
  --apply --actor "$OPERATOR"
```

Le flag, l'attestation réduite et l'audit sont écrits transactionnellement.
À chaque résolution autoritaire, le runtime reconfronte cette attestation au
SHA Git complet actuellement servi, à la configuration canonique et au hash de
l'ensemble trié `{app_id, version, manifest_digest}`. Une attestation absente,
une probation expirée, un historique incohérent, un nouveau SHA ou la moindre
dérive ferme le shell, le bootstrap, les entrées d'app et les action packs. Le
frontend affiche alors un shell `workspace_app_unavailable` sans cockpit,
Mission Room ni application ; seule la console de réparation est accessible
aux admins. Le statut signale un code stable sans publier le contenu des lignes
invalides.

Si la preuve post-activation ne peut pas être finalisée, la probation est
annulée explicitement :

```bash
python -m scripts.rollout_workspace_app_platform abort \
  --workspace-id "$WORKSPACE_ID" \
  --apply --actor "$OPERATOR" --reason "$REASON"
```

Le rollback désactive uniquement l’autorité et conserve manifests, installations,
reçus, configurations et entitlements :

```bash
python -m scripts.rollout_workspace_app_platform deactivate \
  --workspace-id "$WORKSPACE_ID" \
  --apply --actor "$OPERATOR" --reason "$REASON"
```

## Supply chain par digest

`docker/compose.agentium.registry.yml` retire les builds locaux et exige trois
références complètes `@sha256` : backend, frontend et worker. Le migrate et le
service SFTP réutilisent exactement le digest backend ; les workers réutilisent
exactement le digest worker.

`scripts/agentium_release_contract.py` vérifie hors ligne :

- le SHA Git complet ;
- une occurrence de build CI par composant ;
- les références registry immuables ;
- les checksums des SBOM et provenances ;
- la vérification de signature Cosign ;
- l’issuer OIDC et l’identité certificat Cosign contre deux trust anchors
  fournis par le job, jamais contre des valeurs auto-déclarées par la release ;
- l’identité exacte entre images publiées, testées et activées.

Le script ne construit ni ne signe lui-même : le job protégé produit ces
artefacts, puis le vérificateur les confronte avant l’activation de l’overlay.
Tant que ce job n’a pas tourné sur l’environnement cible, cette partie reste
une preuve statique et ne vaut pas preuve de comportement.

## Rollback et hors portée

Le rollback applicatif utilise une version réellement enregistrée par la
lifecycle. Le rollback d’environnement réactive ensemble les trois digests de
la release précédente, puis revérifie le contrat.

Restent hors portée tant que cette lifecycle n’a pas sa preuve complète :

- marketplace ;
- billing ;
- installation de manifestes tiers arbitraires ;
- activation implicite selon un slug ;
- mutation automatique des entitlements ;
- réouverture de P4.
