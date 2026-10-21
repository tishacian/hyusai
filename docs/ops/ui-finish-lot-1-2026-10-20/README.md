# Measured finish (UI/UX plan, lot 1) — evidence, 2026-10-20

> Historical reconstruction notice (21 October 2026): the measurements and
> test results below are inherited from the reconstructed lot 1 report. The
> 20 before/after PNG captures are absent. These visual and browser checks
> have not been rerun on the integrated candidate; see
> [the current validation report](../uiux-plan-2026-10-21/README.md).

Branch `feat/lot-1-finition`, from `origin/demo/agentic` at `7e5652d5e`.
Both builds were measured on the same mocked stack (no backend, no production
call): `ng build --configuration development` served by `e2e/serve-dist.mjs`,
1470 × 776, Chrome, mocks from `e2e/tests/72-finish-geometry-mocked.spec.ts`.

## Measurements

| Criterion | Target | Before | After |
|---|---|---|---|
| « Services and deliveries » anchor height | ≥ 32 px | 18 px | 32 px |
| Creator link height, label centred | ≥ 32 px, ≤ 0.5 px | 32 px, label on the baseline | 32 px, centred |
| Title-bar glyph centre vs its label | ≤ 0.5 px | 1.86 px | 0 px |
| Connections `h1` from the content edge (x, y) | ≥ 24 px | 0, 0 | 32, 24 |
| `<main>` landmarks on Connections | 1 | 2 | 1 |
| Wizard group spacing / inner label gap | 20 px / 6 px | 0 px / 6 px | 20 px / 6 px |
| « Continue editing » / « Continuer l’édition » | 1 line | 2 lines | 1 line |
| Audience with three long group names | ≤ 2 lines | — | 2 lines |

`72-finish-geometry-mocked.spec.ts`: 10 geometry tests fail on the base build
and pass on the branch; the 4 accessibility-matrix tests run fr/en × light/dark
× 1440/456/320 px.

## Accessibility matrix

`/work` passes with no serious or critical axe finding, 320 px reflow included.
Three screens keep one finding that predates this lot and sits in files other
lots own; the spec marks them with `test.fail` so they turn red once fixed:

- `scrollable-region-focusable` on the shell status footer
  (`features/layout/command-bar.component.ts`) under 768 px: Connections,
  applications list, wizard. Handed to lot 3 (needs an accessible label in
  `chrome.dict.ts`).
- `scrollable-region-focusable` on the wizard steps (`.xp-steps`) under 768 px:
  fixed on lot 4's branch.

## Non-regression

- `npm run check:ui-chrome` and its self-tests (8/8) pass with the new
  `tiny-type` rule; no existing budget was loosened. Under-12 px occurrences
  in the touched files: 251 → 240.
- `npm run check:i18n` passes; no copy was added or changed.
- `npm run test:unit`: 2433/2436 on the branch and on the base; the same 3
  tests fail on both (`work-release-pages-nav` ×2, `mandate-components`).
- Mocked Luma and connector specs (26, 28, 33, 50, 53, 70, 29, 17, 24): no
  test fails on the branch that passes on the base (14 failures on the
  branch, 15 on the base, all shared except one base-only flake in 26).

## Captures

`before-*.png` / `after-*.png`: Work home, Connections, PostgreSQL, the
applications list and the new-application wizard, dark and light. The glyph and
icon change also moves the side-rail and title-bar icons by 2–4 px into their
optical centre on every screen; no other screen changed in the sweep (Runs,
Flow builder, Systems, SFTP, connector list).

## UI review (agentium-ui-review, captures above)

- P1, out of scope: the wizard header shows two « Close » controls (lot 4).
- P2, out of scope: on PostgreSQL the error banner touches the first step card.
- P2: the « Services and deliveries » button sits directly on the Work lede;
  the home header spacing is lot 3's « accueil Work ».

Verdict: the measured defects are gone where they were caused, in the shared
components; the single change that would improve these screens most next is
the status-footer accessibility fix (lot 3).
