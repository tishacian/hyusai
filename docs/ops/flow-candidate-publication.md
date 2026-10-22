# Publish a reviewed Flow without replacing the saved draft

A release may need a small change to the currently published Flow while a
builder has unrelated, unfinished work in the server draft. The candidate
publication API reviews and publishes an explicit graph without saving it as
that draft. It applies to any System; it has no demo-specific behavior.

The regular builder path remains `PUT /flow-draft` followed by
`POST /flow/publish`. Do not temporarily replace a user's draft and restore it
after publication: the candidate path preserves it throughout the operation.

## Review and publish

All paths below start with `/api/v1/systems/{system_id}` and use the same
workspace-scoped `system.admin` / `flow_publish` authority as normal publication.
No migration or new feature flag is required.

1. Read `GET /flow-state` and the currently published immutable version. Keep
   its version ID and the saved draft revision/hash. Construct a separate
   candidate from the published graph.
2. Submit `POST /flow/review-candidate` with:

   ```json
   {
     "flow_definition": {"schema_version": 3, "nodes": [], "edges": []},
     "expected_flow_sha256": "<canonical candidate SHA-256>",
     "expected_draft_revision": 38,
     "expected_draft_flow_sha256": "<saved draft SHA-256>",
     "expected_published_version_id": "<current immutable version ID>"
   }
   ```

   The graph above is a shape illustration, not an executable example. Hash
   with the canonical Flow serializer, not the byte formatting of a JSON file.
   Review validates the entire candidate DAG, authorized Skills, resources,
   ingress/output contracts and mandate. It returns the secret-free semantic
   `diff`, `breaking_change_intent_required`, and these candidate digests:

   - `candidate.flow_sha256` identifies the submitted graph;
   - `candidate.execution_contract_sha256` identifies its compiled contracts;
   - `candidate.control_policy_snapshot_sha256` identifies its inherited mandate;
   - `candidate.review_sha256` binds the System, current publication, preserved
     draft revision/hash, candidate graph hash and execution-contract hash.

   Review is read-only and releases its database locks before responding. It
   creates neither a draft revision nor a version, and makes no provider call.
3. Submit `POST /flow/publish-candidate` with the **same** five request fields,
   plus `message`, `expected_execution_contract_sha256` and
   `expected_review_sha256` copied from that review. Include
   `breaking_change_intent: "acknowledged"` when the reviewed diff requires it.

Publication locks System then draft, rechecks both concurrency bases and both
review digests, and recompiles the candidate before appending an immutable
version. It updates the normal published pointer/mirror in the same transaction.
The System's active/paused status is preserved. An equivalent current graph and
contract is a no-op; a changed catalog contract still receives a new version.

The mandate is inherited from the **current published contract**, with the
existing explicitly identified policy fallback for legacy publications. An
unfinished draft mandate is not used. Caller-provided policy overrides are
rejected. New mandate edits continue to use the regular draft review/publication
workflow.

## Evidence and concurrency

Success returns the standard `published` and `draft` payloads plus
`draft_preserved: true`. The nested draft's `no_op` is true even when a new
publication was created. Every saved draft column remains unchanged, including
its graph, revision, mandate, base-publication pointer, author and timestamps.
An unfinished draft is not required to compile before publishing the candidate.

The new version has `release_kind: "publish"` and `draft_revision: null`, because
the candidate was never the user's draft. The `flow.published` audit entry
records `publication_source: "candidate"`, the previous publication ID and the
preserved draft's revision/hash. The draft's historical base remains protected
by version retention.

Stale revisions, graph hashes, publication IDs or review hashes fail without a
partial publication. A competing successful publisher makes the old request
stale. After an uncertain response, reread state and compare the published graph
and contract before deciding whether a new review is needed; do not retry with
invented replacement preconditions.

## Work application rollout and recovery

Candidate publication does not automatically retarget ordinary System bindings
or deploy a Work release. Existing deployed releases retain their immutable
binding snapshots. Mutable bindings pinned to the old publication report drift
and must be reviewed before creating a new release. The established seed-stub
binding reconciliation still applies, as with regular publication.

After updating the reviewed binding pins, choose the appropriate release path.
If the Work draft itself is ready to ship, use its ordinary ready-check and
release creation with revision/content/binding hashes. To keep unrelated Work
draft edits unpublished, use the existing deployed release as the source:

1. `GET /api/v1/experiences/{id}/releases/{source_release_id}/rebind-ready-check`
   validates its immutable content against the current bindings. Review blockers,
   warnings and the returned source and binding hashes.
2. `POST /api/v1/experiences/{id}/releases/{source_release_id}/rebind` with `notes`,
   `expected_source_release_sha256`, `expected_content_sha256`,
   `expected_experience_updated_at` and `expected_bindings_sha256` from that review
   creates a new release. It preserves the source's pages, content hash, identity,
   audience, languages, theme and renderer version. It leaves every draft field
   and deployment unchanged. The regular release permission applies, and the
   audit records the source release and preservation of the draft.
3. Deploy the resulting release with the existing current-release/timestamp
   preconditions. An identical rebind retry returns its original release; it
   does not automatically redeploy it.

Binding patches and workspace settings writes are separate transactions and
currently have no revision CAS; read them immediately before mutation and stop
on concurrent changes. Preserve unrelated Flow and Work drafts throughout.

To restore the previous graph while preserving a draft, submit that graph as a
**new candidate**, review it against the now-current publication and publish a
new immutable version. This recompiles current callable contracts and inherits
the current published mandate; it does not pretend to restore historical catalog
or policy state. A Work deployment can instead be rolled back to its previous
immutable release with the existing deployment rollback endpoint. Neither action
rewrites version history or silently restores a user's draft.
