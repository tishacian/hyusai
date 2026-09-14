/** Source-level contract for the first-run model setup loop. */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

const source = (path: string): string => readFileSync(join(process.cwd(), path), 'utf8');
const resourcesSource = source('src/app/features/resources/resources-page.component.ts');
const routesSource = source('src/app/app.routes.ts');
const recoverySource = source('src/app/features/chat/chat-reliability.component.ts');
const chatSource = source('src/app/features/chat/chat-panel.component.ts');
const settingsSource = source('src/app/core/settings.service.ts');

test('one guided form validates routing and credentials through the atomic setup endpoint', () => {
  assert.ok(resourcesSource.includes(".put<ModelSetupResponse>('/models/setup'"));
  assert.equal(
    (resourcesSource.match(/\.put<ModelSetupResponse>\('\/models\/setup'/g) || []).length,
    1,
  );
  assert.equal(resourcesSource.includes(".put<RoutingResponse>('/models/routing'"), false);
  assert.equal(resourcesSource.includes('saveCredential('), false);
  assert.ok(resourcesSource.includes("resources.providers.routing.validation_hint"));
});

test('Settings owns the single provider setup surface', () => {
  assert.match(
    routesSource,
    /path: 'settings',[\s\S]*?defaultFacet: 'providers'[\s\S]*?ResourcesPageComponent/,
  );
  assert.match(routesSource, /path: 'settings\/models',[\s\S]*?redirectTo: 'settings'/);
  assert.match(resourcesSource, /focusedSettings\.set\(this\.router\.url\.split\('\?'\)\[0\] === '\/settings'\)/);
  assert.match(resourcesSource, /@if \(!focusedSettings\(\)\) \{[\s\S]*Portfolio summary belongs to Resources/);
});

test('model readiness is reported from the validated save, never from the form', () => {
  assert.match(
    resourcesSource,
    /next: \(res\) => \{[\s\S]{0,1200}?recordOnce\('model_ready'\)/,
  );
  assert.match(resourcesSource, /recoveryKind: 'model_setup_save',/);
  // The failing save arms the recovery instead of claiming one.
  assert.match(resourcesSource, /error: \(err\) => \{[\s\S]{0,300}?this\.setupRecoveryPending = true;/);
  assert.equal(resourcesSource.includes('product.activation'), false);
});

test('validated workspace model selection becomes the visible chat runtime', () => {
  assert.match(
    resourcesSource,
    /next: \(res\) => \{[\s\S]{0,1400}?adoptValidatedModelSelection\([\s\S]{0,200}?res\.routing\.default_provider[\s\S]{0,200}?res\.routing\.default_model/,
  );
  assert.match(
    chatSource,
    /readiness\?\.provider && readiness\?\.model[\s\S]{0,180}?adoptValidatedModelSelection\(readiness\.provider, readiness\.model\)/,
  );
  assert.match(
    chatSource,
    /this\.modelReadiness\(\)\?\.model \|\| this\.settings\.settings\(\)\.defaultModel/,
  );
  assert.match(settingsSource, /adoptValidatedModelSelection\(provider: string, model: string\)/);
  assert.match(settingsSource, /performs\s*\n\s*\* no second write/);
});

test('chat recovery preserves the question and exposes only compact safe diagnostics', () => {
  assert.ok(recoverySource.includes('readonly configure = output<void>()'));
  assert.ok(recoverySource.includes("chat.failure.technical_details"));
  assert.equal(recoverySource.includes('All connection attempts failed'), false);
  assert.equal(recoverySource.includes('NavLinkDirective'), false);
});
