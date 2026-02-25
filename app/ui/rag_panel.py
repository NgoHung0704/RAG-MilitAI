"""
Streamlit panel — RAG query mode.
"""

from __future__ import annotations

import streamlit as st
from openai import OpenAI

from app.rag.chain import answer_with_rag


def render(client: OpenAI | None, config) -> None:
    st.header("RAG — Ask a question")
    st.caption(
        "Ask anything about the soldiers in natural language. "
        "The system retrieves the most relevant records and answers using an LLM."
    )

    if client is None:
        st.error(
            "DeepSeek API key not configured. "
            "Set **DEEPSEEK_API_KEY** in your `.env` file and restart."
        )
        return

    question = st.text_area(
        "Your question",
        placeholder="e.g. Which soldiers were born in Paris and died in 1721?",
        height=100,
        key="rag_question",
    )

    if st.button("Search", type="primary", key="rag_search"):
        if not question.strip():
            st.warning("Please enter a question.")
            return

        try:
            with st.spinner("Retrieving records and generating answer …"):
                result = answer_with_rag(
                    question=question,
                    client=client,
                    persist_dir=config.CHROMA_PERSIST_DIR,
                    model_name=config.EMBEDDING_MODEL,
                    k=config.RAG_TOP_K,
                )
        except FileNotFoundError as exc:
            st.error(
                f"ChromaDB collection not found.\n\n"
                f"{exc}\n\n"
                "Run the following command to build the vector store:\n"
                "```\npython scripts/ingest_rag.py\n```"
            )
            return
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")
            return

        st.markdown("### Answer")
        st.markdown(result["answer"])

        with st.expander(f"Source records used ({len(result['sources'])})"):
            for i, src in enumerate(result["sources"], start=1):
                nom = src.get("nom", "")
                prenom = src.get("prenom", "")
                regiment = src.get("regiment", "")
                ark_url = src.get("ark_url", "")
                source_image = src.get("source_image", "")

                title = f"**{i}. {prenom} {nom}**"
                if regiment:
                    title += f" — {regiment}"

                st.markdown(title)
                if source_image:
                    st.caption(f"Source: `{source_image}`")
                if ark_url:
                    st.markdown(f"[Open archive record]({ark_url})")
                st.divider()
