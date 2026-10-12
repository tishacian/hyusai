# Docker

The files here build the Agentium images (`Dockerfile.agentium-*`) and run them with Compose, on the VM or locally. The OmniRAG monolith and Papai-LLM stack (`Dockerfile`, `docker-compose.yml`) are read at the tag `archive/omnirag-rd`.

## Run Agentium canonical stack

Agentium's production-oriented Compose stack:

```bash
cd docker
docker compose -f compose.agentium.yml config
```

The base file is production-oriented and fails closed onto the pre-created
external volumes `agentium_minio_block` and `agentium_qdrant_block`. It must
not silently create root-local state. For an intentional local development
stack, opt in explicitly:

```bash
docker compose \
  -f compose.agentium.yml \
  -f compose.agentium.local-storage.yml \
  up -d agentium-rabbitmq agentium-backend agentium-worker-cpu
```

Never add the local-storage overlay on a VM. Local model modes are mutually
exclusive and still switchable from the model portal. The contract is
`docs/ops/agentium-local-models.md`.

Container mode (Linux Ollama, CPU inside Docker on a Mac):

```bash
docker compose \
  -f compose.agentium.yml \
  -f compose.agentium.local-storage.yml \
  -f compose.agentium.local.yml \
  up -d
```

Mac GPU mode (Ollama 0.34+ on macOS, Metal; GGUF uses llama.cpp, safetensors
uses MLX). Pull the models on the host first with `./ollama-host-models.sh`.

```bash
docker compose \
  -f compose.agentium.yml \
  -f compose.agentium.local-storage.yml \
  -f compose.agentium.local-mac.yml \
  up -d
```

vLLM is the `gpu-models` profile and needs an NVIDIA GPU. It does not replace
the routing default.

Use `AGENTIUM_ENV_FILE` to point
to a non-committed env file. On the demo VM, use
`scripts/agentium-vm-deploy.sh storage-check` and follow
`docs/agentium-release-process.md`; `migrate` and `up` run that read-only gate
automatically.
