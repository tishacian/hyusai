# Offline bundles and physical purge

The backend exposes these endpoints below `/api/v1/huggingface`. Workspace
administrators control their deployments and offline bundles. Only platform
administrators can request a global physical purge.

## Preparation services

Mount the same protected data-disk directory as `HF_BUNDLE_SPOOL_DIR`
(`/data/hub-bundles` by default) in the API, `hub-fetch` worker and tabular
worker. Those processes need a shared service UID or equivalent restricted
group permissions. Inference processes do not mount the spool. The artifact
cache remains a separate read-only mount in the API and inference workers.

Model bundle jobs run on `hub_fetch` with the dedicated Hub object identity.
Dataset bundles run on the tabular worker with its tabular identity; they move
only the retained Parquet result. No bundle job contacts the Hub during import.
The preparation scheduler recovers undispatched jobs and removes failed,
cancelled or expired spool data while respecting worker locks.

The following deployment variables configure offline trust:

| Variable | Purpose |
| --- | --- |
| `HF_BUNDLE_TRUST_KEYS_JSON` | JSON object mapping exporter key IDs to Ed25519 public keys, in PEM or base64-encoded raw form. Required in API and import workers. |
| `HF_BUNDLE_SIGNING_KEY_PATH` | Mounted private Ed25519 key file, PEM or raw bytes. Required only by export workers. |
| `HF_BUNDLE_SIGNING_KEY_ID` | Exporter ID matching a configured trust entry on the isolated installation. |
| `HF_BUNDLE_SPOOL_DIR` | Shared bounded temporary spool, separate from model runtime mounts. |

Key files are operator-provisioned secrets. The API never returns private keys
and no key is embedded in a bundle. Every bundle, including a public repository,
is signed so that access flags and license metadata cannot be changed to bypass
policy. The signed proof binds the complete immutable manifest, artifact ID,
target workspace ID, license evidence digest, issue time and expiry. The target
workspace ID must match the isolated installation's workspace.

## Export and import

`POST /artifacts/{id}/bundles` accepts `{"expiry_seconds":86400}` and returns
`job_id`. The maximum HTTP export validity is one day. Current grant and license
policy are checked again on the worker. For private/gated repositories, export
also proves access using the target workspace's own Hub connection; a platform
fallback token is insufficient. Download the completed bundle through
`GET /bundle-jobs/{job_id}/download`; the backend checks access and expiry again.

`POST /bundles` receives the raw uncompressed `.tar` bytes with a bounded
`Content-Length`, for example `Content-Type: application/x-tar`. Multipart and
compressed archives are not part of this endpoint contract. It streams into
the spool with physical disk checks, verifies signed metadata, then dispatches
to the appropriate preparation worker. The worker verifies each declared size
and SHA-256, validates the source selection, publishes immutable objects and
manifest, then grants access. Uploaded storage keys are never trusted as local
destinations. Models accept the same safe file types and configuration rules as
online import; datasets retain their signed result and original selection.

If the signed license requires explicit acceptance, the response has
`stage: "license_required"` and includes the license tag, text and digest.
`GET /bundle-jobs/{id}` can recover that signed text after a reload.
`POST /bundle-jobs/{id}/accept-license` records the workspace administrator's
acceptance and dispatches the import. This path works without the Hub. A blocked
license still requires a platform policy exception; an exporter signature does
not override the effective license policy.

`GET /jobs/{id}` and `GET /bundle-jobs/{id}` expose progress. Cancellation of a
bundle uses `POST /bundle-jobs/{id}/cancel`. Publication checks the current job
state, actor permission, proof freshness and policy before creating a grant.

## Physical purge

`POST /artifacts/{id}/purge` creates a preparation-worker job. It requires prior
global revocation. Catalogue references, active workspace authorizations,
runtime usages and unexpired leases block deletion. Shared file references are
kept, including pending imports. Nodes must confirm that stopped deployments'
copies have been removed; a timeout, a missing node or a plain stop response is
insufficient proof. Local cache removal uses the cache's exclusive lease lock.

S3 buckets may be versioned. Deletion removes the exact retained key's versions
and delete markers before recording a receipt, without touching sibling keys.
Dataset results live outside the Hub writer prefix, so their physical deletion
uses a separate narrow capability:

- `HF_TABULAR_DELETE_ACCESS_KEY`
- `HF_TABULAR_DELETE_SECRET_KEY`

This identity needs object/version deletion only for
`workspaces/*/tabular/hub-artifacts/*/result.parquet`, and bucket version listing
limited to those prefixes. Normal tabular runtime credentials are never used as
a fallback for S3 deletion. Without that configured capability, dataset purge
reports `HF_PURGE_BLOCKED` and leaves the retained result intact.

Purge jobs record a receipt only after remote copies, local cache and owned
objects are removed. A failure records the named error and is safe to retry;
already removed keys are treated as absent. Immutable registry provenance is
kept after purge.
