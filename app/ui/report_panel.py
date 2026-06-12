"""
Validation Report panel (Validation Report Spec v0.1).

Renders the **aggregate evaluation scorecard** — the aggregate counterpart to the
Showcase's single-example reveal. It reads the precomputed ``results.json`` /
``rag_results.json`` emitted by the eval runner (single source of truth with the
paper's eval table, §2) and shows: the COMPLETE-vs-MASKED headline, the
difficulty / mode / use-case / split breakdowns, the retrieval-vs-decision
decomposition, the genealogy and RAG metrics, a per-question drill-down, and a
method card. No live LLM runs here — the booth renders the cached artifact (§3).

Honesty (§6): the corpus is synthetic, so every number is an **upper bound** on
real-data correctness, and the MASKED degradation is the *intended* result, not a
defect.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import report_loader as rl


# --------------------------------------------------------------------------- #
# entry point                                                                  #
# --------------------------------------------------------------------------- #

def render(config) -> None:
    st.header("Validation Report — evaluation scorecard")

    meta = rl.artifact_meta()
    if not meta.get("available"):
        st.warning(
            "No evaluation artifact found at "
            f"`{rl.RESULTS_PATH}`.\n\n"
            "Generate it with the eval runner:\n\n"
            "```\nmake eval            # reference oracle only\n"
            "make eval-live       # + template / nl2cypher vs Neo4j\n```"
        )
        return

    # Real dataset has no gold → the report is N/A there (§7), mirroring the
    # Showcase's provenance-instead-of-gold behaviour.
    active = st.session_state.get("active_dataset", config.DEFAULT_DATASET)
    ds = config.get_dataset(active)
    if not ds["has_gold"]:
        st.info(
            "The **real archive** has no ground truth, so there is no scorecard "
            "to render here — the evaluation is a property of the **synthetic** "
            "COMPLETE/MASKED conditions. Switch to a Synthetic dataset in the "
            "sidebar to read the report (the numbers below are identical for both "
            "synthetic conditions — they *are* the COMPLETE-vs-MASKED study)."
        )

    rows = rl.load_results()
    rag_rows = rl.load_rag_results()

    _render_honesty_banner()
    _render_manifest(meta, rows, rag_rows)

    st.markdown("---")
    _render_headline(rows)

    st.markdown("---")
    _render_breakdowns(rows, rag_rows)

    st.markdown("---")
    _render_decomposition(rows)

    st.markdown("---")
    _render_genealogy(rows)

    st.markdown("---")
    _render_rag(rag_rows)

    st.markdown("---")
    _render_drilldown(rows)

    st.markdown("---")
    _render_method_card()


# --------------------------------------------------------------------------- #
# labelling + manifest (§3, §6)                                               #
# --------------------------------------------------------------------------- #

def _render_honesty_banner() -> None:
    st.warning(
        "**Synthetic upper bound.** All scores are measured on the *synthetic* "
        "corpus (clean values), so they are an **upper bound** on real-data "
        "correctness. The **MASKED** column is the *intended* degradation from "
        "masking fields to real-archive sparsity — low masked scores are the "
        "result, not a failure. The delta is the cost of incomplete annotation."
    )


def _render_manifest(meta: dict, rows: list[dict], rag_rows: list[dict]) -> None:
    n_questions = len({r["id"] for r in rows})
    engines = ", ".join(rl.engines(rows)) or "—"
    with st.expander("Run manifest — what produced these numbers", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Questions", n_questions)
        c2.metric("Engines (modes)", len(rl.engines(rows)))
        c3.metric("RAG questions", len({r["id"] for r in rag_rows}) if rag_rows else 0)
        st.caption(
            f"**Engines:** {engines}  ·  **RAG judge:** {rl.JUDGE_MODEL} "
            "(a different model family from the generator, per spec)."
        )
        st.caption(
            f"**Artifact:** `{meta.get('results_path')}` · "
            f"last updated {meta.get('results_modified', '—')}"
            + (f" · RAG {meta.get('rag_modified')}" if meta.get("rag_modified") else "")
        )
        st.caption(
            "Precomputed and rendered as-is — the paper's eval table is generated "
            "from the same file, so the demo and the paper cannot drift. "
            "_(Seed / snapshot / model-version fields are not yet emitted by the "
            "runner; they will surface here once the manifest is added.)_"
        )


# --------------------------------------------------------------------------- #
# headline — COMPLETE vs MASKED (§4)                                          #
# --------------------------------------------------------------------------- #

def _fmt(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def _render_headline(rows: list[dict]) -> None:
    st.subheader("Headline — COMPLETE vs MASKED")
    st.caption(
        "Mean headline score per engine and condition. `reference` is the oracle "
        "(1.0 on COMPLETE by construction); the live engines (`template`, "
        "`nl2cypher`) reveal real system error."
    )

    hl = rl.headline(rows)
    if not hl:
        st.info("No scored rows yet.")
        return

    # information-degradation: engine-independent cost of annotation, one figure
    degr, n_degr = rl.information_degradation(rows)
    cols = st.columns(len(hl) + 1)
    for col, h in zip(cols, hl):
        col.metric(
            h["engine"],
            _fmt(h["complete"]),
            delta=None if h["delta"] is None else f"{h['delta']:+.3f} masked",
            help=f"COMPLETE n={h['n_complete']} · MASKED n={h['n_masked']}",
        )
    cols[-1].metric(
        "Info. degradation",
        _fmt(degr),
        help=f"Mean MASKED-gold recall vs COMPLETE truth over {n_degr} questions — "
             "the engine-independent cost of masking. 1.0 = no information lost.",
    )

    df = pd.DataFrame(
        [{"engine": h["engine"], "COMPLETE": h["complete"], "MASKED": h["masked"],
          "Δ (masked−complete)": h["delta"]} for h in hl]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    chart = df.set_index("engine")[["COMPLETE", "MASKED"]]
    st.bar_chart(chart, height=240)


# --------------------------------------------------------------------------- #
# breakdowns — stratum / mode / use case / split (§4)                         #
# --------------------------------------------------------------------------- #

def _cond_table(records: list[dict], label_col: str) -> None:
    if not records:
        st.info("No data.")
        return
    df = pd.DataFrame(records)
    show = df.rename(columns={"complete": "COMPLETE", "masked": "MASKED",
                              "delta": "Δ", "n": "n"})
    st.dataframe(show, use_container_width=True, hide_index=True)
    idx = [r[label_col] for r in records]
    chart = pd.DataFrame(
        {"COMPLETE": [r["complete"] for r in records],
         "MASKED": [r["masked"] for r in records]}, index=idx,
    )
    st.bar_chart(chart, height=240)


def _render_breakdowns(rows: list[dict], rag_rows: list[dict]) -> None:
    st.subheader("Breakdowns")
    eng = _engine_selector(rows, key="bd_engine")

    t_strat, t_mode, t_uc, t_split = st.tabs(
        ["By difficulty stratum", "By mode", "By use case", "Seen / unseen split"]
    )

    with t_strat:
        st.caption(
            "lookup / multi-hop / aggregation / unanswerable. For *unanswerable*, "
            "abstention is the rewarded behaviour (CRAG convention) — see the RAG "
            "panel for the abstention-vs-hallucination split."
        )
        _cond_table(rl.by_field(rows, "stratum", engine=eng), "stratum")

    with t_mode:
        st.caption(
            "Each engine is a mode: `template` (deterministic baseline), "
            "`nl2cypher` (LLM-generated Cypher), `reference` (oracle). RAG is "
            "scored on a different metric set — see the RAG panel."
        )
        _cond_table(
            [{"mode": h["engine"], "complete": h["complete"], "masked": h["masked"],
              "delta": h["delta"], "n": h["n_complete"] + h["n_masked"]}
             for h in rl.headline(rows)],
            "mode",
        )

    with t_uc:
        st.caption("lookup / bounded / genealogy / migration / anthropometric / mechanics.")
        _cond_table(rl.by_field(rows, "use_case", engine=eng), "use_case")

    with t_split:
        st.caption(
            "Generalization across the query/template split (Finegan-Dollak 2018): "
            "`seen` templates vs `unseen` held-out phrasings."
        )
        _cond_table(rl.by_field(rows, "split", engine=eng), "split")


def _engine_selector(rows: list[dict], key: str) -> str:
    opts = rl.engines(rows)
    default = "nl2cypher" if "nl2cypher" in opts else (opts[0] if opts else "reference")
    return st.selectbox(
        "Engine", opts, index=opts.index(default) if default in opts else 0, key=key,
        help="The breakdowns below are filtered to this engine.",
    )


# --------------------------------------------------------------------------- #
# decomposition — retrieval vs decision (§4)                                  #
# --------------------------------------------------------------------------- #

def _render_decomposition(rows: list[dict]) -> None:
    st.subheader("Decomposition — retrieval vs decision")
    st.caption(
        "For the post-processing kinds (linkage / partition), did the generated "
        "query surface the right records (**retrieval recall**) vs did the "
        "decision module reach the right answer (**decision accuracy**)? Splitting "
        "these attributes an error to the query or to the post-proc module "
        "(corpus spec §7.1)."
    )
    dec = rl.decomposition(rows)
    if not dec:
        st.info(
            "No decomposition rows — these require live engines that emit retrieved "
            "record ids (run `make eval-live`)."
        )
        return
    df = pd.DataFrame(dec).rename(columns={
        "retrieval_recall": "retrieval recall", "decision_acc": "decision accuracy",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# genealogy — linkage / partition / false-merge (§4)                          #
# --------------------------------------------------------------------------- #

def _render_genealogy(rows: list[dict]) -> None:
    st.subheader("Genealogy")
    st.caption(
        "Linkage precision/recall/F1; partition pairwise P/R/F1 + B³; and the "
        "**false-merge rate** on sibling decoys (target 0)."
    )
    eng = _engine_selector(rows, key="gen_engine")
    cond = st.radio("Condition", list(rl.CONDITIONS), horizontal=True, key="gen_cond")
    g = rl.genealogy(rows, engine=eng, condition=cond)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Linkage** (father link)")
        lk = g["linkage"]
        if lk:
            st.metric("F1", _fmt(lk["f1"]))
            st.caption(f"P {_fmt(lk['precision'])} · R {_fmt(lk['recall'])} · n={lk['n']}")
            st.caption("Outcomes: " + ", ".join(f"{k} {v}" for k, v in lk["outcomes"].items() if k))
        else:
            st.caption("No linkage cases for this engine/condition.")
    with c2:
        st.markdown("**Partition** (sibling clusters)")
        pt = g["partition"]
        if pt:
            st.metric("B³ F1", _fmt(pt["b3_f1"]))
            st.caption(
                f"pairwise P {_fmt(pt['pairwise_precision'])} · "
                f"R {_fmt(pt['pairwise_recall'])} · F1 {_fmt(pt['pairwise_f1'])} · n={pt['n']}"
            )
        else:
            st.caption("No partition cases for this engine/condition.")
    with c3:
        st.markdown("**False-merge rate** (decoys)")
        fm = g["false_merge"]
        if fm:
            st.metric("Rate", _fmt(fm["rate"]), help="Target 0 — fraction of decoy "
                      "cases where a non-sibling was wrongly merged in.")
            st.caption(f"n={fm['n']}")
        else:
            st.caption("No decoy cases for this engine/condition.")


# --------------------------------------------------------------------------- #
# RAG — retrieval / faithfulness / abstention (§4)                            #
# --------------------------------------------------------------------------- #

def _render_rag(rag_rows: list[dict]) -> None:
    st.subheader("RAG")
    if not rag_rows:
        st.info(
            "No RAG results — run the RAG path with `python validation/evaluate.py "
            "--rag` (needs DeepSeek + an OpenRouter/Gemma judge)."
        )
        return
    st.caption(
        "Retrieval (hit-rate / recall@k / nDCG@10) and name-coverage are "
        "deterministic vs the oracle gold; faithfulness and abstention are judged "
        f"by **{rl.JUDGE_MODEL}** — a different model family from the generator."
    )
    summ = rl.rag_summary(rag_rows)
    df = pd.DataFrame(summ).rename(columns={
        "hit_rate": "hit@k", "recall_at_k": "recall@k", "ndcg_at_10": "nDCG@10",
        "coverage": "name-coverage", "abstention_acc": "abstention-acc",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)

    ab = rl.rag_abstention(rag_rows, "COMPLETE")
    st.markdown(
        f"**Abstention (CRAG framing, COMPLETE):** {ab['n_unanswerable']} "
        f"unanswerable → **{ab['abstained']} correctly abstained**, "
        f"**{ab['hallucinated']} hallucinated**; {ab['n_answerable']} answerable → "
        f"{ab['over_abstained']} over-abstained (conservative when retrieval "
        "misses — not a hallucination)."
    )
    st.caption(
        "**Judge calibration** (Gemma vs human labels): N/A — human agreement "
        "labels are not yet collected, so the judge's trust level cannot be shown "
        "here. This is the honest current state."
    )


# --------------------------------------------------------------------------- #
# drill-down — per-question (§4)                                              #
# --------------------------------------------------------------------------- #

def _render_drilldown(rows: list[dict]) -> None:
    st.subheader("Drill-down — per question")
    st.caption("Filter the individual questions behind any number above.")

    pq = rl.per_question(rows)
    df = pd.DataFrame(pq)
    if df.empty:
        st.info("No rows.")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        eng = st.multiselect("Engine", sorted(df["engine"].dropna().unique()), key="dd_eng")
    with c2:
        cond = st.multiselect("Condition", sorted(df["condition"].dropna().unique()), key="dd_cond")
    with c3:
        strat = st.multiselect("Stratum", sorted(df["stratum"].dropna().unique()), key="dd_strat")
    with c4:
        uc = st.multiselect("Use case", sorted(df["use_case"].dropna().unique()), key="dd_uc")

    if eng:
        df = df[df["engine"].isin(eng)]
    if cond:
        df = df[df["condition"].isin(cond)]
    if strat:
        df = df[df["stratum"].isin(strat)]
    if uc:
        df = df[df["use_case"].isin(uc)]

    st.caption(f"{len(df)} row(s)")
    st.dataframe(df, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# method card — §11 conformance / positioning (§5)                            #
# --------------------------------------------------------------------------- #

_METHOD_CARD = [
    ("Execution & denotation accuracy", "Answers scored by what the query returns, "
     "not string-matching the query — the Spider/denotation convention."),
    ("Query/template split", "Held-out `unseen` phrasings vs `seen` templates "
     "(Finegan-Dollak 2018) to measure generalization, not memorization."),
    ("Abstention rewarded", "Unanswerable questions reward a correct *no-answer* "
     "over a confident wrong one (CRAG convention)."),
    ("Judge ≠ generator", "The RAG faithfulness/abstention judge (Gemma) is a "
     "different model family from the answer generator (DeepSeek)."),
    ("RAGAS / BEIR RAG metrics", "Retrieval reported as hit-rate / recall@k / "
     "nDCG; answer quality as faithfulness + coverage."),
    ("Shared-artifact discipline", "GUI and paper read one `results.json`, the "
     "same single-source-of-truth pattern as the `norm()` utility."),
]


def _render_method_card() -> None:
    st.subheader("Method card — which conventions the eval follows")
    st.caption(
        "The rigor made visible: the SOTA evaluation conventions this scorecard "
        "conforms to."
    )
    st.dataframe(
        pd.DataFrame(_METHOD_CARD, columns=["Convention", "What it means"]),
        use_container_width=True, hide_index=True,
    )
