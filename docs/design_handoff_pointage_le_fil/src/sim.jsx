// sim.jsx — moteur de simulation de la séance de capture.
// Expose window.useSession(opts) : un hook qui déroule buildScript() dans le temps,
// gère le streaming "provisoire → finalisé", les ancres déictiques selon le mode,
// et renvoie l'état du Fil + les commandes (play / pause / restart).
const { useState, useRef, useEffect, useCallback } = React;

let __uid = 0;
const uid = (p) => `${p}-${++__uid}`;

// Horloge → libellé "mm:ss" (départ fictif 14:31).
function clockLabel(ms) {
  const base = 14 * 3600 + 31 * 60; // 14:31:00
  const total = base + Math.floor(ms / 1000);
  const h = Math.floor(total / 3600) % 24;
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const p = (n) => String(n).padStart(2, '0');
  return `${p(h)}:${p(m)}:${p(s)}`;
}

const TICK = 90;            // ms par tick d'horloge
const WORDS_PER_TICK = 1.6; // débit de "frappe" de la parole streamée
const FINALIZE_DELAY = 420; // provisoire → finalisé
const HYBRID_CONFIRM = 4200; // ms avant auto-confirmation d'une ancre fantôme

function useSession({ speed = 1, oracleOn = true, pointingMode = 'hybride' } = {}) {
  // État exposé
  const [feed, setFeed] = useState([]);       // entrées du Fil (speak / note / anchor)
  const [scene, setScene] = useState([]);     // vues épinglées
  const [activeView, setActiveView] = useState(null);
  const [oracle, setOracle] = useState([]);   // pistes de l'oracle
  const [phase, setPhase] = useState('—');
  const [clock, setClock] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [done, setDone] = useState(false);
  const [awaitingGesture, setAwaitingGesture] = useState(null); // mode manuel

  // Refs internes au moteur (évitent les stale closures dans l'intervalle)
  const script = useRef(buildScript());
  const cursor = useRef(0);
  const clockRef = useRef(0);
  const nextAt = useRef(0);        // horloge à laquelle exécuter l'événement courant
  const streaming = useRef(null);  // { id, words, shown, pauseAfter }
  const opts = useRef({ speed, oracleOn, pointingMode });
  useEffect(() => { opts.current = { speed, oracleOn, pointingMode }; }, [speed, oracleOn, pointingMode]);

  const reset = useCallback(() => {
    cursor.current = 0;
    clockRef.current = 0;
    nextAt.current = 0;
    streaming.current = null;
    setFeed([]); setScene([]); setActiveView(null); setOracle([]);
    setPhase('—'); setClock(0); setDone(false); setAwaitingGesture(null);
    setPlaying(true);
  }, []);

  // Confirme une ancre fantôme (hybride) ou en attente.
  const confirmAnchor = useCallback((id) => {
    setFeed((f) => f.map((e) => e.id === id && e.kind === 'anchor'
      ? { ...e, status: 'confirmed' } : e));
  }, []);
  const discardAnchor = useCallback((id) => {
    setFeed((f) => f.map((e) => e.id === id && e.kind === 'anchor'
      ? { ...e, status: 'discarded' } : e));
  }, []);
  const rebindAnchor = useCallback((id, viewId) => {
    setFeed((f) => f.map((e) => e.id === id && e.kind === 'anchor'
      ? { ...e, viewId, status: 'confirmed', confidence: 1 } : e));
  }, []);

  // Geste explicite (mode manuel) : matérialise l'ancre en attente.
  const fireGesture = useCallback(() => {
    setAwaitingGesture((aw) => {
      if (!aw) return null;
      setFeed((f) => [...f, {
        id: uid('anc'), kind: 'anchor', t: clockLabel(clockRef.current),
        viewId: aw.viewId, confidence: 1, status: 'confirmed', phrase: aw.phrase,
      }]);
      return null;
    });
  }, []);

  // Insertion manuelle d'une note par l'utilisateur (composer).
  const addNote = useCallback((text) => {
    if (!text.trim()) return;
    setFeed((f) => [...f, {
      id: uid('note'), kind: 'note', t: clockLabel(clockRef.current),
      text: text.trim(), byUser: true,
    }]);
  }, []);

  // Exécute un événement du script.
  const runEvent = useCallback((ev) => {
    const m = opts.current.pointingMode;
    switch (ev.type) {
      case 'phase':
        setPhase(ev.label);
        break;
      case 'speak': {
        const id = uid('sp');
        const words = ev.text.split(' ');
        streaming.current = { id, words, shown: 0, pauseAfter: ev.pauseAfter || 400 };
        setFeed((f) => [...f, {
          id, kind: 'speak', t: clockLabel(clockRef.current), text: '', final: false,
        }]);
        return true; // streaming pilote l'avancement
      }
      case 'oracle':
        if (opts.current.oracleOn) {
          setOracle((o) => [...o, {
            id: uid('orc'), q: ev.q, tag: ev.tag, state: 'open',
            t: clockLabel(clockRef.current),
          }]);
        }
        break;
      case 'pin': {
        const view = VIEWS[ev.viewId];
        setScene((s) => s.find((v) => v.id === view.id) ? s : [...s, view]);
        setActiveView(view.id);
        break;
      }
      case 'show':
        setActiveView(ev.viewId);
        break;
      case 'deictic': {
        if (m === 'manuel') {
          // pas d'ancre tant que le geste n'est pas posé
          setAwaitingGesture({ viewId: ev.viewId, phrase: ev.phrase });
        } else {
          const lowConf = ev.confidence < 0.7;
          let status = 'confirmed';
          if (m === 'hybride') status = 'pending';
          else if (m === 'auto' && lowConf) status = 'lowconf';
          setFeed((f) => [...f, {
            id: uid('anc'), kind: 'anchor', t: clockLabel(clockRef.current),
            viewId: ev.viewId, confidence: ev.confidence, status,
            phrase: ev.phrase, ambiguousWith: ev.ambiguousWith || null,
            confirmAt: status === 'pending' ? clockRef.current + HYBRID_CONFIRM : null,
          }]);
        }
        break;
      }
      case 'gesture':
        if (m === 'manuel') fireGesture();
        break;
      case 'note':
        setFeed((f) => [...f, {
          id: uid('note'), kind: 'note', t: clockLabel(clockRef.current), text: ev.text,
        }]);
        break;
      default: break;
    }
    return false;
  }, [fireGesture]);

  // Boucle d'horloge
  useEffect(() => {
    const iv = setInterval(() => {
      if (!playing) return;
      const sp = opts.current.speed;
      clockRef.current += TICK * sp;
      setClock(clockRef.current);

      // 1) auto-confirmation des ancres fantômes (hybride)
      setFeed((f) => {
        let changed = false;
        const next = f.map((e) => {
          if (e.kind === 'anchor' && e.status === 'pending'
              && e.confirmAt != null && clockRef.current >= e.confirmAt) {
            changed = true; return { ...e, status: 'confirmed' };
          }
          return e;
        });
        return changed ? next : f;
      });

      // 2) streaming de la parole en cours
      if (streaming.current) {
        const st = streaming.current;
        st.shown = Math.min(st.words.length, st.shown + WORDS_PER_TICK * sp);
        const shownInt = Math.floor(st.shown);
        const text = st.words.slice(0, shownInt).join(' ');
        setFeed((f) => f.map((e) => e.id === st.id ? { ...e, text } : e));
        if (st.shown >= st.words.length) {
          const id = st.id, pause = st.pauseAfter;
          streaming.current = null;
          setTimeout(() => {
            setFeed((f) => f.map((e) => e.id === id ? { ...e, final: true } : e));
          }, FINALIZE_DELAY);
          nextAt.current = clockRef.current + pause;
        }
        return;
      }

      // 3) avancement du script
      if (cursor.current >= script.current.length) {
        if (!streaming.current) setDone(true);
        return;
      }
      if (clockRef.current >= nextAt.current) {
        const ev = script.current[cursor.current];
        cursor.current += 1;
        const isStreaming = runEvent(ev);
        // gap de l'événement SUIVANT (négatif = rétro-daté, traité comme 0)
        const nextEv = script.current[cursor.current];
        const gap = nextEv ? Math.max(0, nextEv.gap) : 0;
        if (!isStreaming) nextAt.current = clockRef.current + gap;
      }
    }, TICK);
    return () => clearInterval(iv);
  }, [playing, runEvent]);

  return {
    feed, scene, activeView, oracle, phase, clock, clockLabel,
    playing, done, awaitingGesture,
    setPlaying, restart: reset,
    confirmAnchor, discardAnchor, rebindAnchor, fireGesture, addNote,
    setOracleState: (id, state) =>
      setOracle((o) => o.map((q) => q.id === id ? { ...q, state } : q)),
  };
}

Object.assign(window, { useSession, clockLabel });
