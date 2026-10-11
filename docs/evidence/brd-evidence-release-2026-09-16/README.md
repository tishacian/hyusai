# BRD evidence and generation corrective release

Candidate: 7951e698cb04c6c4791e7e7d7fd620e253402616, pushed on demo/agentic.
Local gates passed: 148 backend tests, 1,466 frontend tests, i18n, navigation,
UI chrome, production build. No migration or feature-default change.

Scope: compact retrieval evidence observations without removing passages;
retain the original operator question in synthesis; carry documentary constraints
to the planner; improve generator mapping feedback and explicit review verification.
Full retrieval output remains in the linked invocation. NAWA styles are unchanged.

All three images were built on omnirag-demo from the pushed clean SHA. Storage
checks passed; six application containers use 7951e698cb04. Backend/frontend are
healthy, public build-info verifies the exact revision, homepage is 200, startup
traceback/exception count is zero. Optional Giskard SDK 2.19.2 offline checks passed.
Carakai: 10 passed, 2 intentional local-fixture skips, 2.1 minutes; artifacts at
/tmp/iteration-canaries-20260916T154240Z.iZVK3n. Manual authenticated smoke remains
pending browser reconnection. Previous runtime/rollback tag: d5a02f49ae9c.

Image IDs:
- backend: sha256:78e6124e07b5c70ad54900dac4c84f57b0e1437da1ca1d469b48af08975e00ab
- worker: sha256:e644265a548e2b6c18a0b60fe85e05c64ba1e703d0be0a3b7e1875fb7b2a79f5
- frontend: sha256:2be16b94a7891fc5ceec8f867643020fd2b6e360b01d105a2ee152090b53eed6

R1 acceptance remains open: runtime-14 qualifies four generated cases locally
with real provider and retrieval, but the absence case still pauses on confidence.
Harness review is not human-user acceptance. Publication to a second user,
manual authenticated smoke and adoption sessions remain unqualified.

A subsequent recorder correction removes forced low reasoning and runtime token
limits. A targeted absence case then passes with provider defaults; the full
suite on that configuration is not yet qualified. This test-only correction is
not included in the deployed SHA and does not change production application code.

Manual Chrome recheck after deployment: the existing Operational Analysis tab
still showed the historical result 04ecd84f-b593-4821-a229-908cfcb86cad. Following
its observed Inspect this result link redirected to sign-in for that exact Run.
This confirms an expired session, not successful authenticated release smoke.
No credentials were accessed and no manual Run was launched. Reconnection remains
required; protected canaries above remain the automated UI evidence.
