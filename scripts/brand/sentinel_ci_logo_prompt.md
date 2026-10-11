# SENTINEL-CI Logo Generation Prompt

Use this prompt with `scripts/brand/openrouter_logo_variants.py --prompt scripts/brand/sentinel_ci_logo_prompt.md`.

## Product Context

SENTINEL-CI is a serious executive mission-room workspace for the
Republic of Côte d'Ivoire. It is used for intelligence briefings,
agenda, press monitoring, situation awareness, strategic decisions, and
AYA, the strategic assistant.

The identity must feel modern, governmental, high-trust, and operational.
It must not look like a vintage ministry badge, a sports crest, or a
crypto token.

## Design Direction

Create premium SVG mark variants for **SENTINEL-CI**.

Visual metaphor:

- Abstract elephant head as a national-strength signal, not a mascot.
- Mission-room / sentinel signal ring.
- Côte d'Ivoire color accents: orange, ivory/gold, green.
- Dark cockpit compatibility.

Style constraints:

- Favicon-first geometry, readable at 32 px and clean at 42 px in a rail.
- One primary focal idea: elephant head + signal ring.
- No detailed coat of arms, no ministry text, no exact official seal.
- No photorealism, no raster image, no external font or URL.
- Avoid tiny laurel details that disappear at small size.
- Avoid cartoon proportions.
- Keep at least 35% negative space.
- Prefer geometric paths, precise strokes, and limited gradients.

Palette:

- Background: `#030608`, `#07100E`
- Orange: `#FF9A3E`, `#D86F1F`
- Ivory/gold: `#F7F1D2`, `#DCC889`
- Green: `#65D66E`, `#20B85B`
- Slate: `#91A0AE`, `#223226`

## Output Requirements

Return strict JSON with exactly this shape:

```json
{
  "variants": [
    {
      "id": "sentinel-elephant-ring",
      "name": "Sentinel Elephant Ring",
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
- Include at least 1 variant that can be used without a background rect.
- Do not output anything outside the JSON object.
