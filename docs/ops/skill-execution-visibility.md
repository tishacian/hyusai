# Skill execution settings

The Skill detail page shows its execution binding and opens the existing editor directly at **Execution**. Saving preserves the Skill identity and uses the canonical Skill PATCH endpoint. Editing requires the server's authoring permission and workspace ownership.

The Flow inspector shows the **current Skill definition** and links to its detail page. When available, a separate expandable section shows the executor frozen into the published version, matched to the System, node and Skill. Reading either section does not change the graph. Published executions keep their frozen binding until a new publication.

Provider and prompt are stored in `Skill.executor.params.provider` and `.template`, separately from the execution timeout/retry settings. The detail page previously omitted this binding and had no edit action; the Flow inspector only exposed input mappings. No configuration migration is needed.

The wizard's dynamic options also explicitly select the saved value when a step opens. Binding only the parent select's value could leave the provider visually blank while its options were being created.

For a prompt-template executor, the model is resolved by the runtime call and provider defaults. The invocation records the model actually used. This change does not add a fixed model parameter to the executor contract.

The subsequent [LLM Portal runtime correction](llm-portal-runtime.md) adds an optional explicit model, shared workspace resolution and provider provenance. The validation below records the earlier visibility-only baseline.

## Regression checks

- Reopen a workspace Skill: provider and complete prompt are visible even when the legacy top-level `provider` is null.
- Select **Edit execution**, change provider/prompt, save and reload: both values persist and the input/output contracts remain intact.
- A reader can inspect the binding but cannot open the editor. A workspace change clears the old settings and editing state.
- Select its Flow node: current settings and the link are visible; published settings remain distinguishable. No graph write occurs.
- Local browser checks extend `16-flow-builder-authoring-contract.spec.ts` using synthetic API fixtures. Unit coverage extends the existing Skill and Flow inspector specs.

## Local validation — 15 September 2026

Based on `origin/demo/agentic` at `9c00d6de6` in branch `codex/skill-execution-visibility`. No backend change or deployment.

- Full unit suite: 1,421 passed; final focused Skill/Flow suite: 44 passed.
- `check:i18n`, `check:nav-links`, `check:ui-chrome`, production build and `git diff --check`: passed. The build retains existing dependency/style warnings.
- Two local Chromium cases: passed, including edit/reload, switching wizard steps, current versus published Flow settings, and read-only permissions.

Local UI with synthetic API fixtures: [Skill detail](../evidence/skill-execution-visibility-2026-09-15/skill-execution-detail.png), [editor](../evidence/skill-execution-visibility-2026-09-15/skill-execution-editor.png), [Flow current definition](../evidence/skill-execution-visibility-2026-09-15/skill-flow-current.png), [published comparison](../evidence/skill-execution-visibility-2026-09-15/skill-flow-execution.png).
