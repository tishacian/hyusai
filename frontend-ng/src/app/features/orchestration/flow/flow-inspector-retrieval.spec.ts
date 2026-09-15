import '@angular/compiler';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { Skill } from '@app/core/canonical-api.service';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FLOW_EN } from '@app/core/i18n/flow.dict';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  FlowInspectorComponent,
  publishedNodeExecutor,
  buildCollectionOptions,
  buildRetrievalDocumentOptions,
} from './flow-inspector.component';

function retrievalNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'retrieve-a',
    type: 'skill',
    kind: 'task',
    label: 'Retrieve',
    config: { skill_slug: 'semantic_search_v1', ...config },
  };
}

function prototypeInspector(): FlowInspectorComponent {
  // These normalization helpers are deliberately instance methods but do not
  // depend on Angular lifecycle state. Calling the prototype keeps this
  // contract dependency-light while exercising the actual implementation.
  return Object.create(FlowInspectorComponent.prototype) as FlowInspectorComponent;
}

test('Retrieval identity is task-only and supports runtime and Skill aliases', () => {
  const inspector = prototypeInspector();
  assert.equal(inspector.isRetrievalNode(retrievalNode()), true);
  assert.equal(inspector.isRetrievalNode({
    id: 'retrieve-by-taxonomy',
    type: 'skill',
    kind: 'task',
    config: {
      skill_slug: 'opaque_vendor_operation_v3',
      skill_category: ' Retrieval ',
    },
  }), true);
  assert.equal(inspector.isRetrievalNode({
    id: 'retrieve-b',
    type: 'retrieve.documents',
    kind: 'task',
    config: {},
  }), true);
  assert.equal(inspector.isRetrievalNode({
    id: 'retrieve-c',
    type: 'skill',
    kind: 'task',
    config: { skill_slug: 'rag-search-v1' },
  }), true);
  assert.equal(inspector.isRetrievalNode({
    id: 'asset-a',
    type: 'semantic_search',
    kind: 'asset',
    config: { skill_category: 'Retrieval' },
  }), false);
  assert.equal(inspector.isRetrievalNode({
    id: 'task-a',
    type: 'skill',
    kind: 'task',
    config: { skill_slug: 'calendar_read_v1' },
  }), false);
});

test('per-node collections and document refs normalize without cross-node state', () => {
  const inspector = prototypeInspector();
  const node = retrievalNode({
    collection_slugs: [' beta ', 'alpha', '', 'alpha', null],
    document_refs: [
      { collection_slug: 'alpha', document_id: 'doc-1' },
      { collection_slug: 'alpha', document_id: 'doc-1' },
      { collection_slug: 'beta', document_id: ' doc-2 ' },
      { collection_slug: '', document_id: 'ignored' },
      null,
    ],
  });

  assert.deepEqual(inspector.retrievalCollections(node), ['alpha', 'beta']);
  assert.deepEqual(inspector.retrievalDocumentRefs(node), [
    { collection_slug: 'alpha', document_id: 'doc-1' },
    { collection_slug: 'beta', document_id: 'doc-2' },
  ]);
  assert.equal(inspector.retrievalDocumentSelected(node, 'alpha', 'doc-1'), true);
  assert.equal(inspector.retrievalDocumentSelected(node, 'alpha', 'doc-2'), false);
  assert.deepEqual(inspector.retrievalCollections(retrievalNode()), []);
  assert.deepEqual(inspector.retrievalDocumentRefs(retrievalNode()), []);
});

test('persisted refs outside the bounded catalogue remain visible and deselectable', () => {
  const options = buildRetrievalDocumentOptions(
    ['alpha'],
    () => [{ id: 'doc-visible', filename: 'Visible.pdf', status: 'ready' }],
    [
      { collection_slug: 'alpha', document_id: 'doc-visible' },
      { collection_slug: 'alpha', document_id: 'doc-after-page-1000' },
      { collection_slug: 'removed-scope', document_id: 'doc-hidden' },
    ],
  );

  assert.deepEqual(options, [
    {
      id: 'doc-visible',
      filename: 'Visible.pdf',
      status: 'ready',
      collection: 'alpha',
      key: 'alpha\u0000doc-visible',
      catalogued: true,
    },
    {
      id: 'doc-after-page-1000',
      filename: 'doc-after-page-1000',
      status: null,
      collection: 'alpha',
      key: 'alpha\u0000doc-after-page-1000',
      catalogued: false,
    },
  ]);
});

test('persisted Retrieval collections remain visible when absent from the catalogue', () => {
  assert.deepEqual(
    buildCollectionOptions(
      ['catalog-a', 'catalog-b', 'catalog-a'],
      [' removed-z ', 'catalog-b', 'removed-z'],
    ),
    ['removed-z', 'catalog-a', 'catalog-b'],
  );
});

test('changing Retrieval collections prunes document refs outside the new scope', () => {
  const inspector = prototypeInspector() as unknown as {
    node: () => CanonicalFlowNode;
    store: { patchNode: (id: string, patch: Partial<CanonicalFlowNode>) => void };
    patchRetrievalCollections: (collections: string[]) => void;
  };
  const node = retrievalNode({
    collection_slugs: ['alpha', 'beta'],
    document_refs: [
      { collection_slug: 'alpha', document_id: 'doc-a' },
      { collection_slug: 'beta', document_id: 'doc-b' },
    ],
  });
  const patches: Array<{ id: string; patch: Partial<CanonicalFlowNode> }> = [];
  inspector.node = () => node;
  inspector.store = { patchNode: (id, patch) => patches.push({ id, patch }) };

  inspector.patchRetrievalCollections([' beta ', 'beta', 'gamma']);

  assert.equal(patches.length, 1);
  assert.equal(patches[0].id, 'retrieve-a');
  assert.deepEqual(patches[0].patch.config, {
    skill_slug: 'semantic_search_v1',
    collection_slugs: ['beta', 'gamma'],
    document_refs: [{ collection_slug: 'beta', document_id: 'doc-b' }],
  });
});

test('document multi-select writes explicit collection/document pairs', () => {
  const inspector = prototypeInspector() as unknown as {
    node: () => CanonicalFlowNode;
    store: { patchNode: (id: string, patch: Partial<CanonicalFlowNode>) => void };
    onRetrievalDocuments: (event: Event) => void;
  };
  const node = retrievalNode({ collection_slugs: ['alpha', 'beta'] });
  const patches: Partial<CanonicalFlowNode>[] = [];
  inspector.node = () => node;
  inspector.store = { patchNode: (_id, patch) => patches.push(patch) };

  inspector.onRetrievalDocuments({
    target: {
      selectedOptions: [
        { value: 'alpha\u0000doc-a' },
        { value: 'beta\u0000doc-b' },
        { value: 'malformed' },
      ],
    },
  } as unknown as Event);

  assert.deepEqual(patches[0].config, {
    skill_slug: 'semantic_search_v1',
    collection_slugs: ['alpha', 'beta'],
    document_refs: [
      { collection_slug: 'alpha', document_id: 'doc-a' },
      { collection_slug: 'beta', document_id: 'doc-b' },
    ],
  });
});

test('Retrieval picker rejects client scopes beyond the server bounds', () => {
  const errors: Array<string | null> = [];
  const patches: Partial<CanonicalFlowNode>[] = [];
  const inspector = prototypeInspector() as unknown as {
    node: () => CanonicalFlowNode;
    store: { patchNode: (id: string, patch: Partial<CanonicalFlowNode>) => void };
    retrievalScopeError: { set: (message: string | null) => void };
    i18n: { t: (key: keyof typeof FLOW_EN) => string };
    onRetrievalDocuments: (event: Event) => void;
    patchRetrievalCollections: (collections: string[]) => void;
  };
  inspector.node = () => retrievalNode({ collection_slugs: ['alpha'] });
  inspector.store = { patchNode: (_id, patch) => patches.push(patch) };
  inspector.retrievalScopeError = { set: (message) => errors.push(message) };
  inspector.i18n = { t: (key) => FLOW_EN[key] };

  inspector.patchRetrievalCollections(
    Array.from({ length: 33 }, (_item, index) => `collection-${index}`),
  );
  inspector.onRetrievalDocuments({
    target: {
      selectedOptions: Array.from(
        { length: 1001 },
        (_item, index) => ({ value: `alpha\u0000doc-${index}` }),
      ),
    },
  } as unknown as Event);

  assert.deepEqual(patches, []);
  assert.match(errors[0] ?? '', /at most 32 collections/i);
  assert.match(errors[1] ?? '', /at most 1000 documents/i);
});


test('published Skill execution preview matches the exact node and Skill without changing the draft', () => {
  const executor = { kind: 'prompt_template', params: { provider: 'ollama', template: 'Published {question}' } };
  const node = retrievalNode({ skill_id: 'skill-1' });
  const before = JSON.stringify(node);
  const contract = { nodes: { [node.id]: { skill_slug: 'semantic_search_v1', skill_id: 'skill-1', executor } } };
  assert.deepEqual(publishedNodeExecutor(node, contract), executor);
  assert.equal(JSON.stringify(node), before);
  assert.equal(publishedNodeExecutor({ ...node, id: 'different-node' }, contract), null);
  assert.equal(publishedNodeExecutor(retrievalNode({ skill_slug: 'another-skill' }), contract), null);
  assert.equal(publishedNodeExecutor(retrievalNode({ skill_id: 'recreated-skill' }), contract), null);
  assert.equal(publishedNodeExecutor(node, null), null);
  assert.equal(publishedNodeExecutor(node, { nodes: { [node.id]: { skill_slug: 'semantic_search_v1', skill_id: 'skill-1' } } }), null);
  assert.equal(publishedNodeExecutor(node, { nodes: { [node.id]: { skill_slug: 'semantic_search_v1', skill_id: 'skill-1', executor: { kind: 'prompt_template', params: [] } } } }), null);
});

test('current Skill lookup remains read-only and distinguishes missing configuration from a pending response', () => {
  const inspector = prototypeInspector() as any;
  const node = retrievalNode();
  const before = JSON.stringify(node);
  const response = new Subject<Skill | null>();
  const scope = { workspaceSlug: 'showcase', workspaceId: 'ws-1', epoch: 1 };
  inspector.node = signal(node);
  inspector.systemId = signal('system-1');
  inspector.skillDefinition = signal(null);
  inspector.workspace = { captureRequestScope: () => scope, isRequestScopeCurrent: () => true };
  inspector.canonical = { getSkill: (slug: string) => { assert.equal(slug, 'semantic_search_v1'); return response; } };
  const request = inspector.loadSkillExecution(node.id, 'semantic_search_v1', 'system-1');
  assert.equal(inspector.skillDefinition(), null, 'pending requests show loading');
  response.next({ id: 'skill-1', slug: 'semantic_search_v1', name: 'Skill', executor: { kind: 'prompt_template', params: { provider: 'azure', template: 'Current {question}' } } });
  assert.equal(inspector.skillDefinition().executor.params.provider, 'azure');
  assert.equal(JSON.stringify(node), before, 'reading an executor cannot dirty or rewrite node.config');
  response.next(null);
  assert.equal(inspector.skillDefinition().executor, null, 'unavailable responses finish loading and show the shared unavailable state');
  request.unsubscribe();
});

test('Skill lookups reject stale node, Skill, System and workspace responses', () => {
  for (const transition of ['node', 'skill', 'system', 'workspace']) {
    const inspector = prototypeInspector() as any;
    const node = retrievalNode();
    const response = new Subject<Skill | null>();
    let epoch = 1;
    inspector.node = signal(node);
    inspector.systemId = signal('system-1');
    inspector.skillDefinition = signal(null);
    inspector.workspace = {
      captureRequestScope: () => ({ workspaceSlug: 'showcase', workspaceId: 'ws-1', epoch }),
      isRequestScopeCurrent: (scope: { epoch: number }) => scope.epoch === epoch,
    };
    inspector.canonical = { getSkill: () => response };
    const request = inspector.loadSkillExecution(node.id, 'semantic_search_v1', 'system-1');
    if (transition === 'node') inspector.node.set({ ...node, id: 'different-node' });
    if (transition === 'skill') inspector.node.set(retrievalNode({ skill_slug: 'another-skill' }));
    if (transition === 'system') inspector.systemId.set('system-2');
    if (transition === 'workspace') epoch = 2;
    response.next({ id: 'skill-1', slug: 'semantic_search_v1', name: 'Skill', executor: { kind: 'prompt_template', params: { template: 'Stale' } } });
    assert.equal(inspector.skillDefinition(), null, `${transition} change fences the old response`);
    request.unsubscribe();
  }
});
