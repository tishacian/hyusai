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
  // --- Session list (history rail) -----------------------------------
  'chat.session.untitled': 'Nouvelle conversation',
  'chat.session.messages': '{count} messages',
  'chat.session.messages_one': '1 message',
  // --- Toolbar controls ----------------------------------------------
  'chat.controls.runtime_hint':
    'Runtime de chat utilisé pour générer les réponses. Les détails du fournisseur sont masqués en présentation démo.',
  'chat.controls.sources': 'Sources',
  'chat.controls.sources_info':
    'Sélectionnez la source du workspace utilisée par la recherche. Auto suit le défaut du profil d’assistant si disponible, sinon le contexte du workspace.',
  'chat.controls.source_auto': 'Auto · {label}',
  'chat.controls.source_default': 'Contexte par défaut',
  'chat.controls.session_docs': 'Docs de session',
  'chat.controls.session_docs_hint':
    'Choisissez si les documents de session déposés remplacent ou complètent les sources du workspace sélectionnées.',
  'chat.controls.session_docs_info':
    '« Seuls » n’interroge que les documents de session déposés. « + Sources » les combine avec les sources du workspace sélectionnées.',
  'chat.controls.session_docs_only': 'Seuls',
  'chat.controls.session_docs_combine': '+ Sources',
  'chat.controls.retrieval': 'Recherche',
  'chat.controls.retrieval_info':
    'Choisissez comment {brand} interroge les sources indexées pour cette question. Auto suit les défauts du workspace et de la source.',
  'chat.controls.reasoning': 'Raisonnement',
  'chat.controls.reasoning_info':
    'Choisissez le cadrage de la réponse. Auto laisse {brand} déduire le meilleur modèle de raisonnement selon la question.',
  'chat.controls.reasoning_auto_hint':
    'Le sélecteur heuristique choisit le modèle de raisonnement pour chaque question',
  'chat.controls.auto': 'Auto',
  'chat.controls.clear': 'Effacer la conversation',
  // --- Retrieval mode picker -----------------------------------------
  'chat.rag.auto_hint': 'Utiliser le défaut du workspace',
  'chat.rag.naive': 'Naïve',
  'chat.rag.naive_hint': 'Recherche vectorielle en une passe',
  'chat.rag.hybrid': 'Hybride',
  'chat.rag.hybrid_hint': 'Sparse + dense, budget maîtrisé',
  'chat.rag.hah': 'HAH',
  'chat.rag.hah_hint': 'Hierarchical Answer Harvesting',
  'chat.rag.chah': 'C-HAH',
  'chat.rag.chah_hint': 'HAH composite, budget maîtrisé',
  // --- Demo voice chips ----------------------------------------------
  'chat.demo.voice_chips': 'Phrases démo (repli voix)',
  'chat.demo.voice_chips_hide': 'Masquer',
  // --- Action manifests bar ------------------------------------------
  'chat.actions.title': 'Actions',
  'chat.actions.info':
    'Manifestes d’actions du workspace ou du système disponibles pour ce chat. La voix peut résoudre les mêmes commandes sûres depuis les transcriptions finales.',
  'chat.actions.confirm_badge': 'à confirmer',
  'chat.actions.proposed':
    'Action proposée : {label}. Une confirmation sera demandée si elle modifie des données.',
  'chat.actions.ready': 'Action prête : {label}.',
  // --- Reasoning trail -----------------------------------------------
  'chat.trail.toggle': 'Fil de raisonnement · {count} étapes',
  'chat.trail.toggle_one': 'Fil de raisonnement · 1 étape',
  'chat.trail.step': 'Étape',
  'chat.trail.running': 'en cours',
  // --- Evaluation metrics --------------------------------------------
  'chat.metrics.collapse': 'Replier les métriques',
  'chat.metrics.expand': 'Déplier les métriques',
  'chat.metrics.label': 'métriques',
  'chat.metrics.lower_better': 'Plus bas = meilleur',
  'chat.metrics.max': 'Max {value}',
  'chat.metrics.good': '{count} bon(s)',
  'chat.metrics.fair': '{count} moyen(s)',
  'chat.metrics.poor': '{count} faible(s)',
  'chat.metrics.none': '{count} nul(s)',
  'chat.metrics.desc.relevance':
    'Similarité cosinus entre les embeddings de la question et de la réponse.',
  'chat.metrics.desc.factuality':
    'Similarité cosinus max entre la réponse et les passages retrouvés.',
  'chat.metrics.desc.coherence':
    'Similarité cosinus moyenne entre les phrases consécutives de la réponse.',
  'chat.metrics.desc.hhem':
    'Ancrage = mean_sim × factualité, tassé par 1/(1+mf). Plus haut = moins d’hallucinations. Plage réaliste ~0,28–0,38.',
  'chat.metrics.desc.adv_hhem':
    'Ancrage composé × cohérence × pertinence. Très pénalisant par construction (produit de 4 scores cosinus). Plage réaliste ~0,10–0,20.',
  'chat.metrics.desc.hallucination_rate':
    'Part des affirmations qui n’ont pas pu être ancrées. Plus bas = meilleur.',
  // --- Citations ------------------------------------------------------
  'chat.citation.unavailable': 'Source [{n}] citée par le modèle mais indisponible',
  'chat.citation.missing': 'Source [{n}] — indisponible',
  'chat.citations.missing_intro': 'Le modèle a fait référence à',
  'chat.citations.missing_none':
    'mais aucune source de recherche n’a été retournée pour cette réponse.',
  'chat.citations.missing_partial':
    'mais seulement {count} sources ont été retournées ; ces citations sont probablement hallucinées.',
  'chat.citations.missing_partial_one':
    'mais une seule source a été retournée ; ces citations sont probablement hallucinées.',
  // --- Sources panel ---------------------------------------------------
  'chat.sources.toggle': 'Sources · {count}',
  'chat.sources.cited_aria': 'Source citée',
  'chat.sources.uncited_aria': 'Trouvée mais non citée dans la réponse',
  'chat.sources.uncited': 'non citée',
  'chat.sources.uncited_hint': 'Ce passage a été trouvé mais le modèle ne l’a pas cité',
  'chat.sources.preview': 'Prévisualiser le document source',
  'chat.source.locator_page': 'p. {page}',
  'chat.source.locator_page_hint': 'Page {page}',
  'chat.source.locator_row': 'ligne {range}',
  'chat.source.locator_sheet': 'Repère tableur : {label}',
  'chat.source.locator_chunk': 'passage {index}',
  'chat.source.locator_chunk_hint': 'Index du passage : {index}',
  'chat.source.locator_doc_hint': 'Identifiant du document : {id}',
  'chat.preview.source_subtitle': 'Source de la recherche',
  'chat.answer.empty': '(pas de réponse)',
  // --- Turn summary bar ------------------------------------------------
  'chat.summary.steps': '{count} étapes',
  'chat.summary.steps_one': '1 étape',
  'chat.summary.sources': '{count} sources',
  'chat.summary.rag_override_hint': 'Mode de recherche forcé',
  'chat.summary.route': 'Route : {label}',
  'chat.summary.sparse_degraded_hint':
    'Couche sparse {status} — recherche hybride repliée en dense seul pour ce tour.',
  'chat.summary.dense_only': 'dense seul',
  'chat.summary.reasoning_template_hint': 'Modèle de raisonnement',
  'chat.summary.runs_link': 'Exécutions',
  'chat.summary.quality_link': 'Qualité',
  // --- Decision trace panel --------------------------------------------
  'chat.decision.title': 'Trace de décision',
  'chat.decision.reason': 'Motif',
  'chat.decision.reason_fallback': 'Route sélectionnée à l’exécution.',
  'chat.decision.tradeoff': 'Compromis',
  'chat.decision.tradeoff_fallback': 'Aucun compromis consigné.',
  'chat.decision.trace_fallback': 'Trace de décision de recherche',
  'chat.decision.quality_fallback': 'Contrôles qualité non consignés',
  'chat.decision.sparse': 'Sparse {status}',
  'chat.decision.cross_encoder': 'Cross-encoder {status}',
  'chat.decision.latency': 'Latence {profile}',
  'chat.decision.query_type': 'Type {type}',
  'chat.decision.sources_none': 'Sources : aucune sélectionnée dans la trace',
  'chat.decision.sources_line': 'Sources : {labels}',
  'chat.decision.sources_count': '{count} source(s) sélectionnée(s)',
  // --- Retrieval policy chip -------------------------------------------
  'chat.retrieval_policy.refine': 'Affinage',
  'chat.retrieval_policy.retrieval': 'Recherche',
  'chat.retrieval_policy.catalogue': 'Catalogue',
  'chat.retrieval_policy.deep': 'Deep',
  'chat.retrieval_policy.guardrail': 'Garde-fou',
  'chat.retrieval_policy.auto_scoped': 'Ciblage auto',
  'chat.retrieval_policy.fast': 'Rapide',
  'chat.retrieval_policy.balanced': 'Équilibré',
  'chat.retrieval_policy.title_fallback': 'Politique de recherche déduite par le système',
  // --- Deep Search tracker ----------------------------------------------
  'chat.deep.title': 'Deep Search',
  'chat.deep.passages': '{count} passages',
  'chat.deep.details': 'Détails',
  'chat.deep.details_loading': 'Chargement des passages de la recherche approfondie',
  'chat.deep.details_empty': 'Recherche approfondie terminée sans passage affichable.',
  'chat.deep.details_error': 'Impossible de charger le détail de la recherche approfondie.',
  'chat.deep.state.partial_count': 'Deep partiel · {count}',
  'chat.deep.state.partial': 'Deep partiel',
  'chat.deep.state.done_count': 'Deep terminé · {count}',
  'chat.deep.state.done': 'Deep terminé',
  'chat.deep.state.failed': 'Deep en échec',
  'chat.deep.state.stopped': 'Deep arrêté',
  'chat.deep.state.progress': 'Deep {percent}%',
  'chat.deep.state.queued': 'Deep en attente',
  'chat.deep.state.running': 'Deep en cours',
  'chat.deep.state.plain': 'Deep',
  'chat.deep.no_source_question':
    'Impossible de retrouver la question d’origine de cette Deep Search.',
  'chat.deep.launch_failed': 'Impossible de lancer la Deep Search.',
  // --- Post-answer audit toolbar -----------------------------------------
  'chat.audit.helpful': 'Utile',
  'chat.audit.not_helpful': 'Pas utile',
  'chat.audit.copy': 'Copier la réponse',
  'chat.audit.deep_search_hint': 'Lancer une Deep Search persistante pour cette réponse',
  'chat.audit.deep_launching': 'Deep…',
  'chat.audit.deep_tracked': 'Suivi Deep',
  'chat.audit.deep_search': 'Deep Search',
  'chat.audit.fact_check_hint': 'Vérifier les faits avec LLM-as-Judge',
  'chat.audit.scoring': 'Notation…',
  'chat.audit.fact_check': 'Vérifier les faits',
  'chat.audit.score': 'Score {value}',
  'chat.audit.claims': 'Audit des affirmations',
  'chat.audit.no_query': 'Aucune question correspondante trouvée pour cette réponse',
  'chat.audit.fact_check_score': 'Score composite {score}/100',
  'chat.audit.evaluation_failed': 'Échec de l’évaluation',
  // --- Auto-QA toast -------------------------------------------------------
  'chat.qa.flagged_title': 'Réponse signalée par le contrôle qualité auto',
  'chat.qa.flagged_breaches':
    'Composite {score}/100 · seuils dépassés : {metrics} · toucher pour vérifier',
  'chat.qa.flagged_review': 'Composite {score}/100 · toucher pour vérifier',
  // --- Composer -------------------------------------------------------------
  'chat.input.ask': 'Interroger',
  'chat.input.send': 'Envoyer',
  'chat.input.working': 'En cours…',
  'chat.input.streaming': 'Génération…',
  // --- Scope labels -----------------------------------------------------------
  'chat.scope.session_only': 'Documents de session uniquement',
  'chat.scope.session_plus': 'Documents de session + {label}',
  'chat.scope.profile_default': 'Défaut du profil',
  'chat.scope.sources': 'Sources : {label}',
  'chat.scope.workspace_fallback': 'workspace',
  'chat.controls.runtime_managed': 'runtime géré',
  'chat.map.command_fallback': 'vue territoriale mise à jour',
  // --- Chat toasts ----------------------------------------------------------
  'chat.toast.create_failed': 'Impossible de créer la session de chat',
  'chat.toast.load_failed': 'Impossible de charger la session de chat',
  'chat.toast.archive_failed': 'Impossible d’archiver cette conversation',
  'chat.toast.delete_failed': 'Impossible de supprimer cette conversation',
  'chat.toast.stream_lost': 'Connexion perdue pendant la génération',
  'chat.toast.copied': 'Copié dans le presse-papiers',
  'chat.toast.copy_failed': 'Échec de la copie',
  'chat.feedback.helpful': 'Marquée utile',
  'chat.feedback.recorded': 'Retour enregistré',
  'chat.correction.send_failed': 'Envoi de la correction impossible.',
  // --- Voice: statuses, notices, oracle panel --------------------------------
  'chat.voice.title': 'Voix',
  'chat.voice.oracle_batch': 'Mode par lot : aucune session vocale persistante ouverte.',
  'chat.voice.oracle_session':
    'Mode session : {brand} émettra des événements de transcription, d’oracle et de runtime à chaque tour de voix.',
  'chat.voice.status.unknown': 'runtime inconnu',
  'chat.voice.status.ready': 'prêt',
  'chat.voice.status.disabled': 'désactivé',
  'chat.voice.status.fallback_required': 'repli requis',
  'chat.voice.status.experimental': 'expérimental',
  'chat.voice.timeline.listening': 'écoute',
  'chat.voice.timeline.listening_detail':
    'Le micro enregistre. La voix de l’agent est en pause pour éviter le chevauchement.',
  'chat.voice.timeline.thinking': 'réflexion',
  'chat.voice.timeline.thinking_detail':
    '{brand} a reçu une transcription et met à jour l’oracle en arrière-plan.',
  'chat.voice.timeline.refreshed': 'rafraîchi',
  'chat.voice.timeline.refreshed_detail':
    'Un signal oracle plus récent a remplacé l’ancien (dernier arrivé prioritaire).',
  'chat.voice.timeline.fallback': 'repli',
  'chat.voice.timeline.fallback_detail':
    'Le runtime sélectionné a utilisé sa voie de repli pour ce tour de voix.',
  'chat.voice.timeline.committed': 'validé',
  'chat.voice.timeline.committed_detail':
    'La dernière décision transcription/oracle est validée pour le tour en cours.',
  'chat.voice.detail.stt_streaming': 'STT en continu',
  'chat.voice.detail.stt_batch': 'STT par lot',
  'chat.voice.detail.stt_cascade': 'cascade de repli en entrée',
  'chat.voice.detail.stt_none': 'pas de STT',
  'chat.voice.detail.out_native': 'sortie native',
  'chat.voice.detail.out_cascade': 'cascade de repli en sortie',
  'chat.voice.detail.out_none': 'pas de TTS',
  'chat.voice.detail.transport_channel': 'canal vocal {brand}',
  'chat.voice.detail.transport_http': 'HTTP par lot',
  'chat.voice.detail.oracle_tandem': 'oracle en tandem',
  'chat.voice.detail.oracle_fallback': 'oracle via repli',
  'chat.voice.detail.webrtc_demo':
    'temps réel · WebRTC requis · pas encore disponible en session de chat',
  'chat.voice.detail.webrtc': '{runtime} · WebRTC requis · session de chat non branchée',
  'chat.voice.oracle_panel_demo':
    'Boucle vocale temps réel avec oracle Knowledge en arrière-plan. Les détails du fournisseur sont masqués.',
  'chat.voice.oracle_panel':
    'Boucle temps réel + oracle en arrière-plan avec événements dernier-arrivé-prioritaire : oracle.delta, oracle.superseded, oracle.action et oracle.commit.',
  'chat.voice.title_webrtc_required': '{label} · WebRTC requis',
  'chat.voice.title_unavailable': '{label} · indisponible',
  'chat.voice.title_not_configured': '{label} · non configuré',
  'chat.voice.title_experimental': '{label} · expérimental',
  'chat.voice.title_webrtc_not_wired': '{label} · WebRTC non branché dans le chat',
  'chat.voice.realtime_requires_webrtc':
    'La voix temps réel requiert la voie WebRTC, qui n’est pas encore branchée sur ce contrôle de chat.',
  'chat.voice.runtime_requires_webrtc':
    '{runtime} requiert WebRTC. Ce contrôle de chat utilise pour l’instant les sessions WebSocket {brand}.',
  'chat.voice.runtime_demo_hint':
    'Runtime {kind}. Les détails du fournisseur et du modèle sont masqués en présentation démo.',
  'chat.voice.realtime_toast':
    'La voix temps réel requiert la voie WebRTC ; cette surface de chat utilise pour l’instant les sessions vocales {brand}.',
  'chat.voice.transport_hint':
    'Le mode par lot enregistre un segment audio via HTTP. Le mode session ouvre un canal vocal {brand} persistant ; Cascade finalise toujours par segment. La voix temps réel complète requiert WebRTC.',
  'chat.voice.realtime_webrtc_not_wired':
    'La voix temps réel requiert WebRTC ; ce contrôle de session de chat n’y est pas encore relié.',
  'chat.voice.session_path_unavailable':
    'Ce runtime vocal n’expose pas la voie de session vocale {brand}.',
  'chat.voice.session_button_hint':
    'Utiliser la session vocale {brand} : text.partial, text.final, événements oracle et métriques runtime.',
  'chat.voice.realtime_webrtc_uses_brand':
    'La voix temps réel requiert la voie WebRTC. Ce contrôle utilise pour l’instant les sessions vocales {brand}.',
  'chat.voice.tandem_hint':
    'Le panneau de session montre le cycle du tour de voix : écoute, mise à jour de l’oracle en arrière-plan, rafraîchissements dernier-arrivé, repli et validation.',
  'chat.voice.mic_cannot_demo': 'Le runtime vocal ne peut pas transcrire l’audio',
  'chat.voice.mic_cannot': 'Le fournisseur sélectionné ne peut pas transcrire la voix',
  'chat.voice.transcribing': 'Transcription…',
  'chat.voice.transcribing_with': 'Transcription avec {provider}…',
  'chat.voice.mic_listening': 'Écoute en cours. Le silence envoie ce tour.',
  'chat.voice.mic_stop': 'Arrêter l’enregistrement',
  'chat.voice.mic_record': 'Enregistrer la voix · {mode}',
  'chat.voice.mic_record_provider': 'Enregistrer la voix · {provider} · {mode}',
  'chat.voice.mode_session': 'session',
  'chat.voice.mode_batch': 'lot',
  'chat.voice.kind.cascade': 'Cascade',
  'chat.voice.kind.realtime': 'Temps réel',
  'chat.voice.kind.stt': 'Transcription',
  'chat.voice.kind.tts': 'Sortie vocale',
  'chat.voice.kind.generic': 'Runtime vocal',
  'chat.voice.resume_playback': 'Reprendre la lecture vocale',
  'chat.voice.pause_playback': 'Mettre la lecture vocale en pause',
  'chat.voice.output_on': 'Sortie vocale activée',
  'chat.voice.output_off': 'Sortie vocale désactivée',
  'chat.voice.tts_cannot_demo': 'Le runtime vocal ne peut pas synthétiser la voix.',
  'chat.voice.tts_cannot': 'Le fournisseur vocal sélectionné ne peut pas synthétiser la voix.',
  'chat.voice.output_enabled': 'Sortie vocale activée',
  'chat.voice.output_disabled': 'Sortie vocale désactivée',
  'chat.voice.capture_manual':
    'Fin de tour automatique désactivée ; utilisez l’arrêt manuel pour les micros dégradés.',
  'chat.voice.capture_robust':
    'Capture robuste : silence {silence} ms, parole min {speech} ms.',
  'chat.voice.capture_normal': 'La capture normale suit les réglages voix du workspace.',
  'chat.voice.capture_manual_enabled': 'Mode de capture manuel activé pour ce tour.',
  'chat.voice.stt_cannot_demo': 'Le runtime vocal ne peut pas transcrire l’audio.',
  'chat.voice.stt_cannot': 'Le fournisseur vocal sélectionné ne peut pas transcrire l’audio.',
  'chat.voice.output_stopped_listening': 'Sortie vocale coupée pour l’écoute',
  'chat.voice.listening_robust':
    'Écoute : la capture robuste attendra un silence stable.',
  'chat.voice.listening_auto':
    'Écoute : l’assistant terminera ce tour de voix après un court silence.',
  'chat.voice.listening_manual':
    'Écoute : appuyez à nouveau sur le micro pour terminer ce tour de voix.',
  'chat.voice.speech_detected': 'Parole détectée. L’assistant enverra après un silence.',
  'chat.voice.no_speech_short': 'Aucune parole détectée',
  'chat.voice.no_turn_submitted':
    'Aucun tour de voix envoyé. Le micro va se rouvrir automatiquement.',
  'chat.voice.turn_ended_transcribing': 'Tour de voix terminé ; transcription de l’audio final.',
  'chat.voice.mic_denied': 'Accès au micro refusé',
  'chat.voice.loop_unavailable': 'La boucle vocale n’est pas disponible pour ce runtime.',
  'chat.voice.session_unsupported':
    'Le runtime sélectionné ne peut pas ouvrir la session vocale {brand}.',
  'chat.voice.loop_starting': 'Démarrage de la boucle de conversation',
  'chat.voice.loop_armed': 'Boucle de conversation armée. Parlez après l’ouverture du micro.',
  'chat.voice.conversation_paused': 'Conversation en pause',
  'chat.voice.loop_paused_msg':
    'Boucle de conversation en pause. Reprenez pour rouvrir le micro.',
  'chat.voice.conversation_resuming': 'Reprise de la conversation',
  'chat.voice.loop_rearming': 'La boucle de conversation réarme le micro.',
  'chat.voice.conversation_stopped': 'Conversation arrêtée',
  'chat.voice.conversation_stopped_reason': 'Conversation arrêtée · {reason}',
  'chat.voice.loop_stopped_msg':
    'Boucle de conversation arrêtée. Les tours vocaux par lot restent disponibles.',
  'chat.voice.conversation_rearming': 'Réarmement de la conversation',
  'chat.voice.answer_complete': 'Réponse terminée. Le micro va se rouvrir automatiquement.',
  'chat.voice.session_reset': 'Session vocale réinitialisée après changement de workspace.',
  'chat.voice.arming_mic': 'Armement du micro',
  'chat.voice.endpoint_detected': 'Fin de tour détectée ; clôture du tour de voix.',
  'chat.voice.loop_paused_short': 'Boucle de conversation en pause.',
  'chat.voice.endpoint.silence': 'Silence détecté',
  'chat.voice.endpoint.max_turn': 'Durée max du tour de voix atteinte',
  'chat.voice.endpoint.pause': 'Tour de voix en pause',
  'chat.voice.endpoint.stop': 'Tour de voix arrêté',
  'chat.voice.endpoint.ended': 'Tour de voix terminé',
  'chat.voice.no_speech_recording': 'Aucune parole détectée dans l’enregistrement',
  'chat.voice.draft_replaced':
    'Brouillon existant remplacé par la transcription vocale finale avant l’envoi auto.',
  'chat.voice.transcript_ready_fallback': 'Transcription prête · repli utilisé',
  'chat.voice.transcript_ready': 'Transcription prête',
  'chat.voice.draft_cancelled': 'Brouillon vocal annulé',
  'chat.voice.no_answer_repeat': 'Aucune réponse à répéter pour l’instant',
  'chat.voice.no_answer_rephrase': 'Aucune réponse à reformuler pour l’instant',
  'chat.voice.command_capture_only':
    'Cette commande vocale est disponible dans les sessions Knowledge Capture.',
  'chat.voice.command_committed': 'Commande vocale validée : {command}.',
  'chat.voice.fallback_used': 'Repli utilisé',
  'chat.voice.transcription_failed': 'Échec de la transcription',
  'chat.voice.session_notice': 'Session vocale',
  'chat.voice.segment_sent':
    'Segment audio envoyé à la session vocale ; en attente de la transcription.',
  'chat.voice.session_failed': 'Échec de la session vocale',
  'chat.voice.session_failed_msg': 'Échec de la session vocale.',
  'chat.voice.finalising_turn':
    'Finalisation du tour de voix en continu ; en attente de la transcription.',
  'chat.voice.session_ready': 'Session vocale prête',
  'chat.voice.channel_ready':
    'Canal de session prêt. Enregistrez un tour de voix pour démarrer le suivi oracle.',
  'chat.voice.transcript_received': 'Transcription reçue : « {text} »',
  'chat.voice.transcript_received_updating':
    'Transcription reçue ; l’oracle se met à jour.',
  'chat.voice.transcript_fallback_done':
    'Transcription produite via le repli ; le texte vocal final est prêt.',
  'chat.voice.transcript_committed': 'Transcription finale validée pour ce tour de voix.',
  'chat.voice.conversation_armed': 'Conversation armée',
  'chat.voice.loop_ready': 'Boucle de conversation prête',
  'chat.voice.output_complete': 'Sortie vocale terminée',
  'chat.voice.output_interrupted': 'Sortie vocale interrompue',
  'chat.voice.command': 'Commande vocale · {command}',
  'chat.voice.oracle_micro_turns': 'Oracle en tandem : suivi des micro-tours',
  'chat.voice.micro_turn_tracked':
    'Micro-tour suivi ; l’oracle en arrière-plan suit la conversation.',
  'chat.voice.oracle_updating': 'Oracle en tandem en mise à jour',
  'chat.voice.oracle_delta':
    'Delta oracle reçu ; le contexte en arrière-plan se met à jour.',
  'chat.voice.oracle_refreshed': 'Oracle en tandem rafraîchi',
  'chat.voice.oracle_superseded_msg':
    'Ancien signal oracle remplacé par un état de transcription plus récent.',
  'chat.voice.oracle_action': 'Action oracle · {action}',
  'chat.voice.oracle_action_ready': 'Action oracle prête : {action}.',
  'chat.voice.oracle_committed': 'Oracle : dernier tour validé',
  'chat.voice.oracle_committed_msg': 'Dernier état oracle validé pour ce tour.',
  'chat.voice.speaking': 'Lecture en cours.',

  // --- Workspace chat shell (chat-workspace) -------------------------
  'chat.workspace.mode.search': 'Recherche',
  'chat.workspace.mode.drop_ask': 'Drop-and-ask',
  'chat.workspace.mode.system': 'Chat de Système',
  'chat.workspace.mode.quick_ask': 'Question rapide',
  'chat.workspace.hint.session_docs': 'Les documents de session ancrent la réponse',
  'chat.workspace.hint.scoped': 'Limité au Système sélectionné',
  'chat.workspace.hint.fast': 'Chat rapide du workspace',
  'chat.workspace.open_flow_builder':
    'Ouvrir ce Système de chat du workspace dans le Flow Builder',
  'chat.workspace.context_label': 'Contexte',
  'chat.workspace.context_hint':
    'Choisissez un Système quand il vous faut un assistant ciblé. La question rapide utilise le contexte du workspace.',
  'chat.workspace.session_docs': 'Documents de session',
  'chat.workspace.session_docs_hint':
    'Déposez des documents ici pour créer un contexte de chat temporaire. Dans les contrôles du chat, choisissez si ces documents remplacent ou complètent les sources du workspace.',
  'chat.workspace.dropzone_collapse': 'Replier la zone de dépôt',
  'chat.workspace.dropzone_expand': 'Déplier la zone de dépôt',
  'chat.workspace.drop_files': 'Déposez des fichiers',
  'chat.workspace.or_click': 'ou cliquez',
  'chat.workspace.indexing': 'Indexation',
  'chat.workspace.indexing_count': 'Indexation de {count}…',
  'chat.workspace.files_one': '{count} fichier',
  'chat.workspace.files_many': '{count} fichiers',
  'chat.workspace.remove_doc': 'Retirer de cette session de chat : {name}',
  'chat.workspace.pages_one': '{count} page',
  'chat.workspace.pages_many': '{count} pages',
  'chat.workspace.tokens': '{count} tokens',
  'chat.workspace.chunks': '{count} segments',
  'chat.workspace.by_author': 'par {name}',
  'chat.workspace.no_docs':
    "Aucun document pour l'instant. Déposez des PDF ou des tableurs, ou cliquez pour parcourir : les réponses s'appuieront sur vos propres fichiers.",
  'chat.workspace.toast.partial': '{ok}/{total} indexés · {failed} en échec',
  'chat.workspace.toast.indexed_one': '{count} fichier indexé — posez votre question.',
  'chat.workspace.toast.indexed_many': '{count} fichiers indexés — posez votre question.',
  'chat.workspace.toast.upload_failed': "Échec de l'envoi",
  'chat.workspace.toast.attach_failed':
    "Impossible d'attacher le fichier à cette session de chat.",
  'chat.workspace.toast.context_failed': 'Impossible de créer un contexte de chat temporaire.',
  'chat.workspace.toast.remove_failed':
    'Impossible de retirer le fichier de cette session de chat.',
  'chat.workspace.toast.persisted_title': 'Session conservée',
  'chat.workspace.toast.persisted': 'Enregistré sous « {name} »',
  'chat.workspace.toast.persist_failed': 'Échec de la conservation de la session',
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
  // --- Session list (history rail) -----------------------------------
  'chat.session.untitled': 'New conversation',
  'chat.session.messages': '{count} messages',
  'chat.session.messages_one': '1 message',
  // --- Toolbar controls ----------------------------------------------
  'chat.controls.runtime_hint':
    'Chat runtime used for answer generation. Provider details are hidden in demo-safe presentation.',
  'chat.controls.sources': 'Sources',
  'chat.controls.sources_info':
    'Select the workspace source searched by retrieval. Auto uses the assistant profile default when available, otherwise the workspace context.',
  'chat.controls.source_auto': 'Auto · {label}',
  'chat.controls.source_default': 'Default context',
  'chat.controls.session_docs': 'Session docs',
  'chat.controls.session_docs_hint':
    'Choose whether uploaded session documents replace or complement the selected workspace sources.',
  'chat.controls.session_docs_info':
    '“Only” searches uploaded session docs. “+ Sources” searches session docs plus the selected workspace sources.',
  'chat.controls.session_docs_only': 'Only',
  'chat.controls.session_docs_combine': '+ Sources',
  'chat.controls.retrieval': 'Retrieval',
  'chat.controls.retrieval_info':
    'Choose how {brand} searches indexed sources for this question. Auto follows workspace/source defaults.',
  'chat.controls.reasoning': 'Reasoning',
  'chat.controls.reasoning_info':
    'Choose the answer framing. Auto lets {brand} infer the best reasoning template from the question.',
  'chat.controls.reasoning_auto_hint': 'Heuristic selector picks the template per query',
  'chat.controls.auto': 'Auto',
  'chat.controls.clear': 'Clear conversation',
  // --- Retrieval mode picker -----------------------------------------
  'chat.rag.auto_hint': 'Use workspace default',
  'chat.rag.naive': 'Naive',
  'chat.rag.naive_hint': 'Single-pass vector retrieval',
  'chat.rag.hybrid': 'Hybrid',
  'chat.rag.hybrid_hint': 'Sparse + dense, budget-aware',
  'chat.rag.hah': 'HAH',
  'chat.rag.hah_hint': 'Hierarchical Answer Harvesting',
  'chat.rag.chah': 'C-HAH',
  'chat.rag.chah_hint': 'Composite HAH, budget-aware',
  // --- Demo voice chips ----------------------------------------------
  'chat.demo.voice_chips': 'Demo phrases (voice fallback)',
  'chat.demo.voice_chips_hide': 'Hide',
  // --- Action manifests bar ------------------------------------------
  'chat.actions.title': 'Actions',
  'chat.actions.info':
    'Workspace/system action manifests available to this chat. Voice can resolve the same safe commands from final transcripts.',
  'chat.actions.confirm_badge': 'confirm',
  'chat.actions.proposed':
    'Action proposed: {label}. Confirmation will be requested if it changes data.',
  'chat.actions.ready': 'Action ready: {label}.',
  // --- Reasoning trail -----------------------------------------------
  'chat.trail.toggle': 'Reasoning trail · {count} steps',
  'chat.trail.toggle_one': 'Reasoning trail · 1 step',
  'chat.trail.step': 'Step',
  'chat.trail.running': 'running',
  // --- Evaluation metrics --------------------------------------------
  'chat.metrics.collapse': 'Collapse metrics',
  'chat.metrics.expand': 'Expand metrics',
  'chat.metrics.label': 'metrics',
  'chat.metrics.lower_better': 'Lower is better',
  'chat.metrics.max': 'Max {value}',
  'chat.metrics.good': '{count} good',
  'chat.metrics.fair': '{count} fair',
  'chat.metrics.poor': '{count} poor',
  'chat.metrics.none': '{count} null',
  'chat.metrics.desc.relevance': 'Cosine similarity between query and response embeddings.',
  'chat.metrics.desc.factuality': 'Max cosine similarity between response and retrieved chunks.',
  'chat.metrics.desc.coherence':
    'Mean cosine similarity between consecutive response sentences.',
  'chat.metrics.desc.hhem':
    'Grounding = mean_sim × factuality, squashed by 1/(1+mf). Higher = less hallucinated. Realistic band ~0.28–0.38.',
  'chat.metrics.desc.adv_hhem':
    'Compound grounding × coherence × relevance. Very penalising by design (product of 4 cosine scores). Realistic band ~0.10–0.20.',
  'chat.metrics.desc.hallucination_rate':
    'Share of claims that could not be grounded. Lower is better.',
  // --- Citations ------------------------------------------------------
  'chat.citation.unavailable': 'Source [{n}] referenced by the model but not available',
  'chat.citation.missing': 'Source [{n}] — not available',
  'chat.citations.missing_intro': 'The model referenced',
  'chat.citations.missing_none': 'but no retrieval source was returned for this answer.',
  'chat.citations.missing_partial':
    'but only {count} sources were returned, so these citations are likely hallucinated.',
  'chat.citations.missing_partial_one':
    'but only 1 source was returned, so these citations are likely hallucinated.',
  // --- Sources panel ---------------------------------------------------
  'chat.sources.toggle': 'Sources · {count}',
  'chat.sources.cited_aria': 'Cited source',
  'chat.sources.uncited_aria': 'Retrieved but not cited in answer',
  'chat.sources.uncited': 'not cited',
  'chat.sources.uncited_hint': 'This chunk was retrieved but the model did not cite it',
  'chat.sources.preview': 'Preview source document',
  'chat.source.locator_page': 'p. {page}',
  'chat.source.locator_page_hint': 'Page {page}',
  'chat.source.locator_row': 'row {range}',
  'chat.source.locator_sheet': 'Spreadsheet locator: {label}',
  'chat.source.locator_chunk': 'chunk {index}',
  'chat.source.locator_chunk_hint': 'Chunk index {index}',
  'chat.source.locator_doc_hint': 'Document id {id}',
  'chat.preview.source_subtitle': 'Retrieval source',
  'chat.answer.empty': '(no response)',
  // --- Turn summary bar ------------------------------------------------
  'chat.summary.steps': '{count} steps',
  'chat.summary.steps_one': '1 step',
  'chat.summary.sources': '{count} sources',
  'chat.summary.rag_override_hint': 'Retrieval mode override',
  'chat.summary.route': 'Route: {label}',
  'chat.summary.sparse_degraded_hint':
    'Sparse layer {status} — hybrid retrieval degraded to dense-only for this turn.',
  'chat.summary.dense_only': 'dense-only',
  'chat.summary.reasoning_template_hint': 'Reasoning template',
  'chat.summary.runs_link': 'Runs',
  'chat.summary.quality_link': 'Quality',
  // --- Decision trace panel --------------------------------------------
  'chat.decision.title': 'Decision trace',
  'chat.decision.reason': 'Reason',
  'chat.decision.reason_fallback': 'Runtime route selected.',
  'chat.decision.tradeoff': 'Tradeoff',
  'chat.decision.tradeoff_fallback': 'No tradeoff recorded.',
  'chat.decision.trace_fallback': 'Retrieval decision trace',
  'chat.decision.quality_fallback': 'Quality controls not recorded',
  'chat.decision.sparse': 'Sparse {status}',
  'chat.decision.cross_encoder': 'Cross-encoder {status}',
  'chat.decision.latency': 'Latency {profile}',
  'chat.decision.query_type': 'Type {type}',
  'chat.decision.sources_none': 'Sources: none selected in trace',
  'chat.decision.sources_line': 'Sources: {labels}',
  'chat.decision.sources_count': '{count} source(s) selected',
  // --- Retrieval policy chip -------------------------------------------
  'chat.retrieval_policy.refine': 'Refine',
  'chat.retrieval_policy.retrieval': 'Retrieval',
  'chat.retrieval_policy.catalogue': 'Catalogue',
  'chat.retrieval_policy.deep': 'Deep',
  'chat.retrieval_policy.guardrail': 'Guardrail',
  'chat.retrieval_policy.auto_scoped': 'Auto scoped',
  'chat.retrieval_policy.fast': 'Fast',
  'chat.retrieval_policy.balanced': 'Balanced',
  'chat.retrieval_policy.title_fallback': 'System-inferred retrieval policy',
  // --- Deep Search tracker ----------------------------------------------
  'chat.deep.title': 'Deep Search',
  'chat.deep.passages': '{count} passages',
  'chat.deep.details': 'Details',
  'chat.deep.details_loading': 'Loading deep retrieval passages',
  'chat.deep.details_empty': 'Deep retrieval completed without displayable passages.',
  'chat.deep.details_error': 'Could not load deep retrieval details.',
  'chat.deep.state.partial_count': 'Deep partial · {count}',
  'chat.deep.state.partial': 'Deep partial',
  'chat.deep.state.done_count': 'Deep done · {count}',
  'chat.deep.state.done': 'Deep done',
  'chat.deep.state.failed': 'Deep failed',
  'chat.deep.state.stopped': 'Deep stopped',
  'chat.deep.state.progress': 'Deep {percent}%',
  'chat.deep.state.queued': 'Deep queued',
  'chat.deep.state.running': 'Deep running',
  'chat.deep.state.plain': 'Deep',
  'chat.deep.no_source_question': 'Could not find the source question for this Deep Search.',
  'chat.deep.launch_failed': 'Could not launch Deep Search.',
  // --- Post-answer audit toolbar -----------------------------------------
  'chat.audit.helpful': 'Helpful',
  'chat.audit.not_helpful': 'Not helpful',
  'chat.audit.copy': 'Copy response',
  'chat.audit.deep_search_hint': 'Launch persistent Deep Search for this answer',
  'chat.audit.deep_launching': 'Deep…',
  'chat.audit.deep_tracked': 'Deep tracked',
  'chat.audit.deep_search': 'Deep search',
  'chat.audit.fact_check_hint': 'Fact-check with LLM-as-Judge',
  'chat.audit.scoring': 'Scoring…',
  'chat.audit.fact_check': 'Fact-check',
  'chat.audit.score': 'Score {value}',
  'chat.audit.claims': 'Claim audit',
  'chat.audit.no_query': 'No matching query found for this response',
  'chat.audit.fact_check_score': 'Composite score {score}/100',
  'chat.audit.evaluation_failed': 'Evaluation failed',
  // --- Auto-QA toast -------------------------------------------------------
  'chat.qa.flagged_title': 'Reply flagged by auto-QA',
  'chat.qa.flagged_breaches': 'Composite {score}/100 · breaches: {metrics} · tap to review',
  'chat.qa.flagged_review': 'Composite {score}/100 · tap to review',
  // --- Composer -------------------------------------------------------------
  'chat.input.ask': 'Ask',
  'chat.input.send': 'Send',
  'chat.input.working': 'Working…',
  'chat.input.streaming': 'Streaming',
  // --- Scope labels -----------------------------------------------------------
  'chat.scope.session_only': 'Session docs only',
  'chat.scope.session_plus': 'Session docs + {label}',
  'chat.scope.profile_default': 'Profile default',
  'chat.scope.sources': 'Sources: {label}',
  'chat.scope.workspace_fallback': 'workspace',
  'chat.controls.runtime_managed': 'managed runtime',
  'chat.map.command_fallback': 'territorial view updated',
  // --- Chat toasts ----------------------------------------------------------
  'chat.toast.create_failed': 'Could not create a chat session',
  'chat.toast.load_failed': 'Could not load chat session',
  'chat.toast.archive_failed': 'Could not archive this conversation',
  'chat.toast.delete_failed': 'Could not delete this conversation',
  'chat.toast.stream_lost': 'Connection lost while streaming',
  'chat.toast.copied': 'Copied to clipboard',
  'chat.toast.copy_failed': 'Copy failed',
  'chat.feedback.helpful': 'Marked as helpful',
  'chat.feedback.recorded': 'Feedback recorded',
  'chat.correction.send_failed': 'Could not send the correction.',
  // --- Voice: statuses, notices, oracle panel --------------------------------
  'chat.voice.title': 'Voice',
  'chat.voice.oracle_batch': 'Batch mode: no persistent voice session is open.',
  'chat.voice.oracle_session':
    'Session mode: {brand} will emit transcript, oracle and runtime events for each voice turn.',
  'chat.voice.status.unknown': 'runtime unknown',
  'chat.voice.status.ready': 'ready',
  'chat.voice.status.disabled': 'disabled',
  'chat.voice.status.fallback_required': 'fallback required',
  'chat.voice.status.experimental': 'experimental',
  'chat.voice.timeline.listening': 'listening',
  'chat.voice.timeline.listening_detail':
    'Microphone input is being recorded. Agent speech is paused to avoid overlap.',
  'chat.voice.timeline.thinking': 'thinking',
  'chat.voice.timeline.thinking_detail':
    '{brand} received a transcript and is updating the background oracle.',
  'chat.voice.timeline.refreshed': 'refreshed',
  'chat.voice.timeline.refreshed_detail':
    'A newer oracle signal replaced an older one using latest-wins semantics.',
  'chat.voice.timeline.fallback': 'fallback',
  'chat.voice.timeline.fallback_detail':
    'The selected runtime used its fallback lane for this voice turn.',
  'chat.voice.timeline.committed': 'committed',
  'chat.voice.timeline.committed_detail':
    'The latest transcript/oracle decision is committed for the current turn.',
  'chat.voice.detail.stt_streaming': 'streaming STT',
  'chat.voice.detail.stt_batch': 'batch STT',
  'chat.voice.detail.stt_cascade': 'input fallback cascade',
  'chat.voice.detail.stt_none': 'no STT',
  'chat.voice.detail.out_native': 'native output',
  'chat.voice.detail.out_cascade': 'output fallback cascade',
  'chat.voice.detail.out_none': 'no TTS',
  'chat.voice.detail.transport_channel': '{brand} voice channel',
  'chat.voice.detail.transport_http': 'HTTP batch',
  'chat.voice.detail.oracle_tandem': 'tandem oracle',
  'chat.voice.detail.oracle_fallback': 'oracle via fallback',
  'chat.voice.detail.webrtc_demo':
    'realtime · WebRTC required · not available in chat session yet',
  'chat.voice.detail.webrtc': '{runtime} · WebRTC required · chat session not wired yet',
  'chat.voice.oracle_panel_demo':
    'Realtime voice loop plus background Knowledge oracle. Provider details are hidden.',
  'chat.voice.oracle_panel':
    'Realtime loop + background oracle with latest-wins events: oracle.delta, oracle.superseded, oracle.action and oracle.commit.',
  'chat.voice.title_webrtc_required': '{label} · WebRTC required',
  'chat.voice.title_unavailable': '{label} · unavailable',
  'chat.voice.title_not_configured': '{label} · not configured',
  'chat.voice.title_experimental': '{label} · experimental',
  'chat.voice.title_webrtc_not_wired': '{label} · WebRTC not wired in chat',
  'chat.voice.realtime_requires_webrtc':
    'Realtime voice requires the WebRTC lane, which is not wired into this chat control yet.',
  'chat.voice.runtime_requires_webrtc':
    '{runtime} requires WebRTC. This chat control currently uses {brand} backend WebSocket sessions.',
  'chat.voice.runtime_demo_hint':
    '{kind} runtime. Provider and model details are hidden in demo-safe presentation.',
  'chat.voice.realtime_toast':
    'Realtime voice requires the WebRTC lane; this chat surface uses {brand} voice sessions for now.',
  'chat.voice.transport_hint':
    'Batch records one audio segment over HTTP. Session opens a persistent {brand} voice channel; Cascade still finalizes by segment. Full realtime speech requires WebRTC.',
  'chat.voice.realtime_webrtc_not_wired':
    'Realtime voice requires WebRTC; this chat session control is not wired to WebRTC yet.',
  'chat.voice.session_path_unavailable':
    'This voice runtime does not expose the {brand} voice session path.',
  'chat.voice.session_button_hint':
    'Use the {brand} voice session: text.partial, text.final, oracle events and runtime metrics.',
  'chat.voice.realtime_webrtc_uses_brand':
    'Realtime voice requires the WebRTC lane. This chat control currently uses {brand} voice sessions.',
  'chat.voice.tandem_hint':
    'The session panel shows the voice turn lifecycle: listening, background oracle update, latest-wins refreshes, fallback and commit.',
  'chat.voice.mic_cannot_demo': 'Voice runtime cannot transcribe audio',
  'chat.voice.mic_cannot': 'Selected provider cannot transcribe voice',
  'chat.voice.transcribing': 'Transcribing…',
  'chat.voice.transcribing_with': 'Transcribing with {provider}…',
  'chat.voice.mic_listening': 'Listening. Silence submits this turn.',
  'chat.voice.mic_stop': 'Stop recording',
  'chat.voice.mic_record': 'Record voice · {mode}',
  'chat.voice.mic_record_provider': 'Record voice · {provider} · {mode}',
  'chat.voice.mode_session': 'session',
  'chat.voice.mode_batch': 'batch',
  'chat.voice.kind.cascade': 'Cascade',
  'chat.voice.kind.realtime': 'Realtime',
  'chat.voice.kind.stt': 'Transcription',
  'chat.voice.kind.tts': 'Speech output',
  'chat.voice.kind.generic': 'Voice runtime',
  'chat.voice.resume_playback': 'Resume voice playback',
  'chat.voice.pause_playback': 'Pause voice playback',
  'chat.voice.output_on': 'Voice output on',
  'chat.voice.output_off': 'Voice output off',
  'chat.voice.tts_cannot_demo': 'Voice runtime cannot synthesize speech.',
  'chat.voice.tts_cannot': 'Selected voice provider cannot synthesize speech.',
  'chat.voice.output_enabled': 'Voice output enabled',
  'chat.voice.output_disabled': 'Voice output disabled',
  'chat.voice.capture_manual': 'Auto endpoint disabled; use manual stop for degraded microphones.',
  'chat.voice.capture_robust': 'Robust capture: silence {silence} ms, min speech {speech} ms.',
  'chat.voice.capture_normal': 'Normal capture uses workspace voice settings.',
  'chat.voice.capture_manual_enabled': 'Manual capture mode enabled for the current turn.',
  'chat.voice.stt_cannot_demo': 'Voice runtime cannot transcribe audio.',
  'chat.voice.stt_cannot': 'Selected voice provider cannot transcribe audio.',
  'chat.voice.output_stopped_listening': 'Voice output stopped for listening',
  'chat.voice.listening_robust': 'Listening: robust capture will wait for a stable silence.',
  'chat.voice.listening_auto':
    'Listening: the assistant will end this voice turn after a short silence.',
  'chat.voice.listening_manual':
    'Listening: press the microphone again to end this voice turn.',
  'chat.voice.speech_detected': 'Speech detected. The assistant will submit after silence.',
  'chat.voice.no_speech_short': 'No speech detected',
  'chat.voice.no_turn_submitted':
    'No voice turn was submitted. The microphone will reopen automatically.',
  'chat.voice.turn_ended_transcribing': 'Voice turn ended; transcribing final audio.',
  'chat.voice.mic_denied': 'Microphone access denied',
  'chat.voice.loop_unavailable': 'Voice session loop is not available for this runtime.',
  'chat.voice.session_unsupported': 'Selected runtime cannot open the {brand} voice session.',
  'chat.voice.loop_starting': 'Conversation loop starting',
  'chat.voice.loop_armed': 'Conversation loop armed. Speak after the microphone opens.',
  'chat.voice.conversation_paused': 'Conversation paused',
  'chat.voice.loop_paused_msg': 'Conversation loop is paused. Resume to reopen the microphone.',
  'chat.voice.conversation_resuming': 'Conversation resuming',
  'chat.voice.loop_rearming': 'Conversation loop is rearming the microphone.',
  'chat.voice.conversation_stopped': 'Conversation stopped',
  'chat.voice.conversation_stopped_reason': 'Conversation stopped · {reason}',
  'chat.voice.loop_stopped_msg':
    'Conversation loop stopped. Batch voice turns remain available.',
  'chat.voice.conversation_rearming': 'Conversation rearming',
  'chat.voice.answer_complete': 'Answer complete. The microphone will reopen automatically.',
  'chat.voice.session_reset': 'Voice session reset for workspace change.',
  'chat.voice.arming_mic': 'Arming microphone',
  'chat.voice.endpoint_detected': 'Endpoint detected; closing the voice turn.',
  'chat.voice.loop_paused_short': 'Conversation loop paused.',
  'chat.voice.endpoint.silence': 'Silence detected',
  'chat.voice.endpoint.max_turn': 'Max voice turn reached',
  'chat.voice.endpoint.pause': 'Voice turn paused',
  'chat.voice.endpoint.stop': 'Voice turn stopped',
  'chat.voice.endpoint.ended': 'Voice turn ended',
  'chat.voice.no_speech_recording': 'No speech detected in the recording',
  'chat.voice.draft_replaced':
    'Existing draft replaced by the final voice transcript before auto-send.',
  'chat.voice.transcript_ready_fallback': 'Transcript ready · fallback used',
  'chat.voice.transcript_ready': 'Transcript ready',
  'chat.voice.draft_cancelled': 'Voice draft cancelled',
  'chat.voice.no_answer_repeat': 'No assistant answer to repeat yet',
  'chat.voice.no_answer_rephrase': 'No assistant answer to rephrase yet',
  'chat.voice.command_capture_only':
    'This voice command is available in Knowledge Capture sessions.',
  'chat.voice.command_committed': 'Voice command committed: {command}.',
  'chat.voice.fallback_used': 'Fallback used',
  'chat.voice.transcription_failed': 'Transcription failed',
  'chat.voice.session_notice': 'Voice session',
  'chat.voice.segment_sent': 'Audio segment sent to the voice session; waiting for transcript.',
  'chat.voice.session_failed': 'Voice session failed',
  'chat.voice.session_failed_msg': 'Voice session failed.',
  'chat.voice.finalising_turn': 'Finalising the streamed voice turn; waiting for the transcript.',
  'chat.voice.session_ready': 'Voice session ready',
  'chat.voice.channel_ready':
    'Session channel ready. Record a voice turn to start oracle tracking.',
  'chat.voice.transcript_received': 'Transcript received: “{text}”',
  'chat.voice.transcript_received_updating': 'Transcript received; oracle is updating.',
  'chat.voice.transcript_fallback_done':
    'Transcript produced through fallback; final voice text is ready.',
  'chat.voice.transcript_committed': 'Final transcript committed for this voice turn.',
  'chat.voice.conversation_armed': 'Conversation armed',
  'chat.voice.loop_ready': 'Conversation loop ready',
  'chat.voice.output_complete': 'Voice output complete',
  'chat.voice.output_interrupted': 'Voice output interrupted',
  'chat.voice.command': 'Voice command · {command}',
  'chat.voice.oracle_micro_turns': 'Tandem oracle tracking micro-turns',
  'chat.voice.micro_turn_tracked':
    'Micro-turn tracked; background oracle is following the conversation.',
  'chat.voice.oracle_updating': 'Tandem oracle updating',
  'chat.voice.oracle_delta': 'Oracle delta received; the background context is updating.',
  'chat.voice.oracle_refreshed': 'Tandem oracle refreshed',
  'chat.voice.oracle_superseded_msg':
    'Older oracle signal superseded by a newer transcript state.',
  'chat.voice.oracle_action': 'Oracle action · {action}',
  'chat.voice.oracle_action_ready': 'Oracle action ready: {action}.',
  'chat.voice.oracle_committed': 'Oracle committed latest turn',
  'chat.voice.oracle_committed_msg': 'Latest oracle state committed for this turn.',
  'chat.voice.speaking': 'Speaking.',

  // --- Workspace chat shell (chat-workspace) -------------------------
  'chat.workspace.mode.search': 'Search',
  'chat.workspace.mode.drop_ask': 'Drop-and-ask',
  'chat.workspace.mode.system': 'System chat',
  'chat.workspace.mode.quick_ask': 'Quick ask',
  'chat.workspace.hint.session_docs': 'Session docs ground the answer',
  'chat.workspace.hint.scoped': 'Scoped to selected system',
  'chat.workspace.hint.fast': 'Fast workspace chat flow',
  'chat.workspace.open_flow_builder': 'Open this workspace chat system in Flow Builder',
  'chat.workspace.context_label': 'Context',
  'chat.workspace.context_hint':
    'Choose a System when you need a scoped assistant. Quick ask uses the workspace context.',
  'chat.workspace.session_docs': 'Session docs',
  'chat.workspace.session_docs_hint':
    'Drop documents here to create a temporary chat context. In the chat controls, choose whether these docs replace or complement workspace sources.',
  'chat.workspace.dropzone_collapse': 'Collapse dropzone',
  'chat.workspace.dropzone_expand': 'Expand dropzone',
  'chat.workspace.drop_files': 'Drop files',
  'chat.workspace.or_click': 'or click',
  'chat.workspace.indexing': 'Indexing',
  'chat.workspace.indexing_count': 'Indexing {count}…',
  'chat.workspace.files_one': '{count} file',
  'chat.workspace.files_many': '{count} files',
  'chat.workspace.remove_doc': 'Remove from this chat session: {name}',
  'chat.workspace.pages_one': '{count} page',
  'chat.workspace.pages_many': '{count} pages',
  'chat.workspace.tokens': '{count} tokens',
  'chat.workspace.chunks': '{count} chunks',
  'chat.workspace.by_author': 'by {name}',
  'chat.workspace.no_docs':
    'No docs yet. Drop PDFs, spreadsheets, or click browse to ground answers on your own files.',
  'chat.workspace.toast.partial': '{ok}/{total} indexed · {failed} failed',
  'chat.workspace.toast.indexed_one': '{count} file indexed — ask anything.',
  'chat.workspace.toast.indexed_many': '{count} files indexed — ask anything.',
  'chat.workspace.toast.upload_failed': 'Failed to upload',
  'chat.workspace.toast.attach_failed': 'Could not attach the file to this chat session.',
  'chat.workspace.toast.context_failed': 'Could not create a temporary chat context.',
  'chat.workspace.toast.remove_failed': 'Could not remove the file from this chat session.',
  'chat.workspace.toast.persisted_title': 'Session persisted',
  'chat.workspace.toast.persisted': 'Saved as "{name}"',
  'chat.workspace.toast.persist_failed': 'Failed to persist session',
};
