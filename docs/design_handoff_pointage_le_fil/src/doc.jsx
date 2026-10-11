// doc.jsx — la contre-proposition écrite (mode DOC). Document cockpit lisible,
// avec liens "→ Voir dans le prototype" qui basculent vers PROTO.
const { useState: dS } = React;

function Kicker({ children }) {
  return <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10.5, letterSpacing: '0.16em',
    textTransform: 'uppercase', color: 'var(--ck-signal-cool)' }}>{children}</span>;
}

function DocSection({ n, title, children }) {
  return (
    <section style={{ marginBottom: 56, scrollMarginTop: 24 }} id={'sec-' + n}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 18,
        paddingBottom: 12, borderBottom: '1px solid var(--ck-stroke-2)' }}>
        <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 13, color: 'var(--ck-fg-5)',
          fontWeight: 700 }}>{String(n).padStart(2, '0')}</span>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 680, color: 'var(--ck-fg-1)',
          letterSpacing: '-0.01em' }}>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function P({ children, style }) {
  return <p style={{ margin: '0 0 14px', fontSize: 14.5, lineHeight: 1.68, textWrap: 'pretty',
    color: 'var(--ck-fg-2)', ...style }}>{children}</p>;
}
function B({ children }) { return <b style={{ color: 'var(--ck-fg-1)', fontWeight: 650 }}>{children}</b>; }

function Goto({ onGoto, to, children }) {
  return (
    <span style={{ display: 'inline-block', margin: '4px 0' }}>
      <Btn size="sm" variant="ghost" icon="arrow" onClick={() => onGoto(to)}>{children}</Btn>
    </span>
  );
}

// item d'analyse (verdict coloré)
function Verdict({ kind, label, children }) {
  const map = { keep: ['pos', 'On garde'], weak: ['warn', 'Faible'], risk: ['neg', 'Risqué'], cut: ['neutral', 'Superflu'] };
  const [dot, def] = map[kind];
  return (
    <div style={{ display: 'flex', gap: 12, padding: '13px 15px', borderRadius: 'var(--ck-radius-md)',
      border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)', marginBottom: 9 }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 7, width: 104 }}>
        <Dot kind={dot} /><span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 10,
          letterSpacing: '0.08em', textTransform: 'uppercase', color: `var(--ck-signal-${dot === 'neutral' ? 'cool' : dot})`,
          fontWeight: 700 }}>{label || def}</span>
      </div>
      <div style={{ flex: 1, fontSize: 13.5, lineHeight: 1.55, color: 'var(--ck-fg-2)' }}>{children}</div>
    </div>
  );
}

function Callout({ icon = 'spark', kind = 'violet', title, children }) {
  return (
    <div style={{ display: 'flex', gap: 13, padding: '15px 17px', borderRadius: 'var(--ck-radius-lg)',
      border: `1px solid var(--ck-signal-${kind})44`, background: `color-mix(in oklab, var(--ck-signal-${kind}) 7%, var(--ck-bg-panel))`,
      margin: '6px 0 18px' }}>
      <Icon name={icon} size={18} style={{ color: `var(--ck-signal-${kind})`, marginTop: 1, flex: 'none' }} />
      <div>
        {title && <div style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--ck-fg-1)', marginBottom: 4 }}>{title}</div>}
        <div style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--ck-fg-2)' }}>{children}</div>
      </div>
    </div>
  );
}

// mini diagramme de flux (boîtes + flèches, formes simples)
function FlowStep({ icon, label }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7, flex: 1, minWidth: 78 }}>
      <div style={{ width: 42, height: 42, borderRadius: 'var(--ck-radius-md)', display: 'grid', placeItems: 'center',
        border: '1px solid var(--ck-stroke-3)', background: 'var(--ck-bg-inset)', color: 'var(--ck-signal-cool)' }}>
        <Icon name={icon} size={18} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--ck-fg-2)', textAlign: 'center', lineHeight: 1.3 }}>{label}</span>
    </div>
  );
}
function FlowArrow() {
  return <Icon name="arrow" size={15} style={{ color: 'var(--ck-fg-5)', flex: 'none', marginTop: 13 }} />;
}

// composant du DS (carte)
function DSItem({ name, role, states }) {
  return (
    <div style={{ padding: '13px 15px', borderRadius: 'var(--ck-radius-md)', border: '1px solid var(--ck-stroke-2)',
      background: 'var(--ck-bg-panel)' }}>
      <div style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 12, color: 'var(--ck-fg-1)', fontWeight: 600 }}>{name}</div>
      <div style={{ fontSize: 12.5, lineHeight: 1.45, color: 'var(--ck-fg-3)', margin: '5px 0 8px' }}>{role}</div>
      {states && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        {states.map((s, i) => <span key={i} style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 9.5,
          padding: '2px 7px', borderRadius: 999, border: '1px solid var(--ck-stroke-2)', color: 'var(--ck-fg-4)' }}>{s}</span>)}
      </div>}
    </div>
  );
}

function CompareTable() {
  const rows = [
    ['Surface de saisie', 'Omni-composer + focus tray (notion de « tour »)', 'Le Fil unique : voix & écrit = événements horodatés, sans tour'],
    ['Pointage déictique', 'Toast + Annuler (éphémère)', 'Ancre persistante & corrigeable in-situ ; fantôme auto-confirmé (hybride)'],
    ['Multi-pièces', 'Chips empilés à piloter', 'La Scène : pellicule + une seule « en scène »'],
    ['Fin de séance', 'Triage = formulaire à cocher', 'Récapitulatif pré-déduit de l\'usage (on confirme, on n\'auteur pas)'],
    ['Direction visuelle', 'Cockpit dense uniforme', 'Bi-température : Studio (capture calme) ⇄ Cockpit (triage/rapport)'],
  ];
  return (
    <div style={{ border: '1px solid var(--ck-stroke-2)', borderRadius: 'var(--ck-radius-lg)', overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '150px 1fr 1fr', background: 'var(--ck-bg-panel-hi)',
        borderBottom: '1px solid var(--ck-stroke-2)' }}>
        {['Critère', 'Concept actuel', 'Ma proposition'].map((h, i) => (
          <div key={i} style={{ padding: '11px 14px', fontFamily: 'var(--ck-font-mono)', fontSize: 10,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: i === 2 ? 'var(--ck-signal-cool)' : 'var(--ck-fg-4)', fontWeight: 700,
            borderLeft: i ? '1px solid var(--ck-stroke-2)' : 'none' }}>{h}</div>
        ))}
      </div>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '150px 1fr 1fr',
          borderBottom: i < rows.length - 1 ? '1px solid var(--ck-stroke-2)' : 'none',
          background: i % 2 ? 'var(--ck-bg-base)' : 'transparent' }}>
          <div style={{ padding: '12px 14px', fontSize: 12.5, fontWeight: 600, color: 'var(--ck-fg-1)' }}>{r[0]}</div>
          <div style={{ padding: '12px 14px', fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-3)',
            borderLeft: '1px solid var(--ck-stroke-2)' }}>{r[1]}</div>
          <div style={{ padding: '12px 14px', fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-1)',
            borderLeft: '1px solid var(--ck-stroke-2)', background: 'color-mix(in oklab, var(--ck-signal-cool) 5%, transparent)' }}>{r[2]}</div>
        </div>
      ))}
    </div>
  );
}

function DocMode({ onGoto }) {
  const TOC = [
    [1, 'Résumé exécutif'], [2, 'Analyse critique'], [3, 'Architecture & flux'],
    [4, 'Maquettes'], [5, 'Design system'], [6, 'Raisonnement (trade-offs)'],
    [7, 'Comparatif'], [8, 'Questions ouvertes'],
  ];
  return (
    <div className="ck-scroll" style={{ position: 'absolute', inset: 0, overflowY: 'auto',
      background: 'var(--ck-bg-base)' }}>
      <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 28px', display: 'grid',
        gridTemplateColumns: '186px 1fr', gap: 40, alignItems: 'start' }}>
        {/* TOC */}
        <nav style={{ position: 'sticky', top: 0, paddingTop: 46, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Kicker>Sommaire</Kicker>
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 1 }}>
            {TOC.map(([n, t]) => (
              <a key={n} href={'#sec-' + n} style={{ display: 'flex', gap: 9, padding: '6px 8px',
                borderRadius: 'var(--ck-radius-sm)', textDecoration: 'none', color: 'var(--ck-fg-3)', fontSize: 12.5 }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--ck-tint-faint)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                <span style={{ fontFamily: 'var(--ck-font-mono)', fontSize: 11, color: 'var(--ck-fg-5)' }}>{String(n).padStart(2, '0')}</span>
                {t}
              </a>
            ))}
          </div>
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--ck-stroke-2)' }}>
            <Btn size="sm" variant="primary" icon="play" onClick={() => onGoto('capture')}>Lancer le prototype</Btn>
          </div>
        </nav>

        {/* corps */}
        <div style={{ paddingTop: 46, paddingBottom: 80, maxWidth: 720 }}>
          <Kicker>Contre-proposition UX/UI · capture de connaissance multimodale</Kicker>
          <h1 style={{ margin: '14px 0 10px', fontSize: 34, fontWeight: 720, color: 'var(--ck-fg-1)',
            letterSpacing: '-0.02em', lineHeight: 1.1 }}>
            Le Fil — capter comme une timeline, pas comme un formulaire
          </h1>
          <p style={{ margin: '0 0 8px', fontSize: 15, lineHeight: 1.6, color: 'var(--ck-fg-3)' }}>
            Un regard neuf sur l'écran de captation écrit + parlé avec pièces jointes.
          </p>

          <DocSection n={1} title="Résumé exécutif">
            <Callout icon="spark" kind="cool" title="La thèse, en 5 lignes">
              La capture n'est pas une <i>saisie</i> mais une <B>timeline d'événements</B>. Voix, écrit, pièce montrée et
              référence déictique sont quatre types d'événements sur <B>un seul Fil horodaté</B>. Je remplace l'« omni-composer +
              focus tray » par ce Fil unique où l'écrit s'insère en ligne ; le toast déictique par une <B>ancre persistante,
              corrigeable in-situ</B> (mode hybride « fantôme auto-confirmé ») ; et l'étape de triage par un <B>récapitulatif
              pré-déduit de l'usage</B>. Côté visuel, un système <B>bi-température</B> : <i>Studio</i> (capture calme, peu de chrome)
              ⇄ <i>Cockpit</i> (triage, rapport, indexation — dense et instrumenté).
            </Callout>
            <P>
              Votre intuition de fond est juste : modalité unique, feedback non bloquant, indexation paresseuse. Je conserve ces
              trois piliers. Je diverge sur la <B>matérialisation</B> : un champ d'action ne suffit pas à porter un discours continu,
              un toast ne suffit pas à garantir une référence fiable, et un formulaire de triage trahit l'objectif de charge minimale.
            </P>
          </DocSection>

          <DocSection n={2} title="Analyse critique de votre concept">
            <P style={{ marginBottom: 16 }}>Ce qui tient, ce qui faiblit, ce qui risque, ce qui est superflu :</P>
            <Verdict kind="keep">La <B>modalité unique</B> (parler ⊕ écrire) est la bonne intuition — je la pousse plus loin encore.</Verdict>
            <Verdict kind="keep">Le <B>feedback non bloquant & réversible</B> est un principe sain : je le garde comme loi.</Verdict>
            <Verdict kind="keep">Le <B>lazy indexing</B> (gros œuvre repoussé à la fin) est excellent : conservé tel quel.</Verdict>
            <Verdict kind="weak">« Omni-composer + focus tray » mélange deux <B>gestes mentaux</B> (parler vs écrire) dans un même champ,
              et ajoute des <B>chips à piloter</B> pendant qu'on parle — exactement la charge qu'on veut éviter.</Verdict>
            <Verdict kind="weak">La notion de « pièces qui s'appliquent <B>au prochain tour</B> » est étrangère à un flux de parole
              continu : il n'y a pas de tours quand on parle, juste un fil qui avance.</Verdict>
            <Verdict kind="risk">La <B>confirmation déictique par toast</B> est éphémère, <B>spammable</B> si plusieurs références
              s'enchaînent, et ne laisse <B>aucune trace navigable</B> pour corriger après coup.</Verdict>
            <Verdict kind="cut">Le <B>triage-formulaire</B> en fin de séance : la décision peut être déduite de l'usage,
              donc l'étape devient une simple confirmation.</Verdict>
          </DocSection>

          <DocSection n={3} title="Architecture d'information & flux">
            <P><B>Une seule source de vérité : Le Fil.</B> Tout ce qui se passe en séance y est un événement horodaté.
              Quatre types seulement :</P>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, margin: '4px 0 20px' }}>
              <DSItem name="◇ parole" role="Transcription temps réel — provisoire (dim) puis finalisée." />
              <DSItem name="✎ écrit" role="Note insérée en ligne, au même rang que la parole." />
              <DSItem name="⬓ pièce" role="Vue épinglée / montrée (entre en Scène)." />
              <DSItem name="⊹ référence" role="Ancre déictique liant un instant à une vue." />
            </div>

            <P><B>Parcours nominal</B> — du calme de bout en bout :</P>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '18px 16px', margin: '6px 0 18px',
              borderRadius: 'var(--ck-radius-lg)', border: '1px solid var(--ck-stroke-2)', background: 'var(--ck-bg-panel)', flexWrap: 'wrap' }}>
              <FlowStep icon="mic" label="Parler & écrire" /><FlowArrow />
              <FlowStep icon="layers" label="Montrer une pièce" /><FlowArrow />
              <FlowStep icon="target" label="Pointer (auto-confirmé)" /><FlowArrow />
              <FlowStep icon="arrow" label="Terminer" /><FlowArrow />
              <FlowStep icon="check" label="Confirmer le partage" /><FlowArrow />
              <FlowStep icon="book" label="Lire le rapport" />
            </div>

            <P><B>États du pointage</B> : <code style={cd}>fantôme</code> → <code style={cd}>confirmé</code>, ou
              <code style={cd}>incertain</code> (faible confiance) / <code style={cd}>annulé</code> (réversible).</P>
            <P><B>Cas limites traités</B> : erreur de pointage (re-liaison), déictique ambigu (incertain explicite),
              perte réseau (buffer local + reprise), reprise de séance (Fil persistant).</P>
            <Goto onGoto={onGoto} to="edge">Voir les cas limites dans le prototype</Goto>
          </DocSection>

          <DocSection n={4} title="Maquettes (prototype cliquable)">
            <P>Cinq écrans clés, en haute fidélité et animés. Les données « bougent » : transcription qui se déroule,
              oracle qui dépose des questions, ancres qui se confirment.</P>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 10 }}>
              {[['capture', 'mic', 'Capture en direct', 'Le Fil + composer + oracle + Scène'],
                ['pieces', 'layers', 'Pièces & pointage', 'Scène multi-pièces + 2 approches'],
                ['fin', 'check', 'Fin de séance', 'Triage pré-rempli'],
                ['index', 'spark', 'Indexation', 'Moteur d\'arrière-plan'],
                ['report', 'book', 'Rapport', 'Sources cliquables + provenance'],
                ['edge', 'target', 'Cas limites', 'États de robustesse']].map(([id, ic, t, d]) => (
                <button key={id} onClick={() => onGoto(id)} style={{ appearance: 'none', cursor: 'pointer', textAlign: 'left',
                  padding: '14px 15px', borderRadius: 'var(--ck-radius-md)', border: '1px solid var(--ck-stroke-2)',
                  background: 'var(--ck-bg-panel)', display: 'flex', flexDirection: 'column', gap: 7 }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--ck-stroke-hot)'; e.currentTarget.style.background = 'var(--ck-bg-panel-hi)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--ck-stroke-2)'; e.currentTarget.style.background = 'var(--ck-bg-panel)'; }}>
                  <Icon name={ic} size={18} style={{ color: 'var(--ck-signal-cool)' }} />
                  <span style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--ck-fg-1)' }}>{t}</span>
                  <span style={{ fontSize: 12, color: 'var(--ck-fg-4)', lineHeight: 1.4 }}>{d}</span>
                </button>
              ))}
            </div>
          </DocSection>

          <DocSection n={5} title="Le design system proposé">
            <P><B>Évolution visuelle : un système bi-température.</B> Le cockpit dense est idéal pour <i>surveiller</i> et
              <i>trier</i> — mais la capture vive demande <B>moins</B>, pas plus. D'où deux régimes sur les mêmes tokens Agentium :</P>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, margin: '4px 0 18px' }}>
              <div style={{ padding: 15, borderRadius: 'var(--ck-radius-lg)', border: '1px solid var(--ck-signal-cool)44',
                background: 'color-mix(in oklab, var(--ck-signal-cool) 6%, var(--ck-bg-panel))' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 7 }}>
                  <Icon name="mic" size={15} style={{ color: 'var(--ck-signal-cool)' }} />
                  <span style={{ fontSize: 13.5, fontWeight: 680, color: 'var(--ck-fg-1)' }}>Studio</span>
                </div>
                <span style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--ck-fg-3)' }}>
                  Capture. Chrome minimal, typo de transcription large, panneaux périphériques atténués qui s'éclairent au focus.
                  L'attention va au discours.
                </span>
              </div>
              <div style={{ padding: 15, borderRadius: 'var(--ck-radius-lg)', border: '1px solid var(--ck-stroke-3)',
                background: 'var(--ck-bg-panel)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 7 }}>
                  <Icon name="grid" size={15} style={{ color: 'var(--ck-fg-2)' }} />
                  <span style={{ fontSize: 13.5, fontWeight: 680, color: 'var(--ck-fg-1)' }}>Cockpit</span>
                </div>
                <span style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--ck-fg-3)' }}>
                  Triage, indexation, rapport. Dense, instrumenté, tabular-nums, grille ambiante. On lit, on inspecte, on décide.
                </span>
              </div>
            </div>

            <P><B>Composants clés</B> et leurs états :</P>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, marginBottom: 16 }}>
              <DSItem name="Le Fil" role="Flux d'événements horodatés, auto-scroll." states={['provisoire', 'finalisé', 'note', 'ancre']} />
              <DSItem name="AnchorChip" role="Référence déictique inline." states={['fantôme', 'confirmé', 'incertain', 'annulé']} />
              <DSItem name="La Scène" role="Pièces épinglées en pellicule." states={['en scène', 'en pellicule', 'à pointer']} />
              <DSItem name="Oracle lane" role="Pistes déposées, jamais modales." states={['ouverte', 'gardée', 'ignorée']} />
              <DSItem name="Composer" role="Saisie écrite + pouls micro." states={['vide', 'frappe', 'micro actif']} />
              <DSItem name="Triage recap" role="Partage pré-déduit, confirmable." states={['entier', 'extrait', 'aucun']} />
              <DSItem name="Provenance" role="Vue pointée + zone + retour au Fil." states={['indexé', 'référencé']} />
              <DSItem name="Index pulse" role="Pouls discret d'arrière-plan." states={['file', 'indexation', 'indexé']} />
            </div>
            <P><B>Micro-interactions</B> : respiration de l'ancre fantôme (2 s), barres micro réactives, compte à rebours
              d'auto-confirmation, surlignage de l'affirmation à la sélection d'une source.
              <B> Iconographie</B> : ⊹/cible = pointage, ✎ = écrit, micro = voix, étincelle = oracle, calques = scène/index.</P>
            <Goto onGoto={onGoto} to="pieces">Voir les composants en action</Goto>
          </DocSection>

          <DocSection n={6} title="Raisonnement : pour chaque écart, le pourquoi">
            <Trade ecart="Fil unique au lieu d'omni-composer + tray"
              why="Un discours est un flux continu, pas une suite de tours. Le Fil supprime la notion de tour et le pilotage de chips."
              tradeoff="On perd l'idée d'« appliquer au prochain tour » — compensé par la Scène qui rend l'état des pièces toujours visible." />
            <Trade ecart="Ancre persistante (vs toast)"
              why="Une référence doit survivre, être relue et corrigée. Une ancre inline est navigable ; un toast disparaît."
              tradeoff="Léger surcroît de densité dans le Fil — assumé : c'est de la valeur, pas du bruit." />
            <Trade ecart="Fantôme auto-confirmé (mode hybride par défaut)"
              why="Concilie l'effort nul de l'auto-détection et la fiabilité du geste : on ne confirme que si on veut corriger."
              tradeoff="Délai de 4 s avant validation ferme — réglable ; l'expert pressé peut passer en 100 % auto." />
            <Trade ecart="Récapitulatif pré-déduit (vs triage-formulaire)"
              why="Le niveau de partage se lit dans l'usage : pointé → entier, épinglé seul → extrait, jamais touché → exclu."
              tradeoff="Le pré-réglage peut se tromper — mais corriger 1 ligne est plus rapide que remplir un formulaire vierge." />
            <Trade ecart="Bi-température Studio/Cockpit"
              why="La capture a besoin de calme ; le triage et le rapport de densité. Un seul régime sert mal les deux."
              tradeoff="Deux régimes à maintenir — mais ils partagent 100 % des tokens, donc coût faible." />
          </DocSection>

          <DocSection n={7} title="Notre concept vs ma proposition">
            <CompareTable />
          </DocSection>

          <DocSection n={8} title="Questions ouvertes">
            <ol style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {['Détection déictique : à quel point le moteur ASR sait-il borner « cette / ici / comme on voit » à un instant fiable ? Le délai de 4 s du fantôme dépend de cette latence.',
                'Multi-pièces simultanées : une seule vue « en scène » suffit-elle, ou faut-il pouvoir pointer une 2ᵉ vue sans la mettre au premier plan ?',
                'Notes écrites : doivent-elles entrer dans l\'index/recherche au même titre que la parole, ou rester des annotations privées ?',
                'Triage déduit : quel signal d\'usage prime si l\'expert pointe une pièce puis dit « ne pas partager celle-ci » à voix haute ?',
                'Reprise de séance : quelle fenêtre de validité du buffer local hors-ligne avant d\'exiger une re-synchro explicite ?'].map((q, i) => (
                <li key={i} style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--ck-fg-2)' }}>{q}</li>
              ))}
            </ol>
          </DocSection>

          <div style={{ paddingTop: 10, borderTop: '1px solid var(--ck-stroke-2)', display: 'flex', gap: 12, alignItems: 'center' }}>
            <Btn variant="primary" icon="play" onClick={() => onGoto('capture')}>Ouvrir le prototype</Btn>
            <span style={{ fontSize: 12.5, color: 'var(--ck-fg-4)' }}>Réglez le mode de pointage, l'oracle et la densité dans les Tweaks.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

const cd = { fontFamily: 'var(--ck-font-mono)', fontSize: 12, padding: '1px 6px', borderRadius: 4,
  background: 'var(--ck-bg-inset)', border: '1px solid var(--ck-stroke-2)', color: 'var(--ck-fg-2)' };

function Trade({ ecart, why, tradeoff }) {
  return (
    <div style={{ padding: '14px 16px', borderRadius: 'var(--ck-radius-md)', border: '1px solid var(--ck-stroke-2)',
      background: 'var(--ck-bg-panel)', marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Icon name="flow" size={15} style={{ color: 'var(--ck-signal-cool)' }} />
        <span style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--ck-fg-1)' }}>{ecart}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div><Label style={{ color: 'var(--ck-signal-pos)' }}>Pourquoi</Label>
          <p style={{ margin: '5px 0 0', fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-2)' }}>{why}</p></div>
        <div><Label style={{ color: 'var(--ck-signal-warn)' }}>Trade-off</Label>
          <p style={{ margin: '5px 0 0', fontSize: 12.5, lineHeight: 1.5, color: 'var(--ck-fg-3)' }}>{tradeoff}</p></div>
      </div>
    </div>
  );
}

Object.assign(window, { DocMode });
