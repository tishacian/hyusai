#!/usr/bin/env node

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const CORE_PERFORMANCE_BUDGETS = Object.freeze({
  initialBytes: 1_000_000,
  routeBytes: Object.freeze({
    'src/app/features/chat/chat-workspace.component.ts': 15_000,
    'src/app/features/resources/resources-page.component.ts': 100_000,
    'src/app/features/knowledge/knowledge-base.component.ts': 80_000,
    'src/app/features/systems/system-builder.component.ts': 100_000,
    'src/app/features/runs/runs-list.component.ts': 40_000,
  }),
});

function staticClosure(outputs, roots) {
  const visited = new Set();
  const pending = [...roots];
  while (pending.length > 0) {
    const outputName = pending.pop();
    if (!outputName || visited.has(outputName)) continue;
    visited.add(outputName);
    for (const dependency of outputs[outputName]?.imports ?? []) {
      if (dependency.kind !== 'dynamic-import') pending.push(dependency.path);
    }
  }
  return visited;
}

export function analyzeCorePerformance(stats, budgets = CORE_PERFORMANCE_BUDGETS) {
  if (!stats || typeof stats !== 'object' || !stats.outputs || !stats.inputs) {
    throw new Error('Angular stats must contain esbuild inputs and outputs.');
  }

  const entries = Object.entries(stats.outputs);
  const mainRoots = entries
    .filter(([, output]) => output.entryPoint === 'src/main.ts')
    .map(([name]) => name);
  const styleRoots = entries
    .filter(([, output]) => output.entryPoint === 'angular:styles/global:styles')
    .map(([name]) => name);
  if (mainRoots.length !== 1) throw new Error(`Expected one src/main.ts output, found ${mainRoots.length}.`);

  const initialOutputs = staticClosure(stats.outputs, [...mainRoots, ...styleRoots]);
  const initialBytes = [...initialOutputs]
    .reduce((total, name) => total + (stats.outputs[name]?.bytes ?? 0), 0);
  const initialInputs = new Set(
    [...initialOutputs].flatMap((name) => Object.keys(stats.outputs[name]?.inputs ?? {})),
  );

  const routes = Object.entries(budgets.routeBytes).map(([entryPoint, maximumBytes]) => {
    const matches = entries.filter(([, output]) => output.entryPoint === entryPoint);
    return {
      entryPoint,
      maximumBytes,
      output: matches[0]?.[0],
      bytes: matches[0]?.[1]?.bytes,
      matches: matches.length,
    };
  });

  const violations = [];
  if (initialBytes > budgets.initialBytes) {
    violations.push(`initial bundle is ${initialBytes} bytes; budget is ${budgets.initialBytes}`);
  }
  if ([...initialInputs].some((name) => name.includes('node_modules/chart.js/'))) {
    violations.push('Chart.js is reachable from the initial bundle');
  }
  if (initialInputs.has('src/app/core/i18n.dict.ts')) {
    violations.push('the complete translation catalogue is reachable from the initial bundle');
  }
  for (const route of routes) {
    if (route.matches !== 1 || route.bytes === undefined) {
      violations.push(`expected one lazy output for ${route.entryPoint}, found ${route.matches}`);
    } else if (route.bytes > route.maximumBytes) {
      violations.push(`${route.entryPoint} is ${route.bytes} bytes; budget is ${route.maximumBytes}`);
    }
    if (route.output && initialOutputs.has(route.output)) {
      violations.push(`${route.entryPoint} is no longer lazy`);
    }
  }

  return { initialBytes, initialOutputs, routes, violations };
}

function run() {
  const statsPath = resolve(process.argv[2] ?? 'dist/agentium/stats.json');
  let stats;
  try {
    stats = JSON.parse(readFileSync(statsPath, 'utf8'));
  } catch (error) {
    console.error(`performance gate: cannot read ${statsPath}: ${error.message}`);
    process.exitCode = 1;
    return;
  }

  const result = analyzeCorePerformance(stats);
  if (result.violations.length > 0) {
    console.error(`performance gate failed:\n- ${result.violations.join('\n- ')}`);
    process.exitCode = 1;
    return;
  }

  const routeSummary = result.routes
    .map((route) => `${route.entryPoint.split('/').at(-1)}=${route.bytes}B`)
    .join(', ');
  console.log(`performance OK — initial=${result.initialBytes}B; ${routeSummary}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) run();
