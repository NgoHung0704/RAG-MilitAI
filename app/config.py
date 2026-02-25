import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Neo4j
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
