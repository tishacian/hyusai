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
