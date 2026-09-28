import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { HelpOverlayService } from '@app/features/help/help-overlay.service';
import { NavLinkDirective } from './nav-link.directive';

test('a connection link in a new tab leaves the Skill draft in its current tab', () => {
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      NavLinkDirective,
      {
        provide: Router,
        useValue: {
          url: '/skills/draft',
          navigateByUrl: (url: string) => {
            navigations.push(url);
            return Promise.resolve(true);
          },
        },
      },
      {
        provide: ZoomContextService,
        useValue: { resolveLink: () => ({ url: '/resources?facet=providers', replaceUrl: false }) },
      },
      { provide: NavigationTelemetryService, useValue: { registerTrigger: () => undefined } },
      { provide: HelpOverlayService, useValue: { openFromLink: () => false } },
      { provide: WorkspaceService, useValue: { current: () => ({ name: 'WS' }) } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
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

test('help-guide nav links open the panel on desktop instead of navigating', () => {
  const opens: unknown[] = [];
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      NavLinkDirective,
      {
        provide: Router,
        useValue: {
          url: '/work',
          navigateByUrl: (url: string) => {
            navigations.push(url);
            return Promise.resolve(true);
          },
        },
      },
      {
        provide: ZoomContextService,
        useValue: { resolveLink: () => ({ url: '/help/start', replaceUrl: false }) },
      },
      { provide: NavigationTelemetryService, useValue: { registerTrigger: () => undefined } },
      {
        provide: HelpOverlayService,
        useValue: {
          openFromLink: (guideId: string, origin: unknown) => {
            opens.push({ guideId, origin });
            return true;
          },
        },
      },
      { provide: WorkspaceService, useValue: { current: () => ({ name: 'Showcase' }) } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const link = injector.get(NavLinkDirective);
  Object.defineProperty(link, 'navLink', {
    value: () => ({ leaf: 'help-guide', params: { guideId: 'start' } }),
  });
  let prevented = false;
  link.onClick({
    button: 0,
    currentTarget: { target: '_self' },
    preventDefault: () => {
      prevented = true;
    },
  } as unknown as MouseEvent);
  assert.equal(prevented, true);
  assert.deepEqual(navigations, []);
  assert.deepEqual(opens, [{
    guideId: 'start',
    origin: { originLabel: 'experience.work.title', originUrl: '/work' },
  }]);
});
