import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { automationJobLines, jobLineText, type AutomationJobView } from './automation-job';

const approved: AutomationJobView['convention'] = {
  status: 'approved',
  value_per_unit: 6,
  currency: 'EUR',
  unit: 'PO',
  contract: {
    revision: 2,
    owner: 'buyer@example.test',
    indicator: 'completed_volume',
    indicator_unit: 'runs',
    target: 50,
    period_start: '2026-09-01',
    period_end: '2026-10-01',
    source: { kind: 'agreement', reference: 'Purchasing plan 2026' },
  },
};

function keys(view: AutomationJobView): string[] {
  return automationJobLines(view).value.map((line) => line.key);
}

test('a published automation shows its objective and names missing convention, gap and proof', () => {
  const lines = automationJobLines({
    objective: { status: 'stated', text: 'Draft the meeting minutes.' },
    convention: { status: 'absent' },
    gap: { status: 'absent' },
    proof: null,
  });
  assert.equal(lines.objective, 'Draft the meeting minutes.');
  assert.deepEqual(lines.value.map((line) => line.key), [
    'flow.automation.work.convention.absent',
    'flow.automation.work.gap.absent',
  ]);
  assert.equal(lines.proof, '');
});

test('an approved contract names its rate, owner, target, period and source', () => {
  const lines = automationJobLines({ objective: { status: 'absent' }, convention: approved, gap: { status: 'absent' }, proof: null });
  const [contract, target] = lines.value;
  assert.deepEqual(contract?.params, { rate: '6 EUR / PO', owner: 'buyer@example.test', revision: 2 });
  assert.deepEqual(target?.params, { target: '50', unit: 'runs', start: '2026-09-01', end: '2026-10-01', source: 'Purchasing plan 2026' });
  assert.deepEqual(target?.labels, { indicator: 'experience.adoption.completed_volume' });
});

test('the gap says where the period stands, never a saving', () => {
  const base = { objective: { status: 'absent' }, convention: approved, proof: null } as const;
  const measured = automationJobLines({ ...base, gap: { status: 'measured', value: 34, target: 50, delta: -16, unit: 'runs' } }).value.at(-1);
  assert.equal(measured?.key, 'flow.automation.work.gap.measured');
  assert.equal(measured?.params?.['delta'], '-16');
  const ahead = automationJobLines({ ...base, gap: { status: 'measured', value: 60, target: 50, delta: 10, unit: 'runs' } }).value.at(-1);
  assert.equal(ahead?.params?.['delta'], '+10');
  assert.equal(keys({ ...base, gap: { status: 'in_progress', value: 12, target: 50 } }).at(-1), 'flow.automation.work.gap.in_progress');
  assert.equal(keys({ ...base, gap: { status: 'not_started' } }).at(-1), 'flow.automation.work.gap.not_started');
  assert.equal(keys({ ...base, gap: { status: 'not_comparable' } }).at(-1), 'flow.automation.work.gap.not_comparable');
  for (const line of automationJobLines({ ...base, gap: { status: 'measured', value: 34, target: 50, delta: -16, unit: 'runs' } }).value) {
    assert.ok(!('saving' in (line.params ?? {})) && !('amount' in (line.params ?? {})));
  }
});

test('every value line resolves in both languages, indicator label included', () => {
  const view: AutomationJobView = { objective: { status: 'absent' }, convention: approved, gap: { status: 'in_progress', value: 12, target: 50, unit: 'runs', period_end: '2026-10-01' }, proof: null };
  for (const dict of [FLOW_EN, FLOW_FR]) {
    const t = (key: string, params?: Record<string, string | number>) => {
      const template = (dict as Record<string, string>)[key] ?? (key.startsWith('experience.adoption.') ? 'Completed Runs' : key);
      return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params?.[name] ?? `{${name}}`));
    };
    for (const line of automationJobLines(view).value) {
      const text = jobLineText(t, line);
      assert.ok(!text.includes('{') && !text.startsWith('flow.'), `${line.key} renders: ${text}`);
    }
  }
});
