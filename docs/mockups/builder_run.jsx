// ============================================
// AGENTIUM — Builder Canvas
// System topology editor. Nodes, edges, live telemetry.
// ============================================

function BuilderView() {
  const [selected, setSelected] = useState('ext');

  const nodes = {
    trigger: { x: 60, y: 220, w: 170, h: 80, label: 'External Webhook', type: 'TRIGGER', tone: 'violet', stat: '12ms avg · 2.4k/s', icon: 'Bolt', active: true },
    ocr:     { x: 290, y: 120, w: 170, h: 80, label: 'OCR Extraction',  type: 'SKILL', tone: 'pos', stat: '99.2% confidence', icon: 'Cube' },
    ext:     { x: 290, y: 320, w: 200, h: 100, label: 'Semantic Extraction', type: 'LLM', tone: 'cool', stat: '98.2% confidence · GPT-4o', icon: 'Cube', focus: true },
    router:  { x: 540, y: 220, w: 170, h: 80, label: 'Routing Logic',   type: 'LOGIC', tone: 'violet', stat: '3 branches · 5ms', icon: 'Flow' },
    hitl:    { x: 780, y: 100, w: 170, h: 80, label: 'Human Review',    type: 'HITL',  tone: 'warn', stat: 'Queue: 2 items', icon: 'Warn' },
    emit:    { x: 780, y: 220, w: 170, h: 80, label: 'Signal Emit',     type: 'OUTPUT',tone: 'pos', stat: '+98.2% acc · live', icon: 'Check' },
    esc:     { x: 780, y: 340, w: 170, h: 80, label: 'Escalate',        type: 'OUTPUT',tone: 'neg', stat: 'Priority queue', icon: 'Arrow' },
  };

  const edges = [
    ['trigger','ocr'], ['trigger','ext'],
    ['ocr','router'], ['ext','router'],
    ['router','hitl'], ['router','emit'], ['router','esc'],
  ];

  const sel = nodes[selected];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', height: '100%', background: 'var(--stroke-2)', gap: 1 }}>
      {/* canvas */}
      <div style={{ position: 'relative', background: 'var(--bg-base)', overflow: 'hidden' }}>
        {/* ambient dot grid */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: 'radial-gradient(circle, var(--stroke-2) 1px, transparent 1px)',
          backgroundSize: '24px 24px', opacity: 0.4,
        }}/>

        {/* toolbar */}
        <div style={{ position: 'absolute', top: 16, left: 16, display: 'flex', flexDirection: 'column', gap: 4, zIndex: 2 }}>
          {['Bolt','Cube','Flow','Sliders','Warn'].map(g => {
            const G = Glyph[g];
            return <button key={g} style={{
              width: 34, height: 34, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--bg-panel)', border: '1px solid var(--stroke-2)', borderRadius: 4,
              color: 'var(--fg-3)',
            }}><G /></button>;
          })}
        </div>

        {/* breadcrumb */}
        <div style={{ position: 'absolute', top: 16, left: 72, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'var(--bg-panel)', border: '1px solid var(--stroke-2)', borderRadius: 4, zIndex: 2 }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>Customer Intelligence</span>
          <span style={{ color: 'var(--fg-5)' }}>›</span>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>Sentiment Routing</span>
          <span style={{ color: 'var(--fg-5)' }}>›</span>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-1)' }}>Data Ingestion Flow</span>
          <span className="live-dot" style={{ marginLeft: 6 }}/>
        </div>

        {/* zoom controls */}
        <div style={{ position: 'absolute', top: 16, right: 16, display: 'flex', gap: 2, padding: 3, background: 'var(--bg-panel)', border: '1px solid var(--stroke-2)', borderRadius: 4, zIndex: 2 }}>
          <button style={builderBtn}>⌖</button>
          <button style={builderBtn}>−</button>
          <button style={builderBtn}>82%</button>
          <button style={builderBtn}>+</button>
        </div>

        {/* graph */}
        <svg viewBox="0 0 1050 480" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" style={{ position: 'absolute', inset: 0 }}>
          <defs>
            <marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6" fill="var(--stroke-3)"/>
            </marker>
            <marker id="arr-hot" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6" fill="var(--signal-cool)"/>
            </marker>
          </defs>
          {/* edges */}
          {edges.map(([a, b], i) => {
            const A = nodes[a], B = nodes[b];
            const x1 = A.x + A.w, y1 = A.y + A.h/2;
            const x2 = B.x,       y2 = B.y + B.h/2;
            const mx = (x1 + x2) / 2;
            const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
            const hot = a === 'trigger' && b === 'ext';
            return (
              <g key={i}>
                <path d={d} stroke={hot ? 'var(--signal-cool)' : 'var(--stroke-3)'} strokeWidth={hot ? 1.4 : 1} fill="none"
                  markerEnd={hot ? 'url(#arr-hot)' : 'url(#arr)'}
                  strokeDasharray={hot ? '0' : '3 3'}
                  opacity={hot ? 1 : 0.6}
                />
                {hot && (
                  <circle r="3" fill="var(--signal-cool)" style={{ filter: 'drop-shadow(0 0 6px var(--signal-cool))' }}>
                    <animateMotion dur="2.4s" repeatCount="indefinite" path={d} />
                  </circle>
                )}
              </g>
            );
          })}
          {/* nodes */}
          {Object.entries(nodes).map(([id, n]) => {
            const G = Glyph[n.icon];
            const focused = selected === id;
            return (
              <g key={id} transform={`translate(${n.x}, ${n.y})`} style={{ cursor: 'pointer' }} onClick={() => setSelected(id)}>
                {focused && <rect x="-4" y="-4" width={n.w + 8} height={n.h + 8} rx="8" fill="none" stroke={`var(--signal-${n.tone})`} strokeWidth="1.2" opacity="0.45" style={{ filter: `drop-shadow(0 0 8px var(--signal-${n.tone}))` }}/>}
                <rect x="0" y="0" width={n.w} height={n.h} rx="6"
                  fill="var(--bg-panel)"
                  stroke={focused ? `var(--signal-${n.tone})` : 'var(--stroke-2)'}
                  strokeWidth={focused ? 1.2 : 1}
                />
                {/* top tone bar */}
                <rect x="0" y="0" width={n.w} height="2" rx="1" fill={`var(--signal-${n.tone})`}/>
                {/* label */}
                <foreignObject x="12" y="10" width={n.w - 24} height={n.h - 20}>
                  <div style={{ fontFamily: 'var(--font-sans)', color: 'var(--fg-1)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ color: `var(--signal-${n.tone})` }}><G /></span>
                      <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.14em' }}>{n.type}</span>
                      {n.active && <span className="live-dot" style={{ marginLeft: 'auto' }}/>}
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 500, marginTop: 8 }}>{n.label}</div>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 4 }}>{n.stat}</div>
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </svg>

        {/* bottom terminal */}
        <div style={{
          position: 'absolute', left: 16, right: 16, bottom: 16,
          background: 'var(--bg-code)', border: '1px solid var(--stroke-2)',
          borderRadius: 4, padding: '10px 14px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em' }}>EXECUTION TERMINAL</span>
            <div style={{ display: 'flex', gap: 10 }}>
              <Tag tone="pos">0 ERRORS</Tag>
              <Tag tone="cool">14 INFO</Tag>
            </div>
          </div>
          <div className="mono" style={{ fontSize: 10, lineHeight: 1.7, color: 'var(--fg-3)' }}>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:01</span> <span style={{ color: 'var(--signal-violet)' }}>[System]</span> Initializing pipeline execution (Run r_992x)</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:02</span> <span style={{ color: 'var(--signal-cool)' }}>[Webhook]</span> Payload 2.4kb received</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:03</span> <span style={{ color: 'var(--signal-cool)' }}>[Extraction]</span> Routing to Semantic Extraction node</div>
            <div><span style={{ color: 'var(--fg-5)' }}>10:42:04</span> <span style={{ color: 'var(--signal-pos)' }}>[Success]</span> Confidence 0.982 · 3 entities parsed</div>
          </div>
        </div>
      </div>

      {/* inspector */}
      <div style={{ background: 'var(--bg-panel)', padding: '22px 22px', overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.14em' }}>NODE INSPECTOR</span>
          <Tag tone={sel.tone}>{sel.type}</Tag>
        </div>
        <div style={{ fontSize: 18, color: 'var(--fg-1)', fontWeight: 400 }}>{sel.label}</div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 4 }}>id: node_{selected}_8f7a9</div>

        <div style={{ marginTop: 22 }}>
          <div className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em', marginBottom: 10 }}>MODEL · GPT-4o Turbo</div>
          <div style={{ padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--fg-2)' }}>GPT-4o Turbo</span>
            <span style={{ color: 'var(--fg-5)' }}>⌄</span>
          </div>
          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)' }}>TEMPERATURE</span>
            <span className="mono tnum" style={{ fontSize: 12, color: 'var(--signal-cool)' }}>0.20</span>
          </div>
          <div style={{ position: 'relative', height: 4, background: 'var(--stroke-2)', borderRadius: 2 }}>
            <div style={{ position: 'absolute', left: 0, width: '20%', height: '100%', background: 'var(--signal-cool)', boxShadow: '0 0 8px var(--signal-cool)', borderRadius: 2 }}/>
          </div>
        </div>

        <div style={{ marginTop: 22 }}>
          <div className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em', marginBottom: 8 }}>SYSTEM PROMPT</div>
          <div className="mono" style={{ padding: 12, background: 'var(--bg-code)', border: '1px solid var(--stroke-2)', borderRadius: 4, fontSize: 10.5, lineHeight: 1.7, color: 'var(--fg-3)' }}>
            <span style={{ color: 'var(--signal-violet)' }}>You are an expert financial analyst.</span><br/>
            Extract the following from input text:<br/>
            <span style={{ color: 'var(--signal-cool)' }}>— Company name</span><br/>
            <span style={{ color: 'var(--signal-cool)' }}>— Q3 revenue figures</span><br/>
            <span style={{ color: 'var(--signal-cool)' }}>— Key risk factors</span>
          </div>
        </div>

        <div style={{ marginTop: 22 }}>
          <div className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em', marginBottom: 10 }}>LOCAL METRICS · 24H</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <Metric label="Latency p95" v="420ms" />
            <Metric label="Success rate" v="99.8%" color="var(--signal-pos)" />
            <Metric label="Tokens" v="1.2M" />
            <Metric label="Cost" v="$240" />
          </div>
        </div>

        <button style={{
          marginTop: 22, width: '100%', padding: '10px', background: 'var(--signal-cool)', color: 'var(--bg-void)',
          border: 'none', borderRadius: 4, fontWeight: 500, fontSize: 12, letterSpacing: '0.04em', textTransform: 'uppercase',
        }}>Apply Changes</button>
      </div>
    </div>
  );
}

const builderBtn = {
  width: 32, height: 28, fontSize: 11,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: 'transparent', border: '1px solid transparent',
  color: 'var(--fg-3)', fontFamily: 'var(--font-mono)',
};

// ============================================
// RUN DETAIL
// ============================================

function RunView() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', height: '100%', background: 'var(--stroke-2)', gap: 1, overflow: 'auto' }}>
      <div style={{ background: 'var(--bg-base)', padding: '24px 32px', overflow: 'auto' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.14em' }}>← AGENT RUNS</span>
          <span style={{ color: 'var(--fg-5)' }}>›</span>
          <Tag>RUN-8924A</Tag>
        </div>
        <h1 style={{ fontSize: 32, color: 'var(--fg-1)', fontWeight: 300, margin: '6px 0 0', letterSpacing: '-0.02em' }}>Invoice Processing</h1>
        <div style={{ fontSize: 12, color: 'var(--fg-4)', marginTop: 6 }}>Executed via Main Controller · 2m ago · Duration 1.42s</div>

        {/* outcome */}
        <div style={{ marginTop: 24, padding: 22, background: 'var(--bg-panel)', border: '1px solid var(--stroke-2)', borderRadius: 8, position: 'relative' }}>
          {/* subtle glow ring for success */}
          <div style={{ position: 'absolute', inset: -1, border: '1px solid rgba(52,211,153,0.22)', borderRadius: 9, pointerEvents: 'none' }}/>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.14em' }}>OUTCOME · PRIMARY</span>
              <div style={{ fontSize: 22, color: 'var(--fg-1)', fontWeight: 400, marginTop: 6, lineHeight: 1.3 }}>
                Extracted 42 line items, reconciled against <span style={{ color: 'var(--signal-cool)' }}>PO-2023-881</span>.<br/>
                Data posted to ERP staging table.
              </div>
            </div>
            <Tag tone="pos">SUCCESS · COMMITTED</Tag>
          </div>
          <div style={{ marginTop: 22, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
            <OutcomeTile label="Items processed" v="42" />
            <OutcomeTile label="Compute cost" v="$0.04" sub="−89% vs manual" color="var(--signal-cool)"/>
            <OutcomeTile label="Time saved" v="~15m" sub="labor avoidance" color="var(--signal-pos)"/>
            <OutcomeTile label="Confidence" v="98.2%" sub="threshold ≥99%" color="var(--signal-pos)" meter={0.982}/>
          </div>
          <div style={{ marginTop: 18, padding: '10px 14px', background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4, display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>VALUE ADDED</span>
            <span className="mono tnum" style={{ fontSize: 14, color: 'var(--signal-pos)' }}>+$12.00</span>
            <span style={{ flex: 1 }}/>
            <span className="mono" style={{ fontSize: 9, color: 'var(--fg-4)' }}>MODEL: gpt-4-turbo · 4,333 tokens</span>
          </div>
        </div>

        {/* trace */}
        <div style={{ marginTop: 24, padding: 22, background: 'var(--bg-panel)', border: '1px solid var(--stroke-2)', borderRadius: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--fg-1)' }}>Execution trace</div>
            <Tag>TOTAL 1.42s</Tag>
          </div>

          {[
            { i: 1, name: 'Document Ingestion · OCR', sub: 'Extracted raw text blocks and layout geometry', ms: 300, tone: 'pos', meta: 'INV-442.PDF · 2.1MB' },
            { i: 2, name: 'Semantic Extraction · LLM', sub: 'Mapped raw text to standard JSON schema', ms: 800, tone: 'cool', meta: 'GPT-4o · t=0.2', focus: true, code: true },
            { i: 3, name: 'Validation · Reconciliation', sub: 'Line items summed. Vendor exists in ERP.', ms: 200, tone: 'pos', meta: 'No flags raised' },
            { i: 4, name: 'Commit · ERP Staging', sub: 'Posted to staging.invoices. Batch ID 44a8e', ms: 120, tone: 'pos', meta: 'Idempotent write' },
          ].map((s, i, arr) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '24px 1fr 80px', gap: 14, position: 'relative' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative' }}>
                <div style={{
                  width: 22, height: 22, borderRadius: '50%',
                  background: 'var(--bg-inset)', border: `1.5px solid var(--signal-${s.tone})`,
                  boxShadow: s.focus ? `0 0 8px var(--signal-${s.tone})` : 'none',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: `var(--signal-${s.tone})`, fontFamily: 'var(--font-mono)', fontSize: 10,
                }}>{s.i}</div>
                {i < arr.length - 1 && <div style={{ width: 1, flex: 1, background: 'var(--stroke-2)', minHeight: 20 }}/>}
              </div>
              <div style={{ paddingBottom: 18 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontSize: 13, color: 'var(--fg-1)', fontWeight: 500 }}>{s.name}</span>
                  <Tag tone={s.tone}>{s.meta}</Tag>
                </div>
                <div style={{ fontSize: 11, color: 'var(--fg-4)', marginTop: 4 }}>{s.sub}</div>
                {s.code && (
                  <div className="mono" style={{ marginTop: 10, padding: 10, background: 'var(--bg-code)', border: '1px solid var(--stroke-2)', borderRadius: 4, fontSize: 10.5, lineHeight: 1.7, color: 'var(--fg-3)' }}>
                    {'{'}<br/>
                    &nbsp;&nbsp;<span style={{ color: 'var(--signal-cool)' }}>"vendor_id"</span>: <span style={{ color: 'var(--signal-pos)' }}>"V-8821"</span>,<br/>
                    &nbsp;&nbsp;<span style={{ color: 'var(--signal-cool)' }}>"invoice_date"</span>: <span style={{ color: 'var(--signal-pos)' }}>"2023-10-24"</span>,<br/>
                    &nbsp;&nbsp;<span style={{ color: 'var(--signal-cool)' }}>"total_amount"</span>: <span style={{ color: 'var(--signal-warn)' }}>4250.00</span>,<br/>
                    &nbsp;&nbsp;<span style={{ color: 'var(--signal-cool)' }}>"line_items_count"</span>: <span style={{ color: 'var(--signal-warn)' }}>4</span><br/>
                    {'}'}
                  </div>
                )}
              </div>
              <div style={{ textAlign: 'right' }}>
                <span className="mono tnum" style={{ fontSize: 12, color: 'var(--fg-2)' }}>{s.ms}ms</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* right rail */}
      <div style={{ background: 'var(--bg-panel)', padding: '22px 22px', overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span className="mono" style={{ fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.14em' }}>TELEMETRY</span>
          <Tag>GPT-4-TURBO-0125</Tag>
        </div>
        <TelemetryRow label="Duration" v="1.42s" />
        <TelemetryRow label="Prompt tokens" v="3,492" />
        <TelemetryRow label="Completion tokens" v="841" />
        <TelemetryRow label="Total cost" v="$0.042" />
        <TelemetryRow label="System uptime" v="99.9%" color="var(--signal-pos)"/>
        <TelemetryRow label="Run token usage" v="1,420" />

        <div style={{ marginTop: 20, padding: 14, background: 'var(--bg-inset)', border: '1px solid rgba(245,184,74,0.25)', borderRadius: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ color: 'var(--signal-warn)' }}><Glyph.Warn /></span>
            <span style={{ fontSize: 13, color: 'var(--fg-1)', fontWeight: 500 }}>Validation required</span>
            <span className="live-dot warn" style={{ marginLeft: 'auto' }}/>
          </div>
          <div style={{ fontSize: 11, color: 'var(--fg-3)', lineHeight: 1.5, marginBottom: 12 }}>
            One field fell below the 99% confidence threshold required for straight-through processing.
          </div>
          <div style={{ padding: '10px 12px', background: 'var(--bg-code)', borderRadius: 4, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ color: 'var(--fg-4)' }}>FIELD: TAX_ID</span>
              <span style={{ color: 'var(--signal-warn)' }}>CONF 82%</span>
            </div>
            <div>
              <span style={{ color: 'var(--fg-5)', textDecoration: 'line-through' }}>12-345678</span>
              <span style={{ color: 'var(--fg-4)' }}> → </span>
              <span style={{ color: 'var(--signal-cool)' }}>12-845678</span>
            </div>
          </div>
          <div style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 10, lineHeight: 1.5 }}>Image quality poor. LLM corrected OCR error based on historical vendor data.</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
            <button style={{ flex: 1, padding: '8px', background: 'transparent', color: 'var(--fg-2)', border: '1px solid var(--stroke-3)', borderRadius: 3, fontSize: 11 }}>Reject</button>
            <button style={{ flex: 1, padding: '8px', background: 'var(--signal-cool)', color: 'var(--bg-void)', border: 'none', borderRadius: 3, fontSize: 11, fontWeight: 500 }}>Approve</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function OutcomeTile({ label, v, sub, color = 'var(--fg-1)', meter }) {
  return (
    <div style={{ padding: '12px 14px', background: 'var(--bg-inset)', border: '1px solid var(--stroke-2)', borderRadius: 4 }}>
      <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>{label}</div>
      <div className="mono tnum" style={{ fontSize: 22, color, fontWeight: 400, marginTop: 6 }}>{v}</div>
      {sub && <div className="mono" style={{ fontSize: 9, color: 'var(--fg-4)', marginTop: 4 }}>{sub}</div>}
      {meter != null && <div style={{ marginTop: 8, height: 2, background: 'var(--stroke-2)', borderRadius: 1, overflow: 'hidden' }}>
        <div style={{ width: `${meter*100}%`, height: '100%', background: color, boxShadow: `0 0 6px ${color}` }}/>
      </div>}
    </div>
  );
}

function TelemetryRow({ label, v, color = 'var(--fg-1)' }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderTop: '1px solid var(--stroke-1)' }}>
      <span style={{ fontSize: 12, color: 'var(--fg-3)' }}>{label}</span>
      <span className="mono tnum" style={{ fontSize: 12, color }}>{v}</span>
    </div>
  );
}

Object.assign(window, { BuilderView, RunView });
