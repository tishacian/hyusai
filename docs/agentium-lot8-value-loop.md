# Agentium Lot 8 — boucle de valeur autoritaire

Ce document décrit la tranche produit qui suit la clôture de P4 et l’extension
du graphe du Lot 7. Il ne constitue ni une attestation runner, ni une preuve
d’environnement : les niveaux formels restent calculés depuis le manifeste de
conformité et des artefacts liés au SHA.

## Contrat produit

Au niveau d’un `System`, Steer porte une seule boucle persistée :

`Outcome → Decision → Simulate → Approve → Act → Measure`

Chaque étape possède une identité, un état et une preuve distincts. Une
simulation n’est jamais une mesure et une valeur absente n’est jamais convertie
en zéro. La mesure ne clôt un scénario que lorsqu’un Run terminé et réellement
observé apporte une valeur post-action ; sinon le scénario reste `acted` avec
un état `not_measured`.

La baseline est elle aussi une mesure runtime, pas un exemple seedé ni une
valeur fournie par l'opérateur. La création d'un scénario exige un Run terminé,
éligible et porteur d'une provenance serveur
`measurement_provenance.source = runtime_auto`. Les Runs de seed, de canari ou
à provenance `operator` sont refusés, même si le client présente un reçu qui
en reproduit la forme. Pendant le canari, le navigateur déclenche donc un Run
frais ; le collecteur recharge ce Run en base, confronte sa provenance à celle
figée dans le scénario et vérifie que son exécution appartient à la fenêtre de
preuve active.

`runtime_auto` est désormais une preuve serveur, pas une valeur JSON mutable.
À la complétion, engine, DAG/agentic et chat classique écrivent dans la même
transaction le reçu embarqué et l'audit exact
`run.outcome.runtime_auto.recorded`. Ils lient Run, workspace, System,
ControlPolicy réellement exécuté, `flow_sha256`, `runtime_revision`, acteur,
horodatage et hash contextualisé de la valeur. La lecture recharge l'audit et
les autorités courantes ; un Run legacy, un audit absent ou transplanté, ou
une dérive d'un seul champ rend la provenance indisponible. Un échec d'écriture
de l'audit annule la complétion du Run.

Un Outcome saisi par un opérateur peut en revanche devenir une mesure
post-action uniquement après l'écriture autoritaire d'un reçu v2. L'endpoint
verrouille le Run, écrit dans la même transaction la valeur, le reçu embarqué et
l'`AuditLog` tenant-scopé exact
`run.outcome.operator_override.recorded`, puis rollback l'ensemble si le
`flush` ou le commit d'audit échoue. Le reçu expose `audit_id` et
`artifact_ref`, sans recopier la valeur ni la note. Leurs SHA-256 sont
contextualisés par `audit_id + run_id + field`, ce qui empêche de transplanter
un hash entre Runs ou reçus.

La lecture de provenance exige une session DB et recharge l'audit par
`audit_id + workspace_id`. Elle confronte version, acteur, timestamp, détails
fermés, digest du reçu et hashes de la valeur/note actuellement persistées. Un
audit absent, étranger au tenant, modifié ou un reçu embarqué altéré rend la
provenance indisponible et la mesure échoue fermée. Cette autorité post-action
ne change jamais la règle de baseline : toute provenance opérateur y reste
refusée, même avec un reçu v2 valide.

Une `ValueMeasurement` référence explicitement la simulation approuvée et
conserve deux écarts distincts : `delta` compare la mesure à la baseline,
tandis que `forecast_delta` compare la mesure au forecast. Elle persiste aussi
un verdict directionnel sur les hypothèses (`confirmed`,
`partially_confirmed`, `not_confirmed` ou `not_evaluable`) et ses critères.
Ce verdict indique si les seuils projetés sont atteints ; il ne prétend jamais
établir une causalité, qui reste explicitement `not_established`.

Le premier actuator est volontairement borné :
`control_policy.guardrails.patch.v1`. Il n’existe que si le `System` déclare
explicitement sa configuration d’actuation et si sa Membrane v2 en mode
`enforce` autorise la même action. Sans actuator réel, Steer expose
`not_configured` et l’API refuse l’action.

## Gate structurel

La boucle est disponible seulement lorsque le workspace porte
`features.value_loop_v1 = true` et que le `System` demandé possède sa propre
activation autoritaire, encore valide pour le SHA et les ancres OIDC courants.
Avant cette activation, un seul `System` à la fois peut être sélectionné pour
la preuve : il porte `settings.experience.value_loop_canary = "v1"` et possède
l'unique fenêtre de preuve ouverte du workspace.

La découverte ne lit ni slug, ni nom métier, ni identifiant codé en dur. Le
marqueur n'est pas une licence d'exécution durable : il désigne seulement la
prochaine cible `prepare/proof`, puis peut être déplacé vers un autre System
sans invalider les activations déjà attestées. Le seed Showcase prépare le
marqueur, le modèle de steering, l’actuator borné et l’action Membrane, mais
laisse le flag à `false`. La procédure de rollout est décrite dans
`docs/agentium-lot8-value-loop-rollout.md`.

Le gate de lecture distingue la sélection temporaire du canari de l'autorité
d'exécution par System. Si le flag et une activation valide sélectionnent encore
le System mais que l'actuator ou sa Membrane dérive, Steer conserve les blocs
`value-loop` et `value-actuator`; les faits de ce dernier passent à
`not_configured`. Les endpoints mutatifs, eux, restent fermés.

L'attestation lie aussi le digest exact du `ControlPolicy` effectif. Toute
modification extérieure à la boucle referme immédiatement l'autorité
d'exécution. Un `Act` autorisé est le seul mouvement accepté : il ajoute, dans
la même transaction que l'action et son audit, une transition append-only du
digest précédent vers le nouveau. L'historique distingue ainsi une actuation
gouvernée d'une dérive de configuration sans rendre mutable le snapshot
d'activation. Cette transition référence aussi l'`audit_id` et le
`request_sha256` exacts de l'action ; le gate recharge l'ActionExecution,
l'audit, l'acteur, le scénario, la Decision, l'instant et les états de policy
avant/après. Un objet seulement bien formé ne peut donc pas autoriser la suite.

Le runtime ne fait confiance ni à la forme du résumé d'activation, ni à son
seul `audit_id`. Il recharge les cinq records autoritaires et leurs liens,
reconfronte le reçu `lot8.value_loop.activated` à l'intégralité des détails
attendus, puis revalide l'issuer, le projet et la ref du runner contre les
ancres OIDC courantes. La fenêtre de canari possède elle aussi son reçu serveur
exact. Un audit absent ou altéré, une identité runner devenue non fiable ou un
record transplanté ferme le gate.

## API System-scopée

Toutes les routes sont sous
`/api/v1/systems/{system_id}/value-loop` et restent tenant-scopées par le
workspace courant :

| Opération | Route | Action d’autorisation |
|---|---|---|
| Lire la boucle | `GET /` | `value_scenario.read` |
| Créer un scénario | `POST /scenarios` | `value_scenario.create` |
| Simuler | `POST /scenarios/{scenario_id}/simulate` | `value_scenario.simulate` |
| Approuver | `POST /scenarios/{scenario_id}/approve` | `value_scenario.approve` |
| Agir | `POST /scenarios/{scenario_id}/act` | `value_scenario.act` |
| Mesurer | `POST /scenarios/{scenario_id}/measure` | `value_scenario.measure` |

Chaque mutation exige `Idempotency-Key`. La clé est unique dans le workspace,
le hash de requête est vérifié et un rejeu identique retrouve le même résultat.
Une même clé réutilisée avec un autre payload échoue fermé.

Pour une nouvelle commande, le service verrouille et rafraîchit l'autorité dans
l'ordre unique `Workspace → System → ControlPolicy → ValueScenario`, avec
`populate_existing` sur les lignes autoritaires. Il revalide ensuite le gate
runtime complet, la Membrane, les bornes de l'actuator, son binding et le
snapshot de policy avant tout reçu d'idempotence ou effet métier. Une commande
qui attend un verrou ne peut donc pas poursuivre sur une identité ORM périmée.
Seul le rejeu strict d'un reçu déjà terminé reste disponible après une
suppression ultérieure d'autorité ; il ne réexécute aucun effet.

La requête de simulation ne peut pas fournir de modèle, de valeur projetée, de
provenance ou de confiance. Le serveur les dérive de la configuration versionnée
du `System`; le client ne propose qu’un patch borné. Le modèle déclare, pour
chaque champ d’actuator, des intervalles explicites et leurs multiplicateurs de
coût et de valeur. Chaque valeur du patch doit correspondre à exactement un
intervalle. Le patch canonique, son SHA-256 et l’intervalle retenu sont inscrits
dans les hypothèses et la provenance. Un champ sans modèle, hors bornes ou dans
des bornes ambiguës produit `SIMULATION_NOT_CONFIGURED` et aucune ligne de
simulation. Les anciens multiplicateurs génériques ne sont jamais utilisés en
fallback.

Deux patchs opposés produisent donc deux forecasts distincts. La projection
Steer n’invente plus de forecast à partir du seul modèle : elle affiche
uniquement une `ValueSimulation` réellement persistée, sinon `not_configured`.
À l'approbation, le serveur persiste le snapshot canonique complet de cette
simulation et son `approved_simulation_content_sha256` : modèle, hypothèses,
projection, action recommandée, provenance et confiance. L’action recalcule ce
contrat et échoue fermé si le moindre champ a changé ; les approbations legacy
sans pin restent inactives. Le frontend ne propose une baseline que si le
backend publie explicitement `baseline_eligible=true` et aucune raison
d'inéligibilité. L’action applique exactement le patch approuvé, sous verrou
transactionnel, et écrit l’audit dans la même transaction.

Les endpoints génériques de Decision refusent toute Decision liée à un scénario
de valeur. Cela empêche de contourner `simulate → approve → act` par une route
historique.

## Projections et interfaces

Dans la lens Steer de System 360, le projecteur ajoute :

- un bloc `value-loop` issu des scénarios, simulations, actions et mesures
  persistés ;
- un bloc `value-actuator` qui indique si l’actuator réel est configuré ;
- les états explicites `available`, `not_measured`, `not_configured`,
  `restricted` ou `unavailable`.

Gate off, la forme historique du payload reste inchangée.

Le composant Steer utilise la même route objet, le même header et les mêmes
facettes. Il guide l’utilisateur dans l’ordre autoritaire, retient la même clé
d’idempotence lors d’un retry et rejette toute réponse tardive provenant d’un
ancien epoch de workspace ou d’un autre `System`.

Le contrôle d'actuation Steer n'est rendu disponible que si le backend compose
le contrat complet `value_loop_enabled`; un actuator structurellement valide
mais dont le rollout, l'autorisation, la Membrane ou la policy ont dérivé reste
`not_configured` avec une raison explicite. Le titre et la progression affichent
les six étapes, sans raccourcir Outcome ou Decision.

Hypervisor agrège les scénarios du Portfolio via
`GET /api/v1/hypervisor/value-loop`. Il ne mélange pas les tenants et ne présente
jamais une projection simulée comme une valeur observée. Sa section Portfolio
sépare explicitement les outcomes mesurés, les risques issus d'états persistés,
les arbitrages/`Decision` et les scénarios. Quand la boucle reste sélectionnée
mais que son autorité d'action a dérivé, l'historique demeure lisible avec un
`actuator_state = not_configured` ; il n'est ni supprimé ni réinterprété.
Le compteur de Capabilities provient des Capabilities visibles et de leur
agrégat propre ; `runs_count` ne sert jamais de substitut.

## Rollout et rollback

L’ordre d’activation est :

1. appliquer les migrations additives `068_value_loop_core` et
   `072_value_measurement_eval`, puis `074_relational_integrity`,
   `075_simulation_approval_pin` et `076_decision_scenario_lineage` ;
2. préparer le seul canari marqué, flag encore désactivé ;
3. passer explicitement la Membrane v2 du canari en `enforce` ; le runtime
   refuse simulation et action avant cette étape ;
4. ouvrir la fenêtre de canari auditée, limitée à deux heures et liée au SHA ;
5. déclencher dans la fenêtre un Run baseline frais avec provenance
   `runtime_auto`, exécuter un scénario réel, déclencher un vrai Run
   post-action et aller jusqu’à `measure`, plus les rejouements
   d’idempotence ;
6. collecter l’observation Playwright expurgée et le JUnit côté serveur, puis
   les confronter aux lignes persistées ;
7. activer atomiquement `value_loop_v1`, ce qui ferme la fenêtre de canari ;
8. lancer les non-régressions.

Le rollback désactive d’abord le flag. Les scénarios, décisions, simulations,
actions, mesures et audits restent append-only afin de préserver l’historique.
La migration reste en place.

La révision `074_relational_integrity` effectue un preflight exhaustif avant
tout DDL et refuse l'upgrade si une relation historique dérive. Elle ajoute les
clés candidates tenant-first et les foreign keys composites qui lient chaque
scénario, simulation, action, mesure, Run et ControlPolicy au même workspace,
System et lignage. La sélection cyclique de la simulation approuvée est
différée au commit ; la migration ne répare et ne devine aucune identité.

La révision `075_simulation_approval_pin` ajoute un snapshot et un digest
nullables sans fabriquer de preuve pour les approbations historiques ; son
downgrade refuse de supprimer les colonnes tant qu'un pin existe. La
révision `076_decision_scenario_lineage` remplace le lien simple de Decision
par une foreign key composite
`workspace_id + scenario_id + target_id → workspace_id + id + system_id`,
ajoute un CHECK anti-NULL et refuse mutation, transplantation ou suppression
du scénario autoritaire. Ses preflight et downgrade échouent avant DDL lorsqu'un
lignage ou une autorité active ne peut pas être prouvé.

Le seed Showcase suit la même discipline append-only. Toute réconciliation
effective de policy, Context ou settings System crée une nouvelle
`SystemVersion` avec une transition `showcase_seed_reconcile` et un audit qui
n'expose que les noms de champs modifiés. Il utilise `purge=False`, conserve
Runs, Decisions, audits et versions historiques, ne crée rien lors d'un second
passage sans écart et n'active aucun gate. Un workspace neuf démarre gates OFF ;
une autorité de rollout déjà présente reste la propriété de son service dédié.
Cette garantie porte sur `seed_showcase_workspace.py`, qui exige le marqueur
structurel `settings.showcase_seed=true` géré par le serveur et n'expose aucune
commande de reset. Les utilitaires de données jetables vidéo et SAP HANA
externes ne constituent ni des faits Agentium autoritaires, ni une preuve Lot 8.

## Limites de preuve actuelles

Le manifeste et la matrice ne démontrent ici que la présence cohérente du code
et des contrats de test. Restent absentes les migrations 074–076 exécutées sur une
instance PostgreSQL réelle, le job GitLab protégé et ses artefacts OCI liés au
SHA et à l'environnement, le canari Playwright authentifié, et une validation
utilisateur sans coaching. Ces absences interdisent toute promotion au-delà de
`static_verified`.

## Hors portée

- aucun actuator générique ou décoratif ;
- aucune activation Andritz pendant cette tranche ;
- aucune promotion globale par rôle ou par slug ;
- aucun marketplace, billing ou changement de lifecycle Workspace App ;
- aucune réouverture de P4.
