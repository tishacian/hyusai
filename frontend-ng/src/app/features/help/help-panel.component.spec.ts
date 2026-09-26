import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { DOCUMENT } from '@angular/common';
import { Injector, NgZone } from '@angular/core';
import { Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
} from '@app/core/workspace.service';
import {
  CkPanelComponent,
  CkPanelHostComponent,
  PanelHostService,
} from '@app/shared/cockpit/panel.component';
import { HelpOverlayService } from './help-overlay.service';
import { HelpPanelComponent } from './help-panel.component';

class WorkspaceStub {
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();
  current = () => ({ name: 'Operational Analysis', settings: {} });
  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }
}

test('? opens the help panel without changing the URL; Escape closes and restores focus', async () => {
  const PreviousHTMLElement = globalThis.HTMLElement;
  class FakeHTMLElement {
    focusCalls = 0;
    isConnected = true;
    focus() {
      this.focusCalls += 1;
    }
  }
  globalThis.HTMLElement = FakeHTMLElement as unknown as typeof HTMLElement;

  try {
    const trigger = new FakeHTMLElement();
    const doc = {
      activeElement: trigger as unknown as HTMLElement,
      defaultView: {
        innerWidth: 1280,
        localStorage: { getItem: () => null, setItem: () => undefined },
        requestAnimationFrame: (cb: FrameRequestCallback) => {
          cb(0);
          return 1;
        },
        cancelAnimationFrame: () => undefined,
      },
    };
    const url = '/work/operational-analysis/analysis';
    const injector = Injector.create({
      providers: [
        HelpOverlayService,
        PanelHostService,
        CkPanelHostComponent,
        CkPanelComponent,
        { provide: DOCUMENT, useValue: doc },
        {
          provide: NgZone,
          useValue: {
            run: <T>(fn: () => T) => fn(),
            runOutsideAngular: <T>(fn: () => T) => fn(),
          },
        },
        { provide: WorkspaceService, useValue: new WorkspaceStub() },
        {
          provide: Router,
          useValue: { url, navigateByUrl: () => Promise.resolve(true) },
        },
        { provide: I18nService, useValue: { t: (key: string) => key } },
      ],
    });
    const overlay = injector.get(HelpOverlayService);
    const host = injector.get(CkPanelHostComponent);
    const panel = injector.get(CkPanelComponent);
    panel.openChange.subscribe((open) => {
      if (!open) overlay.close();
    });

    // Work-bar / title-bar « ? »
    overlay.open({
      guideId: 'start',
      originLabel: 'Operational Analysis',
      originUrl: url,
    });
    panel.open = true;

    assert.equal(overlay.isOpen(), true);
    assert.equal(overlay.origin()?.url, url);
    assert.equal(injector.get(Router).url, url, 'panel open must not navigate');

    host.onEscape({ preventDefault() { /* Escape closes the top panel */ } } as Event);

    assert.equal(panel.open, false);
    assert.equal(overlay.isOpen(), false);
    await Promise.resolve();
    assert.equal(trigger.focusCalls, 1);
  } finally {
    if (PreviousHTMLElement) globalThis.HTMLElement = PreviousHTMLElement;
    else Reflect.deleteProperty(globalThis, 'HTMLElement');
  }
});

test('HelpPanelComponent mirrors ck-panel close onto the overlay service', () => {
  let closed = false;
  const panel = Object.assign(Object.create(HelpPanelComponent.prototype), {
    overlay: {
      close: () => {
        closed = true;
      },
    },
  }) as HelpPanelComponent;
  panel.onOpenChange(false);
  assert.equal(closed, true);
});

test('help panel template exposes search, see-also and full-page affordances', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/help/help-panel.component.ts'),
    'utf8',
  );
  assert.match(source, /experience\.help\.panel\.title/);
  assert.match(source, /experience\.help\.panel\.search/);
  assert.match(source, /experience\.help\.panel\.see_also/);
  assert.match(source, /openFullPage/);
  assert.match(source, /help-panel-full-page/);
});
