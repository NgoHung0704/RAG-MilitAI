import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root (parent of the app/ package) — anchors data + corpus paths.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Neo4j (the `real` dataset instance, default bolt port)
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

# DeepSeek
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")

# RAG / ChromaDB
CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "data/chroma_db")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))

# Data
DATA_PATH: str = os.getenv("DATA_PATH", "data/full_unified_annotations_patch.csv")
SAMPLE_DATA_PATH: str = os.getenv("SAMPLE_DATA_PATH", "data/sample_of_data.csv")

# ---------------------------------------------------------------------------
# Datasets registry — single source of truth (Demo Interface Spec v0.2 §1)
# ---------------------------------------------------------------------------
#
# Neo4j Community allows only one database per instance, so the three logical
# datasets are isolated by *separate Neo4j instances* (distinct bolt ports),
# not by named database. Chroma is unaffected: one persist dir holds all three
# collections, distinguished by collection name. The synthetic corpus already
# lives under validation/corpus/ with precomputed gold (answers.json).

_CORPUS: Path = PROJECT_ROOT / "validation" / "corpus"

DATASETS: dict[str, dict] = {
    "real": {
        "key": "real",
        "label": "Real archive (Mémoire des Hommes)",
        "neo4j_uri": NEO4J_URI,
        "chroma_collection": "soldiers",  # legacy collection name
        "csv": DATA_PATH,
        "questions": None,
        "gold": None,
        "has_gold": False,
        "schema": "legacy",
        "records": "~82k",
        "nature": "no ground truth",
    },
    "synth_complete": {
        "key": "synth_complete",
        "label": "Synthetic — complete annotation",
        "neo4j_uri": os.getenv("NEO4J_URI_SYNTH_COMPLETE", "bolt://localhost:7688"),
        "chroma_collection": "synth_complete",
        "csv": str(_CORPUS / "complete.csv"),
        "questions": str(_CORPUS / "questions.jsonl"),
        "gold": str(_CORPUS / "gold" / "answers.json"),
        "has_gold": True,
        "schema": "fixed",
        "records": 180,
        "nature": "full annotation",
        "condition": "complete",
    },
    "synth_masked": {
        "key": "synth_masked",
        "label": "Synthetic — masked to real sparsity",
        "neo4j_uri": os.getenv("NEO4J_URI_SYNTH_MASKED", "bolt://localhost:7689"),
        "chroma_collection": "synth_masked",
        "csv": str(_CORPUS / "masked.csv"),
        "questions": str(_CORPUS / "questions.jsonl"),
        "gold": str(_CORPUS / "gold" / "answers.json"),
        "has_gold": True,
        "schema": "fixed",
        "records": 180,
        "nature": "masked to real sparsity",
        "condition": "masked",
    },
}

DEFAULT_DATASET: str = "real"
SYNTH_DATASETS: tuple[str, ...] = ("synth_complete", "synth_masked")


def get_dataset(key: str) -> dict:
    """Return the registry entry for *key*, or the default if unknown."""
    return DATASETS.get(key, DATASETS[DEFAULT_DATASET])
