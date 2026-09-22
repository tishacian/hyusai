export interface AutomationJobView {
  objective: { status?: string; text?: string | null };
  convention: { status?: string; value_per_unit?: number | null; currency?: string | null; unit?: string | null };
  gap: { status?: string };
  proof: { run_id?: string; status?: string; sap?: { sealed?: boolean; called?: boolean } | null } | null;
}

/** The four lines a portfolio review may show. Absences stay absences. */
export function automationJobLines(view: AutomationJobView): {
  objective: string;
  convention: string;
  gap: string;
  proof: string;
} {
  const objective = view.objective.status === 'stated' && view.objective.text
    ? view.objective.text
    : '';
  const convention = view.convention.status === 'declared' || view.convention.status === 'measured'
    ? `${view.convention.value_per_unit ?? ''} ${view.convention.currency ?? ''} / ${view.convention.unit ?? ''}`.trim()
    : '';
  const proof = view.proof?.run_id
    ? view.proof.run_id
    : '';
  return {
    objective,
    convention,
    gap: view.gap.status === 'absent' ? '' : view.gap.status ?? '',
    proof,
  };
}
