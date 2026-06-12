# MilitAI validation — eval runner

Self-contained evaluation harness for the synthetic corpus. It **computes its own
gold** by executing the Reference Query Catalogue (`specs/MilitAI_Reference_Query_Catalogue.md`)
over `complete.csv` / `masked.csv` — the catalogue §10 protocol — then scores each
query engine against that gold and reports the COMPLETE→MASKED degradation.

It is **decoupled from the generator**: it reads only the two CSVs and a
`questions.jsonl` (with `ref_query` + `params`). It never reads the generator's
gold, so it is safe to run while `generate.py` is being edited.

## Run

```bash
python validation/evaluate.py
# or point at a specific question set / corpus:
python validation/evaluate.py --questions specs/questions.jsonl --corpus validation/corpus
```

Outputs under `validation/corpus/eval/`:

| File | Contents |
|---|---|
| `gold/<RQ>__<slug>.json` | one oracle gold per question (COMPLETE + MASKED) — the `gold_ref` |
| `results.json` | every (question, engine, condition) score + detail |
| `report.md` | engine-accuracy table + degradation-by-use-case + per-question table |

## Architecture

| Module | Role |
|---|---|
| `text.py` | independent re-impl of catalogue `norm()` (accent/case/dash/apostrophe fold) |
| `toponym.py` | Layer-M region→department resolution (Bretagne→{Finistère,Côtes-du-Nord,Morbihan}), FR/EN |
| `reference.py` | the executable RQ catalogue: `(ref_query, params)` → `(result_kind, gold)` — the oracle |
| `metrics.py` | one scorer per `result_kind` (set P/R/F1, count, histogram L1, partition pairwise+B³, aggregate, linkage, record_fields) |
| `engines.py` | engine registry: `reference` (oracle/baseline) + guarded live `template`/`nl2cypher`/`rag` |
| `../evaluate.py` | orchestration, gold emission, degradation analysis, reporting |

## Two axes of measurement

1. **Engine accuracy** — an engine's prediction vs the oracle gold for that
   condition. The `reference` engine is the oracle, so it is 1.0 on COMPLETE by
   construction; live engines (when wired) reveal real system error.
2. **Information degradation** — MASKED gold vs COMPLETE gold, engine-independent:
   the intrinsic cost of incomplete annotation per use case.

## Corpus dependency

The questions in `specs/questions.jsonl` bind to specific planted records
(Jean DUPONT's family + gap-30 father, MOREAU/GIRARD/ROUX/BLANC vertical links,
LEROY trajectory, BERNARD homonyms, RENARD decoy, CHALET Jean, …). Until the
generator plants these names, those questions yield **empty gold** and their
degradation is not yet meaningful. Once the corpus is regenerated to realize the
new `questions.jsonl`, every gold populates and the genealogy/linkage/migration
degradation becomes real — no change to this harness required.

## Live engines (`--live`)

```bash
python validation/evaluate.py --live                      # template + nl2cypher
python validation/evaluate.py --live --engines template   # one engine
```

Requires Neo4j up (the runner ingests each condition itself via `eval/ingest.py`
with the §1 schema fixes — parent `MERGE`, `Company` primary unit, `region`,
year-as-int, `rid` on each Soldier) and, for `nl2cypher`, `DEEPSEEK_API_KEY` in
`.env`. Neo4j Community has one database, so the runner **wipe-reloads per
condition**: ingest COMPLETE → score → ingest MASKED → score.

- **template** maps each `ref_query` to an `app.graph.templates` template (via
  `_TEMPLATE_MAP` in `engines.py`); reference queries the shipping app has no
  template for (company roster, enrol-range) report `no app template` — a real
  coverage finding.
- **nl2cypher** sends the question text to DeepSeek, executes the returned Cypher.

### Shaping live rows into result kinds (`shaping.py`)

Live engines return arbitrary Neo4j rows; `shaping.shape(rows, kind, …)` turns
them into the gold shape so every `result_kind` is scored (not just set/count):

- **histogram / aggregate** — parse aggregated rows (`{dept, n}` / `{avg, n}`),
  preferring the *department* column to match gold's grain; else reconcile rows→rids
  and compute from the corpus.
- **record_fields** — parse the catalogue's `collect({role,prenom,nom})` parent
  collection (PAR-01), regiment (UNANS, `[]` = correct abstention), trajectory.
- **linkage / partition** — per validation spec §7.1, the shared deterministic
  post-proc (soft-gap `w()`, parent-key clustering — the *same* code as the oracle)
  runs **end-to-end on the system's retrieved rows**. The runner also reports
  **`retrieval_recall`** (did the generated query surface the right candidates?),
  separating NL2Cypher's contribution from the decision step.
- Rows reconcile to `rid`s by matricule → name → (for homonyms) secondary fields.

A row set that can't be shaped is `unparseable`; an LLM that emits invalid Cypher
is `query_error` — **both count as score 0** (a failed answer is a system failure),
reported in the per-engine coverage table.

## RAG path (`--rag`, `rag.py`)

```bash
python validation/evaluate.py --rag      # Chroma + DeepSeek generation + Gemma judge
```

For every `rag`-mode question, per condition (own Chroma store under
`corpus/eval/chroma/{COMPLETE,MASKED}`; doc id `row_<rid>` → corpus rid):

- **Retrieval** (deterministic vs gold): `hit_rate@k`, `recall@k`, `nDCG@10`.
- **Correctness** (deterministic vs gold): coverage of the gold soldiers' names
  in the answer (set-like kinds only).
- **Faithfulness + abstention** (LLM judge): **Gemma 4 31B via OpenRouter**
  (`JUDGE_MODEL`, a *different model family* than the DeepSeek generator, per spec
  §7.1), temp-0, single structured call. Faithfulness = fraction of answer claims
  grounded in the retrieved context; abstention is scored CRAG-style — **abstaining
  beats hallucinating**: the report separates *hallucinated on unanswerable* (the
  real failure) from *over-abstained on answerable* (faithful but conservative when
  retrieval misses).

Needs `DEEPSEEK_API_KEY` (generation) + `OPENROUTER_API_KEY` (judge) in `.env`.
The v1.1 upgrade (spec) is per-claim citation checking.
