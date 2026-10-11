/**
 * ADR 0003 lot 2: the shell names no customer application or skin.
 *
 * A customer application reaches the product through core/client-applications
 * only, and the Agent Studio wears the workspace appearance instead of a
 * customer palette written into the shared styles.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import { appearanceStyles } from './brand-appearance';
import { CLIENT_APPLICATION_SURFACES } from './client-applications';
import { AGENTIUM_SURFACE_ROUTES, matchAgentiumSurface } from './navigation.catalog';

const APP_DIR = join(process.cwd(), 'src', 'app');

function source(path: string): string {
  return readFileSync(join(APP_DIR, path), 'utf8');
}

test('the catalogue lists every customer surface, in place', () => {
  for (const surface of CLIENT_APPLICATION_SURFACES) {
    assert.ok(AGENTIUM_SURFACE_ROUTES.includes(surface), `${surface.id} is in the catalogue`);
  }
});

test('a workspace home inside a customer application still resolves', () => {
  // navigation_profile.default_route of the NAWA workspace; without a matching
  // surface the home silently falls back to /work.
  assert.equal(matchAgentiumSurface('/nawa/itsd')?.id, 'nawa-itsd');
  assert.equal(matchAgentiumSurface('/nawa/itsd/password-reset')?.id, 'nawa-itsd');
});

test('the router mounts customer applications only through the composition module', () => {
  const routes = source('app.routes.ts');
  assert.match(routes, /\.\.\.CLIENT_APPLICATION_ROUTES\.map\(/);
  assert.doesNotMatch(routes, /features\/nawa/);
});

test('the Agent Studio wears the workspace appearance, always dark', () => {
  const studio = source('features/experience/work/pr-to-po-studio.component.ts');
  assert.match(studio, /class="xp-work xp-studio" data-brand-scope data-theme="dark" \[ngStyle\]="brandStyles\(\)"/);
  assert.doesNotMatch(studio, /data-studio=/);
  assert.match(studio, /appearanceStyles\(brand\?\.\['appearance'\], 'dark'\)/);
});

test('the Studio tokens derive from the workspace tokens, not from a palette', () => {
  const styles = source('features/experience/work/work.scss');
  const block = styles.slice(styles.indexOf('.xp-work.xp-studio {'), styles.indexOf('}', styles.indexOf('.xp-work.xp-studio {')));
  for (const token of ['bg', 'surface', 'fg', 'accent']) {
    assert.match(block, new RegExp(`--studio-${token}: [^;]*var\\(--(ck|xp)-`), `--studio-${token} follows the workspace`);
  }
  assert.doesNotMatch(block, /#[0-9a-f]{6}/i, 'no palette literal in the Studio tokens');
  assert.doesNotMatch(source('features/chat/chat-panel.component.ts'), /--nawa-/);
});

test('the appearance migration 113 declares turns the Studio accent and surfaces', () => {
  const styles = appearanceStyles({ palette: 'graphite', accent: '#e8543a' }, 'dark');
  assert.equal(styles['--xp-app-accent'], '#e8543a');
  assert.equal(styles['--ck-bg-base'], '#090909');
  assert.equal(styles['--xp-on-accent'], '#05070a');
});
