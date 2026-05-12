# SENTINEL-CI Visual System

SENTINEL-CI is a workspace app, not a standalone skin. It must feel like a sovereign mission room hosted by Agentium: dense, calm, auditable, confidential and executive-ready.

## Product Tone

- Use operational language: sources qualifiees, arbitrage, validation humaine, canaux habilites, briefing, signaux faibles.
- Avoid frontal meta-demo language in user-facing screens: no "mode demo", "synthetic data", "metadata-only", "provider", "model name" or "advisory-only" unless the screen is explicitly admin/dev.
- Every recommendation should read as prepared action, never autonomous execution.
- Prefer confidence and traceability cues over marketing copy.

## Visual Principles

- Dark sovereign cockpit: low-glare base, restrained cyan for active intelligence, emerald for trust, amber for watch, red only for critical risk.
- No decorative orbs, bokeh or loud gradients. Use grids, borders, hairlines and measured contrast.
- Panels stay compact and information-dense. Use cards only for repeated items, controls and framed mission instruments.
- Typography follows Agentium tokens: `var(--ck-font-sans)` for content, `var(--ck-font-mono)` for labels, timestamps, numeric telemetry and small system readouts.
- Buttons are controls, not hero CTAs. Primary actions use a soft accent wash, not saturated blocks.

## Component Tokens

The Mission Room defines scoped CSS variables in `mission-room.component.ts`:

- `--mission-bg`, `--mission-rail-bg`
- `--mission-panel`, `--mission-panel-hi`, `--mission-inset`
- `--mission-border`, `--mission-border-strong`
- `--mission-text`, `--mission-text-soft`, `--mission-text-muted`, `--mission-text-faint`
- `--mission-accent`, `--mission-trust`, `--mission-warn`, `--mission-danger`
- wash variants for accent, trust, warning and danger
- `--mission-radius`, `--mission-shadow-card`

New SENTINEL-CI views should consume these variables first, then fall back to `--ck-*` tokens only when they are generic Agentium surfaces.

## Interaction Rules

- Keep the left rail stable across views.
- Keep header copy compact: mission label, status, title, date/context, two controls maximum.
- Charts should remain SVG/CSS local and not depend on external tiles or SaaS.
- Demo-safe mode hides provider and model details, but still shows functional architecture through sources, audit, oracle, RAG and validation states.
