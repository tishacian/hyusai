/**
 * Source-level contract for the P2.3 activation funnel.
 *
 * Behaviour lives in `product-telemetry.service.spec.ts` and in the feature
 * specs. This file pins the part that behaviour cannot: that each milestone is
 * attached to the one authoritative success point that already existed in the
 * product, that none is inferred from a route visit or an optimistic click,
 * and that no call site smuggles a user string into the payload.
 */

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const read = (path: string): string => readFileSync(join(process.cwd(), path), 'utf8');

const SIGNIN = 'src/app/features/auth/signin.component.ts';
const RESOURCES = 'src/app/features/resources/resources-page.component.ts';
const KNOWLEDGE = 'src/app/features/knowledge/knowledge-base.component.ts';
const CHAT_WORKSPACE = 'src/app/features/chat/chat-workspace.component.ts';
const CHAT_PANEL = 'src/app/features/chat/chat-panel.component.ts';
const SYSTEM_BUILDER = 'src/app/features/systems/system-builder.component.ts';

const INSTRUMENTED = [SIGNIN, RESOURCES, KNOWLEDGE, CHAT_WORKSPACE, CHAT_PANEL, SYSTEM_BUILDER];

const signin = read(SIGNIN);
const resources = read(RESOURCES);
const knowledge = read(KNOWLEDGE);
const chatWorkspace = read(CHAT_WORKSPACE);
const chatPanel = read(CHAT_PANEL);
const systemBuilder = read(SYSTEM_BUILDER);

test('signed in is emitted once the credentials and the workspace scope are both settled', () => {
  // Inside the loadWorkspaces success handler: the login succeeded AND the
  // workspace the audit row is scoped to is known.
  assert.match(
    signin,
    /loadWorkspaces\(\)\.subscribe\(\{\s*next: \(\) => \{[\s\S]{0,400}?productTelemetry\.recordOnce\('signed_in'\)/,
  );
  // Not on the MFA challenge, and not merely on reaching the sign-in screen.
  assert.equal(/mfaChallenge\.set\([\s\S]{0,200}?recordOnce/.test(signin), false);
  assert.equal((signin.match(/recordOnce\('signed_in'\)/g) || []).length, 1);
});

test('model ready is emitted on the validated atomic setup response', () => {
  assert.match(
    resources,
    /\.put<ModelSetupResponse>\('\/models\/setup'[\s\S]*?next: \(res\) => \{[\s\S]{0,1200}?productTelemetry\.recordOnce\('model_ready'\)/,
  );
  assert.equal((resources.match(/recordOnce\('model_ready'\)/g) || []).length, 1);
  // The error path never claims the milestone.
  assert.equal(/error: \(err\) => \{[\s\S]{0,300}?recordOnce\('model_ready'\)/.test(resources), false);
});

test('model ready is also reached by a returning user whose probe answers ready', () => {
  // Inside the readiness success callback, after the stale-answer guard, and
  // only for an actually ready status.
  assert.match(
    chatPanel,
    /getModelReadiness\(\{ workspaceSlug: scope\.workspaceSlug \}\)[\s\S]*?next: \(readiness\) => \{\s*\n\s*if \(!this\.isChatContinuationCurrent\(scope, generation\)\) return;[\s\S]{0,600}?if \(readiness\?\.status === 'ready'\) \{\s*\n\s*this\.productTelemetry\.recordOnce\('model_ready'\);/,
  );
  assert.equal((chatPanel.match(/recordOnce\('model_ready'\)/g) || []).length, 1);
  // A failed probe blames nothing and claims nothing.
  assert.equal(
    /error: \(\) => \{[\s\S]{0,300}?this\.modelReadiness\.set\(null\);[\s\S]{0,200}?recordOnce\('model_ready'\)/.test(chatPanel),
    false,
  );
});

test('knowledge added requires the batch endpoint to confirm an indexed document', () => {
  for (const source of [knowledge, chatWorkspace]) {
    assert.match(
      source,
      /if \(res\.successful > 0\) \{[\s\S]{0,600}?productTelemetry\.recordOnce\('knowledge_added'\)/,
    );
  }
  // A drop that only opened the dropzone is not knowledge added.
  assert.equal(/onDrop\([\s\S]{0,300}?recordOnce\('knowledge_added'\)/.test(knowledge), false);
  assert.equal(/uploadState\.set\('uploading'\)[\s\S]{0,200}?recordOnce/.test(knowledge), false);
});

test('the first question is recorded when the stream request is actually open', () => {
  assert.match(
    chatPanel,
    /this\.chatWorkspaceSubscriptions\.add\(streamSubscription\);[\s\S]{0,400}?productTelemetry\.recordOnce\('first_question_sent'\)/,
  );
  assert.equal((chatPanel.match(/recordOnce\('first_question_sent'\)/g) || []).length, 1);
  // Typing, or the early return that lazily creates the session, is not a
  // question sent.
  assert.equal(/onKey\(e: KeyboardEvent\)[\s\S]{0,300}?recordOnce/.test(chatPanel), false);
});

test('the first answer requires a completed, non-failed turn that produced text', () => {
  assert.match(
    chatPanel,
    /if \(!streamFailure && !expertCorrection && buffer\.trim\(\)\.length > 0\) \{[\s\S]{0,500}?productTelemetry\.recordOnce\(\s*'first_answer_completed',\s*\{\s*elapsedMs: durationMs,?\s*\},?\s*\)/,
  );
  assert.equal((chatPanel.match(/'first_answer_completed'/g) || []).length, 1);
  // The transport-error path of the same stream records nothing.
  assert.equal(
    /error: \(\) => \{[\s\S]{0,900}?'first_answer_completed'/.test(chatPanel),
    false,
  );
});

test('a source counts as opened once the citation resolved to a real document', () => {
  // `previewSource` returns early unless a document id and collection resolve,
  // so the record sits after the preview is actually open.
  assert.match(
    chatPanel,
    /previewSource\(src: Source\): void \{[\s\S]*?if \(!documentId \|\| !collection\) return;[\s\S]*?this\.sourcePreviewOpen\.set\(true\);[\s\S]{0,300}?productTelemetry\.recordOnce\('source_opened'\)/,
  );
  assert.equal((chatPanel.match(/recordOnce\('source_opened'\)/g) || []).length, 1);
});

test('failure recovered is only claimed when the retried action succeeded', () => {
  // Chat: the retry affordances arm a kind; the successful turn consumes it.
  assert.match(chatPanel, /this\.pendingRecoveryKind = 'chat_retry';\s*\n\s*this\.send\(\);/);
  assert.match(chatPanel, /this\.pendingRecoveryKind = 'model_setup_return';/);
  assert.match(
    chatPanel,
    /const recoveryKind = this\.pendingRecoveryKind;\s*\n\s*this\.pendingRecoveryKind = null;/,
  );
  assert.match(
    chatPanel,
    /if \(recoveryKind\) \{[\s\S]{0,500}?recordOccurrence\('failure_recovered', \{[\s\S]{0,300}?recoveryKind,/,
  );
  // Knowledge and model setup: the previous failure is remembered, and only a
  // later success reports the recovery.
  // `uploadState` is already back to `uploading` by the time a response
  // arrives, so the intent is carried by an explicit flag instead.
  assert.match(knowledge, /this\.uploadRecoveryPending = true;/);
  assert.match(
    knowledge,
    /if \(this\.uploadRecoveryPending && res\.failed === 0\) \{\s*\n\s*this\.uploadRecoveryPending = false;[\s\S]{0,400}?recordOccurrence\('failure_recovered', \{[\s\S]{0,300}?recoveryKind: 'knowledge_upload',/,
  );
  assert.equal(knowledge.includes("this.uploadState() === 'error'"), false);
  assert.match(
    resources,
    /if \(this\.setupRecoveryPending\) \{[\s\S]{0,400}?recordOccurrence\('failure_recovered', \{[\s\S]{0,300}?recoveryKind: 'model_setup_save',/,
  );
  assert.match(resources, /error: \(err\) => \{[\s\S]{0,300}?this\.setupRecoveryPending = true;/);
});

test('a System counts as published only when the API returned a live System', () => {
  assert.match(
    systemBuilder,
    /op\$\.subscribe\(\(sys\) => \{[\s\S]{0,200}?if \(sys\) \{[\s\S]{0,400}?recordOccurrence\('system_published'/,
  );
  // The local-draft fallback is explicitly not a publication.
  assert.equal(
    /createDraft\(\{[\s\S]{0,600}?recordOccurrence\('system_published'/.test(systemBuilder),
    false,
  );
  assert.equal((systemBuilder.match(/'system_published'/g) || []).length, 1);
  // Publication stays gated on readiness, which the record must not bypass.
  assert.match(systemBuilder, /if \(!this\.allGatesValid\(\) \|\| this\.launching\(\)\) return;/);
});

test('every instrumented file imports the one shared telemetry service', () => {
  for (const path of INSTRUMENTED) {
    const source = read(path);
    assert.match(
      source,
      /import \{[\s\S]{0,160}?ProductTelemetryService[\s\S]{0,160}?\} from '@app\/core\/product-telemetry\.service';/,
      `${path} must import ProductTelemetryService`,
    );
    assert.match(
      source,
      /productTelemetry = inject\(ProductTelemetryService\)/,
      `${path} must inject ProductTelemetryService`,
    );
  }
});

test('no feature component builds an activation audit payload of its own', () => {
  for (const path of INSTRUMENTED) {
    const source = read(path);
    assert.equal(
      source.includes('product.activation'),
      false,
      `${path} must not hard-code an activation event name`,
    );
    const audits = source.match(/post\('\/audit'/g) || [];
    // chat-panel keeps its own pre-existing `chat_*` audit helper; nothing else
    // may post to /audit directly for activation.
    assert.ok(
      audits.length === 0 || path === CHAT_PANEL,
      `${path} must go through ProductTelemetryService`,
    );
  }
});

test('activation call sites pass only the closed option set', () => {
  const allowed = new Set(['dedupeKey', 'recoveryKind', 'elapsedMs']);
  const calls = [...INSTRUMENTED
    .map((path) => read(path))
    .join('\n')
    .matchAll(/record(?:Once|Occurrence)\(\s*'[a-z_]+',\s*\{([\s\S]*?)\}\s*\)/g)];
  assert.ok(calls.length >= 4, 'the optioned call sites are covered');
  for (const call of calls) {
    const keys = [...call[1].matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:/gm)].map((m) => m[1]);
    for (const key of keys) {
      assert.ok(allowed.has(key), `unexpected activation option "${key}"`);
    }
  }
});

test('activation is never inferred from navigation', () => {
  const navigation = read('src/app/core/navigation-telemetry.service.ts');
  assert.equal(navigation.includes('ProductTelemetryService'), false);
  const service = read('src/app/core/product-telemetry.service.ts');
  // The service reads the router only to mask the current surface; it never
  // subscribes to navigation events.
  assert.equal(service.includes('router.events'), false);
  assert.equal(service.includes('NavigationEnd'), false);
});

test('the service emits best-effort and cannot change the user action', () => {
  const service = read('src/app/core/product-telemetry.service.ts');
  assert.match(service, /\.post\('\/audit', \{[\s\S]*?\}\)\s*\.subscribe\(\{[\s\S]*?error: \(\) => \{/);
  assert.equal(service.includes('await '), false);
  assert.equal(service.includes('firstValueFrom'), false);
  // The detail contract is the only shape that reaches the wire.
  assert.match(service, /details: ProductActivationDetails;/);
});
