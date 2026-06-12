"""
Scoring functions — one per ``result_kind`` emitted by the question set.

Every scorer takes ``(pred, gold)`` and returns a flat ``dict`` of metrics. The
key ``"score"`` is always present and is the single headline number in [0, 1]
used for aggregation (1.0 = perfect). Scorers are pure and side-effect free, so
they serve double duty: scoring an *engine* against gold, and scoring the MASKED
gold against the COMPLETE gold (the engine-independent degradation analysis).

Conventions
-----------
- ``rid`` sets are compared as sets of ints.
- Histograms are dicts ``{label: count}``; missing labels count as 0.
- Partitions are compared label-agnostically (only the member sets matter).
- ``None`` is a first-class gold value for linkage (correct abstention).
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations


# --------------------------------------------------------------------------- #
# set-valued answers: rid_set, false_merge, trajectory, rag_target            #
# --------------------------------------------------------------------------- #

def score_set(pred, gold) -> dict:
    """Precision / recall / F1 over a set of record ids (or any hashables)."""
    p, g = set(pred or []), set(gold or [])
    tp = len(p & g)
    fp = len(p - g)
    fn = len(g - p)
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not g else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else (
        1.0 if not g and not p else 0.0)
    return {
        "score": round(f1, 4), "precision": round(precision, 4),
        "recall": round(recall, 4), "f1": round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
        "n_pred": len(p), "n_gold": len(g),
        "exact": p == g,
    }


# --------------------------------------------------------------------------- #
# scalar count                                                                #
# --------------------------------------------------------------------------- #

def score_count(pred, gold) -> dict:
    pv = _count_val(pred)
    gv = _count_val(gold)
    exact = pv == gv
    err = abs(pv - gv) if (pv is not None and gv is not None) else None
    return {"score": 1.0 if exact else 0.0, "exact": exact,
            "pred": pv, "gold": gv, "abs_err": err}


def _count_val(x):
    if isinstance(x, dict):
        return x.get("count")
    return x


# --------------------------------------------------------------------------- #
# histograms: histogram, histogram_pair                                       #
# --------------------------------------------------------------------------- #

def score_histogram(pred, gold) -> dict:
    """L1 distance over the union of labels, plus a normalised similarity."""
    p = {k: int(v) for k, v in (pred or {}).items()}
    g = {k: int(v) for k, v in (gold or {}).items()}
    labels = set(p) | set(g)
    l1 = sum(abs(p.get(k, 0) - g.get(k, 0)) for k in labels)
    total_gold = sum(g.values())
    # similarity: 1 - L1 / (sum_gold + sum_pred), the normalised set-overlap form.
    denom = sum(g.values()) + sum(p.values())
    sim = 1.0 - (l1 / denom) if denom else 1.0
    return {
        "score": round(sim, 4), "l1": l1,
        "l1_normalised": round(l1 / total_gold, 4) if total_gold else 0.0,
        "exact": p == g, "n_labels_gold": len(g), "n_labels_pred": len(p),
    }


def score_histogram_pair(pred, gold) -> dict:
    """Mean of the per-component histogram similarity."""
    keys = set(pred or {}) | set(gold or {})
    parts = {k: score_histogram((pred or {}).get(k, {}), (gold or {}).get(k, {})) for k in keys}
    score = sum(v["score"] for v in parts.values()) / len(parts) if parts else 1.0
    l1 = sum(v["l1"] for v in parts.values())
    return {"score": round(score, 4), "l1": l1, "exact": all(v["exact"] for v in parts.values()),
            "components": {k: v["score"] for k, v in parts.items()}}


# --------------------------------------------------------------------------- #
# aggregates: aggregate (mean stature), aggregate_pair                        #
# --------------------------------------------------------------------------- #

def score_aggregate(pred, gold, tol=0.5) -> dict:
    """Mean within ``tol`` cm and n exact. ``pred``/``gold`` = {n, mean_cm}."""
    pm, gm = (pred or {}).get("mean_cm"), (gold or {}).get("mean_cm")
    pn, gn = (pred or {}).get("n"), (gold or {}).get("n")
    if gm is None:
        ok_mean = pm is None
        err = None
    else:
        err = abs((pm if pm is not None else 0.0) - gm)
        ok_mean = pm is not None and err <= tol
    n_exact = pn == gn
    return {"score": 1.0 if (ok_mean and n_exact) else 0.0,
            "mean_ok": ok_mean, "n_exact": n_exact,
            "mean_abs_err": round(err, 4) if err is not None else None,
            "pred": pred, "gold": gold}


def score_aggregate_pair(pred, gold, tol=0.5) -> dict:
    keys = set(gold or {})
    parts = {k: score_aggregate((pred or {}).get(k), (gold or {}).get(k), tol) for k in keys}
    score = sum(v["score"] for v in parts.values()) / len(parts) if parts else 1.0
    return {"score": round(score, 4), "exact": all(v["score"] == 1.0 for v in parts.values()),
            "components": {k: v for k, v in parts.items()}}


# --------------------------------------------------------------------------- #
# linkage (vertical genealogy): predicted father rid or None                  #
# --------------------------------------------------------------------------- #

def score_linkage(pred, gold) -> dict:
    """Categorical correctness for one linkage case.

    Outcome ∈ {TP, TN, FP, FN}:
      - TN  gold None, pred None        (correct abstention)
      - TP  gold rid,  pred == gold      (correct link)
      - FP  pred rid,  gold None         (false link / hallucinated father)
      - FN  gold rid,  pred None          (missed link)
      - WRONG pred rid != gold rid        (linked to the wrong record) -> FP-like
    """
    p = None if pred in (None, "", []) else int(pred) if str(pred).isdigit() else pred
    g = None if gold in (None, "", []) else int(gold)
    if g is None and p is None:
        outcome = "TN"
    elif g is not None and p == g:
        outcome = "TP"
    elif g is None and p is not None:
        outcome = "FP"
    elif g is not None and p is None:
        outcome = "FN"
    else:
        outcome = "WRONG"
    correct = outcome in ("TP", "TN")
    return {"score": 1.0 if correct else 0.0, "outcome": outcome,
            "pred": p, "gold": g, "correct": correct}


# --------------------------------------------------------------------------- #
# partition (sibling clustering within a scope)                               #
# --------------------------------------------------------------------------- #

def _clusters(part) -> list[frozenset]:
    """Normalise {label: [members]} (or [[members]]) to a list of frozensets."""
    if isinstance(part, dict):
        groups = part.values()
    else:
        groups = part or []
    return [frozenset(g) for g in groups if g]


def _pairs(clusters) -> set:
    out = set()
    for c in clusters:
        for a, b in combinations(sorted(c), 2):
            out.add((a, b))
    return out


def score_partition(pred, gold) -> dict:
    """Pairwise P/R/F1 and B³ P/R/F1 over the clustering, label-agnostic."""
    pc, gc = _clusters(pred), _clusters(gold)
    pp, gp = _pairs(pc), _pairs(gc)
    tp = len(pp & gp)
    pw_p = tp / len(pp) if pp else 1.0
    pw_r = tp / len(gp) if gp else 1.0
    pw_f1 = (2 * pw_p * pw_r / (pw_p + pw_r)) if (pw_p + pw_r) else (1.0 if not gp and not pp else 0.0)

    # B³ over the elements that appear in the gold partition.
    pred_of = {e: c for c in pc for e in c}
    gold_of = {e: c for c in gc for e in c}
    elems = set(gold_of) | set(pred_of)
    b3_p_sum = b3_r_sum = 0.0
    for e in elems:
        pe = pred_of.get(e, frozenset([e]))
        ge = gold_of.get(e, frozenset([e]))
        inter = len(pe & ge)
        b3_p_sum += inter / len(pe)
        b3_r_sum += inter / len(ge)
    n = len(elems) or 1
    b3_p, b3_r = b3_p_sum / n, b3_r_sum / n
    b3_f1 = (2 * b3_p * b3_r / (b3_p + b3_r)) if (b3_p + b3_r) else 0.0

    return {
        "score": round(b3_f1, 4),
        "pairwise_precision": round(pw_p, 4), "pairwise_recall": round(pw_r, 4),
        "pairwise_f1": round(pw_f1, 4),
        "b3_precision": round(b3_p, 4), "b3_recall": round(b3_r, 4), "b3_f1": round(b3_f1, 4),
        "exact": set(pc) == set(gc),
        "n_clusters_pred": len(pc), "n_clusters_gold": len(gc),
    }


# --------------------------------------------------------------------------- #
# record_fields / disambiguation: list of dicts, compared exactly             #
# --------------------------------------------------------------------------- #

def score_records(pred, gold) -> dict:
    """Exact match of a list of field-dicts, keyed and compared by ``rid``.

    Also reports field-level accuracy so partial credit is visible (e.g. the
    UNANS abstention case where MASKED gold is empty)."""
    p_by = {r.get("rid"): r for r in (pred or [])}
    g_by = {r.get("rid"): r for r in (gold or [])}
    rids = set(p_by) | set(g_by)
    field_tot = field_ok = 0
    for rid in rids:
        pr, gr = p_by.get(rid, {}), g_by.get(rid, {})
        for k in set(pr) | set(gr):
            if k == "rid":
                continue
            field_tot += 1
            if pr.get(k) == gr.get(k):
                field_ok += 1
    exact = _norm_records(pred) == _norm_records(gold)
    return {"score": 1.0 if exact else 0.0, "exact": exact,
            "field_accuracy": round(field_ok / field_tot, 4) if field_tot else 1.0,
            "n_pred": len(p_by), "n_gold": len(g_by)}


def _norm_records(recs):
    return sorted(
        (tuple(sorted((k, v) for k, v in r.items())) for r in (recs or [])),
        key=str,
    )


# --------------------------------------------------------------------------- #
# dispatch                                                                     #
# --------------------------------------------------------------------------- #

SCORERS = {
    "rid_set": score_set,
    "rag_target": score_set,
    "trajectory": score_set,
    "false_merge": score_set,
    "count": score_count,
    "histogram": score_histogram,
    "histogram_pair": score_histogram_pair,
    "aggregate": score_aggregate,
    "aggregate_pair": score_aggregate_pair,
    "linkage": score_linkage,
    "partition": score_partition,
    "record_fields": score_records,
    "disambiguation": score_records,
}


def score(result_kind: str, pred, gold) -> dict:
    """Dispatch to the scorer for ``result_kind``. Raises on unknown kinds."""
    try:
        scorer = SCORERS[result_kind]
    except KeyError as exc:
        raise ValueError(f"no scorer for result_kind={result_kind!r}") from exc
    return scorer(pred, gold)
