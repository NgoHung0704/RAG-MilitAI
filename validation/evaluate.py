"""
MilitAI validation eval runner.

Consumes the synthetic corpus (``complete.csv`` / ``masked.csv``) and the
question set (``questions.jsonl`` with ``ref_query`` + ``params``), then:

  1. computes the **oracle gold** for COMPLETE and MASKED by executing the
     reference query catalogue (eval/reference.py) — the catalogue §10 protocol;
  2. scores the ``reference`` engine (the oracle baseline) and, with ``--live``,
     the real ``template`` / ``nl2cypher`` engines against that gold;
  3. records the **degradation** = score(MASKED gold vs COMPLETE gold), the
     engine-independent cost of incomplete annotation.

Live engines run against Neo4j. Community edition has one database, so each
condition is loaded in turn (wipe + reload) before its questions are scored.

Outputs (under ``validation/corpus/eval/``): ``gold/<RQ>__<slug>.json`` (one
oracle gold per question), ``results.json``, ``report.md``.

Usage:
    python validation/evaluate.py                      # reference oracle only
    python validation/evaluate.py --live               # + template + nl2cypher vs Neo4j/DeepSeek
    python validation/evaluate.py --live --engines template   # just one live engine
    python validation/evaluate.py --questions specs/questions.jsonl --corpus validation/corpus
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.eval import metrics
from validation.eval.engines import (EngineUnavailable, NL2CypherEngine,
                                      ReferenceEngine, TemplateEngine)
from validation.eval.reference import Corpus

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONDITIONS = ("COMPLETE", "MASKED")


def load_questions(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_corpora(corpus_dir: Path) -> dict:
    return {cond: Corpus(pd.read_csv(corpus_dir / fname, dtype=str, keep_default_na=False))
            for cond, fname in (("COMPLETE", "complete.csv"), ("MASKED", "masked.csv"))}


def slugify(params: dict) -> str:
    from validation.eval.text import norm
    if not params:
        return "all"
    return "_".join(norm(str(v)) for v in params.values() if str(v)) or "all"


# --------------------------------------------------------------------------- #
# phase 1: oracle gold + degradation (reference engine, no Neo4j)             #
# --------------------------------------------------------------------------- #

def compute_gold(questions, corpora, gold_dir: Path):
    ref = ReferenceEngine()
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold_by_q, gaps = {}, []
    for q in questions:
        rq, params = q.get("ref_query"), q.get("params") or {}
        kinds, gold = set(), {}
        for cond in CONDITIONS:
            kind, gval, _ = ref.predict({"ref_query": rq, "params": params}, cond, corpora)
            kinds.add(kind)
            gold[cond] = gval
        kind = next(iter(kinds - {None}), None)
        if kind is None:
            gaps.append((q["id"], rq))
            continue
        gref = q.get("gold_ref") or f"gold/{rq}__{slugify(params)}.json"
        gp = gold_dir.parent / gref
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_text(json.dumps(
            {"id": q["id"], "ref_query": rq, "params": params, "result_kind": kind,
             "complete": gold["COMPLETE"], "masked": gold["MASKED"]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        gold_by_q[q["id"]] = {
            "q": q, "result_kind": kind, "gold": gold,
            "degradation": metrics.score(kind, gold["MASKED"], gold["COMPLETE"])["score"],
        }
    return gold_by_q, gaps


def _row(q, kind, engine, condition, degr):
    return {"id": q["id"], "ref_query": q.get("ref_query"), "use_case": q.get("use_case"),
            "stratum": q.get("stratum"), "split": q.get("split"), "engine": engine,
            "condition": condition, "result_kind": kind, "degradation_score": degr}


def _applies(engine_name, q):
    return engine_name == "reference" or engine_name in (q.get("modes") or [])


def score_engine(engine, questions, gold_by_q, corpora, conditions=CONDITIONS):
    """Score one engine over the given conditions (Neo4j must already hold the
    right condition for live engines)."""
    rows = []
    for q in questions:
        g = gold_by_q.get(q["id"])
        if g is None:
            continue
        kind = g["result_kind"]
        for cond in conditions:
            rec = _row(q, kind, engine.name, cond, g["degradation"])
            if not _applies(engine.name, q):
                rec["status"] = "n/a"
            elif not engine.available():
                rec["status"] = "skipped (unavailable)"
            elif not engine.can_do(kind):
                rec["status"] = "unsupported result_kind"
            else:
                from validation.eval.shaping import UNPARSEABLE
                try:
                    _kind, pred, info = engine.predict(q, cond, corpora)
                    if info.get("cypher"):
                        rec["cypher"] = info["cypher"]
                        rec["n_rows"] = info.get("n_rows")
                    if pred is UNPARSEABLE:
                        # system answer can't be shaped into the kind -> a failure (0)
                        rec["status"], rec["score"] = "unparseable", 0.0
                    else:
                        sc = metrics.score(kind, pred, g["gold"][cond])
                        rec["status"], rec["score"], rec["detail"] = "ok", sc["score"], sc
                        rr = _retrieval_recall(kind, g["gold"][cond], info.get("retrieved_rids"))
                        if rr is not None:
                            rec["retrieval_recall"] = rr
                except EngineUnavailable as exc:
                    rec["status"] = f"skipped ({exc})"
                except Exception as exc:
                    # a Neo4j error here is the LLM's bad Cypher -> system failure (0);
                    # anything else is a harness bug -> excluded from the mean.
                    if type(exc).__module__.split(".")[0] == "neo4j":
                        rec["status"], rec["score"] = "query_error", 0.0
                        rec["error"] = str(exc).splitlines()[0][:160]
                    else:
                        rec["status"] = f"error: {exc}"
            rows.append(rec)
    return rows


def _retrieval_recall(kind, gold, retrieved):
    """For the post-proc kinds: did the generated query surface the right rids?
    (decomposition per validation spec §7.1). None when not applicable."""
    if retrieved is None:
        return None
    rset = set(retrieved)
    if kind == "linkage":
        if gold in (None, "", []):
            return None  # decoy/absent: nothing to retrieve
        return 1.0 if int(gold) in rset else 0.0
    if kind == "partition":
        members = {m for cluster in (gold.values() if isinstance(gold, dict) else gold) for m in cluster}
        return round(len(rset & members) / len(members), 4) if members else None
    return None


# --------------------------------------------------------------------------- #
# phase 2: live engines (per-condition wipe-reload of Neo4j)                  #
# --------------------------------------------------------------------------- #

def run_live(live_engines, questions, gold_by_q, corpora, corpus_dir, driver):
    from validation.eval import ingest
    rows = []
    csv_by_cond = {"COMPLETE": corpus_dir / "complete.csv", "MASKED": corpus_dir / "masked.csv"}
    for cond in CONDITIONS:
        n = ingest.ingest(driver, csv_by_cond[cond], cond, wipe=True)
        print(f"  [live] ingested {cond} ({n} records) into Neo4j")
        for eng in live_engines:
            rows.extend(score_engine(eng, questions, gold_by_q, corpora, conditions=(cond,)))
    return rows


# --------------------------------------------------------------------------- #
# reporting                                                                    #
# --------------------------------------------------------------------------- #

def summarize(rows):
    """Mean headline score; counts every scored row (ok + unparseable + query_error,
    the last two as 0 — a failed/unshapeable answer is a system failure)."""
    agg = defaultdict(lambda: {"n": 0, "sum": 0.0})
    for r in rows:
        if "score" in r:
            agg[(r["engine"], r["condition"])]["n"] += 1
            agg[(r["engine"], r["condition"])]["sum"] += r["score"]
    return {k: round(v["sum"] / v["n"], 4) if v["n"] else None for k, v in agg.items()}


def coverage(rows):
    """Per live engine (COMPLETE): ok / unparseable / query_error / applicable."""
    agg = defaultdict(lambda: {"ok": 0, "unparseable": 0, "query_error": 0, "applicable": 0})
    for r in rows:
        if r["engine"] == "reference" or r["condition"] != "COMPLETE" or r.get("status") == "n/a":
            continue
        agg[r["engine"]]["applicable"] += 1
        st = r.get("status", "")
        if st in agg[r["engine"]]:
            agg[r["engine"]][st] += 1
    return agg


def degradation_by_usecase(gold_by_q):
    agg = defaultdict(lambda: {"n": 0, "sum": 0.0})
    for g in gold_by_q.values():
        uc = g["q"].get("use_case") or "?"
        agg[uc]["n"] += 1
        agg[uc]["sum"] += g["degradation"]
    return {uc: {"n": v["n"], "mean_recall_vs_complete": round(v["sum"] / v["n"], 4)}
            for uc, v in sorted(agg.items())}


def write_report(rows, gold_by_q, gaps, out: Path, n_questions: int, rag_rows=None):
    summary = summarize(rows)
    L = ["# MilitAI validation — evaluation report", "",
         f"Questions evaluated: **{n_questions}**  ·  reference oracle = catalogue §10.", "",
         "## Engine accuracy (mean headline score, scored vs oracle gold)", "",
         "| engine | COMPLETE | MASKED |", "|---|---|---|"]
    for e in sorted({e for (e, _c) in summary}):
        c, m = summary.get((e, "COMPLETE")), summary.get((e, "MASKED"))
        L.append(f"| {e} | {c if c is not None else '—'} | {m if m is not None else '—'} |")
    L += ["", "> `reference` is the oracle (1.0 on COMPLETE by construction); live engines"
              " reveal real system error.", ""]
    cov = coverage(rows)
    if cov:
        L += ["## Live-engine coverage (COMPLETE)", "",
              "| engine | ok | unparseable | query_error | applicable |", "|---|---|---|---|---|"]
        for e, v in sorted(cov.items()):
            L.append(f"| {e} | {v['ok']} | {v['unparseable']} | {v['query_error']} | {v['applicable']} |")
        L.append("")
    if rag_rows:
        from validation.eval.rag import rag_report
        L += rag_report(rag_rows)
    L += ["## Information degradation (MASKED gold vs COMPLETE truth), by use case", "",
          "| use case | n | mean recall vs COMPLETE |", "|---|---|---|"]
    for uc, v in degradation_by_usecase(gold_by_q).items():
        L.append(f"| {uc} | {v['n']} | {v['mean_recall_vs_complete']} |")
    L += ["", "## Per-question", "", "| id | ref_query | kind | degradation | "
          + " | ".join(sorted({r['engine'] for r in rows if r['engine'] != 'reference'})) + " |"]
    live_names = sorted({r['engine'] for r in rows if r['engine'] != 'reference'})
    L.append("|---|---|---|---|" + "---|" * len(live_names))
    by_qe = {(r["id"], r["engine"], r["condition"]): r for r in rows}
    for qid, g in gold_by_q.items():
        cells = []
        for e in live_names:
            r = by_qe.get((qid, e, "COMPLETE"))
            cells.append(str(r.get("score")) if r and r.get("status") == "ok" else "·")
        L.append(f"| {qid} | {g['q'].get('ref_query')} | {g['result_kind']} | {g['degradation']} | "
                 + " | ".join(cells) + " |")
    if gaps:
        L += ["", "## Coverage gaps (no reference handler)"] + [f"- {q} → {rq}" for q, rq in gaps]
    out.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #

def run_rag(questions, gold_by_q, corpora, corpus_dir, out_dir):
    """Score the RAG path. Needs DeepSeek (generator) + OpenRouter (Gemma judge)."""
    from dotenv import load_dotenv
    load_dotenv()
    deepseek, openrouter = os.getenv("DEEPSEEK_API_KEY", ""), os.getenv("OPENROUTER_API_KEY", "")
    if not (deepseek and openrouter):
        print("  [rag] missing DEEPSEEK_API_KEY or OPENROUTER_API_KEY; skipping RAG")
        return []
    from openai import OpenAI

    from validation.eval import rag
    gen = OpenAI(api_key=deepseek, base_url="https://api.deepseek.com")
    judge = OpenAI(api_key=openrouter, base_url="https://openrouter.ai/api/v1")
    rag_qs = [q for q in questions if "rag" in (q.get("modes") or [])]
    print(f"  [rag] {len(rag_qs)} rag-mode questions; judge={rag.JUDGE_MODEL}")
    return rag.run_rag_eval(rag_qs, gold_by_q, corpora, corpus_dir, out_dir, gen, judge)


def build_live_engines(names, corpus_dir, neo4j_uri=None):
    """Construct requested live engines + a shared Neo4j driver, or () if down.

    *neo4j_uri* targets the dedicated eval instance (port 7690 by default) so the
    per-condition wipe+reload never touches the GUI's demo instances.
    """
    from validation.eval import ingest
    try:
        driver = ingest.get_driver(neo4j_uri)
        driver.verify_connectivity()
    except Exception as exc:
        print(f"  [live] Neo4j unavailable at {neo4j_uri or 'NEO4J_URI'} ({exc}); "
              f"skipping live engines. Start it with: "
              f"docker compose --profile eval up -d neo4j-eval")
        return [], None
    drivers = {c: driver for c in CONDITIONS}
    engines = []
    if "template" in names:
        engines.append(TemplateEngine(drivers))
    if "nl2cypher" in names:
        client = None
        from dotenv import load_dotenv
        load_dotenv()
        key = os.getenv("DEEPSEEK_API_KEY", "")
        if key:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        else:
            print("  [live] DEEPSEEK_API_KEY missing; nl2cypher will be skipped")
        engines.append(NL2CypherEngine(drivers, llm_client=client))
    return engines, driver


def main():
    ap = argparse.ArgumentParser(description="MilitAI validation eval runner")
    ap.add_argument("--questions", default=str(HERE / "questions.jsonl"))
    ap.add_argument("--corpus", default=str(HERE / "corpus"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--live", action="store_true", help="also score live Neo4j engines")
    ap.add_argument("--engines", default="template,nl2cypher",
                    help="comma list of live engines to run with --live")
    ap.add_argument("--neo4j-uri", default=os.getenv("NEO4J_EVAL_URI", "bolt://localhost:7690"),
                    help="Neo4j target for --live (dedicated eval instance; "
                         "kept off the GUI's 7687/7688/7689). Default: bolt://localhost:7690")
    ap.add_argument("--rag", action="store_true",
                    help="also score the RAG path (Chroma + DeepSeek + OpenRouter/Gemma judge)")
    args = ap.parse_args()

    qpath, corpus_dir = Path(args.questions), Path(args.corpus)
    out_dir = Path(args.out) if args.out else corpus_dir / "eval"
    gold_dir = out_dir / "gold"
    out_dir.mkdir(parents=True, exist_ok=True)

    questions = load_questions(qpath)
    corpora = load_corpora(corpus_dir)

    gold_by_q, gaps = compute_gold(questions, corpora, gold_dir)
    rows = score_engine(ReferenceEngine(), questions, gold_by_q, corpora)

    driver = None
    if args.live:
        print(f"  [live] eval Neo4j target: {args.neo4j_uri}")
        live, driver = build_live_engines(args.engines.split(","), corpus_dir, args.neo4j_uri)
        live = [e for e in live if e.available()]
        if live:
            rows += run_live(live, questions, gold_by_q, corpora, corpus_dir, driver)

    rag_rows = []
    if args.rag:
        rag_rows = run_rag(questions, gold_by_q, corpora, corpus_dir, out_dir)

    try:
        (out_dir / "results.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        if rag_rows:
            (out_dir / "rag_results.json").write_text(
                json.dumps(rag_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        write_report(rows, gold_by_q, gaps, out_dir / "report.md", len(questions), rag_rows)
    finally:
        if driver is not None:
            driver.close()

    summary = summarize(rows)
    print(f"Evaluated {len(questions)} questions ({len(rows)} score rows).")
    for (e, c), v in sorted(summary.items()):
        print(f"  {e:12} {c:9} mean={v}")
    if gaps:
        print(f"  coverage gaps: {[g[1] for g in gaps]}")
    print(f"Wrote {out_dir/'results.json'}, {out_dir/'report.md'}")


if __name__ == "__main__":
    main()
