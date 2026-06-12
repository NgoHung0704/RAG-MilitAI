# MilitAI — Synthetic Dataset & Validation Report

**Scope.** This report documents (I) the construction of the synthetic validation
corpus and (II) the validation methodology and (III) the results of evaluating the
three MilitAI query modes (Template, NL2Cypher, RAG) against a controlled ground
truth. Machine-readable results accompany it at
[`corpus/eval/validation_results.json`](corpus/eval/validation_results.json); the
auto-generated scoreboard is [`corpus/eval/report.md`](corpus/eval/report.md).

**Why a synthetic corpus.** The real *contrôles de troupes* corpus has no ground
truth: we cannot know the true sibling sets, parent–child links, or origin
distributions, so we cannot measure whether a query system recovers them. A
synthetic corpus with **authored, planted truth** lets us (a) score query *logic*
and use-case *capability* exactly, and (b) measure *graceful degradation* under
the same sparsity the real registers exhibit. The gold is computed by **executing
verified canonical queries** against the corpus — never produced or judged by an
LLM — so it is an oracle, not an opinion.

---

## Part I — Construction of the synthetic dataset

### 1. Design principles

| Principle | Consequence |
|---|---|
| **Two conditions.** `COMPLETE` (all generated fields present) and `MASKED` (record-level tiered masking → real-corpus fill rates). | COMPLETE validates query logic & capability; MASKED validates the real recall ceiling. The **delta** is the cost of incomplete annotation. |
| **Deterministic generation.** One seeded RNG (`seed = 20260611`), fixed draw order. | Byte-for-byte reproducible; gold cannot drift. |
| **Oracle gold, not judged gold.** Gold = result of executing the Reference Query Catalogue on the corpus. | Removes LLM-judge bias from everything the gold can express; the judge is reserved only for RAG faithfulness (Part II §5). |
| **Schema-faithful.** Real 77-column CSV schema. | The corpus drops straight into the production ingest path. |

The corpus is **180 records** — deliberately small so every planted structure is
hand-auditable, yet large enough to host all use cases.

### 2. Generator architecture

A single deterministic pipeline (`validation/generate.py`, value pools in
`validation/pools.py`) runs in fixed stages: load & validate pools → build the
four gold companies → fill the background population → inject families → inject
vertical-link fathers → assign the stature cohort → inject mechanics records →
emit COMPLETE → apply tiered masking → emit MASKED + the generator's own gold.
All randomness flows from one RNG seeded per record id, so output is
order-independent and reproducible.

### 3. Value pools and the gazetteer

- **Surnames** are ALL-CAPS as in the registers. The 11 canonical catalogue
  names the reference questions bind to (`MARTIN, DUPONT, RENARD, MOREAU, ROUX,
  BERNARD, GIRARD, BLANC, LEROY, FAURE, CHALET`) are **reserved**: background
  fillers draw from a disjoint `BG_SURNAMES` pool so accidental duplicates never
  pollute the single-record / linkage probes.
- **Gazetteer.** Each commune maps to exactly one `(département, région, pays)`.
  Region is a deterministic function of department (`Finistère/Côtes-du-Nord/
  Morbihan → Bretagne`; `Bas-Rhin → Alsace`; etc.), which is what makes the
  region-grain migration and stature questions well-defined.
- **Text normalization.** Every name/place match in the oracle operates on a
  `norm()` shadow (NFKD-strip accents → lowercase → drop dashes/whitespace/
  apostrophes), so `André`≡`andre`, `Côtes-du-Nord`≡`cotesdunord`.

### 4. Gold companies A–D (migration probes)

Four companies are instantiated with **exact seeded origin distributions** — the
rosters *are* the migration gold:

| Company | n | Origin distribution (département → count) |
|---|---|---|
| compagnie A | 15 | Finistère 9, Côtes-du-Nord 3, Morbihan 3 (concentrated Breton) |
| compagnie B | 14 | Bas-Rhin 5, Moselle 5, Meurthe 4 (eastern) |
| compagnie C | 12 | Seine/Rhône/Gironde/Nord/Isère/Puy-de-Dôme ×2 (dispersed) |
| compagnie D | 14 | Seine 5, Finistère 4, Morbihan 3, Eure 2 (overlaps A on Brittany) |

A and D deliberately share Brittany, so the company-comparison question
(`RQ-MIG-03`) must surface overlap, not just per-company counts. Background
soldiers never join A–D, keeping the rosters exact.

### 5. Planted structures (the ground truth)

**Families (8)** — recorded as an equivalence partition:

| Family | Surname | Members | Should cluster? | Tests |
|---|---|---|---|---|
| FAM-CLEAN-1 | DUPONT | 3 | yes | sibling recovery (the hub family) |
| FAM-CLEAN-2/3/4 | LE GOFF / SCHMITT / TANGUY | 2 each | yes | sibling recovery |
| FAM-PARTIAL-1 | FAURE | 2 | yes (one sibling lacks birthplace) | name-only fallback, lower confidence |
| FAM-SINGLEP-1 | ROUSSEL | 2 | yes (one parent each) | partial-key handling |
| FAM-DECOY-1 | RENARD | 2 | **no** | same surname + father name, *different* mother/birthplace → must **not** merge |
| FAM-NEG-1 | MASSON | 2 | **no** | same surname, unrelated → not a family |

Sibling identity requires matching on **both** parents (`norm`-folded) plus a
**null-tolerant corroboration** in post-processing (birthplace agree-or-missing
**and** |birth-year gap| ≤ 25-or-missing), so masking-induced nulls do not
over-prune and the decoy's shared surname+father coincidence is overridden.

**Vertical links (5)** — a son and a candidate father record, scored by a
**soft generational-gap weight** `w(g)` (floor 16, full 25–45, taper to 58):

| Case | Son | Father gap | Gold |
|---|---|---|---|
| VERT-TRUE | DUPONT Jean | 30 yr | father rid 55 (w = 1.0) |
| VERT-YOUNG | GIRARD Louis | 17 yr | father rid 56 (admitted at softened floor) |
| VERT-OLD | ROUX Antoine | 52 yr | father rid 57 (admitted at softened ceiling) |
| VERT-DECOY | MOREAU Pierre | −2 yr | **none** (rejected, w = 0) |
| VERT-ABSENT | BLANC Jacques | — | **none** (named father has no record) |

DUPONT Jean is a *hub*: simultaneously a clean-family member, the VERT-TRUE son,
the RQ-MULTI birthplace anchor, and the RQ-PAR-01 subject.

**Stature cohort (~15)** — heights drawn N(region-mean, σ), expressed in
pied/pouce/ligne with a derived `taille_metre`: **Bretagne ≈ 169.8 cm** vs
**Alsace ≈ 164.2 cm** (COMPLETE), a real, recoverable regional difference.

**Trajectories (5)** — complete birth → enrolment → death-place chains; under
masking only **2 of 5** survive (death place collapses) — the trajectory-collapse
demonstration.

**Mechanics** — homonym pair (BERNARD Louis ×2, distinguishable by birthplace),
an unanswerable-regiment probe (CHALET Pierre), a guaranteed zero-result query
(died 1650), and a disambiguation case.

### 6. Consistency invariants (checked on every record)

`naissance_annee = enrolement_annee − enlistment_age` (age ∈ [17, 28]);
`deces_annee > enrolement_annee`; `nom` ALL-CAPS; father has no surname field
(inherits the soldier's `nom`), mother carries her maiden `mere_nom`; birthplace
fields agree via the gazetteer; `taille_metre` equals the pied/pouce/ligne
conversion within rounding; year fields are integers (so range/threshold queries
work); gold companies contain exactly their rosters.

### 7. Tiered masking → MASKED

Masking models **record-level thoroughness**, not independent field dropout.
Records are assigned **thoroughness tiers** — A (rich, 18) / B (standard, 63) /
C (thin, 99) — and each field is kept with a tier-dependent probability
calibrated so the marginal hits the real-corpus target. Three properties matter:

1. **Correlated co-masking.** Co-annotated fields (the `pere/mere` block, the
   `naissance_*` block, date triples) share one keep-decision per record, so
   masking never half-shreds a family key or a date.
2. **Family-key joint ≈ 45%.** Keeping parent fields in tiers A/B (never C)
   yields the realistic full-family-key survival without a separate constraint.
3. **Planted probes survive in A.** Ultra-rare fields (height, death place,
   pieve) survive only on their Tier-A planted subset, so each use case stays
   testable under MASKED while degradation is visible.

**Resulting fill rates** (COMPLETE → MASKED, selected fields):

| Field | COMPLETE | MASKED | | Field | COMPLETE | MASKED |
|---|---|---|---|---|---|---|
| nom / compagnie | 100% | 100% | | deces_annee | 100% | 27% |
| enrolement_annee | 100% | 83% | | grade_final | 100% | 25% |
| matricule | 100% | 84% | | regiment | 100% | 15% |
| naissance_lieu | 99% | 77% | | naissance_region | 13% | 11% |
| naissance_departement | 99% | 66% | | taille_metre | 7% | 2% |
| pere_prenom | 99% | 51% | | deces_departement | 3% | 1% |
| mere_nom | 99% | 42% | | | | |

These mirror the real registers: dense identity/unit/enrolment fields, mid-density
parent fields, and sparse death/rank/regiment/anthropometric fields.

---

## Part II — Validation methodology

### 1. The oracle: an executable Reference Query Catalogue

Each use-case intent has one canonical reference query `RQ-*`. The eval runner
(`validation/evaluate.py`, package `validation/eval/`) **executes each `RQ-*` over
the COMPLETE and MASKED CSVs in pandas**, with the catalogue's matching rules
(`norm()` folding; toponym Layer-M region→department expansion) and
post-processing (sibling corroboration, soft-gap `w()`, height conversion). The
result *is* the gold (catalogue §10). The runner is **decoupled from the
generator**: it reads only the two CSVs + `questions.jsonl` and recomputes gold
itself, so it cannot silently inherit a generator bug.

**Toponym Layer-M.** Place questions resolve a mention (FR or EN) to canonical
departments — *Brittany/Bretagne* → {Finistère, Côtes-du-Nord, Morbihan} — derived
from the corpus's own region→department co-occurrences plus a small EN→FR alias
table (source-language-first).

### 2. Engines under test

| Engine | What it is | Path |
|---|---|---|
| **reference** | the oracle itself — a 100%-correct deterministic baseline | pandas |
| **template** | the app's parameterized Cypher templates | Neo4j |
| **nl2cypher** | DeepSeek translates the NL question → Cypher, executed | Neo4j + DeepSeek |
| **RAG** | retrieve top-k chunks → DeepSeek generates a free-text answer | ChromaDB + DeepSeek |

The graph is loaded under the **fixed target schema** (parent `MERGE` so siblings
share a node, `Company` as primary unit, `region` on `Place`, year-as-int, `rid`
on every Soldier). Neo4j Community has one database, so conditions are evaluated
**one at a time** (wipe → ingest COMPLETE → score → ingest MASKED → score).

### 3. Metrics, by result kind

| Kind | Metric |
|---|---|
| `rid_set`, `rag_target`, `false_merge`, `trajectory` | precision / recall / **F1** over record ids |
| `count` | exact match |
| `histogram`, `histogram_pair` | **L1** error + normalised similarity |
| `partition` | pairwise P/R/F1 and **B³** F1; false-merge rate on decoys |
| `aggregate`, `aggregate_pair` | mean within tolerance + n exact |
| `linkage` | categorical correctness (TP/TN/FP/FN) over the planted link map |
| `record_fields`, `disambiguation` | exact field match + field-level accuracy |

### 4. Scoring the live engines

Live engines return arbitrary Neo4j rows; a **shaping layer**
(`validation/eval/shaping.py`) turns them into the gold shape so *every* kind is
scored (not only sets). Rows reconcile to corpus `rid`s by matricule → name →
(for homonyms) secondary fields. A row set that cannot be shaped is
**`unparseable`**; an LLM that emits invalid Cypher is **`query_error`** — **both
count as score 0** (a failed answer is a system failure), and both are reported
in the coverage table.

**Linkage & partition** are scored **end-to-end** (validation spec §7.1): the
generated query supplies the candidate set, and the *same* deterministic
post-processing module the oracle uses (soft-gap `w()`, parent-key clustering)
makes the decision. The runner **decomposes** this by also reporting
**retrieval recall** — did the generated Cypher surface the right candidates? —
separating NL2Cypher's contribution from the decision step.

### 5. Scoring the RAG path

For each `rag`-mode question, per condition (own Chroma store; doc id
`row_<rid>` ⇒ corpus rid):

- **Retrieval (deterministic vs gold):** hit-rate@k, recall@k, **nDCG@10**.
- **Correctness (deterministic vs gold):** coverage of the gold soldiers' names
  in the answer (set-like kinds).
- **Faithfulness + abstention (LLM judge):** **Gemma 4 31B via OpenRouter** — a
  *different model family* than the DeepSeek generator (the standard judge-bias
  mitigation), temperature 0, single structured call. Faithfulness = fraction of
  answer claims grounded in the retrieved context. Abstention is scored
  **CRAG-style** — abstaining beats hallucinating — and the report separates
  *hallucinated on unanswerable* (the real failure) from *over-abstained on
  answerable* (faithful but conservative when retrieval misses).

### 6. Two axes of measurement

1. **Engine accuracy** — a prediction vs the oracle gold for that condition. The
   reference engine is 1.0 on COMPLETE by construction; live engines reveal real
   system error.
2. **Information degradation** — MASKED gold vs COMPLETE gold,
   engine-independent: the intrinsic cost of incomplete annotation per use case.

---

## Part III — Results

### 1. Engine accuracy (mean headline score vs oracle gold)

| Engine | COMPLETE | MASKED |
|---|---|---|
| reference (oracle) | **1.000** | **1.000** |
| template | **1.000** | 0.980 |
| nl2cypher | 0.516 | 0.523 |

Live coverage (COMPLETE): template scored 7/10 applicable (3 have no app
template — company roster, enrol-range, parents — a real coverage gap);
nl2cypher scored 44/49, with 3 `unparseable` and 2 `query_error`.

### 2. Information degradation (MASKED recall vs COMPLETE truth)

| Use case | n | Mean recall vs COMPLETE | Reading |
|---|---|---|---|
| lookup | 14 | **0.986** | dense identity/unit/enrolment fields are robust |
| genealogy | 11 | **0.925** | planted probes forced into Tier A stay recoverable |
| mechanics | 5 | 0.800 | mixed (zero-result & disambiguation survive; regiment collapses) |
| migration | 8 | 0.787 | birthplace dropout → histograms undercount (absence ≠ zero) |
| bounded | 8 | 0.640 | death-year / rank / desertion are sparse under masking |
| anthropometric | 4 | 0.100 | height is ultra-rare → the cohort `n` collapses (means stay close; it is *recall* of the cohort that degrades) |

This curve is the headline scientific result: it quantifies, per use case, how
much answer quality the real corpus's sparsity costs — independent of any engine.

### 3. What the live engines revealed

**Template (1.000 / 0.980).** The catalogue-correct templates score perfectly on
COMPLETE. Notably, the app's `died_in_year` template now queries the
`deces_annee` *property* (not the `DIED_IN→Place` relationship), so it recovers
all dated deaths — a fix the validation loop surfaced and that the app adopted.

**NL2Cypher (0.516 / 0.523).** DeepSeek-generated Cypher is strong on targeted
lookups and weak where it must know data conventions:

- **Perfect (1.0):** surname lookup (`NAME-01/03`), full-name (`NAME-02`),
  matricule, decoy non-merge (`SIB-03`), homonym disambiguation (`DIS`),
  zero-result abstention (`ZERO`), and **3 of 5 vertical links** (VERT-01b/03/04).
- **Linkage decomposition** cleanly attributes the 2 failures: VERT-01a scored 0
  with **retrieval-recall 0.0** — the generated query never surfaced the father,
  so the failure is *retrieval*, not the soft-gap decision. Where retrieval
  succeeded (VERT-01b/03/04, retrieval-recall 1.0) the shared module linked
  correctly. Partition (`SIB-02`) reached **B³ 0.81** with retrieval-recall 0.80.
- **Systematic weaknesses (genuine findings, not harness bugs):** company
  filters collapse precision (`WHERE toLower(c.nom) CONTAINS 'a'` matches ~every
  company → `COMP-01` ≈ 0.0–0.15); two-company comparison emits
  `c.nom IN ['a','d']` against stored `compagnie A`/`compagnie D` → 0 rows
  (`MIG-03`); and `AVG(s.taille_metre)` raises a Neo4j type error because height
  is stored as a string (`ANTH-01/03` `query_error`) — the model does not know
  height needs post-processing.

### 4. RAG path

| Condition | hit@k | recall@k | nDCG@10 | name-coverage | faithfulness | abstention-acc |
|---|---|---|---|---|---|---|
| COMPLETE | 0.706 | 0.452 | 0.434 | 0.462 | **0.958** | 0.706 |
| MASKED | 0.706 | 0.378 | 0.375 | 0.344 | 0.885 | 0.529 |

The RAG story: **highly faithful** (≈0.96 — very low hallucination), with recall
**bounded by retrieval** — single-record questions (`REC-01`: hit 1.0, faithful
1.0, coverage 1.0) are answered well, while roster/aggregate questions exceed the
top-k window so the model **abstains rather than hallucinate**. Under the CRAG
framing (COMPLETE): of the unanswerable probe, the model **correctly abstained
with 0 hallucinations**; of 16 answerable questions, 5 were *over-abstained*
(faithful-but-conservative when retrieval missed, not a hallucination). MASKED
faithfulness dips (0.885) as thinner context invites more inference.

> *Determinism note.* The judge runs at temperature 0, but DeepSeek generation
> and the Gemma judge are not perfectly deterministic run-to-run (e.g. the
> zero-result probe hallucinated in one earlier run and abstained here). For a
> publishable figure, average a small number of runs and report the spread; the
> spec's v1.1 upgrade (per-claim citation checking) further hardens faithfulness.

### 5. Cross-cutting findings

- The **fixed-schema graph ingest is validated**: the three DUPONT brothers share
  one father `Person` node and graph sibling traversal returns the siblings —
  impossible under the shipping `CREATE`-based parent ingest.
- **Two query paths, complementary failure modes.** The KG path (template/
  nl2cypher) is exact when the query is right but brittle to NL→Cypher errors;
  the RAG path is faithful but retrieval-bounded. Neither dominates — which is the
  argument for offering both.
- The **degradation curve is the reusable artifact**: it sets realistic
  expectations for the real corpus (e.g. don't expect dense death-place
  trajectories; expect histograms to undercount).

---

## Limitations & future work

- **Live structured extraction is partial.** `histogram_pair`/`aggregate_pair`
  and trajectory `record_fields` shaping are best-effort; some live answers
  report `unparseable` (counted as 0). The oracle still scores them.
- **No `RQ-FOLD-01` handler.** The generator's question set added an accent-fold
  test; it is intentionally **not** guessed here pending its catalogue definition.
- **LLM-judge variance.** Single temp-0 call (per spec v1); multi-run averaging
  and per-claim citation checking (v1.1) are the rigor upgrades.
- **Scale.** N = 180 is chosen for auditability; marginal rates for the rarest
  fields are coarse at this size.

## Reproducibility

```bash
python validation/generate.py                 # regenerate corpus (byte-for-byte, seed in seed.txt)
python validation/evaluate.py                 # reference oracle + degradation (no API)
python validation/evaluate.py --live          # + template + nl2cypher (Neo4j + DeepSeek)
python validation/evaluate.py --live --rag    # + RAG (ChromaDB + DeepSeek + OpenRouter/Gemma judge)
```

Artifacts: `corpus/{complete,masked}.csv`, `corpus/eval/gold/RQ-*__*.json` (oracle
gold), `corpus/eval/results.json` + `rag_results.json` (per-row scores),
`corpus/eval/validation_results.json` (consolidated), `corpus/eval/report.md`
(scoreboard). Models: generator/NL2Cypher/RAG = DeepSeek `deepseek-chat`;
embeddings = `all-MiniLM-L6-v2`; RAG judge = `google/gemma-4-31b-it` (OpenRouter).
