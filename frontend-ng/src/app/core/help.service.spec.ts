import '@angular/compiler';
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { ApiService } from './api.service';
import { HelpService } from './help.service';
import { InterfaceLocale } from './interface-locale';
import { WorkspaceService } from './workspace.service';

const STORAGE_KEY = 'agentium.help.lang';
const previousLocalStorage = globalThis.localStorage;
let store: Map<string, string>;

beforeEach(() => {
  store = new Map();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    },
  });
});

afterEach(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: previousLocalStorage,
  });
});

function makeHelp(locale: ReturnType<typeof signal<'fr' | 'en'>>): HelpService {
  const injector = Injector.create({
    providers: [
      HelpService,
      { provide: InterfaceLocale, useValue: { locale } },
      { provide: WorkspaceService, useValue: { registerContextReset: () => undefined } },
      { provide: ApiService, useValue: {} },
    ],
  });
  return injector.get(HelpService);
}

test('guides open in the interface language when the reader has not chosen one', () => {
  const locale = signal<'fr' | 'en'>('fr');
  const help = makeHelp(locale);

  assert.equal(help.language(), 'fr');
  locale.set('en');
  assert.equal(help.language(), 'en');
});

test('a guide language the reader picks wins over the interface and is kept', () => {
  const locale = signal<'fr' | 'en'>('fr');
  const help = makeHelp(locale);

  help.setLanguage('en');
  assert.equal(help.language(), 'en');
  assert.equal(store.get(STORAGE_KEY), 'en');

  const next = makeHelp(signal<'fr' | 'en'>('fr'));
  assert.equal(next.language(), 'en');
});

test('an unreadable stored value falls back to the interface language', () => {
  store.set(STORAGE_KEY, 'de');
  const help = makeHelp(signal<'fr' | 'en'>('fr'));

  assert.equal(help.language(), 'fr');
});
