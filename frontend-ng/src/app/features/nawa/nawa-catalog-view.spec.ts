/**
 * The catalogue must not paraphrase the customer's workbook.
 *
 * Holding the agent counts back from the default view is a line-level decision
 * taken on wording the extractor produces verbatim, and the workbook writes a
 * staffing tally and a narrative branch with the same kind of label — "Failed:
 * 10 Agents" against "Failed: If the request fails after both approvals…".
 * Every string below is copied from `assets/nawa/itsd-use-cases.json`, so a
 * rule that starts eating described branches, or that lets a headcount surface
 * in front of the client, fails here.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  businessTotals,
  isStaffingLine,
  matchesQuery,
  narrativeLines,
  serviceSummary,
  speedupLabel,
  staffingLines,
} from './nawa-catalog-view';
import type { NawaUseCase } from './nawa-itsd.model';

const TALLIES = [
  'Main Flow: 9 Agents',
  'Rejected: 7 Agents',
  'Missed: 12 Agents',
  'Failed: 10 Agents',
  'Total: 38 Agents',
  'Total: 1 Agent',
  'New Code: 4 Agents',
  'Existing Code Upgrade: 4 Agents',
  'Non-Licensed: 5 Agents',
  'Main Flow: — Agents',
  'Completed: 1',
  'Total Agents: 5',
  'Main Flow:',
];

const NARRATIVE = [
  'This automation manages the creation of email distribution groups. NAWA WE presents the Group Distribution Request options (Create, Add, Remove).',
  'Rejected: NAWA WE notifies the requester of the rejection and cancels the ticket.',
  'Missed Approval: If an approver does not respond, NAWA WE automatically sends follow-up reminders up to 7 times until a response is received.',
  'Failed: If the request fails after both approvals, the ticket is marked as Failed and assigned to an IT Engineer.',
  'Rejected / Missed Approval / Failed: Same handling as Email Group – Creation.',
  'Deactivate email accounts when usershave not logged in for 45 Days.',
];

function useCase(over: Partial<NawaUseCase> = {}): NawaUseCase {
  return {
    sr: 4,
    name: 'Email group – Creation',
    slug: 'email-group-creation',
    manual_process: '1.Requester submits a group creation request to ITSD Portal.',
    automated_process: [NARRATIVE[0], NARRATIVE[3], TALLIES[0], TALLIES[3], TALLIES[4]].join('\n'),
    agents: 38,
    monthly_volume: 12.5,
    automated_minutes: 2,
    legacy_minutes: 15,
    status: 'planned',
    route: null,
    pattern_group: 'Directory object change with dual approval',
    ...over,
  };
}

test('a staffing tally is the label plus a count and nothing else', () => {
  for (const line of TALLIES) {
    assert.equal(isStaffingLine(line), true, line);
  }
  for (const line of NARRATIVE) {
    assert.equal(isStaffingLine(line), false, line);
  }
});

test('the two readings partition the field, so nothing is lost by the toggle', () => {
  const item = useCase();
  assert.deepEqual(narrativeLines(item.automated_process), [NARRATIVE[0], NARRATIVE[3]]);
  assert.deepEqual(staffingLines(item.automated_process), [TALLIES[0], TALLIES[3], TALLIES[4]]);
});

test('the card summary is the first prose line, never a headcount', () => {
  assert.equal(serviceSummary(useCase()), NARRATIVE[0]);
  assert.equal(
    serviceSummary(useCase({ automated_process: [TALLIES[0], NARRATIVE[5]].join('\n') })),
    NARRATIVE[5],
  );
});

test('an entry the workbook left blank says nothing rather than something invented', () => {
  assert.equal(serviceSummary(useCase({ automated_process: '' })), '');
  assert.deepEqual(narrativeLines(''), []);
});

test('search reads the name and both process fields', () => {
  const item = useCase();
  assert.equal(matchesQuery(item, 'email group'), true);
  assert.equal(matchesQuery(item, 'itsd portal'), true);
  assert.equal(matchesQuery(item, 'distribution request'), true);
  assert.equal(matchesQuery(item, 'printer'), false);
  assert.equal(matchesQuery(item, ''), true);
});

test('business totals count what is listed, missing figures included as zero', () => {
  const totals = businessTotals([
    useCase({ sr: 1, agents: 2, monthly_volume: 143, status: 'live' }),
    useCase({ sr: 2, agents: 4, monthly_volume: 146.5 }),
    useCase({ sr: 34, agents: null, monthly_volume: null }),
  ]);
  assert.deepEqual(totals, { services: 3, agents: 6, monthlyVolume: 290, available: 1 });
});

test('the speed-up refuses to speak when the two columns do not support a claim', () => {
  assert.equal(speedupLabel(useCase({ legacy_minutes: 15, automated_minutes: 2 })), '~7.5× faster');
  assert.equal(speedupLabel(useCase({ legacy_minutes: 20, automated_minutes: 2 })), '~10× faster');
  assert.equal(speedupLabel(useCase({ legacy_minutes: 15, automated_minutes: 15 })), 'at parity');
  assert.equal(speedupLabel(useCase({ legacy_minutes: 2, automated_minutes: 15 })), '—');
  assert.equal(speedupLabel(useCase({ legacy_minutes: null, automated_minutes: 2 })), '—');
  assert.equal(speedupLabel(useCase({ legacy_minutes: 0, automated_minutes: 2 })), '—');
  assert.equal(
    speedupLabel(useCase({ legacy_minutes: 20160, automated_minutes: 5 })),
    '> 100× faster',
  );
});
