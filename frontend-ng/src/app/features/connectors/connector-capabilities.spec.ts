import assert from 'node:assert/strict';
import { test } from 'node:test';
import { CONNECTOR_ACTIONS, connectorCapabilities, connectionChecks } from './connector-capabilities';

test('unsupported connector actions remain explicit and cannot inherit PostgreSQL features', () => {
  assert.equal(connectorCapabilities('sharepoint').schedule, false);
  assert.equal(connectorCapabilities('sharepoint').test, true);
  assert.equal(connectorCapabilities('rpa_bridge').import, false);
  assert.equal(connectorCapabilities('s3').schedule, true);
  assert.deepEqual(Object.keys(connectorCapabilities('future')), [...CONNECTOR_ACTIONS]);
  assert.equal(Object.values(connectorCapabilities('future')).some(Boolean), false);
  assert.equal(connectorCapabilities('smtp', { available: true, testable: false }).test, false);
});

test('a saved configuration and a missing test response never imply a successful connection', () => {
  const checks = connectionChecks({}, true);
  assert.equal(checks.configuration, 'passed');
  assert.equal(checks.authentication, 'unknown');
  assert.equal(checks.resource, 'unknown');
  assert.equal(connectionChecks({ ok: false }, true).reason, 'unknown');
});

test('authentication, resource permission and transport failures are distinct', () => {
  assert.deepEqual(connectionChecks({ status: 'auth_failed' }, true), {
    configuration: 'passed', authentication: 'failed', resource: 'not-tested', reason: 'auth_failed',
  });
  assert.equal(connectionChecks({ status: 'access_denied' }, true).resource, 'failed');
  assert.equal(connectionChecks({ status: 'unreachable' }, true).resource, 'unknown');
  assert.equal(connectionChecks({ status: 'connected' }, true).resource, 'passed');
  assert.equal(connectionChecks({ status: 'not_configured' }, true).configuration, 'failed');
});
