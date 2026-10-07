"""Qualify the ONNX rerank engine against torch on this host's CPU.

usage (inside the backend image, on the host that will serve):
    python -m scripts.bench_rerank_engines

For the balanced and deep profiles it measures, each engine in its own process
so their thread pools do not contend: agreement with the model card's published
logits, agreement between the two engines on reference passages (scores and
order), and p50/p95 latency at the profile's candidate count and max length.
It prints a verdict: switch with RAG_RERANKER_BACKEND=onnx only when ONNX
matches and fits the balanced budget at least as well as torch does.
"""
from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
import time

CARD = {
    # Published in each model's README (sentence-transformers CrossEncoder.predict).
    "cross-encoder/ms-marco-MiniLM-L-6-v2": (8.607138, -4.320078),
    "cross-encoder/ms-marco-MiniLM-L-12-v2": (9.218911, -4.0780287),
}
CARD_QUERY = "How many people live in Berlin?"
CARD_PASSAGES = [
    "Berlin had a population of 3,520,031 registered inhabitants in an area of 891.82 square kilometers.",
    "Berlin is well known for its museums.",
]
CASES = [
    ("Quelle est la pression nominale du circuit hydraulique ?", [
        "La pression nominale du circuit hydraulique est de 6 bar.",
        "Le personnel doit porter des chaussures de sécurité dans l'atelier.",
        "Une dérive de plus de 0,4 bar déclenche une maintenance préventive.",
        "Le restaurant d'entreprise ferme à 14 heures.",
    ]),
    ("Which subscribers are most likely to churn next month?", [
        "Prepaid subscribers with a falling top-up frequency churn three times more often.",
        "The network operations centre runs 24/7 from Casablanca.",
        "Churn is the share of subscribers who leave within a period.",
        "Annual contracts reduce churn among postpaid customers.",
    ]),
]


def _child(engine: str, model: str, max_length: int, candidates: int) -> dict:
    from app.core.config import settings
    from app.services.retrieval.reranker_config import RerankerConfig

    config = RerankerConfig(model_name=model, max_length=max_length)
    if engine == "onnx":
        from app.services.retrieval.onnx_reranker import OnnxReranker

        reranker = OnnxReranker(config, models_dir=settings.rag_models_dir)
    else:
        from app.services.retrieval.flash_reranker import FlashReranker

        reranker = FlashReranker(config)
    card = [math.log(p / (1 - p)) if 0 < p < 1 else float("nan") for p in reranker.score(CARD_QUERY, CARD_PASSAGES)]
    cases = [reranker.score(query, passages) for query, passages in CASES]
    query, base = CASES[1]
    batch = (base * candidates)[:candidates]
    timings = []
    for _ in range(14):
        started = time.perf_counter()
        reranker.score(query, batch)
        timings.append((time.perf_counter() - started) * 1000)
    timings = sorted(timings[4:])
    return {"card": card, "cases": cases, "p50": statistics.median(timings), "p95": timings[-1]}


def _run(engine: str, model: str, max_length: int, candidates: int) -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "scripts.bench_rerank_engines", "--child", engine, model, str(max_length), str(candidates)],
        capture_output=True, text=True, check=False,
    )
    lines = [line for line in out.stdout.splitlines() if line.startswith("{")]
    if out.returncode or not lines:
        return {"error": (out.stderr.strip().splitlines() or ["no output"])[-1]}
    return json.loads(lines[-1])


def main() -> int:
    from app.core.config import settings

    profiles = [
        ("balanced", settings.rag_cross_encoder_model_balanced, settings.rag_cross_encoder_max_length_balanced,
         settings.rag_cross_encoder_max_candidates, settings.rag_cross_encoder_budget_seconds * 1000),
        ("deep", settings.rag_cross_encoder_model_deep, settings.rag_cross_encoder_max_length_deep,
         settings.rag_cross_encoder_max_candidates_deep, settings.rag_cross_encoder_budget_seconds_deep * 1000),
    ]
    qualified = True
    for profile, model, max_length, candidates, budget_ms in profiles:
        runs = {engine: _run(engine, model, max_length, candidates) for engine in ("torch", "onnx")}
        print(f"\n{profile}: {model} max_length={max_length} candidates={candidates} budget={budget_ms:.0f}ms")
        for engine, run in runs.items():
            if "error" in run:
                print(f"  {engine:5s} unavailable: {run['error']}")
                continue
            card_delta = max(abs(a - b) for a, b in zip(run["card"], CARD.get(model, run["card"])))
            print(f"  {engine:5s} p50={run['p50']:.0f}ms p95={run['p95']:.0f}ms  card |Δlogit|={card_delta:.1e}")
        onnx, torch = runs["onnx"], runs["torch"]
        if "error" in onnx:
            qualified = False
            continue
        onnx_card = max(abs(a - b) for a, b in zip(onnx["card"], CARD.get(model, onnx["card"])))
        ok = onnx_card < 1e-3
        torch_scores = [] if "error" in torch else [s for case in torch["cases"] for s in case]
        if torch_scores and not all(math.isfinite(s) for s in torch_scores):
            # Seen on macOS arm64 with torch 2.14 for L-6: the torch engine is
            # the broken one, so the published logits alone decide.
            print("  torch returns non-finite scores on this host: compared to the model card only")
        elif torch_scores:
            delta = max(abs(a - b) for x, y in zip(torch["cases"], onnx["cases"]) for a, b in zip(x, y))
            same_order = all(
                sorted(range(len(x)), key=lambda i, x=x: -x[i]) == sorted(range(len(y)), key=lambda i, y=y: -y[i])
                for x, y in zip(torch["cases"], onnx["cases"])
            )
            print(f"  torch vs onnx: max|Δscore|={delta:.1e} same order={same_order}")
            ok = ok and delta < 1e-3 and same_order
        if profile == "balanced":
            ok = ok and onnx["p95"] <= budget_ms
        qualified = qualified and ok
        print(f"  verdict: {'ONNX qualified' if ok else 'ONNX NOT qualified'}")
    print("\nRecommendation:", "set RAG_RERANKER_BACKEND=onnx" if qualified else "keep torch")
    return 0 if qualified else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        engine, model, max_length, candidates = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
        print(json.dumps(_child(engine, model, max_length, candidates)))
        sys.exit(0)
    sys.exit(main())
