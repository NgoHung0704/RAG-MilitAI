"""
Gazetteer-backed coordinate resolution for the Explore / Atlas map
(Explore Atlas Spec §3 migration, §6 implementation).

The Atlas map plots birthplaces by latitude/longitude. Per the spec the
coordinates come from the **gazetteer's Layer-M coordinate field** (Toponym
Resolution Spec) — this module reads ``validation/corpus/gazetteer.json`` and
returns a ``(lat, lon)`` for a department or region label, so when the toponym
enrichment populates coordinates the map lights up with no code change here.

Contract for the enrichment thread: add coordinates to any ``regions`` /
``departments`` / ``communes`` entry in the gazetteer in *any* of these shapes —
all are accepted::

    "lat": 48.25, "lon": -4.0          # or "lng"
    "coords": [lon, lat]               # Toponym Spec §1 field name, GeoJSON order
    "coordinates": [lon, lat]          # GeoJSON order (lon first); alias of "coords"
    "coordinates": {"lat": .., "lon": ..}
    "coord": "lat,lon"

Until coordinates are present, a small built-in centroid table covering the
synthetic gazetteer's departments and regions keeps the synthetic demo's planted
clusters visible. Real-archive departments outside the gazetteer resolve to
nothing (the map reports the uncovered count honestly).
"""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

import app.config as config

_GAZETTEER = Path(config.PROJECT_ROOT) / "validation" / "corpus" / "gazetteer.json"


def _norm(s) -> str:
    """Accent-strip + lowercase + drop spaces/dashes/apostrophes (matches the
    catalogue ``norm()`` so labels join the same way the oracle compares them)."""
    if s is None:
        return ""
    out = []
    for ch in unicodedata.normalize("NFKD", str(s)):
        if unicodedata.combining(ch):
            continue
        if ch.isspace() or ch in "'’ʼ`´-‐‑‒–—―−":
            continue
        out.append(ch.lower())
    return "".join(out)


# Built-in centroid fallback (modern administrative geography, approximate),
# covering exactly the synthetic gazetteer's departments + regions so the
# planted recruitment clusters render before the gazetteer carries coordinates.
_FALLBACK_DEPTS: dict[str, tuple[float, float]] = {
    "finistere": (48.25, -4.0),
    "cotesdunord": (48.4, -2.8),
    "morbihan": (47.8, -2.8),
    "basrhin": (48.6, 7.5),
    "moselle": (49.0, 6.7),
    "meurthe": (48.7, 6.0),
    "seine": (48.85, 2.35),
    "rhone": (45.75, 4.6),
    "gironde": (44.85, -0.6),
    "nord": (50.5, 3.1),
    "isere": (45.2, 5.6),
    "puydedome": (45.77, 3.1),
    "eure": (49.1, 1.0),
    "corse": (42.15, 9.1),
}
_FALLBACK_REGIONS: dict[str, tuple[float, float]] = {
    "bretagne": (48.2, -3.0),
    "alsace": (48.5, 7.5),
    "lorraine": (48.9, 6.3),
    "iledefrance": (48.7, 2.5),
    "lyonnais": (45.75, 4.5),
    "guyenne": (44.8, -0.5),
    "flandre": (50.6, 3.0),
    "dauphine": (45.0, 5.7),
    "auvergne": (45.5, 3.1),
    "normandie": (49.1, 0.5),
    "corse": (42.15, 9.1),
}


# Modern metropolitan INSEE department code → name. The real archive stores
# `naissance_departement` as these numeric codes (sometimes unpadded: "2", "8"),
# which are unreadable as labels; this lets the Atlas show the name alongside the
# number. Synthetic data already carries names, so non-code values pass through.
_DEPT_CODE_NAME: dict[str, str] = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche",
    "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "20": "Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor",
    "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure",
    "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine",
    "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise",
    "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées",
    "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône",
    "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie",
    "74": "Haute-Savoie", "75": "Paris", "76": "Seine-Maritime",
    "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme",
    "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges",
    "89": "Yonne", "90": "Territoire de Belfort", "91": "Essonne",
    "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}


def department_name(value: str) -> str | None:
    """Name for a department *code* ("75" → "Paris", "2" → "Aisne"); ``None`` if
    *value* is not a recognised code (e.g. it is already a name)."""
    if value is None:
        return None
    v = str(value).strip().upper()
    if v in ("2A", "2B"):
        return _DEPT_CODE_NAME.get(v)
    if v.isdigit():
        key = v.zfill(2) if len(v) <= 2 else v
        return _DEPT_CODE_NAME.get(key)
    return None


def _extract_coords(entry: dict) -> tuple[float, float] | None:
    """Pull a ``(lat, lon)`` out of a gazetteer entry in any accepted shape."""
    if not isinstance(entry, dict):
        return None
    lat = entry.get("lat")
    lon = entry.get("lon", entry.get("lng"))
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    # "coords" is the Toponym Spec §1 field name; "coordinates"/"coord" are aliases.
    coords = entry.get("coords", entry.get("coordinates", entry.get("coord")))
    if isinstance(coords, (list, tuple)) and len(coords) == 2:
        return float(coords[1]), float(coords[0])  # GeoJSON [lon, lat]
    if isinstance(coords, dict) and "lat" in coords:
        return float(coords["lat"]), float(coords.get("lon", coords.get("lng")))
    if isinstance(coords, str) and "," in coords:
        a, b = coords.split(",", 1)
        return float(a), float(b)
    return None


@lru_cache(maxsize=1)
def _gazetteer_coords() -> dict[str, dict[str, tuple[float, float]]]:
    """``{"department": {norm: (lat,lon)}, "region": {...}}`` from the gazetteer,
    including only entries that actually carry coordinates."""
    depts: dict[str, tuple[float, float]] = {}
    regions: dict[str, tuple[float, float]] = {}
    try:
        gaz = json.loads(_GAZETTEER.read_text(encoding="utf-8"))
    except Exception:
        return {"department": depts, "region": regions}

    for label, entry in (gaz.get("departments") or {}).items():
        c = _extract_coords(entry)
        if c:
            depts[_norm(label)] = c
    for label, entry in (gaz.get("regions") or {}).items():
        c = _extract_coords(entry)
        if c:
            regions[_norm(label)] = c
    return {"department": depts, "region": regions}


def coords_loaded_from_gazetteer() -> bool:
    """True once the gazetteer carries any coordinates (the enrichment landed)."""
    g = _gazetteer_coords()
    return bool(g["department"] or g["region"])


def department_coords(label: str) -> tuple[float, float] | None:
    """``(lat, lon)`` for a department label — gazetteer first, fallback second."""
    n = _norm(label)
    if not n:
        return None
    return _gazetteer_coords()["department"].get(n) or _FALLBACK_DEPTS.get(n)


def region_coords(label: str) -> tuple[float, float] | None:
    """``(lat, lon)`` for a region label — gazetteer first, fallback second."""
    n = _norm(label)
    if not n:
        return None
    return _gazetteer_coords()["region"].get(n) or _FALLBACK_REGIONS.get(n)
