"""
Validation-report loader + aggregation (Validation Report Spec §2,4).

The eval runner (``validation/evaluate.py``) emits a **flat list of score rows**
to ``validation/corpus/eval/results.json`` (and RAG rows to
``rag_results.json``). This module is the single place that reads those
artifacts and reduces them into the per-panel aggregates the report tab renders
— the same shared-artifact discipline the spec calls for (GUI and paper read one
file, so they cannot drift).

All functions here are **pure** over the row lists, so they can be unit-tested
without Streamlit. A row "counts" toward a mean only when it carries a numeric
``score`` (mirrors ``evaluate.summarize`` — ``unparseable`` / ``query_error``
already land as ``0.0``; ``n/a`` / ``skipped`` rows carry no score).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import app.config as config

EVAL_DIR: Path = config.PROJECT_ROOT / "validation" / "corpus" / "eval"
RESULTS_PATH: Path = EVAL_DIR / "results.json"
RAG_RESULTS_PATH: Path = EVAL_DIR / "rag_results.json"

CONDITIONS = ("COMPLETE", "MASKED")

# RAG judge model (mirrors validation/eval/rag.py default) — surfaced in the
# manifest so the judge's identity is visible next to its numbers.
JUDGE_MODEL = "google/gemma-4-31b-it"


# --------------------------------------------------------------------------- #
# loading                                                                      #
# --------------------------------------------------------------------------- #

def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_results() -> list[dict]:
    return _load(RESULTS_PATH)


def load_rag_results() -> list[dict]:
    return _load(RAG_RESULTS_PATH)


def artifact_meta() -> dict:
    """What can be derived about the run (no manifest is emitted yet, §3)."""
    meta: dict = {"available": RESULTS_PATH.exists()}
    if RESULTS_PATH.exists():
        meta["results_path"] = str(RESULTS_PATH)
        meta["results_modified"] = datetime.fromtimestamp(
            RESULTS_PATH.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M")
    if RAG_RESULTS_PATH.exists():
        meta["rag_modified"] = datetime.fromtimestamp(
            RAG_RESULTS_PATH.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M")
    return meta


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def _mean(xs) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return round(sum(xs) / len(xs), 4) if xs else None


def _delta(complete, masked) -> float | None:
    if complete is None or masked is None:
        return None
    return round(masked - complete, 4)


def scored(rows: list[dict]) -> list[dict]:
    """Rows that carry a numeric headline score (the only rows that count)."""
    return [r for r in rows if isinstance(r.get("score"), (int, float))
            and not isinstance(r.get("score"), bool)]


def engines(rows: list[dict]) -> list[str]:
    return sorted({r["engine"] for r in rows})


# --------------------------------------------------------------------------- #
# headline — COMPLETE vs MASKED per engine (§4 headline)                       #
# --------------------------------------------------------------------------- #

def headline(rows: list[dict]) -> list[dict]:
    agg: dict = defaultdict(list)
    for r in scored(rows):
        agg[(r["engine"], r["condition"])].append(r["score"])
    out = []
    for e in engines(scored(rows)):
        c = _mean(agg.get((e, "COMPLETE"), []))
        m = _mean(agg.get((e, "MASKED"), []))
        out.append({
            "engine": e, "complete": c, "masked": m, "delta": _delta(c, m),
            "n_complete": len(agg.get((e, "COMPLETE"), [])),
            "n_masked": len(agg.get((e, "MASKED"), [])),
        })
    return out


def information_degradation(rows: list[dict]) -> tuple[float | None, int]:
    """Engine-independent cost of annotation: mean of the per-question
    degradation_score (MASKED gold's recall vs COMPLETE truth). One value per
    distinct question id."""
    by_id: dict = {}
    for r in rows:
        ds = r.get("degradation_score")
        if isinstance(ds, (int, float)) and not isinstance(ds, bool):
            by_id[r["id"]] = ds
    return _mean(list(by_id.values())), len(by_id)


# --------------------------------------------------------------------------- #
# grouped means by a row field (stratum / use_case / split / engine) (§4)      #
# --------------------------------------------------------------------------- #

def by_field(rows: list[dict], field: str, engine: str | None = None) -> list[dict]:
    src = [r for r in scored(rows) if engine is None or r["engine"] == engine]
    agg: dict = defaultdict(lambda: {"COMPLETE": [], "MASKED": []})
    for r in src:
        key = r.get(field) or "—"
        agg[key][r["condition"]].append(r["score"])
    out = []
    for key in sorted(agg, key=str):
        c, m = _mean(agg[key]["COMPLETE"]), _mean(agg[key]["MASKED"])
        out.append({
            field: key, "complete": c, "masked": m, "delta": _delta(c, m),
            "n": len(agg[key]["COMPLETE"]) + len(agg[key]["MASKED"]),
        })
    return out


def degradation_by_use_case(rows: list[dict]) -> list[dict]:
    """Per-question degradation grouped by use case (one value per id)."""
    seen: set = set()
    agg: dict = defaultdict(list)
    for r in rows:
        if r["id"] in seen:
            continue
        ds = r.get("degradation_score")
        if isinstance(ds, (int, float)) and not isinstance(ds, bool):
            agg[r.get("use_case") or "—"].append(ds)
            seen.add(r["id"])
    return [{"use_case": uc, "mean_recall_vs_complete": _mean(v), "n": len(v)}
            for uc, v in sorted(agg.items())]


# --------------------------------------------------------------------------- #
# decomposition — retrieval vs decision (§4, corpus spec §7.1)                 #
# --------------------------------------------------------------------------- #

def decomposition(rows: list[dict], engine: str | None = None) -> list[dict]:
    """For the post-proc kinds (linkage / partition) that carry a
    ``retrieval_recall``: did the generated query surface the right records
    (retrieval) vs did the decision module get the answer (score)."""
    src = [r for r in rows if r.get("retrieval_recall") is not None
           and (engine is None or r["engine"] == engine)]
    agg: dict = defaultdict(lambda: {"retr": [], "dec": []})
    for r in src:
        key = (r["engine"], r.get("result_kind") or "—")
        agg[key]["retr"].append(r["retrieval_recall"])
        if isinstance(r.get("score"), (int, float)):
            agg[key]["dec"].append(r["score"])
    out = []
    for (eng, kind), v in sorted(agg.items()):
        out.append({
            "engine": eng, "result_kind": kind,
            "retrieval_recall": _mean(v["retr"]),
            "decision_acc": _mean(v["dec"]),
            "n": len(v["retr"]),
        })
    return out


# --------------------------------------------------------------------------- #
# genealogy — linkage P/R/F1, partition pairwise/B³, false-merge (§4)          #
# --------------------------------------------------------------------------- #

def genealogy(rows: list[dict], engine: str, condition: str = "COMPLETE") -> dict:
    sel = [r for r in rows if r["engine"] == engine and r["condition"] == condition]

    # --- linkage: derive P/R/F1 from the {TP,TN,FP,FN,WRONG} outcomes -------- #
    link = [r["detail"] for r in sel
            if r.get("result_kind") == "linkage" and isinstance(r.get("detail"), dict)]
    oc = Counter(d.get("outcome") for d in link)
    tp, fp, fn, wrong = oc["TP"], oc["FP"], oc["FN"], oc["WRONG"]
    # WRONG = linked to the wrong record: counts against both precision & recall.
    p_den, r_den = tp + fp + wrong, tp + fn + wrong
    lp = round(tp / p_den, 4) if p_den else None
    lr = round(tp / r_den, 4) if r_den else None
    lf1 = round(2 * lp * lr / (lp + lr), 4) if (lp and lr) else None
    linkage = {"precision": lp, "recall": lr, "f1": lf1,
               "outcomes": dict(oc), "n": len(link)} if link else None

    # --- partition: mean of the per-case pairwise + B³ figures --------------- #
    part = [r["detail"] for r in sel
            if r.get("result_kind") == "partition" and isinstance(r.get("detail"), dict)]
    partition = {
        "pairwise_precision": _mean([d.get("pairwise_precision") for d in part]),
        "pairwise_recall": _mean([d.get("pairwise_recall") for d in part]),
        "pairwise_f1": _mean([d.get("pairwise_f1") for d in part]),
        "b3_f1": _mean([d.get("b3_f1") for d in part]),
        "n": len(part),
    } if part else None

    # --- false-merge rate on the sibling decoys (target 0) ------------------- #
    fm = [r["detail"] for r in sel
          if r.get("result_kind") == "false_merge" and isinstance(r.get("detail"), dict)]
    # a false merge = the engine pulled in a record the gold excludes (fp > 0).
    false_merge = {
        "rate": round(sum(1 for d in fm if (d.get("fp") or 0) > 0) / len(fm), 4),
        "n": len(fm),
    } if fm else None

    return {"linkage": linkage, "partition": partition, "false_merge": false_merge}


# --------------------------------------------------------------------------- #
# RAG — retrieval / faithfulness / abstention (§4)                             #
# --------------------------------------------------------------------------- #

def rag_summary(rag_rows: list[dict]) -> list[dict]:
    out = []
    for cond in CONDITIONS:
        cr = [r for r in rag_rows if r.get("condition") == cond]
        if not cr:
            continue
        out.append({
            "condition": cond,
            "hit_rate": _mean([r.get("hit_rate") for r in cr]),
            "recall_at_k": _mean([r.get("recall_at_k") for r in cr]),
            "ndcg_at_10": _mean([r.get("ndcg_at_10") for r in cr]),
            "coverage": _mean([r.get("coverage") for r in cr]),
            "faithfulness": _mean([r.get("faithfulness") for r in cr]),
            "abstention_acc": _mean([1.0 if r.get("abstention_ok") else 0.0 for r in cr]),
            "n": len(cr),
        })
    return out


def rag_abstention(rag_rows: list[dict], condition: str = "COMPLETE") -> dict:
    """CRAG framing: of the genuinely-unanswerable questions, how many were
    correctly abstained vs hallucinated (abstention rewarded)."""
    cr = [r for r in rag_rows if r.get("condition") == condition]
    unans = [r for r in cr if r.get("expect_abstain")]
    ans = [r for r in cr if not r.get("expect_abstain")]
    hallucinated = [r for r in unans if not r.get("abstained")]
    over_abstained = [r for r in ans if r.get("abstained")]
    return {
        "n_unanswerable": len(unans),
        "abstained": len(unans) - len(hallucinated),
        "hallucinated": len(hallucinated),
        "n_answerable": len(ans),
        "over_abstained": len(over_abstained),
    }


# --------------------------------------------------------------------------- #
# drill-down — per-question rows (§4)                                          #
# --------------------------------------------------------------------------- #

def per_question(rows: list[dict]) -> list[dict]:
    """Flatten every scored/attempted row to a compact drill-down record."""
    out = []
    for r in rows:
        out.append({
            "id": r.get("id"),
            "ref_query": r.get("ref_query"),
            "use_case": r.get("use_case"),
            "stratum": r.get("stratum"),
            "split": r.get("split"),
            "engine": r.get("engine"),
            "condition": r.get("condition"),
            "result_kind": r.get("result_kind"),
            "status": r.get("status"),
            "score": r.get("score"),
            "degradation": r.get("degradation_score"),
        })
    return out
