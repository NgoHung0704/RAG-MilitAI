"""
One-shot ingestion script: CSV → ChromaDB vector store.

Usage:
    python scripts/ingest_rag.py                   # full dataset
    python scripts/ingest_rag.py --sample           # 4-row sample (for testing)
    python scripts/ingest_rag.py --csv path/to.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.config as config
from app.rag.ingestion import ingest_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CSV into ChromaDB for RAG")
    parser.add_argument("--dataset", default="real",
                        choices=list(config.DATASETS.keys()),
                        help="Target dataset (resolves CSV + Chroma collection from the registry)")
    parser.add_argument("--csv", default=None, help="Override CSV file path")
    parser.add_argument("--sample", action="store_true",
                        help="Use the 4-row sample file for testing (real dataset)")
    parser.add_argument("--collection", default=None,
                        help="Override Chroma collection name")
    parser.add_argument("--chroma-dir", default=None,
                        help=f"ChromaDB persist directory (default: {config.CHROMA_PERSIST_DIR})")
    parser.add_argument("--model", default=None,
                        help=f"Sentence-transformers model (default: {config.EMBEDDING_MODEL})")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Embedding batch size (default: 500)")
    args = parser.parse_args()

    ds = config.get_dataset(args.dataset)
    csv_path = args.csv or (config.SAMPLE_DATA_PATH if args.sample else ds["csv"])
    persist_dir = args.chroma_dir or config.CHROMA_PERSIST_DIR
    model_name = args.model or config.EMBEDDING_MODEL
    collection_name = args.collection or ds["chroma_collection"]

    print(f"Dataset      : {args.dataset} ({ds['label']})")
    print(f"Source CSV   : {csv_path}")
    print(f"ChromaDB dir : {persist_dir}")
    print(f"Collection   : {collection_name}")
    print(f"Model        : {model_name}")
    print()

    n = ingest_csv(
        csv_path=csv_path,
        persist_dir=persist_dir,
        model_name=model_name,
        batch_size=args.batch_size,
        collection_name=collection_name,
    )

    print(f"\nDone. {n} documents stored in ChromaDB.")


if __name__ == "__main__":
    main()
