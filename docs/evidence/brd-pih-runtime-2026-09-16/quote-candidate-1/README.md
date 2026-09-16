# New PIH candidate with exact-quote checks

Generated using local candidate `fa85bbfa` and the configured live Showcase
provider, via the existing opt-in canonical generation-worker test. Generation
passed in 60.96 seconds. The three-stage canonical DAG then executed the three
unaltered generated cases in 98.57 seconds; all proposed assertions passed.
An additional diagnostic examined 7, 5 and 5 quotes and found every one in its
case's original text. The missing-field case preserves the literal supplied
`[No grade specified]`; the injection case returns documentary facts without
an HR decision.

Only the nominal generated case includes the quote check in its frozen suite.
The other two checks are explicitly separate diagnostics, not retroactive
changes to the generated criteria. One three-case attempt does not establish
five consecutive successes, unprepared-case robustness or complete coverage.

Provider calls are real, but Run objects use an isolated local database. HITL
acceptance is performed by the test harness, not a participant. The deployed
Showcase still serves f63f1eaf and retains the previous pending live Runs.
