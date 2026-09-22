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

Embeddings stay `nomic-embed-text`, dimension 768. A fresh Qdrant volume is
required when the embedding dimension changes. Chat defaults are below.
The cloud routing default is unchanged, and so is the Python fallback
`ollama_default_model` (`qwen3:8b`), which applies only when no mode file
sets `OLLAMA_DEFAULT_MODEL`.

## Default chat model

The three local modes serve one family, Qwen3.5-4B. The 9B sibling scores
higher on the model card and does not fit a 16 GB Mini next to Agentium.
These figures are the publisher's, not a measurement on our hardware. No
token-per-second number below was timed on an M4.

Quality, from the Qwen3.5-4B model card (same table for both sizes):

| Bench | Qwen3.5-4B | Qwen3.5-9B |
| --- | --- | --- |
| MMLU-Pro | 79.1 | 82.5 |
| GPQA Diamond | 76.2 | 81.7 |
| IFEval | 89.8 | 91.5 |
| LiveCodeBench v6 | 55.8 | 65.6 |
| HMMT Feb 25 | 74.0 | 83.2 |
| BFCL-V4 | 50.3 | 66.1 |

Fit, from the Ollama library artifact sizes, against the estimated 6.6 GB
left by the 16 GB comfort profile:

| Tag | Engine | Artifact | 16 GB Mini with Agentium |
| --- | --- | --- | --- |
| `qwen3.5:4b-mlx` | MLX | 4.0 GB | Default for the Mac GPU mode |
| `qwen3.5:4b` | llama.cpp | 3.4 GB | Default for the Linux container and the chart |
| `qwen3.5:2b-mlx` | MLX | 3.1 GB | Smaller, and not the size the model card tables |
| `qwen3.5:9b` | llama.cpp | 6.6 GB | Fills the estimated headroom before any KV cache |
| `qwen3.5:9b-mlx` | MLX | 8.9 GB | Above that headroom |

`Qwen/Qwen3.5-4B` is the Hugging Face checkpoint for vLLM. The pinned image
`vllm/vllm-openai:v0.19.1` ships `qwen3_5.py`. Enabling vLLM still does not
set `DEFAULT_PROVIDER`.

Any name starting with `qwen3` keeps the existing 32 768-token window in
`model_context_window`. The model card allows 262 144. That cap stays,
because a 256k cache does not fit the Mini.

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

The Mac overlay asks for `qwen3.5:4b-mlx`. That tag is safetensors, so
Ollama selects the MLX engine. On an M4, MLX uses the GPU and stops at the
120 GB/s memory ceiling. It does not use the Neural Engine, and it does not
see the M5 GPU matrix units. A GGUF tag on the same host would stay on
llama.cpp Metal, which is a smaller step than leaving the Linux VM.

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
