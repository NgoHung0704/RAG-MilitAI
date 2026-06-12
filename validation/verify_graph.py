"""
Graph-side half of the Layer-1 dual-verification (§6.1, §9).

`verify.py` confirms each reference query's gold via the pandas oracle. This
script runs the *canonical Cypher* against a Neo4j graph ingested from
complete.csv and checks its result equals the same gold — closing the
"executes on the graph AND equals an independent pandas computation" rule.

Usage:
    # 1. ingest the COMPLETE corpus (line_idx == our record id):
    python scripts/ingest_neo4j.py --csv validation/corpus/complete.csv
    # 2. run this checker:
    python validation/verify_graph.py

Requires Neo4j running and .env configured. Genealogy queries (CHILD_OF) also
require the parent-MERGE fix noted in §8; until then they are reported SKIP.
It writes the per-query graph verdict back into the catalogue
(`verified_graph`) and exits non-zero on any mismatch.

Only result kinds with an unambiguous denotation are auto-checked here
(rid_set, count, histogram). Linkage / aggregate / record_fields carry a
post-processing step and are checked at the application layer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).parent
CAT = HERE / "corpus" / "reference_queries" / "catalogue.json"

AUTO_KINDS = {"rid_set", "count", "histogram"}


def run_query(session, cypher):
    return list(session.run(cypher))


def as_rid_set(rows):
    return sorted(int(r["rid"]) for r in rows)


def as_count(rows):
    # a single-row count(*) AS n
    return {"count": int(rows[0]["n"])} if rows else {"count": 0}


def as_histogram(rows):
    return {r["dept"]: int(r["n"]) for r in rows if r["dept"] is not None}


def main():
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    try:
        from app.graph.connection import get_driver
        driver = get_driver()
        driver.verify_connectivity()
    except Exception as exc:  # no DB available
        print(f"Neo4j not reachable ({exc}).")
        print("Ingest complete.csv then re-run (see module docstring).")
        sys.exit(2)

    n_pass = n_fail = n_skip = 0
    with driver.session() as session:
        for c in cat:
            kind = c["result_kind"]
            needs_merge = "CHILD_OF" in c["cypher"]
            if kind not in AUTO_KINDS or needs_merge:
                c["verified_graph"] = None
                n_skip += 1
                continue
            gold = c["gold_complete"]
            try:
                rows = run_query(session, c["cypher"])
                if kind == "rid_set":
                    got, want = as_rid_set(rows), sorted(gold)
                elif kind == "count":
                    got, want = as_count(rows), gold
                else:  # histogram
                    got, want = as_histogram(rows), gold
                ok = got == want
            except Exception as exc:
                got, ok = f"ERROR: {exc}", False
            c["verified_graph"] = bool(ok)
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {c['ref_query']:16} ({kind})"
                  + ("" if ok else f"  got={got}  want={gold}"))
            n_pass += ok
            n_fail += (not ok)

    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    driver.close()
    print(f"\ngraph-verified {n_pass} pass / {n_fail} fail / {n_skip} skip "
          f"(skip = needs parent MERGE or has a post-processing step).")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
