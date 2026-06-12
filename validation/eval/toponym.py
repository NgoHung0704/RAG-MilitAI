"""
Toponym resolution — Layer M (modern), the part the demo actually uses.

Per the Toponym Resolution Spec, a place mention (FR data value, or FR/EN query
term) resolves to a canonical French region/department, and a *region* mention
expands through the modern hierarchy to its child departments
(e.g. Brittany / Bretagne -> {Finistère, Côtes-du-Nord, Morbihan}).

For the synthetic corpus the gazetteer is small and is derived deterministically
from the corpus itself — the (naissance_region, naissance_departement) pairs
present in COMPLETE *are* the region->department hierarchy, by construction. A
tiny EN->FR alias table supplies cross-lingual labels (the only thing not
derivable from the French-only data). This keeps the runner decoupled from the
generator's gazetteer.json while honouring the source-language-first rule.

The diachronic Layer H is scaffolded in the spec and not used here.
"""

from __future__ import annotations

from collections import defaultdict

from .text import norm

# EN (and a few variant) labels -> canonical French region/department label.
# Source-language-first: French queries hit the data labels directly; this table
# is only consulted for cross-lingual / variant query terms.
EN_TO_FR = {
    "brittany": "Bretagne",
    "alsatian": "Alsace",          # adjectival forms occasionally appear
    "breton": "Bretagne",
    "lorraine": "Lorraine",
    "normandy": "Normandie",
    "flanders": "Flandre",
    "burgundy": "Bourgogne",
    "gascony": "Guyenne",
    "corsica": "Corse",
    "paris": "Paris",
}


class ToponymResolver:
    """Resolve a place label to the set of department values to match in data."""

    def __init__(self, df):
        # region (normalised) -> set of canonical department strings
        self._region_depts: dict[str, set] = defaultdict(set)
        # normalised department -> canonical department string
        self._depts: dict[str, str] = {}
        self._region_label: dict[str, str] = {}  # normalised region -> canonical
        for col_region, col_dept in (
            ("naissance_region", "naissance_departement"),
            ("deces_region", "deces_departement"),
        ):
            if col_region not in df.columns or col_dept not in df.columns:
                continue
            for region, dept in zip(df[col_region], df[col_dept]):
                if dept:
                    self._depts[norm(dept)] = dept
                if region and dept:
                    self._region_depts[norm(region)].add(dept)
                if region:
                    self._region_label[norm(region)] = region

    def departments_for(self, label: str) -> set:
        """Return the set of department strings a query label denotes.

        A department label -> itself; a region label -> its child departments;
        an EN/variant label is mapped to its French form first.
        """
        n = norm(label)
        # cross-lingual fold (EN_TO_FR keys are already in normalised form)
        fr = EN_TO_FR.get(n)
        if fr is not None:
            n = norm(fr)
        if n in self._region_depts:
            return set(self._region_depts[n])
        if n in self._depts:
            return {self._depts[n]}
        # Unknown: return the label as-is (bare match) so the query still runs.
        return {label}

    def is_region(self, label: str) -> bool:
        n = norm(label)
        fr = EN_TO_FR.get(n)
        if fr is not None:
            n = norm(fr)
        return n in self._region_depts
