// ============================================
// AGENTIUM — Shared primitives
// ============================================

const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;

// ---------- Live number hook (reactive telemetry) ----------
function useLiveNumber(base, { jitter = 0.02, interval = 1400, enabled = true } = {}) {
  const [v, setV] = useState(base);
  useEffect(() => {
    setV(base);
    if (!enabled) return;
    const t = setInterval(() => {
      const delta = (Math.random() - 0.5) * 2 * jitter * base;
      setV(base + delta);
    }, interval);
    return () => clearInterval(t);
  }, [base, jitter, interval, enabled]);
  return v;
}

// ---------- Formatters ----------
const fmt = {
  money: (n) => {
    const abs = Math.abs(n);
    if (abs >= 1e9) return `$${(n/1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `$${(n/1e6).toFixed(2)}M`;
    if (abs >= 1e3) return `$${(n/1e3).toFixed(1)}k`;
    return `$${n.toFixed(2)}`;
  },
  pct: (n, d=1) => `${n >= 0 ? '+' : ''}${n.toFixed(d)}%`,
  num: (n, d=0) => n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }),
  ms: (n) => n < 1000 ? `${Math.round(n)}ms` : `${(n/1000).toFixed(2)}s`,
};

// ---------- Sparkline ----------
function Spark({ data, color = 'var(--signal-cool)', height = 28, width = 120, glow = true, fill = true }) {
  const max = Math.max(...data), min = Math.min(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const pts = data.map((v, i) => `${i * step},${height - ((v - min) / range) * height}`).join(' ');
  const fillPts = `0,${height} ${pts} ${width},${height}`;
  const gid = useRef(`g-${Math.random().toString(36).slice(2,8)}`).current;
  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <polygon points={fillPts} fill={`url(#${gid})`} />}
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={glow ? { filter: `drop-shadow(0 0 4px ${color})` } : undefined}
      />
    </svg>
  );
}

// ---------- Bar (tiny, tabular) ----------
function MicroBar({ value, max = 100, color = 'var(--signal-cool)', w = 80, h = 4 }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div style={{ width: w, height: h, background: 'var(--stroke-1)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, boxShadow: `0 0 8px ${color}` }} />
    </div>
  );
}

// ---------- Glyphs (minimal, line-based) ----------
const Glyph = {
  Flow: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="3" cy="3" r="1.5" stroke="currentColor"/><circle cx="11" cy="11" r="1.5" stroke="currentColor"/><path d="M4.5 3.5 L11 11" stroke="currentColor" strokeLinecap="round"/></svg>,
  Pulse: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 7 L4 7 L5.5 3 L7.5 11 L9 7 L13 7" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Cube: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1 L12 3.5 V10.5 L7 13 L2 10.5 V3.5 Z M7 1 V7 M2 3.5 L7 7 L12 3.5" stroke="currentColor" strokeLinejoin="round"/></svg>,
  Sliders: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 1 V13 M11 1 V13 M3 5 L1 5 M3 5 L5 5 M11 9 L9 9 M11 9 L13 9" stroke="currentColor" strokeLinecap="round"/></svg>,
  Focus: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 4 V1 H4 M10 1 H13 V4 M13 10 V13 H10 M4 13 H1 V10" stroke="currentColor" strokeLinecap="round"/><circle cx="7" cy="7" r="2" stroke="currentColor"/></svg>,
  Bolt: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7.5 1 L3 8 H7 L6.5 13 L11 6 H7 Z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  Arrow: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 7 H11 M7.5 3.5 L11 7 L7.5 10.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Ledger: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 2 H12 V12 H2 Z M2 5 H12 M5 2 V12" stroke="currentColor"/></svg>,
  Telemetry: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 12 L4 8 L6 10 L9 4 L13 7" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/><circle cx="13" cy="7" r="1.2" fill="currentColor"/></svg>,
  Warn: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1 L13 12 H1 Z M7 5 V8 M7 10 V10.5" stroke="currentColor" strokeLinejoin="round"/></svg>,
  Check: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7 L6 11 L12 3" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  X: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 3 L11 11 M11 3 L3 11" stroke="currentColor" strokeLinecap="round"/></svg>,
  ZoomIn: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor"/><path d="M6 4 V8 M4 6 H8 M9 9 L12.5 12.5" stroke="currentColor" strokeLinecap="round"/></svg>,
  ZoomOut: () => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor"/><path d="M4 6 H8 M9 9 L12.5 12.5" stroke="currentColor" strokeLinecap="round"/></svg>,
};

// ---------- Tag / Pill ----------
function Tag({ children, tone = 'neutral', style }) {
  const tones = {
    neutral: { bg: 'var(--stroke-1)', fg: 'var(--fg-3)', bd: 'var(--stroke-2)' },
    pos:     { bg: 'rgba(52,211,153,0.10)', fg: 'var(--signal-pos)', bd: 'rgba(52,211,153,0.25)' },
    neg:     { bg: 'rgba(239,90,111,0.10)', fg: 'var(--signal-neg)', bd: 'rgba(239,90,111,0.25)' },
    cool:    { bg: 'rgba(125,211,252,0.08)', fg: 'var(--signal-cool)', bd: 'rgba(125,211,252,0.25)' },
    violet:  { bg: 'rgba(167,139,250,0.10)', fg: 'var(--signal-violet)', bd: 'rgba(167,139,250,0.28)' },
    warn:    { bg: 'rgba(245,184,74,0.08)', fg: 'var(--signal-warn)', bd: 'rgba(245,184,74,0.25)' },
  };
  const t = tones[tone];
  return (
    <span className="mono" style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 6px', borderRadius: 3,
      fontSize: 10, letterSpacing: '0.04em', textTransform: 'uppercase',
      background: t.bg, color: t.fg, border: `1px solid ${t.bd}`,
      whiteSpace: 'nowrap',
      ...style
    }}>{children}</span>
  );
}

// ---------- KeyCap ----------
function Kbd({ children }) {
  return <span className="mono" style={{
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    minWidth: 16, height: 16, padding: '0 4px',
    fontSize: 10, color: 'var(--fg-3)',
    background: 'var(--stroke-1)', border: '1px solid var(--stroke-2)',
    borderRadius: 3,
  }}>{children}</span>;
}

// Export to window
Object.assign(window, { useLiveNumber, fmt, Spark, MicroBar, Glyph, Tag, Kbd });
