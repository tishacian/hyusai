# Neutral corpora for the blank-workspace test (plan lot 4, test 71)

Two synthetic sets of three internal procedures each. They name no customer,
product or real organisation. `procedures-a` is French, `procedures-b` is
English, with different document names, so the test can be replayed on a
second corpus without changing code (`E2E_BLANK_CORPUS=procedures-b`).

Each set has a `scenario.json` with a question the documents answer, the
document that answers it, and a question they do not cover (abstention).
