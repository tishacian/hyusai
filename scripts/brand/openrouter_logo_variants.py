#!/usr/bin/env python3
"""Generate Agentium SVG logo variants through OpenRouter.

This is a brand-asset utility, not part of the Agentium runtime.

Examples:
    python scripts/brand/openrouter_logo_variants.py --dry-run
    python scripts/brand/openrouter_logo_variants.py --env-dir ../POC/.../envs

It writes non-destructive variants under:
    frontend-ng/src/assets/brand/variants/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = REPO_ROOT / "scripts" / "brand" / "agentium_logo_prompt.md"
OUT_DIR = REPO_ROOT / "frontend-ng" / "src" / "assets" / "brand" / "variants"


def _load_dotenv(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value


def load_openrouter_env(env_dir: Path) -> Tuple[List[str], str, str, float]:
    """Same convention as the Renault benchmark: .env + .env.p* files."""
    keys: List[str] = []
    base_url = "https://openrouter.ai/api/v1"
    model = "google/gemini-2.5-flash"
    request_delay = 1.5

    _load_dotenv(env_dir / ".env", override=False)
    base_url = os.getenv("OPENROUTER_BASE_URL", os.getenv("LLM_BASE_URL", base_url))
    model = os.getenv("OPENROUTER_MODEL", os.getenv("LLM_MODEL", model))
    try:
        request_delay = float(
            os.getenv("OPENROUTER_REQUEST_DELAY", os.getenv("LLM_REQUEST_DELAY", request_delay))
        )
    except (TypeError, ValueError):
        pass

    for env_file in sorted(env_dir.glob(".env.p*")):
        _load_dotenv(env_file, override=True)
        key = os.getenv("OPENROUTER_API_KEY", os.getenv("LLM_API_KEY", ""))
        if key and key not in keys:
            keys.append(key)

    key = os.getenv("OPENROUTER_API_KEY", os.getenv("LLM_API_KEY", ""))
    if key and key not in keys:
        keys.insert(0, key)

    return keys, base_url, model, request_delay


class OpenRouterClient:
    def __init__(self, keys: List[str], base_url: str, model: str, request_delay: float):
        if not keys:
            raise RuntimeError("No OpenRouter key found. Set OPENROUTER_API_KEY or pass --env-dir.")
        self.keys = keys
        self.base_url = base_url
        self.model = model
        self.request_delay = request_delay
        self._idx = 0
        self._clients: Dict[int, Any] = {}

    def _client(self):
        if self._idx not in self._clients:
            from openai import OpenAI

            self._clients[self._idx] = OpenAI(
                base_url=self.base_url,
                api_key=self.keys[self._idx],
                timeout=120,
            )
        return self._clients[self._idx]

    def call(self, prompt: str) -> str:
        last_error: Optional[Exception] = None
        for _ in range(len(self.keys)):
            client = self._client()
            for attempt in range(3):
                try:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are a senior brand identity designer. "
                                    "Return strict JSON only."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.75,
                        max_tokens=8000,
                    )
                    time.sleep(self.request_delay)
                    return response.choices[0].message.content or ""
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    message = str(exc).lower()
                    if "401" in message or "403" in message or "auth" in message:
                        break
                    if "429" in message or "rate" in message:
                        time.sleep(min(2 ** attempt * 2, 30))
                    else:
                        time.sleep(2)
            self._idx = (self._idx + 1) % len(self.keys)
        raise RuntimeError(f"OpenRouter request failed: {last_error}")


def _extract_json(text: str) -> Dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(clean)


def _safe_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "variant"


def _sanitize_svg(svg: str) -> str:
    svg = svg.strip()
    if not svg.startswith("<svg"):
        raise ValueError("variant svg does not start with <svg")
    lowered = svg.lower().replace("http://www.w3.org/2000/svg", "")
    if "<script" in lowered or "http://" in lowered or "https://" in lowered:
        raise ValueError("variant svg contains script or external URL")
    return svg


def write_variants(payload: Dict[str, Any]) -> List[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = payload.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("payload has no variants[]")

    written: List[Path] = []
    manifest = []
    for idx, item in enumerate(variants, start=1):
        if not isinstance(item, dict):
            continue
        variant_id = _safe_id(str(item.get("id") or item.get("name") or f"variant-{idx}"))
        svg = _sanitize_svg(str(item.get("svg") or ""))
        path = OUT_DIR / f"{idx:02d}-{variant_id}.svg"
        path.write_text(svg + "\n", encoding="utf-8")
        written.append(path)
        manifest.append(
            {
                "id": variant_id,
                "file": path.name,
                "name": item.get("name") or variant_id,
                "rationale": item.get("rationale") or "",
            }
        )
    (OUT_DIR / "manifest.json").write_text(
        json.dumps({"variants": manifest}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return written


def fallback_variants() -> Dict[str, Any]:
    active = (REPO_ROOT / "frontend-ng" / "src" / "assets" / "brand" / "agentium-mark.svg")
    svg = active.read_text(encoding="utf-8") if active.exists() else ""
    return {
        "variants": [
            {
                "id": "current-orbit-a",
                "name": "Current Orbit A",
                "rationale": "Current hand-authored fallback mark.",
                "svg": svg,
            }
        ]
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-dir", type=Path, default=Path("envs"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt", type=Path, default=PROMPT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-fallback", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt = args.prompt.read_text(encoding="utf-8")

    if args.dry_run:
        keys, base_url, model, delay = load_openrouter_env(args.env_dir)
        print(
            json.dumps(
                {
                    "prompt": str(args.prompt),
                    "output_dir": str(OUT_DIR),
                    "base_url": base_url,
                    "model": args.model or model,
                    "keys_found": len(keys),
                    "request_delay": delay,
                },
                indent=2,
            )
        )
        return 0

    if args.write_fallback:
        written = write_variants(fallback_variants())
        print(f"Wrote {len(written)} fallback variant(s) to {OUT_DIR}")
        return 0

    keys, base_url, model, delay = load_openrouter_env(args.env_dir)
    client = OpenRouterClient(keys, base_url, args.model or model, delay)
    raw = client.call(prompt)
    payload = _extract_json(raw)
    written = write_variants(payload)
    print(f"Wrote {len(written)} variant(s) to {OUT_DIR}")
    for path in written:
        print(f"- {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
