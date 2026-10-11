// report.jsx — lecture du rapport publié. Mode Cockpit (dense). Sources cliquables :
// chaque affirmation porte un marqueur → ouvre l'inspecteur de provenance
// (vue pointée + zone surlignée + retour à l'instant du transcript).
const { useState: rS } = React;

// instants de transcript associés aux sources (provenance bidirectionnelle)
const SRC_MOMENT = {
  v_coupe: '14:31:24', v_sp3: '14:32:58', v_essais: '14:33:41', v_fissure: '14:35:12',
};

function SourceMark({ n, view, active, onClick }) {
  const tint = view ? TINT[DOCS[view.docId].tint] : 'var(--ck-fg-4)';
  return (
    <button onClick={onClick} title={view ? `${DOCS[view.docId].name} · p.${view.page}` : ''}
      style={{ appearance: 'none', cursor: 'pointer', verticalAlign: 'super', marginLeft: 3,
        display: 'inline-flex', alignItems: 'center', gap: 3, padding: '1px 6px 1px 5px',
        borderRadius: 999, lineHeight: 1,
        border: `1px solid ${active ? tint : tint + '55'}`,
        background: active ? `color-mix(in oklab, ${tint} 22%, transparent)` : `color-mix(in oklab, ${tint} 9%, transparent)`,
        color: tint, fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, fontWeight: 700 }}>
      <Icon name="target" size={9} /> {n}
    </button>
  );
}

function ReportScreen() {
  const [sel, setSel] = rS('v_coupe');
  // n° de source par vue (ordre d'apparition)
  const seq = []; REPORT.sections.forEach((s) => s.body.forEach((b) => { if (b.src && !seq.includes(b.src)) seq.push(b.src); }));
  const numOf = (src) => seq.indexOf(src) + 1;
  const selView = sel ? VIEWS[sel] : null;
  const selDoc = selView ? DOCS[selView.docId] : null;
  const selIndexed = sel === 'v_coupe' || sel === 'v_sp3' || sel === 'v_essais'; // photos = référencé seulement
  const tint = selView ? TINT[selDoc.tint] : 'var(--ck-signal-cool)';

  return (
    <div style={{ position: 'absolute', inset: 0, display: 'grid', gridTemplateColumns: '1fr 396px',
      background: 'var(--ck-bg-base)' }}>
      {/* document */}
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--ck-stroke-2)' }}>
        {/* en-tête + pouls d'indexation */}
        <div style={{ flex: 'none', padding: '16px 28px', borderBottom: '1px solid var(--ck-stroke-2)',
          background: 'var(--ck-bg-panel)', display: 'flex', alignItems: 'center', gap: 14 }}>
          <Icon name="book" size={17} style={{ color: 'var(--ck-fg-3)' }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--ck-fg-1)', whiteSpace: 'nowrap',
              overflow: 'hidden', textOverflow: 'ellipsis' }}>{REPORT.title}</div>
            <div style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)', marginTop: 2 }}>{REPORT.ref}</div>
          </div>
          <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 7,
            padding: '5px 10px', borderRadius: 999, border: '1px solid var(--ck-stroke-2)',
            background: 'var(--ck-bg-inset)' }}>
            <Dot kind="violet" live /><span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10,
              color: 'var(--ck-fg-3)' }}>indexation 2/3 · sources cliquables au fil</span>
          </span>
        </div>

        {/* corps */}
        <div className="ck-scroll ck-ambient-grid" style={{ flex: 1, overflowY: 'auto', padding: '34px 0' }}>
          <div style={{ maxWidth: 660, margin: '0 auto', padding: '0 28px' }}>
            {REPORT.sections.map((s, i) => (
              <div key={i} style={{ marginBottom: 34 }}>
                <h2 style={{ margin: '0 0 14px', fontSize: 12, fontWeight: 700, letterSpacing: '0.06em',
                  textTransform: 'uppercase', color: 'var(--ck-signal-cool)',
                  fontFamily: 'var(--ck-font-mono)' }}>{s.h}</h2>
                {s.body.map((b, j) => (
                  <p key={j} style={{ margin: '0 0 14px', fontSize: 15.5, lineHeight: 1.7, textWrap: 'pretty',
                    color: 'var(--ck-fg-1)',
                    background: b.src && b.src === sel ? `color-mix(in oklab, ${TINT[DOCS[VIEWS[b.src].docId].tint]} 9%, transparent)` : 'transparent',
                    borderRadius: 'var(--ck-radius-sm)', padding: b.src && b.src === sel ? '4px 8px' : '0',
                    margin: b.src && b.src === sel ? '0 -8px 14px' : '0 0 14px',
                    transition: 'background var(--ck-dur-med)' }}>
                    {b.t}
                    {b.src
                      ? <SourceMark n={numOf(b.src)} view={VIEWS[b.src]} active={b.src === sel} onClick={() => setSel(b.src)} />
                      : <span style={{ marginLeft: 5, fontFamily: 'var(--ck-font-mono)', fontSize: 9.5,
                          color: 'var(--ck-fg-5)', verticalAlign: 'super' }}>(synthèse)</span>}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* inspecteur de provenance */}
      <div style={{ display: 'flex', flexDirection: 'column', background: 'var(--ck-bg-panel)', minWidth: 0 }}>
        <div style={{ flex: 'none', padding: '16px 18px', borderBottom: '1px solid var(--ck-stroke-2)',
          display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon name="eye" size={15} style={{ color: 'var(--ck-fg-3)' }} />
          <Label>Source & provenance</Label>
        </div>

        {selView ? (
          <div className="ck-scroll" style={{ flex: 1, overflowY: 'auto', padding: 18, display: 'flex',
            flexDirection: 'column', gap: 16 }}>
            {/* vue pointée avec zone surlignée */}
            <div style={{ position: 'relative' }}>
              <ViewTile view={selView} size="xl" active />
              {/* zone "pointée" surlignée */}
              <div style={{ position: 'absolute', top: '26%', left: '14%', width: '46%', height: '34%',
                border: `2px solid ${tint}`, borderRadius: 4, boxShadow: `0 0 0 9999px color-mix(in oklab, var(--ck-bg-void) 38%, transparent)`,
                pointerEvents: 'none' }}>
                <span style={{ position: 'absolute', top: -9, left: -1, padding: '1px 7px', borderRadius: 3,
                  background: tint, color: 'var(--ck-on-signal)', fontFamily: 'var(--ck-font-mono)',
                  fontSize: 8.5, fontWeight: 700, whiteSpace: 'nowrap' }}>ZONE POINTÉE</span>
              </div>
            </div>

            {/* méta source */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name={selDoc.kind === 'image' ? 'image' : 'doc'} size={14} style={{ color: tint }} />
                <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 12, color: 'var(--ck-fg-1)' }}>{selDoc.name}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Pill k="Vue">{selDoc.kind === 'image' ? 'cliché ' + selView.page : 'page ' + selView.page}</Pill>
                <Pill k="Objet">{selView.label}</Pill>
                <Pill k="Index" tint={selIndexed ? 'var(--ck-signal-pos)' : 'var(--ck-signal-cool)'}>
                  {selIndexed ? 'indexé' : 'référencé'}
                </Pill>
              </div>
            </div>

            {/* retour à l'instant du transcript */}
            <button style={{ appearance: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10,
              padding: '11px 13px', borderRadius: 'var(--ck-radius-md)', textAlign: 'left',
              border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-inset)', color: 'var(--ck-fg-2)' }}>
              <Icon name="undo" size={15} style={{ color: 'var(--ck-signal-cool)' }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: 'var(--ck-fg-1)' }}>Revoir l'instant capté</div>
                <div style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)', marginTop: 2 }}>
                  dit à {SRC_MOMENT[sel] || '—'} dans Le Fil
                </div>
              </div>
              <Icon name="arrow" size={14} />
            </button>

            <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.5, color: 'var(--ck-fg-4)' }}>
              Provenance bidirectionnelle : du rapport vers la pièce <i>et</i> vers le moment exact de la séance où
              l'expert l'a pointée.
            </p>
          </div>
        ) : (
          <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: 'var(--ck-fg-5)', fontSize: 12.5 }}>
            Cliquez une source dans le rapport
          </div>
        )}
      </div>
    </div>
  );
}

function Pill({ k, children, tint }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px',
      borderRadius: 999, border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-inset)' }}>
      <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 8.5, letterSpacing: '0.1em',
        textTransform: 'uppercase', color: 'var(--ck-fg-5)' }}>{k}</span>
      <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, color: tint || 'var(--ck-fg-2)', fontWeight: 600 }}>{children}</span>
    </span>
  );
}

Object.assign(window, { ReportScreen });
