# Agentium UI Chrome

Agentium generic product surfaces use the **Cockpit Lean** chrome.

This applies to the shared workspace, build, govern, resources, connectors,
settings, knowledge, systems, skills, capabilities, and run surfaces.

## Cockpit Lean Rules

- Page titles are white or light gray, never gradient.
- Eyebrows use compact mono cyan text.
- Cards use 6-8px radius, thin borders, and minimal glow.
- Icons are quiet framed glyphs, not large gradient blocks.
- Native form controls must be restyled to match the cockpit surface.
- Accent color is used for state and focus, not as dominant decoration.

## Exceptions

Sentinel-CI and AYA showcase surfaces are product-specific cockpits and keep
their own visual language. Do not apply generic chrome rules to:

- `frontend-ng/src/app/features/mission-room/**`
- `vigie-*` / AYA-specific chat presentation styles
- workspace-specific showcase cockpit shells explicitly marked as such

## Guardrail

Run `npm run check:ui-chrome` from `frontend-ng` before shipping generic UI
changes. The check rejects legacy gradient title and purple/brand gradient
patterns in generic chrome surfaces while leaving the Sentinel-CI exception
out of scope.
