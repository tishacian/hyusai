import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  RECIPE_DEFAULT_CODE,
  RECIPE_MAX_REQUIREMENT_LINES,
  RECIPE_SKILL_SLUG,
  RECIPE_TIMEOUT_DEFAULT_S,
  RECIPE_TIMEOUT_MAX_S,
  clampRecipeTimeout,
  formatBytes,
  isActiveRecipeExecution,
  isPythonRecipeNode,
  previewRequirements,
  readRecipeParams,
  recipeCodeLineCount,
  recipeCodeSummary,
  recipeDefaultParams,
  recipeEnvStatusKey,
  recipeExecutionStatusKey,
  recipeSpecKey,
  recipeTimeline,
  recipeWorkshopTestInput,
  shortFingerprint,
} from './flow-recipe.vm';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';

function recipeNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'task.recipe',
    type: 'skill',
    kind: 'task',
    label: 'Recipe',
    config: { skill_slug: RECIPE_SKILL_SLUG, ...config },
  };
}

test('isPythonRecipeNode matches only task nodes bound to the recipe skill', () => {
  assert.equal(isPythonRecipeNode(recipeNode()), true);
  assert.equal(isPythonRecipeNode(null), false);
  assert.equal(isPythonRecipeNode(undefined), false);
  assert.equal(
    isPythonRecipeNode({ id: 'a', type: 'skill', kind: 'task', config: { skill_slug: 'other' } }),
    false,
  );
  assert.equal(
    isPythonRecipeNode({
      id: 'a',
      type: 'source',
      kind: 'source',
      config: { skill_slug: RECIPE_SKILL_SLUG },
    }),
    false,
    'a non-task node never becomes a recipe, whatever its config claims',
  );
  // kind omitted defaults to task — the palette drops recipe nodes that way.
  assert.equal(
    isPythonRecipeNode({ id: 'a', type: 'skill', config: { skill_slug: RECIPE_SKILL_SLUG } }),
    true,
  );
});

test('readRecipeParams fills defaults and normalises whatever is unset or malformed', () => {
  const defaults = readRecipeParams(recipeNode());
  assert.equal(defaults.code, RECIPE_DEFAULT_CODE);
  assert.equal(defaults.requirements_text, '');
  assert.equal(defaults.index_url, '');
  assert.deepEqual(defaults.extra_index_urls, []);
  assert.equal(defaults.timeout_s, RECIPE_TIMEOUT_DEFAULT_S);
  assert.deepEqual(defaults, recipeDefaultParams());

  const custom = readRecipeParams(
    recipeNode({
      params: {
        code: 'def main(inputs): return {}',
        requirements_text: 'pandas\n',
        index_url: '  https://pypi.example/simple  ',
        extra_index_urls: [' https://mirror.example/simple ', '', 42],
        timeout_s: '45',
      },
    }),
  );
  assert.equal(custom.code, 'def main(inputs): return {}');
  assert.equal(custom.requirements_text, 'pandas\n');
  assert.equal(custom.index_url, 'https://pypi.example/simple');
  assert.deepEqual(custom.extra_index_urls, ['https://mirror.example/simple', '42']);
  assert.equal(custom.timeout_s, 45);
});

test('recipeWorkshopTestInput seeds the Test tab from node data', () => {
  assert.equal(recipeWorkshopTestInput(recipeNode()), '{}');
  assert.equal(recipeWorkshopTestInput(null), '{}');
  assert.equal(
    recipeWorkshopTestInput({
      ...recipeNode(),
      data: { workshop_test_input: '  ' },
    }),
    '{}',
  );
  assert.equal(
    recipeWorkshopTestInput({
      ...recipeNode(),
      data: { workshop_test_input: '{"supplier":"ACME"}' },
    }),
    '{"supplier":"ACME"}',
  );
});

test('clampRecipeTimeout mirrors the server window', () => {
  assert.equal(clampRecipeTimeout(undefined), RECIPE_TIMEOUT_DEFAULT_S);
  assert.equal(clampRecipeTimeout('not a number'), RECIPE_TIMEOUT_DEFAULT_S);
  assert.equal(clampRecipeTimeout(-5), RECIPE_TIMEOUT_DEFAULT_S);
  assert.equal(clampRecipeTimeout(0.4), 1, 'sub-second positives round up to the floor');
  assert.equal(clampRecipeTimeout(45.6), 46);
  assert.equal(clampRecipeTimeout(10_000), RECIPE_TIMEOUT_MAX_S);
  assert.equal(clampRecipeTimeout('90'), 90);
});

test('previewRequirements mirrors the server normalisation (comments, dedupe, sort, options)', () => {
  const preview = previewRequirements(
    [
      '# a comment line',
      '',
      'Requests>=2.31  # trailing comment',
      'pandas==2.2.3',
      'pandas==2.2.3',
      '   numpy   >=   1.26 ',
      '-r other.txt',
      '--index-url https://evil.example/simple',
    ].join('\n'),
  );
  assert.deepEqual(preview.lines, ['numpy >= 1.26', 'pandas==2.2.3', 'Requests>=2.31']);
  assert.deepEqual(preview.invalid, ['-r other.txt', '--index-url https://evil.example/simple']);
  assert.equal(preview.tooMany, false);

  const many = previewRequirements(
    Array.from({ length: RECIPE_MAX_REQUIREMENT_LINES + 1 }, (_, i) => `pkg${i}`).join('\n'),
  );
  assert.equal(many.tooMany, true);
});

test('recipeSpecKey identifies the spec by its normalised fingerprint fields only', () => {
  const base = recipeDefaultParams();
  const a = recipeSpecKey({ ...base, requirements_text: 'pandas\n# note\nnumpy' });
  const b = recipeSpecKey({ ...base, requirements_text: 'numpy\npandas' });
  assert.equal(a, b, 'comment/order differences resolve to the same env identity');
  // The script does NOT change the env identity…
  const c = recipeSpecKey({ ...base, requirements_text: 'pandas\nnumpy', code: 'x = 1' });
  assert.equal(a, c);
  // …the registry does.
  const d = recipeSpecKey({
    ...base,
    requirements_text: 'pandas\nnumpy',
    index_url: 'https://mirror.example/simple',
  });
  assert.notEqual(a, d);
});

test('every env and execution status resolves to FR and EN copy', () => {
  for (const status of ['pending', 'building', 'ready', 'failed', 'evicted']) {
    const key = recipeEnvStatusKey(status) as keyof typeof FLOW_FR;
    assert.ok(FLOW_FR[key]?.trim(), `${key} has FR copy`);
    assert.ok(FLOW_EN[key]?.trim(), `${key} has EN copy`);
  }
  for (const status of [
    'queued',
    'env_building',
    'running',
    'succeeded',
    'failed',
    'cancelled',
    'timed_out',
  ]) {
    const key = recipeExecutionStatusKey(status) as keyof typeof FLOW_FR;
    assert.ok(FLOW_FR[key]?.trim(), `${key} has FR copy`);
    assert.ok(FLOW_EN[key]?.trim(), `${key} has EN copy`);
  }
});

test('the execution timeline projects active, terminal and unknown statuses', () => {
  assert.deepEqual(
    recipeTimeline('queued').map((step) => step.state),
    ['current', 'upcoming', 'upcoming'],
  );
  assert.deepEqual(
    recipeTimeline('env_building').map((step) => step.state),
    ['done', 'current', 'upcoming'],
  );
  assert.deepEqual(
    recipeTimeline('running').map((step) => step.state),
    ['done', 'done', 'current'],
  );
  // Terminal statuses close every phase — including env_building when the
  // ready env let the execution skip it entirely.
  for (const status of ['succeeded', 'failed', 'cancelled', 'timed_out']) {
    assert.deepEqual(
      recipeTimeline(status).map((step) => step.state),
      ['done', 'done', 'done'],
      status,
    );
  }
  assert.deepEqual(
    recipeTimeline('').map((step) => step.state),
    ['upcoming', 'upcoming', 'upcoming'],
    'no execution yet — nothing started',
  );
});

test('active statuses are exactly the cancellable ones', () => {
  for (const status of ['queued', 'env_building', 'running']) {
    assert.equal(isActiveRecipeExecution(status), true, status);
  }
  for (const status of ['succeeded', 'failed', 'cancelled', 'timed_out', '']) {
    assert.equal(isActiveRecipeExecution(status), false, status);
  }
});

test('display helpers stay defensive on absent values', () => {
  assert.equal(shortFingerprint('abcdef0123456789'), 'abcdef012345');
  assert.equal(shortFingerprint(null), '');
  assert.equal(formatBytes(512), '512 o');
  assert.equal(formatBytes(2048), '2 Kio');
  assert.equal(formatBytes(150 * 1024 * 1024), '150 Mio');
  assert.equal(formatBytes(null), '0 o');
  assert.equal(recipeCodeSummary(RECIPE_DEFAULT_CODE), 'def main(inputs: dict) -> dict:');
  assert.equal(recipeCodeSummary('# only a comment'), '# only a comment');
  assert.equal(recipeCodeSummary(''), '');
  assert.equal(recipeCodeLineCount(''), 0);
  assert.equal(recipeCodeLineCount('x = 1\n'), 1);
  assert.equal(recipeCodeLineCount(RECIPE_DEFAULT_CODE), 7);
});
