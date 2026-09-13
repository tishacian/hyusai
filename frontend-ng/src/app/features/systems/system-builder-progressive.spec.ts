import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { firstRunnableCapability } from './system-builder-progressive';

const builderSource = readFileSync(
  join(process.cwd(), 'src/app/features/systems/system-builder.component.ts'),
  'utf8',
);

test('selects the first capability whose skills are bound', () => {
  const blocked = { id: 'blocked', skill_ids: ['catalog-only'] };
  const ready = { id: 'ready', skill_ids: ['answer'] };
  const selected = firstRunnableCapability(
    [blocked, ready],
    [
      { id: 'catalog-only', runtime_status: 'catalog_only' },
      { id: 'answer', runtime_status: 'bound' },
    ],
  );

  assert.equal(selected?.id, 'ready');
});

test('does not present an unbound default as runnable', () => {
  const selected = firstRunnableCapability(
    [{ id: 'missing-wrapper', skill_ids: ['missing'] }],
    [{ id: 'missing', runtime_status: 'unbound' }],
  );

  assert.equal(selected, undefined);
});

test('simple Build reveals only outcome and knowledge until Advanced is requested', () => {
  assert.match(builderSource, /advancedOpen = signal\(false\)/);
  assert.match(builderSource, /section\.key === 'objective' \|\| section\.key === 'context'/);
  assert.match(builderSource, /firstRunnableCapability\(caps, skills\)/);
  assert.match(builderSource, /@if \(advancedOpen\(\)\) \{[\s\S]*Switch to Flow/);
});

test('publication is reported from the live System the API returned', () => {
  assert.match(
    builderSource,
    /if \(sys\) \{[\s\S]{0,400}?recordOccurrence\('system_published', \{[\s\S]{0,300}?dedupeKey: sys\.id,/,
  );
  // Reaching Launch, or falling back to a local draft, publishes nothing.
  assert.equal(
    /createDraft\(\{[\s\S]{0,600}?recordOccurrence\('system_published'/.test(builderSource),
    false,
  );
  assert.equal(builderSource.includes('product.activation'), false);
});
