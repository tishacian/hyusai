# Agentium design system — tokens & styling

**Operating System for Intelligence.** This is a *styling* import: design tokens (CSS
custom properties), the brand fonts (bundled locally), and the signature brand utility
classes. There are no importable components here — the source product is built in Angular,
so style your React UI with these tokens and utility classes to keep every design on-brand.

## Setup

Pull in `styles.css` once at the root of the design. Its `@import` closure brings in the
bundled fonts and all token layers — nothing else is needed:

```jsx
import './styles.css';
```

**Theme.** The shipped product runs **dark** — add `class="dark"` to a root element for the
canonical look. The `--ck-*` cockpit tokens are already dark by default; the legacy
`--bg-*` / `--text-*` tokens flip to dark under `.dark`. Omit it for the legible light variant.

```jsx
<div className="dark" style={{ background: 'var(--ck-bg-base)', color: 'var(--ck-fg-1)' }}>…</div>
```

## Styling idiom — `var(--*)` tokens, not utility frameworks

Style by referencing the CSS custom properties below. **Do not invent color/spacing
values** — every brand color, radius, shadow, and font has a token. There is no Tailwind
preset in this import; use inline styles or your own classes that read these tokens.

There are three token namespaces; prefer **cockpit (`--ck-*`)** for new cockpit-grade
surfaces, **mission/sentinel** for the sovereign mission-room chrome, and the **legacy**
set for general app surfaces.

### Cockpit tokens — `--ck-*` (the primary palette)
- **Surfaces:** `--ck-bg-void`, `--ck-bg-base`, `--ck-bg-panel`, `--ck-bg-panel-hi`, `--ck-bg-inset`, `--ck-bg-code`
- **Strokes:** `--ck-stroke-1`, `--ck-stroke-2`, `--ck-stroke-3`, `--ck-stroke-hot`
- **Text:** `--ck-fg-1` (brightest) → `--ck-fg-5` (faintest)
- **Signals:** `--ck-signal-pos` (green), `--ck-signal-neg` (red), `--ck-signal-warn` (amber), `--ck-signal-cool` (cyan), `--ck-signal-violet`, `--ck-signal-ice`
- **Glows / shadows:** `--ck-glow-cool|pos|violet|warn|neg`, `--ck-shadow-panel|popover|card`
- **Radii:** `--ck-radius-sm` (4px) · `-md` (6px) · `-lg` (10px) · `-xl` (14px)
- **Fonts:** `--ck-font-sans` (Inter Tight / Inter), `--ck-font-mono` (JetBrains Mono)
- **Motion:** `--ck-ease-out`, `--ck-ease-in-out`, `--ck-dur-fast|med|slow`

### Mission / Sentinel tokens (sovereign mission-room chrome)
- **Accent:** `--sentinel-accent` (#65d66e vert-ivoire), `--sentinel-accent-strong`, `--sentinel-accent-soft`
- **Strategic orange / gold:** `--mission-orange`, `--mission-gold`; assistant signature `--agentium-aya`
- **Surfaces/text:** `--mission-surface-1|2|3`, `--mission-text-primary|secondary|tertiary`
- **Semantics:** `--mission-success`, `--mission-warning`, `--mission-critical`, `--mission-info` (+ `-soft` washes)
- **Spacing scale:** `--mission-space-1` (4px) … `--mission-space-12` (48px); type `--mission-text-xs … -2xl`

### Legacy palette
- **Accent:** `--accent` (#00bcd4 cyan), `--accent-violet`, `--accent-indigo`, `--accent-soft`
- **Surfaces/text:** `--bg-app`, `--bg-card`, `--bg-muted`, `--bg-raised`; `--text-primary|secondary|muted`; `--border-default|active`
- **Radii:** `--radius-xs|sm|(default)|lg|xl`
- **Brand gradient:** `linear-gradient(135deg, #00bcd4 0%, #6366f1 50%, #8b5cf6 100%)`

## Brand utility classes (ready to drop on elements)
- `.gradient-title` — cyan→indigo→violet clipped gradient text for hero headings
- `.glass` / `.glass-blur` — opaque vs. translucent-blur brand surfaces
- `.t-card` (+ `.t-elevated`) — token-driven surface card
- `.agentium-mesh` — apply to a full-bleed `position:relative` container for the signature animated radial mesh background
- `.header-underline` — animated gradient underline on a header
- `.focus-ring` — cyan focus ring · `.skeleton` — shimmer loading placeholder
- `.pulse-dot` (+ `.success|warning|danger`) — live status dot
- **Cockpit:** `.ck-surface` / `.ck-surface-hi` / `.ck-inset`, `.ck-mono`, `.ck-tnum`, `.ck-label` / `.ck-label-sm`, `.ck-live-dot` (+ `.cool|violet|warn|neg`), `.ck-hero-ambient`, `.ck-ambient-grid`
- **Mission:** `.mission-status-badge` (+ `.is-live|is-watch|is-advisory|is-baseline`), `.mission-surface-button`, `.mission-metric-tile`, `.mission-panel-title|subtitle|kicker`

## Where the truth lives
Read these bound files for the exact, complete vocabulary before styling:
- `tokens/cockpit-tokens.css` — `--ck-*` palette (+ light overrides under `:not(.dark)`)
- `tokens/mission-tokens.css` — `--mission-*` / `--sentinel-*` / `--agentium-*`
- `tokens/agentium-legacy.css` — legacy tokens + brand utility classes
- `tokens/cockpit-utilities.css` — `.ck-*` utility helpers
- `fonts/fonts.css` — bundled Inter / Inter Tight / JetBrains Mono (`@font-face`)

## Idiomatic example

```jsx
<div className="dark" style={{ background: 'var(--ck-bg-base)', padding: 24, fontFamily: 'var(--ck-font-sans)' }}>
  <h1 className="gradient-title" style={{ fontSize: 36, fontWeight: 700, margin: 0 }}>Agentium</h1>

  <div className="ck-surface" style={{ padding: 16, marginTop: 16 }}>
    <div className="ck-label">THROUGHPUT</div>
    <div className="ck-mono" style={{ fontSize: 22, color: 'var(--ck-fg-1)' }}>42.7</div>
    <span className="mission-status-badge is-live">LIVE</span>
  </div>
</div>
```
