# AGENTS.md — MilitAI Project Guide

> **Purpose**: This document is the single source of truth for any agent or developer working on this project. Read it fully before touching any code.

---

## Project Overview

**MilitAI** is a hybrid historical-data query system built on top of digitized records of French soldiers from the Ancien Régime (17th–18th century). The raw data comes from the *Mémoire des Hommes* archive (SHDGR — Service Historique de la Défense) and has been parsed into structured CSV files.

The system exposes three query regimes over this data, switchable from a single UI:

| Regime | Description |
|--------|-------------|
| **RAG** | Retrieval-Augmented Generation over the CSV as a vector store |
| **Template** | Parameterized Cypher query templates against a Neo4j graph database |
| **NL2Cypher** | Natural-language → Cypher translation via LLM, executed against Neo4j |

---

## Data Model

### Source Files

```
data/
├── sample_of_data.csv               # 4 rows — use for fast iteration and tests
├── full_unified_annotations.csv     # Full dataset
└── full_unified_annotations_patch.csv  # Patched/corrected version of the full set
```

**Always develop and test against `sample_of_data.csv` first. Use the full dataset only for ingestion scripts.**

### CSV Column Reference

The CSV has ~75 columns. They fall into these semantic groups:

#### Archive / Source
| Column | Description |
|--------|-------------|
| `source_image` | Filename of the scanned archive image |
| `double_page` | Double-page scan identifier |
| `section` | Section code (e.g. `1_YC`) |
| `registre` | Register number |
| `numero_page` | Page number within register |
| `side` | Side of the page |
| `line` | Line number on the page |
| `double_page_url` | Direct URL to the scanned page image |
| `ark_url` | Persistent ARK identifier URL |

#### Identity
| Column | Description |
|--------|-------------|
| `nom` | Surname (family name) |
| `nom_autre` | Alternative surname |
| `prenom` | First name |
| `surnom` | Nickname / dit name |
| `age` | Age at time of record |
| `profession` | Civilian profession before enlistment |

#### Physical Description
| Column | Description |
|--------|-------------|
| `pied` | Height in feet (Ancien Régime) |
| `pouce` | Height inches |
| `ligne` | Height in lignes |
| `taille_metre` | Height converted to metres |

#### Domicile
| Column | Description |
|--------|-------------|
| `domicile_departement` | Department of domicile |
| `domicile_lieu` | Place of domicile |
| `domicile_pays` | Country of domicile |

#### Birth (`naissance`)
| Column | Description |
|--------|-------------|
| `naissance_jour` | Day of birth |
| `naissance_mois` | Month of birth |
| `naissance_annee` | Year of birth |
| `naissance_departement` | Department of birth |
| `naissance_lieu` | Place of birth |
| `naissance_juridiction` | Parish/jurisdiction of birth |
| `naissance_region` | Region of birth |
| `naissance_pays` | Country of birth |
| `naissance_pieve` | Pieve (Corsican administrative unit) of birth |

#### Marriage (`mariage`)
| Column | Description |
|--------|-------------|
| `mariage_jour/mois/annee` | Date of marriage |
| `mariage_lieu` | Place of marriage |
| `mariage_departement` | Department of marriage |
| `mariage_pays` | Country of marriage |

#### Death (`deces`)
| Column | Description |
|--------|-------------|
| `deces_jour/mois/annee` | Date of death |
| `deces_lieu` | Place of death |
| `deces_commune` | Commune of death |
| `deces_departement` | Department of death |
| `deces_pays` | Country of death |

#### Father (`pere`)
| Column | Description |
|--------|-------------|
| `pere_decede` | Whether father was deceased at record time |
| `pere_prenom` | Father's first name |
| `pere_autre_prenom` | Father's alternative first name |
| `pere_profession` | Father's profession |

#### Mother (`mere`)
| Column | Description |
|--------|-------------|
| `mere_decedee` | Whether mother was deceased at record time |
| `mere_nom` | Mother's surname |
| `mere_autre_nom` | Mother's alternative surname |
| `mere_prenom` | Mother's first name |
| `mere_autre_prenom` | Mother's alternative first name |

#### Military Service
| Column | Description |
|--------|-------------|
| `regiment` | Regiment name |
| `compagnie` | Company name |
| `bataillon` | Battalion |
| `matricule` | Service number |
| `grade_final` | Final rank |
| `grade_1/2/3` | Successive ranks held |
| `page_bms` | Reference to BMS record |

#### Service Events
| Column | Description |
|--------|-------------|
| `enrolement_jour/mois/annee` | Date of enlistment |
| `renvoi_jour/mois/annee` | Date of discharge |
| `desertion` | Desertion flag |
| `desertion_jour/mois/annee` | Date of desertion |

#### Status / Misc
| Column | Description |
|--------|-------------|
| `sort` | Fate/outcome of the soldier |
| `passe` | Transfer information |
| `invalide` | Invalidity flag |
| `ne_au_regiment` | Born in the regiment flag |
| `commentaires` | Free-text comments |

---

## Task 1 — Neo4j Graph Database

### Goal
Ingest the CSV data into a Neo4j graph database with a normalized, relationship-rich schema.

### Graph Schema

#### Nodes

| Label | Key Properties | Description |
|-------|---------------|-------------|
| `Soldier` | `nom`, `prenom`, `surnom`, `age`, `profession`, `taille_metre`, `matricule` | Core soldier record |
| `Place` | `lieu`, `departement`, `pays`, `region` | A geographical place (birth, death, domicile, marriage) |
| `Regiment` | `nom` | A military regiment |
| `Company` | `nom` | A company within a regiment |
| `Rank` | `nom` | A military rank/grade |
| `Person` | `prenom`, `nom`, `role` | A parent (father or mother) |
| `ArchiveRecord` | `source_image`, `section`, `registre`, `numero_page`, `ark_url`, `double_page_url` | The source archival document |

#### Relationships

| Relationship | From → To | Properties |
|-------------|-----------|------------|
| `BORN_IN` | Soldier → Place | `jour`, `mois`, `annee` |
| `DIED_IN` | Soldier → Place | `jour`, `mois`, `annee` |
| `DOMICILED_IN` | Soldier → Place | — |
| `MARRIED_IN` | Soldier → Place | `jour`, `mois`, `annee` |
| `SERVED_IN` | Soldier → Regiment | `matricule`, `enrolement_annee` |
| `BELONGS_TO` | Soldier → Company | — |
| `HELD_RANK` | Soldier → Rank | `order` (1, 2, 3, or "final") |
| `DESERTED_FROM` | Soldier → Regiment | `jour`, `mois`, `annee` |
| `DISCHARGED_FROM` | Soldier → Regiment | `jour`, `mois`, `annee` |
| `CHILD_OF` | Soldier → Person | `role` ("father" or "mother") |
| `SOURCED_FROM` | Soldier → ArchiveRecord | — |

#### Place Deduplication Strategy
Places must be deduplicated using a composite key: `(lieu, departement, pays)`. Use `MERGE` in Cypher during ingestion to avoid duplicates.

#### Ingestion Script
- File: `scripts/ingest_neo4j.py`
- Uses `neo4j` Python driver
- Reads `data/full_unified_annotations_patch.csv` with `pandas`
- Batch ingestion using `UNWIND` for performance
- Must handle empty/NaN cells gracefully (skip null relationships)
- Connection config via environment variables: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

---

## Task 2 — Cypher Query Templates + NL2Cypher

### 2a. Cypher Query Templates

File: `app/graph/templates.py`

Templates are parameterized Cypher strings. Each template has:
- A human-readable **name**
- A **description** of what it returns
- A **parameter schema** (name → type + description)
- The **Cypher string** with `$param` placeholders

#### Required Templates (minimum set)

```
1.  Find soldiers by surname
    Params: nom (str)

2.  Find soldiers by first name + surname
    Params: prenom (str), nom (str)

3.  Find soldiers who died in a given year
    Params: annee (int)

4.  Find soldiers born in a given place
    Params: lieu (str)

5.  Find all soldiers in a given regiment
    Params: regiment (str)

6.  Find soldiers who deserted
    (no params — returns all)

7.  Find soldiers who died in a given year with a given surname
    Params: annee (int), nom (str)

8.  Find soldiers born in a given year range
    Params: annee_min (int), annee_max (int)

9.  Find soldiers with a given final rank
    Params: grade (str)

10. Find soldiers and their parents
    Params: nom (str)

11. Find soldiers enlisted in a given year
    Params: annee (int)

12. Find soldiers from a given department (birth or domicile)
    Params: departement (str)
```

Each template must be usable from both the UI (template regime) and by the NL2Cypher fallback.

### 2b. NL2Cypher Tool

File: `app/graph/nl2cypher.py`

The NL2Cypher tool takes a natural-language question and returns executable Cypher.

**Approach:**
1. Build a system prompt containing:
   - The full Neo4j schema (nodes, relationships, properties)
   - Several few-shot examples (NL → Cypher pairs, drawn from the templates above)
   - Instruction to return only raw Cypher, no explanation
2. Send user question + system prompt to the LLM API (Claude by default)
3. Parse the response to extract the Cypher query
4. Execute against Neo4j and return results

**LLM**: Use the Anthropic API (`anthropic` Python SDK). Model: `claude-sonnet-4-6`. API key via `ANTHROPIC_API_KEY` env var.

**Fallback**: If Cypher execution fails (syntax error, empty result), catch the exception and return a user-readable error. Do not retry silently.

---

## Task 3 — RAG Pipeline

### Goal
Build a retrieval-augmented generation pipeline over the CSV data so users can ask free-form questions answered by the LLM, grounded in the actual records.

### Approach

#### Chunking Strategy
Each CSV row = one document chunk. Represent each soldier as a human-readable text block, e.g.:

```
Soldier: Jean CHALET (dit SAINT JEAN)
Born: year 71 in Marcigny (Marsigny), France
Died: 3 March 1721
Regiment: compagnie de grenadiers, matricule 6
Source: archives_SHDGR__GR_1_YC_1__0002.jpg
```

The text serialization function lives in `app/rag/ingestion.py` as `soldier_to_text(row: dict) -> str`.

#### Embeddings & Vector Store
- Embeddings: Use `sentence-transformers` locally (model: `all-MiniLM-L6-v2`) or OpenAI embeddings — make it configurable
- Vector store: **ChromaDB** (local, persistent, no server needed)
- Collection name: `soldiers`
- Persist directory: `data/chroma_db/`

#### Retrieval
- Top-k: 5 documents (configurable)
- Return retrieved chunks + their metadata (source image, ark_url)

#### Generation
- Retrieved chunks are injected into a prompt as context
- LLM (Claude via Anthropic API) answers the question
- The answer must cite which soldier records were used

#### Files
```
app/rag/
├── __init__.py
├── ingestion.py    # CSV row → text, embed, store in Chroma
├── retriever.py    # Query Chroma, return top-k chunks
└── chain.py        # Retriever + LLM prompt + answer
scripts/
└── ingest_rag.py   # One-shot script: run ingestion pipeline
```

---

## Task 4 — Streamlit UI

### Goal
A single Streamlit app (`app/main.py`) with a sidebar regime switcher.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  MilitAI — French Military Records Explorer             │
├──────────────┬──────────────────────────────────────────┤
│  SIDEBAR     │  MAIN PANEL                              │
│              │                                          │
│  Query Mode  │  [Mode-specific query form]              │
│  ○ RAG       │                                          │
│  ○ Template  │  [Results table / text]                  │
│  ○ NL2Cypher │                                          │
│              │  [Source links / metadata]               │
└──────────────┴──────────────────────────────────────────┘
```

### RAG Mode
- Single text input: "Ask a question about the soldiers"
- Button: "Search"
- Output: LLM answer + expandable section showing retrieved source chunks with archive links

### Template Mode
- Dropdown to select a template by name
- Dynamically rendered parameter fields (text inputs or number inputs based on schema)
- Button: "Run Query"
- Output: results as a `st.dataframe`

### NL2Cypher Mode
- Single text input: "Describe what you want to find"
- Button: "Generate & Run"
- Expandable section showing the generated Cypher (for transparency)
- Output: results as a `st.dataframe`
- Error display if Cypher fails

### Configuration
- All credentials (Neo4j URI/user/password, Anthropic API key) loaded from `.env` via `python-dotenv`
- A `app/config.py` file centralizes all config loading

---

## Repository Structure (Target)

```
RAG-MilitAI/
├── AGENTS.md                        # This file
├── README.md                        # Public-facing project overview
├── requirements.txt                 # Python dependencies
├── .env.example                     # Template for environment variables
│
├── data/
│   ├── sample_of_data.csv           # 4-row sample for dev/test
│   ├── full_unified_annotations.csv
│   ├── full_unified_annotations_patch.csv
│   └── chroma_db/                   # ChromaDB persistent store (gitignored)
│
├── app/
│   ├── main.py                      # Streamlit entrypoint
│   ├── config.py                    # Env var loading + constants
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── connection.py            # Neo4j driver singleton
│   │   ├── schema.py                # Node/relationship creation + indexes
│   │   ├── templates.py             # Cypher template definitions
│   │   └── nl2cypher.py             # NL → Cypher via LLM
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── ingestion.py             # CSV → text → ChromaDB
│   │   ├── retriever.py             # ChromaDB query
│   │   └── chain.py                 # RAG chain (retriever + LLM)
│   └── ui/
│       ├── rag_panel.py             # RAG mode UI component
│       ├── template_panel.py        # Template mode UI component
│       └── nl2cypher_panel.py       # NL2Cypher mode UI component
│
└── scripts/
    ├── ingest_neo4j.py              # One-shot: CSV → Neo4j
    └── ingest_rag.py                # One-shot: CSV → ChromaDB
```

---

## Environment Variables

Create a `.env` file at the project root (never commit it):

```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# Anthropic (for NL2Cypher and RAG generation)
ANTHROPIC_API_KEY=sk-ant-...

# RAG config
CHROMA_PERSIST_DIR=data/chroma_db
EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_TOP_K=5
```

---

## Dependencies (requirements.txt target)

```
# Data
pandas

# Graph DB
neo4j

# Vector store / RAG
chromadb
sentence-transformers

# LLM
anthropic

# UI
streamlit

# Utils
python-dotenv
```

---

## Implementation Order

Follow this order to avoid blocking dependencies:

```
1. scripts/ingest_neo4j.py          (Neo4j ingestion — validates data model)
2. app/graph/templates.py           (Cypher templates — validates schema)
3. app/graph/nl2cypher.py           (NL2Cypher — needs working schema)
4. scripts/ingest_rag.py            (RAG ingestion — independent of graph)
5. app/rag/retriever.py + chain.py  (RAG chain — needs ingested Chroma)
6. app/ui/*.py                      (UI panels — need all backends ready)
7. app/main.py                      (Wire everything together)
```

---

## Key Conventions

- **Language**: Python 3.11+
- **Null handling**: CSV fields are often empty. Always check for `pd.isna()` or `None` before creating relationships in Neo4j or writing text fields in RAG.
- **Place nodes**: Deduplicated on `(lieu, departement, pays)` — use `MERGE` not `CREATE`.
- **Dates**: Stored as separate `jour`, `mois`, `annee` integer properties. Never try to parse into Python `date` objects (too many missing/partial dates).
- **Encoding**: All CSV files are UTF-8.
- **LLM model**: `claude-sonnet-4-6` for all LLM calls.
- **No hardcoded credentials**: Everything via `.env` + `python-dotenv`.
- **Testing**: Use `data/sample_of_data.csv` (4 rows) for all unit tests and manual smoke tests.

---

## Notes on the Historical Data

- Records are in French. Field names and values are in French.
- Many fields are sparse — most soldiers have birth info but few have marriage or death records.
- Surnames (`nom`) are in ALL CAPS in the source data. Nicknames (`surnom`) often describe origin or physical traits.
- The `naissance_lieu` is a locality name as written in the 17th–18th century — spelling may differ from modern French.
- `compagnie de grenadiers` is a common company name; there will be many soldiers under the same regiment+company combination.
- `matricule` is a unique identifier within a register, not globally unique.


- archive des hommes
- donnez 18e -19 e siecle
- images
- aider interoger aux base de donnees  (on fait pas traitement image - cette etape est deja faite)
- architecture
- demo
- science social (cibler les shs)


pitch (pas technique - 2-3 slide et support visual)