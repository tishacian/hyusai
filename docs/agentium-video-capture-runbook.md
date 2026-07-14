# Agentium video capture runbook

Goal: qualify and run a local capture bench against `https://agentium.papai.ai`
with an explicitly configured demo account.

The current film scenario is the **Agentium C-level Operating System +
Flow Builder + Octocity** premium demo: Connectors make the platform concrete,
Hypervisor shows portfolio ROI, Flow Builder is the design-time pivot,
Observability/Audit is the control-time proof, and Octocity is the concrete
Mission Room payoff.

## Prerequisites

Playwright dependencies live in `scripts/playwright/node_modules`.

The account password must stay outside git:

```bash
export AGENTIUM_EMAIL='<operator-email>'
export AGENTIUM_PASSWORD='<from-secret-manager>'
export AGENTIUM_HOST=https://agentium.papai.ai
```

`ffmpeg` is required only for final MP4 assembly. Browser capture works without
it and produces `.webm` rushes.

## Qualify

Without credentials, this checks browser recording and the public sign-in page:

```bash
cd scripts/playwright
npm run agentium:qualify -- --no-login --preset=1080p
```

With credentials, it also validates API login and the hypervisor landing:

```bash
cd scripts/playwright
npm run agentium:qualify -- --preset=1080p
```

The report is written under `docs/video-captures/qualification-*`.

## Capture rushes

```bash
cd scripts/playwright
npm run agentium:capture -- --continuous --preset=1440p --slow-mo=80
```

Useful options:

```bash
npm run agentium:capture -- --continuous --preset=1440p --slow-mo=80
npm run agentium:capture -- --continuous --preset=4k --slow-mo=80
npm run agentium:capture -- --scene=04-flow-builder-hero
npm run agentium:capture -- --workspace=agentium-showcase
npm run agentium:capture -- --out-dir=/tmp/agentium-capture
npm run agentium:capture -- --headed --slow-mo=150
```

Before a premium capture, refresh the demo values:

```bash
cd backend
python -m app.cli.seed_agentium_video_demo
```

This idempotent seed updates only video-tagged Showcase values and Octocity
settings: configured connector badges, high-value portfolio runs, proactive
recommendations, audit events and anonymized Mission Room presentation labels.

`--continuous` records one walkthrough video and attempts UI navigation clicks
between scenes. If a scene changes workspace or the target route is hidden by an
immersive app shell, it falls back to direct navigation and records that in the
manifest.

The Flow Builder scenes use `systemName: "Agentium Workspace Chat"` and resolve
the live System id from `/api/v1/systems`, so the capture does not depend on a
hardcoded id. This system is the most filmable showcase blueprint for the v2
story because it exposes the real transverse chat runtime flow.

Outputs:

- `capture-manifest.json`
- `screenshots/*.png`
- `video/*.webm`
- `auth-state.json` in the capture output directory

## Assemble MP4

After capture:

```bash
cd scripts/playwright
npm run agentium:assemble -- --dir=/path/to/capture-dir
```

With one voiceover file:

```bash
npm run agentium:assemble -- --dir=/path/to/capture-dir --audio=/path/to/voiceover.wav
```

With transitions between separate scene rushes:

```bash
npm run agentium:assemble -- \
  --dir=/path/to/capture-dir \
  --audio=/path/to/voiceover.wav \
  --transition=smoothleft \
  --transition-duration=0.55 \
  --out=/path/to/final.mp4
```

Good transition choices for this demo: `fade`, `smoothleft`, `dissolve`,
`hblur`, `zoomin`.

Recommended premium assembly for the v2 scenario:

```bash
npm run agentium:assemble -- \
  --dir=/path/to/capture-dir \
  --audio=/path/to/voiceover.wav \
  --transition=hblur \
  --transition-duration=0.55 \
  --out=/path/to/agentium-flowbuilder-octocity.mp4
```

## Professional polish

After assembly, add a 2026 AI pure-player finish with Datategy branding,
scene overlays and a subtle cinematic grade:

```bash
cd scripts/playwright
npm run agentium:polish -- \
  --input=/path/to/agentium-flowbuilder-octocity.mp4 \
  --out=/path/to/agentium-clevel-polished.mp4 \
  --logo=assets/datategy-logo.png \
  --scenes=agentium_video_scenes.json
```

## Voiceover placeholder

Local macOS voiceover uses `say` and `afconvert`:

```bash
cd scripts/playwright
npm run agentium:voiceover
```

Edit `agentium_voiceover_script.json` for the text, or pass another file:

```bash
npm run agentium:voiceover -- --script=/path/to/script.json --voice=Thomas --rate=170
```

Outputs are `.aiff` and `.wav` files plus `voiceover-manifest.json`.

## ElevenLabs voiceover

Keep the key outside git:

```bash
export ELEVENLABS_API_KEY='...'
```

List available voices:

```bash
cd scripts/playwright
npm run agentium:voiceover:elevenlabs -- --list-voices
```

Generate a premium voiceover:

```bash
npm run agentium:voiceover:elevenlabs -- --voice-name="VOICE NAME" --model=eleven_multilingual_v2
```

The script writes per-segment `.mp3` files and a combined `voiceover.wav`.
That combined WAV can be muxed with:

```bash
npm run agentium:assemble -- --dir=/path/to/capture-dir --audio=/path/to/voiceover.wav
```

## Scenario beats

The default scene file now follows this order:

1. Octocity cold open.
2. Enterprise connectors and governed data boundaries.
3. Agentium Hypervisor mental model.
4. Systems factory inventory.
5. Flow Builder hero on `Agentium Workspace Chat`.
6. Runtime manifest / validation / run controls.
7. Observability.
8. Audit.
9. Portfolio ROI control.
10. Octocity Mission Room payoff.
11. OCTAVE chat action.
12. Knowledge Capture loop.
13. Flow Builder closing match cut.
