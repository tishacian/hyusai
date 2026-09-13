import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const source = readFileSync(
  join(process.cwd(), 'src/app/features/knowledge/knowledge-base.component.ts'),
  'utf8',
);

test('Knowledge defaults to upload and Ask while advanced tools stay opt-in', () => {
  assert.match(source, /advancedOpen = signal\(false\)/);
  assert.match(source, /uploadState = signal<'idle' \| 'uploading' \| 'ready' \| 'partial' \| 'error'>/);
  assert.match(source, /knowledge\.ask\.cta/);
  assert.match(source, /@if \(advancedOpen\(\)\) \{[\s\S]*knowledge-capture/);
  assert.match(source, /uploadState\(\) === 'ready' \|\| uploadState\(\) === 'partial'/);
});

test('Knowledge reports activation from the batch result, not from the drop', () => {
  // Only an indexed document counts, and the recovery is claimed only when a
  // batch that had previously failed finally succeeded.
  assert.match(
    source,
    /if \(res\.successful > 0\) \{[\s\S]{0,600}?recordOnce\('knowledge_added'\)/,
  );
  // The success callback cannot read `uploadState` to learn that the previous
  // attempt failed: the current attempt already set it to `uploading`.
  assert.equal(source.includes("this.uploadState() === 'error'"), false);
  assert.match(source, /private uploadRecoveryPending = false;/);
  assert.match(
    source,
    /if \(this\.uploadRecoveryPending && res\.failed === 0\) \{/,
  );
  assert.match(source, /recoveryKind: 'knowledge_upload',/);
  assert.equal(/uploadFiles\(files: FileList\): void \{[\s\S]{0,400}?recordOnce/.test(source), false);
});
