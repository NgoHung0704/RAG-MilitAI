"""
Sidebar — dataset switcher, live badge, and connection status.

Demo Interface Spec v0.2 §2: choose Real vs Synthetic (and, when Synthetic,
Complete vs Masked), show a persistent badge describing what is live, and report
the reachability of the *active* dataset's backends.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.graph.connection import is_reachable


def render_sidebar(config) -> str:
    """Render the sidebar and return the active dataset key.

    Writes ``st.session_state["active_dataset"]`` so every panel can resolve the
    same dataset without re-deriving it.
    """
    with st.sidebar:
        st.title("⚔️ MilitAI")
        st.caption("French Military Records Explorer")
        st.markdown("---")

        # -- dataset family: Real vs Synthetic ----------------------------- #
        family = st.radio(
            "Dataset",
            options=["Real archive", "Synthetic"],
            index=0,
            key="dataset_family",
            help=(
                "**Real archive** — Mémoire des Hommes (~82k records, no ground truth)\n\n"
                "**Synthetic** — generated corpus with hidden gold answers and a "
                "COMPLETE vs MASKED degradation study"
            ),
        )

        if family == "Synthetic":
            annotation = st.radio(
                "Annotation",
                options=["Complete", "Masked"],
                index=0,
                key="dataset_annotation",
                help=(
                    "**Complete** — every field annotated\n\n"
                    "**Masked** — fields blanked to mimic real-archive sparsity"
                ),
            )
            active = "synth_complete" if annotation == "Complete" else "synth_masked"
        else:
            active = "real"

        st.session_state["active_dataset"] = active
        ds = config.get_dataset(active)

        # -- live badge ---------------------------------------------------- #
        _render_badge(ds)

        st.markdown("---")
        st.markdown("### Connection status")
        _render_status(ds, config)
        _render_infra()

        st.markdown("---")
        st.caption(
            "Data source: [Mémoire des Hommes](https://www.memoiredeshommes.defense.gouv.fr/) "
            "(SHDGR / Ministère des Armées)"
        )

    return active


def _render_badge(ds: dict) -> None:
    """Persistent badge describing the live dataset and its nature (§2)."""
    if ds["key"] == "real":
        st.info(f"**Real archive** · {ds['records']} · {ds['nature']}")
    else:
        condition = ds.get("condition", "")
        st.success(
            f"**Synthetic · {condition}** · {ds['records']} records · {ds['nature']}"
        )


def _render_status(ds: dict, config) -> None:
    """Per-instance Neo4j + Chroma + DeepSeek status for the active dataset."""
    # Neo4j (the active dataset's instance)
    if is_reachable(ds["neo4j_uri"]):
        st.success(f"Neo4j  connected ({ds['neo4j_uri']})")
    else:
        st.error(f"Neo4j  unreachable ({ds['neo4j_uri']})")

    # ChromaDB store presence (collections share one persist dir)
    chroma_path = Path(config.CHROMA_PERSIST_DIR)
    if chroma_path.exists() and any(chroma_path.iterdir()):
        st.success(f"ChromaDB  ready (collection: {ds['chroma_collection']})")
    else:
        st.warning("ChromaDB  not ingested")

    # DeepSeek
    if st.session_state.get("anthropic_client") is not None:
        st.success("DeepSeek  configured")
    else:
        st.error("DeepSeek  key missing")


def _render_infra() -> None:
    """Start/inspect the Neo4j Docker containers from the UI (host-only)."""
    import time

    from app import docker_control as dc

    with st.expander("⚙️ Neo4j containers (Docker)"):
        if not dc.docker_available():
            st.caption(
                "Docker CLI/daemon not reachable from here. Start Neo4j manually "
                "with `docker compose up -d` (or `make up`)."
            )
            return

        for svc, status in dc.neo4j_health().items():
            icon = "🟢" if status == "healthy" else ("🟡" if status in ("starting", "running") else "⚪")
            st.caption(f"{icon} {svc}: {status}")

        if st.button("▶ Start / refresh Neo4j containers", use_container_width=True):
            with st.spinner("Starting containers (docker compose up -d) …"):
                ok, out = dc.compose_up()
            if not ok:
                st.error(f"docker compose failed:\n\n```\n{out}\n```")
                return
            with st.spinner("Waiting for Neo4j to become healthy …"):
                for _ in range(24):  # up to ~120s
                    if all(v == "healthy" for v in dc.neo4j_health().values()):
                        break
                    time.sleep(5)
            # let the first-run bootstrap re-evaluate and ingest now that they're up
            st.session_state["bootstrap_done"] = False
            st.success("Neo4j containers up — re-running to ingest …")
            st.rerun()
