# Capture collection and citation routing — correction of live def0b3cc findings

The [retained failed Run](../release-def0b3cc-2026-09-17/capture-question-failed-run.json)
26d9d307 completed but answered from an inventory rather than the actual source.
No old response, source or human decision is rewritten.

- Intent detection ignores a trailing FR/EN citation instruction while keeping
  the original question for retrieval and generation. Real inventory questions
  still use the ledger; standalone source requests are not stripped.
- An explicitly replacing Context excludes the automatic expert-fiche overlay
  and remains bounded after corpus planning. Existing System authority and
  membrane intersection take precedence. Combine/ordinary workspace behavior
  remains covered by the existing tests.
- ChatPanel names the published collection rather than uploaded session files.
  An inactive workspace default is not displayed in Only mode. Combining sources
  remains explicit. Scope-aware questions reuse the existing prompts and controls.

Local gates: **1,512 frontend tests**, **117 backend tests**, **8,077 FR/EN keys**,
nav/chrome and production build pass. Backend suite covers the whole RAG context
worker file, frozen Flow source scope, Context tenant bindings and chat session
bounding. New assertions cover the live question, FR/EN variants, inventory
preservation, planner/overlay replacement and unchanged retrieval question.
Logs are retained alongside this file.

An initial new-test collection attempt failed for a missing pytest import; fixed
before the final full run. That failed attempt is not counted as qualification.
Visual/live acceptance on the new candidate is NOT RUN yet. Repeat the retained
question from Capture in a fresh conversation, inspect 6 bar and the exact source,
then inspect the new Run. Do not relaunch or approve retained R1 Runs.
