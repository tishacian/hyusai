import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  agePhrase,
  homeQueue,
  homeReviewPhrase,
  homeTiles,
  homeTitle,
  homeWaitingTotal,
  isPrToPoDecision,
  receiptPhrases,
  type WorkHome,
} from './work-home.vm';

const NOW = Date.parse('2026-09-29T12:00:00Z');

test('automatic review notices preserve the observed score and localise its number', () => {
  assert.deepEqual(homeReviewPhrase('Run has high hallucination rate (33.3%)', 'fr'), {
    key: 'experience.work.home.review.hallucination', params: { rate: '33,3' },
  });
  assert.deepEqual(homeReviewPhrase('Run has high hallucination rate (33.3%)', 'en'), {
    key: 'experience.work.home.review.hallucination', params: { rate: '33.3' },
  });
  assert.deepEqual(homeReviewPhrase('Run below composite threshold (69/100)', 'fr'), {
    key: 'experience.work.home.review.quality', params: { score: '69' },
  });
  assert.deepEqual(homeReviewPhrase('Run flagged for review', 'fr'), {
    key: 'experience.work.home.review.flagged',
  });
});

test('custom, partial and invalid notices do not acquire an invented quality claim', () => {
  for (const title of [null, 'Compléter le grade', 'Run below composite threshold (69/100) — draft',
    'Run has high hallucination rate (101%)', 'Run has high hallucination rate (-1%)',
    'Run has high hallucination rate (unknown%)']) {
    assert.equal(homeReviewPhrase(title, 'fr'), null, title ?? 'missing title');
  }
});
const app = { kind: 'app', slug: 'pr-to-po', name: 'PR to PO' };
const automation = { kind: 'automation', system_id: 'sys-1', name: 'Nightly check' };

function home(over: Partial<WorkHome> = {}): WorkHome {
  return {
    window_days: 7,
    decisions: {
      count: 2,
      oldest_at: '2026-09-29T08:00:00',
      items: [
        { run_id: 'new', title: 'Newer', started_at: '2026-09-29T11:00:00', source: app },
        { run_id: 'old', title: 'Valider la commande ATEX Services', started_at: '2026-09-29T08:00:00', source: app },
      ],
    },
    reviews: {
      count: 1,
      oldest_at: '2026-09-28T12:00:00',
      items: [{ decision_id: 'rev-1', run_id: 'run-r', title: 'Compléter le grade', created_at: '2026-09-28T12:00:00' }],
    },
    results: {
      items: [
        { run_id: 'res-a', completed_at: '2026-09-27T12:00:00', source: automation },
        { run_id: 'res-b', completed_at: '2026-09-29T10:00:00', source: automation },
      ],
    },
    agent_work: { items: [] },
    ...over,
  };
}

test('priority: decisions oldest first, then reviews, then newest results', () => {
  const queue = homeQueue(home());
  assert.deepEqual(queue.map((item) => item.id), [
    'decision:old',
    'decision:new',
    'review:rev-1',
    'result:res-b',
    'result:res-a',
  ]);
  assert.deepEqual(queue[0]!.target, { kind: 'work', url: '/work/pr-to-po/validations' });
  assert.deepEqual(queue[2]!.target, { kind: 'review', decisionId: 'rev-1' });
  assert.deepEqual(queue[3]!.target, { kind: 'work', url: '/work/automation/sys-1' });
  assert.equal(isPrToPoDecision(queue[0]!), true);
  assert.equal(isPrToPoDecision(queue[2]!), false);
});

test('a decision without a known stamp goes after dated ones', () => {
  const queue = homeQueue(home({
    decisions: { count: 2, items: [
      { run_id: 'undated', source: app },
      { run_id: 'dated', started_at: '2026-09-29T09:00:00', source: app },
    ] },
    reviews: null,
    results: null,
  }));
  assert.deepEqual(queue.map((item) => item.runId), ['dated', 'undated']);
});

test('H1 wording for 0, 1 and n', () => {
  assert.equal(homeTitle(0), null);
  assert.deepEqual(homeTitle(1), { key: 'experience.work.home.title.one' });
  assert.deepEqual(homeTitle(5), { key: 'experience.work.home.title.many', params: { n: 5 } });
  assert.equal(homeWaitingTotal(home()), 5);
  // A server total beyond the listed page still counts.
  assert.equal(homeWaitingTotal(home({ decisions: { count: 14, items: [] }, reviews: null, results: null })), 14);
  assert.equal(homeWaitingTotal(null), 0);
});

test('tiles: reviews hidden when unknown, apps hidden without the catalogue, one emphasis', () => {
  const data = home({ reviews: null });
  const queue = homeQueue(data);
  const tiles = homeTiles(data, null, queue, NOW);
  assert.deepEqual(tiles.map((tile) => tile.id), ['decisions']);
  assert.equal(tiles[0]!.emphasis, true);
  assert.deepEqual(tiles[0]!.noteAge, { key: 'experience.work.home.age.hours', params: { n: 4 } });

  assert.deepEqual(homeTiles(null, { total: 5, live: 4, pilot: 1 }, [], NOW).map((tile) => tile.id), ['apps']);

  const calm = home({ decisions: { count: 0, items: [] }, results: null });
  const calmTiles = homeTiles(calm, { total: 5, live: 4, pilot: 1 }, homeQueue(calm), NOW);
  assert.deepEqual(calmTiles.map((tile) => [tile.id, tile.emphasis]), [
    ['decisions', false],
    ['reviews', true],
    ['apps', false],
  ]);
  assert.equal(calmTiles[0]!.target, null);
  assert.deepEqual(calmTiles[0]!.note, { key: 'experience.work.home.tile.decisions.none' });
  assert.deepEqual(calmTiles[0]!.label, { key: 'experience.work.home.tile.decisions.zero' });
  assert.deepEqual(calmTiles[1]!.label, { key: 'experience.work.home.tile.reviews.one' });
  assert.equal(calmTiles.filter((tile) => tile.emphasis).length, 1);
});

test('tile omits the oldest line when the stamp is unknown', () => {
  const data = home({ decisions: { count: 1, oldest_at: null, items: [{ run_id: 'x', source: app }] } });
  const [decisions] = homeTiles(data, null, homeQueue(data), NOW);
  assert.equal(decisions!.note, null);
  assert.equal(decisions!.noteAge, null);
});

test('receipt line per item type keeps only measured parts', () => {
  const pr = receiptPhrases({ steps: 8, agent_ms: 18_000, write: 'sealed' }, 'fr');
  assert.deepEqual(pr, [
    { key: 'experience.work.home.receipt.steps.many', params: { n: 8 } },
    { key: 'experience.work.home.receipt.duration', params: { value: '18 s' } },
    { key: 'experience.work.home.receipt.write.sealed' },
  ]);
  const knowledge = receiptPhrases({ steps: null, agent_ms: null, passages_read: 3, passages_cited: 1 }, 'en');
  assert.deepEqual(knowledge, [
    { key: 'experience.work.home.receipt.read.many', params: { n: 3 } },
    { key: 'experience.work.home.receipt.cited.one', params: { n: 1 } },
  ]);
  assert.deepEqual(receiptPhrases({ steps: 1, write: 'done' }, 'en'), [
    { key: 'experience.work.home.receipt.steps.one', params: { n: 1 } },
    { key: 'experience.work.home.receipt.write.done' },
  ]);
  assert.deepEqual(receiptPhrases(null, 'fr'), []);
});

test('ages', () => {
  assert.equal(agePhrase(null, NOW), null);
  assert.deepEqual(agePhrase('2026-09-29T11:59:30', NOW), { key: 'experience.work.home.age.now' });
  assert.deepEqual(agePhrase('2026-09-29T11:15:00Z', NOW), { key: 'experience.work.home.age.minutes', params: { n: 45 } });
  assert.deepEqual(agePhrase('2026-09-26T12:00:00', NOW), { key: 'experience.work.home.age.days', params: { n: 3 } });
});
