# Planner evidence order — targeted qualification

The shared decision prompt now presents observations before the goal, allowed
catalog and decision instructions. The evidence, mandate, provider settings,
confidence floor and human gates are unchanged. This is a presentation change,
not a deterministic override of a human decision.

Unedited generation-14 candidate, canonical local engine with real provider and
Showcase retrieval: the planner selected history, recognized explicitly absent
equipment and completed with confidence 0.86. The resulting absence answer and
original assertions passed; the final review was accepted by the test harness.
This is one isolated targeted execution, not human acceptance or a full repeat.

Existing AgentLoop runtime regression tests: **18 passed**. Repeated full suites,
production Runs and user acceptance remain required before claiming reliability.

## Full-suite counterexample

The next full suite again paused for planner clarification on the absence case
after 144.86 seconds. Pressure and duration cases completed. The ordering change
has therefore not established improved reliability and was reverted before
deployment. Its targeted passing result above is retained, not generalized.
The failed case is preserved in full-suite-absence.json; the full suite subsequently ended with four completed cases and this one
clarification failure. See full-suite-outcomes.json.
