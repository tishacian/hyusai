import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { SKILLS_EN, SKILLS_FR } from '@app/core/i18n/skills.dict';
import { ModelExecutionComponent } from './model-execution.component';

function component(locale: 'fr' | 'en') {
  const dictionary = locale === 'fr' ? SKILLS_FR : SKILLS_EN;
  return Injector.create({ providers: [ModelExecutionComponent, {
    provide: I18nService, useValue: { t: (key: string, values: Record<string, unknown> = {}) => {
      const text = dictionary[key as keyof typeof dictionary] ?? key;
      return text.replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? ''));
    } },
  }] }).get(ModelExecutionComponent);
}

test('recorded named routes remain understandable provenance in both languages', () => {
  assert.equal(component('fr').source('route:balanced'), 'Route de modèles · balanced');
  assert.equal(component('en').source('route:fast_local'), 'Model route · fast_local');
});

test('missing route names remain unknown and legacy connection provenance is preserved', () => {
  const view = component('en');
  assert.equal(view.source('route:'), 'Source not recorded');
  assert.equal(view.source('route:   '), 'Source not recorded');
  assert.equal(view.source('unrecognized'), 'Source not recorded');
  assert.equal(view.source('published_legacy_default'), 'Preserved historical default');
  assert.equal(view.source('env'), 'Deployment configuration');
});
