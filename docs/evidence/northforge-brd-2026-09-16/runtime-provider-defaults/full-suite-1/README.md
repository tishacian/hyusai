# NorthForge — first complete suite with provider defaults

Application release: `7951e698`; recorder: `946482bd`. Unedited generation-14
candidate, canonical local engine with isolated database, real configured Showcase
provider and retrieval. Runtime generation options are left to provider defaults.
This is not a production Run or a user acceptance session.

All five cases completed; generated assertions and exact requested review status
passed. Pytest: **1 passed in 455.10 seconds**. Reviews were performed by the test
harness, including the explicit rejection case, not by human participants.

| Case | Seconds | Reviewed result |
|---|---:|---|
| Notice limit | 77.74 | 700 bar continuous; 735 bar relief threshold distinguished |
| NF-04 history | 74.80 | 30 minutes planned, 55 actual; history selected |
| Missing equipment/cause | 83.88 | Explicit absence; no inferred equipment |
| Mutation refusal | 133.98 | Read-only sources consulted; no change or closure claimed |
| Review rejection | 82.27 | Prepared briefing retained; decision status rejected |

Pressure questions select notices, history questions select history; mutation
refusal consults both. Source document identities in the answers match the actual
retrieval evidence retained in results.json. No assertion was changed after execution.
The generated lexical assertions alone do not establish semantic quality.

Limits: citation syntax varies (filename/document, chunk/document, fragment).
Clickable source navigation is not qualified by this record. The history answer
labels a dataset warning “Operating Notice”, which is misleading terminology.
The last answer claims no derating conditions were supplied; this is limited to
retrieved evidence, not an exhaustive statement about the corpus.

This is **one** successful suite, not five consecutive repetitions. Production
execution, human review, second-user consumption, published-version retention,
and an unprepared case remain required.

## Publication and access regression gate

On application code `7951e698` (documentation HEAD `d83fec8b`), the existing
BRD import, Flow publication and Experience authorization suites passed:
**45 passed in 4.05 seconds**. Command, from backend:

```sh
python -m pytest app/tests/api/test_workspace_skill_brd_import.py app/tests/api/test_flow_publication_api.py app/tests/api/test_experience_authorization.py -q
```

These checks cover server-owned BRD origin frozen in publication and Runs,
immutable published Flow snapshots, rerun attribution, and separation between
Experience view/edit/release/deploy permissions. They use isolated test data.
They do not demonstrate a second person consuming this generated NorthForge
application, nor browser source navigation. Those acceptance items remain open.
