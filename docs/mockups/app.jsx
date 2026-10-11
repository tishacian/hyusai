// ============================================
// AGENTIUM — App shell, Tweaks, Concept switcher
// ============================================

function App() {
  // Tweaks (persisted on page)
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "concept": "A",
    "theme": "dark",
    "density": 6,
    "motion": 7,
    "accent": "cool"
  }/*EDITMODE-END*/;

  const [tweaks, setTweaks] = useState(() => {
    try {
      const saved = localStorage.getItem('agentium:tweaks');
      if (saved) return { ...TWEAK_DEFAULTS, ...JSON.parse(saved) };
    } catch {}
    return TWEAK_DEFAULTS;
  });
  const [tweaksOpen, setTweaksOpen] = useState(false);

  const [view, setView] = useState(() => localStorage.getItem('agentium:view') || 'hypervisor');
  useEffect(() => { localStorage.setItem('agentium:view', view); }, [view]);

  useEffect(() => {
    try { localStorage.setItem('agentium:tweaks', JSON.stringify(tweaks)); } catch {}
    document.documentElement.setAttribute('data-theme', tweaks.theme);
    document.documentElement.setAttribute('data-concept', tweaks.concept);
    document.documentElement.setAttribute('data-accent', tweaks.accent);
  }, [tweaks]);

  // Tweaks edit mode protocol
  useEffect(() => {
    const onMsg = (e) => {
      if (e.data?.type === '__activate_edit_mode') setTweaksOpen(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaksOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const updateTweak = (k, v) => {
    setTweaks(t => ({ ...t, [k]: v }));
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { [k]: v } }, '*');
  };

  // Live system state for chrome
  const throughput = useLiveNumber(2.4, { jitter: 0.04, interval: 1800 });
  const latency = useLiveNumber(420, { jitter: 0.03, interval: 1400 });
  const yieldPct = useLiveNumber(24.5, { jitter: 0.01, interval: 2400 });
  const systemState = { throughput, latency, yield: yieldPct };

  return (
    <div style={{ position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-base)', overflow: 'hidden' }}>
      <TitleBar view={view} setView={setView} systemState={systemState} />
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        <SideRail view={view} setView={setView} />
        <div data-screen-label={view.toUpperCase()} data-concept={tweaks.concept} style={{ flex: 1, minWidth: 0, overflow: 'hidden', position: 'relative' }}>
          {view === 'hypervisor' && <Hypervisor systemState={systemState} />}
          {view === 'zoom' && <ZoomView onGoToSteering={() => setView('steering')} onGoToRun={() => setView('run')} />}
          {view === 'steering' && <SteeringView />}
          {view === 'builder' && <BuilderView />}
          {view === 'run' && <RunView />}

          {/* Concept label (top-right floating) */}
          <ConceptBadge concept={tweaks.concept} />
        </div>
      </div>

      {tweaksOpen && <TweaksPanel tweaks={tweaks} onChange={updateTweak} onClose={() => setTweaksOpen(false)} />}

      <BottomCommand view={view} />
    </div>
  );
}

function ConceptBadge({ concept }) {
  const concepts = {
    A: { name: 'Instrument Panel', sub: 'Precision · Dense cockpit' },
    B: { name: 'Living Organism',  sub: 'Ambient · Biological pulse' },
    C: { name: 'Architectural',    sub: 'Editorial · Monochrome' },
    D: { name: 'Spatial OS',       sub: 'Radical · Semantic zoom' },
  };
  const c = concepts[concept] || concepts.A;
  return (
    <div style={{
      position: 'absolute', bottom: 14, left: 18, zIndex: 3,
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '6px 10px',
      background: 'rgba(12,16,20,0.72)',
      backdropFilter: 'blur(10px)',
      border: '1px solid var(--stroke-2)',
      borderRadius: 4,
    }}>
      <span className="mono" style={{ fontSize: 9, color: 'var(--fg-5)', letterSpacing: '0.14em' }}>CONCEPT · {concept}</span>
      <span style={{ color: 'var(--fg-5)' }}>·</span>
      <span style={{ fontSize: 11, color: 'var(--fg-2)', fontWeight: 500 }}>{c.name}</span>
      <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>{c.sub}</span>
    </div>
  );
}

function BottomCommand({ view }) {
  return (
    <div style={{
      height: 28, borderTop: '1px solid var(--stroke-2)',
      background: 'var(--bg-panel)',
      display: 'flex', alignItems: 'center', padding: '0 14px', gap: 18,
    }}>
      <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.12em' }}>
        <span style={{ color: 'var(--signal-pos)' }}>●</span> SYSTEM OPERATIONAL
      </span>
      <span className="mono" style={{ fontSize: 10, color: 'var(--fg-5)' }}>/{view}</span>
      <span style={{ flex: 1 }}/>
      <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Kbd>⌘</Kbd><Kbd>K</Kbd> Command
      </span>
      <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Kbd>⌘</Kbd><Kbd>Z</Kbd> Zoom
      </span>
      <span className="mono" style={{ fontSize: 10, color: 'var(--fg-4)' }}>v4.2.1-build-8829</span>
    </div>
  );
}

function TweaksPanel({ tweaks, onChange, onClose }) {
  return (
    <div style={{
      position: 'fixed', bottom: 44, right: 18, width: 320, zIndex: 50,
      background: 'var(--bg-panel-hi)', border: '1px solid var(--stroke-3)',
      borderRadius: 8, padding: 18,
      boxShadow: '0 20px 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(125,211,252,0.1)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Glyph.Sliders />
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-1)' }}>Tweaks</span>
        </div>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--fg-4)' }}><Glyph.X /></button>
      </div>

      <TweakRow label="Concept">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
          {['A','B','C','D'].map(c => (
            <button key={c} onClick={() => onChange('concept', c)} style={{
              padding: '8px 4px', fontSize: 11, fontWeight: 500,
              background: tweaks.concept === c ? 'var(--signal-cool)' : 'var(--bg-inset)',
              color: tweaks.concept === c ? 'var(--bg-void)' : 'var(--fg-3)',
              border: '1px solid ' + (tweaks.concept === c ? 'var(--signal-cool)' : 'var(--stroke-2)'),
              borderRadius: 3,
            }} className="mono">{c}</button>
          ))}
        </div>
        <div style={{ fontSize: 10, color: 'var(--fg-4)', marginTop: 6 }}>
          {['Instrument Panel','Living Organism','Architectural','Spatial OS'][{A:0,B:1,C:2,D:3}[tweaks.concept]]}
        </div>
      </TweakRow>

      <TweakRow label="Theme">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 4 }}>
          {['dark','light'].map(t => (
            <button key={t} onClick={() => onChange('theme', t)} style={{
              padding: '8px', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em',
              background: tweaks.theme === t ? 'var(--bg-panel)' : 'var(--bg-inset)',
              color: tweaks.theme === t ? 'var(--fg-1)' : 'var(--fg-3)',
              border: '1px solid ' + (tweaks.theme === t ? 'var(--stroke-hot)' : 'var(--stroke-2)'),
              borderRadius: 3,
            }} className="mono">{t}</button>
          ))}
        </div>
      </TweakRow>

      <TweakRow label="Accent">
        <div style={{ display: 'flex', gap: 6 }}>
          {[
            ['cool', '#7dd3fc'],
            ['violet', '#a78bfa'],
            ['pos', '#34d399'],
            ['warn', '#f5b84a'],
          ].map(([name, col]) => (
            <button key={name} onClick={() => onChange('accent', name)} style={{
              width: 36, height: 28, borderRadius: 3,
              background: col, opacity: tweaks.accent === name ? 1 : 0.4,
              border: '1px solid ' + (tweaks.accent === name ? 'var(--fg-1)' : 'transparent'),
              cursor: 'pointer',
            }}/>
          ))}
        </div>
      </TweakRow>

      <TweakRow label={`Density · ${tweaks.density}/10`}>
        <input type="range" min="1" max="10" value={tweaks.density} onChange={e => onChange('density', parseInt(e.target.value))} style={{ width: '100%', accentColor: '#7dd3fc' }}/>
      </TweakRow>

      <TweakRow label={`Motion · ${tweaks.motion}/10`}>
        <input type="range" min="1" max="10" value={tweaks.motion} onChange={e => onChange('motion', parseInt(e.target.value))} style={{ width: '100%', accentColor: '#7dd3fc' }}/>
      </TweakRow>

      <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--bg-inset)', borderRadius: 4, fontSize: 10, color: 'var(--fg-4)', lineHeight: 1.6 }}>
        Cycle concepts A→D to see visual direction explorations. All views work in every concept. Light theme for comparison.
      </div>
    </div>
  );
}

function TweakRow({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="mono" style={{ fontSize: 10, color: 'var(--fg-4)', letterSpacing: '0.12em', marginBottom: 8, textTransform: 'uppercase' }}>{label}</div>
      {children}
    </div>
  );
}

// MOUNT
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
