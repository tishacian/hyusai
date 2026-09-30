import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import type {
  SystemFlowDiff,
  SystemVersionFull,
  SystemVersionSummary,
} from '@app/core/canonical-api.service';
import {
  exactFlowVersionPreviewError,
  flowVersionRestoreBlockReason,
  formatServerFlowSemanticDiff as formatDiff,
  isFlowVersionCurrent,
  isFlowVersionRestoreBlocked,
} from './flow-versions.component';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
const formatServerFlowSemanticDiff = (diff: SystemFlowDiff) => formatDiff(diff,
  (key, params) => (FLOW_EN[key as keyof typeof FLOW_EN] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? '')));

const SOURCE = readFileSync(
  join(process.cwd(), 'src/app/features/orchestration/flow/flow-versions.component.ts'),
  'utf8',
);

function summary(): SystemVersionSummary {
  return {
    id: 'version-published',
    system_id: 'system-a',
    version_number: 2,
    flow_sha256: 'version-sha',
    created_at: '2026-08-06T10:00:00Z',
    created_by: 'operator@example.invalid',
    node_count: 2,
    edge_count: 1,
  };
}

function full(): SystemVersionFull {
  return {
    id: 'version-published',
    system_id: 'system-a',
    workspace_id: 'workspace-a',
    version_number: 2,
    flow_sha256: 'version-sha',
    flow_definition: { nodes: [], edges: [] },
    execution_contract: { contract_sha256: 'contract-v2' },
    created_at: '2026-08-06T10:00:00Z',
    created_by: 'operator@example.invalid',
  };
}

function serverDiff(): SystemFlowDiff {
  return {
    base: { identity: 'version:2', flow_sha256: 'version-sha' },
    target: { identity: 'draft:8', flow_sha256: 'draft-sha' },
    summary: { breaking: 3, behavioral: 0, presentation: 0, total: 3 },
    changes: [
      {
        category: 'topology',
        impact: 'breaking',
        subject: 'flow',
        path: 'nodes/order',
        description: 'Executable node order changed.',
      },
      {
        category: 'topology',
        impact: 'breaking',
        subject: 'flow',
        path: 'edges/order',
        description: 'Executable edge order changed.',
      },
      {
        category: 'execution_contract',
        impact: 'breaking',
        subject: 'flow',
        path: 'execution_contract',
        description: 'Pinned execution contract changed.',
      },
    ],
  };
}

test('Published pointer identity is separate from current server draft identity', () => {
  const version = summary();
  const divergent = {
    publicationMode: true,
    publishedVersionId: version.id,
    draftMatchesPublished: false,
  };
  assert.equal(isFlowVersionCurrent(version, 0, divergent), true);
  assert.equal(
    isFlowVersionRestoreBlocked(version, 0, divergent),
    false,
    'the current Published version remains restorable into a divergent draft',
  );
  assert.equal(
    isFlowVersionRestoreBlocked(version, 0, { ...divergent, draftMatchesPublished: true }),
    true,
  );
  assert.equal(
    isFlowVersionCurrent({ ...version, id: 'older' }, 0, divergent),
    false,
    'publication mode never infers pointer identity from row order',
  );
  assert.equal(
    isFlowVersionRestoreBlocked(version, 0, {
      publicationMode: false,
      publishedVersionId: null,
      draftMatchesPublished: false,
    }),
    true,
    'legacy mode keeps the newest current mirror protected',
  );
});

test('exact rollback evidence validates immutable and draft identities and digests', () => {
  const valid = {
    publicationMode: true,
    systemId: 'system-a',
    summary: summary(),
    full: full(),
    semanticDiff: serverDiff(),
    draftRevision: 8,
    draftFlowSha256: 'draft-sha',
  };
  assert.equal(exactFlowVersionPreviewError(valid), null);

  const mismatches = [
    { full: { ...full(), id: 'wrong-version' } },
    { full: { ...full(), flow_sha256: 'wrong-sha' } },
    { semanticDiff: { ...serverDiff(), base: { identity: 'version:3', flow_sha256: 'version-sha' } } },
    { semanticDiff: { ...serverDiff(), target: { identity: 'draft:7', flow_sha256: 'draft-sha' } } },
    { semanticDiff: { ...serverDiff(), target: { identity: 'draft:8', flow_sha256: 'stale-draft' } } },
  ];
  for (const mismatch of mismatches) {
    assert.ok(exactFlowVersionPreviewError({ ...valid, ...mismatch }), JSON.stringify(mismatch));
  }
});

test('server diff summary exposes contract and executable order changes', () => {
  assert.equal(
    formatServerFlowSemanticDiff(serverDiff()),
    '3 breaking · ↕n order · ↕e order · ~contract',
  );
  assert.equal(
    formatServerFlowSemanticDiff({
      base: { identity: 'version:2', flow_sha256: 'same' },
      target: { identity: 'draft:8', flow_sha256: 'same' },
      summary: { breaking: 0, behavioral: 0, presentation: 0, total: 0 },
      changes: [],
    }),
    '= draft (server verified)',
  );
});

test('component gates rollback on dual exact evidence and revision-bound fences', () => {
  assert.match(SOURCE, /forkJoin\(\{ full: fullRequest, semanticDiff: semanticRequest \}\)/);
  assert.match(SOURCE, /getSystemFlowDiff\(sid, `version:\$\{v\.version_number\}`, 'draft'\)/);
  assert.match(SOURCE, /propagateErrors: true/);
  assert.match(SOURCE, /!previewReady\(tgt\)/);
  assert.match(SOURCE, /state\.fence === this\.currentEvidenceFence\(\)/);
  assert.match(SOURCE, /this\.store\.revision\(\)/);
  assert.match(SOURCE, /this\.persistence\.draftRevision\(\)/);
  assert.match(SOURCE, /this\.persistence\.savedFlowSha256\(\)/);
  assert.match(SOURCE, /this\.persistence\.publishedVersionId\(\)/);
});


test('restore guards keep their precedence and every reason is translated in FR and EN', () => {
  const version = summary();
  const gate = { publicationMode: true, publishedVersionId: version.id, draftMatchesPublished: false,
    historyError: false, restorePending: false, writeInProgress: false, localChanges: false };
  assert.equal(flowVersionRestoreBlockReason(version, 0, gate), null);
  for (const [condition, expected] of [
    ['draftMatchesPublished', 'matches_published'], ['historyError', 'history'],
    ['localChanges', 'local_changes'], ['restorePending', 'pending'], ['writeInProgress', 'write'],
  ]) {
    const reason = flowVersionRestoreBlockReason(version, 0, { ...gate, [condition]: true })!;
    assert.equal(reason, `flow.versions.blocked.${expected}`);
    assert.ok(FLOW_FR[reason as keyof typeof FLOW_FR]);
    assert.ok(FLOW_EN[reason as keyof typeof FLOW_EN]);
  }
  assert.equal(flowVersionRestoreBlockReason(version, 0, { ...gate, publicationMode: false }), 'flow.versions.blocked.current');
  const reason = exactFlowVersionPreviewError({ publicationMode: false, systemId: 'system-a',
    summary: version, full: null, semanticDiff: null, draftRevision: null, draftFlowSha256: null })!;
  assert.equal(FLOW_FR[reason as keyof typeof FLOW_FR], 'Le contenu de la version enregistrée n’a pas été renvoyé.');
  assert.match(formatDiff(serverDiff(), (key, params) => FLOW_FR[key as keyof typeof FLOW_FR].replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? ''))), /rupture.*ordre des nœuds.*contrat/);
});
