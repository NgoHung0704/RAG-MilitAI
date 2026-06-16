# Reproducibility

This document records the exact software, models, and configuration used by
MilitAI (RAG + knowledge-graph assistant), for reproduction of the reported
results.

## Runtime & dependencies

- **Python 3.11** — `.python-version` pins `3.11`; `pyproject.toml` declares
  `requires-python = ">=3.11"`. Reference environment built on **CPython 3.11.9**.
- **Dependency pins** are resolved and locked by [`uv`](https://github.com/astral-sh/uv)
  in **`uv.lock`** (declared in `pyproject.toml`). There is no `requirements.txt`;
  the lockfile is the authoritative, reproducible source of truth. The Docker
  image is built with `uv sync --frozen --no-dev`.

Key locked versions (from `uv.lock`):

| Package | Version |
|---|---|
| streamlit | 1.58.0 |
| chromadb | 1.5.9 |
| sentence-transformers | 5.5.1 |
| neo4j (Python driver) | 6.2.0 |
| openai (client; used for DeepSeek & OpenRouter) | 2.41.1 |
| torch | 2.12.0 |
| transformers | 5.11.0 |
| numpy | 2.4.6 |
| pandas | 3.0.3 |
| plotly | 6.8.0 |
| python-dotenv | 1.2.2 |
| pyyaml | 6.0.3 |
| tqdm | 4.68.2 |

## Backends (Neo4j)

- **Neo4j Community 5.23.0**, Docker image `neo4j:5.23.0-community`, run via
  `docker compose` (see `docker-compose.yml`).
- Multi-instance topology (each on its own bolt port):

| Instance | Records | HTTP | Bolt | Heap (init/max) | Notes |
|---|---|---|---|---|---|
| real archive | ~82k | 7474 | 7687 | 512m / 1024m | demo default |
| synthetic — COMPLETE annotation | 180 | 7475 | 7688 | 128m / 256m | |
| synthetic — MASKED to real sparsity | 180 | 7476 | 7689 | 128m / 256m | |
| eval scratch (`--profile eval`) | per-condition wipe+reload | 7477 | 7690 | 128m / 256m | not started by plain `docker compose up` |

The eval instance is profile-gated; bring it up only for the offline eval runner:

```bash
docker compose --profile eval up -d neo4j-eval
```

## Models

### Generation — NL2Cypher and RAG answers

- **DeepSeek `deepseek-chat`**, OpenAI-compatible API
  (`base_url=https://api.deepseek.com`), via the `openai` 2.41.1 client.
- Decoding parameters differ by code path:

| Path | File | temperature | max_tokens | seed |
|---|---|---|---|---|
| Eval-time RAG generation | `validation/eval/rag.py` | **0** | 512 | none |
| Interactive RAG answers | `app/rag/chain.py` | API default (**1.0**) | 1024 | none |
| Interactive NL2Cypher | `app/graph/nl2cypher.py` | API default (**1.0**) | 512 | none |

  No `seed` parameter is passed on any LLM call. Report results from the
  eval runner (temperature 0) for determinism; the interactive demo paths are
  not pinned to temperature 0.

- **Snapshot:** `deepseek-chat` is a moving alias that always points at the
  current DeepSeek-V3 line; DeepSeek does not expose dated snapshots. To fix the
  version for the paper, record the **run date** and cross-reference DeepSeek's
  changelog (<https://api-docs.deepseek.com/updates>); optionally confirm the
  served id via the API response `model` field or `GET /models`.

### RAG faithfulness judge (eval-time only)

- **`google/gemma-4-31b-it` via OpenRouter** (`base_url=https://openrouter.ai/api/v1`).
  Default set in `validation/eval/rag.py` (overridable via `JUDGE_MODEL`).
  Deliberately a different model family from the DeepSeek generator.
- Decoding: **temperature 0, max_tokens 400**, single structured (JSON) call.

### Embeddings & retrieval

- **`all-MiniLM-L6-v2`** (sentence-transformers, 384-dim); configurable via
  `EMBEDDING_MODEL`.
- Retrieval **top-k = 5** (`RAG_TOP_K`).
- Vector store: **ChromaDB 1.5.9**, persistent client.
- **Distance metric: cosine** — set explicitly at collection creation in
  `app/rag/ingestion.py` (`configuration={"hnsw": {"space": "cosine"}}`).
  (Chroma's default is squared-L2; we pin cosine because the embeddings are
  compared by angle.)
- **No reranking.**

> **Re-ingestion required:** the HNSW space is fixed when a collection is
> created. Stores built before this metric was pinned were created with L2 and
> must be rebuilt to take effect. Delete and re-ingest:
>
> ```bash
> # app store
> rm -rf data/chroma_db
> python scripts/ingest_rag.py            # full real dataset
>
> # eval stores (rebuilt automatically by the eval runner)
> rm -rf validation/corpus/eval/chroma
> python validation/evaluate.py --live --rag
> ```

## Synthetic data determinism (separate from LLM decoding)

- The synthetic corpus is generated with a fixed RNG seed **`SEED = 20260611`**
  (`validation/generate.py`), making regeneration byte-for-byte reproducible.
  This is unrelated to LLM decoding (no LLM `seed` is used).

## Environment knobs (defaults)

From `docker-compose.yml` / `app/config.py`:

| Variable | Default |
|---|---|
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` |
| `RAG_TOP_K` | 5 |
| `JUDGE_MODEL` | `google/gemma-4-31b-it` |
| `NEO4J_URI` | `bolt://neo4j:7687` |
| `CHROMA_PERSIST_DIR` | `/app/data/chroma_db` |

Secrets (not committed): `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`,
`NEO4J_PASSWORD`.
