# MilitAI — Solution Design & Technical Reference

> A hybrid query platform for French military records of the *Ancien Régime*
> (*contrôles de troupes*, 17th–18th century), built around a knowledge graph
> + vector store, with three query modes and a **decoupled, measurable**
> validation harness.

This document is the single, detailed reference for the whole solution: the
architecture and how the components connect, the data and its exploratory
analysis, the synthetic corpus and how it is built, all data enrichment
(including the gazetteer), the three query pipelines and their templates, the
RAG construction, the exact LLMs and versions, the validation protocol and the
results, and the analytic tabs of the UI.

It complements two existing documents:

- [`README.md`](../README.md) — install / run / operate.
- [`validation/VALIDATION_REPORT.md`](../validation/VALIDATION_REPORT.md) — the
  formal synthetic-dataset + validation report (Parts I–III).

---

## Table of contents

1. [Overview & motivation](#1-overview--motivation)
2. [System architecture](#2-system-architecture)
3. [The data — real archive & EDA](#3-the-data--real-archive--eda)
4. [The synthetic validation corpus](#4-the-synthetic-validation-corpus)
5. [Data enrichment & the gazetteer](#5-data-enrichment--the-gazetteer)
6. [Ingestion: graph & vector store](#6-ingestion-graph--vector-store)
7. [The three query pipelines](#7-the-three-query-pipelines)
8. [RAG construction in detail](#8-rag-construction-in-detail)
9. [LLMs, embeddings & versions](#9-llms-embeddings--versions)
10. [Validation protocol](#10-validation-protocol)
11. [Results](#11-results)
12. [The analytic tabs (UI)](#12-the-analytic-tabs-ui)
13. [Reproducibility & operations](#13-reproducibility--operations)
14. [Limitations & future work](#14-limitations--future-work)
15. [Appendix — file map](#15-appendix--file-map)

---

## 1. Overview & motivation

MilitAI lets a historian or social scientist ask questions of a large register
of soldiers and get back **exact**, **source-linked**, and — uniquely —
**measurable** answers. It exposes three complementary query modes over the same
data:

| Mode | Mechanism | Strength | Weakness |
|---|---|---|---|
| **Template** | Hand-written parameterized Cypher on Neo4j | Exact, deterministic, transparent | Bounded to the templates that exist |
| **NL2Cypher** | LLM translates a natural-language question → Cypher → Neo4j | Open-ended graph queries | Brittle to NL→Cypher errors / data conventions |
| **RAG** | Semantic retrieval over a vector store → LLM free-text answer | Natural narrative answers, source citations | Recall bounded by the top-k retrieval window |

The central methodological contribution is the **validation harness**: because
the real archive has *no ground truth* (we cannot know the true sibling sets,
parent–child links, or origin distributions), the project ships a **synthetic
corpus with authored, planted truth** in two conditions — **COMPLETE** (every
field present) and **MASKED** (fields dropped to mirror the real corpus's
sparsity). Scoring each query mode against an **oracle gold** (computed by
*executing* canonical queries, never judged by an LLM) yields two things:

1. **Engine accuracy** — how well each mode recovers the planted truth.
2. **Information degradation** — the intrinsic cost, per use case, of the real
   archive's incomplete annotation, independent of any engine.

---

## 2. System architecture

### 2.1 Component diagram

```text
                              +-----------------------------------+
                              |          Streamlit UI             |
                              |           app/main.py             |
                              |   6 tabs · dataset switch (sidebar)|
                              +-----------------+-----------------+
                                                |
   session state: DeepSeek client (OpenAI-compatible) · active dataset · bootstrap
                                                |
        +-------------------+-------------------+-------------------+----------------+
        |                   |                   |                   |                |
  +-----v-----+      +------v------+     +------v------+     +------v------+   +-----v------+
  | Template  |      |  NL2Cypher  |     |     RAG     |     | Explore /   |   | Showcase + |
  | panel     |      |  panel      |     |  panel      |     | Atlas panel |   | Report     |
  +-----+-----+      +------+------+     +------+------+     +------+------+   +-----+------+
        |                   |                   |                   |                |
  graph/templates    graph/nl2cypher       rag/chain          geo + pandas      showcase_loader
  (Cypher catalog)   (LLM→Cypher)        (retrieve+LLM)       aggregations      report_loader
        |                   |                   |                   |                |
        +--------+----------+                   |              gazetteer.json    eval artifacts
                 |                              |              (geo.py)          (results.json,
          +------v------+                +------v------+                          rag_results.json)
          | Neo4j ×3    |                |  ChromaDB   |
          | (per dataset|                | 3 collections|
          |  bolt 7687/ |                | one persist  |
          |  7688/7689) |                |  dir         |
          +-------------+                +-------------+

   Data sources:  data/*.csv (real ~82k)  ·  validation/corpus/{complete,masked}.csv (synthetic 180)
```

### 2.2 How the components connect

- **Entrypoint — [`app/main.py`](../app/main.py).** On startup it (a) builds the
  DeepSeek client as an OpenAI-compatible instance (`base_url=https://api.deepseek.com`)
  and stashes it in `st.session_state`; (b) runs idempotent first-run ingestion
  via [`app/bootstrap.py`](../app/bootstrap.py); (c) renders the sidebar, which
  returns the **active dataset key**; (d) resolves the Neo4j driver for that
  dataset and dispatches to the six tab panels, passing the driver, the LLM
  client, and the active Chroma collection name.

- **Configuration registry — [`app/config.py`](../app/config.py).** A single
  `DATASETS` dict is the source of truth. Each dataset entry carries its
  `neo4j_uri`, `chroma_collection`, `csv` path, optional `questions`/`gold`
  paths, a `schema` flag (`legacy` vs `fixed`), and metadata (`records`,
  `nature`, `condition`). Global constants: `EMBEDDING_MODEL="all-MiniLM-L6-v2"`,
  `RAG_TOP_K=5`, `CHROMA_PERSIST_DIR="data/chroma_db"`, the three Neo4j URIs.

- **Dataset isolation.** Neo4j Community permits only one database per instance,
  so the three logical datasets run as **three separate Neo4j instances** on
  bolt ports `7687` (real), `7688` (synth_complete), `7689` (synth_masked). A
  fourth, profile-gated instance on `7690` (`neo4j-eval`) is a scratch DB used
  only by the offline eval runner. ChromaDB instead holds all three as **distinct
  collections in one persist directory** (`soldiers`, `synth_complete`,
  `synth_masked`).

- **Bootstrap scoping.** `MILITAI_AUTOINGEST` ∈ `{all (default), synth, off}`
  controls first-run ingestion. Bootstrap checks each backend
  (`MATCH (n:Soldier) RETURN count(n)` for Neo4j; collection count for Chroma)
  and ingests only when empty — so restarts are instant.

- **Connection pooling — [`app/graph/connection.py`](../app/graph/connection.py).**
  Drivers are cached per-URI; `get_driver_for_dataset(key)` resolves the URI
  from the registry; `is_reachable(uri)` is a non-raising health probe used by
  the sidebar status badges.

### 2.3 Two query paths, complementary failure modes

The architecture deliberately offers **two independent paths to an answer**:

- The **knowledge-graph path** (Template + NL2Cypher → Neo4j) is *exact* when the
  query is right, but brittle to NL→Cypher errors.
- The **RAG path** (Chroma → DeepSeek) is *faithful* but retrieval-bounded.

Neither dominates — which is the design argument for shipping both, and the
validation harness quantifies exactly where each wins.

---

## 3. The data — real archive & EDA

### 3.1 Provenance & shape

Source records originate from the French military archives ecosystem
(**Mémoire des Hommes / SHDGR**) — the *contrôles de troupes* registers. The
working file is a **unified annotation CSV**:

- [`data/full_unified_annotations.csv`](../data/full_unified_annotations.csv) —
  **82,821 rows × 77 columns** (~34 MB).
- `full_unified_annotations_patch.csv` — the patched variant used for full
  ingestion runs (same row count).
- `sample_of_data.csv` — a 3-record sample for fast iteration.

The 77-column schema is the canonical record shape that the synthetic corpus
also adopts verbatim, so synthetic data drops straight into the production
ingest path. Columns group into:

| Group | Columns (selected) |
|---|---|
| **Provenance** | `source_image, double_page, section, registre, numero_page, side, line, double_page_url, ark_url` |
| **Identity** | `nom, nom_autre, prenom, surnom, age, profession` |
| **Anthropometry** | `pied, pouce, ligne, taille_metre` |
| **Birth** | `naissance_{jour,mois,annee,departement,lieu,juridiction,region,pays,pieve}` |
| **Domicile** | `domicile_{departement,lieu,pays}` |
| **Marriage** | `mariage_{jour,mois,annee,lieu,departement,pays}` |
| **Death** | `deces_{jour,mois,annee,lieu,commune,departement,pays}` |
| **Parents** | `pere_{decede,prenom,autre_prenom,profession}, mere_{decedee,nom,autre_nom,prenom,autre_prenom}` |
| **Service** | `regiment, compagnie, bataillon, matricule, grade_final, grade_1, grade_2, grade_3` |
| **Events** | `enrolement_{jour,mois,annee}, renvoi_{…}, desertion[_…]` |
| **Status** | `sort, passe, invalide, ne_au_regiment, commentaires` |

### 3.2 Exploratory data analysis (real corpus, n = 82,821)

> Reproducible: [`scripts/eda.py`](../scripts/eda.py) computes everything below
> (fill rates, cardinality, top values, numeric summaries, and the
> masked-vs-real calibration check) and writes
> [`docs/eda/eda_results.json`](eda/eda_results.json). Run `python scripts/eda.py`.

**Fill rates — the defining feature is sparsity.** Identity and unit fields are
dense; biographical, anthropometric, and death fields are sparse:

| Field | Fill | | Field | Fill | | Field | Fill |
|---|---:|---|---|---:|---|---|---:|
| `nom` | 100.0% | | `naissance_departement` | 65.7% | | `regiment` | 14.6% |
| `prenom` | 99.7% | | `pere_prenom` | 50.8% | | `age` | 12.8% |
| `compagnie` | 99.3% | | `mere_prenom` | 45.2% | | `naissance_region` | 11.4% |
| `matricule` | 83.6% | | `mere_nom` | 42.3% | | `profession` | 4.3% |
| `enrolement_annee` | 82.9% | | `deces_annee` | 26.8% | | `mariage_annee` | 3.1% |
| `surnom` | 78.4% | | `grade_final` | 25.3% | | `pied` | 2.4% |
| `naissance_lieu` | 77.3% | | `naissance_annee` | 21.4% | | `taille_metre` | 0.8% |
| `naissance_pays` | 73.7% | | | | | `deces_lieu` | 0.5% |

> This sparsity profile is the empirical target the synthetic **MASKED**
> condition is calibrated to reproduce (see §4.6 — the masked fill rates match
> these within ~1 point on most fields).

**Cardinality.** `nom`: 46,157 distinct surnames; `prenom`: 5,670; `compagnie`:
1,094; `naissance_departement`: 225; `naissance_pays`: 71; `grade_final`: 224;
`profession`: 237; `regiment`: only **4** (the corpus is dominated by a few
regiments).

**Top categorical values.**

- **Regiments:** Régiment du Limousin (~5,400), Régiment de Talaru (~5,200),
  Limousin 3e bataillon (~850), Royal-Corse (~640).
- **Birth country (`naissance_pays`):** France ~50k, then Allemagne (4,048),
  Belgique (2,657), Italie (798), Irlande (661), Écosse (647), Suisse (557) —
  a visibly multinational rank-and-file.
- **Birth department (`naissance_departement`, numeric codes):** 75 (Paris/Seine,
  2,840), 57 (Moselle, 2,227), 59 (Nord, 1,756), 54 (Meurthe, 1,674), 62
  (Pas-de-Calais, 1,331) — concentrated in the north-east.
- **Final rank:** grenadier (3,923), caporal (3,065), sergent (2,923),
  anspessade (2,545).
- **First names:** Jean (9,904), Pierre (6,932), François (5,456), Joseph.

**Temporal coverage.** `enrolement_annee` spans **1614–1858** (median **1747**);
there are visible enrolment spikes around the Revolutionary years (1792: 581;
1793: 211). `deces_annee` median 1748. The bulk of the corpus is solidly 18th
century.

**Data-quality observations (worth flagging to users):**

- **Encoding.** The raw real CSV is Latin-1/CP1252 (e.g. `Régiment` renders as
  `R�giment` when read as UTF-8). Display layers must decode accordingly.
- **Out-of-range / dirty numerics.** `naissance_annee` shows a min of `17` and
  `age` a max of `1792` — transcription / OCR artefacts. Range and threshold
  queries on the real data should defend against these; the synthetic corpus
  enforces integer, in-range year fields by construction (§4.7).
- **Anthropometry is essentially absent.** `taille_metre` is non-null on only
  **14 rows** in the full file (0.8% of `taille_metre`; even rarer if measured
  on the patch). Height-based analyses on the real corpus are effectively
  impossible — exactly the finding the synthetic "anthropometric" use case is
  designed to make measurable.

The Explore/Atlas tab (§12.4) surfaces these distributions live, always
annotating each plot with its sample size `n` and warning when a group falls
below the `N_MIN = 10` threshold.

---

## 4. The synthetic validation corpus

Full detail lives in [`validation/VALIDATION_REPORT.md`](../validation/VALIDATION_REPORT.md);
this section summarizes the construction. The generator
([`validation/generate.py`](../validation/generate.py), pools in
[`validation/pools.py`](../validation/pools.py)) is **user-owned**; the eval
runner is owned separately and is *decoupled* from it (§10).

### 4.1 Why synthetic, and why two conditions

The real corpus has no ground truth. A synthetic corpus with **authored, planted
truth** lets us score query *logic* exactly and measure *graceful degradation*
under realistic sparsity. Two conditions are emitted from the same records:

- **COMPLETE** — every generated field present → validates query logic &
  use-case capability.
- **MASKED** — record-level tiered masking calibrated to the real fill rates →
  validates the real recall ceiling and graceful degradation.

The **delta** between them is the cost of incomplete annotation, per use case.

### 4.2 Determinism

One seeded RNG, **`SEED = 20260611`**, with a per-record stream
(`random.Random(SEED * 100000 + rid)`) and fixed draw order, makes the corpus
**byte-for-byte reproducible** so the gold cannot drift. The snapshot date is
pinned to `2026-06-11`. Corpus size is **180 records** — small enough that every
planted structure is hand-auditable, large enough to host all use cases.

### 4.3 Generator pipeline (fixed stages)

```text
load & validate pools
  → build 4 gold companies (seeded origin distributions)
  → fill background population (disjoint surname pool)
  → inject 8 families (clean / partial / single-parent / decoy / negative)
  → inject 5 vertical-link fathers (soft generational gap)
  → assign the stature cohort (region-conditioned heights)
  → inject mechanics records (homonym / unanswerable / zero-result / disambiguation)
  → emit COMPLETE
  → rebalance thoroughness tiers (A=18, B=63, C=99)
  → apply tiered masking → emit MASKED
  → compute & emit gold artifacts
```

### 4.4 Value pools & reserved names

- **Surnames are ALL-CAPS** as in the registers. The **11 canonical catalogue
  names** the reference questions bind to — `MARTIN, DUPONT, RENARD, MOREAU,
  ROUX, BERNARD, GIRARD, BLANC, LEROY, FAURE, CHALET` — are **reserved**;
  background fillers draw from a disjoint `BG_SURNAMES` pool so accidental
  duplicates never pollute single-record / linkage probes.
- **Ranks** are deliberately limited to enlisted grades (soldat, caporal,
  sergent, fourrier, tambour, anspessade) — no officer ranks.
- **Departments** map cleanly to regions (Bretagne, Alsace, Lorraine,
  Île-de-France, Lyonnais, Guyenne, Flandre, Dauphiné, Auvergne, Normandie,
  Corse), which is what makes region-grain migration and stature questions
  well-defined.

### 4.5 The planted ground truth

- **Gold companies A–D** with exact seeded origin distributions — the rosters
  *are* the migration gold. A (Breton-concentrated, n=15), B (eastern, n=14),
  C (dispersed, n=12), D (mixed, n=14, overlapping A on Brittany so the
  company-comparison query must surface overlap).
- **8 families** as an equivalence partition: clean families (DUPONT ×3,
  LE GOFF/SCHMITT/TANGUY ×2) that *should* cluster; a partial family (FAURE, one
  sibling lacks birthplace → name-only fallback); a single-parent family
  (ROUSSEL); a **decoy** (RENARD — same surname + father name but different
  mother/birthplace → must **not** merge); a **negative** (MASSON — same surname,
  unrelated). Sibling identity requires matching **both** parents (norm-folded)
  plus null-tolerant corroboration (birthplace agree-or-missing **and**
  |birth-year gap| ≤ 25-or-missing).
- **5 vertical links** (son ↔ candidate father), scored by a soft
  generational-gap weight `w(g)` (floor 16, full 25–45, taper to 58): a true
  link (gap 30, w=1.0), a young-but-admissible (17), an old-but-admissible (52),
  a decoy (−2, rejected), and an absent father (named but no record).
  **DUPONT Jean is a hub** — a clean-family member, the true vertical-link son,
  and the subject of the parents and multi-criteria probes.
- **Stature cohort (~15)** with region-conditioned heights: Bretagne ≈ 169.8 cm
  vs Alsace ≈ 164.2 cm (COMPLETE) — a real, recoverable regional difference,
  expressed in pied/pouce/ligne with a derived `taille_metre`.
- **5 trajectories** (birth → enrolment → death-place chains) of which only
  **2 of 5 survive masking** (death place collapses) — the trajectory-collapse
  demonstration.
- **Mechanics:** a homonym pair (BERNARD Louis ×2, distinguishable by
  birthplace), an unanswerable-regiment probe (CHALET Pierre), a guaranteed
  zero-result query (died 1650), and a disambiguation case.

### 4.6 Tiered masking → MASKED

Masking models **record-level thoroughness**, not independent field dropout.
Records are assigned tiers — **A (rich, 18) / B (standard, 63) / C (thin, 99)** —
and each field is kept with a tier-dependent probability calibrated so the
marginal hits the real target. Three properties matter:

1. **Correlated co-masking** — co-annotated blocks (the parent block, the
   `naissance_*` block, date triples) share one keep-decision, so masking never
   half-shreds a family key or a date.
2. **Family-key joint ≈ 45%** — parent fields kept only in tiers A/B.
3. **Planted probes survive in Tier A** — ultra-rare fields (height, death
   place, pieve) survive only on their Tier-A planted subset, so each use case
   stays testable under MASKED while degradation is visible.

**Masked fill rates match the real archive (validation that the calibration
works):**

| Field | Real | Synth MASKED | | Field | Real | Synth MASKED |
|---|---:|---:|---|---|---:|---:|
| `matricule` | 83.6% | 83.9% | | `mere_nom` | 42.3% | 42.2% |
| `naissance_lieu` | 77.3% | 77.2% | | `deces_annee` | 26.8% | 27.2% |
| `enrolement_annee` | 82.9% | 82.8% | | `grade_final` | 25.3% | 25.0% |
| `pere_prenom` | 50.8% | 51.1% | | `regiment` | 14.6% | 15.0% |

Across the 22 focus fields the mean absolute gap is **0.37 points** (max 1.4, on
the ultra-rare `taille_metre`) — i.e. the masking calibration reproduces the real
archive's sparsity almost exactly. Numbers from
[`docs/eda/eda_results.json`](eda/eda_results.json) → `masked_vs_real`.

### 4.7 Consistency invariants

Checked on every record: `naissance_annee = enrolement_annee − enlistment_age`
(age ∈ [17, 28]); `deces_annee > enrolement_annee`; `nom` ALL-CAPS; father
inherits the soldier's surname while the mother carries her maiden `mere_nom`;
birthplace fields agree via the gazetteer; `taille_metre` equals the
pied/pouce/ligne conversion within rounding; year fields are integers (so range
queries behave); gold companies contain exactly their rosters.
[`validation/verify.py`](../validation/verify.py) enforces these acceptance
criteria; `verify_graph.py` checks the graph-ingest invariants.

---

## 5. Data enrichment & the gazetteer

Enrichment happens at three layers: the gazetteer (place → region/country),
text normalization (accent-folding), and toponym resolution (mention → canonical
departments).

### 5.1 The gazetteer

- **Source of truth.** [`validation/corpus/gazetteer.json`](../validation/corpus/gazetteer.json)
  — a frozen, pinned gazetteer with top-level `departments` and `regions`. Each
  **commune maps to exactly one `(département, région, pays)`**, and region is a
  deterministic function of department
  (`Finistère/Côtes-du-Nord/Morbihan → Bretagne`; `Bas-Rhin → Alsace`; …). This
  determinism is what makes the region-grain migration and stature questions
  well-defined.
- **Coordinate resolution — [`app/geo.py`](../app/geo.py).** The Atlas map needs
  lat/lon per place. `department_coords()` / `region_coords()` read the
  gazetteer first; `_extract_coords()` accepts several shapes
  (`{lat,lon}`, GeoJSON `coordinates:[lon,lat]`, `{coordinates:{lat,lon}}`,
  `"lat,lon"` strings).
- **Centroid fallback.** Until real coordinates are populated, a built-in table
  of ~14 department centroids and ~11 region centroids (e.g. Finistère
  `(48.25, -4.0)`, Bas-Rhin `(48.6, 7.5)`, Bretagne `(48.2, -3.0)`) provides
  honest approximate placement. `coords_loaded_from_gazetteer()` reports whether
  real coordinates have superseded the fallback, and the Atlas tab reports any
  uncovered count rather than silently dropping points.

> **Project note:** `Place.coords` (Wikidata P625) is currently a null scaffold;
> the plan is to populate it later from a frozen Wikidata / WHG dump, at which
> point the gazetteer supersedes the centroid fallback.

### 5.2 Text normalization

Every name/place match in the oracle and in graph matching operates on a
**`norm()` shadow**: NFKD-decompose → strip accents → lowercase → drop
dashes/whitespace/apostrophes. So `André ≡ andre` and
`Côtes-du-Nord ≡ cotesdunord`. In the graph these are stored as `*_norm`
property shadows (`nom_norm`, `prenom_norm`, …) with indexes, so fold-tolerant
matching is cheap.

### 5.3 Toponym resolution — "Layer M"

Place questions resolve a mention (FR **or** EN) to canonical departments:
*Brittany / Bretagne* → `{Finistère, Côtes-du-Nord, Morbihan}`. The expansion is
derived from the corpus's own region→department co-occurrences plus a small
EN→FR alias table (source-language-first: `brittany→Bretagne`,
`corsica→Corse`, …). This lives in
[`validation/eval/toponym.py`](../validation/eval/toponym.py) and lets the eval
score cross-lingual and region-grain migration questions correctly.

---

## 6. Ingestion: graph & vector store

### 6.1 Graph ingestion — `scripts/ingest_neo4j.py`

Reads a CSV (by `--dataset`, `--csv`, or `--sample`), sets up the schema, then
ingests in chunks (`--chunk-size`, default 5000). Per chunk, in order: soldiers
(`MERGE`), birth/death/domicile/marriage places, regiments, desertion/discharge,
companies, ranks, parents, archive records. Null/empty relationships are skipped.

**Node labels & key constraints** ([`app/graph/schema.py`](../app/graph/schema.py)):

| Node | Identity / constraint |
|---|---|
| `Soldier` | composite key (`nom, prenom, source_image, line_idx`); plus `rid` in the fixed schema; `*_norm` shadows; year fields as int |
| `Place` | unique `(lieu, departement, pays)` — **deduplicated** |
| `Regiment` | unique `nom` |
| `Company` | unique `nom` (primary unit in the fixed schema) |
| `Rank` | unique `nom` |
| `Person` | parent node, key `(role, nom_norm, prenom_norm)` |
| `ArchiveRecord` | unique `source_image` |

**Relationships:** `BORN_IN{jour,mois,annea}`, `DIED_IN{…}`, `DOMICILED_IN`,
`MARRIED_IN{…}`, `SERVED_IN{matricule,enrolement_annea}`, `BELONGS_TO` (→Company),
`HELD_RANK{order∈"1"/"2"/"3"/"final"}`, `DESERTED_FROM{…}`, `DISCHARGED_FROM{…}`,
`CHILD_OF{role∈"father"/"mother"}`, `SOURCED_FROM` (→ArchiveRecord).

**The fixed-schema fix.** The crucial difference between `legacy` (real, shipping)
and `fixed` (synthetic, target) ingest is that parents are **`MERGE`d** so the
three DUPONT brothers share **one** father `Person` node — making graph sibling
traversal possible. Under the legacy `CREATE`-based ingest each child gets its
own father node and siblings cannot be recovered. The validation loop surfaced
this, and the fixed schema is the recommended target.

### 6.2 Vector ingestion — `scripts/ingest_rag.py` → `app/rag/ingestion.py`

Each CSV row is serialized by `soldier_to_text()` into a **human-readable French
text block** covering identity, birth, domicile, marriage, enrolment, regiment,
family, status, and source. The block is embedded with `all-MiniLM-L6-v2` and
**upserted** into a ChromaDB `PersistentClient` collection (id `row_<rid>` /
`<id>`), with metadata (`nom, prenom, surnom, regiment, naissance_annee,
deces_annee, source_image, ark_url, double_page_url`) carried alongside for
source attribution. Collections are per-dataset (`soldiers`, `synth_complete`,
`synth_masked`) inside one persist dir; batch size defaults to 500.

---

## 7. The three query pipelines

### 7.1 Template mode — `app/graph/templates.py` + `app/ui/template_panel.py`

A registry of **parameterized Cypher templates** (`Template{id, name,
description, params:[ParamDef], cypher}`). The panel renders a dynamic form from
`template.params` (int → `number_input`, str → `text_input`), validates required
params, executes `run_template(driver, template, params)`, shows results as a
DataFrame, and **always shows the exact Cypher** in an expander. The catalogue:

| id | Params | Intent |
|---|---|---|
| `by_surname` | `nom` | surname (case-insensitive `CONTAINS`) |
| `by_full_name` | `prenom, nom` | first name + surname |
| `died_in_year` | `annee` | deaths in a year (now queries the `deces_annee` **property**, not the `DIED_IN` relationship — a fix the validation loop surfaced) |
| `died_year_surname` | `annee, nom` | deaths in a year filtered by surname |
| `born_in_place` | `lieu` | born in a place (`BORN_IN→Place`) |
| `born_year_range` | `annee_min, annee_max` | birth-year range |
| `in_regiment` | `regiment` | roster of a regiment |
| `enlisted_year` | `annee` | enrolled in a year |
| `by_final_rank` | `grade` | by final rank (`HELD_RANK{order:'final'}`) |
| `from_department` | `departement` | birth **or** domicile department |
| `soldier_parents` | `nom` | a soldier with collected parents (`CHILD_OF→Person`) |
| `deserted` | — | soldiers who deserted (`DESERTED_FROM`) |

Example (`by_surname`):

```cypher
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS toLower($nom)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       s.naissance_annee AS naissance_annee, s.naissance_lieu AS naissance_lieu,
       s.regiment AS regiment, s.matricule AS matricule
ORDER BY s.nom, s.prenom
```

### 7.2 NL2Cypher mode — `app/graph/nl2cypher.py` + `app/ui/nl2cypher_panel.py`

```text
NL question → DeepSeek (system = full schema + rules + 9 few-shot examples)
           → raw Cypher (markdown fences stripped)
           → executed on the active Neo4j driver
           → (cypher, rows); ValueError on execution failure
```

The system prompt (`SCHEMA_DESCRIPTION`) injects the **entire graph schema** plus
hard rules that encode the data conventions the model must respect:

- surnames are ALL CAPS; dates are separate int properties (never `date()`);
  `toLower() + CONTAINS` for fuzzy name match; `Place` dedup on
  `(lieu, departement, pays)`; `HELD_RANK.order='final'` for the final rank;
  sibling = same father **and** mother; `MATCH` vs `OPTIONAL MATCH` guidance;
  company labels are full strings (`compagnie A`).

The panel exposes the **generated Cypher** in an expander and renders rows as a
DataFrame; on error it shows the Cypher plus the Neo4j error so the failure is
transparent. DeepSeek call: `model="deepseek-chat"`, `max_tokens=512`,
temperature unset (API default).

### 7.3 RAG mode

Covered in full in §8.

---

## 8. RAG construction in detail

`app/rag/{ingestion,retriever,chain}.py` + `app/ui/rag_panel.py`.

### 8.1 Index

CSV row → `soldier_to_text()` French narrative → embedded with
**`all-MiniLM-L6-v2`** (384-dim SentenceTransformer) → upserted into a ChromaDB
collection with source metadata (§6.2).

### 8.2 Retrieve — `app/rag/retriever.py`

`get_collection()` opens the existing persistent collection with a
`SentenceTransformerEmbeddingFunction(model_name)`. `retrieve(query, k, …)` runs
`collection.query(query_texts=[query], n_results=min(k, count), include=[documents,
metadatas, distances])` and returns a list of
`{"text", "metadata", "distance"}` (lower distance = closer). Default
**`k = RAG_TOP_K = 5`**.

### 8.3 Generate — `app/rag/chain.py`

`build_rag_prompt()` formats the chunks into numbered `[Record i] (source: <ark>)`
blocks followed by the question. The call:

```python
client.chat.completions.create(
    model="deepseek-chat",
    max_tokens=1024,
    messages=[{"role": "system", "content": _SYSTEM_PROMPT},
              {"role": "user",   "content": prompt}],
)
```

System prompt (verbatim intent):

> "You are a historian specialising in French Ancien Régime military records
> (17th–18th century). You answer questions about soldiers based **ONLY** on the
> archival records provided as context. If the answer cannot be found in the
> context, say so clearly — do not invent information. When you cite a soldier,
> mention their name and the source record if available. Reply in the same
> language the user asked the question in."

The grounding-only instruction and "say so clearly" are what produce the **high
faithfulness / abstention** behaviour measured in §11. `answer_with_rag()`
returns `{"answer", "sources"}`, and the panel lists the source records
(name, regiment, `ark_url`, `source_image`) in an expander so every answer is
traceable to the archive.

---

## 9. LLMs, embeddings & versions

| Role | Model / id | Where | Params |
|---|---|---|---|
| **RAG generation** | DeepSeek `deepseek-chat` (OpenAI-compatible API) | `app/rag/chain.py` | `max_tokens=1024`, temp = API default |
| **NL2Cypher generation** | DeepSeek `deepseek-chat` | `app/graph/nl2cypher.py` | `max_tokens=512`, temp = API default |
| **Embeddings** | `all-MiniLM-L6-v2` (SentenceTransformers, 384-dim) | `app/config.py`, ingestion & retrieval | — |
| **RAG faithfulness/abstention judge** | `google/gemma-4-31b-it` via **OpenRouter** | `validation/eval/rag.py` | **temperature 0**, single structured call, `max_tokens≈400` |

Design choices: a **single DeepSeek key** powers both generative paths; the
**judge is a different model family** (Gemma vs DeepSeek) — the standard
judge-bias mitigation — and runs at temperature 0 for stability. The judge is
reserved **only** for RAG faithfulness; everything the oracle can express is
scored deterministically, never by an LLM.

> Note: the dataset comprises historical French archive records; the LLM choices
> above (DeepSeek generation + a cross-family Gemma judge) are what the codebase
> currently wires. For a publishable figure the report recommends averaging a
> few runs since DeepSeek generation and the Gemma judge are not perfectly
> deterministic run-to-run.

---

## 10. Validation protocol

Detail in [`validation/VALIDATION_REPORT.md`](../validation/VALIDATION_REPORT.md)
Part II and [`validation/eval/README.md`](../validation/eval/README.md).

### 10.1 The oracle — an executable Reference Query Catalogue

Each use-case intent has one canonical reference query `RQ-*`. The eval runner
([`validation/evaluate.py`](../validation/evaluate.py), package
[`validation/eval/`](../validation/eval/)) **executes each `RQ-*` over the
COMPLETE and MASKED CSVs in pandas**, applying the catalogue's matching rules
(`norm()` folding, toponym Layer-M expansion) and post-processing (sibling
corroboration, soft-gap `w()`, height conversion `pied×32.484 + pouce×2.707 +
ligne×0.2256` cm). **The result *is* the gold.** Critically, the runner is
**decoupled from the generator** — it reads only the two CSVs +
`questions.jsonl` and recomputes gold itself, so it cannot silently inherit a
generator bug. The catalogue lives in
[`validation/corpus/reference_queries/catalogue.json`](../validation/corpus/reference_queries/catalogue.json).

### 10.2 The question set

**55 questions** ([`validation/corpus/questions.jsonl`](../validation/corpus/questions.jsonl)),
each with FR + EN phrasings, applicable `modes`, a `ref_query`, `use_case`,
`stratum` (lookup / multi-hop / aggregation / unanswerable), a `held_out` flag,
and `conditions` (COMPLETE, MASKED). They span lookup (`NAME/COMP/ENR/BPL`),
bounded (`RNK/DTH/DES`), genealogy (`PAR/SIB/VERT`), migration/anthropometric
(`MIG/ANTH`), and mechanics (`DIS/ZERO/UNANS/AGG-COUNT/MULTI`). Gold answers are
keyed by question id in
[`validation/corpus/gold/answers.json`](../validation/corpus/gold/answers.json).

### 10.3 Engines under test

| Engine | What it is | Backend |
|---|---|---|
| **reference** | the oracle — a 100%-correct deterministic baseline | pandas |
| **template** | the app's parameterized Cypher templates | Neo4j |
| **nl2cypher** | DeepSeek NL→Cypher, executed | Neo4j + DeepSeek |
| **RAG** | retrieve top-k → DeepSeek free-text answer | ChromaDB + DeepSeek |

Neo4j Community has one database, so conditions are scored **one at a time**
(wipe → ingest COMPLETE → score → wipe → ingest MASKED → score) on the dedicated
eval instance (port 7690).

### 10.4 Metrics by result kind — `validation/eval/metrics.py`

| Result kind | Metric |
|---|---|
| `rid_set`, `rag_target`, `false_merge`, `trajectory` | precision / recall / **F1** over record ids |
| `count` | exact match |
| `histogram`, `histogram_pair` | **L1** error + normalised similarity |
| `partition` | pairwise P/R/F1 **and B³ F1**; false-merge rate on decoys |
| `aggregate`, `aggregate_pair` | mean within tolerance (0.5 cm) + n exact |
| `linkage` | categorical correctness (TP/TN/FP/FN) over the planted link map |
| `record_fields`, `disambiguation` | exact field match + field-level accuracy |

### 10.5 Scoring the live engines — `validation/eval/shaping.py`

Live engines return arbitrary Neo4j rows; a **shaping layer** reconciles rows to
corpus `rid`s (matricule → name → secondary fields for homonyms) and turns them
into the gold shape so *every* kind is scored. A row set that cannot be shaped is
**`unparseable`**; invalid Cypher is **`query_error`** — both count as **score 0**
(a failed answer is a system failure) and both appear in the coverage table.
**Linkage & partition** are scored **end-to-end**: the generated query supplies
the candidate set, the *same* deterministic post-processing the oracle uses makes
the decision, and the runner also reports **retrieval recall** to separate
NL2Cypher's contribution from the decision step.

### 10.6 Scoring the RAG path — `validation/eval/rag.py`

Per `rag`-mode question, per condition (own Chroma store, `row_<rid>` ⇒ rid):

- **Retrieval (deterministic vs gold):** hit-rate@k, recall@k, **nDCG@10**.
- **Correctness (deterministic vs gold):** coverage of gold soldiers' names in
  the answer.
- **Faithfulness + abstention (Gemma judge, temp 0):** faithfulness = fraction
  of answer claims grounded in retrieved context; abstention is scored
  **CRAG-style** (abstaining beats hallucinating), separating *hallucinated on
  unanswerable* (real failure) from *over-abstained on answerable* (faithful but
  conservative).

### 10.7 Two axes of measurement

1. **Engine accuracy** — prediction vs oracle gold for that condition (reference
   = 1.0 on COMPLETE by construction).
2. **Information degradation** — MASKED gold vs COMPLETE gold,
   *engine-independent*: the intrinsic cost of incomplete annotation per use
   case.

---

## 11. Results

Authored narrative in
[`validation/VALIDATION_REPORT.md`](../validation/VALIDATION_REPORT.md) Part III;
the auto-generated scoreboard is
[`validation/corpus/eval/report.md`](../validation/corpus/eval/report.md) and the
machine-readable results are
[`validation/corpus/eval/{results,rag_results,validation_results}.json`](../validation/corpus/eval/).

### 11.1 Engine accuracy (mean headline score vs oracle gold)

| Engine | COMPLETE | MASKED |
|---|---|---|
| reference (oracle) | **1.000** | **1.000** |
| template | **1.000** | 0.980 |
| nl2cypher | ~0.52–0.64* | ~0.52–0.66* |

\* *NL2Cypher figures vary run-to-run with LLM non-determinism: the formal report
cites 0.516 / 0.523, the latest auto-generated scoreboard 0.637 / 0.662. Average
several runs for a publishable figure.*

Live coverage (COMPLETE): template scored 7/10 applicable (3 have no app
template — company roster, enrol-range, parents — a real coverage gap);
nl2cypher scored 44/49 with 2 `unparseable` and 3 `query_error`.

### 11.2 Information degradation (MASKED recall vs COMPLETE truth)

| Use case | n | Mean recall vs COMPLETE | Reading |
|---|---|---|---|
| lookup | 14 | **0.986** | dense identity/unit/enrolment fields are robust |
| genealogy | 11 | **0.925** | planted probes forced into Tier A stay recoverable |
| mechanics | 5 | 0.800 | zero-result & disambiguation survive; regiment collapses |
| migration | 8 | 0.787 | birthplace dropout → histograms undercount (absence ≠ zero) |
| bounded | 8 | 0.640 | death-year / rank / desertion are sparse under masking |
| anthropometric | 4 | 0.100 | height is ultra-rare → the cohort `n` collapses |

This per-use-case curve is the headline scientific result: it quantifies how much
answer quality the real corpus's sparsity costs, independent of any engine.

### 11.3 What the live engines revealed

- **Template (1.000 / 0.980).** Catalogue-correct templates score perfectly on
  COMPLETE. The `died_in_year` fix (query the `deces_annee` property, not the
  `DIED_IN` relationship) recovers all dated deaths — a fix the validation loop
  surfaced and the app adopted.
- **NL2Cypher.** Perfect on targeted lookups (surname, full name, matricule,
  decoy non-merge, homonym disambiguation, zero-result abstention, 3 of 5
  vertical links). The **linkage decomposition** cleanly attributes the failures
  to *retrieval* (the generated query never surfaced the father, retrieval-recall
  0.0) vs the decision step (where retrieval succeeded, the shared module linked
  correctly). Genuine systematic weaknesses (not harness bugs): company filters
  collapse precision (`CONTAINS 'a'` matches ~every company); two-company
  comparison emits `c.nom IN ['a','d']` against stored `compagnie A` → 0 rows;
  and `AVG(s.taille_metre)` raises a type error because height is stored as a
  string — the model doesn't know height needs post-processing.

### 11.4 RAG path

| Condition | hit@k | recall@k | nDCG@10 | name-coverage | faithfulness | abstention-acc |
|---|---|---|---|---|---|---|
| COMPLETE | 0.706 | 0.452 | 0.434 | 0.462 | **0.958** | 0.706 |
| MASKED | 0.706 | 0.378 | 0.375 | 0.344 | 0.885 | 0.529 |

**Highly faithful** (≈0.96, very low hallucination), with recall **bounded by
retrieval**: single-record questions are answered well (`REC-01`: hit 1.0,
faithful 1.0, coverage 1.0), while roster/aggregate questions exceed the top-k
window so the model **abstains rather than hallucinate**. MASKED faithfulness
dips as thinner context invites more inference.

### 11.5 Cross-cutting findings

- The **fixed-schema graph ingest is validated**: the three DUPONT brothers share
  one father node and sibling traversal returns the siblings — impossible under
  the shipping `CREATE`-based ingest.
- **Two query paths, complementary failure modes** — KG path is exact but
  brittle to NL→Cypher errors; RAG path is faithful but retrieval-bounded.
  Neither dominates, which is the argument for offering both.
- The **degradation curve is the reusable artifact**: it sets realistic
  expectations for the real corpus (don't expect dense death-place trajectories;
  expect histograms to undercount).

---

## 12. The analytic tabs (UI)

The Streamlit app ([`app/main.py`](../app/main.py)) ships **six tabs** plus a
sidebar dataset switch. Three are query tabs (§7), three are analytic.

### 12.1 Sidebar — `app/ui/sidebar.py`

Switches dataset *family* (Real archive vs Synthetic) and, for synthetic,
*annotation* (Complete vs Masked); writes `active_dataset` to session state.
Shows live status badges (Neo4j reachability per the dataset's URI, ChromaDB
persist-dir presence, DeepSeek client availability) and a Docker control
expander.

### 12.2 Showcase — `app/ui/showcase_panel.py` + `showcase_loader.py` + `showcase_render.py`

A guided tour / gallery of curated genealogy / migration / degradation examples.
`load_showcase()` joins [`showcase.yaml`](../showcase.yaml) with the question
corpus and gold answers into `ShowcaseExample` records. Each card shows the
question (EN/FR toggle), optionally runs the example live, lets the user
**"Reveal expected answer"** (the planted gold), and can **compare COMPLETE vs
MASKED** side by side. `showcase_render.py` dispatches by result kind (row_set,
histogram, partition, link_map, scalar). On the real dataset (no gold) it falls
back to a provenance view linking records to source images.

### 12.3 Validation Report — `app/ui/report_panel.py` + `app/report_loader.py`

Renders the **evaluation scorecard from precomputed artifacts** (`results.json`,
`rag_results.json`) — **no live LLM at view time**. Sections: an honesty banner;
the artifact manifest (paths + timestamps); the **headline** (mean score by
engine × condition + the information-degradation metric, with a COMPLETE vs
MASKED bar chart); **breakdowns** by difficulty stratum / mode / use case /
seen-unseen split; the **genealogy decomposition** (linkage F1, partition B³ F1,
false-merge rate); the **RAG** panel (hit-rate, recall@k, nDCG@10, name-coverage,
faithfulness + the abstention breakdown judged by `google/gemma-4-31b-it`); a
per-question drilldown; and a method card. `report_loader.py` is the single
aggregation source of truth (`headline()`, `by_field()`).

### 12.4 Explore / Atlas — `app/ui/explore_panel.py`

Free-browsing aggregate visualisations over the active dataset, organised into
tabs **Demographics / Anthropometric / Migration / Coverage survival**:

- **Demographics:** enrolment-year distribution (optionally split by company),
  company sizes, birthplace breakdown (country / department), age at enrolment,
  age at death (longevity).
- **Anthropometric:** stature distribution from pied/pouce/ligne or
  `taille_metre` (conversion factor `_PIED_M = 0.32484`).
- **Migration:** birthplace → company flows (stacked bars), a **gazetteer-backed
  birthplace scatter map** (`app.geo`), and birth → death-place arcs.
- **Coverage survival:** a table of `n` per plot for COMPLETE vs MASKED with ✓/✗
  against the `N_MIN = 10` threshold — i.e. *which analyses survive real
  sparsity*.

Every plot annotates its sample size `n` and **warns on sub-threshold groups**;
an honesty banner labels synthetic views as capability demonstrations and real
views as illustrative. A compare toggle (synthetic only) renders COMPLETE and
MASKED side by side, making the degradation visible directly in the analytics.

---

## 13. Reproducibility & operations

```bash
# regenerate the corpus (byte-for-byte; seed 20260611)
python validation/generate.py
python validation/verify.py

# score the engines
python validation/evaluate.py                 # reference oracle + degradation (no API)
python validation/evaluate.py --live          # + template + nl2cypher (Neo4j 7690 + DeepSeek)
python validation/evaluate.py --live --rag    # + RAG (ChromaDB + DeepSeek + Gemma judge)

# run the app
make up                                        # Docker: 3 Neo4j instances + Streamlit
streamlit run app/main.py                      # local
```

Required env: `NEO4J_URI/USER/PASSWORD` (graph), `DEEPSEEK_API_KEY` (NL2Cypher +
RAG generation), `OPENROUTER_API_KEY` + `JUDGE_MODEL` (RAG judge). Optional:
`CHROMA_PERSIST_DIR`, `EMBEDDING_MODEL`, `RAG_TOP_K`, the two synth Neo4j URIs,
and `MILITAI_AUTOINGEST ∈ {all, synth, off}`.

**Operational guardrails:** auto-ingestion is idempotent and skips populated
backends; the Report tab reads frozen artifacts (no surprise API spend at view
time); the Atlas map reports any gazetteer-uncovered count honestly; sub-`N_MIN`
groups are flagged rather than silently plotted.

---

## 14. Limitations & future work

- **Gazetteer coordinates.** `Place.coords` (Wikidata P625) is a null scaffold;
  the Atlas currently uses a centroid fallback. Plan: populate from a frozen
  Wikidata / WHG dump.
- **Live structured extraction is partial.** `histogram_pair` / `aggregate_pair`
  and trajectory `record_fields` shaping are best-effort; some live answers
  report `unparseable` (counted as 0). The oracle still scores them.
- **LLM-judge variance.** Single temp-0 call (spec v1); multi-run averaging and
  per-claim citation checking (v1.1) are the rigor upgrades. NL2Cypher / RAG
  headline figures move run-to-run.
- **Scale.** N = 180 is chosen for auditability; marginal rates for the rarest
  fields are coarse at this size.
- **Real-data quality.** Encoding (CP1252), out-of-range numerics, and
  near-absent anthropometry in the real archive constrain what the real-dataset
  analytics can claim — which is precisely why the synthetic harness exists.

---

## 15. Appendix — file map

```text
app/
  main.py            Streamlit entrypoint — 6 tabs, dataset switch, session state
  config.py          DATASETS registry + env config (models, ports, top_k)
  bootstrap.py       idempotent first-run ingestion (MILITAI_AUTOINGEST scope)
  geo.py             gazetteer coord resolution + centroid fallback (Atlas)
  report_loader.py   loads eval artifacts for the Report tab (single source of truth)
  showcase_loader.py joins showcase.yaml + questions + gold
  graph/
    connection.py    cached per-dataset Neo4j drivers + reachability
    schema.py        node/relationship constraints & indexes
    templates.py     12 parameterized Cypher templates
    nl2cypher.py     DeepSeek schema-grounded NL→Cypher + execution
  rag/
    ingestion.py     CSV row → French text → Chroma upsert (all-MiniLM-L6-v2)
    retriever.py     ChromaDB top-k semantic retrieval
    chain.py         RAG prompt + DeepSeek generation + sources
  ui/                sidebar + per-tab panels (template/rag/nl2cypher/explore/report/showcase)
data/                real-archive CSVs (82,821 × 77) + chroma_db/
validation/
  generate.py        deterministic corpus generator (seed 20260611) [user-owned]
  pools.py           value pools (reserved vs background names, companies, depts)
  verify.py / verify_graph.py   acceptance-criteria checks
  evaluate.py        decoupled eval runner entrypoint
  eval/              engines, metrics, rag (judge), reference oracle, shaping, toponym, ingest
  corpus/
    complete.csv / masked.csv     the two synthetic conditions (180 each)
    questions.jsonl               55 FR/EN questions
    gazetteer.json                frozen place → region/country gazetteer
    reference_queries/catalogue.json   the executable RQ catalogue
    gold/ …                       authored gold artifacts
    eval/ …                       results.json, rag_results.json, report.md
  VALIDATION_REPORT.md            formal synthetic-dataset + validation report
scripts/
  ingest_neo4j.py    CSV → Neo4j (per dataset/sample/csv)
  ingest_rag.py      CSV → ChromaDB collection
showcase.yaml        guided-tour example registry
Dockerfile / docker-compose.yml / Makefile / pyproject.toml / uv.lock
```

> *Synthetic-corpus disclaimer: the validation corpus is authored data for system
> testing and carries no historical meaning. Source records originate from the
> French military archives ecosystem (Mémoire des Hommes / SHDGR); historical
> interpretation remains the responsibility of the researcher.*
