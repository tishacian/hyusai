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
            sources: [],
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

async function installAndritzMocks(
  page: Page,
  options: {
    roleTemplate?: MockRoleTemplate;
    secureDepositEnabled?: boolean;
    chatDocumentUploadEnabled?: boolean;
    collectionsShouldFail?: boolean;
    documentListShouldFail?: boolean;
    documentListEmpty?: boolean;
    documentListRequests?: string[];
    collectionPreviewRequests?: string[];
    collectionPreviewUnsafeContent?: boolean;
    collectionPreviewForbidden?: boolean;
    collectionPreviewForbiddenAfterFirstSuccess?: boolean;
    searchShouldFail?: boolean;
    chatUploadShouldFail?: boolean;
    chatUploadPartialFailure?: boolean;
    chatUploadTwoSuccess?: boolean;
    chatMetadataShouldFail?: boolean;
    chatMetadataLongKeywords?: boolean;
    acceptedProposal?: boolean;
    capturePlanRequests?: unknown[];
    chatStreamRequests?: unknown[];
    chatSessionCreateRequests?: unknown[];
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
    captureDocumentPreviewRequests?: string[];
    captureDocumentPreviewShouldFail?: boolean;
    contextCreateRequests?: unknown[];
    contextCreateShouldFail?: boolean;
    contextUpdateRequests?: unknown[];
    contextUpdateShouldFail?: boolean;
    contextPersistRequests?: unknown[];
    contextPersistShouldFail?: boolean;
    knowledgeScopes?: MockKnowledgeScope[];
  } = {},
) {
  const roleTemplate = options.roleTemplate ?? 'workspace_admin';
  const secureDepositEnabled = options.secureDepositEnabled ?? true;
  const chatDocumentUploadEnabled = options.chatDocumentUploadEnabled ?? true;
  const collectionsShouldFail = options.collectionsShouldFail ?? false;
  const documentListShouldFail = options.documentListShouldFail ?? false;
  const documentListEmpty = options.documentListEmpty ?? false;
  const documentListRequests = options.documentListRequests;
  const collectionPreviewRequests = options.collectionPreviewRequests;
  const collectionPreviewUnsafeContent = options.collectionPreviewUnsafeContent ?? false;
  const collectionPreviewForbidden = options.collectionPreviewForbidden ?? false;
  const collectionPreviewForbiddenAfterFirstSuccess = options.collectionPreviewForbiddenAfterFirstSuccess ?? false;
  const searchShouldFail = options.searchShouldFail ?? false;
  const chatUploadShouldFail = options.chatUploadShouldFail ?? false;
  const chatUploadPartialFailure = options.chatUploadPartialFailure ?? false;
  const chatUploadTwoSuccess = options.chatUploadTwoSuccess ?? false;
  const chatMetadataShouldFail = options.chatMetadataShouldFail ?? false;
  const chatMetadataLongKeywords = options.chatMetadataLongKeywords ?? false;
  const includeAcceptedProposal = options.acceptedProposal ?? false;
  const capturePlanRequests = options.capturePlanRequests;
  const chatStreamRequests = options.chatStreamRequests;
  const chatSessionCreateRequests = options.chatSessionCreateRequests;
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
  const captureDocumentPreviewRequests = options.captureDocumentPreviewRequests;
  const captureDocumentPreviewShouldFail = options.captureDocumentPreviewShouldFail ?? false;
  const contextCreateRequests = options.contextCreateRequests;
  const contextCreateShouldFail = options.contextCreateShouldFail ?? false;
  const contextUpdateRequests = options.contextUpdateRequests;
  const contextUpdateShouldFail = options.contextUpdateShouldFail ?? false;
  const contextPersistRequests = options.contextPersistRequests;
  const contextPersistShouldFail = options.contextPersistShouldFail ?? false;
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
        return json(route, { detail: 'Persist permission denied' }, 403);
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
      return json(route, { systems: [] });
    }

    if (path === '/documents/collections') {
      if (collectionsShouldFail) {
        return json(route, { detail: 'Collections service unavailable' }, 500);
      }
      return json(route, {
        collections: ['andritz-qa'],
        default: 'andritz-qa',
        items: [
          {
            slug: 'andritz-qa',
            name: 'Andritz QA',
            document_count: 2,
            chunk_count: 12,
            updated_at: '2026-06-23T00:00:00Z',
            status: 'ready',
          },
        ],
      });
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
    if (path === '/documents/upload-batch' && method === 'POST') {
      const uploadBody = request.postData() || '';
      chatUploadRequests?.push(uploadBody);
      if (chatUploadShouldFail) {
        return json(route, { detail: 'Mocked upload failure' }, 500);
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
      return json(
        route,
        createdFreeConversationSession(
          String(body['title'] || 'Andritz QA free conversation smoke'),
          captureSessionStartsActive ? 'active' : 'draft',
        ),
      );
    }
    if (path === '/knowledge-capture/sessions') {
      return json(route, { sessions: includeAcceptedProposal ? [acceptedCaptureSession()] : [] });
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
          session: createdFreeConversationSession('Andritz QA document capture smoke', 'active'),
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
        session: createdFreeConversationSession('Andritz QA document capture smoke', 'active'),
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/turns' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      captureTurnRequests?.push(body);
      const noteText = String(body['text'] || 'Synthetic written capture note.');
      return json(route, {
        session: {
          ...createdFreeConversationSession('Andritz QA document capture smoke', 'active'),
          transcript: [
            {
              id: 'turn-written-capture-doc',
              speaker: 'expert',
              text: noteText,
              input_modality: 'text',
              document_refs: body['document_refs'] || [],
              visual_context: body['visual_context'] || null,
            },
          ],
        },
        evaluation: null,
        next_prompt: null,
        next_question_id: null,
        system_prompt_event_id: null,
      });
    }
    if (path === '/knowledge-capture/sessions/session-andritz-free-smoke/events') {
      return json(route, { events: [] });
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
        status: 'ok',
        workspace: 'andritz',
        enabled: true,
        default_allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx', '.png', '.jpg'],
      });
    }
    if (path === '/sftp/links') {
      return json(route, {
        links: [
          {
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
          },
        ],
      });
    }
    if (path === '/sftp/deposits') {
      return json(route, { files: [] });
    }
    if (path === '/sftp/operations') {
      return json(route, emptyOperations());
    }
    if (path === '/sftp/deposits/indexing-assist') {
      return json(route, {
        collection: { slug: 'andritz-qa', name: 'Andritz QA', jobs: [] },
        files: [],
        summary: { recommended: 0, needs_review: 0, blocked: 0 },
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
      return sse(route, [
        {
          chunk_type: 'session',
          session_id: 'chat-session-andritz-qa',
        },
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
      ]);
    }
    if (path.startsWith('/chat/')) {
      return json(route, path.endsWith('/sessions') ? { sessions: [] } : {});
    }
    if (path === '/actions/effective') {
      return json(route, { actions: [] });
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
    await expect(page.locator('body')).toContainText(/Vos sessions|Sessions de capture|Nouvelle capture|Capture sessions|New session/i);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Question rapide|Posez votre question|Quick ask|Ask/i);
  });

  test('shows disabled SFTP connector as ready but not configured', async ({ page }) => {
    await installAndritzMocks(page, { secureDepositEnabled: false });

    await page.goto('/connectors');
    const sftpCard = page.locator('article').filter({ hasText: 'SFTP / Secure Deposit' }).first();
    await expect(sftpCard).toBeVisible();
    await expect(sftpCard).toContainText(/ready/i);
    await expect(sftpCard).not.toContainText(/configured|Config saved/i);
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

    await page.goto('/knowledge/capture');
    await expect(page.locator('body')).toContainText(/Capture sessions|Sessions de capture|New session|Nouvelle capture/i);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Quick ask|Question rapide|Ask|Posez votre question/i);
  });

  test('enables new capture for reviewer IAM matrix', async ({ page }) => {
    await installAndritzMocks(page, { roleTemplate: 'workspace_reviewer' });

    await page.goto('/knowledge/capture');
    const newCapture = page
      .getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i })
      .first();
    await expect(newCapture).toBeVisible();
    await expect(newCapture).toBeEnabled();
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

    await page.goto('/knowledge/capture');
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

  test('creates a no-plan capture from the browser without exposing the plan rail', async ({ page }) => {
    const capturePlanRequests: unknown[] = [];
    await installAndritzMocks(page, { capturePlanRequests });

    await page.goto('/knowledge/capture');
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
    expect(capturePlanRequests).toHaveLength(1);
    expect(capturePlanRequests[0]).toMatchObject({
      title: 'Andritz QA free conversation smoke',
      plan_mode: 'free_conversation',
      voice_runtime: 'cascade_openai',
    });
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

    await page.goto('/knowledge/capture');
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
    await expect(captureDocuments.getByText(/Vue active : Andritz capture reference · page 1/i)).toBeVisible();

    const noteInput = captureDocuments.getByPlaceholder('Note écrite liée au tour ou à la vue active...');
    await noteInput.fill('Sur cette page, le convoyeur de test Andritz reste aligné.');
    await captureDocuments.getByRole('button', { name: /Ajouter la note/i }).click();

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

  test('keeps written capture references scoped to the latest active document', async ({ page }) => {
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

    await page.goto('/knowledge/capture');
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
    await expect(captureDocuments.getByText(/Vue active : Andritz capture reference · page 1/i)).toBeVisible();

    await page.getByRole('button', { name: /Andritz capture photo/i }).click();
    await expect(page.getByText('Synthetic capture photo content for the second active visual context.')).toBeVisible();
    await page.getByRole('button', { name: /Close preview/i }).click();
    await expect(captureDocuments.getByText(/Vue active : Andritz capture photo · page 1/i)).toBeVisible();

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

    const noteInput = captureDocuments.getByPlaceholder('Note écrite liée au tour ou à la vue active...');
    await noteInput.fill('Sur cette photo, la zone d accès maintenance Andritz reste visible.');
    await captureDocuments.getByRole('button', { name: /Ajouter la note/i }).click();

    await expect.poll(() => captureTurnRequests.length).toBe(1);
    expect(captureTurnRequests[0]).toMatchObject({
      speaker: 'expert',
      text: 'Sur cette photo, la zone d accès maintenance Andritz reste visible.',
      turn_kind: 'complement',
      input_modality: 'text',
      document_refs: [
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
    expect(JSON.stringify(captureTurnRequests[0])).not.toContain('doc-capture-reference');
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

    await page.goto('/knowledge/capture');
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
    await expect(captureDocuments.getByText(/Vue active : Andritz capture reference · page 1/i)).toBeVisible();

    const noteInput = captureDocuments.getByPlaceholder('Note écrite liée au tour ou à la vue active...');
    await noteInput.fill('Le document reste lie au tour meme si la preview est temporairement indisponible.');
    await captureDocuments.getByRole('button', { name: /Ajouter la note/i }).click();

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

    await page.goto('/knowledge/capture');
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
    await expect(captureDocuments.getByText(/Vue active : Andritz capture reference · page 1/i)).toBeVisible();

    const noteInput = captureDocuments.getByPlaceholder('Note écrite liée au tour ou à la vue active...');
    await noteInput.fill('Sur cette page, le repère Andritz reste exploitable malgré l audit différé.');
    await captureDocuments.getByRole('button', { name: /Ajouter la note/i }).click();

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

    await page.goto('/knowledge/capture');
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

    const noteInput = captureDocuments.getByPlaceholder('Note écrite liée au tour ou à la vue active...');
    await noteInput.fill('La note écrite continue même sans document attaché.');
    await captureDocuments.getByRole('button', { name: /Ajouter la note/i }).click();

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

    await page.goto('/knowledge/capture');
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

    const noteInput = captureDocuments.getByPlaceholder('Note écrite liée au tour ou à la vue active...');
    await noteInput.fill('La capture reste disponible apres le rejet du document.');
    await captureDocuments.getByRole('button', { name: /Ajouter la note/i }).click();

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
});
