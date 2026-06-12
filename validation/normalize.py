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

import hashlib
import json
import unicodedata
from dataclasses import dataclass
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


def _snapshot_id() -> str:
    """Content hash over the pinned source data + dates (§2: a snapshot_id is a
    content hash + dates, recorded on every row). Stable across runs because it
    folds only the frozen inputs, not the stamped output."""
    src = json.dumps(
        {"source": SNAPSHOT["source"], "pinned": SNAPSHOT["pinned"],
         "geography": SNAPSHOT["geography"], "regions": REGIONS,
         "dept_qid": DEPT_QID, "dept_modern": DEPT_MODERN, "departments": DEPARTMENTS},
        ensure_ascii=False, sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


SNAPSHOT_ID = _snapshot_id()
SNAPSHOT["snapshot_id"] = SNAPSHOT_ID


def _empty_historical() -> dict:
    """Layer-H fields: present in the schema, populated only when Layer H is
    implemented (§1). Layer M leaves them empty."""
    return {
        "historical_names": [],     # [{name, start, end, source}] from P1448 + P580/P582 / WHG
        "historical_parents": [],   # [{entity, start, end}] généralité/province at a date
        "existence": {"inception": None, "abolished": None},  # P571 / P576
    }


def _build_gazetteer() -> dict:
    dept_region = {}
    for reg, info in REGIONS.items():
        for d in info["departments"]:
            dept_region[d] = reg

    departments = {}
    for d, reg in dept_region.items():
        modern = DEPT_MODERN.get(d)
        region_qid = REGIONS[reg]["qid"]
        departments[d] = {
            "label_fr": d,
            "label_en": modern or d,
            "en_label": d,                      # FR/EN department names coincide
            # alt_labels: variant/renamed forms (e.g. Côtes-du-Nord -> Côtes-d'Armor)
            "alt_labels": [modern] if modern and modern != d else [],
            "wikidata_qid": DEPT_QID.get(d),
            "geonames_id": None,
            "whg_id": None,                     # Layer-H anchor, not wired in the demo
            "admin_level": "department",
            "p131_region": reg,
            "parent_qids": [q for q in (region_qid,) if q],
            "coords": None,
            "norm": norm(d),
            **_empty_historical(),
            "snapshot_id": SNAPSHOT_ID,
        }

    communes = {}
    for d, info in DEPARTMENTS.items():
        reg = dept_region.get(d)
        dept_qid = DEPT_QID.get(d)
        region_qid = REGIONS[reg]["qid"] if reg in REGIONS else None
        for c in info["communes"]:
            communes[c] = {
                "label": c,
                "en_label": c,
                "alt_labels": [],
                "wikidata_qid": None,
                "geonames_id": None,
                "whg_id": None,
                "admin_level": "commune",
                "p131_department": d,
                "p131_region": reg,
                "parent_qids": [q for q in (dept_qid, region_qid) if q],
                "coords": None,
                "norm": norm(c),
                **_empty_historical(),
                "snapshot_id": SNAPSHOT_ID,
            }

    regions = {}
    for r, v in REGIONS.items():
        regions[r] = {
            **v,
            "en_label": v["en"],
            "alt_labels": [],
            "geonames_id": None,
            "whg_id": None,
            "admin_level": "region",
            "parent_qids": [],          # top of the modelled hierarchy
            "coords": None,
            "norm_fr": norm(r),
            "norm_en": norm(v["en"]),
            **_empty_historical(),
            "snapshot_id": SNAPSHOT_ID,
        }

    return {
        "snapshot": SNAPSHOT,
        "regions": regions,
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
# Communes index norm -> [labels]: a single normalised form can denote several
# communes (the many Saint-Martins). Disambiguation is by administrative context.
_COMMUNE_INDEX: dict[str, list] = {}
for _c, _v in GAZETTEER["communes"].items():
    _COMMUNE_INDEX.setdefault(_v["norm"], []).append(_c)


def resolve_place(name: str, context_dept: str | None = None) -> dict | None:
    """Resolve a FR or modern-EN place label to its canonical entry + the set of
    departments it covers (region -> its departments; department/commune -> itself).

    ``context_dept`` (Toponym Spec §3 step 3) disambiguates homonyms at department
    grain: when a normalised commune name maps to several communes, the one whose
    P131 department matches ``context_dept`` is preferred. Returns None if unresolved.
    """
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
        cands = _COMMUNE_INDEX[n]
        c = _disambiguate_commune(cands, context_dept)
        return {"kind": "commune", "canonical_fr": c,
                "wikidata_qid": GAZETTEER["communes"][c]["wikidata_qid"],
                "departments": [GAZETTEER["communes"][c]["p131_department"]]}
    return None


def _disambiguate_commune(cands: list, context_dept: str | None) -> str:
    """Pick one commune from homonym candidates (Toponym Spec §3 step 3): prefer the
    one consistent with ``context_dept``; otherwise resolve deterministically."""
    if len(cands) == 1:
        return cands[0]
    if context_dept:
        cd = norm(context_dept)
        match = [x for x in cands
                 if norm(GAZETTEER["communes"][x]["p131_department"]) == cd]
        if match:
            return sorted(match)[0]
    return sorted(cands)[0]


# ---------------------------------------------------------------------------
# Layer H — diachronic resolution (scaffold; Toponym Spec §4)
# ---------------------------------------------------------------------------
# Interfaces defined, deferred. The temporal-validity filter and the WHG fallback
# stay unimplemented for the demo; the signature below and the empty historical_* /
# existence schema fields are the hooks the real (HistoMil-AI / ArchivAI) pipeline
# builds to. Nothing in the demo calls resolve_historical().
LAYER_H_IMPLEMENTED = False


@dataclass
class PlaceResolution:
    """Result of Layer-H resolution at a record's date (Toponym Spec §4).

    ``qid`` / ``whg_id`` identify the entity (WHG is the historical anchor);
    ``label_at_year`` and ``parent_at_year`` are the period-correct name and
    administrative parent (parish -> généralité/province, not modern department);
    ``confidence`` in [0, 1]; ``source`` is which authority answered
    ('wikidata' | 'whg' | 'layer-M-fallback' | 'unresolved').
    """
    qid: str | None
    whg_id: str | None
    label_at_year: str | None
    parent_at_year: str | None
    confidence: float
    source: str


def resolve_historical(mention: str, year: int,
                       context_dept: str | None = None) -> PlaceResolution:
    """Resolve ``mention`` to the entity valid at ``year`` (Toponym Spec §4 contract).

    Scaffold only — does NOT honour ``year``. The temporal-validity filter (keep
    candidates whose historical_names/existence span contains ``year``) and the WHG
    fallback are deferred until Layer H is wired to a frozen Wikidata+WHG snapshot
    with populated ``historical_names`` / ``historical_parents`` / ``existence``.
    Until then it delegates to Layer-M (present-day) resolution and flags the result
    as a fallback with confidence 0 (not a period-correct answer).
    """
    # 1. candidate generation over canonical_fr + alt_labels (+ historical_names,
    #    currently empty), narrowed by administrative context.
    res = resolve_place(mention, context_dept=context_dept)
    if res is None:
        return PlaceResolution(None, None, None, None, 0.0, "unresolved")

    # 2. TODO(Layer H): temporal-validity filter on historical_names/existence vs `year`.
    # 3. TODO(Layer H): disambiguate by temporal parent at `year`; WHG fallback when
    #    Wikidata coverage is thin (small/defunct communes). Deferred — see §4.
    if LAYER_H_IMPLEMENTED:  # pragma: no cover - reserved for the diachronic pipeline
        raise NotImplementedError("Layer-H temporal resolution is not implemented")

    # Layer-M fallback: modern label + modern parent stand in for the period-correct
    # ones; confidence 0 marks that `year` was not applied.
    kind, cf = res["kind"], res["canonical_fr"]
    if kind == "department":
        parent = GAZETTEER["departments"][cf]["p131_region"]
    elif kind == "commune":
        parent = GAZETTEER["communes"][cf]["p131_department"]
    else:
        parent = None
    return PlaceResolution(qid=res["wikidata_qid"], whg_id=None,
                           label_at_year=cf, parent_at_year=parent,
                           confidence=0.0, source="layer-M-fallback")


def write_gazetteer(path: Path):
    path.write_text(json.dumps(GAZETTEER, ensure_ascii=False, indent=2), encoding="utf-8")
