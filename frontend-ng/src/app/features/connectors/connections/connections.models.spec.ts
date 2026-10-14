import assert from 'node:assert/strict';
import { test } from 'node:test';
import { connectionPayload, parameterEnabled, type ConnectionProfile } from './connections.models';

const profile: ConnectionProfile = {
  key: 'postgresql', version: 1, family: 'dbapi', certification: 'unverified', driver_status: 'runner_unchecked', capabilities: { read: true },
  parameters: [
    { key: 'port', type: 'integer', required: true, choices: [], when: {}, advanced: false, min: 1, max: 65535 },
    { key: 'password', type: 'secret', required: true, choices: [], when: {}, advanced: false },
    { key: 'policy', type: 'json', required: false, choices: [], when: {}, advanced: true },
  ],
};
test('generated form submits typed public fields and references only', () => {
  const body = connectionPayload(profile, ' ERP ', { port: '5432', password: 'never-send-me', policy: '{"read":true}', unknown: 'not-in-profile' }, { password: 'secret://workspace/pg' }, 'read', ['public'], []);
  assert.equal(body.name, 'ERP'); assert.deepEqual(body.values, { port: 5432, policy: { read: true } });
  assert.deepEqual(body.secret_refs, { password: 'secret://workspace/pg' });
  assert.equal(JSON.stringify(body).includes('never-send-me'), false);
});
test('generated form rejects malformed JSON, out-of-range ports and wrong-scope references', () => {
  for (const fields of [{ port: '5432', policy: 'invalid' }, { port: 70000 }, { port: 1.1 }]) assert.throws(() => connectionPayload(profile, 'ERP', fields, { password: 'secret://workspace/pg' }, 'read', [], []));
  assert.throws(() => connectionPayload(profile, 'ERP', { port: 5432 }, { password: 'secret://user/other/pg' }, 'read', [], []));
  assert.throws(() => connectionPayload(profile, 'ERP', { port: 5432 }, {}, 'read', [], []));
});
test('conditional required credential follows the declared profile condition', () => {
  const parameter = { ...profile.parameters[1], when: { demo_mode: [false] } };
  assert.equal(parameterEnabled(parameter, { demo_mode: true }), false);
  assert.equal(parameterEnabled(parameter, { demo_mode: false }), true);
});
