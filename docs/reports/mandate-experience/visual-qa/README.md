# Mandate interface — rendered QA

These are screenshots of the implemented Angular components running from a local production build. The API responses are synthetic test fixtures, not deployed Run evidence.

The 20 states cover light/dark themes, French/English, System summary, governance coverage, exact control-to-Run navigation, and 390 px layouts with missing historical evidence. The report records viewport bounds and runtime errors. Longer component exports keep the tested width and expand the capture height so the fixed application shell does not cover their content.

- [Governance, French](coverage-light-fr.png)
- [Run investigation, English](run-mandate-dark-en.png)
- [Missing historical evidence, narrow French](coverage-narrow-missing-dark-fr.png)
- [Run investigation, narrow English](run-mandate-narrow-light-en.png)
- [Machine-readable checks](visual-report.json)

Run `node e2e/qa-mandate.mjs` from `frontend-ng` against the production bundle served on port 4200. Set `BASE`, `OUT`, or `E2E_CHROMIUM_EXECUTABLE` if required. The script does not change live workspaces or Runs.
