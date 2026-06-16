"""
Streamlit panel — parameterized Cypher template mode.
"""

from __future__ import annotations

import neo4j
import pandas as pd
import streamlit as st

from app.graph.templates import (
    TEMPLATES,
    ParamDef,
    Template,
    fetch_options,
    run_template,
)


def _options_for(driver: neo4j.Driver, p: ParamDef) -> list[str]:
    """Fetch (and cache for the session) the selectable values for a multiselect param."""
    cache = st.session_state.setdefault("_tpl_options_cache", {})
    if p.options_cypher not in cache:
        cache[p.options_cypher] = fetch_options(driver, p.options_cypher)
    return cache[p.options_cypher]


def render(driver: neo4j.Driver | None, config) -> None:
    st.header("Template — Cypher query")
    st.caption(
        "Select a pre-built query template, fill in the parameters, and run it against Neo4j."
    )

    if driver is None:
        st.error(
            "Neo4j is not connected. "
            "Check **NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD** in your `.env` file and restart."
        )
        return

    # Template selector
    template_names = [t.name for t in TEMPLATES]
    selected_name = st.selectbox("Query template", template_names, key="tpl_select")
    template: Template = next(t for t in TEMPLATES if t.name == selected_name)

    st.caption(f"_{template.description}_")

    # Dynamic parameter form
    params: dict = {}
    if template.params:
        with st.form(key="tpl_form"):
            for p in template.params:
                if p.type == "int":
                    params[p.name] = st.number_input(
                        p.label,
                        value=0,
                        step=1,
                        format="%d",
                        key=f"tpl_param_{p.name}",
                    )
                elif p.type == "multiselect":
                    params[p.name] = st.multiselect(
                        p.label,
                        options=_options_for(driver, p),
                        key=f"tpl_param_{p.name}",
                        help="Type to search; select one or more.",
                    )
                else:
                    params[p.name] = st.text_input(
                        p.label,
                        placeholder=p.placeholder,
                        key=f"tpl_param_{p.name}",
                    )
            submitted = st.form_submit_button("Run Query", type="primary")
    else:
        # No params — single button outside a form
        submitted = st.button("Run Query", type="primary", key="tpl_run_noparams")

    if submitted:
        # Validate that required string params are non-empty
        missing = [
            p.label for p in template.params
            if (p.type == "str" and not str(params.get(p.name, "")).strip())
            or (p.type == "multiselect" and not params.get(p.name))
        ]
        if missing:
            st.warning(f"Please fill in: {', '.join(missing)}")
            return

        # Cast int params
        for p in template.params:
            if p.type == "int":
                params[p.name] = int(params[p.name])

        try:
            with st.spinner("Running query …"):
                rows = run_template(driver, template, params)
        except Exception as exc:
            st.error(f"Query failed: {exc}")
            return

        if not rows:
            st.info("No results found.")
            return

        st.caption(f"{len(rows)} result(s)")
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)

    # Always show the Cypher for transparency
    with st.expander("Cypher query"):
        st.code(template.cypher, language="cypher")
