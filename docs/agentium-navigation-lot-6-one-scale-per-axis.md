# Agentium — Lot 6 : une échelle par axe

Statut : L6.0–L6.5 implémentés sur l'arbre courant. La télémétrie v2 *zone
flip* / *back-bounce* se mesure après déploiement (pas de chiffre inventé).

Références :

- `docs/mental-model.md` §5bis (réécriture à L6.5 seulement) ;
- `docs/agentium-navigation-lot-0-baseline.md` … `lot-5-cleanup-governance.md` ;
- `frontend-ng/src/app/core/navigation.catalog.ts` ;
- maquettes Paper [Navigation · Lot 6](https://app.paper.design/file/01KZXGRFVFWR9G56P5FVDBD4X1/2-0).

## Contrat fonctionnel

Trois questions, trois contrôles, une grammaire d'URL.

| Question | Contrôle unique | Porté par l'URL |
|---|---|---|
| *Pourquoi je suis là ?* → **Zone** (Hypervisor · Create · Operate · Steer · Govern) | rail | `?lens=` sur un objet ; sinon la zone d'origine du `path` |
| *Où suis‑je ?* → **Objet** (Portfolio › Capability › System › Run › Skill) | breadcrumb (seule échelle d'objets) | `path` |
| *Comment je regarde ?* → **Facette** | onglets `ck-tabs` | `?facet=` (toujours, pour tous les objets) |

Le mini‑rail est le **sommaire stable de la zone**. Les descendants d'un objet
sont **ses facettes**. Les listes de zone restent filtrables par **chips**.

Work est un **espace** (lien RBAC), jamais un verbe du rail.

## Huit invariants

| # | Invariant |
|---|---|
| I1 | La hiérarchie d'objets n'est rendue que par le breadcrumb. Le rail ne rend que des zones ; le sommaire ne rend que les surfaces de la zone et, à partir de L6.3, la branche de facettes du System en contexte — jamais un index de types d'objets. |
| I2 | La zone active est une fonction pure de l'URL (`path` + `?lens`). |
| I3 | Tout lien vers une surface catalogue passe par le catalogue et conserve par défaut zone et ascendance ; changer de zone est explicite (`lens:`). |
| I4 | Descendre d'un niveau ne change pas de zone ; changer de zone ne change pas d'objet. |
| I5 | Les descendants d'un objet sont ses facettes ; une liste filtrée est un filtre (chip), jamais une ascendance. `?scope=` disparaît. |
| I6 | La facette est toujours dans l'URL (`?facet=`), pour tous les objets à onglets. `?tab=` et `?focus=` sont des alias résolus puis retirés. Aucune sélection de navigation en `sessionStorage` / `localStorage`. |
| I7 | Le layout ne saute pas à la descente : colonne sommaire à largeur fixe. |
| I8 | Un seul modèle de navigation par espace : Cockpit v5 (gradué), Work, Business, Immersif. |

## Grammaire d'URL v5

```text
/{zone-home}                          # /hypervisor /create /runs /steering /governance
/{objectType}/{id}                    # objet ; ascendance = graphe prouvé, jamais l'URL
    ?lens=build|operate|steer|govern  # build = identifiant technique de Créer
    ?facet=<id>                       # facette — remplace tab/focus
/skills/{slug}?systemId=&runId=       # seul cas où l'URL décrit un parent
/{zone-list}?systemId=&capabilityId=  # filtre de liste (chip, breadcrumb = Portfolio)
```

Clés reconnues : `lens`, `facet`, `systemId`, `capabilityId`, `runId`.
Retirées : `scope`, `tab`, `focus`, `capability_id`, `system_id`.

## Décisions D1–D8

| # | Décision |
|---|---|
| D1 | Descendants = facettes de l'objet. Les listes scopées `?scope=` sont retirées. |
| D2 | Un seul nom de zone : **Créer**. L'identifiant technique reste `build`. |
| D3 | Facette et lentille via `replaceUrl` ; objet ou zone‑home via push. |
| D4 | Mode `builder` : Hypervisor et Steer masqués **et** home `/create`. |
| D5 | Lentille visible en texte dans l'`eyebrow` de `ck-object-header` (« {TYPE} · VU DEPUIS {ZONE} »). |
| D6 | Un seul « Retour » : `ck-back-link` = parent du breadcrumb. La barre de commande affiche la position (« Zone · {zone} · Profondeur n/5 »). Pas de back‑link sur une liste filtrée. |
| D7 | Branche « Dans {System} » = facettes (L6.3). L6.2 livre le sommaire sans branche. |
| D8 | Work = lien « Work ↗ » (RBAC) + « Ouvrir dans Work » si application publiée. Aucun commutateur. |

## Flags

| Flag | Rôle | Défaut |
|---|---|---|
| `navigation_telemetry_v2` | Émet `navigation.transition` en plus de `navigation.resolved`. | opt‑in |
| `cockpit_nav_v5` | Chrome cible (L6.2–L6.3). | **gradué** (absence = on ; `false` = opt‑out) |
| `cockpit_router_axes_v3` / `_v4` | Axes routés (chrome). | **gradués** (absence = on). Le resolver garde `axes_v4` explicite pour ne pas casser le demo `/hypervisor` → Mission Room. |

## Télémétrie v2

Événement additif `navigation.transition`, même table d'audit, `extra=forbid`,
pseudonymisé comme v1 (surfaces canoniques, jamais d'id) :

```text
{
  schema_version: 2,
  from_surface, to_surface,
  trigger: rail | minirail | breadcrumb | inpage | palette | history | redirect,
  zone_changed, depth_delta, facet_changed
}
```

Mesures dérivées (baseline L6.0, cible L6.4) :

- *zone flip* = `zone_changed && trigger === inpage` ;
- *back‑bounce* = `trigger === history` moins de 3 s après une navigation de page ;
- profondeur moyenne avant remontée à Portfolio = moyenne des `depth_delta` négatifs
  qui aboutissent à la profondeur 1.

La baseline chiffrée Showcase / workspace interne se collecte derrière le flag,
après le premier déploiement L6.0. Formules ci‑dessus ; pas de chiffre inventé.

## Garde des liens

`frontend-ng/scripts/check-nav-links.mjs` (`npm run check:nav-links`) compte les
trois motifs de lien brut du plan §1. L6.0 : mode rapport (exit 0). L6.1 :
fail‑closed. Baseline versionnée : `docs/compliance/nav-links-baseline.v1.json`.

## Sous‑lots

| Lot | Visible ? | Gate |
|---|---|---|
| L6.0 Contrat et mesure | non | tests télémétrie ; rapport `check-nav-links` |
| L6.1 Étanchéité des liens | oui (liens stables) | canary axes v3 vert ; 0 lien de page qui casse `lens`/ascendance |
| L6.2 Un rail, un sommaire | flag `cockpit_nav_v5` | I1, I7 ; rollback = flag off |
| L6.3 Objet‑centrique | même flag | `19-navigation-v5-canary` |
| L6.4 Graduation | oui | `check-nav-links` à zéro hors allowlist |
| L6.5 Preuves | docs | `mental-model.md` §5bis, `agentium-reference.md` §6 |

## Preuves L6.5

- Parcours *Operate › System X › Flow › Retour* : le lien Flow passe par le
  catalogue (`system-flow`) et conserve `lens` ; le rail ne bascule plus vers
  Create par un lien brut. Preuve unitaire : `navigation.catalog.spec` I3 +
  `zoom-context.service.spec` Flow builder.
- Drill-down 5 niveaux sans saut de colonne : sommaire `ck-mini-rail-stable`
  208 px ; canary `19-navigation-v5-canary` compare `main.boundingBox().x`.
- Télémétrie v2 *zone flip* / *back-bounce* : formules ci-dessus. Aucun
  chiffre inventé — à extraire après le premier déploiement du flag gradué.
