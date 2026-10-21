/**
 * Sign-in destination contract (US02): after a session expires, signing in
 * reopens the page the person was on, never a sign-in page, and never an
 * address on another origin.
 */
import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { Router, UrlTree, type Params } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthApiService } from './auth-api.service';
import { AuthRefreshCoordinator } from './auth-refresh-coordinator.service';
import { normalizeAuthRedirect, unwrapAuthRedirect } from './auth-redirect';
import { TokenStorageService } from './token-storage.service';
import { AuthStore } from '../store/auth.store';

test('an in-app path is its own destination', () => {
  assert.equal(normalizeAuthRedirect('/systems/x/flow'), '/systems/x/flow');
  assert.equal(normalizeAuthRedirect('/runs/r1?since=7d#q'), '/runs/r1?since=7d#q');
});

test('a sign-in URL is unwrapped to the destination it carries', () => {
  const once = `/auth/signin?redirectURL=${encodeURIComponent('/systems/x/flow')}`;
  const twice = `/auth/signin?redirectURL=${encodeURIComponent(once)}`;
  assert.equal(normalizeAuthRedirect(once), '/systems/x/flow');
  assert.equal(normalizeAuthRedirect(twice), '/systems/x/flow');
});

test('a sign-in URL without destination falls back to the home page', () => {
  assert.equal(unwrapAuthRedirect('/auth/signin'), null);
  assert.equal(normalizeAuthRedirect('/auth/signin'), '/');
  assert.equal(normalizeAuthRedirect('/auth'), '/');
});

test('another origin is never a destination', () => {
  for (const value of ['//evil.example/x', '/\\evil.example', 'https://evil.example', '', null, 42]) {
    assert.equal(normalizeAuthRedirect(value), '/', String(value));
  }
  const smuggled = `/auth/signin?redirectURL=${encodeURIComponent('//evil.example')}`;
  assert.equal(normalizeAuthRedirect(smuggled), '/');
});

test('a route that only starts with "auth" is not a sign-in page', () => {
  assert.equal(normalizeAuthRedirect('/authorizations'), '/authorizations');
});

function expiringCoordinator(router: Record<string, unknown>) {
  const navigations: { commands: unknown[]; queryParams: Params }[] = [];
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: AuthStore, useValue: { clear: () => undefined } },
      {
        provide: TokenStorageService,
        useValue: { getToken: () => null, getRefreshToken: () => null, clear: () => undefined },
      },
      { provide: AuthApiService, useValue: {} },
      {
        provide: Router,
        useValue: {
          getCurrentNavigation: () => null,
          serializeUrl: (tree: UrlTree) => tree.toString(),
          ...router,
          navigate: (commands: unknown[], extras: { queryParams: Params }) => {
            navigations.push({ commands, queryParams: extras.queryParams });
            return Promise.resolve(true);
          },
        },
      },
    ],
  });
  return { coordinator: injector.get(AuthRefreshCoordinator), navigations };
}

async function expire(coordinator: AuthRefreshCoordinator): Promise<void> {
  await assert.rejects(firstValueFrom(coordinator.refreshAccessToken()));
}

test('an expired session on a Flow page signs in back to that page', async () => {
  const { coordinator, navigations } = expiringCoordinator({ url: '/systems/x/flow' });
  await expire(coordinator);
  assert.deepEqual(navigations, [
    { commands: ['/auth/signin'], queryParams: { redirectURL: '/systems/x/flow' } },
  ]);
});

test('an expiry on the sign-in page keeps the original destination, unnested', async () => {
  const { coordinator, navigations } = expiringCoordinator({
    url: `/auth/signin?redirectURL=${encodeURIComponent('/systems/x/flow')}`,
  });
  await expire(coordinator);
  assert.deepEqual(navigations[0].queryParams, { redirectURL: '/systems/x/flow' });
});

test('an expiry during a navigation resumes the page being opened', async () => {
  const target = { toString: () => '/runs/r1?since=30d' } as unknown as UrlTree;
  const { coordinator, navigations } = expiringCoordinator({
    url: '/systems/x/flow',
    getCurrentNavigation: () => ({ extractedUrl: target, finalUrl: undefined }),
  });
  await expire(coordinator);
  assert.deepEqual(navigations[0].queryParams, { redirectURL: '/runs/r1?since=30d' });
});

test('an expiry with no destination opens sign-in without a redirect', async () => {
  const { coordinator, navigations } = expiringCoordinator({ url: '/auth/signin' });
  await expire(coordinator);
  assert.deepEqual(navigations[0].queryParams, {});
});
