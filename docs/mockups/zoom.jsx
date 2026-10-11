// ============================================
// AGENTIUM — Semantic Zoom Navigator
// The radical concept: same object, 5 levels of abstraction.
// ============================================

const ZOOM_SCALES = [
  { id: 0, name: 'PORTFOLIO', sub: 'Business outcomes' },
  { id: 1, name: 'CAPABILITY', sub: 'Customer Intelligence' },
  { id: 2, name: 'SYSTEM', sub: 'Sentiment Routing v4.2' },
  { id: 3, name: 'SKILL', sub: 'Semantic Extraction' },
  { id: 4, name: 'RUN', sub: 'RUN-8924A' },
];

function ZoomView({ onGoToSteering, onGoToRun }) {
  const [zoom, setZoom] = useState(2);

  return (
    <div style={{
      height: '100%', display: 'grid',
      gridTemplateRows: '1fr 72px',
      background: 'var(--bg-base)',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* grid bg */}
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: 'radial-gradient(circle at 50% 50%, var(--stroke-1) 1px, transparent 1px)',
        backgroundSize: '36px 36px', opacity: 0.5,
        pointerEvents: 'none',
      }}/>

      {/* stage */}
      <div style={{
        position: 'relative', overflow: 'hidden',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {/* left meta */}
        <div style={{ position: 'absolute', left: 28, top: 28, display: 'flex', flexDirection: 'column', gap: 10, zIndex: 2 }}>
          <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.16em', textTransform: 'uppercase' }}>Semantic Zoom</span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 28, color: 'var(--fg-1)', fontWeight: 300, letterSpacing: '-0.02em', lineHeight: 1 }}>{ZOOM_SCALES[zoom].name}</span>
            <span className="mono" style={{ fontSize: 11, color: 'var(--signal-cool)', letterSpacing: '0.04em' }}>{ZOOM_SCALES[zoom].sub}</span>
          </div>
        </div>

        {/* right meta */}
        <div style={{ position: 'absolute', right: 28, top: 28, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, zIndex: 2 }}>
          <Tag tone="cool">SAME OBJECT · DIFFERENT SCALE</Tag>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>Use ← → or scroll</span>
        </div>

        {/* The morphing scene */}
        <div style={{ width: '100%', maxWidth: 900, height: '100%', position: 'relative' }}>
          {zoom === 0 && <ScalePortfolio />}
          {zoom === 1 && <ScaleCapability />}
          {zoom === 2 && <ScaleSystem />}
          {zoom === 3 && <ScaleSkill onConfigure={onGoToSteering} />}
          {zoom === 4 && <ScaleRun onOpen={onGoToRun} />}
        </div>
      </div>

      {/* Zoom ladder */}
      <div style={{
        borderTop: '1px solid var(--stroke-2)',
        background: 'var(--bg-panel)',
        padding: '0 28px',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <button onClick={() => setZoom(Math.max(0, zoom-1))} disabled={zoom===0} style={zoomBtn(zoom===0)}><Glyph.ZoomOut /></button>
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: `repeat(${ZOOM_SCALES.length}, 1fr)`, gap: 6 }}>
          {ZOOM_SCALES.map((s, i) => (
            <button key={s.id} onClick={() => setZoom(i)} style={{
              display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
              padding: '8px 10px',
              background: i === zoom ? 'var(--bg-inset)' : 'transparent',
              border: '1px solid ' + (i === zoom ? 'var(--stroke-hot)' : 'var(--stroke-2)'),
              borderRadius: 4, cursor: 'pointer',
              transition: 'all 160ms',
            }}>
              <span className="mono" style={{ fontSize: 9, color: i === zoom ? 'var(--signal-cool)' : 'var(--fg-5)', letterSpacing: '0.12em' }}>L{i}</span>
              <span className="mono" style={{ fontSize: 11, color: i === zoom ? 'var(--fg-1)' : 'var(--fg-3)', marginTop: 2, letterSpacing: '0.04em' }}>{s.name}</span>
            </button>
          ))}
        </div>
        <button onClick={() => setZoom(Math.min(4, zoom+1))} disabled={zoom===4} style={zoomBtn(zoom===4)}><Glyph.ZoomIn /></button>
      </div>
    </div>
  );
}

function zoomBtn(disabled) {
  return {
    width: 36, height: 36,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)',
    color: disabled ? 'var(--fg-5)' : 'var(--fg-2)',
    borderRadius: 4, cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1,
  };
}

// ——— L0: PORTFOLIO ———
function ScalePortfolio() {
  const caps = [
    { name: 'Customer Intelligence', x: 0.2, y: 0.35, r: 62, roi: 840, tone: 'pos' },
    { name: 'Contract Analysis',     x: 0.55, y: 0.22, r: 48, roi: 620, tone: 'pos' },
    { name: 'Lead Scoring',          x: 0.78, y: 0.45, r: 40, roi: 410, tone: 'cool' },
    { name: 'Invoice Recon',         x: 0.35, y: 0.68, r: 32, roi: 305, tone: 'cool' },
    { name: 'Fraud Detection',       x: 0.65, y: 0.72, r: 28, roi: 178, tone: 'warn' },
  ];
  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <svg viewBox="0 0 900 600" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
        {/* axes */}
        <line x1="40" y1="570" x2="860" y2="570" stroke="var(--stroke-2)"/>
        <line x1="40" y1="40" x2="40" y2="570" stroke="var(--stroke-2)"/>
        <text x="860" y="590" fill="var(--fg-5)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.12em" textAnchor="end">COMPUTE COST →</text>
        <text x="28" y="40" fill="var(--fg-5)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.12em" transform="rotate(-90, 28, 40)">VALUE ↑</text>

        {caps.map((c, i) => (
          <g key={i} transform={`translate(${40 + c.x*800}, ${40 + c.y*520})`}>
            <circle r={c.r} fill={`var(--signal-${c.tone})`} opacity="0.08"/>
            <circle r={c.r} fill="none" stroke={`var(--signal-${c.tone})`} strokeWidth="1" opacity="0.6"/>
            <circle r={3} fill={`var(--signal-${c.tone})`} style={{ filter: `drop-shadow(0 0 6px var(--signal-${c.tone}))`}}/>
            <text x={c.r+8} y="0" fill="var(--fg-1)" fontSize="12" fontFamily="var(--font-sans)" dominantBaseline="middle">{c.name}</text>
            <text x={c.r+8} y="14" fill={`var(--signal-${c.tone})`} fontSize="11" fontFamily="var(--font-mono)" dominantBaseline="middle">{c.roi}% ROI</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ——— L1: CAPABILITY ———
function ScaleCapability() {
  const systems = [
    { name: 'Sentiment Routing', v: 4.2, runs: '1.2M', lat: 420, yield: '+840%', focus: true },
    { name: 'Intent Classifier', v: 3.1, runs: '890k', lat: 280, yield: '+620%' },
    { name: 'Response Generator', v: 2.8, runs: '640k', lat: 1200, yield: '+410%' },
    { name: 'Escalation Engine', v: 1.9, runs: '180k', lat: 50, yield: '+180%' },
  ];
  return (
    <div style={{ position: 'absolute', inset: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14, width: '100%', maxWidth: 700 }}>
        {systems.map((s, i) => (
          <div key={i} style={{
            padding: 18,
            background: s.focus ? 'var(--bg-inset)' : 'var(--bg-panel)',
            border: '1px solid ' + (s.focus ? 'var(--stroke-hot)' : 'var(--stroke-2)'),
            borderRadius: 6,
            boxShadow: s.focus ? 'var(--glow-cool)' : 'none',
            position: 'relative',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--fg-1)', fontWeight: 500 }}>{s.name}</div>
                <div className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 3 }}>v{s.v} · {s.runs} runs/mo</div>
              </div>
              <Tag tone="pos">{s.yield}</Tag>
            </div>
            <div style={{ marginTop: 14, display: 'flex', gap: 16 }}>
              <MiniStat label="p95 LAT" v={`${s.lat}ms`} />
              <MiniStat label="VOLUME" v={s.runs} />
              <MiniStat label="YIELD" v={s.yield} color="var(--signal-pos)" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ——— L2: SYSTEM ———
function ScaleSystem() {
  return (
    <div style={{ position: 'absolute', inset: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg viewBox="0 0 800 400" width="100%" height="100%" style={{ maxWidth: 900 }}>
        <defs>
          <marker id="arrow-c" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6" fill="var(--stroke-3)"/>
          </marker>
        </defs>
        {/* nodes */}
        {[
          { x: 80,  y: 180, label: 'Trigger',       sub: 'Webhook', tone: 'violet' },
          { x: 250, y: 100, label: 'OCR',           sub: '98% conf', tone: 'pos' },
          { x: 250, y: 260, label: 'Semantic Ext.', sub: 'GPT-4o',   tone: 'cool', focus: true },
          { x: 440, y: 180, label: 'Router',        sub: '3 paths',  tone: 'violet' },
          { x: 620, y: 80,  label: 'HITL',          sub: '0.12 autonomy', tone: 'warn' },
          { x: 620, y: 180, label: 'Emit',          sub: '+98.2% acc',   tone: 'pos' },
          { x: 620, y: 280, label: 'Escalate',      sub: 'priority',     tone: 'neg' },
        ].map((n, i) => (
          <g key={i} transform={`translate(${n.x}, ${n.y})`}>
            {n.focus && <rect x="-70" y="-26" width="140" height="52" rx="6" fill="none" stroke={`var(--signal-${n.tone})`} strokeWidth="1.5" opacity="0.4" style={{ filter: `drop-shadow(0 0 8px var(--signal-${n.tone}))` }}/>}
            <rect x="-64" y="-22" width="128" height="44" rx="4" fill="var(--bg-panel)" stroke={`var(--stroke-${n.focus ? '3' : '2'})`}/>
            <circle cx="-48" cy="0" r="3" fill={`var(--signal-${n.tone})`} style={{ filter: `drop-shadow(0 0 4px var(--signal-${n.tone}))` }}/>
            <text x="-36" y="-3" fill="var(--fg-1)" fontSize="11" fontFamily="var(--font-sans)" fontWeight="500">{n.label}</text>
            <text x="-36" y="11" fill="var(--fg-4)" fontSize="9" fontFamily="var(--font-mono)">{n.sub}</text>
          </g>
        ))}
        {/* edges */}
        {[
          ['80,180', '250,100'], ['80,180', '250,260'],
          ['250,100', '440,180'], ['250,260', '440,180'],
          ['440,180', '620,80'], ['440,180', '620,180'], ['440,180', '620,280'],
        ].map(([a, b], i) => (
          <line key={i} x1={parseInt(a.split(',')[0])+64} y1={a.split(',')[1]} x2={parseInt(b.split(',')[0])-64} y2={b.split(',')[1]}
            stroke="var(--stroke-3)" strokeWidth="1" markerEnd="url(#arrow-c)"/>
        ))}
        {/* data packet on hot edge */}
        <circle r="3" fill="var(--signal-cool)" style={{ filter: 'drop-shadow(0 0 6px var(--signal-cool))' }}>
          <animateMotion dur="2.8s" repeatCount="indefinite"
            path="M314,260 L376,180"/>
        </circle>
      </svg>
    </div>
  );
}

// ——— L3: SKILL ———
function ScaleSkill({ onConfigure }) {
  return (
    <div style={{ position: 'absolute', inset: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: '100%', maxWidth: 620, display: 'grid', gap: 14 }}>
        <div style={{ padding: 20, background: 'var(--bg-panel)', border: '1px solid var(--stroke-3)', borderRadius: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div>
              <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.14em' }}>SKILL · LLM NODE</div>
              <div style={{ fontSize: 20, color: 'var(--fg-1)', fontWeight: 400, marginTop: 4 }}>Semantic Extraction</div>
            </div>
            <Tag tone="cool">GPT-4o · t=0.2</Tag>
          </div>
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
            <Metric label="p50" v="240ms" />
            <Metric label="p95" v="420ms" />
            <Metric label="Conf." v="98.2%" color="var(--signal-pos)" />
            <Metric label="$/call" v="$0.002" />
          </div>
        </div>
        <div style={{ padding: 16, background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)', lineHeight: 1.7 }}>
          <span style={{ color: 'var(--signal-violet)' }}>system</span>:<br/>
          You are an expert financial analyst.<br/>
          Extract: <span style={{ color: 'var(--signal-cool)' }}>[company, revenue_q3, risk_factors]</span>
        </div>
        <button onClick={onConfigure} style={{
          padding: '10px 14px', background: 'var(--signal-cool)', color: 'var(--bg-void)',
          border: 'none', borderRadius: 4, fontWeight: 500, fontSize: 12, letterSpacing: '0.02em',
          justifySelf: 'start',
        }}>Open Steering →</button>
      </div>
    </div>
  );
}

// ——— L4: RUN ———
function ScaleRun({ onOpen }) {
  return (
    <div style={{ position: 'absolute', inset: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: '100%', maxWidth: 620, padding: 22, background: 'var(--bg-panel)', border: '1px solid var(--stroke-3)', borderRadius: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div>
            <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.14em' }}>RUN · INVOCATION</div>
            <div style={{ fontSize: 20, color: 'var(--fg-1)', fontWeight: 400, marginTop: 4 }}>RUN-8924A</div>
          </div>
          <Tag tone="pos">COMPLETED · 1.42s</Tag>
        </div>
        <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
          <Metric label="Items" v="42" />
          <Metric label="Cost" v="$0.04" />
          <Metric label="Saved" v="~15m" color="var(--signal-pos)" />
          <Metric label="Conf." v="98.2%" color="var(--signal-pos)" />
        </div>
        <button onClick={onOpen} style={{
          marginTop: 18, padding: '10px 14px', background: 'transparent', color: 'var(--signal-cool)',
          border: '1px solid var(--signal-cool)', borderRadius: 4, fontSize: 12, letterSpacing: '0.02em',
        }}>Inspect execution trace →</button>
      </div>
    </div>
  );
}

function MiniStat({ label, v, color = 'var(--fg-1)' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="mono" style={{ fontSize: 8, color: 'var(--fg-5)', letterSpacing: '0.12em' }}>{label}</span>
      <span className="mono tnum" style={{ fontSize: 13, color }}>{v}</span>
    </div>
  );
}

function Metric({ label, v, color = 'var(--fg-1)' }) {
  return (
    <div style={{ padding: '10px 12px', background: 'var(--bg-inset)', borderRadius: 4, border: '1px solid var(--stroke-1)' }}>
      <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>{label}</div>
      <div className="mono tnum" style={{ fontSize: 15, color, marginTop: 4 }}>{v}</div>
    </div>
  );
}

Object.assign(window, { ZoomView });
