import { DEFAULT_PALETTE, type PaletteItem } from './flow.types';

/** Governed blocks added once an automation exists. They sit beside the four
 *  primitives and do not reopen the skill catalog. */
export function automationGovernedPalette(): PaletteItem[] {
  const approval = DEFAULT_PALETTE.find((item) => item.kind === 'hitl');
  if (!approval) return [];
  return [
    {
      ...approval,
      label: 'Approval',
      description: 'Named human decision. A later write stays sealed until this person decides.',
      outputs: [
        ...(approval.outputs ?? []),
        { name: 'decided_by', schema: 'string' },
      ],
    },
    {
      type: 'skill',
      kind: 'task',
      label: 'Retrieve',
      description: 'Returns the cited passage and the original it came from.',
      icon: 'file-search',
      tone: 'cyan',
      inputs: [{ name: 'query', schema: 'string' }],
      outputs: [
        { name: 'passage', schema: 'string' },
        { name: 'source', schema: 'string' },
      ],
      config: {
        skill_slug: 'semantic_search_v1',
        skill_category: 'Retrieval',
        inputs_map: { query: 'run.transcript' },
        outputs_map: {},
      },
    },
    {
      type: 'skill',
      kind: 'task',
      label: 'SAP write',
      description: 'Purchase-order write. It stays sealed unless Approval.decided_by is a person.',
      icon: 'shield',
      tone: 'rose',
      inputs: [
        { name: 'pr_id', schema: 'string' },
        { name: 'decided_by', schema: 'string' },
      ],
      outputs: [
        { name: 'sealed', schema: 'boolean' },
        { name: 'po_number', schema: 'string' },
        { name: 'rolled_back', schema: 'boolean' },
      ],
      config: {
        skill_slug: 'sap_create_po_v1',
        skill_category: 'Connections',
        inputs_map: {},
        outputs_map: {},
      },
    },
  ];
}
