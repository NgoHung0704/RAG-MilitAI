"""
Streamlit panel — NL2Cypher mode.
"""

from __future__ import annotations

import neo4j
from openai import OpenAI
import pandas as pd
import streamlit as st

from app.graph.nl2cypher import run_nl2cypher


def render(driver: neo4j.Driver | None, client: OpenAI | None, config) -> None:
    st.header("NL2Cypher — Natural language query")
    st.caption(
        "Describe what you want to find in plain language (French or English). "
        "The LLM will generate a Cypher query and run it against Neo4j."
    )

    if driver is None:
        st.error(
            "Neo4j is not connected. "
            "Check **NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD** in your `.env` file and restart."
        )
        return

    if client is None:
        st.error(
            "DeepSeek API key not configured. "
            "Set **DEEPSEEK_API_KEY** in your `.env` file and restart."
        )
        return

    question = st.text_area(
        "Describe your query",
        placeholder=(
            "e.g. Find all soldiers born in Normandie who served in the grenadiers "
            "and deserted before 1730"
        ),
        height=120,
        key="nl2c_question",
    )

    if st.button("Generate & Run", type="primary", key="nl2c_run"):
        if not question.strip():
            st.warning("Please enter a question.")
            return

        generated_cypher: str | None = None

        try:
            with st.spinner("Generating Cypher with LLM …"):
                cypher, rows = run_nl2cypher(driver, question, client)
            generated_cypher = cypher
        except ValueError as exc:
            # Execution failed — show Cypher + error
            # The generated Cypher is embedded in the error message; extract it if possible
            st.error(str(exc))
            if generated_cypher:
                with st.expander("Generated Cypher (failed)"):
                    st.code(generated_cypher, language="cypher")
            return
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")
            return

        with st.expander("Generated Cypher", expanded=False):
            st.code(cypher, language="cypher")

        if not rows:
            st.info("Query executed successfully but returned no results.")
            return

        st.caption(f"{len(rows)} result(s)")
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
