# design-sync notes — Agentium

## Why this is an off-script, styling-only sync

`frontend-ng` is an **Angular 20 application** (`agentium`), not a React component
library. Claude Design renders **React** (compiled components from `window.<globalName>.*`,
`.jsx` previews, React prop typings). Angular components need the Angular runtime and
cannot render in that environment, and the skill forbids reimplementing them in React.
So a component sync is impossible. We sync only the **design-token + styling layer**, which
*is* consumable by Claude Design (`styles.css` + its `@import` closure, `tokens/`, `fonts/`).

Result: the design agent still builds with generic React components, but they come out
on-brand (correct colors, typography, spacing, radii, brand utilities).

## What was produced (build dir: `ds-bundle/`, gitignored)

- `styles.css` — entry; `@import`s fonts + the four token layers. This closure is what
  rendered designs receive.
- `tokens/agentium-legacy.css` — hand-curated from `src/styles.scss`: the legacy `:root`/
  `.dark` tokens + brand utility classes. **Omitted on purpose:** app-only chrome
  (scrollbars, toastr, lucide sizing, `app-root`/`body` base) and the light-mode Tailwind
  compat shim (the nested `html:not(.dark) { [class~='…'] … }` block). The `body::before`
  mesh background was reworked into a reusable `.agentium-mesh` utility.
- `tokens/cockpit-tokens.css`, `tokens/mission-tokens.css`, `tokens/cockpit-utilities.css`
  — verbatim copies of the `src/styles/*.scss` partials (they are already pure CSS).
- `fonts/` — Inter (400/500/600/700), Inter Tight (500/600/700), JetBrains Mono
  (400/500/600), **latin + latin-ext** subsets, bundled locally as woff2 + `@font-face`
  because the app loads them from Google Fonts CDN and Claude Design can't reach external
  hosts. Regenerate with `scratchpad/build-fonts.mjs` (kept in session scratchpad) or any
  Google Fonts css2 fetch.
- `README.md` — the design agent's reference (= `.design-sync/conventions.md`).

## Verification

Rendered `ds-bundle/` via Playwright (system Chrome channel) against a throwaway preview
page — gradient title, all three font families, every token namespace, and the brand
utilities render correctly on the dark theme. The preview HTML was not uploaded.

## No sync anchor (`_ds_sync.json`)

Off-script styling import has no component render hashes, so no anchor was written. A
future re-sync simply rebuilds and re-uploads everything (correct, just not incremental).

## If revisiting

- To refresh tokens: re-copy the `src/styles/*.scss` partials → `ds-bundle/tokens/*.css`
  and re-curate `agentium-legacy.css` from `src/styles.scss`.
- Brand logos (`src/assets/brand/*.svg`) were **not** included — could be added if the
  design agent should use the real Agentium mark.
- `.design-sync/conventions.md` is human-editable; keep it true to the built CSS.
