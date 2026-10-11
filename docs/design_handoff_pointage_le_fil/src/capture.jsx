// capture.jsx — écran "Capture en direct" (le cœur). Mode Studio : chrome minimal,
// Le Fil au centre, La Scène + l'Oracle en périphérie atténuée.
const { useState: uS, useEffect: uE, useRef: uR } = React;

// ── Chip d'ancre déictique (inline dans le Fil) ───────────────────────────
function AnchorChip({ entry, scene, onConfirm, onDiscard, onRebind }) {
  const [rebinding, setRebinding] = uS(false);
  const [left, setLeft] = uS(0);
  const view = VIEWS[entry.viewId];
  const doc = DOCS[view.docId];
  const tint = TINT[doc.tint];

  // compte à rebours fantôme (hybride)
  uE(() => {
    if (entry.status !== 'pending' || entry.confirmAt == null) return;
    const tick = () => setLeft(Math.max(0, Math.ceil((entry.confirmAt - (window.__clock || 0)) / 1000)));
    tick(); const iv = setInterval(tick, 200); return () => clearInterval(iv);
  }, [entry.status, entry.confirmAt]);

  if (entry.status === 'discarded') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
        color: 'var(--ck-fg-5)', textDecoration: 'line-through', opacity: 0.6 }}>
        <Icon name="target" size={13} /> {view.label} — pointage annulé
      </span>
    );
  }

  const pending = entry.status === 'pending';
  const low = entry.status === 'lowconf';
  const accent = low ? 'var(--ck-signal-warn)' : pending ? 'var(--ck-fg-3)' : tint;

  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 6, maxWidth: 460 }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 10px',
        borderRadius: 999, alignSelf: 'flex-start',
        background: pending || low ? 'transparent' : `color-mix(in oklab, ${tint} 12%, transparent)`,
        border: `1px ${pending || low ? 'dashed' : 'solid'} ${pending || low ? accent : tint + '88'}`,
        color: 'var(--ck-fg-1)', animation: pending ? 'anc-breathe 2s ease-in-out infinite' : 'none' }}>
        <Icon name="target" size={14} style={{ color: accent }} />
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{view.label}</span>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>
          {doc.kind === 'image' ? 'IMG' : 'p.' + view.page} · {doc.name.replace('.pdf', '').replace('.zip', '')}
        </span>
        {!pending && !low && <Icon name="check" size={12} style={{ color: tint }} />}
      </span>

      {/* bandeau d'action selon le statut */}
      {pending && !rebinding && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, paddingLeft: 4 }}>
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, color: 'var(--ck-fg-4)' }}>
            confirmation auto dans {left}s
          </span>
          <ChipBtn onClick={() => onConfirm(entry.id)} accent="var(--ck-signal-pos)"><Icon name="check" size={11} /> Confirmer</ChipBtn>
          <ChipBtn onClick={() => setRebinding(true)}><Icon name="target" size={11} /> Relier…</ChipBtn>
          <ChipBtn onClick={() => onDiscard(entry.id)} accent="var(--ck-signal-neg)"><Icon name="x" size={11} /></ChipBtn>
        </span>
      )}
      {low && !rebinding && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, paddingLeft: 4 }}>
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, color: 'var(--ck-signal-warn)' }}>
            ⚠ association incertaine · « {entry.phrase} »
          </span>
          <ChipBtn onClick={() => setRebinding(true)} accent="var(--ck-signal-warn)"><Icon name="target" size={11} /> Corriger</ChipBtn>
          <ChipBtn onClick={() => onConfirm(entry.id)}><Icon name="check" size={11} /> OK</ChipBtn>
        </span>
      )}
      {rebinding && (
        <span style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingLeft: 4, alignItems: 'center' }}>
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>relier à :</span>
          {scene.map((v) => (
            <ChipBtn key={v.id} onClick={() => { onRebind(entry.id, v.id); setRebinding(false); }}
              accent={v.id === entry.viewId ? 'var(--ck-signal-cool)' : undefined}>
              {v.label}
            </ChipBtn>
          ))}
          <ChipBtn onClick={() => setRebinding(false)}><Icon name="x" size={11} /></ChipBtn>
        </span>
      )}
    </span>
  );
}

function ChipBtn({ children, onClick, accent }) {
  const [h, setH] = uS(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
      style={{ appearance: 'none', display: 'inline-flex', alignItems: 'center', gap: 4,
        fontFamily: 'var(--ck-font-sans)', fontSize: 11, fontWeight: 550, padding: '3px 8px',
        borderRadius: 'var(--ck-radius-sm)', cursor: 'pointer',
        border: `1px solid ${accent || 'var(--ck-stroke-2)'}`,
        background: h ? (accent ? `color-mix(in oklab, ${accent} 16%, transparent)` : 'var(--ck-tint-soft)') : 'transparent',
        color: accent || 'var(--ck-fg-2)' }}>
      {children}
    </button>
  );
}

// ── Entrée du Fil ─────────────────────────────────────────────────────────
function FeedEntry({ e, fs, scene, onConfirm, onDiscard, onRebind }) {
  const time = <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10,
    color: 'var(--ck-fg-5)', flex: 'none', width: 56, paddingTop: 4,
    fontVariantNumeric: 'tabular-nums' }}>{e.t}</span>;

  if (e.kind === 'speak') {
    return (
      <div style={{ display: 'flex', gap: 14 }}>
        {time}
        <p style={{ margin: 0, fontSize: fs, lineHeight: 1.62, textWrap: 'pretty',
          color: e.final ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)',
          fontStyle: e.final ? 'normal' : 'italic' }}>
          {e.text}
          {!e.final && <span style={{ display: 'inline-block', width: 2, height: fs,
            background: 'var(--ck-signal-cool)', marginLeft: 3, verticalAlign: 'text-bottom',
            animation: 'cur-blink 1s steps(2) infinite' }} />}
        </p>
      </div>
    );
  }
  if (e.kind === 'note') {
    return (
      <div style={{ display: 'flex', gap: 14 }}>
        {time}
        <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '8px 12px',
          borderLeft: `2px solid ${e.byUser ? 'var(--ck-signal-cool)' : 'var(--ck-signal-violet)'}`,
          background: 'var(--ck-tint-faint)', borderRadius: '0 var(--ck-radius-sm) var(--ck-radius-sm) 0',
          maxWidth: 540 }}>
          <Icon name="pen" size={14} style={{ color: e.byUser ? 'var(--ck-signal-cool)' : 'var(--ck-signal-violet)', marginTop: 2 }} />
          <span style={{ fontSize: fs - 2, lineHeight: 1.5, color: 'var(--ck-fg-2)' }}>{e.text}</span>
        </div>
      </div>
    );
  }
  if (e.kind === 'anchor') {
    return (
      <div style={{ display: 'flex', gap: 14 }}>
        {time}
        <AnchorChip entry={e} scene={scene} onConfirm={onConfirm} onDiscard={onDiscard} onRebind={onRebind} />
      </div>
    );
  }
  return null;
}

// ── Indicateur micro (barres animées) ─────────────────────────────────────
function MicMeter({ active }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 2, height: 20 }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} style={{ width: 2.5, borderRadius: 2, background: active ? 'var(--ck-signal-cool)' : 'var(--ck-fg-5)',
          height: active ? undefined : 4,
          animation: active ? `mic-bar 0.9s ease-in-out ${i * 0.12}s infinite` : 'none' }} />
      ))}
    </div>
  );
}

// ── Carte oracle ──────────────────────────────────────────────────────────
function OracleCard({ q, onPin, onDismiss }) {
  if (q.state === 'dismissed') return null;
  const pinned = q.state === 'pinned';
  return (
    <div style={{ padding: '10px 11px', borderRadius: 'var(--ck-radius-md)',
      border: `1px solid ${pinned ? 'var(--ck-signal-violet)88' : 'var(--ck-stroke-2)'}`,
      background: pinned ? 'color-mix(in oklab, var(--ck-signal-violet) 9%, transparent)' : 'var(--ck-bg-inset)',
      display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Icon name="spark" size={12} style={{ color: 'var(--ck-signal-violet)' }} />
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 8.5, letterSpacing: '0.12em',
          textTransform: 'uppercase', color: 'var(--ck-signal-violet)' }}>{q.tag}</span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--ck-font-mono)', fontSize: 9,
          color: 'var(--ck-fg-5)' }}>{q.t}</span>
      </div>
      <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.45, color: 'var(--ck-fg-2)' }}>{q.q}</p>
      <div style={{ display: 'flex', gap: 6 }}>
        <ChipBtn onClick={onPin} accent={pinned ? 'var(--ck-signal-violet)' : undefined}>
          <Icon name="pin" size={11} /> {pinned ? 'À traiter' : 'Garder'}
        </ChipBtn>
        <ChipBtn onClick={onDismiss}><Icon name="x" size={11} /> Ignorer</ChipBtn>
      </div>
    </div>
  );
}

// ── Écran de capture ──────────────────────────────────────────────────────
function CaptureScreen({ tweaks, onFinish, offline, onToggleOffline }) {
  const sess = useSession({ speed: tweaks.speed, oracleOn: tweaks.oracle, pointingMode: tweaks.pointing });
  const [draft, setDraft] = uS('');
  const feedRef = uR(null);

  // clock global lu par les chips (compte à rebours)
  uE(() => { window.__clock = sess.clock; }, [sess.clock]);

  // auto-scroll du Fil
  uE(() => { const el = feedRef.current; if (el) el.scrollTop = el.scrollHeight; }, [sess.feed]);

  const fs = { compact: 15, regular: 17, comfy: 19 }[tweaks.density] || 17;
  const activeView = sess.activeView ? VIEWS[sess.activeView] : null;
  const refsCount = sess.feed.filter((e) => e.kind === 'anchor' && e.status === 'confirmed').length;
  const aw = sess.awaitingGesture;

  const submitNote = () => { if (draft.trim()) { sess.addNote(draft); setDraft(''); } };

  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
      background: 'var(--ck-bg-base)' }}>
      {/* barre de statut (calme) */}
      <div style={{ height: 50, flex: 'none', display: 'flex', alignItems: 'center', gap: 14,
        padding: '0 18px', borderBottom: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)' }}>
        <Dot kind={offline ? 'warn' : 'neg'} live={!offline} />
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 11, color: offline ? 'var(--ck-signal-warn)' : 'var(--ck-signal-neg)',
          fontWeight: 700, letterSpacing: '0.08em' }}>{offline ? 'HORS-LIGNE · buffer local' : 'CAPTURE'}</span>
        <span style={{ width: 1, height: 18, background: 'var(--ck-stroke-2)' }} />
        <span style={{ fontSize: 13, color: 'var(--ck-fg-1)', fontWeight: 600 }}>Résidence Belvédère — Lot 7</span>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 12, color: 'var(--ck-fg-3)',
          fontVariantNumeric: 'tabular-nums' }}>{clockLabel(sess.clock)}</span>
        <Label style={{ marginLeft: 4 }}>{sess.phase}</Label>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)',
            padding: '3px 8px', border: '1px solid var(--ck-stroke-2)', borderRadius: 999 }}>
            pointage · {tweaks.pointing}
          </span>
          <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10, color: 'var(--ck-fg-4)' }}>
            {refsCount} réf.
          </span>
          <Btn size="sm" variant="bare" icon="wifioff" onClick={onToggleOffline}
            title="Simuler une perte réseau">{offline ? 'Rétablir' : ''}</Btn>
          <Btn size="sm" variant="bare" icon={sess.playing ? 'pause' : 'play'}
            onClick={() => sess.setPlaying(!sess.playing)} />
          <Btn size="sm" variant="bare" icon="restart" onClick={sess.restart} title="Rejouer" />
          <Btn size="sm" variant="primary" icon="arrow" onClick={onFinish}>Terminer la capture</Btn>
        </div>
      </div>

      {/* bandeau hors-ligne */}
      {offline && (
        <div style={{ flex: 'none', padding: '8px 18px', background: 'color-mix(in oklab, var(--ck-signal-warn) 12%, var(--ck-bg-panel))',
          borderBottom: '1px solid var(--ck-signal-warn)44', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="wifioff" size={14} style={{ color: 'var(--ck-signal-warn)' }} />
          <span style={{ fontSize: 12, color: 'var(--ck-fg-1)' }}>
            Réseau perdu — <b>la capture continue en local</b>. Transcription et pointages sont mis en file, synchronisés à la reprise. Rien n'est perdu.
          </span>
        </div>
      )}

      {/* corps 3 colonnes */}
      <div style={{ flex: 1, display: 'grid',
        gridTemplateColumns: tweaks.oracle ? '58px 1fr 340px' : '58px 1fr 300px', minHeight: 0 }}>
        {/* col 1 — spine temporelle */}
        <div style={{ borderRight: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)',
          display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 16, gap: 2 }}>
          <Icon name="mic" size={16} style={{ color: 'var(--ck-signal-cool)' }} />
          <MicMeter active={sess.playing && !offline} />
          <div style={{ flex: 1, width: 1, background: 'var(--ck-stroke-2)', marginTop: 14, position: 'relative' }}>
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <span key={i} style={{ position: 'absolute', left: -2, top: `${i * 15}%`, width: 5, height: 1,
                background: 'var(--ck-stroke-3)' }} />
            ))}
          </div>
          <span style={{ writingMode: 'vertical-rl', fontFamily: 'var(--ck-font-mono)', fontSize: 8.5,
            letterSpacing: '0.18em', color: 'var(--ck-fg-5)', textTransform: 'uppercase', padding: '8px 0' }}>
            le fil
          </span>
        </div>

        {/* col 2 — Le Fil + composer */}
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
          <div ref={feedRef} className="ck-scroll" style={{ flex: 1, overflowY: 'auto', padding: '24px 30px',
            display: 'flex', flexDirection: 'column', gap: 16 }}>
            {sess.feed.length === 0 && (
              <div style={{ color: 'var(--ck-fg-4)', fontSize: 13, fontStyle: 'italic', marginTop: 20 }}>
                En écoute… la parole et l'écrit s'inscrivent ici, sur un seul fil horodaté.
              </div>
            )}
            {sess.feed.map((e) => (
              <FeedEntry key={e.id} e={e} fs={fs} scene={sess.scene}
                onConfirm={sess.confirmAnchor} onDiscard={sess.discardAnchor} onRebind={sess.rebindAnchor} />
            ))}
          </div>

          {/* composer — modalité unique */}
          <div style={{ flex: 'none', padding: '14px 30px 18px', borderTop: '1px solid var(--ck-stroke-2)',
            background: 'var(--ck-bg-panel)' }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12,
              border: '1px solid var(--ck-stroke-3)', borderRadius: 'var(--ck-radius-lg)',
              background: 'var(--ck-bg-inset)', padding: '10px 12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, paddingBottom: 2 }}>
                <Icon name="mic" size={16} style={{ color: sess.playing && !offline ? 'var(--ck-signal-cool)' : 'var(--ck-fg-4)' }} />
                <MicMeter active={sess.playing && !offline} />
              </div>
              <span style={{ width: 1, height: 22, background: 'var(--ck-stroke-2)' }} />
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitNote(); } }}
                rows={1} placeholder="Écrire une note — s'insère dans le Fil  ·  la voix est captée en continu"
                style={{ flex: 1, resize: 'none', border: 'none', outline: 'none', background: 'transparent',
                  color: 'var(--ck-fg-1)', fontFamily: 'var(--ck-font-sans)', fontSize: 14, lineHeight: 1.5,
                  maxHeight: 90 }} />
              <Btn size="sm" variant={draft.trim() ? 'primary' : 'ghost'} icon="pen" onClick={submitNote}
                disabled={!draft.trim()}>Insérer</Btn>
            </div>
            <div style={{ display: 'flex', gap: 16, marginTop: 7, paddingLeft: 4 }}>
              <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-5)' }}>↵ insérer</span>
              <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-5)' }}>⇧↵ nouvelle ligne</span>
              <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5, color: 'var(--ck-fg-5)' }}>voix ⇄ écrit : même flux</span>
            </div>
          </div>
        </div>

        {/* col 3 — La Scène + Oracle */}
        <div style={{ borderLeft: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)',
          display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {/* Scène */}
          <div style={{ flex: tweaks.oracle ? '1 1 56%' : '1 1 100%', display: 'flex', flexDirection: 'column',
            minHeight: 0, overflow: 'hidden', padding: '14px 14px 10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flex: 'none' }}>
              <Icon name="layers" size={13} style={{ color: 'var(--ck-fg-3)' }} />
              <Label>La Scène · {sess.scene.length} pièce{sess.scene.length > 1 ? 's' : ''}</Label>
            </div>
            {/* vue active, agrandie */}
            {activeView ? (
              <div style={{ flex: '1 1 auto', minHeight: 0, marginBottom: 12, display: 'flex',
                justifyContent: 'center' }}>
                <div style={{ position: 'relative', height: '100%', maxWidth: '100%' }}>
                  <ViewTile view={activeView} size="xl" active style={{ height: '100%', width: 'auto' }} />
                  {/* mode manuel : cible pulsante à pointer */}
                  {aw && aw.viewId === activeView.id && (
                    <button onClick={sess.fireGesture} style={{ position: 'absolute', inset: 0,
                      display: 'grid', placeItems: 'center', background: 'color-mix(in oklab, var(--ck-bg-void) 35%, transparent)',
                      border: '2px dashed var(--ck-signal-cool)', borderRadius: 'var(--ck-radius-md)',
                      cursor: 'pointer', appearance: 'none' }}>
                      <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                        color: 'var(--ck-signal-cool)', animation: 'anc-breathe 1.4s ease-in-out infinite' }}>
                        <Icon name="target" size={32} />
                        <span style={{ fontSize: 11.5, fontWeight: 600 }}>Pointer cette vue</span>
                        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5 }}>« {aw.phrase} »</span>
                      </span>
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ flex: '1 1 auto', minHeight: 90, border: '1px dashed var(--ck-stroke-3)',
                borderRadius: 'var(--ck-radius-md)', display: 'grid', placeItems: 'center',
                color: 'var(--ck-fg-5)', fontSize: 12, marginBottom: 12 }}>aucune pièce montrée</div>
            )}
            {/* pellicule des autres pièces */}
            <div className="ck-scroll" style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4,
              flex: 'none' }}>
              {sess.scene.map((v) => (
                <div key={v.id} style={{ flex: 'none', width: 84 }}>
                  <ViewTile view={v} size="sm" dim={v.id !== sess.activeView}
                    active={v.id === sess.activeView} onClick={() => {}} />
                </div>
              ))}
            </div>
          </div>

          {/* Oracle */}
          {tweaks.oracle && (
            <div style={{ flex: '1 1 44%', display: 'flex', flexDirection: 'column', minHeight: 0,
              borderTop: '1px solid var(--ck-stroke-2)', padding: '14px 14px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <Icon name="spark" size={13} style={{ color: 'var(--ck-signal-violet)' }} />
                <Label>Pistes de l'oracle</Label>
                <span style={{ marginLeft: 'auto', fontFamily: 'var(--ck-font-mono)', fontSize: 9,
                  color: 'var(--ck-fg-5)' }}>non bloquant</span>
              </div>
              <div className="ck-scroll" style={{ flex: 1, overflowY: 'auto', display: 'flex',
                flexDirection: 'column', gap: 8 }}>
                {sess.oracle.filter((q) => q.state !== 'dismissed').length === 0 && (
                  <span style={{ color: 'var(--ck-fg-5)', fontSize: 12, fontStyle: 'italic' }}>
                    L'oracle écoute… il déposera ici des questions d'approfondissement.
                  </span>
                )}
                {sess.oracle.map((q) => (
                  <OracleCard key={q.id} q={q}
                    onPin={() => sess.setOracleState(q.id, q.state === 'pinned' ? 'open' : 'pinned')}
                    onDismiss={() => sess.setOracleState(q.id, 'dismissed')} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { CaptureScreen });
