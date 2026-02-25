"""
MilitAI — Streamlit entrypoint.

Run with:
    streamlit run app/main.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from openai import OpenAI

import app.config as config
from app.ui import nl2cypher_panel, rag_panel, template_panel

st.set_page_config(
    page_title="MilitAI — French Military Records",
    page_icon="⚔️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session-state initialisation (runs once per browser session)
# ---------------------------------------------------------------------------

if "neo4j_driver" not in st.session_state:
    try:
        from app.graph.connection import get_driver
        st.session_state["neo4j_driver"] = get_driver()
        st.session_state["neo4j_status"] = "connected"
    except Exception as exc:
        st.session_state["neo4j_driver"] = None
        st.session_state["neo4j_status"] = f"error: {exc}"

if "anthropic_client" not in st.session_state:
    if config.DEEPSEEK_API_KEY:
        st.session_state["anthropic_client"] = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
    else:
        st.session_state["anthropic_client"] = None

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚔️ MilitAI")
    st.caption("French Military Records Explorer")
    st.markdown("---")

    mode = st.radio(
        "Query Mode",
        options=["RAG", "Template", "NL2Cypher"],
        index=0,
        key="query_mode",
        help=(
            "**RAG** — Semantic search + LLM answer\n\n"
            "**Template** — Parameterized Cypher queries\n\n"
            "**NL2Cypher** — Natural language → Cypher via LLM"
        ),
    )

    st.markdown("---")
    st.markdown("### Connection status")

    # Neo4j status badge
    neo4j_status = st.session_state.get("neo4j_status", "unknown")
    if neo4j_status == "connected":
        st.success("Neo4j  connected")
    else:
        st.error(f"Neo4j  {neo4j_status}")

    # ChromaDB status badge
    chroma_path = Path(config.CHROMA_PERSIST_DIR)
    if chroma_path.exists() and any(chroma_path.iterdir()):
        st.success("ChromaDB  ready")
    else:
        st.warning("ChromaDB  not ingested")

    # DeepSeek status badge
    if st.session_state["anthropic_client"] is not None:
        st.success("DeepSeek  configured")
    else:
        st.error("DeepSeek  key missing")

    st.markdown("---")
    st.caption(
        "Data source: [Mémoire des Hommes](https://www.memoiredeshommes.defense.gouv.fr/) "
        "(SHDGR / Ministère des Armées)"
    )

# ---------------------------------------------------------------------------
# Main panel — route to the selected mode
# ---------------------------------------------------------------------------

driver = st.session_state["neo4j_driver"]
client = st.session_state["anthropic_client"]

if mode == "RAG":
    rag_panel.render(client, config)

elif mode == "Template":
    template_panel.render(driver, config)

elif mode == "NL2Cypher":
    nl2cypher_panel.render(driver, client, config)
