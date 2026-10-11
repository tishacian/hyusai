// ui.jsx — primitives partagées (icônes géométriques, placeholders rayés, chips).
// Aucune illustration : les "pages/images" sont des placeholders hachurés + libellé mono.
const { useState: useStateUI, useRef: useRefUI, useEffect: useEffectUI } = React;

// ── Icônes (traits géométriques simples, currentColor) ────────────────────
function Icon({ name, size = 16, style }) {
  const s = { width: size, height: size, display: 'block', flex: 'none', ...style };
  const p = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5,
    strokeLinecap: 'round', strokeLinejoin: 'round' };
  const paths = {
    mic: <><rect x="9" y="3" width="6" height="11" rx="3" {...p} /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" {...p} /></>,
    pen: <path d="M4 20l4-1L20 7l-3-3L5 16l-1 4z" {...p} />,
    target: <><circle cx="12" cy="12" r="7" {...p} /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" {...p} /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /></>,
    doc: <><path d="M6 3h8l4 4v14H6z" {...p} /><path d="M14 3v4h4M9 13h6M9 17h6" {...p} /></>,
    image: <><rect x="4" y="5" width="16" height="14" rx="1.5" {...p} /><circle cx="9" cy="10" r="1.6" {...p} /><path d="M5 17l4-4 3 3 3-3 4 4" {...p} /></>,
    question: <><circle cx="12" cy="12" r="9" {...p} /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.2 2.4c-.7.3-1.2.9-1.2 1.6v.5" {...p} /><circle cx="11.5" cy="17" r="1" fill="currentColor" stroke="none" /></>,
    check: <path d="M4 12l5 5L20 6" {...p} />,
    x: <path d="M6 6l12 12M18 6L6 18" {...p} />,
    undo: <path d="M9 7L4 12l5 5M4 12h11a5 5 0 0 1 0 10h-1" {...p} />,
    wifioff: <><path d="M3 3l18 18" {...p} /><path d="M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 4-2.6M2 9a16 16 0 0 1 5-3M22 9a16 16 0 0 0-6.5-3.4" {...p} /><circle cx="12" cy="20" r="1" fill="currentColor" stroke="none" /></>,
    play: <path d="M7 4l13 8-13 8z" {...p} fill="currentColor" />,
    pause: <><rect x="6" y="4" width="4" height="16" rx="1" {...p} fill="currentColor" /><rect x="14" y="4" width="4" height="16" rx="1" {...p} fill="currentColor" /></>,
    restart: <path d="M4 12a8 8 0 1 0 2.5-5.8M4 3v4h4" {...p} />,
    pin: <path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6zM12 14v7" {...p} />,
    arrow: <path d="M5 12h14M13 6l6 6-6 6" {...p} />,
    layers: <path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5" {...p} />,
    spark: <path d="M12 3v6M12 15v6M3 12h6M15 12h6M6 6l3 3M15 15l3 3M18 6l-3 3M9 15l-3 3" {...p} />,
    grid: <><rect x="4" y="4" width="7" height="7" rx="1" {...p} /><rect x="13" y="4" width="7" height="7" rx="1" {...p} /><rect x="4" y="13" width="7" height="7" rx="1" {...p} /><rect x="13" y="13" width="7" height="7" rx="1" {...p} /></>,
    text: <path d="M5 7V5h14v2M12 5v14M9 19h6" {...p} />,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" {...p} /><circle cx="12" cy="12" r="2.5" {...p} /></>,
    flow: <><circle cx="6" cy="6" r="2.5" {...p} /><circle cx="18" cy="18" r="2.5" {...p} /><path d="M6 8.5v4a3 3 0 0 0 3 3h6.5" {...p} /></>,
    book: <path d="M4 5a2 2 0 0 1 2-2h6v18H6a2 2 0 0 1-2-2zM12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2h-6" {...p} />,
  };
  return <svg viewBox="0 0 24 24" style={s} aria-hidden="true">{paths[name] || null}</svg>;
}

const TINT = {
  cool: 'var(--ck-signal-cool)', violet: 'var(--ck-signal-violet)',
  warn: 'var(--ck-signal-warn)', pos: 'var(--ck-signal-pos)', neg: 'var(--ck-signal-neg)',
};

// ── Placeholder de vue (page / image / slide) : hachures + libellé mono ────
function ViewTile({ view, size = 'md', active = false, dim = false, onClick, style }) {
  const doc = DOCS[view.docId];
  const tint = TINT[doc.tint] || 'var(--ck-signal-cool)';
  const dims = { sm: 52, md: 96, lg: 150, xl: 260 }[size] || 96;
  const isImg = view.shape === 'image';
  const stripe = isImg
    ? `repeating-linear-gradient(135deg, ${tint}14 0 7px, transparent 7px 14px)`
    : `repeating-linear-gradient(0deg, var(--ck-stroke-1) 0 11px, transparent 11px 12px)`;
  return (
    <button onClick={onClick} title={`${doc.name} · ${view.label}`} style={{
      appearance: 'none', textAlign: 'left', cursor: onClick ? 'pointer' : 'default',
      position: 'relative', width: '100%', aspectRatio: '4 / 3',
      maxWidth: dims === 260 ? '100%' : dims * 1.33,
      background: 'var(--ck-bg-inset)',
      border: `1px solid ${active ? tint : 'var(--ck-stroke-2)'}`,
      borderRadius: 'var(--ck-radius-md)', overflow: 'hidden',
      boxShadow: active ? `0 0 0 1px ${tint}, 0 0 22px ${tint}40` : 'none',
      opacity: dim ? 0.5 : 1, transition: 'opacity var(--ck-dur-med) var(--ck-ease-out), box-shadow var(--ck-dur-med)',
      padding: 0, ...style,
    }}>
      <div style={{ position: 'absolute', inset: 0, background: stripe }} />
      <div style={{ position: 'absolute', inset: 0,
        background: `linear-gradient(160deg, ${tint}10, transparent 55%)` }} />
      {/* étiquette */}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0,
        padding: '7px 9px', background: 'linear-gradient(0deg, var(--ck-bg-void) 30%, transparent)',
        display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, color: 'var(--ck-fg-1)',
          fontWeight: 600, lineHeight: 1.15 }}>{view.label}</span>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9, color: 'var(--ck-fg-4)',
          letterSpacing: '0.04em' }}>
          {doc.kind === 'image' ? 'IMG' : 'p.' + view.page} · {view.sub}
        </span>
      </div>
      {/* coin type */}
      <div style={{ position: 'absolute', top: 6, left: 6, color: tint, opacity: 0.85 }}>
        <Icon name={isImg ? 'image' : 'doc'} size={13} />
      </div>
      {active && (
        <div style={{ position: 'absolute', top: 6, right: 6, display: 'flex', alignItems: 'center',
          gap: 4, padding: '2px 6px', borderRadius: 999, background: 'var(--ck-bg-void)',
          border: `1px solid ${tint}` }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: tint,
            boxShadow: `0 0 6px ${tint}` }} />
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 8.5, letterSpacing: '0.1em',
            color: tint, fontWeight: 700 }}>EN SCÈNE</span>
        </div>
      )}
    </button>
  );
}

// ── Bouton cockpit ────────────────────────────────────────────────────────
function Btn({ children, onClick, variant = 'ghost', size = 'md', icon, disabled, style, title }) {
  const [h, setH] = useStateUI(false);
  const pad = size === 'sm' ? '5px 9px' : size === 'lg' ? '11px 18px' : '7px 13px';
  const fs = size === 'sm' ? 11.5 : size === 'lg' ? 14 : 12.5;
  const base = {
    appearance: 'none', display: 'inline-flex', alignItems: 'center', gap: 7,
    fontFamily: 'var(--ck-font-sans)', fontSize: fs, fontWeight: 550, padding: pad,
    borderRadius: 'var(--ck-radius-md)', cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid transparent', transition: 'all var(--ck-dur-fast) var(--ck-ease-out)',
    letterSpacing: '0.01em', whiteSpace: 'nowrap', opacity: disabled ? 0.45 : 1, ...style,
  };
  const variants = {
    primary: { background: h ? 'var(--ck-signal-cool)' : 'color-mix(in oklab, var(--ck-signal-cool) 88%, transparent)',
      color: 'var(--ck-on-signal)', boxShadow: h ? 'var(--ck-glow-cool)' : 'none' },
    solid: { background: h ? 'var(--ck-bg-panel-hi)' : 'var(--ck-bg-panel)',
      color: 'var(--ck-fg-1)', borderColor: 'var(--ck-stroke-2)' },
    ghost: { background: h ? 'var(--ck-tint-soft)' : 'transparent',
      color: h ? 'var(--ck-fg-1)' : 'var(--ck-fg-2)', borderColor: 'var(--ck-stroke-2)' },
    bare: { background: h ? 'var(--ck-tint-faint)' : 'transparent',
      color: h ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)', borderColor: 'transparent' },
  };
  return (
    <button title={title} onClick={disabled ? undefined : onClick} disabled={disabled}
      onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
      style={{ ...base, ...variants[variant] }}>
      {icon && <Icon name={icon} size={fs + 2} />}{children}
    </button>
  );
}

// ── Pastille d'état ───────────────────────────────────────────────────────
function Dot({ kind = 'pos', live = false, size = 6 }) {
  const c = { pos: 'var(--ck-signal-pos)', cool: 'var(--ck-signal-cool)',
    violet: 'var(--ck-signal-violet)', warn: 'var(--ck-signal-warn)',
    neg: 'var(--ck-signal-neg)', neutral: 'var(--ck-fg-4)' }[kind];
  return <span className={live ? 'ck-live-dot ' + (kind === 'pos' ? '' : kind) : ''}
    style={live ? {} : { display: 'inline-block', width: size, height: size, borderRadius: '50%',
      background: c, flex: 'none' }} />;
}

// ── Étiquette mono ────────────────────────────────────────────────────────
function Label({ children, style }) {
  return <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, letterSpacing: '0.12em',
    textTransform: 'uppercase', color: 'var(--ck-fg-4)', ...style }}>{children}</span>;
}

// ── Annotation (bulle de raisonnement, dans les maquettes) ────────────────
function Annot({ n, children, style }) {
  return (
    <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', ...style }}>
      <span style={{ flex: 'none', width: 19, height: 19, borderRadius: '50%',
        border: '1px solid var(--ck-signal-cool)', color: 'var(--ck-signal-cool)',
        fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, fontWeight: 700,
        display: 'grid', placeItems: 'center', marginTop: 1 }}>{n}</span>
      <span style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-2)' }}>{children}</span>
    </div>
  );
}

Object.assign(window, { Icon, ViewTile, Btn, Dot, Label, Annot, TINT });
