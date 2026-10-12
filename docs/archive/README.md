# Archive de la documentation

Documents historiques : preuves de release, captures, rendus et rapports datés. Ils
ne sont plus maintenus, mais restent dans le dépôt pour l'historique (`git log
--follow`) et pour les liens des documents vivants. La règle est fixée par
[ADR 0004](../adr/0004-reorganisation-monorepo.md), décision D3.

Un document archivé garde son chemin d'origine sous l'année d'archivage :
`docs/evidence/x` devient `docs/archive/2026/evidence/x`.

## 2026

| Dossier | Contenu |
|---|---|
| [`compliance-2/`](2026/compliance-2/) | packs de conformité hébergement (ANDRITZ, OVH) |
| [`design/`](2026/design/) | maquettes et notes de design |
| [`diagrams/`](2026/diagrams/) | diagrammes d'architecture |
| [`render/`](2026/render/) | générateurs Python et sorties Office (decks, offres, annexes) |
| [`status-screenshots/`](2026/status-screenshots/) | captures de QA de mai 2026 |
| [`evidence/`](2026/evidence/) | preuves de release, de runtime et de recette (septembre et octobre 2026) |
| [`demo-runs/`](2026/demo-runs/) | scripts, specs et captures des démos clients |
| [`reports/`](2026/reports/) | rapports d'audit, de passation et de QA visuelle |
| [`ui/`](2026/ui/) | captures et notes d'interface |

## Restés en place

Ces fichiers sont lus par des tests et ne sont pas archivés :

- `docs/evidence/brd-pih-runtime-2026-09-16/candidate-10.json`,
  `docs/evidence/northforge-brd-2026-09-16/revision-2/live-generation.json` et
  `docs/evidence/release-1e374c3c-2026-09-17/generation-job.json`
  (`backend/app/tests/services/test_brd_generation.py`) ;
- `docs/demo-runs/showcase-ecommerce/fixtures/` (tests e-commerce, claims et sources
  de flow).

## Notes

- Les générateurs de `render/` ont été écrits pour être lancés depuis
  `docs/render/` ; leurs chemins relatifs vers `docs/pih/` ne sont pas réécrits.
- Les scripts de QA n'écrivent plus ici : leur sortie par défaut est `artifacts/qa/`,
  ignoré par git.
- Les images de ces dossiers ne sont pas copiées dans les images Docker Python
  (`docker/Dockerfile.agentium-*.dockerignore`).
