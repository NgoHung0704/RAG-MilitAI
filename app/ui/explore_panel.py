"""
Explore / Atlas panel (Explore Atlas Spec v0.1).

A free-browsing aggregate-visualisation tab — demographics, anthropometrics,
migration — over the **active dataset** from the sidebar switcher. Its purpose is
twofold: show what the structured KG *enables*, and demonstrate **which analyses
survive real sparsity** (the COMPLETE→MASKED through-line, §2). Dense-field plots
(enrolment, company, recruitment geography) hold up under masking; sparse-field
plots (age, longevity, height, death-place) collapse — that contrast *is* the
point (§3).

This is a **capability demonstration, not a source of historical findings** (§1):
synthetic distributions are authored to exercise the system, real ones are HTR
output. Honesty rules from §4 are enforced throughout — every plot shows its `n`,
sub-threshold groups render a warning instead of a confident chart, and the
longevity / death-place caveats are always visible.

Pure aggregation over the dataset CSV (pandas) — no live LLM, network-proof (§6).
The map reads coordinates from the gazetteer via :mod:`app.geo`.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app import geo

# §4: below this group size, show a sparsity warning instead of a chart. The
# spec suggests "e.g. n < 20"; the synthetic corpus is only 180 rows (stature
# fills just ~13 on COMPLETE), so 10 keeps the intended contrasts legible —
# height renders ✓ on COMPLETE and collapses ✗ on MASKED (the degradation
# exemplar), while death-place stays near-empty both ways (the finding). On the
# 82k real archive every dense field clears this comfortably.
N_MIN = 10

# French pied du roi → metres (pied = 12 pouces = 144 lignes).
_PIED_M = 0.32484

# Distinct palette for colour-by-company on the map / flows.
_PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
            "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC"]


# --------------------------------------------------------------------------- #
# data helpers                                                                #
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def _load(csv_path: str) -> pd.DataFrame:
    """Load a dataset CSV as all-strings ('' for absent), cached by path."""
    return pd.read_csv(csv_path, dtype=str, keep_default_na=False)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([pd.NA] * len(df), dtype="Float64")
    return pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")


def _present(df: pd.DataFrame, col: str) -> pd.Series:
    """Boolean mask of non-empty cells for *col*."""
    if col not in df.columns:
        return pd.Series([False] * len(df))
    return df[col].fillna("").astype(str).str.strip().ne("")


def _heights_m(df: pd.DataFrame) -> pd.Series:
    """Stature in metres — from pied/pouce/ligne when present, else taille_metre."""
    pied, pouce, ligne = _num(df, "pied"), _num(df, "pouce"), _num(df, "ligne")
    from_units = (
        pied.fillna(0) + pouce.fillna(0) / 12 + ligne.fillna(0) / 144
    ) * _PIED_M
    from_units = from_units.where(pied.notna())  # only valid when feet present
    metres = from_units.fillna(_num(df, "taille_metre"))
    return metres.where((metres > 1.0) & (metres < 2.3))  # drop implausible


def _fill_caption(n: int, total: int, extra: str = "") -> None:
    rate = f" · {100 * n / total:.0f}% fill" if total else ""
    st.caption(f"n = **{n}**{rate}{extra}")


def _guard(n: int, what: str) -> bool:
    """True if *n* clears the sparsity threshold; else render a warning (§4)."""
    if n >= N_MIN:
        return True
    st.warning(
        f"⚠️ Sparse: only **{n}** record(s) for {what} (< {N_MIN}). "
        "Withholding the chart — this field collapses at the active annotation level."
    )
    return False


def _palette_map(values) -> dict[str, str]:
    return {v: _PALETTE[i % len(_PALETTE)] for i, v in enumerate(sorted(values))}


def _hbar(series: pd.Series, value_name: str, kp: str, *,
          trim_to: int = 30, weight: pd.Series | None = None) -> None:
    """Horizontal bar chart with **full, un-truncated** category labels.

    Long company / place names overflow ``st.bar_chart``'s default axis label
    limit; an explicit Altair chart with ``labelLimit=0`` on a horizontal axis
    shows them in full and scales height to the number of bars.

    Charts are **trimmed to the top *trim_to*** by default. When there are more
    than *trim_to* bars, a "Show all N" toggle is offered (off by default) to
    expand to the full set — handy on the real archive where a chart can run to
    hundreds of bars.

    The trim ranks by *weight* when given (aligned to *series*), else by the
    plotted value. For a mean (e.g. stature) pass the per-group ``n`` as *weight*
    so "top N" keeps the **best-sampled** groups, not the highest averages.
    """
    rank = (weight if weight is not None else series).sort_values(ascending=False)
    omitted = 0
    keep = rank.index
    if len(rank) > trim_to:
        basis = "best-sampled (largest n)" if weight is not None else "largest"
        if not st.toggle(
            f"Show all {len(rank)}", key=f"{kp}_all",
            help=f"Off keeps the {trim_to} {basis}; on shows all {len(rank)} bars.",
        ):
            keep = rank.head(trim_to).index
            omitted = len(rank) - trim_to
    s = series.reindex(keep)
    data = s.rename_axis("category").reset_index(name=value_name)
    tooltip = ["category", value_name]
    if weight is not None:  # the bar shows a mean — add the group size n
        data["n soldiers"] = weight.reindex(keep).to_numpy()
        tooltip.append("n soldiers")
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X(f"{value_name}:Q", title=value_name),
            y=alt.Y("category:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=0)),
            tooltip=tooltip,
        )
        .properties(height=max(160, len(data) * 18))
    )
    st.altair_chart(chart, use_container_width=True)
    if omitted:
        st.caption(
            f"Showing the top {trim_to}; {omitted} smaller group(s) hidden — "
            "turn on **Show all** above to expand."
        )


# --------------------------------------------------------------------------- #
# plots — each renders for ONE dataframe (single or one compare column)        #
# --------------------------------------------------------------------------- #

def _plot_enrolment(df: pd.DataFrame, kp: str) -> None:
    years = _num(df, "enrolement_annee").dropna().astype(int)
    n = len(years)
    _fill_caption(n, len(df), " — `enrolement_annee` (dense, ~83% real)")
    if not _guard(n, "enrolment years"):
        return
    by_company = st.toggle("Split by company", key=f"{kp}_split")
    if by_company and "compagnie" in df.columns:
        sub = df.loc[years.index]
        tmp = pd.DataFrame({"year": years.values, "compagnie": sub["compagnie"].values})
        tmp = tmp[tmp["compagnie"].str.strip().ne("")]
        pivot = tmp.pivot_table(index="year", columns="compagnie",
                                aggfunc=len, fill_value=0)
        st.bar_chart(pivot, height=280)
    else:
        counts = years.value_counts().sort_index()
        st.bar_chart(counts.rename("enrolments"), height=280)


def _plot_company_sizes(df: pd.DataFrame, kp: str) -> None:
    present = _present(df, "compagnie")
    sizes = df.loc[present, "compagnie"].value_counts()
    _fill_caption(int(present.sum()), len(df), " — `compagnie` (~99%, robust)")
    if sizes.empty:
        st.info("No company values.")
        return
    _hbar(sizes, "soldiers", kp)


def _plot_birthplace(df: pd.DataFrame, kp: str) -> None:
    level = st.radio("Granularity", ["Country", "Department"], horizontal=True,
                     key=f"{kp}_lvl")
    col = "naissance_pays" if level == "Country" else "naissance_departement"
    present = _present(df, col)
    counts = df.loc[present, col].value_counts()
    rate = "~74%" if level == "Country" else "~66%"
    _fill_caption(int(present.sum()), len(df), f" — `{col}` ({rate}, mostly robust)")
    if counts.empty:
        st.info("No birthplace values at this level.")
        return
    _hbar(counts, "soldiers", kp)


def _binned_counts(series: pd.Series, edges, name: str) -> pd.Series:
    """Histogram counts over pd.cut bins with Altair-safe, ordered string labels.

    pd.cut produces an IntervalIndex whose Interval labels (e.g. ``(10, 15]``)
    Vega/Altair cannot serialize as axis categories — so we label the bins
    explicitly as strings while preserving bin order.
    """
    edges = list(edges)
    labels = [f"{a}–{b}" for a, b in zip(edges[:-1], edges[1:])]
    cats = pd.cut(series, bins=edges, labels=labels)
    return cats.value_counts().sort_index().rename(name)


def _plot_age_enrolment(df: pd.DataFrame, kp: str) -> None:
    enrol, birth = _num(df, "enrolement_annee"), _num(df, "naissance_annee")
    age = (enrol - birth)
    age = age.where((age >= 10) & (age <= 70)).dropna()
    n = len(age)
    _fill_caption(n, len(df),
                  " — enrolment − birth year (birth ~21%, **sparse**)")
    if not _guard(n, "age at enrolment"):
        return
    st.bar_chart(_binned_counts(age, range(10, 75, 5), "soldiers"), height=280)
    st.caption(f"Median age at enrolment ≈ **{age.median():.0f}** (n={n}).")


def _plot_longevity(df: pd.DataFrame, kp: str) -> None:
    death, birth = _num(df, "deces_annee"), _num(df, "naissance_annee")
    age = (death - birth)
    age = age.where((age >= 10) & (age <= 100)).dropna()
    n = len(age)
    _fill_caption(n, len(df),
                  " — death − birth year (needs **both**, very sparse)")
    st.info(
        "⚖️ **Censoring caveat:** a missing death year usually means "
        "*left-service-alive* or *unobserved*, not missing-at-random — so the "
        "observed ages are a biased subsample (in-service deaths). This is **not** "
        "life expectancy."
    )
    if not _guard(n, "age at death"):
        return
    st.bar_chart(_binned_counts(age, range(10, 105, 5), "deaths"), height=280)


def _plot_height(df: pd.DataFrame, kp: str) -> None:
    metres = _heights_m(df).dropna()
    n = len(metres)
    _fill_caption(n, len(df),
                  " — `pied/pouce/ligne` (~2%) / `taille_metre` (~0.8%) — **the "
                  "degradation exemplar**")
    if not _guard(n, "stature"):
        return
    st.bar_chart(_binned_counts(metres, [round(1.4 + 0.05 * i, 2) for i in range(13)], "soldiers"), height=260)
    st.caption(f"Mean stature ≈ **{metres.mean():.3f} m** (n={n}).")

    # mean stature by region / company — rich on COMPLETE, hollow on real/masked
    by = st.radio("Mean stature by", ["Region", "Company"], horizontal=True,
                  key=f"{kp}_by")
    col = "naissance_region" if by == "Region" else "compagnie"
    if col not in df.columns:
        return
    grp = pd.DataFrame({"m": metres, "g": df.loc[metres.index, col]})
    grp = grp[grp["g"].str.strip().ne("")]
    agg = grp.groupby("g")["m"].agg(["mean", "count"])
    agg = agg[agg["count"] >= 5]  # don't plot a "mean" from 1–2 soldiers
    if agg.empty:
        st.caption(f"No {by.lower()} group reaches n≥5 for a mean — collapsed here.")
        return
    _hbar(agg["mean"], "mean stature (m)", kp, weight=agg["count"])
    st.caption("Groups with n < 5 omitted from the means.")


def _plot_flows(df: pd.DataFrame, kp: str) -> None:
    origin = "naissance_region" if _present(df, "naissance_region").any() \
        else "naissance_departement"
    mask = _present(df, origin) & _present(df, "compagnie")
    n = int(mask.sum())
    _fill_caption(n, len(df),
                  f" — `{origin}` + `compagnie` (joint ~78.6%, dense)")
    if not _guard(n, "birthplace→company flows"):
        return
    sub = df.loc[mask, [origin, "compagnie"]]
    pivot = sub.pivot_table(index=origin, columns="compagnie",
                            aggfunc=len, fill_value=0)
    st.bar_chart(pivot, height=320)
    st.caption(
        "Each bar is a birth region; segments are companies — on synthetic the "
        "planted geography (A Breton · B eastern · C national) shows as distinct "
        "composition."
    )


def _plot_flows_one(df: pd.DataFrame, kp: str) -> None:
    """Company composition for a *single* selected birthplace — the per-place
    slice of the flows plot, far easier to read than the full stacked bars."""
    granularity = st.radio(
        "Birthplace level", ["Region", "Department"], horizontal=True,
        key=f"{kp}_lvl",
    )
    origin = "naissance_region" if granularity == "Region" else "naissance_departement"
    if not _present(df, origin).any():
        st.info(f"No `{origin}` values in this dataset.")
        return

    # Offer birthplaces by descending count (most-recruited first).
    have = df.loc[_present(df, origin) & _present(df, "compagnie")]
    places = have[origin].value_counts()
    if places.empty:
        st.info("No birthplace has any recorded company.")
        return
    choice = st.selectbox(
        "Birthplace",
        options=list(places.index),
        format_func=lambda p: f"{p}  ({places[p]} soldiers)",
        key=f"{kp}_place",
    )

    sub = have[have[origin] == choice]
    n = len(sub)
    _fill_caption(n, len(df),
                  f" — company recruitment from **{choice}** (`{origin}`)")
    if not _guard(n, f"recruitment from {choice}"):
        return
    counts = sub["compagnie"].value_counts()
    _hbar(counts, "soldiers", kp)
    top = counts.index[0]
    share = 100 * counts.iloc[0] / n
    st.caption(
        f"{counts.size} compan(ies) recruited from {choice}; the largest, "
        f"**{top}**, took **{share:.0f}%** ({counts.iloc[0]}/{n})."
    )


def _plot_map(df: pd.DataFrame, kp: str) -> None:
    col = "naissance_departement"
    present = _present(df, col)
    counts = df.loc[present, col].value_counts()
    _fill_caption(int(present.sum()), len(df),
                  " — birthplaces by department, plotted by gazetteer coordinates")

    color_by_company = st.toggle("Colour by dominant company", key=f"{kp}_colcmp")

    rows, unmapped = [], 0
    for dept, count in counts.items():
        latlon = geo.department_coords(dept)
        if latlon is None:
            unmapped += int(count)
            continue
        lat, lon = latlon
        rec = {"lat": lat, "lon": lon, "department": dept, "count": int(count)}
        if color_by_company and "compagnie" in df.columns:
            sub = df[(df[col] == dept) & _present(df, "compagnie")]
            if not sub.empty:
                rec["company"] = sub["compagnie"].value_counts().idxmax()
        rows.append(rec)

    if not rows:
        st.warning(
            "No birthplaces could be geocoded yet. The map reads the gazetteer's "
            "Layer-M coordinate field — once the toponym enrichment populates it, "
            "departments appear here automatically."
        )
        return

    mdf = pd.DataFrame(rows)
    cmax = mdf["count"].max()
    mdf["size"] = 5000 + (mdf["count"] / cmax) * 45000  # radius in metres
    map_kwargs = dict(latitude="lat", longitude="lon", size="size")
    if color_by_company and "company" in mdf.columns:
        cmap = _palette_map(mdf["company"].dropna().unique())
        mdf["color"] = mdf["company"].map(cmap).fillna("#888888")
        map_kwargs["color"] = "color"
    st.map(mdf, **map_kwargs)

    src = ("gazetteer Layer-M" if geo.coords_loaded_from_gazetteer()
           else "approximate department centroids (built-in fallback — gazetteer "
           "not yet geocoded)")
    note = f"Coordinates: **{src}**. {len(mdf)} department(s) plotted"
    if unmapped:
        note += f"; **{unmapped}** record(s) in un-geocoded departments omitted"
    st.caption(note + ".")


def _plot_death_arcs(df: pd.DataFrame, kp: str) -> None:
    mask = _present(df, "naissance_departement") & (
        _present(df, "deces_lieu") | _present(df, "deces_departement")
    )
    n = int(mask.sum())
    _fill_caption(n, len(df),
                  " — birthplace → death-place (~0.6% joint, **the sparsest case**)")
    st.info(
        "🪦 **Near-empty on real is the finding:** the registers support recruitment "
        "geography, not birth→death trajectories. Arcs render only where both "
        "endpoints exist; on synthetic the planted trajectory cases populate it."
    )
    if n == 0:
        st.caption("No record has both a birth department and a death place.")
        return

    sub = df.loc[mask]
    arcs = []
    for _, r in sub.iterrows():
        src = geo.department_coords(r.get("naissance_departement", ""))
        dst = (geo.department_coords(r.get("deces_departement", ""))
               or geo.department_coords(r.get("deces_lieu", "")))
        if src and dst:
            arcs.append({"sx": src[1], "sy": src[0], "tx": dst[1], "ty": dst[0]})

    st.caption(f"{n} record(s) with both endpoints; {len(arcs)} geocoded to arcs.")
    if not arcs:
        return
    try:
        import pydeck as pdk

        adf = pd.DataFrame(arcs)
        layer = pdk.Layer(
            "ArcLayer", data=adf,
            get_source_position=["sx", "sy"], get_target_position=["tx", "ty"],
            get_source_color=[76, 120, 168], get_target_color=[228, 87, 86],
            get_width=3,
        )
        view = pdk.ViewState(latitude=46.7, longitude=2.4, zoom=4.2)
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view))
    except Exception as exc:  # pydeck ships with streamlit, but degrade safely
        st.caption(f"(Arc map unavailable: {exc}) — showing the trajectory table.")
        st.dataframe(
            sub[["nom", "prenom", "naissance_departement", "deces_lieu"]],
            use_container_width=True, hide_index=True,
        )


# --------------------------------------------------------------------------- #
# coverage-survival view (§5)                                                  #
# --------------------------------------------------------------------------- #

# (plot label, predicate over a df → n of usable records)
def _n_height(df):  # pied OR taille_metre present
    return int((_present(df, "pied") | _present(df, "taille_metre")).sum())


def _n_all(*cols):
    def f(df):
        mask = pd.Series([True] * len(df))
        for c in cols:
            mask &= _present(df, c)
        return int(mask.sum())
    return f


_COVERAGE_PLOTS = [
    ("Enrolment-year distribution", _n_all("enrolement_annee"), "dense"),
    ("Company sizes", _n_all("compagnie"), "dense"),
    ("Birthplace breakdown", _n_all("naissance_departement"), "dense"),
    ("Recruitment flows (birth→company)", _n_all("naissance_departement", "compagnie"), "dense"),
    ("Recruitment-origin map", _n_all("naissance_departement"), "dense"),
    ("Age at enrolment", _n_all("enrolement_annee", "naissance_annee"), "sparse"),
    ("Longevity / age at death", _n_all("deces_annee", "naissance_annee"), "sparse"),
    ("Height / stature", _n_height, "sparse"),
    ("Death-place arcs", _n_all("naissance_departement", "deces_lieu"), "sparse"),
]


def _render_coverage(df_complete: pd.DataFrame, df_masked: pd.DataFrame) -> None:
    st.caption(
        "Does each plot stay interpretable (n ≥ "
        f"{N_MIN}) from COMPLETE → MASKED? Dense-field plots hold; sparse-field "
        "plots collapse — annotation completeness gates which analyses are "
        "possible (§5). This is the Explore tab's one-glance contribution to the "
        "headline result."
    )
    rows = []
    for name, fn, kind in _COVERAGE_PLOTS:
        nc, nm = fn(df_complete), fn(df_masked)
        rows.append({
            "Plot": name,
            "Field density": kind,
            "COMPLETE n": nc,
            "MASKED n": nm,
            "COMPLETE": "✓" if nc >= N_MIN else "✗",
            "MASKED": "✓" if nm >= N_MIN else "✗",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "The ✗ column under MASKED is the COMPLETE→MASKED collapse — the point, "
        "not a defect."
    )


# --------------------------------------------------------------------------- #
# entry point                                                                  #
# --------------------------------------------------------------------------- #

def _render_one(plot_fn, cols, base_key: str) -> None:
    """Render *plot_fn* for the active dataset, or side-by-side in compare mode."""
    if len(cols) == 1:
        plot_fn(cols[0][1], f"{base_key}_{cols[0][2]}")
        return
    c = st.columns(2)
    for (label, df, suf), col in zip(cols, c):
        with col:
            st.markdown(f"**{label}**")
            plot_fn(df, f"{base_key}_{suf}")


def render(config) -> None:
    active = st.session_state.get("active_dataset", config.DEFAULT_DATASET)
    ds = config.get_dataset(active)

    st.header("Explore / Atlas — aggregate visualisation")
    st.caption(
        "Free browsing of demographics, anthropometrics and migration over the "
        "**active dataset**. A capability demonstration, not historical findings."
    )

    # Honesty banner (§4) — synthetic = capability, real = illustrative.
    if ds["has_gold"]:
        st.warning(
            "🧪 **Synthetic dataset.** These distributions are *authored to exercise "
            "the system*, not real 18th-century demographic facts. Read them as "
            "*what the KG enables*, and watch the COMPLETE→MASKED collapse."
        )
    else:
        st.info(
            "🗂️ **Real archive — illustrative.** The data is HTR output (presence ≠ "
            "correctness), so treat every pattern as *suggestive*, not authoritative."
        )

    # Compare control (§2) — synthetic only, mirrors the Showcase.
    compare = False
    if ds["key"] in config.SYNTH_DATASETS:
        compare = st.toggle(
            "Compare COMPLETE vs MASKED side-by-side",
            help="The dense-vs-sparse contrast is the through-line.",
        )

    df_complete = _load(config.get_dataset("synth_complete")["csv"])
    df_masked = _load(config.get_dataset("synth_masked")["csv"])

    if compare:
        cols = [("COMPLETE", df_complete, "c"), ("MASKED", df_masked, "m")]
    else:
        cols = [(ds["label"], _load(ds["csv"]), "a")]

    st.markdown("---")
    tab_demo, tab_anthro, tab_mig, tab_cov = st.tabs(
        ["Demographics", "Anthropometric", "Migration", "Coverage survival"]
    )

    with tab_demo:
        st.subheader("Enrolment-year distribution")
        _render_one(_plot_enrolment, cols, "enrol")
        st.markdown("---")
        st.subheader("Company sizes / composition")
        _render_one(_plot_company_sizes, cols, "csize")
        st.markdown("---")
        st.subheader("Birthplace breakdown")
        _render_one(_plot_birthplace, cols, "birth")
        st.markdown("---")
        st.subheader("Age at enrolment")
        _render_one(_plot_age_enrolment, cols, "age")
        st.markdown("---")
        st.subheader("Longevity / age at death")
        _render_one(_plot_longevity, cols, "long")

    with tab_anthro:
        st.subheader("Height distribution & mean stature")
        st.caption(
            "The degradation exemplar — rich on COMPLETE, hollow on real/masked. "
            "Lean into the contrast."
        )
        _render_one(_plot_height, cols, "height")

    with tab_mig:
        st.subheader("Birthplace → company recruitment flows")
        _render_one(_plot_flows, cols, "flows")
        st.markdown("---")
        st.subheader("Company recruitment for one birthplace")
        st.caption("Pick a birthplace to read its company breakdown on its own.")
        _render_one(_plot_flows_one, cols, "flows1")
        st.markdown("---")
        st.subheader("Recruitment-origin map")
        _render_one(_plot_map, cols, "map")
        st.markdown("---")
        st.subheader("Death-place arcs (where available)")
        _render_one(_plot_death_arcs, cols, "arcs")

    with tab_cov:
        st.subheader("Coverage-survival view")
        _render_coverage(df_complete, df_masked)
