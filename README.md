# MilitAI

MilitAI is a hybrid query platform for French military records from the Ancien Régime.
It combines three query modes over a knowledge graph + vector store, and ships with
a **synthetic validation corpus** and a **decoupled evaluation harness** so every
query mode can be scored against controlled ground truth.

The three query modes, in one Streamlit interface:

- **RAG** over CSV records with ChromaDB + sentence-transformers.
- **Template** — parameterized Cypher templates executed on Neo4j.
- **NL2Cypher** — natural-language-to-Cypher generation using DeepSeek.

The project targets history and social-science workflows by making archive-backed
data exploration faster, reproducible, and — critically — *measurable*.

## Core Features

- **Single UI, six tabs:** Template, RAG, NL2Cypher, Showcase, Explore / Atlas, Validation Report.
- **Three datasets, one switch:** the real archive plus two synthetic datasets
  (complete annotation and masked-to-real-sparsity), selected from the sidebar.
- **Graph ingestion** from CSV into Neo4j with a relationship-rich schema.
- **Local vector store** ingestion and semantic retrieval with source metadata.
- **First-run auto-ingestion:** on startup the app populates each dataset's Neo4j
  instance and Chroma collection if empty (idempotent; scoped via `MILITAI_AUTOINGEST`).
- **Query transparency:**
  - Template mode always shows the exact Cypher.
  - NL2Cypher mode exposes the generated Cypher.
  - RAG mode shows the source records used for the answer.
- **Explore / Atlas:** free-browsing aggregate visualisations (demographics,
  anthropometrics, recruitment geography) over the active dataset, with a
  gazetteer-backed birthplace map. Every plot shows its sample size `n` and warns
  on sub-threshold groups — it demonstrates *which analyses survive real sparsity*.
- **Showcase:** a guided tour of curated genealogy / migration / degradation
  examples that compare COMPLETE vs MASKED and reveal the planted ground truth.
- **Validation Report:** an aggregate evaluation scorecard rendered from the
  precomputed eval artifacts (no live LLM at view time).
- **Synthetic validation corpus + eval harness** (`validation/`): a deterministic
  180-record corpus with authored ground truth and an evaluation runner that scores
  each query mode and quantifies COMPLETE→MASKED degradation.

## Datasets

The three logical datasets are isolated by **separate Neo4j instances** (Neo4j
Community allows only one database per instance), each on its own bolt port. Chroma
holds all three as distinct collections in one persist directory.

| Dataset | Label | Neo4j (host) | Records | Ground truth |
|---|---|---|---|---|
| `real` | Real archive (Mémoire des Hommes) | `localhost:7687` | ~82k | none |
| `synth_complete` | Synthetic — complete annotation | `localhost:7688` | 180 | yes |
| `synth_masked` | Synthetic — masked to real sparsity | `localhost:7689` | 180 | yes |

A fourth, profile-gated instance (`neo4j-eval`, `localhost:7690`) is a dedicated
scratch database used only by the offline eval runner (`make eval-live`).

## Architecture

```text
                          +-------------------------+
                          |       Streamlit UI      |
                          |        app/main.py      |
                          |  6 tabs · dataset switch |
                          +------------+------------+
                                       |
          +-------------------+--------+--------+-------------------+
          |                   |                 |                   |
   +------v------+     +------v------+   +------v------+     +------v------+
   | Graph (Neo4j)|     |  RAG (Chroma)|   | Explore/Atlas|     |   Showcase  |
   | templates +  |     | retriever +  |   |  geo + agg   |     |  + Report   |
   | nl2cypher    |     | chain        |   |  (pandas)    |     | (artifacts) |
   +------+------+     +------+------+   +-------------+     +-------------+
          |                   |
   +------v------+     +------v------+
   | Neo4j ×3     |     |  ChromaDB    |
   | (per dataset)|     | (3 collections)
   +-------------+     +-------------+

Data sources: data/*.csv (real) · validation/corpus/*.csv (synthetic)
```

## Repository Layout

```text
RAG-MilitAI/
├── app/
│   ├── main.py              # Streamlit entrypoint (6 tabs, dataset switch)
│   ├── config.py            # dataset registry + env config
│   ├── bootstrap.py         # idempotent first-run ingestion
│   ├── geo.py               # gazetteer-backed coordinate resolution (Atlas map)
│   ├── report_loader.py     # loads eval artifacts for the Report tab
│   ├── showcase_loader.py   # joins showcase.yaml with questions + gold
│   ├── graph/               # connection, schema, templates, nl2cypher
│   ├── rag/                 # ingestion, retriever, chain
│   └── ui/                  # sidebar + per-tab panels
├── data/                    # real-archive CSVs
├── validation/              # synthetic corpus generator + eval harness
│   ├── generate.py          # deterministic corpus generator (user-owned)
│   ├── verify.py            # acceptance-criteria checks
│   ├── evaluate.py          # decoupled eval runner entrypoint
│   ├── eval/                # eval modules (oracle, metrics, engines, rag, ...)
│   └── corpus/              # generated corpus + gold + eval artifacts
├── scripts/                 # ingest_neo4j.py, ingest_rag.py
├── showcase.yaml            # guided-tour example registry
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml           # dependencies (managed with uv)
├── uv.lock
└── .env.example
```

## Prerequisites

Choose one workflow:

- **Docker workflow (recommended):**
  - Docker Desktop 4.0+
  - GNU Make (or a compatible `make`)
- **Local Python workflow:**
  - Python 3.11+
  - [uv](https://docs.astral.sh/uv/) (recommended) or pip
  - Neo4j running locally or remotely

## Environment Configuration

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Update values in `.env`:

- Required for graph mode: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- Required for NL2Cypher and RAG generation: `DEEPSEEK_API_KEY`
- Optional (RAG): `CHROMA_PERSIST_DIR`, `EMBEDDING_MODEL`, `RAG_TOP_K`
- Optional (synthetic datasets, override host ports): `NEO4J_URI_SYNTH_COMPLETE`,
  `NEO4J_URI_SYNTH_MASKED`
- Optional (RAG eval judge): `OPENROUTER_API_KEY`, `JUDGE_MODEL`
- Optional (first-run ingestion scope): `MILITAI_AUTOINGEST` =
  `all` (default) | `synth` (skip the 82k real archive) | `off`

## Quick Start (Docker + Make)

1. Build and start all services (app + the three Neo4j instances):

```bash
make up
```

   On first launch the app auto-ingests any empty dataset. To skip the slow ~82k
   real-archive ingestion and demo only the synthetic data, set
   `MILITAI_AUTOINGEST=synth` in `.env` before `make up`.

2. (Optional) Ingest the synthetic datasets explicitly:

```bash
make ingest-synth          # both synth datasets, Neo4j + RAG
```

3. Open the applications:

- Streamlit: http://localhost:8501
- Neo4j Browser (real): http://localhost:7474
- Neo4j Browser (synth complete / masked): http://localhost:7475 / :7476

4. Stop services:

```bash
make down
```

## Local Python Workflow (without Docker)

1. Install dependencies. Dependencies are declared in `pyproject.toml` (there is
   no `requirements.txt`).

   With uv (recommended):

```bash
uv sync
```

   Or with pip in a virtual environment:

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1   # Windows PowerShell  (use source .venv/bin/activate on macOS/Linux)
pip install -e .
```

2. Run ingestion scripts (point Neo4j at a running instance via `.env`):

```bash
python scripts/ingest_neo4j.py --sample
python scripts/ingest_rag.py --sample
```

3. Start the UI:

```bash
streamlit run app/main.py
```

## Make Targets

```bash
make help
```

**Infrastructure**

- `make build` — build the app Docker image.
- `make up` — start the three Neo4j instances + Streamlit.
- `make down` — stop services.
- `make restart` — restart services.
- `make logs` — follow container logs.
- `make ps` — show service status.

**Ingestion**

- `make ingest-neo4j-sample` / `make ingest-neo4j-full` — load sample/full CSV into the real Neo4j.
- `make ingest-rag-sample` / `make ingest-rag-full` — build the real Chroma collection.
- `make ingest-synth-neo4j` — ingest `synth_complete` + `synth_masked` into Neo4j (7688/7689).
- `make ingest-synth-rag` — build the synthetic Chroma collections.
- `make ingest-synth` — both of the above.

**Validation eval** (isolated on the dedicated eval Neo4j at 7690)

- `make up-eval` — start the dedicated eval Neo4j instance (port 7690).
- `make eval` — reference-oracle eval (no Neo4j needed); writes `validation/corpus/eval/`.
- `make eval-live` — start 7690 + score `template`/`nl2cypher` against it.

**Utilities**

- `make app-shell` — open a shell in the app container.
- `make neo4j-shell` — open cypher-shell in the real Neo4j container.
- `make clean` — stop and remove containers, networks, and volumes.

## Validation Corpus & Evaluation

The `validation/` directory contains a deterministic synthetic corpus and an
evaluation harness used to score the query modes against controlled ground truth.

- **Generator** (`generate.py`, `verify.py`) — produces a 180-record corpus with
  authored ground truth, a **complete** view and a **masked** view calibrated to the
  real corpus's fill rates, gold artifacts, and an FR/EN question set. See
  [validation/README.md](validation/README.md).
- **Eval runner** (`evaluate.py`, `eval/`) — decoupled from the generator: it
  computes its own gold by executing the Reference Query Catalogue over the two
  CSVs, then scores each engine and reports COMPLETE→MASKED degradation. See
  [validation/eval/README.md](validation/eval/README.md).

```bash
# generate / re-verify the corpus
python validation/generate.py
python validation/verify.py

# score the engines (writes validation/corpus/eval/{results.json,report.md,...})
make eval            # reference oracle only — no Neo4j required
make eval-live       # + live template / nl2cypher against Neo4j on 7690
```

The two synthetic conditions are the heart of the method: **COMPLETE** validates
query logic and use-case capability; **MASKED** validates graceful degradation and
the real recall ceiling. The delta between them quantifies the cost of incomplete
annotation. The Showcase and Validation Report tabs surface these results in the UI.

## Data and Ingestion Notes

- Use `sample_of_data.csv` for fast iteration; `full_unified_annotations_patch.csv`
  for full real-archive ingestion runs.
- CSV values are sparse; ingestion scripts skip null/empty relationships.
- Place deduplication in graph ingestion relies on `MERGE` with place identity fields.
- Synthetic corpus CSVs live under `validation/corpus/` and ingest by `--dataset`
  (e.g. `python scripts/ingest_neo4j.py --dataset synth_complete`) or `--csv`.

## Operational Notes

- If NL2Cypher or RAG generation is unavailable, verify `DEEPSEEK_API_KEY`.
- If the RAG eval judge fails, verify `OPENROUTER_API_KEY` / `JUDGE_MODEL`.
- If graph queries fail, verify the relevant Neo4j credentials and that the
  dataset's instance (7687 / 7688 / 7689) is healthy.
- If RAG returns no useful sources, re-run ingestion and verify the Chroma persist directory.
- The Atlas map plots birthplaces from the gazetteer; until real coordinates are
  populated it uses a built-in centroid fallback and reports any uncovered count honestly.

## Troubleshooting

- Neo4j not ready:

```bash
make logs
```

- Recreate the stack from scratch:

```bash
make clean
make up
```

- Rebuild the app image after dependency changes:

```bash
make build
make up
```

## License and Data Attribution

Source records originate from the French military archives ecosystem
(Mémoire des Hommes / SHDGR). This repository provides processing, query, and
evaluation tooling; historical interpretation remains the responsibility of the
researcher. The synthetic validation corpus is authored data for system testing
and carries no historical meaning.
