// data.jsx — contenu statique du prototype (documents, session, rapport, triage)
// Domaine simulé : expertise géotechnique d'un chantier ("Résidence Belvédère — Lot 7").
// Tout le copy est en français. Exporté sur window pour les autres scripts Babel.

// ── Documents épinglables ─────────────────────────────────────────────────
// `tint` pilote la teinte du placeholder rayé (aucune image réelle).
const DOCS = {
  rapport: {
    id: 'rapport',
    name: 'Rapport_geotech_Lot7.pdf',
    kind: 'pdf',
    pages: 24,
    tint: 'cool',
  },
  sondages: {
    id: 'sondages',
    name: 'Sondages_carottage.pdf',
    kind: 'pdf',
    pages: 11,
    tint: 'violet',
  },
  plan: {
    id: 'plan',
    name: 'Plan_implantation_v3.pdf',
    kind: 'pdf',
    pages: 3,
    tint: 'warn',
  },
  photos: {
    id: 'photos',
    name: 'Photos_site_03-2026.zip',
    kind: 'image',
    pages: 18,
    tint: 'pos',
  },
};

// Vues précises (page / slide / zone) référencées pendant la séance.
const VIEWS = {
  v_coupe: { id: 'v_coupe', docId: 'rapport', page: 12, label: 'Coupe stratigraphique', sub: 'SP-1 → SP-4', shape: 'page' },
  v_essais: { id: 'v_essais', docId: 'rapport', page: 8, label: 'Tableau essais pressio.', sub: 'EM / pl*', shape: 'page' },
  v_fissure: { id: 'v_fissure', docId: 'photos', page: 7, label: 'Fissure pignon Est', sub: 'Cliché 07', shape: 'image' },
  v_sp3: { id: 'v_sp3', docId: 'sondages', page: 3, label: 'Carottage SP-3', sub: '0–6 m', shape: 'page' },
  v_implant: { id: 'v_implant', docId: 'plan', page: 1, label: 'Implantation bâti', sub: 'Plan masse', shape: 'page' },
};

// ── Script de la séance de capture (le Fil qui se déroule) ────────────────
// gap = ms écoulés depuis l'événement précédent (avant mise à l'échelle vitesse).
// type: phase | speak | oracle | pin | show | deictic | gesture | note
function buildScript() {
  return [
    { type: 'phase', label: 'Contexte', gap: 0 },
    { type: 'speak', gap: 200, pauseAfter: 600,
      text: "Bon, on est sur le lot 7 de la résidence Belvédère, terrain en pente côté Est." },
    { type: 'speak', gap: 300, pauseAfter: 500,
      text: "Le sol c'est de l'argile limoneuse sur les six premiers mètres, puis on tombe sur un substratum marno-calcaire." },
    { type: 'oracle', gap: 400, tag: 'profondeur',
      q: "À quelle profondeur exacte est rencontré le substratum sur SP-3 ?" },
    { type: 'pin', gap: 900, viewId: 'v_coupe' },
    { type: 'speak', gap: 700, pauseAfter: 300,
      text: "Si on regarde cette coupe, on voit bien le pendage des couches vers le talweg." },
    { type: 'deictic', gap: -2600, viewId: 'v_coupe', confidence: 0.94,
      phrase: 'cette coupe', anchorAfter: true },
    { type: 'note', gap: 1400,
      text: "Pendage ~8° NE — surveiller stabilité talus pendant terrassement." },
    { type: 'phase', label: 'Sondages', gap: 600 },
    { type: 'pin', gap: 300, viewId: 'v_sp3' },
    { type: 'speak', gap: 700, pauseAfter: 400,
      text: "Là sur le carottage de SP-3, le toit du marno-calcaire est à 5,80 mètres." },
    { type: 'deictic', gap: -2400, viewId: 'v_sp3', confidence: 0.88,
      phrase: 'le carottage de SP-3', anchorAfter: true },
    { type: 'oracle', gap: 500, tag: 'fondations',
      q: "Recommande-t-on des fondations profondes ou un radier compte tenu de pl* ?" },
    { type: 'pin', gap: 900, viewId: 'v_essais' },
    { type: 'speak', gap: 700, pauseAfter: 400,
      text: "Les pressiomètres donnent une pression limite faible en surface, comme on le voit ici." },
    // déictique AMBIGU : deux vues à l'écran (essais + sp3) → faible confiance
    { type: 'deictic', gap: -2200, viewId: 'v_essais', confidence: 0.41,
      phrase: 'comme on le voit ici', anchorAfter: true, ambiguousWith: 'v_sp3' },
    { type: 'phase', label: 'Désordres', gap: 700 },
    { type: 'pin', gap: 300, viewId: 'v_fissure' },
    { type: 'speak', gap: 700, pauseAfter: 400,
      text: "Et cette fissure sur le pignon Est, c'est typiquement un tassement différentiel." },
    { type: 'deictic', gap: -2300, viewId: 'v_fissure', confidence: 0.91,
      phrase: 'cette fissure', anchorAfter: true },
    { type: 'note', gap: 1300,
      text: "Lier au point bas de la coupe (p.12) — même zone que SP-3." },
    { type: 'oracle', gap: 500, tag: 'risque',
      q: "Le tassement observé est-il compatible avec un radier rigide ?" },
    { type: 'speak', gap: 900, pauseAfter: 600,
      text: "Donc ma reco c'est plutôt un système de pieux courts ancrés dans le substratum." },
    { type: 'phase', label: 'Synthèse', gap: 400 },
  ];
}

// ── Données figées de fin de séance (triage + indexation) ─────────────────
// Niveau de partage PRÉ-DÉDUIT de l'usage (le triage ne fait que confirmer).
const TRIAGE = [
  { docId: 'rapport', pointed: 3, pinned: true, proposal: 'full',
    reason: 'Pointé 3× (coupe, essais, tassement)', index: 'queued' },
  { docId: 'sondages', pointed: 1, pinned: true, proposal: 'full',
    reason: 'Pointé 1× (carottage SP-3)', index: 'queued' },
  { docId: 'photos', pointed: 1, pinned: true, proposal: 'excerpt',
    reason: 'Pointé 1× — cliché isolé', index: 'referenced' },
  { docId: 'plan', pointed: 0, pinned: true, proposal: 'none',
    reason: 'Épinglé, jamais pointé', index: 'none' },
];

// États d'indexation possibles (ordre = progression).
const INDEX_STATES = {
  none: { label: 'Non indexé', dot: 'neutral', fg: 'var(--ck-fg-4)' },
  referenced: { label: 'Référencé', dot: 'cool', fg: 'var(--ck-signal-cool)' },
  queued: { label: 'En file', dot: 'warn', fg: 'var(--ck-signal-warn)' },
  indexing: { label: 'Indexation…', dot: 'violet', fg: 'var(--ck-signal-violet)' },
  indexed: { label: 'Indexé', dot: 'pos', fg: 'var(--ck-signal-pos)' },
};

// ── Rapport publié (lecture + sources cliquables) ─────────────────────────
// Chaque `src` pointe une VIEW + un instant du transcript (provenance bidir.).
const REPORT = {
  title: 'Étude géotechnique — Résidence Belvédère, Lot 7',
  ref: 'GEO-2026-0712 · v1 · publié 25 juin 2026',
  sections: [
    {
      h: 'Contexte & morphologie',
      body: [
        { t: "Le terrain présente une pente marquée vers l'Est, avec un pendage des couches d'environ 8° en direction du talweg." , src: 'v_coupe' },
        { t: "La stratigraphie se compose d'une argile limoneuse sur les six premiers mètres surmontant un substratum marno-calcaire." , src: 'v_coupe' },
      ],
    },
    {
      h: 'Reconnaissance & essais',
      body: [
        { t: "Le toit du substratum marno-calcaire est rencontré à 5,80 m de profondeur au droit du sondage SP-3.", src: 'v_sp3' },
        { t: "Les essais pressiométriques indiquent une pression limite faible dans les horizons superficiels.", src: 'v_essais' },
      ],
    },
    {
      h: 'Désordres observés',
      body: [
        { t: "Une fissuration du pignon Est traduit un tassement différentiel, localisé sur la même zone que le point bas de la coupe.", src: 'v_fissure' },
      ],
    },
    {
      h: 'Recommandation',
      body: [
        { t: "Un système de fondations profondes par pieux courts ancrés dans le substratum est préconisé, de préférence à un radier rigide.", src: null },
      ],
    },
  ],
};

Object.assign(window, { DOCS, VIEWS, buildScript, TRIAGE, INDEX_STATES, REPORT });
