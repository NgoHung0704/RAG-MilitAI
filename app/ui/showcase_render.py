"""
Gold-vs-result renderers for the Showcase (Demo Interface Spec v0.2 §7).

The renderer keys off the gold's ``result_kind``:

  rid_set / rag_target / false_merge / trajectory / record_fields / disambiguation
        -> row_set      : table of records; on reveal mark matched/missing/extra
  histogram / histogram_pair
        -> histogram    : bar chart, gold vs produced, with L1 error
  partition
        -> partition    : family clusters; planted vs recovered
  linkage
        -> link_map     : the linked father record (or "none")
  aggregate / aggregate_pair / count
        -> scalar/mean_n: the number (+ n), and whether within tolerance

Every function takes the system value for the shown condition and (optionally)
the COMPLETE truth, plus the corpus DataFrames needed to resolve row indices
(``rid``) to readable records.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

# row-index → record kinds that render as a table of soldiers
ROW_SET_KINDS = {
    "rid_set", "rag_target", "false_merge", "trajectory",
    "record_fields", "disambiguation",
}
HISTOGRAM_KINDS = {"histogram", "histogram_pair"}
SCALAR_KINDS = {"aggregate", "aggregate_pair", "count"}

DISPLAY_COLS = [
    "nom", "prenom", "surnom", "compagnie", "regiment",
    "naissance_lieu", "naissance_departement", "naissance_annee", "deces_annee",
]


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def load_corpus_df(csv_path: str) -> pd.DataFrame:
    """Load a corpus CSV (all-string cells, '' for absent) keyed by rid."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return df.reset_index(drop=True)


def _rows(df: pd.DataFrame, rids, status: str | None = None) -> pd.DataFrame:
    cols = [c for c in DISPLAY_COLS if c in df.columns]
    out = []
    for rid in rids:
        if 0 <= rid < len(df):
            rec = {"rid": rid}
            if status:
                rec["status"] = status
            for c in cols:
                rec[c] = df.at[rid, c]
            out.append(rec)
    return pd.DataFrame(out)


def _as_rid_list(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, dict):  # partition / aggregate handled elsewhere
        return []
    return [int(r) for r in value]


# --------------------------------------------------------------------------- #
# row_set                                                                      #
# --------------------------------------------------------------------------- #

def render_row_set(system, truth, df_active, df_truth, revealed: bool) -> None:
    sys_rids = _as_rid_list(system)

    st.caption(f"System returned **{len(sys_rids)}** record(s).")
    if sys_rids:
        st.dataframe(_rows(df_active, sys_rids), use_container_width=True, hide_index=True)
    else:
        st.info("No records returned.")

    if not revealed:
        return

    truth_rids = _as_rid_list(truth)
    matched = [r for r in sys_rids if r in truth_rids]
    missing = [r for r in truth_rids if r not in sys_rids]
    extra = [r for r in sys_rids if r not in truth_rids]
    exact = not missing and not extra

    st.markdown("---")
    if exact:
        st.success(f"✓ Exact match — {len(matched)}/{len(truth_rids)} expected records.")
    else:
        st.warning(
            f"✗ {len(matched)}/{len(truth_rids)} expected · "
            f"{len(missing)} missing · {len(extra)} extra."
        )
    if missing:
        st.markdown("**Missing (in gold, not found):**")
        st.dataframe(_rows(df_truth, missing, "missing"), use_container_width=True, hide_index=True)
    if extra:
        st.markdown("**Extra (found, not in gold):**")
        st.dataframe(_rows(df_active, extra, "extra"), use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# histogram                                                                    #
# --------------------------------------------------------------------------- #

def _l1(a: dict, b: dict) -> int:
    keys = set(a) | set(b)
    return sum(abs(int(a.get(k, 0)) - int(b.get(k, 0))) for k in keys)


def _flatten_hist(value) -> dict:
    """histogram -> {bucket: n}; histogram_pair -> {group/bucket: n}."""
    if not isinstance(value, dict):
        return {}
    if value and all(isinstance(v, dict) for v in value.values()):
        flat = {}
        for group, hist in value.items():
            for bucket, n in hist.items():
                flat[f"{group} · {bucket}"] = n
        return flat
    return dict(value)


def render_histogram(system, truth, df_active, df_truth, revealed: bool) -> None:
    produced = _flatten_hist(system)
    st.caption("Distribution produced by the system:")
    if produced:
        st.bar_chart(pd.Series(produced, name="produced"))
    else:
        st.info("Empty distribution.")

    if not revealed:
        return

    gold = _flatten_hist(truth)
    st.markdown("---")
    keys = sorted(set(produced) | set(gold))
    comp = pd.DataFrame(
        {"gold": [gold.get(k, 0) for k in keys],
         "produced": [produced.get(k, 0) for k in keys]},
        index=keys,
    )
    st.bar_chart(comp)
    l1 = _l1(produced, gold)
    if l1 == 0:
        st.success("✓ Exact match with gold distribution (L1 = 0).")
    else:
        st.warning(f"✗ L1 error vs gold = {l1}.")


# --------------------------------------------------------------------------- #
# partition                                                                    #
# --------------------------------------------------------------------------- #

def _names(df, rids) -> str:
    out = []
    for rid in rids:
        if 0 <= rid < len(df):
            out.append(f"{df.at[rid, 'prenom']} {df.at[rid, 'nom']} (#{rid})")
    return ", ".join(out)


def render_partition(system, truth, df_active, df_truth, revealed: bool) -> None:
    clusters = system if isinstance(system, dict) else {}
    st.caption(f"System recovered **{len(clusters)}** family cluster(s):")
    for name, rids in clusters.items():
        st.markdown(f"- **{name}** — {_names(df_active, rids)}")

    if not revealed:
        return

    gold = truth if isinstance(truth, dict) else {}
    st.markdown("---")
    st.markdown("**Planted families (gold):**")
    for name, rids in gold.items():
        recovered = clusters.get(name)
        mark = "✓" if recovered == rids else "✗"
        st.markdown(f"- {mark} **{name}** — {_names(df_truth, rids)}")
    if clusters == gold:
        st.success("✓ Every planted family recovered exactly; no false merge.")
    else:
        st.warning("✗ Recovered partition differs from the planted families.")


# --------------------------------------------------------------------------- #
# linkage / link_map                                                           #
# --------------------------------------------------------------------------- #

def render_link_map(system, truth, df_active, df_truth, revealed: bool) -> None:
    if system is None:
        st.caption("System linked **no** father record (candidate score below threshold).")
    else:
        st.caption("System's best father candidate:")
        st.dataframe(_rows(df_active, [int(system)]), use_container_width=True, hide_index=True)

    if not revealed:
        return

    st.markdown("---")
    if truth is None:
        st.info("Gold: **no** father record should be linked (none planted / corroborated).")
        ok = system is None
    else:
        st.markdown("**Gold father record:**")
        st.dataframe(_rows(df_truth, [int(truth)]), use_container_width=True, hide_index=True)
        ok = system is not None and int(system) == int(truth)
    st.success("✓ Linkage matches gold.") if ok else st.warning("✗ Linkage differs from gold.")


# --------------------------------------------------------------------------- #
# scalar / mean_n / count                                                      #
# --------------------------------------------------------------------------- #

def _fmt_scalar(value) -> str:
    if not isinstance(value, dict):
        return str(value)
    if "count" in value:
        return f"count = {value['count']}"
    parts = []
    if "mean_metre" in value:
        mm = value["mean_metre"]
        parts.append("mean = " + ("—" if mm is None else f"{float(mm):.3f} m"))
    if "mean_cm" in value:
        parts.append(f"mean = {value['mean_cm']} cm")
    if "n" in value:
        parts.append(f"n = {value['n']}")
    return " · ".join(parts) if parts else str(value)


def render_scalar(system, truth, df_active, df_truth, revealed: bool, tol: float = 0.02) -> None:
    if isinstance(system, dict) and all(isinstance(v, dict) for v in system.values()):
        # aggregate_pair: per-group scalars
        for group, val in system.items():
            st.metric(group, _fmt_scalar(val))
    else:
        st.metric("System result", _fmt_scalar(system))

    if not revealed:
        return

    st.markdown("---")
    st.markdown(f"**Gold:** {_render_scalar_truth(truth)}")
    if _scalar_matches(system, truth, tol):
        st.success("✓ Within tolerance of gold.")
    else:
        st.warning("✗ Differs from gold (note the smaller n under MASKED).")


def _render_scalar_truth(truth) -> str:
    if isinstance(truth, dict) and all(isinstance(v, dict) for v in truth.values()):
        return " | ".join(f"{g}: {_fmt_scalar(v)}" for g, v in truth.items())
    return _fmt_scalar(truth)


def _scalar_matches(system, truth, tol: float) -> bool:
    def one(a, b) -> bool:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return a == b
        if "count" in a or "count" in b:
            return a.get("count") == b.get("count")
        am, bm = a.get("mean_metre"), b.get("mean_metre")
        if am is None or bm is None:
            return am == bm
        return abs(float(am) - float(bm)) <= tol

    if isinstance(system, dict) and isinstance(truth, dict) \
            and all(isinstance(v, dict) for v in {**system, **truth}.values()):
        keys = set(system) | set(truth)
        return all(one(system.get(k), truth.get(k)) for k in keys)
    return one(system, truth)


# --------------------------------------------------------------------------- #
# dispatch                                                                     #
# --------------------------------------------------------------------------- #

def render_result(
    result_kind: str,
    system,
    truth,
    df_active: pd.DataFrame,
    df_truth: pd.DataFrame,
    revealed: bool,
) -> None:
    """Render *system* (and, when revealed, *truth*) for the given result_kind."""
    if result_kind in ROW_SET_KINDS:
        render_row_set(system, truth, df_active, df_truth, revealed)
    elif result_kind in HISTOGRAM_KINDS:
        render_histogram(system, truth, df_active, df_truth, revealed)
    elif result_kind == "partition":
        render_partition(system, truth, df_active, df_truth, revealed)
    elif result_kind == "linkage":
        render_link_map(system, truth, df_active, df_truth, revealed)
    elif result_kind in SCALAR_KINDS:
        render_scalar(system, truth, df_active, df_truth, revealed)
    else:
        st.write(system)
        if revealed:
            st.markdown("**Gold:**")
            st.write(truth)
