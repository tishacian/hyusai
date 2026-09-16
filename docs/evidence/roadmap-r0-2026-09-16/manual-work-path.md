# Manual Work → Run check

Date: 2026-09-16. Runtime: e09bde5c3072f406f8f47a8f41be93f2b6bc8323.
Workspace: Agentium Showcase. Chrome, authenticated operator.

1. Opened `/work/operational-analysis`.
2. Clicked **Analyze the example** once, after the five API runs completed.
3. Observed **Completed**, Orders **4**, Net overrun **35**, Late orders **3**,
   and the model explanation identifying **NF-04 +25 minutes**.
4. Clicked **Inspect this result**.
5. The page opened `/runs/852223ad-f518-4972-ba4e-36791588641e`, the exact
   identifier from the result link, with two Python operations and one LLM
   operation. Effective provider: OpenAI; model: gpt-5-2025-08-07.

This is an agent-assisted manual check, not an independent user trial.
The UI was English and the generated explanation French. The investigation
had no semantic evaluation; the legacy summary's approved/100% is not human
validation. No approval or value override was performed.
