import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { defaultGroundedQaCapability } from './system-builder-progressive';

const builderSource = readFileSync(
  join(process.cwd(), 'src/app/features/systems/system-builder.component.ts'),
  'utf8',
);

test('simple mode selects only the verified Grounded Q&A capability', () => {
  const unrelated = { id: 'audit', slug: 'answer_quality_audit', skill_ids: ['audit'] };
  const ready = { id: 'qa', slug: 'intelligent_qa', skill_ids: ['answer'] };
  const selected = defaultGroundedQaCapability(
    [unrelated, ready],
    [
      { id: 'audit', runtime_status: 'bound' },
      { id: 'answer', runtime_status: 'bound' },
    ],
  );

  assert.equal(selected?.id, 'qa');
});

test('does not default Grounded Q&A when one of its runtimes is unavailable', () => {
  const selected = defaultGroundedQaCapability(
    [{ id: 'qa', slug: 'intelligent_qa', skill_ids: ['missing'] }],
    [{ id: 'missing', runtime_status: 'unbound' }],
  );

  assert.equal(selected, undefined);
});

test('does not silently select a different runnable capability', () => {
  const selected = defaultGroundedQaCapability(
    [{ id: 'audit', slug: 'answer_quality_audit', skill_ids: ['audit'] }],
    [{ id: 'audit', runtime_status: 'bound' }],
  );

  assert.equal(selected, undefined);
});

test('simple Build reveals only outcome and knowledge until Advanced is requested', () => {
  assert.match(builderSource, /advancedOpen = signal\(false\)/);
  assert.match(builderSource, /section\.key === 'objective' \|\| section\.key === 'context'/);
  assert.match(builderSource, /defaultGroundedQaCapability\(caps, skills\)/);
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

test('switching to Flow Builder persists a draft instead of advertising a live System', () => {
  assert.match(builderSource, /switchToFlow\(\)[\s\S]*?systemBodyFromDraft\(\{[\s\S]*?status:\s*'draft'/);
});
