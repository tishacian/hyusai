# Outcome-card responsive refinement

The c19d30e8 live review revealed narrow readout overflow and long cost captions.
The card now uses an intrinsic grid with a 120 px minimum column, preserving all
five metrics. Short FR/EN cost labels keep the ledger compact; invocation audit
retains the calculation evidence. The override input now says declared value.
Small negative declarations preserve their inequality below display precision.

1,503 frontend tests, i18n, navigation, UI chrome and production build pass.
Backend unchanged from c19d30e8's 19 cost/provenance tests. The existing live
observability canary additionally checks each readout's width at 390 px.
The release must still record the live canary and final real browser captures.
See the existing [reference lock](../../design/brd-system-ui-reference-lock.md#run-outcome-card--17-september).
