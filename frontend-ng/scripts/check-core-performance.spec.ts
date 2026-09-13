import assert from 'node:assert/strict';
import test from 'node:test';

import { analyzeCorePerformance } from './check-core-performance.mjs';

const routeEntries = {
  'ask.js': 'src/app/features/chat/chat-workspace.component.ts',
  'settings.js': 'src/app/features/resources/resources-page.component.ts',
  'knowledge.js': 'src/app/features/knowledge/knowledge-base.component.ts',
  'build.js': 'src/app/features/systems/system-builder.component.ts',
  'runs.js': 'src/app/features/runs/runs-list.component.ts',
};

function statsFixture() {
  return {
    inputs: { 'src/main.ts': {}, 'src/app/core/i18n.dict.ts': {} },
    outputs: {
      'main.js': {
        bytes: 100,
        entryPoint: 'src/main.ts',
        inputs: { 'src/main.ts': {} },
        imports: [
          { path: 'shared.js', kind: 'import-statement' },
          { path: 'ask.js', kind: 'dynamic-import' },
        ],
      },
      'shared.js': { bytes: 200, inputs: {}, imports: [] },
      'styles.css': {
        bytes: 50,
        entryPoint: 'angular:styles/global:styles',
        inputs: {},
        imports: [],
      },
      ...Object.fromEntries(Object.entries(routeEntries).map(([name, entryPoint]) => [
        name,
        { bytes: 10, entryPoint, inputs: {}, imports: [] },
      ])),
    },
  };
}

test('counts the static startup graph while excluding dynamic route imports', () => {
  const result = analyzeCorePerformance(statsFixture());
  assert.equal(result.initialBytes, 350);
  assert.deepEqual(result.violations, []);
});

test('fails closed when heavy libraries or core routes become eager', () => {
  const stats = statsFixture();
  stats.outputs['shared.js'].inputs = {
    'node_modules/chart.js/dist/chart.js': {},
    'src/app/core/i18n.dict.ts': {},
  };
  stats.outputs['main.js'].imports.push({ path: 'knowledge.js', kind: 'import-statement' });
  const result = analyzeCorePerformance(stats);
  assert.ok(result.violations.some((message) => message.includes('Chart.js')));
  assert.ok(result.violations.some((message) => message.includes('translation catalogue')));
  assert.ok(result.violations.some((message) => message.includes('knowledge-base.component.ts is no longer lazy')));
});

test('rejects malformed stats instead of silently passing', () => {
  assert.throws(() => analyzeCorePerformance({ outputs: {} }), /inputs and outputs/);
});
