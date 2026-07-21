import { expect, test, type Page, type Route } from '@playwright/test';

const workspace = {
  id: 'ws-andritz-qa',
  name: 'Andritz QA',
  slug: 'andritz',
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 3,
  created_at: '2026-06-23T00:00:00Z',
  is_active: true,
  mode: 'executive',
  settings: {
    connectors: {
      secure_deposit: { enabled: true },
      sftp: { enabled: true },
    },
  },
};

const user = {
  id: 'user-andritz-qa',
  username: 'andritz.qa',
  email: 'andritz.qa@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Andritz',
  last_name: 'QA',
  phone: null,
  company: 'Andritz',
  job_title: 'QA',
  workspaces: [{ id: workspace.id, name: workspace.name, slug: workspace.slug, role: workspace.role }],
};

type MockRoleTemplate = 'workspace_admin' | 'workspace_reviewer';
type MockKnowledgeScope = {
  key: string;
  label: string;
  is_default?: boolean;
  collection_slugs?: string[];
};
type MockKnowledgeCollectionItem = {
  slug: string;
  name?: string | null;
  status?: string | null;
  document_count?: number | null;
  chunk_count?: number | null;
  updated_at?: string | null;
};
type MockChatSystem = {
  id: string;
  name: string;
  objective?: string;
  settings?: Record<string, unknown>;
  flow_definition?: Record<string, unknown>;
  status?: string;
};
type MockDocumentFact = {
  id?: string;
  document_id?: string;
  document_filename?: string;
  semantic_type?: string;
  page?: number | null;
  section_path?: string | null;
  content?: string | null;
  value_raw?: string | null;
  confidence?: number | null;
  qualifiers?: Record<string, unknown> | null;
  evidence_locator?: Record<string, unknown> | null;
};
type MockSftpDepositLink = {
  id: string;
  label: string;
  access_id: string;
  public_url: string;
  generated_password?: string | null;
  status: 'active' | 'revoked' | string;
  expires_at: string | null;
  max_file_size_mb: number;
  allowed_extensions: string[];
  created_at: string;
  created_by_user_id: string;
  created_by: string;
};
type MockSftpDepositFile = {
  id: string;
  access_link_id: string;
  filename: string;
  content_type?: string | null;
  size_bytes: number;
  sha256: string;
  status: 'received' | 'rejected' | 'promoted';
  uploaded_at: string | null;
  promoted_at: string | null;
  promoted_collection_slug?: string | null;
  worker_job_id: string | null;
  promotion_result?: Record<string, unknown> | null;
  rejection_reason?: string | null;
};
type MockSftpIndexingAssist = {
  summary: Record<string, unknown>;
  recommendations: Array<Record<string, unknown>>;
  collection: Record<string, unknown>;
};

function defaultSftpDepositLink(activeUser = user): MockSftpDepositLink {
  return {
    id: 'link-andritz-qa',
    label: 'Andritz QA external upload',
    access_id: 'andritz-qa',
    public_url: 'https://example.test/deposit/andritz-qa',
    status: 'active',
    expires_at: null,
    max_file_size_mb: 250,
    allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx'],
    created_at: '2026-06-23T00:00:00Z',
    created_by_user_id: activeUser.id,
    created_by: activeUser.email,
  };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function sse(route: Route, chunks: unknown[]) {
  const body = chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join('') + 'data: [DONE]\n\n';
  return route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    headers: {
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
    body,
  });
}

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function captureExpressionComposer(page: Page) {
  const root = page.locator('app-knowledge-capture');
  const input = root.getByPlaceholder(
    /Ecrire ou parler|Écrire ou parler|Saisir ou corriger la réponse expert avant évaluation/i,
  );
  const section = input.locator('xpath=ancestor::section[1]');
  return {
    section,
    input,
    submit: section.getByRole('button', { name: /^Envoyer$/i }),
  };
}

function focusedCapturePin(page: Page, name: RegExp) {
  return captureExpressionComposer(page).section.getByRole('button', { name }).locator('..');
}

function emptyOperations() {
  return {
    stale_after_hours: 24,
    poll_interval_seconds: 5,
    active_uploads: [],
    stale_partials: [],
    storage_summary: {
      active_count: 0,
      idle_count: 0,
      stale_count: 0,
      temporary_count: 0,
      temporary_size_bytes: 0,
      unattributed_partial_count: 0,
      unattributed_partial_size_bytes: 0,
      last_received_at: null,
      last_received_filename: null,
      link_count: 1,
      deposit_counts: {},
    },
    reconciliation_summary: {
      mode: 'dry_run',
      status: 'clean',
      stale_after_hours: 24,
      stale_partials: 0,
      orphan_files: 0,
      missing_db_files: 0,
      pending_rows: 0,
      unattributed_partials: 0,
      stale_partial_bytes: 0,
      orphan_file_bytes: 0,
      generated_at: '2026-06-23T00:00:00Z',
      confirm_from_job_id: null,
    },
    last_jobs: [],
  };
}

function syntheticSftpOperations() {
  return {
    stale_after_hours: 24,
    poll_interval_seconds: 5,
    active_uploads: [
      {
        id: 'upload-andritz-live-1',
        temp_name: 'andritz-live-upload.tmp',
        filename: '1-NON-WOVENS/FRANCE/andritz-live-upload.pdf',
        access_id: 'andritz-qa',
        link_id: 'link-andritz-qa',
        link_label: 'Andritz QA external upload',
        workspace_id: workspace.id,
        size_bytes: 4_096,
        max_bytes: 262_144_000,
        created_at: '2026-06-23T00:30:00Z',
        modified_at: '2026-06-23T00:30:04Z',
        age_seconds: 34,
        idle_seconds: 2,
        status: 'receiving',
        attributed: true,
        actionable: false,
      },
    ],
    stale_partials: [],
    storage_summary: {
      active_count: 1,
      idle_count: 0,
      stale_count: 1,
      temporary_count: 2,
      temporary_size_bytes: 4_096,
      unattributed_partial_count: 1,
      unattributed_partial_size_bytes: 2_048,
      last_received_at: '2026-06-23T00:29:00Z',
      last_received_filename: '1-NON-WOVENS/FRANCE/andritz-last-received.pdf',
      link_count: 1,
      deposit_counts: {
        received: { count: 1, size_bytes: 128_000 },
        promoted: { count: 1, size_bytes: 64_000 },
        rejected: { count: 1, size_bytes: 512 },
      },
    },
    reconciliation_summary: {
      mode: 'dry_run',
      status: 'completed',
      stale_after_hours: 24,
      stale_partials: 1,
      orphan_files: 1,
      missing_db_files: 0,
      pending_rows: 0,
      unattributed_partials: 1,
      stale_partial_bytes: 2_048,
      orphan_file_bytes: 4_096,
      generated_at: '2026-06-23T00:31:00Z',
      confirm_from_job_id: 'job-sftp-dry-run',
    },
    last_jobs: [
      {
        id: 'job-sftp-dry-run',
        kind: 'sftp_reconciliation',
        title: 'Synthetic SFTP reconciliation dry run',
        status: 'completed',
        progress: 100,
        stage: 'dry_run',
        error: null,
        input_ref: { mode: 'dry_run' },
        result: {
          counts: { stale_partials: 1, orphan_files: 1, missing_db_files: 0, pending_rows: 0 },
          sizes: { stale_partial_bytes: 2_048, orphan_file_bytes: 4_096 },
        },
        created_at: '2026-06-23T00:31:00Z',
        updated_at: '2026-06-23T00:31:05Z',
        completed_at: '2026-06-23T00:31:05Z',
      },
    ],
  };
}

function emptySftpIndexingAssist(): MockSftpIndexingAssist {
  return {
    summary: {
      total_files: 0,
      found_files: 0,
      promote_now_count: 0,
      inspect_archive_count: 0,
      unsupported_count: 0,
      already_promoted_count: 0,
      needs_target_count: 0,
      recommended_count: 0,
      recommended_bytes: 0,
      zip_count: 0,
      missing_count: 0,
      recommended_file_ids: [],
      target_collection_slug: 'andritz-qa',
    },
    recommendations: [],
    collection: {
      slug: 'andritz-qa',
      name: 'Andritz QA',
      exists: true,
      status: 'ready',
      source_count: 2,
      document_count: 2,
      chunk_count: 12,
      zero_chunk_sources: 0,
      error_sources: 0,
      job_counts: { queued: 0, running: 0, completed: 3, failed: 0 },
      latest_job: null,
      jobs: [],
    },
  };
}

function syntheticSftpIndexingAssist(): MockSftpIndexingAssist {
  const runningJob = {
    id: 'job-sftp-indexing-running',
    kind: 'knowledge_indexing',
    title: 'Synthetic Andritz indexing',
    status: 'running',
    progress: 45,
    stage: 'Embedding synthetic SFTP files',
    error: null,
    input_ref: { source: 'secure_deposit', collection_slug: 'andritz-qa' },
    result: null,
    created_at: '2026-06-23T00:32:00Z',
    started_at: '2026-06-23T00:32:05Z',
    updated_at: '2026-06-23T00:32:20Z',
    completed_at: null,
  };
  return {
    summary: {
      total_files: 1,
      found_files: 1,
      promote_now_count: 1,
      inspect_archive_count: 0,
      unsupported_count: 0,
      already_promoted_count: 0,
      needs_target_count: 0,
      recommended_count: 1,
      recommended_bytes: 128_000,
      zip_count: 0,
      missing_count: 0,
      recommended_file_ids: ['deposit-andritz-received-1'],
      target_collection_slug: 'andritz-qa',
    },
    recommendations: [
      {
        file_id: 'deposit-andritz-received-1',
        filename: '1-NON-WOVENS/FRANCE/andritz-pump-check.pdf',
        status: 'received',
        extension: '.pdf',
        recommendation: 'promote_now',
        label: 'Promote now',
        reason: 'Synthetic supported PDF in the current SFTP queue view.',
        eligible_for_batch: true,
        size_bytes: 128_000,
        target_collection_slug: 'andritz-qa',
      },
    ],
    collection: {
      slug: 'andritz-qa',
      name: 'Andritz QA',
      exists: true,
      status: 'ready',
      source_count: 2,
      document_count: 2,
      chunk_count: 12,
      zero_chunk_sources: 0,
      error_sources: 0,
      job_counts: { queued: 0, running: 1, completed: 3, failed: 0 },
      latest_job: runningJob,
      jobs: [runningJob],
    },
  };
}

function syntheticSftpDepositFiles(): MockSftpDepositFile[] {
  return [
    {
      id: 'deposit-andritz-received-1',
      access_link_id: 'link-andritz-qa',
      filename: '1-NON-WOVENS/FRANCE/andritz-pump-check.pdf',
      content_type: 'application/pdf',
      size_bytes: 128_000,
      sha256: 'sha-received-pump-check',
      status: 'received',
      uploaded_at: '2026-06-23T00:10:00Z',
      promoted_at: null,
      worker_job_id: null,
      promotion_result: null,
    },
    {
      id: 'deposit-andritz-promoted-1',
      access_link_id: 'link-andritz-qa',
      filename: '1-NON-WOVENS/FRANCE/andritz-promoted-manual.docx',
      content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      size_bytes: 64_000,
      sha256: 'sha-promoted-manual',
      status: 'promoted',
      uploaded_at: '2026-06-23T00:12:00Z',
      promoted_at: '2026-06-23T00:20:00Z',
      promoted_collection_slug: 'andritz-qa',
      worker_job_id: 'job-promoted-manual',
      promotion_result: { indexing_status: 'completed' },
    },
    {
      id: 'deposit-andritz-rejected-1',
      access_link_id: 'link-andritz-qa',
      filename: '2-PULP/QA/andritz-rejected.tmp',
      content_type: 'application/octet-stream',
      size_bytes: 512,
      sha256: 'sha-rejected-temp',
      status: 'rejected',
      uploaded_at: '2026-06-23T00:14:00Z',
      promoted_at: null,
      worker_job_id: null,
      promotion_result: null,
      rejection_reason: 'Unsupported synthetic extension.',
    },
  ];
}

function syntheticSftpPreviewDepositFiles(): MockSftpDepositFile[] {
  return [
    ...syntheticSftpDepositFiles(),
    {
      id: 'deposit-andritz-archive-1',
      access_link_id: 'link-andritz-qa',
      filename: '1-NON-WOVENS/FRANCE/andritz-archive-bundle.zip',
      content_type: 'application/zip',
      size_bytes: 256_000,
      sha256: 'sha-archive-bundle',
      status: 'received',
      uploaded_at: '2026-06-23T00:16:00Z',
      promoted_at: null,
      worker_job_id: null,
      promotion_result: null,
    },
  ];
}

function syntheticLargeSftpDepositFiles(count = 125): MockSftpDepositFile[] {
  return Array.from({ length: count }, (_, index) => {
    const padded = String(index + 1).padStart(3, '0');
    return {
      id: `deposit-andritz-large-${padded}`,
      access_link_id: 'link-andritz-qa',
      filename: `1-NON-WOVENS/FRANCE/PAGINATION/pagination-probe-${padded}.pdf`,
      content_type: 'application/pdf',
      size_bytes: 10_000 + index,
      sha256: `sha-pagination-probe-${padded}`,
      status: 'received',
      uploaded_at: `2026-06-23T01:${String(index % 60).padStart(2, '0')}:00Z`,
      promoted_at: null,
      worker_job_id: null,
      promotion_result: null,
    };
  });
}

function acceptedCaptureSession() {
  return {
    id: 'session-andritz-qa',
    title: 'Andritz QA capture',
    objective: 'Capture synthetic Andritz QA knowledge.',
    status: 'completed',
    plan: {
      schema_version: 'free_conversation_v1',
      mode: 'free_conversation',
      topics: [],
    },
    transcript: [
      {
        id: 'turn-andritz-qa',
        speaker: 'expert',
        text: 'Synthetic Andritz QA fact for explicit publication guard.',
      },
    ],
    metrics: {},
    open_questions_count: 0,
    created_by_user_id: user.id,
    created_by_label: user.email,
    completed_at: '2026-06-23T00:00:00Z',
    last_activity: '2026-06-23T00:00:00Z',
  };
}

function acceptedCaptureProposal() {
  return {
    id: 'proposal-andritz-qa',
    status: 'accepted',
    session_id: 'session-andritz-qa',
    created_by_user_id: user.id,
    proposal: {
      title: 'Andritz QA accepted capture report',
      objective: 'Capture synthetic Andritz QA knowledge.',
      report_markdown:
        '# Fiche connaissance - Andritz QA\n\n## Synthèse de la capture\n- Synthetic Andritz QA fact for explicit publication guard.',
      captured_facts: [
        {
          id: 'fact-andritz-qa',
          text: 'Synthetic Andritz QA fact for explicit publication guard.',
          source: 'capture',
          confidence: 0.91,
        },
      ],
      plan_structure: {
        topics: [
          {
            topic_id: 'session',
            title: 'Synthèse de la capture',
            facts: [
              {
                id: 'fact-andritz-qa',
                text: 'Synthetic Andritz QA fact for explicit publication guard.',
                source: 'capture',
                confidence: 0.91,
              },
            ],
            subtopics: [],
            sources: [
              {
                title: 'Andritz QA safe document',
                filename: 'andritz-qa-safe.pdf',
                document_id: 'doc-andritz-qa',
                collection: 'andritz-qa',
                page: 2,
                preview: 'Synthetic Andritz QA source snippet.',
              },
            ],
            open_questions: [],
          },
        ],
      },
      open_questions: [],
      recommended_ingestion: {
        title: 'Andritz QA accepted capture report',
        content:
          '# Fiche connaissance - Andritz QA\n\n## Synthèse de la capture\n- Synthetic Andritz QA fact for explicit publication guard.',
        metadata: { publication_category: 'technical' },
      },
      publication: {
        category: 'technical',
        destination: 'andritz-qa',
        destination_scope: 'andritz-qa',
        final_title: 'Andritz QA accepted capture report',
        include_unresolved_questions: true,
        suggested: true,
      },
      audit: { event_count: 1, amendment_count: 0 },
    },
  };
}

function createdFreeConversationSession(title = 'Andritz QA free conversation smoke', status = 'draft') {
  return {
    id: 'session-andritz-free-smoke',
    title,
    objective: 'Capture synthetic Andritz QA knowledge.',
    status,
    plan: {
      schema_version: 'free_conversation_v1',
      mode: 'free_conversation',
      topics: [],
      questions: [],
    },
    transcript: [],
    metrics: {},
    open_questions_count: 0,
    created_by_user_id: user.id,
    created_by_label: user.email,
    last_activity: '2026-06-23T00:00:00Z',
  };
}

function createdPlannedCaptureSession(title = 'Andritz QA guided plan smoke', status = 'planned') {
  return {
    id: 'session-andritz-free-smoke',
    title,
    objective: 'Capture synthetic Andritz QA knowledge with a guided plan.',
    status,
    plan: {
      schema_version: 'plan_build_v2',
      mode: 'plan_build',
      question_bank_status: 'ready',
      dialogue: { turns: [], ready_to_finalize: true, status: 'ready' },
      review: { status: 'topics_validated', revision: 1 },
      topics: [
        {
          id: 'topic-maintenance',
          title: 'Maintenance Andritz',
          objective: 'Structurer les constats de maintenance Andritz.',
          subtopics: [
            {
              id: 'subtopic-alignment',
              title: 'Alignement convoyeur',
              objective: 'Capturer les repères terrain sur l alignement du convoyeur.',
              questions: [
                {
                  id: 'q-alignment',
                  question: 'Quels repères confirment l alignement du convoyeur Andritz ?',
                  topic_id: 'topic-maintenance',
                  subtopic_id: 'subtopic-alignment',
                  path_label: 'Maintenance Andritz › Alignement convoyeur',
                  estimated_minutes: 3,
                },
              ],
            },
            {
              id: 'subtopic-safety-stop',
              title: 'Sécurité arrêt machine',
              objective: 'Capturer les conditions de sécurité avant arrêt machine.',
              questions: [
                {
                  id: 'q-safety-stop',
                  question: 'Quelles sécurités doivent être vérifiées avant l arrêt machine ?',
                  topic_id: 'topic-maintenance',
                  subtopic_id: 'subtopic-safety-stop',
                  path_label: 'Maintenance Andritz › Sécurité arrêt machine',
                  estimated_minutes: 4,
                },
              ],
            },
          ],
        },
      ],
    },
    transcript:
      status === 'active'
        ? [
            {
              id: 'turn-guided-plan-note',
              speaker: 'expert',
              text: 'Synthetic guided plan note.',
              input_modality: 'text',
              topic_id: 'topic-maintenance',
              subtopic_id: 'subtopic-alignment',
            },
          ]
        : [],
    metrics:
      status === 'active'
        ? {
            active_topic_id: 'topic-maintenance',
            active_subtopic_id: 'subtopic-alignment',
          }
        : {},
    open_questions_count: 0,
    created_by_user_id: user.id,
    created_by_label: user.email,
    started_at: status === 'active' ? '2026-06-23T00:00:00Z' : null,
    last_activity: '2026-06-23T00:00:00Z',
  };
}

async function installAndritzMocks(
  page: Page,
  options: {
    roleTemplate?: MockRoleTemplate;
    secureDepositEnabled?: boolean;
    chatDocumentUploadEnabled?: boolean;
    collectionsShouldFail?: boolean;
    collectionCreateRequests?: string[];
    collectionCreateShouldFail?: boolean;
    collectionDeleteRequests?: string[];
    collectionDeleteShouldFail?: boolean;
    documentListShouldFail?: boolean;
    documentListEmpty?: boolean;
    documentListRequests?: string[];
    documentDeleteRequests?: string[];
    documentDeleteShouldFail?: boolean;
    collectionPreviewRequests?: string[];
    collectionPreviewUnsafeContent?: boolean;
    collectionPreviewForbidden?: boolean;
    collectionPreviewForbiddenAfterFirstSuccess?: boolean;
    searchShouldFail?: boolean;
    chatUploadShouldFail?: boolean;
    chatUploadFailureDetail?: string;
    chatUploadFailureStatus?: number;
    chatUploadDelayMs?: number;
    chatUploadPartialFailure?: boolean;
    chatUploadTwoSuccess?: boolean;
    chatMetadataShouldFail?: boolean;
    chatMetadataLongKeywords?: boolean;
    acceptedProposal?: boolean;
    activeCaptureSession?: boolean;
    capturePlanRequests?: unknown[];
    capturePlanShouldFail?: boolean;
    capturePlanFailureStatus?: number;
    capturePlanFailureDetail?: string;
    planSourceExtractRequests?: string[];
    planSourceExtractShouldFail?: boolean;
    planSourceExtractFailureStatus?: number;
    planSourceExtractFailureDetail?: string;
    planSourceExtractText?: string;
    capturePlanDialogueRequests?: unknown[];
    capturePlanDialogueShouldFail?: boolean;
    capturePlanDialogueFailureStatus?: number;
    capturePlanDialogueFailureDetail?: string;
    capturePlanTopicsRequests?: unknown[];
    capturePlanValidationRequests?: string[];
    captureStartRequests?: string[];
    capturePlannedSession?: boolean;
    chatStreamRequests?: unknown[];
    chatStreamDelayMs?: number;
    chatStreamAbort?: boolean;
    chatStreamAbortDelayMs?: number;
    chatStreamDeepQueued?: boolean;
    chatSessionCreateRequests?: unknown[];
    auditRequests?: unknown[];
    auditShouldFail?: boolean;
    workspaceJobRequests?: string[];
    chatUploadRequests?: string[];
    sourcePreviewRequests?: string[];
    sourcePreviewShouldFail?: boolean;
    sourcePreviewForbidden?: boolean;
    captureSessionStartsActive?: boolean;
    captureDocumentUploadRequests?: string[];
    captureDocumentUploadShouldFail?: boolean;
    captureDocumentUploadFailureDetail?: string;
    captureDocumentUploadFailureStatus?: number;
    captureDocumentUploadTwoSuccess?: boolean;
    captureDocumentViewShouldFail?: boolean;
    captureDocumentViewRequests?: unknown[];
    captureTurnRequests?: unknown[];
    captureClosureRequests?: unknown[];
    captureClosureShouldFail?: boolean;
    captureClosureNoProposal?: boolean;
    captureDeleteRequests?: string[];
    captureDocumentPreviewRequests?: string[];
    captureDocumentPreviewShouldFail?: boolean;
    captureHintQueueRequests?: string[];
    captureHintQueueShouldFail?: boolean;
    captureHintQueueFailureStatus?: number;
    captureHintQueueFailureDetail?: string;
    contextCreateRequests?: unknown[];
    contextCreateShouldFail?: boolean;
    contextUpdateRequests?: unknown[];
    contextUpdateShouldFail?: boolean;
    contextPersistRequests?: unknown[];
    contextPersistShouldFail?: boolean;
    contextPersistFailureStatus?: number;
    contextPersistFailureDetail?: string;
    chatSystems?: MockChatSystem[];
    chatSystemsRequests?: string[];
    chatSystemsShouldFail?: boolean;
    chatSystemsFailureStatus?: number;
    chatSystemsFailureDetail?: string;
    documentFacts?: MockDocumentFact[];
    documentFactRequests?: string[];
    knowledgeScopes?: MockKnowledgeScope[];
    knowledgeCollectionItems?: MockKnowledgeCollectionItem[];
    sftpLinks?: MockSftpDepositLink[];
    sftpDepositFiles?: MockSftpDepositFile[];
    sftpOperations?: unknown;
    sftpOperationsRequests?: string[];
    sftpOperationsShouldFail?: boolean;
    sftpOperationsFailureStatus?: number;
    sftpOperationsFailureDetail?: string;
    sftpIndexingAssist?: MockSftpIndexingAssist;
    sftpIndexingAssistRequests?: unknown[];
    sftpOperationsReconcileRequests?: unknown[];
    sftpPromoteRequests?: unknown[];
    sftpBulkPromoteRequests?: unknown[];
    sftpArchiveDownloadRequests?: string[];
    sftpPreviewRequests?: string[];
    sftpArchiveBrowseRequests?: string[];
    sftpArchiveMemberPreviewRequests?: string[];
    sftpFileDownloadRequests?: string[];
    sftpFileDownloadFailureDetail?: string;
    sftpFileDownloadFailureStatus?: number;
    sftpArchiveMemberDownloadRequests?: string[];
    sftpLinkMutationRequests?: Array<{ path: string; body?: unknown }>;
    sftpLinkMutationShouldFail?: boolean;
    sftpJobsRequests?: string[];
    sftpJobsShouldFail?: boolean;
    sftpOperationsReconcileResponse?: unknown;
    sftpOperationsReconcileFailureStatus?: number;
    sftpOperationsReconcileFailureDetail?: string;
  } = {},
) {
  const roleTemplate = options.roleTemplate ?? 'workspace_admin';
  const secureDepositEnabled = options.secureDepositEnabled ?? true;
  const chatDocumentUploadEnabled = options.chatDocumentUploadEnabled ?? true;
  const collectionsShouldFail = options.collectionsShouldFail ?? false;
  const collectionCreateRequests = options.collectionCreateRequests;
  const collectionCreateShouldFail = options.collectionCreateShouldFail ?? false;
  const collectionDeleteRequests = options.collectionDeleteRequests;
  const collectionDeleteShouldFail = options.collectionDeleteShouldFail ?? false;
  const documentListShouldFail = options.documentListShouldFail ?? false;
  const documentListEmpty = options.documentListEmpty ?? false;
  const documentListRequests = options.documentListRequests;
  const documentDeleteRequests = options.documentDeleteRequests;
  const documentDeleteShouldFail = options.documentDeleteShouldFail ?? false;
  const collectionPreviewRequests = options.collectionPreviewRequests;
  const collectionPreviewUnsafeContent = options.collectionPreviewUnsafeContent ?? false;
  const collectionPreviewForbidden = options.collectionPreviewForbidden ?? false;
  const collectionPreviewForbiddenAfterFirstSuccess = options.collectionPreviewForbiddenAfterFirstSuccess ?? false;
  const searchShouldFail = options.searchShouldFail ?? false;
  const chatUploadShouldFail = options.chatUploadShouldFail ?? false;
  const chatUploadFailureDetail = options.chatUploadFailureDetail ?? 'Mocked upload failure';
  const chatUploadFailureStatus = options.chatUploadFailureStatus ?? 500;
  const chatUploadDelayMs = options.chatUploadDelayMs ?? 0;
  const chatUploadPartialFailure = options.chatUploadPartialFailure ?? false;
  const chatUploadTwoSuccess = options.chatUploadTwoSuccess ?? false;
  const chatMetadataShouldFail = options.chatMetadataShouldFail ?? false;
  const chatMetadataLongKeywords = options.chatMetadataLongKeywords ?? false;
  const includeAcceptedProposal = options.acceptedProposal ?? false;
  const includeActiveCaptureSession = options.activeCaptureSession ?? false;
  const capturePlanRequests = options.capturePlanRequests;
  const capturePlanShouldFail = options.capturePlanShouldFail ?? false;
  const capturePlanFailureStatus = options.capturePlanFailureStatus ?? 500;
  const capturePlanFailureDetail = options.capturePlanFailureDetail ?? 'Mocked capture plan creation failed';
  const planSourceExtractRequests = options.planSourceExtractRequests;
  const planSourceExtractShouldFail = options.planSourceExtractShouldFail ?? false;
  const planSourceExtractFailureStatus = options.planSourceExtractFailureStatus ?? 400;
  const planSourceExtractFailureDetail =
    options.planSourceExtractFailureDetail ?? 'Format de fichier non supporté pour une source de plan.';
  const planSourceExtractText =
    options.planSourceExtractText ??
    ['# Inspection machine Andritz', '## Sécurité inspection', '- Vérifier arrêt machine'].join('\n');
  const capturePlanDialogueRequests = options.capturePlanDialogueRequests;
  const capturePlanDialogueShouldFail = options.capturePlanDialogueShouldFail ?? false;
  const capturePlanDialogueFailureStatus = options.capturePlanDialogueFailureStatus ?? 504;
  const capturePlanDialogueFailureDetail = options.capturePlanDialogueFailureDetail ?? 'Plan oracle timeout';
  const capturePlanTopicsRequests = options.capturePlanTopicsRequests;
  const capturePlanValidationRequests = options.capturePlanValidationRequests;
  const captureStartRequests = options.captureStartRequests;
  const capturePlannedSession = options.capturePlannedSession ?? false;
  const chatStreamRequests = options.chatStreamRequests;
  const chatStreamDelayMs = options.chatStreamDelayMs ?? 0;
  const chatStreamAbort = options.chatStreamAbort ?? false;
  const chatStreamAbortDelayMs = options.chatStreamAbortDelayMs ?? 0;
  const chatStreamDeepQueued = options.chatStreamDeepQueued ?? false;
  const chatSessionCreateRequests = options.chatSessionCreateRequests;
  const auditRequests = options.auditRequests;
  const auditShouldFail = options.auditShouldFail ?? false;
  const workspaceJobRequests = options.workspaceJobRequests;
  const chatUploadRequests = options.chatUploadRequests;
  const sourcePreviewRequests = options.sourcePreviewRequests;
  const sourcePreviewShouldFail = options.sourcePreviewShouldFail ?? false;
  const sourcePreviewForbidden = options.sourcePreviewForbidden ?? false;
  const captureSessionStartsActive = options.captureSessionStartsActive ?? false;
  const captureDocumentUploadRequests = options.captureDocumentUploadRequests;
  const captureDocumentUploadShouldFail = options.captureDocumentUploadShouldFail ?? false;
  const captureDocumentUploadFailureDetail =
    options.captureDocumentUploadFailureDetail ?? 'Chargement document impossible pour cette capture.';
  const captureDocumentUploadFailureStatus = options.captureDocumentUploadFailureStatus ?? 500;
  const captureDocumentUploadTwoSuccess = options.captureDocumentUploadTwoSuccess ?? false;
  const captureDocumentViewShouldFail = options.captureDocumentViewShouldFail ?? false;
  const captureDocumentViewRequests = options.captureDocumentViewRequests;
  const captureTurnRequests = options.captureTurnRequests;
  const captureClosureRequests = options.captureClosureRequests;
  const captureClosureShouldFail = options.captureClosureShouldFail ?? false;
  const captureClosureNoProposal = options.captureClosureNoProposal ?? false;
  const captureDeleteRequests = options.captureDeleteRequests;
  const captureDocumentPreviewRequests = options.captureDocumentPreviewRequests;
  const captureDocumentPreviewShouldFail = options.captureDocumentPreviewShouldFail ?? false;
  const captureHintQueueRequests = options.captureHintQueueRequests;
  const captureHintQueueShouldFail = options.captureHintQueueShouldFail ?? false;
  const captureHintQueueFailureStatus = options.captureHintQueueFailureStatus ?? 503;
  const captureHintQueueFailureDetail = options.captureHintQueueFailureDetail ?? 'Mocked hint queue unavailable';
  const contextCreateRequests = options.contextCreateRequests;
  const contextCreateShouldFail = options.contextCreateShouldFail ?? false;
  const contextUpdateRequests = options.contextUpdateRequests;
  const contextUpdateShouldFail = options.contextUpdateShouldFail ?? false;
  const contextPersistRequests = options.contextPersistRequests;
  const contextPersistShouldFail = options.contextPersistShouldFail ?? false;
  const contextPersistFailureStatus = options.contextPersistFailureStatus ?? 403;
  const contextPersistFailureDetail = options.contextPersistFailureDetail ?? 'Persist permission denied';
  const chatSystems = options.chatSystems ?? [];
  const chatSystemsRequests = options.chatSystemsRequests;
  const chatSystemsShouldFail = options.chatSystemsShouldFail ?? false;
  const chatSystemsFailureStatus = options.chatSystemsFailureStatus ?? 403;
  const chatSystemsFailureDetail = options.chatSystemsFailureDetail ?? 'Mocked system catalogue permission denied';
  const documentFacts = options.documentFacts ?? [];
  const documentFactRequests = options.documentFactRequests;
  const knowledgeCollectionItems = options.knowledgeCollectionItems ?? [];
  const sftpDepositFiles = options.sftpDepositFiles ?? [];
  const sftpOperations = options.sftpOperations ?? emptyOperations();
  const sftpOperationsRequests = options.sftpOperationsRequests;
  const sftpOperationsShouldFail = options.sftpOperationsShouldFail ?? false;
  const sftpOperationsFailureStatus = options.sftpOperationsFailureStatus ?? 500;
  const sftpOperationsFailureDetail = options.sftpOperationsFailureDetail ?? 'Mocked SFTP operations unavailable';
  const sftpIndexingAssist = options.sftpIndexingAssist;
  const sftpIndexingAssistRequests = options.sftpIndexingAssistRequests;
  const sftpOperationsReconcileRequests = options.sftpOperationsReconcileRequests;
  const sftpPromoteRequests = options.sftpPromoteRequests;
  const sftpBulkPromoteRequests = options.sftpBulkPromoteRequests;
  const sftpArchiveDownloadRequests = options.sftpArchiveDownloadRequests;
  const sftpPreviewRequests = options.sftpPreviewRequests;
  const sftpArchiveBrowseRequests = options.sftpArchiveBrowseRequests;
  const sftpArchiveMemberPreviewRequests = options.sftpArchiveMemberPreviewRequests;
  const sftpFileDownloadRequests = options.sftpFileDownloadRequests;
  const sftpFileDownloadFailureDetail =
    options.sftpFileDownloadFailureDetail ?? 'Mocked file download should not be called in this smoke';
  const sftpFileDownloadFailureStatus = options.sftpFileDownloadFailureStatus ?? 500;
  const sftpArchiveMemberDownloadRequests = options.sftpArchiveMemberDownloadRequests;
  const sftpLinkMutationRequests = options.sftpLinkMutationRequests;
  const sftpLinkMutationShouldFail = options.sftpLinkMutationShouldFail ?? false;
  const sftpJobsRequests = options.sftpJobsRequests;
  const sftpJobsShouldFail = options.sftpJobsShouldFail ?? false;
  const sftpOperationsReconcileResponse = options.sftpOperationsReconcileResponse;
  const sftpOperationsReconcileFailureStatus = options.sftpOperationsReconcileFailureStatus ?? 500;
  const sftpOperationsReconcileFailureDetail =
    options.sftpOperationsReconcileFailureDetail ?? 'Mocked reconciliation mutation should not be called in this smoke';
  let collectionDeleted = false;
  const createdCollections: string[] = [];
  let collectionPreviewRequestCount = 0;
  const legacyRole = roleTemplate === 'workspace_reviewer' ? 'member' : 'admin';
  const activeWorkspace = {
    ...workspace,
    role: legacyRole,
    role_template: roleTemplate,
    settings: {
      ...workspace.settings,
      connectors: {
        ...(workspace.settings.connectors || {}),
        secure_deposit: { enabled: secureDepositEnabled },
        sftp: { enabled: secureDepositEnabled },
      },
      features: {
        chat_document_upload: chatDocumentUploadEnabled,
      },
      ...(options.knowledgeScopes ? { knowledge_scopes: options.knowledgeScopes } : {}),
    },
  };
  const activeUser = {
    ...user,
    role: legacyRole,
    email: roleTemplate === 'workspace_reviewer' ? 'reviewer.andritz.qa@example.test' : user.email,
    workspaces: [
      {
        id: workspace.id,
        name: workspace.name,
        slug: workspace.slug,
        role: legacyRole,
        role_template: roleTemplate,
      },
    ],
  };
  const sftpLinks = options.sftpLinks ?? [defaultSftpDepositLink(activeUser)];
  let currentCaptureSessionTitle = 'Andritz QA free conversation smoke';

  await page.addInitScript(() => {
    localStorage.setItem('agentium_token', 'Bearer mocked-andritz-token');
    localStorage.setItem('agentium_workspace_slug', 'andritz');
  });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = request.method();

    if (path === '/auth/validate' && method === 'POST') {
      return json(route, { valid: true, user_id: activeUser.id, email: activeUser.email, role: activeUser.role });
    }
    if (path === '/auth/workspaces') {
      return json(route, [activeWorkspace]);
    }
    if (path === '/auth/me') {
      return json(route, activeUser);
    }
    if (path === '/iam/matrix') {
      return json(route, {
        workspace: { id: activeWorkspace.id, slug: activeWorkspace.slug, name: activeWorkspace.name },
        subject_user_id: activeUser.id,
        role_template: roleTemplate,
        custom_labels: [],
        role_flags: { require_second_eye_for_ingestion: false },
        enforcement: true,
        permissions: [
          { resource_kind: 'capture_session', action: 'create', roles: [roleTemplate], conditions: [], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'capture_session', action: 'read', roles: [roleTemplate], conditions: [], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'capture_session', action: 'update', roles: [roleTemplate], conditions: ['owner_match'], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'capture_session', action: 'execute', roles: [roleTemplate], conditions: ['owner_match'], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'knowledge_proposal', action: 'review_decide', roles: [roleTemplate], conditions: [], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'knowledge_proposal', action: 'trigger_ingestion', roles: [roleTemplate], conditions: ['second_eye_ingestion'], policy_id: 'qa', allowed_for_subject: true },
        ],
      });
    }

    if (path === '/contexts' && method === 'GET') {
      return json(route, { contexts: [] });
    }
    if (path === '/contexts' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      contextCreateRequests?.push(body);
      if (contextCreateShouldFail) {
        return json(route, { detail: 'Mocked context create failure' }, 500);
      }
      return json(route, {
        id: 'ctx-chat-drop-and-ask',
        name: body['name'] || 'Drop-and-ask · synthetic',
        data_refs: body['data_refs'] || [],
        environment_state: body['environment_state'] || {},
        business_constraints: body['business_constraints'] || {},
        ephemeral: true,
        ttl_hours: 24,
      });
    }
    if (path === '/contexts/ctx-chat-drop-and-ask/persist' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      contextPersistRequests?.push(body);
      if (contextPersistShouldFail) {
        return json(route, { detail: contextPersistFailureDetail }, contextPersistFailureStatus);
      }
      return json(route, {
        id: 'ctx-chat-drop-and-ask',
        name: 'Drop-and-ask · synthetic',
        data_refs: ['andritz-chat-drop.txt'],
        environment_state: { collection: 'documents' },
        business_constraints: { source: 'drop_and_ask' },
        ephemeral: false,
        ttl_hours: null,
      });
    }
    if (path === '/contexts/ctx-chat-drop-and-ask' && method === 'PATCH') {
      const body = request.postDataJSON() as Record<string, unknown>;
      contextUpdateRequests?.push(body);
      if (contextUpdateShouldFail) {
        return json(route, { detail: 'Mocked context update failure' }, 500);
      }
      return json(route, {
        id: 'ctx-chat-drop-and-ask',
        name: 'Drop-and-ask · synthetic',
        data_refs: body['data_refs'] || [],
        environment_state: body['environment_state'] || {},
        business_constraints: body['business_constraints'] || {},
        ephemeral: true,
      });
    }
    if (path === '/systems') {
      chatSystemsRequests?.push(url.search);
      if (chatSystemsShouldFail) {
        return json(route, { detail: chatSystemsFailureDetail }, chatSystemsFailureStatus);
      }
      return json(route, { systems: chatSystems });
    }

    if (path === '/documents/collections' && method === 'GET') {
      if (collectionsShouldFail) {
        return json(route, { detail: 'Collections service unavailable' }, 500);
      }
      const baseCollections = collectionDeleted ? [] : ['andritz-qa'];
      const collectionNames = Array.from(new Set([
        ...baseCollections,
        ...knowledgeCollectionItems.map((item) => item.slug).filter(Boolean),
        ...createdCollections,
      ]));
      const baseItems: MockKnowledgeCollectionItem[] = !collectionDeleted
        ? [{
            slug: 'andritz-qa',
            name: 'Andritz QA',
            document_count: 2,
            chunk_count: 12,
            updated_at: '2026-06-23T00:00:00Z',
            status: 'ready',
          }]
        : [];
      return json(route, {
        collections: collectionNames,
        default: collectionNames[0] ?? null,
        items: [
          ...baseItems,
          ...knowledgeCollectionItems.filter((item) => item.slug !== 'andritz-qa'),
          ...createdCollections.map((name) => ({
            slug: name,
            name,
            document_count: 0,
            chunk_count: 0,
            updated_at: '2026-06-23T00:00:00Z',
            status: 'ready',
          })),
        ],
      });
    }
    if (path === '/documents/collections' && method === 'POST') {
      collectionCreateRequests?.push(url.search);
      if (collectionCreateShouldFail) {
        return json(route, { detail: 'Mocked collection create permission denied' }, 403);
      }
      const name = url.searchParams.get('collection_name') || 'untitled';
      if (!createdCollections.includes(name)) {
        createdCollections.push(name);
      }
      return json(route, { status: 'created', collection_name: name });
    }
    if (path === '/documents/collections/andritz-qa' && method === 'DELETE') {
      collectionDeleteRequests?.push(path);
      if (collectionDeleteShouldFail) {
        return json(route, { detail: 'Mocked collection delete permission denied' }, 403);
      }
      collectionDeleted = true;
      return json(route, { status: 'deleted', collection_name: 'andritz-qa' });
    }
    if (path === '/documents/list') {
      documentListRequests?.push(url.search);
      if (documentListShouldFail) {
        return json(route, { detail: 'Document inventory unavailable' }, 500);
      }
      if (documentListEmpty) {
        return json(route, {
          documents: [],
          total: 0,
          offset: 0,
          limit: 100,
          has_more: false,
        });
      }
      return json(route, {
        documents: [
          {
            document_id: 'doc-andritz-qa',
            filename: 'andritz-qa-safe.pdf',
            chunk_count: 3,
            mime_type: 'application/pdf',
          },
        ],
        total: 1,
        offset: 0,
        limit: 100,
        has_more: false,
      });
    }
    if (path === '/documents/document-facts' && method === 'GET') {
      documentFactRequests?.push(url.search);
      const semanticType = url.searchParams.get('semantic_type');
      const query = (url.searchParams.get('q') || '').trim().toLowerCase();
      const offset = Math.max(0, Number(url.searchParams.get('offset') || 0) || 0);
      const limit = Math.max(1, Number(url.searchParams.get('limit') || 100) || 100);
      const filtered = documentFacts.filter((fact) => {
        if (semanticType && fact.semantic_type !== semanticType) return false;
        if (!query) return true;
        return [
          fact.content,
          fact.value_raw,
          fact.document_filename,
          fact.section_path,
          fact.semantic_type,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(query);
      });
      const byType = filtered.reduce<Record<string, number>>((acc, fact) => {
        const type = fact.semantic_type || 'unknown';
        acc[type] = (acc[type] || 0) + 1;
        return acc;
      }, {});
      return json(route, {
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        total_returned: filtered.length,
        offset,
        limit,
        has_more: offset + limit < filtered.length,
        by_type: byType,
      });
    }
    if (path === '/documents/search') {
      if (searchShouldFail) {
        return json(route, { detail: 'Search service unavailable' }, 500);
      }
      return json(route, {
        results: [
          {
            score: 0.91,
            content: 'Synthetic Andritz QA result',
            metadata: { filename: 'andritz-qa-safe.pdf', document_id: 'doc-andritz-qa' },
          },
        ],
      });
    }
    if (path === '/documents/preview/doc-andritz-qa') {
      collectionPreviewRequests?.push(url.search);
      collectionPreviewRequestCount += 1;
      if (collectionPreviewForbidden || (collectionPreviewForbiddenAfterFirstSuccess && collectionPreviewRequestCount > 1)) {
        return json(route, { detail: 'Mocked collection preview permission denied' }, 403);
      }
      if (collectionPreviewUnsafeContent) {
        return json(route, {
          content_type: 'text/html',
          content:
            '<h1>Unsafe Andritz preview</h1><script>window.__andritzPreviewXss = true</script><img src=x onerror="window.__andritzPreviewXss = true">',
        });
      }
      return json(route, {
        content_type: 'application/pdf',
        download_url: '/api/v1/documents/doc-andritz-qa/download?collection_name=andritz-qa',
      });
    }
    if (path === '/documents/doc-andritz-qa' && method === 'DELETE') {
      documentDeleteRequests?.push(url.search);
      if (documentDeleteShouldFail) {
        return json(route, { detail: 'Mocked document delete permission denied' }, 403);
      }
      return json(route, { status: 'deleted', document_id: 'doc-andritz-qa' });
    }
    if (path === '/documents/upload-batch' && method === 'POST') {
      const uploadBody = request.postData() || '';
      chatUploadRequests?.push(uploadBody);
      if (chatUploadDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, chatUploadDelayMs));
      }
      if (chatUploadShouldFail) {
        return json(route, { detail: chatUploadFailureDetail }, chatUploadFailureStatus);
      }
      if (uploadBody.includes('andritz-chat-return.txt')) {
        return json(route, {
          total: 1,
          successful: 1,
          failed: 0,
          documents: [
            {
              document_id: 'doc-chat-drop-return',
              filename: 'andritz-chat-return.txt',
              status: 'success',
              chunks_processed: 1,
            },
          ],
        });
      }
      if (uploadBody.includes('andritz-chat-drop.pdf')) {
        return json(route, {
          total: 1,
          successful: 1,
          failed: 0,
          documents: [
            {
              document_id: 'doc-chat-drop-pdf',
              filename: 'andritz-chat-drop.pdf',
              status: 'success',
              chunks_processed: 2,
            },
          ],
        });
      }
      if (uploadBody.includes('andritz-chat-large.xlsx')) {
        return json(route, {
          total: 1,
          successful: 1,
          failed: 0,
          documents: [
            {
              document_id: 'doc-chat-large-xlsx',
              filename: 'andritz-chat-large.xlsx',
              status: 'success',
              chunks_processed: 24,
            },
          ],
        });
      }
      if (chatUploadPartialFailure) {
        return json(route, {
          total: 2,
          successful: 1,
          failed: 1,
          documents: [
            {
              document_id: 'doc-chat-drop-and-ask',
              filename: 'andritz-chat-drop.txt',
              status: 'success',
              chunks_processed: 1,
            },
            {
              document_id: null,
              filename: 'andritz-chat-drop-rejected.txt',
              status: 'failed',
              chunks_processed: 0,
            },
          ],
        });
      }
      if (chatUploadTwoSuccess) {
        return json(route, {
          total: 2,
          successful: 2,
          failed: 0,
          documents: [
            {
              document_id: 'doc-chat-drop-and-ask',
              filename: 'andritz-chat-drop.txt',
              status: 'success',
              chunks_processed: 1,
            },
            {
              document_id: 'doc-chat-drop-extra',
              filename: 'andritz-chat-extra.txt',
              status: 'success',
              chunks_processed: 1,
            },
          ],
        });
      }
      return json(route, {
        total: 1,
        successful: 1,
        failed: 0,
        documents: [
          {
            document_id: 'doc-chat-drop-and-ask',
            filename: 'andritz-chat-drop.txt',
            status: 'success',
            chunks_processed: 1,
          },
        ],
      });
    }
    if (path === '/documents/doc-chat-drop-and-ask/metadata') {
      if (chatMetadataShouldFail) {
        return json(route, { detail: 'Mocked metadata failure' }, 404);
      }
      if (chatMetadataLongKeywords) {
        return json(route, {
          document_id: 'doc-chat-drop-and-ask',
          metadata: {
            document_title: 'Andritz chat keyword stress note',
            document_filename: 'andritz-chat-drop.txt',
            document_num_pages: 12,
            document_token_count: 18420,
            chunks_count: 9,
            document_extracted_keywords: [
              'screening',
              'filtration',
              'centrifuge',
              'maintenance',
              'operator-training',
              'safety-procedure',
              'spare-parts',
              'commissioning',
            ],
          },
        });
      }
      return json(route, {
        document_id: 'doc-chat-drop-and-ask',
        metadata: {
          document_title: 'Andritz chat drop note',
          document_filename: 'andritz-chat-drop.txt',
          document_num_pages: 1,
          document_token_count: 42,
          chunks_count: 1,
          document_extracted_keywords: ['andritz', 'qa', 'drop-and-ask'],
        },
      });
    }
    if (path === '/documents/doc-chat-drop-pdf/metadata') {
      return json(route, {
        document_id: 'doc-chat-drop-pdf',
        metadata: {
          document_title: 'Andritz chat PDF note',
          document_filename: 'andritz-chat-drop.pdf',
          document_num_pages: 3,
          document_token_count: 128,
          chunks_count: 2,
          document_extracted_keywords: ['andritz', 'pdf', 'drop-and-ask'],
        },
      });
    }
    if (path === '/documents/doc-chat-large-xlsx/metadata') {
      return json(route, {
        document_id: 'doc-chat-large-xlsx',
        metadata: {
          document_title: 'Andritz chat large workbook',
          document_filename: 'andritz-chat-large.xlsx',
          document_num_pages: 18,
          document_token_count: 24576,
          chunks_count: 24,
          document_extracted_keywords: ['andritz', 'xlsx', 'boundary', 'drop-and-ask'],
        },
      });
    }
    if (path === '/documents/doc-chat-drop-extra/metadata') {
      return json(route, {
        document_id: 'doc-chat-drop-extra',
        metadata: {
          document_title: 'Andritz chat extra note',
          document_filename: 'andritz-chat-extra.txt',
          document_num_pages: 2,
          document_token_count: 64,
          chunks_count: 1,
          document_extracted_keywords: ['andritz', 'qa', 'extra'],
        },
      });
    }
    if (path === '/documents/doc-chat-drop-return/metadata') {
      return json(route, {
        document_id: 'doc-chat-drop-return',
        metadata: {
          document_title: 'Andritz chat return note',
          document_filename: 'andritz-chat-return.txt',
          document_num_pages: 1,
          document_token_count: 58,
          chunks_count: 1,
          document_extracted_keywords: ['andritz', 'qa', 'return'],
        },
      });
    }
    if (path === '/documents/doc-andritz-qa/rich-preview') {
      sourcePreviewRequests?.push(url.search);
      if (sourcePreviewShouldFail) {
        return json(route, { detail: 'Mocked source preview unavailable' }, 404);
      }
      if (sourcePreviewForbidden) {
        return json(route, { detail: 'Mocked source preview permission denied' }, 403);
      }
      return json(route, {
        kind: 'text',
        filename: 'andritz-qa-safe.pdf',
        content_type: 'text/plain',
        size_bytes: 96,
        download_url: '/api/v1/documents/doc-andritz-qa/download?collection_name=andritz-qa',
        content: [
          'Synthetic Andritz QA source preview full text.',
          'Synthetic Andritz QA source snippet.',
        ].join('\n'),
      });
    }

    if (path === '/knowledge-capture/plans' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      capturePlanRequests?.push(body);
      currentCaptureSessionTitle = String(body['title'] || currentCaptureSessionTitle);
      if (capturePlanShouldFail) {
        return json(route, { detail: capturePlanFailureDetail }, capturePlanFailureStatus);
      }
      return json(
        route,
        capturePlannedSession
          ? createdPlannedCaptureSession(
              currentCaptureSessionTitle,
              captureSessionStartsActive ? 'active' : 'planned',
            )
          : createdFreeConversationSession(
              currentCaptureSessionTitle,
              captureSessionStartsActive ? 'active' : 'draft',
          ),
      );
    }
    if (path === '/knowledge-capture/plan-source/extract' && method === 'POST') {
      const body = request.postData() || '';
      planSourceExtractRequests?.push(body);
      if (planSourceExtractShouldFail) {
        return json(route, { detail: planSourceExtractFailureDetail }, planSourceExtractFailureStatus);
      }
      return json(route, {
        filename: 'andritz-imported-plan.md',
        content_type: 'text/markdown',
        document_type: 'text',
        chars: planSourceExtractText.length,
        truncated: false,
        text: planSourceExtractText,
      });
    }
    if (path === '/knowledge-capture/sessions') {
      const sessions = [
        ...(includeActiveCaptureSession
          ? [
              {
                ...createdFreeConversationSession('Andritz QA active capture', 'active'),
                transcript: [
                  {
                    id: 'turn-andritz-active',
                    speaker: 'expert',
                    text: 'Synthetic active Andritz capture note.',
                    input_modality: 'text',
                  },
                ],
              },
            ]
          : []),
        ...(includeAcceptedProposal ? [acceptedCaptureSession()] : []),
      ];
      return json(route, { sessions });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/plan/topics' && method === 'PATCH') {
      capturePlanTopicsRequests?.push(request.postDataJSON());
      return json(route, createdPlannedCaptureSession(currentCaptureSessionTitle, 'planned'));
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/plan/topics' && method === 'GET') {
      const session = createdPlannedCaptureSession(currentCaptureSessionTitle, 'planned');
      return json(route, {
        topics: session.plan.topics,
        question_bank_status: session.plan.question_bank_status,
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/plan/dialogue-turn' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      capturePlanDialogueRequests?.push(body);
      if (capturePlanDialogueShouldFail) {
        return json(route, { detail: capturePlanDialogueFailureDetail }, capturePlanDialogueFailureStatus);
      }
      return json(route, {
        session: createdPlannedCaptureSession(currentCaptureSessionTitle, 'planned'),
        next_prompt: 'Quels autres points Andritz doivent être ajoutés au plan ?',
        ready_to_finalize: true,
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/plan/validate-topics' && method === 'POST') {
      capturePlanValidationRequests?.push(path);
      return json(route, createdPlannedCaptureSession(currentCaptureSessionTitle, 'planned'));
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/start' && method === 'POST') {
      captureStartRequests?.push(path);
      return json(route, createdPlannedCaptureSession(currentCaptureSessionTitle, 'active'));
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/hint-queue') {
      captureHintQueueRequests?.push(`${path}${url.search}`);
      if (captureHintQueueShouldFail) {
        return json(route, { detail: captureHintQueueFailureDetail }, captureHintQueueFailureStatus);
      }
      return json(route, { subtopic_id: url.searchParams.get('subtopic_id') || null, hints: [] });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/documents') {
      if (method === 'POST') {
        const uploadBody = request.postData() || '';
        captureDocumentUploadRequests?.push(uploadBody);
        if (captureDocumentUploadShouldFail) {
          return json(route, { detail: captureDocumentUploadFailureDetail }, captureDocumentUploadFailureStatus);
        }
        const documents = [
          {
            document_id: 'doc-capture-reference',
            filename: 'andritz-capture-reference.pdf',
            title: 'Andritz capture reference',
            status: 'ready',
            chunks_processed: 2,
            collection: 'capture-session-session-andritz-free-smoke',
            collection_name: 'capture-session-session-andritz-free-smoke',
          },
          ...(captureDocumentUploadTwoSuccess
            ? [
                {
                  document_id: 'doc-capture-photo',
                  filename: 'andritz-capture-photo.jpg',
                  title: 'Andritz capture photo',
                  status: 'ready',
                  chunks_processed: 1,
                  collection: 'capture-session-session-andritz-free-smoke',
                  collection_name: 'capture-session-session-andritz-free-smoke',
                },
              ]
            : []),
        ];
        return json(route, {
          collection: 'capture-session-session-andritz-free-smoke',
          collection_name: 'capture-session-session-andritz-free-smoke',
          documents,
          session: capturePlannedSession
            ? createdPlannedCaptureSession(currentCaptureSessionTitle, 'active')
            : createdFreeConversationSession('Andritz QA document capture smoke', 'active'),
        });
      }
      return json(route, {
        collection: 'capture-session-session-andritz-free-smoke',
        collection_name: 'capture-session-session-andritz-free-smoke',
        documents: [],
        active_view: null,
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/documents/view') {
      const body = request.postDataJSON() as Record<string, unknown>;
      captureDocumentViewRequests?.push(body);
      if (captureDocumentViewShouldFail) {
        return json(route, { detail: 'Mocked capture document view logging failure' }, 500);
      }
      return json(route, {
        active_view: body,
        session: capturePlannedSession
          ? createdPlannedCaptureSession(currentCaptureSessionTitle, 'active')
          : createdFreeConversationSession('Andritz QA document capture smoke', 'active'),
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/turns' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      captureTurnRequests?.push(body);
      const noteText = String(body['text'] || 'Synthetic written capture note.');
      const plannedQuestionId = String(body['question_id'] || '');
      const plannedSubtopicId =
        plannedQuestionId === 'q-safety-stop' ? 'subtopic-safety-stop' : 'subtopic-alignment';
      return json(route, {
        session: {
          ...(capturePlannedSession
            ? createdPlannedCaptureSession(currentCaptureSessionTitle, 'active')
            : createdFreeConversationSession(currentCaptureSessionTitle, 'active')),
          transcript: [
            {
              id: 'turn-written-capture-doc',
              speaker: 'expert',
              text: noteText,
              input_modality: 'text',
              document_refs: body['document_refs'] || [],
              visual_context: body['visual_context'] || null,
              ...(capturePlannedSession
                ? {
                    topic_id: 'topic-maintenance',
                    subtopic_id: plannedSubtopicId,
                  }
                : {}),
            },
          ],
        },
        evaluation: null,
        next_prompt: null,
        next_question_id: null,
        system_prompt_event_id: null,
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/closure' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      captureClosureRequests?.push(body);
      if (captureClosureShouldFail) {
        return json(route, { detail: 'Mocked finalization timeout' }, 504);
      }
      if (captureClosureNoProposal) {
        return json(route, {
          action: body['action'] || 'finish',
          session: createdFreeConversationSession(currentCaptureSessionTitle, 'completed'),
          closure_sheet: {
            markdown: '## Synthese\n- Aucun fait exploitable dans cette capture.',
          },
          proposal: null,
        });
      }
      return json(route, {
        action: body['action'] || 'finish',
        session: {
          ...createdFreeConversationSession(currentCaptureSessionTitle, 'completed'),
          transcript: [
            {
              id: 'turn-written-capture-doc',
              speaker: 'expert',
              text: 'Synthetic written note before finalization.',
              input_modality: 'text',
              document_refs: [],
              visual_context: null,
            },
          ],
        },
        closure_sheet: {
          markdown: '## Synthese\n- Synthetic closure material.',
        },
        proposal: acceptedCaptureProposal(),
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/events') {
      return json(route, { events: [] });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-qa' && method === 'DELETE') {
      captureDeleteRequests?.push(path);
      return json(route, { deleted: true });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/quality-backlog') {
      return json(route, { imprecisions: [], contradictions: [], open_questions: [] });
    }
    if (path === '/knowledge-capture/proposals') {
      return json(route, { proposals: includeAcceptedProposal ? [acceptedCaptureProposal()] : [] });
    }
    if (path === '/knowledge-capture/fiches') {
      return json(route, { fiches: [], total: 0, limit: 100, offset: 0, has_more: false });
    }
    if (path === '/knowledge-capture/proposals/proposal-andritz-qa/content') {
      return json(route, acceptedCaptureProposal());
    }
    if (path === '/knowledge-capture/proposals/proposal-andritz-qa/publish') {
      return json(route, {
        proposal_id: 'proposal-andritz-qa',
        status: 'published',
        collection: 'andritz-qa',
        document_id: 'doc-published-andritz-qa',
        chunks_processed: 1,
        category: 'technical',
        destination: 'andritz-qa',
        final_title: 'Andritz QA accepted capture report',
        export_urls: { download_url: '/api/v1/documents/doc-published-andritz-qa/download' },
      });
    }
    if (path === '/documents/doc-capture-reference/rich-preview') {
      captureDocumentPreviewRequests?.push(url.search);
      if (captureDocumentPreviewShouldFail) {
        return json(route, { detail: 'Mocked capture document preview unavailable' }, 404);
      }
      return json(route, {
        kind: 'text',
        filename: 'andritz-capture-reference.pdf',
        content_type: 'text/plain',
        size_bytes: 98,
        download_url:
          '/api/v1/documents/doc-capture-reference/download?collection_name=capture-session-session-andritz-free-smoke',
        content: 'Synthetic capture document page content for active visual context.',
      });
    }
    if (path === '/documents/doc-capture-photo/rich-preview') {
      captureDocumentPreviewRequests?.push(url.search);
      return json(route, {
        kind: 'text',
        filename: 'andritz-capture-photo.jpg',
        content_type: 'text/plain',
        size_bytes: 82,
        download_url:
          '/api/v1/documents/doc-capture-photo/download?collection_name=capture-session-session-andritz-free-smoke',
        content: 'Synthetic capture photo content for the second active visual context.',
      });
    }

    if (path === '/sftp/health') {
      return json(route, {
        status: secureDepositEnabled ? 'ok' : 'disabled',
        workspace: 'andritz',
        enabled: secureDepositEnabled,
        default_allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx', '.png', '.jpg'],
      });
    }
    if (path === '/sftp/links' && method === 'GET') {
      return json(route, {
        links: sftpLinks,
      });
    }
    if (path === '/sftp/links' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      sftpLinkMutationRequests?.push({ path, body });
      if (sftpLinkMutationShouldFail) {
        return json(route, { detail: 'Mocked SFTP link management permission denied' }, 403);
      }
      return json(route, {
        link: {
          id: 'link-andritz-new',
          label: body['label'] || 'External deposit',
          access_id: 'andritz-new',
          public_url: 'https://example.test/deposit/andritz-new',
          generated_password: 'temporary-secret-visible-once',
          status: 'active',
          expires_at: body['expires_at'] || null,
          max_file_size_mb: body['max_file_size_mb'] || 100,
          allowed_extensions: body['allowed_extensions'] || ['.pdf'],
          created_at: '2026-06-23T00:45:00Z',
          created_by_user_id: activeUser.id,
          created_by: activeUser.email,
        },
      });
    }
    if (/^\/sftp\/links\/[^/]+\/(rotate|revoke)$/.test(path) && method === 'POST') {
      sftpLinkMutationRequests?.push({ path, body: request.postDataJSON() });
      if (sftpLinkMutationShouldFail) {
        return json(route, { detail: 'Mocked SFTP link management permission denied' }, 403);
      }
      return json(route, {
        link: {
          id: 'link-andritz-qa',
          label: 'Andritz QA external upload',
          access_id: 'andritz-qa',
          public_url: 'https://example.test/deposit/andritz-qa',
          generated_password: path.endsWith('/rotate') ? 'rotated-secret-visible-once' : null,
          status: path.endsWith('/revoke') ? 'revoked' : 'active',
          expires_at: null,
          max_file_size_mb: 250,
          allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx'],
          created_at: '2026-06-23T00:00:00Z',
          created_by_user_id: activeUser.id,
          created_by: activeUser.email,
        },
      });
    }
    if (path === '/sftp/deposits' && method === 'GET') {
      return json(route, { files: sftpDepositFiles });
    }
    if (/^\/sftp\/deposits\/[^/]+\/promote$/.test(path) && method === 'POST') {
      sftpPromoteRequests?.push({ path, body: request.postDataJSON() });
      return json(route, { detail: 'Mocked promote should not be called in this smoke' }, 500);
    }
    if (path === '/sftp/deposits/promote-bulk' && method === 'POST') {
      sftpBulkPromoteRequests?.push(request.postDataJSON());
      return json(route, { detail: 'Mocked bulk promote should not be called in this smoke' }, 500);
    }
    if (path === '/sftp/deposits/archive' && method === 'GET') {
      sftpArchiveDownloadRequests?.push(url.search);
      return json(route, { detail: 'Mocked archive download should not be called in this smoke' }, 500);
    }
    if (/^\/sftp\/deposits\/[^/]+\/preview$/.test(path) && method === 'GET') {
      sftpPreviewRequests?.push(path);
      return json(route, {
        kind: 'text',
        filename: 'andritz-pump-check.pdf',
        content_type: 'text/plain',
        size_bytes: 128_000,
        download_url: '/api/v1/sftp/deposits/deposit-andritz-received-1/download',
        content: 'Synthetic SFTP text preview for pump check.',
      });
    }
    if (/^\/sftp\/deposits\/[^/]+\/download$/.test(path) && method === 'GET') {
      sftpFileDownloadRequests?.push(path);
      return route.fulfill({
        status: sftpFileDownloadFailureStatus,
        contentType: 'application/json',
        body: JSON.stringify({ detail: sftpFileDownloadFailureDetail }),
      });
    }
    if (/^\/sftp\/deposits\/[^/]+\/archive$/.test(path) && method === 'GET') {
      sftpArchiveBrowseRequests?.push(`${path}${url.search}`);
      return json(route, {
        file_id: 'deposit-andritz-archive-1',
        filename: '1-NON-WOVENS/FRANCE/andritz-archive-bundle.zip',
        path: url.searchParams.get('path') || '',
        truncated: false,
        max_entries: 100,
        total_files: 1,
        total_size_bytes: 2_048,
        items: [
          {
            kind: 'file',
            name: 'qa-summary.txt',
            path: 'manuals/qa-summary.txt',
            extension: '.txt',
            content_type: 'text/plain',
            size_bytes: 2_048,
            compressed_size_bytes: 1_024,
            previewable: true,
          },
        ],
      });
    }
    if (/^\/sftp\/deposits\/[^/]+\/archive\/member\/preview$/.test(path) && method === 'GET') {
      sftpArchiveMemberPreviewRequests?.push(`${path}${url.search}`);
      return json(route, {
        kind: 'text',
        filename: 'qa-summary.txt',
        content_type: 'text/plain',
        size_bytes: 2_048,
        download_url:
          '/api/v1/sftp/deposits/deposit-andritz-archive-1/archive/member/download?path=manuals%2Fqa-summary.txt',
        archive_path: 'manuals/qa-summary.txt',
        content: 'Synthetic ZIP member preview from SFTP archive.',
      });
    }
    if (/^\/sftp\/deposits\/[^/]+\/archive\/member\/download$/.test(path) && method === 'GET') {
      sftpArchiveMemberDownloadRequests?.push(`${path}${url.search}`);
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Mocked archive member download should not be called in this smoke' }),
      });
    }
    if (path === '/sftp/operations' && method === 'GET') {
      sftpOperationsRequests?.push(url.search);
      if (sftpOperationsShouldFail) {
        return json(route, { detail: sftpOperationsFailureDetail }, sftpOperationsFailureStatus);
      }
      return json(route, sftpOperations);
    }
    if (path === '/sftp/operations/reconcile' && method === 'POST') {
      sftpOperationsReconcileRequests?.push(request.postDataJSON());
      if (sftpOperationsReconcileResponse) {
        return json(route, sftpOperationsReconcileResponse);
      }
      return json(route, { detail: sftpOperationsReconcileFailureDetail }, sftpOperationsReconcileFailureStatus);
    }
    if (path === '/sftp/deposits/indexing-assist' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      sftpIndexingAssistRequests?.push(body);
      const fileIds = Array.isArray(body['file_ids']) ? body['file_ids'] : [];
      return json(route, fileIds.length > 0 && sftpIndexingAssist ? sftpIndexingAssist : emptySftpIndexingAssist());
    }
    if (path === '/documents/jobs' && method === 'GET') {
      sftpJobsRequests?.push(url.search);
      if (sftpJobsShouldFail) {
        return json(route, { detail: 'Mocked indexing jobs unavailable' }, 500);
      }
      const assist = sftpIndexingAssist || emptySftpIndexingAssist();
      const collection = assist.collection as { jobs?: unknown[] };
      return json(route, { items: collection.jobs || [] });
    }
    if (/^\/workspace-jobs\/job-andritz-deep-1$/.test(path) && method === 'GET') {
      workspaceJobRequests?.push(url.search);
      return json(route, {
        id: 'job-andritz-deep-1',
        status: 'completed',
        progress: 100,
        stage: 'deep_completed',
        result: {
          status: 'completed',
          answer: 'Synthetic deep retrieval answer with expanded Andritz evidence [1].',
          answer_status: 'completed',
          answer_provider: 'mock',
          answer_model: 'deep-mock',
          summary: {
            chunks_retrieved: 4,
            sources_returned: 2,
            top_score: 0.94,
            pipeline: 'deep_hierarchical_dense',
            partial: false,
            top_sources: [
              {
                label: 'andritz-deep-evidence.pdf',
                chunks: 3,
              },
            ],
          },
          sources_preview: [
            {
              id: 'src-andritz-deep-1',
              document_id: 'doc-andritz-deep',
              filename: 'andritz-deep-evidence.pdf',
              title: 'Andritz deep evidence',
              snippet: 'Synthetic deep retrieval source snippet.',
              collection: 'andritz-qa',
              score: 0.94,
              page: 2,
            },
          ],
        },
      });
    }

    if (path === '/sessions' && method === 'GET') {
      return json(route, { sessions: [] });
    }
    if (path === '/sessions' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      chatSessionCreateRequests?.push(body);
      return json(route, {
        id: 'chat-session-andritz-qa',
        title: 'Synthetic Andritz QA chat',
        status: 'active',
        message_count: 0,
        updated_at: '2026-06-23T00:00:00Z',
      });
    }
    if (path === '/sessions/chat-session-andritz-qa') {
      return json(route, {
        id: 'chat-session-andritz-qa',
        title: 'Synthetic Andritz QA chat',
        status: 'active',
        messages: [],
      });
    }
    if (path === '/chat/stream' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      chatStreamRequests?.push(body);
      if (chatStreamAbort) {
        if (chatStreamAbortDelayMs > 0) await delay(chatStreamAbortDelayMs);
        return route.abort('failed');
      }
      if (chatStreamDelayMs > 0) await delay(chatStreamDelayMs);
      const streamChunks: unknown[] = [
        {
          chunk_type: 'session',
          session_id: 'chat-session-andritz-qa',
        },
      ];
      if (chatStreamDeepQueued) {
        streamChunks.push({
          chunk_type: 'retrieval',
          phase: 'deep_queued',
          details: {
            deep_job_id: 'job-andritz-deep-1',
            deep_poll_url: '/workspace-jobs/job-andritz-deep-1',
            deep_status: 'queued',
            deep_progress: 10,
            deep_stage: 'auto_deep_search',
            message_id: 'deep-msg-andritz-1',
          },
        });
      }
      streamChunks.push(
        {
          chunk_type: 'retrieval',
          phase: 'completed',
          details: {
            latency_profile: 'fast',
            retrieval_scope: { collection: 'andritz-qa' },
            candidate_counts: { dense: 1, selected: 1 },
          },
        },
        {
          chunk_type: 'text',
          content: 'Synthetic Andritz QA answer with cited source [1].',
          sources: [
            {
              id: 'src-andritz-qa',
              document_id: 'doc-andritz-qa',
              filename: 'andritz-qa-safe.pdf',
              title: 'Andritz QA safe document',
              snippet: 'Synthetic Andritz QA source snippet.',
              collection: 'andritz-qa',
              score: 0.91,
            },
          ],
        },
      );
      return sse(route, streamChunks);
    }
    if (path.startsWith('/chat/')) {
      return json(route, path.endsWith('/sessions') ? { sessions: [] } : {});
    }
    if (path === '/actions/effective') {
      return json(route, { actions: [] });
    }
    if (path === '/audit' && method === 'POST') {
      auditRequests?.push(request.postDataJSON());
      if (auditShouldFail) {
        return json(route, { detail: 'Mocked audit unavailable' }, 500);
      }
      return json(route, { status: 'ok' });
    }
    if (path === '/voice/runtimes') {
      return json(route, {
        default_provider: 'mock',
        allowed_providers: ['mock'],
        fallback_providers: [],
        events: [],
        providers: [],
      });
    }

    return json(route, {});
  });
}

test.describe('Andritz mocked browser smoke', () => {
  for (const routePath of ['/chat', '/knowledge', '/knowledge/capture', '/connectors/sftp']) {
    test(`redirects unauthenticated ${routePath} access to sign-in`, async ({ page }) => {
      await page.goto(routePath);

      await expect(page).toHaveURL(/\/auth\/signin\?/);
      expect(new URL(page.url()).searchParams.get('redirectURL')).toBe(routePath);
      await expect(page.getByRole('heading', { name: /Sign in|Connexion/i })).toBeVisible();
    });
  }

  test('renders Chat, Knowledge Capture, Collections and SFTP entry without real data', async ({ page }) => {
    await installAndritzMocks(page);

    await page.goto('/connectors');
    await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Open secure deposit/i })).toBeVisible();

    await page.goto('/connectors/sftp');
    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/No active SFTP transfer|Live upload monitor/i);

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Andritz QA|andritz-qa/i);

    await page.goto('/knowledge/capture');
    await expect(page.locator('app-capture-fil-shell')).toBeVisible();
    await expect(page.locator('body')).toContainText(/Vos séances de capture|Nouvelle capture|Capture · Connaissances/i);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Question rapide|Posez votre question|Quick ask|Ask/i);
  });

  test('renders an empty Knowledge Capture dashboard without mutating capture data', async ({ page }) => {
    const captureMutations: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (
        url.pathname.includes('/api/v1/knowledge-capture')
        && ['POST', 'PATCH', 'DELETE'].includes(request.method())
      ) {
        captureMutations.push(`${request.method()} ${url.pathname}`);
      }
    });
    await installAndritzMocks(page);

    await page.goto('/knowledge/capture?exp=v0');
    await expect(page.locator('body')).toContainText(/Sessions de capture|Capture sessions/i);
    await expect(page.getByRole('button', { name: /Nouvelle capture|Nouvelle session|New capture|New session/i }).first()).toBeVisible();
    await expect(page.locator('body')).toContainText(/Aucune session pour l’instant|No sessions yet/i);
    await expect(page.locator('body')).toContainText(/Afficher les sessions archivées|Show archived sessions/i);

    const publishedTab = page.getByRole('button', { name: /Fiches publiées|Published sheets/i });
    await expect(publishedTab).toBeVisible();
    await publishedTab.click();
    await expect(page.locator('body')).toContainText(/Fiches publiées|Published knowledge sheets/i);
    await expect(page.locator('body')).toContainText(/Aucune fiche publiée pour l’instant|No published sheets yet/i);

    expect(captureMutations).toEqual([]);
  });

  test('shows disabled SFTP connector as ready but not configured', async ({ page }) => {
    await installAndritzMocks(page, { secureDepositEnabled: false });

    await page.goto('/connectors');
    const sftpCard = page.locator('article').filter({ hasText: 'SFTP / Secure Deposit' }).first();
    await expect(sftpCard).toBeVisible();
    await expect(sftpCard).toContainText(/ready/i);
    await expect(sftpCard).not.toContainText(/configured|Config saved/i);
  });

  test('opens SFTP from the connectors catalogue without mutating secure deposit state', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors');
    await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible();
    const sftpCard = page.locator('article').filter({ hasText: 'SFTP / Secure Deposit' }).first();
    await expect(sftpCard).toBeVisible();
    await sftpCard.getByRole('link', { name: /Open secure deposit/i }).click();

    await expect(page).toHaveURL(/\/connectors\/sftp$/);
    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Live upload monitor|No active SFTP transfer/i);
    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('shows the default SFTP target collection before any promotion action', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpIndexingAssist: emptySftpIndexingAssist(),
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    const targetCard = page.locator('section').filter({ hasText: 'Knowledge destination' }).first();
    await expect(targetCard.getByText('Target collection', { exact: true })).toBeVisible();
    await expect(targetCard.getByText('Knowledge destination')).toBeVisible();
    const collectionPicker = targetCard.locator('select[name="collectionPicker"]');
    await expect(collectionPicker).toHaveValue('andritz-qa');
    await expect(collectionPicker).toContainText('andritz-qa · ready · 12 chunks');
    await expect(targetCard.locator('input[name="collection"]')).toHaveValue('andritz-qa');
    await expect(targetCard.getByText('Andritz QA · ready · 2 docs')).toBeVisible();
    await expect(targetCard.getByRole('link', { name: 'Open', exact: true })).toHaveAttribute('href', '/knowledge/andritz-qa');

    const targetState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          targetCollectionSlug?: () => string;
          collectionSlug?: string;
          selectedKnowledgeCollection?: () => { slug?: string; name?: string; status?: string } | null;
        }
        | undefined;
      return {
        targetCollectionSlug: component?.targetCollectionSlug?.(),
        collectionSlug: component?.collectionSlug,
        selectedKnowledgeCollection: component?.selectedKnowledgeCollection?.(),
      };
    });
    expect(targetState).toMatchObject({
      targetCollectionSlug: 'andritz-qa',
      collectionSlug: 'andritz-qa',
      selectedKnowledgeCollection: {
        slug: 'andritz-qa',
        name: 'Andritz QA',
        status: 'ready',
      },
    });
    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('keeps direct SFTP page read-only when Secure Deposit is disabled', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      secureDepositEnabled: false,
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText(/Secure Deposit is not enabled for Andritz/i)).toBeVisible();
    await expect(page.locator('input[name="label"]')).toBeDisabled();
    await expect(page.locator('input[name="max"]')).toBeDisabled();
    await expect(page.locator('input[name="expires"]')).toBeDisabled();
    await expect(page.locator('input[name="extensions"]')).toBeDisabled();
    await expect(page.getByRole('button', { name: /Create link/i })).toBeDisabled();
    await expect(page.locator('section').filter({ hasText: 'Deposit links' }).first()).toContainText(
      'Andritz QA external upload',
    );

    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('loads enabled SFTP health without exposing secrets or mutating state', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      secureDepositEnabled: true,
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText(/Secure Deposit is not enabled/i)).toHaveCount(0);
    await expect(page.locator('input[name="label"]')).toBeEnabled();
    await expect(page.locator('input[name="max"]')).toBeEnabled();
    await expect(page.locator('input[name="expires"]')).toBeEnabled();
    await expect(page.locator('input[name="extensions"]')).toBeEnabled();
    await expect(page.getByRole('button', { name: /Create link/i })).toBeEnabled();

    const healthState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          health?: () => Record<string, unknown> | null;
          secureDepositEnabled?: () => boolean;
        }
        | undefined;
      return {
        enabled: component?.secureDepositEnabled?.(),
        health: component?.health?.(),
      };
    });
    expect(healthState).toMatchObject({
      enabled: true,
      health: {
        status: 'ok',
        workspace: 'andritz',
        enabled: true,
        default_allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx', '.png', '.jpg'],
      },
    });
    expect(JSON.stringify(healthState.health).toLowerCase()).not.toMatch(
      /password|secret|token|private|credential|session/,
    );

    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('copies an existing SFTP deposit URL without exposing a stored password or mutating links', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async (value: string) => {
            window.localStorage.setItem('andritz_mock_clipboard', value);
          },
        },
      });
    });
    await installAndritzMocks(page, {
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    const depositLinks = page.locator('section').filter({ hasText: 'Deposit links' }).first();
    await expect(depositLinks).toContainText('Andritz QA external upload');
    await expect(depositLinks).toContainText('https://example.test/deposit/andritz-qa');
    await expect(depositLinks.getByText(/Password:/i)).toHaveCount(0);

    await depositLinks.getByRole('button', { name: /Copy URL/i }).click();
    await expect(page.getByText('URL copied').first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.localStorage.getItem('andritz_mock_clipboard'))).toBe(
      'https://example.test/deposit/andritz-qa',
    );

    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('shows a recoverable SFTP deposit URL copy error without mutating links', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async () => {
            throw new Error('clipboard denied');
          },
        },
      });
    });
    await installAndritzMocks(page, {
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    const depositLinks = page.locator('section').filter({ hasText: 'Deposit links' }).first();
    await expect(depositLinks).toContainText('Andritz QA external upload');
    await depositLinks.getByRole('button', { name: /Copy URL/i }).click();

    await expect(page.getByText('Copy failed').first()).toBeVisible();
    await expect(page.getByText('URL copied')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.localStorage.getItem('andritz_mock_clipboard'))).toBeNull();

    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('creates, rotates and revokes synthetic SFTP links without exposing stored passwords or promoting files', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.locator('input[name="label"]').fill('Andritz QA one-time handoff');
    await page.locator('input[name="max"]').fill('128');
    await page.locator('input[name="expires"]').fill('2026-07-15');
    await page.locator('input[name="extensions"]').fill('pdf, .docx, PPTX');
    await page.getByRole('button', { name: /Create link/i }).click();

    const shareOnce = page.locator('section').filter({ hasText: 'Share once' }).first();
    await expect(shareOnce).toBeVisible();
    await expect(shareOnce).toContainText('Andritz QA one-time handoff');
    await expect(shareOnce).toContainText('temporary-secret-visible-once');
    expect(sftpLinkMutationRequests).toEqual([
      {
        path: '/sftp/links',
        body: expect.objectContaining({
          label: 'Andritz QA one-time handoff',
          max_file_size_mb: 128,
          allowed_extensions: ['pdf', 'docx', 'pptx'],
        }),
      },
    ]);
    expect((sftpLinkMutationRequests[0]?.body as { expires_at?: string } | undefined)?.expires_at).toBe(
      new Date('2026-07-15T23:59:59').toISOString(),
    );

    const depositLinks = page.locator('section').filter({ hasText: 'Deposit links' }).first();
    await expect(depositLinks).toContainText('Andritz QA external upload');
    await expect(depositLinks.getByText(/Password:/i)).toHaveCount(0);
    await shareOnce.getByRole('button', { name: /Hide/i }).click();
    await expect(page.getByText('temporary-secret-visible-once')).toHaveCount(0);
    await expect(depositLinks.getByText(/Password:/i)).toHaveCount(0);

    await depositLinks.getByRole('button', { name: /Rotate/i }).click();
    await expect(shareOnce).toContainText('rotated-secret-visible-once');
    await expect(depositLinks.getByText(/Password:/i)).toHaveCount(0);

    await depositLinks.getByRole('button', { name: /Revoke/i }).click();
    expect(sftpLinkMutationRequests).toEqual([
      expect.objectContaining({ path: '/sftp/links' }),
      { path: '/sftp/links/link-andritz-qa/rotate', body: {} },
      { path: '/sftp/links/link-andritz-qa/revoke', body: {} },
    ]);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('keeps SFTP link state unchanged when link management is forbidden', async ({ page }) => {
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      roleTemplate: 'workspace_reviewer',
      sftpLinkMutationRequests,
      sftpLinkMutationShouldFail: true,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    const depositLinks = page.locator('section').filter({ hasText: 'Deposit links' }).first();
    await expect(depositLinks).toContainText('Andritz QA external upload');

    await page.locator('input[name="label"]').fill('Andritz denied handoff');
    await page.getByRole('button', { name: /Create link/i }).click();
    await expect(page.getByText('Mocked SFTP link management permission denied')).toBeVisible();
    await expect(page.getByText('Andritz denied handoff')).toHaveCount(0);
    await expect(page.getByText('temporary-secret-visible-once')).toHaveCount(0);

    await depositLinks.getByRole('button', { name: /Rotate/i }).click();
    await expect(page.getByText('Unable to rotate password')).toBeVisible();
    await expect(page.getByText('rotated-secret-visible-once')).toHaveCount(0);

    await depositLinks.getByRole('button', { name: /Revoke/i }).click();
    await expect(page.getByText('Unable to revoke link')).toBeVisible();
    await expect(depositLinks).toContainText('active');
    await expect(depositLinks.getByText(/Password:/i)).toHaveCount(0);

    expect(sftpLinkMutationRequests).toEqual([
      expect.objectContaining({ path: '/sftp/links' }),
      { path: '/sftp/links/link-andritz-qa/rotate', body: {} },
      { path: '/sftp/links/link-andritz-qa/revoke', body: {} },
    ]);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('loads and filters the SFTP staging queue without promoting synthetic files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.getByText('Workspace staging queue', { exact: true }).scrollIntoViewIfNeeded();
    await page.mouse.wheel(0, 500);
    await expect(page.locator('body')).toContainText(/1 \/ 3 files/i);
    await expect(page.getByText(/2 hidden by status filter/i)).toBeVisible();
    await expect(page.getByTitle('Promote up to 25 files recommended by the latest indexing assist run.')).toBeDisabled();

    await page.locator('select[name="queueStatusFilter"]').selectOption('all');
    await page.locator('input[name="queueSearch"]').fill('promoted');
    const queueState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          queueItems?: () => Array<{ kind?: string; name?: string; path?: string }>;
          queueSearch?: () => string;
          statusFilter?: () => string;
        }
        | undefined;
      return {
        queueSearch: component?.queueSearch?.(),
        statusFilter: component?.statusFilter?.(),
        queueItems: component?.queueItems?.() || [],
      };
    });
    expect(queueState).toMatchObject({
      queueSearch: 'promoted',
      statusFilter: 'all',
    });
    expect(queueState.queueItems).toEqual([
      expect.objectContaining({
        kind: 'file',
        name: 'andritz-promoted-manual.docx',
        path: '1-NON-WOVENS/FRANCE/andritz-promoted-manual.docx',
      }),
    ]);

    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('paginates a large mocked SFTP staging queue without mutating files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticLargeSftpDepositFiles(125),
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await page.getByText('Workspace staging queue', { exact: true }).scrollIntoViewIfNeeded();
    await page.locator('input[name="queueSearch"]').fill('pagination-probe');
    await page.locator('select[name="queuePageSize"]').selectOption('50');
    await expect(page.locator('body')).toContainText('1-50 of 125 rows');
    await expect(page.locator('body')).toContainText('Page 1 / 3');

    await page.locator('select[name="queuePageSize"]').selectOption('100');
    await expect(page.locator('body')).toContainText('1-100 of 125 rows');
    await expect(page.locator('body')).toContainText('Page 1 / 2');
    await page.getByRole('button', { name: /Next/i }).click();
    await expect(page.locator('body')).toContainText('101-125 of 125 rows');
    await expect(page.locator('body')).toContainText('Page 2 / 2');

    const queueState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          currentQueuePage?: () => number;
          queueItems?: () => Array<{ kind?: string; name?: string; path?: string }>;
          queuePageSize?: () => number;
          queueSearch?: () => string;
          totalQueuePages?: () => number;
          visibleQueueItems?: () => Array<{ kind?: string; name?: string; path?: string }>;
        }
        | undefined;
      return {
        currentQueuePage: component?.currentQueuePage?.(),
        queueItemCount: component?.queueItems?.().length,
        queuePageSize: component?.queuePageSize?.(),
        queueSearch: component?.queueSearch?.(),
        totalQueuePages: component?.totalQueuePages?.(),
        visibleCount: component?.visibleQueueItems?.().length,
        firstVisible: component?.visibleQueueItems?.()[0],
        lastVisible: component?.visibleQueueItems?.().at(-1),
      };
    });

    expect(queueState).toMatchObject({
      currentQueuePage: 2,
      queueItemCount: 125,
      queuePageSize: 100,
      queueSearch: 'pagination-probe',
      totalQueuePages: 2,
      visibleCount: 25,
      firstVisible: expect.objectContaining({ name: 'pagination-probe-101.pdf' }),
      lastVisible: expect.objectContaining({ name: 'pagination-probe-125.pdf' }),
    });
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('filters the SFTP staging queue by deposit link and shows an empty search without mutating files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const secondaryLink: MockSftpDepositLink = {
      ...defaultSftpDepositLink(),
      id: 'link-andritz-maintenance',
      label: 'Andritz maintenance upload',
      access_id: 'andritz-maintenance',
      public_url: 'https://example.test/deposit/andritz-maintenance',
    };
    await installAndritzMocks(page, {
      sftpLinks: [defaultSftpDepositLink(), secondaryLink],
      sftpDepositFiles: [
        ...syntheticSftpDepositFiles(),
        {
          id: 'deposit-andritz-maintenance-1',
          access_link_id: secondaryLink.id,
          filename: '3-MAINTENANCE/andritz-maintenance-note.pdf',
          content_type: 'application/pdf',
          size_bytes: 48_000,
          sha256: 'sha-maintenance-note',
          status: 'received',
          uploaded_at: '2026-06-23T00:18:00Z',
          promoted_at: null,
          worker_job_id: null,
          promotion_result: null,
        },
      ],
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.getByText('Workspace staging queue', { exact: true }).scrollIntoViewIfNeeded();
    await expect(page.locator('select[name="queueFilter"]')).toContainText('Andritz maintenance upload');
    await page.locator('select[name="queueFilter"]').selectOption(secondaryLink.id);
    await expect(page.locator('select[name="queueFilter"]')).toHaveValue(secondaryLink.id);

    const linkedQueueState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          selectedLinkId?: () => string;
          filteredFiles?: () => Array<{ filename?: string; access_link_id?: string; status?: string }>;
          queueItems?: () => Array<{ kind?: string; name?: string; path?: string }>;
          queueSearch?: () => string;
        }
        | undefined;
      return {
        selectedLinkId: component?.selectedLinkId?.(),
        queueSearch: component?.queueSearch?.(),
        filteredFiles: component?.filteredFiles?.() || [],
        queueItems: component?.queueItems?.() || [],
      };
    });
    expect(linkedQueueState).toMatchObject({
      selectedLinkId: secondaryLink.id,
      queueSearch: '',
      filteredFiles: [
        expect.objectContaining({
          access_link_id: secondaryLink.id,
          filename: '3-MAINTENANCE/andritz-maintenance-note.pdf',
          status: 'received',
        }),
      ],
    });
    expect(linkedQueueState.queueItems).toEqual([
      expect.objectContaining({
        kind: 'folder',
        name: '3-MAINTENANCE',
        path: '3-MAINTENANCE',
      }),
    ]);

    await page.locator('input[name="queueSearch"]').fill('no-maintenance-match');
    await expect(page.getByText('No files match this search.')).toBeVisible();
    const emptySearchState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          selectedLinkId?: () => string;
          filteredFiles?: () => Array<{ filename?: string; access_link_id?: string; status?: string }>;
          queueItems?: () => Array<{ kind?: string; name?: string; path?: string }>;
          queueSearch?: () => string;
        }
        | undefined;
      return {
        selectedLinkId: component?.selectedLinkId?.(),
        queueSearch: component?.queueSearch?.(),
        filteredFiles: component?.filteredFiles?.() || [],
        queueItems: component?.queueItems?.() || [],
      };
    });
    expect(emptySearchState).toMatchObject({
      selectedLinkId: secondaryLink.id,
      queueSearch: 'no-maintenance-match',
      filteredFiles: [
        expect.objectContaining({
          access_link_id: secondaryLink.id,
          filename: '3-MAINTENANCE/andritz-maintenance-note.pdf',
        }),
      ],
      queueItems: [],
    });

    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('shows SFTP operations and indexing assist without mutating synthetic files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpIndexingAssistRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperations: syntheticSftpOperations(),
      sftpIndexingAssist: syntheticSftpIndexingAssist(),
      sftpIndexingAssistRequests,
      sftpOperationsReconcileRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText('1 active transfer')).toBeVisible();
    await expect(page.getByText('andritz-live-upload.pdf')).toBeVisible();
    await expect(page.getByText('Dry-run completed')).toBeVisible();
    await expect(page.getByText(/2 quarantine candidates/i)).toBeVisible();

    await page.locator('input[name="queueSearch"]').fill('pump');
    await page.getByRole('button', { name: /Analyze current view/i }).click();
    await expect(page.getByText('Promote now').first()).toBeVisible();
    await expect(page.getByText('Synthetic supported PDF in the current SFTP queue view.').first()).toBeVisible();
    await expect(page.getByText('Embedding synthetic SFTP files').first()).toBeVisible();

    const sftpState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          liveUploads?: () => Array<{ filename?: string }>;
          operationsSummary?: () => { active_count?: number; last_received_filename?: string } | null;
          quarantineCandidateCount?: () => number;
          indexingAssist?: () => { summary?: { recommended_count?: number } } | null;
          recommendedBatchFiles?: () => Array<{ id?: string; filename?: string }>;
        }
        | undefined;
      return {
        liveUploadFilenames: component?.liveUploads?.().map((item) => item.filename) || [],
        operationsSummary: component?.operationsSummary?.(),
        quarantineCandidateCount: component?.quarantineCandidateCount?.(),
        recommendedCount: component?.indexingAssist?.()?.summary?.recommended_count,
        recommendedBatchFiles: component?.recommendedBatchFiles?.() || [],
      };
    });
    expect(sftpState).toMatchObject({
      liveUploadFilenames: ['1-NON-WOVENS/FRANCE/andritz-live-upload.pdf'],
      operationsSummary: {
        active_count: 1,
        last_received_filename: '1-NON-WOVENS/FRANCE/andritz-last-received.pdf',
      },
      quarantineCandidateCount: 2,
      recommendedCount: 1,
    });
    expect(sftpState.recommendedBatchFiles).toEqual([
      expect.objectContaining({
        id: 'deposit-andritz-received-1',
        filename: '1-NON-WOVENS/FRANCE/andritz-pump-check.pdf',
      }),
    ]);

    expect(sftpIndexingAssistRequests.at(-1)).toMatchObject({
      collection_slug: 'andritz-qa',
      file_ids: ['deposit-andritz-received-1'],
    });
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('keeps SFTP indexing monitor failure visible and non-mutating', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpIndexingAssistRequests: unknown[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpJobsRequests: string[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperations: syntheticSftpOperations(),
      sftpJobsRequests,
      sftpJobsShouldFail: true,
      sftpIndexingAssistRequests,
      sftpOperationsReconcileRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
      sftpLinkMutationRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.getByRole('button', { name: /Refresh pipeline/i }).click();
    await expect(page.getByText('Mocked indexing jobs unavailable')).toBeVisible();
    await expect(page.getByRole('button', { name: /Analyze current view/i })).toBeEnabled();
    await expect(page.getByRole('button', { name: /Create link/i })).toBeEnabled();

    const monitorState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          indexingMonitorError?: () => string | null;
          knowledgeJobs?: () => unknown[];
          knowledgeJobsLoading?: () => boolean;
        }
        | undefined;
      return {
        indexingMonitorError: component?.indexingMonitorError?.(),
        knowledgeJobs: component?.knowledgeJobs?.() || [],
        knowledgeJobsLoading: component?.knowledgeJobsLoading?.(),
      };
    });
    expect(monitorState).toMatchObject({
      indexingMonitorError: 'Mocked indexing jobs unavailable',
      knowledgeJobs: [],
      knowledgeJobsLoading: false,
    });
    expect(sftpJobsRequests.length).toBeGreaterThan(0);
    expect(sftpJobsRequests.at(-1)).toContain('collection_id=andritz-qa');
    expect(sftpIndexingAssistRequests.every((request) => {
      const fileIds = (request as { file_ids?: unknown }).file_ids;
      return Array.isArray(fileIds) && fileIds.length === 0;
    })).toBe(true);
    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('keeps SFTP long-session polling bounded and cleans up on teardown', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    const sftpOperationsRequests: string[] = [];
    const sftpJobsRequests: string[] = [];

    await page.addInitScript(() => {
      const originalSetInterval = window.setInterval.bind(window);
      const originalClearInterval = window.clearInterval.bind(window);
      const probe = {
        created: [] as Array<{ id: number; requested_ms: number; effective_ms: number }>,
        cleared: [] as number[],
      };
      (window as unknown as { __sftpPollingProbe?: typeof probe }).__sftpPollingProbe = probe;
      window.setInterval = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
        const requested = Number(timeout || 0);
        const effective = requested === 5000 ? 50 : requested;
        const id = originalSetInterval(handler, effective, ...args);
        probe.created.push({ id: Number(id), requested_ms: requested, effective_ms: effective });
        return id;
      }) as typeof window.setInterval;
      window.clearInterval = ((id?: number) => {
        if (typeof id === 'number') {
          probe.cleared.push(id);
        }
        return originalClearInterval(id);
      }) as typeof window.clearInterval;
    });

    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperations: syntheticSftpOperations(),
      sftpOperationsRequests,
      sftpJobsRequests,
      sftpOperationsReconcileRequests,
      sftpLinkMutationRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect.poll(async () => {
      return page.evaluate(() => {
        const probe = (window as unknown as {
          __sftpPollingProbe?: {
            created: Array<{ requested_ms: number }>;
          };
        }).__sftpPollingProbe;
        return probe?.created.filter((entry) => entry.requested_ms === 5000).length || 0;
      });
    }).toBe(2);

    await page.waitForTimeout(190);

    const pollProbeBeforeNavigation = await page.evaluate(() => {
      const probe = (window as unknown as {
        __sftpPollingProbe?: {
          created: Array<{ id: number; requested_ms: number; effective_ms: number }>;
          cleared: number[];
        };
      }).__sftpPollingProbe;
      return {
        pollIntervals: probe?.created.filter((entry) => entry.requested_ms === 5000) || [],
        cleared: probe?.cleared || [],
      };
    });
    expect(pollProbeBeforeNavigation.pollIntervals).toHaveLength(2);
    expect(pollProbeBeforeNavigation.pollIntervals.every((entry) => entry.effective_ms === 50)).toBe(true);
    expect(sftpOperationsRequests.length).toBeGreaterThanOrEqual(2);
    expect(sftpJobsRequests.length).toBeGreaterThanOrEqual(1);
    // Request totals depend on scheduler load once the 5 s timers are
    // accelerated to 50 ms. Boundedness is proven structurally by the two
    // intervals above and behaviourally by zero additional requests after
    // both interval ids are cleared below.

    await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as { ngOnDestroy?: () => void } | undefined;
      component?.ngOnDestroy?.();
    });
    await page.waitForTimeout(80);

    const pollProbeAfterNavigation = await page.evaluate(() => {
      const probe = (window as unknown as {
        __sftpPollingProbe?: {
          created: Array<{ id: number; requested_ms: number }>;
          cleared: number[];
        };
      }).__sftpPollingProbe;
      const pollIntervals = probe?.created.filter((entry) => entry.requested_ms === 5000) || [];
      return {
        pollIntervals,
        cleared: probe?.cleared || [],
      };
    });
    const cleared = new Set(pollProbeAfterNavigation.cleared);
    expect(pollProbeAfterNavigation.pollIntervals).toHaveLength(2);
    for (const interval of pollProbeAfterNavigation.pollIntervals) {
      expect(cleared.has(interval.id)).toBe(true);
    }
    const operationsAfterNavigation = sftpOperationsRequests.length;
    const jobsAfterNavigation = sftpJobsRequests.length;
    await page.waitForTimeout(120);
    expect(sftpOperationsRequests).toHaveLength(operationsAfterNavigation);
    expect(sftpJobsRequests).toHaveLength(jobsAfterNavigation);

    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
  });

  test('shows SFTP reconciliation permission denial without quarantine mutation', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      roleTemplate: 'workspace_reviewer',
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperations: syntheticSftpOperations(),
      sftpOperationsReconcileRequests,
      sftpOperationsReconcileFailureStatus: 403,
      sftpOperationsReconcileFailureDetail: 'Mocked reconciliation forbidden for reviewer',
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText(/2 quarantine candidates/i)).toBeVisible();
    await page.getByRole('button', { name: /Run check/i }).click();
    await expect(page.getByText('Mocked reconciliation forbidden for reviewer')).toBeVisible();
    await expect(page.getByRole('button', { name: /Run check/i })).toBeEnabled();
    await expect(page.getByRole('button', { name: /Move to quarantine/i })).toBeEnabled();

    expect(sftpOperationsReconcileRequests).toEqual([
      expect.objectContaining({
        mode: 'dry_run',
        stale_after_hours: 24,
      }),
    ]);
    expect(sftpOperationsReconcileRequests).not.toContainEqual(expect.objectContaining({ mode: 'quarantine' }));
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('runs SFTP reconciliation dry-run without quarantine mutation', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpOperationsRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    const sftpLinkMutationRequests: Array<{ path: string; body?: unknown }> = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperations: syntheticSftpOperations(),
      sftpOperationsRequests,
      sftpOperationsReconcileRequests,
      sftpOperationsReconcileResponse: {
        job: {
          id: 'job-sftp-dry-run-refresh',
          kind: 'sftp_reconciliation',
          title: 'Synthetic SFTP reconciliation dry run refresh',
          status: 'completed',
          progress: 100,
          stage: 'dry_run',
          error: null,
          input_ref: { mode: 'dry_run' },
          result: {
            counts: { stale_partials: 1, orphan_files: 1, missing_db_files: 0, pending_rows: 0 },
            sizes: { stale_partial_bytes: 2_048, orphan_file_bytes: 4_096 },
          },
          created_at: '2026-06-23T00:35:00Z',
          updated_at: '2026-06-23T00:35:05Z',
          completed_at: '2026-06-23T00:35:05Z',
        },
      },
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
      sftpLinkMutationRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText(/2 quarantine candidates/i)).toBeVisible();
    await page.getByRole('button', { name: /Run check/i }).click();
    await expect(page.getByText('Reconciliation completed')).toBeVisible();
    await expect(page.getByRole('button', { name: /Run check/i })).toBeEnabled();
    await expect.poll(() => sftpOperationsRequests.length).toBeGreaterThanOrEqual(2);

    expect(sftpOperationsReconcileRequests).toEqual([
      expect.objectContaining({
        mode: 'dry_run',
        stale_after_hours: 24,
      }),
    ]);
    expect(sftpOperationsReconcileRequests).not.toContainEqual(expect.objectContaining({ mode: 'quarantine' }));
    expect(sftpOperationsRequests.at(-1)).toContain('stale_after_hours=24');
    expect(sftpLinkMutationRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('requires explicit confirmation before SFTP quarantine mutation', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperations: syntheticSftpOperations(),
      sftpOperationsReconcileRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText(/2 quarantine candidates/i)).toBeVisible();

    let confirmationMessage = '';
    page.once('dialog', async (dialog) => {
      confirmationMessage = dialog.message();
      await dialog.dismiss();
    });
    await page.getByRole('button', { name: /Move to quarantine/i }).click();

    expect(confirmationMessage).toContain('Move 2 stale/orphan item(s)');
    expect(confirmationMessage).toContain('No active upload or recent file will be touched');
    await expect(page.getByRole('button', { name: /Move to quarantine/i })).toBeEnabled();
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('keeps SFTP operations monitor failure visible and non-mutating', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpOperationsRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpOperationsRequests,
      sftpOperationsShouldFail: true,
      sftpOperationsFailureDetail: 'Mocked SFTP operations unavailable',
      sftpOperationsReconcileRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.getByText('Mocked SFTP operations unavailable')).toBeVisible();
    await page.getByRole('button', { name: /Refresh ops/i }).click();
    await expect(page.getByText('Mocked SFTP operations unavailable')).toBeVisible();
    await expect(page.getByRole('button', { name: /Run check/i })).toBeEnabled();
    await expect(page.getByRole('button', { name: /Analyze current view/i })).toBeEnabled();
    await expect(page.getByRole('button', { name: /Create link/i })).toBeEnabled();

    const operationsState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          operations?: () => unknown | null;
          operationsError?: () => string | null;
          operationsLoading?: () => boolean;
        }
        | undefined;
      return {
        operations: component?.operations?.() || null,
        operationsError: component?.operationsError?.(),
        operationsLoading: component?.operationsLoading?.(),
      };
    });
    expect(operationsState).toMatchObject({
      operations: null,
      operationsError: 'Mocked SFTP operations unavailable',
      operationsLoading: false,
    });
    expect(sftpOperationsRequests.length).toBeGreaterThanOrEqual(2);
    expect(sftpOperationsRequests.at(-1)).toContain('stale_after_hours=24');
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('uses the selected SFTP target collection for indexing assist without promoting files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpIndexingAssistRequests: unknown[] = [];
    await installAndritzMocks(page, {
      knowledgeCollectionItems: [
        {
          slug: 'maintenance-qa',
          name: 'Maintenance QA',
          status: 'ready',
          document_count: 3,
          chunk_count: 33,
          updated_at: '2026-06-23T00:40:00Z',
        },
      ],
      sftpDepositFiles: syntheticSftpDepositFiles(),
      sftpIndexingAssist: syntheticSftpIndexingAssist(),
      sftpIndexingAssistRequests,
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    const collectionPicker = page.locator('select[name="collectionPicker"]');
    await expect(collectionPicker).toContainText('maintenance-qa');
    await expect(page.locator('input[name="collection"]')).toHaveValue('andritz-qa');

    await collectionPicker.selectOption('maintenance-qa');
    await expect(collectionPicker).toHaveValue('maintenance-qa');
    await expect(page.locator('input[name="collection"]')).toHaveValue('maintenance-qa');

    await page.locator('input[name="queueSearch"]').fill('pump');
    await page.getByRole('button', { name: /Analyze current view/i }).click();
    await expect(page.getByText('Promote now').first()).toBeVisible();

    const targetState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          targetCollectionSlug?: () => string;
          collectionSlug?: string;
          recommendedBatchFiles?: () => Array<{ id?: string; filename?: string }>;
        }
        | undefined;
      return {
        targetCollectionSlug: component?.targetCollectionSlug?.(),
        collectionSlug: component?.collectionSlug,
        recommendedBatchFiles: component?.recommendedBatchFiles?.() || [],
      };
    });
    expect(targetState).toMatchObject({
      targetCollectionSlug: 'maintenance-qa',
      collectionSlug: 'maintenance-qa',
    });
    expect(targetState.recommendedBatchFiles).toEqual([
      expect.objectContaining({
        id: 'deposit-andritz-received-1',
        filename: '1-NON-WOVENS/FRANCE/andritz-pump-check.pdf',
      }),
    ]);
    expect(sftpIndexingAssistRequests.at(-1)).toMatchObject({
      collection_slug: 'maintenance-qa',
      file_ids: ['deposit-andritz-received-1'],
    });
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
  });

  test('previews SFTP files and ZIP members without downloading or promoting synthetic files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpPreviewRequests: string[] = [];
    const sftpArchiveBrowseRequests: string[] = [];
    const sftpArchiveMemberPreviewRequests: string[] = [];
    const sftpFileDownloadRequests: string[] = [];
    const sftpArchiveMemberDownloadRequests: string[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpPreviewDepositFiles(),
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
      sftpPreviewRequests,
      sftpArchiveBrowseRequests,
      sftpArchiveMemberPreviewRequests,
      sftpFileDownloadRequests,
      sftpArchiveMemberDownloadRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.locator('input[name="queueSearch"]').fill('pump');
    await page.getByTitle('Preview file').click();
    await expect(page.getByText('andritz-pump-check.pdf').first()).toBeVisible();
    await expect(page.getByText('Synthetic SFTP text preview for pump check.')).toBeVisible();

    await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as { closePreview?: () => void } | undefined;
      component?.closePreview?.();
    });

    await page.locator('input[name="queueSearch"]').fill('archive');
    await page.getByTitle('Browse ZIP archive').click();
    await expect(page.getByText('andritz-archive-bundle.zip').first()).toBeVisible();
    await expect(page.getByText('qa-summary.txt').first()).toBeVisible();
    await expect(page.getByText('Select a previewable file in the archive.')).toBeVisible();

    await page.getByTitle('Preview archive member').click();
    await expect(page.getByText('Synthetic ZIP member preview from SFTP archive.')).toBeVisible();

    const previewState = await page.locator('app-sftp-connector').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
          archiveMode?: () => boolean;
          archivePreviewPath?: () => string | null;
          previewData?: () => { filename?: string; content?: string } | null;
          previewFileTarget?: () => { id?: string; filename?: string } | null;
        }
        | undefined;
      return {
        archiveMode: component?.archiveMode?.(),
        archivePreviewPath: component?.archivePreviewPath?.(),
        previewData: component?.previewData?.(),
        previewFileTarget: component?.previewFileTarget?.(),
      };
    });
    expect(previewState).toMatchObject({
      archiveMode: true,
      archivePreviewPath: 'manuals/qa-summary.txt',
      previewData: {
        filename: 'qa-summary.txt',
        content: 'Synthetic ZIP member preview from SFTP archive.',
      },
      previewFileTarget: {
        id: 'deposit-andritz-archive-1',
        filename: '1-NON-WOVENS/FRANCE/andritz-archive-bundle.zip',
      },
    });

    expect(sftpPreviewRequests).toEqual(['/sftp/deposits/deposit-andritz-received-1/preview']);
    expect(sftpArchiveBrowseRequests).toEqual(['/sftp/deposits/deposit-andritz-archive-1/archive?path=']);
    expect(sftpArchiveMemberPreviewRequests).toEqual([
      '/sftp/deposits/deposit-andritz-archive-1/archive/member/preview?path=manuals/qa-summary.txt',
    ]);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
    expect(sftpFileDownloadRequests).toHaveLength(0);
    expect(sftpArchiveMemberDownloadRequests).toHaveLength(0);
  });

  test('shows a recoverable SFTP file download error without mutating synthetic files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpFileDownloadRequests: string[] = [];
    const sftpArchiveMemberDownloadRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpPreviewDepositFiles(),
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
      sftpFileDownloadRequests,
      sftpFileDownloadFailureDetail: 'Mocked SFTP file download forbidden',
      sftpArchiveMemberDownloadRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.locator('input[name="queueSearch"]').fill('pump');
    await page.getByTitle('Download file').click();
    await expect(page.getByText('Unable to download file.')).toBeVisible();
    await expect(page.getByTitle('Download file')).toBeEnabled();

    expect(sftpFileDownloadRequests).toEqual(['/sftp/deposits/deposit-andritz-received-1/download']);
    expect(sftpArchiveDownloadRequests).toHaveLength(0);
    expect(sftpArchiveMemberDownloadRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
  });

  test('shows a recoverable SFTP archive download error without mutating synthetic files', async ({ page }) => {
    const sftpPromoteRequests: unknown[] = [];
    const sftpBulkPromoteRequests: unknown[] = [];
    const sftpArchiveDownloadRequests: string[] = [];
    const sftpFileDownloadRequests: string[] = [];
    const sftpArchiveMemberDownloadRequests: string[] = [];
    const sftpOperationsReconcileRequests: unknown[] = [];
    await installAndritzMocks(page, {
      sftpDepositFiles: syntheticSftpPreviewDepositFiles(),
      sftpPromoteRequests,
      sftpBulkPromoteRequests,
      sftpArchiveDownloadRequests,
      sftpFileDownloadRequests,
      sftpArchiveMemberDownloadRequests,
      sftpOperationsReconcileRequests,
    });

    await page.goto('/connectors/sftp');

    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await page.getByRole('button', { name: /Download ZIP/i }).click();
    await expect(page.getByText('Unable to download staging archive.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Download ZIP/i })).toBeEnabled();

    expect(sftpArchiveDownloadRequests).toEqual(['?status=received']);
    expect(sftpFileDownloadRequests).toHaveLength(0);
    expect(sftpArchiveMemberDownloadRequests).toHaveLength(0);
    expect(sftpOperationsReconcileRequests).toHaveLength(0);
    expect(sftpPromoteRequests).toHaveLength(0);
    expect(sftpBulkPromoteRequests).toHaveLength(0);
  });

  test('hides Chat drop-and-ask upload controls when the workspace flag is disabled', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatUploadRequests,
    });

    await page.goto('/chat');
    await expect(page.getByText(/Drop files/i)).toHaveCount(0);
    await expect(page.locator('input[type="file"]')).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('La recherche reste disponible sans upload.');
    await input.press('Enter');

    await expect(page.getByText('La recherche reste disponible sans upload.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatUploadRequests).toHaveLength(0);
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'La recherche reste disponible sans upload.',
      context_id: null,
      context_mode: null,
      stream: true,
      include_sources: true,
    });
  });

  test('keeps a jittered Chat voice final and emits client chunk-gap metrics', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const voiceMetrics = await page.evaluate(() => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const metrics: Record<string, unknown>[] = [];
      component.chatVoiceSessionId = 'chat-jitter-session';
      component.voiceTurnId = 'turn-chat-jitter';
      component.voiceConnection = {
        clientMetric: (payload: Record<string, unknown>) => metrics.push(payload),
      };
      component.voiceConversationActive.set(true);
      component.voiceConversationPaused.set(false);
      component.voiceAutoSend.set(true);
      component.transcribing.set(true);
      component.voicePartial.set('partiel avant jitter');
      component.emitVoiceClientMetric({
        metric: 'chunk_gap_ms',
        value_ms: 3800,
        chunk_gap_ms: 3800,
        chunk_size: 4096,
      });
      component.handleVoiceSessionEvent({
        id: 'evt-chat-jitter-final',
        session_id: 'chat-jitter-session',
        type: 'text.final',
        ts_ms: Date.now(),
        sequence: 4,
        payload: {
          text: 'La pompe reprend correctement apres un trou reseau.',
          fallback_used: false,
        },
      });
      return metrics;
    });

    expect(voiceMetrics).toHaveLength(1);
    expect(voiceMetrics[0]).toMatchObject({
      surface: 'chat',
      turn_id: 'turn-chat-jitter',
      metric: 'chunk_gap_ms',
      chunk_gap_ms: 3800,
      chunk_size: 4096,
    });
    await expect.poll(() => chatSessionCreateRequests.length).toBe(1);
    await expect.poll(() => chatStreamRequests.length).toBe(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'La pompe reprend correctement apres un trou reseau.',
      stream: true,
      include_sources: true,
    });
    await expect(page.getByText('La pompe reprend correctement apres un trou reseau.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
  });

  test('interrupts Chat TTS on speech while keeping the voice loop armed', async ({ page }) => {
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(async () => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const bargeIns: unknown[] = [];
      const ttsInterrupts: unknown[] = [];
      const loopArmed: unknown[] = [];
      let resetCount = 0;
      let startCount = 0;
      let capturedConfig: Record<string, any> | null = null;

      component.voiceTransport.set('backend_ws');
      component.voiceConversationActive.set(true);
      component.voiceConversationPaused.set(false);
      component.voiceConnection = {
        bargeIn: (payload?: unknown) => bargeIns.push(payload || {}),
        ttsInterrupted: (payload: unknown) => ttsInterrupts.push(payload),
        loopArmed: (payload: unknown) => loopArmed.push(payload),
      };
      component.ttsPlayback.reset = (_force?: boolean) => {
        resetCount += 1;
        component.ttsSpeaking.set(false);
        component.ttsPaused.set(false);
      };
      component.voiceLoop.startTurn = async (config: Record<string, any>) => {
        startCount += 1;
        capturedConfig = config;
        return true;
      };

      const started = await component.startVoiceTurn(true);
      component.ttsSpeaking.set(true);
      component.ttsPaused.set(false);
      capturedConfig?.onSpeechStart?.();

      return {
        started,
        startCount,
        recording: component.recording(),
        ttsSpeaking: component.ttsSpeaking(),
        resetCount,
        bargeIns,
        ttsInterrupts,
        loopArmed,
        oracleMessage: component.voiceOracleMessage(),
      };
    });

    expect(result).toMatchObject({
      started: true,
      startCount: 1,
      recording: true,
      ttsSpeaking: false,
      resetCount: 1,
      oracleMessage: 'Speech detected. The assistant will submit after silence.',
    });
    expect(result.bargeIns).toHaveLength(1);
    expect(result.ttsInterrupts).toEqual([{ reason: 'user_speech', surface: 'chat' }]);
    expect(result.loopArmed).toHaveLength(1);
    expect(result.loopArmed[0]).toMatchObject({
      surface: 'chat',
      mode: 'conversation_loop',
      auto_endpoint: true,
    });
  });

  test('repeats the last Chat answer by voice command without creating a new query', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(() => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const voiceCommands: unknown[] = [];
      const ttsFlushes: string[] = [];
      let resetCount = 0;
      let beginCount = 0;

      component.messages.set([
        { id: 'msg-user-repeat', role: 'user', content: 'Explique le réglage convoyeur.' },
        { id: 'msg-assistant-repeat', role: 'assistant', content: 'Dernière réponse Andritz à répéter.' },
      ]);
      component.voiceConnection = {
        voiceCommand: (command: string, transcript: string, payload: unknown) =>
          voiceCommands.push({ command, transcript, payload }),
      };
      component.ttsEnabled.set(true);
      component.transcribing.set(true);
      component.voicePartial.set('repete');
      component.resetTtsPipeline = () => {
        resetCount += 1;
      };
      component.beginTtsStream = () => {
        beginCount += 1;
      };
      component.flushTrailingTts = (text: string) => {
        ttsFlushes.push(text);
      };

      const handled = component.handleFinalVoiceTranscript('repete', {
        fallbackUsed: false,
        provider: 'openai',
      });

      return {
        handled,
        voiceCommands,
        ttsFlushes,
        resetCount,
        beginCount,
        transcribing: component.transcribing(),
        partial: component.voicePartial(),
        userInput: component.userInput,
        oracleMessage: component.voiceOracleMessage(),
      };
    });

    expect(result).toMatchObject({
      handled: true,
      ttsFlushes: ['Dernière réponse Andritz à répéter.'],
      resetCount: 1,
      beginCount: 1,
      transcribing: false,
      partial: '',
      userInput: '',
      oracleMessage: 'Voice command committed: repeat.',
    });
    expect(result.voiceCommands).toEqual([
      {
        command: 'repeat',
        transcript: 'repete',
        payload: { surface: 'chat' },
      },
    ]);
    expect(chatStreamRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(0);
  });

  test('keeps a Chat rephrase voice command local when no assistant answer exists', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(() => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const voiceCommands: unknown[] = [];
      const toasts: unknown[] = [];
      let rearmCount = 0;

      component.messages.set([]);
      component.voiceConnection = {
        voiceCommand: (command: string, transcript: string, payload: unknown) =>
          voiceCommands.push({ command, transcript, payload }),
      };
      component.toast.info = (message: string, title?: string) => {
        toasts.push({ message, title });
      };
      component.scheduleVoiceLoopRearm = () => {
        rearmCount += 1;
      };
      component.transcribing.set(true);
      component.voicePartial.set('reformule');

      const handled = component.handleFinalVoiceTranscript('reformule', {
        fallbackUsed: false,
        provider: 'openai',
      });

      return {
        handled,
        voiceCommands,
        toasts,
        rearmCount,
        transcribing: component.transcribing(),
        partial: component.voicePartial(),
        userInput: component.userInput,
        oracleMessage: component.voiceOracleMessage(),
      };
    });

    expect(result).toMatchObject({
      handled: true,
      rearmCount: 1,
      transcribing: false,
      partial: '',
      userInput: '',
      oracleMessage: 'Voice command committed: rephrase.',
    });
    expect(result.voiceCommands).toEqual([
      {
        command: 'rephrase',
        transcript: 'reformule',
        payload: { surface: 'chat' },
      },
    ]);
    expect(result.toasts).toEqual([{ message: 'No assistant answer to rephrase yet', title: 'Voice' }]);
    expect(chatStreamRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(0);
  });

  test('fills the Chat composer from server voice partial and final transcript events', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(() => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      component.chatVoiceSessionId = 'chat-dictation-session';
      component.transcribing.set(true);
      component.handleVoiceSessionEvent({
        id: 'evt-chat-dictation-partial',
        session_id: 'chat-dictation-session',
        type: 'text.partial',
        ts_ms: Date.now(),
        sequence: 1,
        payload: {
          text: 'Réglage convoyeur en cours',
        },
      });
      const partial = component.voicePartial();
      const oracleDuringPartial = component.voiceOracleMessage();
      component.handleVoiceSessionEvent({
        id: 'evt-chat-dictation-final',
        session_id: 'chat-dictation-session',
        type: 'text.final',
        ts_ms: Date.now(),
        sequence: 2,
        payload: {
          text: 'Réglage convoyeur final validé.',
          fallback_used: false,
        },
      });
      return {
        partial,
        oracleDuringPartial,
        finalPartial: component.voicePartial(),
        transcribing: component.transcribing(),
        userInput: component.userInput,
        voiceNotice: component.voiceNotice(),
        oracleStage: component.voiceOracleStage(),
        oracleMessage: component.voiceOracleMessage(),
      };
    });

    expect(result).toMatchObject({
      partial: 'Réglage convoyeur en cours',
      finalPartial: '',
      transcribing: false,
      userInput: 'Réglage convoyeur final validé.',
      voiceNotice: 'Transcript ready',
      oracleStage: 'committed',
      oracleMessage: 'Final transcript committed for this voice turn.',
    });
    expect(result.oracleDuringPartial).toContain('Réglage convoyeur en cours');
    await expect(page.locator('app-chat-panel textarea[name="userInput"]').first()).toHaveValue(
      'Réglage convoyeur final validé.',
    );
    expect(chatStreamRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(0);
  });

  test('keeps Chat voice state clear when microphone permission is denied', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(async () => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const toasts: unknown[] = [];
      let loopStartCount = 0;

      component.toast.error = (message: string, title?: string) => {
        toasts.push({ message, title });
      };
      component.voiceLoop.startTurn = async () => {
        loopStartCount += 1;
        throw new DOMException('Synthetic microphone permission denial', 'NotAllowedError');
      };
      component.recording.set(false);
      component.transcribing.set(false);
      component.voiceConversationActive.set(false);

      const started = await component.startVoiceTurn(false);

      return {
        started,
        loopStartCount,
        toasts,
        recording: component.recording(),
        transcribing: component.transcribing(),
        conversationActive: component.voiceConversationActive(),
        userInput: component.userInput,
      };
    });

    expect(result).toEqual({
      started: false,
      loopStartCount: 1,
      toasts: [{ message: 'Microphone access denied', title: 'Voice' }],
      recording: false,
      transcribing: false,
      conversationActive: false,
      userInput: '',
    });
    expect(chatStreamRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(0);
  });

  test('runs a Chat conversation loop ask turn and auto-sends the final transcript', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(async () => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const loopStarts: unknown[] = [];
      const loopArmed: unknown[] = [];
      const startTurnConfigs: Record<string, unknown>[] = [];
      const sentDrafts: string[] = [];

      component.canUseVoiceSession = () => true;
      component.ensureVoiceSession = () => {
        component.voiceConnection = {
          loopStart: (payload: unknown) => loopStarts.push(payload),
          loopArmed: (payload: unknown) => loopArmed.push(payload),
          loopStop: () => undefined,
          close: () => undefined,
        };
        return component.voiceConnection;
      };
      component.voiceLoop.startTurn = async (config: Record<string, unknown>) => {
        startTurnConfigs.push({
          autoEndpoint: config['autoEndpoint'],
          mimeType: config['mimeType'],
          timesliceMs: config['timesliceMs'],
          captureMode: config['captureMode'],
        });
        return true;
      };
      component.send = () => {
        sentDrafts.push(component.userInput);
      };

      await component.startConversationLoop();
      component.transcribing.set(true);
      component.handleVoiceSessionEvent({
        id: 'evt-chat-loop-final',
        session_id: component.chatVoiceSessionId,
        type: 'text.final',
        ts_ms: Date.now(),
        sequence: 3,
        payload: {
          text: 'Question orale Andritz envoyée automatiquement.',
          fallback_used: false,
        },
      });
      await new Promise((resolve) => setTimeout(resolve, 0));

      return {
        loopStarts,
        loopArmed,
        startTurnConfigs,
        sentDrafts,
        active: component.voiceConversationActive(),
        paused: component.voiceConversationPaused(),
        recording: component.recording(),
        transcribing: component.transcribing(),
        userInput: component.userInput,
        voiceNotice: component.voiceNotice(),
        oracleStage: component.voiceOracleStage(),
      };
    });

    expect(result.active).toBe(true);
    expect(result.paused).toBe(false);
    expect(result.recording).toBe(true);
    expect(result.transcribing).toBe(false);
    expect(result.userInput).toBe('Question orale Andritz envoyée automatiquement.');
    expect(result.sentDrafts).toEqual(['Question orale Andritz envoyée automatiquement.']);
    expect(result.voiceNotice).toBe('Transcript ready');
    expect(result.oracleStage).toBe('committed');
    expect(result.loopStarts).toHaveLength(1);
    expect(result.loopStarts[0]).toMatchObject({
      surface: 'chat',
      mode: 'conversation_loop',
      auto_endpoint: true,
    });
    expect(result.loopArmed).toHaveLength(1);
    expect(result.loopArmed[0]).toMatchObject({
      surface: 'chat',
      mode: 'conversation_loop',
      auto_endpoint: true,
    });
    expect(result.startTurnConfigs).toHaveLength(1);
    expect(result.startTurnConfigs[0]).toMatchObject({
      autoEndpoint: true,
      mimeType: 'audio/webm',
      timesliceMs: 1200,
    });
    expect(chatStreamRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(0);
  });

  test('stops the Chat conversation loop cleanly while transcription is in flight', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatSessionCreateRequests,
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-panel')).toBeVisible();

    const result = await page.evaluate(() => {
      const host = document.querySelector('app-chat-panel');
      const component = (window as any).ng.getComponent(host);
      const hardStops: unknown[] = [];
      const loopStops: unknown[] = [];
      let closeCount = 0;

      component.voiceConversationActive.set(true);
      component.voiceConversationPaused.set(false);
      component.recording.set(false);
      component.transcribing.set(true);
      component.voicePartial.set('transcription partielle à nettoyer');
      component.voiceConnection = {
        loopStop: (payload: unknown) => loopStops.push(payload),
        close: () => {
          closeCount += 1;
        },
      };
      component.voiceLoop.hardStop = (payload: unknown) => {
        hardStops.push(payload);
      };

      component.stopConversationLoop('user_stop');

      return {
        active: component.voiceConversationActive(),
        paused: component.voiceConversationPaused(),
        recording: component.recording(),
        transcribing: component.transcribing(),
        partial: component.voicePartial(),
        connection: component.voiceConnection,
        voiceNotice: component.voiceNotice(),
        oracleStage: component.voiceOracleStage(),
        oracleMessage: component.voiceOracleMessage(),
        hardStopCount: hardStops.length,
        loopStops,
        closeCount,
      };
    });

    expect(result).toMatchObject({
      active: false,
      paused: false,
      recording: false,
      transcribing: false,
      partial: '',
      connection: null,
      voiceNotice: 'Conversation stopped',
      oracleStage: 'idle',
      oracleMessage: 'Conversation loop stopped. Batch voice turns remain available.',
      hardStopCount: 1,
      closeCount: 1,
    });
    expect(result.loopStops).toEqual([{ surface: 'chat', reason: 'user_stop' }]);
    expect(chatStreamRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(0);
  });

  test('ignores direct Chat drop mode when document upload is disabled', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    await installAndritzMocks(page, {
      chatDocumentUploadEnabled: false,
      chatStreamRequests,
      chatUploadRequests,
    });

    await page.goto('/workspace/andritz/chat?mode=drop');
    await expect(page.getByRole('heading', { name: /Andritz QA Assistant/i })).toBeVisible();
    await expect(page.getByText(/Drop files/i)).toHaveCount(0);
    await expect(page.locator('input[type="file"]')).toHaveCount(0);

    const dataTransfer = await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['synthetic disabled upload'], 'disabled-chat-upload.pdf', { type: 'application/pdf' }));
      return transfer;
    });
    await page.locator('app-chat-workspace').dispatchEvent('drop', { dataTransfer });
    await page.waitForTimeout(100);
    expect(chatUploadRequests).toHaveLength(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Le mode drop désactivé doit rester une recherche texte.');
    await input.press('Enter');

    await expect(page.getByText('Le mode drop désactivé doit rester une recherche texte.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatUploadRequests).toHaveLength(0);
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Le mode drop désactivé doit rester une recherche texte.',
      context_id: null,
      context_mode: null,
      stream: true,
      include_sources: true,
    });
  });

  test('opens Chat system mode from the command palette without route mutation', async ({ page }) => {
    const chatSystemsRequests: string[] = [];
    await installAndritzMocks(page, {
      chatSystemsRequests,
      chatSystems: [
        {
          id: 'system-andritz-recherche',
          name: 'Andritz Recherche transverse',
          objective: 'Répondre avec le contexte transverse Andritz QA.',
          settings: { system_type: 'workspace_chat' },
          flow_definition: { variant: 'chat_transverse_v1' },
          status: 'active',
        },
      ],
    });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event('ck:command-palette:open')));
    await expect(page.locator('app-command-palette input[type="search"]')).toBeFocused();

    await page.getByRole('button', { name: /Discuter avec un système|Chat with a system/i }).click();

    await expect(page.locator('app-command-palette input[type="search"]')).toHaveCount(0);
    await expect(page).toHaveURL(/\/knowledge$/);
    await expect(page.getByText(/Discuter avec un système|Chat with a system/i).first()).toBeVisible();
    await expect(page.locator('app-chat-overlay .chat-overlay-expand')).toBeVisible();
    await expect(page.locator('app-chat-overlay app-chat-workspace')).toBeVisible();
    await expect.poll(() => chatSystemsRequests.length).toBeGreaterThan(0);
  });

  test('keeps selected Recherche system scope on the direct workspace chat route', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatSystemsRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatSystemsRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
      chatSystems: [
        {
          id: 'system-andritz-recherche',
          name: 'Andritz Recherche transverse',
          objective: 'Répondre avec le contexte transverse Andritz QA.',
          settings: { system_type: 'workspace_chat' },
          flow_definition: { variant: 'chat_transverse_v1' },
          status: 'active',
        },
      ],
    });

    await page.goto('/workspace/andritz/chat?mode=system&systemId=system-andritz-recherche');
    await expect(page.getByRole('heading', { name: /Andritz QA Assistant/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Settings/i })).toHaveAttribute('href', /\/workspace\/andritz\/chat-knowledge$/);
    await expect.poll(() => chatSystemsRequests.length).toBeGreaterThan(0);
    await expect(page.getByText('System chat').first()).toBeVisible();
    await expect(page.getByText('Répondre avec le contexte transverse Andritz QA.')).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Route focus directe avec système Recherche.');
    await input.press('Enter');

    await expect(page.getByText('Route focus directe avec système Recherche.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        system_id: 'system-andritz-recherche',
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Route focus directe avec système Recherche.',
      agent_id: 'system-andritz-recherche',
      session_id: 'chat-session-andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('uploads a mocked PDF drop-and-ask document before asking', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    expect(chatUploadRequests[0]).toContain('andritz-chat-drop.pdf');
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat PDF note|andritz-chat-drop\.pdf/i).first()).toBeVisible();
    await expect(page.getByText('3 pages')).toBeVisible();
    await expect(page.getByText('128 tokens')).toBeVisible();
    await expect(page.getByText('2 chunks')).toBeVisible();
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.pdf'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
      ttl_hours: 24,
    });

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Que dit le PDF ajouté ?');
    await input.press('Enter');

    await expect(page.getByText('Que dit le PDF ajouté ?')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Que dit le PDF ajouté ?',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('keeps a large mocked Chat drop-and-ask upload responsive before asking', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      chatUploadDelayMs: 650,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-large.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.alloc(512 * 1024, 'A'),
    });

    await expect(page.getByText(/Indexing 1/i)).toBeVisible();
    await expect.poll(() => chatUploadRequests.length).toBe(1);
    expect(chatUploadRequests[0]).toContain('andritz-chat-large.xlsx');
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Indexing 1/i)).toHaveCount(0);
    await expect(page.getByText(/Andritz chat large workbook|andritz-chat-large\.xlsx/i).first()).toBeVisible();
    await expect(page.getByText('18 pages')).toBeVisible();
    await expect(page.getByText('24.6k tokens')).toBeVisible();
    await expect(page.getByText('24 chunks')).toBeVisible();
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-large.xlsx'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
      ttl_hours: 24,
    });

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Résume le classeur ajouté.');
    await input.press('Enter');

    await expect(page.getByText('Résume le classeur ajouté.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Résume le classeur ajouté.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('shows a backend rejection for unsupported Chat drop-and-ask files', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatUploadRequests,
      contextCreateRequests,
      chatUploadShouldFail: true,
      chatUploadFailureStatus: 400,
      chatUploadFailureDetail: 'Type de fichier non supporte pour le drop-and-ask.',
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-unsupported.bin',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('Synthetic unsupported Andritz chat document.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    expect(chatUploadRequests[0]).toContain('andritz-chat-unsupported.bin');
    await expect(
      page.getByRole('alert', { name: /Type de fichier non supporte pour le drop-and-ask/i }),
    ).toBeVisible();
    expect(contextCreateRequests).toHaveLength(0);
    await expect(page.getByText(/andritz-chat-unsupported\.bin/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Persist$/i })).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('La recherche reste disponible après un type refusé.');
    await input.press('Enter');

    await expect(page.getByText('La recherche reste disponible après un type refusé.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'La recherche reste disponible après un type refusé.',
      context_id: null,
      context_mode: null,
      stream: true,
      include_sources: true,
    });
  });

  test('shows a recoverable error when Chat drop-and-ask upload fails', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatUploadRequests,
      contextCreateRequests,
      chatUploadShouldFail: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz failed upload evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect(page.getByRole('alert', { name: /Mocked upload failure/i })).toBeVisible();
    expect(contextCreateRequests).toHaveLength(0);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Persist$/i })).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('La recherche reste utilisable après un upload refusé.');
    await input.press('Enter');

    await expect(page.getByText('La recherche reste utilisable après un upload refusé.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'La recherche reste utilisable après un upload refusé.',
      context_id: null,
      context_mode: null,
      stream: true,
      include_sources: true,
    });
  });

  test('keeps failed Chat drop-and-ask files out of the ephemeral context', async ({ page }) => {
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatUploadRequests,
      contextCreateRequests,
      chatUploadPartialFailure: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles([
      {
        name: 'andritz-chat-drop.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Synthetic Andritz successful upload evidence.'),
      },
      {
        name: 'andritz-chat-drop-rejected.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Synthetic Andritz rejected upload evidence.'),
      },
    ]);

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByRole('alert', { name: /1\/2 indexed · 1 failed/i })).toBeVisible();
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByText('andritz-chat-drop-rejected.txt')).toHaveCount(0);
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
      ttl_hours: 24,
    });
  });

  test('does not show a drop-and-ask doc as attached when context creation fails', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextCreateShouldFail: true,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz failed context create evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
    });
    await expect(page.getByRole('alert', { name: /Could not create a temporary chat context/i })).toBeVisible();
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Persist$/i })).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds sans contexte temporaire après échec.');
    await input.press('Enter');

    await expect(page.getByText('Réponds sans contexte temporaire après échec.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds sans contexte temporaire après échec.',
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
    });
  });

  test('keeps Chat drop-and-ask usable when document metadata fails', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatUploadRequests,
      contextCreateRequests,
      chatMetadataShouldFail: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz metadata failure evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText('andritz-chat-drop.txt').first()).toBeVisible();
    await expect(page.locator('.t-doc-spin')).toHaveCount(0);
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
      ttl_hours: 24,
    });

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Utilise le fichier même si les métadonnées sont indisponibles.');
    await input.press('Enter');

    await expect(page.getByText('Utilise le fichier même si les métadonnées sont indisponibles.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Utilise le fichier même si les métadonnées sont indisponibles.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      stream: true,
      include_sources: true,
    });
  });

  test('renders Chat document metadata facts after drop-and-ask upload', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatUploadRequests,
      contextCreateRequests,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz metadata facts evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText('Andritz chat drop note')).toBeVisible();
    await expect(page.locator('.t-doc-spin')).toHaveCount(0);
    await expect(page.getByText('1 page')).toBeVisible();
    await expect(page.getByText('42 tokens')).toBeVisible();
    await expect(page.getByText('1 chunks')).toBeVisible();
    await expect(page.locator('.t-doc-kw')).toHaveCount(3);
    await expect(page.locator('.t-doc-kw').filter({ hasText: /^andritz$/ })).toBeVisible();
    await expect(page.locator('.t-doc-kw').filter({ hasText: /^qa$/ })).toBeVisible();
    await expect(page.locator('.t-doc-kw').filter({ hasText: /^drop-and-ask$/ })).toBeVisible();
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
      ttl_hours: 24,
    });

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Utilise les faits du fichier ajouté.');
    await input.press('Enter');

    await expect(page.getByText('Utilise les faits du fichier ajouté.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Utilise les faits du fichier ajouté.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      stream: true,
      include_sources: true,
    });
  });

  test('keeps long Chat document metadata keywords compact', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatUploadRequests,
      contextCreateRequests,
      chatMetadataLongKeywords: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz long metadata keyword evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText('Andritz chat keyword stress note')).toBeVisible();
    await expect(page.locator('.t-doc-kw')).toHaveCount(4);
    await expect(page.getByText('screening')).toBeVisible();
    await expect(page.getByText('filtration')).toBeVisible();
    await expect(page.getByText('centrifuge')).toBeVisible();
    await expect(page.getByText('maintenance')).toBeVisible();
    await expect(page.getByText('operator-training')).toHaveCount(0);
    await expect(page.getByText('safety-procedure')).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Résume le fichier malgré les métadonnées longues.');
    await input.press('Enter');

    await expect(page.getByText('Résume le fichier malgré les métadonnées longues.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Résume le fichier malgré les métadonnées longues.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      stream: true,
      include_sources: true,
    });
  });

  test('shows a non-destructive error state when Collections cannot load', async ({ page }) => {
    await installAndritzMocks(page, { collectionsShouldFail: true });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.getByText('Unable to load collections')).toBeVisible();
    await expect(page.getByText('Collections service unavailable')).toBeVisible();
    await expect(page.getByRole('button', { name: /Retry/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /New collection/i })).toBeDisabled();
    await expect(page.getByRole('button', { name: /Upload/i })).toBeDisabled();
    await expect(page.locator('a[href="/knowledge/andritz-qa"]')).toHaveCount(0);
    await expect(page.locator('[title="Delete collection"]')).toHaveCount(0);
  });

  test('creates a synthetic collection only after explicit user input', async ({ page }) => {
    const collectionCreateRequests: string[] = [];
    await installAndritzMocks(page, { collectionCreateRequests });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.getByRole('button', { name: /New collection/i }).click();

    const nameInput = page.getByPlaceholder('e.g. policies, research');
    const createButton = page.getByRole('button', { name: /^Create$/ });
    await expect(nameInput).toBeVisible();
    await expect(createButton).toBeDisabled();
    await nameInput.fill('andritz-qa-scratch');
    await expect(createButton).toBeEnabled();
    await expect.poll(() => collectionCreateRequests.length).toBe(0);

    await createButton.click();

    await expect.poll(() => collectionCreateRequests.length).toBe(1);
    const createParams = new URLSearchParams(collectionCreateRequests[0].replace(/^\?/, ''));
    expect(createParams.get('collection_name')).toBe('andritz-qa-scratch');
    await expect(page.getByText('Collection "andritz-qa-scratch" created')).toBeVisible();
    await expect(nameInput).toHaveCount(0);
    await expect(page.locator('a[href="/knowledge/andritz-qa-scratch"]')).toBeVisible();
  });

  test('does not show a synthetic collection when collection creation is forbidden', async ({ page }) => {
    const collectionCreateRequests: string[] = [];
    await installAndritzMocks(page, {
      collectionCreateRequests,
      collectionCreateShouldFail: true,
    });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.getByRole('button', { name: /New collection/i }).click();

    const nameInput = page.getByPlaceholder('e.g. policies, research');
    await expect(nameInput).toBeVisible();
    await nameInput.fill('andritz-qa-denied');
    await page.getByRole('button', { name: /^Create$/ }).click();

    await expect.poll(() => collectionCreateRequests.length).toBe(1);
    const createParams = new URLSearchParams(collectionCreateRequests[0].replace(/^\?/, ''));
    expect(createParams.get('collection_name')).toBe('andritz-qa-denied');
    await expect(page.getByText('Mocked collection create permission denied')).toBeVisible();
    await expect(nameInput).toBeVisible();
    await expect(page.locator('a[href="/knowledge/andritz-qa-denied"]')).toHaveCount(0);
    await expect(page.locator('a[href="/knowledge/andritz-qa"]')).toBeVisible();
  });

  test('requires typed confirmation before deleting a collection without real data', async ({ page }) => {
    const collectionDeleteRequests: string[] = [];
    await installAndritzMocks(page, { collectionDeleteRequests });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.locator('a[href="/knowledge/andritz-qa"]')).toBeVisible();
    await page.locator('[title="Delete collection"]').first().click();

    await expect.poll(() => collectionDeleteRequests.length).toBe(0);
    const confirmDialog = page.locator('app-confirm-dialog').filter({ hasText: 'Delete collection andritz-qa' });
    await expect(confirmDialog.getByText('All documents and chunks in this collection will be deleted. This cannot be undone.')).toBeVisible();

    const confirmInput = confirmDialog.getByPlaceholder('andritz-qa');
    const confirmButton = confirmDialog.getByRole('button', { name: 'Delete collection' });
    await expect(confirmButton).toBeDisabled();
    await confirmInput.fill('andritz');
    await expect(confirmButton).toBeDisabled();
    await confirmInput.fill('andritz-qa');
    await expect(confirmButton).toBeEnabled();
    await expect.poll(() => collectionDeleteRequests.length).toBe(0);

    await confirmButton.click();

    await expect.poll(() => collectionDeleteRequests).toEqual(['/documents/collections/andritz-qa']);
    await expect(page.locator('a[href="/knowledge/andritz-qa"]')).toHaveCount(0);
  });

  test('keeps a collection visible when collection deletion is forbidden', async ({ page }) => {
    const collectionDeleteRequests: string[] = [];
    await installAndritzMocks(page, {
      collectionDeleteRequests,
      collectionDeleteShouldFail: true,
    });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.locator('a[href="/knowledge/andritz-qa"]')).toBeVisible();
    await page.locator('[title="Delete collection"]').first().click();

    const confirmDialog = page.locator('app-confirm-dialog').filter({ hasText: 'Delete collection andritz-qa' });
    await expect(confirmDialog.getByPlaceholder('andritz-qa')).toBeVisible();
    await confirmDialog.getByPlaceholder('andritz-qa').fill('andritz-qa');
    await expect.poll(() => collectionDeleteRequests.length).toBe(0);
    await confirmDialog.getByRole('button', { name: 'Delete collection' }).click();

    await expect.poll(() => collectionDeleteRequests).toEqual(['/documents/collections/andritz-qa']);
    await expect(page.getByText('Mocked collection delete permission denied')).toBeVisible();
    await expect(confirmDialog).toHaveCount(0);
    await expect(page.locator('a[href="/knowledge/andritz-qa"]')).toBeVisible();
  });

  test('renders only current permitted system bindings in collection detail', async ({ page }) => {
    const chatSystemsRequests: string[] = [];
    await installAndritzMocks(page, {
      chatSystemsRequests,
      chatSystems: [
        {
          id: 'system-visible-andritz',
          name: 'Visible Andritz system',
          objective: 'Repondre avec le contexte visible Andritz QA.',
          flow_definition: { collections: ['andritz-qa'] },
          status: 'active',
        },
        {
          id: 'system-stale-andritz',
          name: 'Stale Andritz system',
          objective: 'This system still references an old Andritz collection slug.',
          flow_definition: { collections: ['andritz-legacy'] },
          status: 'active',
        },
      ],
    });

    await page.goto('/knowledge/andritz-qa');
    await expect(page.getByRole('button', { name: /^Bindings$/ })).toBeVisible();
    await expect.poll(() => chatSystemsRequests.length).toBeGreaterThan(0);

    await page.getByRole('button', { name: /^Bindings$/ }).click();
    await expect(page.getByText('Visible Andritz system')).toBeVisible();
    await expect(page.getByText('Repondre avec le contexte visible Andritz QA.')).toBeVisible();
    await expect(page.getByText('Stale Andritz system')).toHaveCount(0);
    await expect(page.getByText('This system still references an old Andritz collection slug.')).toHaveCount(0);
    await expect(page.getByText('Hidden Andritz system')).toHaveCount(0);
    await expect(page.getByText('Do not expose hidden Andritz context.')).toHaveCount(0);
    await expect(page.getByText('Bindings overview')).toHaveCount(0);
  });

  test('dedupes duplicate OCR facts in collection detail without real data', async ({ page }) => {
    const documentFactRequests: string[] = [];
    const duplicatedOcrText = 'ANDRITZ OCR DUPLICATE BLOCK';
    await installAndritzMocks(page, {
      documentFactRequests,
      documentFacts: [
        {
          id: 'ocr-fact-1',
          document_id: 'doc-andritz-ocr',
          document_filename: 'andritz-ocr-photo.jpg',
          semantic_type: 'document_ocr_text',
          page: 2,
          content: duplicatedOcrText,
          qualifiers: { provider: 'PP-OCR', confidence: 0.93, bbox: [10, 20, 110, 42] },
        },
        {
          id: 'ocr-fact-duplicate',
          document_id: 'doc-andritz-ocr',
          document_filename: 'andritz-ocr-photo.jpg',
          semantic_type: 'document_ocr_text',
          page: 2,
          content: duplicatedOcrText,
          qualifiers: { provider: 'PP-OCR', confidence: 0.91, bbox: [10, 20, 110, 42] },
        },
        {
          id: 'ocr-warning-1',
          document_id: 'doc-andritz-ocr',
          document_filename: 'andritz-ocr-photo.jpg',
          semantic_type: 'visual_warning',
          page: 2,
          content: 'Andritz OCR low contrast warning',
          qualifiers: { provider: 'vision-fallback', warning: 'Low contrast area' },
        },
      ],
    });

    await page.goto('/knowledge/andritz-qa');
    await expect(page.getByRole('tab', { name: 'OCR' })).toBeVisible();
    await page.locator('app-knowledge-view').evaluate((host) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(host) as { onTabChange?: (id: string) => void } | undefined;
      if (!component?.onTabChange) throw new Error('KnowledgeViewComponent instance not found');
      component.onTabChange('ocr');
    });

    await expect.poll(() => documentFactRequests.length).toBe(4);
    const semanticTypes = documentFactRequests
      .map((search) => new URLSearchParams(search.replace(/^\?/, '')).get('semantic_type'))
      .sort();
    expect(semanticTypes).toEqual([
      'document_ocr_text',
      'visual_parameter',
      'visual_text_block',
      'visual_warning',
    ]);
    await expect(page.getByText('2 loaded / 3 total OCR or visual facts')).toBeVisible();
    await expect(page.getByText(duplicatedOcrText)).toHaveCount(1);
    await expect(page.getByText('Andritz OCR low contrast warning')).toBeVisible();
    await expect(page.getByText('Provider: PP-OCR')).toBeVisible();
    await expect(page.getByText('Low contrast area')).toBeVisible();
  });

  test('opens the collection document inventory drawer without real data', async ({ page }) => {
    const documentListRequests: string[] = [];
    await installAndritzMocks(page, { documentListRequests });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    await expect.poll(() => documentListRequests.length).toBe(1);
    const params = new URLSearchParams(documentListRequests[0].replace(/^\?/, ''));
    expect(params.get('collection_name')).toBe('andritz-qa');
    expect(params.get('limit')).toBe('100');
    expect(params.get('offset')).toBe('0');

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'andritz-qa-safe.pdf' });
    await expect(documentsDrawer.getByRole('heading', { name: 'Documents' })).toBeVisible();
    await expect(documentsDrawer.getByText('andritz-qa', { exact: true })).toBeVisible();
    await expect(documentsDrawer.getByText('1–1 / 1')).toBeVisible();
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
    await expect(documentsDrawer.getByText('3 chunks')).toBeVisible();
    await expect(documentsDrawer.getByText('application/pdf')).toBeVisible();
    await expect(documentsDrawer.locator('[title="Preview"]')).toBeVisible();
    await expect(documentsDrawer.locator('[title="Delete document"]')).toBeVisible();
    await expect(documentsDrawer.getByText('Unable to load documents')).toHaveCount(0);
    await expect(documentsDrawer.getByText('Empty collection')).toHaveCount(0);
  });

  test('requires explicit confirmation before deleting a collection document without real data', async ({ page }) => {
    const documentDeleteRequests: string[] = [];
    await installAndritzMocks(page, { documentDeleteRequests });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'andritz-qa-safe.pdf' });
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
    await documentsDrawer.locator('[title="Delete document"]').click();

    await expect.poll(() => documentDeleteRequests.length).toBe(0);
    const confirmDialog = page.locator('app-confirm-dialog').filter({ hasText: 'Delete andritz-qa-safe.pdf' });
    await expect(confirmDialog.getByText('This document and its chunks will be removed from the collection.')).toBeVisible();
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();

    await confirmDialog.getByRole('button', { name: /^Delete$/ }).click();

    await expect.poll(() => documentDeleteRequests.length).toBe(1);
    const deleteParams = new URLSearchParams(documentDeleteRequests[0].replace(/^\?/, ''));
    expect(deleteParams.get('collection_name')).toBe('andritz-qa');
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toHaveCount(0);
  });

  test('keeps a collection document visible when document deletion is forbidden', async ({ page }) => {
    const documentDeleteRequests: string[] = [];
    await installAndritzMocks(page, {
      documentDeleteRequests,
      documentDeleteShouldFail: true,
    });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'andritz-qa-safe.pdf' });
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
    await documentsDrawer.locator('[title="Delete document"]').click();

    const confirmDialog = page.locator('app-confirm-dialog').filter({ hasText: 'Delete andritz-qa-safe.pdf' });
    await expect(confirmDialog.getByText('This document and its chunks will be removed from the collection.')).toBeVisible();
    await expect.poll(() => documentDeleteRequests.length).toBe(0);
    await confirmDialog.getByRole('button', { name: /^Delete$/ }).click();

    await expect.poll(() => documentDeleteRequests.length).toBe(1);
    const deleteParams = new URLSearchParams(documentDeleteRequests[0].replace(/^\?/, ''));
    expect(deleteParams.get('collection_name')).toBe('andritz-qa');
    await expect(page.getByText('Mocked document delete permission denied')).toBeVisible();
    await expect(confirmDialog).toHaveCount(0);
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
  });

  test('opens a collection document preview fallback without real data', async ({ page }) => {
    const documentListRequests: string[] = [];
    const collectionPreviewRequests: string[] = [];
    await installAndritzMocks(page, { documentListRequests, collectionPreviewRequests });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'andritz-qa-safe.pdf' });
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
    await documentsDrawer.locator('[title="Preview"]').click();

    await expect.poll(() => documentListRequests.length).toBe(1);
    await expect.poll(() => collectionPreviewRequests.length).toBe(1);
    const listParams = new URLSearchParams(documentListRequests[0].replace(/^\?/, ''));
    expect(listParams.get('collection_name')).toBe('andritz-qa');
    const previewParams = new URLSearchParams(collectionPreviewRequests[0].replace(/^\?/, ''));
    expect(previewParams.get('collection_name')).toBe('andritz-qa');

    const previewDrawer = page.locator('app-drawer').filter({ hasText: 'Document preview' }).filter({ hasText: 'Open file' });
    await expect(previewDrawer.getByRole('heading', { name: 'andritz-qa-safe.pdf' })).toBeVisible();
    await expect(previewDrawer.getByText('This document is a binary file. Open or download it to view.')).toBeVisible();
    await expect(previewDrawer.getByRole('link', { name: /Open file/i })).toHaveAttribute(
      'href',
      /\/api\/v1\/documents\/doc-andritz-qa\/download\?collection_name=andritz-qa$/,
    );
    await expect(previewDrawer.getByText('Unable to load documents')).toHaveCount(0);
  });

  test('renders unsafe collection preview content as inert text', async ({ page }) => {
    const collectionPreviewRequests: string[] = [];
    await installAndritzMocks(page, { collectionPreviewRequests, collectionPreviewUnsafeContent: true });
    await page.addInitScript(() => {
      (window as Window & { __andritzPreviewXss?: boolean }).__andritzPreviewXss = false;
    });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'andritz-qa-safe.pdf' });
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
    await documentsDrawer.locator('[title="Preview"]').click();

    await expect.poll(() => collectionPreviewRequests.length).toBe(1);
    const previewParams = new URLSearchParams(collectionPreviewRequests[0].replace(/^\?/, ''));
    expect(previewParams.get('collection_name')).toBe('andritz-qa');

    const previewDrawer = page.locator('app-drawer').filter({ hasText: 'Unsafe Andritz preview' });
    await expect(previewDrawer.getByRole('heading', { name: 'andritz-qa-safe.pdf' })).toBeVisible();
    await expect(previewDrawer.getByText('<h1>Unsafe Andritz preview</h1>')).toBeVisible();
    await expect(previewDrawer.getByText('window.__andritzPreviewXss = true')).toBeVisible();
    await expect(previewDrawer.getByRole('link', { name: /Open file/i })).toHaveCount(0);
    await expect.poll(async () => page.evaluate(() => Boolean((window as Window & { __andritzPreviewXss?: boolean }).__andritzPreviewXss))).toBe(false);
  });

  test('does not leak stale collection preview content when preview is forbidden', async ({ page }) => {
    const collectionPreviewRequests: string[] = [];
    await installAndritzMocks(page, {
      collectionPreviewRequests,
      collectionPreviewForbiddenAfterFirstSuccess: true,
    });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'andritz-qa-safe.pdf' });
    await expect(documentsDrawer.getByText('andritz-qa-safe.pdf')).toBeVisible();
    await documentsDrawer.locator('[title="Preview"]').click();

    await expect.poll(() => collectionPreviewRequests.length).toBe(1);
    const firstPreviewParams = new URLSearchParams(collectionPreviewRequests[0].replace(/^\?/, ''));
    expect(firstPreviewParams.get('collection_name')).toBe('andritz-qa');

    const firstPreviewDrawer = page.locator('app-drawer').filter({ hasText: 'Document preview' }).filter({ hasText: 'Open file' });
    await expect(firstPreviewDrawer.getByRole('heading', { name: 'andritz-qa-safe.pdf' })).toBeVisible();
    await expect(firstPreviewDrawer.getByRole('link', { name: /Open file/i })).toHaveAttribute(
      'href',
      /\/api\/v1\/documents\/doc-andritz-qa\/download\?collection_name=andritz-qa$/,
    );
    await firstPreviewDrawer.getByRole('button', { name: 'Close' }).click();
    await expect(firstPreviewDrawer).toHaveCount(0);

    await documentsDrawer.locator('[title="Preview"]').click();

    await expect.poll(() => collectionPreviewRequests.length).toBe(2);
    const secondPreviewParams = new URLSearchParams(collectionPreviewRequests[1].replace(/^\?/, ''));
    expect(secondPreviewParams.get('collection_name')).toBe('andritz-qa');

    const previewDrawer = page.locator('app-drawer').filter({ hasText: 'Mocked collection preview permission denied' });
    await expect(previewDrawer.getByRole('heading', { name: 'andritz-qa-safe.pdf' })).toBeVisible();
    await expect(previewDrawer.getByText('Mocked collection preview permission denied')).toBeVisible();
    await expect(previewDrawer.getByRole('link', { name: /Open file/i })).toHaveCount(0);
    await expect(previewDrawer.getByText('This document is a binary file. Open or download it to view.')).toHaveCount(0);
    await expect(previewDrawer.getByText('Unsafe Andritz preview')).toHaveCount(0);
  });

  test('shows an empty collection state only after a successful empty inventory load', async ({ page }) => {
    const documentListRequests: string[] = [];
    await installAndritzMocks(page, { documentListEmpty: true, documentListRequests });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    await expect.poll(() => documentListRequests.length).toBe(1);
    const params = new URLSearchParams(documentListRequests[0].replace(/^\?/, ''));
    expect(params.get('collection_name')).toBe('andritz-qa');
    expect(params.get('limit')).toBe('100');
    expect(params.get('offset')).toBe('0');

    const documentsDrawer = page.locator('app-drawer').filter({ hasText: 'Empty collection' });
    await expect(documentsDrawer.getByRole('heading', { name: 'Documents' })).toBeVisible();
    await expect(documentsDrawer.getByText('andritz-qa', { exact: true })).toBeVisible();
    await expect(documentsDrawer.getByText('Empty collection')).toBeVisible();
    await expect(documentsDrawer.getByText('Upload documents to this collection.')).toBeVisible();
    await expect(documentsDrawer.getByText('Unable to load documents')).toHaveCount(0);
    await expect(documentsDrawer.locator('[title="Preview"]')).toHaveCount(0);
    await expect(documentsDrawer.locator('[title="Delete document"]')).toHaveCount(0);
  });

  test('shows a non-destructive error state when collection documents cannot load', async ({ page }) => {
    await installAndritzMocks(page, { documentListShouldFail: true });

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await page.locator('[title="Browse documents"]').first().click();

    await expect(page.getByText('Unable to load documents')).toBeVisible();
    await expect(page.getByText('Document inventory unavailable')).toBeVisible();
    await expect(page.getByRole('button', { name: /Retry/i })).toBeVisible();
    await expect(page.locator('[title="Delete document"]')).toHaveCount(0);
  });

  test('shows an inline error state when collection search fails', async ({ page }) => {
    await installAndritzMocks(page, { searchShouldFail: true });

    await page.goto('/knowledge');
    await page.getByRole('button', { name: /^Search$/ }).first().click();
    await page.getByPlaceholder('Ask semantic question…').fill('pump maintenance');
    await page.getByRole('button', { name: /^Search$/ }).last().click();

    await expect(page.getByText('Unable to search knowledge')).toBeVisible();
    await expect(
      page.locator('app-empty-state').filter({ hasText: 'Unable to search knowledge' }).filter({ hasText: 'Search service unavailable' }),
    ).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA result')).toHaveCount(0);
  });

  test('clears stale search results when opening a new search context', async ({ page }) => {
    await installAndritzMocks(page);

    await page.goto('/knowledge');
    await page.getByRole('button', { name: /^Search$/ }).first().click();
    await page.getByPlaceholder('Ask semantic question…').fill('pump maintenance');
    await page.getByRole('button', { name: /^Search$/ }).last().click();
    await expect(page.getByText('Synthetic Andritz QA result')).toBeVisible();

    await page.getByRole('button', { name: 'Close' }).click();
    await page.locator('[title="Search in this collection"]').first().click();

    await expect(page.getByPlaceholder('Ask semantic question…')).toHaveValue('');
    await expect(page.getByText('Synthetic Andritz QA result')).toHaveCount(0);
    await expect(page.locator('app-empty-state').filter({ hasText: /No results|Unable to search knowledge/ })).toHaveCount(0);
  });

  test('keeps primary Andritz surfaces reachable on mobile viewport', async ({ page }) => {
    await installAndritzMocks(page);
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto('/connectors');
    await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Open secure deposit/i })).toBeVisible();

    await page.goto('/connectors/sftp');
    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Live upload monitor|No active SFTP transfer/i);

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Andritz QA|andritz-qa/i);

    await page.goto('/knowledge/capture?exp=v0');
    await expect(page.locator('body')).toContainText(/Capture sessions|Sessions de capture|New session|Nouvelle capture/i);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Quick ask|Question rapide|Ask|Posez votre question/i);
  });

  test('enables new capture for reviewer IAM matrix', async ({ page }) => {
    await installAndritzMocks(page, { roleTemplate: 'workspace_reviewer' });

    await page.goto('/knowledge/capture?exp=v0');
    const newCapture = page
      .getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i })
      .first();
    await expect(newCapture).toBeVisible();
    await expect(newCapture).toBeEnabled();
  });

  test('reopens an active Knowledge Capture session without creating or publishing data', async ({ page }) => {
    const captureMutations: string[] = [];
    const proposalRequests: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.includes('/api/v1/knowledge-capture/proposals')) {
        proposalRequests.push(`${request.method()} ${url.pathname}${url.search}`);
      }
      if (
        url.pathname.includes('/api/v1/knowledge-capture')
        && ['POST', 'PATCH', 'DELETE'].includes(request.method())
      ) {
        captureMutations.push(`${request.method()} ${url.pathname}`);
      }
    });
    await installAndritzMocks(page, { activeCaptureSession: true });

    await page.goto('/knowledge/capture?exp=v0');
    await expect(page.getByText('Andritz QA active capture').first()).toBeVisible();
    await page.getByText('Andritz QA active capture').first().click();

    await expect(page.getByRole('heading', { name: 'Andritz QA active capture' })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Échange capturé|Captured exchange|The expert drives/i);
    const state = await page.locator('app-knowledge-capture').evaluate((element) => {
      const ng = (window as unknown as { ng?: { getComponent?: (el: Element) => unknown } }).ng;
      const component = ng?.getComponent?.(element) as
        | {
            activeSurface?: () => string;
            session?: () => { id?: string; status?: string; title?: string } | null;
            proposal?: () => unknown;
          }
        | undefined;
      return {
        activeSurface: component?.activeSurface?.(),
        session: component?.session?.(),
        hasProposal: Boolean(component?.proposal?.()),
      };
    });
    expect(state).toMatchObject({
      activeSurface: 'session',
      session: {
        id: 'session-andritz-free-smoke',
        status: 'active',
        title: 'Andritz QA active capture',
      },
      hasProposal: false,
    });
    expect(proposalRequests).toContain('GET /api/v1/knowledge-capture/proposals?session_id=session-andritz-free-smoke');
    expect(captureMutations).toEqual([]);
  });

  test('requires explicit confirmation before deleting a Knowledge Capture session', async ({ page }) => {
    const captureDeleteRequests: string[] = [];
    await installAndritzMocks(page, { acceptedProposal: true, captureDeleteRequests });

    await page.goto('/knowledge/capture?exp=v0');
    const sessionCard = page.locator('[role="button"]').filter({ hasText: 'Andritz QA capture' }).first();
    await expect(sessionCard).toBeVisible();

    await sessionCard.locator('button[title="Supprimer la session"]').click();
    await expect(sessionCard).toContainText(/Supprimer définitivement cette session/i);
    expect(captureDeleteRequests).toEqual([]);

    await sessionCard.getByRole('button', { name: /Annuler/i }).click();
    await expect(sessionCard).not.toContainText(/Supprimer définitivement cette session/i);
    expect(captureDeleteRequests).toEqual([]);

    await sessionCard.locator('button[title="Supprimer la session"]').click();
    await sessionCard.getByRole('button', { name: /^Supprimer$/i }).click();

    await expect.poll(() => captureDeleteRequests).toEqual(['/knowledge-capture/sessions/session-andritz-qa']);
  });

  test('requires an explicit publish click for an accepted capture proposal', async ({ page }) => {
    let publishRequests = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals/proposal-andritz-qa/publish')) {
        publishRequests += 1;
      }
    });
    await installAndritzMocks(page, { acceptedProposal: true });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /Andritz QA accepted capture report/i }).click();
    await expect(page.getByRole('heading', { name: /Andritz QA accepted capture report/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Rapport final éditable|Editable final report/i);
    expect(publishRequests).toBe(0);

    await page.getByRole('button', { name: /Continuer vers publication|Continue to publication/i }).click();
    await expect(page.locator('body')).toContainText(/Aperçu de la fiche|Sheet preview/i);
    expect(publishRequests).toBe(0);

    await page.getByRole('button', { name: /Publier dans la base de connaissances|Publish to knowledge base/i }).click();
    await expect.poll(() => publishRequests).toBe(1);
    await expect(page.locator('body')).toContainText(/Andritz QA accepted capture report/i);
  });

  test('opens a Knowledge Capture report source preview at the referenced page', async ({ page }) => {
    const sourcePreviewRequests: string[] = [];
    let publishRequests = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals/proposal-andritz-qa/publish')) {
        publishRequests += 1;
      }
    });
    await installAndritzMocks(page, {
      acceptedProposal: true,
      sourcePreviewRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /Andritz QA accepted capture report/i }).click();
    await expect(page.getByRole('heading', { name: /Andritz QA accepted capture report/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Rapport final éditable|Editable final report/i);

    await page.getByRole('button', { name: /Andritz QA safe document · page 2/i }).click();

    await expect.poll(() => sourcePreviewRequests.length).toBe(1);
    const params = new URLSearchParams(sourcePreviewRequests[0].replace(/^\?/, ''));
    expect(params.get('collection_name')).toBe('andritz-qa');
    expect(params.get('filename')).toBe('andritz-qa-safe.pdf');
    await expect(page.getByRole('heading', { name: /Andritz QA safe document · page 2/i })).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA source preview full text.')).toBeVisible();
    await expect(page.locator('#omnirag-hl-anchor')).toContainText('Synthetic Andritz QA source snippet.');

    const previewState = await page.evaluate(() => {
      const host = document.querySelector('app-knowledge-capture');
      const component = (window as any).ng?.getComponent?.(host);
      return {
        open: component?.sourcePreviewOpen?.(),
        page: component?.sourcePreviewPage?.(),
        highlight: component?.sourcePreviewHighlight?.(),
        title: component?.sourcePreviewTitle?.(),
      };
    });

    expect(previewState).toMatchObject({
      open: true,
      page: 2,
      highlight: 'Synthetic Andritz QA source snippet.',
      title: 'Andritz QA safe document · page 2',
    });
    expect(publishRequests).toBe(0);
  });

  test('keeps Knowledge Capture preparation blocked when the title is blank', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, { capturePlanRequests });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await expect(page.locator('body')).toContainText(/Préparer la capture|Prepare the capture/i);
    const continueButton = page.getByRole('button', { name: /^Continuer$|^Continue$/i });
    await expect(continueButton).toBeDisabled();
    await expect(page.locator('body')).toContainText(/Renseignez un titre de session pour continuer|session title/i);

    await page.getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i).fill('   ');
    await expect(continueButton).toBeDisabled();
    expect(capturePlanRequests).toEqual([]);
  });

  test('keeps Knowledge Capture preparation editable when session creation fails', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlanRequests,
      capturePlanShouldFail: true,
      capturePlanFailureDetail: 'Mocked plan service unavailable',
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    const titleInput = page.getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i);
    await titleInput.fill('Andritz QA plan failure smoke');
    const continueButton = page.getByRole('button', { name: /^Continuer$|^Continue$/i });
    await continueButton.click();

    await expect.poll(() => capturePlanRequests.length).toBe(1);
    await expect(page.locator('body')).toContainText(/Préparation de session impossible|session preparation failed|réessayez|try again/i);
    await expect(titleInput).toHaveValue('Andritz QA plan failure smoke');
    await expect(continueButton).toBeEnabled();
    await expect(page.locator('body')).not.toContainText(/Conversation libre|Free conversation/i);
    expect(capturePlanRequests[0]).toMatchObject({
      title: 'Andritz QA plan failure smoke',
      plan_mode: 'free_conversation',
    });
  });

  test('creates a no-plan capture from the browser without exposing the plan rail', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, { capturePlanRequests });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await expect(page.locator('body')).toContainText(/Préparer la capture|Prepare the capture/i);
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA free conversation smoke');
    await expect(page.getByRole('button', { name: /Sans plan|Without plan/i })).toBeVisible();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA free conversation smoke' })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Conversation libre|Free conversation/i);
    await expect(page.getByRole('button', { name: /^Plan$/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Terminer la section|Finish section/i })).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(/Position\s+1\. Maintenance Andritz/i);
    expect(capturePlanRequests).toHaveLength(1);
    expect(capturePlanRequests[0]).toMatchObject({
      title: 'Andritz QA free conversation smoke',
      plan_mode: 'free_conversation',
      voice_runtime: 'cascade_openai',
    });
  });

  test('keeps planned capture usable when the hint queue load fails', async ({ page }) => {
    const captureHintQueueRequests: string[] = [];
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      captureSessionStartsActive: true,
      captureHintQueueRequests,
      captureHintQueueShouldFail: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA hint queue failure smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA hint queue failure smoke' })).toBeVisible();

    await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      component.hintStack.set([{ id: 'stale-hint', hint: 'Stale hint before reload failure' }]);
      component.refreshHintQueue('session-andritz-free-smoke', 'subtopic-alignment');
      ng?.applyChanges?.(component);
    });

    await expect.poll(() => captureHintQueueRequests).toEqual([
      '/knowledge-capture/sessions/session-andritz-free-smoke/hint-queue?subtopic_id=subtopic-alignment',
    ]);
    const state = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      return {
        hints: component.hintStack(),
        notice: component.voiceNotice(),
        noticeTone: component.voiceNoticeTone(),
        sessionStatus: component.session()?.status,
      };
    });
    expect(state).toMatchObject({
      hints: [],
      notice: 'Relances indisponibles pour le moment. La capture continue.',
      noticeTone: 'warning',
      sessionStatus: 'active',
    });
    await expect(page.getByRole('button', { name: /Validate plan|Valider le plan/i })).toBeVisible();
    expect(pageErrors).toEqual([]);
  });

  test('finishes an empty planned capture section without creating transcript turns', async ({ page }) => {
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      captureSessionStartsActive: true,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA empty planned section smoke');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA empty planned section smoke' })).toBeVisible();
    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await page.getByRole('button', { name: /^Parler$|^Speak$/i }).click();
    await expect(page.getByRole('button', { name: /Terminer la section|Finish section/i })).toBeVisible();

    const result = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      const sectionFinishes: unknown[] = [];
      component.voiceConnection = {
        sectionFinish: (payload: unknown) => sectionFinishes.push(payload),
      };

      const session = component.session();
      if (!session) throw new Error('Capture session not found');
      const beforeTranscriptLength = session.transcript?.length || 0;
      component.finishCurrentSection(session);

      return {
        sectionFinishes,
        beforeTranscriptLength,
        afterTranscriptLength: component.session()?.transcript?.length || 0,
        voiceState: component.voiceState(),
        notice: component.voiceNotice(),
        currentSectionValue: component.currentSectionValue(),
        sessionStatus: component.session()?.status,
      };
    });

    expect(result).toMatchObject({
      beforeTranscriptLength: 1,
      afterTranscriptLength: 1,
      voiceState: 'thinking',
      notice: 'Section terminée. L’IA va vous demander si vous souhaitez continuer.',
      currentSectionValue: 'topic-maintenance|subtopic-alignment',
      sessionStatus: 'active',
    });
    expect(result.sectionFinishes).toEqual([
      {
        topic_id: 'topic-maintenance',
        subtopic_id: 'subtopic-alignment',
        surface: 'knowledge_capture',
      },
    ]);
    expect(captureTurnRequests).toHaveLength(0);
  });

  test('handles capture voice turn commands once and ignores section commands in free mode', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlanRequests,
      captureSessionStartsActive: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA voice command free capture');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA voice command free capture' })).toBeVisible();

    const result = await page.evaluate(async () => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      const voiceCommands: unknown[] = [];
      const sectionFinishes: unknown[] = [];
      const finishReasons: string[] = [];

      component.voiceConnection = {
        voiceCommand: (command: string, transcript: string, payload: unknown) =>
          voiceCommands.push({ command, transcript, payload }),
        sectionFinish: (payload: unknown) => sectionFinishes.push(payload),
      };
      component.finishStreamingVoiceTurn = async (reason: string) => {
        finishReasons.push(reason);
      };

      component.currentClientTurnId = 'turn-command-free-1';
      const endTurn = component.detectCaptureVoiceCommand('tour suivant');
      const firstEndTurnHandled = component.handleCaptureVoiceCommand(endTurn, 'tour suivant');
      const duplicateEndTurnHandled = component.handleCaptureVoiceCommand(endTurn, 'tour suivant');

      component.currentClientTurnId = 'turn-command-free-2';
      const endSection = component.detectCaptureVoiceCommand('section suivante');
      const freeSectionHandled = component.handleCaptureVoiceCommand(endSection, 'section suivante');

      return {
        endTurn,
        endSection,
        firstEndTurnHandled,
        duplicateEndTurnHandled,
        freeSectionHandled,
        finishReasons,
        voiceCommands,
        sectionFinishes,
        notice: component.voiceNotice(),
        sessionMode: component.session()?.plan?.mode,
        sessionStatus: component.session()?.status,
      };
    });

    expect(result).toMatchObject({
      endTurn: 'end_turn',
      endSection: 'end_section',
      firstEndTurnHandled: true,
      duplicateEndTurnHandled: true,
      freeSectionHandled: true,
      finishReasons: ['voice_command'],
      sectionFinishes: [],
      notice: 'Commande de section ignorée en capture libre. La capture continue.',
      sessionMode: 'free_conversation',
      sessionStatus: 'active',
    });
    expect(result.voiceCommands).toEqual([
      {
        command: 'end_turn',
        transcript: 'tour suivant',
        payload: { surface: 'knowledge_capture' },
      },
      {
        command: 'end_section',
        transcript: 'section suivante',
        payload: { surface: 'knowledge_capture' },
      },
    ]);
    expect(capturePlanRequests).toHaveLength(1);
  });

  test('starts pauses and resumes a free Knowledge Capture voice session without ending the turn', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlanRequests,
      captureSessionStartsActive: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA start pause resume capture');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA start pause resume capture' })).toBeVisible();

    const result = await page.evaluate(async () => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      const loopStarts: unknown[] = [];
      const loopArmed: unknown[] = [];
      const audioPauses: unknown[] = [];
      let releaseCount = 0;
      let recorderStopCount = 0;

      const connection = {
        loopStart: (payload: unknown) => loopStarts.push(payload),
        loopArmed: (payload: unknown) => loopArmed.push(payload),
        audioPause: (payload: unknown) => audioPauses.push(payload),
      };
      component.ensureVoiceConnection = async () => {
        component.voiceConnection = connection;
        return connection;
      };
      component.ensureAudioStream = async () => true;
      component.releaseAudioStream = () => {
        releaseCount += 1;
      };
      component.startAudioRecorder = (message: string) => {
        component.recorder = {
          state: 'recording',
          onstop: null,
          ondataavailable: null,
          stop() {
            recorderStopCount += 1;
            this.state = 'inactive';
            this.onstop?.();
          },
        };
        component.recording.set(true);
        component.voiceState.set('listening');
        component.setVoiceNotice(message, 'info');
        return true;
      };

      await component.toggleConversationSession();
      const afterStart = {
        active: component.conversationSessionActive(),
        recording: component.recording(),
        voiceState: component.voiceState(),
        notice: component.voiceNotice(),
      };

      component.pendingVoiceFrameSends = [Promise.resolve('tail-flushed')];
      component.pauseMicrophone();
      await new Promise((resolve) => setTimeout(resolve, 0));
      const afterPause = {
        active: component.conversationSessionActive(),
        recording: component.recording(),
        voiceState: component.voiceState(),
        notice: component.voiceNotice(),
        releaseCount,
        recorderStopCount,
        audioPauses: [...audioPauses],
      };

      await component.toggleConversationSession();
      const afterResume = {
        active: component.conversationSessionActive(),
        recording: component.recording(),
        voiceState: component.voiceState(),
        notice: component.voiceNotice(),
      };

      return {
        loopStarts,
        loopArmed,
        audioPauses,
        afterStart,
        afterPause,
        afterResume,
        releaseCount,
        recorderStopCount,
        sessionStatus: component.session()?.status,
        sessionMode: component.session()?.plan?.mode,
      };
    });

    expect(result.afterStart).toMatchObject({
      active: true,
      recording: true,
      voiceState: 'listening',
      notice: 'Micro ouvert. Terminez le tour quand la réponse expert est complète.',
    });
    expect(result.afterPause).toMatchObject({
      active: false,
      recording: false,
      voiceState: 'idle',
      notice: 'Micro en pause. Aucune relance déclenchée — reprenez quand vous voulez.',
      releaseCount: 1,
      recorderStopCount: 1,
    });
    expect(result.afterResume).toMatchObject({
      active: true,
      recording: true,
      voiceState: 'listening',
      notice: 'Micro ouvert. Terminez le tour quand la réponse expert est complète.',
    });
    expect(result.loopStarts).toHaveLength(2);
    expect(result.loopArmed).toHaveLength(2);
    expect(result.audioPauses).toEqual([{ surface: 'knowledge_capture' }]);
    expect(result.sessionStatus).toBe('active');
    expect(result.sessionMode).toBe('free_conversation');
    expect(capturePlanRequests).toHaveLength(1);
  });

  test('defers Knowledge Capture stop while final STT is still transcribing', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlanRequests,
      captureSessionStartsActive: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA pause while final STT');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA pause while final STT' })).toBeVisible();

    const result = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      const loopStops: unknown[] = [];
      let closeCount = 0;
      let releaseCount = 0;

      component.conversationSessionActive.set(true);
      component.recording.set(false);
      component.transcribing.set(true);
      component.voiceState.set('partial_transcribing');
      component.voiceConnection = {
        loopStop: (payload: unknown) => loopStops.push(payload),
        close: () => {
          closeCount += 1;
        },
      };
      component.releaseAudioStream = () => {
        releaseCount += 1;
      };

      component.stopConversation();
      const afterStopClick = {
        active: component.conversationSessionActive(),
        transcribing: component.transcribing(),
        voiceState: component.voiceState(),
        notice: component.voiceNotice(),
        closeCount,
        loopStops: [...loopStops],
        deferredLoopStop: component.deferredLoopStopAfterStreamingTurn,
        closeDeferred: component.closeVoiceAfterStreamingTurn,
      };

      component.transcribing.set(false);
      component.finalizeDeferredStreamingStop();
      const afterFinalized = {
        active: component.conversationSessionActive(),
        transcribing: component.transcribing(),
        voiceState: component.voiceState(),
        notice: component.voiceNotice(),
        closeCount,
        releaseCount,
        loopStops: [...loopStops],
        connection: component.voiceConnection,
        deferredLoopStop: component.deferredLoopStopAfterStreamingTurn,
        closeDeferred: component.closeVoiceAfterStreamingTurn,
      };

      return {
        afterStopClick,
        afterFinalized,
        sessionStatus: component.session()?.status,
      };
    });

    expect(result.afterStopClick).toMatchObject({
      active: false,
      transcribing: true,
      voiceState: 'partial_transcribing',
      notice: 'Conversation arrêtée. Finalisation du dernier tour…',
      closeCount: 0,
      loopStops: [],
      deferredLoopStop: { surface: 'knowledge_capture', reason: 'user_stop' },
      closeDeferred: true,
    });
    expect(result.afterFinalized).toMatchObject({
      active: false,
      transcribing: false,
      voiceState: 'idle',
      closeCount: 1,
      releaseCount: 1,
      loopStops: [{ surface: 'knowledge_capture', reason: 'user_stop' }],
      connection: null,
      deferredLoopStop: null,
      closeDeferred: false,
    });
    expect(result.sessionStatus).toBe('active');
    expect(capturePlanRequests).toHaveLength(1);
  });

  test('falls back to written capture when the microphone is unavailable in no-plan mode', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: {
          getUserMedia: async () => {
            throw new DOMException('Synthetic microphone permission denial', 'NotAllowedError');
          },
        },
      });
      (window as any).__voiceWsUrls = [];
      (window as any).__voiceWsFrames = [];
      class MockVoiceWebSocket {
        static readonly CONNECTING = 0;
        static readonly OPEN = 1;
        static readonly CLOSING = 2;
        static readonly CLOSED = 3;
        readyState = MockVoiceWebSocket.OPEN;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        onclose: ((event: CloseEvent) => void) | null = null;

        constructor(url: string) {
          (window as any).__voiceWsUrls.push(url);
          setTimeout(() => this.onopen?.(new Event('open')), 0);
        }

        send(frame: string): void {
          (window as any).__voiceWsFrames.push(JSON.parse(frame));
        }

        close(): void {
          this.readyState = MockVoiceWebSocket.CLOSED;
          this.onclose?.(new CloseEvent('close'));
        }
      }
      Object.defineProperty(window, 'WebSocket', {
        configurable: true,
        value: MockVoiceWebSocket,
      });
    });
    await installAndritzMocks(page, {
      capturePlanRequests,
      captureSessionStartsActive: true,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA voice unavailable fallback');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA voice unavailable fallback' })).toBeVisible();
    await page.getByRole('button', { name: /^Parler$|^Speak$/i }).click();

    await expect(page.locator('body')).toContainText(/Micro indisponible|microphone permission|saisie guidée/i);
    const { input: answerComposer, submit: sendButton } = captureExpressionComposer(page);
    await expect(answerComposer).toBeVisible();
    await answerComposer.fill('Note de secours saisie quand le micro est indisponible.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(capturePlanRequests).toHaveLength(1);
    expect(capturePlanRequests[0]).toMatchObject({
      title: 'Andritz QA voice unavailable fallback',
      plan_mode: 'free_conversation',
      voice_runtime: 'cascade_openai',
    });
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Note de secours saisie quand le micro est indisponible.',
      turn_kind: 'answer',
      input_modality: 'text',
    });
    const voiceFrames = await page.evaluate(() => (window as any).__voiceWsFrames || []);
    expect(voiceFrames.map((frame: { type?: string }) => frame.type)).toContain('session.start');
    expect(voiceFrames.map((frame: { type?: string }) => frame.type)).toContain('loop.start');
    expect(voiceFrames.map((frame: { type?: string }) => frame.type)).not.toContain('audio.frame');
    expect(voiceFrames.map((frame: { type?: string }) => frame.type)).not.toContain('audio.endpoint');
  });

  test('uploads a capture document while recording without stopping the voice state', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA upload while recording');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA upload while recording' })).toBeVisible();

    await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      component.conversationSessionActive.set(true);
      component.recording.set(true);
      component.transcribing.set(false);
      component.voiceState.set('recording');
      component.currentClientTurnId = 'turn-upload-while-recording';
      ng?.applyChanges?.(component);
    });
    await expect(page.getByRole('button', { name: /Pause micro/i })).toBeVisible();

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz upload while recording reference PDF content.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await expect(page.getByRole('button', { name: /Andritz capture reference/i })).toBeVisible();
    const voiceState = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      return {
        recording: component.recording(),
        transcribing: component.transcribing(),
        conversationSessionActive: component.conversationSessionActive(),
        voiceState: component.voiceState(),
        currentClientTurnId: component.currentClientTurnId,
      };
    });
    expect(voiceState).toMatchObject({
      recording: true,
      transcribing: false,
      conversationSessionActive: true,
      voiceState: 'recording',
      currentClientTurnId: 'turn-upload-while-recording',
    });
    expect(captureTurnRequests).toEqual([]);
  });

  test('renders a late same-turn voice partial while endpoint STT is finalizing', async ({ page }) => {
    await installAndritzMocks(page, { captureSessionStartsActive: true });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA late partial smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA late partial smoke' })).toBeVisible();

    await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      component.currentClientTurnId = 'turn-late-partial';
      component.recording.set(false);
      component.transcribing.set(true);
      component.closeVoiceAfterStreamingTurn = false;
      component.realtimeSttActive = false;
      component.handleVoiceSessionEvent({
        type: 'transcript.partial',
        payload: {
          turn_id: 'turn-late-partial',
          segment_id: 'turn-late-partial',
          text: 'Le convoyeur Andritz reste audible pendant la finalisation STT.',
        },
      });
      ng?.applyChanges?.(component);
    });

    const partial = page
      .locator('span')
      .filter({ hasText: 'Le convoyeur Andritz reste audible pendant la finalisation STT.' });
    await expect(partial).toBeVisible();
    await expect(partial).toHaveClass(/italic/);
  });

  test('imports a Knowledge Capture plan source file before validating the guided plan', async ({ page }) => {
    const planSourceExtractRequests: string[] = [];
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      planSourceExtractRequests,
      planSourceExtractText: [
        '# Inspection machine Andritz',
        '## Sécurité inspection',
        '- Vérifier arrêt machine',
        '## Vitesse de ligne',
        '- Contrôler la consigne vitesse',
      ].join('\n'),
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA imported plan source');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const planEditor = page.locator('textarea').first();
    await expect(planEditor).toHaveValue(/Maintenance Andritz/);
    const importInput = page.getByTitle('Importer un fichier de plan').locator('input[type="file"]').first();
    await importInput.setInputFiles({
      name: 'andritz-plan-source.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# Client-side content ignored by extractor mock'),
    });

    await expect.poll(() => planSourceExtractRequests.length).toBe(1);
    expect(planSourceExtractRequests[0]).toContain('andritz-plan-source.md');
    await expect(planEditor).toHaveValue(/Inspection machine Andritz/);
    await expect(planEditor).toHaveValue(/Vitesse de ligne/);
    await expect(page.locator('body')).toContainText(/Plan importé depuis andritz-plan-source.md/i);

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);
    expect(JSON.stringify(capturePlanTopicsRequests[0])).toContain('Inspection machine Andritz');
    expect(JSON.stringify(capturePlanTopicsRequests[0])).toContain('Vitesse de ligne');
  });

  test('rejects an unsupported Knowledge Capture plan source without corrupting the draft plan', async ({ page }) => {
    const planSourceExtractRequests: string[] = [];
    const capturePlanTopicsRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      planSourceExtractRequests,
      planSourceExtractShouldFail: true,
      planSourceExtractFailureDetail: 'Format de fichier non supporté pour une source de plan.',
      capturePlanTopicsRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA unsupported plan source');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const planEditor = page.locator('textarea').first();
    await expect(planEditor).toHaveValue(/Maintenance Andritz/);
    await page.getByTitle('Importer un fichier de plan').locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-plan-source.exe',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('This binary-looking payload must not replace the plan draft.'),
    });

    await expect.poll(() => planSourceExtractRequests.length).toBe(1);
    await expect(page.locator('body')).toContainText(/Format de fichier non supporté/i);
    await expect(planEditor).toHaveValue(/Maintenance Andritz/);
    await expect(planEditor).not.toHaveValue(/binary-looking payload/);
    expect(capturePlanTopicsRequests).toEqual([]);
  });

  test('keeps a large pasted Knowledge Capture plan editable and validatable', async ({ page }) => {
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA large pasted plan');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const largePlan = Array.from({ length: 180 }, (_, index) => {
      const n = index + 1;
      return `${n}. Sujet Andritz ${n.toString().padStart(3, '0')}\n   - Point terrain ${n} avec contexte maintenance, sécurité et qualité ligne.`;
    }).join('\n');
    const planEditor = page.locator('textarea').first();
    await planEditor.fill(largePlan);
    await expect(planEditor).toHaveValue(/Sujet Andritz 180/);

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);
    expect(JSON.stringify(capturePlanTopicsRequests[0])).toContain('Sujet Andritz 180');
  });

  test('keeps Knowledge Capture plan co-construction retryable when dialogue generation times out', async ({ page }) => {
    const capturePlanDialogueRequests: unknown[] = [];
    const capturePlanTopicsRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanDialogueRequests,
      capturePlanDialogueShouldFail: true,
      capturePlanDialogueFailureDetail: 'Plan oracle timeout',
      capturePlanTopicsRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA plan dialogue timeout');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const planEditor = page.locator('textarea').first();
    await expect(planEditor).toHaveValue(/Maintenance Andritz/);
    const instruction = page.getByPlaceholder(/Ajoutez un point|fusionnez deux sections|simplifiez les titres/i);
    await instruction.fill('Ajoute une rubrique sur les alarmes de vitesse Andritz.');
    await page.getByRole('button', { name: /^Appliquer$|^Apply$/i }).click();

    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanDialogueRequests.length).toBe(1);
    expect(capturePlanDialogueRequests[0]).toMatchObject({
      text: 'Ajoute une rubrique sur les alarmes de vitesse Andritz.',
    });
    await expect(page.locator('body')).toContainText(/Plan oracle timeout/i);
    await expect(instruction).toHaveValue('Ajoute une rubrique sur les alarmes de vitesse Andritz.');
    await expect(page.getByRole('button', { name: /^Appliquer$|^Apply$/i })).toBeEnabled();
    await expect(planEditor).toHaveValue(/Maintenance Andritz/);
  });

  test('reorders nested Knowledge Capture plan topics before validation', async ({ page }) => {
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA reordered nested plan');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const planEditor = page.locator('textarea').first();
    await expect(planEditor).toHaveValue(/Alignement convoyeur/);
    await expect(planEditor).toHaveValue(/Sécurité arrêt machine/);
    await planEditor.evaluate((element) => {
      const textarea = element as HTMLTextAreaElement;
      const start = textarea.value.indexOf('Alignement convoyeur');
      if (start < 0) throw new Error('subtopic not found');
      textarea.focus();
      textarea.setSelectionRange(start, start + 'Alignement convoyeur'.length);
      textarea.dispatchEvent(new Event('select', { bubbles: true }));
    });
    await page.getByRole('button', { name: /Descendre la sélection/i }).click();
    await expect(planEditor).toHaveValue(/Sécurité arrêt machine[\s\S]*Alignement convoyeur/);

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);

    const payload = capturePlanTopicsRequests[0] as {
      topics?: Array<{ title?: string; subtopics?: Array<{ title?: string }> }>;
    };
    expect(payload.topics?.[0]?.subtopics?.map((item) => item.title)).toEqual([
      'Sécurité arrêt machine',
      'Alignement convoyeur',
    ]);
  });

  test('keeps written capture note submission disabled while the note is blank', async ({ page }) => {
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    const captureStartRequests: string[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
      captureStartRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA blank written note');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);
    await page.getByRole('button', { name: /Parler|Speak/i }).click();
    await expect.poll(() => captureStartRequests.length).toBe(1);

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await expect(sendButton).toBeDisabled();

    await noteInput.fill('     ');
    await expect(sendButton).toBeDisabled();
    expect(captureTurnRequests).toEqual([]);
  });

  test('accepts a written capture note while voice transcription is finalizing', async ({ page }) => {
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    const captureStartRequests: string[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
      captureStartRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA written note during transcription');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);
    await page.getByRole('button', { name: /Parler|Speak/i }).click();
    await expect.poll(() => captureStartRequests.length).toBe(1);

    await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      component.recording.set(false);
      component.transcribing.set(true);
      component.voiceState.set('transcribing');
      component.currentClientTurnId = 'turn-written-while-transcribing';
      ng?.applyChanges?.(component);
    });

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Complément écrit pendant la finalisation de la transcription voix.');
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Complément écrit pendant la finalisation de la transcription voix.',
      question_id: 'q-alignment',
      turn_kind: 'answer',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });
    await expect(noteInput).toHaveValue('');
  });

  test('keeps written capture anchored to the active guided plan section', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    const captureStartRequests: string[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanRequests,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
      captureStartRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA guided plan smoke');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA guided plan smoke' })).toBeVisible();
    const planOutline = page.locator('textarea').first();
    await expect(planOutline).toHaveValue(/Maintenance Andritz/);
    await expect(planOutline).toHaveValue(/Alignement convoyeur/);
    expect(capturePlanRequests).toHaveLength(1);
    expect(capturePlanRequests[0]).toMatchObject({
      title: 'Andritz QA guided plan smoke',
      plan_mode: 'plan_build',
      voice_runtime: 'cascade_openai',
    });

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);
    await expect(page.locator('body')).toContainText(/Position/i);
    await expect(page.locator('body')).toContainText(/Maintenance Andritz/);
    await expect(page.locator('body')).toContainText(/Alignement convoyeur/);

    await page.getByRole('button', { name: /Parler|Speak/i }).click();
    await expect.poll(() => captureStartRequests.length).toBe(1);
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Le repère d alignement doit rester rattaché à la section convoyeur.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Le repère d alignement doit rester rattaché à la section convoyeur.',
      question_id: 'q-alignment',
      turn_kind: 'answer',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });
    await expect(noteInput).toHaveValue('');
  });

  test('keeps written capture anchored after switching guided plan section', async ({ page }) => {
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    const captureStartRequests: string[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
      captureStartRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA guided section switch smoke');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA guided section switch smoke' })).toBeVisible();

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);

    await page.getByRole('button', { name: /Parler|Speak/i }).click();
    await expect.poll(() => captureStartRequests.length).toBe(1);
    const safetySection = page.getByRole('button', { name: /Sécurité arrêt machine/i }).first();
    await expect(safetySection).toBeVisible();
    await safetySection.click();
    await expect(safetySection).toHaveClass(/text-brand-100/);

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('La consignation doit être confirmée avant l arrêt machine.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'La consignation doit être confirmée avant l arrêt machine.',
      question_id: 'q-safety-stop',
      turn_kind: 'answer',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });
    expect(JSON.stringify(captureTurnRequests[0])).not.toContain('q-alignment');
    await expect(noteInput).toHaveValue('');
  });

  test('keeps guided written capture anchored to the selected section and active document view', async ({ page }) => {
    const capturePlanTopicsRequests: unknown[] = [];
    const capturePlanValidationRequests: string[] = [];
    const captureStartRequests: string[] = [];
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlannedSession: true,
      capturePlanTopicsRequests,
      capturePlanValidationRequests,
      captureStartRequests,
      captureDocumentUploadRequests,
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA guided document section smoke');
    await page.getByRole('button', { name: /Avec plan|With plan/i }).click();
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA guided document section smoke' })).toBeVisible();

    await page.getByRole('button', { name: /Valider le plan|Validate plan/i }).click();
    await expect.poll(() => capturePlanTopicsRequests.length).toBe(1);
    await expect.poll(() => capturePlanValidationRequests.length).toBe(1);

    await page.getByRole('button', { name: /Parler|Speak/i }).click();
    await expect.poll(() => captureStartRequests.length).toBe(1);
    const safetySection = page.getByRole('button', { name: /Sécurité arrêt machine/i }).first();
    await expect(safetySection).toBeVisible();
    await safetySection.click();
    await expect(safetySection).toHaveClass(/text-brand-100/);

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz guided capture reference PDF content.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    const referenceDocument = page.getByRole('button', { name: /Andritz capture reference/i });
    await expect(referenceDocument).toBeVisible();
    await referenceDocument.focus();
    await page.keyboard.press('Enter');

    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(1);
    const previewParams = new URLSearchParams(captureDocumentPreviewRequests[0].replace(/^\?/, ''));
    expect(previewParams.get('collection_name')).toBe('capture-session-session-andritz-free-smoke');
    expect(previewParams.get('filename')).toBe('andritz-capture-reference.pdf');
    await expect.poll(() => captureDocumentViewRequests.length).toBe(1);
    expect(captureDocumentViewRequests[0]).toMatchObject({
      document_id: 'doc-capture-reference',
      collection: 'capture-session-session-andritz-free-smoke',
      collection_name: 'capture-session-session-andritz-free-smoke',
      filename: 'andritz-capture-reference.pdf',
      title: 'Andritz capture reference',
      page: 1,
      association_mode: 'active_view',
    });
    await expect(page.getByRole('heading', { name: /Andritz capture reference/i })).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.1/i)).toHaveClass(
      /ring-brand-300\/40/,
    );
    await expect(safetySection).toHaveClass(/text-brand-100/);

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Sur cette page, la consignation avant arrêt machine est visible.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Sur cette page, la consignation avant arrêt machine est visible.',
      question_id: 'q-safety-stop',
      turn_kind: 'answer',
      input_modality: 'text',
      document_refs: [
        expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 1,
          association_mode: 'active_view',
        }),
      ],
      visual_context: expect.objectContaining({
        document_id: 'doc-capture-reference',
        filename: 'andritz-capture-reference.pdf',
        page: 1,
        association_mode: 'active_view',
      }),
    });
    expect(JSON.stringify(captureTurnRequests[0])).not.toContain('q-alignment');
    await expect(noteInput).toHaveValue('');
  });

  test('attaches a written capture note to the active document view without real upload', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      capturePlanRequests,
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA document capture smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA document capture smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz capture reference PDF content.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await expect(page.getByRole('button', { name: /Andritz capture reference/i })).toBeVisible();
    await page.getByRole('button', { name: /Andritz capture reference/i }).click();

    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(1);
    const previewParams = new URLSearchParams(captureDocumentPreviewRequests[0].replace(/^\?/, ''));
    expect(previewParams.get('collection_name')).toBe('capture-session-session-andritz-free-smoke');
    expect(previewParams.get('filename')).toBe('andritz-capture-reference.pdf');
    await expect.poll(() => captureDocumentViewRequests.length).toBe(1);
    expect(captureDocumentViewRequests[0]).toMatchObject({
      document_id: 'doc-capture-reference',
      collection: 'capture-session-session-andritz-free-smoke',
      collection_name: 'capture-session-session-andritz-free-smoke',
      filename: 'andritz-capture-reference.pdf',
      title: 'Andritz capture reference',
      page: 1,
      association_mode: 'active_view',
    });
    await expect(page.getByRole('heading', { name: /Andritz capture reference/i })).toBeVisible();
    await expect(page.getByText('Synthetic capture document page content for active visual context.')).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.1/i)).toHaveClass(
      /ring-brand-300\/40/,
    );

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Sur cette page, le convoyeur de test Andritz reste aligné.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Sur cette page, le convoyeur de test Andritz reste aligné.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [
        expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 1,
          association_mode: 'active_view',
        }),
      ],
      visual_context: expect.objectContaining({
        document_id: 'doc-capture-reference',
        filename: 'andritz-capture-reference.pdf',
        page: 1,
        association_mode: 'active_view',
      }),
    });
    await expect(noteInput).toHaveValue('');
    expect(capturePlanRequests).toHaveLength(1);
  });

  test('updates written capture document refs after a preview page change', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA document page-change smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz capture reference PDF content.'),
    });
    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await page.getByRole('button', { name: /Andritz capture reference/i }).click();
    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(1);
    await expect.poll(() => captureDocumentViewRequests.length).toBe(1);
    expect(captureDocumentViewRequests[0]).toMatchObject({
      document_id: 'doc-capture-reference',
      page: 1,
      association_mode: 'active_view',
    });

    await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      component.onSourcePreviewViewChanged({
        kind: 'pdf',
        filename: 'andritz-capture-reference.pdf',
        page: 2,
      });
    });

    await expect.poll(() => captureDocumentViewRequests.length).toBe(2);
    expect(captureDocumentViewRequests[1]).toMatchObject({
      document_id: 'doc-capture-reference',
      collection: 'capture-session-session-andritz-free-smoke',
      collection_name: 'capture-session-session-andritz-free-smoke',
      filename: 'andritz-capture-reference.pdf',
      title: 'Andritz capture reference',
      page: 2,
      association_mode: 'active_view',
    });
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.2/i)).toHaveClass(
      /ring-brand-300\/40/,
    );

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Sur cette page 2, le réducteur Andritz est identifié.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Sur cette page 2, le réducteur Andritz est identifié.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [
        expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 2,
          association_mode: 'active_view',
        }),
      ],
      visual_context: expect.objectContaining({
        document_id: 'doc-capture-reference',
        filename: 'andritz-capture-reference.pdf',
        page: 2,
        association_mode: 'active_view',
      }),
    });
  });

  test('keeps voice capture references on the latest page after rapid preview changes', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA rapid page voice reference smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();
    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz capture reference PDF content.'),
    });
    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await page.getByRole('button', { name: /Andritz capture reference/i }).click();
    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(1);
    await expect.poll(() => captureDocumentViewRequests.length).toBe(1);

    const state = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      component.currentClientTurnId = 'turn-rapid-doc-page';
      component.recording.set(true);
      component.transcribing.set(false);

      for (const pageNumber of [2, 3, 4]) {
        component.onSourcePreviewViewChanged({
          kind: 'pdf',
          filename: 'andritz-capture-reference.pdf',
          page: pageNumber,
        });
      }

      const meta = component.voiceFrameMeta('manual');
      const pins = component.pinnedCaptureDocumentViews();
      const focusedKey = component.focusedPinKey();
      const focusedView = pins.find((pin: { key?: string }) => pin.key === focusedKey) || pins[0] || null;
      if (!focusedView) throw new Error('Focused capture pin not found');
      ng?.applyChanges?.(component);
      return {
        pinCount: pins.length,
        focusedKey,
        focusedView,
        meta,
        focusedLabel: component.capturePinLabel(focusedView),
        sourcePreviewPage: component.sourcePreviewPage(),
        recording: component.recording(),
      };
    });

    await expect.poll(() => captureDocumentViewRequests.length).toBe(4);
    expect(captureDocumentViewRequests.map((entry) => (entry as { page?: number }).page)).toEqual([1, 2, 3, 4]);
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.4/i)).toHaveClass(
      /ring-brand-300\/40/,
    );
    expect(state).toMatchObject({
      pinCount: 1,
      focusedKey: 'doc-capture-reference',
      focusedLabel: 'Andritz capture reference · p.4',
      sourcePreviewPage: 4,
      recording: true,
      focusedView: expect.objectContaining({
        document_id: 'doc-capture-reference',
        filename: 'andritz-capture-reference.pdf',
        page: 4,
        association_mode: 'active_view',
      }),
      meta: expect.objectContaining({
        turn_id: 'turn-rapid-doc-page',
        content_type: 'audio/webm',
        visual_context: expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 4,
          association_mode: 'active_view',
        }),
        document_refs: [
          expect.objectContaining({
            document_id: 'doc-capture-reference',
            filename: 'andritz-capture-reference.pdf',
            page: 4,
            association_mode: 'active_view',
          }),
        ],
      }),
    });
  });

  test('carries every pinned written capture reference and keeps the latest pin focused', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentUploadTwoSuccess: true,
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA document capture smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA document capture smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    await captureDocuments.locator('input[type="file"]').setInputFiles([
      {
        name: 'andritz-capture-reference.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('Synthetic Andritz capture reference PDF content.'),
      },
      {
        name: 'andritz-capture-photo.jpg',
        mimeType: 'image/jpeg',
        buffer: Buffer.from('Synthetic Andritz capture photo bytes.'),
      },
    ]);

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await expect(page.getByRole('button', { name: /Andritz capture reference/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Andritz capture photo/i })).toBeVisible();

    await page.getByRole('button', { name: /Andritz capture reference/i }).click();
    await expect(page.getByText('Synthetic capture document page content for active visual context.')).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.1/i)).toHaveClass(
      /ring-brand-300\/40/,
    );

    await page.getByRole('button', { name: /Andritz capture photo/i }).click();
    await expect(page.getByText('Synthetic capture photo content for the second active visual context.')).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture photo · p\.1/i)).toHaveClass(
      /ring-brand-300\/40/,
    );

    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(2);
    const secondPreviewParams = new URLSearchParams(captureDocumentPreviewRequests[1].replace(/^\?/, ''));
    expect(secondPreviewParams.get('collection_name')).toBe('capture-session-session-andritz-free-smoke');
    expect(secondPreviewParams.get('filename')).toBe('andritz-capture-photo.jpg');
    await expect.poll(() => captureDocumentViewRequests.length).toBe(2);
    expect(captureDocumentViewRequests[0]).toMatchObject({
      document_id: 'doc-capture-reference',
      filename: 'andritz-capture-reference.pdf',
      page: 1,
      association_mode: 'active_view',
    });
    expect(captureDocumentViewRequests[1]).toMatchObject({
      document_id: 'doc-capture-photo',
      filename: 'andritz-capture-photo.jpg',
      page: 1,
      association_mode: 'active_view',
    });
    const pinState = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      return {
        keys: component.pinnedCaptureDocumentViews().map((pin: { key?: string }) => pin.key),
        focusedKey: component.focusedPinKey(),
      };
    });
    expect(pinState).toEqual({
      keys: ['doc-capture-reference', 'doc-capture-photo'],
      focusedKey: 'doc-capture-photo',
    });

    const { input: noteInput } = captureExpressionComposer(page);
    await noteInput.fill('Sur cette photo, la zone d accès maintenance Andritz reste visible.');
    await noteInput.press('Enter');

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Sur cette photo, la zone d accès maintenance Andritz reste visible.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [
        expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 1,
          association_mode: 'active_view',
        }),
        expect.objectContaining({
          document_id: 'doc-capture-photo',
          filename: 'andritz-capture-photo.jpg',
          page: 1,
          association_mode: 'active_view',
        }),
      ],
      visual_context: expect.objectContaining({
        document_id: 'doc-capture-photo',
        filename: 'andritz-capture-photo.jpg',
        page: 1,
        association_mode: 'active_view',
      }),
    });
    expect((captureTurnRequests[0] as { document_refs?: unknown[] }).document_refs).toHaveLength(2);
    await expect(noteInput).toHaveValue('');
  });

  test('keeps written capture usable when capture document preview is unavailable', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentPreviewRequests,
      captureDocumentPreviewShouldFail: true,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA unavailable document preview smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA unavailable document preview smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz capture reference PDF content.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await page.getByRole('button', { name: /Andritz capture reference/i }).click();

    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(1);
    const previewParams = new URLSearchParams(captureDocumentPreviewRequests[0].replace(/^\?/, ''));
    expect(previewParams.get('collection_name')).toBe('capture-session-session-andritz-free-smoke');
    expect(previewParams.get('filename')).toBe('andritz-capture-reference.pdf');
    await expect.poll(() => captureDocumentViewRequests.length).toBe(1);
    expect(captureDocumentViewRequests[0]).toMatchObject({
      document_id: 'doc-capture-reference',
      filename: 'andritz-capture-reference.pdf',
      page: 1,
      association_mode: 'active_view',
    });
    await expect(page.getByText('Mocked capture document preview unavailable')).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.1/i)).toHaveClass(
      /ring-brand-300\/40/,
    );

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Le document reste lie au tour meme si la preview est temporairement indisponible.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Le document reste lie au tour meme si la preview est temporairement indisponible.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [
        expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 1,
          association_mode: 'active_view',
        }),
      ],
      visual_context: expect.objectContaining({
        document_id: 'doc-capture-reference',
        filename: 'andritz-capture-reference.pdf',
        page: 1,
        association_mode: 'active_view',
      }),
    });
    await expect(noteInput).toHaveValue('');
  });

  test('keeps written capture usable when active document view logging fails', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentViewRequests,
      captureDocumentViewShouldFail: true,
      captureDocumentPreviewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA document view failure smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA document view failure smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-reference.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz capture reference PDF content.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await page.getByRole('button', { name: /Andritz capture reference/i }).click();

    await expect.poll(() => captureDocumentPreviewRequests.length).toBe(1);
    await expect.poll(() => captureDocumentViewRequests.length).toBe(1);
    expect(captureDocumentViewRequests[0]).toMatchObject({
      document_id: 'doc-capture-reference',
      filename: 'andritz-capture-reference.pdf',
      page: 1,
      association_mode: 'active_view',
    });
    await expect(page.getByText('Synthetic capture document page content for active visual context.')).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(focusedCapturePin(page, /Andritz capture reference · p\.1/i)).toHaveClass(
      /ring-brand-300\/40/,
    );

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('Sur cette page, le repère Andritz reste exploitable malgré l audit différé.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Sur cette page, le repère Andritz reste exploitable malgré l audit différé.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [
        expect.objectContaining({
          document_id: 'doc-capture-reference',
          filename: 'andritz-capture-reference.pdf',
          page: 1,
          association_mode: 'active_view',
        }),
      ],
      visual_context: expect.objectContaining({
        document_id: 'doc-capture-reference',
        filename: 'andritz-capture-reference.pdf',
        page: 1,
        association_mode: 'active_view',
      }),
    });
    await expect(noteInput).toHaveValue('');
  });

  test('keeps written Knowledge Capture usable when capture document upload fails', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentUploadShouldFail: true,
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA failed document upload smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA failed document upload smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-rejected.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic Andritz rejected capture document.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await expect(page.getByText('Chargement document impossible pour cette capture.')).toBeVisible();
    await expect(page.getByText(/andritz-capture-rejected\.pdf|Andritz capture reference/i)).toHaveCount(0);
    expect(captureDocumentPreviewRequests).toHaveLength(0);
    expect(captureDocumentViewRequests).toHaveLength(0);

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('La note écrite continue même sans document attaché.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'La note écrite continue même sans document attaché.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });
    await expect(noteInput).toHaveValue('');
  });

  test('surfaces capture document upload rejection detail without creating document state', async ({ page }) => {
    const captureDocumentUploadRequests: string[] = [];
    const captureDocumentPreviewRequests: string[] = [];
    const captureDocumentViewRequests: unknown[] = [];
    const captureTurnRequests: unknown[] = [];
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureDocumentUploadRequests,
      captureDocumentUploadShouldFail: true,
      captureDocumentUploadFailureStatus: 400,
      captureDocumentUploadFailureDetail: 'Type de fichier non supporte pour la capture.',
      captureDocumentPreviewRequests,
      captureDocumentViewRequests,
      captureTurnRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA unsupported capture document smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA unsupported capture document smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    await captureDocuments.locator('input[type="file"]').setInputFiles({
      name: 'andritz-capture-unsupported.bin',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('Synthetic unsupported Andritz capture document.'),
    });

    await expect.poll(() => captureDocumentUploadRequests.length).toBe(1);
    await expect(page.getByText('Type de fichier non supporte pour la capture.')).toBeVisible();
    await expect(page.getByText(/andritz-capture-unsupported\.bin|Andritz capture reference/i)).toHaveCount(0);
    expect(captureDocumentPreviewRequests).toHaveLength(0);
    expect(captureDocumentViewRequests).toHaveLength(0);

    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill('La capture reste disponible apres le rejet du document.');
    await sendButton.click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'La capture reste disponible apres le rejet du document.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });
    await expect(noteInput).toHaveValue('');
  });

  test('finishes a no-plan capture with material into a structured report without publishing', async ({ page }) => {
    const captureTurnRequests: unknown[] = [];
    const captureClosureRequests: unknown[] = [];
    let publishRequests = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals/proposal-andritz-qa/publish')) {
        publishRequests += 1;
      }
    });
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureTurnRequests,
      captureClosureRequests,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA no-plan structured finish smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA no-plan structured finish smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    const noteText = 'La fiche doit garder une synthese structuree sans publication.';
    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill(noteText);
    await sendButton.click();
    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: noteText,
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });

    await page.getByRole('button', { name: /Terminer la capture|Finish capture/i }).click();

    await expect.poll(() => captureClosureRequests.length).toBe(1);
    expect(captureClosureRequests[0]).toMatchObject({ action: 'finish' });
    await expect(page.locator('body')).toContainText(/Rapport final éditable|Editable final report/i);
    await expect(page.locator('body')).toContainText(/Synthèse de la capture|Synthese de la capture/i);
    await expect(page.locator('body')).toContainText(/Synthetic Andritz QA fact for explicit publication guard/i);
    await expect(page.getByRole('button', { name: /Continuer vers publication|Continue to publication/i })).toBeVisible();
    expect(publishRequests).toBe(0);
  });

  test('opens the persisted report when the finalization done event is lost', async ({ page }) => {
    const proposalRequests: string[] = [];
    let publishRequests = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals')) {
        proposalRequests.push(`${request.method()} ${url.pathname}${url.search}`);
      }
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals/proposal-andritz-qa/publish')) {
        publishRequests += 1;
      }
    });
    await installAndritzMocks(page, {
      acceptedProposal: true,
      captureSessionStartsActive: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA lost done-event fallback');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();
    await expect(page.getByRole('heading', { name: 'Andritz QA lost done-event fallback' })).toBeVisible();

    const finalizingState = await page.evaluate(() => {
      const ng = (window as any).ng;
      const host = document.querySelector('app-knowledge-capture');
      const component = ng?.getComponent?.(host);
      if (!component) throw new Error('KnowledgeCaptureComponent instance not found');
      const win = window as any;
      const originalSetTimeout = win.setTimeout;
      win.setTimeout = (handler: (...args: unknown[]) => void, timeout?: number, ...args: unknown[]) =>
        originalSetTimeout(handler, timeout === 8000 ? 25 : timeout, ...args);
      component.setProposal(null);
      component.beginCaptureFinalizing();
      component.handleVoiceSessionEvent({
        type: 'capture.finalize.progress',
        payload: {
          stage: 'done',
          label: 'Synthèse finale persistée, attente de l’événement rapport.',
        },
      });
      win.setTimeout = originalSetTimeout;
      ng?.applyChanges?.(component);
      return {
        captureFinalizing: component.captureFinalizing(),
        activeSurface: component.activeSurface(),
        hasProposal: Boolean(component.proposal()),
      };
    });

    expect(finalizingState).toMatchObject({
      captureFinalizing: true,
      activeSurface: 'session',
      hasProposal: false,
    });
    await expect(page.locator('body')).toContainText(/Synthèse finale|Synthese finale/i);
    await expect.poll(() => proposalRequests.some((entry) => entry.includes('session_id=session-andritz-free-smoke'))).toBe(true);
    await expect(page.locator('body')).toContainText(/Rapport final éditable|Editable final report/i);
    await expect(page.locator('body')).toContainText(/Synthetic Andritz QA fact for explicit publication guard/i);

    const recoveredState = await page.evaluate(() => {
      const host = document.querySelector('app-knowledge-capture');
      const component = (window as any).ng?.getComponent?.(host);
      return {
        captureFinalizing: component?.captureFinalizing?.(),
        activeSurface: component?.activeSurface?.(),
        proposalId: component?.proposal?.()?.id || null,
      };
    });

    expect(recoveredState).toMatchObject({
      captureFinalizing: false,
      activeSurface: 'review',
      proposalId: 'proposal-andritz-qa',
    });
    expect(publishRequests).toBe(0);
  });

  test('keeps no-plan capture in-session when finalization fails', async ({ page }) => {
    const captureTurnRequests: unknown[] = [];
    const captureClosureRequests: unknown[] = [];
    let publishRequests = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals/proposal-andritz-qa/publish')) {
        publishRequests += 1;
      }
    });
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureTurnRequests,
      captureClosureRequests,
      captureClosureShouldFail: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA finalization failure smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA finalization failure smoke' })).toBeVisible();
    const captureDocuments = page.locator('section').filter({ hasText: 'Documents de capture' }).first();
    await expect(captureDocuments).toBeVisible();

    const noteText = 'La note reste dans la capture si la finalisation echoue.';
    const { input: noteInput, submit: sendButton } = captureExpressionComposer(page);
    await noteInput.fill(noteText);
    await sendButton.click();
    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: noteText,
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [],
      visual_context: null,
    });

    await page.getByRole('button', { name: /Terminer la capture|Finish capture/i }).click();

    await expect.poll(() => captureClosureRequests.length).toBe(1);
    expect(captureClosureRequests[0]).toMatchObject({ action: 'finish' });
    await expect(page.getByText('Action de fin de session impossible.')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Andritz QA document capture smoke|Andritz QA finalization failure smoke/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Terminer la capture|Finish capture/i })).toBeVisible();
    expect(publishRequests).toBe(0);
  });

  test('finishes an empty no-plan capture without creating a bogus proposal', async ({ page }) => {
    const captureClosureRequests: unknown[] = [];
    let publishRequests = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/api/v1/knowledge-capture/proposals/proposal-andritz-qa/publish')) {
        publishRequests += 1;
      }
    });
    await installAndritzMocks(page, {
      captureSessionStartsActive: true,
      captureClosureRequests,
      captureClosureNoProposal: true,
    });

    await page.goto('/knowledge/capture?exp=v0');
    await page.getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i }).click();
    await page
      .getByPlaceholder(/Usure prématurée des paliers|Premature bearing wear/i)
      .fill('Andritz QA empty no-plan smoke');
    await page.getByRole('button', { name: /^Continuer$|^Continue$/i }).click();

    await expect(page.getByRole('heading', { name: 'Andritz QA empty no-plan smoke' })).toBeVisible();
    await expect(page.locator('body')).toContainText(/La transcription de l’échange apparaîtra ici|Démarrez la conversation/i);

    await page.getByRole('button', { name: /Terminer la capture|Finish capture/i }).click();

    await expect.poll(() => captureClosureRequests.length).toBe(1);
    expect(captureClosureRequests[0]).toMatchObject({ action: 'finish' });
    await expect(page.getByText('Aucun rapport exploitable n’a encore été produit.')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Andritz QA empty no-plan smoke' })).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Rapport final éditable|Editable final report/i);
    await expect(page.locator('body')).not.toContainText(/Aperçu de la fiche|Sheet preview/i);
    expect(publishRequests).toBe(0);
  });

  test('streams a mocked Recherche answer with source grounding without real backend data', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    await installAndritzMocks(page, { chatStreamRequests });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Que dit la documentation Andritz QA ?');
    await input.press('Enter');

    await expect(page.getByText('Que dit la documentation Andritz QA ?')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    const sourcesToggle = page.getByRole('button', { name: /Sources · 1|1 sources/i }).first();
    await expect(sourcesToggle).toBeVisible();
    await sourcesToggle.click();
    await expect(page.getByText(/Andritz QA safe document|andritz-qa-safe\.pdf/i)).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Que dit la documentation Andritz QA ?',
      session_id: 'chat-session-andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('records Recherche answer feedback without changing the answer or source scope', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const auditRequests: unknown[] = [];
    await installAndritzMocks(page, { chatStreamRequests, auditRequests });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Cette réponse Andritz QA est-elle vérifiable ?');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    const helpful = page.getByTitle('Helpful').first();
    const notHelpful = page.getByTitle('Not helpful').first();
    await expect(helpful).toBeVisible();
    await expect(notHelpful).toBeVisible();

    await helpful.click();
    await expect(helpful).toHaveClass(/text-emerald-400/);
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();

    await notHelpful.click();
    await expect(notHelpful).toHaveClass(/text-red-400/);
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await expect(page.getByRole('button', { name: /Sources · 1|1 sources/i }).first()).toBeVisible();

    expect(chatStreamRequests).toHaveLength(1);
    await expect.poll(() => auditRequests.filter((entry) => (entry as { event_type?: string }).event_type === 'chat_feedback').length).toBe(2);
    const feedbackAuditRequests = auditRequests.filter(
      (entry) => (entry as { event_type?: string }).event_type === 'chat_feedback',
    );
    expect(feedbackAuditRequests).toEqual([
      expect.objectContaining({
        event_type: 'chat_feedback',
        actor: 'user',
        severity: 'info',
        details: expect.objectContaining({ verdict: 'up' }),
      }),
      expect.objectContaining({
        event_type: 'chat_feedback',
        actor: 'user',
        severity: 'info',
        details: expect.objectContaining({ verdict: 'down' }),
      }),
    ]);
  });

  test('keeps Recherche answer feedback local when audit logging fails', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const auditRequests: unknown[] = [];
    await installAndritzMocks(page, { chatStreamRequests, auditRequests, auditShouldFail: true });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Le retour utilisateur doit rester non bloquant.');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    const helpful = page.getByTitle('Helpful').first();
    await helpful.click();

    await expect(helpful).toHaveClass(/text-emerald-400/);
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await expect(page.getByRole('button', { name: /Sources · 1|1 sources/i }).first()).toBeVisible();
    await expect(input).toBeEnabled();

    expect(chatStreamRequests).toHaveLength(1);
    await expect.poll(() => auditRequests.filter((entry) => (entry as { event_type?: string }).event_type === 'chat_feedback').length).toBe(1);
    expect(auditRequests).toContainEqual(
      expect.objectContaining({
        event_type: 'chat_feedback',
        details: expect.objectContaining({ verdict: 'up' }),
      }),
    );
  });

  test('keeps Recherche Quick ask responsive with a long prompt', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });
    const longPrompt = Array.from(
      { length: 90 },
      (_, index) =>
        `Segment ${index + 1}: explique la procedure Andritz QA, les contraintes source et les exceptions de validation sans ajouter de document temporaire.`,
    ).join(' ');

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill(longPrompt);
    await input.press('Enter');

    await expect(page.getByText('Segment 1: explique la procedure Andritz QA').first()).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await expect(input).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: longPrompt,
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('keeps Recherche progress visible while mocked retrieval is slow', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatStreamDelayMs: 1500,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Analyse lentement les sources Andritz QA.');
    await input.press('Enter');

    await expect.poll(() => chatStreamRequests.length).toBe(1);
    await expect(page.getByText('Analyse lentement les sources Andritz QA.')).toBeVisible();
    await expect(page.getByText(/Préparation de la requête|Recherche dans les documents/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Streaming|En cours/i })).toBeVisible();
    await expect(input).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();

    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Analyse lentement les sources Andritz QA.',
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('recovers Recherche composer when the mocked stream is interrupted', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatStreamAbort: true,
      chatStreamAbortDelayMs: 500,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Interromps le flux Recherche Andritz QA.');
    await input.press('Enter');

    await expect.poll(() => chatStreamRequests.length).toBe(1);
    await expect(page.getByText('Interromps le flux Recherche Andritz QA.')).toBeVisible();
    await expect(page.getByText(/Préparation de la requête|Recherche dans les documents/i)).toBeVisible();
    await expect(page.getByText(/Failed to fetch|Load failed|NetworkError|fetch/i)).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toHaveCount(0);
    await expect(input).toBeEnabled();
    await input.fill('Nouvelle question apres interruption.');
    await expect(input).toHaveValue('Nouvelle question apres interruption.');

    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Interromps le flux Recherche Andritz QA.',
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('tracks a mocked auto Deep Search job from stream queue to completed answer', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const workspaceJobRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      workspaceJobRequests,
      chatStreamDeepQueued: true,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Lance une recherche approfondie Andritz QA.');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await expect(page.getByText('Recherche approfondie lancée pour affiner cette réponse.')).toBeVisible();
    await expect(page.getByText(/Deep queued|Deep 10|Deep running/i)).toBeVisible();

    await expect.poll(() => workspaceJobRequests.length, { timeout: 6_000 }).toBeGreaterThanOrEqual(1);
    await expect(page.getByText('Synthetic deep retrieval answer with expanded Andritz evidence')).toBeVisible();
    await expect(page.getByText(/Deep done · 4/i)).toBeVisible();
    await expect(page.getByText(/4 passages/i)).toBeVisible();
    await expect(page.getByText(/2 sources/i)).toBeVisible();

    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Lance une recherche approfondie Andritz QA.',
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('records Recherche feedback on a promoted Deep Search answer without changing its scope', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const workspaceJobRequests: string[] = [];
    const auditRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      workspaceJobRequests,
      auditRequests,
      chatStreamDeepQueued: true,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Note la réponse approfondie Andritz QA.');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await expect.poll(() => workspaceJobRequests.length, { timeout: 6_000 }).toBeGreaterThanOrEqual(1);
    await expect(page.getByText('Synthetic deep retrieval answer with expanded Andritz evidence')).toBeVisible();

    const deepAnswer = page
      .locator('div.flex.flex-col.gap-2')
      .filter({ hasText: 'Synthetic deep retrieval answer with expanded Andritz evidence' })
      .last();
    const helpful = deepAnswer.getByRole('button', { name: 'Helpful', exact: true });
    await helpful.click();
    await expect(helpful).toHaveClass(/text-emerald-400/);
    await expect(deepAnswer.getByText('Synthetic deep retrieval answer with expanded Andritz evidence')).toBeVisible();

    const deepSourcesToggle = deepAnswer.getByRole('button', { name: /Sources · 1|1 sources/i });
    await expect(deepSourcesToggle).toBeVisible();
    await deepSourcesToggle.click();
    await expect(deepAnswer.getByText('Andritz deep evidence', { exact: true })).toBeVisible();
    await expect(deepAnswer.getByTitle('Page 2', { exact: true })).toBeVisible();

    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatStreamRequests).toHaveLength(1);
    await expect.poll(() => auditRequests.filter((entry) => (entry as { event_type?: string }).event_type === 'chat_feedback').length).toBe(1);
    expect(auditRequests).toContainEqual(
      expect.objectContaining({
        event_type: 'chat_feedback',
        details: expect.objectContaining({
          message_id: 'deep-msg-andritz-1',
          verdict: 'up',
        }),
      }),
    );
  });

  test('sends the selected Recherche system scope in the chat payload', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatSystemsRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatSystemsRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
      chatSystems: [
        {
          id: 'system-andritz-recherche',
          name: 'Andritz Recherche transverse',
          objective: 'Répondre avec le contexte transverse Andritz QA.',
          settings: { system_type: 'workspace_chat' },
          flow_definition: { variant: 'chat_transverse_v1' },
          status: 'active',
        },
      ],
    });

    await page.goto('/chat');
    await expect.poll(() => chatSystemsRequests.length).toBeGreaterThan(0);
    const systemPicker = page.locator('select.t-picker').first();
    await expect(systemPicker).toBeVisible();
    await systemPicker.selectOption({ label: 'Andritz Recherche transverse' });
    await expect(page.getByText('System chat').first()).toBeVisible();
    await expect(page.getByText('Répondre avec le contexte transverse Andritz QA.')).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Utilise le système Recherche transverse Andritz.');
    await input.press('Enter');

    await expect(page.getByText('Utilise le système Recherche transverse Andritz.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        system_id: 'system-andritz-recherche',
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Utilise le système Recherche transverse Andritz.',
      agent_id: 'system-andritz-recherche',
      session_id: 'chat-session-andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('falls back to Quick ask when a preselected Recherche system is stale', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatSystemsRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatSystemsRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
      chatSystems: [],
    });

    await page.goto('/workspace/andritz/chat?mode=system&systemId=system-deleted-andritz');
    await expect.poll(() => chatSystemsRequests.length).toBeGreaterThan(0);
    await expect(page.getByText('Quick ask').first()).toBeVisible();
    await expect(page.getByText('Contexte du workspace')).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Continue sans système supprimé.');
    await input.press('Enter');

    await expect(page.getByText('Continue sans système supprimé.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        system_id: null,
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Continue sans système supprimé.',
      agent_id: null,
      session_id: 'chat-session-andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('keeps Recherche usable when the system catalogue is forbidden', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatSystemsRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatSystemsRequests,
      chatSystemsShouldFail: true,
      chatSystemsFailureStatus: 403,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/workspace/andritz/chat?mode=system&systemId=system-forbidden-andritz');
    await expect.poll(() => chatSystemsRequests.length).toBeGreaterThan(0);
    await expect(page.getByText('Quick ask').first()).toBeVisible();
    await expect(page.getByText('Contexte du workspace')).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Continue sans accès catalogue systèmes.');
    await input.press('Enter');

    await expect(page.getByText('Continue sans accès catalogue systèmes.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        system_id: null,
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Continue sans accès catalogue systèmes.',
      agent_id: null,
      session_id: 'chat-session-andritz-qa',
      stream: true,
      include_sources: true,
      include_reasoning: true,
    });
  });

  test('opens a mocked Recherche source preview without real backend data', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const sourcePreviewRequests: string[] = [];
    await installAndritzMocks(page, { chatStreamRequests, sourcePreviewRequests });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Montre la source Andritz QA.');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    const sourcesToggle = page.getByRole('button', { name: /Sources · 1|1 sources/i }).first();
    await sourcesToggle.click();
    await page.getByTitle('Preview source document').first().click();

    await expect.poll(() => sourcePreviewRequests.length).toBe(1);
    const params = new URLSearchParams(sourcePreviewRequests[0].replace(/^\?/, ''));
    expect(params.get('collection_name')).toBe('andritz-qa');
    expect(params.get('filename')).toBe('andritz-qa-safe.pdf');
    await expect(page.getByRole('heading', { name: /Andritz QA safe document/i })).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA source preview full text.')).toBeVisible();
    await expect(page.locator('#omnirag-hl-anchor')).toContainText('Synthetic Andritz QA source snippet.');
    expect(chatStreamRequests).toHaveLength(1);
  });

  test('shows a recoverable error when a mocked Recherche source preview is unavailable', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const sourcePreviewRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      sourcePreviewRequests,
      sourcePreviewShouldFail: true,
    });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Ouvre une source indisponible Andritz QA.');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await page.getByRole('button', { name: /Sources · 1|1 sources/i }).first().click();
    await page.getByTitle('Preview source document').first().click();

    await expect.poll(() => sourcePreviewRequests.length).toBe(1);
    const params = new URLSearchParams(sourcePreviewRequests[0].replace(/^\?/, ''));
    expect(params.get('collection_name')).toBe('andritz-qa');
    expect(params.get('filename')).toBe('andritz-qa-safe.pdf');
    await expect(page.getByRole('heading', { name: /Andritz QA safe document/i })).toBeVisible();
    await expect(page.getByText('Mocked source preview unavailable')).toBeVisible();
    await expect(page.locator('app-chat-panel textarea[name="userInput"]').first()).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
  });

  test('does not leak content when a mocked Recherche source preview is forbidden', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const sourcePreviewRequests: string[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      sourcePreviewRequests,
      sourcePreviewForbidden: true,
    });

    await page.goto('/chat');
    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Ouvre une source interdite Andritz QA.');
    await input.press('Enter');

    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    await page.getByRole('button', { name: /Sources · 1|1 sources/i }).first().click();
    await page.getByTitle('Preview source document').first().click();

    await expect.poll(() => sourcePreviewRequests.length).toBe(1);
    const params = new URLSearchParams(sourcePreviewRequests[0].replace(/^\?/, ''));
    expect(params.get('collection_name')).toBe('andritz-qa');
    expect(params.get('filename')).toBe('andritz-qa-safe.pdf');
    await expect(page.getByRole('heading', { name: /Andritz QA safe document/i })).toBeVisible();
    await expect(page.getByText('Mocked source preview permission denied')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA source preview full text.')).toHaveCount(0);
    await expect(page.locator('#omnirag-hl-anchor')).toHaveCount(0);
    await expect(page.locator('app-chat-panel textarea[name="userInput"]').first()).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
  });

  test('keeps Quick ask unscoped when no drop-and-ask session docs are attached', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await expect(page.getByText('Quick ask').first()).toBeVisible();
    await expect(page.getByText(/No docs yet/i)).toBeVisible();
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Only$/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /\+ Sources/i })).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds sans document de session ajouté.');
    await input.press('Enter');

    await expect(page.getByText('Réponds sans document de session ajouté.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatUploadRequests).toHaveLength(0);
    expect(contextCreateRequests).toHaveLength(0);
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds sans document de session ajouté.',
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
    });
  });

  test('keeps drop-and-ask session docs in the chat stream contract without real upload', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz drop-and-ask evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByText(/Session docs/i).first()).toBeVisible();

    const combineButton = page.getByRole('button', { name: /\+ Sources/i }).first();
    await expect(combineButton).toBeVisible();
    await combineButton.click();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Croise le fichier ajouté avec la base Andritz QA.');
    await input.press('Enter');

    await expect(page.getByText('Croise le fichier ajouté avec la base Andritz QA.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
      ttl_hours: 24,
    });
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'combine',
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Croise le fichier ajouté avec la base Andritz QA.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'combine',
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
    });
  });

  test('keeps drop-and-ask Only mode isolated from workspace scope without real upload', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz isolated drop-and-ask evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Only$/i }).first()).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds uniquement avec le fichier ajouté.');
    await input.press('Enter');

    await expect(page.getByText('Réponds uniquement avec le fichier ajouté.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds uniquement avec le fichier ajouté.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
    });
  });

  test('uses the latest drop-and-ask source mode after switching back to Only', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz source toggle evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();

    const combineButton = page.getByRole('button', { name: /\+ Sources/i }).first();
    const onlyButton = page.getByRole('button', { name: /^Only$/i }).first();
    await combineButton.click();
    await onlyButton.click();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Ignore les sources workspace après retour en Only.');
    await input.press('Enter');

    await expect(page.getByText('Ignore les sources workspace après retour en Only.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Ignore les sources workspace après retour en Only.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
    });
  });

  test('detaches the last drop-and-ask doc before asking without stale session scope', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextUpdateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextUpdateRequests,
      knowledgeScopes: [
        {
          key: 'andritz-qa',
          label: 'Andritz QA knowledge',
          is_default: true,
          collection_slugs: ['andritz-qa'],
        },
      ],
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz detach evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();

    await page
      .getByRole('button', { name: /Remove from this chat session: (Andritz chat drop note|andritz-chat-drop\.txt)/i })
      .first()
      .click();

    await expect.poll(() => contextUpdateRequests.length).toBe(1);
    expect(contextUpdateRequests[0]).toMatchObject({
      data_refs: [],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
    });
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Persist$/i })).toHaveCount(0);

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds après retrait du document de session.');
    await input.press('Enter');

    await expect(page.getByText('Réponds après retrait du document de session.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: null,
        context_mode: null,
        knowledge_scope: 'andritz-qa',
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds après retrait du document de session.',
      context_id: null,
      context_mode: null,
      knowledge_scope: 'andritz-qa',
      stream: true,
      include_sources: true,
    });
  });

  test('keeps remaining drop-and-ask docs scoped after detaching one file', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextUpdateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextUpdateRequests,
      chatUploadTwoSuccess: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles([
      {
        name: 'andritz-chat-drop.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Synthetic Andritz first detach evidence.'),
      },
      {
        name: 'andritz-chat-extra.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Synthetic Andritz remaining detach evidence.'),
      },
    ]);

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt', 'andritz-chat-extra.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
    });
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByText(/Andritz chat extra note|andritz-chat-extra\.txt/i).first()).toBeVisible();

    await page
      .getByRole('button', { name: /Remove from this chat session: (Andritz chat drop note|andritz-chat-drop\.txt)/i })
      .first()
      .click();

    await expect.poll(() => contextUpdateRequests.length).toBe(1);
    expect(contextUpdateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-extra.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
    });
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i)).toHaveCount(0);
    await expect(page.getByText(/Andritz chat extra note|andritz-chat-extra\.txt/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Persist$/i })).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds avec le document restant seulement.');
    await input.press('Enter');

    await expect(page.getByText('Réponds avec le document restant seulement.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds avec le document restant seulement.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
    });
  });

  test('recreates a drop-and-ask context after detaching the last doc and uploading again', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextUpdateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextUpdateRequests,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz initial detach/recreate evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    expect(contextCreateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
    });
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();

    await page
      .getByRole('button', { name: /Remove from this chat session: (Andritz chat drop note|andritz-chat-drop\.txt)/i })
      .first()
      .click();

    await expect.poll(() => contextUpdateRequests.length).toBe(1);
    expect(contextUpdateRequests[0]).toMatchObject({
      data_refs: [],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
    });
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Persist$/i })).toHaveCount(0);

    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-return.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz recreated context evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(2);
    await expect.poll(() => contextCreateRequests.length).toBe(2);
    expect(contextCreateRequests[1]).toMatchObject({
      data_refs: ['andritz-chat-return.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
      ephemeral: true,
    });
    await expect(contextUpdateRequests).toHaveLength(1);
    await expect(page.getByText(/Andritz chat return note|andritz-chat-return\.txt/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Persist$/i })).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds avec le nouveau contexte recréé.');
    await input.press('Enter');

    await expect(page.getByText('Réponds avec le nouveau contexte recréé.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds avec le nouveau contexte recréé.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
    });
  });

  test('keeps a drop-and-ask doc attached when detach context update fails', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextUpdateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextUpdateRequests,
      contextUpdateShouldFail: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz failed detach evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();

    await page
      .getByRole('button', { name: /Remove from this chat session: (Andritz chat drop note|andritz-chat-drop\.txt)/i })
      .first()
      .click();

    await expect.poll(() => contextUpdateRequests.length).toBe(1);
    await expect(page.getByRole('alert', { name: /Could not remove the file from this chat session/i })).toBeVisible();
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Persist$/i })).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds après échec de retrait du document.');
    await input.press('Enter');

    await expect(page.getByText('Réponds après échec de retrait du document.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds après échec de retrait du document.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
    });
  });

  test('rolls back only the newly added drop-and-ask doc when append context update fails', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatSessionCreateRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextUpdateRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatSessionCreateRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextUpdateRequests,
      contextUpdateShouldFail: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz initial append evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Persist$/i })).toBeVisible();

    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-return.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz failed append evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(2);
    await expect.poll(() => contextUpdateRequests.length).toBe(1);
    expect(contextUpdateRequests[0]).toMatchObject({
      data_refs: ['andritz-chat-drop.txt', 'andritz-chat-return.txt'],
      environment_state: { collection: 'documents' },
      business_constraints: { source: 'drop_and_ask' },
    });
    await expect(page.getByRole('alert', { name: /Could not attach the file to this chat session/i })).toBeVisible();
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByText(/Andritz chat return note|andritz-chat-return\.txt/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Persist$/i })).toBeVisible();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Réponds avec le premier document seulement après échec append.');
    await input.press('Enter');

    await expect(page.getByText('Réponds avec le premier document seulement après échec append.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatSessionCreateRequests).toHaveLength(1);
    expect(chatSessionCreateRequests[0]).toMatchObject({
      context: {
        context_id: 'ctx-chat-drop-and-ask',
        context_mode: 'replace',
        knowledge_scope: null,
        source_selection: 'auto',
      },
    });
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Réponds avec le premier document seulement après échec append.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      knowledge_scope: null,
      stream: true,
      include_sources: true,
    });
  });

  test('persists a mocked drop-and-ask context only after explicit user click', async ({ page }) => {
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextPersistRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatUploadRequests,
      contextCreateRequests,
      contextPersistRequests,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz persist evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Persist$/i })).toBeVisible();
    expect(contextPersistRequests).toHaveLength(0);

    await page.getByRole('button', { name: /^Persist$/i }).click();

    await expect.poll(() => contextPersistRequests.length).toBe(1);
    await expect(page.getByRole('alert', { name: /Saved as "Drop-and-ask · synthetic"/i })).toBeVisible();
  });

  test('shows a recoverable error when mocked drop-and-ask context persistence fails', async ({ page }) => {
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextPersistRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatUploadRequests,
      contextCreateRequests,
      contextPersistRequests,
      contextPersistShouldFail: true,
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz failed persist evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    const persistButton = page.getByRole('button', { name: /^Persist$/i });
    await expect(persistButton).toBeVisible();
    expect(contextPersistRequests).toHaveLength(0);

    await persistButton.click();

    await expect.poll(() => contextPersistRequests.length).toBe(1);
    await expect(page.getByRole('alert', { name: /Failed to persist session/i })).toBeVisible();
    await expect(persistButton).toBeEnabled();
  });

  test('keeps chat usable when a mocked drop-and-ask context has expired before persist', async ({ page }) => {
    const chatStreamRequests: unknown[] = [];
    const chatUploadRequests: string[] = [];
    const contextCreateRequests: unknown[] = [];
    const contextPersistRequests: unknown[] = [];
    await installAndritzMocks(page, {
      chatStreamRequests,
      chatUploadRequests,
      contextCreateRequests,
      contextPersistRequests,
      contextPersistShouldFail: true,
      contextPersistFailureStatus: 410,
      contextPersistFailureDetail: 'Drop-and-ask context expired',
    });

    await page.goto('/chat');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'andritz-chat-drop.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Synthetic Andritz expired persist evidence.'),
    });

    await expect.poll(() => chatUploadRequests.length).toBe(1);
    await expect.poll(() => contextCreateRequests.length).toBe(1);
    await expect(page.getByText(/Andritz chat drop note|andritz-chat-drop\.txt/i).first()).toBeVisible();
    const persistButton = page.getByRole('button', { name: /^Persist$/i });
    await expect(persistButton).toBeVisible();

    await persistButton.click();

    await expect.poll(() => contextPersistRequests.length).toBe(1);
    await expect(page.getByRole('alert', { name: /Failed to persist session/i })).toBeVisible();
    await expect(persistButton).toBeEnabled();

    const input = page.locator('app-chat-panel textarea[name="userInput"]').first();
    await input.fill('Le chat reste utilisable après expiration du contexte.');
    await input.press('Enter');

    await expect(page.getByText('Le chat reste utilisable après expiration du contexte.')).toBeVisible();
    await expect(page.getByText('Synthetic Andritz QA answer with cited source')).toBeVisible();
    expect(chatStreamRequests).toHaveLength(1);
    expect(chatStreamRequests[0]).toMatchObject({
      query: 'Le chat reste utilisable après expiration du contexte.',
      context_id: 'ctx-chat-drop-and-ask',
      context_mode: 'replace',
      stream: true,
      include_sources: true,
    });
  });
});
