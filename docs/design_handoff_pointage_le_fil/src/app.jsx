// app.jsx — coquille : navigation DOC ⇄ PROTO, sous-onglets d'écrans, Tweaks.
const { useState: aS, useEffect: aE } = React;

const SCREENS = [
  { id: 'capture', label: 'Capture', icon: 'mic' },
  { id: 'pieces', label: 'Pièces & pointage', icon: 'layers' },
  { id: 'fin', label: 'Fin de séance', icon: 'check' },
  { id: 'index', label: 'Indexation', icon: 'spark' },
  { id: 'report', label: 'Rapport', icon: 'book' },
  { id: 'edge', label: 'Cas limites', icon: 'target' },
];

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "sombre",
  "pointing": "hybride",
  "oracle": true,
  "density": "regular",
  "speed": 1.2
}/*EDITMODE-END*/;

function NavTab({ active, onClick, icon, children, compact }) {
  const [h, setH] = aS(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
      style={{ appearance: 'none', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 7,
        padding: compact ? '6px 10px' : '7px 13px', borderRadius: 'var(--ck-radius-md)', border: 'none',
        fontFamily: 'var(--ck-font-sans)', fontSize: 12.5, fontWeight: active ? 650 : 520,
        background: active ? 'var(--ck-bg-panel-hi)' : (h ? 'var(--ck-tint-faint)' : 'transparent'),
        color: active ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)', whiteSpace: 'nowrap',
        boxShadow: active ? 'inset 0 0 0 1px var(--ck-stroke-2)' : 'none' }}>
      {icon && <Icon name={icon} size={14} style={{ color: active ? 'var(--ck-signal-cool)' : 'inherit' }} />}
      {children}
    </button>
  );
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [mode, setMode] = aS('doc');          // 'doc' | 'proto'
  const [screen, setScreen] = aS('capture');
  const [offline, setOffline] = aS(false);

  // thème global
  aE(() => {
    const root = document.documentElement;
    if (t.theme === 'sombre') { root.classList.add('dark'); root.setAttribute('data-theme', 'dark'); }
    else { root.classList.remove('dark'); root.setAttribute('data-theme', 'light'); }
  }, [t.theme]);

  const goto = (target) => {
    if (target === 'doc') { setMode('doc'); return; }
    setMode('proto'); setScreen(target);
  };

  const tweaks = { pointing: t.pointing, oracle: t.oracle, density: t.density, speed: t.speed };

  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
      fontFamily: 'var(--ck-font-sans)', background: 'var(--ck-bg-base)' }}>
      {/* barre supérieure */}
      <header style={{ height: 52, flex: 'none', display: 'flex', alignItems: 'center', gap: 16,
        padding: '0 16px', borderBottom: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)',
        zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center',
            background: 'linear-gradient(135deg, var(--ck-signal-cool), var(--ck-signal-violet))',
            color: 'var(--ck-bg-void)' }}><Icon name="target" size={14} /></span>
          <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--ck-fg-1)', letterSpacing: '-0.01em' }}>Le Fil</span>
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-5)',
            padding: '2px 6px', border: '1px solid var(--ck-stroke-2)', borderRadius: 999 }}>contre-proposition</span>
        </div>

        {/* bascule DOC / PROTO */}
        <div style={{ display: 'flex', gap: 2, padding: 2, borderRadius: 'var(--ck-radius-md)',
          background: 'var(--ck-bg-void)', border: '1px solid var(--ck-stroke-2)' }}>
          <NavTab active={mode === 'doc'} onClick={() => setMode('doc')} icon="text" compact>Doc</NavTab>
          <NavTab active={mode === 'proto'} onClick={() => setMode('proto')} icon="eye" compact>Prototype</NavTab>
        </div>

        {/* sous-onglets prototype */}
        {mode === 'proto' && (
          <div className="ck-scroll" style={{ display: 'flex', gap: 2, overflowX: 'auto', flex: 1 }}>
            {SCREENS.map((s) => (
              <NavTab key={s.id} active={screen === s.id} onClick={() => setScreen(s.id)} icon={s.icon} compact>
                {s.label}
              </NavTab>
            ))}
          </div>
        )}

        {mode === 'doc' && (
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-5)' }}>
              ⚙ Tweaks : pointage · oracle · densité · thème
            </span>
          </span>
        )}
      </header>

      {/* corps */}
      <main style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        {mode === 'doc' && <DocMode onGoto={goto} />}
        {mode === 'proto' && screen === 'capture' && (
          <CaptureScreen tweaks={tweaks} onFinish={() => setScreen('fin')}
            offline={offline} onToggleOffline={() => setOffline((o) => !o)} />
        )}
        {mode === 'proto' && screen === 'pieces' && <PiecesScreen />}
        {mode === 'proto' && screen === 'fin' && <FinScreen onOpenReport={() => setScreen('report')} />}
        {mode === 'proto' && screen === 'index' && <IndexScreen />}
        {mode === 'proto' && screen === 'report' && <ReportScreen />}
        {mode === 'proto' && screen === 'edge' && <EdgeScreen />}
      </main>

      {/* Tweaks */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="Pointage déictique" />
        <TweakRadio label="Mode" value={t.pointing}
          options={[{ value: 'auto', label: 'Auto' }, { value: 'hybride', label: 'Hybride' }, { value: 'manuel', label: 'Manuel' }]}
          onChange={(v) => setTweak('pointing', v)} />
        <TweakSection label="Capture" />
        <TweakToggle label="Oracle actif" value={t.oracle} onChange={(v) => setTweak('oracle', v)} />
        <TweakRadio label="Densité du Fil" value={t.density}
          options={['compact', 'regular', 'comfy']} onChange={(v) => setTweak('density', v)} />
        <TweakSlider label="Vitesse simu" value={t.speed} min={0.5} max={2.5} step={0.1} unit="×"
          onChange={(v) => setTweak('speed', v)} />
        <TweakSection label="Apparence" />
        <TweakRadio label="Thème" value={t.theme}
          options={[{ value: 'sombre', label: 'Sombre' }, { value: 'clair', label: 'Clair' }]}
          onChange={(v) => setTweak('theme', v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
