"""
First-run ingestion bootstrap.

When the app starts it ensures every configured dataset's backends are
populated: each dataset's CSV is ingested into its Neo4j instance and its Chroma
collection if they are reachable and not already loaded. **Idempotent** —
populated backends are skipped, so restarts are instant.

Scope is controlled by the ``MILITAI_AUTOINGEST`` env var:
    "all"  (default) — real + synth_complete + synth_masked
    "synth"          — only the two synthetic datasets (fast; skips the 82k real archive)
    "off"            — do nothing (manual ingestion via scripts/Makefile)

A Neo4j instance that is unreachable (e.g. its container isn't running) is
skipped with a note rather than failing the app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `app.*` and `scripts.*` importable when launched via Streamlit.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb

import app.config as config
from app.graph.connection import get_driver, is_reachable
from app.rag.ingestion import ingest_csv


def _scope() -> str:
    return os.getenv("MILITAI_AUTOINGEST", "all").strip().lower()


def datasets_in_scope() -> list[str]:
    scope = _scope()
    if scope == "off":
        return []
    if scope == "synth":
        return list(config.SYNTH_DATASETS)
    return list(config.DATASETS.keys())  # "all"


def _neo4j_soldier_count(driver) -> int:
    with driver.session() as session:
        return session.run("MATCH (n:Soldier) RETURN count(n) AS n").single()["n"]


def _chroma_count(collection_name: str) -> int:
    try:
        client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        return client.get_collection(collection_name).count()
    except Exception:
        return 0


def ensure_ingested(log=print) -> list[dict]:
    """Ingest any in-scope dataset whose backends are empty. Returns a report.

    *log* is a callable taking one string (defaults to ``print``); the Streamlit
    caller passes a status writer so progress is visible in the UI.
    """
    # Imported lazily so importing this module never triggers a Neo4j connection.
    from scripts.ingest_neo4j import ingest_to_neo4j

    report: list[dict] = []
    scope = _scope()
    if scope == "off":
        log("Auto-ingestion disabled (MILITAI_AUTOINGEST=off).")
        return report

    for key in datasets_in_scope():
        ds = config.get_dataset(key)
        entry = {"dataset": key, "neo4j": "skipped", "chroma": "skipped"}

        # -- Neo4j ------------------------------------------------------- #
        uri = ds["neo4j_uri"]
        if not is_reachable(uri):
            log(f"[{key}] Neo4j unreachable ({uri}) — skipped")
        else:
            try:
                driver = get_driver(uri)
                if _neo4j_soldier_count(driver) > 0:
                    log(f"[{key}] Neo4j already populated — skipped")
                    entry["neo4j"] = "already"
                else:
                    log(f"[{key}] ingesting Neo4j ← {ds['csv']} …")
                    n = ingest_to_neo4j(driver, ds["csv"])
                    log(f"[{key}] Neo4j: {n} records ingested")
                    entry["neo4j"] = f"ingested ({n})"
            except Exception as exc:  # never let ingestion crash the app
                log(f"[{key}] Neo4j ingest failed: {exc}")
                entry["neo4j"] = f"error: {exc}"

        # -- Chroma ------------------------------------------------------ #
        coll = ds["chroma_collection"]
        if _chroma_count(coll) > 0:
            log(f"[{key}] Chroma '{coll}' already populated — skipped")
            entry["chroma"] = "already"
        else:
            note = " (82k rows — this takes a few minutes)" if key == "real" else ""
            log(f"[{key}] embedding RAG → Chroma '{coll}'{note} …")
            try:
                n = ingest_csv(
                    csv_path=ds["csv"],
                    persist_dir=config.CHROMA_PERSIST_DIR,
                    model_name=config.EMBEDDING_MODEL,
                    collection_name=coll,
                )
                log(f"[{key}] Chroma '{coll}': {n} docs embedded")
                entry["chroma"] = f"ingested ({n})"
            except Exception as exc:
                log(f"[{key}] Chroma ingest failed: {exc}")
                entry["chroma"] = f"error: {exc}"

        report.append(entry)

    return report
