// ============================================
// AGENTIUM — Chrome & Semantic Zoom Navigator
// ============================================

const ZOOM_LEVELS = [
  { id: 'portfolio', label: 'Portfolio', sub: 'All capabilities' },
  { id: 'capability', label: 'Capability', sub: 'Customer Intelligence' },
  { id: 'system',     label: 'System',     sub: 'Sentiment Routing v4.2' },
  { id: 'skill',      label: 'Skill',      sub: 'Semantic Extraction' },
  { id: 'run',        label: 'Run',        sub: 'RUN-8924A' },
];

const VIEWS = [
  { id: 'hypervisor', label: 'Hypervisor',     glyph: 'Ledger',   desc: 'Executive cockpit' },
  { id: 'zoom',       label: 'Zoom',           glyph: 'Focus',    desc: 'Semantic navigator' },
  { id: 'steering',   label: 'Steering',       glyph: 'Sliders',  desc: 'Control plane' },
  { id: 'builder',    label: 'Builder',        glyph: 'Flow',     desc: 'System canvas' },
  { id: 'run',        label: 'Run',            glyph: 'Telemetry',desc: 'Execution detail' },
];

// ---------- Title bar ----------
function TitleBar({ view, setView, systemState }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'stretch',
      height: 48,
      borderBottom: '1px solid var(--stroke-2)',
      background: 'var(--bg-base)',
      position: 'relative', zIndex: 10,
    }}>
      {/* Brand */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '0 18px', minWidth: 240,
        borderRight: '1px solid var(--stroke-2)',
      }}>
        <BrandMark />
        <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg-1)', letterSpacing: '-0.01em' }}>Agentium</span>
          <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', marginTop: 3, letterSpacing: '0.08em', textTransform: 'uppercase' }}>OS / v4.2.1</span>
        </div>
      </div>

      {/* Zoom breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '0 14px', flex: 1, overflow: 'hidden' }}>
        {ZOOM_LEVELS.map((lv, i) => (
          <React.Fragment key={lv.id}>
            <button style={{
              display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
              padding: '6px 10px', border: 'none', background: 'transparent',
              color: i === 2 ? 'var(--fg-1)' : 'var(--fg-4)',
              borderRadius: 4, cursor: 'pointer', textAlign: 'left',
            }}>
              <span className="mono" style={{
                fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase',
                color: i === 2 ? 'var(--signal-cool)' : 'var(--fg-5)',
              }}>{lv.label}</span>
              <span style={{ fontSize: 12, marginTop: 2, whiteSpace: 'nowrap', fontWeight: i === 2 ? 500 : 400 }}>{lv.sub}</span>
            </button>
            {i < ZOOM_LEVELS.length - 1 && (
              <span style={{ color: 'var(--fg-5)', fontSize: 10 }}>›</span>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* System status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '0 18px', borderLeft: '1px solid var(--stroke-2)' }}>
        <StatusReadout label="THRPT" value={`${systemState.throughput.toFixed(1)}k/s`} color="var(--signal-cool)" />
        <StatusReadout label="LATENCY" value={`${Math.round(systemState.latency)}ms`} color="var(--signal-violet)" />
        <StatusReadout label="YIELD" value={`+${systemState.yield.toFixed(1)}%`} color="var(--signal-pos)" />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 14, borderLeft: '1px solid var(--stroke-2)' }}>
          <span className="live-dot" />
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.08em' }}>LIVE</span>
        </div>
      </div>
    </div>
  );
}

function StatusReadout({ label, value, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', lineHeight: 1 }}>
      <span className="mono" style={{ fontSize: 8, color: 'var(--fg-5)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>{label}</span>
      <span className="mono tnum" style={{ fontSize: 12, color, marginTop: 3, fontWeight: 500 }}>{value}</span>
    </div>
  );
}

function BrandMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
      <rect x="0.5" y="0.5" width="25" height="25" rx="4" stroke="var(--stroke-3)" fill="var(--bg-panel-hi)"/>
      <circle cx="13" cy="13" r="7" stroke="var(--signal-cool)" strokeWidth="0.8" opacity="0.6"/>
      <circle cx="13" cy="13" r="3.5" stroke="var(--signal-cool)" strokeWidth="0.8"/>
      <circle cx="13" cy="13" r="1.5" fill="var(--signal-cool)"/>
      <path d="M13 3 V6 M13 20 V23 M3 13 H6 M20 13 H23" stroke="var(--signal-cool)" strokeWidth="0.8" strokeLinecap="round" opacity="0.8"/>
    </svg>
  );
}

// ---------- Side rail (views) ----------
function SideRail({ view, setView }) {
  return (
    <div style={{
      width: 56, borderRight: '1px solid var(--stroke-2)',
      background: 'var(--bg-base)',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '12px 0', gap: 4,
    }}>
      {VIEWS.map(v => {
        const G = Glyph[v.glyph];
        const active = view === v.id;
        return (
          <button key={v.id}
            onClick={() => setView(v.id)}
            title={`${v.label} — ${v.desc}`}
            style={{
              width: 40, height: 40,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid ' + (active ? 'var(--stroke-hot)' : 'transparent'),
              background: active ? 'rgba(125,211,252,0.06)' : 'transparent',
              color: active ? 'var(--signal-cool)' : 'var(--fg-4)',
              borderRadius: 6,
              transition: 'all 120ms',
              position: 'relative',
            }}
          >
            <G />
            {active && <span style={{
              position: 'absolute', left: -1, top: 10, bottom: 10, width: 2,
              background: 'var(--signal-cool)', boxShadow: '0 0 8px var(--signal-cool)',
              borderRadius: 2,
            }}/>}
          </button>
        );
      })}

      <div style={{ flex: 1 }} />

      <button style={{
        width: 40, height: 40,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        border: '1px solid var(--stroke-2)', background: 'var(--bg-panel)',
        color: 'var(--fg-3)', borderRadius: 6,
        fontSize: 10,
      }} className="mono">⌘K</button>
    </div>
  );
}

Object.assign(window, { TitleBar, SideRail, VIEWS, ZOOM_LEVELS });
