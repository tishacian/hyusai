/**
 * A catalogued surface with no route is a menu entry that leads nowhere.
 *
 * `AGENTIUM_SURFACE_ROUTES` is what the side rail, the mini rail, the command
 * palette and the breadcrumb all navigate by, and none of them checks that the
 * router can serve the destination: an unmatched path falls through to the
 * shell's wildcard, so the entry looks fine, clicks, and quietly lands on the
 * default page. That is exactly how the Models entry shipped in the Build menu
 * with no `path: 'models'` behind it.
 *
 * The routes are read from source rather than imported because `app.routes.ts`
 * pulls in every guard and lazy chunk in the application; the declaration is a
 * literal, and a literal is enough to prove the segment exists.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import { AGENTIUM_SURFACE_ROUTES } from './navigation.catalog';

const APP_ROUTES = join(process.cwd(), 'src', 'app', 'app.routes.ts');

/** Every `path: '…'` literal declared in the application's route tree. */
function declaredPaths(): string[] {
  const source = readFileSync(APP_ROUTES, 'utf8');
  const paths = [...source.matchAll(/path: '([^']*)'/g)].map((match) => match[1]);
  assert.ok(paths.length > 20, 'the route scanner stopped finding path declarations');
  return paths;
}

/** The first segment of a route, ignoring any query string the catalog carries. */
function rootSegment(route: string): string {
  return route.split('?')[0].split('/').filter(Boolean)[0] ?? '';
}

test('every catalogued surface route is reachable through a declared route', () => {
  // A declaration may itself be multi-segment (`deposit/:accessId`), so the
  // comparison is on first segments rather than on whole paths.
  const roots = new Set(declaredPaths().map(rootSegment).filter(Boolean));
  const unreachable = AGENTIUM_SURFACE_ROUTES.filter(
    (surface) => !roots.has(rootSegment(surface.route)),
  ).map((surface) => `${surface.id} → ${surface.route}`);

  assert.deepEqual(
    unreachable,
    [],
    `these surfaces are navigable from the chrome but have no route:\n  ${unreachable.join('\n  ')}`,
  );
});

test('every surface route is absolute, so it can be navigated from anywhere', () => {
  const relative = AGENTIUM_SURFACE_ROUTES.filter(
    (surface) => !surface.route.startsWith('/'),
  ).map((surface) => surface.id);
  assert.deepEqual(relative, []);
});
