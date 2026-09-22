# Local model modes

The deployment default stays a cloud provider (`DEFAULT_PROVIDER=openai`).
A local install opts into one mode below. The model portal can still point
a workspace at OpenAI, Azure, Anthropic, Gemini, or a registered endpoint.
Changing mode does not add a runner for the Apple Neural Engine.

| Mode | Inference process | What Agentium calls | How to select it |
| --- | --- | --- | --- |
| Cloud | The provider in the portal | Unchanged code default | Base Compose, lab Helm values |
| Container | `ollama/ollama:0.34.2` in Linux | `http://agentium-ollama:11434` | `compose.agentium.local.yml`, or Helm `values-local.yaml` |
| Mac GPU | Ollama 0.34+ on macOS | `http://host.docker.internal:11434` | `compose.agentium.local-mac.yml` |
| NVIDIA | `vllm/vllm-openai:v0.19.1` | Portal node, OpenAI-compatible | Compose profile `gpu-models`, or Helm `vllm.enabled` |

Chat model for the two Ollama modes: `qwen2.5:3b`. Embeddings:
`nomic-embed-text`, dimension 768. A fresh Qdrant volume is required when
the embedding dimension changes.

## Container

One Ollama serves chat (`/api/chat` via the existing provider) and
embeddings (`POST /api/embed`). The image is the same on Compose and in the
chart. On a Mac the container runs in a Linux VM, so it sees the ARM CPU.
That is the right mode for a Linux host and for the lab cluster. It is the
wrong mode when the goal is the M4 GPU.

```bash
cd docker
docker compose \
  -f compose.agentium.yml \
  -f compose.agentium.local-storage.yml \
  -f compose.agentium.local.yml \
  up -d
```

Helm: `ops/helm/agentium/values-local.yaml`. The lab values leave Ollama off.

## Mac GPU

Ollama stays a macOS process. Metal can then schedule the M4 GPU (10 cores,
120 GB/s on the base Mini). Agentium's API and worker stay in Compose and
reach the host through `host.docker.internal`.

```bash
cd docker
./ollama-host-models.sh
docker compose \
  -f compose.agentium.yml \
  -f compose.agentium.local-storage.yml \
  -f compose.agentium.local-mac.yml \
  up -d
```

Do not pass `compose.agentium.local.yml` in the same command. That file
starts the Linux container and would bind host port 11434.

Ollama 0.30 and later keeps two engines. A GGUF tag, including
`qwen2.5:3b`, runs on llama.cpp through Metal. A safetensors tag runs on
MLX, still on that GPU, still in the same Ollama process. Set
`AGENTIUM_OLLAMA_CHAT_MODEL` to the tag you pulled. On an M4 both engines
share the 120 GB/s ceiling. The larger MLX speedups Ollama published were
measured on M5-class machines, whose GPU has matrix units the M4 does not.

`qwen2.5:3b` in 4-bit is on the order of 2 GB. An 8B model in 4-bit is
about 5.6 GB of weights in Apple's MLX figures, which consumes most of the
headroom left by the 16 GB comfort profile.

## NVIDIA

vLLM is an OpenAI-compatible server for an NVIDIA GPU. Enabling the profile
or `vllm.enabled` does not set `DEFAULT_PROVIDER`. Register the node in the
model portal (engine `vllm`) and switch the workspace there.

```bash
docker compose -f compose.agentium.yml --profile gpu-models up -d agentium-vllm
```

## Not a mode

The Apple Neural Engine is a separate 16-core inferencer. Its public path is
Core ML, and Core AI since WWDC 2026. MLX declined that device (ml-explore/mlx
issue 18, still closed in 2025) because the API is private and the GPU is
faster for large models. ANEMLL can run short-context models on the Neural
Engine at a few watts; published M4 Max figures put an 8B near 9 tok/s there
against about 30 tok/s on the GPU. There is no Compose service and no portal
provider for it.

The "Neural Accelerators" in Apple's 19 November 2025 MLX note are matrix
units inside the M5 GPU. They cut time to first token by roughly 3.3–4.1×
versus an M4, and token generation by roughly 1.2×, in line with the move
from 120 GB/s to 153 GB/s. They are absent on the M4 Mini.
