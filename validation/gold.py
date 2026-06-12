"""
Gold-artifact computation for the validation corpus.

All gold is computed programmatically from the authored records (never by an
LLM). Record ids are 0-based row positions in complete.csv / masked.csv.
See specs/MilitAI_Synthetic_Validation_Spec.md §5, §7.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

# Soft generational-gap weight (§5.2).
def w_gap(g: int) -> float:
    if g < 16:
        return 0.0
    if g < 25:
        return round((g - 16) / (25 - 16), 3)
    if g <= 45:
        return 1.0
    if g <= 58:
        return round(1 - (g - 45) / (58 - 45), 3)
    return 0.0


def _by_rid(records):
    return {r["_rid"]: r for r in records}


def _present(rec, field):
    return rec[field] != ""


# --- shared anchor resolver (spec §6.2: "anchors from planted tags") ---------
# questions.py binds each question's entity to a planted record via this same
# resolver, so question text and gold stay consistent with the corpus across
# reseeds instead of drifting from hardcoded names.

def find_anchor(records, *, family=None, role=None, tag=None, nom=None, prenom=None):
    """Planted records matching the given selectors (AND-combined), sorted by
    `_rid`. Selectors: `_family` id, `_role`, membership in `_tags`, and/or
    exact `nom`/`prenom`."""
    out = []
    for r in records:
        if family is not None and r.get("_family") != family:
            continue
        if role is not None and r.get("_role") != role:
            continue
        if tag is not None and tag not in r.get("_tags", ()):
            continue
        if nom is not None and r["nom"] != nom:
            continue
        if prenom is not None and r["prenom"] != prenom:
            continue
        out.append(r)
    return sorted(out, key=lambda r: r["_rid"])


def anchor_one(records, **selectors):
    """The lowest-`_rid` planted anchor matching the selectors, or None."""
    matches = find_anchor(records, **selectors)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------

def family_gold(records):
    """Authored family partition + which sets should cluster as one family."""
    fams = defaultdict(list)
    for r in records:
        if r["_family"]:
            fams[r["_family"]].append(r["_rid"])

    # cluster semantics per family id
    SHOULD_CLUSTER = {  # True -> one family; False -> must NOT merge
        "FAM-CLEAN-1": True, "FAM-CLEAN-2": True, "FAM-CLEAN-3": True,
        "FAM-CLEAN-4": True, "FAM-PARTIAL-1": True, "FAM-SINGLEP-1": True,
        "FAM-DECOY-1": False, "FAM-NEG-1": False,
    }
    by = _by_rid(records)
    out = {}
    for fid, members in sorted(fams.items()):
        members = sorted(members)
        sample = by[members[0]]
        out[fid] = {
            "members": members,
            "should_cluster": SHOULD_CLUSTER[fid],
            "nom": sample["nom"],
            "key": {
                "nom": sample["nom"],
                "pere_prenom": sample["pere_prenom"],
                "mere_nom": sample["mere_nom"],
                "mere_prenom": sample["mere_prenom"],
            },
            "matricules": [by[m]["matricule"] for m in members],
        }
    # True equivalence partition (gold for B3 / pairwise scoring):
    # each clustering family is one class; decoy/neg members are singletons.
    classes = []
    for fid, info in out.items():
        if info["should_cluster"]:
            classes.append(sorted(info["members"]))
        else:
            classes.extend([[m] for m in info["members"]])
    return {"families": out, "true_partition": sorted(classes)}


def linkage_gold(records, masked):
    """Per vertical-link son: correct father rid (or none) + candidate scores."""
    by = _by_rid(records)
    father_recs = [r for r in records if r["_role"].startswith("father:")]
    sons = find_anchor(records, tag="vert_son")

    EXPECTED = {  # son role -> father case label expected (or None)
        "VERT-TRUE": "VERT-TRUE", "VERT-YOUNG": "VERT-YOUNG",
        "VERT-OLD": "VERT-OLD", "VERT-DECOY": None, "VERT-ABSENT": None,
    }
    links = {}
    for son in sorted(sons, key=lambda r: r["_rid"]):
        case = son["_role"]
        son_by = int(son["naissance_annee"]) if son["naissance_annee"] else None
        # candidates: ANY record matching (nom, pere_prenom) — faithful to what
        # a real matcher scanning the whole corpus would surface.
        candidates = []
        for f in records:
            if f["_rid"] == son["_rid"]:
                continue
            if f["nom"] == son["nom"] and f["prenom"] == son["pere_prenom"]:
                f_by = int(f["naissance_annee"]) if f["naissance_annee"] else None
                g = (son_by - f_by) if (son_by and f_by) else None
                candidates.append({
                    "rid": f["_rid"], "father_birth": f_by,
                    "gap": g, "w": w_gap(g) if g is not None else 0.0,
                })
        # expected father rid: the candidate matching the expected case with w>0
        exp_case = EXPECTED[case]
        father_rid = None
        if exp_case is not None:
            for f in father_recs:
                if f["_role"] == f"father:{exp_case}" and f["nom"] == son["nom"] \
                        and f["prenom"] == son["pere_prenom"]:
                    father_rid = f["_rid"]
        links[str(son["_rid"])] = {
            "case": case,
            "son_nom": son["nom"], "son_prenom": son["prenom"],
            "pere_prenom": son["pere_prenom"], "son_birth": son_by,
            "expected_father_rid": father_rid,
            "candidates": sorted(candidates, key=lambda c: -c["w"]),
            # masked survival: does son keep birth year + pere_prenom in MASKED?
            "masked_son_has_birth": masked[son["_rid"]]["naissance_annee"] != "",
            "masked_son_has_pere": masked[son["_rid"]]["pere_prenom"] != "",
        }
    return links


def _histogram(recs, field):
    return dict(sorted(Counter(r[field] for r in recs if r[field] != "").items()))


def migration_gold(records, masked):
    by_company = defaultdict(list)
    for r in records:
        if r["compagnie"] in ("compagnie A", "compagnie B", "compagnie C", "compagnie D"):
            by_company[r["compagnie"]].append(r)
    m_by_company = defaultdict(list)
    for m in masked:
        if m["compagnie"] in ("compagnie A", "compagnie B", "compagnie C", "compagnie D"):
            m_by_company[m["compagnie"]].append(m)

    out = {}
    for comp in ("compagnie A", "compagnie B", "compagnie C", "compagnie D"):
        out[comp] = {
            "n": len(by_company[comp]),
            "members": sorted(r["_rid"] for r in by_company[comp]),
            "origin_histogram_complete": _histogram(by_company[comp], "naissance_departement"),
            "origin_histogram_masked": _histogram(m_by_company[comp], "naissance_departement"),
            "enrolement_years": sorted({int(r["enrolement_annee"]) for r in by_company[comp]}),
        }
    return out


def cohort_gold(records, masked, year=1710):
    gold_comps = {"compagnie A", "compagnie B", "compagnie C", "compagnie D"}
    cohort = [r for r in records
              if r["compagnie"] in gold_comps and r["enrolement_annee"] == str(year)]
    m_cohort = [m for m in masked
                if m["compagnie"] in gold_comps and m["enrolement_annee"] == str(year)]
    return {
        "year": year,
        "members": sorted(r["_rid"] for r in cohort),
        "birth_department_complete": _histogram(cohort, "naissance_departement"),
        "birth_department_masked": _histogram(m_cohort, "naissance_departement"),
    }


def _cm(rec):
    try:
        return (int(rec["pied"]) * 32.48 + int(rec["pouce"]) * 2.71
                + int(rec["ligne"]) * 0.226)
    except (ValueError, KeyError):
        return None


def stature_gold(records, masked, threshold_cm=170.0):
    cohort = [r for r in records if "stature" in r["_tags"]]
    by_region_c = defaultdict(list)
    for r in cohort:
        by_region_c[r["naissance_region"]].append(_cm(r))
    region_means_complete = {
        reg: {"n": len(v), "mean_cm": round(sum(v) / len(v), 1)}
        for reg, v in by_region_c.items()
    }
    # masked: only Tier-A keep height
    m_cohort = [m for m in masked if m["pied"] != ""]
    by_region_m = defaultdict(list)
    for m in m_cohort:
        by_region_m[m["naissance_region"]].append(_cm(m))
    region_means_masked = {
        reg: {"n": len(v), "mean_cm": round(sum(v) / len(v), 1)}
        for reg, v in by_region_m.items()
    }
    tall = sorted(r["_rid"] for r in cohort if (_cm(r) or 0) > threshold_cm)
    tall_masked = sorted(m["_rid"] for m in m_cohort if (_cm(m) or 0) > threshold_cm)
    return {
        "cohort": sorted(r["_rid"] for r in cohort),
        "threshold_cm": threshold_cm,
        "region_means_complete": region_means_complete,
        "region_means_masked": region_means_masked,
        "taller_than_threshold_complete": tall,
        "taller_than_threshold_masked": tall_masked,
    }


def trajectory_gold(records, masked):
    traj = [r for r in records if "trajectory" in r["_tags"]]
    out = []
    for r in sorted(traj, key=lambda x: x["_rid"]):
        m = masked[r["_rid"]]
        out.append({
            "rid": r["_rid"], "tier": r["_tier"],
            "birth_departement": r["naissance_departement"],
            "birth_lieu": r["naissance_lieu"],
            "enrolement_annee": int(r["enrolement_annee"]),
            "death_departement": r["deces_departement"],
            "death_lieu": r["deces_lieu"],
            "recoverable_masked": m["naissance_departement"] != ""
                                  and m["deces_departement"] != "",
        })
    n_rec = sum(1 for t in out if t["recoverable_masked"])
    return {"trajectories": out, "n_total": len(out), "n_recoverable_masked": n_rec}


def compute_all(records, masked, survival, gold_dir: Path):
    artifacts = {
        "family_partition.json": family_gold(records),
        "link_map.json": linkage_gold(records, masked),
        "migration_origin.json": migration_gold(records, masked),
        "mig_cohort_1710.json": cohort_gold(records, masked, 1710),
        "stature_regions.json": stature_gold(records, masked),
        "trajectories.json": trajectory_gold(records, masked),
        "masked_survival.json": survival,
    }
    for name, data in artifacts.items():
        (gold_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifacts
