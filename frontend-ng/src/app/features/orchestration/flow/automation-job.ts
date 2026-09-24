export interface AutomationContractView {
  revision?: number;
  owner?: string | null;
  indicator?: string;
  indicator_unit?: string;
  target?: number;
  period_start?: string;
  period_end?: string;
  source?: { kind?: string; reference?: string } | null;
}

export interface AutomationGapView {
  status?: string;
  value?: number | null;
  target?: number;
  delta?: number;
  unit?: string;
  period_start?: string;
  period_end?: string;
}

export interface AutomationJobView {
  objective: { status?: string; text?: string | null };
  convention: {
    status?: string;
    value_per_unit?: number | null;
    currency?: string | null;
    unit?: string | null;
    contract?: AutomationContractView | null;
  };
  gap: AutomationGapView;
  proof: { run_id?: string; status?: string; sap?: { sealed?: boolean; called?: boolean } | null } | null;
}

/**
 * One translatable line. `labels` names params whose value is itself a
 * dictionary key (an indicator), translated before the line is.
 */
export interface JobLine {
  key: string;
  params?: Record<string, string | number>;
  labels?: Record<string, string>;
}

function amount(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '';
  return String(Math.round(value * 100) / 100);
}

function signed(value: number | null | undefined): string {
  const shown = amount(value);
  return typeof value === 'number' && value > 0 ? `+${shown}` : shown;
}

function rate(view: AutomationJobView['convention']): string {
  return `${view.value_per_unit ?? ''} ${view.currency ?? ''} / ${view.unit ?? ''}`.trim();
}

export function gapLine(gap: AutomationGapView): JobLine {
  const params = {
    value: amount(gap.value),
    target: amount(gap.target),
    delta: signed(gap.delta),
    unit: gap.unit ?? '',
    start: gap.period_start ?? '',
    end: gap.period_end ?? '',
  };
  switch (gap.status) {
    case 'measured':
      return { key: 'flow.automation.work.gap.measured', params };
    case 'in_progress':
      return { key: 'flow.automation.work.gap.in_progress', params };
    case 'not_started':
      return { key: 'flow.automation.work.gap.not_started', params };
    case 'not_comparable':
      return { key: 'flow.automation.work.gap.not_comparable', params };
    default:
      return { key: 'flow.automation.work.gap.absent' };
  }
}

/**
 * What a portfolio review may show. The value lines come from the approved
 * value contract: its convention and owner, its target and period, then the
 * measured gap. Absences stay absences, and a gap is never a saving.
 */
export function automationJobLines(view: AutomationJobView): {
  objective: string;
  value: JobLine[];
  proof: string;
} {
  const objective = view.objective.status === 'stated' && view.objective.text
    ? view.objective.text
    : '';
  const proof = view.proof?.run_id ? view.proof.run_id : '';
  const contract = view.convention.contract;
  const value: JobLine[] = [];
  if (view.convention.status === 'approved' && contract) {
    value.push({
      key: 'flow.automation.work.contract',
      params: { rate: rate(view.convention), owner: contract.owner ?? '', revision: contract.revision ?? '' },
    });
    value.push({
      key: 'flow.automation.work.target',
      params: {
        target: amount(contract.target),
        unit: contract.indicator_unit ?? '',
        start: contract.period_start ?? '',
        end: contract.period_end ?? '',
        source: contract.source?.reference ?? '',
      },
      labels: { indicator: `experience.adoption.${contract.indicator ?? ''}` },
    });
  } else if (view.convention.status === 'declared' || view.convention.status === 'measured') {
    value.push({ key: 'flow.automation.work.convention', params: { rate: rate(view.convention) } });
  } else {
    value.push({ key: 'flow.automation.work.convention.absent' });
  }
  value.push(gapLine(view.gap ?? {}));
  return { objective, value, proof };
}

export function jobLineText(
  t: (key: string, params?: Record<string, string | number>) => string,
  line: JobLine,
): string {
  const params: Record<string, string | number> = { ...(line.params ?? {}) };
  for (const [name, key] of Object.entries(line.labels ?? {})) params[name] = t(key);
  return t(line.key, params);
}
