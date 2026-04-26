# Agentium Logo Generation Prompt

Use this prompt with `scripts/brand/openrouter_logo_variants.py`.

## Product Context

Agentium is a professional AI orchestration cockpit for enterprise teams.
It lets executives, operators, builders, quality owners, and admins manage
AI systems, runs, skills, knowledge, evaluation loops, human review,
proactive recommendations, and governance.

Core words:

- orchestration
- cockpit
- agency
- signal
- trusted automation
- feedback loop
- enterprise precision

## Design Direction

Create a premium geometric SVG logo system for **Agentium**.

This is a second-pass prompt. The previous generation was too generic:
targets, atoms, bulky filled letters, and abstract diamonds are rejected.

The design must be favicon-first. The mark must remain recognizable at
16×16 px and feel premium in a 26×26 title-bar slot.

Visual metaphor:

- A geometric `A` monogram is preferred, but it must not look like a
  generic font glyph.
- It should suggest orchestration, routing, evaluation loops, or an orbital
  control system.
- It must work as a 16×16 favicon and as a 128×128 product mark.

Style constraints inspired by the logo-generator-skill method:

- Extreme simplicity: 1 to 2 core shapes maximum.
- Generous negative space: 40%+ empty canvas.
- Precise proportions and line weights.
- Single focal point.
- No mascots, no brain, no robot, no generic sparkles.
- Should feel like enterprise SaaS, not a crypto coin.
- Use negative space to imply the `A` where possible.
- Use one routing/orbit path at most.
- Avoid filled bulky `A` shapes.
- Avoid target/crosshair icons.
- Avoid atom icons.
- Avoid diamond-only / abstract-module icons.
- Avoid more than 2 dots/nodes.
- Avoid tiny details that disappear at favicon size.
- Prefer strokes with rounded caps or precise cut geometric forms.
- Gradients are allowed only when the shape remains readable in one color.

Palette:

- Background: `#070A10`
- Cyan signal: `#00BCD4`
- Electric cyan: `#61F6FF`
- Violet accent: `#8B5CF6`
- Slate stroke: `#1D2733`
- Text: `#F8FAFC`

## Output Requirements

Return strict JSON with exactly this shape:

```json
{
  "variants": [
    {
      "id": "orbit-a",
      "name": "Orbit A",
      "rationale": "Short explanation",
      "svg": "<svg ...>...</svg>"
    }
  ]
}
```

Rules:

- Generate 6 variants.
- Every `svg` must be standalone SVG.
- Use `viewBox="0 0 128 128"` for marks.
- Do not include markdown.
- Do not include raster images.
- Do not use external fonts or external URLs in SVG.
- Prefer `<path>`, `<circle>`, `<rect>`, `<ellipse>`, `<line>`.
- Ensure `id` is lowercase kebab-case.
- Include at least 2 variants that are single-color compatible.
- Include at least 2 variants that use negative space for the A.
- Include at least 1 variant that can be used without a background rect.
- Do not output anything outside the JSON object.
