"""Per-use-case accuracy under COMPLETE vs MASKED.

Reads the eval `results.json` and draws mean headline score per use case,
COMPLETE vs MASKED, for one engine. MASKED simulates the real corpus's sparsity
(gold fields blanked out), so the gap between the two conditions shows which
analyses survive that sparsity and which collapse.

Three styles:
  * ``bar``        — grouped bars, one engine (default for --style).
  * ``dumbbell``   — horizontal COMPLETE→MASKED dumbbell, one engine
                     (this is paper Figure 2; saved to specs/militai_fig2.png).
  * per-engine     — faceted dumbbell, one panel per engine (--per-engine).

By default we plot the live `nl2cypher` engine: `reference` is the oracle and
sits at 1.0 everywhere by construction, while `template` only covers a couple of
use cases. Pass --engine to override.

Records with status `n/a` or `skipped` are not applicable to the engine and are
dropped; `query_error` / `unparseable` count as 0.0 (they carry score 0).

Usage:
    uv run python -m validation.eval.plot_usecase_accuracy                  # bar, nl2cypher
    uv run python -m validation.eval.plot_usecase_accuracy --style dumbbell  # Figure 2
    uv run python -m validation.eval.plot_usecase_accuracy --per-engine      # faceted
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# Fixed semantic order: lookup -> multi-hop -> aggregation strata.
USE_CASE_ORDER = [
    "lookup",
    "bounded",
    "genealogy",
    "migration",
    "mechanics",
    "anthropometric",
]
CONDITIONS = ["COMPLETE", "MASKED"]
COLOURS = {"COMPLETE": "#2b7bba", "MASKED": "#e8632a"}
COND_LABEL = {
    "COMPLETE": "COMPLETE (engine accuracy)",
    "MASKED": "MASKED (under real sparsity)",
}
# `reference` is the oracle (1.0 everywhere by construction) — it carries no
# real engine signal, so it is excluded from the per-engine comparison by
# default. Pass --engines to override.
LIVE_ENGINES = ["template", "nl2cypher"]

DEFAULT_RESULTS = Path("validation/corpus/eval/results.json")
DEFAULT_OUT = Path("validation/corpus/eval/usecase_accuracy.png")
FIG2_OUT = Path("specs/militai_fig2.png")
PER_ENGINE_OUT = Path("validation/corpus/eval/usecase_accuracy_by_engine.png")


def _applicable(rec: dict) -> bool:
    """Applicable rows carry a score; n/a and skipped rows do not."""
    return "score" in rec


def aggregate(records: list[dict], engine: str):
    """Return {use_case: {condition: (mean_score, n)}} for one engine."""
    bucket: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {c: [] for c in CONDITIONS}
    )
    for rec in records:
        if rec["engine"] != engine or not _applicable(rec):
            continue
        cond = rec["condition"]
        if cond not in CONDITIONS:
            continue
        bucket[rec["use_case"]][cond].append(rec["score"])

    out: dict[str, dict[str, tuple[float, int]]] = {}
    for uc, conds in bucket.items():
        out[uc] = {
            c: (sum(v) / len(v), len(v)) if v else (float("nan"), 0)
            for c, v in conds.items()
        }
    return out


def plot(agg, engine: str, out_path: Path) -> None:
    use_cases = [uc for uc in USE_CASE_ORDER if uc in agg]
    use_cases += [uc for uc in agg if uc not in USE_CASE_ORDER]

    x = range(len(use_cases))
    width = 0.38

    fig, ax = plt.subplots(figsize=(10, 5.6))

    for i, cond in enumerate(CONDITIONS):
        offset = (i - 0.5) * width
        heights = [agg[uc][cond][0] for uc in use_cases]
        ns = [agg[uc][cond][1] for uc in use_cases]
        bars = ax.bar(
            [xi + offset for xi in x],
            heights,
            width,
            label=cond,
            color=COLOURS[cond],
            edgecolor="white",
            linewidth=0.6,
        )
        for rect, h, n in zip(bars, heights, ns):
            if n == 0:
                continue
            ax.annotate(
                f"{h:.2f}\nn={n}",
                (rect.get_x() + rect.get_width() / 2, h),
                textcoords="offset points",
                xytext=(0, 3),
                ha="center",
                va="bottom",
                fontsize=8,
                color="#333333",
            )

    # Oracle ceiling: reference engine is 1.0 everywhere by construction.
    ax.axhline(1.0, ls="--", lw=1, color="#888888", zorder=0)
    ax.text(
        len(use_cases) - 0.5,
        1.012,
        "reference oracle ceiling (1.0)",
        ha="right",
        va="bottom",
        fontsize=8,
        color="#888888",
    )

    ax.set_xticks(list(x))
    ax.set_xticklabels(use_cases, fontsize=10)
    ax.set_ylim(0, 1.15)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(0.25))
    ax.set_ylabel("Mean headline score (accuracy)")
    ax.set_title(
        f"Per-use-case accuracy — {engine} engine: COMPLETE vs MASKED\n"
        "MASKED blanks gold fields to emulate the real corpus's sparsity",
        fontsize=12,
    )
    ax.legend(title="condition", loc="lower left", framealpha=0.9)
    ax.grid(axis="y", ls=":", lw=0.5, color="#cccccc", zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def _order_by_complete(agg) -> list[str]:
    """Use cases sorted by COMPLETE accuracy descending (preview convention)."""

    def key(uc: str) -> float:
        v = agg[uc]["COMPLETE"][0]
        return -1.0 if v != v else v  # NaN -> bottom

    return sorted(agg, key=key, reverse=True)


def _total_n(agg_uc) -> int:
    """Applicable rows across both conditions (matches the preview's n=)."""
    return sum(agg_uc[c][1] for c in CONDITIONS)


def _draw_dumbbell(
    ax, agg, order, *, label_pct=True, annotate_delta=True, show_n=True, ceiling=None
):
    """Draw one engine's COMPLETE->MASKED dumbbell onto `ax`.

    Returns the y-tick labels so callers can reuse them. Accuracy is plotted on
    a 0-100 percent scale. `show_n` appends each use case's applicable row count
    (drop it when panels share one y-axis but differ in coverage per engine).
    `ceiling` (0-1) draws a faint dashed vertical line — the reference oracle
    accuracy — so each engine's gap to the ceiling is visible.
    """
    if ceiling is not None:
        ax.axvline(ceiling * 100, ls="--", lw=1, color="#9a9a9a", zorder=0)
    ylabels = []
    for row, uc in enumerate(order):
        y = len(order) - 1 - row  # first item on top
        comp = agg[uc]["COMPLETE"][0]
        mask = agg[uc]["MASKED"][0]
        label = uc.capitalize() + (f"  (n={_total_n(agg[uc])})" if show_n else "")
        ylabels.append((y, label))

        have = comp == comp and mask == mask  # not NaN
        if have:
            ax.plot(
                [comp * 100, mask * 100], [y, y],
                color="#b8b8b8", lw=4, solid_capstyle="round", zorder=1,
            )
        for cond, val in (("COMPLETE", comp), ("MASKED", mask)):
            if val != val:
                continue
            ax.scatter(
                val * 100, y, s=130, color=COLOURS[cond],
                edgecolor="#2b2b2b", linewidth=1.1, zorder=3,
            )
        if annotate_delta and have:
            delta = mask - comp
            sign = "+" if delta >= 0 else "−"
            ax.annotate(
                f"{sign}{abs(delta):.2f}",
                (max(comp, mask) * 100, y),
                textcoords="offset points", xytext=(10, 0),
                va="center", ha="left", fontsize=9, color="#666666",
            )

    ax.set_yticks([y for y, _ in ylabels])
    ax.set_yticklabels([lab for _, lab in ylabels])
    ax.set_xlim(-4, 116)
    ax.set_ylim(-0.6, len(order) - 0.4)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(25))
    if label_pct:
        ax.set_xlabel("Accuracy (%)")
    ax.grid(axis="x", ls=":", lw=0.6, color="#dddddd", zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(left=False)
    return ylabels


def _dumbbell_legend(fig_or_ax, loc="upper right", *, ceiling=False, **kw):
    handles = [
        plt.Line2D(
            [], [], marker="o", linestyle="none", markersize=11,
            markerfacecolor=COLOURS[c], markeredgecolor="#2b2b2b",
            label=COND_LABEL[c],
        )
        for c in CONDITIONS
    ]
    if ceiling:
        handles.append(
            plt.Line2D(
                [], [], ls="--", lw=1, color="#9a9a9a",
                label="reference oracle (1.0)",
            )
        )
    fig_or_ax.legend(handles=handles, loc=loc, frameon=False, fontsize=10, **kw)


def plot_dumbbell(agg, engine: str, out_path: Path) -> None:
    order = _order_by_complete(agg)
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    _draw_dumbbell(ax, agg, order)
    _dumbbell_legend(ax, loc="lower right")
    ax.set_title(
        f"Per-use-case accuracy — {engine}: COMPLETE vs MASKED",
        fontsize=12, pad=10,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    print(f"wrote {out_path}")


def _oracle_ceiling(records) -> float | None:
    """Reference accuracy as a single ceiling, if it is uniform (it is 1.0)."""
    ref = aggregate(records, "reference")
    if not ref:
        return None
    vals = [ref[uc][c][0] for uc in ref for c in CONDITIONS]
    vals = [v for v in vals if v == v]  # drop NaN
    return vals[0] if vals and max(vals) - min(vals) < 1e-9 else None


def build_per_engine_figure(records, engines, *, suptitle=True):
    """Build the faceted per-engine dumbbell and return the matplotlib Figure.

    One panel per engine, shared use-case order/x-axis. `reference` is excluded
    as a panel (flat oracle); its accuracy is drawn as a dashed ceiling line in
    every panel instead. Returns ``None`` if no engine has applicable rows.

    Pure (no disk I/O) so it can be embedded directly in the GUI via
    ``st.pyplot`` as well as saved to a file by :func:`plot_per_engine`.
    """
    ceiling = _oracle_ceiling(records)
    aggs = {e: aggregate(records, e) for e in engines}
    aggs = {e: a for e, a in aggs.items() if a}
    engines = [e for e in engines if e in aggs]
    if not engines:
        return None

    # Consistent y-order across panels: by the live engine's COMPLETE, else union.
    ref = "nl2cypher" if "nl2cypher" in aggs else engines[-1]
    base_order = _order_by_complete(aggs[ref])
    order = base_order + [
        uc for a in aggs.values() for uc in a if uc not in base_order
    ]
    order = list(dict.fromkeys(order))

    fig, axes = plt.subplots(
        1, len(engines), figsize=(5.6 * len(engines), 4.4),
        sharex=True, sharey=True,
    )
    if len(engines) == 1:
        axes = [axes]

    for ax, eng in zip(axes, engines):
        agg = aggs[eng]
        # Pad missing use cases so every panel shares the same rows.
        padded = {
            uc: agg.get(uc, {c: (float("nan"), 0) for c in CONDITIONS})
            for uc in order
        }
        # n differs per engine, so drop the per-row n and put applicable
        # question count (COMPLETE rows) in the panel title instead.
        n_q = sum(agg[uc]["COMPLETE"][1] for uc in agg)
        _draw_dumbbell(ax, padded, order, show_n=False, ceiling=ceiling)
        ax.set_title(f"{eng}  (n={n_q})", fontsize=12)

    for ax in axes[1:]:
        ax.tick_params(labelleft=False)

    _dumbbell_legend(
        fig, loc="lower center", ncol=3, bbox_to_anchor=(0.5, 0.0),
        columnspacing=2.5, ceiling=ceiling is not None,
    )
    if suptitle:
        fig.suptitle(
            "Per-use-case accuracy by engine: COMPLETE vs MASKED (under real sparsity)",
            fontsize=13,
        )
    # Reserve a bottom strip for the shared legend so it never overlaps a panel.
    fig.tight_layout(rect=(0, 0.12, 1, 0.95 if suptitle else 1.0))
    return fig


def plot_per_engine(records, engines, out_path: Path) -> None:
    """Render the faceted per-engine dumbbell to ``out_path``."""
    fig = build_per_engine_figure(records, engines)
    if fig is None:
        raise SystemExit("no applicable records for any requested engine")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    print(f"wrote {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--engine", default="nl2cypher")
    ap.add_argument("--style", choices=["bar", "dumbbell"], default="bar")
    ap.add_argument(
        "--per-engine", action="store_true",
        help="faceted dumbbell, one panel per engine (ignores --engine/--style)",
    )
    ap.add_argument(
        "--engines", default=",".join(LIVE_ENGINES),
        help="comma-separated engine panels for --per-engine "
        "(reference is shown as a ceiling line, not a panel)",
    )
    ap.add_argument(
        "--out", type=Path, default=None,
        help="output path; defaults depend on mode",
    )
    args = ap.parse_args()

    records = json.loads(args.results.read_text(encoding="utf-8"))

    if args.per_engine:
        engines = [e.strip() for e in args.engines.split(",") if e.strip()]
        plot_per_engine(records, engines, args.out or PER_ENGINE_OUT)
        return

    agg = aggregate(records, args.engine)
    if not agg:
        raise SystemExit(f"no applicable records for engine {args.engine!r}")

    if args.style == "dumbbell":
        default = FIG2_OUT if args.engine == "nl2cypher" else DEFAULT_OUT
        plot_dumbbell(agg, args.engine, args.out or default)
    else:
        plot(agg, args.engine, args.out or DEFAULT_OUT)


if __name__ == "__main__":
    main()
