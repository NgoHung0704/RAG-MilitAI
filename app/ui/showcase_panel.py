"""
Showcase panel (Demo Interface Spec v0.2 §4,5,7,8).

Guided tour + gallery over the curated example registry. Each example: show the
question, Run it (deterministic cached gold for the condition, with an optional
live NL2Cypher translation overlaid when the instance + API are up), Reveal the
hidden gold with a ✓/✗ indicator, and — on synthetic datasets — Compare
COMPLETE vs MASKED side-by-side. On the real dataset there is no gold, so the
reveal is replaced by a document→record provenance view.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.showcase_loader import group_by_use_case, load_showcase
from app.ui import showcase_render as sr


# --------------------------------------------------------------------------- #
# entry point                                                                  #
# --------------------------------------------------------------------------- #

def render_panel(config) -> None:
    active = st.session_state.get("active_dataset", config.DEFAULT_DATASET)
    ds = config.get_dataset(active)

    st.header("Showcase — guided demo")

    if not ds["has_gold"]:
        _render_provenance(config, ds)
        return

    examples = load_showcase()
    if not examples:
        st.warning(
            "No showcase examples loaded. Check `showcase.yaml` and the synthetic "
            "corpus under `validation/corpus/`."
        )
        return

    st.caption(
        "Synthetic dataset with hidden gold. Pose the question, Run it, then "
        "Reveal the expected answer — or Compare COMPLETE vs MASKED to see the "
        "cost of annotation."
    )

    # language + navigation mode
    cols = st.columns([1, 2])
    with cols[0]:
        lang = st.radio("Language", ["en", "fr"], horizontal=True, key="showcase_lang")
    with cols[1]:
        mode = st.radio(
            "Navigation", ["Guided tour", "Gallery"], horizontal=True, key="showcase_nav"
        )

    st.markdown("---")
    if mode == "Guided tour":
        _render_tour(examples, config, ds, lang)
    else:
        _render_gallery(examples, config, ds, lang)


# Streamlit-friendly alias used by main.py (kept distinct from the `sr` render module)
def render(config) -> None:
    render_panel(config)


# --------------------------------------------------------------------------- #
# navigation                                                                   #
# --------------------------------------------------------------------------- #

def _render_tour(examples, config, ds, lang) -> None:
    idx = st.session_state.get("tour_idx", 0)
    idx = max(0, min(idx, len(examples) - 1))

    ex = examples[idx]
    nav = st.columns([1, 3, 1])
    with nav[0]:
        if st.button("◀ Prev", disabled=idx == 0, use_container_width=True):
            st.session_state["tour_idx"] = idx - 1
            st.rerun()
    with nav[1]:
        st.markdown(
            f"<div style='text-align:center'>Step <b>{idx + 1}</b> / {len(examples)} "
            f"· {ex.use_case}</div>",
            unsafe_allow_html=True,
        )
    with nav[2]:
        if st.button("Next ▶", disabled=idx == len(examples) - 1, use_container_width=True):
            st.session_state["tour_idx"] = idx + 1
            st.rerun()

    st.markdown("---")
    _render_card(ex, config, ds, lang, key_prefix=f"tour_{idx}")


def _render_gallery(examples, config, ds, lang) -> None:
    groups = group_by_use_case(examples)
    for use_case, items in groups.items():
        st.subheader(use_case.capitalize())
        for ex in items:
            with st.expander(f"{ex.title}  ·  {ex.question_id}", expanded=False):
                _render_card(ex, config, ds, lang, key_prefix=f"gal_{ex.id}")


# --------------------------------------------------------------------------- #
# example card                                                                 #
# --------------------------------------------------------------------------- #

def _render_card(ex, config, ds, lang, key_prefix: str) -> None:
    st.markdown(f"### {ex.title}")
    st.markdown(f"> **{ex.text(lang)}**")
    if ex.narrative:
        st.caption(ex.narrative.strip())

    can_compare = ex.compare and ds["key"] in config.SYNTH_DATASETS
    compare = False
    if can_compare:
        compare = st.toggle(
            "Compare COMPLETE vs MASKED", key=f"{key_prefix}_cmp"
        )

    run = st.button("▶ Run", type="primary", key=f"{key_prefix}_run")
    if run:
        st.session_state[f"{key_prefix}_ran"] = True
    ran = st.session_state.get(f"{key_prefix}_ran", False)
    if not ran:
        return

    reveal = False
    if ex.reveal_gold:
        reveal = st.toggle("Reveal expected answer", key=f"{key_prefix}_reveal")

    df_complete = sr.load_corpus_df(config.get_dataset("synth_complete")["csv"])
    df_masked = sr.load_corpus_df(config.get_dataset("synth_masked")["csv"])

    if compare:
        _render_compare(ex, df_complete, df_masked, reveal)
    else:
        condition = ds.get("condition", "complete")
        df_active = df_complete if condition == "complete" else df_masked
        system = ex.gold_for(condition)
        truth = ex.gold_for("complete")
        _maybe_live_overlay(ex, config, ds, lang, key_prefix)
        sr.render_result(
            ex.result_kind, system, truth, df_active, df_complete, reveal
        )


def _render_compare(ex, df_complete, df_masked, reveal) -> None:
    truth = ex.gold_for("complete")
    left, right = st.columns(2)
    with left:
        st.markdown("#### COMPLETE")
        sr.render_result(
            ex.result_kind, ex.gold_for("complete"), truth, df_complete, df_complete, reveal
        )
    with right:
        st.markdown("#### MASKED")
        sr.render_result(
            ex.result_kind, ex.gold_for("masked"), truth, df_masked, df_complete, reveal
        )
    if reveal:
        st.info(
            "The gold is the same for both columns — COMPLETE matches it while "
            "MASKED falls short. The degradation **is** the reveal."
        )


def _maybe_live_overlay(ex, config, ds, lang, key_prefix: str) -> None:
    """Show the live NL2Cypher translation when the instance + API are up (§9)."""
    if "nl2cypher" not in ex.run_modes:
        return
    client = st.session_state.get("anthropic_client")
    if client is None:
        return
    if not st.toggle("Show live NL2Cypher translation", key=f"{key_prefix}_live"):
        return
    try:
        from app.graph.connection import get_driver_for_dataset
        from app.graph.nl2cypher import nl_to_cypher

        driver = get_driver_for_dataset(ds["key"])
        with st.spinner("Generating Cypher with DeepSeek …"):
            cypher = nl_to_cypher(ex.text(lang), client)
        with st.expander("Generated Cypher (live)", expanded=True):
            st.code(cypher, language="cypher")
        with driver.session() as session:
            rows = [dict(r) for r in session.run(cypher)]
        st.caption(f"Live query returned {len(rows)} row(s).")
    except Exception as exc:
        st.caption(f"Live NL2Cypher unavailable — using cached result. ({exc})")


# --------------------------------------------------------------------------- #
# real-data provenance (§8)                                                    #
# --------------------------------------------------------------------------- #

def _render_provenance(config, ds) -> None:
    st.caption(
        "The real archive has no ground truth, so the Showcase demonstrates the "
        "complementary strength: **document → record provenance**. Each record "
        "links back to the scanned register page it was transcribed from."
    )
    try:
        df = pd.read_csv(ds["csv"], dtype=str, keep_default_na=False, nrows=300)
    except Exception as exc:
        st.error(f"Could not read the real corpus CSV: {exc}")
        return

    have_prov = [c for c in ("double_page_url", "ark_url") if c in df.columns]
    if not have_prov:
        st.warning("No provenance columns (double_page_url / ark_url) in this CSV.")
        return

    df = df[df[have_prov].apply(lambda r: any(v for v in r), axis=1)]
    if df.empty:
        st.info("No records with provenance links in the sampled rows.")
        return

    labels = [
        f"#{i} — {row.get('prenom','')} {row.get('nom','')} ({row.get('regiment','')})"
        for i, row in df.iterrows()
    ]
    choice = st.selectbox("Pick a record", options=list(df.index), format_func=lambda i: labels[list(df.index).index(i)])
    row = df.loc[choice]

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Record**")
        st.json({k: row[k] for k in ("nom", "prenom", "regiment", "naissance_lieu",
                                      "naissance_annee", "source_image") if k in df.columns})
    with cols[1]:
        st.markdown("**Source document**")
        dp = row.get("double_page_url", "")
        ark = row.get("ark_url", "")
        if dp:
            st.markdown(f"[Open scanned double page]({dp})")
        if ark:
            st.markdown(f"[Open archive record (ARK)]({ark})")
        if not (dp or ark):
            st.caption("No provenance link for this record.")
