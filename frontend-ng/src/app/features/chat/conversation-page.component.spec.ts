import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { AuthStore } from '@app/store/auth.store';
import { ChatOverlayService } from './chat-overlay.service';
import { ConversationPageComponent } from './conversation-page.component';

function harness(opts: {
  userId: string;
  session: Record<string, unknown>;
}) {
  const opens: Array<Record<string, unknown>> = [];
  const getCalls: string[] = [];
  const injector = Injector.create({
    providers: [
      ConversationPageComponent,
      {
        provide: ApiService,
        useValue: {
          get: (url: string) => {
            getCalls.push(url);
            return of(opts.session);
          },
        },
      },
      {
        provide: ChatOverlayService,
        useValue: {
          open: (o: Record<string, unknown>) => opens.push(o),
        },
      },
      {
        provide: AuthStore,
        useValue: { userId: () => opts.userId },
      },
      {
        provide: I18nService,
        useValue: {
          locale: () => 'fr',
          t: (key: string, vars?: Record<string, string>) => {
            if (key === 'nav.zoom.linked_to') return `Liée à ${vars?.['name']}`;
            return key;
          },
        },
      },
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: of(convertToParamMap({ conversationId: String(opts.session['id']) })),
        },
      },
    ],
  });
  const component = injector.get(ConversationPageComponent);
  return { injector, component, opens, getCalls };
}

test('conversation page loads session, shows Liée à, and Reprendre opens overlay', () => {
  const { injector, component, opens, getCalls } = harness({
    userId: 'user-me',
    session: {
      id: 'sess-1',
      user_id: 'user-me',
      title: 'Pompe',
      message_count: 2,
      messages: [{ role: 'user', content: 'bonjour' }],
      meta_data: {
        linked_object: { type: 'system', id: 'sys-1', label: 'Système Alpha', lens: 'operate' },
      },
    },
  });
  try {
    component.loadSession('sess-1');
    assert.ok(getCalls.some((url) => url.includes('/sessions/sess-1')));
    assert.equal(component.title(), 'Pompe');
    assert.equal(component.linkedLabel(), 'Système Alpha');
    assert.equal(component.readOnly(), false);
    component.resumeInOverlay();
    assert.deepEqual(opens[0], {
      mode: 'system',
      systemId: 'sys-1',
      sessionId: 'sess-1',
      linkedLabel: 'Système Alpha',
    });
  } finally {
    injector.destroy();
  }
});

test('others conversations are read-only for admin', () => {
  const { injector, component, opens } = harness({
    userId: 'user-admin',
    session: {
      id: 'sess-other',
      user_id: 'user-other',
      title: 'Autre',
      messages: [],
      meta_data: {},
    },
  });
  try {
    component.loadSession('sess-other');
    assert.equal(component.readOnly(), true);
    component.resumeInOverlay();
    assert.equal(opens.length, 0);
  } finally {
    injector.destroy();
  }
});
