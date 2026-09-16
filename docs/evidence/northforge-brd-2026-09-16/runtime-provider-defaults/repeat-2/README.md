# Repeat 2 — absence handling is not reliable yet

Unchanged generation-14 candidate and provider defaults, same canonical local
engine and real Showcase retrieval as suite 1. The pressure and NF-04 duration
cases completed (78.51s and 68.34s). The absence case paused after 112.50s.

The planner selected history, then notices. It recognized that history contains
only durations and no equipment/cause, but returned `needs_human=true`,
`exit=ask_human`, confidence 0.9, asking the user for equipment and work-order
notes. No review was supplied by the harness. This is a planner clarification,
not the required final briefing review and not a successful absence answer.

This is not a confidence-threshold failure. The common prompt and generated goal
already explicitly permit an absence report; an earlier planner rationale nevertheless
suggested escalation for missing evidence. No automatic decision override, changed
assertion, lowered threshold or regenerated answer was used to count it as a pass.

Five consecutive successful suites are **not established**. Suite 1 remains one
successful execution; the repeated absence failure is retained in absence.json.
Remaining cases of this repeat were still running when this partial record was made.
