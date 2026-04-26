# Agentium Brand Assets

The mark follows the same principles as the public
`logo-generator-skill` workflow: extreme simplicity, generous negative
space, precise proportions, and one focal idea. The active V3 mark merges
the hand-authored cockpit finish with the stronger favicon geometry from
the OpenRouter-generated `06-precision-a` variant.

## Concept

Agentium is an AI orchestration cockpit. The mark is therefore a
precision routed `A`:

- `A` = Agentium / agency.
- Routed crossbar = orchestration and controlled execution path.
- Signal node = evaluated output / canonical answer.
- Cyan/violet stroke = cockpit signal + AI gradient.

## Files

- `agentium-mark.svg` — square app mark for product chrome.
- `agentium-logo.svg` — horizontal lockup for docs / splash contexts.
- `favicon.svg` — simplified 64×64 browser icon.

## OpenRouter Note

The Renault translation bench uses the OpenAI-compatible OpenRouter
interface:

```python
from openai import OpenAI

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)
```

That is enough for future prompt-driven SVG variant generation without
Gemini. The current assets are hand-authored SVG, so no API key is
required to build the frontend.

## Variant Generation

The utility lives at:

```bash
scripts/brand/openrouter_logo_variants.py
```

Dry-run configuration:

```bash
python3 scripts/brand/openrouter_logo_variants.py --dry-run
```

Generate through OpenRouter:

```bash
python3 scripts/brand/openrouter_logo_variants.py \
  --env-dir /path/to/envs \
  --model google/gemini-2.5-flash
```

The prompt is editable at:

```bash
scripts/brand/agentium_logo_prompt.md
```

Outputs are non-destructive:

```bash
frontend-ng/src/assets/brand/variants/
```

Use `--write-fallback` to copy the current hand-authored mark as a
baseline variant for comparison.
