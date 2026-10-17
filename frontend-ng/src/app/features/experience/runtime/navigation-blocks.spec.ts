import '@angular/compiler';
import { Injector, runInInjectionContext, signal } from '@angular/core';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { I18nService } from '@app/core/i18n.service';
import { ExperienceRuntimeService } from './experience-runtime.service';
import type { ExperienceNode } from './model';
import { CalloutBlock, FeedBlock } from './runtime-blocks';

function setup<T>(create: () => T, initial: ExperienceNode) {
  const locale = signal('fr');
  const node = signal(initial);
  const injector = Injector.create({ providers: [
    { provide: I18nService, useValue: { t: () => locale() === 'fr' ? 'Ouvrir' : 'Open' } },
    { provide: ExperienceRuntimeService, useValue: {} },
  ] });
  const block = runInInjectionContext(injector, create);
  Object.defineProperty(block, 'node', { value: node });
  return { block, locale, node };
}

test('callout links retain their route and use localized business context as their accessible name', () => {
  const href = '/models/12345678-1234-1234-1234-123456789abc';
  const { block, locale, node } = setup(() => new CalloutBlock(), {
    type: 'callout', id: 'capacity-model', props: { body: 'Prévision de charge', href },
  });
  assert.equal(block.href(), href);
  assert.equal(block.linkName(), 'Ouvrir: Prévision de charge');
  locale.set('en');
  node.set({ type: 'callout', props: { body: { $i18n: 'forecast', fallback: 'Workload forecast' }, href } });
  assert.equal(block.body(), 'Workload forecast');
  assert.equal(block.linkName(), 'Open: Workload forecast');
  for (const unsafe of ['//external.example/path', 'https://external.example/path', '/\\external.example/path']) {
    node.set({ type: 'callout', props: { href: unsafe } });
    assert.equal(block.href(), null);
  }
});

test('feed links use the authored title and never include their destination or internal block id', () => {
  const { block, node } = setup(() => new FeedBlock(), {
    type: 'intelligence_feed', id: 'feed-internal', props: { title: 'Événements à revoir', href: '/observability/activities' },
  });
  assert.equal(block.href(), '/observability/activities');
  assert.equal(block.linkName(), 'Ouvrir: Événements à revoir');
  node.set({ type: 'unknown-feed', id: 'feed-internal', props: { href: '/observability/activities' } });
  assert.equal(block.linkName(), 'Ouvrir');
});
