# Agentium — statut pré-démo du 21 juillet 2026

Heure de clôture technique : 12:13 CEST.

## SHA testé

`cfa3f616050bb5f75c9a3709219b52939e7ec0bd`

Backend et frontend ont tous deux annoncé cette révision avec
`revision_verified: true`.

## Résultats

- Canari authentifié System 360 : **1/1 passé**, garde console stricte incluse.
- Contrats prouvés : découverte par marqueur, quatre projections distinctes,
  identité/header/breadcrumb/tabs invariants, comparaison UI/API, deep links,
  reload, historique, conservation de facette, purge atomique au changement de
  workspace, états manquants/restreints explicites.
- Smoke fonctionnel : **5/5 passé** pour Andritz, Showcase, Sentinel et Octocity.
  Andritz expose désormais quatre apps intentionnelles : les trois historiques
  plus FSE.
- Captures de secours : quatre lenses System 360, quatre apps Andritz, Showcase,
  Sentinel et Octocity.

## Limites connues

- Le smoke avec garde console expérimentale a localisé un `422` de télémétrie
  FSE (`POST /api/v1/audit`) : aucun impact de navigation, mais l'événement FSE
  n'est pas persisté.
- Sentinel et Octocity rendent correctement ; leur appel secondaire
  `GET /api/v1/meetings/decisions-log` répond `404`. Sentinel masque ainsi 11
  décisions existantes derrière l'état vide, Octocity en possède réellement 0.
- Le contrat backend ne connaît pas encore le motif axes v4
  `legacy_hypervisor_object_lens` ; un ancien deep link est redirigé mais son
  événement de télémétrie serait refusé.
- Aucun de ces trois correctifs n'a été redéployé avant la démo afin de garder
  la production gelée sur le SHA testé.
- L'attestation protégée refuse volontairement de se générer hors GitLab. Le
  statut formel `deployed_verified` attend donc le miroir et le job protégé.
- La validation humaine 1–2 participants reste à réaliser ; ne pas revendiquer
  `user_validated`.

## Artefacts principaux

- [`observations/lot6-system360-runner-local.json`](observations/lot6-system360-runner-local.json)
- [`observations/lot6-system360-behavior-local.json`](observations/lot6-system360-behavior-local.json)
- [`observations/workspace-smoke-junit.xml`](observations/workspace-smoke-junit.xml)
- [`screenshots/`](screenshots/)
- [`demo-runbook.md`](demo-runbook.md)
- [`validation-protocol.md`](validation-protocol.md)
