import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  ActivatedRouteSnapshot,
  Route,
  convertToParamMap,
} from '@angular/router';
import { WorkspaceRouteReuseStrategy } from './workspace-route-reuse.strategy';

function snapshot(routeConfig: Route | null, params: Record<string, string>): ActivatedRouteSnapshot {
  return {
    routeConfig,
    paramMap: convertToParamMap(params),
  } as ActivatedRouteSnapshot;
}

test('workspace Chat is not reused when the deep-link slug changes', () => {
  const strategy = new WorkspaceRouteReuseStrategy();
  const routeConfig: Route = { path: ':slug/chat' };

  assert.equal(
    strategy.shouldReuseRoute(
      snapshot(routeConfig, { slug: 'sentinel-ci' }),
      snapshot(routeConfig, { slug: 'andritz' }),
    ),
    false,
  );
});

test('workspace Chat remains reusable inside the same workspace', () => {
  const strategy = new WorkspaceRouteReuseStrategy();
  const routeConfig: Route = { path: ':slug/chat' };

  assert.equal(
    strategy.shouldReuseRoute(
      snapshot(routeConfig, { slug: 'andritz' }),
      snapshot(routeConfig, { slug: 'andritz' }),
    ),
    true,
  );
});

test('workspace shell is recreated from workspace A settings to workspace B settings', () => {
  const strategy = new WorkspaceRouteReuseStrategy();
  const workspaceRouteConfig: Route = { path: ':slug' };

  assert.equal(
    strategy.shouldReuseRoute(
      snapshot(workspaceRouteConfig, { slug: 'sentinel-ci' }),
      snapshot(workspaceRouteConfig, { slug: 'andritz' }),
    ),
    false,
  );
});

test('hierarchy detail components are recreated when their route-owned id changes', () => {
  const strategy = new WorkspaceRouteReuseStrategy();
  const routeConfig: Route = { path: ':systemId' };

  assert.equal(
    strategy.shouldReuseRoute(
      snapshot(routeConfig, { systemId: 'system-b' }),
      snapshot(routeConfig, { systemId: 'system-a' }),
    ),
    false,
  );
});

test('unrelated parameterized routes keep Angular default reuse semantics', () => {
  const strategy = new WorkspaceRouteReuseStrategy();
  const routeConfig: Route = { path: ':presetId' };

  assert.equal(
    strategy.shouldReuseRoute(
      snapshot(routeConfig, { presetId: 'preset-b' }),
      snapshot(routeConfig, { presetId: 'preset-a' }),
    ),
    true,
  );
});
