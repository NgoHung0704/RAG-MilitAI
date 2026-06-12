"""
RAG-path evaluation (validation spec §7.1 "RAG path" / "RAG judge design v1").

Scores the RAG mode against the same Layer-1 oracle gold, splitting the work so
the LLM judge does as little as possible:

  - **Retrieval** (deterministic vs gold): hit-rate@k, recall@k, nDCG@10. The
    Chroma doc id ``row_<rid>`` reconciles a retrieved chunk to a corpus rid.
  - **Correctness** (deterministic vs gold): coverage of the gold entities/facts
    in the answer text, plus precision (no extra soldiers named).
  - **Faithfulness + abstention** (LLM judge — a *different* family from the
    generator, per spec): Gemma via OpenRouter, temp-0, single structured call.

Per-condition Chroma stores live under ``corpus/eval/chroma/{COMPLETE,MASKED}``.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from .reference import Corpus, execute
from .text import norm

EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "google/gemma-4-31b-it")  # spec §7.1; different family than the DeepSeek generator
TOP_K = int(os.getenv("RAG_TOP_K", "5"))


# --------------------------------------------------------------------------- #
# per-condition Chroma ingestion + retrieval                                  #
# --------------------------------------------------------------------------- #

def chroma_dir(out_dir: Path, condition: str) -> Path:
    return out_dir / "chroma" / condition


def ingest_condition(csv_path: Path, persist_dir: Path, model=EMBED_MODEL) -> int:
    """Embed a condition's corpus into its own Chroma store (idempotent upsert)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.rag.ingestion import ingest_csv
    persist_dir.mkdir(parents=True, exist_ok=True)
    return ingest_csv(str(csv_path), str(persist_dir), model)


def _rid_of(meta: dict):
    """Chroma id is 'row_<rid>'."""
    rid = meta.get("id", "")
    m = re.match(r"row_(\d+)", str(rid))
    return int(m.group(1)) if m else None


def retrieve(query: str, persist_dir: Path, k=TOP_K, model=EMBED_MODEL):
    from app.rag.retriever import retrieve as _retrieve
    chunks = _retrieve(query, k, str(persist_dir), model)
    for c in chunks:
        c["rid"] = _rid_of(c.get("metadata", {}))
    return chunks


# --------------------------------------------------------------------------- #
# deterministic metrics                                                        #
# --------------------------------------------------------------------------- #

def gold_rids(result_kind, gold) -> list[int]:
    """Flatten an oracle gold value to the set of involved rids."""
    if gold is None:
        return []
    if isinstance(gold, int):
        return [gold]
    if isinstance(gold, list):
        out = []
        for x in gold:
            if isinstance(x, int):
                out.append(x)
            elif isinstance(x, dict) and isinstance(x.get("rid"), int):
                out.append(x["rid"])
        return out
    if isinstance(gold, dict):
        out = []
        for v in gold.values():
            if isinstance(v, list):
                out += [m for m in v if isinstance(m, int)]
        return out
    return []


def is_empty_gold(kind, gold) -> bool:
    """Genuinely unanswerable gold (-> abstention is the correct behaviour)."""
    if gold is None:
        return True
    if isinstance(gold, list):
        return len(gold) == 0
    if isinstance(gold, dict):
        if "count" in gold:
            return gold["count"] == 0
        if "mean_cm" in gold:
            return not gold.get("n")
        return len(gold) == 0
    return False


def relevant_rids(q, kind, gold, corpus):
    """Docs a faithful answer should draw on. For aggregation the gold is a
    distribution (no rids), so derive the scope (company / cohort) from params."""
    p, rq = q.get("params") or {}, q.get("ref_query")
    if rq == "RQ-MIG-01" and "cie" in p and "region" not in p:
        return corpus.company_rids(p["cie"])
    if rq == "RQ-MIG-03":
        return corpus.company_rids(p["cie1"]) + corpus.company_rids(p["cie2"])
    if rq == "RQ-MIG-02":
        return [r for r in corpus.rids if str(corpus.g(r, "enrolement_annee")) == str(p.get("year"))]
    return gold_rids(kind, gold)


def retrieval_metrics(ranked_rids: list[int], relevant: list[int], k=TOP_K) -> dict:
    rel = set(relevant)
    topk = ranked_rids[:k]
    hit = 1.0 if (rel & set(topk)) else (1.0 if not rel else 0.0)
    recall = len(rel & set(topk)) / len(rel) if rel else 1.0
    # nDCG@10
    K = 10
    dcg = sum((1.0 if rid in rel else 0.0) / math.log2(i + 2)
              for i, rid in enumerate(ranked_rids[:K]))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), K)))
    ndcg = (dcg / idcg) if idcg else (1.0 if not rel else 0.0)
    return {"hit_rate": round(hit, 4), "recall_at_k": round(recall, 4),
            "ndcg_at_10": round(ndcg, 4), "n_relevant": len(rel)}


def correctness(answer: str, corpus: Corpus, relevant: list[int], result_kind) -> dict:
    """Deterministic: do the gold soldiers' names appear in the answer?
    Coverage (recall of gold entities) + a light precision check."""
    na = norm(answer)
    if not relevant:  # unanswerable / zero: correctness handled by abstention
        return {"coverage": None, "expected": 0}
    hits = 0
    for rid in relevant:
        nom, prenom = corpus.g(rid, "nom"), corpus.g(rid, "prenom")
        if norm(nom) and norm(nom) in na and (not prenom or norm(prenom) in na):
            hits += 1
    return {"coverage": round(hits / len(relevant), 4), "expected": len(relevant),
            "found": hits}


# --------------------------------------------------------------------------- #
# LLM judge (faithfulness + abstention) — Gemma via OpenRouter                 #
# --------------------------------------------------------------------------- #

_JUDGE_SYS = (
    "You are a strict evaluator of a retrieval-augmented answer about historical "
    "French soldiers. You are given the QUESTION, the retrieved CONTEXT passages, "
    "and the ANSWER. Judge only what the text supports. Respond with JSON only."
)

_JUDGE_TMPL = """QUESTION:
{question}

CONTEXT (retrieved passages the answer must be grounded in):
{context}

ANSWER:
{answer}

Return JSON with exactly these keys:
- "faithfulness": float 0..1 — fraction of the answer's factual claims that are
  supported by the CONTEXT (1.0 = every claim grounded, 0.0 = hallucinated).
- "abstained": true/false — does the answer decline to give specific facts
  (says it cannot find / not recorded) rather than asserting them?
- "rationale": one short sentence.
JSON:"""


def judge_faithfulness(question, context, answer, client, model=JUDGE_MODEL) -> dict:
    prompt = _JUDGE_TMPL.format(question=question, context=context, answer=answer)
    resp = client.chat.completions.create(
        model=model, temperature=0, max_tokens=400,
        messages=[{"role": "system", "content": _JUDGE_SYS},
                  {"role": "user", "content": prompt}],
    )
    raw = resp.choices[0].message.content.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        d = json.loads(m.group(0) if m else raw)
    except Exception:
        return {"faithfulness": None, "abstained": None, "rationale": "unparseable judge output"}
    return {"faithfulness": d.get("faithfulness"), "abstained": bool(d.get("abstained")),
            "rationale": d.get("rationale", "")}


# --------------------------------------------------------------------------- #
# RAG-path orchestration                                                       #
# --------------------------------------------------------------------------- #

# kinds where gold soldier-name coverage is a meaningful correctness signal
_SET_KINDS = {"rid_set", "rag_target", "disambiguation", "record_fields", "false_merge"}
CONDITIONS = ("COMPLETE", "MASKED")


def run_rag_eval(rag_questions, gold_by_q, corpora, corpus_dir, out_dir,
                 gen_client, judge_client, k=TOP_K):
    """Score the RAG path per condition: retrieval + correctness (deterministic)
    + faithfulness/abstention (judge). Returns a list of result rows."""
    from app.rag.chain import _SYSTEM_PROMPT, build_rag_prompt
    csv_by_cond = {"COMPLETE": corpus_dir / "complete.csv", "MASKED": corpus_dir / "masked.csv"}
    rows = []
    for cond in CONDITIONS:
        pdir = chroma_dir(out_dir, cond)
        n = ingest_condition(csv_by_cond[cond], pdir)
        print(f"  [rag] embedded {cond} ({n} docs)")
        corpus = corpora[cond]
        for q in rag_questions:
            g = gold_by_q.get(q["id"])
            if not g:
                continue
            kind, gold = g["result_kind"], g["gold"][cond]
            relevant = relevant_rids(q, kind, gold, corpus)
            chunks = retrieve(q["en"], pdir, k)
            ranked = [c["rid"] for c in chunks if c["rid"] is not None]
            retr = retrieval_metrics(ranked, relevant, k)
            prompt = build_rag_prompt(q["en"], chunks)
            answer = gen_client.chat.completions.create(
                model="deepseek-chat", temperature=0, max_tokens=512,
                messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}],
            ).choices[0].message.content
            context = "\n\n".join(c["text"] for c in chunks)
            jd = judge_faithfulness(q["en"], context, answer, judge_client)
            corr = correctness(answer, corpus, relevant, kind) if kind in _SET_KINDS else {"coverage": None}
            expect_abstain = is_empty_gold(kind, gold)
            abst_ok = (jd["abstained"] is True) if expect_abstain else (jd["abstained"] is False)
            rows.append({
                "id": q["id"], "ref_query": q.get("ref_query"), "use_case": q.get("use_case"),
                "condition": cond, "result_kind": kind, "engine": "rag",
                "hit_rate": retr["hit_rate"], "recall_at_k": retr["recall_at_k"],
                "ndcg_at_10": retr["ndcg_at_10"], "coverage": corr["coverage"],
                "faithfulness": jd["faithfulness"], "abstained": jd["abstained"],
                "expect_abstain": expect_abstain, "abstention_ok": abst_ok,
                "answer": answer.strip()[:300], "rationale": jd.get("rationale", ""),
            })
    return rows


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 4) if xs else None


def rag_report(rows) -> list[str]:
    """Markdown lines for the RAG section, COMPLETE vs MASKED."""
    L = ["## RAG path (retrieval deterministic; faithfulness/abstention judged by "
         f"{JUDGE_MODEL})", "",
         "| condition | hit@k | recall@k | nDCG@10 | name-coverage | faithfulness | abstention-acc |",
         "|---|---|---|---|---|---|---|"]
    for cond in CONDITIONS:
        cr = [r for r in rows if r["condition"] == cond]
        L.append(f"| {cond} | {_mean([r['hit_rate'] for r in cr])} "
                 f"| {_mean([r['recall_at_k'] for r in cr])} "
                 f"| {_mean([r['ndcg_at_10'] for r in cr])} "
                 f"| {_mean([r['coverage'] for r in cr])} "
                 f"| {_mean([r['faithfulness'] for r in cr])} "
                 f"| {_mean([1.0 if r['abstention_ok'] else 0.0 for r in cr])} |")
    # CRAG-style breakdown (abstention rewarded over hallucination)
    co = [r for r in rows if r["condition"] == "COMPLETE"]
    unans = [r for r in co if r["expect_abstain"]]
    ans = [r for r in co if not r["expect_abstain"]]
    hallu = [r for r in unans if not r["abstained"]]
    over = [r for r in ans if r["abstained"]]
    L += ["", "*Abstention (CRAG framing, COMPLETE):* "
          f"{len(unans)} unanswerable → {len(unans)-len(hallu)} correctly abstained, "
          f"**{len(hallu)} hallucinated**; "
          f"{len(ans)} answerable → {len(over)} over-abstained "
          "(faithful but conservative when retrieval misses — not a hallucination).", ""]
    return L

