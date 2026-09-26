import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AuthStore } from '@app/store/auth.store';
import { I18nService } from '@app/core/i18n.service';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { HelpOverlayService } from '@app/features/help/help-overlay.service';
import { WorkBarComponent } from './work-bar.component';

test('Work-bar ? opens the help panel for the current app without navigating', () => {
  const opens: unknown[] = [];
  const router = { url: '/work/operational-analysis/analysis', navigateByUrl: () => Promise.resolve(true) };
  const injector = Injector.create({
    providers: [
      WorkBarComponent,
      {
        provide: HelpOverlayService,
        useValue: {
          isOpen: () => false,
          open: (options: unknown) => opens.push(options),
          close: () => undefined,
          openFullPage: () => undefined,
        },
      },
      {
        provide: ChatOverlayService,
        useValue: { isOpen: () => false, open: () => undefined, close: () => undefined },
      },
      {
        provide: WorkspaceService,
        useValue: {
          current: () => ({ name: 'Agentium Showcase', settings: {}, role_template: 'viewer' }),
          experienceStudioV1Enabled: () => false,
          isAdmin: () => false,
        },
      },
      { provide: AuthStore, useValue: { email: () => 'ti@example.test' } },
      {
        provide: ThemeService,
        useValue: { resolved: () => 'dark' },
      },
      {
        provide: I18nService,
        useValue: {
          t: (key: string) => key,
          locale: signal('fr'),
          setLocale: () => undefined,
        },
      },
      { provide: Router, useValue: router },
    ],
  });
  const bar = injector.get(WorkBarComponent);
  Object.defineProperty(bar, 'appContext', { value: () => 'Operational Analysis' });

  bar.openHelp();

  assert.equal(opens.length, 1);
  assert.deepEqual(opens[0], {
    originLabel: 'Operational Analysis',
    originUrl: '/work/operational-analysis/analysis',
  });
});
