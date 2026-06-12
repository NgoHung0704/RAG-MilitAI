"""
MilitAI — Streamlit entrypoint.

Run with:
    streamlit run app/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path so `app.*` and `validation.*` imports work
# when run via Streamlit.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from openai import OpenAI

import app.config as config
from app.graph.connection import get_driver_for_dataset
from app.ui import nl2cypher_panel, rag_panel, showcase_panel, template_panel
from app.ui.sidebar import render_sidebar

st.set_page_config(
    page_title="MilitAI — French Military Records",
    page_icon="⚔️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session-state initialisation (runs once per browser session)
# ---------------------------------------------------------------------------

if "anthropic_client" not in st.session_state:
    if config.DEEPSEEK_API_KEY:
        st.session_state["anthropic_client"] = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
    else:
        st.session_state["anthropic_client"] = None

client = st.session_state["anthropic_client"]

# ---------------------------------------------------------------------------
# First-run ingestion bootstrap (idempotent; scope via MILITAI_AUTOINGEST).
# Populates each dataset's Neo4j + Chroma if empty, then skips on later runs.
# ---------------------------------------------------------------------------

if not st.session_state.get("bootstrap_done"):
    from app.bootstrap import ensure_ingested

    with st.status("Preparing datasets — first-run ingestion …", expanded=False) as _status:
        ensure_ingested(log=lambda m: _status.write(m))
        _status.update(label="Datasets ready", state="complete")
    st.session_state["bootstrap_done"] = True

# ---------------------------------------------------------------------------
# Sidebar — dataset switcher, badge, connection status
# ---------------------------------------------------------------------------

active_dataset = render_sidebar(config)
ds = config.get_dataset(active_dataset)

# Resolve the active dataset's Neo4j driver lazily (None if its instance is down).
try:
    driver = get_driver_for_dataset(active_dataset)
except Exception:
    driver = None

collection_name = ds["chroma_collection"]

# ---------------------------------------------------------------------------
# Main panels — four tabs
# ---------------------------------------------------------------------------

tab_template, tab_rag, tab_nl2cypher, tab_showcase = st.tabs(
    ["Template", "RAG", "NL2Cypher", "Showcase"]
)

with tab_template:
    template_panel.render(driver, config)

with tab_rag:
    rag_panel.render(client, config, collection_name=collection_name)

with tab_nl2cypher:
    nl2cypher_panel.render(driver, client, config)

with tab_showcase:
    showcase_panel.render(config)
