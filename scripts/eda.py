#!/usr/bin/env python
"""Exploratory data analysis for the MilitAI datasets.

Computes, for one or more CSVs, the descriptive statistics used in
``docs/SOLUTION.md`` §3: fill rates, cardinality, top categorical values, and
numeric-field summaries. The real MASKED-vs-real fill-rate comparison that
validates the synthetic calibration is emitted when both the real archive and
the synthetic masked corpus are analysed in one run.

Usage
-----
    # default: real archive + both synthetic conditions, write the JSON used by the docs
    python scripts/eda.py

    # a single file, print to stdout only
    python scripts/eda.py --csv data/sample_of_data.csv --no-write

    # custom output path
    python scripts/eda.py --out docs/eda/eda_results.json

Notes
-----
* The real CSV is Latin-1/CP1252 encoded (e.g. ``Régiment``); pandas reads it
  fine in binary-safe ``str`` mode, but top-value strings may contain the raw
  bytes. We decode best-effort for display only.
* Empty strings are treated as missing (``na_values=['']``) so fill rates match
  the ingestion path, which skips null/empty fields.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# Fields highlighted in docs/SOLUTION.md §3.2 / §4.6 (the real<->masked check).
FILL_FOCUS = [
    "nom", "prenom", "compagnie", "matricule", "enrolement_annee", "surnom",
    "naissance_lieu", "naissance_pays", "naissance_departement", "naissance_region",
    "pere_prenom", "mere_prenom", "mere_nom", "deces_annee", "grade_final",
    "naissance_annee", "regiment", "age", "profession", "taille_metre",
    "deces_lieu", "deces_departement",
]
CATEGORICAL = [
    "regiment", "compagnie", "naissance_departement", "naissance_pays",
    "naissance_region", "grade_final", "prenom", "nom", "profession",
]
NUMERIC = [
    "enrolement_annee", "naissance_annee", "deces_annee", "mariage_annee",
    "age", "taille_metre",
]
# The dataset registry (mirrors app/config.py for standalone use).
DEFAULT_TARGETS = [
    ("real", "data/full_unified_annotations.csv"),
    ("synth_complete", "validation/corpus/complete.csv"),
    ("synth_masked", "validation/corpus/masked.csv"),
]


def _read(path: str) -> pd.DataFrame:
    """Read a CSV in binary-safe string mode with empty == missing."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def _clean(value: object) -> object:
    """Best-effort fix for CP1252 bytes mis-read as UTF-8, for display only."""
    if not isinstance(value, str):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def analyse(name: str, path: str, top_n: int = 10) -> dict:
    df = _read(path)
    n = len(df)

    fill_rates = {c: round(df[c].notna().sum() / n * 100, 1) for c in df.columns}
    fill_focus = {c: fill_rates[c] for c in FILL_FOCUS if c in df.columns}

    cardinality = {c: int(df[c].nunique()) for c in CATEGORICAL if c in df.columns}

    top_values = {}
    for c in CATEGORICAL:
        if c in df.columns:
            vc = df[c].value_counts().head(top_n)
            top_values[c] = {_clean(k): int(v) for k, v in vc.items()}

    numeric = {}
    for c in NUMERIC:
        if c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            present = int(s.notna().sum())
            if present:
                numeric[c] = {
                    "n": present,
                    "min": float(s.min()),
                    "max": float(s.max()),
                    "mean": round(float(s.mean()), 3),
                    "median": float(s.median()),
                }

    return {
        "dataset": name,
        "path": path,
        "rows": n,
        "columns": len(df.columns),
        "fill_rates_all": dict(sorted(fill_rates.items(), key=lambda kv: -kv[1])),
        "fill_rates_focus": fill_focus,
        "cardinality": cardinality,
        "top_values": top_values,
        "numeric": numeric,
    }


def masked_vs_real(results: dict) -> dict | None:
    """Compare synthetic MASKED fill rates to the real archive (calibration check)."""
    real = results.get("real")
    masked = results.get("synth_masked")
    if not real or not masked:
        return None
    comparison = {}
    for c, real_v in real["fill_rates_focus"].items():
        if c in masked["fill_rates_focus"]:
            masked_v = masked["fill_rates_focus"][c]
            comparison[c] = {
                "real": real_v,
                "masked": masked_v,
                "delta_pts": round(masked_v - real_v, 1),
            }
    deltas = [abs(v["delta_pts"]) for v in comparison.values()]
    return {
        "fields": comparison,
        "max_abs_delta_pts": max(deltas) if deltas else None,
        "mean_abs_delta_pts": round(sum(deltas) / len(deltas), 2) if deltas else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="EDA for the MilitAI datasets.")
    ap.add_argument("--csv", action="append", metavar="PATH",
                    help="analyse a single CSV (repeatable); overrides the defaults")
    ap.add_argument("--out", default="docs/eda/eda_results.json",
                    help="output JSON path (default: docs/eda/eda_results.json)")
    ap.add_argument("--top-n", type=int, default=10,
                    help="number of top categorical values to keep (default: 10)")
    ap.add_argument("--no-write", action="store_true",
                    help="print a summary only; do not write the JSON")
    args = ap.parse_args()

    if args.csv:
        targets = [(Path(p).stem, p) for p in args.csv]
    else:
        targets = DEFAULT_TARGETS

    results: dict[str, dict] = {}
    for name, path in targets:
        if not Path(path).exists():
            print(f"[skip] {name}: {path} not found")
            continue
        print(f"[eda]  {name}: {path}")
        results[name] = analyse(name, path, top_n=args.top_n)
        r = results[name]
        print(f"       rows={r['rows']} cols={r['columns']}")

    payload = {
        "tool": "scripts/eda.py",
        "datasets": results,
        "masked_vs_real": masked_vs_real(results),
    }

    if args.no_write:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[write] {out}")
    mvr = payload["masked_vs_real"]
    if mvr:
        print(f"[check] masked-vs-real mean abs delta = {mvr['mean_abs_delta_pts']} pts, "
              f"max abs delta = {mvr['max_abs_delta_pts']} pts")


if __name__ == "__main__":
    main()
