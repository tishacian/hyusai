/**
 * Every Router path has a catalog surface, a catalog leaf, or a named
 * exemption. The previous check only proved the first path segment existed,
 * which is how `/systems/:id/flow` shipped without a catalog entry.
 */
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import {
  AGENTIUM_SURFACE_LEAVES,
  AGENTIUM_SURFACE_ROUTES,
} from './navigation.catalog';

const APP_DIR = join(process.cwd(), 'src', 'app');
const APP_ROUTES = join(APP_DIR, 'app.routes.ts');

/** Shells and internals that are not Cockpit chrome destinations (plan A.2). */
const NAMED_EXEMPTIONS = [
  '',
  '**',
  'auth',
  'nawa',
  'account',
  'workspace',
  'settings',
  'settings/legacy',
  'apps',
  'hypervisor/mission-room',
  // Retired alias kept reachable as a redirect; the lexicon retires the word.
  'work/pr-to-po/desk',
];

const REQUIRED_LEAVES = [
  '/systems/new',
  '/systems/:systemId/flow',
  '/systems/:systemId/run',
  '/capabilities/curation',
  '/connectors/rpa-bridge',
  '/create/apps/new',
  '/create/preview',
  '/workspace-app-unavailable',
  '/workspace-app-repair',
];

function pathOnly(route: string): string {
  return route.split('?')[0].split('#')[0] || '/';
}

function normalize(route: string): string {
  return pathOnly(route).replace(/:[A-Za-z][A-Za-z0-9]*/g, ':param');
}

function declaredPaths(file: string): string[] {
  const source = readFileSync(file, 'utf8');
  return [...source.matchAll(/path:\s*'([^']*)'/g)].map((match) => match[1]);
}

function walk(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      walk(full, acc);
      continue;
    }
    if (name.endsWith('.routes.ts')) acc.push(full);
  }
  return acc;
}

/** Absolute patterns declared by the Router (app + feature modules). */
function routerPatterns(): string[] {
  const appPaths = declaredPaths(APP_ROUTES);
  const patterns = new Set<string>();
  for (const path of appPaths) {
    patterns.add(path ? `/${path}` : '/');
  }

  const featureFiles = walk(join(APP_DIR, 'features'));
  const prefixByFolder: Record<string, string> = {
    auth: '/auth',
    nawa: '/nawa',
    work: '/work',
    'mission-room': '/hypervisor/mission-room',
    experience: '/create',
    capabilities: '/capabilities',
    skills: '/skills',
    systems: '/systems',
    knowledge: '/knowledge',
    data: '/data',
    models: '/models',
    governance: '/governance',
    observability: '/observability',
    runs: '/runs',
    intelligence: '/intelligence',
    orchestration: '/orchestration',
    client360: '/client360',
    workspace: '/workspace',
    account: '/account',
    presets: '/presets',
    settings: '/settings/legacy',
    tasks: '/tasks',
    resources: '/resources',
    connectors: '/connectors',
    apps: '/apps',
  };

  for (const file of featureFiles) {
    const rel = file.slice(join(APP_DIR, 'features').length + 1);
    const folder = rel.split('/')[0];
    if (folder === 'experience' && rel.includes('/work/')) {
      for (const path of declaredPaths(file)) {
        patterns.add(path ? `/work/${path}` : '/work');
      }
      continue;
    }
    const prefix = prefixByFolder[folder];
    if (!prefix) continue;
    for (const path of declaredPaths(file)) {
      patterns.add(path ? `${prefix}/${path}` : prefix);
    }
  }

  return [...patterns];
}

function catalogPatterns(): string[] {
  return [
    ...AGENTIUM_SURFACE_ROUTES.flatMap((surface) => [
      surface.route,
      ...(surface.routeAliases ?? []),
    ]),
    ...AGENTIUM_SURFACE_LEAVES.map((leaf) => leaf.route),
  ].map(pathOnly);
}

function isNamedExemption(pattern: string): boolean {
  const normalized = pathOnly(pattern).replace(/^\//, '');
  return NAMED_EXEMPTIONS.some((exemption) => {
    if (exemption === '') return normalized === '';
    if (exemption === '**') return normalized === '**';
    return normalized === exemption || normalized.startsWith(`${exemption}/`);
  });
}

function isCatalogued(pattern: string): boolean {
  const target = normalize(pattern);
  if (catalogPatterns().some((candidate) => normalize(candidate) === target)) {
    return true;
  }
  const segments = pathOnly(pattern).split('/').filter(Boolean);
  if (segments.length >= 2 && segments[segments.length - 1].startsWith(':')) {
    const parent = `/${segments.slice(0, -1).join('/')}`;
    return catalogPatterns().some((candidate) => normalize(candidate) === normalize(parent));
  }
  return false;
}

test('every catalogued surface route is reachable through a declared route', () => {
  const roots = new Set(
    declaredPaths(APP_ROUTES).map((path) => path.split('/')[0]).filter(Boolean),
  );
  const unreachable = AGENTIUM_SURFACE_ROUTES.filter((surface) => {
    const root = pathOnly(surface.route).split('/').filter(Boolean)[0] ?? '';
    return root && !roots.has(root);
  }).map((surface) => `${surface.id} → ${surface.route}`);
  assert.deepEqual(unreachable, []);
});

test('the authenticated root redirects to the canonical Quick Ask home', () => {
  const source = readFileSync(APP_ROUTES, 'utf8');
  assert.match(source, /path:\s*'',\s*pathMatch:\s*'full',\s*redirectTo:\s*\(\)\s*=>\s*new DefaultUrlSerializer\(\)\.parse\(ASK_HOME_ROUTE\)/s);
});

test('every surface and leaf route is absolute', () => {
  const relative = [
    ...AGENTIUM_SURFACE_ROUTES.map((surface) => surface.route),
    ...AGENTIUM_SURFACE_LEAVES.map((leaf) => leaf.route),
  ].filter((route) => !pathOnly(route).startsWith('/'));
  assert.deepEqual(relative, []);
});

test('planned orphan leaves have a catalog entry', () => {
  const routes = new Set(AGENTIUM_SURFACE_LEAVES.map((leaf) => normalize(leaf.route)));
  const missing = REQUIRED_LEAVES.filter((route) => !routes.has(normalize(route)));
  assert.deepEqual(missing, []);
  assert.ok(AGENTIUM_SURFACE_ROUTES.some((surface) => normalize(surface.route) === '/work'));
});

test('every Router path has a catalog entry or a named exemption', () => {
  const uncovered = routerPatterns().filter(
    (pattern) => !isNamedExemption(pattern) && !isCatalogued(pattern),
  );
  assert.deepEqual(
    uncovered,
    [],
    `these Router paths have no catalog entry or named exemption:\n  ${uncovered.join('\n  ')}`,
  );
});
