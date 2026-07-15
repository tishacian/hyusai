import assert from 'node:assert/strict';
import test from 'node:test';
import {
  resolveSigninExperience,
  SIGNIN_EXPERIENCE_QUERY_PARAM,
} from './signin-experience';

function params(values: Record<string, string | null>) {
  return { get: (name: string) => values[name] ?? null };
}

test('signin presentation is selected by the explicit experience contract', () => {
  const experience = resolveSigninExperience(params({
    [SIGNIN_EXPERIENCE_QUERY_PARAM]: 'sentinel_government_v1',
  }));

  assert.equal(experience.profile, 'sentinel_government_v1');
  assert.equal(experience.source, 'explicit_profile');
  assert.equal(experience.title, 'Hyperviseur souverain SENTINEL-CI');
  assert.equal(experience.submitLabel, 'CONNEXION VPM');
});

test('legacy Sentinel workspace links keep the same presentation without component slug logic', () => {
  const experience = resolveSigninExperience(params({ workspace: 'sentinel-ci', demo: 'true' }));

  assert.equal(experience.profile, 'sentinel_government_v1');
  assert.equal(experience.source, 'legacy_workspace_alias');
  assert.equal(experience.prefillEmail, 'vp.demo@sentinel-ci.local');
  assert.match(experience.securityBand || '', /Athea/);
});

test('unknown profile fails closed to standard and cannot reactivate a legacy alias', () => {
  const experience = resolveSigninExperience(params({
    experience: 'future-untrusted-profile',
    workspace: 'sentinel-ci',
  }));

  assert.equal(experience.profile, 'standard');
  assert.equal(experience.source, 'default');
  assert.equal(experience.securityBand, null);
  assert.equal(experience.submitLabel, 'SIGN IN');
});

test('historical demo-only link preserves its prefilled account', () => {
  const experience = resolveSigninExperience(params({ demo: 'true' }));

  assert.equal(experience.profile, 'standard');
  assert.equal(experience.prefillEmail, 'vp.demo@sentinel-ci.local');
});
