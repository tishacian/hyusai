import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ChatOverlayService } from './chat-overlay.service';
import { ConversationsComponent } from './conversations.component';

function harness(opts: { admin: boolean; facet?: string }) {
  const opens: unknown[] = [];
  const injector = Injector.create({
    providers: [
      ConversationsComponent,
      {
        provide: WorkspaceService,
        useValue: {
          isAdmin: () => opts.admin,
          getIamSummary: () => of({ members: [] }),
        },
      },
      {
        provide: ApiService,
        useValue: { get: () => of({ sessions: [] }) },
      },
      {
        provide: ChatOverlayService,
        useValue: { open: (o: unknown) => opens.push(o) },
      },
      {
        provide: I18nService,
        useValue: { locale: () => 'fr', t: (key: string) => key },
      },
      {
        provide: ActivatedRoute,
        useValue: {
          queryParamMap: of(convertToParamMap(opts.facet ? { facet: opts.facet } : {})),
        },
      },
      {
        provide: Router,
        useValue: { navigate: () => Promise.resolve(true) },
      },
    ],
  });
  return { injector, component: injector.get(ConversationsComponent), opens };
}

test('member has no facet toggle and stays on mine', () => {
  const { injector, component } = harness({ admin: false, facet: 'workspace' });
  try {
    component.setScopeFromQuery(convertToParamMap({ facet: 'workspace' }));
    assert.equal(component.isAdmin(), false);
    assert.equal(component.facet(), 'mine');
    assert.equal(component.showAuthorColumn(), false);
  } finally {
    injector.destroy();
  }
});

test('admin has facet toggle and author column on workspace', () => {
  const { injector, component } = harness({ admin: true, facet: 'workspace' });
  try {
    component.setScopeFromQuery(convertToParamMap({ facet: 'workspace' }));
    assert.equal(component.isAdmin(), true);
    assert.equal(component.facet(), 'workspace');
    assert.equal(component.showAuthorColumn(), true);
  } finally {
    injector.destroy();
  }
});

test('?facet=workspace is restored from the query map', () => {
  const { injector, component } = harness({ admin: true });
  try {
    assert.equal(component.facet(), 'mine');
    component.setScopeFromQuery(convertToParamMap({ facet: 'workspace' }));
    assert.equal(component.facet(), 'workspace');
  } finally {
    injector.destroy();
  }
});
