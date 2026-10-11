# Hugging Face artifact node protocol v1

This is the Agentium client contract for the external `omnirag-llm-portal`
preparation service. The external service is not included in this repository.
An old node returns `HF_NODE_INCOMPATIBLE` before transfer; installing Agentium
does not upgrade its GPU nodes. Acceptance on a real vLLM node is required before
declaring a deployment operational.

All requests use the configured node control token in the existing
`Authorization: Bearer` and `X-LLM-Portal-Token` headers. The node must authenticate
every endpoint below. Hugging Face credentials are never sent to the node.

## Capability advertisement

`GET /api/v1/artifacts/capabilities` returns:

```json
{
  "artifact_api_version": 1,
  "manifest_versions": [2],
  "sha256_verification": true,
  "offline_inference": true,
  "read_only_weights": true,
  "idempotent_deployments": true,
  "deployment_states": ["preparing", "verifying", "starting", "ready", "failed", "draining", "stopped"],
  "max_signed_url_seconds": 300,
  "hub_network_access": true,
  "runtimes": {
    "vllm": {
      "version": "<installed version>",
      "formats": ["safetensors"],
      "architectures": ["LlamaForCausalLM"],
      "max_context_length": 8192,
      "available_memory_bytes": 24000000000
    },
    "llamacpp": {
      "version": "<installed build>",
      "formats": ["gguf"],
      "architectures": ["llama"],
      "max_context_length": 8192,
      "available_memory_bytes": 24000000000
    }
  }
}
```

The backend verifies the requested architecture, runtime, context and memory
before requesting any transfer URLs. Required memory includes weights, KV cache
and runtime overhead. The node repeats admission atomically against actual free
capacity; an earlier capability response is not a memory reservation.

## Deployment lifecycle

`PUT /api/v1/artifacts/deployments/{deployment_id}` accepts the exact immutable
manifest, its SHA-256, artifact/workspace identity, architecture, context length,
required memory, runtime version, source and provenance. Without an explicit
deployment ID the backend derives one from these immutable inputs. The node
persists an idempotency record before starting work: replaying the same deployment
returns its current state; reusing its ID for different inputs returns HTTP 409.
Expiring transfer URLs are not part of the immutable deployment fingerprint.

The `source` is either:

- `huggingface`: credential-free HTTPS endpoint, repository, exact commit and the
  exact selected file URLs. The preparation agent verifies every SHA-256 and byte
  size. If the pinned revision is unavailable, it reports `source_unavailable` and
  waits for an authorized MinIO refresh. It never switches to a branch or requests
  a Hub token.
- `minio`: one temporary URL per selected path, with `expires_in_seconds` no
  greater than 300. Used immediately for private/gated repositories or isolated
  nodes. A node may request a lower maximum expiry in its capabilities.

The preparation agent stages all selected files, rejects paths or hashes outside
the manifest, then publishes the verified snapshot atomically. It mounts weights
read-only in an inference process with `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1` and no network access. Runtime configuration must enforce
that network isolation; environment flags alone are insufficient.

Every lifecycle response includes `deployment_id`, `artifact_id` and `state`.
Progress, typed errors, bytes transferred and release confirmation may accompany
the response. The accepted states are `preparing`, `verifying`, `starting`,
`ready`, `failed`, `draining`, `stopped`.

- `GET /api/v1/artifacts/deployments/{id}` returns current progress/state.
- `POST /api/v1/artifacts/deployments/{id}/stop`, body `{"drain":true}`, cancels
  preparation or drains active inference; it reaches `stopped` only after all
  runtime readers release their leases.
- `PUT /api/v1/artifacts/deployments/{id}/sources` replaces temporary transfer
  URLs without changing the immutable manifest. Only Agentium can issue this
  request, after checking deployment ownership, current grant, global status and
  effective license policy. Already issued URLs expire naturally within 300s.
- `DELETE /api/v1/artifacts/deployments/{id}` removes a stopped deployment's
  retained weights and returns `state: "stopped"` with `copies_deleted: true`
  only after physical deletion. Agentium requires this explicit receipt before
  completing a global artifact purge; HTTP 404 alone is not a deletion receipt.

Status and stop remain available to the owning workspace administrator after
revocation; URL renewal and new inference do not. A timeout or unreachable node
never counts as confirmation of stopped inference or deletion.

The existing instance inventory must expose a running deployment with its
workspace ID, artifact ID, repository, commit, variant, runtime version,
deployment ID and served model/port. Agentium preserves that provenance when
registering the route. Each canonical model invocation rechecks workspace rights
and the current artifact policy; a cached provider entry alone grants no access.

## Validation boundary

The backend has local contract tests for capability refusal, exact public Hub
selection, restricted/isolated MinIO transfer, idempotent IDs, URL renewal after
revocation, and lifecycle visibility. Actual checksum verification, process
isolation, GPU capacity reservation, crash recovery and cancellation are duties
of the external implementation and need its own tests and a real-node acceptance
run. Physical purge requires explicit confirmation that every remote copy has
been removed; stopping an instance is not by itself proof of deletion.
