# BRD → System panel — local visual qualification

16 September 2026. Actual `BrdSystemProposalComponent`, rendered with Angular and
Cockpit styles in fresh headless Chrome. The API responses and PIH proposal in
these images are controlled fixtures, not deployed or model-generated results.

Matrix: French/English × light/dark × 1280/390/320 px. The capture check rejects
horizontal page overflow, browser exceptions and an enabled draft-creation action
before explicit review. Desktop French light and mobile English dark were
visually inspected; the empty coverage separator was removed and warning copy
uses the primary foreground with a semantic border for contrast.

[Desktop FR light](fr-light-1280.png) · [Mobile EN dark](en-dark-390.png)

The fixture covers the proposed/uncovered review state. Full live integration,
provider failures, original-file download, persisted job recovery and successful
Flow navigation remain in the release acceptance, beyond this visual matrix.

References and design decisions: [reference lock](../../design/brd-system-ui-reference-lock.md).
