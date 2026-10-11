# Agentium UI Chrome

Agentium platform surfaces use the **Cockpit Workbench** chrome. This is the
official generic product design for the platform.

The reference applications are:

- Recherche (`/chat`)
- Client360 PDR (`/client360`)
- Capture "Le Fil" (`/knowledge/capture`)

This applies to the shared workspace, build, operate, govern, resources,
connectors, settings, knowledge, systems, skills, capabilities, and run
surfaces.

## Cockpit Workbench Rules

- Page titles are white or light gray, never gradient.
- Eyebrows use compact mono cyan text.
- Cards use 6-8px radius, thin borders, and minimal glow.
- Icons are quiet framed glyphs, not large gradient blocks.
- Native form controls must be restyled to match the cockpit surface.
- Accent color is used for state and focus, not as dominant decoration.
- Use shared cockpit primitives (`ck-page-frame`, `ck-surface`, `ck-tag`,
  `ck-glyph`, `ck-stat-readout`, `ck-panel`) or local classes backed by
  `--ck-*` tokens.
- Do not introduce legacy `brand-*`, violet gradient, `glass`, or `t-card`
  styling on platform surfaces.

## Exceptions

Mission Room, Sentinel-CI and AYA showcase surfaces are product-specific
cockpits. They keep their own visual language and are not the platform standard
to copy. Do not apply generic chrome rules to:

- `frontend-ng/src/app/features/mission-room/**`
- `vigie-*` / AYA-specific chat presentation styles
- workspace-specific showcase cockpit shells explicitly marked as such
- legacy Capture v0 (`KnowledgeCaptureComponent`) while the fallback exists

## Guardrail

Run `npm run check:ui-chrome` from `frontend-ng` before shipping generic UI
changes. The check rejects legacy gradient title, purple/brand gradient,
`brand-*`, `glass`, and `t-card` patterns in official platform cockpit surfaces
while leaving Mission Room / Sentinel-CI / AYA exceptions out of scope.
Legacy Capture v0 is also ignored while it remains available as an explicit
fallback.
