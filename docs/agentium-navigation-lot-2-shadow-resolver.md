# Agentium — Lot 2 : resolver d'expérience en shadow mode

Date du candidat local : 2026-07-15
Branche de travail : `demo/agentic`
État : implémentation locale terminée ; non committée, non poussée et non
déployée.

Ce document complète la baseline du
[`Lot 0`](./agentium-navigation-lot-0-baseline.md) et les stabilisations du
[`Lot 1`](./agentium-navigation-lot-1-stability.md). Le Lot 2 prépare un modèle
d'expérience workspace unifié sans changer l'expérience rendue ni transférer
la propriété des redirections établie au Lot 1.

## 1. Périmètre exact

Le Lot 2 doit :

1. introduire un registry déclaratif et le contrat `WorkspaceExperienceV2` ;
2. conserver des adaptateurs de compatibilité pour `business_end_user`, le
   mode legacy `portfolio`, `workspace_app_shell` et les profils Mission Room ;
3. calculer en parallèle l'expérience V2 et l'expérience legacy effectivement
   utilisée, puis les comparer sans appliquer le résultat V2 ;
4. empêcher toute activation ultérieure tant qu'une divergence non expliquée,
   une erreur ou une preuve manquante subsiste sur Andritz, Sentinel-CI ou
   Octocity.

Le Lot 2 reste un lot d'observation. Le resolver legacy demeure l'unique source
exécutée par Angular et `NavigationResolverService` conserve la propriété des
décisions de redirection.

## 2. Architecture frontend-only

Le calcul d'expérience appartient au frontend, car il dépend simultanément :

- du `WorkspaceInfo` chargé pour le membre courant ;
- du rôle et du `role_template` effectifs dans ce workspace ;
- de la preview métier stockée localement pour les admins ;
- de la route demandée et de la route finalement résolue ;
- du catalogue frontend `AGENTIUM_SURFACE_ROUTES` et des verbes du cockpit ;
- du payload Mission Room disponible seulement après l'appel API dédié.

Le backend ne doit pas héberger un second resolver de navigation ou recopier le
catalogue Angular. Il reste propriétaire des droits, du scope workspace et du
payload `/api/v1/mission-room/navigation`.

Le flux cible du shadow mode est :

```text
WorkspaceInfo + rôle + preview + route
                │
                ├── projection legacy ───────────────┐
                │                                    │
                └── registry → WorkspaceExperienceV2 ├── comparator → rapport
                                                     │
NavigationResolverService legacy ── exécution UI ────┘
```

Les rapports courants et les preuves scellées peuvent alimenter le gate en
mémoire. Ils ne pilotent ni le `Router`, ni le shell, ni le rail, ni les
surfaces métier.

## 3. Contrat `WorkspaceExperienceV2`

La projection V2 décrit une expérience effective, et non une copie brute de
`Workspace.settings` :

```ts
interface WorkspaceExperienceV2 {
  schemaVersion: 2;
  resolverVersion: 'workspace-experience-v2.shadow.1';
  workspaceSlug: string;
  scenarioKey: string;
  registryEntryIds: string[];
  shellKind:
    | 'agentium_standard'
    | 'business'
    | 'workspace_app_immersive'
    | 'workspace_focus';
  homeRoute: string;
  primarySurfaceIds: string[];
  advancedAccess: 'admin_only' | 'link' | 'hidden';
  chrome: {
    titleBar: boolean;
    sideRail: boolean;
    objectIndex: boolean;
    commandBar: boolean;
    commandPalette: boolean;
    businessHeader: boolean;
    missionRail: boolean;
  };
  workspaceApp: {
    configured: boolean;
    shell: string | null;
    profile: string | null;
    defaultView: string | null;
    immersiveRouteScope: string | null;
  };
  immersiveRouteScope: string | null;
  cockpitVerbs: string[];
  routeResolution: {
    requestedRoute: string;
    resolvedRoute: string;
    semanticQueryKeys: string[];
    workspaceTargetMatchesCurrent: boolean | null;
    semanticTargetPreserved: boolean | null;
    redirectOwner:
      | 'legacy_navigation_resolver'
      | 'workspace_experience_v2';
    redirectReason:
      | 'none'
      | 'business_profile_disallowed'
      | 'business_knowledge_compatibility'
      | 'business_system_capture_compatibility'
      | 'workspace_default_route'
      | 'workspace_settings_entrypoint';
  };
  business: {
    configured: boolean;
    active: boolean;
    admin: boolean;
    preview: boolean;
    declaredPrimarySurfaceIds: string[];
  };
  missionRoom: {
    profile: string;
    label: string;
    assistantLabel: string;
    assistantProfile: string;
    brandStyle: string;
    navigationKeys: string[];
  } | null;
  issues: Array<{
    kind: 'error' | 'unknown_adapter';
    code: string;
    path: string;
  }>;
  provenance: string[];
}
```

Le contrat est volontairement plat pour `shellKind`, `chrome`, `workspaceApp`
et `routeResolution` : il représente à la fois la projection du workspace et
la résolution du scénario observé. Les routes sont absolues et normalisées.
Les valeurs de query string et les fragments sont supprimés. La présence de
clés sémantiques issues d'une allowlist fermée est toutefois conservée dans
`routeResolution.semanticQueryKeys` ; l'implémentation n'autorise actuellement
que `systemId`, jamais sa valeur. Deux booléens présence-only prouvent en plus
que la cible `/workspace/:slug` reste le workspace courant et que le
`systemId` forwardé est bien celui de la route source, sans conserver aucun des
deux identifiants.

## 4. Registry et adaptateurs de compatibilité

Le registry compose des fragments déterministes. Deux entrées identiques
doivent toujours produire la même projection, indépendamment du slug.

### `business_end_user`

L'adaptateur conserve le comportement existant :

- profil actif pour un membre non-admin ;
- profil inactif pour un admin tant que la preview n'est pas activée ;
- home `/chat` quand le profil est actif ;
- ordre visible Recherche, Client360 PDR, Capture de connaissances ;
- accès utilitaire à `/account/**` ;
- compatibilités `/knowledge` vers `/knowledge/capture` et
  `/systems/:systemId/capture` vers la capture workspace ;
- accès avancé `admin_only` par défaut.

La projection legacy doit décrire l'UI réellement rendue. Aujourd'hui, le
header métier et les chemins autorisés restent codés en dur, même si
`primary_surfaces` est parsé depuis les settings. Comparer uniquement les deux
objets de configuration masquerait donc une divergence réelle.

L'oracle legacy possède ses propres ancres UI pour les trois liens métier, les
verbes du Side Rail et la navigation Mission Room. Il ne réutilise ni registry,
ni helper de politique, ni constante d'attente V2. Une dérive du candidat doit
donc produire une divergence au lieu de déplacer simultanément les deux côtés
du comparator.

### `portfolio`

`portfolio` est une valeur legacy persistée par le workspace Showcase mais ne
fait pas partie du type moderne `WorkspaceMode`. Son adaptateur doit conserver
le comportement observé : shell Agentium standard, home `/hypervisor` et cinq
verbes du cockpit. Il ne faut pas propager `portfolio` comme nouveau mode
canonique.

### `workspace_app_shell`

La valeur `immersive` n'est pas globale. Elle ne devient effective que lorsque :

- le workspace est en mode `demo` ;
- la route finale appartient à `/hypervisor/mission-room/**` ;
- `workspace_app_shell` vaut exactement `immersive`.

Sur `/systems`, `/workspace/**` ou toute autre surface Agentium, le shell reste
standard. La route `/workspace/:slug/chat` conserve son shell focus générique,
indépendant de la Mission Room.

### Profils Mission Room

Les profils enrichissent l'expérience workspace app sans reprendre la
résolution métier du backend :

- le profil gouvernemental peut être dérivé de
  `demo_profile=government_mission_room` lorsque `mission_room.profile` est
  absent ; son fallback de marque est `sentinel`, comme l'UI actuelle ;
- Octocity utilise explicitement `octocity_institutional_v1` et
  `demo_profile=octocity_mission_room` ;
- assistant, profil assistant, style de marque et clés de navigation sont
  comparés après chargement du payload Mission Room ;
- aucune sélection d'adaptateur ne doit tester `andritz`, `sentinel-ci` ou
  `octocity-mission-room`.

Les slugs sont autorisés uniquement dans la liste bornée des workspaces de
référence du gate. Ils n'influencent jamais le calcul d'expérience.

### Ordre de composition

L'ordre doit reproduire les précédences actuelles :

```text
business_end_user actif
  > workspace app / Mission Room
  > portfolio legacy
  > expérience Agentium standard
```

Un admin sans preview ne prend pas la branche métier. Une configuration
`workspace_app_shell=immersive` sans mode `demo` reste standard. Ces cas de
chevauchement doivent être couverts explicitement.

## 5. Projection attendue par scénario

| Scénario | Shell effectif | Home | Surfaces ou navigation protégées |
|---|---|---|---|
| Andritz, membre sans preview | `business` | `/chat` | `chat`, `client360-pdr`, `knowledge-capture` |
| Andritz, admin avec preview | `business` | `/chat` | mêmes trois surfaces, dans le même ordre |
| Andritz, admin sans preview | `agentium_standard` | `/hypervisor` | verbes `build`, `operate`, `govern` en mode builder |
| Showcase, mode `portfolio` | `agentium_standard` | `/hypervisor` | cinq verbes Agentium |
| Sentinel-CI, route Mission Room | `workspace_app_immersive` | `/hypervisor/mission-room/cockpit` | AYA et sept clés Mission Room |
| Sentinel-CI, `/systems` | `agentium_standard` | inchangée | cockpit Agentium standard |
| Octocity, route Mission Room | `workspace_app_immersive` | `/hypervisor/mission-room/cockpit` | OCTAVE et sept clés Mission Room |
| Octocity, `/systems` | `agentium_standard` | inchangée | cockpit Agentium standard |

L'ordre des sept clés Mission Room est contractuel :

```text
cockpit → strategie → securite → reputation → agenda → presse → decisions
```

Pour Octocity, les variants et bindings restent contrôlés par le backend et
les tests Mission Room existants. Le payload visible ne doit contenir aucun
identifiant Sentinel-CI ou AYA.

## 6. Shadow mode strictement passif

Le point de comparaison principal se situe dans le guard, après l'activation
éventuelle du workspace porté par un deep link. À cet instant, le rôle, la
preview et les settings utilisés par les deux projections sont cohérents.

L'ordre obligatoire est :

1. activer le workspace demandé avec le mécanisme legacy ;
2. calculer la décision legacy ;
3. calculer la projection et la décision V2 ;
4. enregistrer le rapport de comparaison en mémoire ;
5. ignorer la décision V2 ;
6. exécuter exactement le booléen ou le `UrlTree` produit par le legacy.

Le shadow resolver ne doit appeler aucune méthode de navigation et ne doit pas
modifier le workspace, la preview, les settings ou un store UI. Une erreur V2
est convertie en rapport bloquant ; elle ne casse pas la navigation legacy.

Le scope `{ workspaceSlug, epoch }` introduit au Lot 1 s'applique aussi aux
observations shadow. Le reset de contexte vide synchroniquement toute la
matière brute liée au workspace actif : dernière navigation, observations
Mission Room, déduplication des logs et rapports courants. Un calcul pour A
après une transition A vers B est abandonné et ne peut ni remplacer le rapport
de B, ni être attribué à B.

Chaque observation Mission Room brute est en plus liée au `workspace.id`, à
l'epoch et au fingerprint exact de configuration présents lors de son
acceptation. Elle est supprimée avant toute nouvelle comparaison si l'un de ces
éléments dérive ; une navigation ultérieure ne peut donc pas resceller un ancien
payload sous une recréation same-slug ou une nouvelle configuration.

`WorkspaceExperienceEvidence` est l'unité transmise au gate : versions de
schéma et de resolver, workspace, scénario, epochs, comparaison publique ou
code d'erreur. `reports` est le signal public contenant le dernier lot
d'évaluation runtime ; ce n'est ni un historique ni l'agrégateur du gate. Il
est remis à vide lors du reset de contexte. L'agrégateur multi-workspace décrit
en section 9 conserve séparément des copies scellées et privées de ces preuves.

## 7. Observation Mission Room après l'API

Le `WorkspaceInfo` initial ne suffit pas à prouver l'expérience Mission Room :
la liste visible, les variants et les `system_id` sont résolus par
`/api/v1/mission-room/navigation`.

La comparaison Mission Room est donc complétée après la réception et la mise en
place du payload API. Cette observation :

- vérifie le scope courant avant puis juste avant publication ;
- refuse un `workspace.id` ou un `workspace.slug` contradictoire lorsqu'il est
  fourni par le payload ;
- exige un objet `app`, un tableau `items`, les champs applicatifs requis et
  une clé non vide pour chaque item ; toute forme invalide devient une preuve
  bloquante ;
- conserve seulement la présence d'un objet `brand` non vide ainsi que ses
  éventuels `label` et `style` ; des types invalides sont bloquants ;
- réduit la copie en mémoire aux seuls champs comparés, sans transformer le
  payload installé dans le composant ;
- compare le profil, l'assistant, la marque et l'ordre des sept clés ;
- ne remplace jamais `navigation.items` par une projection frontend ;
- ne décide aucune route ;
- ignore toute réponse devenue obsolète après un changement de workspace.

Le profil vide de Sentinel est accepté parce qu'il fait partie du contrat API,
puis le profil sémantique et la marque retombent respectivement sur
`government_mission_room` et `sentinel`. Les doublons, clés inconnues ou ordres
différents restent visibles par le comparator au lieu d'être filtrés.

La marque comparée est celle effectivement rendue par `MissionRoomComponent` :
un objet `app.brand` non vide est autoritaire ; son `label` précède
`app.label`, et l'absence de `style` rend le thème `sentinel`. Ainsi un payload
Octocity `{ brand: { label: ... } }` ne peut pas être déclaré équivalent au
thème `agentium` attendu.

Le backend Mission Room demeure l'unique propriétaire des fallbacks de
navigation, de la liaison aux Systems actifs et de l'anonymisation Octocity.

## 8. Comparator, fingerprints et explications

Le comparator travaille en privé sur les valeurs effectives normalisées :

- ordre significatif pour les surfaces, verbes et entrées Mission Room ;
- ordre des clés d'objet non significatif ;
- routes comparées sans valeur de query string, fragment ou segment dynamique
  privé ; les seules présences de clés sémantiques autorisées et les preuves
  booléennes d'égalité de cible sont comparées ;
- defaults appliqués avant comparaison ;
- `undefined`, champ absent et chaîne vide ne sont pas rendus équivalents sans
  règle explicite.

Un rapport prend l'un des états suivants :

```text
match | explained_divergence | unexplained_divergence | error
```

L'API publique d'une divergence ne porte que `path` et `code`. Elle n'expose
jamais les valeurs legacy ou V2. Ces valeurs normalisées ne sont utilisées
qu'en interne pour dériver le fingerprint d'une sérialisation canonique de :

```text
schemaVersion + resolverVersion + workspaceSlug + scenarioKey
  + diffs bruts (path + code + valeurs legacy/V2 normalisées)
```

Une explication doit correspondre exactement au triplet workspace, scénario et
fingerprint. Elle comprend obligatoirement un `id` non vide, un propriétaire
technique (`owner`), une justification non vide et une échéance parsable
(`expiresAt`) strictement future. Il doit exister exactement une explication
pour ce triplet : zéro correspondance laisse la divergence inexpliquée et deux
correspondances ou plus rendent l'explication invalide. Les mécanismes suivants
sont interdits :

- expliquer toutes les divergences d'un workspace par son slug ;
- utiliser un wildcard de chemin ;
- ne comparer que le code de divergence ;
- conserver une explication expirée ou sans gouvernance complète ;
- considérer automatiquement toute divergence comme compatible.

Si une valeur change, le fingerprint change et l'ancienne explication ne
s'applique plus. Une explication sans correspondance exacte n'a aucun effet.

## 9. Gate de rollout fail-closed

Le gate est déterministe et exécutable localement ou en CI. Les E2E live
complètent la preuve, mais ne peuvent pas être son unique implémentation.

Les scénarios obligatoires sont au minimum :

- Andritz membre sans preview ;
- Andritz admin avec preview ;
- Andritz admin sans preview ;
- Sentinel-CI sur la home Mission Room et sur une route Agentium standard ;
- Octocity sur la home Mission Room et sur une route Agentium standard.

Le rollout reste bloqué si :

- un scénario obligatoire est absent ou dupliqué ;
- la version de schéma ou du resolver n'est pas celle attendue ;
- le calcul produit une erreur ou un adaptateur inconnu ;
- une divergence ne possède pas d'explication exacte et valide ;
- un rapport appartient à un ancien epoch workspace ;
- la preuve Mission Room post-API manque pour Sentinel-CI ou Octocity.

Le gate n'est ouvert que lorsque chaque scénario obligatoire est `match` ou
`explained_divergence`. Cet état ne déclenche aucune activation dans le Lot 2 :
il indique seulement qu'un futur lot peut demander explicitement le passage du
shadow mode au mode actif.

Le gate ne lit pas seulement le dernier rapport du workspace actif. Le service
maintient un agrégateur privé multi-workspace de preuves scellées et
dédupliquées par workspace et scénario. Une preuve runtime bloquante garde la
priorité sur une projection synthétique ultérieure. Chaque preuve est liée à un
fingerprint privé de configuration comprenant la version du resolver ainsi que
`id`, `slug`, `mode` et `settings` du `WorkspaceInfo` runtime. Ce hash et les
settings qui l'alimentent ne sont jamais exposés dans les rapports publics.

À chaque lecture du gate, une preuve scellée est rejetée si le workspace a
disparu de la liste runtime ou si son fingerprint de configuration a changé.
L'agrégateur peut ainsi réunir les preuves valides d'Andritz, Sentinel-CI et
Octocity au fil des observations, tandis que le reset de contexte supprime
intégralement les données brutes du workspace quitté. Les preuves scellées ne
survivent que tant que leur configuration exacte reste présente et inchangée.

## 10. Sécurité et confidentialité

Dans ce lot, rapports courants et preuves scellées restent exclusivement en
mémoire et ne sont persistés nulle part :

- aucun nouvel événement `/audit` ;
- aucun endpoint backend ;
- aucune écriture en base ;
- aucun `localStorage` ou `sessionStorage` ;
- aucun envoi réseau ;
- aucune capture d'email, d'ID utilisateur, de texte libre ou de settings
  complets dans les rapports, preuves ou logs ; les settings ne servent qu'au
  calcul éphémère du fingerprint privé de configuration.

Les routes sont canonicalisées ; les fragments et valeurs de query string sont
supprimés. Seule la présence de `systemId`, clé sémantique explicitement
allowlistée, peut être conservée. L'égalité du System forwardé et du workspace
ciblé est réduite à deux booléens calculés avant cette suppression. Les diffs
publics n'exposent que `path` et `code`; les logs n'exposent que statut, codes et fingerprint. Les labels de
données, noms de Systems et valeurs métier ne sont jamais publiés dans un diff
ou un log.

Une éventuelle persistance future nécessiterait un événement dédié, un schéma
backend strict avec `extra=forbid`, un workspace imposé côté serveur et un
acteur pseudonyme. Elle ne fait pas partie du Lot 2.

## 11. Non-objectifs

Le Lot 2 ne doit pas :

- activer `WorkspaceExperienceV2` pour rendre ou router l'UI ;
- modifier le shell, le header métier, les rails ou le canvas ;
- changer les redirects, leurs raisons ou leur propriétaire ;
- déplacer la navigation Mission Room dans le frontend ;
- modifier les permissions backend ou l'IAM ;
- ajouter un comportement conditionné par un slug métier ;
- faire évoluer les profils ou le branding des workspaces de référence ;
- présenter `brand.lines`, `brand.emblem`, les libellés ou glyphes des items
  Mission Room comme couverts par le modèle : ces détails visuels restent à
  vérifier en E2E avant activation ;
- committer, pousser ou déployer ce candidat dans le cadre du Lot 2.

## 12. Matrice de validation du candidat

La matrice distingue les preuves locales obtenues de la validation E2E live qui
reste obligatoire avant toute activation future.

| Gate | Preuve attendue | État |
|---|---|---|
| Core resolver ciblé | registry, adaptateurs, deux oracles indépendants, comparator, explications et gate | OK — 37/37 ciblés |
| Shadow passif | la décision V2 est ignorée et la décision legacy seule est exécutée | OK — 21/21 service shadow + 3/3 guard |
| Reset workspace | contexte brut vidé ; aucune observation tardive de A publiée dans B | OK — inclus dans la suite frontend |
| Mission Room post-API | validation stricte, sept clés, profil, assistant, marque et scope courant | OK — 6/6 intégration composant + scénarios shadow/core |
| Frontend unitaire complet | `npm run test:unit` | OK — 220/220 |
| TypeScript | `npx tsc -p tsconfig.app.json --noEmit` | OK |
| Build Angular | `npm run build` | OK — warnings de budgets/compatibilité existants, sans erreur |
| i18n | `npm run check:i18n` | OK — 26 contrôles |
| UI chrome | `npm run check:ui-chrome` | OK |
| Backend ciblé de non-régression | contrats Andritz, navigation audit, Mission Room et seed Showcase | OK — 90 tests passés |
| Hygiène du diff | `git diff --check` et revue de l'absence de consommateur UI V2 | OK |
| E2E live | Andritz, Sentinel-CI et Octocity inchangés | Non exécuté — obligatoire avant toute activation |

## 13. Critères de clôture du Lot 2

Le lot peut être déclaré terminé localement lorsque :

1. le registry et `WorkspaceExperienceV2` couvrent tous les adaptateurs requis ;
2. la projection legacy décrit le comportement rendu, pas seulement les
   settings ;
3. le guard exécute toujours exclusivement le resolver legacy ;
4. l'observation Mission Room intervient après le payload API sans en prendre
   la propriété ;
5. le comparator et les explications utilisent des fingerprints exacts ;
6. le gate fail-closed couvre tous les scénarios Andritz, Sentinel-CI et
   Octocity ;
7. aucune donnée shadow n'est persistée ou envoyée ;
8. les preuves locales disponibles et la limite E2E restante sont documentées
   sans présenter le shadow mode comme une activation.

L'implémentation du Lot 2 est terminée localement. Elle n'est ni committée, ni
poussée, ni déployée. Une activation UI reste interdite avant les E2E live
obligatoires sur les trois workspaces critiques.
