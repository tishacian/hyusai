/**
 * Conversational surfaces: chat panel, chat overlay, drafts.
 *
 * See `./CONVENTION.md` for key naming, domain ownership and the
 * guard that keeps FR/EN in parity (`npm run check:i18n`).
 */

export const CHAT_FR = {
  // --- Chat overlay / workspace -----------------------------------
  'chat.title': 'Chat',
  'chat.placeholder': 'Posez votre question…',
  'chat.send': 'Envoyer',
  'chat.quick_ask': 'Question rapide',
  'chat.with_system': 'Avec un système',
  'chat.drop_files': 'Déposez des fichiers pour démarrer une session',
  'chat.drop_files.hint': 'Les documents sont utilisés pour cette session uniquement.',
  'chat.persist': 'Conserver le contexte',
  'chat.persist.hint': 'Transformer cette session en contexte permanent du workspace.',
  'chat.uploading': 'Envoi des fichiers…',
  'chat.empty': 'Démarrez une conversation pour voir les réponses ici.',
  'chat.overlay.hint': 'Panneau rapide',
  'chat.overlay.expand': 'Plein écran',
  'chat.overlay.expand.hint': 'Ouvrir ce chat en vue plein écran',
  // --- Recommendation draft drawer ---------------------------------
  'chat.draft.badge': 'Brouillon de recommandation',
  'chat.draft.doc_preview': 'Aperçu document',
  'chat.draft.cited': 'Extraits cités par AYA',
  'chat.draft.cited_eyebrow': 'Aperçu document · extraits cités par AYA',
  'chat.draft.page': 'Page {page}',
  'chat.draft.pdf_hint': 'PDF complet disponible via « Télécharger ».',
  'chat.draft.preview_loading': "Chargement de l'aperçu PDF…",
  'chat.draft.preview_unavailable':
    'Aperçu indisponible — utilisez le bouton « Télécharger » pour ouvrir le document.',
  'chat.draft.pdf_unavailable':
    'Document PDF indisponible — utilisez le bouton « Télécharger » ou consultez les passages cités.',
  'chat.draft.subject': 'Objet',
  'chat.draft.sources': 'Sources',
  'chat.draft.download': 'Télécharger',
  'chat.draft.validate': 'Valider la recommandation',
  'chat.draft.validate.saved': 'Recommandation enregistrée',
  'chat.draft.validate.failed':
    'La validation de la recommandation est indisponible pour le moment.',
  // --- Session history ---------------------------------------------
  'chat.history.archive': 'Archiver',
  'chat.history.title': 'Conversations',
  'chat.history.count': '{count} actives',
  'chat.history.new': 'Nouveau chat',
  'chat.history.search': 'Rechercher',
  'chat.history.loading': 'Chargement',
  'chat.history.empty': 'Aucune conversation',
  'chat.context.workspace': 'Contexte du workspace',
  'chat.context.workspace_sources': 'Questions sur les sources du workspace',
  'chat.context.workspace_sources_pill': 'Sources du workspace',
  'chat.context.sources_scope': 'Sources : {label}',
  'chat.context.workspace_search_hint': 'Questions et recherche sur les connaissances du workspace.',
  // --- Executive briefing bar --------------------------------------
  'chat.exec.kicker': 'Briefing souverain',
  'chat.exec.scope': 'Sources qualifiées · presse, projets, agenda, carte et observations',
  'chat.voice.stop': 'Arrêter',
  'chat.voice.stop.hint': 'Arrêter la voix : couper la lecture et la boucle d’écoute.',
  'chat.deep_search.done_for': 'Deep Search terminé pour « {query} ».',
  'chat.deep_search.running_for': 'Deep Search en cours pour « {query} ».',
  'chat.deep_search.started_notice': 'Recherche approfondie lancée pour affiner cette réponse.',
  'chat.voice.unavailable': 'Voix indisponible',
  'chat.voice.resume_aya': 'Reprendre AYA',
  'chat.voice.aya_listening': 'AYA écoute',
  'chat.voice.talk_to_aya': 'Parler à AYA',
  'chat.voice.resume_aya_title': 'Relancer la boucle vocale AYA.',
  'chat.voice.aya_active_title': 'La session vocale AYA est active. Les commandes stop, pause et annule restent disponibles.',
  'chat.voice.talk_to_aya_title': 'Démarrer une conversation vocale continue avec AYA.',
  'chat.voice.loop_paused_title': 'Boucle de conversation en pause. Appuyez sur Reprendre pour réouvrir le micro.',
  'chat.voice.stop_no_rearm_title': 'Arrêter la voix : couper la lecture et la boucle d’écoute (sans relance).',
  'chat.voice.cut_playback_title': 'Couper la lecture vocale en cours.',
  'chat.voice.playback_cut': 'Lecture coupée',
  'chat.voice.rephrase_prompt': 'Reformule ta dernière réponse de façon plus courte et opérationnelle.',
  'chat.suggestion.question_ready': 'Question prête. Complétez si besoin, puis envoyez.',
  'chat.qa.review_tooltip': 'Le contrôle qualité automatique recommande de vérifier cette réponse avant de l’utiliser. Cliquez pour consulter le détail.',
  'chat.correction.title': 'Correction',
  'chat.correction.dictation': 'Dictée',
  'chat.correction.thanks': 'Merci',
  'chat.correction.mic_unsupported': 'Le micro n’est pas disponible dans ce navigateur. Saisissez la correction.',
  'chat.correction.mic_denied': 'Accès au micro refusé. Vous pouvez saisir la correction manuellement.',
  'chat.correction.no_sound': 'Aucun son capté. Réessayez ou saisissez la correction.',
  'chat.correction.empty_transcript': 'Transcription vide. Vous pouvez saisir la correction.',
  'chat.correction.local_transcript': 'Transcription serveur indisponible — texte capté localement, relisez-le.',
  'chat.correction.transcript_failed': 'Transcription indisponible. Saisissez la correction manuellement.',
  'chat.correction.text_required': 'Saisissez ou dictez une correction avant d’envoyer.',
  'chat.correction.published': 'Connaissance experte publiée — prioritaire.',
  'chat.correction.sent_tap': 'Correction envoyée en revue — toucher pour ouvrir la file de revue.',
  'chat.correction.sent': 'Correction envoyée en revue.',
  'chat.correction.disabled': 'La correction experte n’est pas activée pour ce workspace.',
  'chat.trace.toggle': 'Traçabilité',
  'chat.trace.hide': 'Masquer les paramètres avancés',
  'chat.trace.show': 'Afficher traçabilité et paramètres avancés',
  'chat.map.ready': 'Carte stratégique prête',
  // --- Deep Search --------------------------------------------------
  'chat.deep.answer': 'Réponse Deep Search',
  'chat.deep.tracking': 'suivi persistant',
  'chat.deep.server_note':
    'Deep Search continue côté serveur ; ce suivi se met à jour depuis {url}.',
  'chat.deep.resume_note':
    'Deep Search continue côté serveur ; le suivi restera disponible après la réponse.',
  // --- Expert correction --------------------------------------------
  'chat.correct.action': 'Corriger',
  'chat.correct.hint': 'Corriger ou compléter cette réponse (relecture experte requise)',
  'chat.correct.title': 'Correction experte',
  'chat.correct.placeholder':
    'Corrigez ou complétez la réponse. Vous pouvez aussi dicter au micro.',
  'chat.correct.question': 'Question :',
  'chat.correct.mic.stop': 'Arrêter et transcrire',
  'chat.correct.mic.transcribing': 'Transcription en cours…',
  'chat.correct.mic.start': 'Dicter la correction',
  'chat.correct.live': 'En direct',
  'chat.correct.state.recording': '● Enregistrement… touchez le carré pour arrêter',
  'chat.correct.state.ready': 'Transcription prête — relisez et ajustez avant d’envoyer.',
  'chat.correct.state.idle': 'Saisie ou dictée — relecture experte requise avant publication.',
  'chat.correct.sending': 'Envoi…',
  'chat.correct.submit': 'Envoyer en revue',
  'chat.correct.trace.published': 'Connaissance experte publiée — prioritaire',
  'chat.correct.trace.sent': 'Correction envoyée en revue',
  'chat.correct.trace.voice': 'Dictée vocale',
  'chat.correct.trace.published_note': 'Publiée et priorisée devant les documents ingérés.',
  'chat.correct.trace.pending_note': 'En attente de relecture experte avant publication.',
  'chat.correct.trace.queue': 'Voir la file de revue',
  'chat.qa.verify': 'Réponse à vérifier',
  // --- Ask surface: the chat empty state and its configurable defaults ---
  // Shared by chat-panel and the workspace chat/Knowledge settings preview,
  // which seeds the very same copy into the editable tenant configuration.
  'chat.ask.title': 'Posez votre question',
  'chat.ask.title_scoped': 'Interroger {name}',
  'chat.ask.subtitle':
    'Posez une question sur le contexte du workspace. La réponse cite les sources utilisées.',
  'chat.ask.subtitle_scoped': 'Posez une question sur le contexte {scope}.',
  'chat.ask.placeholder': 'Posez votre question…',
  'chat.ask.placeholder_scoped': 'Interroger {name} sur les sources du workspace…',
  'chat.ask.source_fallback': 'contexte du workspace',
  'chat.ask.title_default': 'Démarrez une conversation',
  'chat.ask.subtitle_context':
    'Posez une question sur le contexte {scope}. La réponse cite les sources utilisées.',
  'chat.ask.subtitle_executive':
    'Posez une question sur les signaux, projets, sources et décisions attendues.',
  'chat.ask.subtitle_session':
    'Posez une question sourcée, fondée uniquement sur les documents déposés pour cette session.',
  'chat.ask.subtitle_session_combine':
    'Posez une question sourcée sur les documents de session et {source}.',
  'chat.ask.subtitle_scope': 'Posez une question sourcée à partir de {source}.',
  'chat.ask.subtitle_default':
    'Posez une question au workspace. {brand} choisit la recherche et cite les sources utilisées.',
  'chat.ask.placeholder_session': 'Interroger les documents déposés pour cette session…',
  'chat.ask.placeholder_session_combine':
    'Interroger les documents de session et {source}…',
  'chat.ask.placeholder_scope': 'Poser une question sourcée à partir de {source}…',
  'chat.ask.placeholder_default': 'Posez une question au workspace…',
  // --- Live progress while an answer is being composed ---------------
  'chat.progress.composing': 'Rédaction de la réponse…',
  'chat.progress.passages_found': '{count} passages trouvés · analyse en cours…',
  'chat.progress.passages_found_one': '1 passage trouvé · analyse en cours…',
  'chat.progress.passages_analysed': 'Passages analysés…',
  'chat.progress.analysing': 'Analyse des passages…',
  'chat.progress.searching': 'Recherche dans les documents…',
  'chat.progress.preparing': 'Préparation de la requête…',
  // --- Generated prompt pack ----------------------------------------
  // `[votre sujet]` is a slot the reader replaces by hand, so it stays part
  // of the copy instead of becoming a `{param}`.
  'chat.prompt.ask.label': 'Poser une question',
  'chat.prompt.ask.prompt':
    'Que disent les documents {source} sur [votre sujet] ? Cite les sources utilisées.',
  'chat.prompt.ask.prompt_selected':
    'Que disent les documents sélectionnés sur [votre sujet] ? Cite les sources utilisées.',
  'chat.prompt.find.label': 'Retrouver un passage',
  'chat.prompt.find.prompt':
    'Retrouve dans {source} le passage, la procédure ou la section qui explique [votre sujet].',
  'chat.prompt.compare.label': 'Comparer',
  'chat.prompt.compare.prompt':
    'Compare les informations disponibles dans {source} sur [votre sujet].',
  'chat.prompt.summarize.label': 'Résumer',
  'chat.prompt.summarize.prompt':
    'Résume les points clés trouvés dans {source} sur [votre sujet], avec les sources utiles.',
  // Same four intents, worded for a scope that names no source.
  'chat.prompt.ask.prompt_plain':
    'Que disent les documents sur [votre sujet] ? Cite les sources utilisées.',
  'chat.prompt.ask.prompt_workspace':
    'Que disent les documents du workspace sur [votre sujet] ? Cite les sources utilisées.',
  'chat.prompt.find.prompt_plain':
    'Retrouve le passage, la procédure ou la section qui explique [votre sujet].',
  'chat.prompt.find.prompt_with_doc':
    'Retrouve le passage, la procédure ou la section qui explique [votre sujet], avec le document source.',
  'chat.prompt.compare.prompt_plain':
    'Compare les informations disponibles sur [votre sujet] et indique les sources utilisées.',
  'chat.prompt.compare.prompt_docs':
    'Compare les informations disponibles sur [votre sujet] dans les documents.',
  'chat.prompt.summarize.prompt_plain':
    'Résume les points clés sur [votre sujet] avec les sources utiles.',
  'chat.prompt.verify.label': 'Vérifier les sources',
  'chat.prompt.verify.prompt':
    'Réponds à la question avec les documents disponibles. Si aucun passage ne répond clairement, indique-le simplement.',
  'chat.prompt.sourced.label': 'Réponse sourcée',
  'chat.prompt.sourced.prompt':
    'Réponds à ma question uniquement avec les documents sélectionnés et cite les sources utiles.',
  // Session-scoped files dropped into the conversation.
  'chat.prompt.files_summarize.label': 'Résumer les fichiers',
  'chat.prompt.files_summarize.prompt':
    'Résume les fichiers ajoutés et cite les noms de fichiers utilisés.',
  'chat.prompt.files_summarize.prompt_combine':
    'Résume les fichiers ajoutés et complète avec {source} si utile, en citant les sources.',
  'chat.prompt.files_ask.label': 'Question aux fichiers',
  'chat.prompt.files_ask.prompt':
    'Réponds à ma question à partir des fichiers ajoutés, avec les sources utiles.',
  'chat.prompt.files_compare.prompt':
    'Compare les informations disponibles dans les fichiers ajoutés sur [votre sujet].',
  'chat.prompt.files_compare.prompt_combine':
    'Compare les fichiers ajoutés avec {source} sur [votre sujet].',
  'chat.prompt.files_note.label': 'Préparer une note',
  'chat.prompt.files_note.prompt':
    'Prépare une note courte à partir des fichiers ajoutés, avec les sources à vérifier.',
} as const satisfies Record<string, string>;

/**
 * The `Record<keyof typeof CHAT_FR, string>` annotation is the parity
 * contract: `tsc` fails on a key present in one locale and missing in the
 * other, before the guard even runs.
 */
export const CHAT_EN: Record<keyof typeof CHAT_FR, string> = {
  // --- Chat overlay / workspace -----------------------------------
  'chat.title': 'Chat',
  'chat.placeholder': 'Ask your question…',
  'chat.send': 'Send',
  'chat.quick_ask': 'Quick ask',
  'chat.with_system': 'With a system',
  'chat.drop_files': 'Drop files to start a session',
  'chat.drop_files.hint': 'Documents are used for this session only.',
  'chat.persist': 'Keep context',
  'chat.persist.hint': 'Promote this session into a permanent workspace context.',
  'chat.uploading': 'Uploading files…',
  'chat.empty': 'Start a conversation to see answers here.',
  'chat.overlay.hint': 'Quick panel',
  'chat.overlay.expand': 'Full screen',
  'chat.overlay.expand.hint': 'Open this chat as a full-page workspace view',
  // --- Recommendation draft drawer ---------------------------------
  'chat.draft.badge': 'Recommendation draft',
  'chat.draft.doc_preview': 'Document preview',
  'chat.draft.cited': 'Passages cited by AYA',
  'chat.draft.cited_eyebrow': 'Document preview · passages cited by AYA',
  'chat.draft.page': 'Page {page}',
  'chat.draft.pdf_hint': 'Full PDF available from “Download”.',
  'chat.draft.preview_loading': 'Loading the PDF preview…',
  'chat.draft.preview_unavailable':
    'Preview unavailable — use the “Download” button to open the document.',
  'chat.draft.pdf_unavailable':
    'PDF document unavailable — use the “Download” button or read the cited passages.',
  'chat.draft.subject': 'Subject',
  'chat.draft.sources': 'Sources',
  'chat.draft.download': 'Download',
  'chat.draft.validate': 'Approve the recommendation',
  'chat.draft.validate.saved': 'Recommendation saved',
  'chat.draft.validate.failed': 'Approving the recommendation is unavailable right now.',
  // --- Session history ---------------------------------------------
  'chat.history.archive': 'Archive',
  'chat.history.title': 'Conversations',
  'chat.history.count': '{count} active',
  'chat.history.new': 'New chat',
  'chat.history.search': 'Search',
  'chat.history.loading': 'Loading',
  'chat.history.empty': 'No conversation yet',
  'chat.context.workspace': 'Workspace context',
  'chat.context.workspace_sources': 'Questions about the workspace sources',
  'chat.context.workspace_sources_pill': 'Workspace sources',
  'chat.context.sources_scope': 'Sources: {label}',
  'chat.context.workspace_search_hint': 'Questions and search across the workspace knowledge.',
  // --- Executive briefing bar --------------------------------------
  'chat.exec.kicker': 'Sovereign briefing',
  'chat.exec.scope': 'Qualified sources · press, projects, agenda, map and observations',
  'chat.voice.stop': 'Stop',
  'chat.voice.stop.hint': 'Stop the voice: cut playback and the listening loop.',
  'chat.deep_search.done_for': 'Deep Search finished for “{query}”.',
  'chat.deep_search.running_for': 'Deep Search running for “{query}”.',
  'chat.deep_search.started_notice': 'Deep search started to refine this answer.',
  'chat.voice.unavailable': 'Voice unavailable',
  'chat.voice.resume_aya': 'Resume AYA',
  'chat.voice.aya_listening': 'AYA is listening',
  'chat.voice.talk_to_aya': 'Talk to AYA',
  'chat.voice.resume_aya_title': 'Restart the AYA voice loop.',
  'chat.voice.aya_active_title': 'The AYA voice session is active. The stop, pause and cancel commands stay available.',
  'chat.voice.talk_to_aya_title': 'Start a continuous voice conversation with AYA.',
  'chat.voice.loop_paused_title': 'Conversation loop paused. Press Resume to reopen the microphone.',
  'chat.voice.stop_no_rearm_title': 'Stop the voice: cut playback and the listening loop (no follow-up).',
  'chat.voice.cut_playback_title': 'Cut the voice playback in progress.',
  'chat.voice.playback_cut': 'Playback cut',
  'chat.voice.rephrase_prompt': 'Rephrase your last answer in a shorter, more actionable way.',
  'chat.suggestion.question_ready': 'Question ready. Complete it if needed, then send.',
  'chat.qa.review_tooltip': 'The automatic quality check recommends verifying this answer before using it. Click to see the detail.',
  'chat.correction.title': 'Correction',
  'chat.correction.dictation': 'Dictation',
  'chat.correction.thanks': 'Thank you',
  'chat.correction.mic_unsupported': 'The mic is unavailable in this browser. Type the correction.',
  'chat.correction.mic_denied': 'Mic access denied. You can type the correction manually.',
  'chat.correction.no_sound': 'No sound captured. Retry or type the correction.',
  'chat.correction.empty_transcript': 'Empty transcription. You can type the correction.',
  'chat.correction.local_transcript': 'Server transcription unavailable — text captured locally, please review it.',
  'chat.correction.transcript_failed': 'Transcription unavailable. Type the correction manually.',
  'chat.correction.text_required': 'Type or dictate a correction before sending.',
  'chat.correction.published': 'Expert knowledge published — takes priority.',
  'chat.correction.sent_tap': 'Correction sent for review — tap to open the review queue.',
  'chat.correction.sent': 'Correction sent for review.',
  'chat.correction.disabled': 'Expert correction is not enabled for this workspace.',
  'chat.trace.toggle': 'Traceability',
  'chat.trace.hide': 'Hide advanced settings',
  'chat.trace.show': 'Show traceability and advanced settings',
  'chat.map.ready': 'Strategic map ready',
  // --- Deep Search --------------------------------------------------
  'chat.deep.answer': 'Deep Search answer',
  'chat.deep.tracking': 'persistent tracking',
  'chat.deep.server_note': 'Deep Search keeps running on the server; this tracker updates from {url}.',
  'chat.deep.resume_note':
    'Deep Search keeps running on the server; tracking stays available after the answer.',
  // --- Expert correction --------------------------------------------
  'chat.correct.action': 'Correct',
  'chat.correct.hint': 'Correct or complete this answer (expert review required)',
  'chat.correct.title': 'Expert correction',
  'chat.correct.placeholder': 'Correct or complete the answer. You can also dictate it.',
  'chat.correct.question': 'Question:',
  'chat.correct.mic.stop': 'Stop and transcribe',
  'chat.correct.mic.transcribing': 'Transcribing…',
  'chat.correct.mic.start': 'Dictate the correction',
  'chat.correct.live': 'Live',
  'chat.correct.state.recording': '● Recording… tap the square to stop',
  'chat.correct.state.ready': 'Transcript ready — review and adjust before sending.',
  'chat.correct.state.idle': 'Typing or dictation — expert review required before publishing.',
  'chat.correct.sending': 'Sending…',
  'chat.correct.submit': 'Send for review',
  'chat.correct.trace.published': 'Expert knowledge published — ranked first',
  'chat.correct.trace.sent': 'Correction sent for review',
  'chat.correct.trace.voice': 'Voice dictation',
  'chat.correct.trace.published_note': 'Published and ranked ahead of ingested documents.',
  'chat.correct.trace.pending_note': 'Awaiting expert review before publishing.',
  'chat.correct.trace.queue': 'Open the review queue',
  'chat.qa.verify': 'Answer to verify',
  // --- Ask surface: the chat empty state and its configurable defaults ---
  'chat.ask.title': 'Ask your question',
  'chat.ask.title_scoped': 'Ask {name}',
  'chat.ask.subtitle':
    'Ask a question about the workspace context. The answer cites the sources it used.',
  'chat.ask.subtitle_scoped': 'Ask a question about the {scope} context.',
  'chat.ask.placeholder': 'Ask your question…',
  'chat.ask.placeholder_scoped': 'Ask {name} about the workspace sources…',
  'chat.ask.source_fallback': 'the workspace context',
  'chat.ask.title_default': 'Start a conversation',
  'chat.ask.subtitle_context':
    'Ask a question about the {scope} context. The answer cites the sources it used.',
  'chat.ask.subtitle_executive':
    'Ask about signals, projects, sources and the decisions expected of you.',
  'chat.ask.subtitle_session':
    'Ask a sourced question grounded only in the documents uploaded for this session.',
  'chat.ask.subtitle_session_combine':
    'Ask a sourced question across session documents and {source}.',
  'chat.ask.subtitle_scope': 'Ask a sourced question using {source}.',
  'chat.ask.subtitle_default':
    'Ask a workspace question. {brand} routes retrieval automatically and cites the sources used.',
  'chat.ask.placeholder_session': 'Ask about the uploaded session documents…',
  'chat.ask.placeholder_session_combine': 'Ask across session documents and {source}…',
  'chat.ask.placeholder_scope': 'Ask a sourced question using {source}…',
  'chat.ask.placeholder_default': 'Ask a workspace question…',
  // --- Live progress while an answer is being composed ---------------
  'chat.progress.composing': 'Writing the answer…',
  'chat.progress.passages_found': '{count} passages found · analysing…',
  'chat.progress.passages_found_one': '1 passage found · analysing…',
  'chat.progress.passages_analysed': 'Passages analysed…',
  'chat.progress.analysing': 'Analysing the passages…',
  'chat.progress.searching': 'Searching the documents…',
  'chat.progress.preparing': 'Preparing the query…',
  // --- Generated prompt pack ----------------------------------------
  'chat.prompt.ask.label': 'Ask a question',
  'chat.prompt.ask.prompt':
    'What do the {source} documents say about [your topic]? Cite the sources you used.',
  'chat.prompt.ask.prompt_selected':
    'What do the selected documents say about [your topic]? Cite the sources you used.',
  'chat.prompt.find.label': 'Find a passage',
  'chat.prompt.find.prompt':
    'Find in {source} the passage, procedure or section that explains [your topic].',
  'chat.prompt.compare.label': 'Compare',
  'chat.prompt.compare.prompt':
    'Compare the information available in {source} about [your topic].',
  'chat.prompt.summarize.label': 'Summarise',
  'chat.prompt.summarize.prompt':
    'Summarise the key points found in {source} about [your topic], with the relevant sources.',
  // Same four intents, worded for a scope that names no source.
  'chat.prompt.ask.prompt_plain':
    'What do the documents say about [your topic]? Cite the sources you used.',
  'chat.prompt.ask.prompt_workspace':
    'What do the workspace documents say about [your topic]? Cite the sources you used.',
  'chat.prompt.find.prompt_plain':
    'Find the passage, procedure or section that explains [your topic].',
  'chat.prompt.find.prompt_with_doc':
    'Find the passage, procedure or section that explains [your topic], with its source document.',
  'chat.prompt.compare.prompt_plain':
    'Compare the information available about [your topic] and list the sources you used.',
  'chat.prompt.compare.prompt_docs':
    'Compare the information available about [your topic] across the documents.',
  'chat.prompt.summarize.prompt_plain':
    'Summarise the key points about [your topic] with the relevant sources.',
  'chat.prompt.verify.label': 'Check the sources',
  'chat.prompt.verify.prompt':
    'Answer the question from the available documents. If no passage answers it clearly, just say so.',
  'chat.prompt.sourced.label': 'Sourced answer',
  'chat.prompt.sourced.prompt':
    'Answer my question using only the selected documents and cite the relevant sources.',
  // Session-scoped files dropped into the conversation.
  'chat.prompt.files_summarize.label': 'Summarise the files',
  'chat.prompt.files_summarize.prompt':
    'Summarise the files I added and cite the file names you used.',
  'chat.prompt.files_summarize.prompt_combine':
    'Summarise the files I added and complete with {source} where useful, citing the sources.',
  'chat.prompt.files_ask.label': 'Ask the files',
  'chat.prompt.files_ask.prompt':
    'Answer my question from the files I added, with the relevant sources.',
  'chat.prompt.files_compare.prompt':
    'Compare the information available across the files I added about [your topic].',
  'chat.prompt.files_compare.prompt_combine':
    'Compare the files I added with {source} about [your topic].',
  'chat.prompt.files_note.label': 'Draft a note',
  'chat.prompt.files_note.prompt':
    'Draft a short note from the files I added, with the sources to verify.',
};
