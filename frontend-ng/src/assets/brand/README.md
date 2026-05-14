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
- `sentinel-ci-mark.svg` — workspace mark for the SENTINEL-CI mission-room.
- `sentinel-ci-logo.svg` — SENTINEL-CI horizontal lockup for docs / splash contexts.
- `sentinel-ci-favicon.svg` — favicon used while `/hypervisor/mission-room/*` is open.

## SENTINEL-CI Workspace Mark

SENTINEL-CI keeps Agentium as the platform brand while giving the
government mission-room a dedicated identity. The active mark is a
hand-authored SVG inspired by the same generation workflow:

- abstract elephant head = institutional strength without copying an
  official ministry seal;
- tricolor signal ring = Côte d'Ivoire palette and mission-room
  surveillance posture;
- dark circular base = compatibility with the cockpit rail and
  executive screens.

The reusable prompt for future OpenRouter variants lives at:

```bash
scripts/brand/sentinel_ci_logo_prompt.md
```

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

The generation workflow is intentionally outside the Agentium runtime. It
is an operator/design utility used to produce SVG candidates, compare them,
then manually promote the chosen asset into the active files.

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

## Full Process We Used

### 1. Generate rough variants

Initial prompt inspired by `logo-generator-skill` produced six variants:

- `01-orbital-flow.svg`
- `02-precision-core.svg`
- `03-signal-route.svg`
- `04-loop-matrix.svg`
- `05-agency-nexus.svg`
- `06-controlled-path.svg`

Outcome: useful exploration, but too generic. The strongest directions
were `03-signal-route` for favicon readability and `01-orbital-flow` for
Agentium’s loop/orchestration metaphor.

### 2. Tighten the prompt

We updated `scripts/brand/agentium_logo_prompt.md` to reject:

- targets / crosshairs
- atom icons
- bulky filled `A` marks
- generic diamonds
- tiny details that disappear at favicon size

The V2 prompt asks for a favicon-first geometric `A`, one route/orbit at
most, and strict standalone SVG JSON.

### 3. Generate V2 through OpenRouter

Command:

```bash
export OPENROUTER_API_KEY="..."
python3 scripts/brand/openrouter_logo_variants.py \
  --model google/gemini-2.5-flash
unset OPENROUTER_API_KEY
```

V2 outputs:

- `01-orbital-a.svg`
- `02-signal-a.svg`
- `03-loop-a.svg`
- `04-nested-a.svg`
- `05-routed-a.svg`
- `06-precision-a.svg`

Decision: `06-precision-a.svg` had the best favicon geometry and
single-color compatibility, but it was still too generic as-is.

### 4. Promote a hand-finished V3

The active V3 mark is a manual refinement:

- base geometry from `06-precision-a`
- product finish from the earlier hand-authored cockpit mark
- a routed crossbar for orchestration
- one signal node for evaluated output / canonical answer
- reduced detail compared with the original orbital mark

Active files:

- `agentium-mark.svg`
- `favicon.svg`
- `agentium-logo.svg`

Generated variants are kept for comparison in:

```bash
frontend-ng/src/assets/brand/variants/
```

## Validation Checklist

After changing active brand assets:

```bash
npm run build
```

On the VM:

```bash
cd /home/ubuntu/omnirag/frontend-ng
npm run build
sudo rsync -a --delete dist/agentium/browser/ /var/www/agentium/
curl -sk -o /tmp/agentium-favicon.svg -w "favicon=%{http_code}\n" \
  https://agentium.papai.ai/assets/brand/favicon.svg
E2E_BASE_URL=https://agentium.papai.ai \
  npx playwright test e2e/tests/01-auth-keycloak.spec.ts --project=chromium --reporter=list
```

Expected:

- favicon returns `200`
- `index.html` references `/assets/brand/favicon.svg`
- title bar and auth shell show `agentium-mark.svg`
- auth E2E passes

## Security Notes

- Never commit OpenRouter keys.
- Prefer `export OPENROUTER_API_KEY=...` for one terminal session.
- Run `unset OPENROUTER_API_KEY` after generation.
- If a key is pasted into chat or logs, rotate it in OpenRouter.
