# thinking-orbs — vendored render engine

Source: [Jakubantalik/thinking-orbs](https://github.com/Jakubantalik/thinking-orbs)
v0.1.1, MIT © Jakub Antalik (see `LICENSE`).

## Why vendored rather than installed

The published package declares `react >= 18` and `react-dom >= 18` as peer
dependencies and ships a React component. This application is Angular, and
pulling React in to draw a loading indicator is not a trade anyone would make.

The animation itself needs no framework: it is plain 2D canvas, and upstream
already keeps it in a `src/engine/` folder with no React import anywhere. Those
files are copied here **unmodified**, so a future version is a re-copy rather
than a merge. Two exceptions, both stated at the top of the files concerned:

- `types.ts` is trimmed to the three type aliases the engine uses. The original
  also declares the React props interface, and it is the only file in the set
  that imports React.
- The React component (`src/ThinkingOrb.tsx`) and its theme hooks
  (`src/theme.ts`) are **not** vendored. Their job — size the canvas at the
  device pixel ratio, run the frame loop, pause offscreen, resolve the theme —
  is done by `../thinking-orb.component.ts` in Angular's own idioms.

## Updating

```
npm pack thinking-orbs && tar xzf thinking-orbs-*.tgz     # for the LICENCE
curl -sO https://raw.githubusercontent.com/Jakubantalik/thinking-orbs/main/src/engine/<file>
```

Copy `src/engine/*` and `src/presets.ts` over the files here, re-trim
`types.ts`, then check that `resolvePreset` and `MODE_DRAWS` still have the
signatures the component calls.
