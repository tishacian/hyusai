"""
Benchmark: dense pipeline vs BM25 rebuild — independent scaling analysis.

Two independent measurements on separate axes:
  dense  — chunk + embed + Qdrant upsert  →  O(n_docs)         collection size irrelevant
  sparse — BM25 scroll + build + pickle   →  O(collection_size) n_docs irrelevant

Three output charts:
  Left   — Dense total time (+ sub-steps) vs number of documents
  Centre — BM25 total time (+ sub-steps) vs collection size
  Right  — Equilibrium curve: for each collection size, the n_docs threshold
            where dense_time == BM25_time.  Regions show which pipeline dominates.

Run:
    pytest tests/benchmarks/test_bm25_vs_dense.py -m benchmark -s

    # Re-measure sparse phase (slow — requires populating up to 500k chunks):
    RECOMPUTE_SPARSE=1 pytest tests/benchmarks/test_bm25_vs_dense.py -m benchmark -s

Requires:
    - Running Qdrant on localhost:6333 (set QDRANT__SERVICE__API_KEY if needed)
    - Embedding model cached locally (downloads automatically on first run):
          sentence-transformers/all-mpnet-base-v2
    - matplotlib:  pip install matplotlib
"""

import os
import pickle
import platform
import subprocess
import time
import uuid
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import torch
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from src.chunker import BM25Retriever, TextChunker
from src.embeddingloader import EmbeddingModelLoader
from src.globalvariables import EMBEDDING_NAME, ChunkingMethod

# ── Tunable parameters ────────────────────────────────────────────────────────

CHUNK_SIZE = 200
CHUNK_OVERLAP = 50

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_API_KEY = os.environ.get("QDRANT__SERVICE__API_KEY", "changeme")

# Synthetic document shape (pre-chunking)
DOC_SENTENCES = 80  # sentences per synthetic document
WORDS_PER_SENTENCE = 18  # words per sentence (~90-char sentences)

SCROLL_BATCH = 256  # mirrors the limit used in EmbeddingVectors.save_index()
POPULATE_BATCH = 1000  # larger batch for fast pre-population (setup only)
UPSERT_BATCH = 512  # max points per upsert call (avoids Qdrant payload size limit)

# Dense measurement: vary number of documents.
# Entries above INFER_ABOVE are not actually run — per-chunk rates from the last
# directly-measured point are scaled linearly to infer the cost.
INFER_ABOVE = 25
DOC_COUNTS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000, 50000]

# Sparse measurement: vary collection size
COLLECTION_SIZES = [
    0,
    100,
    500,
    1000,
    2500,
    5000,
    10000,
    25000,
    50000,
    100000,
    250000,
    500000,
]

OUTPUT_FILE = Path("tests/benchmarks/results/bm25_vs_dense.png")

# Set RECOMPUTE_SPARSE=1 to re-run Phase 2 against a live Qdrant instance.
# By default the hardcoded measurements below are used (500k-chunk run is slow).
RECOMPUTE_SPARSE = os.environ.get("RECOMPUTE_SPARSE", "0") == "1"

# ── Precomputed sparse data ───────────────────────────────────────────────────
# Measured on: chunk_size=200, overlap=50, scroll_batch=256, all-mpnet-base-v2
# Machine: Apple M1, Qdrant running locally via Docker
_PRECOMPUTED_SPARSE: dict[int, dict] = {
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

# ── Synthetic data ────────────────────────────────────────────────────────────

_VOCAB = [f"word{i}" for i in range(500)]


def _synthetic_doc(seed: int) -> str:
    rng = np.random.default_rng(seed)
    sentences = []
    for _ in range(DOC_SENTENCES):
        words = [_VOCAB[j] for j in rng.integers(0, len(_VOCAB), WORDS_PER_SENTENCE)]
        sentences.append(" ".join(words) + ".")
    return " ".join(sentences)


def _synthetic_text(n_words: int, seed: int) -> str:
    rng = np.random.default_rng(seed)
    return " ".join(_VOCAB[i] for i in rng.integers(0, len(_VOCAB), n_words))


def _make_points(
    n: int, id_offset: int, dim: int, words_per_chunk: int
) -> list[PointStruct]:
    rng = np.random.default_rng(id_offset)
    return [
        PointStruct(
            id=id_offset + i,
            vector=rng.random(dim).tolist(),
            payload={"text": _synthetic_text(words_per_chunk, seed=id_offset + i)},
        )
        for i in range(n)
    ]


# ── Chunking ──────────────────────────────────────────────────────────────────


def _time_chunk(docs: list[str]) -> tuple[list[str], float]:
    chunker = TextChunker(None, None)
    t0 = time.perf_counter()
    all_chunks: list[str] = []
    for doc in docs:
        chunks = chunker.chunker(
            doc,
            method=ChunkingMethod.RECURSIVE_CHARACTER,
            chunk_size=CHUNK_SIZE,
            overlap=CHUNK_OVERLAP,
        )
        if chunks:
            all_chunks.extend(chunks)
    return all_chunks, time.perf_counter() - t0


# ── Model loading ─────────────────────────────────────────────────────────────


def _load_model():
    print(f"\nLoading embedding model: {EMBEDDING_NAME}  (downloads if not cached)")
    model = EmbeddingModelLoader.load_embedding_model(EMBEDDING_NAME)
    dim = EmbeddingModelLoader.get_embedding_dimension(EMBEDDING_NAME)
    device = _device()
    print(f"  → loaded  dim={dim}  device={device.type}")
    return model, dim


def _device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _time_embed(model, texts: list[str]) -> float:
    device = _device()
    t0 = time.perf_counter()
    model.encode(
        texts, show_progress_bar=False, convert_to_tensor=True, device=device.type
    )
    return time.perf_counter() - t0


# ── Qdrant helpers ────────────────────────────────────────────────────────────


def _create_collection(client: QdrantClient, name: str, dim: int) -> None:
    try:
        client.delete_collection(name)
    except Exception:
        pass
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


def _populate(
    client: QdrantClient, name: str, n: int, dim: int, words_per_chunk: int
) -> None:
    for offset in range(0, n, POPULATE_BATCH):
        batch_n = min(POPULATE_BATCH, n - offset)
        client.upsert(
            collection_name=name,
            wait=True,
            points=_make_points(
                batch_n, id_offset=offset, dim=dim, words_per_chunk=words_per_chunk
            ),
        )


def _time_batched_upsert(
    client: QdrantClient, col: str, points: list[PointStruct]
) -> float:
    """Upsert in UPSERT_BATCH-sized chunks to avoid Qdrant payload size limits."""
    t0 = time.perf_counter()
    for i in range(0, len(points), UPSERT_BATCH):
        client.upsert(
            collection_name=col, wait=True, points=points[i : i + UPSERT_BATCH]
        )
    return time.perf_counter() - t0


def _time_bm25_rebuild(client: QdrantClient, col: str) -> tuple[float, float, float]:
    """Returns (t_scroll, t_build, t_serialize) mirroring save_index()."""
    t0 = time.perf_counter()
    all_texts: list[str] = []
    scroll_offset = None
    while True:
        batch, scroll_offset = client.scroll(
            collection_name=col,
            with_payload=True,
            with_vectors=False,
            offset=scroll_offset,
            limit=SCROLL_BATCH,
        )
        if not batch:
            break
        all_texts.extend(p.payload["text"] for p in batch if "text" in p.payload)
        if scroll_offset is None:
            break
    t_scroll = time.perf_counter() - t0

    t0 = time.perf_counter()
    retriever = BM25Retriever(all_texts)
    t_build = time.perf_counter() - t0

    t0 = time.perf_counter()
    buf = BytesIO()
    pickle.dump(retriever, buf)
    t_serialize = time.perf_counter() - t0

    return t_scroll, t_build, t_serialize


# ── Benchmark ─────────────────────────────────────────────────────────────────


def test_populate_qdrant():
    """Sanity check: can we populate a collection with synthetic data?"""
    client = QdrantClient(
        host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY, https=False
    )

    col = f"test_populate_{uuid.uuid4().hex[:8]}"
    _create_collection(client, col, dim=128)
    points = _make_points(100, id_offset=0, dim=128, words_per_chunk=20)
    client.upsert(collection_name=col, wait=True, points=points)
    count = client.count(col).count
    assert count == 100, f"Expected 100 points in collection, found {count}"


@pytest.mark.benchmark
def test_bm25_vs_dense_benchmark():
    """
    Phase 1 — Dense: chunk + embed + upsert time for varying n_docs.
               Collection size has no effect — measured on a fresh empty collection.
    Phase 2 — Sparse: BM25 rebuild time for varying collection sizes.
               n_docs has no effect — only total collection size matters.
    Produces a 3-panel PNG at OUTPUT_FILE.
    """
    try:
        import matplotlib.pyplot as plt  # noqa: F401
    except ImportError:
        pytest.skip("matplotlib not installed — pip install matplotlib")

    model, embedding_dim = _load_model()
    client = QdrantClient(
        host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY, https=False
    )

    # Warm-up (JIT, MPS graph compilation, etc.)
    _probe_chunks, _ = _time_chunk([_synthetic_doc(0)])
    model.encode(["warmup"], show_progress_bar=False, convert_to_tensor=True)
    mean_words = (
        int(np.mean([len(c.split()) for c in _probe_chunks])) if _probe_chunks else 20
    )
    print(f"  → chunks/doc={len(_probe_chunks)}  mean_words={mean_words}")

    # ── Phase 1: dense — vary n_docs ──────────────────────────────────────────
    print("\n── Dense pipeline (chunk + embed + upsert) ──────────────────────────")
    print(
        f"{'n_docs':>7}  {'n_chunks':>8}  {'chunk':>6}  {'embed':>7}  {'upsert':>6}  {'total':>7}  {'note':}"
    )
    print("-" * 70)

    dense: dict[int, dict] = {}
    # Per-chunk rates (s/chunk) updated after each directly-measured point
    _rate_chunk = _rate_embed = _rate_upsert = 0.0
    chunks_per_doc = len(_probe_chunks) or 1

    col_dense = f"bench_dense_{uuid.uuid4().hex[:8]}"
    try:
        _create_collection(client, col_dense, embedding_dim)
        for n_docs in DOC_COUNTS:
            n_new = n_docs * chunks_per_doc
            inferred = n_docs > INFER_ABOVE

            if not inferred:
                docs = [_synthetic_doc(seed=d) for d in range(n_docs)]
                new_texts, t_chunk = _time_chunk(docs)
                n_new = len(new_texts)
                t_embed = _time_embed(model, new_texts)
                points = _make_points(
                    n_new, id_offset=0, dim=embedding_dim, words_per_chunk=mean_words
                )
                client.delete_collection(col_dense)
                _create_collection(client, col_dense, embedding_dim)
                t_upsert = _time_batched_upsert(client, col_dense, points)
                # update per-chunk rates from this measurement
                _rate_chunk = t_chunk / n_new
                _rate_embed = t_embed / n_new
                _rate_upsert = t_upsert / n_new
                chunks_per_doc = n_new // n_docs
            else:
                t_chunk = _rate_chunk * n_new
                t_embed = _rate_embed * n_new
                t_upsert = _rate_upsert * n_new

            t_total = t_chunk + t_embed + t_upsert
            dense[n_docs] = {
                "n_new": n_new,
                "t_chunk": t_chunk,
                "t_embed": t_embed,
                "t_upsert": t_upsert,
                "t_total": t_total,
                "inferred": inferred,
            }
            note = "(inferred)" if inferred else "(measured)"
            print(
                f"{n_docs:>7}  {n_new:>8}  {t_chunk:>6.3f}  {t_embed:>7.3f}"
                f"  {t_upsert:>6.3f}  {t_total:>7.3f}  {note}"
            )
    finally:
        try:
            client.delete_collection(col_dense)
        except Exception:
            pass

    # ── Phase 2: sparse — vary collection size ────────────────────────────────
    print("\n── BM25 rebuild (scroll + build + pickle) ───────────────────────────")
    print(f"{'col_size':>9}  {'scroll':>7}  {'build':>7}  {'pickle':>7}  {'total':>7}")
    print("-" * 50)

    if not RECOMPUTE_SPARSE:
        sparse = _PRECOMPUTED_SPARSE
        print("  (using precomputed data — set RECOMPUTE_SPARSE=1 to re-measure)")
        for col_size in sorted(sparse):
            r = sparse[col_size]
            print(
                f"{col_size:>9}  {r['t_scroll']:>7.3f}  {r['t_build']:>7.3f}"
                f"  {r['t_serialize']:>7.3f}  {r['t_total']:>7.3f}"
            )
    else:
        sparse = {}
        for col_size in COLLECTION_SIZES:
            col = f"bench_sparse_{uuid.uuid4().hex[:8]}"
            try:
                _create_collection(client, col, embedding_dim)
                _populate(client, col, col_size, embedding_dim, mean_words)
                t_scroll, t_build, t_ser = _time_bm25_rebuild(client, col)
                t_total = t_scroll + t_build + t_ser

                sparse[col_size] = {
                    "t_scroll": t_scroll,
                    "t_build": t_build,
                    "t_serialize": t_ser,
                    "t_total": t_total,
                }
                print(
                    f"{col_size:>9}  {t_scroll:>7.3f}  {t_build:>7.3f}"
                    f"  {t_ser:>7.3f}  {t_total:>7.3f}"
                )
            finally:
                try:
                    client.delete_collection(col)
                except Exception:
                    pass

    _save_graph(dense, sparse, mean_words, chunks_per_doc, _device_info())


# ── Graph ─────────────────────────────────────────────────────────────────────


def _device_info() -> str:
    """Return a human-readable string describing the embedding device."""
    dev = _device()
    if dev.type == "mps":
        try:
            chip = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        except Exception:
            chip = platform.processor() or "Apple Silicon"
        return f"mps — {chip}"
    if dev.type == "cuda":
        try:
            return f"cuda — {torch.cuda.get_device_name(0)}"
        except Exception:
            return "cuda"
    return f"cpu — {platform.processor() or platform.machine()}"


def _chunks_to_docs_axis(ax, chunks_per_doc: int) -> None:
    """Add a secondary x-axis above `ax` showing collection size in documents."""
    ax2 = ax.twiny()
    lo, hi = ax.get_xlim()
    ax2.set_xlim(lo / chunks_per_doc, hi / chunks_per_doc)
    ax2.set_xlabel("Collection size (docs)", fontsize=9)
    ax2.tick_params(labelsize=8)


def _save_graph(
    dense: dict, sparse: dict, mean_words: int, chunks_per_doc: int, device_info: str
) -> None:
    import matplotlib.pyplot as plt

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax_dense, ax_sparse, ax_eq) = plt.subplots(1, 3, figsize=(21, 6))

    doc_counts = sorted(dense)
    col_sizes = sorted(sparse)

    dense_totals = [dense[n]["t_total"] for n in doc_counts]
    sparse_totals = [sparse[c]["t_total"] for c in col_sizes]

    # ── Compute equilibrium first so y_max is known before plotting ───────────
    _ns = np.array(doc_counts, dtype=float)
    _dt = np.array(dense_totals, dtype=float)
    _cs = np.array(col_sizes, dtype=float)
    _st = np.array(sparse_totals, dtype=float)

    clipped_st = np.clip(_st, _dt.min(), _dt.max())
    breakeven_ns = np.interp(clipped_st, _dt, _ns)

    # Shared "documents" scale: dense x-axis and equilibrium y-axis use the same range.
    y_max = max(float(breakeven_ns.max()) * 1.5, 1.0)

    # Only plot doc counts within [0, y_max] on the dense chart — plotting points
    # outside the visible x range causes matplotlib to autoscale the y-axis to
    # include their huge inferred time values.
    visible_ns = [n for n in doc_counts if n <= y_max]
    visible_meas = [n for n in visible_ns if not dense[n]["inferred"]]
    visible_inf = [n for n in visible_ns if dense[n]["inferred"]]

    # ── Left: dense time vs n_docs (x-axis capped at y_max) ──────────────────
    for key, color, marker, label in [
        ("t_chunk", "#795548", "s", "Chunking"),
        ("t_embed", "#4CAF50", "^", "Embedding"),
        ("t_upsert", "#2196F3", "o", "Qdrant upsert"),
    ]:
        ax_dense.plot(
            visible_ns,
            [dense[n][key] for n in visible_ns],
            color=color,
            linewidth=1.8,
            label=label,
        )
        ax_dense.plot(
            visible_meas,
            [dense[n][key] for n in visible_meas],
            color=color,
            marker=marker,
            markersize=6,
            linestyle="none",
        )
        if visible_inf:
            ax_dense.plot(
                visible_inf,
                [dense[n][key] for n in visible_inf],
                color=color,
                marker=marker,
                markersize=6,
                linestyle="none",
                markerfacecolor="none",
                markeredgewidth=1.5,
            )

    ax_dense.plot(
        visible_ns,
        [dense[n]["t_total"] for n in visible_ns],
        color="#1565C0",
        linestyle="--",
        linewidth=2.2,
        label="Dense total",
        zorder=5,
    )
    if visible_inf:
        ax_dense.plot(
            [],
            [],
            color="gray",
            marker="o",
            markersize=6,
            linestyle="none",
            label=f"● measured  (n_docs ≤ {INFER_ABOVE})",
        )
        ax_dense.plot(
            [],
            [],
            color="gray",
            marker="o",
            markersize=6,
            linestyle="none",
            markerfacecolor="none",
            markeredgewidth=1.5,
            label=f"○ inferred  (n_docs > {INFER_ABOVE})",
        )
    ax_dense.set_title("Dense pipeline vs documents added", fontsize=10)
    ax_dense.set_xlabel("Documents added", fontsize=10)
    ax_dense.set_ylabel("Time (s)", fontsize=10)
    ax_dense.set_xlim(0, y_max)
    ax_dense.legend(fontsize=8, loc="upper left")
    ax_dense.grid(True, alpha=0.3)
    ax_dense.set_ylim(bottom=0)

    # ── Centre: sparse time vs collection size ────────────────────────────────
    ax_sparse.plot(
        col_sizes,
        [sparse[c]["t_scroll"] for c in col_sizes],
        color="#EF5350",
        marker="s",
        linewidth=1.8,
        markersize=6,
        label="Scroll Qdrant",
    )
    ax_sparse.plot(
        col_sizes,
        [sparse[c]["t_build"] for c in col_sizes],
        color="#FF9800",
        marker="^",
        linewidth=1.8,
        markersize=6,
        label="Build index",
    )
    ax_sparse.plot(
        col_sizes,
        [sparse[c]["t_serialize"] for c in col_sizes],
        color="#AB47BC",
        marker="D",
        linewidth=1.8,
        markersize=6,
        label="Pickle",
    )
    ax_sparse.plot(
        col_sizes,
        sparse_totals,
        color="black",
        linestyle="--",
        linewidth=2.2,
        label="BM25 total",
        zorder=5,
    )
    ax_sparse.set_title("BM25 rebuild vs collection size", fontsize=10)
    ax_sparse.set_xlabel("Collection size (chunks)", fontsize=10)
    ax_sparse.set_ylabel("Time (s)", fontsize=10)
    ax_sparse.legend(fontsize=8, loc="upper left")
    ax_sparse.grid(True, alpha=0.3)
    ax_sparse.set_ylim(bottom=0)
    _chunks_to_docs_axis(ax_sparse, chunks_per_doc)

    # ── Right: equilibrium ────────────────────────────────────────────────────
    ax_eq.plot(
        _cs,
        breakeven_ns,
        color="black",
        linewidth=2.2,
        label="Equilibrium  (dense = BM25)",
    )
    ax_eq.fill_between(
        _cs,
        breakeven_ns,
        y_max,
        alpha=0.15,
        color="#EF5350",
        label="Dense slower  (dense > sparse)",
    )
    ax_eq.fill_between(
        _cs,
        0,
        breakeven_ns,
        alpha=0.15,
        color="#2196F3",
        label="BM25 slower  (sparse > dense)",
    )
    ax_eq.set_title("Equilibrium: n_docs where dense cost = BM25 cost", fontsize=10)
    ax_eq.set_xlabel("Collection size (chunks)", fontsize=10)
    ax_eq.set_ylabel("Documents added at breakeven", fontsize=10)
    ax_eq.legend(fontsize=8, loc="upper left")
    ax_eq.grid(True, alpha=0.3)
    ax_eq.set_ylim(0, y_max)
    _chunks_to_docs_axis(ax_eq, chunks_per_doc)

    fig.suptitle(
        f"Dense pipeline vs BM25 rebuild — {EMBEDDING_NAME}  [{device_info}]\n"
        f"chunk_size={CHUNK_SIZE} · overlap={CHUNK_OVERLAP} · "
        f"≈{mean_words} words/chunk · scroll_batch={SCROLL_BATCH}",
        fontsize=10,
    )
    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches="tight")
    print(f"\n→ Graph saved: {OUTPUT_FILE.resolve()}")
    plt.close()
