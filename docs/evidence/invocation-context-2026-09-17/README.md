# Preserve invocation ancestry — 17 September 2026

Follow-up to the manual finding on runtime 970f4512. The shared navigation
resolver now derives the invocation leaf from the canonical Run's readable
invocation list, without requesting a 360-gated endpoint. The parent Run is the
server-owned membership proof. A missing/filtered invocation still clears the
ancestry; query-supplied parents do not establish access.

All 1,497 frontend tests pass, including navigation with no 360 endpoint and
missing invocation membership. i18n, links, chrome and production build pass.
The existing live observability canary additionally checks the Run breadcrumb.
Backend unchanged from the 16 targeted tests recorded with 970f4512.
Runtime verification is pending at this commit.
