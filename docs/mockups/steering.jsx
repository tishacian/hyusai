// ============================================
// AGENTIUM — Steering Cockpit (Control Plane)
// Three variants of the same control surface:
//  A. Linear sliders with impact ghosts (conservative)
//  B. Radial dials (aircraft cockpit)
//  C. 2D tradeoff space (direct manipulation)
// ============================================

function SteeringView() {
  const [variant, setVariant] = useState('A');
  const [params, setParams] = useState({
    resource: 0.65,     // 0 = lean, 1 = deep
    velocity: 0.82,     // 0 = thorough, 1 = rapid
    autonomy: 0.30,     // 0 = HITL, 1 = full autonomy
  });

  // Baseline values; deltas react live to params
  const baseline = { roi: 482, cost: 2.94, risk: 0.12, latency: 420 };
  const projected = useMemo(() => {
    const r = params.resource, v = params.velocity, a = params.autonomy;
    // Simple deterministic model — enough to feel alive
    const roiDelta = (r - 0.5)*8 + (a - 0.3)*6 - (v - 0.5)*2;
    const costDelta = (r - 0.5)*14 + (a - 0.3)*(-8) + (v - 0.5)*(-6);
    const riskDelta = (a - 0.3)*0.18 + (v - 0.5)*0.08 - (r - 0.5)*0.04;
    const latDelta = (v - 0.5)*(-180) + (r - 0.5)*40;
    return {
      roi: baseline.roi * (1 + roiDelta/100),
      cost: baseline.cost * (1 + costDelta/100),
      risk: Math.max(0.02, Math.min(0.95, baseline.risk + riskDelta)),
      latency: Math.max(60, baseline.latency + latDelta),
      roiDelta, costDelta, riskDelta, latDelta,
    };
  }, [params]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 420px', gap: 1, height: '100%', background: 'var(--stroke-2)' }}>
      {/* — MAIN — */}
      <div style={{ background: 'var(--bg-base)', padding: '24px 32px', overflow: 'auto', position: 'relative' }}>
        {/* ambient grid */}
        <div style={{
          position: 'absolute', inset: 0, opacity: 0.25,
          backgroundImage: 'linear-gradient(var(--stroke-1) 1px, transparent 1px), linear-gradient(90deg, var(--stroke-1) 1px, transparent 1px)',
          backgroundSize: '48px 48px', pointerEvents: 'none',
        }}/>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6, position: 'relative' }}>
          <div>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.16em' }}>CONTROL PLANE</span>
            <h1 style={{ fontSize: 32, color: 'var(--fg-1)', fontWeight: 300, margin: '6px 0 0', letterSpacing: '-0.02em' }}>Steering · Sentiment Routing</h1>
            <p style={{ color: 'var(--fg-3)', fontSize: 13, margin: '8px 0 0', maxWidth: 520 }}>Adjust operational parameters in real-time. Changes propagate to live traffic within 300ms.</p>
          </div>
          <div style={{ display: 'flex', gap: 2, padding: 3, background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4 }}>
            {['A','B','C'].map(v => (
              <button key={v} onClick={() => setVariant(v)} style={{
                padding: '6px 12px', fontSize: 11, fontWeight: 500, letterSpacing: '0.04em',
                background: variant === v ? 'var(--bg-panel-hi)' : 'transparent',
                color: variant === v ? 'var(--signal-cool)' : 'var(--fg-3)',
                border: '1px solid ' + (variant === v ? 'var(--stroke-hot)' : 'transparent'),
                borderRadius: 3,
              }} className="mono">VAR · {v}</button>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 28, position: 'relative' }}>
          {variant === 'A' && <LinearVariant params={params} setParams={setParams} />}
          {variant === 'B' && <RadialVariant params={params} setParams={setParams} />}
          {variant === 'C' && <SpatialVariant params={params} setParams={setParams} />}
        </div>

        {/* Terminal */}
        <div style={{ marginTop: 32, padding: '16px 18px', background: 'var(--bg-code)', border: '1px solid var(--stroke-2)', borderRadius: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em' }}>LIVE OUTPUT STREAM</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="live-dot cool"/><span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>LIVE</span></div>
          </div>
          <div className="mono" style={{ fontSize: 11, lineHeight: 1.9, color: 'var(--fg-3)' }}>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:01 →</span> Modifying parameter <span style={{ color: 'var(--signal-cool)' }}>[resource_allocation]</span> to {params.resource.toFixed(2)}</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:01 →</span> Re-balancing compute clusters across 8 regions</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:02 ✓</span> <span style={{ color: 'var(--signal-pos)' }}>Validation passed.</span> Latency expected: {Math.round(projected.latency)}ms</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:02 →</span> Shadow-running 12,400 requests against new params...</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:03 ✓</span> <span style={{ color: 'var(--signal-pos)' }}>ROI delta confirmed:</span> <span style={{ color: 'var(--signal-pos)' }}>{fmt.pct(projected.roiDelta)}</span></div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:04 →</span> Awaiting commit authorization...</div>
          </div>
        </div>
      </div>

      {/* — IMPACT PROJECTION — */}
      <div style={{ background: 'var(--bg-panel)', padding: '24px 22px', overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.14em' }}>IMPACT PROJECTION</span>
          <Tag tone="cool">LIVE</Tag>
        </div>
        <div style={{ fontSize: 11, color: 'var(--fg-4)', marginBottom: 18 }}>Predicted deltas · next 24h rolling window</div>

        <ImpactCard
          label="Projected ROI"
          base={`${baseline.roi.toFixed(0)}%`}
          projected={`${projected.roi.toFixed(0)}%`}
          delta={fmt.pct(projected.roiDelta, 1)}
          tone={projected.roiDelta >= 0 ? 'pos' : 'neg'}
        />
        <ImpactCard
          label="Compute cost"
          base={`${fmt.money(baseline.cost*1e6)}/mo`}
          projected={`${fmt.money(projected.cost*1e6)}/mo`}
          delta={fmt.pct(projected.costDelta, 1)}
          tone={projected.costDelta <= 0 ? 'pos' : 'warn'}
          invert
        />
        <ImpactCard
          label="p95 Latency"
          base={`${Math.round(baseline.latency)}ms`}
          projected={`${Math.round(projected.latency)}ms`}
          delta={`${projected.latDelta >= 0 ? '+' : ''}${Math.round(projected.latDelta)}ms`}
          tone={projected.latDelta <= 0 ? 'pos' : 'warn'}
          invert
        />
        <ImpactCard
          label="Anomaly risk"
          base={`${(baseline.risk*100).toFixed(1)}%`}
          projected={`${(projected.risk*100).toFixed(1)}%`}
          delta={`${projected.riskDelta >= 0 ? '+' : ''}${(projected.riskDelta*100).toFixed(1)}pp`}
          tone={projected.riskDelta <= 0 ? 'pos' : 'neg'}
          invert
        />

        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button style={{
            flex: 1, padding: '12px', background: 'var(--signal-cool)', color: 'var(--bg-void)',
            border: 'none', borderRadius: 4, fontWeight: 500, fontSize: 12, letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>Commit Topology</button>
          <button style={{
            padding: '12px 14px', background: 'transparent', color: 'var(--fg-3)',
            border: '1px solid var(--stroke-2)', borderRadius: 4, fontSize: 12,
          }}>Revert</button>
        </div>

        <div style={{ marginTop: 24, padding: '12px 14px', background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ color: 'var(--signal-violet)', marginTop: 2 }}><Glyph.Bolt /></span>
          <div>
            <div style={{ fontSize: 12, color: 'var(--fg-2)', fontWeight: 500 }}>AI recommendation</div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', marginTop: 4, lineHeight: 1.5 }}>Raise <span style={{ color: 'var(--signal-cool)' }}>autonomy</span> to 0.45 and lower <span style={{ color: 'var(--signal-cool)' }}>velocity</span> to 0.70. Est. +$4.2k/mo saved with nominal risk shift.</div>
            <button style={{
              marginTop: 10, padding: '4px 8px', background: 'transparent',
              border: '1px solid var(--stroke-3)', borderRadius: 3, color: 'var(--fg-2)', fontSize: 10, letterSpacing: '0.08em',
            }} className="mono">APPLY →</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ImpactCard({ label, base, projected, delta, tone = 'pos', invert }) {
  return (
    <div style={{ padding: '14px 14px', background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 6, marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>{label}</span>
        <span className="mono tnum" style={{ fontSize: 11, color: `var(--signal-${tone})`, fontWeight: 500 }}>{delta}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 10 }}>
        <span className="mono tnum" style={{ fontSize: 10, color: 'var(--fg-5)', textDecoration: 'line-through' }}>{base}</span>
        <span style={{ color: 'var(--fg-5)' }}>→</span>
        <span className="mono tnum" style={{ fontSize: 20, color: 'var(--fg-1)', fontWeight: 400 }}>{projected}</span>
      </div>
    </div>
  );
}

// ——— VARIANT A: LINEAR ———
function LinearVariant({ params, setParams }) {
  const rows = [
    { key: 'resource', label: 'Resource allocation', sub: 'Compute depth vs operational budget', left: 'LEAN', right: 'DEEP', tone: 'cool' },
    { key: 'velocity', label: 'Execution velocity', sub: 'Response threshold vs analytical depth', left: 'THOROUGH', right: 'RAPID', tone: 'violet' },
    { key: 'autonomy', label: 'Autonomy threshold', sub: 'Human intervention required per action', left: 'HITL', right: 'FULL', tone: 'warn' },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
      {rows.map(r => {
        const val = params[r.key];
        return (
          <div key={r.key}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 15, color: 'var(--fg-1)', fontWeight: 500 }}>{r.label}</div>
                <div style={{ fontSize: 11, color: 'var(--fg-4)', marginTop: 3 }}>{r.sub}</div>
              </div>
              <Tag tone={r.tone}>{(val*100).toFixed(0)}%</Tag>
            </div>
            <div style={{ position: 'relative', height: 36, display: 'flex', alignItems: 'center' }}>
              <div style={{ position: 'absolute', left: 0, right: 0, height: 2, background: 'var(--stroke-2)' }}/>
              <div style={{ position: 'absolute', left: 0, width: `${val*100}%`, height: 2, background: `var(--signal-${r.tone})`, boxShadow: `0 0 12px var(--signal-${r.tone})` }}/>
              {/* ghost original */}
              <div style={{ position: 'absolute', left: 0, width: '50%', height: 6, top: '50%', marginTop: -3, borderLeft: '1px dashed var(--stroke-3)', borderRight: '1px dashed var(--stroke-3)', pointerEvents: 'none' }}/>
              <input type="range" min="0" max="1" step="0.01" value={val}
                onChange={e => setParams(p => ({...p, [r.key]: parseFloat(e.target.value)}))}
                style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%' }}/>
              {/* thumb */}
              <div style={{
                position: 'absolute', left: `${val*100}%`, width: 16, height: 16,
                marginLeft: -8, borderRadius: '50%', background: 'var(--fg-1)',
                border: `2px solid var(--signal-${r.tone})`,
                boxShadow: `0 0 12px var(--signal-${r.tone})`,
                pointerEvents: 'none',
              }}/>
              {/* ticks */}
              {[0,0.25,0.5,0.75,1].map(t => (
                <span key={t} style={{ position: 'absolute', left: `${t*100}%`, width: 1, height: 6, background: 'var(--stroke-3)', bottom: 6 }}/>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
              <span className="mono" style={{ fontSize: 9, color: 'var(--fg-5)', letterSpacing: '0.12em' }}>{r.left}</span>
              <span className="mono" style={{ fontSize: 9, color: 'var(--fg-5)', letterSpacing: '0.12em' }}>{r.right}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ——— VARIANT B: RADIAL DIALS ———
function RadialVariant({ params, setParams }) {
  const dials = [
    { key: 'resource', label: 'RESOURCE', sub: 'Lean → Deep', tone: 'cool' },
    { key: 'velocity', label: 'VELOCITY', sub: 'Thorough → Rapid', tone: 'violet' },
    { key: 'autonomy', label: 'AUTONOMY', sub: 'HITL → Full', tone: 'warn' },
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20 }}>
      {dials.map(d => <Dial key={d.key} d={d} val={params[d.key]} onChange={v => setParams(p => ({...p, [d.key]: v}))}/>)}
    </div>
  );
}

function Dial({ d, val, onChange }) {
  const size = 220;
  const r = size/2 - 22;
  const cx = size/2, cy = size/2;
  // arc from -135° to +135° (270° sweep)
  const start = -135 * Math.PI/180, end = 135 * Math.PI/180;
  const cur = start + val * (end - start);
  const startPt = { x: cx + r*Math.cos(start), y: cy + r*Math.sin(start) };
  const endPt = { x: cx + r*Math.cos(end), y: cy + r*Math.sin(end) };
  const curPt = { x: cx + r*Math.cos(cur), y: cy + r*Math.sin(cur) };
  const arc = (from, to) => {
    const fp = { x: cx + r*Math.cos(from), y: cy + r*Math.sin(from) };
    const tp = { x: cx + r*Math.cos(to), y: cy + r*Math.sin(to) };
    const large = (to - from) > Math.PI ? 1 : 0;
    return `M ${fp.x} ${fp.y} A ${r} ${r} 0 ${large} 1 ${tp.x} ${tp.y}`;
  };
  return (
    <div style={{ padding: 18, background: 'var(--bg-panel)', border: '1px solid var(--stroke-2)', borderRadius: 8, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width={size} height={size} style={{ cursor: 'pointer' }}
        onMouseDown={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const handle = (mv) => {
            const dx = mv.clientX - (rect.left + cx), dy = mv.clientY - (rect.top + cy);
            let ang = Math.atan2(dy, dx);
            if (ang < start) ang = start;
            if (ang > end) ang = end;
            if (ang < -Math.PI/2 && dx < 0 && dy > 0) ang = end;
            const v = Math.max(0, Math.min(1, (ang - start) / (end - start)));
            onChange(v);
          };
          handle(e);
          window.addEventListener('mousemove', handle);
          window.addEventListener('mouseup', () => window.removeEventListener('mousemove', handle), { once: true });
        }}>
        <path d={arc(start, end)} stroke="var(--stroke-2)" strokeWidth="2" fill="none"/>
        <path d={arc(start, cur)} stroke={`var(--signal-${d.tone})`} strokeWidth="3" fill="none" style={{ filter: `drop-shadow(0 0 6px var(--signal-${d.tone}))` }}/>
        {/* ticks */}
        {Array.from({ length: 27 }, (_, i) => {
          const a = start + (i/26)*(end - start);
          const r1 = r+5, r2 = r + (i % 5 === 0 ? 12 : 8);
          return <line key={i} x1={cx + r1*Math.cos(a)} y1={cy + r1*Math.sin(a)} x2={cx + r2*Math.cos(a)} y2={cy + r2*Math.sin(a)} stroke="var(--stroke-3)" strokeWidth={i % 5 === 0 ? 1.2 : 0.8}/>;
        })}
        {/* needle */}
        <line x1={cx} y1={cy} x2={curPt.x} y2={curPt.y} stroke={`var(--signal-${d.tone})`} strokeWidth="2" strokeLinecap="round" style={{ filter: `drop-shadow(0 0 4px var(--signal-${d.tone}))` }}/>
        <circle cx={cx} cy={cy} r="22" fill="var(--bg-inset)" stroke="var(--stroke-3)"/>
        <circle cx={cx} cy={cy} r="4" fill={`var(--signal-${d.tone})`}/>
        <text x={cx} y={cy+50} textAnchor="middle" fill={`var(--signal-${d.tone})`} fontSize="22" fontFamily="var(--font-mono)" fontWeight="300">{(val*100).toFixed(0)}</text>
        <text x={cx} y={cy+68} textAnchor="middle" fill="var(--fg-5)" fontSize="10" fontFamily="var(--font-mono)" letterSpacing="0.2em">%</text>
      </svg>
      <div className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.16em', marginTop: 8 }}>{d.label}</div>
      <div style={{ fontSize: 10, color: 'var(--fg-5)', marginTop: 4 }}>{d.sub}</div>
    </div>
  );
}

// ——— VARIANT C: SPATIAL ———
function SpatialVariant({ params, setParams }) {
  const boxRef = useRef(null);
  const onDrag = (e) => {
    const rect = boxRef.current.getBoundingClientRect();
    const handle = (mv) => {
      const x = Math.max(0, Math.min(1, (mv.clientX - rect.left) / rect.width));
      const y = Math.max(0, Math.min(1, 1 - (mv.clientY - rect.top) / rect.height));
      setParams(p => ({ ...p, resource: y, velocity: x }));
    };
    handle(e);
    window.addEventListener('mousemove', handle);
    window.addEventListener('mouseup', () => window.removeEventListener('mousemove', handle), { once: true });
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 20 }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.14em' }}>TRADEOFF SURFACE · DRAG TO STEER</span>
          <Tag>VELOCITY × RESOURCE</Tag>
        </div>
        <div ref={boxRef} onMouseDown={onDrag} style={{
          position: 'relative', aspectRatio: '1.3 / 1', background: 'var(--bg-inset)',
          border: '1px solid var(--stroke-2)', borderRadius: 6, cursor: 'crosshair', overflow: 'hidden',
        }}>
          {/* gradient heat */}
          <div style={{ position: 'absolute', inset: 0,
            background: 'radial-gradient(circle at 70% 30%, rgba(52,211,153,0.18), transparent 50%), radial-gradient(circle at 20% 80%, rgba(239,90,111,0.14), transparent 50%)',
          }}/>
          {/* grid */}
          <div style={{ position: 'absolute', inset: 0,
            backgroundImage: 'linear-gradient(var(--stroke-1) 1px, transparent 1px), linear-gradient(90deg, var(--stroke-1) 1px, transparent 1px)',
            backgroundSize: '10% 10%',
          }}/>
          {/* current point */}
          <div style={{
            position: 'absolute', left: `${params.velocity*100}%`, top: `${(1-params.resource)*100}%`,
            width: 16, height: 16, marginLeft: -8, marginTop: -8, borderRadius: '50%',
            background: 'var(--fg-1)', border: '2px solid var(--signal-cool)',
            boxShadow: '0 0 16px var(--signal-cool)',
          }}/>
          {/* crosshairs */}
          <div style={{ position: 'absolute', left: `${params.velocity*100}%`, top: 0, bottom: 0, width: 1, background: 'rgba(125,211,252,0.3)' }}/>
          <div style={{ position: 'absolute', top: `${(1-params.resource)*100}%`, left: 0, right: 0, height: 1, background: 'rgba(125,211,252,0.3)' }}/>
          {/* axis labels */}
          <span className="mono" style={{ position: 'absolute', top: 8, left: 10, fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>DEEP COMPUTE</span>
          <span className="mono" style={{ position: 'absolute', bottom: 8, left: 10, fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>LEAN</span>
          <span className="mono" style={{ position: 'absolute', bottom: 8, right: 10, fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>RAPID →</span>
          <span className="mono" style={{ position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)', fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>THOROUGH</span>
          {/* zones */}
          <span className="mono" style={{ position: 'absolute', top: '20%', right: '18%', fontSize: 9, color: 'var(--signal-pos)', letterSpacing: '0.12em' }}>OPTIMAL</span>
          <span className="mono" style={{ position: 'absolute', bottom: '20%', left: '14%', fontSize: 9, color: 'var(--signal-neg)', letterSpacing: '0.12em' }}>STARVED</span>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ padding: 12, background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4 }}>
          <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>AUTONOMY</div>
          <input type="range" min="0" max="1" step="0.01" value={params.autonomy}
            onChange={e => setParams(p => ({...p, autonomy: parseFloat(e.target.value)}))}
            style={{ width: '100%', marginTop: 10, accentColor: '#f5b84a' }}/>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="mono" style={{ fontSize: 9, color: 'var(--fg-5)' }}>HITL</span>
            <span className="mono tnum" style={{ fontSize: 12, color: 'var(--signal-warn)' }}>{(params.autonomy*100).toFixed(0)}%</span>
            <span className="mono" style={{ fontSize: 9, color: 'var(--fg-5)' }}>FULL</span>
          </div>
        </div>
        <div style={{ padding: 12, background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4 }}>
          <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>PRESETS</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
            {[['Precision', 0.85, 0.25, 0.15], ['Balanced', 0.55, 0.60, 0.35], ['Throughput', 0.30, 0.90, 0.60]].map(([name, r, v, a]) => (
              <button key={name} onClick={() => setParams({ resource: r, velocity: v, autonomy: a })} style={{
                textAlign: 'left', padding: '6px 8px', background: 'transparent',
                border: '1px solid var(--stroke-2)', borderRadius: 3, color: 'var(--fg-2)', fontSize: 11,
              }}>{name}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SteeringView });
