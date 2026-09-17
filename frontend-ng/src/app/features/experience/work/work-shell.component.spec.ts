import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DefaultUrlSerializer, UrlTree } from '@angular/router';
import { WorkShellComponent } from './work-shell.component';

test('Work editor links preserve the application ID and release context as router query parameters', () => {
  const serializer = new DefaultUrlSerializer();
  const shell = Object.assign(Object.create(WorkShellComponent.prototype), {
    router: { parseUrl: (url: string) => serializer.parse(url) },
    activePage: () => 'analysis',
    requestedPage: () => null,
    slug: () => 'operational-analysis',
    experienceId: () => 'app-1',
    releaseId: () => 'release-1',
    releaseNumber: () => 3,
  }) as WorkShellComponent;

  const tree = shell.studioLink();
  assert.ok(tree instanceof UrlTree, 'RouterLink must receive a UrlTree, not a URL string encoded as one path');
  assert.deepEqual(tree.root.children['primary'].segments.map(s => s.path), ['create', 'apps', 'app-1']);
  assert.deepEqual(tree.queryParams, {
    pageId: 'analysis', returnTo: '/work/operational-analysis/analysis', releaseId: 'release-1', releaseNumber: '3',
  });
  assert.equal(serializer.serialize(tree), '/create/apps/app-1?pageId=analysis&returnTo=%2Fwork%2Foperational-analysis%2Fanalysis&releaseId=release-1&releaseNumber=3');

  Object.assign(shell, { activePage: () => 'validations', releaseId: () => null, releaseNumber: () => null });
  assert.deepEqual(shell.studioLink().queryParams, { returnTo: '/work/operational-analysis/validations' });
});
