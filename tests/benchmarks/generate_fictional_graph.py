"""
Generate a fictional BM25 vs dense graph from hardcoded benchmark data,
with embedding time divided by 10 (e.g. GPU / faster hardware scenario).

Run:
    python tests/benchmarks/generate_fictional_graph.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _make_conf_mock():
    m = Mock()
    for cls in ("BackendConfig", "WorkerConfig", "FastAPIConfig", "FrontendConfig"):
        mc = Mock()
        mc.get = Mock(return_value=MagicMock())
        setattr(m, cls, mc)
    return m


# Mock service modules so the benchmark file can be imported as a plain script
# (when running under pytest the conftest already does this).
sys.modules.setdefault("configurations", _make_conf_mock())
sys.modules.setdefault("connections.qdrant", Mock())
sys.modules.setdefault("connections.storage", Mock())


import tests.benchmarks.test_bm25_vs_dense as _bm  # noqa: E402

OUTPUT = Path("tests/benchmarks/results/bm25_vs_dense_embed_div10.png")
_bm.OUTPUT_FILE = OUTPUT

# ── Dense data (measured/inferred) — embed time ÷ 10 ─────────────────────────
#   (n_docs, n_new, t_chunk, t_embed_original, t_upsert, inferred)
_DENSE_RAW = [
    (1, 80, 0.000, 1.586, 0.080, False),
    (5, 400, 0.001, 4.885, 0.350, False),
    (10, 800, 0.002, 9.306, 0.540, False),
    (25, 2000, 0.004, 23.745, 1.493, False),
    (50, 4000, 0.008, 47.490, 2.985, True),
    (100, 8000, 0.016, 94.980, 5.971, True),
    (250, 20000, 0.041, 237.450, 14.927, True),
    (500, 40000, 0.082, 474.900, 29.854, True),
    (1000, 80000, 0.165, 949.801, 59.708, True),
    (5000, 400000, 0.823, 4749.005, 298.541, True),
    (10000, 800000, 1.646, 9498.010, 597.083, True),
    (50000, 4000000, 8.230, 47490.048, 2985.414, True),
]

dense = {}
for n_docs, n_new, t_chunk, t_embed, t_upsert, inferred in _DENSE_RAW:
    t_embed_mod = t_embed / 10
    dense[n_docs] = {
        "n_new": n_new,
        "t_chunk": t_chunk,
        "t_embed": t_embed_mod,
        "t_upsert": t_upsert,
        "t_total": t_chunk + t_embed_mod + t_upsert,
        "inferred": inferred,
    }

# ── Sparse data (precomputed, unchanged) ─────────────────────────────────────
sparse = {
    0: {"t_scroll": 0.012, "t_build": 0.001, "t_serialize": 0.000, "t_total": 0.013},
    100: {"t_scroll": 0.006, "t_build": 0.001, "t_serialize": 0.000, "t_total": 0.007},
    500: {"t_scroll": 0.010, "t_build": 0.003, "t_serialize": 0.001, "t_total": 0.015},
    1000: {"t_scroll": 0.020, "t_build": 0.006, "t_serialize": 0.002, "t_total": 0.028},
    2500: {"t_scroll": 0.036, "t_build": 0.013, "t_serialize": 0.004, "t_total": 0.053},
    5000: {"t_scroll": 0.064, "t_build": 0.030, "t_serialize": 0.011, "t_total": 0.106},
    10000: {
        "t_scroll": 0.124,
        "t_build": 0.179,
        "t_serialize": 0.019,
        "t_total": 0.322,
    },
    25000: {
        "t_scroll": 0.717,
        "t_build": 0.139,
        "t_serialize": 0.068,
        "t_total": 0.924,
    },
    50000: {
        "t_scroll": 0.710,
        "t_build": 0.259,
        "t_serialize": 0.210,
        "t_total": 1.179,
    },
    100000: {
        "t_scroll": 6.031,
        "t_build": 0.968,
        "t_serialize": 0.494,
        "t_total": 7.493,
    },
    250000: {
        "t_scroll": 9.000,
        "t_build": 2.339,
        "t_serialize": 1.999,
        "t_total": 13.338,
    },
    500000: {
        "t_scroll": 34.055,
        "t_build": 5.338,
        "t_serialize": 5.400,
        "t_total": 44.793,
    },
}

_bm._save_graph(
    dense,
    sparse,
    mean_words=24,
    chunks_per_doc=80,
    device_info="mps — Apple M1  [fictional: embed ÷ 10]",
)
print(f"→ Saved: {OUTPUT.resolve()}")
