/**
 * Dependency-light unit-test runner for the Flow Builder's engine-agnostic
 * logic (adapter + CanonicalFlow serializer).
 *
 * The repo has no Angular unit-test harness (no Karma/Jasmine/Vitest) and the
 * Playwright e2e suite targets a live VM + Keycloak, so it can't run locally.
 * Rather than add a heavy runner, this bundles each co-located `*.spec.ts`
 * with the already-installed esbuild (which erases `import type`, applies the
 * tsconfig `@app/*` paths, and aliases `@angular/core` to a metadata-only
 * stub) and runs the bundles with Node's built-in test runner.
 *
 * Usage: `npm run test:unit`
 */
import { build } from 'esbuild';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const stub = join(here, 'ng-core.stub.mjs');

// Pure specs: engine-agnostic logic. `@angular/core` is aliased to a
// metadata-only stub (the serializer uses it only for `@Injectable`).
const pureSpecs = [
  'src/app/features/orchestration/flow/flow-foblex.adapter.spec.ts',
  'src/app/features/orchestration/flow/flow-manifest-strip.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-variable.service.spec.ts',
  'src/app/features/orchestration/flow/flow-validation-strip.vm.spec.ts',
  'src/app/core/flow-serializer.service.spec.ts',
];

// Store specs: exercised through a REAL Angular Injector (ngrx signalStore +
// JIT). No `@angular/core` alias; the spec imports `@angular/compiler` itself.
const storeSpecs = [
  'src/app/features/orchestration/flow/flow.store.spec.ts',
  'src/app/features/orchestration/flow/flow-run.service.spec.ts',
  'src/app/features/orchestration/flow/flow-validation-strip.spec.ts',
];

const outDir = mkdtempSync(join(tmpdir(), 'flow-unit-'));
const common = {
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'es2022',
  sourcemap: 'inline',
  absWorkingDir: root,
  nodePaths: [join(root, 'node_modules')],
  tsconfig: join(root, 'tsconfig.json'),
  logLevel: 'warning',
};

try {
  await build({
    ...common,
    entryPoints: pureSpecs.map((s) => join(root, s)),
    outdir: outDir,
    outbase: root,
    alias: { '@angular/core': stub },
  });
  await build({
    ...common,
    entryPoints: storeSpecs.map((s) => join(root, s)),
    outdir: outDir,
    outbase: root,
  });

  const bundles = [...pureSpecs, ...storeSpecs].map((s) =>
    join(outDir, s.replace(/\.ts$/, '.js')),
  );
  const result = spawnSync(process.execPath, ['--test', ...bundles], {
    stdio: 'inherit',
  });
  process.exit(result.status ?? 1);
} finally {
  rmSync(outDir, { recursive: true, force: true });
}
