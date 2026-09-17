import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DefaultUrlSerializer, UrlTree } from '@angular/router';
import { SystemViewComponent } from './system-view.component';

test('all System stage links keep their context outside the router path', () => {
  const serializer = new DefaultUrlSerializer();
  const surface = (id: string) => `/${id}?systemId=system-1&lens=build`;
  const leaf = (id: string) => `/${id}?systemId=system-1&lens=build`;
  for (const family of ['rag', 'translation', 'capture']) {
    const view = Object.assign(Object.create(SystemViewComponent.prototype), {
      systemId: 'system-1',
      isTranslationSuite: () => family === 'translation',
      isExpertKnowledgeCapture: () => family === 'capture',
      i18n: { t: (key: string) => key },
      navigation: {
        surfaceUrl: surface, leafUrl: leaf,
        surfaceUrlTree: (id: string) => serializer.parse(surface(id)),
        leafUrlTree: (id: string) => serializer.parse(leaf(id)),
      },
    }) as SystemViewComponent;
    assert.ok(view.pipelineStages.length > 0);
    for (const stage of view.pipelineStages) {
      assert.ok(stage.route instanceof UrlTree, `${family}/${stage.key} must supply RouterLink a UrlTree`);
      assert.equal(stage.route.queryParams['systemId'], 'system-1');
      assert.equal(stage.route.queryParams['lens'], 'build');
      assert.ok(!serializer.serialize(stage.route).includes('%3F'));
    }
  }
});
