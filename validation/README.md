# MilitAI synthetic validation corpus

Deterministic generator for the validation corpus specified in
[`specs/MilitAI_Synthetic_Validation_Spec.md`](../specs/MilitAI_Synthetic_Validation_Spec.md).

It produces a 180-record corpus with **authored ground truth**, a **masked**
view calibrated to the real-corpus fill rates, the **gold artifacts**, and a
**FR/EN question set** — to validate the three query modes (RAG, Template,
NL2Cypher) and the two use cases (genealogy, migration) against controlled truth.

## Quick start

```bash
cd validation
python generate.py     # writes corpus/  (csvs, gold/, reference_queries/, questions.jsonl, seed.txt)
python verify.py       # checks the §9 acceptance criteria (28 checks; exit 0 = all pass)

# optional — graph-side half of the Layer-1 dual-verification, needs Neo4j:
python ../scripts/ingest_neo4j.py --csv corpus/complete.csv
python verify_graph.py
```

No third-party deps beyond `pandas` (already in the project `requirements.txt`).
Tracks spec **v0.6** (two-layer query design, matching normalization, toponym enrichment).

## What gets generated (`validation/corpus/`)

| File | Contents |
|---|---|
| `complete.csv` | The truth — all generated fields present (no masking). 180 rows, real CSV schema. |
| `masked.csv` | Same 180 records, record-level tiered masking applied so fill rates match the real corpus. |
| `seed.txt` | The RNG seed. Regeneration is byte-for-byte reproducible. |
| `questions.jsonl` | 53 human-authored FR/EN questions (Layer 2), each with `stratum`, `ref_query`, `held_out`, `gold_ref` + conditions. |
| `reference_queries/catalogue.json` | Layer-1 reference queries (the oracle): per intent, the canonical Cypher, post-processing note, schema dependency, and the gold for both conditions. |
| `gazetteer.json` | Pinned toponym snapshot: regions/departments/communes with `wikidata_qid`, modern labels, P131 parent hierarchy, and `norm()` keys. |
| `gold/family_partition.json` | The 8 families, the true equivalence partition, and which sets must / must not cluster. |
| `gold/link_map.json` | Per vertical-link son: correct father record id (or none) + candidate gaps and soft-gap weights `w(g)`. |
| `gold/migration_origin.json` | Per gold company (A–D): exact origin histogram (COMPLETE + MASKED), roster, enrolment years. |
| `gold/mig_cohort_1710.json` | Birth-department distribution of the 1710 enlistment cohort. |
| `gold/stature_regions.json` | Per-region mean stature (COMPLETE + MASKED) and the >170 cm set. |
| `gold/trajectories.json` | The 5 complete birth→death trajectories + how many survive masking. |
| `gold/masked_survival.json` | For every planted probe: its tier and whether it survives masking (§4.2). |
| `gold/answers.json` | Per-question gold denotation for COMPLETE and MASKED. |

Record ids in every gold file are **0-based row positions**, identical across
`complete.csv` and `masked.csv`.

## The two conditions

- **COMPLETE** — all generated fields present. Validates query *logic* and
  use-case *capability* (sibling checks, generational linkage, birth→death
  trajectories all fire). Gold is computed here — it is the truth.
- **MASKED** — derived from COMPLETE by record-level **thoroughness tiers**
  (A rich 10% / B standard 35% / C thin 55%) so marginals match the real corpus.
  Validates *graceful degradation* and the real recall ceiling.

The **delta** between conditions quantifies the cost of incomplete annotation.

## Two-layer query design (§6)

Gold is never produced or judged by an LLM. Instead:

- **Layer 1 — reference-query catalogue** (`reference_queries/catalogue.json`) is
  the *oracle*: each intent is authored once as a canonical Cypher query (plus a
  post-processing step for aggregations and linkage). Gold is the result of that
  query. It is **dual-verified**: `verify.py` confirms the gold via an independent
  pandas computation; `verify_graph.py` (when Neo4j is up) runs the canonical
  Cypher and checks it returns the same set.
- **Layer 2 — question set** (`questions.jsonl`) is the FR/EN NL phrasings. Each
  question carries a difficulty `stratum` (`lookup` / `multi_hop` / `aggregation`
  / `unanswerable`), points at its `ref_query`, and a `held_out` flag marks
  reference-query *structures* to exclude from any NL2Cypher few-shot prompt so
  Layer 2 also tests generalization to unseen query shapes (query/template split).

`unanswerable` items (the regiment trap `Q-UNANS-REG`, the zero-result controls)
reward abstention over hallucination.

## Matching normalization + toponym enrichment (§2, v0.6)

`normalize.py` provides the two shared utilities (mirror them at graph ingest):

- **`norm()`** — fold-only matching key (NFKD strip accents → lowercase → drop
  dashes/whitespace/apostrophes). **Storage stays accented**; only *matching*
  folds. The fold-tests `Q-FOLD-01` ("Cotes-du-Nord" → `Côtes-du-Nord`) and
  `Q-FOLD-02` ("Rene" → `René`) use intentionally unaccented params and must
  return the accented gold. The canonical Cypher assumes a `*_norm` shadow
  property computed at ingest.
- **Pinned gazetteer** (`gazetteer.json`) — places carry a `wikidata_qid`, modern
  label, and a P131 parent hierarchy (commune → department → region). FR/EN place
  questions resolve against this frozen snapshot: `Q-XLING-01` resolves EN
  "Brittany" → region `Bretagne` (Q12130) → its departments (Finistère /
  Côtes-du-Nord / Morbihan) → the soldiers born there. QIDs are pinned where
  confident (the Brittany path is fully pinned) and `null` otherwise; the
  diachronic historical-name layer is scaffolded, not used in the demo.

## How it works

1. `pools.py` — authored value pools and the department→commune gazetteer.
2. `generate.py`
   - builds gold companies A–D with the exact seeded origin distributions (§5.3);
   - embeds the planted structures — 8 families (§5.1), 5 vertical-link cases
     (§5.2), the ~15-soldier stature cohort (§5.5), 5 complete trajectories,
     and the mechanics records (§5.4);
   - fills the background population to 180 (avoiding name collisions with the
     reserved linkage father keys);
   - assigns thoroughness tiers (forced for planted probes, balanced to 18/63/99);
   - **masks deterministically by tier priority** — for each field it keeps
     exactly `round(target × 180)` records, richest tier first, so that record
     completeness is correlated (rich records keep most fields) and the marginals
     hit §3.1 exactly. Ultra-rare / planted-only fields survive only on their
     Tier-A planted subset.
3. `gold.py` — computes every gold artifact from the authored records.
4. `questions.py` — the authored FR/EN questions; gold denotations are computed
   directly from the records so they are correct by construction in both conditions.
5. `verify.py` — checks the §9 acceptance criteria.

## Acceptance criteria (`verify.py`)

All 35 checks pass on a clean generation, covering the §9 list: 180 records;
MASKED marginals within ±5 pp (and within ±10 pp of the **real corpus** sample —
realism); family-key joint ≈ 45% (±3 pp); ultra-rare fields planted-only; exact
gold rosters and origin histograms (L1 = 0); all 8 families and 5 linkage cases
present and gold-consistent; stature regions separated; trajectory collapse under
masking; every question resolves to a Layer-1 ref query whose **pandas gold
matches** the question gold; all difficulty strata present incl. unanswerable +
regiment trap; held-out query structures flagged; FR/EN phrasings present and
distinct; zero-result controls empty; `norm()` folding + both fold-tests; gazetteer
resolves every birthplace and the Brittany→Bretagne path; and byte-for-byte
regeneration.

The graph-execution half of the Layer-1 dual-verification is `verify_graph.py`
(needs a running, ingested Neo4j; genealogy queries also need the §8 parent-MERGE
fix and are reported SKIP until then).

## Planted structures (cheat sheet)

| Structure | Where | Test family |
|---|---|---|
| FAM-CLEAN-1..4 (true sibling sets) | companies A, B, D | T-SIB-01/02 |
| FAM-DECOY-1 (must not merge) | background | T-SIB-03 (false-merge = 0) |
| FAM-PARTIAL-1 (one missing birthplace) | background | T-SIB-04 (name-only fallback) |
| FAM-SINGLEP-1 (one parent each) | background | partial-key handling |
| FAM-NEG-1 (same surname, unrelated) | background | T-SIB-05 |
| VERT-TRUE / YOUNG / OLD / DECOY / ABSENT | sons in A–D, fathers in background | T-VERT-01..05 |
| Gold companies A–D (seeded origins) | — | T-MIG-01..03 |
| 5 complete trajectories | background | T-MIG-04 / T-MIG-DEG |
| Stature cohort (Bretagne ≈169 cm vs Lorraine ≈165 cm) | A, B, D | T-ANTH-01..03 |
| Homonyms / surnom alias / accented place / Corse pieve / partial dates | mechanics block | T-MECH-* |

## Note for the graph (Neo4j) genealogy tests

The current `scripts/ingest_neo4j.py` (line ~241) `CREATE`s parent nodes, so
siblings do not share a parent node and graph-based family traversal is
impossible. To run the T-SIB **graph** tests, switch that to `MERGE` on a
composite parent identity (father on soldier-surname + `pere_prenom`; mother on
`mere_nom` + `mere_prenom`). RAG/CSV-layer clustering does not depend on this.
