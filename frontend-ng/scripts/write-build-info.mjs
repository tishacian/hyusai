import { writeFileSync } from 'node:fs';

const raw = process.env.AGENTIUM_IMAGE_REVISION || process.env.CI_COMMIT_SHA || 'development';
const revision = raw.trim().toLowerCase();
const revisionVerified = /^[0-9a-f]{40}$/.test(revision);

if (process.env.CI && !revisionVerified) {
  throw new Error('AGENTIUM_IMAGE_REVISION must be the full 40-character commit SHA in CI');
}

writeFileSync(
  new URL('../src/build-info.json', import.meta.url),
  `${JSON.stringify({ service: 'frontend', revision, revision_verified: revisionVerified }, null, 2)}\n`,
  'utf8',
);
