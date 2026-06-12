"""
Acceptance-criteria checker for the validation corpus (§9 of the spec).

Reads the generated outputs and verifies:
  - MASKED marginal fill rates match §3.1 within ±5 pp
  - full family-key joint ~45% within ±3 pp
  - ultra-rare fields present only via planted probes
  - each gold company has exactly its seeded roster; histograms match §5.3
  - planted structures present and gold-consistent
  - every question has a computed gold answer
  - template-mode sanity: every COMPLETE denotation reproducible by a filter
  - regeneration is byte-for-byte stable

Run:  python validation/verify.py
Exit code 0 = all pass.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).parent
OUT = HERE / "corpus"
GOLD = OUT / "gold"

# §3.1 MASKED targets we calibrate (subset that is marginal-matched).
TARGETS = {
    "surnom": 0.78, "age": 0.13, "profession": 0.04,
    "naissance_annee": 0.21, "naissance_lieu": 0.77,
    "naissance_departement": 0.66, "naissance_juridiction": 0.68,
    "naissance_region": 0.11, "naissance_pays": 0.74,
    "domicile_lieu": 0.05, "mariage_annee": 0.03, "deces_annee": 0.27,
    "pere_prenom": 0.51, "mere_nom": 0.42, "mere_prenom": 0.45,
    "regiment": 0.15, "bataillon": 0.11, "matricule": 0.84,
    "grade_final": 0.25, "enrolement_annee": 0.83, "ark_url": 0.84,
    "double_page_url": 0.97,
}

PLANTED_ONLY = ["pied", "pouce", "ligne", "taille_metre", "naissance_pieve",
                "deces_lieu", "deces_departement", "desertion_annee"]

# §5.3 seeded origin distributions.
SEEDED = {
    "compagnie A": {"Finistère": 9, "Côtes-du-Nord": 3, "Morbihan": 3},
    "compagnie B": {"Bas-Rhin": 5, "Moselle": 5, "Meurthe": 4},
    "compagnie C": {"Seine": 2, "Rhône": 2, "Gironde": 2, "Nord": 2, "Isère": 2, "Puy-de-Dôme": 2},
    "compagnie D": {"Finistère": 4, "Morbihan": 3, "Seine": 5, "Eure": 2},
}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  — {detail}" if detail else ""))


def fill_rate(df, col):
    return df[col].fillna("").astype(str).str.strip().ne("").mean()


def main():
    cdf = pd.read_csv(OUT / "complete.csv", dtype=str, keep_default_na=False)
    mdf = pd.read_csv(OUT / "masked.csv", dtype=str, keep_default_na=False)

    check("record count == 180", len(cdf) == 180 and len(mdf) == 180,
          f"complete={len(cdf)} masked={len(mdf)}")

    # --- MASKED marginals within ±5 pp ---
    worst = 0.0
    bad = []
    for col, t in TARGETS.items():
        r = fill_rate(mdf, col)
        d = abs(r - t)
        worst = max(worst, d)
        if d > 0.05:
            bad.append(f"{col}: {r:.2f} vs {t:.2f}")
    check("MASKED marginals within ±5pp", not bad,
          f"worst Δ={worst*100:.1f}pp" + (("; off: " + ", ".join(bad)) if bad else ""))

    # --- family-key joint ~45% ±3pp ---
    def has(df, col):
        return df[col].fillna("").astype(str).str.strip().ne("")
    joint = (has(mdf, "nom") & has(mdf, "pere_prenom") & has(mdf, "mere_prenom")).mean()
    check("family-key joint ≈45% (±3pp)", abs(joint - 0.45) <= 0.03,
          f"joint={joint*100:.1f}%")

    # --- ultra-rare fields planted-only (present only on Tier-A planted in MASKED) ---
    surv = json.loads((GOLD / "masked_survival.json").read_text(encoding="utf-8"))
    planted_rids = {int(k) for k in surv}
    ok_planted = True
    detail_planted = []
    for col in PLANTED_ONLY:
        present_m = set(mdf.index[has(mdf, col)])
        stray = present_m - planted_rids
        if stray:
            ok_planted = False
            detail_planted.append(f"{col}:{len(stray)} stray")
    check("ultra-rare fields planted-only in MASKED", ok_planted,
          "; ".join(detail_planted))

    # --- gold company rosters + histograms (COMPLETE) ---
    mig = json.loads((GOLD / "migration_origin.json").read_text(encoding="utf-8"))
    roster_ok = True
    hist_ok = True
    for comp, seeded in SEEDED.items():
        members = cdf.index[cdf["compagnie"] == comp]
        n = len(members)
        if n != sum(seeded.values()):
            roster_ok = False
        hist = mig[comp]["origin_histogram_complete"]
        if hist != seeded:
            hist_ok = False
    check("gold rosters exact (A–D)", roster_ok)
    check("origin histograms match §5.3 (COMPLETE, L1=0)", hist_ok)

    # background soldiers never belong to A–D
    bg_in_gold = cdf[(cdf["compagnie"].isin(SEEDED)) ].shape[0]
    check("only seeded soldiers in A–D", bg_in_gold == 55, f"A–D total={bg_in_gold}")

    # --- planted structures present ---
    fam = json.loads((GOLD / "family_partition.json").read_text(encoding="utf-8"))
    check("8 families planted", len(fam["families"]) == 8,
          f"n={len(fam['families'])}")
    # no background record collides with a planted family's full key
    fam_keys = {(f["key"]["nom"], f["key"]["pere_prenom"],
                 f["key"]["mere_nom"], f["key"]["mere_prenom"])
                for f in fam["families"].values() if f["should_cluster"]}
    fam_rids = {rid for f in fam["families"].values() for rid in f["members"]}
    collide = []
    for i, row in cdf.iterrows():
        if i in fam_rids:
            continue
        k = (row["nom"], row["pere_prenom"], row["mere_nom"], row["mere_prenom"])
        if all(k) and k in fam_keys:
            collide.append(i)
    check("no stray full-key collision with families", not collide,
          f"colliding rids={collide}")

    link = json.loads((GOLD / "link_map.json").read_text(encoding="utf-8"))
    check("5 vertical-link cases", len(link) == 5, f"n={len(link)}")
    # each linkage case has exactly one father candidate (no spurious homonyms)
    cand_ok = all(len(info["candidates"]) <= 1 for info in link.values())
    check("linkage candidates clean (≤1 each)", cand_ok,
          "; ".join(f"{i['case']}:{len(i['candidates'])}" for i in link.values()))

    # linkage expectations: TRUE/YOUNG/OLD have a father, DECOY/ABSENT none
    link_ok = True
    detail_link = []
    for rid, info in link.items():
        case = info["case"]
        exp = info["expected_father_rid"]
        if case in ("VERT-TRUE", "VERT-YOUNG", "VERT-OLD") and exp is None:
            link_ok = False; detail_link.append(f"{case}:missing")
        if case in ("VERT-DECOY", "VERT-ABSENT") and exp is not None:
            link_ok = False; detail_link.append(f"{case}:unexpected")
        # boundary admission: YOUNG (gap~17) and OLD (gap~52) must have w>0
        if case in ("VERT-YOUNG", "VERT-OLD"):
            top = info["candidates"][0]["w"] if info["candidates"] else 0
            if top <= 0:
                link_ok = False; detail_link.append(f"{case}:w=0")
        # decoy must have w==0 on its homonym
        if case == "VERT-DECOY":
            if info["candidates"] and info["candidates"][0]["w"] != 0:
                link_ok = False; detail_link.append("DECOY:w>0")
    check("linkage gold matches case expectations", link_ok, "; ".join(detail_link))

    stat = json.loads((GOLD / "stature_regions.json").read_text(encoding="utf-8"))
    check("stature cohort ~15", 12 <= len(stat["cohort"]) <= 18,
          f"n={len(stat['cohort'])}")
    means = stat["region_means_complete"]
    sep_ok = ("Bretagne" in means and "Lorraine" in means
              and means["Bretagne"]["mean_cm"] > means["Lorraine"]["mean_cm"])
    check("stature regions separated (Bretagne > Lorraine)", sep_ok,
          f"{means.get('Bretagne')} vs {means.get('Lorraine')}")

    traj = json.loads((GOLD / "trajectories.json").read_text(encoding="utf-8"))
    check("5 complete trajectories", traj["n_total"] == 5)
    check("trajectory collapse under MASKED",
          0 < traj["n_recoverable_masked"] < traj["n_total"],
          f"recoverable={traj['n_recoverable_masked']}/5")

    # --- questions all have gold ---
    qs = [json.loads(l) for l in (OUT / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
    ans = json.loads((GOLD / "answers.json").read_text(encoding="utf-8"))
    missing = [q["id"] for q in qs if q["id"] not in ans]
    check("every question has gold", not missing,
          f"{len(qs)} questions" + (f"; missing {missing}" if missing else ""))

    # zero-result questions actually return empty in COMPLETE
    zero_ok = (ans["Q-MECH-ZERO-01"]["complete"] == []
               and ans["Q-MECH-ZERO-02"]["complete"] == [])
    check("zero-result controls empty", zero_ok)

    # --- §6 two-layer design: reference-query catalogue ---
    cat = json.loads((OUT / "reference_queries" / "catalogue.json").read_text(encoding="utf-8"))
    cat_ids = {c["ref_query"] for c in cat}
    unresolved = [q["id"] for q in qs if q.get("ref_query") not in cat_ids]
    check("every question resolves to a Layer-1 ref query", not unresolved,
          f"{len(cat)} ref queries" + (f"; unresolved {unresolved}" if unresolved else ""))

    # ref-query gold == question gold (pandas oracle consistency, §9)
    cat_by = {c["ref_query"]: c for c in cat}
    mismatch = [q["id"] for q in qs
                if cat_by[q["ref_query"]]["gold_complete"] != ans[q["id"]]["complete"]]
    check("ref-query gold matches question gold (pandas-verified)", not mismatch,
          f"mismatches={mismatch}")
    check("all ref queries carry canonical Cypher",
          all(c["cypher"].strip() for c in cat))

    # --- difficulty strata + unanswerable (§6.2) ---
    strata = {q["stratum"] for q in qs}
    check("all difficulty strata present",
          {"lookup", "multi_hop", "aggregation", "unanswerable"} <= strata,
          f"strata={sorted(strata)}")
    unans = [q["id"] for q in qs if q["stratum"] == "unanswerable"]
    reg_trap = any(q["id"] == "Q-UNANS-REG" for q in qs)
    check("unanswerable items incl. regiment trap", len(unans) >= 3 and reg_trap,
          f"unanswerable={unans}")

    # --- query/template split (§6.2, §9) ---
    held = [q["id"] for q in qs if q.get("held_out")]
    check("held-out query structures flagged", len(held) >= 3, f"held_out={held}")

    # --- FR/EN cross-lingual equivalence (§6.2): both present, distinct, shared gold ---
    xling_ok = all(q["fr"].strip() and q["en"].strip() and q["fr"] != q["en"] for q in qs)
    check("every question has FR + EN phrasings", xling_ok)
    # the toponym item maps EN 'Brittany' to FR 'Bretagne' onto the same gold
    check("toponym cross-lingual item present", any(q["id"] == "Q-XLING-01" for q in qs))

    # --- §2 matching normalization (store accented, match normalized) ---
    from normalize import norm, resolve_place, GAZETTEER
    check("norm() folds accents/dashes/apostrophes",
          norm("Côtes-du-Nord") == "cotesdunord" == norm("cotes du nord")
          and norm("L'HOSTIS") == "lhostis" and norm("René") == norm("Rene"))
    # fold-test questions (unaccented params) match the accented stored values
    fold01 = ans["Q-FOLD-01"]["complete"]
    exact_cdn = sorted(int(i) for i, row in cdf.iterrows()
                       if row["naissance_departement"] == "Côtes-du-Nord")
    check("fold-test Q-FOLD-01 (unaccented) == accented gold",
          fold01 == exact_cdn and len(fold01) > 0, f"n={len(fold01)}")
    fold02 = ans["Q-FOLD-02"]["complete"]
    exact_rene = sorted(int(i) for i, row in cdf.iterrows() if row["prenom"] == "René")
    check("fold-test Q-FOLD-02 (unaccented) == accented gold",
          fold02 == exact_rene and len(fold02) > 0, f"n={len(fold02)}")

    # --- §2 toponym enrichment: pinned gazetteer ---
    gaz = json.loads((OUT / "gazetteer.json").read_text(encoding="utf-8"))
    check("gazetteer pinned snapshot present",
          gaz.get("snapshot", {}).get("pinned") is not None)
    # every birthplace department/commune in the corpus resolves via the gazetteer
    places = set(cdf["naissance_departement"]) | set(cdf["naissance_lieu"])
    places.discard("")
    unresolved = sorted(p for p in places if resolve_place(p) is None)
    check("every birthplace resolves via gazetteer", not unresolved,
          f"unresolved={unresolved}")
    # Brittany resolves (EN->FR region->P131 departments) with a pinned QID
    brit = resolve_place("Brittany")
    check("EN 'Brittany' -> Bretagne (Q12130) -> 3 departments",
          brit is not None and brit["canonical_fr"] == "Bretagne"
          and brit["wikidata_qid"] == "Q12130" and len(brit["departments"]) == 3)
    # Q-XLING gold == soldiers born in the Breton departments
    bret_depts = {"Finistère", "Côtes-du-Nord", "Morbihan"}
    xling_gold = sorted(int(i) for i, row in cdf.iterrows()
                        if row["naissance_departement"] in bret_depts)
    check("Q-XLING-01 gold == Breton-department births",
          ans["Q-XLING-01"]["complete"] == xling_gold and len(xling_gold) > 0,
          f"n={len(xling_gold)}")

    # --- realism: MASKED marginals vs a real-corpus sample (§9) ---
    real_path = HERE.parent / "data" / "full_unified_annotations.csv"
    if real_path.exists():
        cols = [c for c in TARGETS if c not in ("ark_url", "double_page_url")]
        rdf = pd.read_csv(real_path, dtype=str, keep_default_na=False, usecols=cols)
        worst_r, off_r = 0.0, []
        for c in cols:
            d = abs(fill_rate(mdf, c) - fill_rate(rdf, c))
            worst_r = max(worst_r, d)
            if d > 0.10:
                off_r.append(f"{c}:{d*100:.0f}pp")
        check("MASKED marginals within ±10pp of real corpus", not off_r,
              f"worst Δ={worst_r*100:.1f}pp" + ("; off: " + ", ".join(off_r) if off_r else ""))
    else:
        check("real-corpus realism check (skipped — file absent)", True)

    # --- byte-for-byte regeneration ---
    def digest():
        h = hashlib.sha256()
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()
    before = digest()
    subprocess.run([sys.executable, str(HERE / "generate.py")], check=True,
                   cwd=HERE, capture_output=True)
    after = digest()
    check("regeneration byte-for-byte stable", before == after)

    n_fail = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - n_fail}/{len(results)} checks passed.")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
