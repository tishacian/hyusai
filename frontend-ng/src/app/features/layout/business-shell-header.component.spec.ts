import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { type WorkspaceSwitchState, WorkspaceSwitchService } from '@app/core/workspace-switch.service';
import { AuthStore } from '@app/store/auth.store';
import { BusinessShellHeaderComponent } from './business-shell-header.component';

function harness(outcome: WorkspaceSwitchState) {
  const requested: string[] = [];
  const injector = Injector.create({
    providers: [
      BusinessShellHeaderComponent,
      {
        provide: WorkspaceSwitchService,
        useValue: {
          state: signal<WorkspaceSwitchState>({ phase: 'idle' }),
          switch: async (slug: string) => {
            requested.push(slug);
            return outcome;
          },
        },
      },
      {
        provide: WorkspaceService,
        useValue: {
          brandName: signal('Agentium'),
          currentSlug: () => 'andritz',
          workspaces: () => [],
          current: () => null,
        },
      },
      { provide: NavigationProfileService, useValue: {} },
      { provide: AuthStore, useValue: { email: () => null } },
      { provide: ThemeService, useValue: { businessTheme: () => 'dark', cycleBusinessTheme: () => undefined } },
      { provide: I18nService, useValue: { locale: signal('en'), t: (key: string) => key } },
      { provide: Router, useValue: {} },
    ],
  });
  return { injector, requested, header: injector.get(BusinessShellHeaderComponent) };
}

test('the business header switches through the shared service and never reloads the page', () => {
  const source = readFileSync(
    join(process.cwd(), 'src', 'app', 'features', 'layout', 'business-shell-header.component.ts'),
    'utf8',
  );
  assert.doesNotMatch(source, /location\.reload/);
  assert.doesNotMatch(source, /navigateByUrl\('\/hypervisor', \{ replaceUrl: true \}\)/);
});

test('a switch that does not land puts the native select back on the current workspace', async () => {
  const { injector, requested, header } = harness({
    phase: 'suspended',
    slug: 'sentinel-ci',
    label: 'PR to PO',
    count: 3,
  });
  try {
    const select = { value: 'sentinel-ci' } as HTMLSelectElement;
    await header.selectWorkspace('sentinel-ci', select);
    assert.deepEqual(requested, ['sentinel-ci']);
    assert.equal(select.value, 'andritz');
  } finally {
    injector.destroy();
  }
});

test('a switch that lands leaves the select on the new workspace', async () => {
  const { injector, header } = harness({
    phase: 'switched',
    slug: 'sentinel-ci',
    previousSlug: 'andritz',
    url: '/chat',
  });
  try {
    const select = { value: 'sentinel-ci' } as HTMLSelectElement;
    await header.selectWorkspace('sentinel-ci', select);
    assert.equal(select.value, 'sentinel-ci');
  } finally {
    injector.destroy();
  }
});
