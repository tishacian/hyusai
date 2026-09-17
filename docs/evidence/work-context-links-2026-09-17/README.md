# Work and System navigation — preserve query context

The [live 447997ee smoke](../release-447997ee-2026-09-17/README.md) reproduced
“Experience not found” after Work → Edit application. Angular RouterLink treated
the entire URL string as a path command, encoding `?pageId=…&returnTo=…&releaseId=…`
into the application ID. System pipeline-stage links had the same failure.

Work now returns an Angular UrlTree through the existing Router. Pipeline stages
use the existing navigation service's surfaceUrlTree/leafUrlTree. No permissions,
branding, route identifiers or release objects change. Both Work edit/repair and
both System stage displays share their corrected producer.

[Work regression](focused.log) verifies the ID, page, return path and immutable
release context. [System regression](system-focused.log) covers RAG, translation
and Capture stage destinations. The existing Work canary additionally follows a
visible editor link and verifies it resolves; absent standard applications or
editing permission are reported explicitly rather than claimed as coverage.

[Full frontend](frontend.log): 1,495 passed. [FR/EN](i18n.log), [navigation](nav.log),
[chrome](chrome.log), [production build](build.log): passed. Backend code is
unchanged from the 318-test qualified 447997ee release. Live deployment and
post-fix browser verification remain to be recorded.
