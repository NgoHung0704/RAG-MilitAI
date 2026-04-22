# MilitAI — French Military Records Explorer

A hybrid query system over digitized Ancien Régime French military records from the
[Mémoire des Hommes](https://www.memoiredeshommes.defense.gouv.fr/) archive (SHDGR).
The system exposes three query regimes over the same dataset through a single Streamlit UI.

---

## Table of Contents

1. [What it does](#what-it-does)
2. [Architecture overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Data ingestion](#data-ingestion)
7. [Running the app](#running-the-app)
8. [Query modes](#query-modes)
9. [Project structure](#project-structure)
10. [Troubleshooting](#troubleshooting)

---

## What it does

The dataset contains ~75 columns per soldier record: identity, birth, domicile, marriage,
death, military service, ranks, enlistment, discharge, desertion, and parents.
MilitAI lets you query this corpus in three ways:

| Mode | Description |
|------|-------------|
| **RAG** | Semantic similarity search — each soldier row is embedded as text in ChromaDB. Ask free-form questions; an LLM answers using retrieved records as grounding context. |
| **Template** | 12 pre-built parameterized Cypher queries against a Neo4j graph. Fill in the form fields and run. Guaranteed-correct queries, fast. |
| **NL2Cypher** | Type a natural-language question; an LLM generates Cypher on the fly and executes it against Neo4j. More flexible than templates, less predictable. |

---

## Architecture overview

- **Streamlit UI** — single-page app with a sidebar toggle between three query modes.
  - **RAG pipeline**
    1. CSV rows are serialized to human-readable text blocks and embedded with `sentence-transformers`.
    2. Vectors are stored persistently in ChromaDB on disk.
    3. At query time the top-k most similar records are retrieved.
    4. Retrieved records are passed as grounding context to DeepSeek, which generates a natural-language answer.
  - **Graph pipeline** (shared by Template and NL2Cypher modes)
    1. CSV rows are ingested into Neo4j as a labeled property graph (soldiers, places, regiments, ranks, parents, archive records).
    2. **Template mode** — user picks a pre-written parameterized Cypher query, fills in the form, and the query runs directly against Neo4j.
    3. **NL2Cypher mode** — user types a free-form question; DeepSeek generates Cypher using the graph schema and few-shot examples as context; the generated query is executed against Neo4j.

**Tech stack**

| Component | Technology |
|-----------|-----------|
| Graph database | Neo4j |
| Vector store | ChromaDB (local, persistent) |
| Embeddings | `sentence-transformers` — `all-MiniLM-L6-v2` |
| LLM | DeepSeek API (`deepseek-chat`) via `openai` SDK |
| UI | Streamlit |
| Data | pandas |

---

## Prerequisites

### 1. Python

Python **3.11 or newer** is required.

```bash
python --version   # must be 3.11+
```

### 2. Neo4j

You need a running Neo4j instance. The easiest options:

**Option A — Neo4j Desktop (recommended for local dev)**

1. Download from [neo4j.com/download](https://neo4j.com/download/).
2. Create a new project and start a local DBMS.
3. Note the bolt URI (`bolt://localhost:7687` by default), username (`neo4j`), and password
   you set during setup.

**Option B — Docker**

```bash
docker run \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest
```

Neo4j Browser will be available at `http://localhost:7474`.

**Required Neo4j version**: 5.x (uses `IF NOT EXISTS` constraint syntax).

### 3. DeepSeek API key

Create an account at [platform.deepseek.com](https://platform.deepseek.com/) and generate
an API key. You will need it for both the NL2Cypher and RAG modes.

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd RAG-MilitAI

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

> **Note on `sentence-transformers`**: the first time the embedding model runs it downloads
> ~90 MB from Hugging Face. This happens automatically during ingestion.

---

## Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Then edit `.env`:

```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password

# DeepSeek (required for RAG and NL2Cypher modes)
DEEPSEEK_API_KEY=sk-...

# ChromaDB — where the vector store is persisted on disk
CHROMA_PERSIST_DIR=data/chroma_db

# Sentence-transformers model for embeddings
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Number of records to retrieve per RAG query
RAG_TOP_K=5

# CSV data paths (defaults work if you haven't moved the files)
DATA_PATH=data/full_unified_annotations_patch.csv
SAMPLE_DATA_PATH=data/sample_of_data.csv
```

> `.env` is listed in `.gitignore` — it will never be committed.

---

## Data ingestion

The dataset must be ingested into Neo4j (for Template and NL2Cypher modes) and into
ChromaDB (for RAG mode) before the app can query anything. These are one-time operations;
re-run them only if the data changes.

### Quick test with the 4-row sample

Use the `--sample` flag to ingest just the four records in `data/sample_of_data.csv`.
This is instant and useful for verifying that everything is wired up correctly before
processing the full dataset.

```bash
# Step 1 — ingest into Neo4j
python scripts/ingest_neo4j.py --sample

# Step 2 — ingest into ChromaDB
python scripts/ingest_rag.py --sample
```

### Full dataset ingestion

```bash
# Step 1 — ingest into Neo4j (full CSV, ~37 MB)
python scripts/ingest_neo4j.py

# Step 2 — ingest into ChromaDB (full CSV, embedding every row)
python scripts/ingest_rag.py
```

The Neo4j ingestion processes rows in batches of 5 000 and shows a progress bar.
The ChromaDB ingestion batches embeddings in groups of 500; expect it to take several
minutes on the full dataset, longer on first run when the model is downloaded.

### Custom CSV path

```bash
python scripts/ingest_neo4j.py --csv path/to/your_file.csv
python scripts/ingest_rag.py   --csv path/to/your_file.csv
```

### What gets created in Neo4j

The ingestion script creates the following schema:

**Nodes**: `Soldier`, `Place`, `Regiment`, `Company`, `Rank`, `Person`, `ArchiveRecord`

**Relationships**:
```
(Soldier)-[:BORN_IN     {jour, mois, annee}]->(Place)
(Soldier)-[:DIED_IN     {jour, mois, annee}]->(Place)
(Soldier)-[:DOMICILED_IN               ]->(Place)
(Soldier)-[:MARRIED_IN  {jour, mois, annee}]->(Place)
(Soldier)-[:SERVED_IN   {matricule, enrolement_annee}]->(Regiment)
(Soldier)-[:BELONGS_TO                 ]->(Company)
(Soldier)-[:HELD_RANK   {order}        ]->(Rank)
(Soldier)-[:DESERTED_FROM {jour, mois, annee}]->(Regiment)
(Soldier)-[:DISCHARGED_FROM {jour, mois, annee}]->(Regiment)
(Soldier)-[:CHILD_OF    {role}         ]->(Person)
(Soldier)-[:SOURCED_FROM               ]->(ArchiveRecord)
```

Place nodes are deduplicated on `(lieu, departement, pays)` using `MERGE`.

---

## Running the app

```bash
streamlit run app/main.py
```

The app opens at `http://localhost:8501`.

The **sidebar** shows live connection status badges for Neo4j, ChromaDB, and the DeepSeek
API key. If any service is unavailable, the corresponding mode will display an error message
with setup instructions instead of crashing the whole app.

---

## Query modes

### RAG

1. Select **RAG** in the sidebar.
2. Type any question in the text box — French or English.
3. Click **Search**.

The system retrieves the `RAG_TOP_K` most similar soldier records from ChromaDB and passes
them as context to DeepSeek. The answer is grounded only in those records; the LLM will
say so if the answer is not in the data.

The **Source records used** expander shows which archive records were retrieved, including
a direct link to the source scan on the Mémoire des Hommes website.

> Requires: ChromaDB ingested, `DEEPSEEK_API_KEY` set.

### Template

1. Select **Template** in the sidebar.
2. Pick a query from the dropdown. The description explains what it returns.
3. Fill in the parameter fields (text or number inputs are generated automatically).
4. Click **Run Query**.

Results appear as a sortable, filterable dataframe. The Cypher query is shown in an
expander for transparency.

Available templates:

| # | Name | Parameters |
|---|------|-----------|
| 1 | Find by surname | `nom` |
| 2 | Find by first name + surname | `prenom`, `nom` |
| 3 | Died in year | `annee` |
| 4 | Born in place | `lieu` |
| 5 | All soldiers in regiment | `regiment` |
| 6 | Soldiers who deserted | *(none)* |
| 7 | Died in year with surname | `annee`, `nom` |
| 8 | Born in year range | `annee_min`, `annee_max` |
| 9 | By final rank | `grade` |
| 10 | Soldier with parents | `nom` |
| 11 | Enlisted in year | `annee` |
| 12 | From department | `departement` |

> Requires: Neo4j running with data ingested.

### NL2Cypher

1. Select **NL2Cypher** in the sidebar.
2. Describe what you want in plain language (French or English), e.g.:
   > *"Find soldiers born in Normandie who served in the grenadiers and deserted before 1730"*
3. Click **Generate & Run**.

DeepSeek generates a Cypher query using the graph schema and few-shot examples as context.
The generated query is always shown in an expander so you can inspect (and copy) it.
If execution fails, the error and the failing Cypher are both displayed.

> Requires: Neo4j running with data ingested, `DEEPSEEK_API_KEY` set.

---

## Project structure

```
RAG-MilitAI/
├── AGENTS.md                        # Full architecture reference for agents/devs
├── README.md                        # This file
├── requirements.txt
├── .env.example                     # Template — copy to .env and fill in
├── .gitignore
│
├── data/
│   ├── sample_of_data.csv           # 4-row sample for testing
│   ├── full_unified_annotations.csv
│   ├── full_unified_annotations_patch.csv   # ← used by default
│   └── chroma_db/                   # Created on first RAG ingestion (gitignored)
│
├── app/
│   ├── main.py                      # Streamlit entrypoint
│   ├── config.py                    # Env-var loading
│   │
│   ├── graph/
│   │   ├── connection.py            # Neo4j driver singleton
│   │   ├── schema.py                # Constraints + indexes setup
│   │   ├── templates.py             # 12 Cypher templates + run_template()
│   │   └── nl2cypher.py             # NL → Cypher via DeepSeek
│   │
│   ├── rag/
│   │   ├── ingestion.py             # CSV row → text → ChromaDB upsert
│   │   ├── retriever.py             # ChromaDB similarity query
│   │   └── chain.py                 # RAG chain (retrieve + LLM answer)
│   │
│   └── ui/
│       ├── rag_panel.py             # RAG mode Streamlit panel
│       ├── template_panel.py        # Template mode Streamlit panel
│       └── nl2cypher_panel.py       # NL2Cypher mode Streamlit panel
│
└── scripts/
    ├── ingest_neo4j.py              # CLI: CSV → Neo4j
    └── ingest_rag.py                # CLI: CSV → ChromaDB
```

---

## Troubleshooting

### "Neo4j  error: …" in the sidebar

- Confirm Neo4j is running: open `http://localhost:7474` in a browser.
- Check `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` in `.env`.
- If you changed the password in Neo4j Desktop after first launch, update `.env` to match.

### "ChromaDB  not ingested" in the sidebar

Run the RAG ingestion script:

```bash
python scripts/ingest_rag.py --sample   # quick test
python scripts/ingest_rag.py            # full dataset
```

### "DeepSeek  key missing" in the sidebar

Set `DEEPSEEK_API_KEY` in your `.env` file and restart the Streamlit server
(`Ctrl+C` then `streamlit run app/main.py`).

### Template query returns no results

- Confirm Neo4j ingestion ran: open Neo4j Browser and run `MATCH (s:Soldier) RETURN count(s)`.
  A zero means ingestion did not complete successfully.
- String parameters are matched with case-insensitive `CONTAINS`, so partial names work
  (e.g. `CHALE` will match `CHALET`).

### NL2Cypher returns a Cypher error

The generated query is shown in the "Generated Cypher (failed)" expander. Common causes:
- The LLM hallucinated a property name — the actual schema is documented in `AGENTS.md`.
- The question involves a concept not in the graph (e.g. physical description properties
  are on the `Soldier` node directly, not as a separate node).

Rephrasing the question more precisely usually resolves it.

### RAG answers seem unrelated

- Check that the ChromaDB store was built from the correct CSV (`DATA_PATH` in `.env`).
- Try increasing `RAG_TOP_K` (e.g. `10`) to give the LLM more context.
- The embedding model (`all-MiniLM-L6-v2`) works in both French and English but may be
  less precise for highly specific proper nouns. Try querying in the same language as the
  stored text (French).

### Slow first run

`sentence-transformers` downloads the `all-MiniLM-L6-v2` model (~90 MB) from Hugging Face
on the very first call. Subsequent runs use the local cache.

---

## Data source

Records come from the **Service Historique de la Défense** (SHDGR), digitized and published
via the [Mémoire des Hommes](https://www.memoiredeshommes.defense.gouv.fr/) portal by the
French Ministry of Armed Forces. Each record links back to the original scanned archive page
via an ARK persistent identifier.
