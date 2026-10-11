// ============================================
// AGENTIUM — Hypervisor (Executive Cockpit)
// The hero view. Decision interface, not dashboard.
// ============================================

function Hypervisor({ systemState }) {
  const netValue = useLiveNumber(14.2e6, { jitter: 0.003, interval: 2400 });
  const roi = useLiveNumber(482, { jitter: 0.008, interval: 2000 });
  const cost = useLiveNumber(2.94e6, { jitter: 0.004, interval: 2600 });
  const vpc = useLiveNumber(4.83, { jitter: 0.006, interval: 2200 });

  // Main sparkline (value curve)
  const curve = useMemo(() => Array.from({ length: 80 }, (_, i) => {
    const t = i / 80;
    return 7 + 3*Math.sin(t * 6) + 4*t + Math.random()*0.4;
  }), []);

  const capabilities = [
    { name: 'Customer Intelligence', roi: 840, value: 6.2e6, cost: 740e3, conf: 0.98, trend: [4,5,5,6,7,7,8,8,9,9,10,10,11,12,13,13,14], status: 'compounding' },
    { name: 'Contract Analysis',     roi: 620, value: 3.8e6, cost: 610e3, conf: 0.94, trend: [3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,12], status: 'stable' },
    { name: 'Lead Scoring',          roi: 410, value: 2.4e6, cost: 590e3, conf: 0.91, trend: [6,6,5,5,6,7,7,6,7,7,8,8,9,9,9,10,10], status: 'stable' },
    { name: 'Invoice Reconciliation',roi: 305, value: 1.1e6, cost: 360e3, conf: 0.89, trend: [5,5,6,5,6,6,7,6,7,7,7,8,8,8,8,9,9], status: 'warming' },
    { name: 'Fraud Detection',       roi: 178, value: 0.7e6, cost: 400e3, conf: 0.82, trend: [6,5,6,6,5,6,5,6,6,7,6,7,7,7,7,7,8], status: 'review' },
  ];

  const signals = [
    { t: '0s',  txt: 'Autonomy threshold raised on Sentiment.Routing', tone: 'violet' },
    { t: '12s', txt: 'Anomaly cleared: Triage p95 latency returned to 420ms', tone: 'pos' },
    { t: '48s', txt: 'Lead Scoring ROI crossed +410% band', tone: 'pos' },
    { t: '2m',  txt: 'Compute budget 65% consumed — projected to finish at 89%', tone: 'warn' },
    { t: '4m',  txt: 'New skill deployed: Vendor.ID.Normalizer (shadow)', tone: 'cool' },
    { t: '9m',  txt: 'Fraud Detection confidence dropped below 0.85', tone: 'neg' },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 360px',
      gridTemplateRows: '280px 1fr',
      gap: 1,
      height: '100%',
      background: 'var(--stroke-2)',
    }}>
      {/* === HERO: VALUE PANEL === */}
      <div style={{
        gridColumn: '1', gridRow: '1',
        background: 'var(--bg-base)',
        padding: '24px 28px',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* ambient grid */}
        <div style={{
          position: 'absolute', inset: 0, opacity: 0.3,
          backgroundImage: 'linear-gradient(var(--stroke-1) 1px, transparent 1px), linear-gradient(90deg, var(--stroke-1) 1px, transparent 1px)',
          backgroundSize: '48px 48px', pointerEvents: 'none',
        }} />

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4, position: 'relative' }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>Net Value Generated</span>
          <Tag tone="cool">QTD · Q2 · LIVE</Tag>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 32, position: 'relative' }}>
          <div style={{
            fontSize: 84, fontWeight: 300, lineHeight: 0.9,
            letterSpacing: '-0.04em', color: 'var(--fg-1)',
            fontFeatureSettings: '"tnum"',
          }} className="tnum">
            {fmt.money(netValue)}
          </div>
          <div style={{ paddingBottom: 14, display: 'flex', gap: 20 }}>
            <StatReadout label="ROI" value={`${roi.toFixed(0)}%`} delta="+120bps" color="var(--signal-pos)" />
            <StatReadout label="Cost" value={fmt.money(cost)} delta="65% of budget" color="var(--signal-violet)" />
            <StatReadout label="$/compute" value={`${vpc.toFixed(2)}×`} delta="+0.14× WoW" color="var(--signal-cool)" />
          </div>
        </div>

        {/* main curve */}
        <div style={{ marginTop: 28, position: 'relative' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>Value curve · 90d</span>
            <div style={{ display: 'flex', gap: 14 }}>
              <CurveKey color="var(--signal-cool)" label="Value" />
              <CurveKey color="var(--signal-violet)" label="Cost" dashed />
              <CurveKey color="var(--signal-pos)" label="Net" />
            </div>
          </div>
          <ValueCurve height={130} />
        </div>
      </div>

      {/* === RIGHT RAIL: AI BALANCE SHEET === */}
      <div style={{
        gridColumn: '2', gridRow: '1 / 3',
        background: 'var(--bg-panel)',
        padding: '22px 22px',
        display: 'flex', flexDirection: 'column',
        overflow: 'auto',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-1)' }}>AI Balance Sheet</span>
          <Tag>T-24H</Tag>
        </div>

        <Section title="Assets · Value Created" tone="pos" total="+$8.8M">
          <LedgerLine name="Revenue acceleration" sub="Customer Intelligence" v="+$4.2M" pct={48} tone="pos" />
          <LedgerLine name="Labor hour savings" sub="Contract · Invoice · Triage" v="+$3.1M" pct={35} tone="pos" />
          <LedgerLine name="Risk avoidance" sub="Fraud · Compliance" v="+$1.5M" pct={17} tone="pos" />
        </Section>

        <Section title="Liabilities · Operating" tone="neg" total="−$2.9M">
          <LedgerLine name="LLM inference" sub="1.4B tokens · mixed" v="−$1.8M" pct={62} tone="neg" />
          <LedgerLine name="Vector storage" sub="4.2B embeddings" v="−$0.6M" pct={21} tone="neg" />
          <LedgerLine name="Orchestration" sub="Control plane · HITL" v="−$0.5M" pct={17} tone="neg" />
        </Section>

        <div style={{
          marginTop: 8, padding: '14px 14px',
          background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)',
          borderRadius: 'var(--radius-md)',
          display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>Net position</span>
            <Tag tone="pos">+482% ROI</Tag>
          </div>
          <div className="tnum" style={{ fontSize: 28, fontWeight: 300, color: 'var(--fg-1)', letterSpacing: '-0.02em' }}>
            +{fmt.money(netValue - cost)}
          </div>
          <Spark data={curve} color="var(--signal-pos)" height={40} width={300} />
        </div>

        <div style={{ marginTop: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>Signal stream</span>
            <span className="live-dot" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {signals.map((s, i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '36px 10px 1fr',
                gap: 8, padding: '6px 0',
                borderTop: i === 0 ? 'none' : '1px solid var(--stroke-1)',
                alignItems: 'start',
              }}>
                <span className="mono" style={{ fontSize: 10, color: 'var(--fg-5)' }}>−{s.t}</span>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%', marginTop: 5,
                  background: `var(--signal-${s.tone === 'cool' ? 'cool' : s.tone === 'violet' ? 'violet' : s.tone === 'neg' ? 'neg' : s.tone === 'warn' ? 'warn' : 'pos'})`,
                  boxShadow: `0 0 6px var(--signal-${s.tone === 'cool' ? 'cool' : s.tone === 'violet' ? 'violet' : s.tone === 'neg' ? 'neg' : s.tone === 'warn' ? 'warn' : 'pos'})`,
                }}/>
                <span style={{ fontSize: 11, color: 'var(--fg-2)', lineHeight: 1.4 }}>{s.txt}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* === CAPABILITIES PORTFOLIO === */}
      <div style={{
        gridColumn: '1', gridRow: '2',
        background: 'var(--bg-base)',
        padding: '22px 28px', overflow: 'auto',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-1)' }}>Capability Portfolio</span>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>5 active · 2 shadow · 1 deprecated</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Tag>YIELD</Tag>
            <Tag>VOLUME</Tag>
            <Tag>CONFIDENCE</Tag>
          </div>
        </div>

        <div style={{
          display: 'grid', gridTemplateColumns: '1fr', gap: 0,
          border: '1px solid var(--stroke-2)',
          borderRadius: 'var(--radius-md)', overflow: 'hidden',
        }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1.6fr 80px 120px 1fr 90px 70px 28px',
            gap: 14, padding: '10px 16px',
            background: 'var(--bg-inset)',
            borderBottom: '1px solid var(--stroke-2)',
          }}>
            {['Capability', 'ROI', 'Value', '90d Trend', 'Cost', 'Conf.', ''].map((h, i) => (
              <span key={i} className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>{h}</span>
            ))}
          </div>
          {capabilities.map((c, i) => (
            <CapabilityRow key={c.name} c={c} />
          ))}
        </div>
      </div>
    </div>
  );
}

function CapabilityRow({ c }) {
  const tone = c.roi >= 500 ? 'pos' : c.roi >= 300 ? 'cool' : c.roi >= 200 ? 'warn' : 'neg';
  const statusColor = {
    compounding: 'var(--signal-pos)',
    stable: 'var(--signal-cool)',
    warming: 'var(--signal-warn)',
    review: 'var(--signal-neg)',
  }[c.status];
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1.6fr 80px 120px 1fr 90px 70px 28px',
      gap: 14, padding: '14px 16px',
      borderTop: '1px solid var(--stroke-1)',
      alignItems: 'center',
      cursor: 'pointer',
      transition: 'background 120ms',
    }}
    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-panel)'}
    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ width: 4, height: 24, borderRadius: 1, background: statusColor, boxShadow: `0 0 6px ${statusColor}` }}/>
        <div>
          <div style={{ fontSize: 13, color: 'var(--fg-1)', fontWeight: 500 }}>{c.name}</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 2, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{c.status}</div>
        </div>
      </div>
      <span className="mono tnum" style={{ fontSize: 14, color: `var(--signal-${tone})`, fontWeight: 500 }}>{c.roi}%</span>
      <span className="mono tnum" style={{ fontSize: 14, color: 'var(--fg-1)' }}>{fmt.money(c.value)}</span>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <Spark data={c.trend} color={`var(--signal-${tone})`} height={28} width={220} />
      </div>
      <span className="mono tnum" style={{ fontSize: 12, color: 'var(--fg-3)' }}>{fmt.money(c.cost)}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <MicroBar value={c.conf * 100} color={`var(--signal-${tone})`} w={40} />
        <span className="mono tnum" style={{ fontSize: 10, color: 'var(--fg-3)' }}>{(c.conf*100).toFixed(0)}</span>
      </div>
      <span style={{ color: 'var(--fg-4)' }}><Glyph.Arrow /></span>
    </div>
  );
}

function StatReadout({ label, value, delta, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>{label}</span>
      <span className="mono tnum" style={{ fontSize: 20, color: 'var(--fg-1)', fontWeight: 400 }}>{value}</span>
      <span className="mono" style={{ fontSize: 10, color }}>{delta}</span>
    </div>
  );
}

function CurveKey({ color, label, dashed }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 14, height: 2, background: color, opacity: dashed ? 0.5 : 1,
        borderTop: dashed ? `2px dashed ${color}` : 'none',
        background: dashed ? 'transparent' : color,
      }}/>
      <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
    </div>
  );
}

function Section({ title, tone, total, children }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>{title}</span>
        <span className="mono tnum" style={{ fontSize: 12, color: `var(--signal-${tone})`, fontWeight: 500 }}>{total}</span>
      </div>
      <div>{children}</div>
    </div>
  );
}

function LedgerLine({ name, sub, v, pct, tone }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, padding: '8px 0', borderTop: '1px solid var(--stroke-1)', alignItems: 'center' }}>
      <div>
        <div style={{ fontSize: 12, color: 'var(--fg-2)' }}>{name}</div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 2 }}>{sub}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
        <span className="mono tnum" style={{ fontSize: 13, color: 'var(--fg-1)' }}>{v}</span>
        <MicroBar value={pct} color={`var(--signal-${tone})`} w={60} h={3} />
      </div>
    </div>
  );
}

// Value curve — the hero visualization
function ValueCurve({ height = 120 }) {
  const width = 900;
  const { valuePts, costPts, netPts } = useMemo(() => {
    const N = 90;
    const valueArr = [], costArr = [], netArr = [];
    let v = 3, c = 2;
    for (let i = 0; i < N; i++) {
      v += 0.12 + Math.sin(i/6) * 0.08 + (Math.random() - 0.3) * 0.15;
      c += 0.03 + Math.sin(i/9) * 0.02 + (Math.random() - 0.5) * 0.05;
      valueArr.push(v); costArr.push(c); netArr.push(v - c);
    }
    const step = width / (N - 1);
    const max = Math.max(...valueArr) * 1.05;
    const toPts = (arr) => arr.map((val, i) => `${i*step},${height - (val/max)*height}`).join(' ');
    return { valuePts: toPts(valueArr), costPts: toPts(costArr), netPts: toPts(netArr) };
  }, [height]);

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="vcg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--signal-cool)" stopOpacity="0.18" />
          <stop offset="100%" stopColor="var(--signal-cool)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="netg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--signal-pos)" stopOpacity="0.16" />
          <stop offset="100%" stopColor="var(--signal-pos)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* grid */}
      {[0, 0.25, 0.5, 0.75, 1].map(p => (
        <line key={p} x1="0" x2={width} y1={height*p} y2={height*p} stroke="var(--stroke-1)" strokeWidth="1" />
      ))}
      {/* today marker */}
      <line x1={width*0.7} x2={width*0.7} y1="0" y2={height} stroke="var(--signal-cool)" strokeWidth="0.8" strokeDasharray="2 3" opacity="0.5" />
      <text x={width*0.7 + 4} y="12" fill="var(--signal-cool)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.1em">TODAY</text>

      <polygon points={`0,${height} ${valuePts} ${width},${height}`} fill="url(#vcg)" />
      <polygon points={`0,${height} ${netPts} ${width},${height}`} fill="url(#netg)" />
      <polyline points={costPts} fill="none" stroke="var(--signal-violet)" strokeWidth="1.2" strokeDasharray="3 3" opacity="0.7" />
      <polyline points={valuePts} fill="none" stroke="var(--signal-cool)" strokeWidth="1.6" style={{ filter: 'drop-shadow(0 0 4px var(--signal-cool))' }}/>
      <polyline points={netPts} fill="none" stroke="var(--signal-pos)" strokeWidth="1.6" style={{ filter: 'drop-shadow(0 0 4px var(--signal-pos))' }}/>
    </svg>
  );
}

Object.assign(window, { Hypervisor });
