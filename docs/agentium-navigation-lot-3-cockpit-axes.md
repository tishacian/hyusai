# Agentium — Lot 3 : axes du cockpit standard

Statut : implémenté derrière un feature flag, avec rollout ordonné
`agentium-showcase` puis workspace interne standard.

Références :

- `docs/mental-model.md`, §5bis ;
- `docs/agentium-navigation-lot-1-stability.md` ;
- `docs/agentium-navigation-lot-2-shadow-resolver.md` ;
- `frontend-ng/src/app/core/navigation.catalog.ts`.

## Contrat fonctionnel

La hiérarchie canonique est :

`Portfolio > Capability > System > Run > Skill`

La hiérarchie, la lens et le scope sont trois axes orthogonaux :

- une lens change la manière de lire le même objet ; elle ne change jamais son
  identifiant ;
- le mini-rail sélectionne un type d’objet sous l’ascendance courante ;
- le breadcrumb ne montre que les arêtes prouvées par les APIs canoniques du
  workspace courant ;
- l’objet sélectionné dans le path est l’autorité. Une query string ne peut ni
  le remplacer, ni lui greffer un descendant provenant d’une autre branche.

Exemples canoniques :

```text
/runs/<runId>?lens=steer&capabilityId=<capId>&systemId=<systemId>
/systems?lens=operate&scope=systems&capabilityId=<capId>
/runs?scope=runs&capabilityId=<capId>&systemId=<systemId>
/skills?lens=operate&scope=skills&capabilityId=<capId>&systemId=<systemId>&runId=<runId>
```

Les paramètres reconnus sont limités à `lens`, `scope`, `tab`, `facet`,
`focus`, `capabilityId`, `systemId`, `runId` et `skillRef`. Les autres sont
ignorés par la projection de navigation.

Quand une ascendance est active, le mini-rail n’affiche que les surfaces qui
consomment réellement ce contrat (`Capabilities`, `Systems`, `Runs`, `Skills`
et le Flow du System). Les canvases encore globaux restent accessibles depuis
leur lens, mais ne sont jamais présentés à tort comme filtrés par l’ascendance.

## Architecture

### Registry unique

`navigation.catalog.ts` est la source unique pour :

- les surfaces et leurs routes ;
- les cinq lenses ;
- les sections des rails ;
- les aliases de routes ;
- les surfaces autorisées du profil business ;
- la classification de télémétrie ;
- les destinations du resolver et de la palette.

Les consumers utilisent un `surface.id`, puis résolvent la route depuis le
registry. Les sections historiques sont conservées dans ce même registry pour
les workspaces hors canari ; il n’existe pas de seconde matrice de routes.

### Router source de vérité

`ZoomContextService` ne possède plus aucun setter d’objet. C’est une projection
read-only du Router :

1. le path désigne le leaf (`Capability`, `System`, `Run` ou `Skill`) ;
2. les APIs workspace-scoped hydratent ses parents ;
3. les réponses sont validées par slug, epoch, génération et URL ;
4. une réponse de A arrivée après un passage à B est rejetée ;
5. durant le switch, la projection devient immédiatement un Portfolio neutre,
   avant la publication atomique de B.

Règles particulières :

- un Run impose son vrai System, puis la Capability de ce System ;
- un System sélectionné dans le path ignore tout `runId` descendant en query ;
- un Skill sous un Run exige une invocation réelle de ce Skill par ce Run ; sa
  simple présence dans `System.skill_ids` ne suffit pas ;
- un objet absent ou étranger au workspace échoue fermé, sans réutiliser un
  label ou un parent précédent.

Les liens Angular portant une query string sont construits sous forme de
`UrlTree`. Cela évite que `?` soit encodé en `%3F` par `[routerLink]`.

### Rechargement atomique des vues

Les vues longues (`CapabilityView`, `SystemView`, `RunView`) et les listes
scopées (`Systems`, `Runs`, `Skills`) utilisent `WorkspaceViewContext` :

- purge synchrone au reset A → B ;
- annulation des abonnements et timers ;
- reload de B après publication de son epoch ;
- rejet des réponses tardives lors d’un changement d’ID dans le même workspace.

Le sélecteur du title bar retourne à `/`. Le `NavigationResolverService` reste
donc l’unique propriétaire de la destination après un changement de workspace.

## APIs de scope

`GET /systems` accepte `capability_id`.

`GET /runs` accepte `system_id` et `capability_id`, séparément ou ensemble. La
Capability d’un Run lié à un System est dérivée du System dans le workspace
courant. `Run.capability_id` n’est utilisé qu’en repli pour un Run sans System.
Ce contrat couvre les anciens producteurs qui n’ont pas renseigné le champ
`Run.capability_id`.

## Feature flag et rollback

Le flag est :

```json
{
  "features": {
    "cockpit_router_axes_v3": true
  }
}
```

Quand il est absent ou faux :

- `lens`, `scope` et l’ascendance en query sont inertes ;
- les rails gardent leurs sections historiques ;
- les listes restent non filtrées ;
- les liens n’émettent aucun paramètre Lot 3 ;
- le breadcrumb garde sa présentation historique.

Le seed Showcase active le flag sans écraser les autres settings ou features.
Le rollback consiste à retirer ou désactiver uniquement ce flag ; aucun rollback
de schéma ou de données n’est nécessaire. Pendant un rollback Showcase, le job
de seed doit être suspendu ou configuré pour ne pas réactiver le flag au passage
suivant ; son comportement normal force volontairement le canari à `true`.

## Rollout ordonné

1. Déployer le code avec le flag absent sur les workspaces ordinaires.
2. Rejouer le seed `agentium-showcase` afin d’activer le premier canari visible.
3. Exécuter le premier test de `10-cockpit-axes-canary.spec.ts` : graphe réel,
   lens, scopes réseau, reload et historique.
4. Uniquement après succès, lancer le second test sur `acme` (ou un autre
   workspace interne standard). Le test active temporairement le flag, crée un
   System et un Run éphémères, puis supprime le System et restaure les settings
   dans un `finally`.
5. Étendre ensuite le flag par cohortes. Sentinel/Octocity et les shells métier
   restent des non-régressions, pas des canaris du cockpit standard.

Commande de compilation du canari :

```bash
npx playwright test e2e/tests/10-cockpit-axes-canary.spec.ts --list
```

Commande live complète (credentials uniquement via environnement) :

```bash
E2E_LOT3_CANARY=1 \
E2E_LOT3_INTERNAL_CANARY=1 \
E2E_LOT3_INTERNAL_WORKSPACE_SLUG=acme \
E2E_USERNAME=... E2E_PASSWORD=... \
npx playwright test e2e/tests/10-cockpit-axes-canary.spec.ts
```

La suite est `serial` : un échec Showcase bloque le test interne. Trace et vidéo
sont désactivées pour ne jamais sérialiser le login live.

## Preuves automatisées

- matrice 3 objets × 5 lenses avec conservation du path et de l’ID ;
- routes de scope avec conservation de l’ascendance ;
- registry unique pour rails, palette, guards, resolver et télémétrie ;
- graphe réel Run → System → Capability et Skill → parent le plus profond ;
- contradiction `/systems/B?runId=R-de-A` rejetée ;
- liens `UrlTree` sans `%3F` ;
- gate inerte hors canari ;
- reset A → B et réponses tardives rejetées ;
- filtres backend, y compris `Run.capability_id = NULL` ;
- canari Playwright Showcase puis interne.
