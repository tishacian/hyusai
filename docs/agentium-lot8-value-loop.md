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

La boucle est disponible seulement lorsque les trois conditions suivantes sont
simultanément vraies :

1. le workspace porte `features.value_loop_v1 = true` ;
2. exactement un `System` porte
   `settings.experience.value_loop_canary = "v1"` ;
3. le `System` demandé est ce sujet marqué.

La découverte ne lit ni slug, ni nom métier, ni identifiant codé en dur. Le
seed Showcase prépare le marqueur, le modèle de steering, l’actuator borné et
l’action Membrane, mais laisse le flag à `false`. La procédure de rollout est
décrite dans `docs/agentium-lot8-value-loop-rollout.md`.

Le gate de lecture distingue la sélection du canari de l'autorité d'exécution.
Si le flag, le marqueur unique et l'attestation de rollout sélectionnent encore
le System mais que l'actuator ou sa Membrane dérive, Steer conserve les blocs
`value-loop` et `value-actuator`; les faits de ce dernier passent à
`not_configured`. Les endpoints mutatifs, eux, restent fermés.

L'attestation lie aussi le digest exact du `ControlPolicy` effectif. Toute
modification extérieure à la boucle referme immédiatement l'autorité
d'exécution. Un `Act` autorisé est le seul mouvement accepté : il ajoute, dans
la même transaction que l'action et son audit, une transition append-only du
digest précédent vers le nouveau. L'historique distingue ainsi une actuation
gouvernée d'une dérive de configuration sans rendre mutable le snapshot
d'activation.

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
L’action applique exactement le patch approuvé, sous verrou transactionnel, et
écrit l’audit dans la même transaction.

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

Hypervisor agrège les scénarios du Portfolio via
`GET /api/v1/hypervisor/value-loop`. Il ne mélange pas les tenants et ne présente
jamais une projection simulée comme une valeur observée. Sa section Portfolio
sépare explicitement les outcomes mesurés, les risques issus d'états persistés,
les arbitrages/`Decision` et les scénarios. Quand la boucle reste sélectionnée
mais que son autorité d'action a dérivé, l'historique demeure lisible avec un
`actuator_state = not_configured` ; il n'est ni supprimé ni réinterprété.

## Rollout et rollback

L’ordre d’activation est :

1. appliquer les migrations additives `068_value_loop_core` et
   `072_value_measurement_eval` ;
2. préparer le seul canari marqué, flag encore désactivé ;
3. passer explicitement la Membrane v2 du canari en `enforce` ; le runtime
   refuse simulation et action avant cette étape ;
4. ouvrir la fenêtre de canari auditée, limitée à deux heures et liée au SHA ;
5. exécuter un scénario réel, déclencher un vrai Run post-action et aller
   jusqu’à `measure`, plus les rejouements d’idempotence ;
6. collecter l’observation Playwright expurgée et le JUnit côté serveur, puis
   les confronter aux lignes persistées ;
7. activer atomiquement `value_loop_v1`, ce qui ferme la fenêtre de canari ;
8. lancer les non-régressions.

Le rollback désactive d’abord le flag. Les scénarios, décisions, simulations,
actions, mesures et audits restent append-only afin de préserver l’historique.
La migration reste en place.

## Hors portée

- aucun actuator générique ou décoratif ;
- aucune activation Andritz pendant cette tranche ;
- aucune promotion globale par rôle ou par slug ;
- aucun marketplace, billing ou changement de lifecycle Workspace App ;
- aucune réouverture de P4.
