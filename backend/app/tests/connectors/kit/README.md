# Connector certification kit — C0 contract

This directory currently validates the pure evidence contract in
`app.services.connectors.certification`. It contains **unit fixtures only**.
It does not connect to a database, deploy a bench, revoke a credential or
qualify any connector.

Run from `backend`:

```sh
python -m pytest -q app/tests/connectors/kit/test_certification_contract.py
```

Future bench adapters must execute every suite returned by `required_suites`
for the exact declared capabilities. An unsupported operation requires a
passing refusal test; it is not a skipped write test. File export has its own
capability and outcome checks. Failed and skipped required tests prevent
verification.

Bundles carry exact component identities, server version, environment, source
revision, UTC-aware completion time and report digests. A changed component
requires a new suite. Certification additionally requires a recent real canary
and revocation test for the specified deployed environment. Emulator evidence
can verify an applicable profile, but never supplies that live canary. SAP HANA
requires a real instance; its Showcase demo fallback cannot qualify it.

The SHA256 is an integrity check, **not proof of origin**. Before using the pure
decision function, a future authoritative reader must authenticate the producer,
verify the referenced report bytes and load current deployment identities. There
is no evidence upload endpoint, persistence, seed, profile fixture registration
or frontend badge feed in C0. The bench host/runner remains an operator decision.
