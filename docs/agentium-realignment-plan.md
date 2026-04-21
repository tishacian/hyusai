# Agentium — Plan de réalignement produit / implémentation

## Objet du document

Ce document consolide l'écart entre la vision produit, les maquettes et
l'implémentation actuelle d'Agentium. Il sert de référence
opérationnelle pour réaligner le vocabulaire, les contrats de contrôle,
les vues cockpit et le workflow Builder sans laisser de décisions
implicites à l'équipe d'implémentation.

Il ne remplace ni le [mental model](./mental-model.md), ni le
[deck produit](./deck-product-review.md), ni les
[mockups](./mockups). Il traduit ces sources en plan exécutable et fixe
une règle d'arbitrage claire lorsque la documentation, les maquettes et
le code ne racontent pas la même chose.

Le résultat attendu est un produit cohérent de bout en bout autour des
entités `System`, `Run` et `Decision`, d'un contrôle canonique à quatre
leviers, d'un cockpit réellement sémantique et d'un Builder conforme au
modèle produit.

## Sources de vérité et règle d'arbitrage

- [Mental model](./mental-model.md): source normative pour la
  sémantique, les primitives métier, les invariants, le vocabulaire
  partagé entre UI, API et runtime, ainsi que pour le baseline
  `✅/🟡/🔵/⚠️` de ce qui est réellement livré.
- [Deck produit](./deck-product-review.md): source normative pour
  l'intention produit, les workflows cibles et la priorisation des
  surfaces livrées.
- [Mockups](./mockups): source normative pour le langage de navigation,
  la structure cockpit et la lecture visuelle des vues coeur.

> **Règle d'arbitrage**
>
> Si le mental model et le code divergent, le code doit converger vers le
> mental model. Si le deck ou les mockups sont en retard sur une
> fonctionnalité déjà réelle et cohérente avec le mental model, la
> documentation doit être mise à jour au lieu de régresser le produit.
> Aucun nouveau développement ne doit réintroduire `agent`, `trace` ou
> `playground` dans l'UI ou dans les contrats frontend canoniques. Tant
> qu'une surface est marquée `🟡 Partial`, `🔵 Planned` ou `⚠️ Legacy`
> dans le mental model, le plan et la documentation dérivée doivent
> conserver ce niveau de vérité.

## Résumé exécutif

- Le drift principal n'est pas visuel mais sémantique: le shell cockpit
  a progressé plus vite que les concepts métier canoniques.
- Le contrôle opérateur n'est pas aligné de bout en bout sur les quatre
  leviers `resource`, `velocity`, `autonomy` et `risk_tolerance`.
- La boucle `Decision -> Adaptation -> Commit` est visible mais pas
  réellement actionnable depuis Hypervisor.
- Le zoom sémantique existe déjà comme primitive de navigation, mais il
  reste partiel: changement de route plutôt que transformation continue
  des cartes, et contexte cockpit encore hétérogène selon les vues.
- Le Builder a été simplifié au point de masquer l'étape `Skills` et de
  dériver des presets de retrieval qui ne correspondent plus à la
  taxonomie canonique.
- Le vocabulaire produit n'est pas proprement migré: des reliquats
  `agent`, `trace` et `playground` subsistent côté UI et dans certains
  contrats.
- Le nouveau mental model fixe désormais un baseline machine-checké du
  produit livré; le plan doit donc corriger les drifts réels sans
  sur-promettre la voice, les connecteurs ou les surfaces encore
  partielles.
- La couche de valeur (Outcome) n’est pas encore explicitement contractualisée dans toutes les vues; elle doit devenir une primitive obligatoire (coût, valeur, confiance, efficacité) visible et traçable de bout en bout.
- L’Hypervisor doit évoluer d’un feed de décisions vers un cockpit économique (Balance Sheet minimal + ranking des capabilities + actions d’allocation).
- Le produit doit imposer une réactivité temps réel (feedback <300ms perçu) pour matérialiser le lien cause → effet des contrôles.

## Matrice de drift

| Domaine | Spécification cible | Implémentation actuelle | Drift | Priorité |
| --- | --- | --- | --- | --- |
| Steering et 4 leviers | Pilotage canonique à 4 axes avec `risk_tolerance`, relié à des policies scoppées par `scope + target_id` | Les levers Hypervisor sont canoniques, mais Steering et les policies restent sémantiquement hétérogènes | Aligner Steering, policies et projections sur les mêmes axes et scopes canoniques | P0 |
| Hypervisor et boucle de décision | Feed de décisions actionnable avec passage direct vers un patch de policy ou de system | Feed visible mais approbation non reliée au changement effectif de policy | Fermer la boucle `Decision -> policy patch` depuis Hypervisor | P0 |
| Zoom sémantique | Primitive cockpit transversale, avec contexte préservé et représentations cohérentes par niveau | Les raccourcis existent, mais la navigation repose encore sur des changements de route et des vues peu unifiées | Fiabiliser le zoom sémantique sans créer de vue ou de route dédiée artificielle | P1 |
| Builder et étape Skills | Workflow en 6 étapes avec `Skills` explicite et presets de retrieval canoniques | Workflow simplifié, skills implicites et presets divergents | Restaurer l'étape `Skills` et la taxonomie canonique côté UI | P1 |
| Vocabulaire canonique | UI et types frontend alignés sur `System`, `Run`, `Decision` | Reliquats `agent`, `trace` et `playground` encore visibles | Purger le vocabulaire legacy des surfaces livrées et des nouveaux contrats | P0 |
| Resources / Apps / Connectors | Surface honnête sur le niveau réel de support des apps et connecteurs | Les catalogues et connecteurs ne reflètent pas toujours le statut réellement câblé du runtime | Exposer des statuts cohérents avec `catalog only`, `stub`, `bound` ou `unbound` | P2 |
| Governance | Poste d'audit crédible, détaillé et clairement borné | Surfaces surtout démonstratives, peu profondes et parfois sur-promettantes | Ajouter les capacités minimales utiles sans prétendre livrer un RBAC complet | P2 |
| Langage visuel cockpit | Grammaire cockpit homogène sur toutes les vues coeur | Mélange entre surfaces cockpit récentes et surfaces plus anciennes | Unifier les vues livrées sur la même grammaire visuelle | P1 |

## Décisions cibles

### P0 — Contrats canoniques et sémantique

- Le vocabulaire produit canonique devient `System / Run / Decision`
  dans toute l'UI, dans les types frontend et dans les nouveaux appels
  API.
- Les quatre leviers `resource`, `velocity`, `autonomy` et
  `risk_tolerance` sont obligatoires dans les projections, dans les
  simulations et dans la persistance des policies.
- Les policies ne peuvent plus être créées ou maintenues à un scope
  autre que `portfolio`, `capability` ou `system`. Toute autre
  granularité reste legacy et n'est plus émise par le frontend.
- Les alias backend legacy peuvent survivre pendant une release pour
  compatibilité, mais ils sont explicitement non canoniques et ne
  doivent plus être consommés par les nouvelles surfaces frontend.
- Le feed Hypervisor doit porter un cycle de décision complet et
  actionnable: une décision approuvée doit pouvoir déclencher depuis la
  même surface le patch de `ControlPolicy`, `AdaptivePolicy` ou `System`
  correspondant.

### P0 — Contrat Outcome / Value (nouveau)

- Chaque `Run` DOIT produire un `Outcome` canonique:
  `{ cost, value, confidence, efficiency }`.
- Chaque `Decision` DOIT référencer un `Outcome` (ou un delta d’Outcome en cas de simulation).
- L’Outcome est visible dans toutes les vues coeur: Run, System, Capability, Hypervisor.
- Aucun écran n’autorise une action sans afficher l’impact attendu (preview coût/valeur/ROI).

### P1 — Cockpit et workflows coeur

- Le zoom sémantique reste une primitive cockpit transversale, fondée
  sur un contexte explicite `Portfolio -> Capability -> System -> Run ->
  Skill`, et non une route dédiée à créer artificiellement.
- Les raccourcis `⌘Z` / `⇧⌘Z` doivent rester cohérents sur toutes les
  vues qui dépendent du contexte cockpit et préserver le contexte
  business lors du changement de niveau.
- Le Builder est restauré en six étapes:
  `Objective -> Capability -> Context -> Skills -> Policy -> Launch`.
- L'étape `Skills` redevient explicite; elle expose les unités utilisées
  par le `System` et les dépendances runtime à satisfaire avant
  lancement.
- La title bar doit consommer une télémétrie réelle. En cas
  d'indisponibilité d'une métrique, l'UI doit afficher un état neutre
  plutôt qu'une valeur fictive.
- Les presets de retrieval exposés en UI doivent s'aligner sur les modes
  réellement supportés par le runtime canonique, y compris `CHAH`
  lorsqu'il est déclaré `bound`, sans rebaptiser les moteurs internes au
  niveau produit.

### P2 — Surfaces non-GA et documentation

- La surface `Resources / Apps / Connectors` doit refléter
  explicitement la réalité du runtime: `Resources` expose ce qui est
  réellement géré côté modèles et credentials, `Apps` reste `catalog
  only` tant qu'il n'existe pas de wiring end-to-end, et aucun
  connecteur ne peut être présenté comme `GA` s'il reste `stub`.
- `Governance` doit être amélioré sur ses fonctions utiles de base
  d'audit et de lisibilité des accès, sans être présenté comme un RBAC
  complet et dynamique tant que ce backend n'existe pas.
- Le deck produit et les mockups doivent être mis à jour après
  réalignement du code, y compris sur les statuts réels de la voice, des
  connecteurs, du zoom et du Builder.

## Contrats, APIs et types à réaligner

- `ControlPlaneVector = { resource, velocity, autonomy, risk_tolerance }`
  devient le contrat canonique pour la simulation et l'application des
  policies.
- Le ciblage des policies devient
  `{ scope: 'portfolio' | 'capability' | 'system', target_id }`, avec
  `target_id` nullable uniquement pour `scope = 'portfolio'`. Aucun
  nouveau contrat frontend ne doit émettre d'autre valeur de `scope`.
- Les états de décision canoniques deviennent au minimum
  `proposed | accepted | rejected | applied` et structurent le feed
  Hypervisor ainsi que la transition `Decision -> policy patch`.
- Le payload canonique de lancement d'un `System` inclut explicitement
  `skills[]` et `retrieval_preset`, en plus des réglages de policy et de
  contexte déjà nécessaires au lancement.
- Les identifiants frontend canoniques deviennent `systemId`, `runId`
  et `decisionId`. Les identifiants legacy de type `agent_id` ou
  `trace_id` peuvent survivre côté backend pendant une release, mais
  aucun nouvel appel frontend ne doit les consommer.
- Les presets produit exposés dans l'UI sont
  `auto`, `fast`, `rich`, `HAH` et `CHAH` dès lors que le runtime les
  déclare supportés. Le mapping technique vers les moteurs internes
  reste une décision d'implémentation, mais il ne doit pas fuiter dans
  le langage produit.
- Les surfaces `Skills`, `Apps` et les connecteurs doivent réutiliser un
  vocabulaire de statut cohérent avec le mental model:
  `bound | stub | unbound | catalog only`.
- `Outcome = { cost: number, value: number, confidence: number, efficiency: number }` devient un payload canonique.
- `DecisionUnit = { decisionId, outcome, context, runId }` devient l’unité atomique de comparaison et d’agrégation.
- Les endpoints de `simulate` et `what-if` DOIVENT retourner un `Outcome` projeté.

## Plan d'exécution

1. Réaligner d'abord les contrats backend et les types partagés afin que
   `Steering`, `Hypervisor` et `Builder` travaillent tous sur les mêmes
   entités, les mêmes scopes canoniques et les mêmes statuts runtime.
2. Brancher `Steering` et `Hypervisor` sur ces contrats canoniques et livrer un flux complet de simulation, décision et application de patch actionnable depuis le cockpit, incluant systématiquement un `Outcome` projeté avant application.
2.b. Implémenter la couche Outcome dans toutes les vues coeur (Run, System, Capability, Hypervisor) avec affichage standardisé (coût, valeur, confiance, efficacité).
3. Fiabiliser ensuite le zoom sémantique, le breadcrumb continuum et les
   transitions de contexte pour qu'ils restent cohérents entre
   Portfolio, Capability, System, Run et Skill sans créer de route
   dédiée artificielle.
4. Restaurer le `Builder` avec son étape `Skills`, ses presets de
   retrieval canoniques et un payload de lancement cohérent avec les
   contrats `System`.
5. Terminer par `Governance`, `Resources` et la mise à jour documentaire
   pour rendre les surfaces partielles honnêtes et réaligner le deck
   ainsi que les mockups sur le code final.

## Critères d'acceptation

- `what-if`, `simulate` et les mutations de policies reflètent les
  quatre axes canoniques, y compris `risk_tolerance`, sans divergence de
  vocabulaire entre Hypervisor et Steering.
- Une décision peut être proposée, acceptée, rejetée puis appliquée
  depuis Hypervisor au bon `System` ou à la bonne policy, avec un état
  cohérent dans la liste et dans le détail.
- Le zoom sémantique fonctionne comme une primitive transversale
  cohérente, avec contexte conservé entre `Portfolio`, `Capability`,
  `System`, `Run` et `Skill`.
- Le `Builder` expose explicitement `Skills` et bloque le lancement si
  une dépendance ou un runtime requis manque.
- Aucune surface livrée n'expose `Playground`, `agent` ou `trace` à
  l'utilisateur final.
- La title bar n'affiche plus de métriques factices; elle reflète soit
  une télémétrie réelle, soit un état neutre explicite.
- Les surfaces `Skills`, `Apps` et les connecteurs affichent un statut
  fidèle au runtime (`bound`, `stub`, `unbound` ou `catalog only`) et
  ne se présentent pas comme pleinement supportées quand elles ne le
  sont pas.
- `Governance` n'annonce pas de capacités absentes et expose au minimum
  une expérience d'audit crédible et lisible.
- Chaque `Run` expose un `Outcome` complet (coût, valeur, confiance, efficacité) sans exception.
- Toute modification de policy via Steering ou Hypervisor affiche un `Impact Preview` (delta coût, valeur, ROI) avant application.
- Les interactions de contrôle produisent un feedback visuel en temps réel (<300ms perçu) sans rechargement de page.
- L’Hypervisor expose au minimum:
  - un agrégat valeur vs coût (Balance Sheet simplifié),
  - un ranking des capabilities par efficacité,
  - des actions directes d’allocation (scale, reduce cost, adjust thresholds).

## Extension Hypervisor — Cockpit économique minimal

- Ajouter une vue agrégée `Value vs Cost` (Balance Sheet simplifié) en tête de l’Hypervisor.
- Exposer un ranking des `Capabilities` basé sur `efficiency`.
- Permettre des actions directes depuis l’Hypervisor:
  `scale capability`, `reduce cost`, `adjust risk_tolerance`.
- Le feed de décisions reste présent mais devient subordonné au pilotage global.

## Hors périmètre

- Pas de nouveau backend connecteur dans cette passe; l'objectif est de
  réaligner la vérité produit sur l'existant avant d'étendre le
  catalogue.
- Pas de RBAC complet et dynamique dans cette passe.
- Pas de full `Focus Mode` ni de card-transformation polymorphique
  complète dans cette passe; on fiabilise d'abord le contexte et les
  transitions du zoom.
- Pas de promotion de la voice, de SharePoint ou des apps au statut
  `✅ Shipped` tant que le runtime reste `stub`, `partial` ou
  `catalog only`.

## Mise à jour documentaire après implémentation

Ce document ouvre la marche. Une fois le réalignement code livré, le
[deck produit](./deck-product-review.md) et les
[mockups](./mockups) doivent être mis à jour pour décrire le produit tel
qu'il fonctionne réellement, et non l'inverse.

- Mettre à jour le deck et les mockups sur les statuts réels de la
  voice, des connecteurs et des surfaces `catalog only` ou `stub`.
- Corriger les raccourcis, la portée et la sémantique du zoom dans le
  deck et les mockups sans inventer une vue dédiée qui n'existe pas
  dans le modèle canonique.
- Réaligner le Builder et les routes cockpit coeur dans les artefacts de
  démonstration.
- Retirer les mentions legacy encore visibles dans la documentation
  produit.

## Règle UX critique — Feedback temps réel

- Toute interaction utilisateur sur les contrôles (`resource`, `velocity`, `autonomy`, `risk_tolerance`) DOIT produire une mise à jour immédiate de:
  - coût estimé
  - valeur estimée
  - comportement système
- L’absence de feedback temps réel est considérée comme un bug produit.

## Règle produit — Outcome-first

- Aucune surface ne doit être livrée sans exposition claire de la valeur produite.
- Le produit est considéré non conforme si un utilisateur ne peut pas répondre en <5s à:
  "Combien ça coûte et combien ça rapporte ?".
