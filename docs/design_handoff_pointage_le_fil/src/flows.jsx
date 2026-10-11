// flows.jsx — écrans périphériques du parcours :
// FinScreen (triage pré-rempli) · IndexScreen (indexation fond) ·
// PiecesScreen (pièces & pointage + comparatif des 2 approches) · EdgeScreen (cas limites)
const { useState: fS, useEffect: fE, useRef: fR } = React;

const SHARE = {
  full: { label: 'Entier', dot: 'pos' },
  excerpt: { label: 'Extrait', dot: 'cool' },
  none: { label: 'Aucun', dot: 'neutral' },
};

// petit segmenté inline
function Seg({ value, options, onChange }) {
  return (
    <div style={{ display: 'inline-flex', padding: 2, borderRadius: 'var(--ck-radius-md)',
      background: 'var(--ck-bg-void)', border: '1px solid var(--ck-stroke-2)', gap: 2 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button key={o.value} onClick={() => onChange(o.value)} style={{ appearance: 'none',
            display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 10px',
            borderRadius: 'var(--ck-radius-sm)', cursor: 'pointer', border: 'none',
            fontFamily: 'var(--ck-font-sans)', fontSize: 11.5, fontWeight: 550,
            background: on ? 'var(--ck-bg-panel-hi)' : 'transparent',
            color: on ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)',
            boxShadow: on ? 'var(--ck-shadow-card)' : 'none' }}>
            <Dot kind={o.dot} size={5} />{o.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Triage de fin (récapitulatif pré-rempli, pas de formulaire) ───────────
function FinScreen({ onOpenReport }) {
  const [rows, setRows] = fS(TRIAGE.map((r) => ({ ...r, choice: r.proposal })));
  const shareCount = rows.filter((r) => r.choice !== 'none').length;
  return (
    <div className="ck-scroll" style={{ position: 'absolute', inset: 0, overflowY: 'auto',
      background: 'var(--ck-bg-base)', display: 'flex', justifyContent: 'center' }}>
      <div style={{ width: 'min(760px, 100%)', padding: '46px 28px 60px' }}>
        <Label>Fin de séance · étape légère</Label>
        <h1 style={{ margin: '12px 0 8px', fontSize: 28, fontWeight: 680, color: 'var(--ck-fg-1)',
          letterSpacing: '-0.01em' }}>Confirmer ce qui est partagé</h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: 'var(--ck-fg-3)', maxWidth: 580 }}>
          Le niveau de partage est <b style={{ color: 'var(--ck-fg-2)' }}>déduit de votre usage</b> pendant la séance.
          Vous ne remplissez rien — vous corrigez si besoin. Tout reste réversible depuis le rapport.
        </p>

        <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => {
            const doc = DOCS[r.docId];
            const tint = TINT[doc.tint];
            return (
              <div key={r.docId} style={{ display: 'flex', alignItems: 'center', gap: 16,
                padding: '14px 16px', borderRadius: 'var(--ck-radius-lg)',
                border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)',
                opacity: r.choice === 'none' ? 0.62 : 1, transition: 'opacity var(--ck-dur-med)' }}>
                <div style={{ width: 34, height: 42, flex: 'none', borderRadius: 'var(--ck-radius-sm)',
                  border: `1px solid ${tint}66`, background: `repeating-linear-gradient(0deg, var(--ck-stroke-1) 0 5px, transparent 5px 6px)`,
                  display: 'grid', placeItems: 'center', color: tint }}>
                  <Icon name={doc.kind === 'image' ? 'image' : 'doc'} size={15} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 12.5, color: 'var(--ck-fg-1)',
                    fontWeight: 600 }}>{doc.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--ck-fg-4)', marginTop: 3 }}>{r.reason}</div>
                </div>
                <Seg value={r.choice} onChange={(v) => setRows((rs) => rs.map((x, j) => j === i ? { ...x, choice: v } : x))}
                  options={[{ value: 'full', ...SHARE.full }, { value: 'excerpt', ...SHARE.excerpt }, { value: 'none', ...SHARE.none }]} />
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 22, padding: '14px 16px', borderRadius: 'var(--ck-radius-md)',
          border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-inset)', display: 'flex',
          gap: 11, alignItems: 'flex-start' }}>
          <Icon name="layers" size={16} style={{ color: 'var(--ck-signal-violet)', marginTop: 1 }} />
          <span style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-3)' }}>
            L'<b style={{ color: 'var(--ck-fg-2)' }}>indexation lourde</b> (extraction + vectorisation) démarre en arrière-plan
            <b style={{ color: 'var(--ck-fg-2)' }}> dès l'ouverture du rapport</b>. Vous lisez immédiatement ; les sources
            deviennent cliquables au fil de l'indexation.
          </span>
        </div>

        <div style={{ marginTop: 26, display: 'flex', alignItems: 'center', gap: 16 }}>
          <Btn variant="primary" size="lg" icon="arrow" onClick={onOpenReport}>Ouvrir le rapport</Btn>
          <span style={{ fontSize: 12.5, color: 'var(--ck-fg-4)' }}>
            {shareCount} document{shareCount > 1 ? 's' : ''} partagé{shareCount > 1 ? 's' : ''} · indexation en file
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Indexation en arrière-plan ────────────────────────────────────────────
function IndexScreen() {
  const order = ['none', 'referenced', 'queued', 'indexing', 'indexed'];
  const init = TRIAGE.filter((r) => r.proposal !== 'none')
    .map((r) => ({ docId: r.docId, state: r.index, progress: r.index === 'referenced' ? 100 : 0 }));
  const [items, setItems] = fS(init);
  const [running, setRunning] = fS(true);

  fE(() => {
    if (!running) return;
    const iv = setInterval(() => {
      setItems((list) => {
        // une seule indexation à la fois (file)
        const idxIndexing = list.findIndex((x) => x.state === 'indexing');
        if (idxIndexing >= 0) {
          return list.map((x, i) => i === idxIndexing
            ? (x.progress >= 100 ? { ...x, state: 'indexed' } : { ...x, progress: Math.min(100, x.progress + 9) })
            : x);
        }
        const idxQueued = list.findIndex((x) => x.state === 'queued');
        if (idxQueued >= 0) return list.map((x, i) => i === idxQueued ? { ...x, state: 'indexing', progress: 4 } : x);
        return list;
      });
    }, 260);
    return () => clearInterval(iv);
  }, [running]);

  const allDone = items.every((x) => x.state === 'indexed' || x.state === 'referenced');
  const pct = Math.round(items.reduce((a, x) => a + (x.state === 'indexed' ? 100 : x.state === 'referenced' ? 100 : x.progress), 0) / items.length);

  return (
    <div className="ck-scroll" style={{ position: 'absolute', inset: 0, overflowY: 'auto',
      background: 'var(--ck-bg-base)', display: 'flex', justifyContent: 'center' }}>
      <div style={{ width: 'min(720px, 100%)', padding: '46px 28px 60px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Label>Moteur · arrière-plan</Label>
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 7,
            fontFamily: 'var(--ck-font-mono)', fontSize: 11, color: allDone ? 'var(--ck-signal-pos)' : 'var(--ck-signal-violet)' }}>
            <Dot kind={allDone ? 'pos' : 'violet'} live={!allDone} /> {allDone ? 'terminé' : pct + '%'}
          </span>
        </div>
        <h1 style={{ margin: '12px 0 8px', fontSize: 26, fontWeight: 680, color: 'var(--ck-fg-1)' }}>
          Indexation discrète, jamais bloquante
        </h1>
        <p style={{ margin: '0 0 24px', fontSize: 14, lineHeight: 1.55, color: 'var(--ck-fg-3)', maxWidth: 560 }}>
          Le rapport est <b style={{ color: 'var(--ck-fg-2)' }}>déjà ouvert et lisible</b>. Ce moteur tourne derrière —
          un seul indicateur de pouls suffit. Aucune action requise.
        </p>

        {/* fil de progression global */}
        <div style={{ height: 3, borderRadius: 999, background: 'var(--ck-stroke-2)', overflow: 'hidden', marginBottom: 26 }}>
          <div style={{ height: '100%', width: pct + '%', background: 'var(--ck-signal-violet)',
            boxShadow: 'var(--ck-glow-violet)', transition: 'width 0.26s linear' }} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((x) => {
            const doc = DOCS[x.docId];
            const st = INDEX_STATES[x.state];
            return (
              <div key={x.docId} style={{ display: 'flex', alignItems: 'center', gap: 14,
                padding: '12px 15px', borderRadius: 'var(--ck-radius-md)',
                border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)' }}>
                <Dot kind={st.dot} live={x.state === 'indexing'} />
                <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 12.5, color: 'var(--ck-fg-1)',
                  flex: 1, minWidth: 0 }}>{doc.name}</span>
                {x.state === 'indexing' && (
                  <div style={{ width: 120, height: 3, borderRadius: 999, background: 'var(--ck-stroke-2)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: x.progress + '%', background: st.fg, transition: 'width 0.26s linear' }} />
                  </div>
                )}
                <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 11, color: st.fg, width: 92,
                  textAlign: 'right', fontWeight: 600 }}>{st.label}</span>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 22, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {order.map((k) => (
            <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
              fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, color: 'var(--ck-fg-4)' }}>
              <Dot kind={INDEX_STATES[k].dot} size={5} /> {INDEX_STATES[k].label}
            </span>
          ))}
          <Btn size="sm" variant="bare" icon="restart" style={{ marginLeft: 'auto' }}
            onClick={() => { setItems(init.map((x) => ({ ...x, state: x.docId === 'photos' ? 'referenced' : 'queued', progress: 0 }))); setRunning(true); }}>
            Rejouer
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Pièces & pointage : modèle + comparatif des 2 approches ───────────────
function PointDemo({ mode, phrase, view, recommended }) {
  const doc = DOCS[view.docId];
  const tint = TINT[doc.tint];
  const meta = {
    auto: { title: 'Auto-détection', dot: 'cool',
      desc: 'L\'ancre se pose seule dès la phrase déictique. Zéro action — mais une mauvaise association passe inaperçue.',
      cost: 'Effort : nul', risk: 'Risque : faux positif silencieux' },
    manuel: { title: 'Geste manuel', dot: 'warn',
      desc: 'L\'expert tape la pièce (ou raccourci) pour pointer. Fiable à 100 % — mais demande une micro-action à chaque fois.',
      cost: 'Effort : 1 tap', risk: 'Risque : oubli de pointer' },
    hybride: { title: 'Fantôme auto-confirmé', dot: 'pos',
      desc: 'L\'ancre apparaît en « fantôme » et se confirme seule après 4 s, sauf rejet. Non bloquant, réversible, sans spam.',
      cost: 'Effort : nul (sauf correction)', risk: 'Risque : quasi nul' },
  }[mode];
  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12,
      padding: 16, borderRadius: 'var(--ck-radius-lg)',
      border: `1px solid ${recommended ? 'var(--ck-signal-pos)66' : 'var(--ck-stroke-2)'}`,
      background: 'var(--ck-bg-panel)', position: 'relative' }}>
      {recommended && (
        <span style={{ position: 'absolute', top: -10, left: 14, padding: '2px 9px', borderRadius: 999,
          background: 'var(--ck-signal-pos)', color: 'var(--ck-on-signal)', fontFamily: 'var(--ck-font-mono)',
          fontSize: 9, fontWeight: 700, letterSpacing: '0.1em' }}>RECO PAR DÉFAUT</span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Dot kind={meta.dot} /><span style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--ck-fg-1)' }}>{meta.title}</span>
      </div>
      {/* mini transcript */}
      <div style={{ padding: 11, borderRadius: 'var(--ck-radius-md)', background: 'var(--ck-bg-inset)',
        border: '1px solid var(--ck-stroke-2)', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <span style={{ fontSize: 12.5, color: 'var(--ck-fg-2)', lineHeight: 1.5 }}>
          « …comme on le voit, <span style={{ color: tint, fontWeight: 600 }}>{phrase}</span>… »
        </span>
        {mode === 'manuel' ? (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, padding: '6px 10px',
            borderRadius: 999, border: '1px dashed var(--ck-signal-warn)', color: 'var(--ck-signal-warn)',
            fontSize: 11.5, alignSelf: 'flex-start' }}>
            <Icon name="target" size={13} /> en attente du geste…
          </span>
        ) : (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, padding: '6px 10px',
            borderRadius: 999, alignSelf: 'flex-start',
            border: `1px ${mode === 'hybride' ? 'dashed var(--ck-fg-3)' : 'solid ' + tint + '88'}`,
            background: mode === 'hybride' ? 'transparent' : `color-mix(in oklab, ${tint} 12%, transparent)`,
            color: 'var(--ck-fg-1)', fontSize: 11.5,
            animation: mode === 'hybride' ? 'anc-breathe 2s ease-in-out infinite' : 'none' }}>
            <Icon name="target" size={13} style={{ color: mode === 'hybride' ? 'var(--ck-fg-3)' : tint }} />
            {view.label} · p.{view.page}
            {mode === 'hybride' && <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-4)' }}>auto 4s</span>}
            {mode === 'auto' && <Icon name="check" size={11} style={{ color: tint }} />}
          </span>
        )}
      </div>
      <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: 'var(--ck-fg-3)' }}>{meta.desc}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 'auto' }}>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>{meta.cost}</span>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>{meta.risk}</span>
      </div>
    </div>
  );
}

function PiecesScreen() {
  const views = [VIEWS.v_coupe, VIEWS.v_sp3, VIEWS.v_essais, VIEWS.v_fissure];
  const [active, setActive] = fS('v_coupe');
  return (
    <div className="ck-scroll" style={{ position: 'absolute', inset: 0, overflowY: 'auto',
      background: 'var(--ck-bg-base)', display: 'flex', justifyContent: 'center' }}>
      <div style={{ width: 'min(940px, 100%)', padding: '40px 28px 60px' }}>
        <Label>Pièces & pointage</Label>
        <h1 style={{ margin: '12px 0 8px', fontSize: 26, fontWeight: 680, color: 'var(--ck-fg-1)' }}>
          La Scène — plusieurs pièces, une seule « en scène »
        </h1>
        <p style={{ margin: '0 0 24px', fontSize: 14, lineHeight: 1.55, color: 'var(--ck-fg-3)', maxWidth: 620 }}>
          Au lieu d'empiler des chips, les pièces vivent dans une <b style={{ color: 'var(--ck-fg-2)' }}>pellicule latérale</b>.
          Une seule est « en scène » à la fois — c'est elle que le pointage référencera. Cliquez pour changer.
        </p>

        {/* démo scène */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 20, marginBottom: 40 }}>
          <ViewTile view={VIEWS[active]} size="xl" active />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            <Label>Pellicule · {views.length} épinglées</Label>
            {views.map((v) => (
              <div key={v.id} role="button" tabIndex={0} onClick={() => setActive(v.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActive(v.id); } }}
                style={{ cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 10, padding: 8, borderRadius: 'var(--ck-radius-md)',
                border: `1px solid ${v.id === active ? TINT[DOCS[v.docId].tint] : 'var(--ck-stroke-2)'}`,
                background: v.id === active ? 'var(--ck-bg-panel-hi)' : 'var(--ck-bg-panel)', textAlign: 'left' }}>
                <div style={{ width: 44, height: 33, flex: 'none', pointerEvents: 'none' }}><ViewTile view={v} size="sm" active={v.id === active} dim={v.id !== active} /></div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: 'var(--ck-fg-1)', fontWeight: 550 }}>{v.label}</div>
                  <div style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-4)' }}>
                    {DOCS[v.docId].name.replace(/\.(pdf|zip)/, '')} · {v.shape === 'image' ? 'img' : 'p.' + v.page}
                  </div>
                </div>
                {v.id === active && <span style={{ marginLeft: 'auto', fontFamily: 'var(--ck-font-mono)',
                  fontSize: 8.5, color: TINT[DOCS[v.docId].tint], fontWeight: 700 }}>EN SCÈNE</span>}
              </div>
            ))}
          </div>
        </div>

        <h2 style={{ margin: '0 0 6px', fontSize: 18, fontWeight: 650, color: 'var(--ck-fg-1)' }}>
          Pointage : deux approches, une recommandation
        </h2>
        <p style={{ margin: '0 0 18px', fontSize: 13.5, lineHeight: 1.5, color: 'var(--ck-fg-3)', maxWidth: 620 }}>
          Réponse directe à votre question ouverte « auto vs manuel ». Voici les deux extrêmes, puis l'option hybride
          que je recommande par défaut (réglable dans les Tweaks).
        </p>
        <div style={{ display: 'flex', gap: 14, alignItems: 'stretch', flexWrap: 'wrap' }}>
          <PointDemo mode="auto" phrase="cette coupe" view={VIEWS.v_coupe} />
          <PointDemo mode="manuel" phrase="cette coupe" view={VIEWS.v_coupe} />
          <PointDemo mode="hybride" phrase="cette coupe" view={VIEWS.v_coupe} recommended />
        </div>
      </div>
    </div>
  );
}

// ── Cas limites ───────────────────────────────────────────────────────────
function EdgeCard({ icon, iconKind, title, children, mock }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', borderRadius: 'var(--ck-radius-lg)',
      border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)', overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px 12px', borderBottom: '1px solid var(--ck-stroke-2)',
        display: 'flex', alignItems: 'center', gap: 9 }}>
        <Icon name={icon} size={16} style={{ color: `var(--ck-signal-${iconKind})` }} />
        <span style={{ fontSize: 14, fontWeight: 650, color: 'var(--ck-fg-1)' }}>{title}</span>
      </div>
      <div style={{ padding: 16, background: 'var(--ck-bg-inset)', borderBottom: '1px solid var(--ck-stroke-2)',
        minHeight: 116, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{mock}</div>
      <p style={{ margin: 0, padding: '13px 16px', fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-3)' }}>{children}</p>
    </div>
  );
}

function EdgeScreen() {
  return (
    <div className="ck-scroll" style={{ position: 'absolute', inset: 0, overflowY: 'auto',
      background: 'var(--ck-bg-base)', display: 'flex', justifyContent: 'center' }}>
      <div style={{ width: 'min(940px, 100%)', padding: '40px 28px 60px' }}>
        <Label>Robustesse</Label>
        <h1 style={{ margin: '12px 0 8px', fontSize: 26, fontWeight: 680, color: 'var(--ck-fg-1)' }}>Cas limites & états</h1>
        <p style={{ margin: '0 0 26px', fontSize: 14, lineHeight: 1.55, color: 'var(--ck-fg-3)', maxWidth: 600 }}>
          Tout est conçu pour rester <b style={{ color: 'var(--ck-fg-2)' }}>réversible et non bloquant</b>,
          même quand ça dérape. Aucune modale en pleine séance.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          <EdgeCard icon="target" iconKind="cool" title="Erreur de pointage"
            mock={<div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>relier à :</span>
              {[VIEWS.v_coupe, VIEWS.v_sp3].map((v) => (
                <span key={v.id} style={{ padding: '4px 9px', borderRadius: 'var(--ck-radius-sm)', fontSize: 11,
                  border: `1px solid ${v.id === 'v_sp3' ? 'var(--ck-signal-cool)' : 'var(--ck-stroke-2)'}`,
                  color: v.id === 'v_sp3' ? 'var(--ck-signal-cool)' : 'var(--ck-fg-3)' }}>{v.label}</span>
              ))}
            </div>}>
            Chaque ancre reste cliquable : <b style={{ color: 'var(--ck-fg-2)' }}>« Relier… »</b> rebascule la référence
            vers une autre pièce de la Scène, sans casser le fil ni recharger.
          </EdgeCard>

          <EdgeCard icon="question" iconKind="warn" title="Déictique ambigu"
            mock={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, padding: '6px 10px',
              borderRadius: 999, border: '1px dashed var(--ck-signal-warn)', color: 'var(--ck-signal-warn)', fontSize: 11.5 }}>
              <Icon name="target" size={13} /> 2 vues à l'écran — « ici » ?
            </span>}>
            Si deux pièces sont en scène, la confiance chute : l'ancre s'affiche en
            <b style={{ color: 'var(--ck-signal-warn)' }}> incertain</b> avec choix explicite, jamais une fausse certitude.
          </EdgeCard>

          <EdgeCard icon="wifioff" iconKind="warn" title="Perte réseau"
            mock={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '7px 11px',
              borderRadius: 'var(--ck-radius-md)', background: 'color-mix(in oklab, var(--ck-signal-warn) 14%, transparent)',
              border: '1px solid var(--ck-signal-warn)44', color: 'var(--ck-fg-1)', fontSize: 11.5 }}>
              <Icon name="wifioff" size={14} style={{ color: 'var(--ck-signal-warn)' }} /> Capture locale · file de synchro
            </span>}>
            La capture ne dépend pas du réseau : transcription et pointages sont <b style={{ color: 'var(--ck-fg-2)' }}>bufferisés
            en local</b> puis synchronisés à la reprise. Bandeau discret, zéro interruption.
          </EdgeCard>

          <EdgeCard icon="restart" iconKind="pos" title="Reprise de séance"
            mock={<div style={{ padding: '10px 13px', borderRadius: 'var(--ck-radius-md)', background: 'var(--ck-bg-panel)',
              border: '1px solid var(--ck-stroke-2)', display: 'flex', flexDirection: 'column', gap: 8, minWidth: 200 }}>
              <span style={{ fontSize: 12, color: 'var(--ck-fg-1)' }}>Séance interrompue à <b>14:38</b></span>
              <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>3 pièces · 5 réf · 2 notes</span>
              <div style={{ display: 'flex', gap: 6 }}>
                <span style={{ padding: '3px 9px', borderRadius: 'var(--ck-radius-sm)', fontSize: 10.5,
                  background: 'var(--ck-signal-cool)', color: 'var(--ck-on-signal)', fontWeight: 600 }}>Reprendre</span>
                <span style={{ padding: '3px 9px', borderRadius: 'var(--ck-radius-sm)', fontSize: 10.5,
                  border: '1px solid var(--ck-stroke-2)', color: 'var(--ck-fg-3)' }}>Clôturer</span>
              </div>
            </div>}>
            L'état du Fil est persistant. À la réouverture, une carte propose de
            <b style={{ color: 'var(--ck-fg-2)' }}> reprendre exactement où on s'est arrêté</b> — contexte et scène restaurés.
          </EdgeCard>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FinScreen, IndexScreen, PiecesScreen, EdgeScreen });
