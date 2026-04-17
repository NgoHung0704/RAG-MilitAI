# MilitAI

MilitAI is a hybrid query platform for French military records from the Ancien Regime.
It combines three query modes in one Streamlit interface:

- RAG over CSV records with ChromaDB + sentence-transformers.
- Parameterized Cypher templates executed on Neo4j.
- NL2Cypher generation (natural language to Cypher) using DeepSeek.

The project targets history and social science workflows by making archive-backed data exploration faster and reproducible.

## Core Features

- Single UI with mode switch: RAG, Template, NL2Cypher.
- Graph model ingestion from CSV into Neo4j with relationship-rich schema.
- Local vector store ingestion and semantic retrieval with source metadata.
- Query transparency:
	- Template mode always shows exact Cypher.
	- NL2Cypher mode exposes generated Cypher.
	- RAG mode shows source records used for the answer.

## Architecture

```text
												 +-------------------------+
												 |       Streamlit UI      |
												 |        app/main.py      |
												 +------------+------------+
																			|
										 +----------------+----------------+
										 |                                 |
					+----------v----------+            +---------v----------+
					|    Graph Pipeline   |            |    RAG Pipeline    |
					| app/graph/*         |            | app/rag/*          |
					+----------+----------+            +---------+----------+
										 |                                 |
					+----------v----------+            +---------v----------+
					|      Neo4j DB       |            |      ChromaDB      |
					| soldiers graph      |            | local vector store |
					+---------------------+            +--------------------+

Data source for both pipelines: data/*.csv
```

## Repository Layout

```text
RAG-MilitAI/
├── app/
│   ├── config.py
│   ├── main.py
│   ├── graph/
│   ├── rag/
│   └── ui/
├── data/
├── scripts/
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── requirements.txt
└── .env.example
```

## Prerequisites

Choose one workflow:

- Docker workflow (recommended):
	- Docker Desktop 4.0+
	- GNU Make (or compatible make command)
- Local Python workflow:
	- Python 3.11+
	- Neo4j running locally or remotely

## Environment Configuration

1. Copy environment template:

```bash
cp .env.example .env
```

2. Update values in .env:

- Required for graph mode: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
- Required for LLM features: DEEPSEEK_API_KEY
- Optional: CHROMA_PERSIST_DIR, EMBEDDING_MODEL, RAG_TOP_K

## Quick Start (Docker + Make)

1. Build and start services:

```bash
make up
```

2. Ingest sample data first (recommended for smoke tests):

```bash
make ingest-neo4j-sample
make ingest-rag-sample
```

3. Open applications:

- Streamlit: http://localhost:8501
- Neo4j Browser: http://localhost:7474

4. Stop services:

```bash
make down
```

## Local Python Workflow (without Docker)

1. Create and activate virtual environment:

```bash
python -m venv .venv
# Windows PowerShell
. .venv/Scripts/Activate.ps1
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run ingestion scripts:

```bash
python scripts/ingest_neo4j.py --sample
python scripts/ingest_rag.py --sample
```

4. Start UI:

```bash
streamlit run app/main.py
```

## Make Targets

```bash
make help
```

Main commands:

- make build: Build app image.
- make up: Start Neo4j + Streamlit.
- make down: Stop services.
- make restart: Restart services.
- make logs: Tail logs.
- make ps: Show service status.
- make app-shell: Open shell inside app container.
- make neo4j-shell: Open cypher-shell in Neo4j container.
- make ingest-neo4j-sample: Load sample CSV into Neo4j.
- make ingest-neo4j-full: Load full CSV into Neo4j.
- make ingest-rag-sample: Build Chroma collection from sample CSV.
- make ingest-rag-full: Build Chroma collection from full CSV.
- make clean: Stop and remove containers, networks, and volumes.

## Data and Ingestion Notes

- Use sample_of_data.csv for fast iteration and validation.
- Use full_unified_annotations_patch.csv for full ingestion runs.
- CSV values are sparse; ingestion scripts skip null/empty relationships.
- Place deduplication in graph ingestion relies on MERGE with place identity fields.

## Operational Notes

- If NL2Cypher or RAG generation is unavailable, verify DEEPSEEK_API_KEY.
- If graph queries fail, verify NEO4J credentials and service health.
- If RAG returns no useful sources, run ingestion again and verify Chroma persist directory.

## Troubleshooting

- Neo4j not ready:

```bash
make logs
```

- Recreate stack from scratch:

```bash
make clean
make up
```

- Rebuild app image after dependency changes:

```bash
make build
make up
```

## License and Data Attribution

Source records originate from the French military archives ecosystem (Memoire des Hommes / SHDGR).
This repository provides processing and query tooling; historical interpretation remains the responsibility of the researcher.
