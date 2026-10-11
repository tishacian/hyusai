import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { DatasetLabelReviewComponent } from './dataset-label-review.component';
import type { LabelReviewPage } from './label-review.vm';

const page: LabelReviewPage = { decision_id: 'decision', dataset_id: 'labels', dataset_name: 'Tickets', source_version: 1, sha256: 'hash', label_column: 'topic', labels: ['yes', 'no'], text_columns: ['message'], total: 51, offset: 0, rows: [{ row_id: 0, values: { message: 'Hi' }, label: 'yes' }] };
function harness() {
  let currentScope = true;
  const responses: Subject<LabelReviewPage>[] = [];
  const component = Object.assign(Object.create(DatasetLabelReviewComponent.prototype), {
    runId: () => 'run', decisionId: () => 'decision', disabled: () => false, identity: () => 'workspace/run/decision',
    page: signal<LabelReviewPage | null>(null), corrections: signal({}), acknowledged: signal(false), loading: signal(false), error: signal(false), generation: 0,
    destroy: { onDestroy: () => () => {} },
    workspace: { captureRequestScope: () => 'workspace', isRequestScopeCurrent: () => currentScope },
    api: { getLabelReview: () => { const response = new Subject<LabelReviewPage>(); responses.push(response); return response; } },
  }) as DatasetLabelReviewComponent;
  return { component, responses, switchWorkspace: () => { currentScope = false; } };
}

test('review keeps corrections across pages and invalidates acknowledgment on edits', () => {
  const { component, responses } = harness();
  component.loadPage(0); responses[0].next(page);
  component.acknowledged.set(true); component.change(0, 'no');
  assert.equal(component.acknowledged(), false);
  component.loadPage(50); responses[1].next({ ...page, offset: 50, rows: [{ row_id: 50, values: { message: 'Last' }, label: 'no' }] });
  component.change(50, 'yes');
  assert.deepEqual(component.corrections(), { 0: 'no', 50: 'yes' });
});

test('a changed fingerprint and a 409 invalidate confirmation', () => {
  const { component, responses } = harness();
  component.loadPage(0); responses[0].next(page); component.acknowledged.set(true);
  component.loadPage(50); responses[1].next({ ...page, sha256: 'new' });
  assert.equal(component.error(), true); assert.equal(component.acknowledged(), false);
  component.reload(); responses[2].error({ status: 409 });
  assert.equal(component.error(), true); assert.equal(component.page(), null);
});

test('a response from the old workspace cannot expose rows', () => {
  const { component, responses, switchWorkspace } = harness();
  component.loadPage(0); switchWorkspace(); responses[0].next(page);
  assert.equal(component.page(), null);
});
