# -*- coding: utf-8 -*-
"""Branded diagram renderers for the Agentium product document (PIH).

Each function renders one figure to a PNG that matches the deck design system
(navy / blue / green / amber). Diagrams are box-and-arrow schematics drawn with
matplotlib so they carry no external toolchain dependency (no mermaid/graphviz).
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica Neue", "Helvetica", "DejaVu Sans"]

# ---------------------------------------------------------------- palette
NAVY   = "#0B2545"
BLUE   = "#2D6CDF"
PURPLE = "#6D28D9"
GREEN  = "#0E8F62"
AMBER  = "#B45309"
INK    = "#151A23"
MUT    = "#596371"
LINE   = "#D7DCE3"
PANEL  = "#F3F5F8"
WHITE  = "#FFFFFF"
LIGHT  = {NAVY: "#E7ECF4", BLUE: "#E5EDFB", PURPLE: "#EFE8FB",
          GREEN: "#E2F2EC", AMBER: "#F6ECE0", MUT: "#EEF0F3"}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "diagrams")


# ---------------------------------------------------------------- helpers
def _fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.set_xlim(0, w * 10)
    ax.set_ylim(0, h * 10)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig, ax


def _box(ax, cx, cy, w, h, lines, fill=WHITE, edge=LINE, fg=INK, fs=10.5,
         title_fs=None, accent=None, lw=1.0, round_r=2.2):
    """Rounded box centred on (cx, cy). `lines` = str or list[(text, bold, size, color)]."""
    x, y = cx - w / 2, cy - h / 2
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle=f"round,pad=0,rounding_size={round_r}",
                         linewidth=lw, edgecolor=edge, facecolor=fill, zorder=2)
    ax.add_patch(box)
    if accent:
        bar = FancyBboxPatch((x + 0.9, y + 0.9), 0.9, h - 1.8,
                             boxstyle="round,pad=0,rounding_size=0.4",
                             linewidth=0, facecolor=accent, zorder=3)
        ax.add_patch(bar)
    if isinstance(lines, str):
        lines = [(lines, False, fs, fg)]
    # expand embedded newlines into discrete physical lines
    norm = []
    for text, bold, size, color in lines:
        for sub in str(text).split("\n"):
            norm.append((sub, bold, size, color))
    LH = lambda s: s / 6.0          # data units per text line (generous leading)
    LEAD = 0.45
    total = sum(LH(s) for _, _, s, _ in norm) + (len(norm) - 1) * LEAD
    cur = cy + total / 2
    xoff = 0.6 if accent else 0
    for text, bold, size, color in norm:
        cur -= LH(size) / 2
        ax.text(cx + xoff, cur, text, ha="center", va="center",
                fontsize=size, fontweight="bold" if bold else "normal",
                color=color, zorder=4)
        cur -= LH(size) / 2 + LEAD


def _arrow(ax, x1, y1, x2, y2, color=MUT, lw=1.6, style="-|>", rad=0.0, ls="-"):
    a = FancyArrowPatch((x1, y1), (x2, y2),
                        arrowstyle=style, mutation_scale=14, lw=lw,
                        color=color, zorder=1,
                        connectionstyle=f"arc3,rad={rad}", linestyle=ls)
    ax.add_patch(a)


def _kicker(ax, x, y, text, color=NAVY):
    ax.text(x, y, text.upper(), ha="left", va="center", fontsize=9.5,
            color=color, fontweight="bold", family="monospace")


def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.12,
                facecolor=WHITE)
    plt.close(fig)
    return path


# ============================================================ D1 — value loop
def d1_value_loop():
    fig, ax = _fig(13, 3.4)
    steps = [("Objective", "the business intent", BLUE),
             ("System", "capabilities + flow", PURPLE),
             ("Execution", "metered runs", NAVY),
             ("Measurement", "cost · value · quality", GREEN),
             ("Optimization", "governed adaptation", AMBER)]
    n = len(steps)
    w, h = 21, 17
    gap = (130 - n * w) / (n - 1)
    y = 24
    xs = []
    for i, (t, sub, c) in enumerate(steps):
        cx = w / 2 + i * (w + gap)
        xs.append(cx)
        _box(ax, cx, y, w, h, [(t, True, 12.5, c), (sub, False, 9.5, MUT)],
             fill=LIGHT[c], edge=c, accent=c, round_r=2.4)
        if i:
            _arrow(ax, xs[i - 1] + w / 2 + 0.6, y, cx - w / 2 - 0.6, y, color=MUT, lw=1.8)
    # feedback loop from Optimization back to Objective
    _arrow(ax, xs[-1], y - h / 2 - 0.6, xs[0], y - h / 2 - 0.6,
           color=AMBER, lw=1.7, rad=-0.32, style="-|>")
    ax.text((xs[0] + xs[-1]) / 2, 4.0, "continuous improvement loop",
            ha="center", va="center", fontsize=9.5, color=AMBER, style="italic")
    return _save(fig, "d1_value_loop.png")


# ============================================================ D2 — canonical chain + entities
def d2_chain():
    fig, ax = _fig(13, 6.6)
    # main chain
    chain = [("System", BLUE), ("Run", NAVY), ("Evaluation", GREEN),
             ("Decision", PURPLE), ("Action", AMBER)]
    w, h = 20, 13
    gap = (130 - len(chain) * w) / (len(chain) - 1)
    y = 40
    xs = []
    for i, (t, c) in enumerate(chain):
        cx = w / 2 + i * (w + gap)
        xs.append(cx)
        _box(ax, cx, y, w, h, [(t, True, 13, WHITE)], fill=c, edge=c, round_r=2.4)
        if i:
            _arrow(ax, xs[i - 1] + w / 2 + 0.6, y, cx - w / 2 - 0.6, y, color=NAVY, lw=2.0)
    ax.text(65, 58, "The canonical chain", ha="center", fontsize=12.5,
            fontweight="bold", color=INK)
    # composition cluster (feeds System) — above, fanning cleanly into System
    comp = ["Capability", "Skill", "Context", "Policies"]
    cw = 21
    cgap = 3.2
    startx = xs[0] - w / 2
    sys_bottom = (xs[0], y - h / 2 - 0.6)
    for i, t in enumerate(comp):
        cx = startx + cw / 2 + i * (cw + cgap)
        _box(ax, cx, 18, cw, 9, [(t, True, 10.5, INK)], fill=PANEL, edge=LINE,
             accent=BLUE, round_r=2.0)
        rad = (i - 1.5) * 0.07
        _arrow(ax, cx, 22.7, sys_bottom[0], sys_bottom[1], color=MUT, lw=1.1, rad=rad)
    ax.text(startx + (4 * cw + 3 * cgap) / 2 - cw / 2, 9.0,
            "Composition — what a System is built from",
            ha="center", fontsize=9.5, color=MUT, style="italic")
    # ledger note under Run
    _box(ax, xs[1], 64, 30, 7, [("Skill-Invocation ledger", True, 9.5, NAVY),
                                ("every tool-call, metered & traced", False, 8.5, MUT)],
         fill=WHITE, edge=NAVY, round_r=1.8)
    _arrow(ax, xs[1], 60.5, xs[1], y + h / 2 + 0.5, color=NAVY, lw=1.2)
    return _save(fig, "d2_chain.png")


# ============================================================ D3 — execution lifecycle
def d3_lifecycle():
    fig, ax = _fig(13, 4.6)
    phases = [("1 Initialize", "resolve objective,\ncompile flow", BLUE),
              ("2 Plan", "select skills\n& order", PURPLE),
              ("3 Execute", "invoke skills,\nstream output", NAVY),
              ("4 Observe", "capture metrics,\ncost, latency", GREEN),
              ("5 Evaluate", "score vs.\nsuccess criteria", GREEN),
              ("6 Adapt", "switch model,\nescalate, retry", AMBER)]
    n = len(phases)
    w, h = 18, 16
    gap = (130 - n * w) / (n - 1)
    y = 34
    xs = []
    for i, (t, sub, c) in enumerate(phases):
        cx = w / 2 + i * (w + gap)
        xs.append(cx)
        _box(ax, cx, y, w, h, [(t, True, 11, c), (sub, False, 8.7, MUT)],
             fill=LIGHT[c], edge=c, accent=c, round_r=2.2)
        if i:
            _arrow(ax, xs[i - 1] + w / 2 + 0.5, y, cx - w / 2 - 0.5, y, color=MUT, lw=1.7)
    # adaptive feedback from Adapt back to Plan
    _arrow(ax, xs[-1], y - h / 2 - 0.5, xs[1], y - h / 2 - 0.5,
           color=AMBER, lw=1.7, rad=-0.28)
    ax.text((xs[1] + xs[-1]) / 2, 11.5, "adaptive feedback (governed by policy)",
            ha="center", fontsize=9.3, color=AMBER, style="italic")
    return _save(fig, "d3_lifecycle.png")


# ============================================================ D4 — answer pipeline (serpentine 3+3)
def d4_pipeline():
    fig, ax = _fig(13, 6.2)
    stages = [("1 · Indexing", "parse · OCR · chunk\nembed · hash", BLUE),
              ("2 · Storage", "vectors · keyword index\nfacts · originals", BLUE),
              ("3 · Query Resolution", "intent · memory\nlatency profile", PURPLE),
              ("4 · Multi-Source Retrieval", "dense + sparse + exact\nweighted fusion", NAVY),
              ("5 · Ranking & Refinement", "rerank · filter\ncompress · diversify", GREEN),
              ("6 · Generation & Grounding", "grounded answer\ncitations · streaming", AMBER)]
    w, h = 33, 16
    col_x = [26, 65, 104]
    row_y = [46, 16]
    pos = []
    for idx, (t, sub, c) in enumerate(stages):
        row = idx // 3
        col = idx % 3 if row == 0 else (2 - idx % 3)  # serpentine
        cx, cy = col_x[col], row_y[row]
        pos.append((cx, cy))
        _box(ax, cx, cy, w, h, [(t, True, 10.5, c), (sub, False, 8.7, MUT)],
             fill=LIGHT[c], edge=c, accent=c, round_r=2.2)
    # arrows along serpentine path in stage order
    order_xy = pos
    for i in range(1, len(order_xy)):
        (x1, y1), (x2, y2) = order_xy[i - 1], order_xy[i]
        if abs(y1 - y2) < 1:  # same row horizontal
            if x2 > x1:
                _arrow(ax, x1 + w / 2 + 0.5, y1, x2 - w / 2 - 0.5, y2, color=MUT, lw=1.7)
            else:
                _arrow(ax, x1 - w / 2 - 0.5, y1, x2 + w / 2 + 0.5, y2, color=MUT, lw=1.7)
        else:  # drop to next row (right edge -> right edge)
            _arrow(ax, x1, y1 - h / 2 - 0.5, x2, y2 + h / 2 + 0.5, color=MUT, lw=1.7, rad=-0.3)
    return _save(fig, "d4_pipeline.png")


# ============================================================ D5 — sovereign deployment
def d5_deployment():
    fig, ax = _fig(13, 7.2)
    # sovereign boundary
    bound = FancyBboxPatch((3, 4), 124, 64,
                           boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.6, edgecolor=NAVY, facecolor="#FAFBFD",
                           linestyle=(0, (6, 4)), zorder=0)
    ax.add_patch(bound)
    ax.text(65, 71.5, "Sovereign boundary — runs entirely on customer infrastructure",
            ha="center", fontsize=10.5, color=NAVY, fontweight="bold")

    def layer(cy, label, items, c):
        ax.text(8, cy, label, ha="left", va="center", fontsize=8.6,
                color=MUT, family="monospace", rotation=0)
        bw = 30
        gap = 4
        startx = 30
        for i, it in enumerate(items):
            cx = startx + bw / 2 + i * (bw + gap)
            _box(ax, cx, cy, bw, 8.5, [(it, True, 9.6, INK)],
                 fill=LIGHT[c], edge=c, accent=c, round_r=1.8)

    layer(61, "experience", ["Cockpit (Hypervisor · Steering)", "API gateway (FastAPI · SSE)"], BLUE)
    layer(49.5, "orchestration", ["Run engine + Skill registry", "Policies · Evaluation"], PURPLE)
    layer(38, "model plane", ["On-prem model serving", "Multi-provider router"], NAVY)
    layer(26.5, "data plane", ["Vector store", "Relational ledger"], GREEN)
    # cross-cutting side column
    _box(ax, 112, 49.5, 26, 30, [("IAM — Keycloak / OIDC", True, 9.2, AMBER),
                                 ("", False, 3, MUT),
                                 ("Async workers", True, 9.2, AMBER),
                                 ("", False, 3, MUT),
                                 ("Audit & observability", True, 9.2, AMBER)],
         fill=LIGHT[AMBER], edge=AMBER, accent=AMBER, round_r=2.0)
    layer(15, "storage", ["Object store (documents)", "Backups · artifacts"], GREEN)
    # vertical flow arrows
    for cy1, cy2 in [(61, 49.5), (49.5, 38), (38, 26.5), (26.5, 15)]:
        _arrow(ax, 65, cy1 - 4.3, 65, cy2 + 4.3, color=MUT, lw=1.3)
    return _save(fig, "d5_deployment.png")


# ============================================================ D6 — PIH alignment
def d6_alignment():
    fig, ax = _fig(13, 6.8)
    needs = [("Sovereignty", NAVY),
             ("Robustness", BLUE),
             ("Security", PURPLE),
             ("Observability\n& Scalability", GREEN),
             ("Token\nPerformance", AMBER)]
    caps = ["On-prem model serving & router",
            "Stateful runs · replay · resubmission",
            "RBAC + ABAC · agent identity · guardrails",
            "Tool-call ledger · audit · async scale",
            "Deterministic generation budget & fusion"]
    nh = len(needs)
    top, bot = 60, 8
    ys = [top - i * (top - bot) / (nh - 1) for i in range(nh)]
    lx, rx = 26, 104
    lw_, rw = 30, 46
    for i, ((t, c), cap, y) in enumerate(zip(needs, caps, ys)):
        _box(ax, lx, y, lw_, 9.5, [(t, True, 10.5, WHITE)], fill=c, edge=c, round_r=2.0)
        _box(ax, rx, y, rw, 9.5, [(cap, False, 9.3, INK)], fill=LIGHT[c], edge=c,
             accent=c, round_r=2.0)
        _arrow(ax, lx + lw_ / 2 + 0.6, y, rx - rw / 2 - 0.6, y, color=c, lw=1.7)
    ax.text(lx, top + 8, "PIH need", ha="center", fontsize=10, fontweight="bold", color=INK)
    ax.text(rx, top + 8, "Agentium capability", ha="center", fontsize=10,
            fontweight="bold", color=INK)
    return _save(fig, "d6_alignment.png")


# ============================================================ D7 — engineering foundation
def d7_foundation():
    fig, ax = _fig(13, 5.8)
    bound = FancyBboxPatch((3, 3), 124, 50,
                           boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.6, edgecolor=NAVY, facecolor="#FAFBFD",
                           linestyle=(0, (6, 4)), zorder=0)
    ax.add_patch(bound)
    ax.text(65, 50.6,
            "Sovereign boundary — open-source foundation, proprietary orchestration, fully on-premisable",
            ha="center", fontsize=10, color=NAVY, fontweight="bold")

    def band(cy, h, label, c, chips, chip_fs=8.0):
        b = FancyBboxPatch((24, cy - h / 2), 98, h,
                           boxstyle="round,pad=0,rounding_size=2",
                           linewidth=1.0, edgecolor=c, facecolor=LIGHT[c], zorder=1)
        ax.add_patch(b)
        ax.text(11.5, cy, label, ha="center", va="center", fontsize=7.8, color=c,
                family="monospace", fontweight="bold", rotation=90)
        n = len(chips)
        span, x0 = 94, 26
        cw = min(15.5, (span - (n - 1) * 2) / n)
        gap = (span - n * cw) / (n - 1) if n > 1 else 0
        for i, t in enumerate(chips):
            cx = x0 + cw / 2 + i * (cw + gap)
            _box(ax, cx, cy, cw, h * 0.56, [(t, True, chip_fs, c)],
                 fill=WHITE, edge=c, round_r=1.1)

    band(43, 9, "PRODUCT", BLUE,
         ["Cockpit", "API · SSE", "Chat + citations"], 9)
    band(28, 13.5, "AGENTIUM", PURPLE,
         ["Run engine", "Deterministic\ntoken budget", "Adaptive\nfusion",
          "Evaluation\nloop", "RBAC + ABAC", "Tool-call\nledger"], 7.4)
    band(13, 9, "FOUNDATION", GREEN,
         ["FastAPI", "PostgreSQL", "Qdrant", "Keycloak", "Celery /\nRabbitMQ",
          "vLLM /\nOllama", "Cross-\nencoder", "BM25 · RRF"], 7.2)
    return _save(fig, "d7_foundation.png")


ALL = [d1_value_loop, d2_chain, d3_lifecycle, d4_pipeline, d5_deployment,
       d6_alignment, d7_foundation]


def render_all():
    paths = [fn() for fn in ALL]
    for p in paths:
        print("rendered:", os.path.relpath(p))
    return paths


if __name__ == "__main__":
    render_all()
