"""
Matching normalization + frozen toponym gazetteer (spec v0.6, §2).

Two shared utilities, used by the pandas gold (and meant to be mirrored at graph
ingest as shadow `*_norm` properties / `wikidata_qid` on Place nodes):

- norm(s): fold-only matching key — NFKD strip accents -> lowercase -> remove
  dashes, whitespace, apostrophes. Deterministic. Storage keeps the accented,
  hyphenated, cased original; only *matching* folds. This lets intentionally
  unaccented question params (e.g. "Cotes-du-Nord", "Rene") match stored values.

- GAZETTEER + resolve_place(name): a pinned snapshot mapping place labels (FR and
  modern-EN) to a wikidata_qid and a P131 parent hierarchy (commune -> department
  -> region). FR/EN place questions resolve against this snapshot, deterministically
  — e.g. EN "Brittany" -> region Bretagne -> its departments. The diachronic
  (historical-name / parent-at-date) layer is only scaffolded here, not used by the
  demo (see the Toponym Resolution Spec).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from pools import DEPARTMENTS

# Pinned snapshot metadata (determinism is against this frozen snapshot).
SNAPSHOT = {
    "source": "Wikidata",
    "pinned": "2026-06-11",
    "geography": "modern",
    "note": "Illustrative pinned QIDs for modern administrative geography; "
            "null where not pinned. Diachronic layer scaffolded, not used in demo.",
}

_STRIP = (" ", "\t", "\n", "-", "'", "’")  # space, dash, straight/curly apostrophe


def norm(s) -> str:
    """Fold-only matching key (see module docstring)."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    for ch in _STRIP:
        s = s.replace(ch, "")
    return s


# Regions (province grain). Only the QIDs we are confident about are pinned;
# Bretagne (the toponym-resolution path) is fully pinned.
REGIONS = {
    "Bretagne":      {"qid": "Q12130", "en": "Brittany",
                      "departments": ["Finistère", "Côtes-du-Nord", "Morbihan"]},
    "Alsace":        {"qid": "Q1142",  "en": "Alsace",        "departments": ["Bas-Rhin"]},
    "Lorraine":      {"qid": "Q1133",  "en": "Lorraine",      "departments": ["Moselle", "Meurthe"]},
    "Île-de-France": {"qid": "Q13917", "en": "Île-de-France", "departments": ["Seine"]},
    "Lyonnais":      {"qid": None,     "en": "Lyonnais",      "departments": ["Rhône"]},
    "Guyenne":       {"qid": None,     "en": "Guyenne",       "departments": ["Gironde"]},
    "Flandre":       {"qid": None,     "en": "Flanders",      "departments": ["Nord"]},
    "Dauphiné":      {"qid": None,     "en": "Dauphiné",      "departments": ["Isère"]},
    "Auvergne":      {"qid": None,     "en": "Auvergne",      "departments": ["Puy-de-Dôme"]},
    "Normandie":     {"qid": "Q18677", "en": "Normandy",      "departments": ["Eure"]},
    "Corse":         {"qid": "Q14112", "en": "Corsica",       "departments": ["Corse"]},
}

# Departments: pinned modern QID where confident, modern label, P131 region.
DEPT_QID = {
    "Finistère": "Q3361", "Côtes-du-Nord": "Q3354", "Morbihan": "Q3331",
    "Bas-Rhin": "Q12722", "Moselle": None, "Meurthe": None, "Seine": None,
    "Rhône": "Q12724", "Gironde": "Q3338", "Nord": "Q12709", "Isère": "Q3214",
    "Puy-de-Dôme": "Q7139", "Eure": "Q3319", "Corse": None,
}
DEPT_MODERN = {  # modern label where the name changed since 1790
    "Côtes-du-Nord": "Côtes-d'Armor", "Meurthe": "Meurthe-et-Moselle",
    "Seine": "Paris (former Seine)", "Corse": "Corse",
}


def _build_gazetteer() -> dict:
    dept_region = {}
    for reg, info in REGIONS.items():
        for d in info["departments"]:
            dept_region[d] = reg

    departments = {}
    for d, reg in dept_region.items():
        departments[d] = {
            "label_fr": d,
            "label_en": DEPT_MODERN.get(d, d),
            "wikidata_qid": DEPT_QID.get(d),
            "p131_region": reg,
            "norm": norm(d),
        }

    communes = {}
    for d, info in DEPARTMENTS.items():
        for c in info["communes"]:
            communes[c] = {
                "label": c, "wikidata_qid": None,
                "p131_department": d, "p131_region": dept_region.get(d),
                "norm": norm(c),
            }

    return {
        "snapshot": SNAPSHOT,
        "regions": {r: {**v, "norm_fr": norm(r), "norm_en": norm(v["en"])}
                    for r, v in REGIONS.items()},
        "departments": departments,
        "communes": communes,
    }


GAZETTEER = _build_gazetteer()

# norm -> canonical FR region label (both FR and EN labels resolve)
_REGION_INDEX = {}
for _r, _v in GAZETTEER["regions"].items():
    _REGION_INDEX[_v["norm_fr"]] = _r
    _REGION_INDEX[_v["norm_en"]] = _r
_DEPT_INDEX = {v["norm"]: d for d, v in GAZETTEER["departments"].items()}
_DEPT_INDEX.update({norm(v["label_en"]): d for d, v in GAZETTEER["departments"].items()})
_COMMUNE_INDEX = {v["norm"]: c for c, v in GAZETTEER["communes"].items()}


def resolve_place(name: str) -> dict | None:
    """Resolve a FR or modern-EN place label to its canonical entry + the set of
    departments it covers (region -> its departments; department/commune -> itself).
    Returns None if unresolved."""
    n = norm(name)
    if n in _REGION_INDEX:
        reg = _REGION_INDEX[n]
        return {"kind": "region", "canonical_fr": reg,
                "wikidata_qid": GAZETTEER["regions"][reg]["qid"],
                "departments": list(GAZETTEER["regions"][reg]["departments"])}
    if n in _DEPT_INDEX:
        d = _DEPT_INDEX[n]
        return {"kind": "department", "canonical_fr": d,
                "wikidata_qid": GAZETTEER["departments"][d]["wikidata_qid"],
                "departments": [d]}
    if n in _COMMUNE_INDEX:
        c = _COMMUNE_INDEX[n]
        return {"kind": "commune", "canonical_fr": c, "wikidata_qid": None,
                "departments": [GAZETTEER["communes"][c]["p131_department"]]}
    return None


def write_gazetteer(path: Path):
    path.write_text(json.dumps(GAZETTEER, ensure_ascii=False, indent=2), encoding="utf-8")
