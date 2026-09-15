import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { NavLinkDirective } from './nav-link.directive';

test('a connection link in a new tab leaves the Skill draft in its current tab', () => {
  const navigations: string[] = [];
  const injector = Injector.create({ providers: [NavLinkDirective,
    { provide: Router, useValue: { navigateByUrl: (url: string) => { navigations.push(url); return Promise.resolve(true); } } },
    { provide: ZoomContextService, useValue: { resolveLink: () => ({ url: '/resources?facet=providers', replaceUrl: false }) } },
    { provide: NavigationTelemetryService, useValue: { registerTrigger: () => undefined } },
  ] });
  const link = injector.get(NavLinkDirective);
  Object.defineProperty(link, 'navLink', { value: () => ({ surface: 'resources', facet: 'providers' }) });
  let prevented = false;
  const event = (target: string) => ({
    button: 0, currentTarget: { target }, preventDefault: () => { prevented = true; },
  }) as unknown as MouseEvent;
  link.onClick(event('_blank'));
  assert.equal(prevented, false);
  assert.deepEqual(navigations, []);
  link.onClick(event('_self'));
  assert.equal(prevented, true);
  assert.deepEqual(navigations, ['/resources?facet=providers']);
});
